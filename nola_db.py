"""
Speicherschicht von NOLA: eine SQLite-Datei, nur dieses Modul spricht SQL.

Grundsaetze (Spec .internal/specs/2026-10-08-lokale-datenbank-design.md):
- Jede Verbindung oeffnet mit mode=rw - eine fehlende Datei ist ein Fehler,
  nie eine neue leere Datenbank. Nur der Umzug legt an (anlegen=True).
- Fachspalten sind TEXT, wie _read_csv_any sie liefert (dtype=str).
- Ganze Tabellen werden nur mit Vergleich gegen den gelesenen Stand ersetzt.
- Tabellen- und Spaltennamen kommen nur aus den Konstanten dieses Moduls.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

SCHEMA_VERSION = 1
PROJEKT_DB = Path(__file__).resolve().parent / "nola.db"
#: Einzige Definition des Sicherungsordners (iCloud Drive) - app.BACKUP_DIR verweist darauf.
ECHTER_SICHERUNGSORDNER = (
    Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Claude/Claude Code/NOTAM Parser Backups"
)
KONFLIKT_TEXT = (
    "Changed by someone else meanwhile – the view has been reloaded, please check again."
)
GESPERRT_TEXT = "Database is locked – write or revert the changes in DB Browser."

#: Fachtabellen und ihre Spalten - identisch mit den CSV-Spalten in app.py.
FACHTABELLEN: Dict[str, Tuple[str, ...]] = {
    "startplaetze": ("Kurzel", "Latitude", "Longitude", "Name", "Land"),
    "firs": (
        "ICAO Code", "Latitude", "Longitude", "Betroffene Region / FIR Name",
        "Land", "Zugehörige Startnation",
    ),
    "traegersysteme": ("Land", "Name", "Alternativname englisch", "Abkürzung"),
    "startarchiv": (
        "NOTAM", "Startdatum", "Startzeit", "Nation", "Weltraumbahnhof", "Trägersystem",
        "Payload", "Orbit", "Inklination", "Azimuth", "Dropzones",
    ),
    "seestarts": (
        "Datum", "Zeit", "Nation", "Breite", "Länge", "Radius (km)", "Azimut",
        "Inklination", "Orbit", "Dropzones", "NOTAM", "Nächster bekannter Platz",
    ),
}


class DbFehler(Exception):
    """Lese- oder Schreibfehler. `ursache` ist eine kurze Kennung fuer die Meldung."""

    def __init__(self, ursache: str, text: str) -> None:
        super().__init__(text)
        self.ursache = ursache


class Gesperrt(DbFehler):
    """Ein anderes Programm haelt eine Schreibtransaktion offen."""


class Konflikt(DbFehler):
    """Der Stand hat sich seit dem Lesen geaendert - nichts wurde geschrieben."""


class DateiFehlt(DbFehler):
    """nola.db fehlt - es wird keine leere Datei angelegt."""


class SchemaZuNeu(DbFehler):
    """Die Datei stammt von einer neueren NOLA-Fassung."""


def _uebersetze(exc: sqlite3.Error) -> DbFehler:
    text = str(exc)
    klein = text.lower()
    if "locked" in klein or "busy" in klein:
        return Gesperrt("locked", GESPERRT_TEXT)
    if "full" in klein:
        return DbFehler("disk full", "Not saved: the disk is full ({}).".format(text))
    if "constraint" in klein:
        return DbFehler("constraint failed", "Not saved: constraint failed: {}".format(text))
    if "malformed" in klein or "not a database" in klein:
        return DbFehler("database corrupt", "The database file is corrupt ({}).".format(text))
    if "readonly" in klein or "read-only" in klein:
        return DbFehler("read-only", "Not saved: the database is read-only ({}).".format(text))
    return DbFehler("error", "Database error: {}".format(text))


def _q(name: str) -> str:
    """Bezeichner in Anfuehrungszeichen - nur fuer Namen aus den Konstanten."""
    return '"{}"'.format(name.replace('"', '""'))


def _zahl(spalte: str, lo: float, hi: float) -> str:
    s = _q(spalte)
    return (
        "CHECK ({s} IS NOT NULL AND {s} GLOB '*[0-9]*' "
        "AND trim({s}) NOT GLOB '*[^0-9.+eE-]*' "
        "AND CAST({s} AS REAL) BETWEEN {lo} AND {hi})".format(s=s, lo=lo, hi=hi)
    )


def _voll(spalte: str) -> str:
    s = _q(spalte)
    return "NOT NULL CHECK (trim({}) <> '')".format(s)


def _schema_sql() -> str:
    def spalten(tabelle: str, extra: Dict[str, str]) -> str:
        return ",\n  ".join(
            "{} TEXT {}".format(_q(sp), extra.get(sp, "")).rstrip()
            for sp in FACHTABELLEN[tabelle]
        )

    return """
CREATE TABLE meta (schluessel TEXT PRIMARY KEY, wert TEXT);
CREATE TABLE startplaetze (
  {sp},
  PRIMARY KEY ("Kurzel")
);
CREATE TABLE firs (
  {fir},
  PRIMARY KEY ("ICAO Code")
);
CREATE TABLE traegersysteme (
  {tr},
  PRIMARY KEY ("Abkürzung")
);
CREATE TABLE startarchiv (
  id INTEGER PRIMARY KEY,
  {ar}
);
CREATE TABLE seestarts (
  id INTEGER PRIMARY KEY,
  {se}
);
CREATE TABLE manuelle_notams (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL CHECK (trim(text) <> ''),
  added TEXT,
  geaendert_utc TEXT NOT NULL
);
CREATE TABLE entscheidungen (
  schluessel TEXT NOT NULL,
  art TEXT NOT NULL CHECK (art IN ('bestaetigt', 'ausgeblendet', 'abgelehnt',
    'wiederhergestellt', 'archiv_entfernt', 'seestart_entfernt')),
  geaendert_utc TEXT NOT NULL,
  UNIQUE (schluessel, art)
);
CREATE TABLE zuweisungen (
  schluessel TEXT NOT NULL,
  feld TEXT NOT NULL CHECK (feld IN ('traegersystem', 'payload', 'startplatz')),
  wert TEXT NOT NULL CHECK (trim(wert) <> ''),
  geaendert_utc TEXT NOT NULL,
  PRIMARY KEY (schluessel, feld)
);
CREATE TABLE archiv_korpus (
  schluessel TEXT PRIMARY KEY,
  notam_id TEXT NOT NULL, b TEXT NOT NULL, text TEXT NOT NULL, quellen_json TEXT NOT NULL
);
CREATE TABLE archiv_import_tage (
  iso TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, inhalt_json TEXT NOT NULL
);
CREATE TABLE archiv_import_entscheidungen (
  schluessel TEXT PRIMARY KEY, wert_json TEXT NOT NULL
);
CREATE TABLE archiv_import_review (
  art TEXT NOT NULL CHECK (art IN ('bestaetigt', 'ausgeblendet')),
  pos INTEGER NOT NULL, schluessel TEXT NOT NULL,
  PRIMARY KEY (art, pos)
);
""".format(
        sp=spalten("startplaetze", {
            "Kurzel": _voll("Kurzel"), "Latitude": _zahl("Latitude", -90, 90),
            "Longitude": _zahl("Longitude", -180, 180),
        }),
        fir=spalten("firs", {
            "ICAO Code": "NOT NULL CHECK (length(trim(\"ICAO Code\")) = 4)",
            "Latitude": _zahl("Latitude", -90, 90), "Longitude": _zahl("Longitude", -180, 180),
        }),
        tr=spalten("traegersysteme", {"Abkürzung": _voll("Abkürzung"), "Name": _voll("Name")}),
        ar=spalten("startarchiv", {
            "NOTAM": _voll("NOTAM"), "Startdatum": _voll("Startdatum"), "Nation": _voll("Nation"),
        }),
        se=spalten("seestarts", {"Datum": _voll("Datum"), "Nation": _voll("Nation")}),
    )


def schuetze_echte_orte(*pfade: Path) -> None:
    """Unter NOLA_TEST: nie die Projektdatenbank oder den echten Sicherungsordner beruehren."""
    if not os.environ.get("NOLA_TEST"):
        return
    gesperrt = {PROJEKT_DB, ECHTER_SICHERUNGSORDNER.resolve()}
    for p in pfade:
        if Path(p).resolve() in gesperrt:
            raise RuntimeError("NOLA_TEST is set: tests must never touch {}".format(p))


def verbinde(pfad: Path, anlegen: bool = False) -> sqlite3.Connection:
    """
    Oeffnet die Datenbank. Ohne `anlegen` mit mode=rw: eine fehlende Datei
    bricht mit DateiFehlt ab, statt still eine leere Datenbank anzulegen.
    isolation_level=None: Transaktionen steuert dieses Modul selbst (BEGIN).
    """
    pfad = Path(pfad)
    schuetze_echte_orte(pfad)
    if not anlegen and not pfad.exists():
        raise DateiFehlt("missing", "The database {} is missing.".format(pfad.name))
    uri = "file:{}?mode={}".format(
        urllib.parse.quote(str(pfad.resolve())), "rwc" if anlegen else "rw"
    )
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5.0)
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as exc:
        if not pfad.exists():
            raise DateiFehlt("missing", "The database {} is missing.".format(pfad.name)) from exc
        raise _uebersetze(exc) from exc
    return conn


@contextmanager
def _transaktion(conn: sqlite3.Connection):
    """
    BEGIN IMMEDIATE ... COMMIT. Bei einem Fehler wird nur zurueckgerollt, wenn
    SQLite das nicht schon selbst getan hat - so bleibt der Originalfehler
    (z. B. Platte voll) die gemeldete Ursache.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise


def lege_schema_an(conn: sqlite3.Connection) -> None:
    """
    Legt alle Tabellen an und traegt die Schema-Version ein (nur auf leerer Datei).
    Die Version steht in derselben Transaktion wie die Tabellen.
    """
    version = int(SCHEMA_VERSION)  # Modulkonstante, keine Eingabe
    skript = (
        "BEGIN;\n" + _schema_sql()
        + "\nINSERT INTO meta (schluessel, wert) VALUES ('schema_version', '{}');".format(version)
        + "\nCOMMIT;"
    )
    try:
        conn.executescript(skript)
    except sqlite3.Error as exc:
        if conn.in_transaction:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise _uebersetze(exc) from exc


def setze_wal(conn: sqlite3.Connection) -> None:
    """WAL einmal in der Datei setzen - Lesen und Schreiben behindern sich nicht."""
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def lese_meta(conn: sqlite3.Connection, schluessel: str) -> Optional[str]:
    try:
        zeile = conn.execute(
            "SELECT wert FROM meta WHERE schluessel = ?", (schluessel,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    return None if zeile is None else zeile[0]


def setze_meta(conn: sqlite3.Connection, schluessel: str, wert: str) -> None:
    try:
        conn.execute(
            "INSERT INTO meta (schluessel, wert) VALUES (?, ?) "
            "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
            (schluessel, wert),
        )
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def schema_version(conn: sqlite3.Connection) -> int:
    wert = lese_meta(conn, "schema_version")
    try:
        return int(wert) if wert is not None else 0
    except ValueError as exc:
        raise DbFehler("database corrupt", "schema_version is not a number") from exc


#: Umbauschritte: SCHRITTE[n] hebt Version n auf n + 1. Noch keine.
SCHRITTE: Dict[int, str] = {}


def pruefe_schema(conn: sqlite3.Connection, sichern: Callable[[], Optional[Path]]) -> None:
    """
    Hebt eine aeltere Datei auf SCHEMA_VERSION. Vorher wird gesichert; liefert
    `sichern` keinen Pfad, wird nicht umgebaut. Eine neuere Datei bleibt unberuehrt.
    """
    version = schema_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaZuNeu(
            "schema too new",
            "nola.db was written by a newer NOLA (schema {} > {}). Nothing was changed.".format(
                version, SCHEMA_VERSION),
        )
    if version == SCHEMA_VERSION:
        return
    fehlend = [n for n in range(version, SCHEMA_VERSION) if n not in SCHRITTE]
    if fehlend:
        raise DbFehler(
            "schema step missing",
            "No upgrade step from schema {} - the database was not changed.".format(fehlend[0]),
        )
    if sichern() is None:
        raise DbFehler(
            "backup failed",
            "Backup before the schema upgrade failed - the database was not changed.",
        )
    try:
        with _transaktion(conn):
            for n in range(version, SCHEMA_VERSION):
                conn.execute(SCHRITTE[n])  # einzelne Anweisungen; executescript beendete die Transaktion
            conn.execute(
                "UPDATE meta SET wert = ? WHERE schluessel = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def _zeilen(conn: sqlite3.Connection, tabelle: str) -> List[Tuple[Any, ...]]:
    spalten = ", ".join(_q(s) for s in FACHTABELLEN[tabelle])
    return conn.execute(
        "SELECT {} FROM {} ORDER BY rowid".format(spalten, _q(tabelle))
    ).fetchall()


def _stand(zeilen: Sequence[Tuple[Any, ...]]) -> str:
    roh = json.dumps([list(z) for z in zeilen], ensure_ascii=False, default=str)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


def _als_text(wert: Any) -> Optional[str]:
    """Wie to_csv: NaN/None/'' werden NULL, alles andere Text."""
    if wert is None:
        return None
    if isinstance(wert, float) and math.isnan(wert):
        return None
    try:
        if pd.isna(wert):
            return None
    except (TypeError, ValueError):
        pass
    text = str(wert)
    return text if text != "" else None


def lese_tabelle(conn: sqlite3.Connection, tabelle: str) -> pd.DataFrame:
    """
    Liest eine Fachtabelle wie _read_csv_any eine CSV: Text-Spalten, leer = NaN.
    df.attrs["nola_stand"] ist die Pruefsumme des gelesenen Inhalts - wer die
    Tabelle spaeter ersetzt, gibt sie als `erwartet` mit.
    """
    try:
        zeilen = _zeilen(conn, tabelle)
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    spalten = list(FACHTABELLEN[tabelle])
    df = pd.DataFrame([list(z) for z in zeilen], columns=spalten, dtype=object)
    for sp in spalten:
        df[sp] = df[sp].map(lambda v: np.nan if v is None or v == "" else str(v)).astype(object)
    df.attrs["nola_stand"] = _stand(zeilen)
    return df


def ersetze_tabelle(
    conn: sqlite3.Connection, tabelle: str, df: pd.DataFrame, erwartet: Optional[str]
) -> str:
    """
    Ersetzt den Inhalt in einer Schreibtransaktion - nur, wenn der Stand noch
    `erwartet` ist. `erwartet=None` nur fuer Umzug und Wiederherstellen.
    Rueckgabe: der neue Stand.
    """
    spalten = FACHTABELLEN[tabelle]
    werte = [tuple(_als_text(r.get(s)) for s in spalten) for r in df.to_dict("records")]
    einfuegen = "INSERT INTO {} ({}) VALUES ({})".format(
        _q(tabelle), ", ".join(_q(s) for s in spalten), ", ".join("?" for _ in spalten)
    )
    try:
        with _transaktion(conn):
            if erwartet is not None and _stand(_zeilen(conn, tabelle)) != erwartet:
                raise Konflikt("changed", KONFLIKT_TEXT)
            conn.execute("DELETE FROM {}".format(_q(tabelle)))
            conn.executemany(einfuegen, werte)
            neu = _stand(_zeilen(conn, tabelle))
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    return neu


def zaehle(conn: sqlite3.Connection, tabelle: str) -> int:
    erlaubt = set(FACHTABELLEN) | {
        "manuelle_notams", "entscheidungen", "zuweisungen", "archiv_korpus",
        "archiv_import_tage", "archiv_import_entscheidungen", "archiv_import_review",
    }
    if tabelle not in erlaubt:
        raise ValueError("unknown table {}".format(tabelle))
    try:
        return int(conn.execute("SELECT count(*) FROM {}".format(_q(tabelle))).fetchone()[0])
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
