"""
Umzug der alten Dateien in die Datenbank, Start-Entscheidung und Export.

Die alten Dateien werden nur gelesen, nie veraendert. Lesen ist hier streng:
eine vorhandene, aber unlesbare Datei bricht den Umzug ab - ein Neuanfang ohne
Meldung waere genau der Weg, auf dem Daten verloren gehen.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

import app
import archiv_import as ai
import nola_db as db


@dataclass
class Altdateien:
    startplaetze: Path
    firs: Path
    traegersysteme: Path
    startarchiv: Path
    seestarts: Path
    arbeitsstand: Path
    korpus: Path
    importzustand: Path


def altdateien_im(app_dir: Path) -> Altdateien:
    d = Path(app_dir)
    return Altdateien(
        startplaetze=d / app.SPACEPORT_CSV.name, firs=d / app.FIR_CSV.name,
        traegersysteme=d / app.VEHICLE_CSV.name, startarchiv=d / app.ARCHIVE_CSV.name,
        seestarts=d / app.SEA_LAUNCH_CSV.name, arbeitsstand=d / app.WORKSPACE_FILE.name,
        korpus=d / ai.KORPUS_JSON.name, importzustand=d / ai.IMPORT_JSON.name,
    )


class UmzugFehler(Exception):
    """Eine Altdatei ist unlesbar - es wurde keine Datenbank angelegt."""


@dataclass
class Startzustand:
    art: str
    grund: str = ""
    zaehlung: Dict[str, int] = field(default_factory=dict)


def _csv_streng(pfad: Path, spalten) -> pd.DataFrame:
    leer = pd.DataFrame(columns=list(spalten), dtype=object)
    if not pfad.exists():
        return leer
    try:
        df = app._read_csv_any(str(pfad))
    except Exception as exc:
        raise UmzugFehler("{} could not be read ({}). No database was created.".format(pfad.name, exc)) from exc
    # Nur die Spalten pruefen - Werte bleiben unangetastet (kein _require_columns: das wandelt
    # Koordinaten in Zahlen und setzt Latitude/Longitude voraus).
    fehlend = [s for s in spalten if s not in df.columns]
    if fehlend:
        raise UmzugFehler("{} lacks columns {}. No database was created.".format(pfad.name, ", ".join(fehlend)))
    return df[list(spalten)].reset_index(drop=True)


def _arbeitsstand_streng(pfad: Path) -> Dict[str, Any]:
    stand = db.leerer_arbeitsstand()
    if not pfad.exists():
        return stand
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
        if not isinstance(roh, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        raise UmzugFehler("{} could not be read ({}). No database was created.".format(pfad.name, exc)) from exc
    stand["manual_notams"] = [
        {"text": str(n.get("text", "")), "added": str(n.get("added", ""))}
        for n in roh.get("manual_notams", []) if isinstance(n, dict) and str(n.get("text", "")).strip()
    ]
    for k in db.ENTSCHEIDUNGS_SCHLUESSEL:
        stand[k] = {str(x) for x in roh.get(k, [])}
    stand["archiv_removed"] = app.migrate_archive_keys(stand["archiv_removed"])
    for k in db.ZUWEISUNGS_SCHLUESSEL:
        werte = roh.get(k, {})
        stand[k] = {str(a): str(b) for a, b in werte.items() if b} if isinstance(werte, dict) else {}
    return stand


def umziehen(datenbank: Path, alt: Altdateien) -> Dict[str, int]:
    """
    Liest alle Altdateien und schreibt sie in eine temporaere Datenbank; erst
    wenn alles stimmt, wird sie per os.link zu `datenbank` - das schlaegt fehl,
    wenn dort schon eine Datei liegt (ein zweiter Prozess war schneller), und
    ueberschreibt so nie eine Datenbank.
    """
    try:
        tabellen = {
            "startplaetze": _csv_streng(alt.startplaetze, db.FACHTABELLEN["startplaetze"]),
            "firs": _csv_streng(alt.firs, db.FACHTABELLEN["firs"]),
            "traegersysteme": _csv_streng(alt.traegersysteme, db.FACHTABELLEN["traegersysteme"]),
            "seestarts": _csv_streng(alt.seestarts, db.FACHTABELLEN["seestarts"]),
        }
        try:
            tabellen["startarchiv"] = app.read_archive_strict(alt.startarchiv)[
                list(db.FACHTABELLEN["startarchiv"])].reset_index(drop=True)
        except app.ArchiveUnreadable as exc:
            raise UmzugFehler(str(exc) + " No database was created.") from exc
        stand = _arbeitsstand_streng(alt.arbeitsstand)
        korpus = ai.load_korpus(alt.korpus)
        zustand = ai.read_json(alt.importzustand)
        if zustand:
            ai.zustand_aus_daten(zustand, alt.importzustand.name)
    except ai.ImportStateError as exc:
        raise UmzugFehler(str(exc) + " No database was created.") from exc

    tmp = datenbank.parent / "{}.{}.tmp".format(datenbank.name, os.urandom(4).hex())
    jetzt = datetime.now(timezone.utc).isoformat()
    zaehlung: Dict[str, int] = {}
    try:
        conn = db.verbinde(tmp, anlegen=True)
        try:
            db.lege_schema_an(conn)
            for name, df in tabellen.items():
                db.ersetze_tabelle(conn, name, df, None)
                zaehlung[name] = db.zaehle(conn, name)
                if zaehlung[name] != len(df):
                    raise UmzugFehler("{}: {} rows read, {} written. No database was created.".format(
                        name, len(df), zaehlung[name]))
            db.schreibe_arbeitsstand_neu(conn, stand, jetzt)
            zaehlung["manuelle_notams"] = db.zaehle(conn, "manuelle_notams")
            if zaehlung["manuelle_notams"] != len(stand["manual_notams"]):
                raise UmzugFehler("Pasted NOTAMs: count mismatch. No database was created.")
            db.speichere_korpus(conn, [
                (n.schluessel, {"notam_id": n.notam_id, "b": n.b, "text": n.text, "quellen": n.quellen})
                for n in korpus.values()])
            if zustand:
                db.speichere_importzustand(conn, zustand)
            db.setze_meta(conn, "umgezogen_utc", jetzt)
            db.setze_meta(conn, "umzug_quellen", json.dumps(
                {k: str(v) for k, v in alt.__dict__.items()}, ensure_ascii=False))
        finally:
            conn.close()
        try:
            os.link(tmp, datenbank)
        except FileExistsError:
            pass  # ein anderer Prozess hat schon umgezogen - dessen Datei gilt
    except db.DbFehler as exc:
        raise UmzugFehler("Moving to the database failed ({}). No database was created.".format(exc)) from exc
    finally:
        for rest in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm"), Path(str(tmp) + "-journal")):
            rest.unlink(missing_ok=True)
    return zaehlung


def stelle_bereit(datenbank: Path, alt: Altdateien, sicherungsordner: Path, jetzt: datetime) -> Startzustand:
    """Einmal je Serverprozess: pruefen, umziehen oder zur Wahl stellen."""
    if datenbank.exists():
        try:
            conn = db.verbinde(datenbank)
            try:
                db.setze_wal(conn)
                db.pruefe_schema(conn, lambda: _sichern_oder_none(
                    conn, sicherungsordner, jetzt, "vor-schema-{}".format(db.SCHEMA_VERSION)))
            finally:
                conn.close()
        except db.DbFehler as exc:
            return Startzustand("fehlgeschlagen", grund=str(exc))
        return Startzustand("bereit")
    if db.liste_sicherungen(sicherungsordner):
        return Startzustand("fehlt_mit_sicherungen")
    try:
        zaehlung = umziehen(datenbank, alt)
        conn = db.verbinde(datenbank)
        try:
            db.setze_wal(conn)
        finally:
            conn.close()
    except (UmzugFehler, db.DbFehler) as exc:
        return Startzustand("fehlgeschlagen", grund=str(exc))
    return Startzustand("umgezogen", zaehlung=zaehlung)


def _sichern_oder_none(conn, ordner: Path, jetzt: datetime, zusatz: str):
    try:
        return db.sichere(conn, ordner, jetzt, zusatz=zusatz)
    except db.DbFehler:
        return None


def exportieren(datenbank: Path, ziel: Path) -> Path:
    """Schreibt alle Tabellen in die bisherigen Formate nach `ziel` (neuer Ordner)."""
    ziel = Path(ziel)
    if os.environ.get("NOLA_TEST") and (app.APP_DIR / "export").resolve() in ziel.resolve().parents:
        raise RuntimeError("NOLA_TEST is set: tests must never export into the project folder")
    ziel.mkdir(parents=True, exist_ok=False)
    conn = db.verbinde(datenbank)
    try:
        for name, pfad, spalten in [
            ("startplaetze", app.SPACEPORT_CSV, app.SPACEPORT_EXPORT_COLUMNS),
            ("firs", app.FIR_CSV, app.FIR_EXPORT_COLUMNS),
            ("traegersysteme", app.VEHICLE_CSV, app.VEHICLE_EXPORT_COLUMNS),
        ]:
            app.persist_reference(ziel / pfad.name, db.lese_tabelle(conn, name), spalten)
        app._write_bytes_atomic(
            ziel / app.ARCHIVE_CSV.name,
            db.lese_tabelle(conn, "startarchiv")[list(app.ARCHIVE_COLUMNS)].to_csv(index=False).encode("utf-8-sig"),
        )
        app._write_bytes_atomic(
            ziel / app.SEA_LAUNCH_CSV.name,
            db.lese_tabelle(conn, "seestarts")[list(app.SEA_LAUNCH_COLUMNS)].to_csv(index=False).encode("utf-8-sig"),
        )
        stand = db.lade_arbeitsstand(conn)
        roh_ws = {
            "gespeichert_utc": datetime.now(timezone.utc).isoformat(),
            "manual_notams": [{"text": n["text"], "added": n["added"]} for n in stand["manual_notams"]],
        }
        for k in db.ENTSCHEIDUNGS_SCHLUESSEL:
            roh_ws[k] = sorted(stand[k])
        for k in db.ZUWEISUNGS_SCHLUESSEL:
            roh_ws[k] = dict(sorted(stand[k].items()))
        (ziel / app.WORKSPACE_FILE.name).write_text(
            json.dumps(roh_ws, ensure_ascii=False, indent=2), encoding="utf-8")
        ai.write_json_atomic(ziel / ai.KORPUS_JSON.name, {"version": 1, "notams": db.lade_korpus(conn)})
        ai.write_json_atomic(ziel / ai.IMPORT_JSON.name, db.lade_importzustand(conn) or {
            "version": 1, "tage": {}, "entscheidungen": {}, "review_bestaetigt": [],
            "review_ausgeblendet": [], "erkennungsstand": ""})
    finally:
        conn.close()
    return ziel
