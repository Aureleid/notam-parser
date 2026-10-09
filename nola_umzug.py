"""
Umzug der alten Dateien in die Datenbank, Start-Entscheidung und Export.

Die alten Dateien werden nur gelesen, nie veraendert. Lesen ist hier streng:
eine vorhandene, aber unlesbare Datei bricht den Umzug ab - ein Neuanfang ohne
Meldung waere genau der Weg, auf dem Daten verloren gehen.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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


def _csv_streng(pfad: Path, spalten, nachsatz: str = "No database was created.") -> pd.DataFrame:
    leer = pd.DataFrame(columns=list(spalten), dtype=object)
    if not pfad.exists():
        return leer
    try:
        df = app._read_csv_any(str(pfad))
    except Exception as exc:
        raise UmzugFehler("{} could not be read ({}). {}".format(pfad.name, exc, nachsatz)) from exc
    # Nur die Spalten pruefen - Werte bleiben unangetastet (kein _require_columns: das wandelt
    # Koordinaten in Zahlen und setzt Latitude/Longitude voraus).
    fehlend = [s for s in spalten if s not in df.columns]
    if fehlend:
        raise UmzugFehler("{} lacks columns {}. {}".format(pfad.name, ", ".join(fehlend), nachsatz))
    return df[list(spalten)].reset_index(drop=True)


#: Referenztabellen, deren Quell-CSVs im Repository liegen (Cloud liest sie bei Aenderung neu ein).
REFERENZ_TABELLEN = ("startplaetze", "firs", "traegersysteme")


def _referenz_shas(alt: Altdateien) -> Dict[str, str]:
    """SHA-256 der vorhandenen Referenz-CSVs; eine fehlende Datei hat keinen Eintrag."""
    shas: Dict[str, str] = {}
    for tabelle in REFERENZ_TABELLEN:
        pfad = Path(getattr(alt, tabelle))
        if pfad.exists():
            shas[tabelle] = hashlib.sha256(pfad.read_bytes()).hexdigest()
    return shas


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

    def falsch(was: str) -> UmzugFehler:
        return UmzugFehler("{} has an unexpected structure ({}). No database was created.".format(pfad.name, was))

    manuell = roh.get("manual_notams", [])
    if not isinstance(manuell, list):
        raise falsch("manual_notams is not a list")
    stand["manual_notams"] = [
        {"text": str(n.get("text", "")), "added": str(n.get("added", ""))}
        for n in manuell if isinstance(n, dict) and str(n.get("text", "")).strip()
    ]
    for k in db.ENTSCHEIDUNGS_SCHLUESSEL:
        werte = roh.get(k, [])
        if not isinstance(werte, list):
            raise falsch("{} is not a list".format(k))
        stand[k] = {str(x) for x in werte}
    stand["archiv_removed"] = app.migrate_archive_keys(stand["archiv_removed"])
    for k in db.ZUWEISUNGS_SCHLUESSEL:
        werte = roh.get(k, {})
        if not isinstance(werte, dict):
            raise falsch("{} is not an object".format(k))
        stand[k] = {str(a): str(b) for a, b in werte.items() if b}
    return stand


def umziehen(datenbank: Path, alt: Altdateien) -> Dict[str, int]:
    """
    Liest alle Altdateien und schreibt sie in eine temporaere Datenbank; erst
    wenn alles stimmt, wird sie per os.link zu `datenbank` - das schlaegt fehl,
    wenn dort schon eine Datei liegt (ein zweiter Prozess war schneller), und
    ueberschreibt so nie eine Datenbank. Liegen alte -wal/-shm neben einer
    fehlenden `datenbank`, wird nichts angelegt (sonst spielte SQLite deren Seiten ein).
    """
    datenbank = Path(datenbank)
    db.schuetze_echte_orte(datenbank)
    if not datenbank.exists() and db.alte_nebendateien(datenbank):
        raise UmzugFehler(db.nebendateien_text(datenbank) + " No database was created.")
    try:
        quellen_sha = _referenz_shas(alt)
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
    except OSError as exc:
        raise UmzugFehler("Old files could not be read ({}). No database was created.".format(exc)) from exc

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
            erwartet = {
                "entscheidungen": sum(len(stand[k]) for k in db.ENTSCHEIDUNGS_SCHLUESSEL),
                "zuweisungen": sum(len(stand[k]) for k in db.ZUWEISUNGS_SCHLUESSEL),
                "archiv_korpus": len(korpus),
                "archiv_import_tage": len(zustand.get("tage", {})),
                "archiv_import_entscheidungen": len(zustand.get("entscheidungen", {})),
                "archiv_import_review": len(zustand.get("review_bestaetigt", []))
                + len(zustand.get("review_ausgeblendet", [])),
            }
            db.speichere_korpus(conn, [
                (n.schluessel, {"notam_id": n.notam_id, "b": n.b, "text": n.text, "quellen": n.quellen})
                for n in korpus.values()])
            if zustand:
                db.speichere_importzustand(conn, zustand)
            for name, soll in erwartet.items():
                zaehlung[name] = db.zaehle(conn, name)
                if zaehlung[name] != soll:
                    raise UmzugFehler("{}: {} rows read, {} written. No database was created.".format(
                        name, soll, zaehlung[name]))
            db.setze_meta(conn, "umgezogen_utc", jetzt)
            db.setze_meta(conn, "umzug_quellen", json.dumps(
                {k: str(v) for k, v in alt.__dict__.items()}, ensure_ascii=False))
            db.setze_meta(conn, "referenz_quellen_sha", json.dumps(quellen_sha, sort_keys=True))
        finally:
            conn.close()
        try:
            os.link(tmp, datenbank)
        except FileExistsError:
            # ein anderer Prozess hat schon umgezogen - dessen Datei gilt, auch fuer die Zahlen
            zaehlung = _zaehle_alle(datenbank)
        except OSError as exc:
            raise UmzugFehler("Moving to the database failed ({}). No database was created.".format(exc)) from exc
    except db.DbFehler as exc:
        raise UmzugFehler("Moving to the database failed ({}). No database was created.".format(exc)) from exc
    finally:
        for rest in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm"), Path(str(tmp) + "-journal")):
            rest.unlink(missing_ok=True)
    return zaehlung


#: Gezaehlte Tabellen: die eine Liste aus nola_db, ohne die Verwaltungstabelle meta.
_ZAEHLTABELLEN = tuple(t for t in db.ALLE_TABELLEN if t != "meta")


def _zaehle_alle(datenbank: Path) -> Dict[str, int]:
    conn = db.verbinde(datenbank)
    try:
        return {t: db.zaehle(conn, t) for t in _ZAEHLTABELLEN}
    finally:
        conn.close()


def stelle_bereit(
    datenbank: Path, alt: Altdateien, sicherungsordner: Path, jetzt: datetime,
    referenzen_aus_dateien: bool = False,
) -> Startzustand:
    """
    Einmal je Serverprozess: pruefen, umziehen oder zur Wahl stellen.

    `referenzen_aus_dateien` (nur oeffentliche Fassung): weichen die Referenz-CSVs
    vom Stand beim letzten Einlesen ab (SHA-256 in meta), werden nur die drei
    Referenztabellen daraus ersetzt - Arbeitsstand, Archiv usw. bleiben.
    """
    datenbank = Path(datenbank)
    db.schuetze_echte_orte(datenbank, Path(sicherungsordner))
    if datenbank.exists():
        try:
            conn = db.verbinde(datenbank)
            try:
                db.setze_wal(conn)
                db.pruefe_schema(conn, lambda: _sichern_oder_none(
                    conn, sicherungsordner, jetzt, "vor-schema-{}".format(db.SCHEMA_VERSION)))
                if referenzen_aus_dateien:
                    _referenzen_auffrischen(conn, alt)
            finally:
                conn.close()
        except (db.DbFehler, UmzugFehler) as exc:
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


def _referenzen_auffrischen(conn, alt: Altdateien) -> None:
    """Geaenderte Referenz-CSVs in einer Transaktion uebernehmen; unveraendert -> kein Schreiben."""
    try:
        aktuell = _referenz_shas(alt)
    except OSError as exc:
        raise UmzugFehler("Reference files could not be read ({}). The database was not changed.".format(exc)) from exc
    roh = db.lese_meta(conn, "referenz_quellen_sha")
    try:
        bekannt: Optional[Dict[str, str]] = json.loads(roh) if roh else {}
    except ValueError:
        bekannt = {}
    if not isinstance(bekannt, dict):
        bekannt = {}
    geaendert = [t for t in REFERENZ_TABELLEN if t in aktuell and bekannt.get(t) != aktuell[t]]
    if not geaendert:
        return
    nachsatz = "The database was not changed."
    tabellen = {
        t: _csv_streng(Path(getattr(alt, t)), db.FACHTABELLEN[t], nachsatz) for t in geaendert
    }
    neu = dict(bekannt)
    neu.update(aktuell)
    db.ersetze_tabellen(conn, tabellen, {"referenz_quellen_sha": json.dumps(neu, sort_keys=True)})


def _sichern_oder_none(conn, ordner: Path, jetzt: datetime, zusatz: str):
    try:
        return db.sichere(conn, ordner, jetzt, zusatz=zusatz)
    except db.DbFehler:
        return None


def exportieren(datenbank: Path, ziel: Path) -> Path:
    """Schreibt alle Tabellen in die bisherigen Formate nach `ziel` (neuer Ordner)."""
    ziel = Path(ziel)
    if os.environ.get("NOLA_TEST"):
        proj = app.APP_DIR.resolve()
        z = ziel.resolve()
        if z == proj or proj in z.parents:
            raise RuntimeError("NOLA_TEST is set: tests must never export into the project folder")
    ziel.mkdir(parents=True, exist_ok=False)
    try:
        _schreibe_export(datenbank, ziel)
    except BaseException:
        shutil.rmtree(ziel, ignore_errors=True)
        raise
    return ziel


def _schreibe_export(datenbank: Path, ziel: Path) -> None:
    conn = db.verbinde(datenbank)
    try:
        # Eine Lesetransaktion: alle Tabellen stammen aus derselben Momentaufnahme,
        # auch wenn waehrenddessen jemand schreibt (WAL: der Schreiber wartet nicht).
        conn.execute("BEGIN")
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
        app._write_bytes_atomic(
            ziel / app.WORKSPACE_FILE.name,
            json.dumps(roh_ws, ensure_ascii=False, indent=2).encode("utf-8"))
        ai.write_json_atomic(ziel / ai.KORPUS_JSON.name, {"version": 1, "notams": db.lade_korpus(conn)})
        ai.write_json_atomic(ziel / ai.IMPORT_JSON.name, db.lade_importzustand(conn) or {
            "version": 1, "tage": {}, "entscheidungen": {}, "review_bestaetigt": [],
            "review_ausgeblendet": [], "erkennungsstand": ""})
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")  # nur gelesen - nichts festzuschreiben
        conn.close()
