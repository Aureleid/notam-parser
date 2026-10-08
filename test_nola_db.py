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
for _label, _df in [("Breite 12abc", _sp(Latitude="12abc")), ("Breite 4O.9 (Buchstabe O)", _sp(Latitude="4O.9"))]:
    try:
        db.ersetze_tabelle(_c, "startplaetze", _df, None); check(_label + " abgelehnt", False)
    except db.DbFehler as e:
        check(_label + " abgelehnt", e.ursache == "constraint failed", e.ursache)
try:
    db.ersetze_tabelle(_c, "startplaetze", _sp(Latitude="-12.5"), None)
    check("Breite -12.5 angenommen", db.lese_tabelle(_c, "startplaetze").loc[0, "Latitude"] == "-12.5")
except db.DbFehler as e:
    check("Breite -12.5 angenommen", False, e.ursache)
db.ersetze_tabelle(_c, "startplaetze", _sp().iloc[0:0], None)

def _fir(code):
    zeile = {k: "x" for k in db.FACHTABELLEN["firs"]}
    zeile.update({"ICAO Code": code, "Latitude": "32.1", "Longitude": "-106.2"})
    return pd.DataFrame([zeile])
try:
    db.ersetze_tabelle(_c, "firs", _fir("ZAB"), None)
    check("FIR-Code ZAB (3 Zeichen) angenommen", db.zaehle(_c, "firs") == 1)
except db.DbFehler as e:
    check("FIR-Code ZAB (3 Zeichen) angenommen", False, e.ursache)
for _code in ("ZB", "ZBPEX"):
    try:
        db.ersetze_tabelle(_c, "firs", _fir(_code), None); check("FIR-Code " + _code + " abgelehnt", False)
    except db.DbFehler as e:
        check("FIR-Code " + _code + " abgelehnt", e.ursache == "constraint failed", e.ursache)
db.ersetze_tabelle(_c, "firs", _fir("ZAB").iloc[0:0], None)
_pfad_echt, _c_echt = neue_db()
for _tab, _csv in [("startplaetze", app.SPACEPORT_CSV), ("firs", app.FIR_CSV), ("traegersysteme", app.VEHICLE_CSV)]:
    _df = app._read_csv_any(_csv)[list(db.FACHTABELLEN[_tab])]
    try:
        db.ersetze_tabelle(_c_echt, _tab, _df, None)
        check("Echtdaten " + _tab + ": Zeilenzahl gleich", db.zaehle(_c_echt, _tab) == len(_df), len(_df))
    except db.DbFehler as e:
        check("Echtdaten " + _tab + ": Zeilenzahl gleich", False, e.ursache)
_c_echt.close()

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
db.SCHRITTE[0] = "SELECT 1"  # Schritt vorhanden, damit die Sicherungspruefung greift
try:
    db.pruefe_schema(_c, lambda: None); check("ohne Sicherung kein Umbau", False)
except db.DbFehler as e:
    check("ohne Sicherung kein Umbau", e.ursache == "backup failed")
finally:
    del db.SCHRITTE[0]
check("Version unveraendert", db.schema_version(_c) == 0)
_c.close()

print("== 7. Platte voll: Originalursache bleibt ==")
_pv, _cv = neue_db()
_vorher = db.ersetze_tabelle(_cv, "startplaetze", _sp(), None)
_seiten = _cv.execute("PRAGMA page_count").fetchone()[0]
_cv.execute("PRAGMA max_page_count = {}".format(_seiten + 2))
_gross = pd.DataFrame([{"Kurzel": "K{}".format(i), "Latitude": "1", "Longitude": "1",
                        "Name": "x" * 5000, "Land": "L"} for i in range(200)])
try:
    db.ersetze_tabelle(_cv, "startplaetze", _gross, None); check("volle Platte -> DbFehler", False)
except db.DbFehler as e:
    check("volle Platte -> Ursache disk full", e.ursache == "disk full", e.ursache + " | " + str(e))
check("volle Platte: keine offene Transaktion", not _cv.in_transaction)
check("volle Platte: Tabelle unveraendert", db.lese_tabelle(_cv, "startplaetze").attrs["nola_stand"] == _vorher)
_cv.close()

print("== 8. Schema: fehlender Schritt, Anlegen ==")
_ps, _cs = neue_db()
_cs.execute("UPDATE meta SET wert = '0' WHERE schluessel = 'schema_version'")
_aufrufe = []
try:
    db.pruefe_schema(_cs, lambda: (_aufrufe.append(1), _ps)[1]); check("fehlender Schritt -> DbFehler", False)
except db.DbFehler as e:
    check("fehlender Schritt -> Ursache schema step missing", e.ursache == "schema step missing", e.ursache)
except BaseException as e:
    check("fehlender Schritt -> DbFehler", False, type(e).__name__)
check("fehlender Schritt: nicht gesichert", _aufrufe == [])
check("fehlender Schritt: Version bleibt 0", db.schema_version(_cs) == 0)
check("fehlender Schritt: keine offene Transaktion", not _cs.in_transaction)
try:
    db.lege_schema_an(_cs); check("Anlegen auf vorhandener Datei scheitert", False)
except db.DbFehler:
    check("Anlegen auf vorhandener Datei scheitert", True)
check("Anlegen-Fehler laesst keine Transaktion offen", not _cs.in_transaction)
_cs.close()
_pn = Path(tempfile.mkdtemp()) / "n.db"
_cn = db.verbinde(_pn, anlegen=True)
db.lege_schema_an(_cn)
check("Version 1 nach Anlegen", db.schema_version(_cn) == 1)
_cn.close()

print("== 9. Arbeitsstand ==")
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

print("== 10. Archiv-Import-Zustand ==")
_eintraege = [("A1/26|2610010000", {"notam_id": "A1/26", "b": "2610010000", "text": "T", "quellen": ["s1.html"]})]
db.speichere_korpus(_c2, _eintraege)
check("Korpus Rundlauf", db.lade_korpus(_c2) == [_eintraege[0][1]])
_zst = {"version": 1, "tage": {"2026-10-01": {"fingerprint": "f", "kandidaten": [{"key": "x"}],
        "pruefliste": [], "usa": 2}}, "entscheidungen": {"x": {"status": "confirmed"}},
        "review_bestaetigt": ["r2", "r1"], "review_ausgeblendet": ["r3"], "erkennungsstand": "abc"}
db.speichere_importzustand(_c2, _zst)
check("Importzustand Rundlauf", db.lade_importzustand(_c2) == _zst)
_c2.close()

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
