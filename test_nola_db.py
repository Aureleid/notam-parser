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
check("gleicher Zielzustand: k9 in DB bestaetigt", "k9" in db.lade_arbeitsstand(_c2)["confirmed_launches"])

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

# F1: ids manueller NOTAMs werden nie wiederverwendet (AUTOINCREMENT)
_snap = db.lade_arbeitsstand(_c2)
_hoechste = _snap["manual_notams"][-1]["id"]
_fremd.execute("DELETE FROM manuelle_notams WHERE id = ?", (_hoechste,))
_fremd.execute("INSERT INTO manuelle_notams (text, added, geaendert_utc) VALUES ('NEW/26 NOTAMN', '', 'x')")
_neue_id = _fremd.execute("SELECT id FROM manuelle_notams WHERE text = 'NEW/26 NOTAMN'").fetchone()[0]
check("id des extern eingefuegten NOTAMs ist neu und groesser", _neue_id > _hoechste)
_ohne_c = _copy.deepcopy(_snap); _ohne_c["manual_notams"] = _snap["manual_notams"][:-1]
db.schreibe_unterschiede(_c2, _snap, _ohne_c, "t")
check("extern eingefuegtes NOTAM nicht still geloescht",
      "NEW/26 NOTAMN" in [n["text"] for n in db.lade_arbeitsstand(_c2)["manual_notams"]])
_fremd.close()

# F2: schreibe_arbeitsstand_neu ist atomar
_vor = db.lade_arbeitsstand(_c2)
_schlecht = db.leerer_arbeitsstand()
_schlecht["confirmed_launches"] = {"z1"}
_schlecht["manual_notams"] = [{"text": "   ", "added": ""}]
try:
    db.schreibe_arbeitsstand_neu(_c2, _schlecht, "t"); check("ungueltiger Stand -> DbFehler", False)
except db.DbFehler:
    check("ungueltiger Stand -> DbFehler", True)
_nach = db.lade_arbeitsstand(_c2)
check("Neuaufbau-Abbruch: Vorstand vollstaendig erhalten",
      _nach == _vor and len(_nach["manual_notams"]) >= 2 and _nach["confirmed_launches"] != set())
check("Neuaufbau-Abbruch: keine offene Transaktion", not _c2.in_transaction)

print("== 10. Archiv-Import-Zustand ==")
_eintraege = [("A1/26|2610010000", {"notam_id": "A1/26", "b": "2610010000", "text": "T", "quellen": ["s1.html"]})]
db.speichere_korpus(_c2, _eintraege)
check("Korpus Rundlauf", db.lade_korpus(_c2) == [_eintraege[0][1]])
_umgekehrt = [("B2/26|2610020000", {"notam_id": "B2/26", "b": "2610020000", "text": "T2", "quellen": ["s2.html", "s3.html"]}),
              _eintraege[0]]
db.speichere_korpus(_c2, _umgekehrt)
check("Korpus: nach Schluessel sortiert, beide vollstaendig",
      db.lade_korpus(_c2) == [_umgekehrt[1][1], _umgekehrt[0][1]])
_zst = {"version": 1, "tage": {"2026-10-01": {"fingerprint": "f", "kandidaten": [{"key": "x"}],
        "pruefliste": [], "usa": 2}}, "entscheidungen": {"x": {"status": "confirmed"}},
        "review_bestaetigt": ["r2", "r1"], "review_ausgeblendet": ["r3"], "erkennungsstand": "abc"}
db.speichere_importzustand(_c2, _zst)
check("Importzustand Rundlauf", db.lade_importzustand(_c2) == _zst)
_c2.close()

print("== 11. Sicherung ==")
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

# Fix-Runde 1: Fehlerarten
import errno as _errno
_ord2 = Path(tempfile.mkdtemp())
for _n in range(31):
    (_ord2 / "nola-2026-09-{:02d}-0000.db".format(_n + 1)).write_bytes(b"x")
_unlink_orig = Path.unlink
def _unlink_kaputt(self, *a, **k):
    if self.parent == _ord2 and not self.name.startswith("."):
        raise PermissionError(_errno.EACCES, "Permission denied")
    return _unlink_orig(self, *a, **k)
Path.unlink = _unlink_kaputt
try:
    db.sichere(_c3, _ord2, _dt(2026, 10, 9, 9, 0)); check("Rotation-Fehler -> DbFehler", False)
except db.DbFehler as e:
    check("Rotation-Fehler -> DbFehler", e.ursache == "backup rotation failed", e.ursache)
except OSError:
    check("Rotation-Fehler -> DbFehler", False, "roher OSError")
finally:
    Path.unlink = _unlink_orig
check("Sicherung trotz Rotation-Fehler vorhanden", (_ord2 / "nola-2026-10-09-0900.db").exists())

_stat_orig = os.stat
_connect_orig = db.sqlite3.connect
_oeffnungen = []
_cloud_datei = _ord / "nola-cloud-test.db"; _cloud_datei.write_bytes(b"x")
def _stat_cloud(pfad, *a, **k):
    if str(pfad) == str(_cloud_datei):
        return _StatAus()
    return _stat_orig(pfad, *a, **k)
def _connect_zaehle(*a, **k):
    _oeffnungen.append(a); return _connect_orig(*a, **k)
os.stat = _stat_cloud; db.sqlite3.connect = _connect_zaehle
try:
    _res_cloud = db.pruefe_sicherung(_cloud_datei)
finally:
    os.stat = _stat_orig; db.sqlite3.connect = _connect_orig
check("ausgelagert -> in_cloud", _res_cloud == ("in_cloud", None), _res_cloud)
check("in_cloud-Datei nicht geoeffnet", _oeffnungen == [], _oeffnungen)
_cloud_datei.unlink()

print("== 12. Wiederherstellen ==")
_ziel = Path(tempfile.mkdtemp()) / "nola.db"
db.stelle_wieder_her(_reg[0], _ziel)
_cz = db.verbinde(_ziel)
check("wiederhergestellt", db.zaehle(_cz, "startplaetze") == 1); _cz.close()
_vorher = _ziel.read_bytes()
try:
    db.stelle_wieder_her(_reg[1], _ziel); check("ueberschreibt nie", False)
except db.DbFehler as e:
    check("ueberschreibt nie", e.ursache == "exists" and _ziel.read_bytes() == _vorher)
check("keine tmp nach Wiederherstellen", not any(p.name.endswith(".tmp") for p in _ziel.parent.iterdir()))
_zd = Path(tempfile.mkdtemp()); _zz = _zd / "nola.db"
_link_orig = os.link
def _link_kaputt(*a, **k):
    raise OSError(_errno.EPERM, "Operation not permitted")
os.link = _link_kaputt
try:
    db.stelle_wieder_her(_reg[0], _zz); check("link-Fehler -> DbFehler", False)
except db.DbFehler as e:
    check("link-Fehler -> DbFehler", e.ursache == "restore failed", e.ursache)
except OSError:
    check("link-Fehler -> DbFehler", False, "roher OSError")
finally:
    os.link = _link_orig
check("link-Fehler: Ziel fehlt, keine tmp", not _zz.exists() and list(_zd.iterdir()) == [], list(_zd.iterdir()))
_c3.close()

print("== 13. Umzug ==")
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

print("== 14. Start-Entscheidung ==")
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

print("== 15. Export ==")
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

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
