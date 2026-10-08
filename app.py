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

import base64
import hashlib
import html
import io
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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

#: Anzeigenamen der Zielnationen.
#:
#: Die Werte selbst bleiben deutsch, weil sie die Spalte `Land` der FIR-Referenz
#: treffen muessen - das ist der Vertrag mit einer Datei, die der Benutzer
#: pflegt. Uebersetzt wird nur, was auf dem Bildschirm und im Archiv landet.
NATION_LABELS = {
    "Russland": "Russia",
    "Indien": "India",
    "Nordkorea": "North Korea",
}


def nation_label(nation: Optional[str]) -> str:
    """Englischer Anzeigename einer Nation; unbekannte bleiben unveraendert."""
    if not nation:
        return ""
    return NATION_LABELS.get(nation, nation)


#: Bahntypen. Sie sind reine Anzeigewerte - in den Referenzdateien kommen sie
#: nicht vor, deshalb stehen sie direkt auf Englisch.
ORBIT_UNKNOWN = "Undetermined"
ORBIT_RETROGRADE = "Retrograde"
ORBIT_SSO = "Sun-synchronous (SSO / polar)"
ORBIT_HIGH_INC = "High inclination / near-polar"
ORBIT_LEO_MEO = "Standard LEO / MEO (station corridor)"
ORBIT_GTO = "Equatorial / low inclination (GTO transit)"

#: Belastbarkeit der Bahnabschaetzung.
RELIABILITY_HIGH = "high"
RELIABILITY_MEDIUM = "medium"
RELIABILITY_LOW = "low"

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


#: Bahngeschwindigkeit einer niedrigen Erdumlaufbahn, fuer die Umrechnung von
#: Start- in Bahnazimut. Die Abschaetzung reagiert schwach darauf: zwischen
#: 7,5 und 8,0 km/s aendert sich das Ergebnis um weniger als ein halbes Grad.
ORBITAL_VELOCITY_MS = 7800.0

#: Umfangsgeschwindigkeit der Erde am Aequator.
EARTH_ROTATION_MS = 465.1


def orbital_azimuth_deg(site_lat: float, azimuth_deg: float) -> float:
    """
    Rechnet den Startazimut in den Bahnazimut um.

    Zur Startgeschwindigkeit addiert sich die Ostkomponente der Erddrehung,
    V_erde * cos(phi). Bei einem Start nach Osten verstaerkt sie die Bewegung
    und aendert die Richtung nicht; bei einem Start nach Sueden oder Norden
    dreht sie die Bahn nach Osten.
    """
    phi = math.radians(site_lat)
    alpha = math.radians(azimuth_deg)
    v_ost = ORBITAL_VELOCITY_MS * math.sin(alpha) + EARTH_ROTATION_MS * math.cos(phi)
    v_nord = ORBITAL_VELOCITY_MS * math.cos(alpha)
    return math.degrees(math.atan2(v_ost, v_nord)) % 360.0


def estimate_inclination_deg(site_lat: float, azimuth_deg: float) -> float:
    """
    Orbitale Inklination aus Startplatz-Breite phi und Startazimut alpha.

        cos(i) = cos(phi) * sin(Bahnazimut)

    Die Erdrotation ist eingerechnet (siehe orbital_azimuth_deg). Ohne sie
    ueberschaetzt die Rechnung rueckwaerts gerichtete Starts systematisch: Ein
    chinesischer Seestart vom 11./12.02.2026 ergab unkorrigiert 99,7 und 100,5
    Grad - zwei Klassen fuer denselben Start, einmal sonnensynchron, einmal
    retrograd. Mit Rotation sind es 96,7 und 97,6 Grad, also beide Male
    sonnensynchron, und das ist das Band, in dem solche Bahnen liegen.

    Es bleibt eine Abschaetzung: Sie unterstellt eine niedrige Erdumlaufbahn
    und einen Aufstieg ohne Bahnaenderung nach dem Start.
    """
    cos_i = math.cos(math.radians(site_lat)) * math.sin(
        math.radians(orbital_azimuth_deg(site_lat, azimuth_deg))
    )
    cos_i = max(-1.0, min(1.0, cos_i))
    return math.degrees(math.acos(cos_i))


def classify_orbit(inclination_deg: Optional[float]) -> str:
    """Klassifiziert den Ziel-Orbit anhand der abgeschaetzten Inklination."""
    if inclination_deg is None or (
        isinstance(inclination_deg, float) and math.isnan(inclination_deg)
    ):
        return ORBIT_UNKNOWN
    i = float(inclination_deg)
    # Die Grenzen sind bewusst weit: Die Inklination ist eine Abschaetzung aus
    # Startplatzbreite und einem Azimut, der selbst aus der Richtung zu einer
    # Dropzone stammt. Gemessen an bekannten SSO-Starts - Taiyuan, Jiuquan und
    # zwei chinesischen Seestarts - streut sie um rund drei Grad. Ein vier Grad
    # breites Band darum herum haette denselben Start je nach Tag einmal als
    # sonnensynchron und einmal als retrograd gefuehrt.
    if i > 103.0:
        return ORBIT_RETROGRADE
    if 93.0 <= i <= 103.0:
        return ORBIT_SSO
    if 66.0 <= i < 93.0:
        return ORBIT_HIGH_INC
    if 31.0 <= i <= 65.0:
        return ORBIT_LEO_MEO
    if 0.0 <= i <= 30.0:
        return ORBIT_GTO
    return ORBIT_UNKNOWN


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
    # AREA\s*\d statt AREA\s+\d: japanische Meldungen schreiben "AREA1:" ohne
    # Leerzeichen. Das \b dahinter schuetzt weiterhin davor, dass
    # "DANGER AREA 1936N11057E" mitten in der Koordinate getrennt wird - dort
    # folgt auf die Ziffer eine weitere Ziffer, also keine Wortgrenze.
    r"(?:(?<=[.:)])|^|\n)\s*(?:\d{1,2}\s*[.)]\s|SIMILAR ACTIVITIES\b)"
    # AREA1/AREA2 steht oft mitten im Satz: extract_items faltet die
    # Zeilenumbrueche, aus "...0321\nAREA1:" wird "...0321 AREA1:". Deshalb
    # genuegt hier ein Leerzeichen davor. Geschuetzt bleibt es durch das \b:
    # in "DANGER AREA 1936N11057E" folgt auf die Ziffer eine weitere Ziffer.
    r"|(?:(?<=[\s.:)])|^)AREA\s*\d\b"
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
MANUAL_COLOR = "#B7A8FF"
MANUAL_COLOR_LIGHT = "#6D4AE0"

#: Geometrisches Symbolvokabular nach der Referenzoberflaeche: Kreis, Dreieck,
#: Raute, Hexagon - gefuellt oder offen, die Bedeutung traegt die Form plus die
#: Farbe. Bewusst keine Piktogramme: sie tragen hier keine Information und
#: lassen ein Fachwerkzeug wie ein Spielzeug aussehen.
GLYPH_OK = "\u25CF"        # gefuellter Kreis - Referenz geladen
GLYPH_MISSING = "\u25C6"   # Raute - Referenz fehlt oder ist fehlerhaft
GLYPH_EMPTY = "\u25CB"     # offener Kreis - vorhanden, aber ohne Inhalt
GLYPH_REVIEW = "\u25B2"    # Dreieck - braucht eine Entscheidung
GLYPH_HIDDEN = "\u25A0"    # Quadrat - bewusst aus der Auswertung genommen
GLYPH_LAUNCH = "\u25B8"    # Pfeilspitze - ein Start

#: Farben zu den Symbolen; die Farbtoene stammen aus der Referenzoberflaeche
#: und stehen ebenso in .streamlit/config.toml.
COLOR_OK = "#2ECC89"
COLOR_ALERT = "#F2952B"
COLOR_ERROR = "#E5484F"
COLOR_MUTED = "#838C97"


def glyph(zeichen: str, farbe: str, deckkraft: float = 1.0) -> str:
    """
    Faerbt ein Symbol fuer die Anzeige in Markdown.

    Die Deckkraft bildet die Abstufung der Referenz nach: was gilt, steht voll
    da, was nur Zustand meldet, tritt zurueck.
    """
    return '<span style="color:{};opacity:{:.2f}">{}</span>'.format(
        farbe, deckkraft, zeichen
    )


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
SOURCE_MANUAL = "Pasted"

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
        "ISRO", "SRIHARIKOTA", "SDSC", "PSLV", "GSLV", "SSLV", "THUMBA",
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
        "FALCON 9", "FALCON HEAVY", "CREW DRAGON", "CARGO DRAGON",
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

KIND_LAUNCH = "Launch"
KIND_REENTRY = "Re-entry"
#: Eine Meldung, die den Luftraum eines Starts schon Tage vorher reserviert.
#: Sie wird nicht erkannt, sondern zugewiesen - siehe pair_advance_announcements.
KIND_ADVANCE = "Advance notice"


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


@lru_cache(maxsize=512)
def _hint_pattern(term: str) -> "re.Pattern":
    """
    Suchmuster fuer einen Stichwortbegriff - mit Wortgrenzen.

    Ohne sie trifft ein blosses ``t in text`` mitten in fremde Woerter hinein:
    SHAR in SHARJAH, CASC in CASCADE, NASA in NASAL, VEGA in LAS VEGAS. Jeder
    dieser Treffer setzt eine Startnation und sticht anschliessend die
    Drittstaaten-Regel - also genau den Schutz, der eine falsche Zuordnung
    verhindern soll.

    Die Grenze hinten entfaellt, wenn der Begriff selbst nicht auf einem
    Wortzeichen endet: "CZ-" soll weiterhin CZ-2D treffen, "INDIA " weiterhin
    "INDIA " und nicht INDIAN OCEAN.
    """
    begriff = term.strip()
    hinten = r"(?![A-Z0-9])" if begriff[-1:].isalnum() else ""
    return re.compile(r"(?<![A-Z0-9])" + re.escape(begriff) + hinten)


def hint_hits(text: str, terms: Sequence[str]) -> List[str]:
    """Stichwoerter, die im Text als eigenes Wort vorkommen."""
    upper = re.sub(r"\s+", " ", (text or "").upper())
    return [t.strip() for t in terms if _hint_pattern(t).search(upper)]


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
        found = [t.strip() for t in terms if _hint_pattern(t).search(upper)]
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
    return hint_hits(text, FOREIGN_OPERATORS)


#: Q-Code aus der Q-Line, z.B. QRDCA in "ZLHW/QRDCA/IV/BO/W/000/999/...".
RE_QCODE = re.compile(r"\bQ([A-Z]{4})\b")

#: Maximale Dauer, die noch als Startfenster gilt.
LAUNCH_WINDOW_MAX_HOURS = 24.0

#: Ab dieser Gesamtlaufzeit ohne taegliches Aktivierungsfenster ist eine Meldung
#: keine Startankuendigung mehr, sondern eine Daueranordnung.
#:
#: Die Grenze ist an Messwerten gewaehlt, nicht geraten. Laengste belegte
#: Startmeldung ohne Tagesfenster: eine NAVAREA-Warnung zu einem russischen
#: Start mit 216 h. Laengste Startmeldung ueberhaupt: 403 h, aber mit
#: Tagesfenster. Gegenbeispiel: eine japanische Anordnung zur Raketenabwehr
#: ueber Okinawa mit 2192 h - sie nennt ROCKET und erreichte damit HIGH,
#: obwohl sie keinen Start ankuendigt, sondern die Abwehr eines fremden.
#: 720 h lassen ueber dem laengsten belegten Echtfall Faktor drei Luft.
STANDING_ORDER_HOURS = 720.0


def extract_qcode(items: Dict[str, str], text: str = "") -> str:
    """Liest den fuenfstelligen Q-Code (z.B. QRDCA) aus der Q-Line."""
    q_line = items.get("Q", "")
    match = RE_QCODE.search(q_line.upper())
    if not match:
        match = re.search(r"/(Q[A-Z]{4})/", (text or "").upper())
        return match.group(1) if match else ""
    return "Q" + match.group(1)


#: Taegliche Zeitfenster im D-Item, z.B. "DAILY 0900-2100", "24-28 1100-2100"
#: oder "DLY BTN 1700/0400".
#:
#: Beide Trennzeichen kommen vor. Gemessen an der Echtdatei vom 18.09.2026:
#: von 100 D-Items mit Tagesfenster nutzen 8 den Schraegstrich. Nur den
#: Bindestrich zu lesen hiess, bei diesen acht kein Fenster zu finden - und
#: ohne Fenster greift der Daueranordnungs-Deckel und stuft auf LOW zurueck.
RE_DAILY_WINDOW = re.compile(r"\b(\d{4})\s*[-/]\s*(\d{4})\b")


def daily_windows(d_item: Optional[str]) -> List[Tuple[int, int]]:
    """
    Alle taeglichen Aktivierungsfenster des D-Items als Minuten nach Mitternacht.

    Ein Fenster ueber Mitternacht behaelt seine Endzeit kleiner als die
    Startzeit ("1700/0400"); das muss die auswertende Stelle beruecksichtigen.
    Ohne lesbares Fenster ist die Liste leer.
    """
    if not d_item:
        return []
    fenster: List[Tuple[int, int]] = []
    for match in RE_DAILY_WINDOW.finditer(d_item.upper()):
        try:
            start_h, start_m = int(match.group(1)[:2]), int(match.group(1)[2:])
            end_h, end_m = int(match.group(2)[:2]), int(match.group(2)[2:])
        except ValueError:
            continue
        if start_h > 24 or end_h > 24 or start_m >= 60 or end_m >= 60:
            continue
        fenster.append((start_h * 60 + start_m, end_h * 60 + end_m))
    return fenster


def daily_window_hours(d_item: Optional[str]) -> Optional[float]:
    """
    Laengstes taegliches Aktivierungsfenster aus dem D-Item, in Stunden.

    Ein NOTAM kann zwei Wochen gueltig sein und trotzdem nur taeglich wenige
    Stunden aktiv - fuer die Startsignatur zaehlt das tatsaechliche Fenster,
    nicht die Gesamtlaufzeit. Ohne D-Item ist das Ergebnis None.
    """
    longest: Optional[float] = None
    for start, end in daily_windows(d_item):
        minutes = end - start
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


CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


def exclusion_hits(text: str) -> List[str]:
    """
    Ausschlussbegriffe im Text - als Liste, nicht als fertiger Satz.

    Der Aufrufer entscheidet, was er damit tut: das Scoring baut daraus eine
    Begruendung, die Ausblende-Regel prueft nur, ob ueberhaupt einer da ist.
    Beides auf denselben Satz zu stuetzen waere eine Verzweigung auf Prosa.
    """
    upper = re.sub(r"\s+", " ", (text or "").upper())
    return [k.strip() for k in EXCLUSION_KEYWORDS if k in upper]


def auto_hide_reason(level: str, text: str) -> str:
    """
    Begruendung, wenn ein NOTAM ohne Nachfrage ausgeblendet wird - sonst "".

    Die Regel greift nur bei niedriger Konfidenz UND mindestens einem
    Ausschlussbegriff. Die Konfidenzstufe ist dabei die Bremse: ein echtes
    Start-NOTAM, in dem zufaellig BALLOON oder ALT RESERVATION auftaucht,
    erreicht ueber Q-Code, SFC-UNL und kurzes Aktivierungsfenster trotzdem
    MEDIUM oder HIGH und bleibt unangetastet. Der Ausschlussbegriff allein
    haette diese Bremse nicht.

    Ohne diese Regel landen an einem realen Tag 275 von 332 NOTAMs im Review;
    rund 50 davon sind ADS-B-Dienste, Wetterballons und Amateurraketen.
    """
    if level != "LOW":
        return ""
    treffer = exclusion_hits(text)
    if not treffer:
        return ""
    return "Low confidence with exclusion term(s): {}.".format(", ".join(treffer[:4]))


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

    blockers = exclusion_hits(text)
    if blockers:
        score -= 4 * min(len(blockers), 2)
        notes.append("Ausschlussbegriffe: {}".format(", ".join(blockers[:4])))

    if score >= 5:
        level = "HIGH"
    elif score >= 3:
        level = "MEDIUM"
    else:
        level = "LOW"

    # Eine Meldung, die wochenlang durchgehend gilt, kuendigt keinen Start an.
    # Das Scoring allein faengt das nicht: ein einziges starkes Stichwort wie
    # ROCKET genuegt fuer HIGH, auch wenn die Meldung 91 Tage laeuft. Der
    # Deckel greift nur ohne taegliches Fenster - mehrtaegige Startwarnungen
    # (NAVAREA, australische und neuseelaendische Meldungen) bleiben unberuehrt.
    if valid_from and valid_to:
        dauer = (valid_to - valid_from).total_seconds() / 3600.0
        taeglich = daily_window_hours((items or {}).get("D"))
        if dauer > STANDING_ORDER_HOURS and not taeglich:
            level = "LOW"
            notes.append(
                "Daueranordnung: {:.0f} Tage durchgehend gueltig, kein "
                "taegliches Fenster".format(dauer / 24.0)
            )
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
    raise ValueError("Could not read CSV: {}".format(last_error))


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
                "{} files need the '{}' package: pip install {}".format(
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


#: Kein Traegersystem zugewiesen.
VEHICLE_NONE = ""
#: Trennzeile im Dropdown - waehlbar, aber ohne Wirkung (siehe _on_vehicle_change).
VEHICLE_SEPARATOR = "__andere_nationen__"
#: Zwei NOTAMs desselben Starts tragen verschiedene Angaben.
MIXED_VALUE = "mixed"
#: Beschriftung des leeren Eintrags.
VEHICLE_NONE_LABEL = "none"


def vehicle_label(
    code: str, vehicles: Optional[pd.DataFrame] = None, with_nation: bool = False
) -> str:
    """
    Beschriftung eines Traegersystems fuer Dropdown und Tabelle.

    Ohne Referenztabelle bleibt der gespeicherte Kuerzel-Code stehen. Steht ein
    zugewiesener Code nicht mehr in der Referenz - weil er im Optionsmenue
    entfernt wurde -, wird das ausgewiesen statt die Zuweisung stillschweigend
    fallen zu lassen.
    """
    if code == VEHICLE_SEPARATOR:
        return "\u2500" * 8 + " other nations " + "\u2500" * 8
    if not code:
        return VEHICLE_NONE_LABEL
    if code == MIXED_VALUE:
        return MIXED_VALUE
    if vehicles is None or vehicles.empty:
        return code
    treffer = vehicles[vehicles["Abk\u00fcrzung"].astype(str) == str(code)]
    if treffer.empty:
        return "{} (no longer in the reference)".format(code)
    zeile = treffer.iloc[0]
    text = "{} ({})".format(zeile["Name"], code)
    if with_nation:
        text = "{} \u00b7 {}".format(text, zeile["Land"])
    return text


def vehicle_nation(event: "LaunchEvent") -> Optional[str]:
    """
    Nation, nach der das Dropdown gestaffelt wird.

    Die festgestellte Startnation zuerst. Steht sie nicht fest - im Review der
    Regelfall, weil ohne Koordinaten keine Zuordnung moeglich ist -, dienen
    Textbeleg und FIR als Behelf, aber nur wenn sie auf eine Zielnation zeigen.
    Das ist allein eine Sortierhilfe und praejudiziert die Zuordnung nicht.
    """
    for kandidat in (event.nation, event.nation_hint, event.fir_country):
        if kandidat and kandidat in TARGET_NATIONS:
            return kandidat
    return None


def vehicle_options(vehicles: pd.DataFrame, nation: Optional[str]) -> List[str]:
    """
    Auswahlliste fuer das Dropdown: erst die Traeger der erkannten Nation,
    darunter durch eine Trennzeile abgesetzt alle uebrigen.

    Eine harte Filterung nach Nation waere falsch: im Review korrigiert man
    gerade eine moeglicherweise falsche Zuordnung und braucht dort die volle
    Liste.
    """
    if vehicles is None or vehicles.empty:
        return [VEHICLE_NONE]
    codes = [str(c) for c in vehicles["Abk\u00fcrzung"]]
    laender = [str(l) for l in vehicles["Land"]]
    eigene = [c for c, land in zip(codes, laender) if nation and land == nation]
    andere = [c for c, land in zip(codes, laender) if not (nation and land == nation)]
    optionen = [VEHICLE_NONE] + eigene
    if eigene and andere:
        optionen.append(VEHICLE_SEPARATOR)
    return optionen + andere


def apply_manual_attribute(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    assignments: Dict[str, str],
    attribut: str,
) -> None:
    """
    Traegt eine von Hand gesetzte Angabe in Events und Starts ein.

    Gespeichert wird je NOTAM, weil dessen Schluessel ueber Sitzungen hinweg
    stabil ist - die Start-Kennung (START-01) ist es nicht. Gehoeren mehrere
    NOTAMs zu einem erkannten Start, gilt die Angabe fuer den ganzen Start und
    wird auf die uebrigen Sperrzonen uebertragen. Widersprechen sich zwei
    gespeicherte Angaben - moeglich, wenn eine spaetere Gruppierung zwei zuvor
    getrennte Starts zusammenfasst -, behaelt jedes NOTAM seine eigene und der
    Start wird als uneinheitlich ausgewiesen.

    Traegersystem und Nutzlast verhalten sich hier gleich; sie unterscheiden
    sich nur in der Eingabe (Auswahlliste gegen Freitext).
    """
    for event in events:
        setattr(event, attribut, str(assignments.get(event.key, "") or ""))
    per_row = {e.row_index: e for e in events}
    for group in groups:
        # Vorankuendigungen gehoeren zum Start, auch wenn sie nicht als Zone
        # zaehlen: wer das Traegersystem auf deren Zeile waehlt, meint denselben
        # Start, und umgekehrt muss die Angabe sie erreichen.
        mitglieder = [
            per_row[r]
            for r in list(group.row_indices) + list(group.advance_row_indices)
            if r in per_row
        ]
        gesetzt: List[str] = []
        for m in mitglieder:
            wert = getattr(m, attribut)
            if wert and wert not in gesetzt:
                gesetzt.append(wert)
        if not gesetzt:
            setattr(group, attribut, "")
        elif len(gesetzt) == 1:
            setattr(group, attribut, gesetzt[0])
            for m in mitglieder:
                setattr(m, attribut, gesetzt[0])
        else:
            setattr(group, attribut, MIXED_VALUE)


def mark_site_alternatives(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    spaceports: pd.DataFrame,
) -> int:
    """
    Vermerkt bei jedem Start, ob sein Platz nicht unterscheidbare Nachbarn hat.

    Eigener Durchgang statt ein Vermerk an jeder Stelle, die einen Startplatz
    setzt - davon gibt es mehrere, und eine vergessene waere ein stiller Fehler.
    Rueckgabe: Zahl der Starts mit Nachbarplaetzen.
    """
    betroffen = 0
    for group in groups:
        # Nur beim ersten Durchgang: danach steht hier moeglicherweise schon
        # eine Handentscheidung, und die darf den Urzustand nicht ueberschreiben.
        if not group.auto_spaceport_code and group.spaceport_code:
            group.auto_spaceport_code = group.spaceport_code
        group.site_alternatives = site_alternatives_for(group.spaceport_code, spaceports)
        if group.site_alternatives:
            betroffen += 1
    for event in events:
        event.site_alternatives = site_alternatives_for(event.spaceport_code, spaceports)
    return betroffen


def apply_launch_site_assignments(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    spaceports: pd.DataFrame,
    assignments: Dict[str, str],
) -> None:
    """
    Traegt eine von Hand gesetzte Startplatzwahl ein und schreibt sie durch.

    Sinnvoll nur bei nebeneinanderliegenden Plaetzen: dort kann die Geometrie
    nicht entscheiden, also entscheidet der Benutzer. Die Wahl ueberschreibt
    Kuerzel, Name und Koordinaten des Starts und aller seiner NOTAMs.

    Azimut und Inklination werden NICHT neu gerechnet. Der Unterschied liegt
    bei 0,06 bis 0,22 Grad und damit weit unter der Genauigkeit der
    Abschaetzung, die ihre Inklination selbst nur auf wenige Grad angibt. Eine
    Neurechnung erzeugte Scheingenauigkeit und wuerde zwei Zahlen fuer dieselbe
    Bahn liefern, je nachdem ob das Pad gesetzt wurde.
    """
    apply_manual_attribute(events, groups, assignments, "launch_site")
    nach_kurzel = {str(r["Kurzel"]): r for _, r in spaceports.iterrows()}
    per_row = {e.row_index: e for e in events}
    for group in groups:
        wahl = group.launch_site
        if wahl == MIXED_VALUE or (wahl and wahl not in nach_kurzel):
            continue
        # Keine Wahl mehr: zurueck auf das, was die Geometrie ergeben hatte.
        # Ohne diesen Zweig bliebe eine zurueckgenommene Wahl stehen.
        ziel = wahl or group.auto_spaceport_code
        if not ziel or ziel not in nach_kurzel or ziel == group.spaceport_code:
            continue
        row = nach_kurzel[ziel]
        group.spaceport_code = str(row["Kurzel"])
        group.spaceport_name = str(row["Name"])
        group.spaceport_lat = float(row["Latitude"])
        group.spaceport_lon = float(row["Longitude"])
        for r in list(group.row_indices) + list(group.advance_row_indices):
            event = per_row.get(r)
            if event is None:
                continue
            event.spaceport_code = group.spaceport_code
            event.spaceport_name = group.spaceport_name
            event.spaceport_lat = group.spaceport_lat
            event.spaceport_lon = group.spaceport_lon
    # Die Wahl kann den Platz veraendert haben - die Nachbarschaft neu vermerken.
    mark_site_alternatives(events, groups, spaceports)


def launch_site_history(
    archiv: Optional[pd.DataFrame],
    vehicle: str,
    code: Optional[str],
    spaceports: pd.DataFrame,
) -> str:
    """
    Was das eigene Archiv ueber dieses Traegersystem sagt.

    Bewusst eine Rechnung auf den eigenen Daten statt einer Tabelle im Code:
    welche Rakete von welchem Pad fliegt, ist keine Eigenschaft der Rakete,
    sondern eine Momentaufnahme der Praxis. CZ-8 flog von Anfang an von beiden
    Wenchang-Gelaenden. Eine fest verdrahtete Zuordnung wuerde veralten, und
    zwar unbemerkt - diese Zaehlung verschiebt sich stattdessen sichtbar.

    Ein Hinweis, keine Vorgabe: gesetzt wird nichts.

    Eine Schieflage gehoert dazugesagt: der nachrangige Platz einer
    Nachbarschaftsgruppe kann nur von Hand gesetzt worden sein, denn die
    Geometrie waehlt ihn nie. Der erstverzeichnete kann dagegen auch bedeuten,
    dass das Pad nie bestimmt wurde. Beim ersten Durchlauf sagt die Zaehlung
    deshalb noch nichts - sie verdient sich die Aussage.
    """
    if archiv is None or archiv.empty or not vehicle or not code:
        return ""
    if not {"Trägersystem", "Weltraumbahnhof"} <= set(archiv.columns):
        return ""
    gruppe = co_located_groups(spaceports).get(code, ())
    if not gruppe:
        return ""
    passend = archiv[archiv["Trägersystem"].astype(str).str.strip() == str(vehicle).strip()]
    if passend.empty:
        return ""
    zaehler: Dict[str, int] = {}
    for wert in passend["Weltraumbahnhof"].astype(str).str.strip():
        if wert:
            zaehler[wert] = zaehler.get(wert, 0) + 1
    if not zaehler:
        return ""
    teile = ", ".join(
        "{}x {}".format(n, k) for k, n in sorted(zaehler.items(), key=lambda p: (-p[1], p[0]))
    )
    satz = "Your archive: {} flew {}.".format(vehicle, teile)
    # Nur der erstverzeichnete Platz der Gruppe kann "nicht bestimmt" meinen.
    vorrangig = gruppe[0]
    if zaehler.get(vorrangig):
        satz += " {} may also mean the pad was never determined.".format(vorrangig)
    return satz


def apply_vehicle_assignments(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    assignments: Dict[str, str],
) -> None:
    """Manuell gewaehlte Traegersysteme uebernehmen."""
    apply_manual_attribute(events, groups, assignments, "vehicle")


def apply_payload_assignments(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    assignments: Dict[str, str],
) -> None:
    """Manuell eingetragene Nutzlasten uebernehmen."""
    apply_manual_attribute(events, groups, assignments, "payload")


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
#: Archiv der erkannten Starts - anders als die drei Referenzen oben wird diese
#: Datei nicht eingelesen, sondern von der Anwendung selbst fortgeschrieben.
ARCHIVE_CSV = APP_DIR / "startarchiv_updated.csv"


def is_public_deployment(app_dir: Path = APP_DIR) -> bool:
    """
    Laeuft die Anwendung als oeffentliche Fassung?

    Streamlit Community Cloud legt die Repositories unter /mount/src ab. Dort
    darf der Archiv-Import nicht erscheinen, solange es keinen Demo-Modus gibt.
    """
    return Path(app_dir).resolve().parts[:3] == ("/", "mount", "src")


def is_local_request(host: Optional[str]) -> bool:
    """
    Kommt die Anfrage nachweislich vom eigenen Rechner?

    Fail-closed: fehlt der Host-Header oder ist er unklar, gilt sie als nicht
    lokal. Ein Aufruf ueber die IP im Heimnetz zaehlt bewusst nicht dazu.
    """
    if not host:
        return False
    host = host.strip().lower()
    if host.startswith("["):
        name = host[1:].split("]", 1)[0]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in ("localhost", "127.0.0.1", "::1")


def import_gate(app_dir: Path, host: Optional[str], peer_is_loopback: bool) -> bool:
    """
    Reine Entscheidung fuer den Archiv-Import - alle drei Bedingungen zugleich.

    Der Host-Header allein genuegt nicht: Streamlit lauscht auf allen
    Schnittstellen, ein Skript im Heimnetz kann <LAN-IP>:8501 ansprechen und
    dabei "Host: localhost" senden. Deshalb muss auch die TCP-Gegenstelle der
    eigene Rechner sein. Hinter einem Cloud-Proxy koennte die Gegenstelle
    selbst lokal aussehen - darum bleiben /mount/src und Host als Bedingung.
    """
    return (
        not is_public_deployment(app_dir)
        and peer_is_loopback is True
        and is_local_request(host)
    )


def archive_import_allowed() -> bool:
    """Reiter nur lokal: nicht unter /mount/src, Host localhost, Gegenstelle Loopback."""
    if is_public_deployment():
        return False
    try:
        # ohne Laufzeit (Tests, bare mode) gibt es keinen Host - verborgen,
        # und st.context wird gar nicht erst angefasst (sonst Warnung)
        if not st.runtime.exists():
            return False
        host = st.context.headers.get("Host")
        # Streamlit 1.50 liefert ip_address = None genau dann, wenn Tornados
        # remote_ip 127.0.0.1 oder ::1 ist. Streamlit schaltet xheaders nicht
        # ein, remote_ip ist also die echte TCP-Gegenstelle und laesst sich
        # nicht per X-Forwarded-For/X-Real-IP faelschen. (Ohne Anfrage ist es
        # ebenfalls None - dann fehlt aber auch der Host, und es bleibt zu.)
        peer_lokal = st.context.ip_address is None
    except Exception:  # ohne Laufzeit/Kontext: verborgen
        return False
    return import_gate(APP_DIR, host, peer_lokal)
#: Protokoll der Starts von beweglichen Seeplattformen. Wie das Archiv von der
#: Anwendung geschrieben, nicht eingelesen.
SEA_LAUNCH_CSV = APP_DIR / "seestarts_updated.csv"

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
    vehicle_assignments: Optional[Dict[str, str]] = None,
    payload_assignments: Optional[Dict[str, str]] = None,
    launch_site_assignments: Optional[Dict[str, str]] = None,
    archiv_removed: Sequence[str] = (),
    restored: Sequence[str] = (),
    seestarts_removed: Sequence[str] = (),
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
                    "vehicle_assignments": {
                        k: v
                        for k, v in sorted((vehicle_assignments or {}).items())
                        if v
                    },
                    "payload_assignments": {
                        k: v
                        for k, v in sorted((payload_assignments or {}).items())
                        if v
                    },
                    "launch_site_assignments": {
                        k: v
                        for k, v in sorted((launch_site_assignments or {}).items())
                        if v
                    },
                    "archiv_removed": sorted(archiv_removed),
                    "restored_events": sorted(restored),
                    "seestarts_removed": sorted(seestarts_removed),
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
    orbit_type: str = ORBIT_UNKNOWN
    altitude_profile: str = "-"
    confidence_score: int = 0
    confidence_level: str = "LOW"
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
    auto_hidden_reason: str = ""
    vehicle: str = ""
    payload: str = ""
    #: Von Hand gewaehlter Startplatz. Nur dort sinnvoll, wo Plaetze so nah
    #: beieinanderliegen, dass die Geometrie nicht entscheiden kann.
    launch_site: str = ""
    #: Nachbarplaetze des zugeordneten Platzes, die nicht unterscheidbar sind.
    site_alternatives: List[str] = field(default_factory=list)

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

#: Bis zu dieser Entfernung gilt eine geratene FIR als Beleg dafuer, dass die
#: Zone im Luftraum dieser Nation liegt.
#:
#: Die Referenz kennt keine FIR-Grenzen, nur den Sitz der Bezirkszentrale.
#: Naehe ist damit ein Behelf - aber ein brauchbarer, solange er eng bleibt.
#: Gemessen: eine Zone im Suedchinesischen Meer liegt 213 km von Sanya, die
#: US-Inlandsfaelle der Echtdatei 477-541 km von ihrer Zentrale. Eine Zone
#: ueber Nicaragua liegt 1460 km von Miami und wurde bisher als US-Luftraum
#: gewertet - daraus wurde ein Start von Cape Canaveral. 800 km liegen
#: oberhalb aller belegten Echtfaelle und deutlich unter dem Fehlfall.
#:
#: Darueber hinaus wird die FIR weiterhin gefunden und angezeigt, sie belegt
#: dann aber keine Staatszugehoerigkeit mehr.
FIR_OWN_AIRSPACE_KM = 800.0

#: Wie eine FIR zugeordnet wurde. Feste Marken, keine Prosa: der weitere Ablauf
#: verzweigt danach, und ein uebersetzter Satz haette diese Verzweigung still
#: ausgehebelt. Der Anzeigetext steht getrennt in FIR_METHOD_LABELS.
FIR_BY_ICAO = "icao"
FIR_BY_TEXT = "text"
FIR_BY_GEOMETRY = "geo"
FIR_OUTSIDE = "outside"
FIR_TOO_FAR = "too_far"
FIR_NONE = "-"

FIR_METHOD_LABELS = {
    FIR_BY_ICAO: "ICAO code",
    FIR_BY_TEXT: "named in the text",
    FIR_BY_GEOMETRY: "nearest FIR",
    FIR_NONE: "-",
}


def fir_method_label(method: str, detail: str = "") -> str:
    """Anzeigetext zu einer Zuordnungsmarke."""
    if method == FIR_OUTSIDE:
        return "outside the target nations ({})".format(detail) if detail else "outside"
    if method == FIR_TOO_FAR:
        return "too far from any target FIR ({})".format(detail) if detail else "too far"
    return FIR_METHOD_LABELS.get(method, method)


#: US-Bezirkszentralen tragen dreibuchstabige Kennungen (ZLA, ZOA, ZAB ...),
#: keine vierbuchstabigen ICAO-Codes. RE_ICAO verlangt genau vier Buchstaben -
#: damit waren 21 Zeilen der FIR-Referenz ueber den expliziten Weg nie
#: erreichbar, und jedes US-Inlands-NOTAM fiel still auf die Geometrie zurueck.
#: Das Muster bleibt eng: nur Z plus zwei Buchstaben, damit nicht jedes
#: dreibuchstabige Wort im Freitext (ACT, SFC, UNL, GND) als Luftraum gilt.
RE_ARTCC = re.compile(r"\bZ[A-Z]{2}\b")


def _luftraum_kennungen(text: str) -> List[str]:
    """Explizit genannte Luftraum-Kennungen: vierstellige ICAO plus US-ARTCC."""
    upper = (text or "").upper()
    return RE_ICAO.findall(upper) + RE_ARTCC.findall(upper)


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
        explicit += _luftraum_kennungen(str(fir_hint))
    if items.get("A"):
        explicit += _luftraum_kennungen(items["A"])
    q_line = items.get("Q", "")
    if q_line:
        explicit += _luftraum_kennungen(q_line.split("/")[0])

    for code in explicit:
        if code in known:
            return firs.loc[known[code]], FIR_BY_ICAO
    if explicit:
        return None, "{}:{}".format(FIR_OUTSIDE, explicit[0])

    for code in _luftraum_kennungen(text or ""):
        if code in known:
            return firs.loc[known[code]], FIR_BY_TEXT

    if centroid is not None and len(firs):
        distances = firs.apply(
            lambda r: haversine_km(centroid[0], centroid[1], r["Latitude"], r["Longitude"]),
            axis=1,
        )
        if distances.min() <= MAX_FIR_FALLBACK_KM:
            return firs.loc[distances.idxmin()], FIR_BY_GEOMETRY
        return None, "{}:{:.0f} km".format(FIR_TOO_FAR, distances.min())

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


# --- Nebeneinanderliegende Startplaetze -------------------------------------
#
# Wenchang hat zwei Startgelaende: die staatlichen Pads und den kommerziellen
# Platz unmittelbar noerdlich davon. Sie liegen 1,92 km auseinander. Der Azimut
# zu einer Dropzone unterscheidet sich dadurch um 0,06 bis 0,22 Grad - bei
# einer Auswahlschwelle von 15 Grad.
#
# Die Startplatzwahl rechnet "Streuung x 100 + mittlere Entfernung". Bei diesem
# Abstand entscheidet also verhundertfachtes Rauschen. Gemessen an vier
# realistischen Startkorridoren kippte das Ergebnis zwischen den beiden
# Plaetzen je nach Dropzone-Muster - zwei Starts derselben Rakete vom selben
# Pad waeren auf verschiedene Plaetze gebucht worden.
#
# Deshalb darf die Geometrie zwischen solchen Plaetzen nie entscheiden. Der
# zuerst verzeichnete bleibt automatisch waehlbar, spaeter danebengelegte nur
# von Hand oder bei ausdruecklicher Nennung im NOTAM-Text.

#: Ab diesem Abstand gelten zwei Plaetze derselben Nation als unterscheidbar.
#:
#: Gemessen an der Referenz: engstes Paar 1,92 km (WSLC/HAIN), naechstes
#: 10,45 km (KXMR/KTTS). Die Schwelle sitzt in dieser Luecke. Die Floridagruppe
#: bei 10 bis 20 km ist mit 0,3 bis 2,3 Grad ebenfalls schwach getrennt; sie
#: bleibt bewusst unberuehrt, weil dort keine bestehende Zuordnung zur Debatte
#: steht und eine Aenderung Zuordnungen betreffen wuerde, die niemand in Frage
#: gestellt hat.
CO_LOCATED_SITE_KM = 5.0


@lru_cache(maxsize=16)
def _co_located_from_rows(
    rows: Tuple[Tuple[str, float, float, str], ...]
) -> Dict[str, Tuple[str, ...]]:
    """Rechnet die Nachbarschaftsgruppen; getrennt wegen des Zwischenspeichers."""
    gruppen: List[List[int]] = []
    for pos, (_kurzel, lat, lon, land) in enumerate(rows):
        ziel: Optional[int] = None
        for nummer, mitglieder in enumerate(gruppen):
            for m in mitglieder:
                _k2, lat2, lon2, land2 = rows[m]
                if land2 != land:
                    continue
                if surface_distance_km(lat, lon, lat2, lon2) <= CO_LOCATED_SITE_KM:
                    ziel = nummer
                    break
            if ziel is not None:
                break
        if ziel is None:
            gruppen.append([pos])
        else:
            gruppen[ziel].append(pos)

    ergebnis: Dict[str, Tuple[str, ...]] = {}
    for mitglieder in gruppen:
        if len(mitglieder) < 2:
            continue
        kuerzel = tuple(rows[m][0] for m in mitglieder)
        for k in kuerzel:
            ergebnis[k] = kuerzel
    return ergebnis


def co_located_groups(spaceports: pd.DataFrame) -> Dict[str, Tuple[str, ...]]:
    """
    Startplaetze, die zu nah beieinanderliegen, um sie an der Geometrie der
    Sperrzonen zu unterscheiden.

    Rueckgabe: je Kuerzel die Kuerzel seiner ganzen Gruppe, in der Reihenfolge
    der Referenz. Das erste ist der automatisch waehlbare. Plaetze ohne Nachbarn
    kommen nicht vor.
    """
    if spaceports is None or spaceports.empty:
        return {}
    rows = tuple(
        (str(r["Kurzel"]), float(r["Latitude"]), float(r["Longitude"]), str(r["Land"]))
        for _, r in spaceports.iterrows()
    )
    return _co_located_from_rows(rows)


def _auto_selectable(spaceports: pd.DataFrame) -> pd.DataFrame:
    """Die Plaetze, unter denen die Geometrie waehlen darf."""
    gruppen = co_located_groups(spaceports)
    nachrangig = {k for k, mitglieder in gruppen.items() if mitglieder[0] != k}
    if not nachrangig:
        return spaceports
    return spaceports[~spaceports["Kurzel"].isin(nachrangig)]


def site_alternatives_for(
    code: Optional[str], spaceports: pd.DataFrame
) -> List[str]:
    """Nachbarplaetze eines Startplatzes - leer, wenn er allein steht."""
    if not code:
        return []
    return [k for k in co_located_groups(spaceports).get(code, ()) if k != code]


def site_separation_km(codes: Sequence[str], spaceports: pd.DataFrame) -> float:
    """Groesster Abstand innerhalb einer Nachbarschaftsgruppe, in Kilometern."""
    punkte = [
        (float(r["Latitude"]), float(r["Longitude"]))
        for _, r in spaceports.iterrows()
        if str(r["Kurzel"]) in set(codes)
    ]
    weit = 0.0
    for i in range(len(punkte)):
        for j in range(i + 1, len(punkte)):
            weit = max(weit, surface_distance_km(*punkte[i], *punkte[j]))
    return weit


def _restrict_candidates(
    spaceports: pd.DataFrame, nations: Sequence[str], hint: Sequence[str]
) -> pd.DataFrame:
    """
    Schraenkt die Startplatz-Auswahl ein: zuerst auf die im Text genannten
    Startplaetze, sonst auf die Kandidaten-Nationen.

    Nebeneinanderliegende Plaetze sind von der automatischen Wahl ausgenommen -
    siehe CO_LOCATED_SITE_KM. Nennt der Text einen davon ausdruecklich, gilt er
    trotzdem: der Text ist die staerkere Quelle als die Geometrie.
    """
    candidates = _auto_selectable(spaceports)
    if nations:
        gefiltert = candidates[candidates["Land"].isin(list(nations))]
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
                "{} is closer ({:.0f} km) but would imply azimuth {:.0f}° "
                "(westward launch) - rejected.".format(
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
        return RELIABILITY_LOW
    if distance_km <= NEAR_ZONE_KM:
        return RELIABILITY_HIGH
    if distance_km <= FAR_ZONE_KM:
        return RELIABILITY_MEDIUM
    return RELIABILITY_LOW

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
    orbit_type: str = ORBIT_UNKNOWN
    max_range_km: Optional[float] = None
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None
    confidence_level: str = "LOW"
    reliability: str = "-"
    kind: str = KIND_LAUNCH
    manual_override: bool = False
    vehicle: str = ""
    payload: str = ""
    #: Startpunkt aus der Geometrie abgeleitet statt aus der Referenz genommen.
    site_from_geometry: bool = False
    #: Meldungen, die denselben Luftraum vor dem Starttag reserviert haben.
    #: Sie zaehlen nicht als Sperrzonen: es ist dieselbe Flaeche, nicht eine
    #: weitere. Bahn, Streuung und Startplatz bleiben davon unberuehrt.
    advance_notam_ids: List[str] = field(default_factory=list)
    #: Deren Tabellenzeilen. Getrennt von row_indices, weil zone_count daraus
    #: zaehlt - in die Zonenzahl gehoeren sie nicht, in die startweite
    #: Zuweisung von Traegersystem und Nutzlast aber doch.
    advance_row_indices: List[int] = field(default_factory=list)
    #: Frueheste Gueltigkeit dieser Meldungen.
    advance_from: Optional[datetime] = None
    #: Von Hand gewaehlter Startplatz, siehe CO_LOCATED_SITE_KM.
    launch_site: str = ""
    #: Der Platz, den die Geometrie gewaehlt hat - vor jeder Handentscheidung.
    #: Wird gebraucht, um eine zurueckgenommene Wahl wieder aufzuloesen, ohne
    #: sich darauf zu verlassen, dass der Aufrufer die Gruppe neu baut.
    auto_spaceport_code: str = ""
    #: Nachbarplaetze, die die Geometrie nicht von diesem unterscheiden kann.
    site_alternatives: List[str] = field(default_factory=list)

    @property
    def zone_count(self) -> int:
        return len(self.row_indices)

    @property
    def site_determined(self) -> bool:
        """
        Steht fest, von welchem Pad gestartet wurde?

        Ohne Nachbarplaetze ist nichts zu bestimmen - dann ja. Mit Nachbarn nur
        dann, wenn es von Hand gesetzt wurde. Die Geometrie zaehlt hier nicht
        als Beleg: 1,92 km Abstand ergeben 0,06 bis 0,22 Grad Azimutunterschied.
        """
        return not self.site_alternatives or bool(self.launch_site)

    @property
    def advance_notice_hours(self) -> Optional[float]:
        """Vorlauf zwischen der Ankuendigung und dem Startfenster, in Stunden."""
        if self.advance_from is None or self.window_from is None:
            return None
        return (self.window_from - self.advance_from).total_seconds() / 3600.0

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

    # Seestart: ergibt der Cluster von einem abgeleiteten Startpunkt aus eine
    # schluessige Bahn, darf er nicht zerlegt werden. Sonst entfernt der
    # Splitter genau das NOTAM, das den Startpunkt beschreibt - gemessen am
    # chinesischen Fall vom 22.07.2026: von der Plattform aus 3,5 Grad
    # Streuung, vom naechsten verzeichneten Platz aus 19 Grad. Der Splitter
    # sah nur die 19 und warf die Plattform hinaus.
    abgeleitet = derive_launch_point(events, spaceports)
    if abgeleitet is not None and abgeleitet[3] <= SEA_LAUNCH_MAX_SPREAD_DEG:
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
                        "Shared track with {} further NOTAM(s) of the same launch "
                        "({}, azimuth spread {:.1f}°).".format(
                            len(subcluster) - 1, group.group_id, group.azimuth_spread_deg
                        )
                    )
            groups.append(group)
    return groups


# --- Vorankuendigungen ------------------------------------------------------
#
# Vor einem Start wird derselbe Luftraum oft Tage vorher reserviert: eine
# mehrtaegige Meldung mit taeglichem Fenster, dann am Starttag eine kurze
# Meldung fuer dieselbe Flaeche. Beide beschreiben eine Aktivitaet, nicht zwei.
#
# Gepaart wird nicht ueber den Text, sondern ueber Geometrie und Zeit. Der Text
# hilft hier nicht: die Vorankuendigungen des chinesischen Seestarts vom
# 22.07.2026 sind in taiwanesischem und japanischem Luftraum veroeffentlicht,
# nennen weder China noch einen Startplatz, und landeten deshalb zu Recht im
# Review - die Drittstaaten-Regel laesst keine geratene Nation zu.
#
# Gemessen an genau diesem Fall:
#   Vorankuendigung Taiwan <-> Starttag Taiwan     0,91 km   Zonen 44 / 45 km
#   Vorankuendigung Japan  <-> Starttag Japan      1,20 km   Zonen 52 / 52 km
#   naechster Nicht-Treffer                      328,44 km
# Die Mittelpunkte liegen auf zwei Prozent des Zonenradius zusammen. Das ist
# kein Zufall, sondern dieselbe im Text ausbuchstabierte Flaeche.

#: Zulaessiger Versatz der Zonenmittelpunkte, als Anteil der kleineren Zone.
#: Relativ, nicht absolut: eine 500-km-Dropzone vertraegt mehr Versatz als ein
#: 20-km-Kreis. Ein fester Kilometerwert waere dem einen zu eng, dem anderen
#: zu weit. 0,25 laesst dem Messfall (0,02) Faktor zwoelf Luft.
ADVANCE_ZONE_OFFSET_SHARE = 0.25

#: So aehnlich gross muessen die Zonen sein. Haelt die kleinere nicht mindestens
#: diesen Anteil der groesseren, beschreiben sie nicht dieselbe Flaeche - ein
#: 20-km-Startkreis mitten in einer 500-km-Dropzone ist keine Paarung.
ADVANCE_ZONE_SIZE_SHARE = 0.6

#: So viel laenger muss die Ankuendigung laufen als das Fenster, das sie
#: ankuendigt. Ohne diesen Abstand wuerde eine zweite kurze Meldung desselben
#: Starts als dessen eigene Vorankuendigung gelten. Im Messfall: Faktor 240.
ADVANCE_MIN_DURATION_FACTOR = 4.0

#: Und mindestens so lange. Was nur Stunden vorher kommt, kuendigt nichts an,
#: sondern gehoert zum Starttag - und wird schon von der Zeitgruppierung erfasst.
ADVANCE_MIN_DURATION_HOURS = 24.0


def event_zone_shapes(
    event: "LaunchEvent",
) -> List[Tuple[float, float, float]]:
    """
    Mittelpunkt und Ausdehnung jeder Zone eines NOTAMs, in Kilometern.

    Die Ausdehnung ist der weiteste Eckpunkt vom Mittelpunkt. Ein Kreis-NOTAM
    hat nur einen Punkt und damit die Ausdehnung null - dort steht der Radius
    im Text und wird eingesetzt.
    """
    formen: List[Tuple[float, float, float]] = []
    for zone in event.zones:
        if not zone:
            continue
        lat, lon = polygon_centroid(zone)
        weite = max(
            (surface_distance_km(lat, lon, p[0], p[1]) for p in zone), default=0.0
        )
        if weite < 1e-6 and event.radius_km:
            weite = float(event.radius_km)
        formen.append((lat, lon, weite))
    return formen


def zones_congruent(
    a: Tuple[float, float, float], b: Tuple[float, float, float]
) -> bool:
    """Beschreiben zwei Zonen dieselbe Flaeche?"""
    klein, gross = sorted((a[2], b[2]))
    if gross <= 0.0 or klein < gross * ADVANCE_ZONE_SIZE_SHARE:
        return False
    return surface_distance_km(a[0], a[1], b[0], b[1]) <= klein * ADVANCE_ZONE_OFFSET_SHARE


def window_within_daily(
    von: Optional[datetime], bis: Optional[datetime], d_item: Optional[str]
) -> bool:
    """
    Liegt ein Startfenster innerhalb eines taeglichen Fensters des D-Items?

    Nennt das D-Item kein lesbares Fenster, schraenkt es nichts ein und die
    Antwort ist True - die Pruefung faellt dann auf die uebrigen Bedingungen
    zurueck. Fenster ueber Mitternacht werden auf einer Zweitageslinie
    verglichen, damit "DLY BTN 1700/0400" ein Fenster um 02:45 einschliesst.
    """
    fenster = daily_windows(d_item)
    if not fenster:
        return True
    if von is None or bis is None:
        return False
    tag = 24 * 60
    start = von.hour * 60 + von.minute
    ende = bis.hour * 60 + bis.minute
    if ende < start:
        ende += tag
    for f_start, f_ende in fenster:
        if f_ende <= f_start:
            f_ende += tag
        for versatz in (0, tag):
            if f_start <= start + versatz and ende + versatz <= f_ende:
                return True
    return False


def is_advance_announcement(
    event: "LaunchEvent",
    group: "LaunchGroup",
    group_shapes: Sequence[Tuple[float, float, float]],
) -> bool:
    """
    Kuendigt dieses NOTAM den Start dieser Gruppe voraus an?

    Sechs Bedingungen, alle sprachfrei, alle muessen zutreffen:

    1. Die Nation des Starts muss unter den Kandidaten der Meldung sein. Die
       Paarung darf die Drittstaaten-Regel nicht aushebeln, sondern nur das
       tun, was Gruppierung auch sonst tut: eine zulaessige Kandidatin belegen.
    2. Die Meldung laeuft mindestens einen Tag.
    3. ... und ein Mehrfaches des Startfensters, das sie ankuendigt.
    4. Das Startfenster liegt vollstaendig in ihrer Laufzeit.
    5. Nennt sie ein taegliches Fenster, liegt das Startfenster darin.
    6. Mindestens eine ihrer Zonen ist deckungsgleich mit einer Zone des Starts.
    """
    if group.window_from is None or event.valid_from is None or event.valid_to is None:
        return False
    if group.nation and group.nation not in event.candidate_nations:
        return False

    dauer = _duration_hours(event)
    if dauer < ADVANCE_MIN_DURATION_HOURS:
        return False
    bis = group.window_to or group.window_from
    fenster_h = (bis - group.window_from).total_seconds() / 3600.0
    if dauer < max(fenster_h, 0.0) * ADVANCE_MIN_DURATION_FACTOR:
        return False

    if not (event.valid_from <= group.window_from and bis <= event.valid_to):
        return False
    if not window_within_daily(
        group.window_from, bis, extract_items(event.raw_text).get("D")
    ):
        return False

    return any(
        zones_congruent(eigen, fremd)
        for eigen in event_zone_shapes(event)
        for fremd in group_shapes
    )


def pair_advance_announcements(
    events: Sequence["LaunchEvent"], groups: Sequence["LaunchGroup"]
) -> List["LaunchEvent"]:
    """
    Haengt Vorankuendigungen an den Start, den sie ankuendigen.

    Laeuft nach der Gruppierung und aendert an ihr nichts: die angekuendigte
    Flaeche ist dieselbe wie die Sperrzone am Starttag, also waere sie als
    zusaetzliche Zone eine Doppelzaehlung. Startplatz, Azimut, Streuung und
    Zonenzahl des Starts bleiben unberuehrt; die Meldung erhaelt die Nation und
    den Startplatz der Gruppe und verlaesst damit das Review.

    Eindeutigkeit ist Bedingung: passt eine Meldung auf zwei Starts, bleibt sie
    liegen. Eine falsche Zuordnung waegt in diesem Programm schwerer als ein
    Fall mehr zur Durchsicht.

    Automatisch ausgeblendete Meldungen bleiben ausgeblendet - diese Liste ist
    die Kuration des Benutzers, nicht ein Zwischenergebnis.
    """
    starts = [g for g in groups if g.spaceport_code and g.window_from is not None]
    if not starts:
        return []

    formen: Dict[str, List[Tuple[float, float, float]]] = {g.group_id: [] for g in starts}
    for event in events:
        if event.launch_group in formen:
            formen[event.launch_group].extend(event_zone_shapes(event))

    gepaart: List["LaunchEvent"] = []
    for event in events:
        if event.launch_group or event.status != "REVIEW":
            continue
        if event.auto_hidden_reason or not event.zones:
            continue
        treffer = [
            g for g in starts if is_advance_announcement(event, g, formen[g.group_id])
        ]
        if len(treffer) != 1:
            continue

        group = treffer[0]
        event.launch_group = group.group_id
        event.status = "OK"
        event.kind = KIND_ADVANCE
        event.nation = event.nation or group.nation
        event.spaceport_code = group.spaceport_code
        event.spaceport_name = group.spaceport_name
        event.spaceport_lat = group.spaceport_lat
        event.spaceport_lon = group.spaceport_lon
        event.review_reason = ""
        event.requires_group = False
        vorlauf = (group.window_from - event.valid_from).total_seconds() / 3600.0
        event.assignment_note = (
            "Advance notice for {}: the same airspace was already reserved "
            "{:.0f} h before the launch window ({}).".format(
                group.group_id, vorlauf, event.launch_window
            )
        )
        group.advance_notam_ids.append(event.notam_id)
        group.advance_row_indices.append(event.row_index)
        if group.advance_from is None or event.valid_from < group.advance_from:
            group.advance_from = event.valid_from
        gepaart.append(event)
    return gepaart


#: Ein Startpunkt-Kreis ist klein: die Sperrzone um eine Startplattform misst
#: wenige Dutzend Kilometer. Eine Dropzone ist deutlich groesser.
SEA_LAUNCH_MAX_RADIUS_KM = 60.0

#: So eng muessen die uebrigen Zonen von diesem Punkt aus beieinanderliegen,
#: damit sie eine gemeinsame Bahn beschreiben.
SEA_LAUNCH_MAX_SPREAD_DEG = 15.0

#: Erst ab diesem Abstand zum naechsten bekannten Startplatz wird ueberhaupt
#: abgeleitet. Darunter erklaert die Referenz den Start besser als eine
#: Schaetzung aus drei Zonen.
SEA_LAUNCH_MIN_SITE_DISTANCE_KM = 150.0

#: Zonen naeher als das gelten als Teil des Startgebiets, nicht als Ziel einer
#: Bahn - ihr Azimut waere Rauschen.
SEA_LAUNCH_MIN_ZONE_DISTANCE_KM = 50.0

#: Um so viel besser muss die abgeleitete Bahn sein, damit sie die Referenz
#: schlaegt. Ohne diesen Abstand wuerde schon Messrauschen den Startplatz
#: austauschen.
SEA_LAUNCH_SPREAD_MARGIN_DEG = 5.0


def sea_launch_code(lat: float, lon: float) -> str:
    """
    Kennung eines abgeleiteten Startpunkts, z.B. SEA-31N124E.

    Die Position steckt in der Kennung, damit kein Verzeichnis gepflegt werden
    muss und zwei Starts von derselben Stelle dieselbe Kennung bekommen.
    """
    return "SEA-{:.0f}{}{:.0f}{}".format(
        abs(lat), "N" if lat >= 0 else "S", abs(lon), "E" if lon >= 0 else "W"
    )


def cluster_zone_points(
    cluster: Sequence["LaunchEvent"],
) -> List[Tuple[float, float, "LaunchEvent"]]:
    """
    Alle Zonenmittelpunkte eines Clusters - nicht einer je NOTAM.

    Ein NOTAM kann mehrere getrennte Gebiete beschreiben; sein Gesamtzentroid
    liegt dann zwischen ihnen und beschreibt keinen Ort. Fuer die Geometrie
    zaehlt jede Zone fuer sich.
    """
    punkte: List[Tuple[float, float, "LaunchEvent"]] = []
    for event in cluster:
        if event.zones:
            for zone in event.zones:
                lat, lon = polygon_centroid(zone)
                punkte.append((lat, lon, event))
        elif event.centroid_lat is not None and event.centroid_lon is not None:
            punkte.append((event.centroid_lat, event.centroid_lon, event))
    return punkte


def derive_launch_point(
    cluster: Sequence["LaunchEvent"], spaceports: pd.DataFrame
) -> Optional[Tuple[float, float, float, float, "LaunchEvent"]]:
    """
    Leitet den Startpunkt aus der Geometrie des NOTAM-Satzes ab.

    Fuer Starts von beweglichen Seeplattformen versagt die Referenz
    grundsaetzlich: Die Plattform steht nicht, wo die Tabelle sie vermutet.
    Beobachtet wurde ein chinesischer Start, dessen Sperrzonen vom tatsaechlichen
    Startpunkt aus eine Streuung von 3,3 Grad ergaben - vom naechsten
    verzeichneten Platz aus, 473 km entfernt, dagegen 19 Grad.

    Die Ableitung nutzt genau diesen Unterschied: Eine der Zonen ist der
    Startpunkt, und von ihr aus reihen sich die uebrigen auf einer Bahn.
    Zuerst werden kreisfoermige Zonen geprueft - eine Plattformsperrung ist ein
    kleiner Kreis -, danach als Auffangnetz jede Zone des Clusters.

    Rueckgabe: (Breite, Laenge, mittlerer Azimut, Streuung, Ursprungs-NOTAM)
    oder None.
    """
    punkte = cluster_zone_points(cluster)
    if len(punkte) < 3:
        return None

    kreise = [
        p for p in punkte
        if p[2].radius_km is not None and p[2].radius_km <= SEA_LAUNCH_MAX_RADIUS_KM
    ]
    bester: Optional[Tuple[float, float, float, float, "LaunchEvent"]] = None
    for kandidaten in (kreise, punkte):
        for lat, lon, ursprung in kandidaten:
            ziele = [
                (zl, zo) for zl, zo, _ in punkte
                if surface_distance_km(lat, lon, zl, zo) >= SEA_LAUNCH_MIN_ZONE_DISTANCE_KM
            ]
            if len(ziele) < 2:
                continue
            azimute = [initial_bearing_deg(lat, lon, zl, zo) for zl, zo in ziele]
            streuung = _angular_spread(azimute)
            mittel = _circular_mean(azimute)
            low, high = IMPLAUSIBLE_AZIMUTH_SECTOR
            if low <= mittel <= high:
                continue
            if bester is None or streuung < bester[3]:
                bester = (lat, lon, mittel, streuung, ursprung)
        if bester is not None:
            break

    if bester is None or bester[3] > SEA_LAUNCH_MAX_SPREAD_DEG:
        return None

    # Nur dort ableiten, wo die Referenz ohnehin nichts Besseres weiss.
    if len(spaceports):
        abstand = spaceports.apply(
            lambda r: haversine_km(bester[0], bester[1], r["Latitude"], r["Longitude"]),
            axis=1,
        ).min()
        if abstand < SEA_LAUNCH_MIN_SITE_DISTANCE_KM:
            return None
    return bester


def _derived_port(
    abgeleitet: Tuple[float, float, float, float, "LaunchEvent"],
    cluster: Sequence["LaunchEvent"],
    nations: Sequence[str],
) -> Optional[Tuple[pd.Series, float, List[float], List[float]]]:
    """
    Baut aus einem abgeleiteten Startpunkt einen Startplatz-Datensatz.

    Die Nation kommt aus dem Luftraum des Ursprungs-NOTAMs, nicht aus der
    Geometrie: Beim beobachteten Fall liegt der Startpunkt in chinesischer FIR,
    waehrend die Dropzones taiwanesischen und japanischen Luftraum beruehren.
    Genau dafuer gibt es die Anker-Regel - der Ursprung traegt die Nation, die
    uebrigen Zonen erben sie.
    """
    lat, lon, mittel, streuung, ursprung = abgeleitet
    nation = next(
        (
            n for n in (ursprung.fir_country, ursprung.nation,
                        nations[0] if len(nations) == 1 else None)
            if n in TARGET_NATIONS
        ),
        None,
    )
    if nation is None:
        return None

    port = pd.Series(
        {
            "Kurzel": sea_launch_code(lat, lon),
            "Name": "Sea launch position {:.2f}{} {:.2f}{}".format(
                abs(lat), "N" if lat >= 0 else "S",
                abs(lon), "E" if lon >= 0 else "W",
            ),
            "Latitude": lat,
            "Longitude": lon,
            "Land": nation,
        }
    )
    azimute: List[float] = []
    abstaende: List[float] = []
    for event in cluster:
        abstand = surface_distance_km(lat, lon, event.centroid_lat, event.centroid_lon)
        # Das NOTAM, das den Startpunkt beschreibt, hat keinen eigenen Azimut -
        # es bekommt den der Gruppe, damit Bahnneigung und Orbit stimmen.
        azimute.append(
            mittel
            if abstand < SEA_LAUNCH_MIN_ZONE_DISTANCE_KM
            else initial_bearing_deg(lat, lon, event.centroid_lat, event.centroid_lon)
        )
        abstaende.append(abstand)
    return port, streuung, azimute, abstaende


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

    # Seestart: der Startpunkt steht im NOTAM-Satz selbst, nicht in der
    # Referenz. Uebernommen wird er nur, wenn seine Bahn die der Referenz
    # deutlich schlaegt - sonst entscheidet weiterhin die gepflegte Tabelle.
    abgeleitet = derive_launch_point(cluster, spaceports)
    aus_geometrie = False
    if abgeleitet is not None and (
        selection is None
        or abgeleitet[3] + SEA_LAUNCH_SPREAD_MARGIN_DEG < selection[1]
    ):
        ersatz = _derived_port(abgeleitet, cluster, nations)
        if ersatz is not None:
            port, spread, azimuths, distances = ersatz
            aus_geometrie = True
    if not aus_geometrie:
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

    group.site_from_geometry = aus_geometrie
    group.nation = str(port["Land"])
    group.spaceport_code = str(port["Kurzel"])
    group.spaceport_name = str(port["Name"])
    group.spaceport_lat = float(port["Latitude"])
    group.spaceport_lon = float(port["Longitude"])
    group.azimuth_deg = _circular_mean(azimuths)
    # Ausgewiesen wird die Streuung ueber ALLE Zonen, nicht die ueber die nahen.
    # Die Nahzonen-Streuung taugt zur Auswahl des Startplatzes - fuer die
    # Anzeige und das Archiv ist sie irrefuehrend: liegt hoechstens eine Zone
    # innerhalb der Fernzonen-Grenze, ist sie definitionsgemaess 0.0, und ein
    # Start mit Azimuten von 87°, 331° und 180° meldete "Streuung 0.0°".
    group.azimuth_spread_deg = _angular_spread(azimuths)
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
    min_confidence: str = "MEDIUM",
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
        # Wird gesetzt, aber nicht hier ausgewertet: ob das NOTAM tatsaechlich
        # ausgeblendet wird, entscheidet die Oberflaeche - dort liegt auch die
        # Liste der von Hand zurueckgeholten Faelle.
        event.auto_hidden_reason = auto_hide_reason(event.confidence_level, text)
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
                    "Zone derived from the Q-line reference point - the NOTAM "
                    "states no area boundaries."
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
            event.review_reason = "Operator outside the target nations: {}".format(
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
                    "Confirmed as a launch by hand. Without coordinates in the "
                    "text no track can be estimated."
                )
                events.append(event)
                continue
            event.status = "REVIEW"
            event.review_reason = "No usable coordinates found in the NOTAM text."
            events.append(event)
            continue
        if fir_row is None and (
            is_confirmed or event.nation_hint in TARGET_NATIONS
        ):
            # Zwei Faelle ohne FIR-Treffer, die trotzdem weiterlaufen duerfen:
            # ein von Hand bestaetigtes NOTAM - dort waehlt die Geometrie - und
            # eines, dessen Text die Nation nennt. Letzteres ist genau der
            # Beleg, den die Drittstaaten-Regel verlangt; dass die genannte
            # Kennung nicht in der FIR-Referenz steht (fremde FIR oder
            # Flugplatzkennung wie KVBG), entwertet ihn nicht.
            nations = (
                [event.nation_hint]
                if event.nation_hint in TARGET_NATIONS
                else list(TARGET_NATIONS)
            )
            event.candidate_nations = list(nations)
        elif fir_row is None:
            event.status = "REVIEW"
            if (
                method == FIR_NONE or method.startswith(FIR_TOO_FAR)
            ) and event.confidence_level in ("HIGH", "MEDIUM"):
                # Maritime Warnungen und Meldungen ausserhalb jeder erfassten FIR
                # tragen die Nation nicht in der Kennung. Sie werden nicht
                # verworfen, sondern koennen ueber die Start-Gruppierung einem
                # Start zugeordnet werden - allein bleiben sie im Review.
                event.requires_group = True
                event.candidate_nations = list(TARGET_NATIONS)
                if event.nation_hint in TARGET_NATIONS:
                    event.candidate_nations = [event.nation_hint]
                event.review_reason = (
                    "No FIR match - resolvable only by grouping with further NOTAMs "
                    "of the same launch."
                )
                events.append(event)
                continue
            if method.startswith(FIR_OUTSIDE):
                event.review_reason = (
                    "NOTAM belongs to FIR {} - not a FIR of the target nations.".format(
                        method.split(":", 1)[-1]
                    )
                )
            elif method.startswith(FIR_TOO_FAR):
                event.review_reason = "Zone lies {}.".format(
                    fir_method_label(FIR_TOO_FAR, method.split(":", 1)[-1])
                )
            else:
                event.review_reason = "No FIR match possible (check the reference data)."
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
        elif method == FIR_BY_GEOMETRY and haversine_km(
            event.centroid_lat, event.centroid_lon,
            float(fir_row["Latitude"]), float(fir_row["Longitude"]),
        ) > FIR_OWN_AIRSPACE_KM:
            # Die FIR wurde nicht genannt, sondern ueber den naechstgelegenen
            # Referenzpunkt geraten - und dieser Punkt ist in der Referenz der
            # Sitz der Bezirkszentrale, nicht die FIR-Grenze. Bis zu 1500 km
            # von einer Stadt entfernt zu liegen heisst nicht, im Luftraum
            # dieser Nation zu sein: eine Sperrzone ueber Nicaragua landete so
            # bei Miami und wurde ein Start von Cape Canaveral.
            #
            # Der Massstab verlangt, dass der Luftraum der Nation *selbst*
            # gehoert. Ein Nachbarschaftsschaetzer belegt das nicht, also gilt
            # hier dieselbe Zurueckhaltung wie bei einer Drittstaaten-FIR:
            # ohne Nennung im Text oder Aufloesung ueber die Gruppe bleibt das
            # NOTAM im Review.
            event.status = "REVIEW"
            event.requires_group = True
            event.review_reason = (
                "No FIR named in the NOTAM - {} is only the nearest reference "
                "point ({:.0f} km). That does not establish whose airspace this "
                "is. Resolvable by a mention in the text or by grouping with "
                "further NOTAMs of the same launch.".format(
                    event.fir_code,
                    haversine_km(
                        event.centroid_lat, event.centroid_lon,
                        float(fir_row["Latitude"]), float(fir_row["Longitude"]),
                    ),
                )
            )
            events.append(event)
            continue
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
                "FIR {} lies in {} - the launch nation ({}) would only be assumed "
                "there and is not named in the text. Resolvable only by grouping "
                "with further NOTAMs of the same launch.".format(
                    event.fir_code, event.fir_country or "a third country",
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
                "FIR {} covers several launch nations ({}) and the text names none - "
                "resolvable only by grouping with a launch.".format(
                    event.fir_code, ", ".join(nations)
                )
            )
            events.append(event)
            continue

        if not event.passes_confidence and not is_confirmed:
            event.status = "REVIEW"
            event.review_reason = "Launch confidence {} (score {}){}".format(
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
                "Launch site derived from the text ({}). ".format(
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
            event.review_reason = "No launch site for {} in the reference.".format(
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
                "Zone sits on the launch site - no reliable azimuth."
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
                + "Caution: azimuth {:.0f}° points west - the launch site "
                "assignment is uncertain.".format(event.azimuth_deg)
            )
        elif not azimuth_plausible:
            event.status = "REVIEW"
            event.review_reason = (
                "No launch site with a plausible direction: azimuth {:.0f}° "
                "points west, against the Earth's rotation.".format(event.azimuth_deg)
            )
            events.append(event)
            continue

        if event.distance_km > MAX_PLAUSIBLE_RANGE_KM:
            event.status = "REVIEW"
            event.review_reason = (
                "Distance from launch site to zone is {:.0f} km - check the assignment.".format(
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
                "Moved from the launch table back to review by hand."
            )
            event.manual_override = False
            event.launch_group = ""

    # Mehrfach gelistete NOTAMs entfernen, dann zu Starts zusammenfassen.
    events, stats["duplicates"] = _drop_duplicate_events(events)
    groups = group_launches(events, spaceports)
    # Erst jetzt, mit fertigen Gruppen: Meldungen, die denselben Luftraum schon
    # Tage vorher reserviert haben, an ihren Start haengen. Die Gruppen selbst
    # bleiben unveraendert - es ist dieselbe Flaeche, nicht eine weitere Zone.
    stats["advance"] = len(pair_advance_announcements(events, groups))
    # Vermerken, wo zwei Plaetze so nah beieinanderliegen, dass die Geometrie
    # sie nicht unterscheiden kann. Entschieden wird das nicht hier, sondern
    # von Hand - siehe apply_launch_site_assignments.
    stats["site_ambiguous"] = mark_site_alternatives(events, groups, spaceports)
    stats["groups"] = groups
    stats["launches"] = sum(1 for g in groups if g.spaceport_code)
    stats["grouped"] = sum(1 for g in groups if g.zone_count > 1)
    stats["events"] = len(events)
    stats["min_confidence"] = min_confidence
    stats["manual"] = sum(1 for e in events if e.source == SOURCE_MANUAL)
    stats["confirmed"] = sum(1 for e in events if e.manual_override)
    stats["rejected"] = sum(1 for e in events if e.key in rejected)
    stats["high_confidence"] = sum(1 for e in events if e.confidence_level == "HIGH")
    stats["ok"] = sum(1 for e in events if e.status == "OK")
    stats["review"] = sum(1 for e in events if e.status == "REVIEW")
    return events, stats


def events_to_dataframe(
    events: Sequence[LaunchEvent], vehicles: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    Baut die Ergebnistabelle mit den fachlich geforderten Spalten.

    `vehicles` dient allein der Beschriftung der Spalte "Traegersystem"; ohne
    Referenztabelle steht dort der gespeicherte Kuerzel-Code.
    """
    records: List[Dict[str, Any]] = []
    for e in events:
        records.append(
            {
                "NOTAM ID": mark_id(e.notam_id, e.manual_override),
                "Geprüft": "by hand" if e.manual_override else "-",
                "Art": e.kind,
                "Start": e.launch_group or "-",
                "Quelle": e.source,
                "Startnation": nation_label(e.nation) or "-",
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
                "Trägersystem": (
                    vehicle_label(e.vehicle, vehicles) if e.vehicle else "-"
                ),
                "Payload": e.payload or "-",
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
        "Trägersystem",
        "Payload",
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
    ORBIT_SSO: (
        "a near-polar track that passes every point at the same local time - "
        "typical of earth observation and reconnaissance satellites"
    ),
    ORBIT_HIGH_INC: (
        "a steeply inclined track close to the poles - typical of earth "
        "observation and military reconnaissance"
    ),
    ORBIT_LEO_MEO: (
        "a medium inclination, as used by space stations, crewed flights and "
        "navigation or communication satellites"
    ),
    ORBIT_GTO: (
        "a shallow, near-equatorial track - usually the transfer towards "
        "geostationary orbit, so communication or weather satellites"
    ),
    ORBIT_RETROGRADE: (
        "a track running against the Earth's rotation - very rare, the "
        "assignment should be checked"
    ),
}

#: 16-teilige Kompassrose fuer die Startrichtung in Worten.
_COMPASS = (
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
)


#: Englische Anzeigenamen der Ergebnistabellen.
#:
#: Die Schluessel der Dataframes bleiben bewusst deutsch: sie sind ueber die
#: ganze Anwendung verdrahtet - Filter, Export, Review, Ausgeblendet greifen
#: darauf zu. Uebersetzt wird nur, was der Leser sieht. Die Begriffe sind die
#: der Luft- und Raumfahrt, nicht woertliche Uebersetzungen; die NOTAM-Texte
#: selbst sind englisch.
COLUMN_LABELS = {
    "NOTAM ID": "NOTAM",
    "NOTAMs": "NOTAMs",
    "Gepr\u00fcft": "Verified",
    "Art": "Type",
    "Start": "Launch",
    "Quelle": "Source",
    "Archiv": "Archive",
    "Startnation": "Nation",
    "Weltraumbahnhof": "Launch Site",
    "Startfenster (UTC)": "Launch Window (UTC)",
    "FIR Code": "FIR",
    "FIR": "FIR",
    "FIR liegt in": "FIR Country",
    "H\u00f6henprofil": "Altitude",
    "Launch Azimut (\u00b0)": "Azimuth",
    "Est. Inklination (\u00b0)": "Inclination",
    "Orbit-Typ": "Orbit",
    "Tr\u00e4gersystem": "Vehicle",
    "Payload": "Payload",
    "Konfidenz": "Confidence",
    "Zuverl\u00e4ssigkeit": "Reliability",
    "Nationsbeleg": "Nation Evidence",
    "Distanz (km)": "Distance",
    "Punkte": "Points",
    "Status": "Status",
    "Trigger": "Triggers",
    "Hinweis": "Note",
    "Sperrzonen": "Zones",
    "Pad": "Pad",
    "Vorank\u00fcndigung": "Advance Notice",
    "Reichweite (km)": "Range",
    "Azimut-Streuung (\u00b0)": "Spread",
}

#: Zahlenspalten mit ihrem Anzeigeformat. Ohne das zeigt Streamlit float64 mit
#: sechs Nachkommastellen - aus 112.1 wird 112.100000.
COLUMN_FORMATS = {
    "Launch Azimut (\u00b0)": "%.1f\u00b0",
    "Est. Inklination (\u00b0)": "%.1f\u00b0",
    "Azimut-Streuung (\u00b0)": "%.1f\u00b0",
    "Distanz (km)": "%.0f km",
    "Reichweite (km)": "%.0f km",
}

#: Spaltenreihenfolge der Start-Tabelle: erst wer und was, dann die Bahn,
#: zuletzt die Belege. Traegersystem und Payload stehen vorn, weil man sie
#: taeglich liest - vorher lagen sie hinter dem Azimut.
GROUP_COLUMN_ORDER = (
    "Start", "Startnation", "Weltraumbahnhof", "Tr\u00e4gersystem", "Payload",
    "Startfenster (UTC)", "Orbit-Typ", "Est. Inklination (\u00b0)",
    "Launch Azimut (\u00b0)", "Sperrzonen", "Reichweite (km)",
    "Azimut-Streuung (\u00b0)", "Konfidenz", "Zuverl\u00e4ssigkeit", "Art",
    "Gepr\u00fcft", "FIR", "Pad", "NOTAMs", "Vorank\u00fcndigung", "Quelle",
)

#: Dasselbe auf NOTAM-Ebene.
EVENT_COLUMN_ORDER = (
    "NOTAM ID", "Startnation", "Weltraumbahnhof", "Tr\u00e4gersystem", "Payload",
    "Startfenster (UTC)", "Orbit-Typ", "Est. Inklination (\u00b0)",
    "Launch Azimut (\u00b0)", "H\u00f6henprofil", "Distanz (km)", "Konfidenz",
    "Zuverl\u00e4ssigkeit", "Start", "Art", "Gepr\u00fcft", "FIR Code",
    "FIR liegt in", "Nationsbeleg", "Punkte", "Status", "Quelle", "Trigger",
    "Hinweis",
)


def table_config(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Baut die Anzeigekonfiguration einer Ergebnistabelle.

    Uebersetzt die Spaltenkoepfe und gibt Zahlen ein Format. Spalten, die nicht
    in der Tabelle stehen, werden uebergangen - dieselbe Funktion bedient die
    Start- und die NOTAM-Ansicht.
    """
    config: Dict[str, Any] = {}
    for spalte in df.columns:
        if spalte.startswith("_"):
            continue
        label = COLUMN_LABELS.get(spalte, spalte)
        format_ = COLUMN_FORMATS.get(spalte)
        if format_:
            config[spalte] = st.column_config.NumberColumn(label, format=format_)
        else:
            config[spalte] = st.column_config.Column(label)
    return config


def visible_order(df: pd.DataFrame, order: Sequence[str]) -> List[str]:
    """Spaltenreihenfolge fuer die Anzeige, beschraenkt auf vorhandene Spalten."""
    bekannt = [s for s in order if s in df.columns]
    rest = [s for s in df.columns if s not in bekannt and not s.startswith("_")]
    return bekannt + rest


def compass_name(azimuth_deg: Optional[float]) -> str:
    """Wandelt einen Azimut in eine Himmelsrichtung in Worten."""
    if azimuth_deg is None:
        return "undetermined"
    return _COMPASS[int((azimuth_deg % 360.0) / 22.5 + 0.5) % 16]


def _format_window_hours(hours: Optional[float]) -> str:
    if hours is None:
        return "unknown"
    if hours < 2:
        return "{:.0f} minutes".format(hours * 60)
    if hours < 48:
        return "{:.1f} hours".format(hours)
    return "{:.0f} days".format(hours / 24.0)


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
            "**What:** A re-entry or splashdown zone{}. Assigned launch site: "
            "{}.".format(
                " for {}".format(nation_label(group.nation)) if group.nation else "",
                group.spaceport_name or "unknown",
            )
        )
    else:
        lines.append(
            "**What:** A space launch{} from {}.".format(
                " by {}".format(nation_label(group.nation)) if group.nation else "",
                group.spaceport_name or "an unknown site",
            )
        )
    lines.append("**When (UTC):** {}".format(group.launch_window))

    # Woran erkannt
    dauern = [
        (e.valid_to - e.valid_from).total_seconds() / 3600.0
        for e in members
        if e.valid_from and e.valid_to
    ]
    taeglich = [daily_window_hours(extract_items(e.raw_text).get("D")) for e in members]
    taeglich = [t for t in taeglich if t]
    # Das taegliche Fenster ist das Argument; die Gesamtlaufzeit ist es nicht.
    # Beides zu vermengen erzeugte Saetze wie "each active for only about 91
    # days" - eine Begruendung, die sich selbst widerspricht.
    aktiv = min(taeglich) if taeglich else (min(dauern) if dauern else None)
    kurz = aktiv is not None and aktiv <= LAUNCH_WINDOW_MAX_HOURS
    if kurz:
        lines.append(
            "**How it was recognised:** {} airspace closure(s) from the surface to "
            "unlimited altitude, each active for only about {}. A closure that high "
            "for that short a time practically only occurs for a rocket launch.".format(
                group.zone_count, _format_window_hours(aktiv)
            )
        )
    elif aktiv is not None:
        lines.append(
            "**How it was recognised:** {} airspace closure(s) from the surface to "
            "unlimited altitude, running for {}. That is long for a launch window - "
            "the closure height and the wording carry the recognition here, not the "
            "duration.".format(group.zone_count, _format_window_hours(aktiv))
        )
    else:
        lines.append(
            "**How it was recognised:** {} airspace closure(s) from the surface to "
            "unlimited altitude. The closure height and the wording of the messages "
            "point to a rocket launch.".format(group.zone_count)
        )
    lines.append("**Underlying messages:** {}".format(", ".join(group.notam_ids)))

    # Vorankuendigung. Steht bewusst direkt hinter den Meldungen des Starttags:
    # es ist derselbe Luftraum, nur frueher gemeldet - keine weitere Sperrzone.
    if group.advance_notam_ids:
        vorlauf = group.advance_notice_hours
        lines.append(
            "**Announced in advance:** {} reserved the same airspace {} before the "
            "launch window. The area matches, the daily activation window contains "
            "the launch window, and the validity covers the launch day - which is "
            "why these messages are assigned to this launch and not counted as "
            "further closure zones.".format(
                ", ".join(group.advance_notam_ids),
                _format_window_hours(vorlauf) if vorlauf else "some time",
            )
        )

    # Nation
    belege = sorted({b for e in members for b in e.nation_evidence})
    if belege:
        lines.append(
            "**Where the nation comes from:** Named in the message text ({}).".format(
                ", ".join(belege[:4])
            )
        )
    else:
        lines.append(
            "**Where the nation comes from:** Derived from the affected airspace "
            "region, not named in the text - check the original text if in doubt."
        )

    # Startplatz
    if group.zone_count > 1:
        lines.append(
            "**Why this launch site:** Seen from {}, all {} closure zones lie in "
            "the same direction (spread {:.1f}°). {}".format(
                group.spaceport_code, group.zone_count, group.azimuth_spread_deg,
                # Mit einem Nachbarplatz waere "kein anderer erklaert sie" falsch:
                # er erklaert sie genauso gut, deshalb steht er ja zur Wahl.
                "Apart from its immediate neighbour {}, no other launch site "
                "explains all zones together.".format(
                    ", ".join(group.site_alternatives)
                )
                if group.site_alternatives
                else "No other launch site explains all zones together.",
            )
            if group.azimuth_spread_deg <= LAUNCH_GROUP_MAX_SPREAD_DEG
            # Bei weit auseinanderliegenden Zonen - typisch fuer mehrere
            # Wiedereintrittsgebiete eines Fluges - waere "dieselbe Richtung"
            # schlicht falsch. Dann traegt die Zeitgleichheit die Gruppe, nicht
            # die Geometrie, und das muss dastehen.
            else "**Why this launch site:** The {} closure zones lie in clearly "
            "different directions seen from {} (spread {:.1f}°). They are grouped "
            "because they are announced for the same window, not because of their "
            "geometry - azimuth and inclination below are therefore averages "
            "without much meaning.".format(
                group.zone_count, group.spaceport_code, group.azimuth_spread_deg
            )
        )
    else:
        hinweis = next((e.assignment_note for e in members if e.assignment_note), "")
        lines.append(
            "**Why this launch site:** Nearest launch site of that nation with a "
            "plausible launch direction.{}".format(" " + hinweis if hinweis else "")
        )

    # Pad. Nur wenn es ueberhaupt zwei gibt - sonst ist nichts zu sagen.
    if group.site_alternatives:
        if group.launch_site:
            lines.append(
                "**Which pad:** Set by hand to {}. {} lies {} away and cannot be "
                "told apart from the closure zones.".format(
                    group.spaceport_code,
                    ", ".join(group.site_alternatives),
                    "less than 2 km",
                )
            )
        else:
            lines.append(
                "**Which pad:** Not determined. {} and {} lie side by side; the "
                "azimuth to a drop zone differs between them by less than a "
                "quarter of a degree, so the closure zones cannot decide it. "
                "{} is shown because it is the longer-established site, not "
                "because it was established for this launch.".format(
                    group.spaceport_code,
                    ", ".join(group.site_alternatives),
                    group.spaceport_code,
                )
            )

    # Folgerung
    if group.kind == KIND_REENTRY:
        lines.append(
            "**What follows from it:** In a re-entry the object comes back from "
            "orbit. The direction from the launch site to the zone therefore says "
            "nothing about the orbital plane - the azimuth and inclination given "
            "here carry no meaning."
        )
    elif group.azimuth_deg is not None and group.inclination_deg is not None:
        erklaerung = ORBIT_EXPLANATIONS.get(group.orbit_type, "")
        lines.append(
            "**What follows from it:** The rocket flies {} ({:.0f}°). That implies "
            "an inclination of roughly {:.0f}° - {}{}.".format(
                compass_name(group.azimuth_deg),
                group.azimuth_deg,
                group.inclination_deg,
                group.orbit_type,
                ", " + erklaerung if erklaerung else "",
            )
        )

    # Sicherheit
    sicher = {
        RELIABILITY_HIGH: (
            "The nearest closure zone lies close to the launch site, so the "
            "direction is well determined."
        ),
        RELIABILITY_MEDIUM: (
            "The closure zones lie further away; the inclination is an approximation."
        ),
        RELIABILITY_LOW: (
            "The closure zones lie very far away (re-entry or deorbit areas). Launch "
            "site and inclination can only be determined roughly there."
        ),
    }.get(group.reliability, "")
    lines.append(
        "**How reliable:** {} - {} {}".format(
            group.reliability,
            sicher,
            "The inclination is an approximation: the contribution of the Earth's "
            "rotation is not accounted for.",
        )
    )
    return "\n\n".join(lines)


def groups_to_dataframe(
    groups: Sequence[LaunchGroup],
    vehicles: Optional[pd.DataFrame] = None,
    archiv_hinweis: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Ergebnistabelle auf Start-Ebene: eine Zeile je Start statt je NOTAM.

    `vehicles` dient allein der Beschriftung der Spalte "Traegersystem".
    `archiv_hinweis` (je group_id) fuellt die letzte Spalte "Archiv":
    "past", "removed from archive" oder "-".
    """
    records: List[Dict[str, Any]] = []
    for g in groups:
        records.append(
            {
                "Start": g.group_id,
                "Art": g.kind,
                "Startnation": nation_label(g.nation) or "-",
                "Weltraumbahnhof": (
                    "{} ({})".format(g.spaceport_name, g.spaceport_code)
                    if g.spaceport_code
                    else "-"
                ),
                "Startfenster (UTC)": g.launch_window,
                "Sperrzonen": g.zone_count,
                "Pad": (
                    "-" if not g.site_alternatives
                    else ("by hand" if g.launch_site else "not determined")
                ),
                "NOTAMs": ", ".join(g.notam_ids),
                "Vorankündigung": (
                    "{} ({:.0f} h)".format(
                        ", ".join(g.advance_notam_ids), g.advance_notice_hours or 0.0
                    )
                    if g.advance_notam_ids
                    else "-"
                ),
                "Geprüft": "by hand" if g.manual_override else "-",
                "FIR": ", ".join(g.fir_codes) if g.fir_codes else "-",
                "Launch Azimut (°)": (
                    round(g.azimuth_deg, 1) if g.azimuth_deg is not None else np.nan
                ),
                "Est. Inklination (°)": (
                    round(g.inclination_deg, 1) if g.inclination_deg is not None else np.nan
                ),
                "Orbit-Typ": g.orbit_type,
                "Trägersystem": (
                    vehicle_label(g.vehicle, vehicles) if g.vehicle else "-"
                ),
                "Payload": g.payload or "-",
                "Reichweite (km)": (
                    round(g.max_range_km, 1) if g.max_range_km is not None else np.nan
                ),
                "Azimut-Streuung (°)": round(g.azimuth_spread_deg, 1),
                "Konfidenz": g.confidence_level,
                "Zuverlässigkeit": g.reliability,
                "Quelle": ", ".join(g.sources),
                "Archiv": (archiv_hinweis or {}).get(g.group_id, "-"),
            }
        )
    columns = [
        "Start",
        "Art",
        "Startnation",
        "Weltraumbahnhof",
        "Startfenster (UTC)",
        "Sperrzonen",
        "Pad",
        "NOTAMs",
        "Vorankündigung",
        "Geprüft",
        "FIR",
        "Launch Azimut (°)",
        "Est. Inklination (°)",
        "Orbit-Typ",
        "Trägersystem",
        "Payload",
        "Reichweite (km)",
        "Azimut-Streuung (°)",
        "Konfidenz",
        "Zuverlässigkeit",
        "Quelle",
        "Archiv",
    ]
    return pd.DataFrame(records, columns=columns)


#: Spalten des Startarchivs, in genau dieser Reihenfolge.
ARCHIVE_COLUMNS = (
    "NOTAM",
    "Startdatum",
    "Startzeit",
    "Nation",
    "Weltraumbahnhof",
    "Tr\u00e4gersystem",
    "Payload",
    "Orbit",
    "Inklination",
    "Azimuth",
    "Dropzones",
)

#: Kurzformen der Orbit-Typen fuer das Archiv - die langen Klartext-Labels
#: waeren in einer Tabellenspalte unleserlich.
ORBIT_SHORT = {
    ORBIT_SSO: "SSO",
    ORBIT_HIGH_INC: "HIGH-INC",
    ORBIT_LEO_MEO: "LEO/MEO",
    ORBIT_GTO: "GTO",
    ORBIT_RETROGRADE: "RETRO",
}


def orbit_short(orbit_type: str) -> str:
    """Kurzform eines Orbit-Typs; unbekannte Werte bleiben, wie sie sind."""
    if not orbit_type or orbit_type == ORBIT_UNKNOWN:
        return "-"
    return ORBIT_SHORT.get(orbit_type, orbit_type)


def archive_row(group: LaunchGroup, events: Sequence[LaunchEvent]) -> Dict[str, Any]:
    """
    Baut die Archivzeile eines Starts.

    Eine Zeile je Start, nicht je NOTAM: Startplatz, Traegersystem und Bahn
    gehoeren zum Vorgang, nicht zur einzelnen Sperrzone. Die Kennungen aller
    Zonen stehen zusammen in der Spalte NOTAM, ihre Mittelpunkte in Dropzones.
    """
    per_row = {e.row_index: e for e in events}
    mitglieder = [per_row[r] for r in group.row_indices if r in per_row]
    kennungen = [m.notam_id for m in mitglieder] or [
        kid.replace(MANUAL_MARK, "").strip() for kid in group.notam_ids
    ]
    # Jede Sperrzone einzeln, nicht ein Mittelpunkt je NOTAM: ein NOTAM kann
    # zwei Gebiete 740 km auseinander beschreiben, deren Mittelwert nirgends
    # liegt. Der abgeleitete Startpunkt gehoert nicht dazu - er ist der
    # Ursprung der Bahn, keine Dropzone.
    zonen: List[str] = []
    for lat, lon, _ in cluster_zone_points(mitglieder):
        if group.site_from_geometry and group.spaceport_lat is not None and (
            surface_distance_km(lat, lon, group.spaceport_lat, group.spaceport_lon)
            < SEA_LAUNCH_MIN_ZONE_DISTANCE_KM
        ):
            continue
        eintrag = "{:.4f} {:.4f}".format(lat, lon)
        if eintrag not in zonen:
            zonen.append(eintrag)
    return {
        "NOTAM": ", ".join(kennungen),
        "Startdatum": group.window_from.strftime("%d.%m.%Y") if group.window_from else "",
        "Startzeit": group.window_from.strftime("%H:%M") if group.window_from else "",
        "Nation": nation_label(group.nation),
        "Weltraumbahnhof": group.spaceport_code or "",
        "Tr\u00e4gersystem": group.vehicle or "",
        "Payload": group.payload or "",
        "Orbit": orbit_short(group.orbit_type),
        "Inklination": (
            "{:.1f}".format(group.inclination_deg)
            if group.inclination_deg is not None
            else ""
        ),
        "Azimuth": (
            "{:.1f}".format(group.azimuth_deg) if group.azimuth_deg is not None else ""
        ),
        "Dropzones": "; ".join(zonen),
    }


def archive_key(row: Dict[str, Any]) -> str:
    """
    Erkennungsmerkmal einer Archivzeile: Startdatum und NOTAM-Kennungen.

    Damit findet ein spaeterer Durchlauf denselben Start wieder und aktualisiert
    ihn, statt ihn ein zweites Mal anzulegen.

    Der Startplatz gehoert ausdruecklich NICHT dazu, obwohl er einmal darin
    stand. Er ist eine Eigenschaft des Starts, nicht seine Identitaet - und er
    aendert sich, wenn die Erkennung besser wird:

      - Die Seestart-Ableitung verschob einen Start von WSLC auf SEA-21N112E.
      - Eine von Hand gesetzte Pad-Wahl verschiebt ihn von WSLC auf HAIN.

    Beides ergab einen neuen Schluessel und damit eine zweite Archivzeile mit
    identischen NOTAM-Kennungen. Im Bestand stehen dadurch drei Zeilen fuer den
    chinesischen Seestart vom 12.02.2026 - F0511/26 in allen drei.

    Gemessen am Bestand vom 02.10.2026: 16 Zeilen ergeben mit und ohne
    Startplatz je 16 Schluessel; keine bestehende Zeile fiel zusammen.

    Was bleibt: wird die GRUPPIERUNG besser, waechst die Kennungsmenge
    (F0511/26 -> F0511/26, A0443/26 -> drei Kennungen) und der Schluessel
    aendert sich trotzdem. Das zu loesen heisst, ueber Kennungs-Ueberschneidung
    zu suchen statt auf Gleichheit zu pruefen - eine Aenderung der
    Zusammenfuehrungs-Semantik, die eine Entscheidung braucht.
    """
    kennungen = sorted(
        teil.strip().upper()
        for teil in str(row.get("NOTAM", "")).split(",")
        if teil.strip()
    )
    return "|".join([str(row.get("Startdatum", "")).strip(), ",".join(kennungen)])


#: Karenz, bevor ein abgelaufener Start die Tageslage verlaesst. 24 Stunden:
#: ein Start von heute frueh bleibt bis morgen sichtbar, und ein verschobener
#: Start mit neuem NOTAM taucht nicht kurz auf und wieder ab.
PAST_LAUNCH_GRACE = timedelta(hours=24)


def _als_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def latest_end(events: Sequence["LaunchEvent"]) -> Optional[datetime]:
    """Spaetestes Ende der Meldungen: valid_to, ersatzweise valid_from (UTC)."""
    enden = [
        _als_utc(e.valid_to or e.valid_from)
        for e in events
        if (e.valid_to or e.valid_from) is not None
    ]
    return max(enden) if enden else None


def event_expired(
    event: "LaunchEvent", now: datetime, karenz: timedelta = PAST_LAUNCH_GRACE
) -> bool:
    """Ist die Meldung laenger als die Karenz abgelaufen? Ohne Zeiten nie."""
    ende = latest_end([event])
    return ende is not None and ende + karenz < _als_utc(now)


def past_launch_rows(
    groups: Sequence["LaunchGroup"],
    events: Sequence["LaunchEvent"],
    archiv_keys: Set[str],
    now: datetime,
    karenz: timedelta = PAST_LAUNCH_GRACE,
    entfernt: Optional[Set[str]] = None,
) -> Set[int]:
    """
    Tabellenzeilen vergangener Starts.

    Vergangen ist ein Start nur, wenn er archiviert ist (derselbe Schluessel,
    den _update_archive schreibt) und sein spaetestes Fenster - Zonen und
    angehaengte Vorankuendigungen - laenger als die Karenz vorbei ist. Review-
    Faelle, Starts ohne Platz und im Archiv-Editor entfernte Starts bleiben
    sichtbar: ausgeblendet wird nur, was nachweislich im Archiv steht.
    """
    entfernt = entfernt or set()
    per_row = {e.row_index: e for e in events}
    vergangen: Set[int] = set()
    for g in groups:
        if not g.spaceport_code:
            continue
        zonen = [per_row[r] for r in g.row_indices if r in per_row]
        if not any(e.status == "OK" for e in zonen):
            continue
        zeilen = list(g.row_indices) + list(g.advance_row_indices)
        ende = latest_end([per_row[r] for r in zeilen if r in per_row])
        if ende is None or ende + karenz >= _als_utc(now):
            continue
        schluessel = archive_key(archive_row(g, events))
        if schluessel not in archiv_keys or schluessel in entfernt:
            continue
        vergangen.update(zeilen)
    return vergangen


def count_hidden_past(
    groups: Sequence["LaunchGroup"], past_rows: Set[int], visible_rows: Set[int]
) -> int:
    """
    Zahl der vergangenen Starts, die der Schalter wirklich ausblendet.

    visible_rows sind die Tabellenzeilen, die ohne den Vergangen-Filter sichtbar
    waeren; ein Start, den Ausschluss oder andere Filter schon verbergen, zaehlt
    nicht mit.
    """
    return sum(
        1
        for g in groups
        if set(g.row_indices) & past_rows and set(g.row_indices) & visible_rows
    )


def archive_hints(
    groups: Sequence["LaunchGroup"],
    events: Sequence["LaunchEvent"],
    past_groups: Set[str],
    entfernt: Set[str],
) -> Dict[str, str]:
    """Archiv-Hinweis je group_id: "past" oder (vorrangig) "removed from archive"."""
    hinweise = {gid: "past" for gid in past_groups}
    for g in groups:
        if g.spaceport_code and archive_key(archive_row(g, events)) in entfernt:
            hinweise[g.group_id] = "removed from archive"
    return hinweise


def fallback_points(
    events: Sequence["LaunchEvent"], rows: Set[int]
) -> List[Dict[str, float]]:
    """Punkte der Ersatzkarte: nur OK-Zonen mit Punkt aus den sichtbaren Zeilen."""
    return [
        {"lat": e.centroid_lat, "lon": e.centroid_lon}
        for e in events
        if e.status == "OK" and e.centroid_lat is not None and e.row_index in rows
    ]


def archive_keys_or_reason(path: Path) -> Tuple[Optional[Set[str]], str]:
    """Schluessel des Archivs; bei unlesbarer Datei None und der Grund."""
    try:
        bestand = read_archive_strict(path)
    except ArchiveUnreadable as exc:
        return None, str(exc)
    return {archive_key(dict(r)) for _, r in bestand.iterrows()}, ""


def migrate_archive_keys(keys: Iterable[str]) -> Set[str]:
    """
    Bringt gespeicherte Loeschschluessel auf die heutige Form.

    Bis zum 02.10.2026 enthielt der Schluessel den Startplatz als Mittelteil
    ("21.09.2025|WSLC|A1234/25"). Ohne diese Umstellung kaemen von Hand
    geloeschte Archivzeilen beim naechsten Durchlauf zurueck.
    """
    umgestellt: Set[str] = set()
    for schluessel in keys or ():
        teile = str(schluessel).split("|")
        if len(teile) == 3:
            teile = [teile[0], teile[2]]
        umgestellt.add("|".join(teile))
    return umgestellt


def merge_archive(
    bestand: pd.DataFrame,
    neue: Sequence[Dict[str, Any]],
    entfernt: Optional[Set[str]] = None,
) -> pd.DataFrame:
    """
    Fuehrt neu erkannte Starts mit dem vorhandenen Archiv zusammen.

    Bekannte Starts werden aktualisiert statt verdoppelt. Nutzlast und
    Traegersystem bilden die Ausnahme: der Tagesbetrieb kennt sie meist nicht,
    sie stammen von Hand oder aus dem Archiv-Import. Ein vorhandener Eintrag
    bleibt deshalb stehen, wenn der neue Durchlauf nichts dazu weiss (leerer
    Wert); ein neuer, nicht leerer Wert ueberschreibt ihn.
    Von Hand geloeschte Zeilen kommen nicht zurueck, solange ihr Schluessel in
    `entfernt` steht.
    """
    entfernt = entfernt or set()
    zeilen: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    if bestand is not None and not bestand.empty:
        for _, r in bestand.iterrows():
            row = {spalte: str(r.get(spalte, "") or "") for spalte in ARCHIVE_COLUMNS}
            schluessel = archive_key(row)
            if schluessel in index:  # Dublette aus einer aelteren Fassung
                continue
            index[schluessel] = len(zeilen)
            zeilen.append(row)
    for roh in neue:
        row = {spalte: str(roh.get(spalte, "") or "") for spalte in ARCHIVE_COLUMNS}
        schluessel = archive_key(row)
        if schluessel in entfernt:
            continue
        if schluessel in index:
            alt = zeilen[index[schluessel]]
            for spalte in ("Payload", "Tr\u00e4gersystem"):
                if not row[spalte]:
                    row[spalte] = alt[spalte]
            zeilen[index[schluessel]] = row
        else:
            index[schluessel] = len(zeilen)
            zeilen.append(row)
    return pd.DataFrame(zeilen, columns=list(ARCHIVE_COLUMNS))


#: Spalten des Seestart-Protokolls.
SEA_LAUNCH_COLUMNS = (
    "Datum",
    "Zeit",
    "Nation",
    "Breite",
    "L\u00e4nge",
    "Radius (km)",
    "Azimut",
    "Inklination",
    "Orbit",
    "Dropzones",
    "NOTAM",
    "N\u00e4chster bekannter Platz",
)


def sea_launch_row(
    group: LaunchGroup, events: Sequence[LaunchEvent], spaceports: pd.DataFrame
) -> Dict[str, Any]:
    """
    Protokollzeile eines Starts von einer beweglichen Plattform.

    Die letzte Spalte ist die aufschlussreichste: Sie zeigt ueber die Zeit, ob
    sich ein neues Startgebiet herausbildet oder ob eine vorhandene Referenz
    nur ungenau liegt. Beim ersten belegten Fall - China, 22.07.2026 - lag der
    naechste verzeichnete Platz 473 km entfernt.
    """
    archiv = archive_row(group, events)
    mitglieder = [e for e in events if e.row_index in group.row_indices]
    radius = next(
        (
            e.radius_km for e in mitglieder
            if e.radius_km is not None
            and group.spaceport_lat is not None
            and surface_distance_km(
                e.centroid_lat, e.centroid_lon,
                group.spaceport_lat, group.spaceport_lon,
            ) < SEA_LAUNCH_MIN_ZONE_DISTANCE_KM
        ),
        None,
    )
    naechster = ""
    if len(spaceports) and group.spaceport_lat is not None:
        abstand = spaceports.apply(
            lambda r: haversine_km(
                group.spaceport_lat, group.spaceport_lon, r["Latitude"], r["Longitude"]
            ),
            axis=1,
        )
        i = abstand.idxmin()
        naechster = "{}, {:.0f} km".format(spaceports.loc[i, "Kurzel"], abstand[i])
    return {
        "Datum": archiv["Startdatum"],
        "Zeit": archiv["Startzeit"],
        "Nation": archiv["Nation"],
        "Breite": "{:.4f}".format(group.spaceport_lat) if group.spaceport_lat is not None else "",
        "L\u00e4nge": "{:.4f}".format(group.spaceport_lon) if group.spaceport_lon is not None else "",
        "Radius (km)": "{:.0f}".format(radius) if radius else "",
        "Azimut": archiv["Azimuth"],
        "Inklination": archiv["Inklination"],
        "Orbit": archiv["Orbit"],
        "Dropzones": archiv["Dropzones"],
        "NOTAM": archiv["NOTAM"],
        "N\u00e4chster bekannter Platz": naechster,
    }


def sea_launch_key(row: Dict[str, Any]) -> str:
    """Erkennungsmerkmal: Datum, Position auf ein Zehntelgrad und Kennungen."""
    kennungen = sorted(
        t.strip().upper() for t in str(row.get("NOTAM", "")).split(",") if t.strip()
    )
    def grob(wert: Any) -> str:
        try:
            return "{:.1f}".format(float(wert))
        except (TypeError, ValueError):
            return ""
    return "|".join(
        [str(row.get("Datum", "")).strip(), grob(row.get("Breite")),
         grob(row.get("L\u00e4nge")), ",".join(kennungen)]
    )


def load_sea_launches(path: Path) -> pd.DataFrame:
    """Liest das Seestart-Protokoll; fehlt es, beginnt es leer."""
    leer = pd.DataFrame(columns=list(SEA_LAUNCH_COLUMNS))
    if not path.exists():
        return leer
    try:
        df = _read_csv_any(str(path))
    except Exception:
        return leer
    for spalte in SEA_LAUNCH_COLUMNS:
        if spalte not in df.columns:
            df[spalte] = ""
    return df[list(SEA_LAUNCH_COLUMNS)].fillna("").astype(str)


def merge_sea_launches(
    bestand: pd.DataFrame,
    neue: Sequence[Dict[str, Any]],
    entfernt: Optional[Set[str]] = None,
) -> pd.DataFrame:
    """Fuehrt neue Beobachtungen mit dem Protokoll zusammen, ohne zu verdoppeln."""
    entfernt = entfernt or set()
    zeilen: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    if bestand is not None and not bestand.empty:
        for _, r in bestand.iterrows():
            row = {sp: str(r.get(sp, "") or "") for sp in SEA_LAUNCH_COLUMNS}
            k = sea_launch_key(row)
            if k in index:
                continue
            index[k] = len(zeilen)
            zeilen.append(row)
    for roh in neue:
        row = {sp: str(roh.get(sp, "") or "") for sp in SEA_LAUNCH_COLUMNS}
        k = sea_launch_key(row)
        if k in entfernt:
            continue
        if k in index:
            zeilen[index[k]] = row
        else:
            index[k] = len(zeilen)
            zeilen.append(row)
    return pd.DataFrame(zeilen, columns=list(SEA_LAUNCH_COLUMNS))


def persist_sea_launches(path: Path, df: pd.DataFrame) -> None:
    """Schreibt das Seestart-Protokoll in die Projektdatei."""
    try:
        path.write_text(
            df[list(SEA_LAUNCH_COLUMNS)].to_csv(index=False), encoding="utf-8-sig"
        )
    except OSError:  # pragma: no cover - Schreibfehler duerfen die App nicht stoppen
        pass


class ArchiveUnreadable(Exception):
    """Das Startarchiv ist vorhanden, aber nicht lesbar - es darf nicht geschrieben werden."""


def read_archive_strict(path: Path) -> pd.DataFrame:
    """
    Liest das Startarchiv fuer jeden Schreibvorgang.

    Fehlt die Datei, beginnt das Archiv leer. Ist sie vorhanden, aber nicht
    lesbar (Zerlegungs-, Rechte-, Encodingfehler, leer oder mit anderer
    Kopfzeile), bricht es mit ArchiveUnreadable ab: ein leeres Archiv
    darueberzuschreiben hiesse, den ganzen Bestand zu verlieren.
    """
    if not path.exists():
        return pd.DataFrame(columns=list(ARCHIVE_COLUMNS))
    try:
        roh = path.read_bytes()
    except OSError as exc:
        raise ArchiveUnreadable(
            "{} could not be read ({}). It was left untouched and not updated - "
            "please check the file.".format(path.name, exc)
        ) from exc
    # 0 Byte oder nur Leerraum: sieht aus wie ein abgebrochener Schreibvorgang.
    # Nicht still neu anlegen - der Benutzer entscheidet.
    if not roh.replace(b"\xef\xbb\xbf", b"").strip():
        raise ArchiveUnreadable(
            "{} is empty. It was left untouched and not updated - if no launches "
            "are to be kept, delete the file and a new archive is started.".format(path.name)
        )
    try:
        df = _read_csv_any(io.BytesIO(roh))
    except Exception as exc:
        raise ArchiveUnreadable(
            "{} could not be read ({}). It was left untouched and not updated - "
            "please check the file.".format(path.name, exc)
        ) from exc
    # Alle Spalten muessen da sein, und keine weiteren: fehlende wuerden beim
    # naechsten Schreiben geleert, unbekannte fielen weg. Alle Spalten kamen mit
    # derselben Fassung (b6c1130) - es gibt kein aelteres Archiv mit weniger.
    fehlend = [s for s in ARCHIVE_COLUMNS if s not in df.columns]
    fremd = [str(s) for s in df.columns if s not in ARCHIVE_COLUMNS]
    if fehlend or fremd:
        teile = []
        if fehlend:
            teile.append("missing columns: {}".format(", ".join(fehlend)))
        if fremd:
            teile.append("unknown columns: {}".format(", ".join(fremd)))
        raise ArchiveUnreadable(
            "{} does not have the launch archive columns ({}). It was left untouched "
            "and not updated - please check the file.".format(path.name, "; ".join(teile))
        )
    return df[list(ARCHIVE_COLUMNS)].fillna("").astype(str)


def load_archive(path: Path) -> pd.DataFrame:
    """
    Liest das Startarchiv fuer Anzeige und Zaehlung; fehlt oder bricht die
    Datei, beginnt es leer. Wer schreibt, liest mit read_archive_strict.

    Bewusst ohne Cache: die Anwendung schreibt diese Datei selbst, ein
    veralteter Zwischenstand waere hier gefaehrlicher als der Lesevorgang teuer.
    """
    try:
        return read_archive_strict(path)
    except ArchiveUnreadable:
        return pd.DataFrame(columns=list(ARCHIVE_COLUMNS))


def _write_bytes_atomic(path: Path, daten: bytes) -> None:
    """
    Schreibt erst eine temporaere Datei und benennt sie dann um.

    mkstemp legt die Datei mit 0600 an. Die Rechte einer vorhandenen Datei
    bleiben deshalb erhalten; eine neue bekommt, was die umask vorgibt
    (wie bei einem gewoehnlichen open).
    """
    # eindeutiger Name im selben Ordner, damit os.replace atomar bleibt
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        try:
            modus = os.stat(path).st_mode & 0o7777
        except FileNotFoundError:
            umask = os.umask(0)
            os.umask(umask)
            modus = 0o666 & ~umask
        os.chmod(tmp_name, modus)
        with os.fdopen(fd, "wb") as fh:
            fh.write(daten)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def persist_archive(path: Path, df: pd.DataFrame) -> None:
    """
    Schreibt das Archiv atomar in die Projektdatei - ein Absturz hinterlaesst
    die alte oder die neue Fassung, nie eine halbe.
    """
    try:
        _write_bytes_atomic(
            path, df[list(ARCHIVE_COLUMNS)].to_csv(index=False).encode("utf-8-sig")
        )
    except OSError:  # Schreibfehler duerfen die App nicht stoppen; der Import prueft nach
        pass


def group_to_export_dict(g: LaunchGroup) -> Dict[str, Any]:
    """JSON-taugliche Darstellung eines Starts."""
    data = asdict(g)
    data["window_from"] = g.window_from.isoformat() if g.window_from else None
    data["window_to"] = g.window_to.isoformat() if g.window_to else None
    data["launch_window"] = g.launch_window
    data["zone_count"] = g.zone_count
    # asdict() reicht datetime unverandert durch - json.dumps kann das nicht.
    data["advance_from"] = g.advance_from.isoformat() if g.advance_from else None
    data["advance_notice_hours"] = (
        round(g.advance_notice_hours, 1) if g.advance_notice_hours is not None else None
    )
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


def order_pasted_entries(
    n: int, offset: int, past_rows: Set[int]
) -> List[Tuple[int, bool]]:
    """
    Reihenfolge der eingefuegten Eintraege in der Seitenleiste.

    Eintrag i liegt in Tabellenzeile offset + i (combine_sources haengt die
    eingefuegten Eintraege hinter die Datei). Vergangene ans Ende, sonst bleibt
    die Reihenfolge - der Arbeitsstand selbst wird nicht umsortiert.
    """
    paare = [(i, (offset + i) in past_rows) for i in range(n)]
    return [p for p in paare if not p[1]] + [p for p in paare if p[1]]


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
            event.notam_id,
            " (pasted)" if is_manual else "",
            nation_label(event.nation) or "undetermined",
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
                    "<b>{}</b><br>Closure zone ({} points)<br>{}".format(
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
                popup="{}: radius {:.1f} km".format(event.notam_id, event.radius_km),
            ).add_to(fmap)

        folium.CircleMarker(
            location=[event.centroid_lat, event.centroid_lon],
            radius=6,
            color=color,
            fill=True,
            fill_opacity=0.9,
            popup=folium.Popup(
                "<b>{}</b><br>Launch: {}<br>Source: {}<br>Zone centroid<br>{:.4f}, {:.4f}<br>{}".format(
                    event.notam_id,
                    event.launch_group or "-",
                    event.source,
                    event.centroid_lat,
                    event.centroid_lon,
                    event.orbit_type,
                ),
                max_width=320,
            ),
            tooltip="Closure zone {}{}".format(
                label, " " + MANUAL_MARK + " verified by hand" if event.manual_override else ""
            ),
        ).add_to(fmap)
        bounds.append([event.centroid_lat, event.centroid_lon])

        if is_manual:
            # Manuell eingefuegte NOTAMs bekommen eine eigene Markierung, damit
            # sie in der Karte von den importierten unterscheidbar bleiben.
            folium.Marker(
                location=[event.centroid_lat, event.centroid_lon],
                icon=folium.Icon(color="purple", icon="edit", prefix="fa"),
                tooltip="{} - pasted by hand".format(event.notam_id),
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
    # Benannt statt nach Position: ein spaeter eingeschobener Parameter hat die
    # Argumente sonst stillschweigend verschoben.
    save_workspace(
        st.session_state.get("manual_notams", []),
        st.session_state.get("confirmed_launches", set()),
        st.session_state.get("hidden_events", set()),
        rejected=st.session_state.get("rejected_launches", set()),
        vehicle_assignments=st.session_state.get("vehicle_assignments", {}),
        payload_assignments=st.session_state.get("payload_assignments", {}),
        launch_site_assignments=st.session_state.get("launch_site_assignments", {}),
        archiv_removed=st.session_state.get("archiv_removed", set()),
        restored=st.session_state.get("restored_events", set()),
        seestarts_removed=st.session_state.get("seestarts_removed", set()),
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


def _render_pasted_entries(
    slot: Any,
    items: Sequence[Dict[str, Any]],
    flags: Optional[List[Tuple[int, bool]]] = None,
) -> None:
    """
    Zeichnet "Pasted entries" in den Platzhalter der Seitenleiste.

    `flags` kommt aus order_pasted_entries: (urspruenglicher Index, vergangen).
    Ohne `flags` unmarkiert in urspruenglicher Reihenfolge. "Remove" bekommt
    immer den urspruenglichen Index - die Liste im Arbeitsstand bleibt, wie sie ist.
    """
    if not items:
        return
    if flags is None:
        flags = [(i, False) for i in range(len(items))]
    n_past = sum(1 for _, vergangen in flags if vergangen)
    titel = (
        "Pasted entries ({} \u00b7 {} past)".format(len(items), n_past)
        if n_past
        else "Pasted entries ({})".format(len(items))
    )
    with slot:
        with st.expander(titel, expanded=True):
            for i, vergangen in flags:
                entry = items[i]
                # Eingefuegter Text ist Fremdtext: als Zeichen zeigen, nie als Markdown.
                preview = re.sub(r"\s+", " ", str(entry.get("text", "")))[:60]
                st.caption(
                    "**{}** \u00b7 {} \u2026{}".format(
                        _md_plain(entry.get("added", "")),
                        _md_plain(preview),
                        " (past)" if vergangen else "",
                    )
                )
                st.button(
                    "Remove",
                    key="del_manual_{}".format(i),
                    on_click=_remove_manual,
                    args=(i,),
                    use_container_width=True,
                )


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


def _push_undo(path: Path, label: str) -> Optional[Dict[str, Any]]:
    """
    Sichert den Dateistand vor einer Aenderung, damit sie ruecknehmbar bleibt.
    Rueckgabe: der neue Eintrag (None, wenn die Datei nicht lesbar war).
    """
    try:
        inhalt = path.read_text(encoding="utf-8")
    except OSError:
        return None
    stapel = st.session_state.setdefault("ref_undo", [])
    eintrag = {"pfad": str(path), "inhalt": inhalt, "label": label}
    stapel.append(eintrag)
    del stapel[:-UNDO_LIMIT]
    return eintrag


class UndoRefused(Exception):
    """Rueckgaengig wurde verweigert - die Meldung sagt dem Benutzer, warum."""


ARCHIVE_UNDO_REFUSED = (
    "Launch archive changed since this action - undo refused to protect newer entries."
)
ARCHIVE_UNDO_UNREADABLE = (
    "Launch archive could not be read - undo refused, the file was left untouched."
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _undo_archive(letzter: Dict[str, Any], stapel: List[Dict[str, Any]]) -> Optional[str]:
    """
    Nimmt eine Aenderung am Startarchiv zurueck - nur, wenn es seit dieser
    Aenderung unveraendert ist. Sonst (Import-Bestaetigungen, Tageslauf)
    wuerde die Ruecknahme neuere Zeilen still mit zuruecksetzen.

    Geaendert: der Eintrag faellt vom Stapel, denn dieser Stand kehrt nicht
    zurueck - und bliebe er liegen, versperrte er die Ruecknahme aller
    aelteren Referenzaenderungen darunter. Unlesbar: der Eintrag bleibt, der
    Benutzer kann die Datei pruefen und es erneut versuchen.
    """
    pfad = Path(letzter["pfad"])
    try:
        read_archive_strict(pfad)
        jetzt = _file_hash(pfad) if pfad.exists() else ""
    except (ArchiveUnreadable, OSError) as exc:
        raise UndoRefused(ARCHIVE_UNDO_UNREADABLE) from exc
    stapel.pop()
    if jetzt != letzter["archiv_nachher"]:
        raise UndoRefused(ARCHIVE_UNDO_REFUSED)
    try:
        # dieselben utf-8-sig-Bytes, die persist_archive vorher geschrieben hatte
        _write_bytes_atomic(pfad, letzter["roh"])
    except OSError:
        return None
    return letzter["label"]


def _undo_reference() -> Optional[str]:
    """
    Nimmt die letzte Referenzaenderung zurueck. Eine Aenderung am Startarchiv
    laeuft ueber _undo_archive und kann mit UndoRefused abgelehnt werden.
    """
    stapel = st.session_state.get("ref_undo", [])
    if not stapel:
        return None
    if "archiv_nachher" in stapel[-1]:
        return _undo_archive(stapel[-1], stapel)
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
        "{} removed - permanently deleted from {}.".format(key, path.name),
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
        "Search", key="sp_search", placeholder="Code, name or country \u2026"
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
        ("Code", "Name", "Lat", "Lon", "Country", ""), breiten, header=True
    )
    st.caption("{} of {} entries".format(len(zeilen), len(spaceports)))
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
            "Remove", key="rm_sp_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                SPACEPORT_CSV, spaceports, SPACEPORT_EXPORT_COLUMNS, "Kurzel", code
            )
            # Der Dialog laeuft als Fragment; ohne App-Scope wuerde nur er selbst
            # neu laufen und die Auswertung mit den alten Daten weiterrechnen.
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Only the first 60 matches are shown - narrow the search.")

    st.divider()
    with st.form("add_spaceport", clear_on_submit=True):
        st.markdown("**Add launch site**")
        a, b = st.columns(2)
        kurzel = a.text_input("Code", max_chars=12, placeholder="e.g. WSLC")
        land = b.selectbox("Country", TARGET_NATIONS, format_func=nation_label)
        name = st.text_input("Name", placeholder="e.g. Wenchang Space Launch Site")
        c, d = st.columns(2)
        lat = c.number_input("Latitude (°N)", -90.0, 90.0, 0.0, format="%.4f")
        lon = d.number_input("Longitude (°E)", -180.0, 180.0, 0.0, format="%.4f")
        if st.form_submit_button("Add", type="primary", use_container_width=True):
            code = kurzel.strip().upper()
            if not code:
                st.error("Code missing.")
            elif code in set(spaceports["Kurzel"].astype(str)):
                st.error("Code {} is already taken.".format(code))
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
        "Search", key="fir_search", placeholder="ICAO code, region, country or launch nation \u2026"
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
        ("ICAO", "Region / FIR", "Lat", "Lon", "FIR country", "Launch nation", ""),
        breiten, header=True,
    )
    st.caption("{} of {} entries".format(len(zeilen), len(firs)))
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
            "Remove", key="rm_fir_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                FIR_CSV, firs, FIR_EXPORT_COLUMNS, "ICAO Code", code
            )
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Only the first 60 matches are shown - narrow the search.")

    st.divider()
    with st.form("add_fir", clear_on_submit=True):
        st.markdown("**Add FIR / ACC**")
        a, b = st.columns(2)
        icao = a.text_input("ICAO code", max_chars=6, placeholder="e.g. ZLHW")
        land = b.text_input("FIR country", placeholder="e.g. China")
        name = st.text_input("Region / FIR name", placeholder="e.g. Lanzhou FIR")
        c, d = st.columns(2)
        lat = c.number_input("Latitude (°N)", -90.0, 90.0, 0.0, format="%.4f", key="fir_lat")
        lon = d.number_input("Longitude (°E)", -180.0, 180.0, 0.0, format="%.4f", key="fir_lon")
        nationen = st.multiselect(
            "Associated launch nation(s)", TARGET_NATIONS,
            help="Several nations mean the assignment needs the nation named in the NOTAM text.",
        )
        if st.form_submit_button("Add", type="primary", use_container_width=True):
            code = icao.strip().upper()
            if not code:
                st.error("ICAO code missing.")
            elif code in set(firs["ICAO Code"].astype(str)):
                st.error("ICAO code {} is already taken.".format(code))
            elif not nationen:
                st.error("Select at least one launch nation.")
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
        "Search", key="veh_search", placeholder="Abbreviation, name or country \u2026"
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
        ("Abbrev.", "Name", "English", "Country", ""), breiten, header=True
    )
    st.caption("{} of {} entries".format(len(zeilen), len(vehicles)))
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
            "Remove", key="rm_veh_{}".format(code), use_container_width=True
        ):
            _remove_reference_row(
                VEHICLE_CSV, vehicles, VEHICLE_EXPORT_COLUMNS, "Abkürzung", code
            )
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Only the first 60 matches are shown - narrow the search.")

    st.divider()
    with st.form("add_vehicle", clear_on_submit=True):
        st.markdown("**Add launch vehicle**")
        a, b = st.columns(2)
        kuerzel = a.text_input("Abbreviation", max_chars=20, placeholder="e.g. CZ-5B")
        land = b.selectbox("Country", TARGET_NATIONS, key="veh_land", format_func=nation_label)
        name = st.text_input("Name", placeholder="e.g. Chang Zheng 5B")
        englisch = st.text_input(
            "Alternative English name", placeholder="e.g. Long March 5B"
        )
        if st.form_submit_button("Add", type="primary", use_container_width=True):
            code = kuerzel.strip()
            if not code:
                st.error("Abbreviation missing.")
            elif code.upper() in {c.upper() for c in vehicles["Abkürzung"].astype(str)}:
                st.error("Abbreviation {} is already taken.".format(code))
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


@st.dialog("Reference Data", width="large")
def _reference_dialog(
    spaceports: pd.DataFrame, firs: pd.DataFrame, vehicles: pd.DataFrame
) -> None:
    """Optionsmenue zur Pflege der Startplatz- und FIR-Referenz."""
    st.caption(
        "Removed entries drop out of every calculation, added ones take effect "
        "immediately. Every change is written straight to the file on disk - "
        "use Undo below to take one back."
    )
    flash = st.session_state.pop("ref_flash", None)
    if flash:
        st.success(flash)
    flash_fehler = st.session_state.pop("ref_flash_error", None)
    if flash_fehler:
        st.error(flash_fehler)
    titel = [
        "Launch Sites ({})".format(len(spaceports)),
        "ICAO FIR / ACC ({})".format(len(firs)),
        "Launch Vehicles ({})".format(len(vehicles)),
        "Launch Archive ({})".format(len(load_archive(ARCHIVE_CSV))),
        "Sea Launches ({})".format(len(load_sea_launches(SEA_LAUNCH_CSV))),
    ]
    # Archiv-Import nur lokal (fail-closed), nie in der oeffentlichen Fassung
    mit_import = archive_import_allowed()
    if mit_import:
        titel.append("Archive Import")
    reiter = st.tabs(titel)
    with reiter[0]:
        _spaceport_editor(spaceports)
    with reiter[1]:
        _fir_editor(firs)
    with reiter[2]:
        _vehicle_editor(vehicles)
    with reiter[3]:
        _archive_editor()
    with reiter[4]:
        _sea_launch_editor()
    if mit_import:
        with reiter[5]:
            _archive_import_tab(spaceports, firs, vehicles)

    st.divider()
    stapel = st.session_state.get("ref_undo", [])
    st.caption(
        "Changes are written to `{}`, `{}`, `{}` and `{}` right away and "
        "survive a restart.".format(
            SPACEPORT_CSV.name, FIR_CSV.name, VEHICLE_CSV.name, ARCHIVE_CSV.name
        )
    )
    a, b, c, d = st.columns(4)
    if a.button(
        "Undo last change ({})".format(len(stapel)),
        disabled=not stapel,
        use_container_width=True,
    ):
        try:
            zurueck = _undo_reference()
        except UndoRefused as exc:
            st.session_state["ref_flash_error"] = str(exc)
        else:
            st.session_state["ref_flash"] = (
                "Undone: {}".format(zurueck) if zurueck else "Nothing to undo."
            )
        st.rerun(scope="app")
    b.download_button(
        "Download launch sites",
        data=reference_to_csv(spaceports, SPACEPORT_EXPORT_COLUMNS),
        file_name="weltraumbahnhoefe_koordinaten_updated.csv",
        mime="text/csv",
        use_container_width=True,
        help="Kopie des aktuellen Stands herunterladen.",
    )
    c.download_button(
        "Download FIRs",
        data=reference_to_csv(firs, FIR_EXPORT_COLUMNS),
        file_name="icao_fir_acc_coordinates_updated.csv",
        mime="text/csv",
        use_container_width=True,
    )
    d.download_button(
        "Download launch vehicles",
        data=reference_to_csv(vehicles, VEHICLE_EXPORT_COLUMNS),
        file_name="traegersysteme_updated.csv",
        mime="text/csv",
        use_container_width=True,
    )
    if st.button("Close", use_container_width=True, type="primary"):
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
    """
    Holt ein ausgeblendetes NOTAM zurueck - und zwar dauerhaft.

    Der Schluessel wandert zusaetzlich in `restored_events`. Ohne das waere der
    Knopf bei automatisch ausgeblendeten NOTAMs wirkungslos: solange die Meldung
    in der Tagesdatei steht, fiele sie beim naechsten Durchlauf sofort wieder
    heraus - ohne Hinweis, warum.
    """
    st.session_state["hidden_events"].discard(key)
    st.session_state.setdefault("restored_events", set()).add(key)
    _persist_workspace()


def _unhide_all() -> None:
    """Holt alle ausgeblendeten NOTAMs zurueck, auch die automatisch entfernten."""
    for schluessel in list(st.session_state.get("auto_hidden_keys", set())):
        st.session_state.setdefault("restored_events", set()).add(schluessel)
    st.session_state["hidden_events"].clear()
    _persist_workspace()


def _set_vehicle(widget_key: str, event_keys: Sequence[str]) -> None:
    """
    Uebernimmt die Auswahl aus dem Dropdown - fuer alle NOTAMs eines Starts.

    Die Trennzeile ist technisch waehlbar, weil Streamlit keine inaktiven
    Eintraege kennt. Wird sie gewaehlt, bleibt die bisherige Zuweisung stehen
    und das Dropdown springt zurueck.
    """
    gewaehlt = str(st.session_state.get(widget_key, VEHICLE_NONE) or "")
    zuweisungen = st.session_state.setdefault("vehicle_assignments", {})
    if gewaehlt == VEHICLE_SEPARATOR:
        bisher = next((zuweisungen[k] for k in event_keys if zuweisungen.get(k)), "")
        st.session_state[widget_key] = bisher
        return
    for schluessel in event_keys:
        if gewaehlt:
            zuweisungen[schluessel] = gewaehlt
        else:
            zuweisungen.pop(schluessel, None)
    _persist_workspace()


def _set_payload(widget_key: str, event_keys: Sequence[str]) -> None:
    """Uebernimmt den Freitext aus dem Payload-Feld - fuer alle Zonen eines Starts."""
    text = str(st.session_state.get(widget_key, "") or "").strip()
    zuweisungen = st.session_state.setdefault("payload_assignments", {})
    for schluessel in event_keys:
        if text:
            zuweisungen[schluessel] = text
        else:
            zuweisungen.pop(schluessel, None)
    _persist_workspace()


def _payload_field(
    event: "LaunchEvent", group_keys: Dict[str, List[str]], prefix: str
) -> None:
    """
    Freitextfeld fuer die Nutzlast.

    Bewusst kein Auswahlfeld: welche Nutzlast an Bord war, steht in keiner
    Referenz und wird oft erst Tage nach dem Start bekannt. Wie beim
    Traegersystem gilt der Eintrag fuer alle Sperrzonen desselben Starts.
    """
    schluessel = group_keys.get(event.key) or [event.key]
    widget_key = "{}_payload_{}".format(prefix, event.key)
    st.session_state[widget_key] = event.payload
    st.text_input(
        "Payload",
        key=widget_key,
        placeholder="e.g. Yaogan-XX · leave empty while unknown",
        on_change=_set_payload,
        args=(widget_key, schluessel),
        help="Manual entry. It changes nothing about the detection and can be "
        "added later at any time.",
    )


def _set_launch_site(widget_key: str, event_keys: Sequence[str]) -> None:
    """Uebernimmt die Pad-Wahl - fuer alle Sperrzonen desselben Starts."""
    gewaehlt = str(st.session_state.get(widget_key, "") or "")
    zuweisungen = st.session_state.setdefault("launch_site_assignments", {})
    for schluessel in event_keys:
        if gewaehlt:
            zuweisungen[schluessel] = gewaehlt
        else:
            zuweisungen.pop(schluessel, None)
    _persist_workspace()


def _launch_site_picker(
    event: "LaunchEvent",
    spaceports: pd.DataFrame,
    archiv: Optional[pd.DataFrame],
    group_keys: Dict[str, List[str]],
    prefix: str,
) -> None:
    """
    Auswahlliste fuer das Startgelaende - nur dort, wo es zwei gibt.

    Erscheint ausschliesslich, wenn der zugeordnete Platz nicht unterscheidbare
    Nachbarn hat. Ueberall sonst waere die Liste eine Scheinfrage: dort gibt es
    nichts zu waehlen.

    Die Vorgabe ist "not determined", nicht der naechstliegende Platz. Eine
    Vorgabe, die zufaellig oft richtig ist, waere eine Behauptung ohne Beleg -
    und spaeter nicht mehr von einer geprueften Angabe zu unterscheiden.
    """
    nachbarn = event.site_alternatives
    if not nachbarn:
        return
    schluessel = group_keys.get(event.key) or [event.key]
    gruppe = list(co_located_groups(spaceports).get(event.spaceport_code, ()))
    if not gruppe:
        return
    namen = {
        str(r["Kurzel"]): str(r["Name"])
        for _, r in spaceports.iterrows()
        if str(r["Kurzel"]) in gruppe
    }
    optionen = [""] + gruppe
    abstand = site_separation_km(gruppe, spaceports)
    widget_key = "{}_site_{}".format(prefix, event.key)
    st.session_state[widget_key] = event.launch_site if event.launch_site in optionen else ""
    st.selectbox(
        "Launch site",
        optionen,
        key=widget_key,
        format_func=lambda code: (
            "not determined" if not code
            else "{} - {}".format(code, namen.get(code, code))
        ),
        on_change=_set_launch_site,
        args=(widget_key, schluessel),
        help="These sites lie {:.1f} km apart. The closure zones cannot tell "
        "them apart - the azimuth differs by less than a quarter of a degree. "
        "Only you can decide this.".format(abstand),
    )
    hinweis = launch_site_history(archiv, event.vehicle, event.spaceport_code, spaceports)
    if hinweis:
        st.caption(hinweis)
    if len(schluessel) > 1:
        st.caption(
            "Applies to all {} closure zones of this launch.".format(len(schluessel))
        )


def _vehicle_picker(
    event: "LaunchEvent",
    vehicles: pd.DataFrame,
    group_keys: Dict[str, List[str]],
    prefix: str,
) -> None:
    """
    Dropdown zur manuellen Wahl des Traegersystems.

    Die Wahl gilt fuer alle Sperrzonen desselben erkannten Starts - dieselbe
    Rakete kann nicht in einer Zone eine andere sein als in der naechsten.
    """
    schluessel = group_keys.get(event.key) or [event.key]
    optionen = vehicle_options(vehicles, vehicle_nation(event))
    trenner = optionen.index(VEHICLE_SEPARATOR) if VEHICLE_SEPARATOR in optionen else None
    andere = set(optionen[trenner + 1:]) if trenner is not None else set()
    if event.vehicle and event.vehicle not in optionen:
        # Aus der Referenz entfernt: der Eintrag bleibt waehlbar, damit die
        # Zuweisung nicht unbemerkt auf "ohne" zurueckfaellt.
        optionen.append(event.vehicle)
    widget_key = "{}_vehicle_{}".format(prefix, event.key)
    st.session_state[widget_key] = event.vehicle if event.vehicle in optionen else VEHICLE_NONE
    st.selectbox(
        "Trägersystem",
        optionen,
        key=widget_key,
        format_func=lambda code: vehicle_label(code, vehicles, with_nation=code in andere),
        on_change=_set_vehicle,
        args=(widget_key, schluessel),
        help="Manual assignment. It changes nothing about the detection - "
        "neither nation nor launch site nor orbit.",
    )
    if len(schluessel) > 1:
        st.caption(
            "Applies to all {} closure zones of this launch.".format(len(schluessel))
        )


def _show_archive_status(platzhalter: Any) -> None:
    """Schreibt den Archivstand in die Seitenleiste."""
    try:
        anzahl = len(read_archive_strict(ARCHIVE_CSV))
    except ArchiveUnreadable:
        platzhalter.markdown(
            "{} Launch archive: unreadable - not updated".format(
                glyph(GLYPH_MISSING, COLOR_ERROR)
            ),
            unsafe_allow_html=True,
        )
        return
    platzhalter.markdown(
        "{} Launch archive: {} launch(es)".format(
            glyph(GLYPH_OK, COLOR_OK, 0.85), anzahl
        )
        if anzahl
        else "{} Launch archive: empty".format(glyph(GLYPH_EMPTY, COLOR_MUTED)),
        unsafe_allow_html=True,
    )


def _update_archive(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    table: pd.DataFrame,
) -> None:
    """
    Schreibt das Startarchiv fort.

    Beruecksichtigt werden alle Starts, die die Anwendung als solche fuehrt -
    bewusst ohne die Filter der Seitenleiste, damit eine Ansichtseinstellung
    nicht darueber entscheidet, was ins Archiv gelangt. Geschrieben wird nur,
    wenn sich tatsaechlich etwas geaendert hat.
    """
    ok_zeilen = (
        set(int(r) for r in table[table["Status"] == "OK"]["_row"])
        if len(table)
        else set()
    )
    kandidaten = [
        g for g in groups if g.spaceport_code and ok_zeilen & set(g.row_indices)
    ]
    if not kandidaten:
        return
    try:
        bestand = read_archive_strict(ARCHIVE_CSV)
    except ArchiveUnreadable as exc:
        # Nie ueber eine unlesbare Datei schreiben; die Auswertung laeuft weiter.
        st.warning("Launch archive: {}".format(exc))
        return
    neu = merge_archive(
        bestand,
        [archive_row(g, events) for g in kandidaten],
        set(st.session_state.get("archiv_removed", set())),
    )
    if neu.to_csv(index=False) != bestand.to_csv(index=False):
        persist_archive(ARCHIVE_CSV, neu)


def _update_sea_launches(
    events: Sequence["LaunchEvent"],
    groups: Sequence["LaunchGroup"],
    table: pd.DataFrame,
    spaceports: pd.DataFrame,
) -> None:
    """
    Schreibt das Seestart-Protokoll fort.

    Aufgenommen wird nur, was aus der Geometrie abgeleitet wurde - ein Start
    von einem verzeichneten Platz gehoert nicht hierher.

    Wichtig: Dieses Protokoll fliesst NICHT in die Startplatz-Suche zurueck.
    Eine Plattform steht beim naechsten Mal woanders; alte Positionen als
    Kandidaten zu fuehren hiesse, genau den Fehler nachzubauen, den die
    Ableitung behebt. Die Liste dient dem Vergleich und der Geschichte.
    """
    ok_zeilen = (
        set(int(r) for r in table[table["Status"] == "OK"]["_row"])
        if len(table)
        else set()
    )
    kandidaten = [
        g for g in groups if g.site_from_geometry and ok_zeilen & set(g.row_indices)
    ]
    if not kandidaten:
        return
    bestand = load_sea_launches(SEA_LAUNCH_CSV)
    neu = merge_sea_launches(
        bestand,
        [sea_launch_row(g, events, spaceports) for g in kandidaten],
        set(st.session_state.get("seestarts_removed", set())),
    )
    if neu.to_csv(index=False) != bestand.to_csv(index=False):
        persist_sea_launches(SEA_LAUNCH_CSV, neu)


def _remove_sea_launch_row(schluessel: str) -> None:
    """Loescht eine Protokollzeile dauerhaft."""
    _push_undo(SEA_LAUNCH_CSV, "Sea launch row removed")
    st.session_state.setdefault("seestarts_removed", set()).add(schluessel)
    bestand = load_sea_launches(SEA_LAUNCH_CSV)
    behalten = [
        r for _, r in bestand.iterrows() if sea_launch_key(dict(r)) != schluessel
    ]
    persist_sea_launches(
        SEA_LAUNCH_CSV, pd.DataFrame(behalten, columns=list(SEA_LAUNCH_COLUMNS))
    )
    _persist_workspace()
    st.session_state["ref_flash"] = "Sea launch row removed"


def _sea_launch_editor() -> None:
    """Tabelle des Seestart-Protokolls mit Entfernen-Funktion."""
    liste = load_sea_launches(SEA_LAUNCH_CSV)
    st.caption(
        "Launches from mobile platforms. The launch point here does not come "
        "from the launch-site reference but from the geometry of the messages: "
        "a small circular zone with the remaining closure areas lined up along "
        "one track from it. **This log does not feed back into the launch-site "
        "search**: a platform sits somewhere else next time."
    )
    if liste.empty:
        st.info(
            "No sea launch recorded yet. As soon as an analysis derives a launch "
            "point from the geometry, `{}` fills itself.".format(SEA_LAUNCH_CSV.name)
        )
        return
    breiten = (1.1, 0.8, 1.0, 1.0, 1.0, 0.9, 0.9, 1.7, 1.3)
    _reference_row(
        ("Date", "Time", "Nation", "Lat", "Lon", "Azimuth", "Incl.",
         "Nearest known site", ""),
        breiten,
        header=True,
    )
    st.caption("{} sea launch(es)".format(len(liste)))
    for _, r in liste.head(60).iterrows():
        schluessel = sea_launch_key(dict(r))
        knopf = _reference_row(
            (
                str(r["Datum"]), str(r["Zeit"]), str(r["Nation"])[:12],
                str(r["Breite"]), str(r["Länge"]), str(r["Azimut"]),
                str(r["Inklination"]), str(r["Nächster bekannter Platz"])[:24], "",
            ),
            breiten,
        )
        if knopf.button(
            "Remove",
            key="rm_sea_{}".format(hashlib.sha1(schluessel.encode()).hexdigest()[:10]),
            use_container_width=True,
        ):
            _remove_sea_launch_row(schluessel)
            st.rerun(scope="app")


def _remove_archive_row(schluessel: str) -> None:
    """
    Loescht eine Archivzeile - dauerhaft.

    Der Schluessel wandert in den Arbeitsstand, sonst legte der naechste Import
    denselben Start sofort wieder an, solange sein NOTAM in der Tagesdatei steht.
    """
    try:
        bestand = read_archive_strict(ARCHIVE_CSV)
    except ArchiveUnreadable as exc:
        st.error("Launch archive: {} Nothing was removed.".format(exc))
        return
    eintrag = _push_undo(ARCHIVE_CSV, "Archivzeile entfernt")
    if eintrag is not None:
        try:
            eintrag["roh"] = ARCHIVE_CSV.read_bytes()
        except OSError:
            st.session_state["ref_undo"].remove(eintrag)
            eintrag = None
    st.session_state.setdefault("archiv_removed", set()).add(schluessel)
    behalten = [
        r for _, r in bestand.iterrows() if archive_key(dict(r)) != schluessel
    ]
    persist_archive(
        ARCHIVE_CSV, pd.DataFrame(behalten, columns=list(ARCHIVE_COLUMNS))
    )
    if eintrag is not None:
        # Stand direkt nach dieser Aenderung - Rueckgaengig nur, solange er gilt
        try:
            eintrag["archiv_nachher"] = _file_hash(ARCHIVE_CSV)
        except OSError:
            eintrag["archiv_nachher"] = ""
    _persist_workspace()
    st.session_state["ref_flash"] = "Archivzeile entfernt"


def _archive_editor() -> None:
    """Tabelle des Startarchivs mit Entfernen-Funktion."""
    try:
        archiv = read_archive_strict(ARCHIVE_CSV)
    except ArchiveUnreadable as exc:
        st.error("Launch archive: {}".format(exc))
        return
    st.caption(
        "This file is written by the application itself: every recognised launch "
        "gets a row, payload or not. You add the payload under *NOTAM Data* - it is "
        "never overwritten by a later run. That is why there is no form to add a "
        "row here, only to remove one."
    )
    if archiv.empty:
        st.info(
            "No launches archived yet. As soon as a NOTAM file has been "
            "analysed, `{}` fills itself.".format(ARCHIVE_CSV.name)
        )
        return
    suche = st.text_input(
        "Search", key="archiv_suche", placeholder="NOTAM, nation, launch site, payload …"
    ).strip().lower()
    zeilen = archiv
    if suche:
        maske = archiv.apply(
            lambda r: suche in " ".join(str(v).lower() for v in r), axis=1
        )
        zeilen = archiv[maske]
    breiten = (1.5, 1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 0.9, 1.0)
    _reference_row(
        ("NOTAM", "Datum", "Zeit", "Nation", "Platz", "Vehicle", "Payload", "Orbit", ""),
        breiten,
        header=True,
    )
    st.caption("{} of {} launches".format(len(zeilen), len(archiv)))
    for _, r in zeilen.head(60).iterrows():
        schluessel = archive_key(dict(r))
        knopf = _reference_row(
            (
                "`{}`".format(str(r["NOTAM"])[:24]),
                str(r["Startdatum"]),
                str(r["Startzeit"]),
                str(r["Nation"])[:12],
                str(r["Weltraumbahnhof"]),
                str(r["Trägersystem"])[:14] or "-",
                str(r["Payload"])[:16] or "-",
                str(r["Orbit"]),
                "",
            ),
            breiten,
        )
        if knopf.button(
            "Remove",
            key="rm_arc_{}".format(hashlib.sha1(schluessel.encode()).hexdigest()[:10]),
            use_container_width=True,
        ):
            _remove_archive_row(schluessel)
            st.rerun(scope="app")
    if len(zeilen) > 60:
        st.info("Only the first 60 matches are shown - narrow the search.")


_RE_MD_ZEICHEN = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:/=])")


def _md_plain(text: Any) -> str:
    """
    Fremdtext (Forum, Upload, GCAT) fuer Markdown-Elemente entschaerfen.

    Beschriftungen von st.radio/st.expander und st.caption/st.warning werden
    als Markdown gesetzt; Links, Fettdruck, Farb- und Icon-Kurzformen aus
    fremden Texten sollen dort nur als Zeichen erscheinen.
    """
    return _RE_MD_ZEICHEN.sub(r"\\\1", str(text)).replace("\r", " ").replace("\n", " ")


def _archive_import_tab(
    spaceports: pd.DataFrame, firs: pd.DataFrame, vehicles: pd.DataFrame
) -> None:
    """
    Archiv-Import historischer NOTAMs (China, Russland, Indien, Iran, Nordkorea).

    Getrennt von der Tageslage: nichts hier beruehrt die eingefuegten NOTAMs
    oder die Arbeitsdatei der Sitzung. Ins Archiv kommt nur, was bestaetigt wird.
    Jeder Lade- und Schreibfehler erscheint als Meldung; dann wird nichts
    gespeichert und nicht neu gezeichnet. Jeder andere Fehler erscheint als
    eine Meldung im Reiter - der Optionsdialog zeichnet alle Reiter bei jedem
    Durchlauf, ein Fehler hier darf die anderen nicht mitreissen.
    """
    # Steuerausnahmen von st.rerun/st.stop - erben in 1.50 von BaseException,
    # werden unten trotzdem ausdruecklich durchgereicht
    from streamlit.runtime.scriptrunner import RerunException, StopException

    try:
        import archiv_import as ai  # erst hier - siehe Modulkopf von archiv_import

        try:
            korpus = ai.load_korpus()
            zustand = ai.load_state()
        except (ai.ImportStateError, OSError) as exc:
            st.error(_md_plain(exc))
            return
        st.caption(
            "Historic launches of China, Russia, India, Iran and North Korea. "
            "Save NSF thread pages in your browser (or copy a whole page) and import "
            "them here. Detection is the same as in daily use; nothing is written to "
            "the archive until you confirm it. US launches are left out."
        )

        with st.form("archiv_import_form", clear_on_submit=True):
            dateien = st.file_uploader(
                "Forum pages", type=["html", "htm", "txt"], accept_multiple_files=True
            )
            text = st.text_area("Or paste a whole page", height=120)
            los = st.form_submit_button("Import", type="primary")
        if los:
            bericht = ai.ingest(korpus, [(d.name, d.getvalue()) for d in dateien or []], text or "")
            balken = st.progress(0.0, text="Analysing days …")
            bericht.tage_ausgewertet = ai.reevaluate(
                korpus, zustand, spaceports, firs,
                fortschritt=lambda n, g: balken.progress(
                    n / g, text="Analysing day {} of {}".format(n, g)
                ),
            )
            balken.empty()
            try:
                ai.save_korpus(korpus)
                ai.save_state(zustand)
            except (ai.ImportStateError, OSError) as exc:
                st.error(_md_plain(exc))
            else:
                st.session_state["archiv_import_bericht"] = bericht
        # Bericht nur einmal zeigen - beim naechsten Durchlauf ist er weg
        bericht = st.session_state.pop("archiv_import_bericht", None)
        if bericht is not None:
            summen = ai.totals(zustand)
            st.info(
                "{} file(s) · {} new NOTAM(s) · {} duplicate(s) · {} not usable · "
                "{} day(s) analysed · {} US case(s) left out in total · {} hidden in total".format(
                    bericht.dateien, bericht.notams_neu, bericht.dubletten, bericht.unbrauchbar,
                    bericht.tage_ausgewertet, summen["usa"], summen["ausgeblendet"],
                )
            )
            for fehler in bericht.fehler:
                st.warning(_md_plain(fehler))

        if ai.is_stale(zustand):
            st.warning(
                "NOLA's detection changed since the last analysis ({} days). Re-analyse "
                "them so the candidates reflect the current rules.".format(len(zustand["tage"]))
            )
            if st.button("Re-analyse all days"):
                balken = st.progress(0.0)
                ai.reevaluate(
                    korpus, zustand, spaceports, firs, alle=True,
                    fortschritt=lambda n, g: balken.progress(n / g, text="Day {} of {}".format(n, g)),
                )
                try:
                    ai.save_state(zustand)
                except (ai.ImportStateError, OSError) as exc:
                    st.error(_md_plain(exc))
                else:
                    st.rerun(scope="app")

        waisen = ai.orphans(zustand)
        if waisen:
            st.subheader("No longer recognised ({})".format(len(waisen)))
            st.caption(
                "Confirmed launches whose NOTAMs no longer form a launch with the current "
                "detection. They are still in the archive until you decide."
            )
            for key, e in waisen[:40]:
                a, b, c = st.columns([3, 1, 1])
                a.text("{} · {} · {}".format(key, e.get("rakete", ""), e.get("payload", "")))
                if b.button("Keep", key="ai_keep_" + key):
                    try:
                        ai.keep_orphan(zustand, key)
                        ai.save_state(zustand)
                    except (ai.ImportStateError, OSError) as exc:
                        st.error(_md_plain(exc))
                    else:
                        st.rerun(scope="app")
                if c.button("Remove from archive", key="ai_rm_" + key):
                    try:
                        ai.remove_orphan(zustand, key)
                        ai.save_state(zustand)
                    except (ai.ImportStateError, OSError) as exc:
                        st.error(_md_plain(exc))
                    else:
                        st.rerun(scope="app")

        links, rechts = st.columns([3, 1])
        # Beim Oeffnen nie laden: alle Reiter laufen bei jedem Durchlauf, ein
        # 13-MB-Abruf ohne Cache wuerde den ganzen Optionsdialog blockieren.
        gcat, gcat_status = ai.load_gcat(
            refresh=rechts.button("Refresh launch list"), auto_download=False
        )
        links.caption(_md_plain(gcat_status))
        sites = ai.load_gcat_sites()

        kandidaten = ai.candidates(zustand)
        offen = [k for k in kandidaten if k["entscheidung"] is None]
        # Abgleich je offenem Kandidaten einmal pro Durchlauf, fuer Sammel- und Einzelansicht
        abgleiche = {k["key"]: ai.match_candidate(k, gcat, sites) for k in offen}
        st.subheader("Candidates ({} open of {})".format(len(offen), len(kandidaten)))
        sammel = ai.bulk_candidates(kandidaten, gcat, sites, vehicles, abgleiche=abgleiche)
        if st.button(
            "Confirm all unique matches ({})".format(len(sammel)), disabled=not sammel
        ):
            try:
                ai.confirm_many(zustand, sammel)
                ai.save_state(zustand)
            except (ai.ImportStateError, OSError) as exc:
                st.error(_md_plain(exc))
            else:
                st.rerun(scope="app")

        jahre = sorted({k["tag"][:4] for k in offen}, reverse=True)
        if jahre:
            jahr = st.selectbox("Year", jahre, key="archiv_import_jahr")
            for k in [k for k in offen if k["tag"].startswith(jahr)][:40]:
                _archive_import_candidate(ai, zustand, k, abgleiche[k["key"]], vehicles)

        pruef = ai.review_items(zustand)
        st.subheader("Review list ({})".format(len(pruef)))
        for p in pruef[:40]:
            with st.expander(_md_plain("{} · {} · {}".format(p["tag"], p["notam_id"], p["grund"][:80]))):
                st.code(p["text"], language=None)
                st.text("Source: " + ", ".join(p["quellen"]))
                a, b = st.columns(2)
                if a.button("Space Launch", key="ai_sl_" + p["event_key"]):
                    ai.review_launch(zustand, korpus, p["event_key"], p["tag"], spaceports, firs)
                    try:
                        ai.save_state(zustand)
                    except (ai.ImportStateError, OSError) as exc:
                        st.error(_md_plain(exc))
                    else:
                        st.rerun(scope="app")
                if b.button("Hide", key="ai_hide_" + p["event_key"]):
                    ai.review_hide(zustand, p["event_key"])
                    try:
                        ai.save_state(zustand)
                    except (ai.ImportStateError, OSError) as exc:
                        st.error(_md_plain(exc))
                    else:
                        st.rerun(scope="app")
    except (RerunException, StopException):
        raise
    except Exception as exc:  # noqa: BLE001 - Meldung statt kaputtem Optionsdialog
        st.error(_md_plain("Archive import failed: {}".format(exc)))


def _archive_import_candidate(
    ai: Any,
    zustand: Dict[str, Any],
    k: Dict[str, Any],
    abgleich: Any,
    vehicles: pd.DataFrame,
) -> None:
    """Ein Kandidat mit Vorschlag, Auswahl und den beiden Entscheidungen."""
    row = k["row"]
    # im_archiv: vorhandene Archivzeilen (etwa Tagesbetrieb) desselben Starts
    im_archiv = k.get("im_archiv") or []
    if im_archiv:
        status = "already archived"
    elif k["ersetzt"]:  # Liste der Vorgaenger-Schluessel, leer = keiner
        status = "updated"
    else:
        status = abgleich.status
    kopf = "{} {} · {} · {} · {} · {}".format(
        row["Startdatum"], row["Startzeit"], nation_label(k["nation"]),
        row["Weltraumbahnhof"] or "sea", row["Orbit"], status,
    )
    with st.expander(_md_plain(kopf)):
        # Quellen und Hinweise stammen aus Forum/Upload/GCAT: nur als Text
        st.text("NOTAM: {} · Source: {}".format(row["NOTAM"], ", ".join(k["quellen"])))
        # Werte der Zielzeile(n) - bei 'updated' der Vorgaenger - gehen vor dem
        # GCAT-Vorschlag; bei widerspruechlichen Werten wird nichts vorbelegt
        archiv_werte = k.get("archiv_werte") or []
        vorbelegung = archiv_werte if im_archiv else (k.get("ersetzt_werte") or [])
        # je Spalte: der eine vorhandene Wert, "" = keiner, None = widerspruechlich
        vorhanden: Dict[str, Optional[str]] = {}
        for spalte in ("Tr\u00e4gersystem", "Payload"):
            gefuellt = sorted({w[spalte] for w in vorbelegung if w.get(spalte)})
            vorhanden[spalte] = None if len(gefuellt) > 1 else (gefuellt or [""])[0]
        if im_archiv:
            st.text(
                "Already in the archive. Confirming sets only vehicle and payload of: "
                + "; ".join(im_archiv)
            )
            for w in archiv_werte:
                st.text("{} - current vehicle: {} · payload: {}".format(
                    w["key"], w.get("Tr\u00e4gersystem") or "-", w.get("Payload") or "-"
                ))
            for alt in k["ersetzt"]:
                st.text(
                    "Older import row {} remains in the archive. Remove it in the "
                    "Launch Archive tab if it is no longer needed.".format(alt)
                )
        elif k["ersetzt"]:
            # Bestaetigen loescht diese Importzeilen - vorher sichtbar machen
            ersetzt_werte = {w["key"]: w for w in k.get("ersetzt_werte") or []}
            for alt in k["ersetzt"]:
                w = ersetzt_werte.get(alt, {})
                st.text(
                    "Confirming will REPLACE (delete) the older import row {} - current "
                    "vehicle: {} · payload: {}".format(
                        alt, w.get("Tr\u00e4gersystem") or "-", w.get("Payload") or "-"
                    )
                )
        for w in abgleich.warnungen:
            st.warning(_md_plain(w))
        for h in abgleich.hinweise:
            st.text(h)
        treffer = None
        if abgleich.treffer:
            # Startplatz mit anzeigen: ein Seestart kann neben Landstarts
            # derselben Nation stehen
            keiner = "none of these"
            beschriftung = [
                _md_plain("{} · {} · {} · {} · {}".format(
                    s.tag, s.zeit.strftime("%d.%m.%Y %H:%M"), s.site or "?", s.rakete, s.nutzlast
                ))
                for s in abgleich.treffer
            ] + [keiner]
            # Nur ein eindeutiger Treffer ist vorgewaehlt; sonst waehlt der Benutzer aktiv
            vorwahl = 0 if abgleich.status == ai.STATUS_EINDEUTIG else len(beschriftung) - 1
            wahl = st.radio("GCAT", beschriftung, index=vorwahl, key="ai_gcat_" + k["key"])
            if wahl is not None and wahl != keiner:
                treffer = abgleich.treffer[beschriftung.index(wahl)]
        gcat_code = ai.vehicle_code_for(treffer.rakete, vehicles) if treffer else ""
        optionen = vehicle_options(vehicles, k["nation"])
        vorschlag = gcat_code
        payload_vorschlag = treffer.nutzlast if treffer else ""
        if vorhanden["Tr\u00e4gersystem"] is None:
            vorschlag = VEHICLE_NONE
        elif vorhanden["Tr\u00e4gersystem"]:
            vorschlag = vorhanden["Tr\u00e4gersystem"]
            if vorschlag not in optionen:  # Kuerzel ausserhalb der Referenz
                optionen = [optionen[0], vorschlag] + optionen[1:]
        if vorhanden["Payload"] is None:
            payload_vorschlag = ""
        elif vorhanden["Payload"]:
            payload_vorschlag = vorhanden["Payload"]
        rakete = st.selectbox(
            "Launch vehicle",
            optionen,
            index=optionen.index(vorschlag) if vorschlag in optionen else 0,
            format_func=lambda c: vehicle_label(c, vehicles),
            key="ai_veh_{}_{}".format(k["key"], treffer.tag if treffer else ""),
        )
        if treffer and not gcat_code and treffer.rakete:
            st.text(
                "GCAT vehicle '{}' has no entry in the vehicle reference.".format(treffer.rakete)
            )
        payload = st.text_input(
            "Payload", value=payload_vorschlag,
            key="ai_pay_{}_{}".format(k["key"], treffer.tag if treffer else ""),
        )
        a, b = st.columns(2)
        if a.button("Confirm", key="ai_ok_" + k["key"], type="primary"):
            wert = "" if rakete == VEHICLE_SEPARATOR else rakete
            try:
                ai.confirm_many(zustand, [(k, wert, payload.strip(), treffer)])
                ai.save_state(zustand)
            except (ai.ImportStateError, OSError) as exc:
                st.error(_md_plain(exc))
            else:
                st.rerun(scope="app")
        if b.button("Discard", key="ai_no_" + k["key"]):
            ai.reject(zustand, k["key"])
            try:
                ai.save_state(zustand)
            except (ai.ImportStateError, OSError) as exc:
                st.error(_md_plain(exc))
            else:
                st.rerun(scope="app")


#: Schriftstapel. Die Grotesk tritt nur in der Wortmarke und in Ueberschriften
#: auf - gross, selbstbewusst und mit viel ruhiger Flaeche um sie herum, nie im
#: Mengensatz. Den Fliesstext traegt eine humanistische Grotesk, die waermer und
#: nahbarer wirkt. Beide Stapel enden bei Arial: sie liegt auf jedem Rechner und
#: ist die vorgesehene Ersatzschrift, wenn die Hausschrift fehlt. Keine
#: Webschrift wird geladen - das spart eine Lizenz und einen Netzzugriff.
FONT_GROTESK = '"Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif'
FONT_HUMANIST = '"Myriad Pro", Myriad, "Segoe UI", Arial, "Liberation Sans", sans-serif'

#: Durchschuss zwischen Wortmarke, Unterzeile und Beschreibung. Derselbe Wert
#: wiederholt sich - diese Selbstaehnlichkeit haelt die Kopfzeile zusammen.
LEADING_REM = 0.55

#: Unbunte Skala. Farbe traegt in dieser Oberflaeche ausschliesslich
#: Information; die Wortmarke und alle Flaechen bleiben neutral.
INK_WHITE = "#FFFFFF"
INK_COOLGRAY = "#ADAFAF"
INK_SILVER = "#9A9B9C"
INK_ANTHRACITE = "#757575"

STYLE_HTML = """
<style>
:root {{
  --nola-grotesk: {grotesk};
  --nola-humanist: {humanist};
  --nola-durchschuss: {leading}rem;
}}

/* Mengensatz in der humanistischen Grotesk, Ueberschriften in der Grotesk. */
html, body, [class*="st-"], .stMarkdown, .stDataFrame {{
  font-family: var(--nola-humanist);
}}
/* Ausnahme: Icons sind Ligaturen. Im DOM steht ihr Name als Text
   ("keyboard_arrow_down"), erst die Icon-Schrift macht daraus ein Zeichen.
   Wird sie mit ueberschrieben, erscheint der Rohtext im Aufklapper. */
[data-testid="stIconMaterial"],
span[translate="no"],
.material-symbols-rounded {{
  font-family: "Material Symbols Rounded" !important;
}}
h1, h2, h3, h4, h5, h6 {{
  font-family: var(--nola-grotesk);
  font-weight: 700;
  letter-spacing: 0.01em;
}}

/* --- Wortmarke ---------------------------------------------------------
   Zweizeilig, ohne Wortzwischenraeume, Versalbuchstaben trennen die Woerter,
   Schlusspunkt auf der zweiten Zeile. Die Farbdifferenzierung der Wortteile
   dient der Lesbarkeit, nicht der Dekoration - sie bleibt unbunt. */
.nola-kopf {{ margin: 0.5rem 0 2.2rem 0; }}
.nola-marke {{
  --nola-mh: clamp(5.2rem, 12vw, 7.4rem);
  display: flex;
  align-items: flex-end;
}}
/* Die Katze liegt in der SVG nicht am linken Rand (ca. 20 % Leerraum). Der
   negative Aussenabstand holt diesen Rand zurueck und laesst bewusst nur
   rund 0.9rem sichtbaren Abstand zur Wortmarke - enger als die Vorlage. */
.nola-maskottchen {{
  height: var(--nola-mh);
  width: auto;
  flex: none;
  margin-left: calc(var(--nola-mh) * -0.197 + 0.9rem);
}}
.nola-wort {{
  font-family: var(--nola-grotesk);
  font-weight: 700;
  font-size: clamp(2.6rem, 7vw, 4.2rem);
  line-height: 1;
  letter-spacing: 0.02em;
  color: {weiss};
}}
.nola-lang {{
  margin-top: var(--nola-durchschuss);
  font-family: var(--nola-grotesk);
  font-weight: 700;
  font-size: clamp(0.95rem, 2vw, 1.25rem);
  line-height: 1;
  letter-spacing: 0.01em;
  color: {silber};
}}
.nola-lang .hell {{ color: {coolgray}; }}
.nola-zeile {{
  margin-top: var(--nola-durchschuss);
  font-size: 0.80rem;
  line-height: 1.4;
  color: {anthrazit};
}}

</style>
"""

HEADER_HTML = """
<div class="nola-kopf">
  <div class="nola-marke">
    <div class="nola-text">
      <div class="nola-wort">NOLA</div>
      <div class="nola-lang">Notam<span class="hell">Launch</span>Analyzer.</div>
    </div>
    __MASKOTTCHEN__
  </div>
  <div class="nola-zeile">
    Daily screening of NOTAM files for space launches &middot; China &middot;
    Russia &middot; India &middot; Iran &middot; North Korea &middot; USA
  </div>
</div>
"""


MASCOT_SVG = APP_DIR / "assets" / "notam-mascot-transparent.svg"


def _mascot_img() -> str:
    """Maskottchen als eingebettetes Bild; fehlt die Datei, bleibt die Wortmarke allein."""
    try:
        daten = base64.b64encode(MASCOT_SVG.read_bytes()).decode("ascii")
    except OSError:
        return ""
    return (
        '<img class="nola-maskottchen" alt="" '
        'src="data:image/svg+xml;base64,{}">'.format(daten)
    )


def _render_header() -> None:
    """Zeichnet Gestaltungsregeln und Kopfzeile."""
    st.markdown(
        STYLE_HTML.format(
            grotesk=FONT_GROTESK,
            humanist=FONT_HUMANIST,
            leading=LEADING_REM,
            weiss=INK_WHITE,
            silber=INK_SILVER,
            coolgray=INK_COOLGRAY,
            anthrazit=INK_ANTHRACITE,
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        HEADER_HTML.replace("__MASKOTTCHEN__", _mascot_img()),
        unsafe_allow_html=True,
    )



def _reference_status(label: str, path: Path) -> Tuple[Optional[pd.DataFrame], str]:
    """Laedt eine Referenz-CSV und liefert Dataframe plus Statusmeldung."""
    if not path.exists():
        return None, "{} {}: file not found ({})".format(
            glyph(GLYPH_MISSING, COLOR_ERROR), label, path.name
        )
    try:
        stamp = path.stat().st_mtime
        if "weltraum" in path.name:
            df = load_spaceports(str(path), stamp)
        elif "traegersysteme" in path.name:
            df = load_vehicles(str(path), stamp)
        else:
            df = load_firs(str(path), stamp)
    except Exception as exc:
        return None, "{} {}: {}".format(glyph(GLYPH_MISSING, COLOR_ERROR), label, exc)
    return df, "{} {}: {} entries ({})".format(
        glyph(GLYPH_OK, COLOR_OK, 0.85),
        label,
        len(df),
        datetime.fromtimestamp(stamp).strftime("%d.%m.%Y %H:%M"),
    )


def main() -> None:
    st.set_page_config(
        page_title="NOLA",
        page_icon="\u25B8",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if not st.session_state.get("workspace_loaded"):
        gespeichert = load_workspace()
        st.session_state["manual_notams"] = list(gespeichert.get("manual_notams", []))
        st.session_state["confirmed_launches"] = set(gespeichert.get("confirmed_launches", []))
        st.session_state["hidden_events"] = set(gespeichert.get("hidden_events", []))
        st.session_state["rejected_launches"] = set(gespeichert.get("rejected_launches", []))
        for feld in (
            "vehicle_assignments", "payload_assignments", "launch_site_assignments",
        ):
            roh = gespeichert.get(feld, {})
            st.session_state[feld] = (
                {str(k): str(v) for k, v in roh.items() if v}
                if isinstance(roh, dict)
                else {}
            )
        st.session_state["archiv_removed"] = migrate_archive_keys(
            gespeichert.get("archiv_removed", [])
        )
        st.session_state["restored_events"] = set(gespeichert.get("restored_events", []))
        st.session_state["seestarts_removed"] = set(
            gespeichert.get("seestarts_removed", [])
        )
        st.session_state["workspace_loaded"] = True
    st.session_state.setdefault("manual_notams", [])
    st.session_state.setdefault("manual_feedback", None)
    st.session_state.setdefault("confirmed_launches", set())
    st.session_state.setdefault("hidden_events", set())
    st.session_state.setdefault("rejected_launches", set())
    st.session_state.setdefault("vehicle_assignments", {})
    st.session_state.setdefault("payload_assignments", {})
    st.session_state.setdefault("launch_site_assignments", {})
    st.session_state.setdefault("archiv_removed", set())
    st.session_state.setdefault("restored_events", set())
    st.session_state.setdefault("seestarts_removed", set())
    st.session_state.setdefault("focus_rows", [])
    st.session_state.setdefault("goto_notam_data", False)
    st.session_state.setdefault("ref_undo", [])
    st.session_state.setdefault("ref_dialog_open", False)
    st.session_state.setdefault("ref_flash", None)

    _render_header()

    # ----------------------------- Sidebar ------------------------------- #
    with st.sidebar:
        kopf, zahnrad = st.columns([6, 1], vertical_alignment="bottom")
        kopf.header("Reference Data")
        # Stift als Strichsymbol aus der Material-Bibliothek statt eines
        # beschrifteten Knopfes - dieselbe Sprache wie die Referenzoberflaeche,
        # die ihre Bearbeiten-Funktion ebenso als Stift fuehrt. "tertiary"
        # nimmt dem Knopf Rahmen und Flaeche, es bleibt das Symbol.
        if zahnrad.button(
            "",
            icon=":material/edit:",
            help="Manage reference data",
            type="tertiary",
            key="ref_edit",
        ):
            st.session_state["ref_dialog_open"] = True

        spaceports, sp_msg = _reference_status("Weltraumbahnhoefe", SPACEPORT_CSV)
        firs, fir_msg = _reference_status("ICAO FIR/ACC", FIR_CSV)
        vehicles, veh_msg = _reference_status("Traegersysteme", VEHICLE_CSV)

        st.markdown(sp_msg, unsafe_allow_html=True)
        st.markdown(fir_msg, unsafe_allow_html=True)
        st.markdown(veh_msg, unsafe_allow_html=True)
        # Platzhalter: das Archiv waechst erst weiter unten, waehrend der
        # Auswertung. Ohne ihn zeigte die Seitenleiste den Stand von vorhin.
        archiv_status = st.empty()
        _show_archive_status(archiv_status)

        if spaceports is None or firs is None or vehicles is None:
            st.error(
                "All three reference CSVs must sit in the folder of app.py:\n\n"
                "- `weltraumbahnhoefe_koordinaten_updated.csv`\n"
                "- `icao_fir_acc_coordinates_updated.csv`\n"
                "- `traegersysteme_updated.csv`"
            )
            st.stop()

        st.divider()
        st.header("Import")
        uploaded = st.file_uploader(
            "Upload the daily NOTAM file",
            type=["csv", "txt", "xls", "xlsx"],
            accept_multiple_files=False,
            help="CSV or Excel export (e.g. FAA FNS). Leading title rows are detected.",
        )
        use_demo = st.toggle(
            "Use demo data set",
            value=False,
            help="Sample NOTAMs to exercise the pipeline without your own file.",
        )
        st.divider()
        st.header("Paste NOTAM")
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
                "Any NOTAM format: ICAO items, FAA domestic (!FDC ...) or plain "
                "text. Coordinates as 1936N11057E, 19°36'N 110°57'E or decimal "
                "degrees. Several NOTAMs at once are split at their identifiers, "
                "otherwise at blank lines."
            ),
        )
        st.button(
            "Add",
            on_click=_add_manual_notams,
            use_container_width=True,
            type="primary",
        )

        feedback = st.session_state.get("manual_feedback")
        if feedback:
            st.success("{} NOTAM(s) added.".format(feedback))
        elif feedback == 0:
            st.warning("Kein auswertbarer Text erkannt.")

        manual_items = st.session_state["manual_notams"]
        # Platzhalter: die Liste wird erst nach der Auswertung gezeichnet, damit
        # vergangene Starts markiert und ans Ende gestellt werden koennen.
        pasted_slot = st.container()
        if manual_items:
            st.button(
                "Discard all pasted entries",
                on_click=_clear_manual,
                use_container_width=True,
            )

        st.divider()
        min_conf = st.select_slider(
            "Mindest-Konfidenz",
            options=["HIGH", "MEDIUM", "LOW"],
            value="MEDIUM",
            help=(
                "The triggers from the specification (SFC/UNL, 000/999, area keywords) "
                "also fire on weather balloons, gunnery exercises and searchlights. The "
                "scoring weights space-specific terms positively and exclusion terms "
                "negatively. Rejected NOTAMs stay visible under Review."
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
            st.error("Could not read the upload: {}".format(exc))
            # Die Liste der eingefuegten Eintraege verschwindet nie.
            _render_pasted_entries(pasted_slot, manual_items)
            st.stop()
    elif use_demo:
        imported = build_demo_notams()
        source_label = "demo data set"

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
        source_label = "{}{}{} pasted".format(
            source_label, " + " if source_label else "", len(manual_entries)
        )

    if notams.empty:
        _render_pasted_entries(pasted_slot, manual_items)
        st.info(
            "Upload a NOTAM file on the left, paste a NOTAM, or switch on the "
            "demo data set to start the analysis."
        )
        col_a, col_b = st.columns(2)
        with col_a:
            with st.expander("Expected file format"):
                st.markdown(
                    "CSV, XLS or XLSX. The parser detects columns automatically; "
                    "`NOTAM ID`, `NOTAM Text`, `FIR`, `Valid From` and `Valid To` "
                    "help. If only a full-text column exists, it is analysed as a "
                    "whole. Leading title rows (e.g. FAA FNS exports) are skipped."
                )
                st.dataframe(build_demo_notams().head(3), use_container_width=True)
        with col_b:
            with st.expander("Paste field"):
                st.markdown(
                    "The **Paste NOTAM** field takes a NOTAM directly - ICAO items, "
                    "FAA domestic format or plain text. Those entries are marked "
                    "`Pasted` in the table, on the map and in the export, and stay "
                    "until you discard them."
                )
        return

    # Die Liste muss auch dann stehen, wenn die Auswertung scheitert (der
    # einzelne Eintrag soll sich dann noch entfernen lassen). Fehler werden
    # nicht verschluckt, das finally zeichnet nur, falls noch nichts steht.
    gezeichnet = False
    try:
        with st.spinner("Analysing NOTAMs \u2026"):
            events, stats = analyze_notams(
                notams,
                spaceports,
                firs,
                min_confidence=min_conf,
                confirmed_keys=st.session_state["confirmed_launches"],
                rejected_keys=st.session_state["rejected_launches"],
            )
        # Automatisch ausgeblendet wird erst hier, nicht in der Auswertung: so bleibt
        # die Entscheidung an einer Stelle, und ein von Hand zurueckgeholtes NOTAM
        # bleibt zurueck.
        zurueckgeholt = st.session_state["restored_events"]
        auto_hidden_keys = {
            e.key for e in events if e.auto_hidden_reason and e.key not in zurueckgeholt
        }
        st.session_state["auto_hidden_keys"] = auto_hidden_keys
        hidden_keys = set(st.session_state["hidden_events"]) | auto_hidden_keys
        hidden_events = [e for e in events if e.key in hidden_keys]
        visible_events = [e for e in events if e.key not in hidden_keys]
        apply_vehicle_assignments(
            events, stats.get("groups", []), st.session_state["vehicle_assignments"]
        )
        apply_payload_assignments(
            events, stats.get("groups", []), st.session_state["payload_assignments"]
        )
        # Vor der Tabelle und vor dem Archivschreiben: die Pad-Wahl veraendert
        # Kuerzel und Name des Startplatzes und muss in beiden stehen.
        apply_launch_site_assignments(
            events,
            stats.get("groups", []),
            spaceports,
            st.session_state["launch_site_assignments"],
        )
        # Einmal je Durchlauf gelesen: der Pad-Hinweis rechnet darauf, und je Zeile
        # zu lesen hiesse, dieselbe Datei dutzendfach anzufassen.
        pad_historie = load_archive(ARCHIVE_CSV)
        table = events_to_dataframe(visible_events, vehicles)
        _update_archive(events, stats.get("groups", []), table)
        _update_sea_launches(events, stats.get("groups", []), table, spaceports)
        _show_archive_status(archiv_status)

        # Vergangene Starts: erst jetzt, das Archiv ist geschrieben. Ausgeblendet
        # wird nur Archiviertes; geloescht wird nichts.
        archiv_keys, archiv_grund = archive_keys_or_reason(ARCHIVE_CSV)
        entfernt = set(st.session_state.get("archiv_removed", set()))
        jetzt = datetime.now(timezone.utc)
        past_rows = (
            past_launch_rows(
                stats.get("groups", []), events, archiv_keys, jetzt, entfernt=entfernt
            )
            if archiv_keys is not None
            else set()
        )
        past_groups = {
            g.group_id for g in stats.get("groups", []) if set(g.row_indices) & past_rows
        }
        archiv_hinweis = archive_hints(
            stats.get("groups", []), events, past_groups, entfernt
        )
        # Eingefuegte Eintraege liegen hinter den Zeilen der Datei.
        pasted_offset = len(imported) if imported is not None and not imported.empty else 0
        # Zuerst setzen: scheitert die markierte Zeichnung selbst, folgt keine
        # zweite (doppelte Widget-Schluessel wuerden den echten Fehler verdecken).
        gezeichnet = True
        _render_pasted_entries(
            pasted_slot,
            manual_items,
            order_pasted_entries(len(manual_items), pasted_offset, past_rows),
        )
    finally:
        if not gezeichnet:
            _render_pasted_entries(pasted_slot, manual_items)

    # ----------------------------- Filter --------------------------------- #
    with st.sidebar:
        st.divider()
        st.header("Filter")
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
        show_review = st.checkbox("Show review cases in the table", value=False)
        # Vorgabe aus, nicht im Arbeitsstand: jede Sitzung beginnt mit der Tageslage.
        show_past = st.toggle(
            "Show past launches",
            value=False,
            help=(
                "Launches whose last window ended more than 24 h ago and that are "
                "in the launch archive. Nothing is deleted."
            ),
        )
        if archiv_keys is None:
            st.text("Past launches are not hidden: {}".format(archiv_grund))
        # Der Zaehler folgt erst nach den anderen Filtern (siehe unten).
        hinweis_slot = st.empty()

        datums_zeilen = (
            table
            if show_past
            else table[~table["_row"].astype(int).isin(past_rows)]
        )
        valid_dates = [d for d in list(datums_zeilen["_from"].dropna()) if d is not None]
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
    # Maske fuer den Zaehler: ohne Datumsfilter, denn dessen Spanne haengt selbst
    # vom Vergangen-Filter ab.
    count_mask = mask.copy()
    if date_filter and isinstance(date_filter, (list, tuple)) and len(date_filter) == 2:
        start_day, end_day = date_filter
        day_series = table["_from"].apply(lambda d: d.date() if d is not None and pd.notna(d) else None)
        mask &= day_series.isna() | ((day_series >= start_day) & (day_series <= end_day))

    # Gezaehlt werden nur vergangene Starts, die sonst sichtbar waeren.
    if archiv_keys is not None and past_groups and not show_past:
        versteckt = count_hidden_past(
            stats.get("groups", []),
            past_rows,
            set(int(r) for r in table.loc[count_mask, "_row"]),
        )
        if versteckt:
            hinweis_slot.caption(
                "{} past launch(es) hidden \u2013 in the launch archive".format(versteckt)
            )
    if not show_past:
        mask &= ~table["_row"].astype(int).isin(past_rows)

    filtered = table[mask]
    ok_rows = filtered[filtered["Status"] == "OK"]
    review_rows = table[table["Status"] == "REVIEW"]
    display_rows = filtered if show_review else ok_rows
    event_by_row = {e.row_index: e for e in events}
    # Eine Traegersystem-Wahl gilt fuer alle Sperrzonen desselben Starts.
    group_keys: Dict[str, List[str]] = {}
    for gruppe in stats.get("groups", []):
        geschwister = [
            event_by_row[r].key for r in gruppe.row_indices if r in event_by_row
        ]
        for schluessel in geschwister:
            group_keys[schluessel] = geschwister
    review_events = [e for e in visible_events if e.status == "REVIEW"]
    confirmed_events = [e for e in visible_events if e.manual_override]

    # Starts, die nach der Filterung noch mindestens eine Sperrzone zeigen.
    visible_rows = set(int(r) for r in ok_rows["_row"]) if len(ok_rows) else set()
    visible_groups = [
        g
        for g in stats.get("groups", [])
        if g.spaceport_code and visible_rows & set(g.row_indices)
    ]
    group_table = groups_to_dataframe(visible_groups, vehicles, archiv_hinweis)

    # ------------------------------ Tabs ---------------------------------- #
    reiter = [
        "Launch Overview",
        "Flightpath Map",
        "NOTAM Data",
        "Export",
        "Review ({})".format(len(review_events)),
        "Excluded ({})".format(len(hidden_events)),
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
        # Kurze Beschriftungen: sechs Kacheln nebeneinander schneiden lange
        # Woerter ab - aus "Erkannte Nationen" wurde "Erkannte Na...".
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric(
            "Launches",
            len(visible_groups),
            help="Launches after merging the drop zones that belong to one flight.",
        )
        c2.metric(
            "Drop Zones",
            len(ok_rows),
            help="Individual NOTAMs - one launch can close several zones along its track.",
        )
        c3.metric(
            "Nations",
            ok_rows["Startnation"].nunique() if len(ok_rows) else 0,
        )
        c4.metric(
            "Pasted",
            int((ok_rows["Quelle"] == SOURCE_MANUAL).sum()) if len(ok_rows) else 0,
            help="NOTAMs added by copy & paste.",
        )
        c5.metric(
            "Verified",
            len(confirmed_events),
            help="Reviewed by hand and confirmed as a launch.",
        )
        c6.metric("Review", len(review_rows))
        lauf = (
            "Source: {} \u00b7 {} rows read \u00b7 {} without launch trigger \u00b7 "
            "{} duplicates removed \u00b7 minimum confidence: {} \u00b7 "
            "{} launch(es) merged from several drop zones".format(
                source_label,
                stats["rows"],
                stats["no_trigger"],
                stats.get("duplicates", 0),
                stats["min_confidence"],
                stats.get("grouped", 0),
            )
        )
        # Nur nennen, wenn es welche gibt - eine stehende Null macht die Zeile
        # nur laenger, ohne etwas zu sagen.
        if stats.get("advance", 0):
            lauf += " \u00b7 {} advance notice(s) assigned to a launch".format(
                stats["advance"]
            )
        st.caption(lauf)

        if visible_groups:
            st.markdown("#### Plain-language summary")
            st.caption(
                "Every recognised launch in one paragraph - with the reasoning behind it "
                "and how reliable the estimate is."
            )
            for group in visible_groups:
                titel = "{} \u00b7 {} \u00b7 {} \u00b7 {} \u00b7 {}".format(
                    mark_id_markdown(group.group_id, group.manual_override),
                    nation_label(group.nation) or "undetermined",
                    group.spaceport_code or "-",
                    group.launch_window,
                    group.orbit_type,
                )
                with st.expander(titel, expanded=len(visible_groups) <= 3):
                    st.markdown(describe_launch(group, events))
            st.divider()

        st.caption(
            "Select a row using the checkbox on the left to open that NOTAM "
            "under *NOTAM Data*."
        )
        view = st.radio(
            "View",
            ["Grouped by launch", "Individual NOTAMs"],
            horizontal=True,
            help=(
                "One launch closes several zones along its track. The launch view "
                "merges them into a single row, the NOTAM view lists every zone."
            ),
        )

        if view == "Grouped by launch":
            if group_table.empty:
                st.warning("No launches match the current filters.")
            else:
                auswahl = st.dataframe(
                    _style_manual(group_table),
                    use_container_width=True,
                    hide_index=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    column_config=table_config(group_table),
                    column_order=visible_order(group_table, GROUP_COLUMN_ORDER),
                    key="auswahl_starts",
                )
                gewaehlt = _auswahl_zeilen(auswahl)
                if gewaehlt:
                    gruppe = visible_groups[gewaehlt[0]]
                    _zur_notam_springen(gruppe.row_indices)
                    st.rerun()
        elif display_rows.empty:
            st.warning("No NOTAMs match the current filters.")
        else:
            sichtbar = display_rows.drop(columns=["_row", "_from", "_to"])
            auswahl = st.dataframe(
                _style_manual(sichtbar),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                column_config=table_config(sichtbar),
                column_order=visible_order(sichtbar, EVENT_COLUMN_ORDER),
                key="auswahl_notams",
            )
            gewaehlt = _auswahl_zeilen(auswahl)
            if gewaehlt:
                _zur_notam_springen([int(display_rows.iloc[gewaehlt[0]]["_row"])])
                st.rerun()

    if bereich == reiter[1]:
        if ok_rows.empty:
            st.info("No georeferenced events to draw on the map.")
        elif not FOLIUM_AVAILABLE:
            st.warning(
                "`folium` / `streamlit-folium` are not installed - "
                "falling back to the simple point map."
            )
            pts = fallback_points(events, set(int(r) for r in ok_rows["_row"]))
            if pts:
                st.map(pd.DataFrame(pts))
        else:
            options = ["All launches"] + [
                "{} · {} · {}".format(g.group_id, g.nation, ", ".join(g.notam_ids))
                for g in visible_groups
            ]
            choice = st.selectbox("Darstellung", options, index=0)
            if choice == "All launches":
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
                    help="Zones along the track: {}".format(", ".join(group.notam_ids)),
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
                with st.expander("What does this show?"):
                    st.markdown(describe_launch(group, events))
            st_folium(
                build_event_map(selection),
                use_container_width=True,
                height=620,
                returned_objects=[],
            )
            st.caption(
                "Dashed: great circle from the launch site along the computed "
                "launch azimuth. One track is drawn per launch - several closure "
                "zones of the same flight lie on it."
            )

    if bereich == reiter[2]:
        fokus = [z for z in st.session_state["focus_rows"] if z in set(display_rows["_row"])]
        if fokus:
            kennungen = ", ".join(
                event_by_row[z].notam_id for z in fokus if z in event_by_row
            )
            hinweis, zuruecksetzen = st.columns([4, 1])
            hinweis.info(
                "Opened from the Launch Overview: **{}**: "
                "the selection is listed first and expanded.".format(kennungen)
            )
            if zuruecksetzen.button("Clear selection", use_container_width=True):
                st.session_state["focus_rows"] = []
                st.rerun()

        if display_rows.empty:
            st.info("No NOTAMs to show.")
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
                    "  pasted" if event.source == SOURCE_MANUAL else "",
                    nation_label(event.nation) or "undetermined",
                    event.spaceport_code or "no launch site",
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
                            "FIR {} ({}) · matched via {}".format(
                                event.fir_code,
                                event.fir_name,
                                fir_method_label(event.fir_match_method),
                            )
                        )
                    st.divider()
                    _vehicle_picker(event, vehicles, group_keys, "data")
                    _launch_site_picker(
                        event, spaceports, pad_historie, group_keys, "data"
                    )
                    _payload_field(event, group_keys, "data")
                    st.divider()
                    zu_review, zu_versteckt = st.columns(2)
                    zu_review.button(
                        "Move to review",
                        key="reject_{}".format(event.key),
                        on_click=_reject_launch,
                        args=(event.key,),
                        use_container_width=True,
                        help="Take out of the launch table and move to Review "
                        "for checking.",
                    )
                    zu_versteckt.button(
                        "Exclude",
                        key="hide_data_{}".format(event.key),
                        on_click=_hide_event,
                        args=(event.key,),
                        use_container_width=True,
                        help="Take out of every analysis and file it under Excluded.",
                    )

    if bereich == reiter[3]:
        st.subheader("Export the day's result")
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
        col_a.download_button(
            "CSV \u00b7 Launches",
            data=group_table.to_csv(index=False).encode("utf-8-sig"),
            file_name="notam_starts_{}.csv".format(stamp),
            mime="text/csv",
            use_container_width=True,
            help="One row per launch, with all its NOTAM identifiers.",
        )
        col_b.download_button(
            "CSV \u00b7 NOTAMs",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="notam_launches_{}.csv".format(stamp),
            mime="text/csv",
            use_container_width=True,
            help="One row per NOTAM, with the launch identifier in the Launch column.",
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
                "advance_notices": stats.get("advance", 0),
            },
            "launches": [group_to_export_dict(g) for g in visible_groups],
            "events": [
                event_to_export_dict(e) for e in events if e.row_index in selected_rows
            ],
        }
        col_c.download_button(
            "JSON",
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
                "{} Verified by hand ({})".format(MANUAL_MARK, len(confirmed_events)),
                expanded=False,
            ):
                st.caption(
                    "These NOTAMs were checked here and taken into the launch table. "
                    "They carry the hexagon before their identifier there."
                )
                for event in confirmed_events:
                    st.markdown(
                        "{} · {} · {}".format(
                            mark_id_html(event.notam_id, True),
                            nation_label(event.nation) or "undetermined",
                            event.launch_group or "keine Bahnberechnung",
                        ),
                        unsafe_allow_html=True,
                    )
                    st.button(
                        "Undo verification",
                        key="revoke_{}".format(event.key),
                        on_click=_revoke_launch,
                        args=(event.key,),
                        use_container_width=True,
                    )
            st.divider()

        st.subheader("NOTAMs without a reliable assignment")
        if not review_events:
            st.success("Every triggered NOTAM could be assigned completely.")
        else:
            zurueck = sum(
                1 for e in review_events if e.key in st.session_state["rejected_launches"]
            )
            st.caption(
                "Check each NOTAM on its own: **Confirm launch** takes it into the "
                "launch table and marks it as verified by hand. **Exclude** moves it "
                "to the *Excluded* section."
                + (
                    "  \n{} of them were moved back here from the launch table.".format(
                        zurueck
                    )
                    if zurueck
                    else ""
                )
            )
            # Abgelaufene Review-Faelle bleiben sichtbar, tragen aber eine Marke.
            abgelaufen = {e.key for e in review_events if event_expired(e, jetzt)}
            abgelaufen_rows = {e.row_index for e in review_events if e.key in abgelaufen}
            review_table = events_to_dataframe(review_events, vehicles)
            review_table["Expired"] = [
                "yes" if int(r) in abgelaufen_rows else "-" for r in review_table["_row"]
            ]
            st.dataframe(
                review_table[
                    ["NOTAM ID", "Quelle", "FIR Code", "FIR liegt in", "Höhenprofil",
                     "Trägersystem", "Konfidenz", "Hinweis", "Expired"]
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.divider()

            for event in review_events:
                with st.expander(
                    ("expired · " if event.key in abgelaufen else "")
                    + "{} · {}".format(event.notam_id, event.review_reason[:90])
                ):
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
                    st.markdown("**Reason for review:** {}".format(event.review_reason))
                    _vehicle_picker(event, vehicles, group_keys, "review")
                    _launch_site_picker(
                        event, spaceports, pad_historie, group_keys, "review"
                    )
                    zurueckgestellt = event.key in st.session_state["rejected_launches"]
                    if zurueckgestellt:
                        st.button(
                            "Undo, assess automatically again",
                            key="unreject_{}".format(event.key),
                            on_click=_reset_decision,
                            args=(event.key,),
                            use_container_width=True,
                        )
                    act_a, act_b = st.columns(2)
                    act_a.button(
                        "Confirm launch",
                        key="confirm_{}".format(event.key),
                        on_click=_confirm_launch,
                        args=(event.key,),
                        type="primary",
                        use_container_width=True,
                        help="Take into the launch table as a checked space launch.",
                    )
                    act_b.button(
                        "Exclude",
                        key="hide_{}".format(event.key),
                        on_click=_hide_event,
                        args=(event.key,),
                        use_container_width=True,
                        help="Remove from review and file it under Excluded.",
                    )

    if bereich == reiter[5]:
        st.subheader("Excluded NOTAMs")
        if not hidden_events:
            st.info(
                "Nothing excluded yet. NOTAMs land here in two ways: automatically, "
                "when their confidence is low and the text carries an exclusion term "
                "or because you moved them here from *Review*."
            )
        else:
            automatisch = [e for e in hidden_events if e.key in auto_hidden_keys]
            von_hand = [e for e in hidden_events if e.key not in auto_hidden_keys]
            st.caption(
                "{} excluded automatically, {} by hand. They count in no analysis and "
                "appear in no export. Restoring one is permanent: it will not be "
                "excluded again on the next import.".format(
                    len(automatisch), len(von_hand)
                )
            )
            uebersicht = events_to_dataframe(hidden_events, vehicles)[
                ["NOTAM ID", "Quelle", "FIR Code", "FIR liegt in", "H\u00f6henprofil",
                 "Konfidenz", "Hinweis"]
            ].copy()
            uebersicht.insert(
                1,
                "Excluded by",
                ["rule" if e.key in auto_hidden_keys else "by hand" for e in hidden_events],
            )
            uebersicht["Hinweis"] = [
                e.auto_hidden_reason if e.key in auto_hidden_keys
                else (e.review_reason or e.assignment_note)
                for e in hidden_events
            ]
            st.dataframe(
                uebersicht,
                use_container_width=True,
                hide_index=True,
                column_config=dict(
                    table_config(uebersicht),
                    **{"Excluded by": st.column_config.Column("Excluded by")}
                ),
            )
            st.button(
                "Restore all",
                key="unhide_all",
                on_click=_unhide_all,
                use_container_width=True,
                help="Also lifts the automatic exclusions - permanently.",
            )
            st.divider()
            for event in hidden_events:
                per_regel = event.key in auto_hidden_keys
                grund = (
                    event.auto_hidden_reason
                    if per_regel
                    else (event.review_reason or "moved here by hand")
                )
                with st.expander(
                    "{} \u00b7 {} \u00b7 {}".format(
                        event.notam_id,
                        "excluded by rule" if per_regel else "excluded by hand",
                        grund[:80],
                    )
                ):
                    if per_regel:
                        st.caption(
                            "The rule caught this one: confidence {} (score {}) and "
                            "an exclusion term in the text. Restore it and it stays "
                            "restored; the next import will leave it alone.".format(
                                event.confidence_level, event.confidence_score
                            )
                        )
                    st.code(event.raw_text, language="text")
                    single_a, single_b = st.columns(2)
                    single_a.button(
                        "Restore",
                        key="unhide_{}".format(event.key),
                        on_click=_unhide_event,
                        args=(event.key,),
                        use_container_width=True,
                    )
                    single_b.button(
                        "Confirm launch after all",
                        key="hconfirm_{}".format(event.key),
                        on_click=_confirm_launch,
                        args=(event.key,),
                        use_container_width=True,
                    )


if __name__ == "__main__":
    main()
