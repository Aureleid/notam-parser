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
import re
import sqlite3
import urllib.parse
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
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
  id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            "ICAO Code": "NOT NULL CHECK (length(trim(\"ICAO Code\")) BETWEEN 3 AND 4)",
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


#: Tabellen, die app.read_archive_strict / load_sea_launches mit "" statt NaN lesen.
_LEER_ALS_TEXT = frozenset({"startarchiv", "seestarts"})


def lese_tabelle(conn: sqlite3.Connection, tabelle: str) -> pd.DataFrame:
    """
    Liest eine Fachtabelle wie _read_csv_any eine CSV: Text-Spalten, leer = NaN.
    Ausnahme wie bei den App-Lesern: Startarchiv und Seestarts haben leer = "".
    df.attrs["nola_stand"] ist die Pruefsumme des gelesenen Inhalts - wer die
    Tabelle spaeter ersetzt, gibt sie als `erwartet` mit.
    """
    try:
        zeilen = _zeilen(conn, tabelle)
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    spalten = list(FACHTABELLEN[tabelle])
    df = pd.DataFrame([list(z) for z in zeilen], columns=spalten, dtype=object)
    leer = "" if tabelle in _LEER_ALS_TEXT else np.nan
    for sp in spalten:
        df[sp] = df[sp].map(lambda v: leer if v is None or v == "" else str(v)).astype(object)
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
    try:
        with _transaktion(conn):
            if erwartet is not None and _stand(_zeilen(conn, tabelle)) != erwartet:
                raise Konflikt("changed", KONFLIKT_TEXT)
            neu = _ersetze_in_transaktion(conn, tabelle, df)
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    return neu


def _ersetze_in_transaktion(conn: sqlite3.Connection, tabelle: str, df: pd.DataFrame) -> str:
    """Leeren und neu fuellen ohne eigenes BEGIN; Rueckgabe: der neue Stand."""
    spalten = FACHTABELLEN[tabelle]
    werte = [tuple(_als_text(r.get(s)) for s in spalten) for r in df.to_dict("records")]
    einfuegen = "INSERT INTO {} ({}) VALUES ({})".format(
        _q(tabelle), ", ".join(_q(s) for s in spalten), ", ".join("?" for _ in spalten)
    )
    conn.execute("DELETE FROM {}".format(_q(tabelle)))
    conn.executemany(einfuegen, werte)
    return _stand(_zeilen(conn, tabelle))


def ersetze_tabellen(
    conn: sqlite3.Connection, tabellen: Dict[str, pd.DataFrame], meta: Dict[str, str]
) -> None:
    """
    Ersetzt mehrere Fachtabellen und setzt Meta-Werte in EINER Schreibtransaktion,
    ohne Vergleich mit dem Stand - nur fuer Uebernahmen aus Quelldateien
    (Cloud: Referenz-CSVs aus dem Repository). Scheitert eine, bleibt alles beim Alten.
    """
    for tabelle in tabellen:
        if tabelle not in FACHTABELLEN:
            raise ValueError("unknown table {}".format(tabelle))
    try:
        with _transaktion(conn):
            for tabelle, df in tabellen.items():
                _ersetze_in_transaktion(conn, tabelle, df)
            for schluessel, wert in meta.items():
                conn.execute(
                    "INSERT INTO meta (schluessel, wert) VALUES (?, ?) "
                    "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                    (schluessel, wert),
                )
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


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


ENTSCHEIDUNGS_SCHLUESSEL: Dict[str, str] = {
    "confirmed_launches": "bestaetigt",
    "hidden_events": "ausgeblendet",
    "rejected_launches": "abgelehnt",
    "restored_events": "wiederhergestellt",
    "archiv_removed": "archiv_entfernt",
    "seestarts_removed": "seestart_entfernt",
}
ZUWEISUNGS_SCHLUESSEL: Dict[str, str] = {
    "vehicle_assignments": "traegersystem",
    "payload_assignments": "payload",
    "launch_site_assignments": "startplatz",
}


def leerer_arbeitsstand() -> Dict[str, Any]:
    stand: Dict[str, Any] = {"manual_notams": []}
    for k in ENTSCHEIDUNGS_SCHLUESSEL:
        stand[k] = set()
    for k in ZUWEISUNGS_SCHLUESSEL:
        stand[k] = {}
    return stand


def lade_arbeitsstand(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Arbeitsstand in der Form des session_state (Mengen, Woerterbuecher, Liste)."""
    stand = leerer_arbeitsstand()
    nach_art = {art: k for k, art in ENTSCHEIDUNGS_SCHLUESSEL.items()}
    nach_feld = {feld: k for k, feld in ZUWEISUNGS_SCHLUESSEL.items()}
    try:
        for schluessel, art in conn.execute("SELECT schluessel, art FROM entscheidungen"):
            stand[nach_art[art]].add(schluessel)
        for schluessel, feld, wert in conn.execute(
            "SELECT schluessel, feld, wert FROM zuweisungen"
        ):
            stand[nach_feld[feld]][schluessel] = wert
        stand["manual_notams"] = [
            {"id": i, "text": t, "added": a or ""}
            for i, t, a in conn.execute("SELECT id, text, added FROM manuelle_notams ORDER BY id")
        ]
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    return stand


def _je_schluessel(stand: Dict[str, Any]) -> Dict[str, frozenset]:
    out: Dict[str, set] = defaultdict(set)
    for k, art in ENTSCHEIDUNGS_SCHLUESSEL.items():
        for schluessel in stand.get(k, ()) or ():
            out[str(schluessel)].add(art)
    return {s: frozenset(a) for s, a in out.items()}


def _zuweisungen(stand: Dict[str, Any]) -> Dict[Tuple[str, str], str]:
    out: Dict[Tuple[str, str], str] = {}
    for k, feld in ZUWEISUNGS_SCHLUESSEL.items():
        for schluessel, wert in (stand.get(k) or {}).items():
            if wert:
                out[(str(schluessel), feld)] = str(wert)
    return out


def _schreibe_unterschiede_in_transaktion(
    conn: sqlite3.Connection, vorher: Dict[str, Any], nachher: Dict[str, Any], jetzt_utc: str
) -> None:
    """Pruefen + Schreiben ohne eigenes BEGIN - laeuft in einer schon offenen Transaktion."""
    vor_e, nach_e = _je_schluessel(vorher), _je_schluessel(nachher)
    leer: frozenset = frozenset()
    e_geaendert = [s for s in set(vor_e) | set(nach_e) if vor_e.get(s, leer) != nach_e.get(s, leer)]
    vor_z, nach_z = _zuweisungen(vorher), _zuweisungen(nachher)
    z_geaendert = [k for k in set(vor_z) | set(nach_z) if vor_z.get(k) != nach_z.get(k)]
    vor_ids = {n["id"] for n in vorher.get("manual_notams", []) if n.get("id") is not None}
    nach_ids = {n["id"] for n in nachher.get("manual_notams", []) if n.get("id") is not None}
    entfernt = sorted(vor_ids - nach_ids)
    neue = [n for n in nachher.get("manual_notams", []) if n.get("id") is None]
    if not (e_geaendert or z_geaendert or entfernt or neue):
        return
    schreiben_e = []
    for s in e_geaendert:
        ist = frozenset(
            a for (a,) in conn.execute("SELECT art FROM entscheidungen WHERE schluessel = ?", (s,))
        )
        if ist == nach_e.get(s, leer):
            continue
        if ist != vor_e.get(s, leer):
            raise Konflikt("changed", KONFLIKT_TEXT)
        schreiben_e.append(s)
    schreiben_z = []
    for s, feld in z_geaendert:
        zeile = conn.execute(
            "SELECT wert FROM zuweisungen WHERE schluessel = ? AND feld = ?", (s, feld)
        ).fetchone()
        ist = None if zeile is None else zeile[0]
        if ist == nach_z.get((s, feld)):
            continue
        if ist != vor_z.get((s, feld)):
            raise Konflikt("changed", KONFLIKT_TEXT)
        schreiben_z.append((s, feld))
    for s in schreiben_e:
        conn.execute("DELETE FROM entscheidungen WHERE schluessel = ?", (s,))
        for art in sorted(nach_e.get(s, leer)):
            conn.execute(
                "INSERT INTO entscheidungen (schluessel, art, geaendert_utc) VALUES (?, ?, ?)",
                (s, art, jetzt_utc),
            )
    for s, feld in schreiben_z:
        conn.execute("DELETE FROM zuweisungen WHERE schluessel = ? AND feld = ?", (s, feld))
        if nach_z.get((s, feld)):
            conn.execute(
                "INSERT INTO zuweisungen (schluessel, feld, wert, geaendert_utc) "
                "VALUES (?, ?, ?, ?)",
                (s, feld, nach_z[(s, feld)], jetzt_utc),
            )
    conn.executemany("DELETE FROM manuelle_notams WHERE id = ?", [(i,) for i in entfernt])
    conn.executemany(
        "INSERT INTO manuelle_notams (text, added, geaendert_utc) VALUES (?, ?, ?)",
        [(n["text"], n.get("added", ""), jetzt_utc) for n in neue],
    )


def schreibe_unterschiede(
    conn: sqlite3.Connection, vorher: Dict[str, Any], nachher: Dict[str, Any], jetzt_utc: str
) -> None:
    """
    Schreibt nur, was sich zwischen Momentaufnahme `vorher` und `nachher`
    geaendert hat - in einer Schreibtransaktion. Fuer jeden beruehrten Schluessel
    muss die Datenbank noch den Stand von `vorher` haben (oder schon den von
    `nachher`); sonst Konflikt und nichts wird geschrieben.
    Ein leerer NOTAM-Text verletzt die Pruefregel der Tabelle und rollt die ganze
    Aktion mit DbFehler zurueck - der Aufrufer filtert leere Texte vorher.
    """
    try:
        with _transaktion(conn):
            _schreibe_unterschiede_in_transaktion(conn, vorher, nachher, jetzt_utc)
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def schreibe_arbeitsstand_neu(conn: sqlite3.Connection, stand: Dict[str, Any], jetzt_utc: str) -> None:
    """Nur fuer Umzug und Tests: leert den Arbeitsstand und schreibt `stand` - atomar."""
    leer = leerer_arbeitsstand()
    ohne_ids = dict(stand)
    ohne_ids["manual_notams"] = [
        {"text": n["text"], "added": n.get("added", "")} for n in stand.get("manual_notams", [])
    ]
    try:
        with _transaktion(conn):
            conn.execute("DELETE FROM entscheidungen")
            conn.execute("DELETE FROM zuweisungen")
            conn.execute("DELETE FROM manuelle_notams")
            _schreibe_unterschiede_in_transaktion(conn, leer, ohne_ids, jetzt_utc)
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def lade_korpus(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    try:
        zeilen = conn.execute(
            "SELECT notam_id, b, text, quellen_json FROM archiv_korpus ORDER BY schluessel"
        ).fetchall()
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    return [{"notam_id": n, "b": b, "text": t, "quellen": json.loads(q)} for n, b, t, q in zeilen]


def speichere_korpus(conn: sqlite3.Connection, eintraege: Sequence[Tuple[str, Dict[str, Any]]]) -> None:
    try:
        with _transaktion(conn):
            conn.execute("DELETE FROM archiv_korpus")
            conn.executemany(
                "INSERT INTO archiv_korpus (schluessel, notam_id, b, text, quellen_json) "
                "VALUES (?, ?, ?, ?, ?)",
                [(s, e["notam_id"], e["b"], e["text"], json.dumps(e["quellen"], ensure_ascii=False))
                 for s, e in eintraege],
            )
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def lade_importzustand(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Rohform wie archiv_import.json - die Strukturpruefung macht archiv_import."""
    try:
        tage = {
            iso: json.loads(inhalt)
            for iso, inhalt in conn.execute(
                "SELECT iso, inhalt_json FROM archiv_import_tage ORDER BY iso")
        }
        entscheidungen = {
            k: json.loads(w)
            for k, w in conn.execute(
                "SELECT schluessel, wert_json FROM archiv_import_entscheidungen ORDER BY schluessel")
        }
        review = {"bestaetigt": [], "ausgeblendet": []}
        for art, s in conn.execute(
            "SELECT art, schluessel FROM archiv_import_review ORDER BY art, pos"
        ):
            review[art].append(s)
        stand = lese_meta(conn, "erkennungsstand")
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    if not (tage or entscheidungen or review["bestaetigt"] or review["ausgeblendet"] or stand):
        return {}
    return {
        "version": 1, "tage": tage, "entscheidungen": entscheidungen,
        "review_bestaetigt": review["bestaetigt"], "review_ausgeblendet": review["ausgeblendet"],
        "erkennungsstand": stand or "",
    }


def speichere_importzustand(conn: sqlite3.Connection, state: Dict[str, Any]) -> None:
    try:
        with _transaktion(conn):
            for t in ("archiv_import_tage", "archiv_import_entscheidungen", "archiv_import_review"):
                conn.execute("DELETE FROM {}".format(_q(t)))
            conn.executemany(
                "INSERT INTO archiv_import_tage (iso, fingerprint, inhalt_json) VALUES (?, ?, ?)",
                [(iso, str(tag.get("fingerprint", "")), json.dumps(tag, ensure_ascii=False))
                 for iso, tag in state.get("tage", {}).items()],
            )
            conn.executemany(
                "INSERT INTO archiv_import_entscheidungen (schluessel, wert_json) VALUES (?, ?)",
                [(k, json.dumps(w, ensure_ascii=False)) for k, w in state.get("entscheidungen", {}).items()],
            )
            for art, liste in (("bestaetigt", state.get("review_bestaetigt", [])),
                               ("ausgeblendet", state.get("review_ausgeblendet", []))):
                conn.executemany(
                    "INSERT INTO archiv_import_review (art, pos, schluessel) VALUES (?, ?, ?)",
                    [(art, i, s) for i, s in enumerate(liste)],
                )
            conn.execute(
                "INSERT INTO meta (schluessel, wert) VALUES ('erkennungsstand', ?) "
                "ON CONFLICT(schluessel) DO UPDATE SET wert = excluded.wert",
                (str(state.get("erkennungsstand", "")),),
            )
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


_SICHERUNG = re.compile(r"^nola-(\d{4})-(\d{2})-(\d{2})-(\d{4})(-[a-z0-9-]+)?\.db$")


def liste_sicherungen(ordner: Path, nur_regulaer: bool = False) -> List[Path]:
    """Sicherungen nach dem Namensmuster, neueste zuerst."""
    schuetze_echte_orte(Path(ordner))
    if not Path(ordner).is_dir():
        return []
    treffer = []
    for p in Path(ordner).iterdir():
        m = _SICHERUNG.match(p.name)
        if m and (not nur_regulaer or m.group(5) is None):
            treffer.append(p)
    return sorted(treffer, key=lambda p: p.name, reverse=True)


def sicherung_faellig(ordner: Path, heute: date) -> bool:
    praefix = "nola-{}-".format(heute.strftime("%Y-%m-%d"))
    return not any(p.name.startswith(praefix) for p in liste_sicherungen(ordner, nur_regulaer=True))


def _entferne_tmp(tmp: Path) -> None:
    """Loescht die temporaere Sicherungsdatei samt SQLite-Nebendateien (-wal/-shm/-journal)."""
    for endung in ("", "-wal", "-shm", "-journal"):
        try:
            Path(str(tmp) + endung).unlink(missing_ok=True)
        except OSError:
            pass


def sichere(
    conn: sqlite3.Connection, ordner: Path, jetzt: datetime, behalten: int = 30, zusatz: str = ""
) -> Path:
    """
    Kopiert die Datenbank mit der SQLite-Sicherungsfunktion (stimmig auch
    waehrend eines Schreibvorgangs) erst in eine temporaere Datei, prueft sie
    und benennt sie dann um - iCloud sieht nie eine halbe Datei. Danach nur
    regulaere Sicherungen ueber `behalten` loeschen.
    """
    ordner = Path(ordner)
    schuetze_echte_orte(ordner)
    if not ordner.is_dir():
        raise DbFehler("backup folder missing", "Backup folder {} is missing.".format(ordner))
    name = "nola-{}{}.db".format(jetzt.strftime("%Y-%m-%d-%H%M"), "-" + zusatz if zusatz else "")
    ziel = ordner / name
    tmp = ordner / ".{}.tmp".format(name)
    try:
        kopie = sqlite3.connect(str(tmp))
        try:
            conn.backup(kopie)
            kopie.execute("PRAGMA journal_mode = DELETE")
            pruefung = kopie.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            kopie.close()
        # backup() uebernimmt den WAL-Modus der Quelle; beim Wechsel zu DELETE bleibt
        # die -shm-Datei der Kopie liegen. Nach dem Schliessen ist sie wertlos.
        for endung in ("-wal", "-shm", "-journal"):
            Path(str(tmp) + endung).unlink(missing_ok=True)
        if pruefung != "ok":
            raise DbFehler("backup corrupt", "Backup failed the integrity check: {}".format(pruefung))
        os.replace(tmp, ziel)
    except sqlite3.Error as exc:
        _entferne_tmp(tmp)
        raise _uebersetze(exc) from exc
    except OSError as exc:
        _entferne_tmp(tmp)
        raise DbFehler("backup failed", "Backup failed: {}".format(exc)) from exc
    except DbFehler:
        _entferne_tmp(tmp)
        raise
    if not zusatz:
        try:
            for alt in liste_sicherungen(ordner, nur_regulaer=True)[behalten:]:
                alt.unlink(missing_ok=True)
        except OSError as exc:
            raise DbFehler(
                "backup rotation failed",
                "Backup written to {}, but old backups could not be removed: {}".format(name, exc),
            ) from exc
    return ziel


#: macOS: Datei ist ein iCloud-Platzhalter ohne Inhalt ("Mac-Speicher optimieren").
SF_DATALESS = 0x40000000


def ist_ausgelagert(stat_ergebnis: Any) -> bool:
    return bool(getattr(stat_ergebnis, "st_flags", 0) & SF_DATALESS)


def pruefe_sicherung(pfad: Path) -> Tuple[str, Optional[Dict[str, int]]]:
    """
    ("ok", Zeilenzahlen) fuer eine heile Sicherung, ("corrupt", None) fuer eine
    defekte, ("in_cloud", None) fuer eine von iCloud ausgelagerte - die wird nicht
    geoeffnet, sonst sahe sie faelschlich defekt aus.
    """
    schuetze_echte_orte(Path(pfad).parent)
    try:
        if ist_ausgelagert(os.stat(pfad)):
            return "in_cloud", None
    except OSError:
        return "corrupt", None
    try:
        conn = sqlite3.connect(
            "file:{}?mode=ro".format(urllib.parse.quote(str(Path(pfad).resolve()))), uri=True
        )
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return "corrupt", None
            return "ok", {
                t: int(conn.execute("SELECT count(*) FROM {}".format(_q(t))).fetchone()[0])
                for t in list(FACHTABELLEN) + ["manuelle_notams", "entscheidungen", "zuweisungen"]
            }
        finally:
            conn.close()
    except sqlite3.Error:
        return "corrupt", None


def alte_nebendateien(pfad: Path) -> List[Path]:
    """
    -wal/-shm neben `pfad`. Fehlt die Datenbank selbst, stammen sie von einer
    frueheren Datei - die naechste Verbindung spielte deren Seiten still in eine
    neu angelegte nola.db ein. Darum legt dann niemand eine neue an.
    """
    return [n for n in (Path(str(pfad) + "-wal"), Path(str(pfad) + "-shm")) if n.exists()]


def nebendateien_text(pfad: Path) -> str:
    name = Path(pfad).name
    return (
        "{0}-wal / {0}-shm from an earlier database are still next to {0}. "
        "Move them away together with any old {0}, then try again.".format(name)
    )


def stelle_wieder_her(sicherung: Path, pfad: Path) -> None:
    """
    Kopiert eine Sicherung nach `pfad` - nur, wenn dort keine Datei liegt (os.link)
    und keine alten -wal/-shm daneben liegen (nichts wird verschoben oder geloescht).
    """
    pfad = Path(pfad)
    schuetze_echte_orte(pfad)
    if pfad.exists():
        raise DbFehler("exists", "{} exists - restore refused, nothing was overwritten.".format(pfad.name))
    if alte_nebendateien(pfad):
        raise DbFehler("stale side files", nebendateien_text(pfad))
    tmp = pfad.parent / "{}.{}.tmp".format(pfad.name, os.urandom(4).hex())
    try:
        quelle = sqlite3.connect(
            "file:{}?mode=ro".format(urllib.parse.quote(str(Path(sicherung).resolve()))), uri=True
        )
        try:
            ziel = sqlite3.connect(str(tmp))
            try:
                quelle.backup(ziel)
                if ziel.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DbFehler("backup corrupt", "The selected backup is corrupt.")
            finally:
                ziel.close()
        finally:
            quelle.close()
        try:
            os.link(tmp, pfad)
        except FileExistsError as exc:
            raise DbFehler("exists", "{} exists - restore refused.".format(pfad.name)) from exc
        except OSError as exc:
            raise DbFehler("restore failed", "Restore failed: {}".format(exc)) from exc
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    finally:
        tmp.unlink(missing_ok=True)
