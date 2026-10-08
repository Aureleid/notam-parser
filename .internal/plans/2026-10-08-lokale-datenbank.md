# Lokale Datenbank (SQLite) — Umsetzungsplan

> **Für ausführende Agenten:** PFLICHT-SKILL: `beads-superpowers:subagent-driven-development`
> (empfohlen) oder `beads-superpowers:executing-plans`. Jede Aufgabe wird ein Bead
> (`bd create -t task --parent <epic-id>`). Schritte mit Checkboxen (`- [ ]`).

**Ziel:** Alle eingepflegten Daten von NOLA (Referenzen, Startarchiv, Seestarts, Arbeitsstand,
Archiv-Import-Zustand) liegen dauerhaft in einer lokalen SQLite-Datei `nola.db`, die auch im
DB Browser bearbeitet werden kann; mehrere Tabs/Personen am eigenen Rechner überschreiben sich nie
still; es gibt Sicherungen, Wiederherstellung und einen Export in die alten Formate.

**Architektur:** `nola_db.py` ist die reine Speicherschicht (nur SQLite + pandas, importiert
`app` nicht). `nola_umzug.py` kennt die alten Dateien (Umzug, Export, Start-Entscheidung) und
importiert `app` und `archiv_import`. `app.py` bekommt dünne Wrapper (`referenz_lesen`,
`archiv_lesen`, `archiv_schreiben`, …) und füllt `session_state` je Durchlauf aus der Datenbank;
`_persist_workspace` schreibt nur Unterschiede mit Konfliktprüfung. Die bisherigen Datei-Leser und
-Schreiber bleiben unverändert erhalten — sie dienen Umzug, Export und den bestehenden Tests.

**Technik:** Python 3, `sqlite3` (Standardbibliothek, SQLite 3.54), pandas ≥ 2.0, Streamlit 1.50.

**Spec:** `.internal/specs/2026-10-08-lokale-datenbank-design.md` (inkl. „Stress Test Results“
und Korrekturen beim Planschreiben). Beads: `nola-xed` (Brainstorming), `nola-b3e` (Stresstest).

## Globale Vorgaben

- **Start erst nach dem Zweig `vergangene-starts`.** Neuer Zweig `lokale-datenbank` von `main`,
  nachdem `vergangene-starts` gemergt ist. Funktionen immer über den Namen suchen
  (`grep -n "^def name" app.py`), nie über Zeilennummern — `app.py` ändert sich parallel.
- **NOLA bis Aufgabe 8 nicht im Projektordner starten.** Sonst entstünde eine `nola.db`, während
  Arbeitsstand/Archiv noch in die alten Dateien geschrieben werden — Änderungen dazwischen gingen
  für die App verloren. Tagesbetrieb in dieser Zeit aus einem zweiten Ordner mit `main`
  (`git worktree add ../NOTAM-Parser-main main`, Datendateien dorthin kopieren). Zusätzlich sperrt
  Aufgabe 8 den automatischen Umzug ohne `NOLA_DB=1`; Aufgabe 9 hebt die Sperre wieder auf.
- **Commits:** CLAUDE.md erlaubt Commits nur auf Aufforderung. Vor Aufgabe 1 den Benutzer fragen,
  ob je Aufgabe auf `lokale-datenbank` committet werden darf. Ohne Erlaubnis entfällt jeder
  Commit-Schritt; das wird im Abschlussbericht der Aufgabe genannt. Commit-Zeile am Ende:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; Bead-ID in der Nachricht.
- **Tests:** zwei Skripte im vorhandenen Stil (`check(label, cond, extra)`, Abschluss
  `ERGEBNIS: …`, Exit-Code): `.venv/bin/python test_app.py` und `.venv/bin/python test_nola_db.py`.
  Kein pytest. Temp-Ordner über `tempfile.mkdtemp()`.
- **Schutz der echten Orte:** Beide Testskripte setzen in ihren ersten Zeilen
  `os.environ["NOLA_TEST"] = "1"` — **vor** `import app`. Unter `NOLA_TEST` werfen
  `nola_db.verbinde` und `stelle_wieder_her` (Ziel = Projektdatei `nola.db`), `sichere`,
  `liste_sicherungen`, `pruefe_sicherung` (Ordner = `nola_db.ECHTER_SICHERUNGSORDNER`) und
  `nola_umzug.exportieren` (Ziel unter `APP_DIR/export`) einen `RuntimeError` — sonst könnte die
  Rotation echte Sicherungen löschen.
- **Nichts abschwächen:** Vor Aufgabe 1 die PASS-Zahl festhalten:
  `.venv/bin/python test_app.py | grep -c "^  PASS"` → in den Bead der Aufgabe 1 schreiben
  (`bd note`). Nach jeder Aufgabe: Zahl ≥ Ausgangswert, `ERGEBNIS: ALLE TESTS BESTANDEN`.
  Umgeschriebene Prüfungen behalten ihre fachliche Aussage; keine wird gelöscht oder auf `SKIP`
  gesetzt.
- **Keine echten Datendateien in Tests schreiben** (weder `nola.db` noch CSV/JSON im Projekt). Deshalb
  kommt der Arbeitsstand (Aufgabe 6) vor dem Archiv (Aufgabe 7): erst danach schreibt
  `_persist_workspace` nicht mehr in `notam_workspace.json`.
- UI-Texte englisch, Code-Kommentare und Docstrings deutsch ohne Umlaute im Code (wie bisher);
  Umlaute nur in Spaltennamen-Strings, wie heute (`"Trägersystem"` oder direkt `Trägersystem`,
  so wie die bestehende Konstante es schreibt).
- SQL nur mit `?`-Platzhaltern. Tabellen- und Spaltennamen nur aus den festen Konstanten in
  `nola_db.py`.
- Die Datenbank liegt in `APP_DIR / "nola.db"` (`app.DB_PATH`); Sicherungen in
  `Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Claude/Claude Code/NOTAM Parser Backups"`
  — einzige Definition `nola_db.ECHTER_SICHERUNGSORDNER`, `app.BACKUP_DIR` verweist darauf; Export nach `APP_DIR / "export" / "JJJJ-MM-TT-HHMM"`.
- Meldungstexte (verbindlich, englisch):
  - Konflikt: `"Changed by someone else meanwhile – the view has been reloaded, please check again."`
  - Sperre: `"Database is locked – write or revert the changes in DB Browser."`
  - Referenz-Undo verweigert: `"Reference table changed since this action - undo refused to protect newer entries."`
- Fehler beim Schreiben werden nie verschluckt (Ausnahme: das automatische Fortschreiben von Archiv
  und Seestarts je Durchlauf meldet sich als `st.warning`).

## Dateien

| Datei | Verantwortung |
|---|---|
| `nola_db.py` (neu) | Schema, Verbindungen, Tabellen lesen/ersetzen mit Stand, Arbeitsstand-Abgleich, Archiv-Import-Zustand, Sicherung/Wiederherstellung, Fehlerklassen |
| `nola_umzug.py` (neu) | Altdateien streng lesen, Umzug in temporäre Datei + `os.link`, `stelle_bereit`, Export in alte Formate |
| `test_nola_db.py` (neu) | Tests für beide neuen Module |
| `app.py` | Wrapper, Referenzen/Archiv/Seestarts/Arbeitsstand über die Datenbank, Undo, Start, Sicherung, Wiederherstellen, Export, Hinweise |
| `archiv_import.py` | Archiv über `app.archiv_lesen`/`archiv_schreiben`, Korpus/Zustand über die Datenbank, Erkennungsstand |
| `test_app.py` | Temp-Datenbank, betroffene Prüfungen umschreiben |
| `.gitignore`, `.claude/launch.json`, `README.md`, `STATUS.md`, `docs/projektplan.html` | Abschluss |

---

### Task 1: Speicherschicht-Kern (`nola_db.py`)

**Files:**
- Create: `nola_db.py`
- Create: `test_nola_db.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces:
  - Fehler: `class DbFehler(Exception)` mit Attribut `ursache: str`; Unterklassen `Gesperrt`,
    `Konflikt`, `DateiFehlt`, `SchemaZuNeu`.
  - `SCHEMA_VERSION: int = 1`, `PROJEKT_DB: Path`, `ECHTER_SICHERUNGSORDNER: Path`, `schuetze_echte_orte(*pfade) -> None`, `KONFLIKT_TEXT: str`, `GESPERRT_TEXT: str`
  - `FACHTABELLEN: Dict[str, Tuple[str, ...]]` — Schlüssel `startplaetze`, `firs`,
    `traegersysteme`, `startarchiv`, `seestarts`
  - `verbinde(pfad: Path, anlegen: bool = False) -> sqlite3.Connection`
  - `lege_schema_an(conn) -> None`, `setze_wal(conn) -> None`
  - `schema_version(conn) -> int`, `pruefe_schema(conn, sichern: Callable[[], Optional[Path]]) -> None`
  - `lese_tabelle(conn, tabelle: str) -> pd.DataFrame` (setzt `df.attrs["nola_stand"]`)
  - `ersetze_tabelle(conn, tabelle: str, df: pd.DataFrame, erwartet: Optional[str]) -> str`
  - `zaehle(conn, tabelle: str) -> int`, `setze_meta(conn, schluessel, wert)`, `lese_meta(conn, schluessel) -> Optional[str]`

**Acceptance Criteria:**
- `verbinde` auf eine fehlende Datei ohne `anlegen` wirft `DateiFehlt` und legt **keine** Datei an.
- Unter `NOLA_TEST=1` wirft `verbinde(PROJEKT_DB)` `RuntimeError`.
- Prüfregeln lehnen Breite `95`, Breite `abc`, leeren `Kurzel`, leere `Abkürzung` ab (`DbFehler`
  mit `ursache == "constraint failed"`).
- `ersetze_tabelle` mit veraltetem `erwartet` wirft `Konflikt` und ändert nichts; mit passendem
  `erwartet` ersetzt es und liefert den neuen Stand, der `lese_tabelle(...).attrs["nola_stand"]`
  entspricht.
- Hält eine zweite Verbindung `BEGIN IMMEDIATE`, wirft `ersetze_tabelle` nach ≤ 6 s `Gesperrt`.
- `lese_tabelle` liefert `object`-Spalten, `NULL` und `''` als `NaN`.
- `FACHTABELLEN` stimmt mit `app.SPACEPORT_EXPORT_COLUMNS`, `FIR_EXPORT_COLUMNS`,
  `VEHICLE_EXPORT_COLUMNS`, `ARCHIVE_COLUMNS`, `SEA_LAUNCH_COLUMNS` überein.
- `pruefe_schema`: neuere Version → `SchemaZuNeu`, nichts geschrieben; ältere Version und
  `sichern()` liefert `None` → `DbFehler(ursache="backup failed")`, Version unverändert.
- `test_app.py` unverändert grün.

- [ ] **Step 0: Ausgangswert festhalten**

```bash
git switch main && git pull --ff-only && git switch -c lokale-datenbank
.venv/bin/python test_app.py | grep -c "^  PASS"
```
Die Zahl mit `bd note <task-id> "PASS-Ausgangswert: <n>"` festhalten.

- [ ] **Step 1: Failing test schreiben — `test_nola_db.py` anlegen**

```python
import os, sys, sqlite3, tempfile, threading, time
os.environ["NOLA_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
import numpy as np
import pandas as pd
import nola_db as db

ok = True
def check(label, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label + (" " + str(extra) if extra else ""))
    if not cond: ok = False

def neue_db():
    pfad = Path(tempfile.mkdtemp()) / "t.db"
    conn = db.verbinde(pfad, anlegen=True)
    db.lege_schema_an(conn)
    return pfad, conn

print("== 1. Verbindung und Schutz ==")
_fehlt = Path(tempfile.mkdtemp()) / "fehlt.db"
try:
    db.verbinde(_fehlt); check("fehlende Datei -> DateiFehlt", False)
except db.DateiFehlt:
    check("fehlende Datei -> DateiFehlt", True)
check("fehlende Datei wird nicht angelegt", not _fehlt.exists())
try:
    db.verbinde(db.PROJEKT_DB); check("NOLA_TEST sperrt die Projektdatei", False)
except RuntimeError:
    check("NOLA_TEST sperrt die Projektdatei", True)
_p, _c = neue_db()
check("Schema-Version 1", db.schema_version(_c) == 1)

print("== 2. Spalten wie in app.py ==")
import app
check("FACHTABELLEN = app-Konstanten", db.FACHTABELLEN == {
    "startplaetze": tuple(app.SPACEPORT_EXPORT_COLUMNS), "firs": tuple(app.FIR_EXPORT_COLUMNS),
    "traegersysteme": tuple(app.VEHICLE_EXPORT_COLUMNS), "startarchiv": tuple(app.ARCHIVE_COLUMNS),
    "seestarts": tuple(app.SEA_LAUNCH_COLUMNS)})

print("== 3. Pruefregeln ==")
def _sp(**w):
    zeile = {"Kurzel": "JSLC", "Latitude": "40.9583", "Longitude": "100.2917", "Name": "J", "Land": "China"}
    zeile.update(w); return pd.DataFrame([zeile])
for _label, _df in [("Breite 95", _sp(Latitude="95")), ("Breite abc", _sp(Latitude="abc")),
                    ("leerer Kurzel", _sp(Kurzel=""))]:
    try:
        db.ersetze_tabelle(_c, "startplaetze", _df, None); check(_label + " abgelehnt", False)
    except db.DbFehler as e:
        check(_label + " abgelehnt", e.ursache == "constraint failed", e.ursache)
try:
    db.ersetze_tabelle(_c, "traegersysteme", pd.DataFrame([{"Land": "China", "Name": "CZ-2D",
        "Alternativname englisch": "", "Abkürzung": ""}]), None)
    check("leere Abkuerzung abgelehnt", False)
except db.DbFehler as e:
    check("leere Abkuerzung abgelehnt", e.ursache == "constraint failed")
check("nach Ablehnung leer", db.zaehle(_c, "startplaetze") == 0)

print("== 4. Lesen, Stand, Konflikt ==")
_stand1 = db.ersetze_tabelle(_c, "startplaetze", _sp(), None)
_df = db.lese_tabelle(_c, "startplaetze")
check("Stand im attrs", _df.attrs["nola_stand"] == _stand1)
check("Werte als Text", _df.loc[0, "Latitude"] == "40.9583" and _df["Latitude"].dtype == object)
_c.execute("UPDATE startplaetze SET Name = '' WHERE Kurzel = 'JSLC'")
check("'' wird NaN", pd.isna(db.lese_tabelle(_c, "startplaetze").loc[0, "Name"]))
try:
    db.ersetze_tabelle(_c, "startplaetze", _sp(Name="neu"), _stand1)
    check("veralteter Stand -> Konflikt", False)
except db.Konflikt:
    check("veralteter Stand -> Konflikt", True)
check("Konflikt aendert nichts", pd.isna(db.lese_tabelle(_c, "startplaetze").loc[0, "Name"]))
_aktuell = db.lese_tabelle(_c, "startplaetze").attrs["nola_stand"]
_stand2 = db.ersetze_tabelle(_c, "startplaetze", _sp(Name="neu"), _aktuell)
check("passender Stand -> geschrieben", db.lese_tabelle(_c, "startplaetze").loc[0, "Name"] == "neu")
check("Rueckgabe = neuer Stand", db.lese_tabelle(_c, "startplaetze").attrs["nola_stand"] == _stand2)

print("== 5. Sperre ==")
_zweite = db.verbinde(_p)
_zweite.execute("BEGIN IMMEDIATE")
_t0 = time.monotonic()
try:
    db.ersetze_tabelle(_c, "startplaetze", _sp(), None); check("gesperrt erkannt", False)
except db.Gesperrt as e:
    check("gesperrt erkannt", e.ursache == "locked")
check("Wartezeit hoechstens 6 s", time.monotonic() - _t0 < 6.5)
_zweite.execute("ROLLBACK"); _zweite.close()
check("Sperre aenderte nichts", db.lese_tabelle(_c, "startplaetze").loc[0, "Name"] == "neu")

print("== 6. Schema-Version ==")
_c.execute("UPDATE meta SET wert = '99' WHERE schluessel = 'schema_version'")
try:
    db.pruefe_schema(_c, lambda: None); check("neuere Version -> SchemaZuNeu", False)
except db.SchemaZuNeu:
    check("neuere Version -> SchemaZuNeu", True)
_c.execute("UPDATE meta SET wert = '0' WHERE schluessel = 'schema_version'")
try:
    db.pruefe_schema(_c, lambda: None); check("ohne Sicherung kein Umbau", False)
except db.DbFehler as e:
    check("ohne Sicherung kein Umbau", e.ursache == "backup failed")
check("Version unveraendert", db.schema_version(_c) == 0)
_c.close()

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
```

- [ ] **Step 2: Test laufen lassen, er scheitert**

Run: `.venv/bin/python test_nola_db.py`
Expected: `ModuleNotFoundError: No module named 'nola_db'`

- [ ] **Step 3: `nola_db.py` schreiben**

```python
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


def lege_schema_an(conn: sqlite3.Connection) -> None:
    """Legt alle Tabellen an und traegt die Schema-Version ein (nur auf leerer Datei)."""
    try:
        conn.executescript("BEGIN;\n" + _schema_sql() + "\nCOMMIT;")
        conn.execute(
            "INSERT INTO meta (schluessel, wert) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    except sqlite3.Error as exc:
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
    if sichern() is None:
        raise DbFehler(
            "backup failed",
            "Backup before the schema upgrade failed - the database was not changed.",
        )
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for n in range(version, SCHEMA_VERSION):
                conn.execute(SCHRITTE[n])  # einzelne Anweisungen; executescript beendete die Transaktion
            conn.execute(
                "UPDATE meta SET wert = ? WHERE schluessel = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
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
        conn.execute("BEGIN IMMEDIATE")
        try:
            if erwartet is not None and _stand(_zeilen(conn, tabelle)) != erwartet:
                raise Konflikt("changed", KONFLIKT_TEXT)
            conn.execute("DELETE FROM {}".format(_q(tabelle)))
            conn.executemany(einfuegen, werte)
            neu = _stand(_zeilen(conn, tabelle))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
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
```

`.gitignore` am Ende ergänzen:

```
# Lokale Datenbank (WAL-Nebendateien, temporaere Umzugsdatei) und Export
nola.db-wal
nola.db-shm
nola.db.*.tmp
export/
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1`
Expected: beide `ERGEBNIS: ALLE TESTS BESTANDEN`.

- [ ] **Step 5: Commit (nur mit Erlaubnis)**

```bash
git add nola_db.py test_nola_db.py .gitignore
git commit -m "Lokale Datenbank Aufgabe 1: Speicherschicht-Kern (<task-id>)"
```

---

### Task 2: Arbeitsstand und Archiv-Import-Zustand in `nola_db.py`

**Files:**
- Modify: `nola_db.py` (anfügen)
- Modify: `test_nola_db.py` (neue Abschnitte vor `print()`/`ERGEBNIS`)

**Interfaces:**
- Consumes: `verbinde`, `lege_schema_an`, `_uebersetze`, `Konflikt`, `KONFLIKT_TEXT` aus Task 1.
  **Seit der Fix-Runde von Aufgabe 1 gilt:** Jede Schreibtransaktion in dieser Aufgabe nutzt
  `with _transaktion(conn):` (Task 1) statt des ausgeschriebenen Musters
  `conn.execute("BEGIN IMMEDIATE") / try … COMMIT / except BaseException: ROLLBACK; raise`, das im
  Code unten noch steht. Grund: Rollt SQLite selbst zurück (z. B. Platte voll), scheitert ein
  explizites `ROLLBACK` und verdeckt die echte Ursache. Der Code unten ist entsprechend umzuschreiben;
  das äußere `except sqlite3.Error as exc: raise _uebersetze(exc) from exc` bleibt.
- Produces:
  - `ENTSCHEIDUNGS_SCHLUESSEL: Dict[str, str]` — `session_state`-Name → `art`
    (`confirmed_launches`→`bestaetigt`, `hidden_events`→`ausgeblendet`,
    `rejected_launches`→`abgelehnt`, `restored_events`→`wiederhergestellt`,
    `archiv_removed`→`archiv_entfernt`, `seestarts_removed`→`seestart_entfernt`)
  - `ZUWEISUNGS_SCHLUESSEL: Dict[str, str]` — `vehicle_assignments`→`traegersystem`,
    `payload_assignments`→`payload`, `launch_site_assignments`→`startplatz`
  - `leerer_arbeitsstand() -> Dict[str, Any]`
  - `lade_arbeitsstand(conn) -> Dict[str, Any]` — Schlüssel wie oben, Werte `set` bzw. `dict`;
    `"manual_notams"`: `List[{"id": int, "text": str, "added": str}]` nach `id`
  - `schreibe_unterschiede(conn, vorher: Dict, nachher: Dict, jetzt_utc: str) -> None` (wirft `Konflikt`)
  - `schreibe_arbeitsstand_neu(conn, stand: Dict, jetzt_utc: str) -> None` (nur Umzug: leert und füllt)
  - `lade_korpus(conn) -> List[Dict[str, Any]]` (Form der JSON-Einträge:
    `{"notam_id","b","text","quellen"}`), `speichere_korpus(conn, eintraege: Sequence[Tuple[str, Dict[str, Any]]])`
  - `lade_importzustand(conn) -> Dict[str, Any]` (Rohform wie `archiv_import.json`),
    `speichere_importzustand(conn, state: Dict[str, Any]) -> None`

**Acceptance Criteria:**
- Rundlauf: `schreibe_arbeitsstand_neu` + `lade_arbeitsstand` gibt jeden Eintrag zurück;
  manuelle NOTAMs bekommen `id`s, Reihenfolge bleibt.
- Zweite Verbindung ändert Schlüssel X, `schreibe_unterschiede` ändert Y → beide vorhanden.
- Gleicher Schlüssel mit veralteter Momentaufnahme → `Konflikt`, nichts geschrieben (auch nicht
  der gleichzeitig geänderte Schlüssel Y).
- Hat die andere Seite bereits genau den Zielzustand geschrieben → kein Konflikt.
- Bestätigen bei A und Ausblenden bei B auf demselben Schlüssel → B bekommt `Konflikt` (nie beides).
- Manuelles NOTAM extern gelöscht, anderes in NOLA entfernt → genau das gewählte ist weg; zwei
  gleichlautende NOTAMs bleiben unterscheidbar.
- Korpus und Importzustand gehen verlustfrei hin und zurück (inkl. Reihenfolge der Review-Listen).

- [ ] **Step 1: Failing tests anfügen (vor `print()` / `ERGEBNIS`)**

```python
print("== 7. Arbeitsstand ==")
_p2, _c2 = neue_db()
_stand = db.leerer_arbeitsstand()
_stand["manual_notams"] = [{"text": "A1/26 NOTAMN", "added": "01.10.2026 06:00Z"},
                           {"text": "A1/26 NOTAMN", "added": "01.10.2026 06:00Z"},
                           {"text": "B2/26 NOTAMN", "added": "02.10.2026 07:00Z"}]
_stand["confirmed_launches"] = {"k1"}
_stand["hidden_events"] = {"k2"}
_stand["vehicle_assignments"] = {"k1": "CZ-2D"}
_stand["archiv_removed"] = {"01.10.2026|A1/26"}
db.schreibe_arbeitsstand_neu(_c2, _stand, "2026-10-08T10:00:00+00:00")
_g = db.lade_arbeitsstand(_c2)
check("Rundlauf Entscheidungen", _g["confirmed_launches"] == {"k1"} and _g["hidden_events"] == {"k2"}
      and _g["archiv_removed"] == {"01.10.2026|A1/26"})
check("Rundlauf Zuweisung", _g["vehicle_assignments"] == {"k1": "CZ-2D"})
check("NOTAMs mit id, Reihenfolge", [n["text"] for n in _g["manual_notams"]]
      == ["A1/26 NOTAMN", "A1/26 NOTAMN", "B2/26 NOTAMN"] and all(isinstance(n["id"], int) for n in _g["manual_notams"]))
check("gleichlautende NOTAMs unterscheidbar", _g["manual_notams"][0]["id"] != _g["manual_notams"][1]["id"])

import copy as _copy
# fremde Verbindung aendert X (k3 bestaetigt), NOLA aendert Y (k2 wieder einblenden)
_fremd = db.verbinde(_p2)
_fremd.execute("INSERT INTO entscheidungen VALUES ('k3', 'bestaetigt', 'x')")
_neu = _copy.deepcopy(_g); _neu["hidden_events"] = set()
db.schreibe_unterschiede(_c2, _g, _neu, "t")
_h = db.lade_arbeitsstand(_c2)
check("verschiedene Zeilen: beide da", _h["confirmed_launches"] == {"k1", "k3"} and _h["hidden_events"] == set())

# veraltete Momentaufnahme: _g kennt k1 nur als bestaetigt; fremd blendet k1 zusaetzlich aus
_fremd.execute("DELETE FROM entscheidungen WHERE schluessel = 'k1'")
_fremd.execute("INSERT INTO entscheidungen VALUES ('k1', 'abgelehnt', 'x')")
_neu2 = _copy.deepcopy(_h); _neu2["confirmed_launches"] = {"k3"}; _neu2["hidden_events"] = {"k1"}
_neu2["vehicle_assignments"] = {"k1": "CZ-4C"}
try:
    db.schreibe_unterschiede(_c2, _h, _neu2, "t"); check("gleiche Zeile veraltet -> Konflikt", False)
except db.Konflikt:
    check("gleiche Zeile veraltet -> Konflikt", True)
_i = db.lade_arbeitsstand(_c2)
check("Konflikt: nichts geschrieben", _i["rejected_launches"] == {"k1"} and _i["hidden_events"] == set()
      and _i["vehicle_assignments"] == {"k1": "CZ-2D"})

# Zielzustand schon von anderer Seite geschrieben -> kein Konflikt
_ziel = _copy.deepcopy(_i); _ziel["confirmed_launches"] = _i["confirmed_launches"] | {"k9"}
_fremd.execute("INSERT INTO entscheidungen VALUES ('k9', 'bestaetigt', 'x')")
try:
    db.schreibe_unterschiede(_c2, _i, _ziel, "t"); check("gleicher Zielzustand -> kein Konflikt", True)
except db.Konflikt:
    check("gleicher Zielzustand -> kein Konflikt", False)

# Bestaetigen (A) gegen Ausblenden (B) auf k5
_basis = db.lade_arbeitsstand(_c2)
_a = _copy.deepcopy(_basis); _a["confirmed_launches"] = _basis["confirmed_launches"] | {"k5"}
_b = _copy.deepcopy(_basis); _b["hidden_events"] = _basis["hidden_events"] | {"k5"}
db.schreibe_unterschiede(_c2, _basis, _a, "t")
try:
    db.schreibe_unterschiede(_fremd, _basis, _b, "t"); check("A bestaetigt, B blendet aus -> Konflikt fuer B", False)
except db.Konflikt:
    check("A bestaetigt, B blendet aus -> Konflikt fuer B", True)
_k = db.lade_arbeitsstand(_c2)
check("k5 nur bestaetigt", "k5" in _k["confirmed_launches"] and "k5" not in _k["hidden_events"])

# manuelles NOTAM extern geloescht, anderes in NOLA entfernt
_m = db.lade_arbeitsstand(_c2)
_ids = [n["id"] for n in _m["manual_notams"]]
_fremd.execute("DELETE FROM manuelle_notams WHERE id = ?", (_ids[0],))
_ohne = _copy.deepcopy(_m); _ohne["manual_notams"] = [n for n in _m["manual_notams"] if n["id"] != _ids[2]]
db.schreibe_unterschiede(_c2, _m, _ohne, "t")
check("genau das gewaehlte NOTAM ist weg", [n["id"] for n in db.lade_arbeitsstand(_c2)["manual_notams"]] == [_ids[1]])
_neu3 = db.lade_arbeitsstand(_c2); _plus = _copy.deepcopy(_neu3)
_plus["manual_notams"].append({"text": "C3/26 NOTAMN", "added": "03.10.2026 08:00Z"})
db.schreibe_unterschiede(_c2, _neu3, _plus, "t")
check("neues NOTAM eingefuegt", [n["text"] for n in db.lade_arbeitsstand(_c2)["manual_notams"]][-1] == "C3/26 NOTAMN")
_fremd.close()

print("== 8. Archiv-Import-Zustand ==")
_eintraege = [("A1/26|2610010000", {"notam_id": "A1/26", "b": "2610010000", "text": "T", "quellen": ["s1.html"]})]
db.speichere_korpus(_c2, _eintraege)
check("Korpus Rundlauf", db.lade_korpus(_c2) == [_eintraege[0][1]])
_zst = {"version": 1, "tage": {"2026-10-01": {"fingerprint": "f", "kandidaten": [{"key": "x"}],
        "pruefliste": [], "usa": 2}}, "entscheidungen": {"x": {"status": "confirmed"}},
        "review_bestaetigt": ["r2", "r1"], "review_ausgeblendet": ["r3"], "erkennungsstand": "abc"}
db.speichere_importzustand(_c2, _zst)
check("Importzustand Rundlauf", db.lade_importzustand(_c2) == _zst)
_c2.close()
```

- [ ] **Step 2: Laufen lassen, scheitert**

Run: `.venv/bin/python test_nola_db.py`
Expected: `AttributeError: module 'nola_db' has no attribute 'leerer_arbeitsstand'`

- [ ] **Step 3: Implementieren (an `nola_db.py` anfügen)**

```python
from collections import defaultdict  # (zu den Importen oben)

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


def schreibe_unterschiede(
    conn: sqlite3.Connection, vorher: Dict[str, Any], nachher: Dict[str, Any], jetzt_utc: str
) -> None:
    """
    Schreibt nur, was sich zwischen Momentaufnahme `vorher` und `nachher`
    geaendert hat - in einer Schreibtransaktion. Fuer jeden beruehrten Schluessel
    muss die Datenbank noch den Stand von `vorher` haben (oder schon den von
    `nachher`); sonst Konflikt und nichts wird geschrieben.
    """
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
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            schreiben_e = []
            for s in e_geaendert:
                ist = frozenset(
                    a for (a,) in conn.execute(
                        "SELECT art FROM entscheidungen WHERE schluessel = ?", (s,))
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
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def schreibe_arbeitsstand_neu(conn: sqlite3.Connection, stand: Dict[str, Any], jetzt_utc: str) -> None:
    """Nur fuer Umzug und Tests: leert den Arbeitsstand und schreibt `stand` vollstaendig."""
    leer = leerer_arbeitsstand()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM entscheidungen")
            conn.execute("DELETE FROM zuweisungen")
            conn.execute("DELETE FROM manuelle_notams")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    ohne_ids = dict(stand)
    ohne_ids["manual_notams"] = [
        {"text": n["text"], "added": n.get("added", "")} for n in stand.get("manual_notams", [])
    ]
    schreibe_unterschiede(conn, leer, ohne_ids, jetzt_utc)


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
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM archiv_korpus")
            conn.executemany(
                "INSERT INTO archiv_korpus (schluessel, notam_id, b, text, quellen_json) "
                "VALUES (?, ?, ?, ?, ?)",
                [(s, e["notam_id"], e["b"], e["text"], json.dumps(e["quellen"], ensure_ascii=False))
                 for s, e in eintraege],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
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
        conn.execute("BEGIN IMMEDIATE")
        try:
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
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1`
Expected: beide `ERGEBNIS: ALLE TESTS BESTANDEN`.

- [ ] **Step 5: Commit (nur mit Erlaubnis)**

```bash
git add nola_db.py test_nola_db.py
git commit -m "Lokale Datenbank Aufgabe 2: Arbeitsstand mit Konfliktschutz, Import-Zustand (<task-id>)"
```

---

### Task 3: Sicherung und Wiederherstellung in `nola_db.py`

**Files:**
- Modify: `nola_db.py`, `test_nola_db.py`

**Interfaces:**
- Produces:
  - `sichere(conn, ordner: Path, jetzt: datetime, behalten: int = 30, zusatz: str = "") -> Path` (wirft `DbFehler`)
  - `liste_sicherungen(ordner: Path, nur_regulaer: bool = False) -> List[Path]` (neueste zuerst)
  - `sicherung_faellig(ordner: Path, heute: date) -> bool`
  - `ist_ausgelagert(stat_ergebnis) -> bool` (macOS-Flag `SF_DATALESS` = `0x40000000`)
  - `pruefe_sicherung(pfad: Path) -> Tuple[str, Optional[Dict[str, int]]]` — Status `ok` (mit Zeilenzahlen), `corrupt` oder `in_cloud` (ausgelagert, nicht geöffnet)
  - `stelle_wieder_her(sicherung: Path, pfad: Path) -> None` (überschreibt nie)

**Acceptance Criteria:**
- Sicherung besteht `integrity_check`, enthält alle Zeilen, liegt im Journalmodus `delete`
  (keine `-wal`-Dateien im iCloud-Ordner); während des Schreibens heißt sie `.nola-…db.tmp`.
- Nach der 31. regulären Sicherung bleiben 30; `…-vor-schema-<n>.db` zählt nicht mit und wird nicht gelöscht.
- `sicherung_faellig` ist `True` ohne Sicherung von heute, sonst `False`.
- Fehlender Ordner → `DbFehler(ursache="backup folder missing")`.
- `stelle_wieder_her` auf vorhandene Zieldatei → `DbFehler(ursache="exists")`, Ziel unverändert;
  sonst ist das Ziel eine gültige Kopie.
- `pruefe_sicherung` auf eine zerstörte Datei → `("corrupt", None)`; `ist_ausgelagert` erkennt das
  Flag an einem nachgebauten `stat`-Ergebnis; ausgelagerte Dateien werden nicht geöffnet (`in_cloud`).
- Unter `NOLA_TEST` werfen `sichere`, `liste_sicherungen`, `pruefe_sicherung` mit dem echten
  Sicherungsordner und `stelle_wieder_her` mit Ziel `PROJEKT_DB` einen `RuntimeError`; die Dateiliste
  des echten Ordners (falls vorhanden) ist danach unverändert.

- [ ] **Step 1: Failing tests anfügen**

```python
print("== 9. Sicherung ==")
from datetime import datetime as _dt, date as _date, timedelta as _td
_p3, _c3 = neue_db()
db.ersetze_tabelle(_c3, "startplaetze", _sp(), None)
_ord = Path(tempfile.mkdtemp())
try:
    db.sichere(_c3, _ord / "fehlt", _dt(2026, 10, 8, 9, 0)); check("fehlender Ordner -> Fehler", False)
except db.DbFehler as e:
    check("fehlender Ordner -> Fehler", e.ursache == "backup folder missing")
check("ohne Sicherung faellig", db.sicherung_faellig(_ord, _date(2026, 10, 8)))
_s1 = db.sichere(_c3, _ord, _dt(2026, 10, 8, 9, 0))
check("Name nach Muster", _s1.name == "nola-2026-10-08-0900.db")
check("keine Temp-Datei uebrig", not any(p.name.endswith(".tmp") for p in _ord.iterdir()))
check("Sicherung geprueft und vollstaendig", db.pruefe_sicherung(_s1)[0] == "ok"
      and db.pruefe_sicherung(_s1)[1]["startplaetze"] == 1)
_jm = sqlite3.connect(str(_s1)).execute("PRAGMA journal_mode").fetchone()[0]
check("Sicherung im Journalmodus delete", _jm == "delete", _jm)
check("heute nicht mehr faellig", not db.sicherung_faellig(_ord, _date(2026, 10, 8)))
check("morgen wieder faellig", db.sicherung_faellig(_ord, _date(2026, 10, 9)))
_vs = db.sichere(_c3, _ord, _dt(2026, 10, 8, 9, 1), zusatz="vor-schema-2")
for _n in range(31):
    db.sichere(_c3, _ord, _dt(2026, 10, 8, 10, 0) + _td(minutes=_n))
_reg = db.liste_sicherungen(_ord, nur_regulaer=True)
check("30 regulaere bleiben", len(_reg) == 30, len(_reg))
check("aelteste regulaere entfernt", not _s1.exists())
check("vor-schema bleibt", _vs.exists())
check("neueste zuerst", _reg[0].name == "nola-2026-10-08-1030.db", _reg[0].name)
_kaputt = _ord / "nola-2026-10-01-0000.db"; _kaputt.write_bytes(b"kein sqlite")
check("zerstoerte Sicherung -> corrupt", db.pruefe_sicherung(_kaputt) == ("corrupt", None))
class _StatAus: st_flags = 0x40000000
class _StatDa: st_flags = 0
check("ausgelagert erkannt", db.ist_ausgelagert(_StatAus()) and not db.ist_ausgelagert(_StatDa()))
_echt_vorher = sorted(os.listdir(db.ECHTER_SICHERUNGSORDNER)) if db.ECHTER_SICHERUNGSORDNER.is_dir() else None
for _label, _aufruf in [
        ("sichere", lambda: db.sichere(_c3, db.ECHTER_SICHERUNGSORDNER, _dt(2026, 10, 8, 9, 0))),
        ("liste_sicherungen", lambda: db.liste_sicherungen(db.ECHTER_SICHERUNGSORDNER)),
        ("pruefe_sicherung", lambda: db.pruefe_sicherung(db.ECHTER_SICHERUNGSORDNER / "nola-2026-10-08-0900.db")),
        ("stelle_wieder_her", lambda: db.stelle_wieder_her(_s1, db.PROJEKT_DB))]:
    try:
        _aufruf(); check("NOLA_TEST sperrt echten Ort: " + _label, False)
    except RuntimeError:
        check("NOLA_TEST sperrt echten Ort: " + _label, True)
check("echter Sicherungsordner unveraendert", _echt_vorher is None
      or sorted(os.listdir(db.ECHTER_SICHERUNGSORDNER)) == _echt_vorher)

print("== 10. Wiederherstellen ==")
_ziel = Path(tempfile.mkdtemp()) / "nola.db"
db.stelle_wieder_her(_reg[0], _ziel)
_cz = db.verbinde(_ziel)
check("wiederhergestellt", db.zaehle(_cz, "startplaetze") == 1); _cz.close()
_vorher = _ziel.read_bytes()
try:
    db.stelle_wieder_her(_reg[1], _ziel); check("ueberschreibt nie", False)
except db.DbFehler as e:
    check("ueberschreibt nie", e.ursache == "exists" and _ziel.read_bytes() == _vorher)
_c3.close()
```

- [ ] **Step 2: Laufen lassen, scheitert**

Run: `.venv/bin/python test_nola_db.py`
Expected: `AttributeError: module 'nola_db' has no attribute 'sichere'`

- [ ] **Step 3: Implementieren**

```python
import re  # (zu den Importen)
from datetime import date, datetime  # (zu den Importen)

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
        if pruefung != "ok":
            raise DbFehler("backup corrupt", "Backup failed the integrity check: {}".format(pruefung))
        os.replace(tmp, ziel)
    except sqlite3.Error as exc:
        tmp.unlink(missing_ok=True)
        raise _uebersetze(exc) from exc
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise DbFehler("backup failed", "Backup failed: {}".format(exc)) from exc
    except DbFehler:
        tmp.unlink(missing_ok=True)
        raise
    if not zusatz:
        for alt in liste_sicherungen(ordner, nur_regulaer=True)[behalten:]:
            alt.unlink(missing_ok=True)
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


def stelle_wieder_her(sicherung: Path, pfad: Path) -> None:
    """Kopiert eine Sicherung nach `pfad` - nur, wenn dort keine Datei liegt (os.link)."""
    pfad = Path(pfad)
    schuetze_echte_orte(pfad)
    if pfad.exists():
        raise DbFehler("exists", "{} exists - restore refused, nothing was overwritten.".format(pfad.name))
    tmp = pfad.parent / "{}.{}.tmp".format(pfad.name, os.urandom(4).hex())
    try:
        quelle = sqlite3.connect(
            "file:{}?mode=ro".format(urllib.parse.quote(str(Path(sicherung).resolve()))), uri=True
        )
        ziel = sqlite3.connect(str(tmp))
        try:
            quelle.backup(ziel)
            if ziel.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DbFehler("backup corrupt", "The selected backup is corrupt.")
        finally:
            ziel.close()
            quelle.close()
        try:
            os.link(tmp, pfad)
        except FileExistsError as exc:
            raise DbFehler("exists", "{} exists - restore refused.".format(pfad.name)) from exc
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
    finally:
        tmp.unlink(missing_ok=True)
```

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1`
Expected: beide bestanden.

- [ ] **Step 5: Commit (nur mit Erlaubnis)**

```bash
git add nola_db.py test_nola_db.py
git commit -m "Lokale Datenbank Aufgabe 3: Sicherung und Wiederherstellung (<task-id>)"
```

---

### Task 4: Umzug, Start-Entscheidung und Export (`nola_umzug.py`)

**Files:**
- Create: `nola_umzug.py`
- Modify: `archiv_import.py` (Strukturprüfungen aus `load_korpus`/`load_state` als Funktionen auf Daten herauslösen)
- Modify: `app.py` (nur: `DB_PATH`, `BACKUP_DIR` neben `WORKSPACE_FILE`)
- Modify: `test_nola_db.py`

**Interfaces:**
- Consumes: Task 1–3; aus `app`: `_read_csv_any`, `_require_columns`, `read_archive_strict`,
  `ArchiveUnreadable`, `migrate_archive_keys`, `persist_reference`, `persist_archive`,
  `persist_sea_launches`, `save_workspace`, Pfadkonstanten; aus `archiv_import`: `load_korpus`,
  `load_state`, `save_korpus`, `save_state`, `KorpusNotam`, `ImportStateError`.
- Produces:
  - `app.DB_PATH: Path = APP_DIR / "nola.db"`, `app.BACKUP_DIR: Path`
  - `archiv_import.korpus_aus_daten(data: Dict, name: str) -> Dict[str, KorpusNotam]`
  - `archiv_import.zustand_aus_daten(data: Dict, name: str) -> Dict[str, Any]`
  - `nola_umzug.Altdateien` (dataclass: `startplaetze, firs, traegersysteme, startarchiv, seestarts, arbeitsstand, korpus, importzustand: Path`), `nola_umzug.altdateien_im(app_dir: Path) -> Altdateien`
  - `nola_umzug.UmzugFehler(Exception)`
  - `nola_umzug.umziehen(db: Path, alt: Altdateien) -> Dict[str, int]`
  - `nola_umzug.Startzustand` (dataclass: `art: str` ∈ `bereit|umgezogen|fehlt_mit_sicherungen|fehlgeschlagen`, `grund: str = ""`, `zaehlung: Dict[str, int]`)
  - `nola_umzug.stelle_bereit(db: Path, alt: Altdateien, sicherungsordner: Path, jetzt: datetime) -> Startzustand`
  - `nola_umzug.exportieren(db: Path, ziel: Path) -> Path`

**Acceptance Criteria:**
- Umzug mit Kopien der echten Projektdateien: Zeilenzahl je Quelle = Tabelle; je Fachtabelle ist
  `lese_tabelle` (ohne `attrs`) `pd.testing.assert_frame_equal`-gleich mit dem Altdatei-Leser
  (`_read_csv_any` + Exportspalten bzw. `read_archive_strict`), **inklusive Datentypen**;
  Umlaute in Spaltennamen kommen an; `archiv_removed` ist mit `migrate_archive_keys` umgestellt.
- Unlesbare Altdatei (kaputte JSON, Archiv mit falscher Kopfzeile, kaputte Seestart-CSV) →
  `UmzugFehler` nennt die Datei; keine `nola.db`, keine `.tmp`-Datei übrig.
- Fehlende Altdatei → leere Tabelle, Umzug gelingt.
- Liegt `nola.db` schon, bevor `os.link` läuft, bleibt sie byte-gleich; `umziehen` gibt trotzdem zurück.
- `stelle_bereit`: vorhandene DB → `bereit`; fehlt und keine Sicherung → `umgezogen`; fehlt und
  Sicherungen vorhanden → `fehlt_mit_sicherungen` und es entsteht **keine** Datei; neuere
  Schema-Version → `fehlgeschlagen`.
- Export → alte Leser → gleich der Datenbank (alle acht Dateien); Altdateien im Projekt unberührt.

- [ ] **Step 1: `archiv_import.py` vorbereiten — Strukturprüfung von Datei trennen**

In `load_korpus` den Körper ab `korpus: Dict[...] = {}` in eine neue Funktion verschieben:

```python
def korpus_aus_daten(data: Dict[str, Any], name: str) -> Dict[str, KorpusNotam]:
    """Prueft und baut den Korpus aus der Rohform (Datei oder Datenbank)."""
    korpus: Dict[str, KorpusNotam] = {}
    try:
        for e in data.get("notams", []):
            quellen = e.get("quellen", [])
            felder = [e["notam_id"], e["b"], e["text"]]
            if not all(isinstance(v, str) for v in felder) or not isinstance(quellen, list) \
                    or not all(isinstance(q, str) for q in quellen):
                raise TypeError("wrong value type in a NOTAM entry")
            n = KorpusNotam(felder[0], felder[1], felder[2], list(quellen))
            korpus[n.schluessel] = n
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ImportStateError(
            "{} has an unexpected structure ({!r}). It is left untouched - please check it.".format(
                name, exc)
        ) from exc
    return korpus


def load_korpus(path: Path = KORPUS_JSON) -> Dict[str, KorpusNotam]:
    return korpus_aus_daten(read_json(path), path.name)
```

Ebenso `load_state`: alles nach `data = read_json(path)` wird `zustand_aus_daten(data, name)`
(in `kaputt` heißt es `name` statt `path.name`); `load_state(path)` ruft
`zustand_aus_daten(read_json(path), path.name)`. Inhalt unverändert.

Run: `.venv/bin/python test_app.py | tail -1` → `ALLE TESTS BESTANDEN` (reine Umstellung).

In `app.py` oben `import nola_db` ergänzen und direkt unter `WORKSPACE_FILE = ...`:

```python
#: Die lokale Datenbank - Quelle der Wahrheit fuer alles Eingepflegte.
DB_PATH = APP_DIR / "nola.db"
#: Sicherungen der Datenbank (iCloud Drive); die Datenbank selbst liegt nie dort.
BACKUP_DIR = nola_db.ECHTER_SICHERUNGSORDNER
```

- [ ] **Step 2: Failing tests anfügen**

```python
print("== 11. Umzug ==")
import shutil, json as _json
import archiv_import as ai
import nola_umzug as um

def _altordner(mit_echten=True):
    d = Path(tempfile.mkdtemp())
    if mit_echten:
        for f in (app.SPACEPORT_CSV, app.FIR_CSV, app.VEHICLE_CSV):
            shutil.copy(f, d / f.name)
        for f in (app.ARCHIVE_CSV, app.SEA_LAUNCH_CSV, app.WORKSPACE_FILE, ai.KORPUS_JSON, ai.IMPORT_JSON):
            if f.exists():
                shutil.copy(f, d / f.name)
    return d

_alt_d = _altordner()
_alt = um.altdateien_im(_alt_d)
_db_p = Path(tempfile.mkdtemp()) / "nola.db"
_zahl = um.umziehen(_db_p, _alt)
_cu = db.verbinde(_db_p)
for _t, _datei, _sp_ in [("startplaetze", _alt.startplaetze, app.SPACEPORT_EXPORT_COLUMNS),
                         ("firs", _alt.firs, app.FIR_EXPORT_COLUMNS),
                         ("traegersysteme", _alt.traegersysteme, app.VEHICLE_EXPORT_COLUMNS)]:
    _erw = app._read_csv_any(str(_datei))[list(_sp_)].reset_index(drop=True)
    _ist = db.lese_tabelle(_cu, _t); _ist.attrs = {}
    try:
        pd.testing.assert_frame_equal(_ist, _erw, check_dtype=True); check("Rundlauf " + _t, True)
    except AssertionError as e:
        check("Rundlauf " + _t, False, str(e)[:200])
_erw_a = app.read_archive_strict(_alt.startarchiv)[list(app.ARCHIVE_COLUMNS)].reset_index(drop=True)
_ist_a = db.lese_tabelle(_cu, "startarchiv"); _ist_a.attrs = {}
try:
    pd.testing.assert_frame_equal(_ist_a, _erw_a, check_dtype=True); check("Rundlauf startarchiv", True)
except AssertionError as e:
    check("Rundlauf startarchiv", False, str(e)[:200])
check("Zeilenzahlen gemeldet", _zahl["startarchiv"] == len(_erw_a))
check("Traegersysteme und Seestarts umgezogen (ohne Koordinatenspalten)",
      _zahl["traegersysteme"] == len(app._read_csv_any(str(_alt.traegersysteme)))
      and _zahl["seestarts"] == (len(app._read_csv_any(str(_alt.seestarts))) if _alt.seestarts.exists() else 0))
check("Umlaut-Spalte vorhanden", "Trägersystem" in db.lese_tabelle(_cu, "startarchiv").columns)
if _alt.arbeitsstand.exists():
    _ws = _json.loads(_alt.arbeitsstand.read_text(encoding="utf-8"))
    _gl = db.lade_arbeitsstand(_cu)
    check("Arbeitsstand: NOTAMs", len(_gl["manual_notams"]) == len(_ws.get("manual_notams", [])))
    check("Arbeitsstand: archiv_removed umgestellt",
          _gl["archiv_removed"] == app.migrate_archive_keys(_ws.get("archiv_removed", [])))
_cu.close()

for _name, _inhalt in [("notam_workspace.json", "kein json"),
                       ("startarchiv_updated.csv", "falsch,kopf\n1,2\n"),
                       ("seestarts_updated.csv", b"\xff\xfe\x00\x00kaputt")]:
    _d = _altordner(); _f = _d / _name
    (_f.write_bytes(_inhalt) if isinstance(_inhalt, bytes) else _f.write_text(_inhalt, encoding="utf-8"))
    _z = Path(tempfile.mkdtemp()) / "nola.db"
    try:
        um.umziehen(_z, um.altdateien_im(_d)); check("unlesbar {} -> Abbruch".format(_name), False)
    except um.UmzugFehler as e:
        check("unlesbar {} -> Abbruch".format(_name), _name in str(e), str(e)[:120])
    check("  keine nola.db", not _z.exists())
    check("  keine Temp-Datei", not any(p.name.endswith(".tmp") for p in _z.parent.iterdir()))

_leer = _altordner(mit_echten=False); _zl = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_zl, um.altdateien_im(_leer))
_cl = db.verbinde(_zl); check("fehlende Altdateien -> leere Tabellen", db.zaehle(_cl, "startarchiv") == 0); _cl.close()

# nola.db entsteht waehrend des Umzugs -> bleibt unveraendert
_zr = Path(tempfile.mkdtemp()) / "nola.db"
_orig_link = um.os.link
def _vorher_anlegen(src, dst):
    Path(dst).write_bytes(b"vorhanden"); return _orig_link(src, dst)
um.os.link = _vorher_anlegen
try:
    um.umziehen(_zr, um.altdateien_im(_altordner()))
finally:
    um.os.link = _orig_link
check("vorhandene nola.db nicht ueberschrieben", _zr.read_bytes() == b"vorhanden")

print("== 12. Start-Entscheidung ==")
from datetime import datetime as _dt2
_sd = Path(tempfile.mkdtemp()); _sdb = _sd / "nola.db"; _sord = Path(tempfile.mkdtemp())
_z1 = um.stelle_bereit(_sdb, um.altdateien_im(_altordner()), _sord, _dt2(2026, 10, 8, 9, 0))
check("fehlt, keine Sicherung -> umgezogen", _z1.art == "umgezogen" and _sdb.exists(), _z1)
_z2 = um.stelle_bereit(_sdb, um.altdateien_im(_altordner()), _sord, _dt2(2026, 10, 8, 9, 0))
check("vorhanden -> bereit", _z2.art == "bereit", _z2)
_cs = db.verbinde(_sdb); db.sichere(_cs, _sord, _dt2(2026, 10, 8, 9, 5)); _cs.close()
_sdb.unlink()
_z3 = um.stelle_bereit(_sdb, um.altdateien_im(_altordner()), _sord, _dt2(2026, 10, 8, 9, 10))
check("fehlt mit Sicherungen -> Wahl, keine Datei", _z3.art == "fehlt_mit_sicherungen" and not _sdb.exists(), _z3)
_z4db = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_z4db, um.altdateien_im(_altordner()))
_c4 = db.verbinde(_z4db); db.setze_meta(_c4, "schema_version", "99"); _c4.close()
_z4 = um.stelle_bereit(_z4db, um.altdateien_im(_altordner()), _sord, _dt2(2026, 10, 8, 9, 0))
check("neuere Version -> fehlgeschlagen", _z4.art == "fehlgeschlagen", _z4)

print("== 13. Export ==")
_ex = um.exportieren(_db_p, Path(tempfile.mkdtemp()) / "export")
_ce = db.verbinde(_db_p)
for _t, _n in [("startplaetze", app.SPACEPORT_CSV.name), ("firs", app.FIR_CSV.name),
               ("traegersysteme", app.VEHICLE_CSV.name)]:
    _a = app._read_csv_any(str(_ex / _n)).reset_index(drop=True)
    _b = db.lese_tabelle(_ce, _t); _b.attrs = {}
    try:
        pd.testing.assert_frame_equal(_a[list(_b.columns)], _b); check("Export " + _t, True)
    except AssertionError as e:
        check("Export " + _t, False, str(e)[:200])
_ea = app.read_archive_strict(_ex / app.ARCHIVE_CSV.name).reset_index(drop=True)
_eb = db.lese_tabelle(_ce, "startarchiv"); _eb.attrs = {}
try:
    pd.testing.assert_frame_equal(_ea[list(_eb.columns)], _eb); check("Export startarchiv", True)
except AssertionError as e:
    check("Export startarchiv", False, str(e)[:200])
_ew = _json.loads((_ex / app.WORKSPACE_FILE.name).read_text(encoding="utf-8"))
_gw = db.lade_arbeitsstand(_ce)
check("Export Arbeitsstand", [n["text"] for n in _ew["manual_notams"]] == [n["text"] for n in _gw["manual_notams"]]
      and set(_ew["hidden_events"]) == _gw["hidden_events"])
check("Export Korpus lesbar", isinstance(ai.load_korpus(_ex / ai.KORPUS_JSON.name), dict))
check("Export Importzustand lesbar", isinstance(ai.load_state(_ex / ai.IMPORT_JSON.name), dict))
try:
    um.exportieren(_db_p, app.APP_DIR / "export" / "test"); check("NOLA_TEST sperrt Export ins Projekt", False)
except RuntimeError:
    check("NOLA_TEST sperrt Export ins Projekt", True)
check("Export Seestarts lesbar", len(app.load_sea_launches(_ex / app.SEA_LAUNCH_CSV.name)) == db.zaehle(_ce, "seestarts"))
_ce.close()
```

- [ ] **Step 3: Laufen lassen, scheitert**

Run: `.venv/bin/python test_nola_db.py`
Expected: `ModuleNotFoundError: No module named 'nola_umzug'`

- [ ] **Step 4: `nola_umzug.py` schreiben**

```python
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
```

Hinweis zum Export-Schreiber: `persist_reference`, `persist_archive` und `persist_sea_launches`
verschlucken `OSError`. Für den Export werden deshalb `persist_reference` (wirft) und direkt
`_write_bytes_atomic` (wirft) verwendet, damit ein Exportfehler sichtbar wird.

- [ ] **Step 5: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1`
Expected: beide bestanden. Scheitert ein Rundlauf an Datentypen, wird `lese_tabelle` oder
`_csv_streng` angepasst — nie der Test.

- [ ] **Step 6: Commit (nur mit Erlaubnis)**

```bash
git add nola_umzug.py nola_db.py archiv_import.py app.py test_nola_db.py
git commit -m "Lokale Datenbank Aufgabe 4: Umzug, Start-Entscheidung, Export (<task-id>)"
```

---

### Task 5: Referenzen über die Datenbank, Undo einheitlich

**Files:**
- Modify: `app.py` — `load_spaceports`, `load_firs`, `load_vehicles` (Aufbereitung herauslösen),
  `_reference_status`, `_push_undo`, `_undo_archive`, `_undo_reference`, `_write_reference`,
  `_remove_reference_row`, `_add_reference_row`, die drei Editoren (`_spaceport_editor` und die
  beiden anderen, über `grep -n "_remove_reference_row(\|_add_reference_row(" app.py` finden),
  `_reference_row`-Aufrufer, Referenzaufruf in `main()`
- Modify: `test_app.py` — Kopf (Temp-Datenbank), betroffene Prüfungen
- Modify: `archiv_import.py` — `detection_stamp`

**Interfaces:**
- Consumes: `nola_db.lese_tabelle`, `ersetze_tabelle`, `Konflikt`, `DbFehler`; `nola_umzug.umziehen`, `altdateien_im` (nur in Tests).
- Produces (in `app.py`):
  - `@contextmanager _db(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]`
  - `REFERENZ_TABELLEN: Dict[str, str]` — `"spaceports"→"startplaetze"`, `"firs"→"firs"`, `"vehicles"→"traegersysteme"`
  - `prepare_spaceports(df) -> DataFrame`, `prepare_firs(df) -> DataFrame`, `prepare_vehicles(df) -> DataFrame`
  - `referenz_lesen(tabelle: str, db: Optional[Path] = None) -> DataFrame` (aufbereitet, `attrs["nola_stand"]` erhalten)
  - `REFERENCE_UNDO_REFUSED: str`
  - `_push_undo(tabelle: str, vorher: DataFrame, nachher_stand: str, label: str) -> Dict`
  - `_write_reference(tabelle: str, df: DataFrame, columns, label: str, vorher: DataFrame) -> None`
  - `_remove_reference_row(tabelle, df, columns, key_column, key)`, `_add_reference_row(tabelle, df, columns, key_column, zeile)` (erster Parameter jetzt Tabellenname statt Pfad)
  - `archiv_import.detection_stamp(paths=(app.py, archiv_import.py), db=None) -> str`

**Acceptance Criteria:**
- `referenz_lesen` liefert dieselben DataFrames wie `load_spaceports/load_firs/load_vehicles` auf
  der gleichen CSV (inkl. `Nationen`), mit `attrs["nola_stand"]`.
- Hinzufügen/Entfernen im Editor schreibt die Datenbank, nicht die CSV (CSV-Bytes unverändert).
- Referenzänderung von außen zwischen Lesen und Schreiben → Konflikt-Meldung, nichts geschrieben.
- Hinzufügen, Entfernen, Undo, Undo → exakt der Ausgangsstand; Undo nach fremder Änderung →
  `UndoRefused(REFERENCE_UNDO_REFUSED)`.
- Werte aus der Datenbank laufen in den Editoren durch `_md_plain` (z. B. Name `**x**` erscheint
  als `\*\*x\*\*`).
- `detection_stamp` ändert sich, wenn eine Referenztabelle in der Datenbank geändert wird.
- `test_app.py` grün, PASS ≥ Ausgangswert.

- [ ] **Step 1: Testkopf von `test_app.py` umstellen**

Die ersten Zeilen werden:

```python
import os, sys, math, re
os.environ["NOLA_TEST"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app
import tempfile as _tf_db
from pathlib import Path as _P_db
import nola_umzug as _um_db
# Jede Pruefung arbeitet auf einer Temp-Datenbank aus den echten Projektdateien;
# die echte nola.db sperrt nola_db.verbinde unter NOLA_TEST.
app.DB_PATH = _P_db(_tf_db.mkdtemp()) / "nola.db"
_um_db.umziehen(app.DB_PATH, _um_db.altdateien_im(app.APP_DIR))
```

- [ ] **Step 2: Failing tests am Ende von `test_app.py` anfügen** (vor `print()` / `ERGEBNIS`)

```python
print("== Lokale Datenbank: Referenzen ==")
import nola_db as _ndb
check("DB-Pfad ist Temp", app.DB_PATH != _ndb.PROJEKT_DB)
_sp_csv = app.load_spaceports(str(app.SPACEPORT_CSV))
_sp_db = app.referenz_lesen("startplaetze")
_sp_db2 = _sp_db.copy(); _sp_db2.attrs = {}
try:
    import pandas as _pd_r
    _pd_r.testing.assert_frame_equal(_sp_db2.reset_index(drop=True), _sp_csv.reset_index(drop=True))
    check("Startplaetze aus DB = aus CSV", True)
except AssertionError as e:
    check("Startplaetze aus DB = aus CSV", False, str(e)[:200])
_fir_db = app.referenz_lesen("firs")
check("FIR mit Nationen", "Nationen" in _fir_db.columns and "nola_stand" in _fir_db.attrs)
_fir_csv = app.load_firs(str(app.FIR_CSV))
_fir_db2 = _fir_db.copy(); _fir_db2.attrs = {}
try:
    _pd_r.testing.assert_frame_equal(_fir_db2.reset_index(drop=True), _fir_csv.reset_index(drop=True))
    check("FIRs aus DB = aus CSV (Koordinaten zahlengleich)", True)
except AssertionError as e:
    check("FIRs aus DB = aus CSV (Koordinaten zahlengleich)", False, str(e)[:200])
_veh_db = app.referenz_lesen("traegersysteme"); _veh_db.attrs = {}
check("Traegersysteme aus DB = aus CSV", _veh_db.equals(app.load_vehicles(str(app.VEHICLE_CSV))))
_csv_bytes = app.SPACEPORT_CSV.read_bytes()

class _StR:
    def __init__(self): self.session_state = {}
    def warning(self, *a, **k): self.session_state.setdefault("_w", []).append(a)
    error = info = success = warning
_st_orig_r = app.st; app.st = _StR()
try:
    _neu = {"Kurzel": "ZZZZ", "Latitude": 1.0, "Longitude": 2.0, "Name": "**x**", "Land": "China"}
    app._add_reference_row("startplaetze", _sp_db, app.SPACEPORT_EXPORT_COLUMNS, "Kurzel", _neu)
    _nach = app.referenz_lesen("startplaetze")
    check("Hinzufuegen schreibt DB", "ZZZZ" in set(_nach["Kurzel"]))
    check("CSV unveraendert", app.SPACEPORT_CSV.read_bytes() == _csv_bytes)
    app._remove_reference_row("startplaetze", _nach, app.SPACEPORT_EXPORT_COLUMNS, "Kurzel", "ZZZZ")
    check("Entfernen schreibt DB", "ZZZZ" not in set(app.referenz_lesen("startplaetze")["Kurzel"]))
    app._undo_reference(); app._undo_reference()
    _zur = app.referenz_lesen("startplaetze"); _zur.attrs = {}
    check("zweimal Undo -> Ausgangsstand", _zur.equals(_sp_db2))
    # fremde Aenderung zwischen Lesen und Schreiben
    _alt_stand = app.referenz_lesen("startplaetze")
    with app._db() as _c:
        _c.execute("UPDATE startplaetze SET Name = 'fremd' WHERE Kurzel = 'JSLC'")
    app._add_reference_row("startplaetze", _alt_stand, app.SPACEPORT_EXPORT_COLUMNS, "Kurzel", _neu)
    check("Konflikt: nichts geschrieben", "ZZZZ" not in set(app.referenz_lesen("startplaetze")["Kurzel"]))
    check("Konflikt gemeldet", app.st.session_state.get("db_meldung", ("", ""))[1] == _ndb.KONFLIKT_TEXT)
    # Undo nach fremder Aenderung verweigert
    app._add_reference_row("startplaetze", app.referenz_lesen("startplaetze"),
                           app.SPACEPORT_EXPORT_COLUMNS, "Kurzel", _neu)
    with app._db() as _c:
        _c.execute("UPDATE startplaetze SET Name = 'fremd2' WHERE Kurzel = 'JSLC'")
    try:
        app._undo_reference(); check("Undo nach fremder Aenderung verweigert", False)
    except app.UndoRefused as e:
        check("Undo nach fremder Aenderung verweigert", str(e) == app.REFERENCE_UNDO_REFUSED)
finally:
    app.st = _st_orig_r
import inspect as _ins_r
check("Editor entschaerft DB-Werte", "_md_plain(" in _ins_r.getsource(app._spaceport_editor))
import archiv_import as _ai_r
_s1 = _ai_r.detection_stamp()
with app._db() as _c:
    _c.execute("UPDATE firs SET Land = Land || ' ' WHERE rowid = 1")
check("Erkennungsstand folgt der DB", _ai_r.detection_stamp() != _s1)
```

- [ ] **Step 3: Laufen lassen, scheitert**

Run: `.venv/bin/python test_app.py | grep -E "FAIL|Error" | head`
Expected: `AttributeError: module 'app' has no attribute 'referenz_lesen'`

- [ ] **Step 4: Implementieren**

Importe oben in `app.py` ergänzen: `import sqlite3`, `from contextlib import contextmanager`,
`from typing import Iterator` (zur bestehenden `typing`-Zeile); `import nola_db` steht seit Aufgabe 4.

Aufbereitung herauslösen (Inhalt unverändert aus den bestehenden Ladern übernommen):

```python
def prepare_spaceports(df: pd.DataFrame) -> pd.DataFrame:
    df = _require_columns(df, SPACEPORT_COLUMNS, "Weltraumbahnhoefe")
    df["Kurzel"] = df["Kurzel"].astype(str).str.strip().str.upper()
    df["Land"] = df["Land"].astype(str).str.strip()
    return df


def prepare_firs(df: pd.DataFrame) -> pd.DataFrame:
    df = _require_columns(df, FIR_COLUMNS, "ICAO FIR/ACC")
    df["ICAO Code"] = df["ICAO Code"].astype(str).str.strip().str.upper()
    df["Nationen"] = (
        df["Zugehörige Startnation"]
        .astype(str)
        .apply(lambda s: [p.strip() for p in re.split(r"[;,/]", s) if p.strip()])
    )
    return df


def prepare_vehicles(df: pd.DataFrame) -> pd.DataFrame:
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
```

`load_spaceports`/`load_firs`/`load_vehicles` behalten Signatur und Cache und rufen nur noch
`prepare_*(_read_csv_any(path_str))` (bei `load_vehicles` ohne den herausgelösten Teil). Falls
`_require_columns` eine Kopie liefert, bleibt das Verhalten gleich, weil es heute genauso aufgerufen wird.

Neue Hilfen (direkt nach `persist_reference`):

```python
@contextmanager
def _db(db: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """Eine kurze Verbindung je Durchlauf bzw. Callback - nie ueber Threads geteilt."""
    conn = nola_db.verbinde(db or DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


REFERENZ_TABELLEN = {"spaceports": "startplaetze", "firs": "firs", "vehicles": "traegersysteme"}
_PREPARE = {"startplaetze": prepare_spaceports, "firs": prepare_firs, "traegersysteme": prepare_vehicles}


def referenz_lesen(tabelle: str, db: Optional[Path] = None) -> pd.DataFrame:
    """Referenztabelle aus der Datenbank, aufbereitet wie aus der CSV; der Stand bleibt in attrs."""
    with _db(db) as conn:
        roh = nola_db.lese_tabelle(conn, tabelle)
    stand = roh.attrs.get("nola_stand")
    df = _PREPARE[tabelle](roh.copy())
    df.attrs["nola_stand"] = stand
    return df
```

`_reference_status(label, path)` wird `_reference_status(label, tabelle)`:

```python
def _reference_status(label: str, tabelle: str) -> Tuple[Optional[pd.DataFrame], str]:
    """Laedt eine Referenztabelle aus der Datenbank und liefert Dataframe plus Statusmeldung."""
    try:
        df = referenz_lesen(tabelle)
    except Exception as exc:
        return None, "{} {}: {}".format(glyph(GLYPH_MISSING, COLOR_ERROR), label, exc)
    if df.empty:
        return None, "{} {}: no entries in the database".format(glyph(GLYPH_MISSING, COLOR_ERROR), label)
    return df, "{} {}: {} entries".format(glyph(GLYPH_OK, COLOR_OK, 0.85), label, len(df))
```

In `main()`: `_reference_status("Weltraumbahnhoefe", SPACEPORT_CSV)` → `"startplaetze"`,
`FIR_CSV` → `"firs"`, `VEHICLE_CSV` → `"traegersysteme"`. Die Hinweisliste der fehlenden Dateien
direkt darunter (`- \`icao_fir_acc_coordinates_updated.csv\`` …) wird zu
`"The reference tables in nola.db are empty or unreadable."`.

Undo einheitlich (ersetzt `_push_undo`, `_undo_archive`, `_undo_reference`, `_write_reference`):

```python
REFERENCE_UNDO_REFUSED = (
    "Reference table changed since this action - undo refused to protect newer entries."
)


def _spalten_von(tabelle: str) -> Tuple[str, ...]:
    return nola_db.FACHTABELLEN[tabelle]


def _push_undo(tabelle: str, vorher: pd.DataFrame, nachher_stand: str, label: str) -> Dict[str, Any]:
    """Merkt den Tabelleninhalt vor und den Stand nach einer Aenderung."""
    stapel = st.session_state.setdefault("ref_undo", [])
    eintrag = {
        "tabelle": tabelle,
        "zeilen": vorher[list(_spalten_von(tabelle))].to_dict("records"),
        "nachher": nachher_stand,
        "label": label,
    }
    stapel.append(eintrag)
    del stapel[:-UNDO_LIMIT]
    return eintrag


def _undo_reference() -> Optional[str]:
    """
    Nimmt die letzte Aenderung zurueck - nur, wenn die Tabelle seitdem
    unveraendert ist. Sonst faellt der Eintrag vom Stapel (dieser Stand kehrt
    nicht zurueck) und UndoRefused nennt den Grund. Bei einem Lesefehler bleibt
    der Eintrag liegen.
    """
    stapel = st.session_state.get("ref_undo", [])
    if not stapel:
        return None
    letzter = stapel[-1]
    tabelle = letzter["tabelle"]
    verweigert = ARCHIVE_UNDO_REFUSED if tabelle == "startarchiv" else REFERENCE_UNDO_REFUSED
    try:
        with _db() as conn:
            nola_db.ersetze_tabelle(
                conn, tabelle, pd.DataFrame(letzter["zeilen"], columns=list(_spalten_von(tabelle))),
                letzter["nachher"],
            )
    except nola_db.Konflikt as exc:
        stapel.pop()
        raise UndoRefused(verweigert) from exc
    except nola_db.DbFehler as exc:
        raise UndoRefused(ARCHIVE_UNDO_UNREADABLE if tabelle == "startarchiv" else str(exc)) from exc
    stapel.pop()
    return letzter["label"]


def _melde_db(art: str, text: str) -> None:
    """Meldung fuer den naechsten Durchlauf (Callbacks koennen nicht dauerhaft zeichnen)."""
    st.session_state["db_meldung"] = (art, text)


def _write_reference(
    tabelle: str, df: pd.DataFrame, columns: Sequence[str], label: str, vorher: pd.DataFrame
) -> None:
    """Schreibt die Tabelle mit Vergleich gegen den gelesenen Stand und merkt das Undo."""
    try:
        with _db() as conn:
            neu = nola_db.ersetze_tabelle(conn, tabelle, df[list(columns)], vorher.attrs.get("nola_stand"))
    except nola_db.Konflikt:
        _melde_db("warning", nola_db.KONFLIKT_TEXT)
        return
    except nola_db.DbFehler as exc:
        _melde_db("error", str(exc))
        return
    _push_undo(tabelle, vorher, neu, label)
    st.session_state["ref_flash"] = label
```

`vorher.attrs.get("nola_stand")` darf nicht `None` sein — `referenz_lesen` setzt ihn immer. Ist
er doch `None`, wäre der Vergleich abgeschaltet; deshalb am Anfang von `_write_reference`:

```python
    if not vorher.attrs.get("nola_stand"):
        raise ValueError("_write_reference needs the table as read by referenz_lesen (attrs['nola_stand'])")
```

`_remove_reference_row` / `_add_reference_row`: erster Parameter `tabelle: str` statt `path`; im
Label `path.name` → `tabelle`; Aufruf `_write_reference(tabelle, rest, columns, label, vorher=df)`.
Die sechs Aufrufe in den Editoren: `SPACEPORT_CSV` → `"startplaetze"`, `FIR_CSV` → `"firs"`,
`VEHICLE_CSV` → `"traegersysteme"`. Die Editoren bekommen ihre Tabelle weiterhin aus `main()`
(die von `_reference_status` geladene, mit `attrs`).

Entschärfen in den drei Editoren: jeder `str(r["…"])`-Wert in `_reference_row(...)` wird
`_md_plain(str(r["…"]))`; der Code-Wert bleibt in Backticks: `"`{}`".format(code)` ist
Inline-Code und wird nicht entschärft (Backticks im Wert werden vorher mit
`code.replace("`", "'")` ersetzt).

Die Zeile in `_options_dialog` (o. ä., über `grep -n "SPACEPORT_CSV.name, FIR_CSV.name" app.py`
finden), die Dateinamen nennt, nennt künftig `"nola.db"`.

Meldung anzeigen: Ganz oben in `main()` direkt nach `_render_header()`:

```python
    meldung = st.session_state.pop("db_meldung", None)
    if meldung:
        (st.warning if meldung[0] == "warning" else st.error)(meldung[1])
```

`archiv_import.detection_stamp`:

```python
def detection_stamp(
    paths: Sequence[Path] = (app.APP_DIR / "app.py", app.APP_DIR / "archiv_import.py"),
    db: Optional[Path] = None,
) -> str:
    """
    Erkennungsstand: aendert sich mit der Pipeline, mit diesem Modul
    (Buendelung, Kandidatenbildung) oder einer ihrer Referenzen (in der Datenbank).
    """
    h = hashlib.sha256()
    for path in paths:
        h.update(path.name.encode("utf-8"))
        h.update(path.read_bytes() if path.exists() else b"-")
    for tabelle in ("startplaetze", "firs", "traegersysteme"):
        h.update(tabelle.encode("utf-8"))
        try:
            h.update(app.referenz_lesen(tabelle, db).attrs["nola_stand"].encode("utf-8"))
        except Exception:
            h.update(b"-")
    return h.hexdigest()[:16]
```

- [ ] **Step 5: Bestehende Prüfungen anpassen**

```bash
grep -nE "_push_undo|_undo_reference|_write_reference|_remove_reference_row|_add_reference_row|_reference_status|detection_stamp|SPACEPORT_CSV.name, FIR_CSV.name" test_app.py
```

Jede Fundstelle auf die neue Signatur umschreiben (Tabellenname statt Pfad, Temp-DB aus dem
Testkopf), Aussage gleich. Prüfungen auf `persist_reference(<temp-csv>, …)` (Zeilen um
„persist_reference(sp_datei“) bleiben unverändert — der Datei-Schreiber bleibt für den Export.

- [ ] **Step 6: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1 && .venv/bin/python test_app.py | grep -c "^  PASS"`
Expected: beide bestanden, PASS ≥ Ausgangswert.

- [ ] **Step 7: Commit (nur mit Erlaubnis)**

```bash
git add app.py archiv_import.py test_app.py
git commit -m "Lokale Datenbank Aufgabe 5: Referenzen aus der Datenbank, Undo einheitlich (<task-id>)"
```

---

### Task 6: Arbeitsstand je Durchlauf aus der Datenbank, Abgleich in `_persist_workspace`

**Files:**
- Modify: `app.py` — `main()` (Block `if not st.session_state.get("workspace_loaded"):`),
  `_persist_workspace`, `_remove_manual`, `_render_pasted_entries`, `_clear_manual`
- Modify: `test_app.py`

**Interfaces:**
- Consumes: `nola_db.lade_arbeitsstand`, `schreibe_unterschiede`, `ENTSCHEIDUNGS_SCHLUESSEL`, `ZUWEISUNGS_SCHLUESSEL`; `_db`, `_melde_db`.
- Produces:
  - `WORKSPACE_KEYS: Tuple[str, ...]` (die zehn `session_state`-Schlüssel des Arbeitsstands)
  - `_arbeitsstand_laden() -> None` (füllt `session_state` und `"_ws_momentaufnahme"`)
  - `_remove_manual(notam_id: int) -> None`

**Acceptance Criteria:**
- `main()` füllt bei **jedem** Durchlauf `session_state` aus der Datenbank (kein `workspace_loaded`-Schalter mehr).
- Jede Aktionsfunktion (`_confirm_launch`, `_reject_launch`, `_reset_decision`, `_revoke_launch`,
  `_hide_event`, `_unhide_event`, `_unhide_all`, `_set_vehicle`, `_set_payload`,
  `_set_launch_site`, `_add_manual_notams`, `_remove_manual`, `_clear_manual`) schreibt ihre
  Änderung in die Datenbank (Regeltest).
- Konflikt in `_persist_workspace` → `db_meldung` mit `KONFLIKT_TEXT`, nichts geschrieben,
  `session_state` danach = Datenbank.
- „Remove“ bei eingefügten NOTAMs nutzt die `id` (Schlüssel `del_manual_<id>`, `args=(id,)`).
- `test_app.py` grün, PASS ≥ Ausgangswert.

- [ ] **Step 1: Failing tests anfügen**

```python
print("== Lokale Datenbank: Arbeitsstand ==")
_st_orig_w = app.st
class _StW(_StR):
    pass
app.st = _StW()
try:
    app._arbeitsstand_laden()
    _basis = app.st.session_state["_ws_momentaufnahme"]
    check("Momentaufnahme vorhanden", set(app.WORKSPACE_KEYS) <= set(_basis))
    def _db_stand():
        with app._db() as _c:
            return _ndb.lade_arbeitsstand(_c)
    _faelle = [
        ("_confirm_launch", ("rk1",), lambda s: "rk1" in s["confirmed_launches"]),
        ("_reject_launch", ("rk2",), lambda s: "rk2" in s["rejected_launches"]),
        ("_hide_event", ("rk3",), lambda s: "rk3" in s["hidden_events"]),
        ("_unhide_event", ("rk3",), lambda s: "rk3" not in s["hidden_events"]),
        ("_reset_decision", ("rk2",), lambda s: "rk2" not in s["rejected_launches"]),
        ("_revoke_launch", ("rk1",), lambda s: "rk1" not in s["confirmed_launches"]),
    ]
    for _fn, _args, _pruef in _faelle:
        app._arbeitsstand_laden()
        getattr(app, _fn)(*_args)
        check("Regel: {} schreibt in die DB".format(_fn), _pruef(_db_stand()))
    app._arbeitsstand_laden()
    app.st.session_state["manual_input"] = "A1111/26 NOTAMN\nQ) ZJSA/QRTCA/IV/BO/W/000/999\nE) TEST"
    app._add_manual_notams()
    _m = _db_stand()["manual_notams"]
    check("Regel: _add_manual_notams schreibt in die DB", any("A1111/26" in n["text"] for n in _m))
    app._arbeitsstand_laden()
    _id = [n["id"] for n in app.st.session_state["manual_notams"] if "A1111/26" in n["text"]][0]
    app._remove_manual(_id)
    check("Regel: _remove_manual(id) schreibt in die DB", all(n["id"] != _id for n in _db_stand()["manual_notams"]))
    app._arbeitsstand_laden(); app._hide_event("rk4"); app._arbeitsstand_laden(); app._unhide_all()
    check("Regel: _unhide_all schreibt in die DB", _db_stand()["hidden_events"] == set())
    app._arbeitsstand_laden(); app._clear_manual()
    check("Regel: _clear_manual schreibt in die DB", _db_stand()["manual_notams"] == [])
    for _fn, _feld, _wkey in [("_set_vehicle", "vehicle_assignments", "wv"),
                              ("_set_payload", "payload_assignments", "wp"),
                              ("_set_launch_site", "launch_site_assignments", "wl")]:
        app._arbeitsstand_laden()
        app.st.session_state[_wkey] = "CZ-2D" if _fn == "_set_vehicle" else ("Yaogan" if _fn == "_set_payload" else "JSLC")
        getattr(app, _fn)(_wkey, ["ek1"])
        check("Regel: {} schreibt in die DB".format(_fn), _db_stand()[_feld].get("ek1") == app.st.session_state[_wkey])
    # Konflikt
    app._arbeitsstand_laden()
    with app._db() as _c:
        _c.execute("INSERT INTO entscheidungen VALUES ('rk9', 'ausgeblendet', 'x')")
    app._confirm_launch("rk9")
    check("Konflikt gemeldet", app.st.session_state.get("db_meldung", ("", ""))[1] == _ndb.KONFLIKT_TEXT)
    check("Konflikt: nichts geschrieben", "rk9" not in _db_stand()["confirmed_launches"])
    check("session_state danach = DB", app.st.session_state["hidden_events"] == _db_stand()["hidden_events"])
finally:
    app.st = _st_orig_w
import inspect as _ins_w
_main_q = _ins_w.getsource(app.main)
check("kein workspace_loaded-Schalter mehr", "workspace_loaded" not in _main_q and "_arbeitsstand_laden()" in _main_q)
```

Falls eine Aktionsfunktion für `_set_*` einen anderen gültigen Widget-Wert erwartet (z. B. muss
`_set_vehicle` einen Code aus der Referenz bekommen), den Wert aus `app.referenz_lesen("traegersysteme")["Abkürzung"].iloc[0]`
nehmen — die Prüfung „schreibt in die DB“ bleibt.

- [ ] **Step 2: Laufen lassen, scheitert**

Run: `.venv/bin/python test_app.py | grep -E "FAIL|Error" | head`
Expected: `AttributeError: module 'app' has no attribute '_arbeitsstand_laden'`

- [ ] **Step 3: Implementieren**

```python
import copy  # (zu den Importen)

WORKSPACE_KEYS = ("manual_notams",) + tuple(nola_db.ENTSCHEIDUNGS_SCHLUESSEL) + tuple(
    nola_db.ZUWEISUNGS_SCHLUESSEL
)


def _arbeitsstand_laden() -> None:
    """
    Fuellt den Arbeitsstand im session_state aus der Datenbank - in jedem
    Durchlauf, damit Aenderungen anderer Tabs und externer Werkzeuge beim
    naechsten Klick sichtbar sind. Die Momentaufnahme ist der Stand, den der
    Benutzer gerade sieht; _persist_workspace schreibt nur Abweichungen davon.
    """
    with _db() as conn:
        stand = nola_db.lade_arbeitsstand(conn)
    stand["archiv_removed"] = migrate_archive_keys(stand["archiv_removed"])
    for k in WORKSPACE_KEYS:
        st.session_state[k] = copy.deepcopy(stand[k])
    st.session_state["_ws_momentaufnahme"] = copy.deepcopy(stand)


def _persist_workspace() -> None:
    """
    Schreibt die Aenderungen am Arbeitsstand seit der Momentaufnahme. Hat
    jemand anderes dieselben Eintraege inzwischen geaendert, wird nichts
    geschrieben und die Ansicht neu geladen.
    """
    vorher = st.session_state.get("_ws_momentaufnahme") or nola_db.leerer_arbeitsstand()
    aktuell = {k: st.session_state.get(k, vorher.get(k)) for k in WORKSPACE_KEYS}
    try:
        with _db() as conn:
            nola_db.schreibe_unterschiede(
                conn, vorher, aktuell, datetime.now(timezone.utc).isoformat()
            )
    except nola_db.Konflikt:
        _melde_db("warning", nola_db.KONFLIKT_TEXT)
    except nola_db.DbFehler as exc:
        _melde_db("error", "Not saved: {}".format(exc))
    # In jedem Fall den echten Stand zeigen (neue NOTAMs bekommen ihre id).
    try:
        _arbeitsstand_laden()
    except nola_db.DbFehler as exc:
        _melde_db("error", str(exc))
```

`_remove_manual`:

```python
def _remove_manual(notam_id: int) -> None:
    """Entfernt einen einzelnen manuellen Eintrag - ueber seine Datenbank-id, nie ueber die Position."""
    st.session_state["manual_notams"] = [
        e for e in st.session_state.get("manual_notams", []) if e.get("id") != notam_id
    ]
    st.session_state["manual_feedback"] = None
    _persist_workspace()
```

In `_render_pasted_entries` der Knopf:

```python
                st.button(
                    "Remove",
                    key="del_manual_{}".format(entry.get("id")),
                    on_click=_remove_manual,
                    args=(entry.get("id"),),
                    use_container_width=True,
                )
```

Docstring-Satz „"Remove" bekommt immer den urspruenglichen Index …“ wird „"Remove" bekommt die
Datenbank-id des Eintrags - die Anzeige-Reihenfolge spielt dafuer keine Rolle.“

In `main()`: den Block `if not st.session_state.get("workspace_loaded"): …` samt
`st.session_state["workspace_loaded"] = True` durch `_arbeitsstand_laden()` ersetzen; die
`setdefault`-Zeilen für die zehn Arbeitsstand-Schlüssel entfallen (die übrigen `setdefault`s bleiben).
`_arbeitsstand_laden()` steht vor jeder Verwendung von `manual_notams` usw. in `main()`.

- [ ] **Step 4: Bestehende Prüfungen anpassen**

```bash
grep -nE "save_workspace wird benannt|del_manual_|_render_pasted_entries\(_stub|workspace_loaded" test_app.py
```

- „save_workspace wird benannt aufgerufen - nicht nach Position“: prüft künftig, dass
  `_persist_workspace` `nola_db.schreibe_unterschiede(` mit `vorher, aktuell` aufruft und keine
  Position-Argumente an `save_workspace` übergibt (`"save_workspace(" not in getsource(_persist_workspace)`).
- `_render_pasted_entries` mit Stub: Testeinträge bekommen `id`s (z. B. 11, 10, 12 in der Reihenfolge
  der Einträge); erwartet werden `("del_manual_10", (10,))` usw. in derselben Anzeige-Reihenfolge wie bisher.
- Prüfungen von `save_workspace`/`load_workspace` auf Temp-Dateien bleiben (Datei-Format für Export).

- [ ] **Step 5: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1 && .venv/bin/python test_app.py | grep -c "^  PASS"`
Expected: beide bestanden, PASS ≥ Ausgangswert.

- [ ] **Step 6: Commit (nur mit Erlaubnis)**

```bash
git add app.py test_app.py
git commit -m "Lokale Datenbank Aufgabe 6: Arbeitsstand je Durchlauf, Abgleich mit Konfliktschutz (<task-id>)"
```

---

### Task 7: Startarchiv und Seestarts über die Datenbank (App und Archiv-Import)

**Files:**
- Modify: `app.py` — `_update_archive`, `_update_sea_launches`, `_remove_archive_row`,
  `_remove_sea_launch_row`, `_sea_launch_editor`, Archiv-Editor (über
  `grep -n "archiv = read_archive_strict(ARCHIVE_CSV)" app.py`), Archiv-Zählung in der Seitenleiste,
  alle Aufrufe `read_archive_strict(ARCHIVE_CSV)`, `load_archive(ARCHIVE_CSV)`,
  `archive_keys_or_reason(ARCHIVE_CSV)`, `load_sea_launches(SEA_LAUNCH_CSV)`, `persist_archive(ARCHIVE_CSV, …)`,
  `persist_sea_launches(SEA_LAUNCH_CSV, …)`; Archiv-Import-Reiter (`ai.load_korpus()`,
  `ai.load_state()`, `ai.save_korpus(…)`, `ai.save_state(…)`)
- Modify: `archiv_import.py` — `_archiv_lesen`, `remove_orphan`, `candidates`, `confirm_many` und
  jede Funktion mit Parameter `archiv: Path = app.ARCHIVE_CSV`; neue Korpus/Zustand-Funktionen
- Modify: `test_app.py`

**Interfaces:**
- Consumes: Task 5 (`_db`, `_push_undo`, `_melde_db`), Task 6 (`_persist_workspace` schreibt in die Datenbank — Voraussetzung, damit `_remove_archive_row`/`_remove_sea_launch_row` in Tests keine Projektdatei berühren), `nola_db.lese_tabelle`/`ersetze_tabelle`/`Konflikt`/`DbFehler`.
- Produces (in `app.py`):
  - `archiv_lesen(db: Optional[Path] = None) -> DataFrame` (wirft `ArchiveUnreadable` bei `DbFehler`)
  - `archiv_anzeigen(db=None) -> DataFrame` (bei Fehler leer, wie `load_archive`)
  - `archiv_schluessel_oder_grund(db=None) -> Tuple[Optional[Set[str]], str]`
  - `archiv_schreiben(neu: DataFrame, vorher: DataFrame, db: Optional[Path] = None) -> str` (wirft `nola_db.Konflikt`, `nola_db.DbFehler`)
  - `seestarts_lesen(db=None) -> DataFrame` (Form wie `load_sea_launches`: alle Spalten str, leer = `""`; `attrs` erhalten)
  - `seestarts_schreiben(neu, vorher, db=None) -> str`
- Produces (in `archiv_import.py`): `korpus_laden(db=None)`, `korpus_speichern(korpus, db=None)`,
  `zustand_laden(db=None)`, `zustand_speichern(state, db=None)`; alle `archiv`-Parameter heißen
  weiter `archiv`, sind aber `Optional[Path] = None` und bedeuten den Datenbankpfad.

**Acceptance Criteria:**
- `_update_archive` schreibt neue Starts in die Datenbank; zwei Läufe mit derselben veralteten
  Ausgangslage ergeben genau eine Zeile (Konflikt → einmal neu lesen, erneut zusammenführen).
- DB-Lesefehler beim Fortschreiben → `st.warning`, nichts geschrieben, Auswertung läuft weiter.
- Archivzeile entfernen → Zeile weg, Schlüssel in `archiv_removed`, Undo stellt sie wieder her;
  Undo nach Tageslauf-Änderung → `UndoRefused(ARCHIVE_UNDO_REFUSED)`.
- Seestart entfernen und automatisches Fortschreiben entsprechend.
- Archiv-Import: `confirm_many`/`remove_orphan` schreiben in die Datenbank; ändert sich das Archiv
  zwischen Lesen und Schreiben, wird `ImportStateError` mit Konflikthinweis geworfen und nichts
  geschrieben; Korpus und Zustand überleben `korpus_speichern`/`zustand_laden` unverändert.
- Keine Fundstelle mehr für `persist_archive(ARCHIVE_CSV`, `persist_sea_launches(SEA_LAUNCH_CSV`,
  `read_archive_strict(ARCHIVE_CSV`, `load_archive(ARCHIVE_CSV`, `load_sea_launches(SEA_LAUNCH_CSV`
  in `app.py` außerhalb von `nola_umzug.py`.
- `test_app.py` grün, PASS ≥ Ausgangswert.

- [ ] **Step 1: Failing tests am Ende von `test_app.py` anfügen**

```python
print("== Lokale Datenbank: Archiv und Seestarts ==")
import pandas as _pd_a
_st_orig_a = app.st; app.st = _StR()
try:
    _a0 = app.archiv_lesen()
    check("Archiv aus DB mit Stand", "nola_stand" in _a0.attrs)
    _zeile = {s: "" for s in app.ARCHIVE_COLUMNS}
    _zeile.update({"NOTAM": "Z9999/26", "Startdatum": "07.10.2026", "Startzeit": "01:00", "Nation": "China"})
    _neu_a = app.merge_archive(_a0, [_zeile], set())
    app.archiv_schreiben(_neu_a, vorher=_a0)
    check("geschrieben", "Z9999/26" in set(app.archiv_lesen()["NOTAM"]))
    try:
        app.archiv_schreiben(_neu_a, vorher=_a0); check("veraltete Vorlage -> Konflikt", False)
    except _ndb.Konflikt:
        check("veraltete Vorlage -> Konflikt", True)
    _vor_rm = app.archiv_lesen()
    app._remove_archive_row(app.archive_key(_zeile))
    check("Zeile entfernt", "Z9999/26" not in set(app.archiv_lesen()["NOTAM"]))
    check("Schluessel gemerkt", app.archive_key(_zeile) in app.st.session_state.get("archiv_removed", set()))
    app._undo_reference()
    check("Undo stellt Zeile wieder her", "Z9999/26" in set(app.archiv_lesen()["NOTAM"]))
    # Undo verweigert, wenn das Archiv sich danach geaendert hat
    app._remove_archive_row(app.archive_key(_zeile))
    _jetzt = app.archiv_lesen()
    _z2 = dict(_zeile); _z2["NOTAM"] = "Z9998/26"
    app.archiv_schreiben(app.merge_archive(_jetzt, [_z2], set()), vorher=_jetzt)
    try:
        app._undo_reference(); check("Archiv-Undo nach Aenderung verweigert", False)
    except app.UndoRefused as e:
        check("Archiv-Undo nach Aenderung verweigert", str(e) == app.ARCHIVE_UNDO_REFUSED)
    # DB-Lesefehler beim Fortschreiben -> Warnung, kein Abbruch
    _db_echt = app.DB_PATH
    app.DB_PATH = _P_db(_tf_db.mkdtemp()) / "fehlt.db"
    try:
        _wk = len(app.st.session_state.get("_w", []))
        _tab = _pd_a.DataFrame({"Status": ["OK"], "_row": [0]})
        class _G: spaceport_code = "JSLC"; row_indices = [0]
        app._update_archive([], [_G()], _tab)
        check("Lesefehler -> Warnung", len(app.st.session_state.get("_w", [])) == _wk + 1)
    finally:
        app.DB_PATH = _db_echt
    _s0 = app.seestarts_lesen()
    _s0b = _s0.copy(); _s0b.attrs = {}
    check("Seestarts aus DB = load_sea_launches(CSV)", _s0b.reset_index(drop=True).equals(
        app.load_sea_launches(app.SEA_LAUNCH_CSV).reset_index(drop=True)))
    check("Seestarts aus DB, Text-Spalten", all(_s0[c].map(lambda v: isinstance(v, str)).all() for c in _s0.columns))
finally:
    app.st = _st_orig_a
check("app.py schreibt keine Archiv-CSV mehr",
      "persist_archive(ARCHIVE_CSV" not in open(app.__file__, encoding="utf-8").read()
      and "persist_sea_launches(SEA_LAUNCH_CSV" not in open(app.__file__, encoding="utf-8").read())
```

- [ ] **Step 2: Laufen lassen, scheitert**

Run: `.venv/bin/python test_app.py | grep -E "FAIL|Error" | head`
Expected: `AttributeError: module 'app' has no attribute 'archiv_lesen'`

- [ ] **Step 3: Wrapper in `app.py` (nach `persist_archive`)**

```python
def archiv_lesen(db: Optional[Path] = None) -> pd.DataFrame:
    """
    Startarchiv aus der Datenbank fuer jeden Schreibvorgang. Ein Lesefehler wird
    ArchiveUnreadable - so greifen alle bestehenden Schutzpfade unveraendert.
    """
    try:
        with _db(db) as conn:
            return nola_db.lese_tabelle(conn, "startarchiv")
    except nola_db.DbFehler as exc:
        raise ArchiveUnreadable(
            "The launch archive could not be read from the database ({}). It was left "
            "untouched and not updated.".format(exc)
        ) from exc


def archiv_anzeigen(db: Optional[Path] = None) -> pd.DataFrame:
    """Fuer Anzeige und Zaehlung; bei Fehler leer (wie load_archive)."""
    try:
        return archiv_lesen(db)
    except ArchiveUnreadable:
        return pd.DataFrame(columns=list(ARCHIVE_COLUMNS))


def archiv_schluessel_oder_grund(db: Optional[Path] = None) -> Tuple[Optional[Set[str]], str]:
    try:
        bestand = archiv_lesen(db)
    except ArchiveUnreadable as exc:
        return None, str(exc)
    return {archive_key(dict(r)) for _, r in bestand.iterrows()}, ""


def archiv_schreiben(neu: pd.DataFrame, vorher: pd.DataFrame, db: Optional[Path] = None) -> str:
    """Ersetzt das Archiv - nur, wenn es noch dem Stand von `vorher` entspricht."""
    stand = vorher.attrs.get("nola_stand")
    if not stand:
        raise ValueError("archiv_schreiben needs `vorher` as read by archiv_lesen")
    with _db(db) as conn:
        return nola_db.ersetze_tabelle(conn, "startarchiv", neu[list(ARCHIVE_COLUMNS)], stand)


def seestarts_lesen(db: Optional[Path] = None) -> pd.DataFrame:
    """Seestart-Protokoll aus der Datenbank, Form wie load_sea_launches (Text, leer = '')."""
    with _db(db) as conn:
        roh = nola_db.lese_tabelle(conn, "seestarts")
    df = roh.fillna("").astype(str)
    df.attrs["nola_stand"] = roh.attrs["nola_stand"]
    return df


def seestarts_schreiben(neu: pd.DataFrame, vorher: pd.DataFrame, db: Optional[Path] = None) -> str:
    stand = vorher.attrs.get("nola_stand")
    if not stand:
        raise ValueError("seestarts_schreiben needs `vorher` as read by seestarts_lesen")
    with _db(db) as conn:
        return nola_db.ersetze_tabelle(conn, "seestarts", neu[list(SEA_LAUNCH_COLUMNS)], stand)
```

- [ ] **Step 4: Aufrufer umstellen**

`_update_archive` (Ende ab `try: bestand = read_archive_strict(ARCHIVE_CSV)`):

```python
    for _ in range(2):  # bei Konflikt einmal neu lesen und erneut zusammenfuehren
        try:
            bestand = archiv_lesen()
        except ArchiveUnreadable as exc:
            # Nie ueber ein unlesbares Archiv schreiben; die Auswertung laeuft weiter.
            st.warning("Launch archive: {}".format(exc))
            return
        neu = merge_archive(
            bestand,
            [archive_row(g, events) for g in kandidaten],
            set(st.session_state.get("archiv_removed", set())),
        )
        if neu.to_csv(index=False) == bestand.to_csv(index=False):
            return
        try:
            archiv_schreiben(neu, vorher=bestand)
            return
        except nola_db.Konflikt:
            continue
        except nola_db.DbFehler as exc:
            st.warning("Launch archive: not updated ({})".format(exc))
            return
```

`_update_sea_launches` genauso mit `seestarts_lesen`/`seestarts_schreiben`/`merge_sea_launches`
(Lesefehler `nola_db.DbFehler` → `st.warning("Sea launch log: …")`).

`_remove_archive_row(schluessel)`:

```python
def _remove_archive_row(schluessel: str) -> None:
    """
    Loescht eine Archivzeile - dauerhaft.

    Der Schluessel wandert in den Arbeitsstand, sonst legte der naechste Import
    denselben Start sofort wieder an, solange sein NOTAM in der Tagesdatei steht.
    """
    try:
        bestand = archiv_lesen()
    except ArchiveUnreadable as exc:
        st.error("Launch archive: {} Nothing was removed.".format(exc))
        return
    behalten = bestand[[archive_key(dict(r)) != schluessel for _, r in bestand.iterrows()]]
    try:
        neu_stand = archiv_schreiben(behalten, vorher=bestand)
    except nola_db.Konflikt:
        _melde_db("warning", nola_db.KONFLIKT_TEXT)
        return
    except nola_db.DbFehler as exc:
        _melde_db("error", "Launch archive: {} Nothing was removed.".format(exc))
        return
    _push_undo("startarchiv", bestand, neu_stand, "Archivzeile entfernt")
    st.session_state.setdefault("archiv_removed", set()).add(schluessel)
    _persist_workspace()
    st.session_state["ref_flash"] = "Archivzeile entfernt"
```

(Die heutige Fassung über `grep -n "^def _remove_archive_row" app.py` lesen und Label/Flash-Texte
genau übernehmen.)

`_remove_sea_launch_row(schluessel)` entsprechend mit `seestarts_lesen`, Filter
`sea_launch_key(dict(r)) != schluessel`, `seestarts_schreiben`, `_push_undo("seestarts", …,
"Sea launch row removed")`, `seestarts_removed`, `_persist_workspace()`.

Übrige Aufrufer (alle mit `grep -n` finden und ersetzen):
- `load_archive(ARCHIVE_CSV)` → `archiv_anzeigen()`
- `read_archive_strict(ARCHIVE_CSV)` → `archiv_lesen()` (Zählung in der Seitenleiste, Archiv-Editor)
- `archive_keys_or_reason(ARCHIVE_CSV)` → `archiv_schluessel_oder_grund()`
- `load_sea_launches(SEA_LAUNCH_CSV)` → `seestarts_lesen()`
- Hinweistexte mit `ARCHIVE_CSV.name` / `SEA_LAUNCH_CSV.name` → `"the launch archive in nola.db"` bzw.
  `"the sea launch log in nola.db"`.
- In Editoren angezeigte Archiv- und Seestartwerte durch `_md_plain(...)`.

`archiv_import.py`:

```python
def _archiv_lesen(archiv: Optional[Path] = None) -> pd.DataFrame:
    """
    Liest das Startarchiv strikt aus der Datenbank: ein Lesefehler bricht mit
    ImportStateError ab, statt als leeres Archiv zu gelten.
    """
    try:
        return app.archiv_lesen(archiv)
    except app.ArchiveUnreadable as exc:
        raise ImportStateError(str(exc)) from exc


def _archiv_schreiben(archiv: Optional[Path], neu: pd.DataFrame, vorher: pd.DataFrame) -> None:
    try:
        app.archiv_schreiben(neu, vorher=vorher, db=archiv)
    except app.nola_db.Konflikt as exc:
        raise ImportStateError(
            "The launch archive changed meanwhile - nothing was written, please reload the tab."
        ) from exc
    except app.nola_db.DbFehler as exc:
        raise ImportStateError("The launch archive was not written ({}).".format(exc)) from exc
```

In `remove_orphan`: `bestand = _archiv_lesen(archiv)`; der gefilterte Bestand wird
`_archiv_schreiben(archiv, gefiltert, vorher=bestand)` statt `app.persist_archive(archiv, bestand)`.
In `confirm_many`: `app.persist_archive(archiv, app.merge_archive(bestand, zeilen, entfernt=set()))`
→ `_archiv_schreiben(archiv, app.merge_archive(bestand, zeilen, entfernt=set()), vorher=bestand)` —
dabei muss `bestand` das **ungefilterte** Ergebnis von `_archiv_lesen` sein; wird es vorher gefiltert
(`bestand = bestand[...]`), das Original vorher in `gelesen = bestand` sichern und `vorher=gelesen`
übergeben. Alle Signaturen `archiv: Path = app.ARCHIVE_CSV` → `archiv: Optional[Path] = None`.
`_archiv_pruefen` bleibt (liest über `_archiv_lesen`).

Korpus/Zustand:

```python
def korpus_laden(db: Optional[Path] = None) -> Dict[str, KorpusNotam]:
    try:
        with app._db(db) as conn:
            eintraege = app.nola_db.lade_korpus(conn)
    except app.nola_db.DbFehler as exc:
        raise ImportStateError("The archive corpus could not be read ({}).".format(exc)) from exc
    return korpus_aus_daten({"notams": eintraege}, "archiv_korpus (nola.db)")


def korpus_speichern(korpus: Dict[str, KorpusNotam], db: Optional[Path] = None) -> None:
    try:
        with app._db(db) as conn:
            app.nola_db.speichere_korpus(conn, [
                (n.schluessel, {"notam_id": n.notam_id, "b": n.b, "text": n.text, "quellen": n.quellen})
                for n in sorted(korpus.values(), key=lambda n: n.schluessel)])
    except app.nola_db.DbFehler as exc:
        raise ImportStateError("The archive corpus was not saved ({}).".format(exc)) from exc


def zustand_laden(db: Optional[Path] = None) -> Dict[str, Any]:
    try:
        with app._db(db) as conn:
            roh = app.nola_db.lade_importzustand(conn)
    except app.nola_db.DbFehler as exc:
        raise ImportStateError("The import state could not be read ({}).".format(exc)) from exc
    return zustand_aus_daten(roh, "archiv_import (nola.db)")


def zustand_speichern(state: Dict[str, Any], db: Optional[Path] = None) -> None:
    try:
        with app._db(db) as conn:
            app.nola_db.speichere_importzustand(conn, state)
    except app.nola_db.DbFehler as exc:
        raise ImportStateError("The import state was not saved ({}).".format(exc)) from exc
```

Im Archiv-Import-Reiter von `app.py`: `ai.load_korpus()` → `ai.korpus_laden()`, `ai.load_state()`
→ `ai.zustand_laden()`, `ai.save_korpus(korpus)` → `ai.korpus_speichern(korpus)`,
`ai.save_state(zustand)` → `ai.zustand_speichern(zustand)` (alle Fundstellen).

- [ ] **Step 5: Bestehende Prüfungen anpassen**

```bash
grep -nE "archiv_t|archiv=|app\.ARCHIVE_CSV *=|persist_archive *=|_update_archive|_remove_archive_row|_remove_sea_launch_row|pad_historie = load_archive|load_archive\(ARCHIVE_CSV|ai\.(load|save)_(korpus|state)\(\)" test_app.py
```

- Prüfungen des Archiv-Imports, die eine Temp-CSV `archiv_t` anlegen und an `candidates`/
  `confirm_many`/`remove_orphan` übergeben: stattdessen eine Temp-Datenbank anlegen
  (`_t = _P_db(_tf_db.mkdtemp()) / "nola.db"; _um_db.umziehen(_t, _um_db.altdateien_im(<ordner mit der Temp-CSV als startarchiv_updated.csv>))`)
  und `_t` übergeben; Lesen über `app.archiv_anzeigen(_t)` statt `app.load_archive(archiv_t)`.
- Die Prüfung, die `app.persist_archive = lambda path, df: None` setzt (geschluckter Schreibfehler),
  ersetzt stattdessen `app.archiv_schreiben = lambda neu, vorher, db=None: "x"` — die Aussage
  („`_archiv_pruefen` erkennt, dass nichts angekommen ist“) bleibt.
- Die Prüfung `pad_historie = load_archive(ARCHIVE_CSV)` zählt künftig `pad_historie = archiv_anzeigen()`.
- Prüfungen mit `app.ARCHIVE_CSV = _kaputt_u` für `_update_archive`: Unlesbarkeit über
  `app.DB_PATH = <fehlende Datei>` herstellen (wie im neuen Test), Aussagen gleich.
- Prüfungen von `read_archive_strict`/`load_archive`/`persist_archive` auf Temp-CSV-Dateien bleiben
  unverändert (Datei-Leser für Umzug und Export).

- [ ] **Step 6: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1 && .venv/bin/python test_app.py | grep -c "^  PASS"`
Expected: beide bestanden, PASS ≥ Ausgangswert.

- [ ] **Step 7: Commit (nur mit Erlaubnis)**

```bash
git add app.py archiv_import.py test_app.py
git commit -m "Lokale Datenbank Aufgabe 7: Archiv und Seestarts aus der Datenbank (<task-id>)"
```

---

### Task 8: Start, Sicherung, Wiederherstellen, Export und Netz-Hinweis in der App

**Files:**
- Modify: `app.py` — `main()` (Anfang), Optionsdialog (Export-Knopf), neue Funktionen
- Modify: `.claude/launch.json` (lokal, nicht im Git)
- Modify: `test_app.py`

**Interfaces:**
- Consumes: `nola_umzug.stelle_bereit`, `altdateien_im`, `exportieren`, `Startzustand`;
  `nola_db.sichere`, `sicherung_faellig`, `liste_sicherungen`, `pruefe_sicherung`,
  `stelle_wieder_her`, `DateiFehlt`, `DbFehler`; `archive_import_allowed`, `is_public_deployment`.
- Produces:
  - `local_admin_allowed() -> bool` (= `archive_import_allowed()`; gleiche Freigabe)
  - `_datenbank_bereit() -> Tuple[nola_umzug.Startzustand, str]` (`@st.cache_resource`; zweiter Wert: Warnung der Startsicherung oder `""`)
  - `_wiederherstellen_auswahl() -> None` (zeigt Wahl, endet mit `st.stop()`)
  - `_taegliche_sicherung() -> Optional[str]` (Warnung oder `None`)
  - `server_address_is_loopback(adresse: Optional[str]) -> bool`
  - `_export_knopf() -> None`

**Acceptance Criteria:**
- `stelle_bereit` läuft einmal je Prozess; `fehlgeschlagen` → `st.error(grund)` + `st.stop()`.
- Übergangssperre: fehlt `nola.db` lokal und ist `NOLA_DB` nicht `1`, wird nicht umgezogen
  (Meldung „Database not enabled yet …“); in der Cloud gilt die Sperre nicht.
- `fehlt_mit_sicherungen` → nur lokal: Liste der Sicherungen (Datum, Zeilenzahlen, defekte und
  „in iCloud only“ markiert und nicht wählbar,
  vorausgewählt die jüngste heile), „Restore backup“, „Rebuild from old files“; nicht lokal →
  `st.error` + `st.stop()`, keine Knöpfe.
- Verschwindet `nola.db` im Betrieb (`DateiFehlt`), wird der Cache geleert und neu entschieden —
  es entsteht keine leere Datei.
- Tägliche Sicherung beim ersten Durchlauf eines neuen Tages; Fehler → Warnung in der Seitenleiste.
- „Export to files“ nur lokal; schreibt nach `export/JJJJ-MM-TT-HHMM/` und meldet den Pfad.
- Lokal mit `server.address` ≠ Loopback → Warnung in der Seitenleiste; unter `/mount/src` nie.
- `server_address_is_loopback`: `127.0.0.1`, `localhost`, `::1` → `True`; `None`, `""`, `0.0.0.0`, LAN-IP → `False`.
- `.claude/launch.json` startet mit `--server.address 127.0.0.1`.

- [ ] **Step 1: Failing tests anfügen**

```python
print("== Lokale Datenbank: Start und Sicherheit ==")
check("Loopback-Adressen", all(app.server_address_is_loopback(a) for a in ("127.0.0.1", "localhost", "::1")))
check("keine Loopback-Adressen", not any(app.server_address_is_loopback(a) for a in (None, "", "0.0.0.0", "192.168.1.20")))
check("Admin-Freigabe = Import-Freigabe", app.local_admin_allowed() == app.archive_import_allowed())
_src_main = _ins_w.getsource(app.main)
check("main nutzt _datenbank_bereit", "_datenbank_bereit()" in _src_main)
check("main behandelt DateiFehlt", "DateiFehlt" in _src_main and "_datenbank_bereit.clear()" in _src_main)
check("Wiederherstellen nur lokal", "local_admin_allowed()" in _ins_w.getsource(app._wiederherstellen_auswahl))
check("Export nur lokal", "local_admin_allowed()" in _ins_w.getsource(app._export_knopf))
check("Uebergangssperre NOLA_DB", "NOLA_DB" in _ins_w.getsource(app._datenbank_bereit))
check("Netz-Hinweis nicht in der Cloud", "is_public_deployment()" in _src_main and "server_address_is_loopback(" in _src_main)
import json as _json_l
_launch = app.APP_DIR / ".claude" / "launch.json"
if _launch.exists():
    _args = _json_l.loads(_launch.read_text(encoding="utf-8"))["configurations"][0]["runtimeArgs"]
    check("launch.json bindet an 127.0.0.1", "--server.address" in _args
          and _args[_args.index("--server.address") + 1] == "127.0.0.1")
else:
    print("  SKIP  launch.json (nicht vorhanden)")
```

- [ ] **Step 2: Laufen lassen, scheitert**

Run: `.venv/bin/python test_app.py | grep -E "FAIL|Error" | head`
Expected: `AttributeError: module 'app' has no attribute 'server_address_is_loopback'`

- [ ] **Step 3: Implementieren**

```python
def local_admin_allowed() -> bool:
    """Speicher-Aktionen (Wiederherstellen, Neuaufbau, Export): gleiche Freigabe wie der Archiv-Import."""
    return archive_import_allowed()


def server_address_is_loopback(adresse: Optional[str]) -> bool:
    return (adresse or "").strip().lower() in ("127.0.0.1", "localhost", "::1")


@st.cache_resource(show_spinner="Preparing the database ...")
def _datenbank_bereit() -> Tuple["nola_umzug.Startzustand", str]:
    """Einmal je Serverprozess: pruefen, umziehen oder zur Wahl stellen; dann Startsicherung."""
    import nola_umzug  # erst hier - nola_umzug importiert app
    if not DB_PATH.exists() and not is_public_deployment() and os.environ.get("NOLA_DB") != "1":
        # Uebergangssperre bis Aufgabe 9: keine halbfertige Datenbank anlegen.
        return nola_umzug.Startzustand(
            "fehlgeschlagen", grund="Database not enabled yet \u2013 set NOLA_DB=1 to move the data."
        ), ""
    jetzt = datetime.now()
    zustand = nola_umzug.stelle_bereit(DB_PATH, nola_umzug.altdateien_im(APP_DIR), BACKUP_DIR, jetzt)
    warnung = ""
    if zustand.art in ("bereit", "umgezogen") and not is_public_deployment():
        try:
            with _db() as conn:
                nola_db.sichere(conn, BACKUP_DIR, jetzt)
        except nola_db.DbFehler as exc:
            warnung = "Backup at start failed: {}".format(exc)
    return zustand, warnung


def _taegliche_sicherung() -> Optional[str]:
    if is_public_deployment() or not nola_db.sicherung_faellig(BACKUP_DIR, datetime.now().date()):
        return None
    try:
        with _db() as conn:
            nola_db.sichere(conn, BACKUP_DIR, datetime.now())
    except nola_db.DbFehler as exc:
        return "Daily backup failed: {}".format(exc)
    return None


def _wiederherstellen_auswahl() -> None:
    """nola.db fehlt, Sicherungen gibt es: nichts still neu aufbauen - der Benutzer waehlt."""
    import nola_umzug
    st.error("The database nola.db is missing. NOLA does not rebuild it silently.")
    if not local_admin_allowed():
        st.info("Restore is only possible on the local machine (http://localhost:8501).")
        st.stop()
    sicherungen = nola_db.liste_sicherungen(BACKUP_DIR)
    zeilen = [(p,) + nola_db.pruefe_sicherung(p) for p in sicherungen]
    heil = [i for i, (_, status, _z) in enumerate(zeilen) if status == "ok"]

    def beschriftung(i: int) -> str:
        p, status, z = zeilen[i]
        if status == "in_cloud":
            return "{} - in iCloud only, download it in Finder first".format(p.name)
        if status != "ok":
            return "{} - corrupt".format(p.name)
        return "{} - {} archive rows, {} launch sites, {} pasted NOTAMs".format(
            p.name, z["startarchiv"], z["startplaetze"], z["manuelle_notams"])

    wahl = st.radio("Backups", list(range(len(zeilen))), index=heil[0] if heil else 0,
                    format_func=beschriftung)
    a, b = st.columns(2)
    if a.button("Restore backup", type="primary", disabled=zeilen[wahl][1] != "ok"):
        try:
            nola_db.stelle_wieder_her(zeilen[wahl][0], DB_PATH)
        except nola_db.DbFehler as exc:
            st.error(str(exc))
            st.stop()
        _datenbank_bereit.clear()
        st.rerun()
    if b.button("Rebuild from old files"):
        try:
            nola_umzug.umziehen(DB_PATH, nola_umzug.altdateien_im(APP_DIR))
        except nola_umzug.UmzugFehler as exc:
            st.error(str(exc))
            st.stop()
        _datenbank_bereit.clear()
        st.rerun()
    st.stop()


def _export_knopf() -> None:
    """Rueckweg: alle Tabellen in die bisherigen Formate (nur lokal)."""
    if not local_admin_allowed():
        return
    if st.button("Export to files", use_container_width=True,
                 help="Writes all tables in the old CSV/JSON formats to export/<time>/."):
        import nola_umzug
        ziel = APP_DIR / "export" / datetime.now().strftime("%Y-%m-%d-%H%M")
        try:
            nola_umzug.exportieren(DB_PATH, ziel)
        except (nola_db.DbFehler, OSError) as exc:
            st.error("Export failed: {}".format(exc))
        else:
            st.success("Exported to {}".format(ziel))
```

Anfang von `main()` (nach `st.set_page_config(...)`, vor `_arbeitsstand_laden()`):

```python
    zustand, start_warnung = _datenbank_bereit()
    if zustand.art == "fehlgeschlagen":
        st.error(zustand.grund)
        st.stop()
    if zustand.art == "fehlt_mit_sicherungen":
        _wiederherstellen_auswahl()
    try:
        with _db():
            pass
    except nola_db.DateiFehlt:
        # Datei im Betrieb verschwunden - neu entscheiden, nie still leer anlegen.
        _datenbank_bereit.clear()
        st.rerun()
    if zustand.art == "umgezogen" and not st.session_state.get("umzug_gemeldet"):
        st.session_state["umzug_gemeldet"] = True
        st.success("Data moved to nola.db ({}). The old files were left untouched.".format(
            ", ".join("{} {}".format(v, k) for k, v in zustand.zaehlung.items())))
    tages_warnung = _taegliche_sicherung()
```

In der Seitenleiste (direkt nach `kopf.header("Reference Data")`-Block):

```python
        for warnung in (start_warnung, tages_warnung):
            if warnung:
                st.warning(warnung)
        if not is_public_deployment() and not server_address_is_loopback(st.get_option("server.address")):
            st.warning("NOLA is reachable from the network. Start it with --server.address 127.0.0.1.")
```

Im Optionsdialog direkt unter dem Undo-Knopf: `_export_knopf()`.

`.claude/launch.json`: in `runtimeArgs` nach `"8501",` die Einträge `"--server.address", "127.0.0.1",` einfügen.

- [ ] **Step 4: Tests laufen lassen**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1 && .venv/bin/python test_app.py | grep -c "^  PASS"`
Expected: beide bestanden, PASS ≥ Ausgangswert.

- [ ] **Step 5: Commit (nur mit Erlaubnis)**

```bash
git add app.py test_app.py
git commit -m "Lokale Datenbank Aufgabe 8: Start, Sicherung, Wiederherstellen, Export, Netz-Hinweis (<task-id>)"
```

---

### Task 9: Browser-Prüfung, Dokumentation, Projektplan

**Files:**
- Modify: `README.md`, `STATUS.md`, `docs/projektplan.html`
- Artifact: `https://claude.ai/artifact/SR4YwYSqPceEBzsiPwVPhe`

**Interfaces:**
- Consumes: alles aus Task 1–8.

**Acceptance Criteria:**
- **Zuerst:** Liegt im Projektordner schon eine `nola.db`, mit dem Benutzer klären, was damit
  geschieht — nie still löschen.
- Browser-Test lokal gegen eine **Kopie** des Projektordners
  (`cp -R "<Projekt>" "<scratchpad>/nola-kopie"`, dort eine eigene `launch.json`-Konfiguration mit
  `NOLA_DB=1` in `env` und `--server.address 127.0.0.1`):
  1. Erster Start: Meldung „Data moved to nola.db …“, Zahlen plausibel; `nola.db` liegt im Projekt;
     im iCloud-Sicherungsordner liegt `nola-<heute>-<zeit>.db`.
  2. Zwei Tabs: in Tab 1 einen Start bestätigen, in Tab 2 (ohne Neuladen) denselben ausblenden →
     Tab 2 zeigt die Konfliktmeldung, der Start bleibt bestätigt.
  3. Mit `sqlite3 nola.db "UPDATE startplaetze SET Name = Name || ' (ext)' WHERE Kurzel = 'JSLC'"`
     ändern → nach dem nächsten Klick zeigt der Editor den neuen Namen.
  4. `sqlite3 nola.db "BEGIN IMMEDIATE;" ` in einer offenen Sitzung halten, in NOLA bestätigen →
     nach ≈5 s Sperr-Meldung; nach `ROLLBACK` klappt es.
  5. Konsole ohne Fehler (`read_console_messages`), Server-Log ohne Traceback (`preview_logs`).
- **Tempo:** Dauer eines Durchlaufs von `main()` mit der echten Tagesdatei auf `main` und auf
  `lokale-datenbank` messen (Messskript im Scratchpad, `time.perf_counter`, Median aus 10 Läufen,
  Streamlit-Stub wie in `test_app.py`). Grenze: höchstens **+150 ms**. Darüber bekommt
  `referenz_lesen` einen Cache mit `nola_stand` im Schlüssel (externe Änderungen bleiben sichtbar)
  und es wird erneut gemessen. Ergebnis im Bead notieren.
- **Übergangssperre entfernen:** die `NOLA_DB`-Abfrage in `_datenbank_bereit` und ihre Prüfung in
  `test_app.py` löschen; Globale Vorgabe „NOLA bis Aufgabe 8 nicht starten“ ist damit erfüllt.
  Den echten Umzug startet der Benutzer selbst (vorher Altdateien sichern; Export als Rückweg).
- README: Abschnitt „Persistenz“ (Datenbank, Tabellen, Sicherung, Wiederherstellen, Export,
  DB Browser, Startbefehl mit `--server.address 127.0.0.1`).
- STATUS: Zeile „Persistenz“ neu; offener Punkt „Automatische `.bak`-Kopie“ entfernt;
  „`persist_sea_launches` nicht atomar“ entfernt (Seestarts schreiben jetzt transaktional);
  Kennzahlen (Zeilen, Tests) aktualisiert.
- `docs/projektplan.html`: neuer Schritt in `STEPS` (Nummer, Name „Lokale Datenbank“, eindeutige
  Überschrift, Beschreibung, Ergebnis), Äste in `TREE` mit echten Funktionsnamen (`verbinde`,
  `schreibe_unterschiede`, `ersetze_tabelle`, `stelle_bereit`, `umziehen`, `sichere`,
  `exportieren`, `_arbeitsstand_laden`, `_persist_workspace`, `archiv_schreiben`,
  `referenz_lesen`) mit `s` auf den neuen Schritt; erledigte offene Punkte entfernt;
  Kopfkennzahlen mit `STATUS.md` abgeglichen.
- Artifact: erst `Artifact action=read url=…SR4YwYSqPceEBzsiPwVPhe`, dann dieselbe Seite ohne
  `<!doctype>`, `<html>`, `<head>`, `<body>`-Hülle mit `url` veröffentlichen.
- ADR „SQLite als lokaler Speicher“ dem Benutzer anbieten (nicht ungefragt anlegen).

- [ ] **Step 0: Auf vorhandene `nola.db` im Projektordner prüfen (`ls nola.db`), ggf. mit dem Benutzer klären**
- [ ] **Step 1: Browser-Prüfung auf der Kopie wie oben, Ergebnisse (Screenshots, Meldungstexte) im Bead notieren**
- [ ] **Step 1b: Tempo messen, ggf. Cache nach Grenze**
- [ ] **Step 1c: Übergangssperre entfernen, Tests grün**
- [ ] **Step 2: README, STATUS, Projektplan schreiben**
- [ ] **Step 3: Artifact lesen und aktualisieren**
- [ ] **Step 4: Abschlusslauf**

Run: `.venv/bin/python test_nola_db.py && .venv/bin/python test_app.py | tail -1 && .venv/bin/python test_app.py | grep -c "^  PASS"`
Expected: beide bestanden, PASS ≥ Ausgangswert.

- [ ] **Step 5: Commit (nur mit Erlaubnis)**

```bash
git add README.md STATUS.md docs/projektplan.html
git commit -m "Lokale Datenbank Aufgabe 9: Browser-Pruefung, Doku, Projektplan (<task-id>)"
```

---

## Abdeckung der Spec

| Spec-Anforderung | Aufgabe |
|---|---|
| Tabellen, Prüfregeln, Text-Spalten, Schema-Version | 1 |
| `mode=rw`, keine stille leere DB, `NOLA_TEST`-Schutz | 1, 8 |
| Verbindung je Durchlauf/Callback | 5 (`_db`), 6, 7, 8 |
| Arbeitsstand-Abgleich, Konfliktschutz, Zeitstempel, NOTAM-`id` | 2, 6 |
| Referenzen mit Prüfsumme, Undo einheitlich | 5 |
| Archiv/Seestarts mit Stand, Wiederholung bei Konflikt, Archiv-Import | 7 |
| Erkennungsstand aus der DB | 5 |
| Archiv-Import-Zustand verlustfrei | 2, 7 |
| Umzug: temp + `os.link`, unlesbar → Abbruch, Zählprüfung | 4 |
| Fehlt mit Sicherungen → Wahl; verschwindet im Betrieb | 4, 8 |
| Sicherung Start/täglich/vor Schema, temp + `integrity_check`, 30 | 3, 8 |
| Wiederherstellen aus geprüfter Auswahl, überschreibt nie | 3, 8 |
| Export in alte Formate | 4, 8 |
| Fehler nie verschluckt; Archiv-Fortschreiben nur Warnung | 5, 6, 7 |
| Nur lokal: `127.0.0.1` im Startbefehl, Hinweis, Speicher-Aktionen nur Loopback | 8 |
| DB-Werte entschärft anzeigen | 5, 7 |
| `.gitignore` | 1 |
| Tests im `check()`-Stil, PASS-Zahl | alle |
| README, STATUS, Projektplan, Artifact, ADR-Angebot | 9 |
| Cloud: Umzug aus Repo-CSVs, keine Sicherung/Export/Hinweis | 4 (`stelle_bereit` ohne Sicherungsordner), 8 (`is_public_deployment`) |

Bewusst nicht enthalten (laut Spec „Nicht Teil“): NOTAM-Historie, Netzzugang/Anmeldung,
Live-Aktualisierung, dauerhafter Cloud-Speicher. Der Archiv-Import-Zustand (`zustand_speichern`)
wird ohne Konfliktprüfung ersetzt — der Reiter ist nur lokal sichtbar; das deckt die Spec
(Konfliktschutz ist für Arbeitsstand, Referenzen und Archiv gefordert).

## Stress Test Results: Plan lokale Datenbank

Vorab geprüft: Rundlauf CSV → SQLite (`TEXT`) → DataFrame an allen fünf echten Dateien identisch
(`assert_frame_equal` inkl. Datentypen, pandas 2.3.3); `~/Documents` wird nicht über iCloud
synchronisiert (die Live-Datenbank liegt also nicht in iCloud).

### Resolved Decisions
- **`_csv_streng`** prüft Spalten selbst; Werte bleiben unangetastet (kein `_require_columns`).
  Koordinaten werden nie umgewandelt gespeichert, Trägersysteme/Seestarts ziehen fehlerfrei um.
  Zusätzlich geprüft: FIRs, Trägersysteme und Seestarts aus der DB = heutige Leser.
- **Übergang:** Regel „NOLA bis Aufgabe 8 nicht im Projektordner starten“ + Code-Sperre
  `NOLA_DB=1` in `_datenbank_bereit` (Aufgabe 8), entfernt in Aufgabe 9; Aufgabe 9 prüft eine
  vorhandene `nola.db` mit dem Benutzer; Browser-Test auf einer Kopie.
- **iCloud-Platzhalter:** `pruefe_sicherung` liefert `ok/corrupt/in_cloud`; ausgelagerte Sicherungen
  erscheinen als „in iCloud only“ statt „corrupt“ und sind nicht wählbar.
- **Testschutz** auf echten Sicherungsordner, Wiederherstellungsziel und Export-Ordner ausgedehnt
  (`schuetze_echte_orte`, Pfad nur in `nola_db.ECHTER_SICHERUNGSORDNER`).
- **Tempo:** Messung in Aufgabe 9, Grenze +150 ms je Durchlauf, Cache nur bei Überschreitung.

### Changes Made
- Aufgaben 1, 3, 4, 5, 7, 8, 9 und Globale Vorgaben entsprechend angepasst (Code, Tests,
  Akzeptanzkriterien).

### Deferred / Parking Lot
- Keine.

### Confidence Assessment
- Overall: **Hoch** für die neuen Module (Kernannahme per Prototyp belegt), **mittel** für den
  Umbau in `app.py` (große Datei, parallel geändert; Fundstellen über `grep` statt Zeilennummern).
- Areas of concern: Anpassung der bestehenden `test_app.py`-Prüfungen in Aufgabe 5–7 ist
  Handarbeit je Fundstelle; die PASS-Zahl ist die Absicherung.
