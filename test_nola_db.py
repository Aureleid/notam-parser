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
# Entscheidung 2: Klick-Aktionen warten 5 s auf eine fremde Sperre, das automatische
# Fortschreiben nur kurz (Parameter wartezeit)
check("verbinde: Standard-Wartezeit 5 s", _c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000)
_c_kurz = db.verbinde(_p, wartezeit=0.5)
try:
    check("verbinde(wartezeit=0.5): busy_timeout 500 ms", _c_kurz.execute("PRAGMA busy_timeout").fetchone()[0] == 500)
    _c.execute("BEGIN IMMEDIATE")
    _t0 = time.monotonic()
    try:
        db.ersetze_tabelle(_c_kurz, "startplaetze", pd.DataFrame(columns=list(db.FACHTABELLEN["startplaetze"])), None)
        check("kurze Wartezeit: fremde Sperre -> Gesperrt", False)
    except db.Gesperrt:
        check("kurze Wartezeit: fremde Sperre -> Gesperrt", True)
    _dauer = time.monotonic() - _t0
    # Grosszuegige Obergrenze (Soll ~0,5 s, Standard waeren 5 s): robust auf langsamen Maschinen
    check("kurze Wartezeit: kehrt nach < 2 s zurueck", _dauer < 2.0, round(_dauer, 2))
finally:
    if _c.in_transaction:
        _c.execute("ROLLBACK")
    _c_kurz.close()

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
_warte = time.monotonic() - _t0
# busy_timeout ist 5 s: die Wartezeit belegt, dass wirklich gewartet wurde (>= 4,5 s), und
# bleibt mit 1,5 s Luft fuer langsame Rechner sicher unter 6,5 s - nicht wackelig.
check("Wartezeit belegt busy_timeout 5 s (4,5 s bis 6,5 s)", 4.5 <= _warte <= 6.5, round(_warte, 2))
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

# Standvergleich (nola-a6c.6): zwei Verbindungen, die zweite schreibt mit veraltetem Stand
_c2b = db.verbinde(_p2)
try:
    _z_a, _st_a = db.lade_importzustand_mit_stand(_c2)
    _z_b, _st_b = db.lade_importzustand_mit_stand(_c2b)
    check("Importzustand mit Stand: gleiche Daten wie ohne", _z_a == _zst and _st_a == _st_b and len(_st_a) == 64)
    _z_neu = dict(_zst, erkennungsstand="neu1")
    _st_neu = db.speichere_importzustand(_c2, _z_neu, erwartet=_st_a)
    check("Importzustand: passender Stand -> geschrieben, neuer Stand zurueck",
          db.lade_importzustand(_c2) == _z_neu and _st_neu == db.lade_importzustand_mit_stand(_c2)[1]
          and _st_neu != _st_a)
    try:
        db.speichere_importzustand(_c2b, dict(_zst, erkennungsstand="veraltet"), erwartet=_st_b)
        check("Importzustand: veralteter Stand -> Konflikt", False)
    except db.Konflikt:
        check("Importzustand: veralteter Stand -> Konflikt", True)
    check("Importzustand: Konflikt schreibt nichts", db.lade_importzustand(_c2) == _z_neu)
    check("Importzustand: keine offene Transaktion nach Konflikt", not _c2b.in_transaction)
    # Jede beteiligte Tabelle zaehlt zum Stand
    for _tab_s, _sql_s in [
            ("archiv_import_tage", "UPDATE archiv_import_tage SET fingerprint = 'g'"),
            ("archiv_import_entscheidungen", "UPDATE archiv_import_entscheidungen SET wert_json = '{}'"),
            ("archiv_import_review", "DELETE FROM archiv_import_review WHERE schluessel = 'r3'"),
            ("meta erkennungsstand", "UPDATE meta SET wert = 'fremd' WHERE schluessel = 'erkennungsstand'")]:
        _vorher_s = db.lade_importzustand_mit_stand(_c2)[1]
        _c2b.execute(_sql_s)
        check("Stand aendert sich mit " + _tab_s, db.lade_importzustand_mit_stand(_c2)[1] != _vorher_s)
    # Umzug/Wiederherstellen: ohne erwarteten Stand weiter moeglich
    db.speichere_importzustand(_c2b, _zst)
    check("Importzustand: erwartet=None (Umzug) schreibt ohne Vergleich", db.lade_importzustand(_c2) == _zst)

    _k_a, _ks_a = db.lade_korpus_mit_stand(_c2)
    _k_b, _ks_b = db.lade_korpus_mit_stand(_c2b)
    check("Korpus mit Stand: gleiche Daten wie ohne", _k_a == db.lade_korpus(_c2) and _ks_a == _ks_b)
    _ks_neu = db.speichere_korpus(_c2, _eintraege, erwartet=_ks_a)
    check("Korpus: passender Stand -> geschrieben, neuer Stand zurueck",
          db.lade_korpus(_c2) == [_eintraege[0][1]] and _ks_neu == db.lade_korpus_mit_stand(_c2)[1])
    try:
        db.speichere_korpus(_c2b, _umgekehrt, erwartet=_ks_b)
        check("Korpus: veralteter Stand -> Konflikt", False)
    except db.Konflikt:
        check("Korpus: veralteter Stand -> Konflikt", True)
    check("Korpus: Konflikt schreibt nichts", db.lade_korpus(_c2) == [_eintraege[0][1]])
    db.speichere_korpus(_c2b, _umgekehrt)
    check("Korpus: erwartet=None (Umzug) schreibt ohne Vergleich", len(db.lade_korpus(_c2)) == 2)

    # Import-Klick schreibt Korpus und Zustand zusammen: veralteter Zustand -> auch Korpus unberuehrt
    _k_v, _ks_v = db.lade_korpus_mit_stand(_c2)
    _z_v, _zs_v = db.lade_importzustand_mit_stand(_c2)
    _c2b.execute("UPDATE meta SET wert = 'fremd2' WHERE schluessel = 'erkennungsstand'")
    try:
        db.speichere_import(_c2, _eintraege, dict(_zst, erkennungsstand="mein"), _ks_v, _zs_v)
        check("speichere_import: veralteter Zustand -> Konflikt", False)
    except db.Konflikt:
        check("speichere_import: veralteter Zustand -> Konflikt", True)
    check("speichere_import: Konflikt -> Korpus und Zustand unberuehrt",
          db.lade_korpus(_c2) == _k_v and db.lade_importzustand(_c2)["erkennungsstand"] == "fremd2")
    _zs_v2 = db.lade_importzustand_mit_stand(_c2)[1]
    _neu_ks, _neu_zs = db.speichere_import(_c2, _eintraege, dict(_zst, erkennungsstand="mein"), _ks_v, _zs_v2)
    check("speichere_import: passende Staende -> beides geschrieben, neue Staende zurueck",
          db.lade_korpus(_c2) == [_eintraege[0][1]] and db.lade_importzustand(_c2)["erkennungsstand"] == "mein"
          and _neu_ks == db.lade_korpus_mit_stand(_c2)[1] and _neu_zs == db.lade_importzustand_mit_stand(_c2)[1])
finally:
    _c2b.close()
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
check("Name nach Muster (mit Sekunden)", _s1.name == "nola-2026-10-08-090000.db", _s1.name)
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
check("neueste zuerst", _reg[0].name == "nola-2026-10-08-103000.db", _reg[0].name)
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
check("Sicherung trotz Rotation-Fehler vorhanden", (_ord2 / "nola-2026-10-09-090000.db").exists())

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

_ENDEN = (".tmp", ".tmp-wal", ".tmp-shm", ".tmp-journal")
def _reste(ordner):
    return [p.name for p in Path(ordner).iterdir() if p.name.endswith(_ENDEN)]
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
    check("  keine Temp-Datei", _reste(_z.parent) == [], _reste(_z.parent))

_leer = _altordner(mit_echten=False); _zl = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_zl, um.altdateien_im(_leer))
_cl = db.verbinde(_zl); check("fehlende Altdateien -> leere Tabellen", db.zaehle(_cl, "startarchiv") == 0); _cl.close()

# nola.db entsteht waehrend des Umzugs -> bleibt unveraendert
import hashlib
_zr = Path(tempfile.mkdtemp()) / "nola.db"
_vorh_quelle = Path(tempfile.mkdtemp()) / "vorh.db"
um.umziehen(_vorh_quelle, um.altdateien_im(_altordner(mit_echten=False)))  # echte, leere DB des "schnelleren" Prozesses
_vorh_bytes = _vorh_quelle.read_bytes()
_orig_link = um.os.link
def _vorher_anlegen(src, dst):
    Path(dst).write_bytes(_vorh_bytes); return _orig_link(src, dst)
um.os.link = _vorher_anlegen
try:
    _zahl_race = um.umziehen(_zr, um.altdateien_im(_altordner()))
finally:
    um.os.link = _orig_link
check("vorhandene nola.db nicht ueberschrieben",
      hashlib.sha256(_zr.read_bytes()).hexdigest() == hashlib.sha256(_vorh_bytes).hexdigest())
check("Race: Zaehlung stammt aus der vorhandenen Datei",
      _zahl_race["startarchiv"] == 0 and _zahl_race["startplaetze"] == 0, _zahl_race)
check("Race: keine Reste",
      not any(p.name.endswith(_e) for p in _zr.parent.iterdir() for _e in (".tmp", ".tmp-wal", ".tmp-shm", ".tmp-journal")))

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

print("== 16. Fix-Runde 1 ==")
def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# F1: roher OSError aus os.link
_d1 = _altordner(); _z1d = Path(tempfile.mkdtemp()); _z1 = _z1d / "nola.db"
_orig_link = um.os.link
def _link_eperm(*a, **k):
    raise PermissionError(_errno.EPERM, "Operation not permitted")
um.os.link = _link_eperm
try:
    try:
        um.umziehen(_z1, um.altdateien_im(_d1)); check("F1 link-OSError -> UmzugFehler", False)
    except um.UmzugFehler as e:
        check("F1 link-OSError -> UmzugFehler", "No database was created" in str(e), str(e)[:120])
    except OSError:
        check("F1 link-OSError -> UmzugFehler", False, "roher OSError")
    check("F1  keine nola.db, kein Rest", not _z1.exists() and _reste(_z1d) == [], list(_z1d.iterdir()))
    _zs = um.stelle_bereit(_z1, um.altdateien_im(_d1), Path(tempfile.mkdtemp()), _dt2(2026, 10, 8, 9, 0))
except OSError:
    check("F1 stelle_bereit -> fehlgeschlagen", False, "roher OSError")
else:
    check("F1 stelle_bereit -> fehlgeschlagen", _zs.art == "fehlgeschlagen" and _zs.grund, _zs)
finally:
    um.os.link = _orig_link

# F2: Typen im Arbeitsstand
for _bez, _roh in [("manual_notams=5", {"manual_notams": 5}),
                   ("hidden_events=null", {"hidden_events": None}),
                   ("hidden_events=String", {"hidden_events": "abc"}),
                   ("vehicle_assignments=Liste", {"vehicle_assignments": ["a"]}),
                   ("confirmed_launches=Zahl", {"confirmed_launches": 7})]:
    _d = _altordner(); (_d / "notam_workspace.json").write_text(_json.dumps(_roh), encoding="utf-8")
    _z = Path(tempfile.mkdtemp()) / "nola.db"
    try:
        um.umziehen(_z, um.altdateien_im(_d)); check("F2 {} -> UmzugFehler".format(_bez), False)
    except um.UmzugFehler as e:
        check("F2 {} -> UmzugFehler".format(_bez), "notam_workspace.json" in str(e), str(e)[:120])
    except Exception as e:
        check("F2 {} -> UmzugFehler".format(_bez), False, repr(e)[:120])
    check("F2  keine nola.db", not _z.exists())

# F3: Zaehlung je Quelle
_d3 = _altordner(mit_echten=False)
(_d3 / "notam_workspace.json").write_text(_json.dumps({
    "manual_notams": [{"text": "A", "added": "t"}],
    "hidden_events": ["a", "b"], "confirmed_launches": ["c"],
    "vehicle_assignments": {"x": "y", "z": ""}, "payload_assignments": {"p": "q"}}), encoding="utf-8")
(_d3 / "archiv_korpus.json").write_text(_json.dumps({"version": 1, "notams": [
    {"notam_id": "A1/26", "b": "2601010000", "text": "T", "quellen": ["q"]}]}), encoding="utf-8")
(_d3 / ai.IMPORT_JSON.name).write_text(_json.dumps({"version": 1,
    "tage": {"2026-01-01": {"fingerprint": "f", "kandidaten": [], "pruefliste": []}},
    "entscheidungen": {"k": {"a": 1}}, "review_bestaetigt": ["r1", "r2"], "review_ausgeblendet": ["r3"],
    "erkennungsstand": "s"}), encoding="utf-8")
_z3 = Path(tempfile.mkdtemp()) / "nola.db"
try:
    _zz = um.umziehen(_z3, um.altdateien_im(_d3))
except Exception as e:
    _zz = {}; check("F3 Umzug mit Arbeitsstand/Korpus/Importzustand", False, repr(e)[:150])
_erw3 = {"manuelle_notams": 1, "entscheidungen": 3, "zuweisungen": 2, "archiv_korpus": 1,
         "archiv_import_tage": 1, "archiv_import_entscheidungen": 1, "archiv_import_review": 3}
for _k, _v in _erw3.items():
    check("F3 Zaehlung {}".format(_k), _zz.get(_k) == _v, "{} != {}".format(_zz.get(_k), _v))
if _z3.exists():
    _c3z = db.verbinde(_z3)
    check("F3 Zaehlung = Tabellen", all(db.zaehle(_c3z, _k) == _v for _k, _v in _erw3.items()))
    _c3z.close()
# F3: echte Dateien
_zr3 = um.umziehen(Path(tempfile.mkdtemp()) / "nola.db", um.altdateien_im(_altordner()))
_ar = um.altdateien_im(_altordner())
_kn = len(ai.load_korpus(_ar.korpus)); _zst = ai.read_json(_ar.importzustand)
check("F3 echte Dateien: Korpus", _zr3.get("archiv_korpus") == _kn, (_zr3.get("archiv_korpus"), _kn))
check("F3 echte Dateien: Importtage", _zr3.get("archiv_import_tage") == len(_zst.get("tage", {})))
check("F3 echte Dateien: Entscheidungen",
      _zr3.get("archiv_import_entscheidungen") == len(_zst.get("entscheidungen", {})))
check("F3 echte Dateien: Review", _zr3.get("archiv_import_review")
      == len(_zst.get("review_bestaetigt", [])) + len(_zst.get("review_ausgeblendet", [])))
_wsr = _json.loads(_ar.arbeitsstand.read_text(encoding="utf-8")) if _ar.arbeitsstand.exists() else {}
check("F3 echte Dateien: Entscheidungen/Zuweisungen", _zr3.get("entscheidungen") == sum(
          len({str(x) for x in _wsr.get(k, [])}) if k != "archiv_removed"
          else len(app.migrate_archive_keys({str(x) for x in _wsr.get(k, [])}))
          for k in db.ENTSCHEIDUNGS_SCHLUESSEL)
      and _zr3.get("zuweisungen") == sum(len({a for a, b in _wsr.get(k, {}).items() if b})
                                         for k in db.ZUWEISUNGS_SCHLUESSEL), _zr3)

# F4: Scheitern nach dem Anlegen der Temp-DB
_d4 = _altordner(); _z4d = Path(tempfile.mkdtemp()); _z4 = _z4d / "nola.db"
_ers_orig = db.ersetze_tabelle
def _ers_kaputt(conn, name, df, *a, **k):
    if name == "seestarts":
        raise db.DbFehler("write failed", "disk full")
    return _ers_orig(conn, name, df, *a, **k)
db.ersetze_tabelle = _ers_kaputt
try:
    try:
        um.umziehen(_z4, um.altdateien_im(_d4)); check("F4 Scheitern nach Temp-DB -> UmzugFehler", False)
    except um.UmzugFehler as e:
        check("F4 Scheitern nach Temp-DB -> UmzugFehler", "disk full" in str(e), str(e)[:120])
finally:
    db.ersetze_tabelle = _ers_orig
check("F4  keine nola.db, kein Rest", not _z4.exists() and _reste(_z4d) == [], list(_z4d.iterdir()))

# F5: Akzeptanzkriterien
_alt5 = um.altdateien_im(_altordner()); _db5 = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_db5, _alt5); _c5 = db.verbinde(_db5)
_erw_s = _alt5.seestarts and um._csv_streng(_alt5.seestarts, db.FACHTABELLEN["seestarts"])
_ist_s = db.lese_tabelle(_c5, "seestarts"); _ist_s.attrs = {}
try:
    pd.testing.assert_frame_equal(_ist_s, app.load_sea_launches(_alt5.seestarts)[list(db.FACHTABELLEN["seestarts"])]
                                  .reset_index(drop=True), check_dtype=True)
    check("F5 Rundlauf seestarts (Altdatei-Leser)", True)
except AssertionError as e:
    check("F5 Rundlauf seestarts (Altdatei-Leser)", False, str(e)[:200])

_alle = [_alt5.startplaetze, _alt5.firs, _alt5.traegersysteme, _alt5.startarchiv, _alt5.seestarts,
         _alt5.arbeitsstand, _alt5.korpus, _alt5.importzustand]
_proj = um.altdateien_im(app.APP_DIR)
_proj_dat = [p for p in (_proj.startplaetze, _proj.firs, _proj.traegersysteme, _proj.startarchiv,
                         _proj.seestarts, _proj.arbeitsstand, _proj.korpus, _proj.importzustand) if p.exists()]
_hash_vorher = {p: _sha(p) for p in _proj_dat}
_dbp = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_dbp, _proj)                                   # liest die Projektdateien direkt
_exp5 = um.exportieren(_dbp, Path(tempfile.mkdtemp()) / "export")
check("F5 Altdateien im Projekt unberuehrt", {p: _sha(p) for p in _proj_dat} == _hash_vorher)
_c5b = db.verbinde(_dbp)
check("F5 Export Korpus = Datenbank",
      ai.load_korpus(_exp5 / ai.KORPUS_JSON.name) == ai.korpus_aus_daten({"notams": db.lade_korpus(_c5b)}, "db"))
_zdb = db.lade_importzustand(_c5b)
_zerw = ai.zustand_aus_daten(_zdb, "db") if _zdb else ai.zustand_aus_daten(
    {"version": 1, "tage": {}, "entscheidungen": {}, "review_bestaetigt": [],
     "review_ausgeblendet": [], "erkennungsstand": ""}, "db")
check("F5 Export Importzustand = Datenbank", ai.load_state(_exp5 / ai.IMPORT_JSON.name) == _zerw)
_sb = db.lese_tabelle(_c5b, "seestarts"); _sb.attrs = {}
try:
    pd.testing.assert_frame_equal(app.load_sea_launches(_exp5 / app.SEA_LAUNCH_CSV.name)[list(_sb.columns)]
                                  .reset_index(drop=True), _sb, check_dtype=True)
    check("F5 Export seestarts gleich Datenbank", True)
except AssertionError as e:
    check("F5 Export seestarts gleich Datenbank", False, str(e)[:200])
_c5b.close(); _c5.close()
# Export mit befuelltem Korpus/Importzustand (synthetisch)
_db3 = _z3; _e3 = um.exportieren(_db3, Path(tempfile.mkdtemp()) / "export")
_c3e = db.verbinde(_db3)
check("F5 Export Korpus (befuellt)", len(ai.load_korpus(_e3 / ai.KORPUS_JSON.name)) == 1)
# F5 Runde 2: Korpus inhaltlich, mehrere Eintraege mit verschiedenen Feldern und Quellen
_dk = _altordner(mit_echten=False)
(_dk / "archiv_korpus.json").write_text(_json.dumps({"version": 1, "notams": [
    {"notam_id": "A0001/26", "b": "2601010000", "text": "ROCKET LAUNCH AREA 1",
     "quellen": ["2026-01-01/a.txt", "2026-01-02/b.txt"]},
    {"notam_id": "B0002/26", "b": "2602030000", "text": "DANGER AREA\nLINE 2 \u00e4",
     "quellen": ["2026-02-03/c.txt"]},
    {"notam_id": "C0003/26", "b": "2603050000", "text": "NAVWARN 3",
     "quellen": ["x.txt", "y.txt", "z.txt"]}]}), encoding="utf-8")
_dbk = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_dbk, um.altdateien_im(_dk))
_ck = db.verbinde(_dbk)
_dbk_inhalt = db.lade_korpus(_ck); _ck.close()
_ek = um.exportieren(_dbk, Path(tempfile.mkdtemp()) / "export")
_gel = ai.load_korpus(_ek / ai.KORPUS_JSON.name)
_gel_liste = [{"notam_id": n.notam_id, "b": n.b, "text": n.text, "quellen": n.quellen}
              for _k, n in sorted(_gel.items())]
check("F5 R2 Export Korpus: 3 Eintraege", len(_dbk_inhalt) == 3 and len(_gel) == 3)
check("F5 R2 Export Korpus inhaltlich = Datenbank", _gel_liste == _dbk_inhalt, (_gel_liste, _dbk_inhalt))
check("F5 Export Importzustand (befuellt)",
      ai.load_state(_e3 / ai.IMPORT_JSON.name) == ai.zustand_aus_daten(db.lade_importzustand(_c3e), "db"))
_c3e.close()

# F5: Schema-Anhebung in stelle_bereit
_sd5 = Path(tempfile.mkdtemp()); _sdb5 = _sd5 / "nola.db"; _sord5 = Path(tempfile.mkdtemp())
um.umziehen(_sdb5, um.altdateien_im(_altordner(mit_echten=False)))
_cc = db.verbinde(_sdb5); db.setze_meta(_cc, "schema_version", "0"); _cc.close()
db.SCHRITTE[0] = "SELECT 1"
try:
    _zs5 = um.stelle_bereit(_sdb5, _alt5, _sord5, _dt2(2026, 10, 8, 9, 0))
    check("F5 Schema-Anhebung -> bereit", _zs5.art == "bereit", _zs5)
    check("F5  Sicherung vor-schema-1", [p.name for p in _sord5.iterdir() if not p.name.startswith(".")] == ["nola-2026-10-08-090000-vor-schema-1.db"],
          [p.name for p in _sord5.iterdir()])
    _cc = db.verbinde(_sdb5); check("F5  Version danach 1", db.schema_version(_cc) == 1); _cc.close()
    # Sicherungsordner fehlt -> fehlgeschlagen, Version bleibt 0
    _cc = db.verbinde(_sdb5); db.setze_meta(_cc, "schema_version", "0"); _cc.close()
    _zs6 = um.stelle_bereit(_sdb5, _alt5, _sord5 / "gibts-nicht", _dt2(2026, 10, 8, 9, 5))
    check("F5 Schema-Anhebung ohne Sicherungsordner -> fehlgeschlagen",
          _zs6.art == "fehlgeschlagen" and "Backup" in _zs6.grund, _zs6)
    _cc = db.verbinde(_sdb5); check("F5  Version bleibt 0", db.schema_version(_cc) == 0); _cc.close()
finally:
    db.SCHRITTE.clear()

# F5: kaputter Korpus / Importzustand
for _name, _inhalt in [("archiv_korpus.json", '{"notams": [{"notam_id": 1}]}'),
                       ("archiv_korpus.json", "kein json"),
                       (ai.IMPORT_JSON.name, '{"tage": 5}'),
                       (ai.IMPORT_JSON.name, "kein json")]:
    _d = _altordner(); (_d / _name).write_text(_inhalt, encoding="utf-8")
    _z = Path(tempfile.mkdtemp()) / "nola.db"
    try:
        um.umziehen(_z, um.altdateien_im(_d)); check("F5 kaputt {} -> UmzugFehler".format(_name), False)
    except um.UmzugFehler as e:
        check("F5 kaputt {} -> UmzugFehler".format(_name), _name in str(e), str(e)[:100])
    check("F5  keine nola.db, kein Rest", not _z.exists() and _reste(_z.parent) == [])

# F6: Testschutz Export im ganzen Projektordner
for _ziel6 in (app.APP_DIR / "export", app.APP_DIR / "x"):
    try:
        um.exportieren(_db_p, _ziel6); check("F6 Export nach {} gesperrt".format(_ziel6.name), False)
    except RuntimeError:
        check("F6 Export nach {} gesperrt".format(_ziel6.name), True)
check("F6  Ordner nicht angelegt", not (app.APP_DIR / "export").exists() and not (app.APP_DIR / "x").exists())

# F7: Workspace atomar, Aufraeumen bei Fehler
_atomar = []
_wba_orig = app._write_bytes_atomic
def _wba_spion(pfad, daten):
    _atomar.append(Path(pfad).name); return _wba_orig(pfad, daten)
app._write_bytes_atomic = _wba_spion
try:
    um.exportieren(_db_p, Path(tempfile.mkdtemp()) / "export")
finally:
    app._write_bytes_atomic = _wba_orig
check("F7 notam_workspace.json atomar geschrieben", app.WORKSPACE_FILE.name in _atomar, _atomar)
_ziel7 = Path(tempfile.mkdtemp()) / "export"
_waj_orig = ai.write_json_atomic
def _waj_kaputt(*a, **k):
    raise OSError(_errno.ENOSPC, "No space left")
ai.write_json_atomic = _waj_kaputt
try:
    try:
        um.exportieren(_db_p, _ziel7); check("F7 Fehler wird weitergereicht", False)
    except OSError:
        check("F7 Fehler wird weitergereicht", True)
finally:
    ai.write_json_atomic = _waj_orig
check("F7 Zielordner nach Fehler entfernt", not _ziel7.exists())

# --- Sicherung ohne Nebendateien (nola-a6c.2) ---
from datetime import datetime as _dt3
def _wal_quelle():
    d = Path(tempfile.mkdtemp())
    c = db.verbinde(d / "t.db", anlegen=True); db.lege_schema_an(c); db.setze_wal(c)
    c.execute('INSERT INTO startplaetze ("Kurzel","Latitude","Longitude","Name","Land") VALUES (?,?,?,?,?)', ("KSC", 28.5, -80.6, "Kennedy", "USA")); c.commit()
    return c
_cw = _wal_quelle()
_ow = Path(tempfile.mkdtemp())
_bw = db.sichere(_cw, _ow, _dt3(2026, 10, 8, 9, 0))
_namen = sorted(x.name for x in _ow.iterdir())
check("G1 Ordner enthaelt genau die Sicherung", _namen == [_bw.name], _namen)
check("G1 keine Nebendateien", not any(n.startswith(".") or n.endswith(("-wal", "-shm", "-journal", ".tmp")) for n in _namen), _namen)
_cx = sqlite3.connect(str(_bw))
check("G1 Journal-Modus delete", _cx.execute("PRAGMA journal_mode").fetchone()[0] == "delete")
_cx.close()
_st, _z = db.pruefe_sicherung(_bw)
check("G1 pruefe_sicherung ok mit Zeilenzahl", _st == "ok" and _z is not None and _z.get("startplaetze") == 1 == db.zaehle(_cw, "startplaetze"), (_st, _z))
check("G1 nach Pruefung weiter sauber", sorted(x.name for x in _ow.iterdir()) == [_bw.name])

_orig_replace = os.replace
def _replace_kaputt(*a, **k):
    raise OSError(_errno.EIO, "kaputt")
os.replace = _replace_kaputt
_ow2 = Path(tempfile.mkdtemp())
try:
    try:
        db.sichere(_cw, _ow2, _dt3(2026, 10, 8, 9, 5)); check("G2 Fehler bei replace -> DbFehler", False)
    except db.DbFehler:
        check("G2 Fehler bei replace -> DbFehler", True)
finally:
    os.replace = _orig_replace
check("G2 Ordner nach Fehler leer", list(_ow2.iterdir()) == [], [x.name for x in _ow2.iterdir()])
_cw.close()

print("== 17. Abschlussreview (nola-a6c) ==")
def _lauf(f, *a, **k):
    """Ruft f auf; liefert (Ergebnis, Ausnahme) - ein Fehlschlag wird ein FAIL, kein Absturz."""
    try:
        return f(*a, **k), None
    except Exception as exc:  # noqa: BLE001
        return None, exc

# --- I1: liegengebliebene -wal/-shm neben einer fehlenden nola.db ---
for _endung in ("-wal", "-shm"):
    _d_i1 = Path(tempfile.mkdtemp()); _z_i1 = _d_i1 / "nola.db"
    _neben = Path(str(_z_i1) + _endung); _inhalt_i1 = b"alte Seiten " + _endung.encode()
    _neben.write_bytes(_inhalt_i1)
    _, _e = _lauf(db.stelle_wieder_her, _reg[0], _z_i1)
    check("I1 Wiederherstellen neben {} -> DbFehler stale side files".format(_endung),
          isinstance(_e, db.DbFehler) and _e.ursache == "stale side files" and "Move them away" in str(_e), repr(_e))
    check("I1   keine nola.db, Nebendatei unveraendert, keine tmp",
          not _z_i1.exists() and _neben.read_bytes() == _inhalt_i1
          and sorted(p.name for p in _d_i1.iterdir()) == [_neben.name], [p.name for p in _d_i1.iterdir()])
    _d_i1b = Path(tempfile.mkdtemp()); _z_i1b = _d_i1b / "nola.db"
    _neben_b = Path(str(_z_i1b) + _endung); _neben_b.write_bytes(_inhalt_i1)
    _, _e = _lauf(um.umziehen, _z_i1b, um.altdateien_im(_altordner(mit_echten=False)))
    check("I1 Umzug neben {} -> UmzugFehler".format(_endung),
          isinstance(_e, um.UmzugFehler) and "nola.db-wal / nola.db-shm" in str(_e)
          and "Move them away" in str(_e), repr(_e))
    check("I1   keine nola.db, Nebendatei unveraendert, keine tmp",
          not _z_i1b.exists() and _neben_b.read_bytes() == _inhalt_i1
          and sorted(p.name for p in _d_i1b.iterdir()) == [_neben_b.name], [p.name for p in _d_i1b.iterdir()])
_d_i1c = Path(tempfile.mkdtemp())
_, _e = _lauf(db.stelle_wieder_her, _reg[0], _d_i1c / "nola.db")
check("I1 ohne Nebendatei: Wiederherstellen weiter erfolgreich", _e is None and (_d_i1c / "nola.db").exists(), repr(_e))
_d_i1d = Path(tempfile.mkdtemp())
_, _e = _lauf(um.umziehen, _d_i1d / "nola.db", um.altdateien_im(_altordner(mit_echten=False)))
check("I1 ohne Nebendatei: Umzug weiter erfolgreich", _e is None and (_d_i1d / "nola.db").exists(), repr(_e))

# --- I4: Testschutz greift am Anfang von umziehen und stelle_bereit ---
class _Erreicht(Exception):
    """Der Ablauf kam hinter die Schutzpruefung - ohne Schutz wuerde hier gelesen/angelegt."""
def _erreicht(*a, **k):
    raise _Erreicht()
def _proj_fingerabdruck():
    return hashlib.sha256(db.PROJEKT_DB.read_bytes()).hexdigest() if db.PROJEKT_DB.exists() else None
_proj_vor = _proj_fingerabdruck()
_proj_reste_vor = sorted(p.name for p in db.PROJEKT_DB.parent.iterdir() if p.name.startswith("nola.db"))
_orig_i4 = (um._csv_streng, db.liste_sicherungen, um.umziehen, os.link)
um._csv_streng = _erreicht; db.liste_sicherungen = _erreicht; os.link = _erreicht
try:
    _, _e = _lauf(_orig_i4[2], db.PROJEKT_DB, um.altdateien_im(_altordner(mit_echten=False)))
    check("I4 umziehen(PROJEKT_DB) unter NOLA_TEST -> RuntimeError vor jedem Lesen",
          isinstance(_e, RuntimeError), repr(_e))
    um.umziehen = _erreicht
    _, _e = _lauf(um.stelle_bereit, db.PROJEKT_DB, um.altdateien_im(_altordner(mit_echten=False)),
                  Path(tempfile.mkdtemp()), _dt2(2026, 10, 9, 9, 0))
    check("I4 stelle_bereit(PROJEKT_DB) unter NOLA_TEST -> RuntimeError", isinstance(_e, RuntimeError), repr(_e))
finally:
    um._csv_streng, db.liste_sicherungen, um.umziehen, os.link = _orig_i4
check("I4 Projektdatenbank unveraendert (bzw. weiter nicht vorhanden)", _proj_fingerabdruck() == _proj_vor)
check("I4 keine neuen nola.db*-Dateien im Projekt",
      sorted(p.name for p in db.PROJEKT_DB.parent.iterdir() if p.name.startswith("nola.db")) == _proj_reste_vor)

# --- I3: Cloud uebernimmt neu committete Referenz-CSVs ---
def _sha_datei(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
_d_i3 = _altordner(); _alt_i3 = um.altdateien_im(_d_i3)
_db_i3 = Path(tempfile.mkdtemp()) / "nola.db"; _sord_i3 = Path(tempfile.mkdtemp())
_z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 0))
check("I3 Umzug", _e is None and _z.art == "umgezogen", (_z, _e))
_c_i3 = db.verbinde(_db_i3)
_roh_i3 = db.lese_meta(_c_i3, "referenz_quellen_sha")
check("I3 Umzug legt referenz_quellen_sha ab",
      _roh_i3 is not None and _json.loads(_roh_i3) == {
          "startplaetze": _sha_datei(_alt_i3.startplaetze), "firs": _sha_datei(_alt_i3.firs),
          "traegersysteme": _sha_datei(_alt_i3.traegersysteme)}, _roh_i3)
db.schreibe_unterschiede(_c_i3, db.leerer_arbeitsstand(),
                         dict(db.leerer_arbeitsstand(), confirmed_launches={"k-i3"}), "2026-10-09T09:00:00+00:00")
_c_i3.close()
_ersetze_aufrufe = []
_orig_et = getattr(db, "ersetze_tabellen", None)
def _et_spion(*a, **k):
    _ersetze_aufrufe.append(1); return _orig_et(*a, **k)
db.ersetze_tabellen = _et_spion
try:
    _z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 1), referenzen_aus_dateien=True)
    check("I3 unveraenderte CSVs -> bereit, keine Schreibvorgaenge",
          _e is None and _z.art == "bereit" and _ersetze_aufrufe == [], (_z, _e, _ersetze_aufrufe))
    _sp_df = app._read_csv_any(str(_alt_i3.startplaetze))
    _sp_df.loc[len(_sp_df)] = {"Kurzel": "ZZI3", "Latitude": "1.5", "Longitude": "2.5", "Name": "Test I3", "Land": "China"}
    _sp_df.to_csv(_alt_i3.startplaetze, index=False)
    _z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 2))
    _c_i3 = db.verbinde(_db_i3)
    check("I3 lokal (False): geaenderte CSV wird nicht eingelesen",
          _e is None and _z.art == "bereit" and "ZZI3" not in set(db.lese_tabelle(_c_i3, "startplaetze")["Kurzel"])
          and _ersetze_aufrufe == [], (_z, _e))
    _stand_ar = db.lese_tabelle(_c_i3, "startarchiv").attrs["nola_stand"]
    _c_i3.close()
    _z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 3), referenzen_aus_dateien=True)
    _c_i3 = db.verbinde(_db_i3)
    check("I3 Cloud (True): geaenderte CSV -> Referenztabellen ersetzt, eine Transaktion",
          _e is None and _z.art == "bereit" and "ZZI3" in set(db.lese_tabelle(_c_i3, "startplaetze")["Kurzel"])
          and len(_ersetze_aufrufe) == 1, (_z, _e, _ersetze_aufrufe))
    check("I3   Arbeitsstand und Archiv bleiben",
          db.lade_arbeitsstand(_c_i3)["confirmed_launches"] == {"k-i3"}
          and db.lese_tabelle(_c_i3, "startarchiv").attrs["nola_stand"] == _stand_ar)
    check("I3   Meta aktualisiert",
          _json.loads(db.lese_meta(_c_i3, "referenz_quellen_sha") or "{}").get("startplaetze")
          == _sha_datei(_alt_i3.startplaetze))
    _c_i3.close()
    _z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 4), referenzen_aus_dateien=True)
    check("I3 zweiter Start mit denselben CSVs -> keine weiteren Schreibvorgaenge",
          _e is None and _z.art == "bereit" and len(_ersetze_aufrufe) == 1, (_z, _e, _ersetze_aufrufe))
    _vor_bytes_i3 = {t: None for t in ("startplaetze", "firs", "traegersysteme")}
    _c_i3 = db.verbinde(_db_i3)
    _vor_stand_i3 = {t: db.lese_tabelle(_c_i3, t).attrs["nola_stand"] for t in _vor_bytes_i3}
    _vor_meta_i3 = db.lese_meta(_c_i3, "referenz_quellen_sha")
    _c_i3.close()
    _alt_i3.firs.write_text("falsch,kopf\n1,2\n", encoding="utf-8")
    _z, _e = _lauf(um.stelle_bereit, _db_i3, _alt_i3, _sord_i3, _dt2(2026, 10, 9, 9, 5), referenzen_aus_dateien=True)
    _c_i3 = db.verbinde(_db_i3)
    check("I3 unlesbare CSV -> fehlgeschlagen mit Grund, DB unveraendert",
          _e is None and _z.art == "fehlgeschlagen" and _alt_i3.firs.name in _z.grund
          and {t: db.lese_tabelle(_c_i3, t).attrs["nola_stand"] for t in _vor_bytes_i3} == _vor_stand_i3
          and db.lese_meta(_c_i3, "referenz_quellen_sha") == _vor_meta_i3, (_z, _e))
    _c_i3.close()
finally:
    if _orig_et is None:
        try:
            del db.ersetze_tabellen
        except AttributeError:
            pass
    else:
        db.ersetze_tabellen = _orig_et

# --- M1: Export als eine Momentaufnahme ---
_db_m1 = Path(tempfile.mkdtemp()) / "nola.db"
um.umziehen(_db_m1, um.altdateien_im(_altordner()))
_c_m1 = db.verbinde(_db_m1); db.setze_wal(_c_m1); _c_m1.close()
_pr_orig = app.persist_reference
_pr_n = [0]
def _pr_spion(pfad, df, spalten):
    _pr_n[0] += 1
    if _pr_n[0] == 1:  # nach dem Lesen der Startplaetze, vor dem Lesen der Traegersysteme
        c2 = db.verbinde(_db_m1)
        try:
            c2.execute('INSERT INTO traegersysteme ("Land", "Name", "Alternativname englisch", "Abkürzung") '
                       "VALUES ('China', 'Test M1', '', 'ZZM1')")
        finally:
            c2.close()
    return _pr_orig(pfad, df, spalten)
app.persist_reference = _pr_spion
try:
    _ex_m1, _e = _lauf(um.exportieren, _db_m1, Path(tempfile.mkdtemp()) / "export")
finally:
    app.persist_reference = _pr_orig
_c_m1 = db.verbinde(_db_m1)
check("M1 fremder Schreibvorgang waehrend des Exports kam an",
      "ZZM1" in set(db.lese_tabelle(_c_m1, "traegersysteme")["Abkürzung"]))
_c_m1.close()
check("M1 Export zeigt den Stand vor dem Schreibvorgang",
      _e is None and "ZZM1" not in set(app._read_csv_any(str(_ex_m1 / app.VEHICLE_CSV.name))["Abkürzung"]), repr(_e))

print("== 18. Folgepunkte Aufgabe 1 ==")
from datetime import datetime as _dt14, date as _date14
import errno as _errno14

# --- Fehlerzuordnung: echte SQLite-Fehler je Art ---
def _fang(aufruf):
    try:
        aufruf()
    except sqlite3.Error as exc:
        return db._uebersetze(exc)
    return None

_d14 = Path(tempfile.mkdtemp())
_k14 = sqlite3.connect(str(_d14 / "k.db"), isolation_level=None)
_k14.execute('CREATE TABLE t (full_name TEXT UNIQUE, locked_by TEXT NOT NULL, readonly TEXT)')
_k14.execute("INSERT INTO t VALUES ('a', 'x', 'r')")
_f = _fang(lambda: _k14.execute("INSERT INTO t VALUES ('a', 'y', 'r')"))
check("Fehler: UNIQUE auf Spalte full_name -> constraint", _f is not None and _f.ursache == "constraint failed",
      None if _f is None else (_f.ursache, str(_f)))
_f = _fang(lambda: _k14.execute("INSERT INTO t (full_name) VALUES ('b')"))
check("Fehler: NOT NULL auf Spalte locked_by -> constraint, nicht gesperrt",
      _f is not None and _f.ursache == "constraint failed" and not isinstance(_f, db.Gesperrt),
      None if _f is None else (_f.ursache, str(_f)))
_f = _fang(lambda: _k14.execute("SELECT full_name_x FROM t"))
check("Fehler: unbekannte Spalte mit 'full' -> allgemein, nicht disk full",
      _f is not None and _f.ursache == "error", None if _f is None else (_f.ursache, str(_f)))
_f = _fang(lambda: _k14.execute("SELECT readonly_x FROM t"))
check("Fehler: unbekannte Spalte mit 'readonly' -> allgemein",
      _f is not None and _f.ursache == "error", None if _f is None else (_f.ursache, str(_f)))
# Platte voll: Seitenzahl deckeln, dann viel schreiben
_k14.execute("CREATE TABLE gross (x TEXT)")
_k14.execute("PRAGMA max_page_count = {}".format(_k14.execute("PRAGMA page_count").fetchone()[0]))
_f = _fang(lambda: _k14.execute("INSERT INTO gross VALUES (?)", ("x" * 100000,)))
check("Fehler: Datenbank voll -> disk full", _f is not None and _f.ursache == "disk full",
      None if _f is None else (_f.ursache, str(_f)))
_k14.close()
# nur lesend geoeffnet
_ro14 = sqlite3.connect("file:{}?mode=ro".format(str(_d14 / "k.db")), uri=True, isolation_level=None)
_f = _fang(lambda: _ro14.execute("INSERT INTO t VALUES ('z', 'z', 'z')"))
check("Fehler: schreibgeschuetzt -> read-only", _f is not None and _f.ursache == "read-only",
      None if _f is None else (_f.ursache, str(_f)))
_ro14.close()
# defekte Datei
(_d14 / "kaputt.db").write_bytes(b"das ist keine sqlite-datei" * 200)
_kp14 = sqlite3.connect(str(_d14 / "kaputt.db"))
_f = _fang(lambda: _kp14.execute("SELECT * FROM sqlite_master").fetchall())
check("Fehler: keine Datenbank -> database corrupt", _f is not None and _f.ursache == "database corrupt",
      None if _f is None else (_f.ursache, str(_f)))
_kp14.close()
# gesperrt (echte zweite Schreibtransaktion, kurze Wartezeit)
_g1 = sqlite3.connect(str(_d14 / "k.db"), isolation_level=None)
_g2 = sqlite3.connect(str(_d14 / "k.db"), isolation_level=None, timeout=0.1)
_g1.execute("BEGIN IMMEDIATE")
_f = _fang(lambda: _g2.execute("BEGIN IMMEDIATE"))
check("Fehler: zweite Schreibtransaktion -> Gesperrt", isinstance(_f, db.Gesperrt) and _f.ursache == "locked",
      None if _f is None else (_f.ursache, str(_f)))
_g1.execute("ROLLBACK"); _g1.close(); _g2.close()
# Klasse vor Text: IntegrityError mit irrefuehrendem Text bleibt constraint
_f = db._uebersetze(sqlite3.IntegrityError("database is locked"))
check("Fehler: IntegrityError -> constraint (Klasse vor Text)", _f.ursache == "constraint failed", _f.ursache)

# --- Eine Tabellenliste fuer Schema, zaehle und pruefe_sicherung ---
_p14, _c14 = neue_db()
_schema_tab = {n for (n,) in _c14.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
check("Tabellenliste = Schema", set(getattr(db, "ALLE_TABELLEN", ())) == _schema_tab,
      sorted(_schema_tab ^ set(getattr(db, "ALLE_TABELLEN", ()))))
_nicht_zaehlbar = []
for _t in sorted(_schema_tab):
    try:
        db.zaehle(_c14, _t)
    except ValueError:
        _nicht_zaehlbar.append(_t)
check("jede Schema-Tabelle zaehlbar", _nicht_zaehlbar == [], _nicht_zaehlbar)
try:
    db.zaehle(_c14, "sqlite_master"); check("unbekannte Tabelle -> ValueError", False)
except ValueError:
    check("unbekannte Tabelle -> ValueError", True)

# --- setze_wal, Meta, NULL ---
db.setze_wal(_c14)
_jm14 = _c14.execute("PRAGMA journal_mode").fetchone()[0]
check("setze_wal -> Modus wal", _jm14 == "wal", _jm14)
check("lese_meta: fehlender Schluessel -> None", db.lese_meta(_c14, "gibts_nicht") is None)
db.setze_meta(_c14, "test_schluessel", "eins")
check("Meta Rundlauf", db.lese_meta(_c14, "test_schluessel") == "eins")
db.setze_meta(_c14, "test_schluessel", "zwei")
check("Meta ueberschreiben", db.lese_meta(_c14, "test_schluessel") == "zwei"
      and _c14.execute("SELECT count(*) FROM meta WHERE schluessel = 'test_schluessel'").fetchone()[0] == 1)
_c14.execute('INSERT INTO startplaetze ("Kurzel", "Latitude", "Longitude", "Name", "Land") '
             "VALUES ('NUL', '1', '2', NULL, NULL)")
_n14 = db.lese_tabelle(_c14, "startplaetze")
check("SQL-NULL -> NaN in lese_tabelle", pd.isna(_n14.loc[0, "Name"]) and pd.isna(_n14.loc[0, "Land"])
      and isinstance(_n14.loc[0, "Name"], float), repr(_n14.loc[0, "Name"]))

# --- sichere: Aufraeumen auf den Fehlerpfaden ---
class _QuelleKaputt:
    """Quelle, deren backup() mitten in der Kopie scheitert (Kopie schon angelegt)."""
    def backup(self, ziel):
        ziel.execute("PRAGMA journal_mode = WAL"); ziel.execute("CREATE TABLE x (a)")
        raise sqlite3.OperationalError("disk I/O error")
_ord14a = Path(tempfile.mkdtemp())
try:
    db.sichere(_QuelleKaputt(), _ord14a, _dt14(2026, 10, 9, 9, 0)); check("Backup-Fehler -> DbFehler", False)
except db.DbFehler as e:
    check("Backup-Fehler -> DbFehler", True, e.ursache)
check("Backup-Fehler: Ordner leer (keine .tmp/Nebendateien)", list(_ord14a.iterdir()) == [],
      [p.name for p in _ord14a.iterdir()])

class _KopieDefekt:
    def __init__(self, echt): self.echt = echt
    def execute(self, sql, *a):
        if "integrity_check" in sql:
            class _C:
                def fetchone(self): return ("*** in database main ***",)
            return _C()
        return self.echt.execute(sql, *a)
    def close(self): self.echt.close()
class _QuelleGut:
    def __init__(self, echt): self.echt = echt
    def backup(self, ziel): self.echt.backup(ziel.echt if isinstance(ziel, _KopieDefekt) else ziel)
_ord14b = Path(tempfile.mkdtemp())
_connect14 = db.sqlite3.connect
_p14b, _c14b = neue_db(); db.setze_wal(_c14b)
db.sqlite3.connect = lambda *a, **k: _KopieDefekt(_connect14(*a, **k))
try:
    db.sichere(_QuelleGut(_c14b), _ord14b, _dt14(2026, 10, 9, 9, 0)); check("integrity-Fehler -> DbFehler", False)
except db.DbFehler as e:
    check("integrity-Fehler -> DbFehler", e.ursache == "backup corrupt", e.ursache)
finally:
    db.sqlite3.connect = _connect14
check("integrity-Fehler: Ordner leer (keine .tmp/Nebendateien)", list(_ord14b.iterdir()) == [],
      [p.name for p in _ord14b.iterdir()])

# --- Sicherungsnamen: Sekunden, alte 4-stellige Namen, gemischte Sortierung ---
_ord14c = Path(tempfile.mkdtemp())
_s14a = db.sichere(_c14b, _ord14c, _dt14(2026, 10, 9, 9, 0, 5))
_s14b = db.sichere(_c14b, _ord14c, _dt14(2026, 10, 9, 9, 0, 40))
check("zwei Sicherungen derselben Minute ueberschreiben sich nicht",
      _s14a != _s14b and _s14a.exists() and _s14b.exists(), (_s14a.name, _s14b.name))
_ord14d = Path(tempfile.mkdtemp())
for _n in ("nola-2026-10-09-0837.db", "nola-2026-10-09-083712.db", "nola-2026-10-09-0901.db",
           "nola-2026-10-09-090030.db", "nola-2026-10-08-235959.db", "nola-2026-10-09-0837-vor-schema-2.db",
           "nola-2026-10-09-08371.db", "nola-2026-10-09-0837.db.tmp"):
    (_ord14d / _n).write_bytes(b"x")
_reg14 = [p.name for p in db.liste_sicherungen(_ord14d, nur_regulaer=True)]
check("gemischte Namen: neueste zuerst ueber beide Formate", _reg14 == [
    "nola-2026-10-09-0901.db", "nola-2026-10-09-090030.db", "nola-2026-10-09-083712.db",
    "nola-2026-10-09-0837.db", "nola-2026-10-08-235959.db"], _reg14)
check("gemischte Namen: Zusatz erkannt, Fremdnamen nicht",
      sorted(p.name for p in db.liste_sicherungen(_ord14d)) == sorted(_reg14 + ["nola-2026-10-09-0837-vor-schema-2.db"]))
_neu14 = db.sichere(_c14b, _ord14d, _dt14(2026, 10, 9, 9, 5, 7), behalten=3)
_rest14 = sorted(p.name for p in _ord14d.iterdir())
check("Rotation ueber beide Formate", _rest14 == sorted([
    "nola-2026-10-09-090507.db", "nola-2026-10-09-0901.db", "nola-2026-10-09-090030.db",
    "nola-2026-10-09-0837-vor-schema-2.db", "nola-2026-10-09-08371.db", "nola-2026-10-09-0837.db.tmp"]), _rest14)
_ord14e = Path(tempfile.mkdtemp()); (_ord14e / "nola-2026-10-09-0837.db").write_bytes(b"x")
check("faellig: alter 4-stelliger Name zaehlt fuer heute",
      not db.sicherung_faellig(_ord14e, _date14(2026, 10, 9)) and db.sicherung_faellig(_ord14e, _date14(2026, 10, 10)))
_ord14f = Path(tempfile.mkdtemp()); (_ord14f / "nola-2026-10-09-083712.db").write_bytes(b"x")
check("faellig: neuer 6-stelliger Name zaehlt fuer heute",
      not db.sicherung_faellig(_ord14f, _date14(2026, 10, 9)) and db.sicherung_faellig(_ord14f, _date14(2026, 10, 10)))
_ord14g = Path(tempfile.mkdtemp()); (_ord14g / "nola-2026-10-09-083712-vor-schema-2.db").write_bytes(b"x")
check("faellig: Zusatz-Sicherung zaehlt nicht", db.sicherung_faellig(_ord14g, _date14(2026, 10, 9)))

# --- behalten <= 0 ---
for _b in (0, -1):
    _ord14h = Path(tempfile.mkdtemp()); (_ord14h / "nola-2026-10-01-0000.db").write_bytes(b"x")
    try:
        db.sichere(_c14b, _ord14h, _dt14(2026, 10, 9, 9, 0), behalten=_b)
        check("behalten={} -> ValueError".format(_b), False)
    except ValueError:
        check("behalten={} -> ValueError".format(_b), True)
    check("behalten={}: nichts geschrieben oder geloescht".format(_b),
          [p.name for p in _ord14h.iterdir()] == ["nola-2026-10-01-0000.db"], [p.name for p in _ord14h.iterdir()])
_c14b.close(); _c14.close()

# --- schuetze_echte_orte: Unterordner und Symlinks ---
_echt14 = Path(tempfile.mkdtemp()) / "Backups"; (_echt14 / "unter" / "tief").mkdir(parents=True)
_link_d14 = Path(tempfile.mkdtemp())
(_link_d14 / "auf_ordner").symlink_to(_echt14)
(_link_d14 / "auf_unter").symlink_to(_echt14 / "unter")
_frei14 = Path(tempfile.mkdtemp())
_echt_orig14 = db.ECHTER_SICHERUNGSORDNER
db.ECHTER_SICHERUNGSORDNER = _echt14
try:
    for _label, _pf in [("Ordner selbst", _echt14), ("Unterordner", _echt14 / "unter"),
                        ("tiefer Unterordner", _echt14 / "unter" / "tief"),
                        ("Datei im Unterordner", _echt14 / "unter" / "nola-2026-10-09-0837.db"),
                        ("Symlink auf Ordner", _link_d14 / "auf_ordner"),
                        ("Symlink auf Unterordner", _link_d14 / "auf_unter"),
                        ("Datei hinter Symlink", _link_d14 / "auf_unter" / "x.db"),
                        ("Pfad mit ..", _frei14 / ".." / _echt14.parent.name / "Backups" / "unter")]:
        try:
            db.schuetze_echte_orte(_pf); check("Schutz sperrt " + _label, False, _pf)
        except RuntimeError:
            check("Schutz sperrt " + _label, True)
    try:
        db.sichere(None, _echt14 / "unter", _dt14(2026, 10, 9, 9, 0)); check("sichere sperrt Unterordner", False)
    except RuntimeError:
        check("sichere sperrt Unterordner", True)
    try:
        db.schuetze_echte_orte(_frei14, _echt14.parent / "Backups-Nachbar", _link_d14)
        check("Schutz laesst Nachbarordner frei", True)
    except RuntimeError as e:
        check("Schutz laesst Nachbarordner frei", False, e)
finally:
    db.ECHTER_SICHERUNGSORDNER = _echt_orig14
check("echter Sicherungsordner wieder eingesetzt", db.ECHTER_SICHERUNGSORDNER == _echt_orig14)
check("Testordner unberuehrt", sorted(p.name for p in _echt14.iterdir()) == ["unter"])

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
