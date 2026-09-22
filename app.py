#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NOTAM Space-Launch Analyzer
===========================

Streamlit-Anwendung zur taeglichen Auswertung von NOTAM-Dateien mit dem Ziel,
Raumfahrtstarts von China, Russland, Indien, Iran, Nordkorea und den USA zu
erkennen, einem Weltraumbahnhof zuzuordnen und die Flugbahn (Azimut /
Inklination / Orbit-Typ) abzuschaetzen.

Start:      streamlit run app.py
Python:     3.9+ (getestet), Zielversion 3.10+
Lizenz:     MIT
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# Optionale Abhaengigkeiten (App bleibt ohne sie lauffaehig)
# --------------------------------------------------------------------------- #
try:
    import folium
    from streamlit_folium import st_folium

    FOLIUM_AVAILABLE = True
except Exception:  # pragma: no cover - reine Laufzeit-Absicherung
    FOLIUM_AVAILABLE = False

try:
    from geopy.distance import geodesic

    GEOPY_AVAILABLE = True
except Exception:  # pragma: no cover
    GEOPY_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Konstanten
# --------------------------------------------------------------------------- #
APP_DIR = Path(__file__).resolve().parent
SPACEPORT_CSV = APP_DIR / "weltraumbahnhoefe_koordinaten_updated.csv"
FIR_CSV = APP_DIR / "icao_fir_acc_coordinates_updated.csv"
VEHICLE_CSV = APP_DIR / "traegersysteme_updated.csv"

EARTH_RADIUS_KM = 6371.0088
NM_TO_KM = 1.852

TARGET_NATIONS = ["China", "Russland", "Indien", "Iran", "Nordkorea", "USA"]

#: Primaere Weltraum-Indikatoren im E-Item / Freitext.
SPACE_KEYWORDS: Tuple[str, ...] = (
    "ROCKET",
    "SPACE LAUNCH",
    "LAUNCH",
    "DEBRIS",
    "FALLING DEBRIS",
    "DANGER AREA",
    "TEMPORARY RESTRICTED AREA",
    "RESTRICTED AREA",
    # Schreibweisen russischer und maritimer Meldungen, die dieselbe Sache
    # bezeichnen, ohne das Wort "AREA" im ICAO-Sinn zu verwenden.
    "AIRSPACE CLSD",
    "AIRSPACE CLOSED",
    "HAZARDOUS OPERATIONS",
    "ALTITUDE RESERVATION",
)

#: Hoehenlimit-Indikatoren (F/G-Item oder Freitext) -> "unlimited"-Profil.
UNLIMITED_PATTERNS: Tuple[str, ...] = (
    "SFC/UNL",
    "SFC TO UNL",
    "SFC-UNL",
    "SFC - UNL",
    "GND/UNL",
    "GND TO UNL",
    "GND-UNL",
    "GND - UNL",
    "SFC/UNLIMITED",
    "GND/UNLIMITED",
    "SFC-UNLIMITED",
    "GND-UNLIMITED",
    "SURFACE TO UNLIMITED",
)

#: Werte der F/G-Items, die zusammen ein "SFC bis unbegrenzt"-Profil ergeben.
_LOWER_UNLIMITED = ("SFC", "GND", "SURFACE", "GROUND")
_UPPER_UNLIMITED = ("UNL", "UNLIMITED", "UNLTD")

#: Eindeutig raumfahrtspezifische Begriffe (starke Evidenz).
STRONG_SPACE_KEYWORDS: Tuple[str, ...] = (
    "ROCKET",
    "SPACE LAUNCH",
    "LAUNCH VEHICLE",
    "CARRIER ROCKET",
    "SPACE DEBRIS",
    "FALLING DEBRIS",
    "SATELLITE LAUNCH",
    "SPACECRAFT",
    "STAGE IMPACT",
    "BOOSTER",
    "REENTRY",
    "RE-ENTRY",
    "LAUNCH ACTIVITY",
    "LAUNCH OPERATION",
    "LAUNCH WINDOW",
    "SPACE ACTIVITY",
    "LAUNCH AREA",
    "JETTISON",
    # Formulierungen russischer, australischer und neuseelaendischer Meldungen
    "MISSILE LAUNCH",
    "LAUNCH MISSILE",
    "MISSILE MISSION",
    "RUSSIAN MISSILES",
    "SPACE LAUNCH AREA",
    "IMPACT AREA",
    "FALL AREA",
    "UNBURNED DEBRIS",
    "DEBRIS RETURN",
    "AEROSPACE FLT",
    "AEROSPACE FLIGHT",
    "SPACE FLT ACT",
)

#: Begriffe, die ein NOTAM trotz passender Trigger als Nicht-Raumfahrt ausweisen.
#: Ohne diese Liste erzeugt der reine SFC/UNL-Trigger massenhaft Fehlalarme
#: (Wetterballons, Suchscheinwerfer, Schiessuebungen).
EXCLUSION_KEYWORDS: Tuple[str, ...] = (
    "BALLOON",
    "SEARCHLIGHT",
    "GUN FRNG",
    "GUN FIRING",
    "AIR EXER",
    "PARACHUT",
    "SKYDIV",
    "GLIDER",
    "KITE",
    "FIREWORK",
    "PYROTECHNIC",
    "CRANE",
    "LASER",
    "UNMANNED ACFT",
    "UAS ",
    "UAV ",
    "DRONE",
    "MODEL ACFT",
    "AIRSHOW",
    "AIR SHOW",
    "ARTILLERY",
    "FIRING PRACTICE",
    "NAVAL SHIP",
    "FRNG",
    "FIRING",
    "ADS-B",
    "TIS-B",
    "FIS-B",
    "SURVEILLANCE REBROADCAST",
    "ALT RESERVATION",
    # Hobby- und Amateurraketen sind kein Raumfahrtstart, auch nicht in den USA.
    "AEROPAC",
    "EXPERIMENTAL ROCKETRY",
    "AMATEUR ROCKET",
    "HIGH POWER ROCKETRY",
    "MODEL ROCKET",
    "AIRSPACE USE PLAN",
    "AMC-MANAGEABLE",
    "TSA/TRA",
    "AUP",
    "AERIAL WORK",
    "WINDMILL",
    "OBST",
)

#: Q-Line Hoehenfenster FL000 - FL999.
QCODE_ALTITUDE = "000/999"


# --------------------------------------------------------------------------- #
# Geodaesie / Orbitmechanik
# --------------------------------------------------------------------------- #
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Grosskreis-Distanz zweier Punkte in Kilometern (Haversine-Formel)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def surface_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """WGS84-Distanz via geopy, mit Haversine als Fallback."""
    if GEOPY_AVAILABLE:
        try:
            return float(geodesic((lat1, lon1), (lat2, lon2)).kilometers)
        except Exception:
            pass
    return haversine_km(lat1, lon1, lat2, lon2)


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Anfangskurs (Launch-Azimut alpha) von Punkt 1 nach Punkt 2, normiert auf 0-360 Grad.

        alpha = atan2( sin(dLon) * cos(lat2),
                       cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dLon) )
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        d_lambda
    )
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def estimate_inclination_deg(site_lat: float, azimuth_deg: float) -> float:
    """
    Genaeherte orbitale Inklination aus Startplatz-Breite phi und Azimut alpha:

        cos(i) = cos(phi) * sin(alpha)

    Mathematische Artefakte (|cos i| > 1 durch Rundung) werden abgefangen.
    Hinweis: Die Naeherung vernachlaessigt den Geschwindigkeitsbeitrag der
    Erdrotation und liefert daher eine Abschaetzung, keinen exakten Wert.
    """
    cos_i = math.cos(math.radians(site_lat)) * math.sin(math.radians(azimuth_deg))
    cos_i = max(-1.0, min(1.0, cos_i))
    return math.degrees(math.acos(cos_i))


def classify_orbit(inclination_deg: Optional[float]) -> str:
    """Klassifiziert den Ziel-Orbit anhand der abgeschaetzten Inklination."""
    if inclination_deg is None or (
        isinstance(inclination_deg, float) and math.isnan(inclination_deg)
    ):
        return "Unbestimmt"
    i = float(inclination_deg)
    if i > 100.0:
        return "Retrograder Orbit"
    if 96.0 <= i <= 100.0:
        return "Sonnensynchron (SSO / Polar)"
    if 66.0 <= i < 96.0:
        return "Hohe Inklination / polnah"
    if 31.0 <= i <= 65.0:
        return "Standard LEO / MEO (ISS-/Station-Korridor)"
    if 0.0 <= i <= 30.0:
        return "Aequatorial / Low Inclination (GTO-Transit)"
    return "Unbestimmt"


def destination_point(
    lat: float, lon: float, bearing_deg: float, distance_km: float
) -> Tuple[float, float]:
    """Zielpunkt auf dem Grosskreis von (lat, lon) mit Kurs und Distanz."""
    phi1, lambda1 = math.radians(lat), math.radians(lon)
    theta = math.radians(bearing_deg)
    delta = distance_km / EARTH_RADIUS_KM
    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(
        delta
    ) * math.cos(theta)
    phi2 = math.asin(max(-1.0, min(1.0, sin_phi2)))
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), (math.degrees(lambda2) + 540.0) % 360.0 - 180.0


def great_circle_path(
    lat: float, lon: float, bearing_deg: float, distance_km: float, steps: int = 96
) -> List[Tuple[float, float]]:
    """Stuetzpunkte entlang eines Grosskreises (fuer die Kartendarstellung)."""
    pts = [
        destination_point(lat, lon, bearing_deg, distance_km * s / float(steps))
        for s in range(steps + 1)
    ]
    return unwrap_longitudes(pts)


def unwrap_longitudes(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """
    Entfernt 180-Grad-Spruenge, damit Linien in folium nicht quer ueber die
    Weltkarte zurueckgezeichnet werden.
    """
    if not points:
        return []
    out = [(float(points[0][0]), float(points[0][1]))]
    for lat, lon in points[1:]:
        prev_lon = out[-1][1]
        lon = float(lon)
        while lon - prev_lon > 180.0:
            lon -= 360.0
        while lon - prev_lon < -180.0:
            lon += 360.0
        out.append((float(lat), lon))
    return out


def polygon_centroid(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """
    Geometrischer Mittelpunkt (Centroid) einer Punktmenge.

    Ab drei Punkten wird die Flaechenformel (Shoelace) verwendet, sonst das
    arithmetische Mittel. Degenerierte Polygone (Flaeche ~ 0) fallen ebenfalls
    auf das Mittel zurueck.
    """
    pts = unwrap_longitudes(points)
    if len(pts) == 1:
        return pts[0]
    mean_lat = sum(p[0] for p in pts) / len(pts)
    mean_lon = sum(p[1] for p in pts) / len(pts)
    if len(pts) < 3:
        return mean_lat, ((mean_lon + 540.0) % 360.0) - 180.0

    area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        x_i, y_i = pts[i][1], pts[i][0]
        x_j, y_j = pts[j][1], pts[j][0]
        cross = x_i * y_j - x_j * y_i
        area += cross
        cx += (x_i + x_j) * cross
        cy += (y_i + y_j) * cross
    area *= 0.5
    if abs(area) < 1e-12:
        return mean_lat, ((mean_lon + 540.0) % 360.0) - 180.0
    lon_c = cx / (6.0 * area)
    lat_c = cy / (6.0 * area)
    return lat_c, ((lon_c + 540.0) % 360.0) - 180.0


# --------------------------------------------------------------------------- #
# Koordinaten-Engine
# --------------------------------------------------------------------------- #
#: Kompaktes ICAO-Format: 1936N11057E / 193600N1105700E / 1936.5N11057.2E
RE_DMS_COMPACT = re.compile(
    r"(?<!\d)(\d{2})(\d{2})(\d{2})?(?:\.(\d{1,3}))?\s*([NS])"
    r"[\s,/-]{0,3}"
    r"(\d{3})(\d{2})(\d{2})?(?:\.(\d{1,3}))?\s*([EW])(?!\d)",
    re.IGNORECASE,
)

#: Hemisphaere vorangestellt: N380300E1071800 / N3803E10718 / N38 03 00 E107 18 00
#: (gaengig in chinesischen und russischen NOTAMs)
RE_DMS_COMPACT_PREFIX = re.compile(
    r"([NS])\s*(\d{2})\s?(\d{2})\s?(\d{2})?(?:\.(\d{1,3}))?"
    r"[\s,/-]{0,3}"
    r"([EW])\s*(\d{3})\s?(\d{2})\s?(\d{2})?(?:\.(\d{1,3}))?(?!\d)",
    re.IGNORECASE,
)

#: Grad/Minuten mit Bindestrich und Dezimalminuten: 59-42.60S 165-49.20E
#: (Schreibweise maritimer NAVAREA-/NAVTEX-Warnungen)
RE_DM_DASH = re.compile(
    r"(?<![\d.])(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([NS])"
    r"[\s,/]{1,4}"
    r"(\d{1,3})-(\d{1,2}(?:\.\d+)?)\s*([EW])(?![\d.])",
    re.IGNORECASE,
)

#: Grad/Minuten/Sekunden durch Leerzeichen getrennt: 59 03 00 S 131 00 00 W
RE_DMS_SPACED = re.compile(
    r"(?<![\d.])(\d{1,3})\s+(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)\s*([NS])"
    r"[\s,/]{1,4}"
    r"(\d{1,3})\s+(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)\s*([EW])(?![\d.])",
    re.IGNORECASE,
)

#: Gradzeichen mit vorangestellter Hemisphaere: N 12°30' E 82°10'
RE_DMS_SYMBOL_PREFIX = re.compile(
    r"([NS])\s*(\d{1,3})\s*[°]\s*(\d{1,2})?\s*['\u2032]?\s*(\d{1,2}(?:\.\d+)?)?\s*[\"\u2033]?"
    r"[\s,/-]{0,4}"
    r"([EW])\s*(\d{1,3})\s*[°]\s*(\d{1,2})?\s*['\u2032]?\s*(\d{1,2}(?:\.\d+)?)?\s*[\"\u2033]?",
    re.IGNORECASE,
)

#: Gradzeichen-Format: 19°36'N 110°57'E  /  19°36'12"N 110°57'30"E
RE_DMS_SYMBOL = re.compile(
    r"(\d{1,3})\s*[°º]\s*(\d{1,2})?\s*['′]?\s*(\d{1,2}(?:\.\d+)?)?\s*[\"″]?\s*([NS])"
    r"[\s,/-]{0,4}"
    r"(\d{1,3})\s*[°º]\s*(\d{1,2})?\s*['′]?\s*(\d{1,2}(?:\.\d+)?)?\s*[\"″]?\s*([EW])",
    re.IGNORECASE,
)

#: Dezimalgrad mit Hemisphaere: 19.60N 110.95E
RE_DECIMAL_HEMI = re.compile(
    r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*°?\s*([NS])[\s,/-]{1,4}(\d{1,3}(?:\.\d+)?)\s*°?\s*([EW])(?![\d.])",
    re.IGNORECASE,
)

#: Radiusangaben in beiden Schreibrichtungen.
RE_RADIUS_BEFORE = re.compile(
    r"(\d{1,4}(?:\.\d+)?)\s*(NM|KM)\b[^A-Z0-9]{0,6}(?:RADIUS|RADIO|RAD)\b", re.IGNORECASE
)
RE_RADIUS_AFTER = re.compile(
    r"\bRADIUS\b\s*(?:OF|VON)?\s*(\d{1,4}(?:\.\d+)?)\s*(NM|KM)\b", re.IGNORECASE
)

#: NOTAM-Kennung, z.B. A1234/24 oder C0421/25
#: Der Buchstabe vor der Nummer fehlt in manchen Meldungen ganz ("4456/26").
RE_NOTAM_ID = re.compile(r"(?<![/\d])\b([A-Z]?\d{3,4}/\d{2})\b")

#: Kennung maritimer Warnungen: "NAVAREA XIV WARNING 189/26".
RE_NAVAREA_ID = re.compile(r"\bNAVAREA\s+([IVXLC]+)\s+WARNING\s+(\d{1,4}/\d{2})\b", re.IGNORECASE)

#: ICAO-Vierbuchstabencode
RE_ICAO = re.compile(r"\b([A-Z]{4})\b")


def _dms_to_decimal(
    deg: str, minutes: Optional[str], seconds: Optional[str], frac: Optional[str] = None
) -> Optional[float]:
    """Wandelt Grad/Minuten/Sekunden in Dezimalgrad. None bei ungueltigen Werten."""
    try:
        d = float(deg)
        m = float(minutes) if minutes else 0.0
        s = float(seconds) if seconds else 0.0
    except (TypeError, ValueError):
        return None
    if m >= 60.0 or s >= 60.0:
        return None
    value = d + m / 60.0 + s / 3600.0
    if frac:
        # Nachkommastellen gehoeren zur jeweils kleinsten angegebenen Einheit.
        frac_val = float("0." + frac)
        value += (frac_val / 3600.0) if seconds else (frac_val / 60.0)
    return value


def _apply_hemisphere(value: float, hemi: str) -> float:
    return -value if hemi.upper() in ("S", "W") else value


def _valid_latlon(lat: Optional[float], lon: Optional[float]) -> bool:
    return (
        lat is not None
        and lon is not None
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
        and not (abs(lat) < 1e-9 and abs(lon) < 1e-9)
    )


def _pair_compact_suffix(m: "re.Match") -> Optional[Tuple[float, float]]:
    """1936N11057E - Ziffern zuerst, Hemisphaere dahinter."""
    lat = _dms_to_decimal(m.group(1), m.group(2), m.group(3), m.group(4))
    lon = _dms_to_decimal(m.group(6), m.group(7), m.group(8), m.group(9))
    if lat is None or lon is None:
        return None
    return _apply_hemisphere(lat, m.group(5)), _apply_hemisphere(lon, m.group(10))


def _pair_compact_prefix(m: "re.Match") -> Optional[Tuple[float, float]]:
    """N380300E1071800 - Hemisphaere zuerst, Ziffern dahinter."""
    lat = _dms_to_decimal(m.group(2), m.group(3), m.group(4), m.group(5))
    lon = _dms_to_decimal(m.group(7), m.group(8), m.group(9), m.group(10))
    if lat is None or lon is None:
        return None
    return _apply_hemisphere(lat, m.group(1)), _apply_hemisphere(lon, m.group(6))


def _pair_dm_dash(m: "re.Match") -> Optional[Tuple[float, float]]:
    """59-42.60S 165-49.20E - Grad und Dezimalminuten mit Bindestrich."""
    try:
        lat = float(m.group(1)) + float(m.group(2)) / 60.0
        lon = float(m.group(4)) + float(m.group(5)) / 60.0
    except ValueError:
        return None
    if float(m.group(2)) >= 60.0 or float(m.group(5)) >= 60.0:
        return None
    return _apply_hemisphere(lat, m.group(3)), _apply_hemisphere(lon, m.group(6))


def _pair_dms_spaced(m: "re.Match") -> Optional[Tuple[float, float]]:
    """59 03 00 S 131 00 00 W - Grad/Minuten/Sekunden durch Leerzeichen getrennt."""
    lat = _dms_to_decimal(m.group(1), m.group(2), m.group(3))
    lon = _dms_to_decimal(m.group(5), m.group(6), m.group(7))
    if lat is None or lon is None:
        return None
    return _apply_hemisphere(lat, m.group(4)), _apply_hemisphere(lon, m.group(8))


def _pair_symbol_suffix(m: "re.Match") -> Optional[Tuple[float, float]]:
    """19°36'N 110°57'E"""
    lat = _dms_to_decimal(m.group(1), m.group(2), m.group(3))
    lon = _dms_to_decimal(m.group(5), m.group(6), m.group(7))
    if lat is None or lon is None:
        return None
    return _apply_hemisphere(lat, m.group(4)), _apply_hemisphere(lon, m.group(8))


def _pair_symbol_prefix(m: "re.Match") -> Optional[Tuple[float, float]]:
    """N 12°30' E 82°10'"""
    lat = _dms_to_decimal(m.group(2), m.group(3), m.group(4))
    lon = _dms_to_decimal(m.group(6), m.group(7), m.group(8))
    if lat is None or lon is None:
        return None
    return _apply_hemisphere(lat, m.group(1)), _apply_hemisphere(lon, m.group(5))


def _pair_decimal(m: "re.Match") -> Optional[Tuple[float, float]]:
    """19.60N 110.95E"""
    try:
        lat = float(m.group(1))
        lon = float(m.group(3))
    except ValueError:
        return None
    return _apply_hemisphere(lat, m.group(2)), _apply_hemisphere(lon, m.group(4))


#: Reihenfolge der Koordinatenformate - spezifischere zuerst. Bereits erkannte
#: Textbereiche werden maskiert, damit ein Treffer nicht doppelt gelesen wird.
COORDINATE_FORMATS = (
    (RE_DMS_COMPACT, _pair_compact_suffix),
    (RE_DMS_COMPACT_PREFIX, _pair_compact_prefix),
    (RE_DMS_SPACED, _pair_dms_spaced),
    (RE_DM_DASH, _pair_dm_dash),
    (RE_DMS_SYMBOL, _pair_symbol_suffix),
    (RE_DMS_SYMBOL_PREFIX, _pair_symbol_prefix),
    (RE_DECIMAL_HEMI, _pair_decimal),
)


def extract_coordinates(text: str) -> List[Tuple[float, float]]:
    """
    Extrahiert alle Koordinatenpaare aus einem NOTAM-Text.

    Unterstuetzt beide Schreibrichtungen des kompakten ICAO-Formats
    (``1936N11057E`` und ``N380300E1071800``), Gradzeichen-Notation mit voran-
    oder nachgestellter Hemisphaere sowie Dezimalgrad. Die Reihenfolge der
    Punkte im Text bleibt erhalten, weil sie die Polygon-Geometrie bestimmt.
    """
    if not text:
        return []

    found: List[Tuple[int, float, float]] = []
    work = text

    for pattern, parser in COORDINATE_FORMATS:
        matches = list(pattern.finditer(work))
        for match in matches:
            pair = parser(match)
            if pair is not None and _valid_latlon(pair[0], pair[1]):
                found.append((match.start(), pair[0], pair[1]))
        for match in reversed(matches):
            start, stop = match.span()
            work = work[:start] + (" " * (stop - start)) + work[stop:]

    found.sort(key=lambda item: item[0])

    # Duplikate / nahezu identische Punkte entfernen (Toleranz ~100 m).
    unique: List[Tuple[float, float]] = []
    for _, lat, lon in found:
        if not any(abs(lat - u[0]) < 1e-3 and abs(lon - u[1]) < 1e-3 for u in unique):
            unique.append((lat, lon))
    return unique


#: Trennmarken zwischen mehreren Gebieten innerhalb eines NOTAMs:
#: nummerierte Listen ("1. ", "2. "), "SIMILAR ACTIVITIES ..." und ein "AND"
#: unmittelbar vor der naechsten Koordinate.
RE_AREA_SPLIT = re.compile(
    r"(?:"
    r"(?:(?<=[.:)])|^|\n)\s*(?:\d{1,2}\s*[.)]\s|AREA\s+\d\b|SIMILAR ACTIVITIES\b)"
    r"|\s+AND\s+(?=\d{6}\s*[NS])"
    r")",
    re.IGNORECASE,
)


#: Bezugspunkt der Q-Line mit angehaengtem Radius: 3950N11625E099 (99 NM).
#: Wird nur als letzter Ausweg genutzt, wenn das NOTAM sonst keine Koordinate
#: enthaelt - im Normalfall beschreibt erst das E-Item die eigentliche Zone.
RE_QLINE_POINT = re.compile(
    r"(?<!\d)(\d{2})(\d{2})([NS])(\d{3})(\d{2})([EW])(\d{3})(?!\d)", re.IGNORECASE
)


def extract_qline_point(text: str) -> Optional[Tuple[float, float, float]]:
    """
    Liest Bezugspunkt und Radius aus der Q-Line.

    Rueckgabe: (Breite, Laenge, Radius in km) oder None.
    """
    match = RE_QLINE_POINT.search(text or "")
    if not match:
        return None
    lat = _dms_to_decimal(match.group(1), match.group(2), None)
    lon = _dms_to_decimal(match.group(4), match.group(5), None)
    if lat is None or lon is None:
        return None
    lat = _apply_hemisphere(lat, match.group(3))
    lon = _apply_hemisphere(lon, match.group(6))
    if not _valid_latlon(lat, lon):
        return None
    return lat, lon, float(match.group(7)) * NM_TO_KM


def extract_zones(text: str) -> List[List[Tuple[float, float]]]:
    """
    Zerlegt den Geometrieteil eines NOTAMs in einzelne Sperrgebiete.

    Ein NOTAM kann mehrere getrennte Gebiete beschreiben - russische Meldungen
    listen sie nummeriert ("1. ... 2. ...") oder nach "SIMILAR ACTIVITIES ALSO
    PLANNED". Ohne diese Trennung entsteht aus zwei Vierecken ein Zickzack-
    Polygon quer ueber die Karte.

    Teilstuecke mit weniger als drei Punkten sind keine eigenen Gebiete, sondern
    Aufzaehlungspunkte - sie werden dem vorherigen Gebiet zugeschlagen.
    """
    if not text:
        return []
    zones: List[List[Tuple[float, float]]] = []
    for part in RE_AREA_SPLIT.split(text):
        coords = extract_coordinates(part)
        if not coords:
            continue
        if len(coords) >= 3 or not zones:
            zones.append(coords)
        else:
            for c in coords:
                if c not in zones[-1]:
                    zones[-1].append(c)
    return zones


def extract_radius_km(text: str) -> Optional[float]:
    """Liest einen Aktionsradius (NM oder KM) aus dem NOTAM-Text."""
    for pattern in (RE_RADIUS_AFTER, RE_RADIUS_BEFORE):
        match = pattern.search(text or "")
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            unit = match.group(2).upper()
            km = value * NM_TO_KM if unit == "NM" else value
            if 0.0 < km <= 5000.0:
                return km
    return None


# --------------------------------------------------------------------------- #
# NOTAM-Felder, Zeitfenster und Trigger
# --------------------------------------------------------------------------- #
#: Markierung fuer NOTAMs, die eine Person geprueft und als Start bestaetigt hat.
MANUAL_MARK = "\u2b22"  # schwarzes Hexagon
#: Streamlits Markdown-Violett (``:violet[...]``) je Theme - hell nutzt purple70,
#: dunkel das hellere purple50. Tabelle, Kopfzeile und HTML-Markierung greifen auf
#: denselben Wert zu, damit die Markierung ueberall gleich aussieht.
MANUAL_COLOR = "#B27EFF"
MANUAL_COLOR_LIGHT = "#803DF5"


def manual_color() -> str:
    """Violett-Ton passend zum aktiven Theme."""
    try:
        if st.context.theme.type == "light":
            return MANUAL_COLOR_LIGHT
    except Exception:  # pragma: no cover - ausserhalb des Streamlit-Laufs
        pass
    return MANUAL_COLOR


def event_key(text: str) -> str:
    """
    Stabile Kennung eines NOTAMs, unabhaengig von seiner Zeilenposition.

    Manuelle Entscheidungen (als Start bestaetigt, ausgeblendet) muessen einen
    neuen Upload und das Hinzufuegen weiterer NOTAMs ueberstehen. Grundlage ist
    deshalb der normalisierte Meldungstext, nicht der Tabellenindex.
    """
    normalized = re.sub(r"\s+", " ", text or "").strip().upper()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]


def mark_id(notam_id: str, manual: bool) -> str:
    """Stellt der Kennung bei manueller Bestaetigung das Hexagon voran."""
    return "{} {}".format(MANUAL_MARK, notam_id) if manual else notam_id


def mark_id_markdown(notam_id: str, manual: bool) -> str:
    """
    Wie ``mark_id``, aber als Streamlit-Markdown mit violetter Einfaerbung.

    Fuer Stellen, die Markdown rendern, aber kein HTML zulassen - etwa die
    Beschriftung eines Aufklappbereichs.
    """
    if not manual:
        return notam_id
    return ":violet[{} {}]".format(MANUAL_MARK, notam_id)


def mark_id_html(notam_id: str, manual: bool) -> str:
    """
    Wie ``mark_id``, aber als HTML mit hochgestelltem, lilanem Hexagon links
    vor dem ersten Zeichen - fuer alle Stellen, die Markdown rendern.
    """
    if not manual:
        return notam_id
    return (
        '<span style="color:{};font-size:0.62em;vertical-align:super;'
        'line-height:0;margin-right:1px;">{}</span>{}'.format(
            manual_color(), MANUAL_MARK, notam_id
        )
    )


#: Spalte, die importierte von manuell eingefuegten NOTAMs unterscheidet.
SOURCE_COLUMN = "__quelle__"
SOURCE_IMPORT = "Import"
SOURCE_MANUAL = "Manuell"

#: Zeichen, die in kopierten NOTAMs statt der ASCII-Varianten auftauchen.
_UNICODE_FIXES = {
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ", "\u200b": "",
    "\ufeff": "", "\u2018": "'", "\u2019": "'", "\u201a": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00ba": "\u00b0", "\u02da": "\u00b0", "\u2218": "\u00b0", "\u030a": "\u00b0",
    "\u2032": "'", "\u02b9": "'", "\u2033": '"', "\u02ba": '"',
    "\u2044": "/", "\u2215": "/",
}

#: Zeilenanfang eines neuen NOTAMs: ICAO-Kennung oder FAA-Domestic-Marker.
RE_PASTE_BOUNDARY = re.compile(
    r"(?m)^(?=[ \t]*(?:\(?[A-Z]?\d{3,4}/\d{2}\b|![A-Z]{3}\b|NAVAREA\s+[IVXLC]+\b))",
    re.IGNORECASE,
)

#: Zeilen, die beim Kopieren aus Mails/Portalen als Etikett vorangestellt werden.
RE_PASTE_LABEL = re.compile(
    r"(?im)^\s*(?:notam(?:\s*(?:text|nr\.?|number|id))?|message|meldung|quelle|source)\s*[:\-]\s*"
)


def normalize_notam_text(text: str) -> str:
    """
    Vereinheitlicht NOTAM-Text aus beliebiger Quelle.

    Loest HTML-Entities auf (Behoerden-Portale liefern &apos; statt ') und
    ersetzt typografische Sonderzeichen durch die ASCII-Formen, die die
    Parser-Regexe erwarten. Wird sowohl beim Datei-Import als auch bei der
    Freitext-Eingabe angewendet.
    """
    if not text:
        return ""
    out = html.unescape(str(text))
    for bad, good in _UNICODE_FIXES.items():
        out = out.replace(bad, good)
    return out


def normalize_pasted_text(text: str) -> str:
    """
    Bereinigt aus Mails, PDFs oder Webseiten kopierten NOTAM-Text.

    Ersetzt typografische Sonderzeichen (geschuetzte Leerzeichen, Gradzeichen-
    Varianten, typografische Anfuehrungszeichen, Gedankenstriche) durch die
    ASCII-Formen, die die Parser-Regexe erwarten, und entfernt Etikettzeilen.
    """
    if not text:
        return ""
    out = normalize_notam_text(text)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = RE_PASTE_LABEL.sub("", out)
    # Weiche Zeilenumbrueche innerhalb eines Items zusammenfassen, echte behalten.
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def split_pasted_notams(text: str) -> List[str]:
    """
    Zerlegt einen eingefuegten Block in einzelne NOTAMs.

    Primaer wird an NOTAM-Kennungen am Zeilenanfang getrennt (A1234/25, !FDC ...).
    Enthaelt der Text keine Kennung, dienen Leerzeilen als Trenner. Ein einzelnes
    NOTAM mit internen Leerzeilen bleibt damit zusammen, sobald es eine Kennung
    traegt - genau der haeufige Fall beim Kopieren aus einem Briefing.
    """
    cleaned = normalize_pasted_text(text)
    if not cleaned:
        return []

    chunks = [c.strip() for c in RE_PASTE_BOUNDARY.split(cleaned) if c.strip()]
    if len(chunks) > 1:
        return chunks
    if len(chunks) == 1 and RE_NOTAM_ID.search(chunks[0].upper()):
        return chunks

    blocks = [b.strip() for b in re.split(r"\n\s*\n", cleaned) if b.strip()]
    return blocks or [cleaned]


def extract_items(text: str) -> Dict[str, str]:
    """
    Zerlegt einen NOTAM-Text in seine ICAO-Items (Q, A, B, C, D, E, F, G).

    Robust gegenueber Zeilenumbruechen und fehlenden Items; bei reinem Freitext
    bleibt das Ergebnis leer.
    """
    items: Dict[str, str] = {}
    if not text:
        return items
    normalized = re.sub(r"\s+", " ", text)
    # Ein Item endet am naechsten Item ODER am Spalten-Trenner " | ", den
    # row_to_text einfuegt - sonst verschluckt das letzte Item (meist G) die
    # angehaengten CSV-Spaltenwerte.
    pattern = re.compile(
        r"\b([QABCDEFG])\)\s*(.*?)(?=\s+\b[QABCDEFG]\)|\s\|\s|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(normalized):
        key = match.group(1).upper()
        value = match.group(2).strip()
        if key not in items and value:
            items[key] = value
    return items


def parse_notam_datetime(value: Any) -> Optional[datetime]:
    """
    Parst NOTAM-Zeitangaben.

    Unterstuetzt YYMMDDHHMM (ICAO B/C-Item), YYYYMMDDHHMM sowie gaengige
    ISO-/Textformate aus CSV-Spalten. Rueckgabe ist tz-aware (UTC).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().upper()
    if not text or text in ("PERM", "PERMANENT", "UFN", "NAN", "NONE", "-"):
        return None
    # "2611161500EST" - der Zusatz markiert eine geschaetzte Zeit, nicht den Wert.
    text = re.sub(r"\s*(?:EST|APRX|APPROX|ESTIMATED)$", "", text).strip()

    # Explizite Formate zuerst - sonst wuerde "03/12/2010 1306" faelschlich
    # als reine Ziffernfolge interpretiert.
    for fmt in ("%m/%d/%Y %H%M", "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    digits = text if text.isdigit() else ""
    try:
        if len(digits) == 10:
            return datetime(
                2000 + int(digits[0:2]),
                int(digits[2:4]),
                int(digits[4:6]),
                int(digits[6:8]),
                int(digits[8:10]),
                tzinfo=timezone.utc,
            )
        if len(digits) == 12:
            return datetime(
                int(digits[0:4]),
                int(digits[4:6]),
                int(digits[6:8]),
                int(digits[8:10]),
                int(digits[10:12]),
                tzinfo=timezone.utc,
            )
    except ValueError:
        return None

    try:
        parsed = pd.to_datetime(text, utc=True, errors="coerce")
    except Exception:
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


#: Zeitraum maritimer Warnungen: "FROM 142100 UTC TO 232100 UTC JUL 2026".
RE_NAVAREA_PERIOD = re.compile(
    r"\bFROM\s+(\d{6})\s*(?:UTC|Z)?\s+TO\s+(\d{6})\s*(?:UTC|Z)?\s+"
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s*(\d{4})",
    re.IGNORECASE,
)

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def extract_navarea_period(
    text: str,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Liest den Gueltigkeitszeitraum einer maritimen NAVAREA-/NAVTEX-Warnung.

    Diese Meldungen tragen keine ICAO-Items; der Zeitraum steht als
    "FROM DDHHMM UTC TO DDHHMM UTC MON YYYY" im Fliesstext.
    """
    match = RE_NAVAREA_PERIOD.search(text or "")
    if not match:
        return None, None
    month = _MONTHS[match.group(3).upper()]
    year = int(match.group(4))
    try:
        start = datetime(
            year, month, int(match.group(1)[:2]),
            int(match.group(1)[2:4]), int(match.group(1)[4:6]), tzinfo=timezone.utc,
        )
        end = datetime(
            year, month, int(match.group(2)[:2]),
            int(match.group(2)[2:4]), int(match.group(2)[4:6]), tzinfo=timezone.utc,
        )
    except ValueError:
        return None, None
    if end < start:  # Monatswechsel
        end = end.replace(month=month % 12 + 1, year=year + (1 if month == 12 else 0))
    return start, end


def detect_triggers(text: str, items: Dict[str, str]) -> List[str]:
    """
    Prueft die High-Priority-Weltraum-Indikatoren.

    Rueckgabe ist die Liste der ausgeloesten Gruende; eine leere Liste bedeutet
    "kein Weltraum-Event".
    """
    upper = (text or "").upper()
    reasons: List[str] = []

    for keyword in SPACE_KEYWORDS:
        if re.search(r"\b" + re.escape(keyword), upper):
            reasons.append("Keyword: {}".format(keyword))

    compact = re.sub(r"\s+", " ", upper)
    for pattern in UNLIMITED_PATTERNS:
        if pattern in compact:
            reasons.append("Hoehenlimit: {}".format(pattern))

    # Zuverlaessiger als jede Schreibweise im Freitext: die F/G-Items selbst.
    lower_item = (items.get("F") or "").strip().upper()
    upper_item = (items.get("G") or "").strip().upper()
    if any(lower_item.startswith(v) for v in _LOWER_UNLIMITED) and any(
        upper_item.startswith(v) for v in _UPPER_UNLIMITED
    ):
        reasons.append("Hoehenlimit: F) {} G) {}".format(lower_item, upper_item))

    q_line = items.get("Q", "")
    if QCODE_ALTITUDE in q_line or QCODE_ALTITUDE in compact:
        reasons.append("Q-Code Hoehenfenster: {}".format(QCODE_ALTITUDE))

    # Duplikate entfernen, Reihenfolge erhalten.
    seen = set()
    unique = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return unique


#: Nationale Zuordnung direkt aus dem NOTAM-Text (Laender, Betreiber, Startplaetze).
NATION_HINTS: Dict[str, Tuple[str, ...]] = {
    "China": (
        "CHINA", "CHINESE", "JIUQUAN", "TAIYUAN", "XICHANG", "WENCHANG", "HAIYANG",
        "LONG MARCH", "CHANG ZHENG", "CASC", "CZ-",
    ),
    "Russland": (
        "RUSSIA", "RUSSIAN", "VOSTOCHNY", "PLESETSK", "BAIKONUR", "KAPUSTIN",
        "SOYUZ", "ANGARA", "PROTON-M", "ROSCOSMOS", "GLONASS",
    ),
    "Indien": (
        "ISRO", "SRIHARIKOTA", "SDSC", "SHAR", "PSLV", "GSLV", "SSLV", "THUMBA",
        "KULASEKARAPATTINAM", "INDIAN SPACE", "INDIA ",
    ),
    "Iran": (
        "IRAN", "IRANIAN", "SEMNAN", "SHAHROUD", "CHABAHAR", "SIMORGH", "SAFIR",
        "QASED", "ZULJANAH",
    ),
    "Nordkorea": (
        "NORTH KOREA", "DPRK", "SOHAE", "TONGHAE", "CHOLIMA", "UNHA",
        "KWANGMYONGSONG",
    ),
    "USA": (
        "SPACE X", "SPACEX", "STARSHIP", "STARBASE", "BOCA CHICA", "STARLINK",
        "FALCON 9", "FALCON HEAVY", "DRAGON", "CREW DRAGON",
        "BLUE ORIGIN", "NEW SHEPARD", "NEW GLENN", "CORN RANCH",
        "UNITED LAUNCH ALLIANCE", "ATLAS V", "VULCAN", "DELTA IV",
        "ANTARES", "MINOTAUR", "CYGNUS", "PEGASUS XL",
        "NASA", "KENNEDY SPACE CENTER", "CAPE CANAVERAL", "VANDENBERG",
        "WALLOPS", "KODIAK", "POKER FLAT", "KWAJALEIN", "REAGAN TEST SITE",
        "SPACEPORT AMERICA", "VIRGIN GALACTIC", "SPACESHIPTWO", "MOJAVE AIR",
        "FIREFLY", "STOKE SPACE", "RELATIVITY SPACE", "SIERRA SPACE",
        "ARTEMIS", "SPACE LAUNCH SYSTEM",
    ),
}

#: Betreiber/Programme ausserhalb der Zielnationen - schliessen ein Event aus.
FOREIGN_OPERATORS: Tuple[str, ...] = (
    # Europaeische, japanische, suedkoreanische und weitere Programme
    "ARIANE", "VEGA", "JAXA", "H-IIA", "H3 ROCKET", "EPSILON ROCKET",
    "NURI", "KSLV", "KOUROU", "ESRANGE", "GUIANA SPACE",
    # Startplaetze ausserhalb der Zielnationen
    "ANDOYA", "ANDOEYA", "ANDØYA", "NAMMO", "SAXAVORD", "SUTHERLAND",
    "SPACEPORT CORNWALL", "SPACEPORT NORWAY", "KIRUNA", "NARO", "PALMACHIM",
    "ALCANTARA", "MAHIA", "ONENUI", "SHAVIT",
)

#: Geographische Wendungen, die sonst faelschlich als Nationsnennung zaehlen.
_GEO_NOISE = ("INDIAN OCEAN", "SOUTH CHINA SEA", "EAST CHINA SEA", "CHINA SEA")


#: Traegersystem oder Programm -> Startplatz. Der Startplatz eines Fluges steht
#: praktisch nie im NOTAM, das Traegersystem dagegen oft. Ohne diese Zuordnung
#: gewinnt der geographisch naechste Startplatz der Nation - bei einem
#: Starship-Wiedereintritt im Indischen Ozean waere das der falsche.
SPACEPORT_HINTS: Dict[str, Tuple[str, ...]] = {
    # --- USA -----------------------------------------------------------------
    "STARSHIP": ("KBRO",),
    "STARBASE": ("KBRO",),
    "BOCA CHICA": ("KBRO",),
    "SUPER HEAVY": ("KBRO",),
    "FALCON 9": ("KXMR", "KTTS", "KVBG", "KCOI"),
    "FALCON HEAVY": ("KTTS", "KXMR"),
    "STARLINK": ("KXMR", "KTTS", "KVBG", "KCOI"),
    "CREW DRAGON": ("KTTS",),
    "NEW SHEPARD": ("K33",),
    "CORN RANCH": ("K33",),
    "NEW GLENN": ("KXMR", "KCOI"),
    "ATLAS V": ("KXMR", "KVBG", "KCOI"),
    "VULCAN": ("KXMR", "KCOI"),
    "DELTA IV": ("KXMR", "KVBG"),
    "ANTARES": ("KLFI",),
    "MINOTAUR": ("KLFI", "KVBG"),
    "CYGNUS": ("KLFI",),
    "WALLOPS": ("KLFI",),
    "ARTEMIS": ("KTTS",),
    "SPACE LAUNCH SYSTEM": ("KTTS",),
    "KENNEDY SPACE CENTER": ("KTTS",),
    "CAPE CANAVERAL": ("KXMR", "KCOI"),
    "VANDENBERG": ("KVBG",),
    "SPACEPORT AMERICA": ("9S2",),
    "VIRGIN GALACTIC": ("9S2",),
    "SPACESHIPTWO": ("9S2",),
    "MOJAVE AIR": ("KMHV",),
    "KODIAK": ("PACD",),
    "PACIFIC SPACEPORT": ("PACD",),
    "POKER FLAT": ("PABR",),
    "KWAJALEIN": ("PKWA",),
    "REAGAN TEST SITE": ("PKWA",),
    # --- China ---------------------------------------------------------------
    "JIUQUAN": ("JSLC",),
    "TAIYUAN": ("TSLC",),
    "XICHANG": ("XSLC",),
    "WENCHANG": ("WSLC",),
    "HAIYANG": ("HIIS", "HYOS"),
    # --- Russland ------------------------------------------------------------
    "PLESETSK": ("GIK-1",),
    "VOSTOCHNY": ("VOSC", "SVOB"),
    "BAIKONUR": ("BAIK",),
    "KAPUSTIN": ("KAP-Y",),
    # --- Indien --------------------------------------------------------------
    "SRIHARIKOTA": ("SDSC",),
    "SDSC": ("SDSC",),
    "THUMBA": ("TERLS",),
    "KULASEKARAPATTINAM": ("KSSL",),
    # --- Iran ----------------------------------------------------------------
    "SEMNAN": ("SSSC",),
    "SHAHROUD": ("SCSL",),
    "CHABAHAR": ("CSSC",),
    # --- Nordkorea -----------------------------------------------------------
    "SOHAE": ("KSS",),
    "TONGHAE": ("THSL",),
}


#: Begriffe, die einen Wiedereintritt statt eines Starts beschreiben.
REENTRY_TERMS: Tuple[str, ...] = (
    "RE-ENTRY", "REENTRY", "RE ENTRY", "SPLASHDOWN", "DEBRIS RETURN",
    "DEORBIT", "DE-ORBIT", "RETURN OF", "RECOVERY AREA", "SPACE VEHICLE RE",
)

#: Begriffe, die eindeutig einen Start beschreiben.
LAUNCH_TERMS: Tuple[str, ...] = (
    "LAUNCH WILL TAKE PLACE", "SPACE LAUNCH", "LAUNCH ACTIVITY", "LAUNCH VEHICLE",
    "LAUNCH AREA", "WILL BE LAUNCHED", "LIFT-OFF", "LIFTOFF",
)

KIND_LAUNCH = "Start"
KIND_REENTRY = "Wiedereintritt"


def classify_event_kind(text: str) -> str:
    """
    Unterscheidet Start von Wiedereintritt.

    Fuer einen Wiedereintritt sagt die Richtung vom Startplatz zur Zone nichts
    ueber die Bahnlage aus - das Objekt kommt aus dem Orbit zurueck, nicht vom
    Startplatz. Die Unterscheidung muss daher im Ergebnis sichtbar sein.
    """
    upper = re.sub(r"\s+", " ", (text or "").upper())
    reentry = any(t in upper for t in REENTRY_TERMS)
    launch = any(t in upper for t in LAUNCH_TERMS)
    if reentry and not launch:
        return KIND_REENTRY
    if reentry and launch:
        # Beides genannt: das Wiedereintrittsgebiet ist die konkrete Sperrzone.
        return KIND_REENTRY
    return KIND_LAUNCH


def detect_spaceport_hint(text: str) -> Tuple[List[str], List[str]]:
    """
    Liest aus dem Meldungstext, welche Startplaetze in Frage kommen.

    Rueckgabe: (Liste der Startplatz-Kuerzel, Liste der Fundstellen). Je
    spezifischer der Treffer, desto enger die Auswahl - wird ein Startplatz
    direkt genannt, bleibt nur dieser uebrig.
    """
    upper = re.sub(r"\s+", " ", (text or "").upper())
    codes: List[str] = []
    belege: List[str] = []
    for begriff, ports in SPACEPORT_HINTS.items():
        if begriff in upper:
            belege.append(begriff)
            for code in ports:
                if code not in codes:
                    codes.append(code)
    # Nennt der Text genau einen Startplatz-Begriff, ist die Auswahl eindeutig;
    # bei mehreren Treffern bleibt die Schnittmenge sinnvollerweise offen.
    return codes, belege


def detect_nation_hint(text: str) -> Tuple[Optional[str], List[str]]:
    """
    Liest die Startnation direkt aus dem NOTAM-Text.

    Die FIR allein traegt keine verlaessliche nationale Zuordnung: ein
    japanisches NOTAM kann einen nordkoreanischen Start beschreiben, ein
    NOTAM ueber dem Indischen Ozean einen amerikanischen Wiedereintritt.
    Rueckgabe: (Nation oder None, Liste der Fundstellen).
    """
    upper = re.sub(r"\s+", " ", (text or "").upper())
    for noise in _GEO_NOISE:
        upper = upper.replace(noise, " ")
    hits: Dict[str, List[str]] = {}
    for nation, terms in NATION_HINTS.items():
        found = [t.strip() for t in terms if t in upper]
        if found:
            hits[nation] = found
    if len(hits) == 1:
        nation = next(iter(hits))
        return nation, hits[nation]
    if len(hits) > 1:
        # Mehrdeutig: die Nation mit den meisten Treffern gewinnt, sonst None.
        ranked = sorted(hits.items(), key=lambda kv: len(kv[1]), reverse=True)
        if len(ranked[0][1]) > len(ranked[1][1]):
            return ranked[0][0], ranked[0][1]
        return None, [t for terms in hits.values() for t in terms]
    return None, []


def detect_foreign_operator(text: str) -> List[str]:
    """Findet Betreiber/Programme, die keiner Zielnation zuzuordnen sind."""
    upper = re.sub(r"\s+", " ", (text or "").upper())
    return [op for op in FOREIGN_OPERATORS if op in upper]


#: Q-Code aus der Q-Line, z.B. QRDCA in "ZLHW/QRDCA/IV/BO/W/000/999/...".
RE_QCODE = re.compile(r"\bQ([A-Z]{4})\b")

#: Maximale Dauer, die noch als Startfenster gilt.
LAUNCH_WINDOW_MAX_HOURS = 24.0


def extract_qcode(items: Dict[str, str], text: str = "") -> str:
    """Liest den fuenfstelligen Q-Code (z.B. QRDCA) aus der Q-Line."""
    q_line = items.get("Q", "")
    match = RE_QCODE.search(q_line.upper())
    if not match:
        match = re.search(r"/(Q[A-Z]{4})/", (text or "").upper())
        return match.group(1) if match else ""
    return "Q" + match.group(1)


#: Taegliche Zeitfenster im D-Item, z.B. "DAILY 0900-2100" oder "24-28 1100-2100".
RE_DAILY_WINDOW = re.compile(r"\b(\d{4})\s*-\s*(\d{4})\b")


def daily_window_hours(d_item: Optional[str]) -> Optional[float]:
    """
    Laengstes taegliches Aktivierungsfenster aus dem D-Item, in Stunden.

    Ein NOTAM kann zwei Wochen gueltig sein und trotzdem nur taeglich wenige
    Stunden aktiv - fuer die Startsignatur zaehlt das tatsaechliche Fenster,
    nicht die Gesamtlaufzeit. Ohne D-Item ist das Ergebnis None.
    """
    if not d_item:
        return None
    longest: Optional[float] = None
    for match in RE_DAILY_WINDOW.finditer(d_item.upper()):
        try:
            start_h, start_m = int(match.group(1)[:2]), int(match.group(1)[2:])
            end_h, end_m = int(match.group(2)[:2]), int(match.group(2)[2:])
        except ValueError:
            continue
        if start_h > 24 or end_h > 24 or start_m >= 60 or end_m >= 60:
            continue
        minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
        if minutes <= 0:
            minutes += 24 * 60
        hours = minutes / 60.0
        if longest is None or hours > longest:
            longest = hours
    return longest


def has_launch_signature(
    items: Dict[str, str],
    text: str,
    valid_from: Optional[datetime],
    valid_to: Optional[datetime],
) -> Tuple[bool, str]:
    """
    Prueft die typische Signatur eines Start-NOTAMs der Zielnationen.

    Chinesische und russische Start-NOTAMs nennen weder "ROCKET" noch "LAUNCH";
    sie bestehen aus einem Gefahrengebiet von der Erdoberflaeche bis unbegrenzt,
    das nur wenige Minuten bis Stunden aktiv ist. Genau diese Kombination
    unterscheidet sie von Dauer-Sperrgebieten und Uebungsraeumen:

    1. Q-Code der Gruppe QR (Gefahren-/Sperr-/Restricted Area) oder QWM
       (Raketen-/Geschossbeschuss),
    2. Hoehenfenster ueber die gesamte Atmosphaere (000/999 bzw. SFC-UNL),
    3. Gueltigkeit von hoechstens 24 Stunden.
    """
    qcode = extract_qcode(items, text)
    if not qcode:
        return False, ""
    if not (qcode[1:2] == "R" or qcode[:3] == "QWM"):
        return False, ""

    upper = re.sub(r"\s+", " ", (text or "").upper())
    full_height = QCODE_ALTITUDE in upper or any(pat in upper for pat in UNLIMITED_PATTERNS)
    lower_item = (items.get("F") or "").strip().upper()
    upper_item = (items.get("G") or "").strip().upper()
    if not full_height:
        full_height = any(lower_item.startswith(v) for v in _LOWER_UNLIMITED) and any(
            upper_item.startswith(v) for v in _UPPER_UNLIMITED
        )
    if not full_height:
        return False, ""

    if valid_from is None or valid_to is None:
        return False, ""
    hours = (valid_to - valid_from).total_seconds() / 3600.0
    if hours <= 0:
        return False, ""

    # Ein mehrtaegiges NOTAM mit taeglichem Fenster ist nur wenige Stunden aktiv.
    daily = daily_window_hours(items.get("D"))
    effective = min(hours, daily) if daily is not None else hours
    if effective > LAUNCH_WINDOW_MAX_HOURS:
        return False, ""

    duration = (
        "{:.0f} min".format(effective * 60) if effective < 2 else "{:.1f} h".format(effective)
    )
    if daily is not None and daily < hours:
        duration += " taeglich"
    return True, "Startsignatur: {} + SFC-UNL + Fenster {}".format(qcode, duration)


CONFIDENCE_LEVELS = ("HOCH", "MITTEL", "NIEDRIG")


def score_confidence(
    text: str,
    triggers: Sequence[str],
    items: Optional[Dict[str, str]] = None,
    valid_from: Optional[datetime] = None,
    valid_to: Optional[datetime] = None,
) -> Tuple[int, str, List[str]]:
    """
    Bewertet, wie wahrscheinlich ein getriggertes NOTAM wirklich ein Raumfahrt-
    Event beschreibt.

    Die Trigger aus der Spezifikation sind bewusst breit (ein blosses
    "SFC/UNL" genuegt). Dieses Scoring trennt die echten Starts von den
    zahlreichen Fehlalarmen, ohne ein NOTAM zu verwerfen - niedrig bewertete
    Faelle landen im Review-Tab.

    Rueckgabe: (Score, Stufe, Begruendungen)
    """
    upper = re.sub(r"\s+", " ", (text or "").upper())
    score = 0
    notes: List[str] = []

    strong_hits = [k for k in STRONG_SPACE_KEYWORDS if k in upper]
    if strong_hits:
        score += 3 * min(len(strong_hits), 2)
        notes.append("Raumfahrt-Begriffe: {}".format(", ".join(strong_hits[:4])))

    generic = [t for t in triggers if t.startswith("Keyword:")]
    if generic:
        score += 1
        if not strong_hits:
            notes.append("nur generische Gebietskeywords")

    if any(t.startswith("Hoehenlimit") for t in triggers):
        score += 1
    if any(t.startswith("Q-Code") for t in triggers):
        score += 1

    signature, signature_note = has_launch_signature(
        items or {}, text, valid_from, valid_to
    )
    if signature:
        score += 3
        notes.append(signature_note)

    blockers = [k for k in EXCLUSION_KEYWORDS if k in upper]
    if blockers:
        score -= 4 * min(len(blockers), 2)
        notes.append("Ausschlussbegriffe: {}".format(", ".join(b.strip() for b in blockers[:4])))

    if score >= 5:
        level = "HOCH"
    elif score >= 3:
        level = "MITTEL"
    else:
        level = "NIEDRIG"
    return score, level, notes


def extract_altitude_profile(text: str, items: Dict[str, str]) -> str:
    """Bildet ein kompaktes Hoehenprofil aus F/G-Items bzw. Freitext."""
    lower = items.get("F"), items.get("G")
    if lower[0] and lower[1]:
        return "{} - {}".format(lower[0].strip(), lower[1].strip())

    compact = re.sub(r"\s+", " ", (text or "").upper())
    for pattern in UNLIMITED_PATTERNS:
        if pattern in compact:
            return pattern
    if QCODE_ALTITUDE in compact:
        return "FL000 - FL999"
    match = re.search(r"\b(FL\d{3})\s*[-/]\s*(FL\d{3})\b", compact)
    if match:
        return "{} - {}".format(match.group(1), match.group(2))
    return "-"


# --------------------------------------------------------------------------- #
# Referenzdaten
# --------------------------------------------------------------------------- #
SPACEPORT_COLUMNS = ["Kurzel", "Latitude", "Longitude", "Name", "Land"]
FIR_COLUMNS = [
    "ICAO Code",
    "Latitude",
    "Longitude",
    "Betroffene Region / FIR Name",
    "Land",
    "Zugehörige Startnation",
]


def _read_csv_any(source: Any) -> pd.DataFrame:
    """Liest eine CSV mit automatischer Trennzeichen- und Encoding-Erkennung."""
    raw = source.read() if hasattr(source, "read") else Path(source).read_bytes()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(
                io.BytesIO(raw), sep=None, engine="python", encoding=encoding, dtype=str
            )
        except Exception as exc:  # pragma: no cover - Formatvielfalt
            last_error = exc
    raise ValueError("CSV konnte nicht gelesen werden: {}".format(last_error))


def _looks_like_header(row: pd.Series) -> bool:
    """Header-Zeilen sind gefuellt und enthalten ausschliesslich kurze Texte."""
    values = [v for v in row.tolist() if pd.notna(v) and str(v).strip()]
    if len(values) < 3:
        return False
    return all(len(str(v).strip()) <= 60 for v in values)


def _promote_header(raw: pd.DataFrame, max_scan: int = 25) -> pd.DataFrame:
    """
    Findet die eigentliche Kopfzeile einer Tabelle mit Vorspann.

    Exporte aus FAA FNS o.ae. beginnen mit Titel- und Filterzeilen; die echten
    Spaltennamen stehen erst darunter.
    """
    for i in range(min(max_scan, len(raw))):
        if _looks_like_header(raw.iloc[i]):
            out = raw.iloc[i + 1 :].copy()
            out.columns = [str(c).strip() for c in raw.iloc[i]]
            return out.dropna(how="all").reset_index(drop=True)
    return raw


def read_notam_table(source: Any, filename: str = "") -> pd.DataFrame:
    """
    Liest eine NOTAM-Tabelle als CSV, XLS oder XLSX ein.

    Vorspannzeilen werden automatisch uebersprungen, Trennzeichen und Encoding
    bei CSV automatisch erkannt.
    """
    name = (filename or getattr(source, "name", "") or "").lower()
    raw_bytes = source.read() if hasattr(source, "read") else Path(source).read_bytes()
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8")

    # Formaterkennung ueber Magic Bytes, damit auch falsch benannte Dateien
    # (haeufig bei Behoerden-Exporten) korrekt gelesen werden.
    is_ole2 = raw_bytes[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    is_zip = raw_bytes[:4] == b"PK\x03\x04"
    if is_ole2 or is_zip or name.endswith((".xls", ".xlsx", ".xlsm")):
        engine = "xlrd" if (is_ole2 or (name.endswith(".xls") and not is_zip)) else "openpyxl"
        try:
            raw = pd.read_excel(io.BytesIO(raw_bytes), dtype=str, header=None, engine=engine)
        except ImportError as exc:
            raise ValueError(
                "Fuer {}-Dateien wird das Paket '{}' benoetigt: pip install {}".format(
                    name.rsplit(".", 1)[-1], engine, engine
                )
            ) from exc
        return _promote_header(raw)

    df = _read_csv_any(io.BytesIO(raw_bytes))
    unnamed = sum(1 for c in df.columns if str(c).lower().startswith("unnamed"))
    if df.shape[1] > 1 and unnamed >= df.shape[1] / 2:
        raw = pd.read_csv(io.BytesIO(raw_bytes), sep=None, engine="python", dtype=str, header=None)
        return _promote_header(raw)
    return df


def _require_columns(df: pd.DataFrame, expected: Sequence[str], label: str) -> pd.DataFrame:
    """Prueft Pflichtspalten und normalisiert numerische Felder."""
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(
            "{}: fehlende Spalte(n) {}. Gefunden: {}".format(
                label, ", ".join(missing), ", ".join(map(str, df.columns))
            )
        )
    out = df.copy()
    for col in ("Latitude", "Longitude"):
        out[col] = pd.to_numeric(
            out[col].astype(str).str.replace(",", ".", regex=False), errors="coerce"
        )
    dropped = int(out["Latitude"].isna().sum() + out["Longitude"].isna().sum())
    out = out.dropna(subset=["Latitude", "Longitude"]).reset_index(drop=True)
    if dropped:
        out.attrs["dropped_rows"] = dropped
    return out


VEHICLE_COLUMNS = ["Land", "Name", "Alternativname englisch", "Abkürzung"]


@st.cache_data(show_spinner=False)
def load_vehicles(path_str: str, mtime: float = 0.0) -> pd.DataFrame:
    """
    Laedt die Referenz der aktiven Traegersysteme.

    Anders als Startplaetze und FIRs traegt sie keine Koordinaten, sondern
    ordnet jedem Traegersystem eine Nation zu. mtime gehoert zum Cache-
    Schluessel, damit Aenderungen an der Datei sofort greifen.
    """
    df = _read_csv_any(path_str)
    fehlend = [c for c in VEHICLE_COLUMNS if c not in df.columns]
    if fehlend:
        raise ValueError(
            "Traegersysteme: fehlende Spalte(n) {}. Gefunden: {}".format(
                ", ".join(fehlend), ", ".join(map(str, df.columns))
            )
        )
    out = df[VEHICLE_COLUMNS].copy()
    for spalte in VEHICLE_COLUMNS:
        out[spalte] = out[spalte].astype(str).str.strip()
    out = out[out["Abkürzung"].astype(bool) & out["Name"].astype(bool)]
    return out.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_spaceports(path_str: str, mtime: float = 0.0) -> pd.DataFrame:
    # mtime gehoert zum Cache-Schluessel: wird die Referenzdatei gepflegt,
    # laedt die App sie beim naechsten Aufruf neu statt die alte Fassung zu
    # behalten, bis der Server neu startet.
    df = _require_columns(_read_csv_any(path_str), SPACEPORT_COLUMNS, "Weltraumbahnhoefe")
    df["Kurzel"] = df["Kurzel"].astype(str).str.strip().str.upper()
    df["Land"] = df["Land"].astype(str).str.strip()
    return df


@st.cache_data(show_spinner=False)
def load_firs(path_str: str, mtime: float = 0.0) -> pd.DataFrame:
    # siehe load_spaceports: der Zeitstempel erzwingt das Neuladen.
    df = _require_columns(_read_csv_any(path_str), FIR_COLUMNS, "ICAO FIR/ACC")
    df["ICAO Code"] = df["ICAO Code"].astype(str).str.strip().str.upper()
    df["Nationen"] = (
        df["Zugehörige Startnation"]
        .astype(str)
        .apply(lambda s: [p.strip() for p in re.split(r"[;,/]", s) if p.strip()])
    )
    return df


#: Arbeitsstand der Sitzung: manuelle NOTAMs, Bestaetigungen, Ausblendungen.
WORKSPACE_FILE = APP_DIR / "notam_workspace.json"

#: Wie viele Schritte im Optionsmenue rueckgaengig gemacht werden koennen.
UNDO_LIMIT = 20


def persist_reference(path: Path, df: pd.DataFrame, columns: Sequence[str]) -> None:
    """
    Schreibt eine Referenztabelle zurueck in ihre Projektdatei.

    Die Datei ist die einzige Quelle der Wahrheit - Aenderungen ueberleben
    damit einen Neustart. Die abgeleitete Spalte ``Nationen`` wird nicht
    geschrieben, sie entsteht beim Laden neu.
    """
    path.write_text(df[list(columns)].to_csv(index=False), encoding="utf-8")


def load_workspace() -> Dict[str, Any]:
    """Liest den gespeicherten Arbeitsstand; fehlt oder bricht er, beginnt man leer."""
    try:
        data = json.loads(WORKSPACE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_workspace(
    manual_notams: Sequence[Dict[str, Any]],
    confirmed: Sequence[str],
    hidden: Sequence[str],
    rejected: Sequence[str] = (),
) -> None:
    """Schreibt den Arbeitsstand in die Projektdatei."""
    try:
        WORKSPACE_FILE.write_text(
            json.dumps(
                {
                    "gespeichert_utc": datetime.now(timezone.utc).isoformat(),
                    "manual_notams": list(manual_notams),
                    "confirmed_launches": sorted(confirmed),
                    "hidden_events": sorted(hidden),
                    "rejected_launches": sorted(rejected),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:  # pragma: no cover - Schreibfehler duerfen die App nicht stoppen
        pass


def apply_reference_overrides(
    df: pd.DataFrame,
    key_column: str,
    removed: Sequence[str],
    added: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    """
    Wendet die im Optionsmenue vorgenommenen Aenderungen auf eine Referenztabelle an.

    Entfernte Eintraege fallen aus jeder Berechnung heraus, ergaenzte kommen
    unmittelbar hinzu. Die Dateien auf der Platte bleiben unangetastet, solange
    sie nicht ausdruecklich geschrieben werden.
    """
    out = df
    if removed:
        out = out[~out[key_column].astype(str).isin(list(removed))]
    if added:
        neu = pd.DataFrame(list(added))
        for spalte in out.columns:
            if spalte not in neu.columns:
                neu[spalte] = None
        neu = neu[out.columns]
        out = pd.concat([out, neu], ignore_index=True)
        # Ein wieder hinzugefuegter Eintrag ersetzt den aus der Datei, statt ihn
        # zu verdoppeln - die manuelle Angabe ist die juengere.
        out = out.drop_duplicates(subset=[key_column], keep="last")
    out = out.copy()
    for spalte in ("Latitude", "Longitude"):
        if spalte in out.columns:
            out[spalte] = pd.to_numeric(out[spalte], errors="coerce")
    out = out.dropna(subset=[c for c in ("Latitude", "Longitude") if c in out.columns])
    if "Zugehörige Startnation" in out.columns:
        # Fuer ergaenzte Zeilen die abgeleitete Nationenliste nachziehen.
        out["Nationen"] = (
            out["Zugehörige Startnation"]
            .astype(str)
            .apply(lambda v: [p.strip() for p in re.split(r"[;,/]", v) if p.strip()])
        )
    return out.reset_index(drop=True)


def reference_to_csv(df: pd.DataFrame, columns: Sequence[str]) -> bytes:
    """Serialisiert eine Referenztabelle im Format der Eingabedateien."""
    return df[list(columns)].to_csv(index=False).encode("utf-8-sig")


# --------------------------------------------------------------------------- #
# NOTAM-CSV Spaltenerkennung
# --------------------------------------------------------------------------- #
def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


COLUMN_HINTS: Dict[str, Tuple[str, ...]] = {
    "id": ("notamid", "id", "notamnumber", "number", "notam", "seriesnumber", "ref"),
    "text": ("text", "notamtext", "message", "rawtext", "body", "eitem", "itemE", "full"),
    "fir": ("fir", "ficir", "firicao", "icao", "location", "loc", "aerodrome", "icaocode"),
    "start": ("validfrom", "startvalidity", "start", "from", "begin", "bitem", "effective"),
    "end": ("validto", "endvalidity", "end", "to", "until", "citem", "expiry"),
    "qline": ("qline", "qcode", "q", "qitem"),
}


def map_notam_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Ordnet die Spalten einer beliebigen NOTAM-Tabelle den benoetigten Rollen zu.

    Die Volltextspalte wird zuerst bestimmt und danach fuer alle anderen Rollen
    gesperrt. Andernfalls greift sich die ID-Rolle eine Spalte wie "NOTAM Text"
    (Teiltreffer auf "notam") und die Ergebnistabelle zeigt den ganzen NOTAM-Text
    als Kennung.
    """
    mapping: Dict[str, Optional[str]] = {key: None for key in COLUMN_HINTS}
    normalized = {col: _normalize(col) for col in df.columns if col != SOURCE_COLUMN}
    if not normalized:
        return mapping

    text_hints = COLUMN_HINTS["text"]
    for col, norm in normalized.items():
        if norm in text_hints:
            mapping["text"] = col
            break
    if mapping["text"] is None:
        for col, norm in normalized.items():
            if any(h in norm for h in text_hints):
                mapping["text"] = col
                break
    if mapping["text"] is None:
        lengths = {
            col: df[col].astype(str).str.len().mean(skipna=True) for col in normalized
        }
        if lengths:
            mapping["text"] = max(lengths, key=lambda c: (lengths[c] or 0))

    remaining = {c: n for c, n in normalized.items() if c != mapping["text"]}
    for role, hints in COLUMN_HINTS.items():
        if role == "text":
            continue
        for col, norm in remaining.items():
            if norm in hints and mapping[role] is None:
                mapping[role] = col
        if mapping[role] is None:
            for col, norm in remaining.items():
                if any(h in norm for h in hints) and col not in mapping.values():
                    mapping[role] = col
                    break
    return mapping


def row_to_text(row: pd.Series, text_col: Optional[str]) -> str:
    """Baut den Analysetext: bevorzugt die Volltextspalte, sonst alle Zellen."""
    parts: List[str] = []
    if text_col is not None and text_col in row.index:
        value = row[text_col]
        if pd.notna(value) and str(value).strip():
            parts.append(str(value))
    for col in row.index:
        if col == text_col or col == SOURCE_COLUMN:
            continue
        value = row[col]
        if pd.notna(value) and str(value).strip():
            parts.append("{}: {}".format(col, value))
    return normalize_notam_text(" | ".join(parts))


# --------------------------------------------------------------------------- #
# Analyse-Ergebnis
# --------------------------------------------------------------------------- #
@dataclass
class LaunchEvent:
    """Ein ausgewertetes NOTAM inklusive Trajektorien-Abschaetzung."""

    row_index: int
    notam_id: str
    raw_text: str
    source: str = SOURCE_IMPORT
    triggers: List[str] = field(default_factory=list)
    coordinates: List[Tuple[float, float]] = field(default_factory=list)
    zones: List[List[Tuple[float, float]]] = field(default_factory=list)
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    radius_km: Optional[float] = None
    fir_code: Optional[str] = None
    fir_name: Optional[str] = None
    fir_country: Optional[str] = None
    fir_match_method: str = "-"
    nation: Optional[str] = None
    spaceport_code: Optional[str] = None
    spaceport_name: Optional[str] = None
    spaceport_lat: Optional[float] = None
    spaceport_lon: Optional[float] = None
    distance_km: Optional[float] = None
    azimuth_deg: Optional[float] = None
    inclination_deg: Optional[float] = None
    orbit_type: str = "Unbestimmt"
    altitude_profile: str = "-"
    confidence_score: int = 0
    confidence_level: str = "NIEDRIG"
    confidence_notes: List[str] = field(default_factory=list)
    assignment_note: str = ""
    candidate_nations: List[str] = field(default_factory=list)
    kind: str = KIND_LAUNCH
    spaceport_hint: List[str] = field(default_factory=list)
    spaceport_evidence: List[str] = field(default_factory=list)
    requires_group: bool = False
    passes_confidence: bool = False
    key: str = ""
    manual_override: bool = False
    reliability: str = "-"
    launch_group: str = ""
    nation_hint: Optional[str] = None
    nation_evidence: List[str] = field(default_factory=list)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    status: str = "OK"
    review_reason: str = ""

    @property
    def launch_window(self) -> str:
        fmt = "%d.%m.%Y %H:%MZ"
        if self.valid_from and self.valid_to:
            return "{} - {}".format(self.valid_from.strftime(fmt), self.valid_to.strftime(fmt))
        if self.valid_from:
            return "ab {}".format(self.valid_from.strftime(fmt))
        if self.valid_to:
            return "bis {}".format(self.valid_to.strftime(fmt))
        return "-"


MAX_FIR_FALLBACK_KM = 1500.0


def _find_fir(
    text: str, fir_hint: Optional[str], firs: pd.DataFrame, centroid: Optional[Tuple[float, float]]
) -> Tuple[Optional[pd.Series], str]:
    """
    Ordnet ein NOTAM einer FIR der Zielnationen zu.

    Wichtig: Ein explizit genannter ICAO-Code (Location-Spalte, A-Item oder
    Q-Line) ist bindend. Gehoert er nicht zur Referenz, liegt das NOTAM
    ausserhalb des Beobachtungsraums und wird NICHT geographisch auf die
    naechstgelegene FIR umgebogen - genau das erzeugte sonst Fehlzuordnungen
    (z.B. ein Londoner NOTAM als russischer Start).
    """
    known = {str(code): idx for idx, code in firs["ICAO Code"].items()}
    items = extract_items(text)

    explicit: List[str] = []
    if fir_hint is not None and pd.notna(fir_hint):
        explicit += RE_ICAO.findall(str(fir_hint).upper())
    if items.get("A"):
        explicit += RE_ICAO.findall(items["A"].upper())
    q_line = items.get("Q", "")
    if q_line:
        explicit += RE_ICAO.findall(q_line.upper().split("/")[0])

    for code in explicit:
        if code in known:
            return firs.loc[known[code]], "ICAO-Code"
    if explicit:
        return None, "Ausserhalb: {}".format(explicit[0])

    for code in RE_ICAO.findall((text or "").upper()):
        if code in known:
            return firs.loc[known[code]], "Text"

    if centroid is not None and len(firs):
        distances = firs.apply(
            lambda r: haversine_km(centroid[0], centroid[1], r["Latitude"], r["Longitude"]),
            axis=1,
        )
        if distances.min() <= MAX_FIR_FALLBACK_KM:
            return firs.loc[distances.idxmin()], "Geographisch (naechste FIR)"
        return None, "Zu weit von jeder Ziel-FIR ({:.0f} km)".format(distances.min())

    return None, "-"


#: Azimut-Sektor, in dem keine der Zielnationen startet.
#: Ein Start nach Westen arbeitet gegen die Erdrotation und kostet rund 900 m/s
#: zusaetzliches Delta-v; operativ kommt das bei China, Russland, Indien, Iran und
#: Nordkorea nicht vor. Startplaetze, die nur ueber diesen Sektor zur Sperrzone
#: passen wuerden, scheiden daher aus - sonst gewinnt bei abgelegenen Dropzonen
#: der geographisch naechste, aber falsche Startplatz.
#: Untergrenze knapp unter den suedlichsten SSO-Azimuten (Taiyuan/Jiuquan ~190°,
#: SDSC ~188°), Obergrenze unter den noerdlichen SSO-Azimuten von Plesetsk und
#: Vostochny (~340-350°), die weiterhin zulaessig bleiben muessen.
IMPLAUSIBLE_AZIMUTH_SECTOR = (225.0, 325.0)


def _restrict_candidates(
    spaceports: pd.DataFrame, nations: Sequence[str], hint: Sequence[str]
) -> pd.DataFrame:
    """
    Schraenkt die Startplatz-Auswahl ein: zuerst auf die im Text genannten
    Startplaetze, sonst auf die Kandidaten-Nationen.
    """
    candidates = spaceports
    if nations:
        gefiltert = spaceports[spaceports["Land"].isin(list(nations))]
        if not gefiltert.empty:
            candidates = gefiltert
    if hint:
        genannt = candidates[candidates["Kurzel"].isin(list(hint))]
        if genannt.empty:
            # Der genannte Startplatz gehoert zu einer anderen Nation als die
            # FIR nahelegt - der Text ist die staerkere Quelle.
            genannt = spaceports[spaceports["Kurzel"].isin(list(hint))]
        if not genannt.empty:
            return genannt
    return candidates


def _find_spaceport(
    centroid: Tuple[float, float],
    spaceports: pd.DataFrame,
    nations: Sequence[str],
    hint: Optional[Sequence[str]] = None,
) -> Tuple[Optional[pd.Series], bool, str]:
    """
    Waehlt den Weltraumbahnhof zur Sperrzone.

    Nennt der Text ein Traegersystem oder einen Startplatz, wird die Auswahl
    darauf beschraenkt. Sonst gilt der naechstgelegene Startplatz (Haversine)
    unter den Kandidaten-Nationen, dessen Startrichtung moeglich ist.

    Rueckgabe: (Startplatz, Startrichtung plausibel, Hinweis).
    """
    candidates = _restrict_candidates(spaceports, nations, hint or [])
    if candidates.empty:
        return None, False, ""

    rows: List[Tuple[float, float, Any]] = []
    for idx, row in candidates.iterrows():
        distance = haversine_km(centroid[0], centroid[1], row["Latitude"], row["Longitude"])
        azimuth = initial_bearing_deg(
            row["Latitude"], row["Longitude"], centroid[0], centroid[1]
        )
        rows.append((distance, azimuth, idx))

    # Die Richtungspruefung gilt nur fuer nahe Zonen: ueber sehr weite Strecken
    # ist der Anfangskurs kein verlaesslicher Hinweis auf den Startazimut.
    low, high = IMPLAUSIBLE_AZIMUTH_SECTOR
    plausible = [
        r for r in rows if r[0] > FAR_ZONE_KM or not (low <= r[1] <= high)
    ]
    pool = sorted(plausible or rows)
    best = pool[0]

    note = ""
    if plausible:
        nearest = min(rows)
        if nearest[2] != best[2]:
            skipped = candidates.loc[nearest[2]]
            note = (
                "{} liegt naeher ({:.0f} km), ergaebe aber Azimut {:.0f}° "
                "(Start nach Westen) - verworfen.".format(
                    skipped["Kurzel"], nearest[0], nearest[1]
                )
            )
    return candidates.loc[best[2]], bool(plausible), note


#: Jenseits dieser Entfernung ist die Zuordnung Sperrzone -> Startplatz nur noch
#: grob: ueber solche Strecken verschiebt die Erdrotation die Bodenspur deutlich,
#: der Anfangskurs entspricht dann nicht mehr sauber dem Startazimut. Solche
#: Zonen (Oberstufen-Deorbit, Wiedereintritt) werden nicht verworfen, sondern
#: mit gemindeter Zuverlaessigkeit ausgewiesen.
FAR_ZONE_KM = 8000.0
NEAR_ZONE_KM = 3000.0

#: Praktisch keine Obergrenze mehr - der halbe Erdumfang betraegt rund 20000 km.
MAX_PLAUSIBLE_RANGE_KM = 20000.0


#: Streuung, ab der die Zonen keine gemeinsame Bahn mehr beschreiben koennen.
MEANINGLESS_SPREAD_DEG = 60.0


def zone_reliability(
    distance_km: Optional[float], kind: str = KIND_LAUNCH, spread_deg: float = 0.0
) -> str:
    """
    Bewertet, wie belastbar die Bahnabschaetzung fuer diese Zone ist.

    Neben der Entfernung zaehlen die Art des Ereignisses - fuer einen
    Wiedereintritt sagt die Richtung vom Startplatz nichts aus - und die
    Streuung der Zonen zueinander.
    """
    if distance_km is None:
        return "-"
    if kind == KIND_REENTRY or spread_deg > MEANINGLESS_SPREAD_DEG:
        return "gering"
    if distance_km <= NEAR_ZONE_KM:
        return "hoch"
    if distance_km <= FAR_ZONE_KM:
        return "mittel"
    return "gering"

#: Zwei NOTAMs gehoeren zum selben Start, wenn ihre Aktivierungszeiten hoechstens
#: so weit auseinanderliegen. Reale Dropzone-NOTAMs eines Starts werden im Abstand
#: von Sekunden bis wenigen Minuten veroeffentlicht.
LAUNCH_GROUP_MAX_GAP_MINUTES = 30.0

#: Obergrenze fuer die Gesamtspanne einer Gruppe, damit eine Kette knapp
#: aufeinanderfolgender NOTAMs nicht unbegrenzt zusammenwaechst.
LAUNCH_GROUP_MAX_SPAN_MINUTES = 90.0

#: Maximale Azimut-Streuung, bei der die Zonen noch auf einer gemeinsamen Bahn
#: liegen koennen. Darueber gehoeren die NOTAMs nicht zum selben Start und werden
#: einzeln zugeordnet. Real beobachtete Streuungen zusammengehoeriger Dropzonen
#: liegen unter 9° (Bahnkruemmung und Dogleg-Manoever); 15° laesst dafuer Luft,
#: trennt aber zeitgleiche Zonen voellig verschiedener Starts zuverlaessig.
LAUNCH_GROUP_MAX_SPREAD_DEG = 15.0

#: Mehrtaegige Meldungen derselben Aktivitaet (australische, neuseelaendische
#: und maritime Warnungen zum selben russischen Start) laufen ueber dieselbe
#: Zeitspanne, starten aber an verschiedenen Tagen. Sie gelten als zusammen-
#: gehoerig, wenn sich ihre Gueltigkeit fast vollstaendig deckt.
LAUNCH_GROUP_LONG_HOURS = 12.0
LAUNCH_GROUP_MIN_OVERLAP = 0.8


def _duration_hours(event: LaunchEvent) -> float:
    if event.valid_from is None or event.valid_to is None:
        return 0.0
    return max((event.valid_to - event.valid_from).total_seconds() / 3600.0, 0.0)


def _overlap_ratio(a: LaunchEvent, b: LaunchEvent) -> float:
    """
    Anteil der Ueberschneidung an der laengeren der beiden Gueltigkeiten.

    Bewusst die laengere: ein kurzes Sperrfenster, das zufaellig innerhalb einer
    wochenlangen Meldung liegt, gehoert nicht automatisch zum selben Start.
    """
    if None in (a.valid_from, a.valid_to, b.valid_from, b.valid_to):
        return 0.0
    start = max(a.valid_from, b.valid_from)
    end = min(a.valid_to, b.valid_to)
    overlap = (end - start).total_seconds()
    if overlap <= 0:
        return 0.0
    longer = max(
        (a.valid_to - a.valid_from).total_seconds(),
        (b.valid_to - b.valid_from).total_seconds(),
    )
    return overlap / longer if longer > 0 else 0.0


def _same_launch_window(cluster: Sequence[LaunchEvent], event: LaunchEvent) -> bool:
    """Prueft, ob ein NOTAM zeitlich zum bisherigen Cluster passt."""
    first, last = cluster[0], cluster[-1]
    if event.valid_from is None or last.valid_from is None:
        return False
    if not (set(event.candidate_nations) & set(first.candidate_nations)):
        return False

    both_short = (
        _duration_hours(event) < LAUNCH_GROUP_LONG_HOURS
        and _duration_hours(first) < LAUNCH_GROUP_LONG_HOURS
    )
    if both_short:
        # Kurze Sperrzonen-NOTAMs eines Starts werden Sekunden bis Minuten
        # nacheinander veroeffentlicht.
        gap = (event.valid_from - last.valid_from).total_seconds() / 60.0
        span = (event.valid_from - first.valid_from).total_seconds() / 60.0
        return gap <= LAUNCH_GROUP_MAX_GAP_MINUTES and span <= LAUNCH_GROUP_MAX_SPAN_MINUTES

    # Mehrtaegige Meldungen: nur bei nahezu deckungsgleicher Gueltigkeit. Eine
    # gleiche Anfangszeit reicht nicht - zwei Starts koennen am selben Tag
    # beginnen und voellig verschiedene Zeitraeume abdecken.
    return _overlap_ratio(first, event) >= LAUNCH_GROUP_MIN_OVERLAP


def _group_hint(cluster: Sequence[LaunchEvent]) -> List[str]:
    """Startplatz-Hinweise aller Mitglieder einer Gruppe, Reihenfolge erhalten."""
    codes: List[str] = []
    for event in cluster:
        for code in event.spaceport_hint:
            if code not in codes:
                codes.append(code)
    return codes


def _group_nations(cluster: Sequence[LaunchEvent]) -> List[str]:
    """
    Kandidaten-Nationen einer Gruppe.

    Bevorzugt wird die Schnittmenge: nennt ein NOTAM der Gruppe die Nation
    eindeutig, gilt sie fuer alle. Ist die Schnittmenge leer, wird die
    Vereinigung genommen.
    """
    sets = [set(e.candidate_nations) for e in cluster if e.candidate_nations]
    if not sets:
        return []
    shared = set.intersection(*sets)
    if shared:
        return sorted(shared)
    return sorted(set().union(*sets))


@dataclass
class LaunchGroup:
    """Ein Start, zu dem eine oder mehrere Sperrzonen-NOTAMs gehoeren."""

    group_id: str
    notam_ids: List[str] = field(default_factory=list)
    row_indices: List[int] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    nation: Optional[str] = None
    spaceport_code: Optional[str] = None
    spaceport_name: Optional[str] = None
    spaceport_lat: Optional[float] = None
    spaceport_lon: Optional[float] = None
    fir_codes: List[str] = field(default_factory=list)
    azimuth_deg: Optional[float] = None
    azimuth_spread_deg: float = 0.0
    inclination_deg: Optional[float] = None
    orbit_type: str = "Unbestimmt"
    max_range_km: Optional[float] = None
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None
    confidence_level: str = "NIEDRIG"
    reliability: str = "-"
    kind: str = KIND_LAUNCH
    manual_override: bool = False

    @property
    def zone_count(self) -> int:
        return len(self.row_indices)

    @property
    def launch_window(self) -> str:
        fmt = "%d.%m.%Y %H:%MZ"
        if self.window_from and self.window_to:
            return "{} - {}".format(
                self.window_from.strftime(fmt), self.window_to.strftime(fmt)
            )
        if self.window_from:
            return "ab {}".format(self.window_from.strftime(fmt))
        return "-"


def _angular_spread(degrees: Sequence[float]) -> float:
    """Groesste Winkeldifferenz innerhalb einer Menge von Azimuten (0-180°)."""
    values = list(degrees)
    if len(values) < 2:
        return 0.0
    widest = 0.0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            diff = abs(values[i] - values[j]) % 360.0
            widest = max(widest, min(diff, 360.0 - diff))
    return widest


def _circular_mean(degrees: Sequence[float]) -> float:
    """Mittlerer Azimut, korrekt ueber den 0°/360°-Sprung hinweg."""
    values = list(degrees)
    if not values:
        return 0.0
    x = sum(math.cos(math.radians(d)) for d in values) / len(values)
    y = sum(math.sin(math.radians(d)) for d in values) / len(values)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _score_spaceport_for_zones(
    port: pd.Series, zones: Sequence[Tuple[float, float]]
) -> Optional[Tuple[float, float, float, List[float], List[float]]]:
    """
    Bewertet einen Startplatz gegen alle Zonen eines Starts.

    Rueckgabe: (Score, Azimut-Streuung, mittlere Distanz, Azimute, Distanzen) oder
    None, wenn eine der Zonen nur ueber eine unmoegliche Startrichtung erreichbar
    waere. Der Score gewichtet die Streuung deutlich staerker als die Entfernung:
    Zonen eines Starts liegen auf einer Linie, auch wenn ein anderer Startplatz
    geographisch naeher liegt.
    """
    azimuths: List[float] = []
    distances: List[float] = []
    low, high = IMPLAUSIBLE_AZIMUTH_SECTOR
    for lat, lon in zones:
        azimuth = initial_bearing_deg(port["Latitude"], port["Longitude"], lat, lon)
        distance = haversine_km(port["Latitude"], port["Longitude"], lat, lon)
        if distance <= FAR_ZONE_KM and low <= azimuth <= high:
            return None
        azimuths.append(azimuth)
        distances.append(distance)

    # Die Streuung wird nur ueber nahe Zonen gemessen: bei Deorbit- und
    # Wiedereintrittsgebieten am anderen Ende der Erde sagt der Anfangskurs
    # nichts mehr ueber die Bahnlage aus, die Streuung waere dort Rauschen.
    near = [a for a, d in zip(azimuths, distances) if d <= FAR_ZONE_KM]
    spread = _angular_spread(near) if len(near) >= 2 else 0.0
    mean_distance = sum(distances) / len(distances)
    return spread * 100.0 + mean_distance, spread, mean_distance, azimuths, distances


def _select_spaceport_for_zones(
    zones: Sequence[Tuple[float, float]],
    spaceports: pd.DataFrame,
    nations: Sequence[str],
    hint: Optional[Sequence[str]] = None,
) -> Optional[Tuple[pd.Series, float, List[float], List[float]]]:
    """Waehlt den Startplatz, der alle Zonen eines Starts am besten erklaert."""
    candidates = _restrict_candidates(spaceports, nations, hint or [])
    if candidates.empty or not zones:
        return None

    best: Optional[Tuple[float, Any, float, List[float], List[float]]] = None
    for idx, row in candidates.iterrows():
        scored = _score_spaceport_for_zones(row, zones)
        if scored is None:
            continue
        score, spread, _mean, azimuths, distances = scored
        if best is None or score < best[0]:
            best = (score, idx, spread, azimuths, distances)
    if best is None:
        return None
    return candidates.loc[best[1]], best[2], best[3], best[4]


def _cluster_by_time(events: Sequence[LaunchEvent]) -> List[List[LaunchEvent]]:
    """
    Bildet Zeit-Cluster: aufeinanderfolgende NOTAMs, deren Aktivierung nah genug
    beieinander liegt und deren Kandidaten-Nationen sich ueberschneiden.
    """
    ordered = sorted(
        events,
        key=lambda e: (
            e.valid_from or datetime.max.replace(tzinfo=timezone.utc),
            e.row_index,
        ),
    )
    clusters: List[List[LaunchEvent]] = []
    current: List[LaunchEvent] = []
    for event in ordered:
        if not current:
            current = [event]
            continue
        if _same_launch_window(current, event):
            current.append(event)
        else:
            clusters.append(current)
            current = [event]
    if current:
        clusters.append(current)
    return clusters


def _split_cluster(
    cluster: Sequence[LaunchEvent], spaceports: pd.DataFrame
) -> List[List[LaunchEvent]]:
    """
    Zerlegt einen Zeit-Cluster in Gruppen, die tatsaechlich auf einer Bahn liegen.

    Passt kein Startplatz zu allen Zonen, wird das NOTAM entfernt, dessen
    Wegfall die Azimut-Streuung am staerksten senkt, und der Rest erneut
    geprueft. So bleibt aus drei zeitgleichen NOTAMs das echte Paar erhalten,
    waehrend der Ausreisser eine eigene Gruppe bildet.
    """
    events = list(cluster)
    if len(events) <= 1:
        return [events]

    nations = _group_nations(events)
    zones = [(e.centroid_lat, e.centroid_lon) for e in events]
    selection = _select_spaceport_for_zones(zones, spaceports, nations, _group_hint(events))
    if selection is not None and selection[1] <= LAUNCH_GROUP_MAX_SPREAD_DEG:
        return [events]

    best_index: Optional[int] = None
    best_spread = float("inf")
    for i in range(len(events)):
        subset = events[:i] + events[i + 1 :]
        sub_nations = _group_nations(subset)
        sub_selection = _select_spaceport_for_zones(
            [(e.centroid_lat, e.centroid_lon) for e in subset], spaceports, sub_nations,
            _group_hint(subset),
        )
        spread = sub_selection[1] if sub_selection is not None else float("inf")
        if spread < best_spread:
            best_spread = spread
            best_index = i

    if best_index is None or best_spread == float("inf"):
        return [[e] for e in events]

    removed = events[best_index]
    rest = events[:best_index] + events[best_index + 1 :]
    return _split_cluster(rest, spaceports) + [[removed]]


def group_launches(
    events: Sequence[LaunchEvent], spaceports: pd.DataFrame
) -> List[LaunchGroup]:
    """
    Fasst NOTAMs desselben Starts zusammen und ordnet sie gemeinsam zu.

    Ein Start erzeugt mehrere Sperrzonen entlang der Flugbahn - erste Stufe,
    Booster, Nutzlastverkleidung. Einzeln betrachtet gewinnt fuer eine weit
    abgelegene Zone der naechstgelegene, aber falsche Startplatz. Gemeinsam
    betrachtet erklaert nur ein Startplatz alle Zonen ueber denselben Azimut.

    Gruppiert wird nach Aktivierungszeit; danach wird der Startplatz gewaehlt,
    der die geringste Azimut-Streuung ueber alle Zonen der Gruppe ergibt.
    """
    groupable = [
        e
        for e in events
        if e.centroid_lat is not None
        and e.candidate_nations
        and (
            e.status == "OK"
            or e.manual_override
            or (e.requires_group and e.passes_confidence)
            or e.review_reason.startswith("Kein Startplatz")
        )
    ]

    groups: List[LaunchGroup] = []
    sequence = 0
    for cluster in _cluster_by_time(groupable):
        for subcluster in _split_cluster(cluster, spaceports):
            group = _build_group(subcluster, spaceports)
            if group is None:
                continue
            sequence += 1
            group.group_id = "START-{:02d}".format(sequence)
            for event in subcluster:
                event.launch_group = group.group_id
                if len(subcluster) > 1:
                    event.assignment_note = (
                        "Gemeinsame Bahn mit {} weiteren NOTAM(s) desselben Starts "
                        "({}, Azimut-Streuung {:.1f}°).".format(
                            len(subcluster) - 1, group.group_id, group.azimuth_spread_deg
                        )
                    )
            groups.append(group)
    return groups


def _build_group(
    cluster: Sequence[LaunchEvent], spaceports: pd.DataFrame
) -> Optional[LaunchGroup]:
    """
    Erzeugt eine Gruppe und schreibt die gemeinsame Zuordnung in die Events.

    Rueckgabe None, wenn kein Start daraus wird - etwa ein einzelnes NOTAM, das
    weiterhin im Review steht.
    """
    if len(cluster) == 1 and (
        cluster[0].status != "OK"
        or (cluster[0].requires_group and not cluster[0].manual_override)
    ):
        return None

    group = LaunchGroup(
        group_id="",
        notam_ids=[],
        row_indices=[e.row_index for e in cluster],
        sources=sorted({e.source for e in cluster}),
        fir_codes=sorted({e.fir_code for e in cluster if e.fir_code}),
    )
    starts = [e.valid_from for e in cluster if e.valid_from]
    ends = [e.valid_to for e in cluster if e.valid_to]
    group.window_from = min(starts) if starts else None
    group.window_to = max(ends) if ends else None
    group.confidence_level = min(
        (e.confidence_level for e in cluster), key=CONFIDENCE_LEVELS.index
    )
    group.manual_override = any(e.manual_override for e in cluster)
    group.kind = (
        KIND_REENTRY if any(e.kind == KIND_REENTRY for e in cluster) else KIND_LAUNCH
    )
    group.notam_ids = [
        mark_id(e.notam_id, e.manual_override)
        for e in cluster
        if mark_id(e.notam_id, e.manual_override) not in []
    ]
    seen_ids: List[str] = []
    for e in cluster:
        marked = mark_id(e.notam_id, e.manual_override)
        if marked not in seen_ids:
            seen_ids.append(marked)
    group.notam_ids = seen_ids

    if len(cluster) == 1:
        # Einzelnes NOTAM: die bereits getroffene Zuordnung bleibt unveraendert.
        event = cluster[0]
        group.nation = event.nation
        group.spaceport_code = event.spaceport_code
        group.spaceport_name = event.spaceport_name
        group.spaceport_lat = event.spaceport_lat
        group.spaceport_lon = event.spaceport_lon
        group.azimuth_deg = event.azimuth_deg
        group.inclination_deg = event.inclination_deg
        group.orbit_type = event.orbit_type
        group.max_range_km = event.distance_km
        group.reliability = event.reliability
        group.kind = event.kind
        return group

    zones = [(e.centroid_lat, e.centroid_lon) for e in cluster]
    nations = _group_nations(cluster)
    selection = _select_spaceport_for_zones(
        zones, spaceports, nations, _group_hint(cluster)
    )
    if selection is None:
        return None
    port, spread, azimuths, distances = selection

    if not any(e.passes_confidence or e.manual_override for e in cluster):
        return None

    # Eine Gruppe darf die Nation nur weitergeben, wenn mindestens ein Mitglied
    # sie gesichert hat - durch Nennung im Text oder durch eine FIR im Gebiet
    # der Startnation selbst. Sonst wuerden sich zwei gleichermassen
    # mehrdeutige Meldungen gegenseitig "bestaetigen" (zwei britische
    # Militaergebiete ergaeben so einen russischen Start).
    if not any((not e.requires_group) or e.manual_override for e in cluster):
        return None

    for event, azimuth, distance in zip(cluster, azimuths, distances):
        event.spaceport_code = str(port["Kurzel"])
        event.spaceport_name = str(port["Name"])
        event.spaceport_lat = float(port["Latitude"])
        event.spaceport_lon = float(port["Longitude"])
        event.nation = str(port["Land"])
        event.distance_km = surface_distance_km(
            event.spaceport_lat, event.spaceport_lon, event.centroid_lat, event.centroid_lon
        )
        event.azimuth_deg = azimuth
        event.inclination_deg = estimate_inclination_deg(event.spaceport_lat, azimuth)
        event.orbit_type = classify_orbit(event.inclination_deg)
        event.reliability = zone_reliability(event.distance_km, event.kind)
        event.status = "OK"
        event.review_reason = ""
        event.requires_group = False

    group.nation = str(port["Land"])
    group.spaceport_code = str(port["Kurzel"])
    group.spaceport_name = str(port["Name"])
    group.spaceport_lat = float(port["Latitude"])
    group.spaceport_lon = float(port["Longitude"])
    group.azimuth_deg = _circular_mean(azimuths)
    group.azimuth_spread_deg = spread
    group.inclination_deg = estimate_inclination_deg(group.spaceport_lat, group.azimuth_deg)
    group.orbit_type = classify_orbit(group.inclination_deg)
    group.max_range_km = max(distances)
    # Massgeblich ist die naechstgelegene Zone: sie bestimmt den Azimut am
    # zuverlaessigsten, die fernen Zonen bestaetigen ihn nur. Liegen die Zonen
    # dagegen in voellig verschiedene Richtungen, beschreibt der Mittelwert
    # keine Bahn mehr - das muss sichtbar werden.
    group.reliability = zone_reliability(
        min(distances), group.kind, _angular_spread(azimuths)
    )
    return group


def _drop_duplicate_events(
    events: Sequence[LaunchEvent],
) -> Tuple[List[LaunchEvent], int]:
    """
    Entfernt mehrfach gelistete NOTAMs.

    Behoerden-Exporte fuehren dasselbe NOTAM haeufig einmal je betroffener FIR
    auf. Fuer die Auswertung ist das eine einzige Sperrzone - ohne diesen
    Schritt zaehlt die Statistik sie mehrfach und die Gruppierung sieht
    scheinbar zusaetzliche Zonen auf derselben Bahn.
    """
    kept: List[LaunchEvent] = []
    seen: List[Tuple[str, Optional[float], Optional[float]]] = []
    removed = 0
    for event in events:
        key = (
            event.notam_id,
            round(event.centroid_lat, 3) if event.centroid_lat is not None else None,
            round(event.centroid_lon, 3) if event.centroid_lon is not None else None,
        )
        if key in seen:
            removed += 1
            continue
        seen.append(key)
        kept.append(event)
    return kept, removed


def analyze_notams(
    notams: pd.DataFrame,
    spaceports: pd.DataFrame,
    firs: pd.DataFrame,
    min_confidence: str = "MITTEL",
    confirmed_keys: Optional[Set[str]] = None,
    rejected_keys: Optional[Set[str]] = None,
) -> Tuple[List[LaunchEvent], Dict[str, Any]]:
    """
    Vollstaendige Auswertung einer NOTAM-Tabelle.

    Rueckgabe: Liste der Events (Status OK oder REVIEW) sowie eine Statistik
    ueber den Verarbeitungslauf; ``stats["groups"]`` enthaelt die zu Starts
    zusammengefassten Events.
    """
    mapping = map_notam_columns(notams)
    events: List[LaunchEvent] = []
    stats: Dict[str, Any] = {"rows": int(len(notams)), "no_trigger": 0, "mapping": mapping}
    manual_seq = 0
    confirmed = set(confirmed_keys or ())
    rejected = set(rejected_keys or ())

    for idx, row in notams.iterrows():
        text = row_to_text(row, mapping["text"])
        items = extract_items(text)
        triggers = detect_triggers(text, items)
        if not triggers:
            stats["no_trigger"] += 1
            continue

        source = SOURCE_IMPORT
        if SOURCE_COLUMN in row.index and pd.notna(row[SOURCE_COLUMN]):
            source = str(row[SOURCE_COLUMN])

        notam_id = ""
        if mapping["id"] and mapping["id"] in row.index and pd.notna(row[mapping["id"]]):
            notam_id = str(row[mapping["id"]]).strip()
        if not notam_id:
            navarea = RE_NAVAREA_ID.search(text.upper())
            match = RE_NOTAM_ID.search(text.upper())
            if navarea:
                notam_id = "NAVAREA {} {}".format(navarea.group(1), navarea.group(2))
            elif match:
                notam_id = match.group(1)
            elif source == SOURCE_MANUAL:
                # Freitext ohne Kennung bekommt eine sprechende laufende Nummer.
                manual_seq += 1
                notam_id = "MANUELL-{:02d}".format(manual_seq)
            else:
                notam_id = "ROW-{}".format(idx)

        key = event_key(text)
        is_confirmed = key in confirmed
        event = LaunchEvent(
            row_index=int(idx),
            notam_id=notam_id,
            raw_text=text,
            source=source,
            triggers=triggers,
            altitude_profile=extract_altitude_profile(text, items),
            key=key,
            manual_override=is_confirmed,
        )

        event.nation_hint, event.nation_evidence = detect_nation_hint(text)
        event.spaceport_hint, event.spaceport_evidence = detect_spaceport_hint(text)
        event.kind = classify_event_kind(text)
        foreign = detect_foreign_operator(text)

        # --- Zeitfenster -------------------------------------------------- #
        start_raw = row[mapping["start"]] if mapping["start"] in row.index else None
        end_raw = row[mapping["end"]] if mapping["end"] in row.index else None
        event.valid_from = parse_notam_datetime(start_raw) or parse_notam_datetime(
            items.get("B")
        )
        event.valid_to = parse_notam_datetime(end_raw) or parse_notam_datetime(items.get("C"))
        if event.valid_from is None and event.valid_to is None:
            # Maritime Warnungen tragen den Zeitraum im Fliesstext.
            event.valid_from, event.valid_to = extract_navarea_period(text)

        # Das Scoring braucht das Zeitfenster: die Dauer eines Gefahrengebiets
        # unterscheidet ein Startfenster von einem Dauer-Sperrgebiet.
        (
            event.confidence_score,
            event.confidence_level,
            event.confidence_notes,
        ) = score_confidence(text, triggers, items, event.valid_from, event.valid_to)
        allowed = (
            CONFIDENCE_LEVELS.index(min_confidence)
            if min_confidence in CONFIDENCE_LEVELS
            else 1
        )
        event.passes_confidence = (
            CONFIDENCE_LEVELS.index(event.confidence_level) <= allowed
        )

        # --- Geometrie ----------------------------------------------------- #
        # Das E-Item beschreibt die eigentliche Sperrzone; die Q-Line enthaelt
        # nur den Bezugspunkt und wuerde das Polygon verfaelschen.
        geometry_text = items.get("E") or text
        event.zones = extract_zones(geometry_text)
        if not event.zones:
            event.zones = extract_zones(text)
        if not event.zones:
            # Letzter Ausweg: der Bezugspunkt der Q-Line. Ungenauer als das
            # E-Item, aber besser als das NOTAM ganz zu verlieren.
            fallback = extract_qline_point(items.get("Q") or text)
            if fallback:
                event.zones = [[(fallback[0], fallback[1])]]
                event.radius_km = event.radius_km or fallback[2]
                event.assignment_note = (
                    "Zone aus dem Bezugspunkt der Q-Line abgeleitet - das NOTAM "
                    "nennt keine Gebietsgrenzen."
                )
        event.coordinates = [c for zone in event.zones for c in zone]
        event.radius_km = (
            extract_radius_km(geometry_text)
            or extract_radius_km(text)
            or event.radius_km  # ggf. aus dem Q-Line-Rueckfall
        )
        centroid: Optional[Tuple[float, float]] = None
        if event.coordinates:
            centroid = polygon_centroid(event.coordinates)
            event.centroid_lat, event.centroid_lon = centroid

        # --- FIR ----------------------------------------------------------- #
        fir_hint = row[mapping["fir"]] if mapping["fir"] in row.index else None
        fir_row, method = _find_fir(text, fir_hint, firs, centroid)
        event.fir_match_method = method
        nations: List[str] = []
        if fir_row is not None:
            event.fir_code = str(fir_row["ICAO Code"])
            event.fir_name = str(fir_row["Betroffene Region / FIR Name"])
            event.fir_country = str(fir_row["Land"]).strip()
            nations = list(fir_row["Nationen"])
        event.candidate_nations = list(nations)

        # --- Plausibilitaet / Review --------------------------------------- #
        if foreign and not event.nation_hint and not is_confirmed:
            event.status = "REVIEW"
            event.review_reason = "Betreiber ausserhalb der Zielnationen: {}".format(
                ", ".join(foreign[:3])
            )
            events.append(event)
            continue
        if centroid is None:
            if is_confirmed:
                # Eine Person hat das NOTAM als Start bestaetigt. Ohne
                # Koordinaten laesst sich keine Bahn berechnen, das Event wird
                # aber gefuehrt statt verworfen.
                event.status = "OK"
                event.review_reason = ""
                event.assignment_note = (
                    "Manuell als Start bestaetigt. Ohne Koordinaten im Text ist "
                    "keine Bahnabschaetzung moeglich."
                )
                events.append(event)
                continue
            event.status = "REVIEW"
            event.review_reason = "Keine verwertbaren Koordinaten im NOTAM-Text gefunden."
            events.append(event)
            continue
        if fir_row is None and is_confirmed:
            # Bestaetigt, aber ohne FIR: die Nation ergibt sich aus der Geometrie.
            nations = list(TARGET_NATIONS)
            event.candidate_nations = list(nations)
        elif fir_row is None:
            event.status = "REVIEW"
            if (
                method == "-" or method.startswith("Zu weit")
            ) and event.confidence_level in ("HOCH", "MITTEL"):
                # Maritime Warnungen und Meldungen ausserhalb jeder erfassten FIR
                # tragen die Nation nicht in der Kennung. Sie werden nicht
                # verworfen, sondern koennen ueber die Start-Gruppierung einem
                # Start zugeordnet werden - allein bleiben sie im Review.
                event.requires_group = True
                event.candidate_nations = list(TARGET_NATIONS)
                if event.nation_hint in TARGET_NATIONS:
                    event.candidate_nations = [event.nation_hint]
                event.review_reason = (
                    "Keine FIR-Zuordnung - nur ueber die Zuordnung zu einem Start "
                    "mit weiteren NOTAMs aufloesbar."
                )
                events.append(event)
                continue
            if method.startswith("Ausserhalb"):
                event.review_reason = (
                    "NOTAM gehoert zu FIR {} - keine FIR der Zielnationen.".format(
                        method.split(": ", 1)[-1]
                    )
                )
            elif method.startswith("Zu weit"):
                event.review_reason = "Sperrzone liegt {}.".format(method.lower())
            else:
                event.review_reason = "Keine FIR-Zuordnung moeglich (Referenzdaten pruefen)."
            events.append(event)
            continue
        if not any(n in TARGET_NATIONS for n in nations) and not is_confirmed:
            event.status = "REVIEW"
            event.review_reason = "FIR {} gehoert zu keiner Zielnation.".format(event.fir_code)
            events.append(event)
            continue

        if event.nation_hint in TARGET_NATIONS:
            nations = [event.nation_hint]
            event.candidate_nations = list(nations)
        elif is_confirmed:
            # Geprueft und bestaetigt: die Nation waehlt die Geometrie unter
            # allen Kandidaten der FIR.
            nations = [n for n in nations if n in TARGET_NATIONS] or list(TARGET_NATIONS)
            event.candidate_nations = list(nations)
        elif event.fir_country not in TARGET_NATIONS:
            # Die FIR liegt im Gebiet eines Drittstaats. Dort steht in der
            # Referenz nur, welche Startnation dieses Gebiet ueblicherweise
            # ueberfliegt - ein NOTAM darf ihr aber nicht allein deshalb
            # zugerechnet werden. Norwegen hat mit Andoeya einen eigenen
            # Startplatz; ohne Nennung im Text waere jeder norwegische Start
            # sonst ein russischer.
            event.status = "REVIEW"
            event.requires_group = True
            event.review_reason = (
                "FIR {} liegt in {} - die Startnation ({}) ist dort nur unterstellt "
                "und wird im Text nicht genannt. Nur ueber die Zuordnung zu einem "
                "Start mit weiteren NOTAMs aufloesbar.".format(
                    event.fir_code, event.fir_country or "einem Drittstaat",
                    ", ".join(nations),
                )
            )
            events.append(event)
            continue
        elif len(nations) > 1:
            # Mehrdeutig - aber wenn dieses NOTAM zu einem Start gehoert, dessen
            # andere Meldungen die Nation nennen, wird es darueber aufgeloest.
            event.status = "REVIEW"
            event.requires_group = True
            event.review_reason = (
                "FIR {} deckt mehrere Startnationen ab ({}) und der Text nennt keine - "
                "nur ueber die Zuordnung zu einem Start aufloesbar.".format(
                    event.fir_code, ", ".join(nations)
                )
            )
            events.append(event)
            continue

        if not event.passes_confidence and not is_confirmed:
            event.status = "REVIEW"
            event.review_reason = "Weltraum-Konfidenz {} (Score {}){}".format(
                event.confidence_level,
                event.confidence_score,
                " - " + "; ".join(event.confidence_notes) if event.confidence_notes else "",
            )
            events.append(event)
            continue

        # --- Weltraumbahnhof + Trajektorie ---------------------------------- #
        port, azimuth_plausible, assignment_note = _find_spaceport(
            centroid, spaceports, nations, event.spaceport_hint
        )
        if event.spaceport_evidence:
            assignment_note = (
                "Startplatz aus dem Text abgeleitet ({}). ".format(
                    ", ".join(event.spaceport_evidence[:3])
                )
                + assignment_note
            ).strip()
        if assignment_note:
            event.assignment_note = (
                (event.assignment_note + " " + assignment_note).strip()
                if event.assignment_note
                else assignment_note
            )
        if port is None:
            event.status = "REVIEW"
            event.review_reason = "Kein Weltraumbahnhof fuer {} in der Referenz.".format(
                ", ".join(nations)
            )
            events.append(event)
            continue

        event.spaceport_code = str(port["Kurzel"])
        event.spaceport_name = str(port["Name"])
        event.spaceport_lat = float(port["Latitude"])
        event.spaceport_lon = float(port["Longitude"])
        event.nation = str(port["Land"])
        event.distance_km = surface_distance_km(
            event.spaceport_lat, event.spaceport_lon, centroid[0], centroid[1]
        )

        if event.distance_km < 1.0:
            event.status = "REVIEW"
            event.review_reason = (
                "Sperrzone liegt auf dem Startplatz - kein belastbarer Azimut."
            )
            events.append(event)
            continue

        event.azimuth_deg = initial_bearing_deg(
            event.spaceport_lat, event.spaceport_lon, centroid[0], centroid[1]
        )
        event.inclination_deg = estimate_inclination_deg(
            event.spaceport_lat, event.azimuth_deg
        )
        event.orbit_type = classify_orbit(event.inclination_deg)
        event.reliability = zone_reliability(event.distance_km, event.kind)

        if not azimuth_plausible and is_confirmed:
            event.assignment_note = (
                (event.assignment_note + " ").lstrip()
                + "Achtung: Azimut {:.0f}° weist nach Westen - die Zuordnung des "
                "Startplatzes ist unsicher.".format(event.azimuth_deg)
            )
        elif not azimuth_plausible:
            event.status = "REVIEW"
            event.review_reason = (
                "Kein Startplatz mit moeglicher Startrichtung: Azimut {:.0f}° "
                "weist nach Westen, gegen die Erdrotation.".format(event.azimuth_deg)
            )
            events.append(event)
            continue

        if event.distance_km > MAX_PLAUSIBLE_RANGE_KM:
            event.status = "REVIEW"
            event.review_reason = (
                "Distanz Startplatz-Sperrzone betraegt {:.0f} km - Zuordnung pruefen.".format(
                    event.distance_km
                )
            )
        events.append(event)

    # Manuell in den Review zurueckgestellte NOTAMs: die Entscheidung einer
    # Person sticht die automatische Bewertung, deshalb erst hier - das Event
    # ist dann vollstaendig ausgewertet und im Review mit allen Angaben lesbar.
    for event in events:
        if event.key in rejected and event.status == "OK":
            event.status = "REVIEW"
            event.review_reason = (
                "Manuell aus der Launch-Tabelle in den Review zurückgestellt."
            )
            event.manual_override = False
            event.launch_group = ""

    # Mehrfach gelistete NOTAMs entfernen, dann zu Starts zusammenfassen.
    events, stats["duplicates"] = _drop_duplicate_events(events)
    groups = group_launches(events, spaceports)
    stats["groups"] = groups
    stats["launches"] = sum(1 for g in groups if g.spaceport_code)
    stats["grouped"] = sum(1 for g in groups if g.zone_count > 1)
    stats["events"] = len(events)
    stats["min_confidence"] = min_confidence
    stats["manual"] = sum(1 for e in events if e.source == SOURCE_MANUAL)
    stats["confirmed"] = sum(1 for e in events if e.manual_override)
    stats["rejected"] = sum(1 for e in events if e.key in rejected)
    stats["high_confidence"] = sum(1 for e in events if e.confidence_level == "HOCH")
    stats["ok"] = sum(1 for e in events if e.status == "OK")
    stats["review"] = sum(1 for e in events if e.status == "REVIEW")
    return events, stats


def events_to_dataframe(events: Sequence[LaunchEvent]) -> pd.DataFrame:
    """Baut die Ergebnistabelle mit den fachlich geforderten Spalten."""
    records: List[Dict[str, Any]] = []
    for e in events:
        records.append(
            {
                "NOTAM ID": mark_id(e.notam_id, e.manual_override),
                "Geprüft": "manuell bestätigt" if e.manual_override else "-",
                "Art": e.kind,
                "Start": e.launch_group or "-",
                "Quelle": e.source,
                "Startnation": e.nation or "-",
                "Weltraumbahnhof": (
                    "{} ({})".format(e.spaceport_name, e.spaceport_code)
                    if e.spaceport_code
                    else "-"
                ),
                "Startfenster (UTC)": e.launch_window,
                "FIR Code": e.fir_code or "-",
                "FIR liegt in": e.fir_country or "-",
                "Höhenprofil": e.altitude_profile,
                "Launch Azimut (°)": (
                    round(e.azimuth_deg, 1) if e.azimuth_deg is not None else np.nan
                ),
                "Est. Inklination (°)": (
                    round(e.inclination_deg, 1) if e.inclination_deg is not None else np.nan
                ),
                "Orbit-Typ": e.orbit_type,
                "Konfidenz": e.confidence_level,
                "Zuverlässigkeit": e.reliability,
                "Nationsbeleg": ", ".join(e.nation_evidence) if e.nation_evidence else "FIR",
                "Distanz (km)": (
                    round(e.distance_km, 1) if e.distance_km is not None else np.nan
                ),
                "Punkte": len(e.coordinates),
                "Status": e.status,
                "Trigger": "; ".join(e.triggers),
                "Hinweis": e.review_reason or e.assignment_note,
                "_row": e.row_index,
                "_from": e.valid_from,
                "_to": e.valid_to,
            }
        )
    columns = [
        "NOTAM ID",
        "Geprüft",
        "Art",
        "Start",
        "Quelle",
        "Startnation",
        "Weltraumbahnhof",
        "Startfenster (UTC)",
        "FIR Code",
        "FIR liegt in",
        "Höhenprofil",
        "Launch Azimut (°)",
        "Est. Inklination (°)",
        "Orbit-Typ",
        "Konfidenz",
        "Zuverlässigkeit",
        "Nationsbeleg",
        "Distanz (km)",
        "Punkte",
        "Status",
        "Trigger",
        "Hinweis",
        "_row",
        "_from",
        "_to",
    ]
    return pd.DataFrame(records, columns=columns)


#: Was der Orbit-Typ praktisch bedeutet - fuer Leser ohne Raumfahrt-Hintergrund.
ORBIT_EXPLANATIONS = {
    "Sonnensynchron (SSO / Polar)": (
        "eine nahezu polare Bahn, die jeden Ort immer zur gleichen Ortszeit "
        "ueberfliegt - typisch fuer Erdbeobachtungs- und Aufklaerungssatelliten"
    ),
    "Hohe Inklination / polnah": (
        "eine stark geneigte Bahn nahe den Polen - typisch fuer Erdbeobachtung "
        "und militaerische Aufklaerung"
    ),
    "Standard LEO / MEO (ISS-/Station-Korridor)": (
        "eine mittlere Bahnneigung, wie sie Raumstationen, bemannte Fluege sowie "
        "Navigations- und Kommunikationssatelliten nutzen"
    ),
    "Aequatorial / Low Inclination (GTO-Transit)": (
        "eine flache, aequatornahe Bahn - meist der Transfer in Richtung "
        "geostationaere Bahn, also Kommunikations- oder Wettersatelliten"
    ),
    "Retrograder Orbit": (
        "eine gegenlaeufige Bahn entgegen der Erddrehung - sehr selten, "
        "die Zuordnung sollte geprueft werden"
    ),
}

#: 16-teilige Kompassrose fuer die Startrichtung in Worten.
_COMPASS = (
    "Norden", "Nordnordost", "Nordost", "Ostnordost",
    "Osten", "Ostsuedost", "Suedost", "Suedsuedost",
    "Sueden", "Suedsuedwest", "Suedwest", "Westsuedwest",
    "Westen", "Westnordwest", "Nordwest", "Nordnordwest",
)


def compass_name(azimuth_deg: Optional[float]) -> str:
    """Wandelt einen Azimut in eine Himmelsrichtung in Worten."""
    if azimuth_deg is None:
        return "unbestimmt"
    return _COMPASS[int((azimuth_deg % 360.0) / 22.5 + 0.5) % 16]


def _format_window_hours(hours: Optional[float]) -> str:
    if hours is None:
        return "unbekannt"
    if hours < 2:
        return "{:.0f} Minuten".format(hours * 60)
    if hours < 48:
        return "{:.1f} Stunden".format(hours)
    return "{:.0f} Tage".format(hours / 24.0)


def describe_launch(group: LaunchGroup, events: Sequence[LaunchEvent]) -> str:
    """
    Formuliert einen Start in Klartext - ohne NOTAM-Fachbegriffe.

    Die Beschreibung nennt nicht nur das Ergebnis, sondern auch, woran es
    erkannt wurde und wie sicher es ist, damit die Auswertung ohne Kenntnis
    des NOTAM-Formats nachvollziehbar bleibt.
    """
    members = [e for e in events if e.row_index in group.row_indices]
    if not members:
        return ""

    lines: List[str] = []
    if group.kind == KIND_REENTRY:
        lines.append(
            "**Was:** Ein Wiedereintritt bzw. eine Splashdown-Zone{}. Zugeordneter "
            "Startplatz: {}.".format(
                " der {}".format(group.nation) if group.nation else "",
                group.spaceport_name or "unbekannt",
            )
        )
    else:
        lines.append(
            "**Was:** Ein Raumfahrtstart{} vom Weltraumbahnhof {}.".format(
                " {}s".format(group.nation) if group.nation else "",
                group.spaceport_name or "unbekannt",
            )
        )
    lines.append("**Wann (UTC):** {}".format(group.launch_window))

    # Woran erkannt
    dauern = [
        (e.valid_to - e.valid_from).total_seconds() / 3600.0
        for e in members
        if e.valid_from and e.valid_to
    ]
    taeglich = [daily_window_hours(extract_items(e.raw_text).get("D")) for e in members]
    taeglich = [t for t in taeglich if t]
    aktiv = min(taeglich) if taeglich else (min(dauern) if dauern else None)
    if aktiv is not None:
        lines.append(
            "**Woran erkannt:** {} Luftraumsperrung(en) von der Erdoberflaeche bis "
            "unbegrenzt nach oben, jeweils nur rund {} aktiv. Eine so hohe Sperrung "
            "fuer so kurze Zeit entsteht praktisch nur bei einem Raketenstart.".format(
                group.zone_count, _format_window_hours(aktiv)
            )
        )
    else:
        lines.append(
            "**Woran erkannt:** {} Luftraumsperrung(en) von der Erdoberflaeche bis "
            "unbegrenzt nach oben. Die Sperrhoehe und der Wortlaut der Meldungen "
            "weisen auf einen Raketenstart hin.".format(group.zone_count)
        )
    lines.append("**Zugrunde liegende Meldungen:** {}".format(", ".join(group.notam_ids)))

    # Nation
    belege = sorted({b for e in members for b in e.nation_evidence})
    if belege:
        lines.append(
            "**Woher die Nation:** Im Meldungstext genannt ({}).".format(", ".join(belege[:4]))
        )
    else:
        lines.append(
            "**Woher die Nation:** Aus der betroffenen Luftraumregion abgeleitet, "
            "nicht im Text genannt - im Zweifel am Originaltext pruefen."
        )

    # Startplatz
    if group.zone_count > 1:
        lines.append(
            "**Warum dieser Startplatz:** Von {} aus liegen alle {} Sperrzonen in "
            "derselben Richtung (Abweichung {:.1f}°). Kein anderer Startplatz "
            "erklaert alle Zonen gemeinsam.".format(
                group.spaceport_code, group.zone_count, group.azimuth_spread_deg
            )
        )
    else:
        hinweis = next((e.assignment_note for e in members if e.assignment_note), "")
        lines.append(
            "**Warum dieser Startplatz:** Naechstgelegener Startplatz der Nation mit "
            "moeglicher Startrichtung.{}".format(" " + hinweis if hinweis else "")
        )

    # Folgerung
    if group.kind == KIND_REENTRY:
        lines.append(
            "**Was daraus folgt:** Bei einem Wiedereintritt kommt das Objekt aus der "
            "Umlaufbahn zurueck. Die Richtung vom Startplatz zur Sperrzone sagt deshalb "
            "nichts ueber die Bahnlage aus - die angegebenen Werte fuer Azimut und "
            "Bahnneigung sind hier nicht aussagekraeftig."
        )
    elif group.azimuth_deg is not None and group.inclination_deg is not None:
        erklaerung = ORBIT_EXPLANATIONS.get(group.orbit_type, "")
        lines.append(
            "**Was daraus folgt:** Die Rakete fliegt Richtung {} ({:.0f}°). Daraus "
            "ergibt sich eine Bahnneigung von rund {:.0f}° - {}{}.".format(
                compass_name(group.azimuth_deg),
                group.azimuth_deg,
                group.inclination_deg,
                group.orbit_type,
                ", " + erklaerung if erklaerung else "",
            )
        )

    # Sicherheit
    sicher = {
        "hoch": "Die naechste Sperrzone liegt nah am Startplatz, die Richtung ist gut bestimmt.",
        "mittel": "Die Sperrzonen liegen weiter entfernt; die Bahnneigung ist eine Naeherung.",
        "gering": (
            "Die Sperrzonen liegen sehr weit entfernt (Wiedereintritts- oder "
            "Deorbit-Gebiete). Startplatz und Bahnneigung sind dort nur grob bestimmbar."
        ),
    }.get(group.reliability, "")
    lines.append(
        "**Wie belastbar:** {} - {} {}".format(
            group.reliability,
            sicher,
            "Die Bahnneigung ist eine Naeherung: der Beitrag der Erddrehung ist "
            "nicht eingerechnet.",
        )
    )
    return "\n\n".join(lines)


def groups_to_dataframe(groups: Sequence[LaunchGroup]) -> pd.DataFrame:
    """Ergebnistabelle auf Start-Ebene: eine Zeile je Start statt je NOTAM."""
    records: List[Dict[str, Any]] = []
    for g in groups:
        records.append(
            {
                "Start": g.group_id,
                "Art": g.kind,
                "Startnation": g.nation or "-",
                "Weltraumbahnhof": (
                    "{} ({})".format(g.spaceport_name, g.spaceport_code)
                    if g.spaceport_code
                    else "-"
                ),
                "Startfenster (UTC)": g.launch_window,
                "Sperrzonen": g.zone_count,
                "NOTAMs": ", ".join(g.notam_ids),
                "Geprüft": "manuell bestätigt" if g.manual_override else "-",
                "FIR": ", ".join(g.fir_codes) if g.fir_codes else "-",
                "Launch Azimut (°)": (
                    round(g.azimuth_deg, 1) if g.azimuth_deg is not None else np.nan
                ),
                "Est. Inklination (°)": (
                    round(g.inclination_deg, 1) if g.inclination_deg is not None else np.nan
                ),
                "Orbit-Typ": g.orbit_type,
                "Reichweite (km)": (
                    round(g.max_range_km, 1) if g.max_range_km is not None else np.nan
                ),
                "Azimut-Streuung (°)": round(g.azimuth_spread_deg, 1),
                "Konfidenz": g.confidence_level,
                "Zuverlässigkeit": g.reliability,
                "Quelle": ", ".join(g.sources),
            }
        )
    columns = [
        "Start",
        "Art",
        "Startnation",
        "Weltraumbahnhof",
        "Startfenster (UTC)",
        "Sperrzonen",
        "NOTAMs",
        "Geprüft",
        "FIR",
        "Launch Azimut (°)",
        "Est. Inklination (°)",
        "Orbit-Typ",
        "Reichweite (km)",
        "Azimut-Streuung (°)",
        "Konfidenz",
        "Zuverlässigkeit",
        "Quelle",
    ]
    return pd.DataFrame(records, columns=columns)


def group_to_export_dict(g: LaunchGroup) -> Dict[str, Any]:
    """JSON-taugliche Darstellung eines Starts."""
    data = asdict(g)
    data["window_from"] = g.window_from.isoformat() if g.window_from else None
    data["window_to"] = g.window_to.isoformat() if g.window_to else None
    data["launch_window"] = g.launch_window
    data["zone_count"] = g.zone_count
    for key in ("azimuth_deg", "inclination_deg", "max_range_km", "azimuth_spread_deg"):
        if data.get(key) is not None:
            data[key] = round(float(data[key]), 3)
    return data


def event_to_export_dict(e: LaunchEvent) -> Dict[str, Any]:
    """JSON-taugliche Darstellung eines Events."""
    data = asdict(e)
    data["valid_from"] = e.valid_from.isoformat() if e.valid_from else None
    data["valid_to"] = e.valid_to.isoformat() if e.valid_to else None
    data["launch_window"] = e.launch_window
    data["coordinates"] = [[round(lat, 6), round(lon, 6)] for lat, lon in e.coordinates]
    for key in ("azimuth_deg", "inclination_deg", "distance_km", "radius_km"):
        if data.get(key) is not None:
            data[key] = round(float(data[key]), 3)
    return data


def manual_entries_to_dataframe(
    entries: Sequence[Dict[str, Any]], text_column: str = "NOTAM Text"
) -> pd.DataFrame:
    """
    Baut aus den manuell eingefuegten NOTAMs eine Tabelle im Format des Imports.

    ``text_column`` wird auf die Volltextspalte der hochgeladenen Datei gesetzt,
    damit beide Quellen anschliessend identisch verarbeitet werden.
    """
    rows: List[Dict[str, Any]] = []
    for entry in entries:
        rows.append(
            {
                text_column: entry.get("text", ""),
                "Erfasst (UTC)": entry.get("added", ""),
                SOURCE_COLUMN: SOURCE_MANUAL,
            }
        )
    return pd.DataFrame(rows)


def combine_sources(
    imported: Optional[pd.DataFrame], manual: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """Fuehrt importierte und manuell eingefuegte NOTAMs zu einer Tabelle zusammen."""
    frames: List[pd.DataFrame] = []
    if imported is not None and not imported.empty:
        df = imported.copy()
        if SOURCE_COLUMN not in df.columns:
            df[SOURCE_COLUMN] = SOURCE_IMPORT
        frames.append(df)
    if manual is not None and not manual.empty:
        frames.append(manual)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False)


# --------------------------------------------------------------------------- #
# Demo-Datensatz (zum Testen ohne eigenen Upload)
# --------------------------------------------------------------------------- #
def build_demo_notams() -> pd.DataFrame:
    """Realistisch formatierte Beispiel-NOTAMs inkl. eines Review-Falls."""
    rows = [
        {
            "NOTAM ID": "A1234/25",
            "FIR": "ZJSA",
            "Valid From": "2509210130",
            "Valid To": "2509210430",
            "NOTAM Text": (
                "A1234/25 NOTAMN Q) ZJSA/QRTCA/IV/BO/W/000/999/1930N11100E050 "
                "A) ZJSA B) 2509210130 C) 2509210430 "
                "E) TEMPORARY RESTRICTED AREA ESTABLISHED FOR SPACE LAUNCH ACTIVITY. "
                "FALLING DEBRIS EXPECTED WITHIN AREA BOUNDED BY "
                "1936N11057E 1948N11212E 1902N11230E 1850N11115E BACK TO START. "
                "F) SFC G) UNL"
            ),
        },
        {
            "NOTAM ID": "B0456/25",
            "FIR": "ZWUQ",
            "Valid From": "2509210600",
            "Valid To": "2509210900",
            "NOTAM Text": (
                "B0456/25 NOTAMN Q) ZWUQ/QRDCA/IV/BO/W/000/999/4100N09930E100 "
                "A) ZWUQ B) 2509210600 C) 2509210900 "
                "E) DANGER AREA ACTIVATED DUE TO ROCKET LAUNCH. DEBRIS DROP ZONE "
                "WITHIN 50NM RADIUS OF 4012N09948E. SFC/UNL"
            ),
        },
        {
            "NOTAM ID": "C0777/25",
            "FIR": "UHPP",
            "Valid From": "2509211200",
            "Valid To": "2509211500",
            "NOTAM Text": (
                "C0777/25 NOTAMN Q) UHPP/QRTCA/IV/BO/W/000/999 "
                "A) UHPP B) 2509211200 C) 2509211500 "
                "E) TEMPORARY DANGER AREA DUE TO SPACE LAUNCH FROM VOSTOCHNY. "
                "AREA BOUNDED BY 5330N15230E 5410N15410E 5250N15500E 5210N15320E. "
                "GND/UNL"
            ),
        },
        {
            "NOTAM ID": "V0099/25",
            "FIR": "VOMF",
            "Valid From": "2509210330",
            "Valid To": "2509210530",
            "NOTAM Text": (
                "V0099/25 NOTAMN A) VOMF B) 2509210330 C) 2509210530 "
                "E) RESTRICTED AREA ACTIVE FOR LAUNCH VEHICLE OPERATIONS FROM SDSC SHAR. "
                "STAGE IMPACT ZONE BOUNDED BY 12°30'N 82°10'E 11°50'N 83°20'E "
                "11°10'N 82°40'E. F) SFC G) UNL"
            ),
        },
        {
            "NOTAM ID": "K0021/25",
            "FIR": "ZKKP",
            "Valid From": "2509212200",
            "Valid To": "2509220200",
            "NOTAM Text": (
                "K0021/25 NOTAMN Q) ZKKP/QRDCA/IV/BO/W/000/999 A) ZKKP "
                "B) 2509212200 C) 2509220200 "
                "E) DANGER AREA FOR SPACE LAUNCH. DEBRIS AREA 3520N12430E "
                "3450N12510E 3410N12420E 3440N12340E. SFC/UNLIMITED"
            ),
        },
        {
            "NOTAM ID": "R0555/25",
            "FIR": "OIIX",
            "Valid From": "2509210800",
            "Valid To": "2509211000",
            "NOTAM Text": (
                "R0555/25 NOTAMN A) OIIX B) 2509210800 C) 2509211000 "
                "E) DANGER AREA ACTIVATED FOR ROCKET LAUNCH. COORDINATES NOT PUBLISHED. "
                "SFC/UNL"
            ),
        },
        {
            "NOTAM ID": "Z9999/25",
            "FIR": "EDGG",
            "Valid From": "2509210900",
            "Valid To": "2509211100",
            "NOTAM Text": (
                "Z9999/25 NOTAMN A) EDGG B) 2509210900 C) 2509211100 "
                "E) CRANE ERECTED 150M AGL 4959N00832E. F) SFC G) 500FT AGL"
            ),
        },
    ]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Kartendarstellung
# --------------------------------------------------------------------------- #
NATION_COLORS = {
    "China": "#d7263d",
    "Russland": "#1b998b",
    "Indien": "#f46036",
    "Iran": "#2e294e",
    "Nordkorea": "#8a1c7c",
    "USA": "#1f6feb",
}


def _view_for(points: Sequence[Tuple[float, float]]) -> Tuple[List[float], int]:
    """Bestimmt Kartenmittelpunkt und passende Zoomstufe fuer eine Punktmenge."""
    if not points:
        return [30.0, 100.0], 3
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)
    center = [(south + north) / 2.0, (west + east) / 2.0]
    lat_span = max(north - south, 0.05)
    lon_span = max(east - west, 0.05)
    # Grobe Umrechnung der Ausdehnung in eine Zoomstufe (Web-Mercator-Kacheln).
    zoom = min(math.log2(360.0 / lon_span), math.log2(170.0 / lat_span))
    return center, int(max(2, min(9, math.floor(zoom))))


def build_event_map(events: Sequence[LaunchEvent], trail_factor: float = 2.5) -> "folium.Map":
    """Erzeugt eine folium-Karte mit Startplatz, Sperrzone und Flugbahn."""
    plotted = [e for e in events if e.centroid_lat is not None]

    # Alle darzustellenden Punkte vorab sammeln: Leaflets fitBounds laeuft im
    # Streamlit-iframe teilweise vor der Groessenberechnung und zoomt dann zu
    # weit hinein. Zentrum und Zoomstufe werden deshalb selbst bestimmt.
    extent: List[Tuple[float, float]] = []
    for event in plotted:
        extent.extend(unwrap_longitudes(event.coordinates))
        extent.append((event.centroid_lat, event.centroid_lon))
        if event.spaceport_lat is not None:
            extent.append((event.spaceport_lat, event.spaceport_lon))
    center, zoom = _view_for(extent)

    fmap = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    bounds: List[List[float]] = []

    for event in plotted:
        color = NATION_COLORS.get(event.nation or "", "#444444")
        is_manual = event.source == SOURCE_MANUAL
        label = "{}{} - {}".format(
            event.notam_id, " (manuell)" if is_manual else "", event.nation or "unbestimmt"
        )

        # Ein NOTAM kann mehrere getrennte Gebiete beschreiben - jedes bekommt
        # ein eigenes Polygon, sonst entsteht ein Zickzack quer ueber die Karte.
        areas = event.zones or ([event.coordinates] if event.coordinates else [])
        for number, area in enumerate(areas, start=1):
            if len(area) < 3:
                continue
            poly = unwrap_longitudes(area)
            label_area = (
                "{} (Gebiet {}/{})".format(event.notam_id, number, len(areas))
                if len(areas) > 1
                else event.notam_id
            )
            folium.Polygon(
                locations=[[lat, lon] for lat, lon in poly],
                color=color,
                weight=3 if is_manual else 2,
                dash_array="6,4" if is_manual else None,
                fill=True,
                fill_opacity=0.25,
                tooltip=label_area,
                popup=folium.Popup(
                    "<b>{}</b><br>Sperrzone ({} Punkte)<br>{}".format(
                        label_area, len(poly), event.altitude_profile
                    ),
                    max_width=320,
                ),
            ).add_to(fmap)
            bounds.extend([[lat, lon] for lat, lon in poly])

        if event.radius_km:
            folium.Circle(
                location=[event.centroid_lat, event.centroid_lon],
                radius=event.radius_km * 1000.0,
                color=color,
                weight=2,
                fill=True,
                fill_opacity=0.15,
                popup="{}: Radius {:.1f} km".format(event.notam_id, event.radius_km),
            ).add_to(fmap)

        folium.CircleMarker(
            location=[event.centroid_lat, event.centroid_lon],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(
                "<b>{}</b><br>Start: {}<br>Quelle: {}<br>Centroid Sperrzone<br>{:.4f}, {:.4f}<br>{}".format(
                    event.notam_id,
                    event.launch_group or "-",
                    event.source,
                    event.centroid_lat,
                    event.centroid_lon,
                    event.orbit_type,
                ),
                max_width=320,
            ),
            tooltip="Sperrzone {}{}".format(
                label, " " + MANUAL_MARK + " manuell bestaetigt" if event.manual_override else ""
            ),
        ).add_to(fmap)
        bounds.append([event.centroid_lat, event.centroid_lon])

        if is_manual:
            # Manuell eingefuegte NOTAMs bekommen eine eigene Markierung, damit
            # sie in der Karte von den importierten unterscheidbar bleiben.
            folium.Marker(
                location=[event.centroid_lat, event.centroid_lon],
                icon=folium.Icon(color="purple", icon="edit", prefix="fa"),
                tooltip="{} - manuell hinzugefuegt".format(event.notam_id),
            ).add_to(fmap)

    # Startplatz und Flugbahn werden je Start gezeichnet, nicht je NOTAM:
    # mehrere Sperrzonen eines Starts liegen auf einer gemeinsamen Bahn.
    per_launch: Dict[str, List[LaunchEvent]] = {}
    for event in plotted:
        if event.spaceport_lat is None or event.azimuth_deg is None:
            continue
        per_launch.setdefault(
            event.launch_group or "EVENT-{}".format(event.row_index), []
        ).append(event)

    for group_id, members in per_launch.items():
        lead = members[0]
        color = NATION_COLORS.get(lead.nation or "", "#444444")
        azimuth = _circular_mean([e.azimuth_deg for e in members])
        inclination = estimate_inclination_deg(lead.spaceport_lat, azimuth)
        reach = max((e.distance_km or 0.0) for e in members)
        zones = ", ".join(e.notam_id for e in members)

        folium.Marker(
            location=[lead.spaceport_lat, lead.spaceport_lon],
            icon=folium.Icon(color="darkred", icon="rocket", prefix="fa"),
            tooltip="{} ({}) - {}".format(lead.spaceport_name, lead.spaceport_code, group_id),
            popup=folium.Popup(
                "<b>{}</b><br>{}<br>{}<br>Sperrzonen: {}<br>"
                "Azimut: {:.1f}&deg;<br>Inklination: {:.1f}&deg;<br>{}".format(
                    lead.spaceport_name,
                    lead.spaceport_code,
                    group_id,
                    zones,
                    azimuth,
                    inclination,
                    classify_orbit(inclination),
                ),
                max_width=340,
            ),
        ).add_to(fmap)
        bounds.append([lead.spaceport_lat, lead.spaceport_lon])

        path = great_circle_path(
            lead.spaceport_lat,
            lead.spaceport_lon,
            azimuth,
            max(reach * trail_factor, 800.0),
        )
        folium.PolyLine(
            locations=[[lat, lon] for lat, lon in path],
            color=color,
            weight=3,
            opacity=0.85,
            dash_array="8,6",
            tooltip="{} - {} Zone(n) - Azimut {:.1f} Grad - {}".format(
                group_id, len(members), azimuth, classify_orbit(inclination)
            ),
        ).add_to(fmap)

    return fmap


# --------------------------------------------------------------------------- #
# Streamlit UI
# --------------------------------------------------------------------------- #
def _persist_workspace() -> None:
    """Sichert den Arbeitsstand nach jeder Aenderung."""
    save_workspace(
        st.session_state.get("manual_notams", []),
        st.session_state.get("confirmed_launches", set()),
        st.session_state.get("hidden_events", set()),
        st.session_state.get("rejected_launches", set()),
    )


def _add_manual_notams() -> None:
    """Uebernimmt den Inhalt des Freitextfelds als manuelle NOTAMs."""
    raw = st.session_state.get("manual_input", "")
    chunks = split_pasted_notams(raw)
    stamp = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%MZ")
    for chunk in chunks:
        st.session_state["manual_notams"].append({"text": chunk, "added": stamp})
    st.session_state["manual_feedback"] = len(chunks)
    st.session_state["manual_input"] = ""
    _persist_workspace()


def _remove_manual(index: int) -> None:
    """Entfernt einen einzelnen manuellen Eintrag."""
    items = st.session_state.get("manual_notams", [])
    if 0 <= index < len(items):
        items.pop(index)
    st.session_state["manual_feedback"] = None
    _persist_workspace()


def _clear_manual() -> None:
    """Verwirft alle manuellen Eintraege."""
    st.session_state["manual_notams"] = []
    st.session_state["manual_feedback"] = None
    _persist_workspace()


SPACEPORT_EXPORT_COLUMNS = ("Kurzel", "Latitude", "Longitude", "Name", "Land")
FIR_EXPORT_COLUMNS = (
    "ICAO Code", "Latitude", "Longitude", "Betroffene Region / FIR Name",
    "Land", "Zugehörige Startnation",
)
VEHICLE_EXPORT_COLUMNS = ("Land", "Name", "Alternativname englisch", "Abkürzung")


def _push_undo(path: Path, label: str) -> None:
    """Sichert den Dateistand vor einer Aenderung, damit sie ruecknehmbar bleibt."""
    try:
        inhalt = path.read_text(encoding="utf-8")
    except OSError:
        return
    stapel = st.session_state.setdefault("ref_undo", [])
    stapel.append({"pfad": str(path), "inhalt": inhalt, "label": label})
    del stapel[:-UNDO_LIMIT]


def _undo_reference() -> Optional[str]:
    """Nimmt die letzte Referenzaenderung zurueck."""
    stapel = st.session_state.get("ref_undo", [])
    if not stapel:
        return None
    letzter = stapel.pop()
    try:
        Path(letzter["pfad"]).write_text(letzter["inhalt"], encoding="utf-8")
    except OSError:
        return None
    return letzter["label"]


def _write_reference(
    path: Path, df: pd.DataFrame, columns: Sequence[str], label: str
) -> None:
    """Sichert den alten Stand und schreibt die Tabelle in die Projektdatei."""
    _push_undo(path, label)
    persist_reference(path, df, columns)
    st.session_state["ref_flash"] = label


def _remove_reference_row(
    path: Path, df: pd.DataFrame, columns: Sequence[str], key_column: str, key: str
) -> None:
    """Entfernt einen Eintrag dauerhaft aus der Referenzdatei."""
    rest = df[df[key_column].astype(str) != key]
    _write_reference(
        path, rest, columns,
        "{} entfernt - dauerhaft aus {} gestrichen.".format(key, path.name),
    )


def _add_reference_row(
    path: Path,
    df: pd.DataFrame,
    columns: Sequence[str],
    key_column: str,
    zeile: Dict[str, Any],
) -> None:
    """Fuegt einen Eintrag dauerhaft zur Referenzdatei hinzu."""
    key = str(zeile[key_column])
    ohne = df[df[key_column].astype(str) != key]
    erweitert = pd.concat([ohne, pd.DataFrame([zeile])], ignore_index=True)
    _write_reference(
        path, erweitert, columns,
        "{} gespeichert - steht ab sofort in {}.".format(key, path.name),
    )


def _reference_row(werte: Sequence[str], breiten: Sequence[float], header: bool = False):
    """Zeichnet eine Tabellenzeile und liefert die Spalte fuer die Schaltflaeche."""
    cols = st.columns(list(breiten))
    for col, wert in zip(cols, werte):
        col.markdown(("**{}**" if header else "{}").format(wert))
    return cols[-1]


def _spaceport_editor(spaceports: pd.DataFrame) -> None:
    """Tabelle der Weltraumbahnhoefe mit Entfernen- und Hinzufuegen-Funktion."""
    suche = st.text_input(
        "Suchen", key="sp_search", placeholder="Kürzel, Name oder Land …"
    ).strip().upper()
    zeilen = spaceports
    if suche:
        maske = (
            zeilen["Kurzel"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Name"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Land"].astype(str).str.upper().str.contains(suche, regex=False)
        )
        zeilen = zeilen[maske]

    breiten = (1.1, 3.4, 1.1, 1.1, 1.4, 1.3)
    _reference_row(
        ("Kürzel", "Name", "Breite", "Länge", "Land", ""), breiten, header=True
    )
    st.caption("{} von {} Einträgen".format(len(zeilen), len(spaceports)))
    for _, r in zeilen.head(60).iterrows():
        code = str(r["Kurzel"])
        knopf = _reference_row(
            (
                "`{}`".format(code),
                str(r["Name"])[:44],
                "{:.3f}".format(float(r["Latitude"])),
                "{:.3f}".format(float(r["Longitude"])),
                str(r["Land"]),
                "",
            ),
            breiten,
        )
        if knopf.button(
            "Entfernen", key="rm_sp_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                SPACEPORT_CSV, spaceports, SPACEPORT_EXPORT_COLUMNS, "Kurzel", code
            )
            # Der Dialog laeuft als Fragment; ohne App-Scope wuerde nur er selbst
            # neu laufen und die Auswertung mit den alten Daten weiterrechnen.
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Nur die ersten 60 Treffer werden gezeigt - Suche eingrenzen.")

    st.divider()
    with st.form("add_spaceport", clear_on_submit=True):
        st.markdown("**➕ Weltraumbahnhof hinzufügen**")
        a, b = st.columns(2)
        kurzel = a.text_input("Kürzel", max_chars=12, placeholder="z.B. WSLC")
        land = b.selectbox("Land", TARGET_NATIONS)
        name = st.text_input("Name", placeholder="z.B. Wenchang Space Launch Site")
        c, d = st.columns(2)
        lat = c.number_input("Breite (°N)", -90.0, 90.0, 0.0, format="%.4f")
        lon = d.number_input("Länge (°E)", -180.0, 180.0, 0.0, format="%.4f")
        if st.form_submit_button("Hinzufügen", type="primary", use_container_width=True):
            code = kurzel.strip().upper()
            if not code:
                st.error("Kürzel fehlt.")
            elif code in set(spaceports["Kurzel"].astype(str)):
                st.error("Kürzel {} ist bereits vergeben.".format(code))
            else:
                _add_reference_row(
                    SPACEPORT_CSV, spaceports, SPACEPORT_EXPORT_COLUMNS, "Kurzel",
                    {
                        "Kurzel": code, "Latitude": float(lat), "Longitude": float(lon),
                        "Name": name.strip() or code, "Land": land,
                    },
                )
                st.rerun(scope="app")


def _fir_editor(firs: pd.DataFrame) -> None:
    """Tabelle der FIRs/ACCs mit Entfernen- und Hinzufuegen-Funktion."""
    suche = st.text_input(
        "Suchen", key="fir_search", placeholder="ICAO-Code, Region, Land oder Startnation …"
    ).strip().upper()
    zeilen = firs
    if suche:
        maske = (
            zeilen["ICAO Code"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Betroffene Region / FIR Name"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Land"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Zugehörige Startnation"].astype(str).str.upper().str.contains(suche, regex=False)
        )
        zeilen = zeilen[maske]

    breiten = (1.0, 2.9, 1.0, 1.0, 1.7, 2.0, 1.3)
    _reference_row(
        ("ICAO", "Region / FIR", "Breite", "Länge", "FIR liegt in", "Startnation", ""),
        breiten, header=True,
    )
    st.caption("{} von {} Einträgen".format(len(zeilen), len(firs)))
    for _, r in zeilen.head(60).iterrows():
        code = str(r["ICAO Code"])
        knopf = _reference_row(
            (
                "`{}`".format(code),
                str(r["Betroffene Region / FIR Name"])[:38],
                "{:.2f}".format(float(r["Latitude"])),
                "{:.2f}".format(float(r["Longitude"])),
                str(r["Land"])[:20],
                str(r["Zugehörige Startnation"])[:26],
                "",
            ),
            breiten,
        )
        if knopf.button(
            "Entfernen", key="rm_fir_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                FIR_CSV, firs, FIR_EXPORT_COLUMNS, "ICAO Code", code
            )
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Nur die ersten 60 Treffer werden gezeigt - Suche eingrenzen.")

    st.divider()
    with st.form("add_fir", clear_on_submit=True):
        st.markdown("**➕ FIR / ACC hinzufügen**")
        a, b = st.columns(2)
        icao = a.text_input("ICAO-Code", max_chars=6, placeholder="z.B. ZLHW")
        land = b.text_input("FIR liegt in", placeholder="z.B. China")
        name = st.text_input("Region / FIR-Name", placeholder="z.B. Lanzhou FIR")
        c, d = st.columns(2)
        lat = c.number_input("Breite (°N)", -90.0, 90.0, 0.0, format="%.4f", key="fir_lat")
        lon = d.number_input("Länge (°E)", -180.0, 180.0, 0.0, format="%.4f", key="fir_lon")
        nationen = st.multiselect(
            "Zugehörige Startnation(en)", TARGET_NATIONS,
            help="Mehrere Nationen bedeuten: die Zuordnung braucht eine Nennung im NOTAM-Text.",
        )
        if st.form_submit_button("Hinzufügen", type="primary", use_container_width=True):
            code = icao.strip().upper()
            if not code:
                st.error("ICAO-Code fehlt.")
            elif code in set(firs["ICAO Code"].astype(str)):
                st.error("ICAO-Code {} ist bereits vergeben.".format(code))
            elif not nationen:
                st.error("Mindestens eine Startnation auswählen.")
            else:
                _add_reference_row(
                    FIR_CSV, firs, FIR_EXPORT_COLUMNS, "ICAO Code",
                    {
                        "ICAO Code": code, "Latitude": float(lat), "Longitude": float(lon),
                        "Betroffene Region / FIR Name": name.strip() or code,
                        "Land": land.strip() or "-",
                        "Zugehörige Startnation": ";".join(nationen),
                    },
                )
                st.rerun(scope="app")


def _vehicle_editor(vehicles: pd.DataFrame) -> None:
    """Tabelle der Traegersysteme mit Entfernen- und Hinzufuegen-Funktion."""
    suche = st.text_input(
        "Suchen", key="veh_search", placeholder="Abkürzung, Name oder Land …"
    ).strip().upper()
    zeilen = vehicles
    if suche:
        maske = (
            zeilen["Abkürzung"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Name"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Alternativname englisch"].astype(str).str.upper().str.contains(suche, regex=False)
            | zeilen["Land"].astype(str).str.upper().str.contains(suche, regex=False)
        )
        zeilen = zeilen[maske]

    breiten = (1.3, 2.4, 2.6, 1.4, 1.3)
    _reference_row(
        ("Abkürzung", "Name", "Englisch", "Land", ""), breiten, header=True
    )
    st.caption("{} von {} Einträgen".format(len(zeilen), len(vehicles)))
    for _, r in zeilen.head(60).iterrows():
        code = str(r["Abkürzung"])
        knopf = _reference_row(
            (
                "`{}`".format(code),
                str(r["Name"])[:30],
                str(r["Alternativname englisch"])[:34],
                str(r["Land"]),
                "",
            ),
            breiten,
        )
        if knopf.button(
            "Entfernen", key="rm_veh_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                VEHICLE_CSV, vehicles, VEHICLE_EXPORT_COLUMNS, "Abkürzung", code
            )
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Nur die ersten 60 Treffer werden gezeigt - Suche eingrenzen.")

    st.divider()
    with st.form("add_vehicle", clear_on_submit=True):
        st.markdown("**➕ Trägersystem hinzufügen**")
        a, b = st.columns(2)
        kuerzel = a.text_input("Abkürzung", max_chars=20, placeholder="z.B. CZ-5B")
        land = b.selectbox("Land", TARGET_NATIONS, key="veh_land")
        name = st.text_input("Name", placeholder="z.B. Chang Zheng 5B")
        englisch = st.text_input(
            "Alternativname englisch", placeholder="z.B. Long March 5B"
        )
        if st.form_submit_button("Hinzufügen", type="primary", use_container_width=True):
            code = kuerzel.strip()
            if not code:
                st.error("Abkürzung fehlt.")
            elif code.upper() in {c.upper() for c in vehicles["Abkürzung"].astype(str)}:
                st.error("Abkürzung {} ist bereits vergeben.".format(code))
            elif not name.strip():
                st.error("Name fehlt.")
            else:
                _add_reference_row(
                    VEHICLE_CSV, vehicles, VEHICLE_EXPORT_COLUMNS, "Abkürzung",
                    {
                        "Land": land,
                        "Name": name.strip(),
                        "Alternativname englisch": englisch.strip() or name.strip(),
                        "Abkürzung": code,
                    },
                )
                st.rerun(scope="app")


@st.dialog("⚙️ Referenzdaten verwalten", width="large")
def _reference_dialog(
    spaceports: pd.DataFrame, firs: pd.DataFrame, vehicles: pd.DataFrame
) -> None:
    """Optionsmenue zur Pflege der Startplatz- und FIR-Referenz."""
    st.caption(
        "Entfernte Einträge werden nicht mehr zur Berechnung herangezogen, "
        "hinzugefügte fließen sofort ein. Die Dateien auf der Platte bleiben "
        "unverändert, bis du sie unten ausdrücklich speicherst."
    )
    flash = st.session_state.pop("ref_flash", None)
    if flash:
        st.success(flash)
    tab_sp, tab_fir, tab_veh = st.tabs(
        [
            "🚀 Weltraumbahnhöfe ({})".format(len(spaceports)),
            "🗺️ ICAO FIR/ACC ({})".format(len(firs)),
            "🛰️ Trägersysteme ({})".format(len(vehicles)),
        ]
    )
    with tab_sp:
        _spaceport_editor(spaceports)
    with tab_fir:
        _fir_editor(firs)
    with tab_veh:
        _vehicle_editor(vehicles)

    st.divider()
    stapel = st.session_state.get("ref_undo", [])
    st.caption(
        "Änderungen werden sofort in `{}`, `{}` bzw. `{}` geschrieben und "
        "überleben einen Neustart.".format(
            SPACEPORT_CSV.name, FIR_CSV.name, VEHICLE_CSV.name
        )
    )
    a, b, c, d = st.columns(4)
    if a.button(
        "↩️ Letzte Änderung rückgängig ({})".format(len(stapel)),
        disabled=not stapel,
        use_container_width=True,
    ):
        zurueck = _undo_reference()
        st.session_state["ref_flash"] = (
            "Rückgängig gemacht: {}".format(zurueck) if zurueck else "Nichts rückgängig zu machen."
        )
        st.rerun(scope="app")
    b.download_button(
        "💾 Startplätze sichern",
        data=reference_to_csv(spaceports, SPACEPORT_EXPORT_COLUMNS),
        file_name="weltraumbahnhoefe_koordinaten_updated.csv",
        mime="text/csv",
        use_container_width=True,
        help="Kopie des aktuellen Stands herunterladen.",
    )
    c.download_button(
        "💾 FIRs sichern",
        data=reference_to_csv(firs, FIR_EXPORT_COLUMNS),
        file_name="icao_fir_acc_coordinates_updated.csv",
        mime="text/csv",
        use_container_width=True,
    )
    d.download_button(
        "💾 Trägersysteme sichern",
        data=reference_to_csv(vehicles, VEHICLE_EXPORT_COLUMNS),
        file_name="traegersysteme_updated.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if st.button("Schließen", use_container_width=True, type="primary"):
        st.session_state["ref_dialog_open"] = False
        st.rerun(scope="app")


def _zur_notam_springen(zeilen: Sequence[int]) -> None:
    """Merkt sich die gewaehlten NOTAMs und oeffnet den Reiter mit dem Volltext."""
    st.session_state["focus_rows"] = [int(z) for z in zeilen]
    st.session_state["goto_notam_data"] = True


def _auswahl_zeilen(auswahl: Any) -> List[int]:
    """Liest die markierten Zeilenpositionen aus dem Rueckgabewert von st.dataframe."""
    try:
        return list(auswahl.selection.rows)
    except AttributeError:
        return []


def _style_manual(df: pd.DataFrame) -> Any:
    """
    Hebt die Kennungen manuell bestaetigter NOTAMs farblich hervor.

    Streamlit kann in einer Tabellenzelle keine einzelnen Zeichen formatieren;
    das vorangestellte Hexagon wird daher zusammen mit der Kennung eingefaerbt.
    """
    if df.empty or "NOTAM ID" not in df.columns and "NOTAMs" not in df.columns:
        return df
    spalte = "NOTAM ID" if "NOTAM ID" in df.columns else "NOTAMs"

    farbe = manual_color()

    def faerben(werte: pd.Series) -> List[str]:
        return [
            "color: {}; font-weight: 600".format(farbe) if MANUAL_MARK in str(v) else ""
            for v in werte
        ]

    try:
        return df.style.apply(faerben, subset=[spalte])
    except Exception:  # pragma: no cover - Styler ist rein kosmetisch
        return df


def _confirm_launch(key: str) -> None:
    """Uebernimmt ein geprueftes NOTAM aus dem Review in die Launch-Tabelle."""
    st.session_state["confirmed_launches"].add(key)
    st.session_state["hidden_events"].discard(key)
    st.session_state["rejected_launches"].discard(key)
    _persist_workspace()


def _reject_launch(key: str) -> None:
    """Stellt einen Start aus der Launch-Tabelle zurueck in den Review."""
    st.session_state["rejected_launches"].add(key)
    st.session_state["confirmed_launches"].discard(key)
    st.session_state["hidden_events"].discard(key)
    _persist_workspace()


def _reset_decision(key: str) -> None:
    """Hebt eine manuelle Entscheidung auf - das NOTAM wird wieder automatisch bewertet."""
    st.session_state["rejected_launches"].discard(key)
    st.session_state["confirmed_launches"].discard(key)
    st.session_state["hidden_events"].discard(key)
    _persist_workspace()


def _revoke_launch(key: str) -> None:
    """Nimmt eine manuelle Bestaetigung zurueck."""
    st.session_state["confirmed_launches"].discard(key)
    _persist_workspace()


def _hide_event(key: str) -> None:
    """Blendet ein NOTAM aus dem Review aus."""
    st.session_state["hidden_events"].add(key)
    st.session_state["confirmed_launches"].discard(key)
    st.session_state["rejected_launches"].discard(key)
    _persist_workspace()


def _unhide_event(key: str) -> None:
    """Holt ein ausgeblendetes NOTAM zurueck in den Review."""
    st.session_state["hidden_events"].discard(key)
    _persist_workspace()


def _reference_status(label: str, path: Path) -> Tuple[Optional[pd.DataFrame], str]:
    """Laedt eine Referenz-CSV und liefert Dataframe plus Statusmeldung."""
    if not path.exists():
        return None, "❌ {}: Datei nicht gefunden ({})".format(label, path.name)
    try:
        stamp = path.stat().st_mtime
        if "weltraum" in path.name:
            df = load_spaceports(str(path), stamp)
        elif "traegersysteme" in path.name:
            df = load_vehicles(str(path), stamp)
        else:
            df = load_firs(str(path), stamp)
    except Exception as exc:
        return None, "❌ {}: {}".format(label, exc)
    return df, "✅ {}: {} Eintraege ({})".format(
        label, len(df), datetime.fromtimestamp(stamp).strftime("%d.%m.%Y %H:%M")
    )


def main() -> None:
    st.set_page_config(
        page_title="NOTAM Space-Launch Analyzer",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not st.session_state.get("workspace_loaded"):
        gespeichert = load_workspace()
        st.session_state["manual_notams"] = list(gespeichert.get("manual_notams", []))
        st.session_state["confirmed_launches"] = set(gespeichert.get("confirmed_launches", []))
        st.session_state["hidden_events"] = set(gespeichert.get("hidden_events", []))
        st.session_state["rejected_launches"] = set(gespeichert.get("rejected_launches", []))
        st.session_state["workspace_loaded"] = True
    st.session_state.setdefault("manual_notams", [])
    st.session_state.setdefault("manual_feedback", None)
    st.session_state.setdefault("confirmed_launches", set())
    st.session_state.setdefault("hidden_events", set())
    st.session_state.setdefault("rejected_launches", set())
    st.session_state.setdefault("focus_rows", [])
    st.session_state.setdefault("goto_notam_data", False)
    st.session_state.setdefault("ref_undo", [])
    st.session_state.setdefault("ref_dialog_open", False)
    st.session_state.setdefault("ref_flash", None)

    st.title("🚀 NOTAM Space-Launch Analyzer")
    st.caption(
        "Taegliche Auswertung von NOTAM-Dateien auf Raumfahrtstarts "
        "(China · Russland · Indien · Iran · Nordkorea · USA)"
    )

    # ----------------------------- Sidebar ------------------------------- #
    with st.sidebar:
        kopf, zahnrad = st.columns([5, 1], vertical_alignment="bottom")
        kopf.header("📚 Referenzdaten")
        if zahnrad.button("⚙️", help="Referenzdaten verwalten", use_container_width=True):
            st.session_state["ref_dialog_open"] = True

        spaceports, sp_msg = _reference_status("Weltraumbahnhoefe", SPACEPORT_CSV)
        firs, fir_msg = _reference_status("ICAO FIR/ACC", FIR_CSV)
        vehicles, veh_msg = _reference_status("Traegersysteme", VEHICLE_CSV)

        st.markdown(sp_msg)
        st.markdown(fir_msg)
        st.markdown(veh_msg)

        if spaceports is None or firs is None or vehicles is None:
            st.error(
                "Alle drei Referenz-CSVs muessen im Ordner von app.py liegen:\n\n"
                "- `weltraumbahnhoefe_koordinaten_updated.csv`\n"
                "- `icao_fir_acc_coordinates_updated.csv`\n"
                "- `traegersysteme_updated.csv`"
            )
            st.stop()

        st.divider()
        st.header("📤 NOTAM-Import")
        uploaded = st.file_uploader(
            "Taegliche NOTAM-Datei hochladen",
            type=["csv", "txt", "xls", "xlsx"],
            accept_multiple_files=False,
            help="CSV oder Excel-Export (z.B. FAA FNS). Vorspannzeilen werden erkannt.",
        )
        use_demo = st.toggle(
            "Demo-Datensatz verwenden",
            value=False,
            help="Beispiel-NOTAMs zum Testen der Pipeline ohne eigenen Upload.",
        )
        st.divider()
        st.header("✍️ NOTAM manuell einfügen")
        st.text_area(
            "NOTAM per Copy & Paste",
            key="manual_input",
            height=160,
            placeholder=(
                "A1234/25 NOTAMN\n"
                "Q) ZJSA/QRTCA/IV/BO/W/000/999\n"
                "A) ZJSA B) 2509210130 C) 2509210430\n"
                "E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH.\n"
                "   DEBRIS AREA 1936N11057E 1948N11212E 1902N11230E\n"
                "F) SFC G) UNL"
            ),
            help=(
                "Beliebiges NOTAM-Format: ICAO-Items, FAA-Domestic (!FDC ...) oder "
                "reiner Freitext. Koordinaten in 1936N11057E, 19°36'N 110°57'E oder "
                "Dezimalgrad. Mehrere NOTAMs auf einmal werden an den Kennungen "
                "getrennt, sonst an Leerzeilen."
            ),
        )
        st.button(
            "➕ Hinzufügen",
            on_click=_add_manual_notams,
            use_container_width=True,
            type="primary",
        )

        feedback = st.session_state.get("manual_feedback")
        if feedback:
            st.success("{} NOTAM(s) übernommen.".format(feedback))
        elif feedback == 0:
            st.warning("Kein auswertbarer Text erkannt.")

        manual_items = st.session_state["manual_notams"]
        if manual_items:
            with st.expander("Manuelle Einträge ({})".format(len(manual_items)), expanded=True):
                for i, entry in enumerate(manual_items):
                    preview = re.sub(r"\s+", " ", entry["text"])[:60]
                    st.caption("**{}** · {} …".format(entry["added"], preview))
                    st.button(
                        "🗑️ Entfernen",
                        key="del_manual_{}".format(i),
                        on_click=_remove_manual,
                        args=(i,),
                        use_container_width=True,
                    )
            st.button(
                "Alle manuellen Einträge verwerfen",
                on_click=_clear_manual,
                use_container_width=True,
            )

        st.divider()
        min_conf = st.select_slider(
            "Mindest-Konfidenz",
            options=["HOCH", "MITTEL", "NIEDRIG"],
            value="MITTEL",
            help=(
                "Die Trigger der Spezifikation (SFC/UNL, 000/999, Gebietskeywords) "
                "sprechen auch auf Wetterballons, Schiessuebungen und Suchscheinwerfer an. "
                "Das Scoring gewichtet raumfahrtspezifische Begriffe positiv und "
                "Ausschlussbegriffe negativ. Verworfene NOTAMs bleiben im Review-Tab sichtbar."
            ),
        )

    if st.session_state["ref_dialog_open"]:
        _reference_dialog(spaceports, firs, vehicles)

    # --------------------------- Daten laden ------------------------------ #
    imported: Optional[pd.DataFrame] = None
    source_label = ""
    if uploaded is not None:
        try:
            imported = read_notam_table(uploaded, uploaded.name)
            source_label = uploaded.name
        except Exception as exc:
            st.error("Upload konnte nicht gelesen werden: {}".format(exc))
            st.stop()
    elif use_demo:
        imported = build_demo_notams()
        source_label = "Demo-Datensatz"

    # Manuelle Eintraege in die Volltextspalte des Imports schreiben, damit beide
    # Quellen anschliessend identisch durch die Pipeline laufen.
    manual_entries = st.session_state["manual_notams"]
    text_column = "NOTAM Text"
    if imported is not None and not imported.empty:
        detected = map_notam_columns(imported)["text"]
        if detected:
            text_column = detected
    manual_df = (
        manual_entries_to_dataframe(manual_entries, text_column) if manual_entries else None
    )
    notams = combine_sources(imported, manual_df)

    if manual_entries:
        source_label = "{}{}{} manuell erfasst".format(
            source_label, " + " if source_label else "", len(manual_entries)
        )

    if notams.empty:
        st.info(
            "⬅️ Lade links eine NOTAM-Datei hoch, füge ein NOTAM per Copy & Paste ein "
            "oder aktiviere den Demo-Datensatz, um die Auswertung zu starten."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            with st.expander("Erwartetes Dateiformat"):
                st.markdown(
                    "CSV, XLS oder XLSX. Der Parser erkennt Spalten automatisch; "
                    "hilfreich sind `NOTAM ID`, `NOTAM Text`, `FIR`, `Valid From`, "
                    "`Valid To`. Liegt nur eine Volltextspalte vor, wird diese "
                    "komplett ausgewertet. Vorspannzeilen (z.B. FAA-FNS-Exporte) "
                    "werden übersprungen."
                )
                st.dataframe(build_demo_notams().head(3), use_container_width=True)
        with col_b:
            with st.expander("Freitext-Eingabe"):
                st.markdown(
                    "Im Feld **NOTAM manuell einfügen** lässt sich ein NOTAM direkt "
                    "einsetzen - ICAO-Items, FAA-Domestic-Format oder reiner Freitext. "
                    "Die Einträge werden in Tabelle, Karte und Export als `Manuell` "
                    "geführt und bleiben erhalten, bis du sie verwirfst."
                )
        return

    with st.spinner("NOTAMs werden ausgewertet ..."):
        events, stats = analyze_notams(
            notams,
            spaceports,
            firs,
            min_confidence=min_conf,
            confirmed_keys=st.session_state["confirmed_launches"],
            rejected_keys=st.session_state["rejected_launches"],
        )
    hidden_keys = st.session_state["hidden_events"]
    hidden_events = [e for e in events if e.key in hidden_keys]
    visible_events = [e for e in events if e.key not in hidden_keys]
    table = events_to_dataframe(visible_events)

    # ----------------------------- Filter --------------------------------- #
    with st.sidebar:
        st.divider()
        st.header("🎛️ Filter")
        nations_available = sorted(
            n for n in table["Startnation"].dropna().unique() if n and n != "-"
        )
        nation_filter = st.multiselect(
            "Startnation", nations_available, default=nations_available
        )
        inc_range = st.slider(
            "Inklinationsbereich (°)", 0.0, 180.0, (0.0, 180.0), step=1.0
        )
        sources_available = sorted(table["Quelle"].dropna().unique()) if len(table) else []
        source_filter = (
            st.multiselect("Quelle", sources_available, default=sources_available)
            if len(sources_available) > 1
            else sources_available
        )
        show_review = st.checkbox("Review-Faelle in der Tabelle anzeigen", value=False)

        valid_dates = [d for d in list(table["_from"].dropna()) if d is not None]
        date_filter = None
        if valid_dates:
            min_day = min(valid_dates).date()
            max_day = max(valid_dates).date()
            if min_day != max_day:
                date_filter = st.date_input(
                    "Startfenster (UTC)", value=(min_day, max_day),
                    min_value=min_day, max_value=max_day,
                )
            else:
                st.caption("Startfenster: alle NOTAMs am {}".format(min_day.strftime("%d.%m.%Y")))

    mask = pd.Series(True, index=table.index)
    if source_filter:
        mask &= table["Quelle"].isin(list(source_filter))
    if nation_filter:
        # Manuell bestaetigte NOTAMs bleiben immer sichtbar - ohne Koordinaten
        # steht dort keine Nation, sie duerfen aber nicht wieder verschwinden.
        mask &= (
            table["Startnation"].isin(nation_filter)
            | (table["Status"] == "REVIEW")
            | (table["Geprüft"] != "-")
        )
    inc = table["Est. Inklination (°)"]
    mask &= (inc.isna()) | ((inc >= inc_range[0]) & (inc <= inc_range[1]))
    if date_filter and isinstance(date_filter, (list, tuple)) and len(date_filter) == 2:
        start_day, end_day = date_filter
        day_series = table["_from"].apply(lambda d: d.date() if d is not None and pd.notna(d) else None)
        mask &= day_series.isna() | ((day_series >= start_day) & (day_series <= end_day))

    filtered = table[mask]
    ok_rows = filtered[filtered["Status"] == "OK"]
    review_rows = table[table["Status"] == "REVIEW"]
    display_rows = filtered if show_review else ok_rows
    event_by_row = {e.row_index: e for e in events}
    review_events = [e for e in visible_events if e.status == "REVIEW"]
    confirmed_events = [e for e in visible_events if e.manual_override]

    # Starts, die nach der Filterung noch mindestens eine Sperrzone zeigen.
    visible_rows = set(int(r) for r in ok_rows["_row"]) if len(ok_rows) else set()
    visible_groups = [
        g
        for g in stats.get("groups", [])
        if g.spaceport_code and visible_rows & set(g.row_indices)
    ]
    group_table = groups_to_dataframe(visible_groups)

    # ------------------------------ Tabs ---------------------------------- #
    reiter = [
        "📊 Launch Overview",
        "🗺️ Flightpath Map",
        "📄 NOTAM Data",
        "📥 Export",
        "⚠️ Unassigned / Review ({})".format(len(review_events)),
        "❗ Ausgeblendet ({})".format(len(hidden_events)),
    ]
    # Bewusst kein st.tabs: dessen aktiver Reiter liegt im Client und laesst sich
    # nicht aus dem Programm heraus umschalten. Mit der Segmentleiste kann ein
    # Klick in der Launch Overview direkt den Volltext oeffnen - und es wird nur
    # der sichtbare Bereich gerendert statt aller sechs.
    if st.session_state.pop("goto_notam_data", False):
        st.session_state["bereich"] = reiter[2]
    bereich = st.segmented_control(
        "Bereich",
        reiter,
        default=reiter[0],
        key="bereich",
        label_visibility="collapsed",
        width="stretch",
    ) or reiter[0]

    if bereich == reiter[0]:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric(
            "Erfasste Launches",
            len(visible_groups),
            help="Starts nach Zusammenfassung mehrerer Sperrzonen desselben Fluges.",
        )
        c2.metric(
            "Aktive Sperrzonen",
            len(ok_rows),
            help="Einzelne NOTAMs - ein Start kann mehrere Zonen entlang der Bahn haben.",
        )
        c3.metric(
            "Erkannte Nationen",
            ok_rows["Startnation"].nunique() if len(ok_rows) else 0,
        )
        c4.metric(
            "Manuell",
            int((ok_rows["Quelle"] == SOURCE_MANUAL).sum()) if len(ok_rows) else 0,
            help="Per Copy & Paste eingefügte NOTAMs unter den erfassten Launches.",
        )
        c5.metric(
            "{} Geprüft".format(MANUAL_MARK),
            len(confirmed_events),
            help="Im Review geprüfte und manuell als Start bestätigte NOTAMs.",
        )
        c6.metric("Review", len(review_rows))
        st.caption(
            "Quelle: {} · {} Zeilen gelesen · {} ohne Weltraum-Trigger verworfen · "
            "{} Mehrfachlistungen entfernt · Mindest-Konfidenz: {} · "
            "{} Start(s) mit mehreren Sperrzonen zusammengefasst".format(
                source_label,
                stats["rows"],
                stats["no_trigger"],
                stats.get("duplicates", 0),
                stats["min_confidence"],
                stats.get("grouped", 0),
            )
        )

        if visible_groups:
            st.markdown("#### Klartext-Auswertung")
            st.caption(
                "Jeder erkannte Start in einem Satz - mit der Begruendung, woran er "
                "erkannt wurde und wie belastbar die Abschaetzung ist."
            )
            for group in visible_groups:
                titel = "🚀 {} · {} · {} · {} · {}".format(
                    mark_id_markdown(group.group_id, group.manual_override),
                    group.nation or "unbestimmt",
                    group.spaceport_code or "-",
                    group.launch_window,
                    group.orbit_type,
                )
                with st.expander(titel, expanded=len(visible_groups) <= 3):
                    st.markdown(describe_launch(group, events))
            st.divider()

        st.caption(
            "Tipp: Ein Klick auf eine Zeile springt zum zugehörigen NOTAM-Volltext "
            "unter *NOTAM Data*."
        )
        view = st.radio(
            "Ansicht",
            ["Nach Start gruppiert", "Einzelne NOTAMs"],
            horizontal=True,
            help=(
                "Ein Start erzeugt mehrere Sperrzonen entlang der Flugbahn. Die "
                "Start-Ansicht fasst sie zu einer Zeile zusammen, die NOTAM-Ansicht "
                "zeigt jede Zone einzeln."
            ),
        )

        if view == "Nach Start gruppiert":
            if group_table.empty:
                st.warning("Keine Starts entsprechen den aktuellen Filtern.")
            else:
                auswahl = st.dataframe(
                    _style_manual(group_table),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="auswahl_starts",
                )
                gewaehlt = _auswahl_zeilen(auswahl)
                if gewaehlt:
                    gruppe = visible_groups[gewaehlt[0]]
                    _zur_notam_springen(gruppe.row_indices)
                    st.rerun()
        elif display_rows.empty:
            st.warning("Keine Events entsprechen den aktuellen Filtern.")
        else:
            auswahl = st.dataframe(
                _style_manual(display_rows.drop(columns=["_row", "_from", "_to"])),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="auswahl_notams",
            )
            gewaehlt = _auswahl_zeilen(auswahl)
            if gewaehlt:
                _zur_notam_springen([int(display_rows.iloc[gewaehlt[0]]["_row"])])
                st.rerun()

    if bereich == reiter[1]:
        if ok_rows.empty:
            st.info("Keine georeferenzierten Events fuer die Kartendarstellung.")
        elif not FOLIUM_AVAILABLE:
            st.warning(
                "`folium` / `streamlit-folium` sind nicht installiert - "
                "Fallback auf die einfache Punktkarte."
            )
            pts = [
                {"lat": e.centroid_lat, "lon": e.centroid_lon}
                for e in events
                if e.status == "OK" and e.centroid_lat is not None
            ]
            if pts:
                st.map(pd.DataFrame(pts))
        else:
            options = ["Alle Starts"] + [
                "{} · {} · {}".format(g.group_id, g.nation, ", ".join(g.notam_ids))
                for g in visible_groups
            ]
            choice = st.selectbox("Darstellung", options, index=0)
            if choice == "Alle Starts":
                selection = [event_by_row[int(r)] for r in ok_rows["_row"]]
            else:
                group = visible_groups[options.index(choice) - 1]
                selection = [
                    event_by_row[r] for r in group.row_indices if r in event_by_row
                ]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Launch Azimut", "{:.1f}°".format(group.azimuth_deg or 0.0))
                m2.metric("Est. Inklination", "{:.1f}°".format(group.inclination_deg or 0.0))
                m3.metric("Reichweite", "{:.0f} km".format(group.max_range_km or 0.0))
                m4.metric(
                    "Sperrzonen",
                    group.zone_count,
                    help="Zonen entlang der Flugbahn: {}".format(", ".join(group.notam_ids)),
                )
                st.caption(
                    "Orbit-Typ: **{}** · Startplatz: {} · Azimut-Streuung {:.1f}° · "
                    "Startrichtung {}".format(
                        group.orbit_type,
                        group.spaceport_name,
                        group.azimuth_spread_deg,
                        compass_name(group.azimuth_deg),
                    )
                )
                with st.expander("Was bedeutet das?"):
                    st.markdown(describe_launch(group, events))
            st_folium(
                build_event_map(selection),
                use_container_width=True,
                height=620,
                returned_objects=[],
            )
            st.caption(
                "Gestrichelt: Grosskreis vom Startplatz entlang des berechneten "
                "Launch-Azimuts. Je Start wird eine Bahn gezeichnet - mehrere "
                "Sperrzonen desselben Fluges liegen darauf."
            )

    if bereich == reiter[2]:
        fokus = [z for z in st.session_state["focus_rows"] if z in set(display_rows["_row"])]
        if fokus:
            kennungen = ", ".join(
                event_by_row[z].notam_id for z in fokus if z in event_by_row
            )
            hinweis, zuruecksetzen = st.columns([4, 1])
            hinweis.info(
                "Aus der Launch Overview geöffnet: **{}** — "
                "die Auswahl steht oben und ist aufgeklappt.".format(kennungen)
            )
            if zuruecksetzen.button("Auswahl aufheben", use_container_width=True):
                st.session_state["focus_rows"] = []
                st.rerun()

        if display_rows.empty:
            st.info("Keine NOTAMs zur Anzeige.")
        else:
            # Die gewaehlten NOTAMs zuerst, damit man nicht suchen muss.
            rang = {z: i for i, z in enumerate(fokus)}
            sortiert = display_rows.assign(
                _rang=display_rows["_row"].map(lambda z: rang.get(int(z), len(rang)))
            ).sort_values("_rang", kind="stable")
            for _, row in sortiert.iterrows():
                event = event_by_row[int(row["_row"])]
                ist_fokus = int(row["_row"]) in rang
                header = "{}{} · {} · {} · {}".format(
                    mark_id_markdown(event.notam_id, event.manual_override),
                    " ✍️ manuell eingefügt" if event.source == SOURCE_MANUAL else "",
                    event.nation or "unbestimmt",
                    event.spaceport_code or "ohne Startplatz",
                    event.orbit_type,
                )
                with st.expander(header, expanded=ist_fokus):
                    st.code(event.raw_text, language="text")
                    left, right = st.columns(2)
                    left.markdown(
                        "**Trigger**\n\n- " + "\n- ".join(event.triggers or ["-"])
                    )
                    coord_lines = [
                        "{:.4f}, {:.4f}".format(lat, lon) for lat, lon in event.coordinates
                    ]
                    right.markdown(
                        "**Koordinaten ({})**\n\n".format(len(coord_lines))
                        + ("\n".join("- " + c for c in coord_lines) if coord_lines else "- keine")
                    )
                    if event.fir_code:
                        st.caption(
                            "FIR {} ({}) · Zuordnung via {}".format(
                                event.fir_code, event.fir_name, event.fir_match_method
                            )
                        )
                    st.divider()
                    zu_review, zu_versteckt = st.columns(2)
                    zu_review.button(
                        "⚠️ In den Review",
                        key="reject_{}".format(event.key),
                        on_click=_reject_launch,
                        args=(event.key,),
                        use_container_width=True,
                        help="Aus der Launch-Tabelle nehmen und zur Prüfung "
                        "in Unassigned / Review verschieben.",
                    )
                    zu_versteckt.button(
                        "❗ Ausblenden",
                        key="hide_data_{}".format(event.key),
                        on_click=_hide_event,
                        args=(event.key,),
                        use_container_width=True,
                        help="Aus allen Auswertungen nehmen und im Reiter "
                        "'Ausgeblendet' ablegen.",
                    )

    if bereich == reiter[3]:
        st.subheader("Tagesergebnis exportieren")
        export_df = (filtered if show_review else ok_rows).drop(
            columns=["_row", "_from", "_to"]
        )
        st.write(
            "Enthalten: **{}** Start(s) · **{}** NOTAM-Datensaetze".format(
                len(group_table), len(export_df)
            )
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        col_a, col_b, col_c = st.columns(3)
        starts_csv = group_table.copy()
        if not starts_csv.empty:
            starts_csv["Klartext"] = [
                re.sub(r"\*\*|\n+", " ", describe_launch(g, events)).strip()
                for g in visible_groups
            ]
        col_a.download_button(
            "📥 CSV · Starts",
            data=starts_csv.to_csv(index=False).encode("utf-8-sig"),
            file_name="notam_starts_{}.csv".format(stamp),
            mime="text/csv",
            use_container_width=True,
            help="Eine Zeile je Start, mit allen zugehoerigen NOTAM-Kennungen.",
        )
        col_b.download_button(
            "📥 CSV · NOTAMs",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="notam_launches_{}.csv".format(stamp),
            mime="text/csv",
            use_container_width=True,
            help="Eine Zeile je NOTAM, mit Start-Kennung in der Spalte 'Start'.",
        )
        selected_rows = set(int(r) for r in (filtered if show_review else ok_rows)["_row"])
        payload = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source": source_label,
            "statistics": {
                "rows_read": stats["rows"],
                "duplicates_removed": stats.get("duplicates", 0),
                "events": stats["events"],
                "launches": len(visible_groups),
                "ok": stats["ok"],
                "review": stats["review"],
            },
            "launches": [
                dict(group_to_export_dict(g), klartext=describe_launch(g, events))
                for g in visible_groups
            ],
            "events": [
                event_to_export_dict(e) for e in events if e.row_index in selected_rows
            ],
        }
        col_c.download_button(
            "📥 JSON herunterladen",
            data=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="notam_launches_{}.json".format(stamp),
            mime="application/json",
            use_container_width=True,
        )
        with st.expander("JSON-Vorschau"):
            st.json(payload["launches"][:2] if payload["launches"] else {})

    if bereich == reiter[4]:
        if confirmed_events:
            with st.expander(
                "{} Manuell bestätigte NOTAMs ({})".format(MANUAL_MARK, len(confirmed_events)),
                expanded=False,
            ):
                st.caption(
                    "Diese NOTAMs wurden hier geprüft und in die Launch-Tabelle "
                    "übernommen. Sie tragen dort das Hexagon vor der Kennung."
                )
                for event in confirmed_events:
                    st.markdown(
                        "{} · {} · {}".format(
                            mark_id_html(event.notam_id, True),
                            event.nation or "unbestimmt",
                            event.launch_group or "keine Bahnberechnung",
                        ),
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "↩️ Bestätigung zurücknehmen",
                        key="revoke_{}".format(event.key),
                        on_click=_revoke_launch,
                        args=(event.key,),
                        use_container_width=True,
                    )
            st.divider()

        st.subheader("NOTAMs ohne belastbare Zuordnung")
        if not review_events:
            st.success("Alle getriggerten NOTAMs konnten vollstaendig zugeordnet werden.")
        else:
            zurueck = sum(
                1 for e in review_events if e.key in st.session_state["rejected_launches"]
            )
            st.caption(
                "Jedes NOTAM einzeln prüfen: **Space Launch** übernimmt es in die "
                "Launch-Tabelle und markiert es dort als manuell geprüft. "
                "**Ausblenden** verschiebt es in den Reiter *Ausgeblendet*."
                + (
                    "  \n{} davon wurden aus der Launch-Tabelle hierher zurückgestellt.".format(
                        zurueck
                    )
                    if zurueck
                    else ""
                )
            )
            review_table = events_to_dataframe(review_events)
            st.dataframe(
                review_table[
                    ["NOTAM ID", "Quelle", "FIR Code", "FIR liegt in", "Höhenprofil",
                     "Konfidenz", "Hinweis"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.divider()

            for event in review_events:
                with st.expander("{} · {}".format(event.notam_id, event.review_reason[:90])):
                    st.code(event.raw_text, language="text")
                    info_a, info_b = st.columns(2)
                    info_a.markdown(
                        "**Erkannte Merkmale**\n\n- "
                        + "\n- ".join(event.triggers or ["keine"])
                    )
                    info_b.markdown(
                        "**Konfidenz:** {} (Score {})\n\n**Koordinaten:** {}\n\n"
                        "**FIR:** {} ({})".format(
                            event.confidence_level,
                            event.confidence_score,
                            len(event.coordinates),
                            event.fir_code or "keine",
                            event.fir_country or "-",
                        )
                    )
                    st.markdown("**Grund für den Review:** {}".format(event.review_reason))
                    zurueckgestellt = event.key in st.session_state["rejected_launches"]
                    if zurueckgestellt:
                        st.button(
                            "↩️ Zurückstellung aufheben (wieder automatisch bewerten)",
                            key="unreject_{}".format(event.key),
                            on_click=_reset_decision,
                            args=(event.key,),
                            use_container_width=True,
                        )
                    act_a, act_b = st.columns(2)
                    act_a.button(
                        "🚀 Space Launch",
                        key="confirm_{}".format(event.key),
                        on_click=_confirm_launch,
                        args=(event.key,),
                        type="primary",
                        use_container_width=True,
                        help="Als geprüften Raumfahrtstart in die Launch-Tabelle übernehmen.",
                    )
                    act_b.button(
                        "❗ Ausblenden",
                        key="hide_{}".format(event.key),
                        on_click=_hide_event,
                        args=(event.key,),
                        use_container_width=True,
                        help="Aus dem Review entfernen und im Reiter 'Ausgeblendet' ablegen.",
                    )

    if bereich == reiter[5]:
        st.subheader("Ausgeblendete NOTAMs")
        if not hidden_events:
            st.info(
                "Noch nichts ausgeblendet. Im Reiter *Unassigned / Review* lassen sich "
                "geprüfte NOTAMs hierher verschieben, wenn sie kein Raumfahrtstart sind."
            )
        else:
            st.caption(
                "Hier liegen die geprüften und verworfenen NOTAMs. Sie zählen in keiner "
                "Auswertung mit und erscheinen nicht im Export - lassen sich aber "
                "jederzeit wieder einblenden."
            )
            st.dataframe(
                events_to_dataframe(hidden_events)[
                    ["NOTAM ID", "Quelle", "FIR Code", "FIR liegt in", "Höhenprofil",
                     "Konfidenz", "Hinweis"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.button(
                "↩️ Alle wieder einblenden",
                key="unhide_all",
                on_click=lambda: (
                    st.session_state["hidden_events"].clear(), _persist_workspace()
                ),
                use_container_width=True,
            )
            st.divider()
            for event in hidden_events:
                with st.expander(
                    "{} · {}".format(event.notam_id, (event.review_reason or "-")[:90])
                ):
                    st.code(event.raw_text, language="text")
                    single_a, single_b = st.columns(2)
                    single_a.button(
                        "↩️ Wieder einblenden",
                        key="unhide_{}".format(event.key),
                        on_click=_unhide_event,
                        args=(event.key,),
                        use_container_width=True,
                    )
                    single_b.button(
                        "🚀 Doch ein Space Launch",
                        key="hconfirm_{}".format(event.key),
                        on_click=_confirm_launch,
                        args=(event.key,),
                        use_container_width=True,
                    )


if __name__ == "__main__":
    main()
