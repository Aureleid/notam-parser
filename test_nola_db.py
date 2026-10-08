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

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
