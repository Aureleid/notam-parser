# Startarchiv von Hand bearbeiten – Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use beads-superpowers:subagent-driven-development (recommended) or beads-superpowers:executing-plans to implement this plan task-by-task. Each Task becomes a bead (`bd create -t task --parent <epic-id>`). Steps within tasks use checkbox (`- [ ]`) syntax for human readability.

**Goal:** Nation, Platz, Vehicle, Payload und Orbit einer Archivzeile lassen sich im Reiter *Launch Archive* von Hand ändern; jede Handänderung überlebt spätere Läufe, ist sichtbar (✎/↻), rücknehmbar (Reset, Undo) und gegen gleichzeitige Änderungen geschützt.

**Architecture:** Der gültige Wert steht weiter in `startarchiv`; eine neue Fachtabelle `archiv_handwerte` merkt je (Schlüssel, Spalte) den früheren NOLA-Wert und die Herkunft (`hand`/`berechnet`). Alle Pfade, die das Archiv schreiben (Tageslauf, Entfernen, Archiv-Import, Bearbeiten, Reset, Undo), lesen beide Tabellen aus einer Momentaufnahme und schreiben sie alles-oder-nichts mit Standvergleich beider. Die Bearbeitungslogik besteht aus reinen Funktionen in `app.py`; die Oberfläche ruft sie nur auf.

**Tech Stack:** Python 3.9 (`.venv`), Streamlit 1.50, pandas 2.3.3, SQLite 3 (Modul `sqlite3`), Tests als Skripte mit `check()`.

**Spec:** `.internal/specs/2026-10-09-archiv-handbearbeitung-design.md` (inkl. „Stress Test Results“).

## Global Constraints

- Python 3.9: keine `match`-Anweisung, keine `X | Y`-Typen, `Optional[...]`/`Dict[...]` aus `typing`.
- Kommentare und Docstrings deutsch ohne Umlaute (ae/oe/ue/ss) wie im umgebenden Code; Bildschirmtexte englisch.
- Tests: `.venv/bin/python test_nola_db.py` und `.venv/bin/python test_app.py`, beide müssen mit „ERGEBNIS: ALLE TESTS BESTANDEN“ enden. Tests setzen `NOLA_TEST=1`; **nie** die echte `nola.db` oder den iCloud-Sicherungsordner berühren (Temp-DBs: `neue_db()` in test_nola_db, `_kopie_der_test_db()`/`_temp_db()` in test_app).
- TDD: erst der fehlschlagende `check()`, dann der Code.
- Erlaubte Handwert-Spalten (CHECK): `Nation`, `Weltraumbahnhof`, `Trägersystem`, `Payload`, `Orbit`, `Inklination`, `Azimuth`. Herkunft (CHECK): `hand`, `berechnet`.
- Orbit-Auswahl: `SSO`, `HIGH-INC`, `LEO/MEO`, `GTO`, `RETRO`, `-`.
- Payload: höchstens 200 Zeichen, Zeilenumbrüche → Leerzeichen; Anfang `=`, `+`, `@`, Tab oder CR → abgelehnt; `-` erlaubt.
- Bahnwerte mit einer Nachkommastelle (`"96.8"`).
- Edit/Reset nur bei `local_admin_allowed()` (fail-closed), geprüft in der Oberfläche **und** in der Schreibfunktion.
- Schema-Version 2, Sicherung `…-vor-schema-2.db` vorher (vorhandener Mechanismus in `nola_umzug.stelle_bereit`).
- Alle angezeigten Fremdwerte durch `_md_plain`; Meldungen im Dialog über `_melde_db_dialog`.
- Arbeit auf Zweig `archiv-handbearbeitung`; Commit je Aufgabe nur, wenn der Benutzer es für diese Runde erlaubt hat; Merge und Push nur auf sein Wort.

## Dateien

| Datei | Verantwortung in diesem Vorhaben |
|---|---|
| `nola_db.py` | Tabelle `archiv_handwerte`, Schema 2, `lese_tabellen`, `ersetze_tabellen_geprueft`, Handwerte in `ersetze_archiv_und_importzustand`, `pruefe_sicherung` für alte Sicherungen |
| `nola_umzug.py` | `archiv_handwerte.csv` in Umzug und Export |
| `app.py` | reine Bearbeitungslogik; Lese-/Schreibhelfer für Archiv + Handwerte; `merge_archive`, `_update_archive`, `_remove_archive_row`, Undo; Reiter *Launch Archive* |
| `archiv_import.py` | `confirm_many`, `remove_orphan` beachten und bereinigen Markierungen |
| `test_nola_db.py`, `test_app.py` | Tests je Aufgabe |
| `README.md`, `STATUS.md`, `docs/projektplan.html` | Doku, Projektplan, Kennzahlen |

---

### Task 1: Speicherschicht – Tabelle `archiv_handwerte`, Schema 2, gemeinsames Schreiben

**Files:**
- Modify: `nola_db.py` (Konstanten ab Zeile 29/41, `_schema_sql` 159–237, `SCHRITTE` 364, `_LEER_ALS_TEXT` 432, nach `ersetze_tabellen` ~510, `ersetze_archiv_und_importzustand` 863, `pruefe_sicherung` 985–1012)
- Modify: `nola_umzug.py` (`Altdateien` 26, `altdateien_im` 37, `umziehen` 124–170, `_schreibe_export` 318–350)
- Modify: `app.py` (neue Konstante `ARCHIVE_HANDWERTE_CSV` neben `ARCHIVE_CSV` 2028)
- Test: `test_nola_db.py`

**Interfaces:**
- Produces:
  - `nola_db.HANDWERT_SPALTEN: Tuple[str, ...]` = `("Nation", "Weltraumbahnhof", "Trägersystem", "Payload", "Orbit", "Inklination", "Azimuth")`
  - `nola_db.HANDWERT_HERKUNFT: Tuple[str, ...]` = `("hand", "berechnet")`
  - `nola_db.FACHTABELLEN["archiv_handwerte"]` = `("schluessel", "spalte", "nola_wert", "herkunft", "geaendert_utc")`
  - `nola_db.SCHEMA_VERSION == 2`, `nola_db.SCHRITTE[1]` legt die Tabelle an.
  - `nola_db.lese_tabellen(conn, tabellen: Sequence[str]) -> Dict[str, pd.DataFrame]` – eine Lesetransaktion, jedes DataFrame mit `attrs["nola_stand"]`.
  - `nola_db.ersetze_tabellen_geprueft(conn, tabellen: Dict[str, Tuple[pd.DataFrame, str]]) -> Dict[str, str]` – alles oder nichts; Abweichung → `Konflikt` mit `ursache == ARCHIV_GEAENDERT` für `startarchiv`, sonst `"changed"`.
  - `nola_db.ersetze_archiv_und_importzustand(conn, archiv_df, archiv_erwartet, state, state_erwartet, handwerte: Optional[Tuple[pd.DataFrame, str]] = None) -> Tuple[str, str]`
  - `app.ARCHIVE_HANDWERTE_CSV = APP_DIR / "archiv_handwerte.csv"`
  - `nola_umzug.Altdateien.handwerte: Path`

**Acceptance Criteria:**
- Neue Datei hat Version 2 und die Tabelle; eine Datei mit Version 1 wird nach Sicherung auf 2 gehoben, alle Daten unverändert, Tabelle leer.
- CHECKs lehnen fremde Spalte, fremde Herkunft, leeren Schlüssel und doppelten (Schlüssel, Spalte) ab.
- `ersetze_tabellen_geprueft`: schreibt alle Tabellen; weicht ein Stand ab → `Konflikt`, keine Tabelle geändert.
- `ersetze_archiv_und_importzustand` mit `handwerte`: weicht der Stand der Handwerte ab → `Konflikt`, nichts geschrieben; ohne `handwerte` Verhalten wie bisher.
- `pruefe_sicherung` meldet eine Sicherung mit Schema 1 (ohne die Tabelle) als `ok` mit Zahl 0 für `archiv_handwerte`.
- Export enthält `archiv_handwerte.csv`; Umzug liest sie zurück; fehlt sie, ist die Tabelle leer.
- Alle bisherigen Tests grün (hart codierte Version 1 auf `db.SCHEMA_VERSION` umgestellt; `SCHRITTE.clear()` in Abschnitt F5 entfernt nur den Test-Schritt).

- [ ] **Step 1: Failing tests in `test_nola_db.py` (neuer Abschnitt nach „== 6. Schema-Version ==“)**

```python
print("== 6b. Handwerte (Schema 2) ==")
_ph, _ch = neue_db()
check("Schema-Version 2 nach Anlegen", db.schema_version(_ch) == 2 == db.SCHEMA_VERSION)
check("archiv_handwerte ist Fachtabelle", db.FACHTABELLEN["archiv_handwerte"] ==
      ("schluessel", "spalte", "nola_wert", "herkunft", "geaendert_utc"))
check("archiv_handwerte nicht im Arbeitsstand", "archiv_handwerte" not in db.ARBEITSTABELLEN)
check("archiv_handwerte in ALLE_TABELLEN", "archiv_handwerte" in db.ALLE_TABELLEN)
_hw = pd.DataFrame([{"schluessel": "01.01.2026|A0001/26", "spalte": "Nation", "nola_wert": "China",
                     "herkunft": "hand", "geaendert_utc": "2026-10-15T00:00:00+00:00"}])
_st0 = db.lese_tabelle(_ch, "archiv_handwerte").attrs["nola_stand"]
db.ersetze_tabelle(_ch, "archiv_handwerte", _hw, _st0)
check("Handwert geschrieben", db.zaehle(_ch, "archiv_handwerte") == 1)
for _label, _aend in [("fremde Spalte", {"spalte": "Startdatum"}), ("fremde Herkunft", {"herkunft": "x"}),
                      ("leerer Schluessel", {"schluessel": " "})]:
    _bad = _hw.copy()
    for _k, _v in _aend.items():
        _bad.loc[0, _k] = _v
    try:
        db.ersetze_tabelle(_ch, "archiv_handwerte", _bad, None); check("CHECK: " + _label, False)
    except db.DbFehler:
        check("CHECK: " + _label, db.zaehle(_ch, "archiv_handwerte") == 1)
try:
    db.ersetze_tabelle(_ch, "archiv_handwerte", pd.concat([_hw, _hw]), None); check("PK doppelt abgelehnt", False)
except db.DbFehler:
    check("PK doppelt abgelehnt", True)
_hw_leer = db.lese_tabelle(_ch, "archiv_handwerte")
db.ersetze_tabelle(_ch, "archiv_handwerte", _hw.assign(nola_wert=""), _hw_leer.attrs["nola_stand"])
check("nola_wert '' <-> NULL", db.lese_tabelle(_ch, "archiv_handwerte").loc[0, "nola_wert"] == ""
      and _ch.execute("SELECT nola_wert FROM archiv_handwerte").fetchone()[0] is None)

# lese_tabellen: eine Momentaufnahme
_beide = db.lese_tabellen(_ch, ("startarchiv", "archiv_handwerte"))
check("lese_tabellen liefert beide mit Stand",
      set(_beide) == {"startarchiv", "archiv_handwerte"} and all("nola_stand" in d.attrs for d in _beide.values()))
check("lese_tabellen laesst keine Transaktion offen", not _ch.in_transaction)

# ersetze_tabellen_geprueft: alles oder nichts
_ar = pd.DataFrame([{**{s: "" for s in db.FACHTABELLEN["startarchiv"]},
                     "NOTAM": "A0001/26", "Startdatum": "01.01.2026", "Nation": "China"}])
_neu = db.ersetze_tabellen_geprueft(_ch, {
    "startarchiv": (_ar, _beide["startarchiv"].attrs["nola_stand"]),
    "archiv_handwerte": (_hw, _beide["archiv_handwerte"].attrs["nola_stand"])})
check("geprueft: beide geschrieben, neue Staende",
      db.zaehle(_ch, "startarchiv") == 1 and set(_neu) == {"startarchiv", "archiv_handwerte"})
_vor = db.lese_tabellen(_ch, ("startarchiv", "archiv_handwerte"))
try:
    db.ersetze_tabellen_geprueft(_ch, {
        "startarchiv": (_ar.iloc[0:0], _vor["startarchiv"].attrs["nola_stand"]),
        "archiv_handwerte": (_hw.iloc[0:0], "veraltet")})
    check("geprueft: veralteter Stand -> Konflikt", False)
except db.Konflikt as exc:
    check("geprueft: veralteter Stand -> Konflikt", exc.ursache == "changed")
check("geprueft: nichts geschrieben", db.zaehle(_ch, "startarchiv") == 1 and db.zaehle(_ch, "archiv_handwerte") == 1)
try:
    db.ersetze_tabellen_geprueft(_ch, {"startarchiv": (_ar, "veraltet")})
    check("geprueft: Archiv-Konflikt traegt ARCHIV_GEAENDERT", False)
except db.Konflikt as exc:
    check("geprueft: Archiv-Konflikt traegt ARCHIV_GEAENDERT", exc.ursache == db.ARCHIV_GEAENDERT)

# ersetze_archiv_und_importzustand mit Handwerten
_vor = db.lese_tabellen(_ch, ("startarchiv", "archiv_handwerte"))
try:
    db.ersetze_archiv_und_importzustand(
        _ch, _ar, _vor["startarchiv"].attrs["nola_stand"], {"version": 1, "tage": {}, "entscheidungen": {},
        "review_bestaetigt": [], "review_ausgeblendet": [], "erkennungsstand": ""}, None,
        handwerte=(_hw.iloc[0:0], "veraltet"))
    check("Import: veraltete Handwerte -> Konflikt", False)
except db.Konflikt:
    check("Import: veraltete Handwerte -> Konflikt", db.zaehle(_ch, "archiv_handwerte") == 1)
_ch.close()

# Schema 1 -> 2: Sicherung vorher, Daten unveraendert
_p1, _c1 = neue_db()
db.ersetze_tabelle(_c1, "startarchiv", _ar, None)
_c1.execute("DROP TABLE archiv_handwerte")
db.setze_meta(_c1, "schema_version", "1")
_ord1 = Path(tempfile.mkdtemp())
_gesichert = []
db.pruefe_schema(_c1, lambda: (_gesichert.append(1), db.sichere(_c1, _ord1, datetime(2026, 10, 15, 9, 0), zusatz="vor-schema-2"))[1])
check("1->2: gesichert", _gesichert == [1] and any("vor-schema-2" in p.name for p in _ord1.iterdir()))
check("1->2: Version 2, Tabelle leer, Archiv unveraendert",
      db.schema_version(_c1) == 2 and db.zaehle(_c1, "archiv_handwerte") == 0 and db.zaehle(_c1, "startarchiv") == 1)
_alt_sich = sorted(_ord1.iterdir())[0]
_art, _zahl = db.pruefe_sicherung(_alt_sich)
check("Sicherung mit Schema 1 ist ok, Handwerte 0", _art == "ok" and _zahl.get("archiv_handwerte") == 0, (_art, _zahl))
_c1.close()
```

(`datetime` ist oben in test_nola_db.py zu importieren, falls noch nicht vorhanden: `from datetime import datetime`.)

Export/Umzug in den vorhandenen F5-Abschnitt (nach „F5 Export Importzustand“):

```python
check("Export enthaelt archiv_handwerte.csv", (_e3 / "archiv_handwerte.csv").exists())
_dh = _altordner()
(_dh / "archiv_handwerte.csv").write_text(
    "schluessel,spalte,nola_wert,herkunft,geaendert_utc\n01.01.2026|A0001/26,Nation,China,hand,2026-10-15T00:00:00+00:00\n",
    encoding="utf-8")
_dbh = Path(tempfile.mkdtemp()) / "nola.db"
_zh = um.umziehen(_dbh, um.altdateien_im(_dh))
_ch2 = db.verbinde(_dbh)
check("Umzug liest archiv_handwerte.csv", db.zaehle(_ch2, "archiv_handwerte") == 1, _zh)
_ch2.close()
_dbh2 = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_dbh2, um.altdateien_im(_altordner()))
_ch3 = db.verbinde(_dbh2)
check("Umzug ohne archiv_handwerte.csv: leer", db.zaehle(_ch3, "archiv_handwerte") == 0)
_ch3.close()
```

(`_e3` ist der Export aus `_db3` in Abschnitt F5, `test_nola_db.py:839`.)

- [ ] **Step 2: Laufen lassen – erwartet FAIL**

Run: `.venv/bin/python test_nola_db.py 2>&1 | grep -E "FAIL|Error|ERGEBNIS" | head`
Expected: `KeyError: 'archiv_handwerte'` bzw. FAIL bei „Schema-Version 2“.

- [ ] **Step 3: Implementierung `nola_db.py`**

```python
SCHEMA_VERSION = 2
```

In `FACHTABELLEN` nach `"seestarts"`:

```python
    "archiv_handwerte": ("schluessel", "spalte", "nola_wert", "herkunft", "geaendert_utc"),
```

Nach `ALLE_TABELLEN`:

```python
#: Spalten des Startarchivs, die von Hand gesetzt (oder nach Platzwechsel neu berechnet) werden koennen.
HANDWERT_SPALTEN: Tuple[str, ...] = (
    "Nation", "Weltraumbahnhof", "Trägersystem", "Payload", "Orbit", "Inklination", "Azimuth",
)
#: Herkunft eines Handwerts: von Hand gesetzt oder aus dem neuen Platz berechnet.
HANDWERT_HERKUNFT: Tuple[str, ...] = ("hand", "berechnet")


def _handwerte_sql() -> str:
    """Eine Anweisung - dient Neuanlage (_schema_sql) und Umbau (SCHRITTE[1])."""
    spalten = ", ".join("'{}'".format(s) for s in HANDWERT_SPALTEN)  # Konstanten, keine Eingabe
    herkunft = ", ".join("'{}'".format(h) for h in HANDWERT_HERKUNFT)
    return (
        "CREATE TABLE IF NOT EXISTS archiv_handwerte (\n"
        "  schluessel TEXT NOT NULL CHECK (trim(schluessel) <> ''),\n"
        "  spalte TEXT NOT NULL CHECK (spalte IN ({})),\n"
        "  nola_wert TEXT,\n"
        "  herkunft TEXT NOT NULL CHECK (herkunft IN ({})),\n"
        "  geaendert_utc TEXT NOT NULL,\n"
        "  PRIMARY KEY (schluessel, spalte)\n"
        ")".format(spalten, herkunft)
    )
```

In `_schema_sql` vor dem schliessenden `"""` des Skripts eine Zeile `{hw};` und im `.format(...)` `hw=_handwerte_sql(),` ergänzen.

```python
#: Umbauschritte: SCHRITTE[n] hebt Version n auf n + 1.
SCHRITTE: Dict[int, str] = {1: _handwerte_sql()}
```

(`SCHRITTE` steht nach `_handwerte_sql`; falls nötig die Definition von `_handwerte_sql` über `SCHRITTE` verschieben.)

```python
_LEER_ALS_TEXT = frozenset({"startarchiv", "seestarts", "archiv_handwerte"})
```

Nach `ersetze_tabellen`:

```python
def lese_tabellen(conn: sqlite3.Connection, tabellen: Sequence[str]) -> Dict[str, pd.DataFrame]:
    """
    Mehrere Fachtabellen aus EINER Momentaufnahme (Lesetransaktion) - wer sie
    spaeter gemeinsam ersetzt, gibt die Staende an ersetze_tabellen_geprueft.
    """
    for tabelle in tabellen:
        if tabelle not in FACHTABELLEN:
            raise ValueError("unknown table {}".format(tabelle))
    try:
        conn.execute("BEGIN")
        try:
            return {t: lese_tabelle(conn, t) for t in tabellen}
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")  # nur gelesen
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc


def ersetze_tabellen_geprueft(
    conn: sqlite3.Connection, tabellen: Dict[str, Tuple[pd.DataFrame, str]]
) -> Dict[str, str]:
    """
    Ersetzt mehrere Fachtabellen in EINER Schreibtransaktion - nur, wenn jede
    noch ihrem erwarteten Stand entspricht. Weicht einer ab: Konflikt, keine
    geschrieben (Ursache ARCHIV_GEAENDERT fuer das Startarchiv, sonst "changed").
    Rueckgabe: die neuen Staende je Tabelle.
    """
    for tabelle in tabellen:
        if tabelle not in FACHTABELLEN:
            raise ValueError("unknown table {}".format(tabelle))
    try:
        with _transaktion(conn):
            for tabelle, (_, erwartet) in tabellen.items():
                if _stand(_zeilen(conn, tabelle)) != erwartet:
                    raise Konflikt(
                        ARCHIV_GEAENDERT if tabelle == "startarchiv" else "changed", KONFLIKT_TEXT)
            return {t: _ersetze_in_transaktion(conn, t, df) for t, (df, _) in tabellen.items()}
    except sqlite3.Error as exc:
        raise _uebersetze(exc) from exc
```

(`ARCHIV_GEAENDERT` ist schon definiert – mit `grep -n "ARCHIV_GEAENDERT =" nola_db.py` prüfen; steht es unterhalb, die neue Funktion dahinter einfügen.)

`ersetze_archiv_und_importzustand` – Parameter `handwerte: Optional[Tuple[pd.DataFrame, str]] = None` anhängen und in der Transaktion:

```python
            if _stand(_zeilen(conn, "startarchiv")) != archiv_erwartet:
                raise Konflikt(ARCHIV_GEAENDERT, KONFLIKT_TEXT)
            if handwerte is not None and _stand(_zeilen(conn, "archiv_handwerte")) != handwerte[1]:
                raise Konflikt(ARCHIV_GEAENDERT, KONFLIKT_TEXT)
            neu_archiv = _ersetze_in_transaktion(conn, "startarchiv", archiv_df)
            if handwerte is not None:
                _ersetze_in_transaktion(conn, "archiv_handwerte", handwerte[0])
            neu_zustand = _speichere_importzustand_in_transaktion(conn, state, state_erwartet)
```

(Ursache `ARCHIV_GEAENDERT`: für den Import ist eine geänderte Markierung eine Änderung am Archiv – `_archiv_und_zustand_schreiben` meldet dann „The launch archive changed meanwhile“.)

`pruefe_sicherung` – nur vorhandene Tabellen zählen, fehlende als 0:

```python
            vorhanden = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            return "ok", {
                t: int(conn.execute("SELECT count(*) FROM {}".format(_q(t))).fetchone()[0]) if t in vorhanden else 0
                for t in tuple(FACHTABELLEN) + ARBEITSTABELLEN
            }
```

- [ ] **Step 4: Implementierung `app.py` und `nola_umzug.py`**

`app.py` neben `ARCHIVE_CSV`:

```python
#: Handwerte des Startarchivs - nur Format des Exports und Quelle des Umzugs.
ARCHIVE_HANDWERTE_CSV = APP_DIR / "archiv_handwerte.csv"
```

`nola_umzug.py`: Feld `handwerte: Path` in `Altdateien` (nach `seestarts`), in `altdateien_im` `handwerte=d / app.ARCHIVE_HANDWERTE_CSV.name,`; in `umziehen` im `tabellen`-Dict:

```python
            "archiv_handwerte": _csv_streng(alt.handwerte, db.FACHTABELLEN["archiv_handwerte"]),
```

In `_schreibe_export` nach dem Seestart-Export:

```python
        app._write_bytes_atomic(
            ziel / app.ARCHIVE_HANDWERTE_CSV.name,
            db.lese_tabelle(conn, "archiv_handwerte")[list(db.FACHTABELLEN["archiv_handwerte"])]
            .to_csv(index=False).encode("utf-8-sig"),
        )
```

Alle anderen Stellen, die `Altdateien(...)` direkt bauen: `grep -n "Altdateien(" *.py` – dort `handwerte=` ergänzen.

- [ ] **Step 5: Bestehende Tests nachziehen**

- `test_nola_db.py:33` `check("Schema-Version 1", db.schema_version(_c) == 1)` → `check("Schema-Version aktuell", db.schema_version(_c) == db.SCHEMA_VERSION)`; ebenso Zeile 220 („Version 1 nach Anlegen“).
- Abschnitt F5 (~Zeile 868–883): `SCHRITTE[0] = "SELECT 1"` bleibt; erwartete Sicherung `vor-schema-{db.SCHEMA_VERSION}`, „Version danach“ `== db.SCHEMA_VERSION`; `finally: db.SCHRITTE.clear()` → `finally: db.SCHRITTE.pop(0, None)` (sonst fehlt SCHRITTE[1] in späteren Abschnitten).
- Ebenso Zeile 173–179 (`del db.SCHRITTE[0]` bleibt richtig).
- `grep -n "== 1)\|schema_version\|vor-schema-1" test_nola_db.py test_app.py` und jede hart codierte Version 1 der aktuellen Fassung auf `db.SCHEMA_VERSION` umstellen.

- [ ] **Step 6: Tests laufen lassen – erwartet PASS**

Run: `.venv/bin/python test_nola_db.py 2>&1 | tail -3 && .venv/bin/python test_app.py 2>&1 | tail -3`
Expected: beide „ERGEBNIS: ALLE TESTS BESTANDEN“.

- [ ] **Step 7: Commit (falls für die Runde erlaubt)**

```bash
git add nola_db.py nola_umzug.py app.py test_nola_db.py test_app.py
git commit -m "Archiv-Handwerte Aufgabe 1: Tabelle archiv_handwerte, Schema 2, gemeinsames Schreiben (<bead>)"
```

---

### Task 2: Reine Bearbeitungslogik in `app.py`

**Files:**
- Modify: `app.py` (neuer Block direkt nach `merge_archive`, ~Zeile 4865)
- Test: `test_app.py` (neuer Abschnitt vor `print("ERGEBNIS:"...)`)

**Interfaces:**
- Consumes: `nola_db.HANDWERT_SPALTEN`, `nola_db.FACHTABELLEN["archiv_handwerte"]` (Task 1); vorhandene `initial_bearing_deg`, `surface_distance_km`, `_circular_mean`, `estimate_inclination_deg`, `classify_orbit`, `orbit_short`, `archive_key`, `TARGET_NATIONS`, `VEHICLE_NONE` (`""`), `VEHICLE_SEPARATOR`.
- Produces:
  - `ARCHIV_EDIT_FELDER = ("Nation", "Weltraumbahnhof", "Trägersystem", "Payload", "Orbit")`
  - `ORBIT_AUSWAHL = ("SSO", "HIGH-INC", "LEO/MEO", "GTO", "RETRO", "-")`
  - `PAYLOAD_MAX = 200`
  - `class ArchivEingabeFehler(ValueError)`
  - `Marken = Dict[str, Tuple[str, str]]` (Spalte → (nola_wert, herkunft))
  - `handwerte_index(handwerte: pd.DataFrame) -> Dict[str, Marken]`
  - `handwerte_mit(handwerte: pd.DataFrame, schluessel: str, marken: Marken, jetzt: str) -> pd.DataFrame`
  - `handwerte_bereinigen(handwerte: pd.DataFrame, archiv: pd.DataFrame) -> pd.DataFrame`
  - `payload_bereinigen(text: str) -> str`
  - `bahn_aus_platz(lat: float, lon: float, dropzones: str) -> Tuple[str, str, str, str]` → (Inklination, Azimuth, Orbit, Hinweis)
  - `archiv_zeile_bearbeiten(zeile: Dict[str, str], neu: Dict[str, str], marken: Marken, erlaubt: Dict[str, Sequence[str]], spaceports: pd.DataFrame) -> Tuple[Dict[str, str], Marken, List[str]]`
  - `archiv_feld_zuruecksetzen(zeile: Dict[str, str], marken: Marken, spalte: str) -> Tuple[Dict[str, str], Marken]`
  - `ueberschneidende_schluessel(archiv: pd.DataFrame) -> Set[str]`
  - `archiv_erlaubt(spaceports: pd.DataFrame, vehicles: pd.DataFrame, nation: str) -> Dict[str, List[str]]`

**Acceptance Criteria:**
- Nur geänderte Felder werden markiert; `nola_wert` = Wert vor der ersten Änderung; eine zweite Änderung behält ihn.
- Zurück auf den `nola_wert` entfernt die Markierung.
- Platzwechsel: Inklination/Azimuth/Orbit neu berechnet und `berechnet` markiert; von Hand gewählter Orbit bleibt (`hand`); Platz zurück auf den ursprünglichen stellt die berechneten Werte zurück und entfernt ihre Markierungen.
- Selbstprobe: drei Zeilen aus dem Import 2026 ergeben am eigenen Platz Inklination und Azimuth ±1°.
- Platzwechsel HAIN → WSLC (2 km entfernt) ergibt Inklination ±1° zur HAIN-Zeile; gleiche Werte werden nicht markiert. JSLC → TSLC markiert Inklination, Azimuth und Orbit als `berechnet`.
- Keine Dropzones → Bahnwerte leer, Hinweis „no drop zones to compute the orbit from“; Zone < 1 km → leer, „zone on the launch site“; Platz ohne Koordinaten → keine Neuberechnung, Hinweis.
- Ungültige Werte (außerhalb Liste ∪ aktuellem Wert; Payload > 200; Payload mit `=`/`+`/`@`/Tab/CR am Anfang; Trennzeile als Vehicle) → `ArchivEingabeFehler`.
- Platz passt nicht zur Nation → Hinweis, kein Fehler.
- Reset stellt Wert und Markierung zurück; Reset des Platzes nimmt alle `berechnet`-Markierungen mit, `hand` bleibt.
- `ueberschneidende_schluessel` liefert genau die Zeilen mit gemeinsamer NOTAM-Kennung am selben Startdatum.
- `handwerte_bereinigen` entfernt Markierungen, deren Zeile nicht mehr im Archiv steht.

- [ ] **Step 1: Failing tests in `test_app.py`**

```python
print("== Archiv von Hand bearbeiten: Logik ==")
import pandas as _pd_h
_sp_h = app.referenz_lesen("startplaetze")
_ve_h = app.referenz_lesen("traegersysteme")
_HAIN = {"NOTAM": "B0200/26, B0202/26, B0067/26, B0068/26", "Startdatum": "13.01.2026", "Startzeit": "15:17",
         "Nation": "China", "Weltraumbahnhof": "HAIN", "Trägersystem": "CZ-8A", "Payload": "Xingwang Digui 18A-I",
         "Orbit": "LEO/MEO", "Inklination": "51.3", "Azimuth": "140.8",
         "Dropzones": "12.9178 116.4648; 7.6076 120.6037"}
_TSLC = {"NOTAM": "A0787/26, A0788/26", "Startdatum": "25.03.2026", "Startzeit": "22:43", "Nation": "China",
         "Weltraumbahnhof": "TSLC", "Trägersystem": "CZ-2D", "Payload": "Siwei Gaojing-2 05 & 06", "Orbit": "SSO",
         "Inklination": "95.6", "Azimuth": "189.8", "Dropzones": "33.8297 110.6076; 29.8167 109.7583"}
_JSLC = {"NOTAM": "A0114/26, A0115/26", "Startdatum": "15.01.2026", "Startzeit": "03:53", "Nation": "China",
         "Weltraumbahnhof": "JSLC", "Trägersystem": "CZ-2C", "Payload": "AlSat-3A", "Orbit": "SSO",
         "Inklination": "98.0", "Azimuth": "193.2", "Dropzones": "36.1119 98.9012; 32.5881 97.9734"}

def _platz_h(code):
    r = _sp_h[_sp_h["Kurzel"] == code].iloc[0]
    return float(r["Latitude"]), float(r["Longitude"])

for _z in (_HAIN, _TSLC, _JSLC):
    _i, _a, _o, _hin = app.bahn_aus_platz(*_platz_h(_z["Weltraumbahnhof"]), _z["Dropzones"])
    check("Selbstprobe {}: Inklination und Azimuth +-1 Grad".format(_z["Weltraumbahnhof"]),
          abs(float(_i) - float(_z["Inklination"])) <= 1 and abs(float(_a) - float(_z["Azimuth"])) <= 1
          and _o == _z["Orbit"] and _hin == "", (_i, _a, _o, _hin))
check("bahn_aus_platz: eine Nachkommastelle", re.fullmatch(r"\d+\.\d", _i) is not None, _i)
check("bahn_aus_platz: keine Dropzones -> leer + Hinweis",
      app.bahn_aus_platz(19.6, 110.9, "") == ("", "", "-", "no drop zones to compute the orbit from"))
check("bahn_aus_platz: Zone auf dem Platz -> leer + Hinweis",
      app.bahn_aus_platz(19.6310, 110.9458, "19.6310 110.9458; 7.6 120.6")[3] == "zone on the launch site")

_erl_h = app.archiv_erlaubt(_sp_h, _ve_h, "China")
check("erlaubt: Orbit-Liste", list(_erl_h["Orbit"]) == list(app.ORBIT_AUSWAHL))
check("erlaubt: Trennzeile nicht waehlbar", app.VEHICLE_SEPARATOR not in _erl_h["Trägersystem"]
      and app.VEHICLE_NONE in _erl_h["Trägersystem"])
check("erlaubt: chinesische Plaetze zuerst", _erl_h["Weltraumbahnhof"][0] in {"JSLC", "TSLC", "XSLC", "WSLC", "HIIS", "HYOS", "HAIN"})

# Payload
check("Payload: Zeilenumbruch -> Leerzeichen", app.payload_bereinigen(" a\nb ") == "a b")
check("Payload: '-' erlaubt", app.payload_bereinigen("-") == "-")
for _bad in ("=HYPERLINK(1)", "+1", "@SUM", "\tx", "x" * 201):
    try:
        app.payload_bereinigen(_bad); check("Payload abgelehnt: {!r}".format(_bad[:6]), False)
    except app.ArchivEingabeFehler:
        check("Payload abgelehnt: {!r}".format(_bad[:6]), True)

# Nur Geaendertes markieren, nola_wert bleibt der erste
_z1, _m1, _h1 = app.archiv_zeile_bearbeiten(dict(_HAIN), {"Payload": "Neu", "Nation": "China"}, {}, _erl_h, _sp_h)
check("nur Payload markiert", _m1 == {"Payload": ("Xingwang Digui 18A-I", "hand")} and _z1["Payload"] == "Neu", _m1)
_z2, _m2, _ = app.archiv_zeile_bearbeiten(_z1, {"Payload": "Neuer"}, _m1, _erl_h, _sp_h)
check("zweite Aenderung behaelt den ersten nola_wert", _m2["Payload"] == ("Xingwang Digui 18A-I", "hand"))
_z3, _m3, _ = app.archiv_zeile_bearbeiten(_z2, {"Payload": "Xingwang Digui 18A-I"}, _m2, _erl_h, _sp_h)
check("zurueck auf NOLA-Wert entfernt die Markierung", _m3 == {} and _z3["Payload"] == "Xingwang Digui 18A-I")

# Platzwechsel HAIN -> WSLC (2 km entfernt): gleiche Bahnwerte, also keine berechnete Marke
_zw, _mw, _ = app.archiv_zeile_bearbeiten(dict(_HAIN), {"Weltraumbahnhof": "WSLC"}, {}, _erl_h, _sp_h)
check("Platzwechsel HAIN->WSLC: Inklination +-1 Grad, nur der Platz markiert",
      abs(float(_zw["Inklination"]) - 51.3) <= 1 and _mw == {"Weltraumbahnhof": ("HAIN", "hand")}, (_zw["Inklination"], _mw))
# Platzwechsel JSLC -> TSLC: andere Bahn (gerechnet 137.4 / 251.7 / RETRO), alle drei berechnet markiert
_z4, _m4, _h4 = app.archiv_zeile_bearbeiten(dict(_JSLC), {"Weltraumbahnhof": "TSLC"}, {}, _erl_h, _sp_h)
check("Platzwechsel: Platz hand, Bahn berechnet",
      _m4["Weltraumbahnhof"] == ("JSLC", "hand") and _m4.get("Inklination", ("", ""))[1] == "berechnet"
      and _m4.get("Azimuth", ("", ""))[1] == "berechnet" and _m4.get("Orbit") == ("SSO", "berechnet"), _m4)
_z5, _m5, _ = app.archiv_zeile_bearbeiten(dict(_JSLC), {"Weltraumbahnhof": "TSLC", "Orbit": "GTO"}, {}, _erl_h, _sp_h)
check("Platzwechsel mit Hand-Orbit: Orbit bleibt hand", _z5["Orbit"] == "GTO" and _m5["Orbit"] == ("SSO", "hand"), _m5)
_z6, _m6, _ = app.archiv_zeile_bearbeiten(_z4, {"Weltraumbahnhof": "JSLC"}, _m4, _erl_h, _sp_h)
check("Platz zurueck: Bahnwerte zurueck, keine Markierung",
      _m6 == {} and all(_z6[s] == _JSLC[s] for s in ("Inklination", "Azimuth", "Orbit")), (_m6, _z6))
_ohne = dict(_HAIN, Dropzones="")
_z7, _m7, _h7 = app.archiv_zeile_bearbeiten(_ohne, {"Weltraumbahnhof": "WSLC"}, {}, _erl_h, _sp_h)
check("ohne Dropzones: Bahn leer + Hinweis", _z7["Inklination"] == "" and
      "no drop zones to compute the orbit from" in " ".join(_h7), _h7)
_sea = dict(_HAIN, Weltraumbahnhof="SEA-21N112E")
_z8, _m8, _h8 = app.archiv_zeile_bearbeiten(_sea, {"Payload": "x"}, {}, _erl_h, _sp_h)
check("aktueller Wert ausserhalb der Liste bleibt gueltig (SEA-Platz)", _z8["Weltraumbahnhof"] == "SEA-21N112E")
_z9, _m9, _h9 = app.archiv_zeile_bearbeiten(dict(_HAIN), {"Weltraumbahnhof": "KSS"}, {},
                                            app.archiv_erlaubt(_sp_h, _ve_h, "China"), _sp_h)
check("Platz passt nicht zur Nation: nur Hinweis", _z9["Weltraumbahnhof"] == "KSS" and
      any("nation" in h for h in _h9), _h9)

for _label, _neu in [("Nation", {"Nation": "Atlantis"}), ("Platz", {"Weltraumbahnhof": "XXXX"}),
                     ("Vehicle", {"Trägersystem": "NOPE-1"}), ("Trennzeile", {"Trägersystem": app.VEHICLE_SEPARATOR}),
                     ("Orbit", {"Orbit": "MARS"}), ("Payload", {"Payload": "=1"})]:
    try:
        app.archiv_zeile_bearbeiten(dict(_HAIN), _neu, {}, _erl_h, _sp_h); check("abgelehnt: " + _label, False)
    except app.ArchivEingabeFehler:
        check("abgelehnt: " + _label, True)

# Reset
_r1, _rm1 = app.archiv_feld_zuruecksetzen(_z5, _m5, "Weltraumbahnhof")
check("Reset Platz: berechnete zurueck, Hand-Orbit bleibt",
      _r1["Weltraumbahnhof"] == "JSLC" and _r1["Inklination"] == "98.0" and _rm1 == {"Orbit": ("SSO", "hand")}, _rm1)
_r2, _rm2 = app.archiv_feld_zuruecksetzen(_r1, _rm1, "Orbit")
check("Reset Orbit", _r2["Orbit"] == "SSO" and _rm2 == {})

# Index, Tabelle, Bereinigen, Ueberschneidung
_k = app.archive_key(_HAIN)
_hw_h = app.handwerte_mit(_pd_h.DataFrame(columns=list(app.nola_db.FACHTABELLEN["archiv_handwerte"])),
                          _k, _m4, "2026-10-15T00:00:00+00:00")
check("handwerte_mit/handwerte_index Rundweg", app.handwerte_index(_hw_h) == {_k: _m4})
check("handwerte_mit: leere Marken entfernen die Zeilen",
      app.handwerte_mit(_hw_h, _k, {}, "x").empty)
_ar_h = _pd_h.DataFrame([_HAIN, _TSLC])
check("bereinigen behaelt vorhandene", len(app.handwerte_bereinigen(_hw_h, _ar_h)) == len(_hw_h))
check("bereinigen entfernt verwaiste", app.handwerte_bereinigen(_hw_h, _pd_h.DataFrame([_TSLC])).empty)
_dup = dict(_HAIN, NOTAM="B0200/26")
_ar_d = _pd_h.DataFrame([_HAIN, _dup, _TSLC, dict(_TSLC, Startdatum="26.03.2026", NOTAM="B0200/26")])
check("Ueberschneidung: genau die beiden Zeilen desselben Datums",
      app.ueberschneidende_schluessel(_ar_d) == {app.archive_key(_HAIN), app.archive_key(_dup)})
```

- [ ] **Step 2: Laufen lassen – erwartet FAIL**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|Error|ERGEBNIS" | head`
Expected: `AttributeError: module 'app' has no attribute 'bahn_aus_platz'`.

- [ ] **Step 3: Implementierung (nach `merge_archive`)**

```python
#: Felder, die der Benutzer im Reiter Launch Archive von Hand aendern kann.
ARCHIV_EDIT_FELDER = ("Nation", "Weltraumbahnhof", "Trägersystem", "Payload", "Orbit")
#: Bahnwerte, die ein Platzwechsel neu berechnet.
BAHN_SPALTEN = ("Inklination", "Azimuth", "Orbit")
#: Auswahl fuer das Orbit-Feld - die Kurzformen des Archivs.
ORBIT_AUSWAHL = ("SSO", "HIGH-INC", "LEO/MEO", "GTO", "RETRO", "-")
PAYLOAD_MAX = 200
#: Anfaenge, die Excel beim Oeffnen der Export-CSV als Formel liest.
_PAYLOAD_FORMEL = ("=", "+", "@", "\t", "\r")
#: Unterhalb dieser Entfernung liegt eine Zone auf dem Platz - keine Richtung ableitbar.
_ZONE_AUF_PLATZ_KM = 1.0

Marken = Dict[str, Tuple[str, str]]


class ArchivEingabeFehler(ValueError):
    """Ein Wert im Bearbeiten-Formular ist nicht erlaubt - nichts wurde geschrieben."""


def handwerte_index(handwerte: pd.DataFrame) -> Dict[str, Marken]:
    """{Schluessel: {Spalte: (nola_wert, herkunft)}} aus der Tabelle archiv_handwerte."""
    index: Dict[str, Marken] = {}
    if handwerte is None or handwerte.empty:
        return index
    for _, r in handwerte.iterrows():
        index.setdefault(str(r["schluessel"]), {})[str(r["spalte"])] = (
            str(r["nola_wert"] or ""), str(r["herkunft"]))
    return index


def handwerte_mit(handwerte: pd.DataFrame, schluessel: str, marken: Marken, jetzt: str) -> pd.DataFrame:
    """
    Tabelle mit den Marken einer Zeile ersetzt. Unveraenderte Marken behalten
    ihren Zeitpunkt, neue oder geaenderte bekommen `jetzt`.
    """
    spalten = list(nola_db.FACHTABELLEN["archiv_handwerte"])
    alt = handwerte_index(handwerte).get(schluessel, {})
    zeit = {}
    if handwerte is not None and not handwerte.empty:
        for _, r in handwerte[handwerte["schluessel"] == schluessel].iterrows():
            zeit[str(r["spalte"])] = str(r["geaendert_utc"])
    andere = [] if handwerte is None or handwerte.empty else [
        {s: r[s] for s in spalten} for _, r in handwerte.iterrows() if str(r["schluessel"]) != schluessel]
    eigene = [
        {"schluessel": schluessel, "spalte": sp, "nola_wert": nola, "herkunft": herkunft,
         "geaendert_utc": zeit[sp] if alt.get(sp) == (nola, herkunft) and sp in zeit else jetzt}
        for sp, (nola, herkunft) in sorted(marken.items())
    ]
    return pd.DataFrame(andere + eigene, columns=spalten)


def handwerte_bereinigen(handwerte: pd.DataFrame, archiv: pd.DataFrame) -> pd.DataFrame:
    """Nur Marken, deren Zeile noch im Archiv steht - Markierungen folgen der Zeile."""
    if handwerte is None or handwerte.empty:
        return handwerte
    schluessel = {archive_key(dict(r)) for _, r in archiv.iterrows()}
    return handwerte[handwerte["schluessel"].isin(schluessel)].reset_index(drop=True)


def payload_bereinigen(text: str) -> str:
    """Zeilenumbrueche zu Leerzeichen; zu lang oder formelartig -> ArchivEingabeFehler."""
    wert = " ".join(str(text or "").replace("\r", "\n").split("\n")).strip()
    roh = str(text or "").lstrip(" ")
    if roh.startswith(_PAYLOAD_FORMEL) or wert.startswith(_PAYLOAD_FORMEL[:3]):
        raise ArchivEingabeFehler(
            "Payload must not start with =, +, @, a tab or a line break.")
    if len(wert) > PAYLOAD_MAX:
        raise ArchivEingabeFehler("Payload is longer than {} characters.".format(PAYLOAD_MAX))
    return wert


def _zonen(dropzones: str) -> List[Tuple[float, float]]:
    """'lat lon; lat lon' -> Punkte; unlesbare Teile fallen weg."""
    punkte = []
    for teil in str(dropzones or "").split(";"):
        zahlen = teil.split()
        if len(zahlen) != 2:
            continue
        try:
            lat, lon = float(zahlen[0]), float(zahlen[1])
        except ValueError:
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            punkte.append((lat, lon))
    return punkte


def bahn_aus_platz(lat: float, lon: float, dropzones: str) -> Tuple[str, str, str, str]:
    """
    Inklination, Azimuth und Orbit eines Archivstarts von einem anderen Platz aus -
    dasselbe Verfahren wie die Pipeline (Kreismittel der Zonen-Azimute).
    Rueckgabe: (Inklination, Azimuth, Orbit, Hinweis); ohne Rechnung ("", "", "-", Grund).
    """
    zonen = _zonen(dropzones)
    if not zonen:
        return "", "", "-", "no drop zones to compute the orbit from"
    if any(surface_distance_km(lat, lon, a, b) < _ZONE_AUF_PLATZ_KM for a, b in zonen):
        return "", "", "-", "zone on the launch site"
    azimut = _circular_mean([initial_bearing_deg(lat, lon, a, b) for a, b in zonen])
    inklination = estimate_inclination_deg(lat, azimut)
    return ("{:.1f}".format(inklination), "{:.1f}".format(azimut),
            orbit_short(classify_orbit(inklination)), "")


def archiv_erlaubt(spaceports: pd.DataFrame, vehicles: pd.DataFrame, nation: str) -> Dict[str, List[str]]:
    """Auswahllisten des Formulars; Plaetze und Traeger der Nation zuerst."""
    codes = [str(c) for c in spaceports["Kurzel"]]
    laender = [str(l) for l in spaceports["Land"]]
    plaetze = [c for c, l in zip(codes, laender) if l == nation] + [
        c for c, l in zip(codes, laender) if l != nation]
    return {
        "Nation": list(TARGET_NATIONS),
        "Weltraumbahnhof": plaetze,
        "Trägersystem": [v for v in vehicle_options(vehicles, nation) if v != VEHICLE_SEPARATOR],
        "Orbit": list(ORBIT_AUSWAHL),
    }


def _platz_der_referenz(spaceports: pd.DataFrame, code: str) -> Optional[pd.Series]:
    treffer = spaceports[spaceports["Kurzel"].astype(str) == str(code)]
    if treffer.empty:
        return None
    r = treffer.iloc[0]
    try:
        float(r["Latitude"]); float(r["Longitude"])
    except (TypeError, ValueError):
        return None
    return r


def archiv_zeile_bearbeiten(
    zeile: Dict[str, str],
    neu: Dict[str, str],
    marken: Marken,
    erlaubt: Dict[str, Sequence[str]],
    spaceports: pd.DataFrame,
) -> Tuple[Dict[str, str], Marken, List[str]]:
    """
    Wendet die Formularwerte auf eine Archivzeile an. Nur geaenderte Felder
    werden markiert; der NOLA-Wert ist der vor der ersten Handaenderung. Ein
    Feld zurueck auf seinen NOLA-Wert verliert die Markierung. Ein Platzwechsel
    berechnet Inklination, Azimuth und (ohne Hand-Orbit) Orbit neu.
    Unerlaubte Werte: ArchivEingabeFehler, nichts geaendert.
    Rueckgabe: (neue Zeile, neue Marken, Hinweise).
    """
    zeile = {s: str(zeile.get(s, "") or "") for s in ARCHIVE_COLUMNS}
    werte: Dict[str, str] = {}
    for feld, wert in neu.items():
        if feld not in ARCHIV_EDIT_FELDER:
            raise ArchivEingabeFehler("{} cannot be edited.".format(feld))
        wert = str(wert if wert is not None else "")
        if feld == "Payload":
            if wert != zeile["Payload"]:
                wert = payload_bereinigen(wert)
        elif wert != zeile[feld] and wert not in erlaubt.get(feld, ()):
            raise ArchivEingabeFehler("{} is not an allowed value for {}.".format(wert, feld))
        werte[feld] = wert
    geaendert = {f: w for f, w in werte.items() if w != zeile[f]}
    marken = dict(marken)
    hinweise: List[str] = []
    if not geaendert:
        return zeile, marken, hinweise

    def setze(spalte: str, wert: str, herkunft: str) -> None:
        nola = marken[spalte][0] if spalte in marken else zeile[spalte]
        if wert == nola:
            marken.pop(spalte, None)
        else:
            marken[spalte] = (nola, herkunft)
        zeile[spalte] = wert

    for feld, wert in geaendert.items():
        if feld != "Orbit":
            setze(feld, wert, "hand")
    if "Weltraumbahnhof" in geaendert:
        if "Weltraumbahnhof" not in marken:
            # zurueck auf den urspruenglichen Platz: berechnete Werte zurueck
            for spalte, (nola, herkunft) in list(marken.items()):
                if herkunft == "berechnet":
                    zeile[spalte] = nola
                    marken.pop(spalte)
        else:
            port = _platz_der_referenz(spaceports, zeile["Weltraumbahnhof"])
            if port is None:
                hinweise.append("launch site has no coordinates in the reference - orbit not recomputed")
            else:
                ink, azi, orbit, hinweis = bahn_aus_platz(
                    float(port["Latitude"]), float(port["Longitude"]), zeile["Dropzones"])
                if hinweis:
                    hinweise.append(hinweis)
                setze("Inklination", ink, "berechnet")
                setze("Azimuth", azi, "berechnet")
                if "Orbit" not in geaendert and marken.get("Orbit", ("", ""))[1] != "hand":
                    setze("Orbit", orbit, "berechnet")
                if str(port["Land"]) != zeile["Nation"]:
                    hinweise.append("launch site {} belongs to {}, the nation is {}".format(
                        zeile["Weltraumbahnhof"], nation_label(str(port["Land"])), nation_label(zeile["Nation"])))
    if "Orbit" in geaendert:
        setze("Orbit", geaendert["Orbit"], "hand")
    return zeile, marken, hinweise


def archiv_feld_zuruecksetzen(zeile: Dict[str, str], marken: Marken, spalte: str) -> Tuple[Dict[str, str], Marken]:
    """Ein Feld auf seinen NOLA-Wert; der Platz nimmt alle berechneten Werte mit."""
    zeile = dict(zeile)
    marken = dict(marken)
    if spalte not in marken:
        return zeile, marken
    zeile[spalte] = marken.pop(spalte)[0]
    if spalte == "Weltraumbahnhof":
        for sp, (nola, herkunft) in list(marken.items()):
            if herkunft == "berechnet":
                zeile[sp] = nola
                marken.pop(sp)
    return zeile, marken


def ueberschneidende_schluessel(archiv: pd.DataFrame) -> Set[str]:
    """Zeilen, die mit einer anderen Zeile desselben Startdatums eine NOTAM-Kennung teilen."""
    nach_datum: Dict[str, List[Tuple[str, Set[str]]]] = {}
    for _, r in archiv.iterrows():
        kennungen = {t.strip().upper() for t in str(r["NOTAM"]).split(",") if t.strip()}
        nach_datum.setdefault(str(r["Startdatum"]).strip(), []).append((archive_key(dict(r)), kennungen))
    treffer: Set[str] = set()
    for zeilen in nach_datum.values():
        for i, (ka, ia) in enumerate(zeilen):
            for kb, ib in zeilen[i + 1:]:
                if ia & ib:
                    treffer.update((ka, kb))
    return treffer
```

Hinweis zur Payload-Prüfung: `roh.startswith(_PAYLOAD_FORMEL)` prüft den ungekürzten Text (Tab/CR am Anfang), `wert.startswith(...)` den bereinigten (`=`, `+`, `@`).

- [ ] **Step 4: Tests laufen lassen – erwartet PASS**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|ERGEBNIS"`
Expected: nur „ERGEBNIS: ALLE TESTS BESTANDEN“. Schlägt eine Selbstprobe fehl: Zahlen ausgeben lassen und mit der Pipeline (`app.py` ~3589, `group.azimuth_deg = _circular_mean(azimuths)`) vergleichen – nicht die Toleranz vergrößern.

- [ ] **Step 5: Commit (falls erlaubt)**

```bash
git add app.py test_app.py
git commit -m "Archiv-Handwerte Aufgabe 2: Bearbeitungslogik, Neuberechnung, Pruefungen (<bead>)"
```

---

### Task 3: Alle Schreibwege beachten die Markierungen (Tageslauf, Entfernen, Import, Undo)

**Files:**
- Modify: `app.py` – `merge_archive` (4823), neue Helfer nach `archiv_und_importzustand_schreiben` (~5146), `_push_undo`/`_undo_reference` (5753–5795), `_update_archive` (6503–6567), `_remove_archive_row` (6724–6753)
- Modify: `archiv_import.py` – `_archiv_und_zustand_schreiben` (1221), `remove_orphan` (1288), `confirm_many` (1445)
- Test: `test_app.py`

**Interfaces:**
- Consumes: Task 1 (`lese_tabellen`, `ersetze_tabellen_geprueft`, `ersetze_archiv_und_importzustand(..., handwerte=)`), Task 2 (`handwerte_index`, `handwerte_bereinigen`).
- Produces:
  - `merge_archive(bestand, neue, entfernt=None, handwerte: Optional[Mapping[str, Iterable[str]]] = None) -> pd.DataFrame`
  - `archiv_mit_handwerten_lesen(db: Optional[Path] = None, wartezeit: float = nola_db.WARTEZEIT) -> Tuple[pd.DataFrame, pd.DataFrame]` (Lesefehler → `ArchiveUnreadable`)
  - `archiv_und_handwerte_schreiben(neu: pd.DataFrame, neu_hw: pd.DataFrame, vorher: pd.DataFrame, vorher_hw: pd.DataFrame, db: Optional[Path] = None, wartezeit: float = nola_db.WARTEZEIT) -> Dict[str, str]`
  - `archiv_und_importzustand_schreiben(neu, vorher, zustand, zustand_erwartet, db=None, handwerte: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None)` – `handwerte = (neu_hw, vorher_hw)`
  - `_push_undo(tabelle, vorher, nachher_stand, label, weitere: Optional[Sequence[Tuple[str, pd.DataFrame, str]]] = None)`; Eintrag erhält Schlüssel `"weitere": [{"tabelle", "zeilen", "nachher"}]`.

**Acceptance Criteria:**
- `merge_archive` mit Markierungen: markierte Spalte bleibt aus dem Bestand, unmarkierte wird aktualisiert; Trägersystem/Payload-Sonderregel unverändert; ohne `handwerte` identisch zu heute.
- `_update_archive`: ein Handwert überlebt einen Tageslauf (über die DB geprüft); ändert sich zwischen Lesen und Schreiben nur die Handwert-Tabelle, gilt das als Konflikt und der Lauf liest neu.
- `_remove_archive_row`: löscht Zeile und ihre Markierungen in einer Transaktion; Undo stellt beide wieder her; Undo nach fremder Änderung an **einer** der beiden Tabellen → verweigert, nichts geändert.
- Alte Undo-Einträge mit einer Tabelle funktionieren unverändert.
- `confirm_many`: ergänzt keine markierten Felder; ersetzte Zeilen verlieren ihre Markierungen; fremde Änderung an den Markierungen → `ImportStateError`, nichts geschrieben.
- `remove_orphan`: löscht die Markierungen der Zeile mit.

- [ ] **Step 1: Failing tests in `test_app.py`** (neuer Abschnitt nach dem Logik-Abschnitt aus Task 2)

```python
print("== Archiv von Hand bearbeiten: Schreibwege ==")
_hwsp = list(app.nola_db.FACHTABELLEN["archiv_handwerte"])
_alt_m = {"NOTAM": "Z7001/26", "Startdatum": "01.10.2026", "Startzeit": "01:00", "Nation": "China",
          "Weltraumbahnhof": "WSLC", "Trägersystem": "", "Payload": "", "Orbit": "LEO/MEO",
          "Inklination": "41.0", "Azimuth": "120.0", "Dropzones": ""}
_k_m = app.archive_key(_alt_m)
_hand = {_k_m: {"Weltraumbahnhof", "Orbit"}}
_neuer_lauf = dict(_alt_m, Weltraumbahnhof="WSLC", Orbit="SSO", Inklination="97.0", Startzeit="02:00")
_bestand_m = _pd_h.DataFrame([dict(_alt_m, Weltraumbahnhof="HAIN", Orbit="GTO")])
_m_erg = app.merge_archive(_bestand_m, [_neuer_lauf], set(), _hand).iloc[0]
check("merge: markierte Spalten bleiben", _m_erg["Weltraumbahnhof"] == "HAIN" and _m_erg["Orbit"] == "GTO")
check("merge: unmarkierte aktualisiert", _m_erg["Startzeit"] == "02:00" and _m_erg["Inklination"] == "97.0")
check("merge ohne handwerte wie bisher",
      app.merge_archive(_bestand_m, [_neuer_lauf], set()).iloc[0]["Weltraumbahnhof"] == "WSLC")

_st_orig_m = app.st; app.st = _StR()
_db_orig_m = app.DB_PATH
_lab_orig_m = app.local_admin_allowed
try:
    app.DB_PATH = _kopie_der_test_db()
    _a, _h = app.archiv_mit_handwerten_lesen()
    check("lesen: beide mit Stand", "nola_stand" in _a.attrs and "nola_stand" in _h.attrs)
    _a2 = app.merge_archive(_a, [dict(_alt_m, Weltraumbahnhof="HAIN")], set())
    _h2 = app.handwerte_mit(_h, _k_m, {"Weltraumbahnhof": ("WSLC", "hand")}, "2026-10-15T00:00:00+00:00")
    app.archiv_und_handwerte_schreiben(_a2, _h2, _a, _h)
    # Tageslauf liefert WSLC - Handwert HAIN muss bleiben
    _a3, _h3 = app.archiv_mit_handwerten_lesen()
    _lauf = app.merge_archive(_a3, [_alt_m], set(),
                              {k: set(v) for k, v in app.handwerte_index(_h3).items()})
    app.archiv_und_handwerte_schreiben(_lauf, _h3, _a3, _h3)
    _nach = app.archiv_lesen()
    check("Handwert ueberlebt den Lauf",
          _nach[_nach["NOTAM"] == "Z7001/26"].iloc[0]["Weltraumbahnhof"] == "HAIN")
    # Konflikt nur ueber die Handwerte
    _a4, _h4 = app.archiv_mit_handwerten_lesen()
    with app._db() as _c:
        app.nola_db.ersetze_tabelle(_c, "archiv_handwerte", _h4.iloc[0:0], _h4.attrs["nola_stand"])
    try:
        app.archiv_und_handwerte_schreiben(_a4, _h4, _a4, _h4); check("fremde Handwert-Aenderung -> Konflikt", False)
    except app.nola_db.Konflikt:
        check("fremde Handwert-Aenderung -> Konflikt", True)
    # wieder markieren fuer Entfernen/Undo
    _a5, _h5 = app.archiv_mit_handwerten_lesen()
    app.archiv_und_handwerte_schreiben(_a5, app.handwerte_mit(_h5, _k_m, {"Weltraumbahnhof": ("WSLC", "hand")}, "t"), _a5, _h5)
    app._remove_archive_row(_k_m)
    _a6, _h6 = app.archiv_mit_handwerten_lesen()
    check("Entfernen loescht Zeile und Markierung",
          "Z7001/26" not in set(_a6["NOTAM"]) and _k_m not in set(_h6["schluessel"]))
    app._undo_reference()
    _a7, _h7 = app.archiv_mit_handwerten_lesen()
    check("Undo stellt Zeile und Markierung wieder her",
          "Z7001/26" in set(_a7["NOTAM"]) and _k_m in set(_h7["schluessel"]))
    app._remove_archive_row(_k_m)
    _a8, _h8 = app.archiv_mit_handwerten_lesen()
    with app._db() as _c:
        app.nola_db.ersetze_tabelle(_c, "archiv_handwerte",
                                    app.handwerte_mit(_h8, "x|y", {"Nation": ("China", "hand")}, "t"),
                                    _h8.attrs["nola_stand"])
    try:
        app._undo_reference(); check("Undo nach fremder Handwert-Aenderung verweigert", False)
    except app.UndoRefused:
        _a9, _ = app.archiv_mit_handwerten_lesen()
        check("Undo nach fremder Handwert-Aenderung verweigert", "Z7001/26" not in set(_a9["NOTAM"]))
finally:
    app.st = _st_orig_m
    app.DB_PATH = _db_orig_m
    app.local_admin_allowed = _lab_orig_m
```

Für den Tageslauf über `_update_archive` (Konflikt nur über Handwerte, einmal neu lesen) und den Import (`confirm_many` ergänzt keine markierten Felder; fremde Markierungsänderung → `ImportStateError`; `remove_orphan` löscht Markierung): in den vorhandenen Abschnitten „Lokale Datenbank: Archiv und Seestarts“ bzw. bei den `confirm_many`/`remove_orphan`-Tests (`grep -n "confirm_many(\|remove_orphan(" test_app.py`) je einen Fall ergänzen, nach dem Muster der dortigen Zwei-Tab-Konflikttests (`ImportStateError` mit Text „The launch archive changed meanwhile“; Prüfsumme des Archivs vorher = nachher). Für `confirm_many` vorher per `archiv_und_handwerte_schreiben` die Spalte `Payload` der Zielzeile markieren, dann einen `im_archiv`-Kandidaten mit Payload bestätigen und prüfen, dass die Payload unverändert ist.

- [ ] **Step 2: Laufen lassen – erwartet FAIL**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|Error" | head`
Expected: `TypeError: merge_archive() takes from 2 to 3 positional arguments` bzw. fehlendes `archiv_mit_handwerten_lesen`.

- [ ] **Step 3: `merge_archive`**

Signatur um `handwerte: Optional[Mapping[str, Iterable[str]]] = None` erweitern (Docstring: „Von Hand gesetzte Spalten (`handwerte`: {Schluessel: Spalten}) uebernimmt ein Lauf aus dem Bestand.“) und im Zweig für eine bekannte Zeile nach der Payload/Trägersystem-Schleife:

```python
            for spalte in (handwerte or {}).get(schluessel, ()):
                row[spalte] = alt[spalte]
```

`Iterable`/`Mapping` aus `typing` importieren, falls noch nicht vorhanden.

- [ ] **Step 4: Lese-/Schreibhelfer (nach `archiv_und_importzustand_schreiben`)**

```python
def archiv_mit_handwerten_lesen(
    db: Optional[Path] = None, wartezeit: float = nola_db.WARTEZEIT
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Startarchiv und Handwerte aus EINER Momentaufnahme; Lesefehler -> ArchiveUnreadable."""
    try:
        with _db(db, wartezeit) as conn:
            beide = nola_db.lese_tabellen(conn, ("startarchiv", "archiv_handwerte"))
    except nola_db.DbFehler as exc:
        raise ArchiveUnreadable(
            "The launch archive could not be read from the database ({}). It was left "
            "untouched and not updated.".format(exc)
        ) from exc
    return beide["startarchiv"], beide["archiv_handwerte"]


def archiv_und_handwerte_schreiben(
    neu: pd.DataFrame, neu_hw: pd.DataFrame, vorher: pd.DataFrame, vorher_hw: pd.DataFrame,
    db: Optional[Path] = None, wartezeit: float = nola_db.WARTEZEIT,
) -> Dict[str, str]:
    """Archiv und Handwerte gemeinsam - nur, wenn beide noch dem gelesenen Stand entsprechen."""
    stand, stand_hw = vorher.attrs.get("nola_stand"), vorher_hw.attrs.get("nola_stand")
    if not stand or not stand_hw:
        raise ValueError("archiv_und_handwerte_schreiben needs `vorher` as read by archiv_mit_handwerten_lesen")
    spalten_hw = list(nola_db.FACHTABELLEN["archiv_handwerte"])
    with _db(db, wartezeit) as conn:
        return nola_db.ersetze_tabellen_geprueft(conn, {
            "startarchiv": (neu[list(ARCHIVE_COLUMNS)], stand),
            "archiv_handwerte": (neu_hw[spalten_hw] if not neu_hw.empty else pd.DataFrame(columns=spalten_hw), stand_hw),
        })
```

`archiv_und_importzustand_schreiben` um `handwerte: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None` erweitern und weiterreichen:

```python
    hw = None
    if handwerte is not None:
        neu_hw, vorher_hw = handwerte
        hw = (neu_hw[list(nola_db.FACHTABELLEN["archiv_handwerte"])], vorher_hw.attrs["nola_stand"])
    with _db(db) as conn:
        return nola_db.ersetze_archiv_und_importzustand(
            conn, neu[list(ARCHIVE_COLUMNS)], stand, zustand, zustand_erwartet, handwerte=hw)
```

- [ ] **Step 5: Undo über mehrere Tabellen**

```python
def _push_undo(
    tabelle: str, vorher: pd.DataFrame, nachher_stand: str, label: str,
    weitere: Optional[Sequence[Tuple[str, pd.DataFrame, str]]] = None,
) -> Dict[str, Any]:
    """
    Merkt den Tabelleninhalt vor und den Stand nach einer Aenderung. `weitere`:
    Tabellen, die in derselben Transaktion geaendert wurden (Tabelle, vorher, Stand nachher).
    """
    stapel = st.session_state.setdefault("ref_undo", [])
    eintrag = {
        "tabelle": tabelle,
        "zeilen": vorher[list(_spalten_von(tabelle))].to_dict("records"),
        "nachher": nachher_stand,
        "label": label,
    }
    if weitere:
        eintrag["weitere"] = [
            {"tabelle": t, "zeilen": df[list(_spalten_von(t))].to_dict("records"), "nachher": n}
            for t, df, n in weitere
        ]
    stapel.append(eintrag)
    del stapel[:-UNDO_LIMIT]
    return eintrag
```

In `_undo_reference` den `ersetze_tabelle`-Aufruf ersetzen durch:

```python
        with _db() as conn:
            teile = [letzter] + list(letzter.get("weitere", []))
            if len(teile) == 1:
                nola_db.ersetze_tabelle(
                    conn, tabelle, pd.DataFrame(letzter["zeilen"], columns=list(_spalten_von(tabelle))),
                    letzter["nachher"],
                )
            else:
                nola_db.ersetze_tabellen_geprueft(conn, {
                    t["tabelle"]: (pd.DataFrame(t["zeilen"], columns=list(_spalten_von(t["tabelle"]))), t["nachher"])
                    for t in teile
                })
```

- [ ] **Step 6: `_update_archive` und `_remove_archive_row`**

`_update_archive`: `bestand = archiv_lesen(wartezeit=WARTEZEIT_AUTOMATISCH)` → `bestand, bestand_hw = archiv_mit_handwerten_lesen(wartezeit=WARTEZEIT_AUTOMATISCH)`; `merge_archive(bestand, zeilen, set(...), {k: set(v) for k, v in handwerte_index(bestand_hw).items()})`; `archiv_schreiben(neu, vorher=bestand, wartezeit=...)` → `archiv_und_handwerte_schreiben(neu, bestand_hw, bestand, bestand_hw, wartezeit=WARTEZEIT_AUTOMATISCH)`. Konflikt-/Gesperrt-/Fehlerzweige bleiben.

`_remove_archive_row`:

```python
    try:
        bestand, bestand_hw = archiv_mit_handwerten_lesen()
    except ArchiveUnreadable as exc:
        _melde_db_dialog("error", "Launch archive: {} Nothing was removed.".format(exc))
        return
    behalten = bestand[[archive_key(dict(r)) != schluessel for _, r in bestand.iterrows()]]
    behalten_hw = handwerte_bereinigen(bestand_hw, behalten)
    try:
        neu = archiv_und_handwerte_schreiben(behalten, behalten_hw, bestand, bestand_hw)
    except nola_db.Konflikt:
        _melde_db_dialog("warning", nola_db.KONFLIKT_TEXT)
        return
    except nola_db.DbFehler as exc:
        _melde_db_dialog("error", "Launch archive: {} Nothing was removed.".format(exc))
        return
    _push_undo("startarchiv", bestand, neu["startarchiv"], "Archivzeile entfernt",
               weitere=[("archiv_handwerte", bestand_hw, neu["archiv_handwerte"])])
```

(Rest der Funktion unverändert.)

- [ ] **Step 7: `archiv_import.py`**

`_archiv_und_zustand_schreiben` bekommt `handwerte: Optional[Tuple[pd.DataFrame, pd.DataFrame]] = None` und reicht ihn an `app.archiv_und_importzustand_schreiben(..., handwerte=handwerte)` weiter.

Neuer Leser:

```python
def _archiv_und_handwerte_lesen(archiv: Optional[Path] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Wie _archiv_lesen, dazu die Handwerte aus derselben Momentaufnahme."""
    try:
        return app.archiv_mit_handwerten_lesen(archiv)
    except app.ArchiveUnreadable as exc:
        raise ImportStateError(str(exc)) from exc
```

`remove_orphan`: `bestand = _archiv_lesen(archiv)` → `bestand, bestand_hw = _archiv_und_handwerte_lesen(archiv)`; Schreiben mit `handwerte=(app.handwerte_bereinigen(bestand_hw, gefiltert), bestand_hw)`.

`confirm_many`: ebenso lesen; `marken = app.handwerte_index(bestand_hw)`; in der Ergänzen-Schleife `if wert and spalte not in marken.get(ziel, {}):`; `app.merge_archive(bestand, zeilen, entfernt=set(), handwerte={k: set(v) for k, v in marken.items()})` als `neues_archiv`; Schreiben mit `handwerte=(app.handwerte_bereinigen(bestand_hw, neues_archiv), bestand_hw)`.

- [ ] **Step 8: Tests laufen lassen – erwartet PASS**

Run: `.venv/bin/python test_nola_db.py 2>&1 | tail -1 && .venv/bin/python test_app.py 2>&1 | tail -1`
Expected: beide „ERGEBNIS: ALLE TESTS BESTANDEN“. Tests, die `app.archiv_lesen` stubben, um `_update_archive`/`_remove_archive_row` zu prüfen (`grep -n "app.archiv_lesen = " test_app.py`), auf `archiv_mit_handwerten_lesen` umstellen – Verhalten unverändert.

- [ ] **Step 9: Commit (falls erlaubt)**

```bash
git add app.py archiv_import.py test_app.py
git commit -m "Archiv-Handwerte Aufgabe 3: Tageslauf, Entfernen, Import und Undo beachten die Markierungen (<bead>)"
```

---

### Task 4: Reiter *Launch Archive* – Blättern, Marken, Bearbeiten, Reset

**Files:**
- Modify: `app.py` – `_reference_row` (5892), `_archive_editor` (6756–6815), Aufruf im Reference-Dialog (6162), neue Callbacks nach `_remove_archive_row`
- Test: `test_app.py`; Browser-Test an einer Kopie

**Interfaces:**
- Consumes: Tasks 2 und 3.
- Produces:
  - `_reference_row(werte, breiten, header=False, hilfen: Optional[Sequence[Optional[str]]] = None)`
  - `_archive_editor(spaceports: pd.DataFrame, vehicles: pd.DataFrame) -> None`
  - `ARCHIV_SEITE = 50`
  - `_archiv_sortiert(archiv: pd.DataFrame) -> pd.DataFrame` (neuestes Startdatum zuerst, Datum geparst)
  - `_archiv_aendern(schluessel: str, aendern: Callable[[Dict[str, str], Marken], Tuple[Dict[str, str], Marken, List[str]]], label: str) -> bool`
  - `_archiv_edit_speichern(schluessel: str, neu: Dict[str, str], spaceports: pd.DataFrame, vehicles: pd.DataFrame) -> bool`
  - `_archiv_reset_klick(schluessel: str, spalte: str) -> bool`
  - `ARCHIV_EDIT_NUR_LOKAL = "Editing the launch archive is only possible on this computer."`

**Acceptance Criteria:**
- Alle Zeilen erreichbar: 50 je Seite, neuestes Datum zuerst, Suche filtert vor dem Blättern; Seite in `session_state["archiv_seite"]`.
- ✎ an `hand`-Feldern, ↻ an `berechnet`-Feldern (Tooltip „NOLA: <wert>“), ⚠ an überschneidenden Zeilen.
- Edit öffnet unter der Zeile ein Formular (kein `st.form`), höchstens eines offen; Save schreibt in einer Transaktion, Cancel verwirft; Reset je `hand`-Feld (berechnete Werte setzt der Reset des Platzes mit zurück – einzeln zurückgesetzt passten sie nicht mehr zum Platz).
- Konflikt → `KONFLIKT_TEXT` im Dialog, nichts geschrieben; ungültiger Wert → Meldung im Dialog, nichts geschrieben; Hinweise erscheinen als Warnung.
- Ein Undo-Eintrag je Speichern/Reset nimmt Zeile und Markierungen zurück.
- Ohne `local_admin_allowed()`: keine Edit-/Reset-Knöpfe; `_archiv_edit_speichern`/`_archiv_reset_klick` verweigern mit `ARCHIV_EDIT_NUR_LOKAL`, nichts geschrieben.
- Browser-Test an einer Kopie: Edit öffnen, Platz ändern, Inklination neu, ✎/↻ sichtbar, Reset, Undo.

- [ ] **Step 1: Failing tests in `test_app.py`**

```python
print("== Archiv von Hand bearbeiten: Oberflaeche ==")
_st_orig_u = app.st; app.st = _StR()
_db_orig_u = app.DB_PATH
_lab_orig_u = app.local_admin_allowed
try:
    app.DB_PATH = _kopie_der_test_db()
    _sp_u, _ve_u = app.referenz_lesen("startplaetze"), app.referenz_lesen("traegersysteme")
    _a, _h = app.archiv_mit_handwerten_lesen()
    app.archiv_und_handwerte_schreiben(app.merge_archive(_a, [dict(_HAIN), dict(_JSLC)], set()), _h, _a, _h)
    _k_u = app.archive_key(_HAIN)
    _k_j = app.archive_key(_JSLC)
    app.local_admin_allowed = lambda: True
    check("Speichern JSLC->TSLC: Bahn als berechnet markiert",
          app._archiv_edit_speichern(_k_j, {"Weltraumbahnhof": "TSLC"}, _sp_u, _ve_u) is True
          and app.handwerte_index(app.archiv_mit_handwerten_lesen()[1])[_k_j]["Inklination"][1] == "berechnet")
    app.local_admin_allowed = lambda: True
    check("Speichern ok", app._archiv_edit_speichern(_k_u, {"Weltraumbahnhof": "WSLC"}, _sp_u, _ve_u) is True)
    _a1, _h1 = app.archiv_mit_handwerten_lesen()
    _z_u = _a1[_a1["NOTAM"] == _HAIN["NOTAM"]].iloc[0]
    check("Speichern: Platz geschrieben und markiert",
          _z_u["Weltraumbahnhof"] == "WSLC" and app.handwerte_index(_h1)[_k_u]["Weltraumbahnhof"] == ("HAIN", "hand"))
    check("Speichern: ein Undo-Eintrag mit zwei Tabellen",
          app.st.session_state["ref_undo"][-1].get("weitere", [{}])[0].get("tabelle") == "archiv_handwerte")
    check("Reset ok", app._archiv_reset_klick(_k_u, "Weltraumbahnhof") is True)
    _a2, _h2 = app.archiv_mit_handwerten_lesen()
    check("Reset: Platz zurueck, keine Markierung",
          _a2[_a2["NOTAM"] == _HAIN["NOTAM"]].iloc[0]["Weltraumbahnhof"] == "HAIN" and _k_u not in app.handwerte_index(_h2))
    app._undo_reference()
    _a3, _h3 = app.archiv_mit_handwerten_lesen()
    check("Undo nach Reset: WSLC und Markierung wieder da",
          _a3[_a3["NOTAM"] == _HAIN["NOTAM"]].iloc[0]["Weltraumbahnhof"] == "WSLC" and _k_u in app.handwerte_index(_h3))
    app.st.session_state.pop("ref_flash_error", None)
    check("ungueltiger Wert: verweigert",
          app._archiv_edit_speichern(_k_u, {"Orbit": "MARS"}, _sp_u, _ve_u) is False
          and "allowed" in app.st.session_state.get("ref_flash_error", ""))
    # Konflikt: Archiv zwischen Lesen und Schreiben fremd geaendert
    _orig_lesen_u = app.archiv_mit_handwerten_lesen
    def _lesen_und_stoeren(*a, **k):
        _ar, _hw = _orig_lesen_u(*a, **k)
        _x, _y = _orig_lesen_u()
        app.archiv_und_handwerte_schreiben(app.merge_archive(_x, [dict(_TSLC)], set()), _y, _x, _y)
        return _ar, _hw
    app.archiv_mit_handwerten_lesen = _lesen_und_stoeren
    try:
        _vor_u = app.archiv_lesen()[lambda d: d["NOTAM"] == _HAIN["NOTAM"]].iloc[0]["Payload"]
        check("Konflikt: verweigert", app._archiv_edit_speichern(_k_u, {"Payload": "Konflikt"}, _sp_u, _ve_u) is False
              and app.st.session_state.get("ref_flash_warning") == app.nola_db.KONFLIKT_TEXT)
    finally:
        app.archiv_mit_handwerten_lesen = _orig_lesen_u
    check("Konflikt: nichts geschrieben",
          app.archiv_lesen()[lambda d: d["NOTAM"] == _HAIN["NOTAM"]].iloc[0]["Payload"] == _vor_u)
    app.local_admin_allowed = lambda: False
    check("nicht lokal: Speichern verweigert",
          app._archiv_edit_speichern(_k_u, {"Payload": "x"}, _sp_u, _ve_u) is False
          and app.st.session_state.get("ref_flash_error") == app.ARCHIV_EDIT_NUR_LOKAL)
    check("nicht lokal: Reset verweigert", app._archiv_reset_klick(_k_u, "Weltraumbahnhof") is False)
    # Sortierung und Seiten
    _df_s = _pd_h.DataFrame([dict(_HAIN, Startdatum="02.01.2026"), dict(_HAIN, Startdatum="10.12.2025"),
                             dict(_HAIN, Startdatum="15.03.2026")])
    check("sortiert: neuestes Datum zuerst (nicht als Text)",
          list(app._archiv_sortiert(_df_s)["Startdatum"]) == ["15.03.2026", "02.01.2026", "10.12.2025"])
finally:
    app.st = _st_orig_u
    app.DB_PATH = _db_orig_u
    app.local_admin_allowed = _lab_orig_u
import inspect as _ins_u
_src_u = _ins_u.getsource(app._archive_editor)
check("Editor: kein st.form, kein head(60), Blaettern, Freigabe",
      "st.form" not in _src_u and "head(60)" not in _src_u and "ARCHIV_SEITE" in _src_u
      and "local_admin_allowed()" in _src_u and "_md_plain(" in _src_u)
```

- [ ] **Step 2: Laufen lassen – erwartet FAIL**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|Error" | head`
Expected: `AttributeError: ... '_archiv_edit_speichern'`.

- [ ] **Step 3: Callbacks (nach `_remove_archive_row`)**

```python
ARCHIV_EDIT_NUR_LOKAL = "Editing the launch archive is only possible on this computer."
ARCHIV_ZEILE_FEHLT = "This launch is no longer in the archive - nothing was changed."


def _archiv_aendern(
    schluessel: str,
    aendern: Callable[[Dict[str, str], "Marken"], Tuple[Dict[str, str], "Marken", List[str]]],
    label: str,
) -> bool:
    """
    Gemeinsamer Weg fuer Speichern und Reset: lesen, anwenden, Zeile und Marken
    in EINER Transaktion schreiben, ein Undo-Eintrag. Meldungen im Dialog.
    """
    if not local_admin_allowed():  # auch hier, nicht nur in der Oberflaeche
        _melde_db_dialog("error", ARCHIV_EDIT_NUR_LOKAL)
        return False
    try:
        bestand, bestand_hw = archiv_mit_handwerten_lesen()
    except ArchiveUnreadable as exc:
        _melde_db_dialog("error", "Launch archive: {} Nothing was changed.".format(exc))
        return False
    positionen = [i for i, (_, r) in enumerate(bestand.iterrows()) if archive_key(dict(r)) == schluessel]
    if not positionen:
        _melde_db_dialog("warning", ARCHIV_ZEILE_FEHLT)
        return False
    pos = positionen[0]
    zeile = {s: str(bestand.iloc[pos][s]) for s in ARCHIVE_COLUMNS}
    try:
        neue_zeile, marken, hinweise = aendern(zeile, handwerte_index(bestand_hw).get(schluessel, {}))
    except ArchivEingabeFehler as exc:
        _melde_db_dialog("error", str(exc))
        return False
    neu = bestand.copy()
    for spalte in ARCHIVE_COLUMNS:
        neu.iat[pos, neu.columns.get_loc(spalte)] = neue_zeile[spalte]
    neu_hw = handwerte_mit(bestand_hw, schluessel, marken, datetime.now(timezone.utc).isoformat())
    try:
        staende = archiv_und_handwerte_schreiben(neu, neu_hw, bestand, bestand_hw)
    except nola_db.Konflikt:
        _melde_db_dialog("warning", nola_db.KONFLIKT_TEXT)
        return False
    except nola_db.DbFehler as exc:
        _melde_db_dialog("error", "Launch archive: {} Nothing was changed.".format(exc))
        return False
    _push_undo("startarchiv", bestand, staende["startarchiv"], label,
               weitere=[("archiv_handwerte", bestand_hw, staende["archiv_handwerte"])])
    if hinweise:
        _melde_db_dialog("warning", "Saved. " + "; ".join(hinweise) + ".")
    st.session_state["ref_flash"] = label
    return True


def _archiv_edit_speichern(
    schluessel: str, neu: Dict[str, str], spaceports: pd.DataFrame, vehicles: pd.DataFrame
) -> bool:
    """Save im Bearbeiten-Formular."""
    def aendern(zeile, marken):
        erlaubt = archiv_erlaubt(spaceports, vehicles, str(neu.get("Nation", zeile["Nation"])))
        return archiv_zeile_bearbeiten(zeile, neu, marken, erlaubt, spaceports)
    return _archiv_aendern(schluessel, aendern, "Archivzeile bearbeitet")


def _archiv_reset_klick(schluessel: str, spalte: str) -> bool:
    """Reset to NOLA value fuer ein markiertes Feld."""
    def aendern(zeile, marken):
        z, m = archiv_feld_zuruecksetzen(zeile, marken, spalte)
        return z, m, []
    return _archiv_aendern(schluessel, aendern, "Archivfeld zurueckgesetzt")
```

(`datetime`, `timezone`, `Callable` sind in `app.py` vorhanden – mit `grep -n "^from datetime\|^from typing" app.py` prüfen und ggf. ergänzen. `_melde_db_dialog("error", …)` legt den Text unter `ref_flash_error` ab, `"warning"` unter `ref_flash_warning` – die Tests lesen genau diese Schlüssel.)

- [ ] **Step 4: `_reference_row` mit Tooltips, Sortierung**

```python
def _reference_row(werte: Sequence[str], breiten: Sequence[float], header: bool = False,
                   hilfen: Optional[Sequence[Optional[str]]] = None):
    """Zeichnet eine Tabellenzeile und liefert die Spalte fuer die Schaltflaeche."""
    cols = st.columns(list(breiten))
    for i, (col, wert) in enumerate(zip(cols, werte)):
        hilfe = hilfen[i] if hilfen and i < len(hilfen) else None
        col.markdown(("**{}**" if header else "{}").format(wert), help=hilfe)
    return cols[-1]


#: Zeilen je Seite im Reiter Launch Archive.
ARCHIV_SEITE = 50


def _archiv_sortiert(archiv: pd.DataFrame) -> pd.DataFrame:
    """Neuestes Startdatum zuerst; unlesbare Daten ans Ende."""
    datum = pd.to_datetime(archiv["Startdatum"], format="%d.%m.%Y", errors="coerce")
    return archiv.assign(_d=datum).sort_values("_d", ascending=False, na_position="last",
                                               kind="stable").drop(columns="_d")
```

- [ ] **Step 5: `_archive_editor(spaceports, vehicles)`**

Aufruf im Dialog (`app.py:6162`) auf `_archive_editor(spaceports, vehicles)` ändern; Test-Stubs, die `_archive_editor` ersetzen (`grep -n "_archive_editor" test_app.py`), nehmen `*a` an.

```python
def _archive_editor(spaceports: pd.DataFrame, vehicles: pd.DataFrame) -> None:
    """Tabelle des Startarchivs: Blaettern, Marken, Bearbeiten (nur lokal), Entfernen."""
    try:
        archiv, handwerte = archiv_mit_handwerten_lesen()
    except ArchiveUnreadable as exc:
        st.error(_md_plain("Launch archive: {}".format(exc)))
        return
    darf = local_admin_allowed()
    st.caption(
        "This table is written by the application itself: every recognised launch gets a row. "
        + ("Edit corrects nation, site, vehicle, payload and orbit - a corrected field (✎) is never "
           "overwritten by a later run; ↻ marks orbit values recomputed for a new site."
           if darf else "Editing is only possible on the computer NOLA runs on.")
    )
    if archiv.empty:
        st.info(
            "No launches archived yet. As soon as a NOTAM file has been "
            "analysed, the launch archive in `nola.db` fills itself."
        )
        return
    marken = handwerte_index(handwerte)
    doppelt = ueberschneidende_schluessel(archiv)
    suche = st.text_input(
        "Search", key="archiv_suche", placeholder="NOTAM, nation, launch site, payload …"
    ).strip().lower()
    zeilen = _archiv_sortiert(archiv)
    if suche:
        zeilen = zeilen[zeilen.apply(lambda r: suche in " ".join(str(v).lower() for v in r), axis=1)]
    seiten = max(1, -(-len(zeilen) // ARCHIV_SEITE))
    seite = min(int(st.session_state.get("archiv_seite", 0)), seiten - 1)
    breiten = (1.5, 1.0, 0.8, 0.9, 1.0, 1.1, 1.2, 0.9, 1.2)
    _reference_row(("NOTAM", "Datum", "Zeit", "Nation", "Platz", "Vehicle", "Payload", "Orbit", ""),
                   breiten, header=True)
    st.caption("{} of {} launches".format(len(zeilen), len(archiv)))

    def zelle(text: str, schluessel: str, spalte: str) -> Tuple[str, Optional[str]]:
        marke = marken.get(schluessel, {}).get(spalte)
        if not marke:
            return _md_plain(text), None
        zeichen = "✎" if marke[1] == "hand" else "↻"
        return "{} {}".format(_md_plain(text), zeichen), "NOLA: {}".format(marke[0] or "-")

    offen = st.session_state.get("archiv_edit")
    for _, r in zeilen.iloc[seite * ARCHIV_SEITE:(seite + 1) * ARCHIV_SEITE].iterrows():
        schluessel = archive_key(dict(r))
        kurz = hashlib.sha1(schluessel.encode()).hexdigest()[:10]
        notam = _md_plain(str(r["NOTAM"])[:24]) + (" ⚠" if schluessel in doppelt else "")
        felder = [zelle(str(r["Nation"])[:12], schluessel, "Nation"),
                  zelle(str(r["Weltraumbahnhof"]), schluessel, "Weltraumbahnhof"),
                  zelle(str(r["Trägersystem"])[:14] or "-", schluessel, "Trägersystem"),
                  zelle(str(r["Payload"])[:16] or "-", schluessel, "Payload"),
                  zelle(str(r["Orbit"]), schluessel, "Orbit")]
        knopf = _reference_row(
            (notam, _md_plain(str(r["Startdatum"])), _md_plain(str(r["Startzeit"])))
            + tuple(t for t, _ in felder) + ("",),
            breiten,
            hilfen=(("shares NOTAM ids with another row – possible duplicate" if schluessel in doppelt else None),
                    None, None) + tuple(h for _, h in felder) + (None,),
        )
        links, rechts = knopf.columns(2)
        if darf and links.button("Edit", key="ed_arc_{}".format(kurz), use_container_width=True):
            st.session_state["archiv_edit"] = schluessel
            offen = schluessel
        if rechts.button("Remove", key="rm_arc_{}".format(kurz), use_container_width=True):
            _remove_archive_row(schluessel)
            st.rerun(scope="app")
        if darf and offen == schluessel:
            _archiv_formular(dict(r), marken.get(schluessel, {}), spaceports, vehicles, kurz)
    if seiten > 1:
        z, m, v = st.columns((1, 2, 1))
        if z.button("◀ Prev", key="archiv_prev", disabled=seite == 0):
            st.session_state["archiv_seite"] = seite - 1
            st.rerun(scope="fragment")
        m.caption("Page {} of {}".format(seite + 1, seiten))
        if v.button("Next ▶", key="archiv_next", disabled=seite >= seiten - 1):
            st.session_state["archiv_seite"] = seite + 1
            st.rerun(scope="fragment")


def _archiv_formular(zeile: Dict[str, Any], marken: "Marken", spaceports: pd.DataFrame,
                     vehicles: pd.DataFrame, kurz: str) -> None:
    """Bearbeiten unter der Zeile - normale Widgets, damit die Listen der Nation folgen."""
    schluessel = archive_key(zeile)
    with st.container(border=True):
        def auswahl(liste: Sequence[str], aktuell: str) -> List[str]:
            return list(liste) + ([aktuell] if aktuell not in liste else [])
        nation = st.selectbox("Nation", auswahl(TARGET_NATIONS, str(zeile["Nation"])),
                              index=auswahl(TARGET_NATIONS, str(zeile["Nation"])).index(str(zeile["Nation"])),
                              format_func=nation_label, key="aed_n_{}".format(kurz))
        erlaubt = archiv_erlaubt(spaceports, vehicles, nation)
        plaetze = auswahl(erlaubt["Weltraumbahnhof"], str(zeile["Weltraumbahnhof"]))
        platz = st.selectbox("Launch site", plaetze, index=plaetze.index(str(zeile["Weltraumbahnhof"])),
                             key="aed_p_{}".format(kurz))
        traeger = auswahl(erlaubt["Trägersystem"], str(zeile["Trägersystem"]))
        vehicle = st.selectbox("Vehicle", traeger, index=traeger.index(str(zeile["Trägersystem"])),
                               format_func=lambda v: v or "none", key="aed_v_{}".format(kurz))
        payload = st.text_input("Payload", value=str(zeile["Payload"]), max_chars=PAYLOAD_MAX,
                                key="aed_l_{}".format(kurz))
        orbits = auswahl(ORBIT_AUSWAHL, str(zeile["Orbit"]))
        orbit = st.selectbox("Orbit", orbits, index=orbits.index(str(zeile["Orbit"])), key="aed_o_{}".format(kurz))
        for spalte, (nola, herkunft) in sorted(marken.items()):
            if herkunft == "hand" and st.button("Reset {} to NOLA value ({})".format(spalte, nola or "-"),
                                                key="aed_r_{}_{}".format(kurz, spalte)):
                if _archiv_reset_klick(schluessel, spalte):
                    st.session_state.pop("archiv_edit", None)
                st.rerun(scope="app")
        speichern, abbrechen = st.columns(2)
        if speichern.button("Save", key="aed_s_{}".format(kurz), type="primary", use_container_width=True):
            if _archiv_edit_speichern(schluessel, {"Nation": nation, "Weltraumbahnhof": platz,
                                                   "Trägersystem": vehicle, "Payload": payload,
                                                   "Orbit": orbit}, spaceports, vehicles):
                st.session_state.pop("archiv_edit", None)
            st.rerun(scope="app")
        if abbrechen.button("Cancel", key="aed_c_{}".format(kurz), use_container_width=True):
            st.session_state.pop("archiv_edit", None)
            st.rerun(scope="fragment")
```

(Hinweis: Die Selectbox-Keys hängen am Zeilen-Hash; nach Save/Cancel werden sie mit dem Formular verworfen. `st.rerun(scope="app")` wie bei Remove, damit Dialogmeldungen und Undo-Knopf neu gezeichnet werden. Prüfen, ob `st.rerun(scope="fragment")` im Dialog erlaubt ist – der Dialog ist ein Fragment; sonst `scope="app"`.)

- [ ] **Step 6: Tests laufen lassen – erwartet PASS**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|ERGEBNIS"`
Expected: nur „ERGEBNIS: ALLE TESTS BESTANDEN“.

- [ ] **Step 7: Browser-Test an einer Kopie**

Die Browser-Vorschau darf `~/Documents` nicht lesen (bekannte Lektion). Wie in den Vorrunden: Projekt und `.venv` in das Scratchpad kopieren (`rsync -a --exclude .git`), in der Kopie `nola.db` durch eine Kopie der echten Datei ersetzen (nur lesend kopiert, die echte bleibt unberührt), ein `start-kopie.sh` mit `--server.address 127.0.0.1 --server.port 8502` starten, als Eintrag `nola-kopie` in `.claude/launch.json`, `preview_start`. Dann: Optionsmenü → Launch Archive → Zeile 15.01.2026 (JSLC, AlSat-3A) → Edit → Platz TSLC → Save → Inklination geändert, ✎ am Platz, ↻ an Orbit; Tooltip „NOLA: JSLC“; Reset → JSLC; Undo → TSLC; Seite 2 erreichbar. Screenshot als Beleg. Danach Eintrag `nola-kopie` aus `launch.json` entfernen und Server stoppen.

- [ ] **Step 8: Commit (falls erlaubt)**

```bash
git add app.py test_app.py
git commit -m "Archiv-Handwerte Aufgabe 4: Reiter Launch Archive mit Blaettern, Marken, Bearbeiten und Reset (<bead>)"
```

---

### Task 5: Doku, Projektplan, Artifact

**Files:**
- Modify: `README.md`, `STATUS.md`, `docs/projektplan.html`
- Publish: Artifact `https://claude.ai/artifact/SR4YwYSqPceEBzsiPwVPhe` (Hauptsitzung, nicht der Subagent)

**Interfaces:**
- Consumes: Funktionsnamen aus Tasks 1–4.

**Acceptance Criteria:**
- README: Abschnitt „Archiv von Hand bearbeiten“ (Felder, ✎/↻/⚠, Reset, Undo, nur lokal, Blättern) und im Abschnitt Sicherungen der Satz „Zurück zu einer älteren NOLA-Fassung nur über die Sicherung `…-vor-schema-2.db`.“; Export nennt `archiv_handwerte.csv`.
- STATUS: Kopfzeile mit aktuellen Zeilen- und Testzahlen (`wc -l app.py`, Zahl der PASS je Lauf), Zeile Startarchiv ergänzt, Schema 2.
- Projektplan: neuer Schritt in `STEPS` („Archiv von Hand bearbeiten“), `TREE`-Äste mit `f`: `archiv_zeile_bearbeiten`, `bahn_aus_platz`, `archiv_feld_zuruecksetzen`, `ueberschneidende_schluessel`, `archiv_mit_handwerten_lesen`, `archiv_und_handwerte_schreiben`, `_archive_editor`; Kopfzahlen = STATUS; „Offene Punkte“: `nola-8m4`, `nola-fqz` ergänzt.
- Artifact: erst lesen, dann aus der Seite ohne `<!doctype>/<html>/<head>/<body>` mit `url` veröffentlichen.

- [ ] **Step 1:** Zahlen ermitteln: `wc -l app.py`; `.venv/bin/python test_app.py | grep -c "  PASS"`; `.venv/bin/python test_nola_db.py | grep -c "  PASS"`.
- [ ] **Step 2:** README, STATUS, Projektplan wie oben ändern.
- [ ] **Step 3:** `docs/projektplan.html` im Browser (Datei) öffnen, Schritt und Äste prüfen.
- [ ] **Step 4:** Commit (falls erlaubt): `git add README.md STATUS.md docs/projektplan.html && git commit -m "Archiv-Handwerte Aufgabe 5: Doku und Projektplan (<bead>)"`.
- [ ] **Step 5 (Hauptsitzung):** Artifact lesen, Body in `scratchpad/projektplan-artifact.html` übernehmen, mit `url` veröffentlichen.

---

## Spec-Abdeckung

| Spec-Anforderung | Aufgabe |
|---|---|
| Tabelle `archiv_handwerte` in `FACHTABELLEN`, CHECKs, `herkunft` | 1 |
| Schema 2 mit Sicherung, ältere Fassung verweigert, alte Sicherungen prüfbar | 1 (+ README in 5) |
| `ersetze_tabellen_geprueft`, Import prüft Markierungen | 1, 3 |
| Export/Umzug `archiv_handwerte.csv` | 1 |
| `merge_archive` mit Markierungen, `_update_archive` mit Standvergleich beider | 3 |
| `confirm_many` überschreibt keine markierten Felder; Entfernen löscht Markierungen | 3 |
| Undo über zwei Tabellen | 3 |
| Formularwerte, Listen ∪ aktueller Wert, Payload-Regeln, Platz≠Nation-Hinweis | 2, 4 |
| Neuberechnung, Selbstprobe, Rückkehr entfernt Markierung, Nachkommastelle | 2 |
| Reset je Feld, Tooltip, Platz-Reset mit `berechnet` | 2, 4 |
| ⚠ Überschneidung | 2, 4 |
| Blättern statt `head(60)` | 4 |
| Nur lokal (UI + Schreibfunktion) | 4 |
| Konflikt → Meldung, nichts geschrieben | 3, 4 |
| Browser-Test | 4 |
| README, STATUS, Projektplan, Artifact | 5 |
