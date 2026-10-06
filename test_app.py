import os, sys, math, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app

ok = True
def check(label, cond, extra=""):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label + (" " + str(extra) if extra else ""))
    if not cond: ok = False

print("== 1. Koordinaten-Engine ==")
c = app.extract_coordinates("AREA WITHIN 1936N11057E")
check("kompakt 1936N11057E -> 19.60/110.95", c == [(19.6, 110.95)], c)
c = app.extract_coordinates("193612N1105730E")
check("mit Sekunden 193612N1105730E", c and abs(c[0][0]-19.6033)<1e-3 and abs(c[0][1]-110.9583)<1e-3, c)
c = app.extract_coordinates("19°36'N 110°57'E")
check("Gradzeichen", c == [(19.6, 110.95)], c)
c = app.extract_coordinates("12.50S 130.25W")
check("Dezimal + Hemisphaere S/W", c == [(-12.5, -130.25)], c)
c = app.extract_coordinates("BOUNDED BY 1936N11057E 1948N11212E 1902N11230E")
check("Polygon 3 Punkte", len(c) == 3, c)
check("ungueltige Minuten (1975N) verworfen", app.extract_coordinates("1975N11057E") == [], app.extract_coordinates("1975N11057E"))
check("Radius 50NM", abs(app.extract_radius_km("WITHIN 50NM RADIUS OF 1936N11057E") - 92.6) < 0.01)
check("Radius RADIUS OF 30KM", abs(app.extract_radius_km("RADIUS OF 30KM") - 30.0) < 0.01)

print("== 2. Geodaesie / Orbitmechanik ==")
d = app.haversine_km(0,0,0,1)
check("Haversine 1 Grad am Aequator ~111.2km", abs(d-111.19)<0.1, round(d,3))
b = app.initial_bearing_deg(0,0,0,10)
check("Bearing Ost = 90", abs(b-90)<1e-6, b)
b = app.initial_bearing_deg(50,0,60,10)
check("Bearing NE-Quadrant", 0 < b < 90, round(b,2))
i = app.estimate_inclination_deg(28.5, 90)
check("Inklination KSC-aehnlich (28.5/90) = 28.5", abs(i-28.5)<1e-6, round(i,3))
i = app.estimate_inclination_deg(45, 180)
# Nicht exakt 90: Bei einem Start genau nach Sueden traegt die Erddrehung eine
# Ostkomponente bei, die Bahn wird dadurch leicht rechtlaeufig. Das ist der
# physikalische Wert, nicht ein Rundungsfehler.
check("Azimut 180 von 45N -> knapp unter 90", 88.0 < i < 88.5, round(i, 3))
check("  ... ohne Erdrotation waeren es 90", abs(
    __import__("math").degrees(__import__("math").acos(
        __import__("math").cos(__import__("math").radians(45))
        * __import__("math").sin(__import__("math").radians(180)))) - 90) < 1e-6)
check("Start nach Osten bleibt unveraendert - die Drehung wirkt dort laengs",
      abs(app.estimate_inclination_deg(28.5, 90) - 28.5) < 1e-6,
      round(app.estimate_inclination_deg(28.5, 90), 3))
check("Klassifikation SSO", app.classify_orbit(98.0) == app.ORBIT_SSO)
check("Klassifikation retrograd", app.classify_orbit(108.0) == app.ORBIT_RETROGRADE)
check("Klassifikation LEO", app.classify_orbit(51.6) == app.ORBIT_LEO_MEO)
check("Klassifikation aequatorial", app.classify_orbit(20.0) == app.ORBIT_GTO)
check("Klassifikation None", app.classify_orbit(None) == app.ORBIT_UNKNOWN)
lat,lon = app.destination_point(0,0,90,111.19)
check("Zielpunkt 111km Ost ~ 1 Grad", abs(lat)<1e-6 and abs(lon-1.0)<1e-3, (round(lat,5),round(lon,5)))
cen = app.polygon_centroid([(0,0),(0,2),(2,2),(2,0)])
check("Centroid Quadrat = (1,1)", abs(cen[0]-1)<1e-9 and abs(cen[1]-1)<1e-9, cen)

print("== 3. Trigger & Items ==")
it = app.extract_items("A1/25 Q) ZBPE/QRTCA/IV/BO/W/000/999 A) ZBPE B) 2509210130 C) 2509210430 E) ROCKET LAUNCH F) SFC G) UNL")
check("Items Q/A/B/C/E/F/G erkannt", set("QABCEFG") <= set(it.keys()), sorted(it))
check("A-Item = ZBPE", it["A"] == "ZBPE", it.get("A"))
check("G-Item = UNL", it["G"] == "UNL", it.get("G"))
tr = app.detect_triggers("ROCKET LAUNCH SFC/UNL", {"Q":"W/000/999"})
check("Trigger Keyword+Hoehe+Qcode", len(tr) >= 3, tr)
check("kein Trigger bei Kran-NOTAM", app.detect_triggers("CRANE ERECTED 150M AGL", {}) == [])
dt = app.parse_notam_datetime("2509210130")
check("YYMMDDHHMM -> 2025-09-21 01:30Z", dt.year==2025 and dt.month==9 and dt.day==21 and dt.hour==1 and dt.minute==30, dt)
check("PERM -> None", app.parse_notam_datetime("PERM") is None)
check("Hoehenprofil SFC-UNL", app.extract_altitude_profile("x", {"F":"SFC","G":"UNL"}) == "SFC - UNL")
joined = "A1/25 A) ZJSA E) ROCKET LAUNCH F) SFC G) UNL | NOTAM ID: A1/25 | FIR: ZJSA | Valid From: 2509210130"
it2 = app.extract_items(joined)
check("letztes Item schluckt keine Spaltenwerte", it2["G"] == "UNL", repr(it2.get("G")))
check("Hoehenprofil bleibt sauber", app.extract_altitude_profile(joined, it2) == "SFC - UNL",
      app.extract_altitude_profile(joined, it2))
check("E-Item endet am Spalten-Trenner", it2["E"] == "ROCKET LAUNCH", repr(it2.get("E")))

print("== 4. Referenzdaten ==")
sp = app.load_spaceports(str(app.SPACEPORT_CSV))
fir = app.load_firs(str(app.FIR_CSV))
check("Weltraumbahnhoefe geladen", len(sp) >= 31, len(sp))
check("FIRs geladen", len(fir) >= 86, len(fir))
check("FIR-Referenz nennt das Land der FIR", "Land" in fir.columns)
inland = fir[fir["Land"].isin(app.TARGET_NATIONS)]
check("FIRs im Gebiet der Zielnationen vorhanden", len(inland) >= 25, len(inland))
check("Drittstaaten-FIRs vorhanden", len(fir) - len(inland) >= 50, len(fir) - len(inland))
check("Alle Zielnationen vertreten", set(app.TARGET_NATIONS) <= set(sp["Land"]), sorted(set(sp["Land"])))
check("Mehrfach-Nation FIR gesplittet", fir.loc[fir["ICAO Code"]=="RJJJ","Nationen"].iloc[0] == ["Nordkorea","China","Russland"])

print("== 5. Gesamtpipeline (Demo-Daten) ==")
demo = app.build_demo_notams()
events, stats = app.analyze_notams(demo, sp, fir)
print("   stats:", {k:v for k,v in stats.items() if k!="mapping"})
print("   mapping:", stats["mapping"])
check("7 Zeilen gelesen", stats["rows"] == 7, stats["rows"])
check("Kran-NOTAM ohne Trigger verworfen", stats["no_trigger"] == 1, stats["no_trigger"])
check("6 Events", stats["events"] == 6, stats["events"])
check("5 OK / 1 Review", stats["ok"] == 5 and stats["review"] == 1, (stats["ok"], stats["review"]))

by_id = {e.notam_id: e for e in events}
print()
for e in events:
    print("   {:10s} {:10s} {:26s} az={:>6s} i={:>6s} {:34s} {}".format(
        e.notam_id, str(e.nation), str(e.spaceport_code)+" / "+str(e.fir_code),
        "{:.1f}".format(e.azimuth_deg) if e.azimuth_deg is not None else "-",
        "{:.1f}".format(e.inclination_deg) if e.inclination_deg is not None else "-",
        e.orbit_type, e.status + (" ("+e.review_reason+")" if e.review_reason else "")))
print()
check("A1234/25 -> Wenchang", by_id["A1234/25"].spaceport_code == "WSLC", by_id["A1234/25"].spaceport_code)
check("A1234/25 Polygon mit 4 Punkten", len(by_id["A1234/25"].coordinates) == 4, len(by_id["A1234/25"].coordinates))
check("A1234/25 Q-Line-Punkt nicht im Polygon", all(abs(c[0]-19.5)>0.01 for c in by_id["A1234/25"].coordinates))
check("B0456/25 -> Jiuquan", by_id["B0456/25"].spaceport_code == "JSLC", by_id["B0456/25"].spaceport_code)
check("B0456/25 Radius 92.6km erkannt", abs(by_id["B0456/25"].radius_km - 92.6) < 0.1, by_id["B0456/25"].radius_km)
check("C0777/25 -> Russland", by_id["C0777/25"].nation == "Russland", by_id["C0777/25"].nation)
check("V0099/25 -> SDSC (Gradzeichen-Parsing)", by_id["V0099/25"].spaceport_code == "SDSC", by_id["V0099/25"].spaceport_code)
check("K0021/25 -> Nordkorea/Sohae", by_id["K0021/25"].spaceport_code == "KSS", by_id["K0021/25"].spaceport_code)
check("R0555/25 im Review (keine Koordinaten)", by_id["R0555/25"].status == "REVIEW", by_id["R0555/25"].review_reason)
check("Startfenster formatiert", by_id["A1234/25"].launch_window == "21.09.2025 01:30Z - 21.09.2025 04:30Z", by_id["A1234/25"].launch_window)

print("== 6. Tabelle & Export ==")
df = app.events_to_dataframe(events)
need = ["NOTAM ID","Startnation","Weltraumbahnhof","Startfenster (UTC)","FIR Code","Höhenprofil","Launch Azimut (°)","Est. Inklination (°)","Orbit-Typ"]
check("Alle geforderten Spalten vorhanden", all(c in df.columns for c in need), [c for c in need if c not in df.columns])
check("Azimut auf 1 Dezimale gerundet", all(abs(v*10-round(v*10))<1e-9 for v in df["Launch Azimut (°)"].dropna()))
import json as _j
payload = [app.event_to_export_dict(e) for e in events]
s = _j.dumps(payload, ensure_ascii=False)
check("JSON-Export serialisierbar", len(s) > 100)
check("CSV-Export erzeugbar", len(df.to_csv(index=False)) > 100)

print("== 7. Karte ==")
m = app.build_event_map([e for e in events if e.status == "OK"])
html = m.get_root().render()
check("folium-Karte gerendert", "leaflet" in html.lower() and len(html) > 10000, len(html))

print("== 8. Robustheit ==")
import pandas as pd
check("leerer Text -> keine Koordinaten", app.extract_coordinates("") == [])
odd = pd.DataFrame({"raw": ["E) ROCKET LAUNCH DEBRIS AREA 1936N11057E SFC/UNL"]})
ev2, st2 = app.analyze_notams(odd, sp, fir)
check("Einspaltige CSV ohne Header-Hinweise verarbeitbar", st2["events"] == 1, st2)
check("Einzelpunkt wird zugeordnet", ev2[0].spaceport_code is not None, ev2[0].status)
ev3, st3 = app.analyze_notams(pd.DataFrame({"x": ["nichts relevantes hier"]}), sp, fir)
check("irrelevante Zeile erzeugt kein Event", st3["events"] == 0, st3)

print("== 9. Konfidenz-Scoring ==")
balloon = "E) MET AIR BALLOON LAUNCH FM NAVAL SHIP 1700N07000E F) SFC G) UNL"
sc, lvl, notes = app.score_confidence(balloon, app.detect_triggers(balloon, {}))
check("Wetterballon -> LOW", lvl == "LOW", (sc, lvl))
launch = ("E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH ACTIVITY. FALLING DEBRIS "
          "EXPECTED. ROCKET STAGE IMPACT 1936N11057E SFC/UNL")
sc, lvl, notes = app.score_confidence(launch, app.detect_triggers(launch, {"Q": "W/000/999"}))
check("echtes Launch-NOTAM -> HIGH", lvl == "HIGH", (sc, lvl))
searchlight = "E) SEARCHLIGHT DISPLAY WI 0.5NM RADIUS OF 512846N 0001745W F) SFC G) UNL"
check("Suchscheinwerfer -> LOW",
      app.score_confidence(searchlight, app.detect_triggers(searchlight, {}))[1] == "LOW")

print("== 10. Nations-Attribution ==")
check("NORTH KOREA erkannt", app.detect_nation_hint("ROCKET LAUNCHED FROM NORTH KOREA")[0] == "Nordkorea")
check("VOSTOCHNY -> Russland", app.detect_nation_hint("LAUNCH FROM VOSTOCHNY")[0] == "Russland")
check("SRIHARIKOTA -> Indien", app.detect_nation_hint("LAUNCH FROM SRIHARIKOTA SHAR")[0] == "Indien")
check("'INDIAN OCEAN' ist keine Nationsnennung",
      app.detect_nation_hint("SPLASHDOWN IN THE INDIAN OCEAN")[0] is None,
      app.detect_nation_hint("SPLASHDOWN IN THE INDIAN OCEAN"))
check("SpaceX ist kein Fremdbetreiber mehr",
      app.detect_foreign_operator("SPACE X STARSHIP RE-ENTRY") == [],
      app.detect_foreign_operator("SPACE X STARSHIP RE-ENTRY"))
check("  ... sondern ein US-Hinweis",
      app.detect_nation_hint("SPACE X STARSHIP RE-ENTRY")[0] == "USA",
      app.detect_nation_hint("SPACE X STARSHIP RE-ENTRY"))
check("Ariane bleibt Fremdbetreiber", app.detect_foreign_operator("ARIANE 6 FROM KOUROU") != [])
check("Amateurraketen werden ausgeschlossen",
      app.score_confidence("ROCKET LAUNCH BY ASSOCIATION OF EXPERIMENTAL ROCKETRY (AEROPAC)",
                           ["Keyword: ROCKET"])[1] == "LOW")
check("kein Fremdbetreiber bei CZ-Start", app.detect_foreign_operator("LONG MARCH CZ-5 LAUNCH") == [])

print("== 11. Regressionen aus Echtdaten ==")
import pandas as pd
cases = pd.DataFrame({"Location": ["EGLL", "FIMM", "ZLC", "RJJJ"], "Text": [
    "A3622/26 Q) EGTT/QXXLW/IV/BO/AW/000/999 A) EGLL E) SEARCHLIGHT DISPLAY WI 0.5NM "
    "RADIUS OF 512846N 0001745W (KEW). F) SFC G) UNL",
    "A0096/26 Q) FIMM/QRALW/IV/NBO/AE/000/999 A) FIMM E) STATIONARY ALTITUDE RESERVATION "
    "FOR ATMOSPHERIC RE-ENTRY AND SPLASHDOWN OF SPACE X STARSHIP FTL-14 ROCKET WI AN AREA "
    "BOUNDED BY 2630S 07500E 2704S 07318E 2436S 07206E 2342S 07500E",
    "!FDC 6/2736 ZLC AIRSPACE BLACK ROCK, NV..TEMPORARY FLIGHT RESTRICTIONS WI AN AREA "
    "DEFINED AS 15NM RADIUS OF 405242N1190233W SFC-UNL FOR ROCKET LAUNCH ACT. PURSUANT TO "
    "14 CFR SECTION 91.143. ASSOCIATION OF EXPERIMENTAL ROCKETRY OF THE PACIFIC (AEROPAC).",
    "P3998/26 Q)RJJJ/QRTCA/IV/BO/W/000/999 A)RJJJ E)ANTIBALLISTIC MISSILES MAY BE LAUNCHED "
    "FOR THE DESTRUCTION OF AN OBJECT PROPELLED BY ROCKET LAUNCHED FROM NORTH KOREA. "
    "AIRSPACE BOUNDED BY 264419N1275729E 255619N1275729E 255619N1272129E 264419N1272129E",
]})
ev, _ = app.analyze_notams(cases, sp, fir, min_confidence="MEDIUM")
res = {e.raw_text[:8].strip(): e for e in ev}
london = [e for e in ev if "SEARCHLIGHT" in e.raw_text][0]
check("Londoner Suchscheinwerfer nicht als Start", london.status == "REVIEW", london.review_reason)
check("  ... und nicht Russland zugeordnet", london.nation is None, london.nation)
starship = [e for e in ev if "STARSHIP" in e.raw_text][0]
check("SpaceX-Wiedereintritt nicht als indischer Start",
      starship.nation != "Indien", (starship.status, starship.nation))
check("  ... sondern den USA zugeordnet", starship.nation == "USA", starship.nation)
check("  ... mit Starbase als Startplatz", starship.spaceport_code == "KBRO",
      starship.spaceport_code)
nevada = [e for e in ev if "BLACK ROCK" in e.raw_text][0]
check("US-Amateurrakete nicht als russischer Start", nevada.status == "REVIEW", nevada.review_reason)
nk = [e for e in ev if "NORTH KOREA" in e.raw_text][0]
check("Japanisches NOTAM korrekt Nordkorea zugeordnet",
      nk.status == "OK" and nk.nation == "Nordkorea" and nk.spaceport_code == "KSS",
      (nk.status, nk.nation, nk.spaceport_code))
check("  ... mit suedlichem Azimut (nicht Richtung China)", 150 < nk.azimuth_deg < 200, nk.azimuth_deg)

print("== 12. Excel-/Upload-Pfad ==")
import io, glob
class UploadedFileStub(io.BytesIO):
    """Verhaelt sich wie Streamlits UploadedFile (BytesIO + .name)."""
    def __init__(self, path):
        super().__init__(open(path, "rb").read())
        self.name = os.path.basename(path)

xls = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.xls")))
if xls:
    up = UploadedFileStub(xls[0])
    real = app.read_notam_table(up, up.name)
    check("Excel-Export mit Vorspann gelesen", len(real) > 100 and "Location" in real.columns,
          (len(real), list(real.columns)[:2]))
    check("Kopfzeile korrekt erkannt", not str(real.columns[0]).startswith("Unnamed"), real.columns[0])
    ev_real, st_real = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    check("Echtdaten laufen ohne Fehler durch", st_real["events"] > 0, st_real["events"])
    no_eu = [e for e in ev_real if e.status == "OK" and e.fir_code in ("EGTT","EGLL","EGPX","LFRR")]
    check("keine europaeischen FIRs als Zielnations-Start", no_eu == [], [e.notam_id for e in no_eu])
    up2 = UploadedFileStub(xls[0]); up2.name = "ohne_endung"
    check("Format auch ohne Dateiendung erkannt (Magic Bytes)",
          len(app.read_notam_table(up2, up2.name)) == len(real))
else:
    print("  SKIP  keine .xls-Testdatei im Projektordner")

print("== 13. Freitext-Eingabe: Normalisierung ==")
check("geschuetztes Leerzeichen -> normal", "\u00a0" not in app.normalize_pasted_text("A\u00a0B"))
check("typografisches Apostroph -> ASCII", app.normalize_pasted_text("12\u00b030\u2032N") == "12\u00b030'N",
      repr(app.normalize_pasted_text("12\u00b030\u2032N")))
check("Ordinalzeichen -> Gradzeichen", app.normalize_pasted_text("12\u00ba30'N") == "12\u00b030'N")
check("CRLF -> LF", "\r" not in app.normalize_pasted_text("A\r\nB"))
check("Etikett 'NOTAM:' entfernt", app.normalize_pasted_text("NOTAM: A1/25 X").startswith("A1/25"),
      app.normalize_pasted_text("NOTAM: A1/25 X"))
check("Gedankenstrich -> Bindestrich", app.normalize_pasted_text("A \u2013 B") == "A - B")

print("== 14. Freitext-Eingabe: Aufteilung ==")
one = "A1234/25 NOTAMN\nA) ZJSA\n\nE) SPACE LAUNCH 1936N11057E\nF) SFC G) UNL"
check("ein NOTAM mit Leerzeile bleibt zusammen", len(app.split_pasted_notams(one)) == 1,
      len(app.split_pasted_notams(one)))
two = "A1234/25 NOTAMN A) ZJSA E) SPACE LAUNCH 1936N11057E\nB0456/25 NOTAMN A) ZWUQ E) ROCKET 4012N09948E"
check("zwei NOTAMs an Kennungen getrennt", len(app.split_pasted_notams(two)) == 2,
      len(app.split_pasted_notams(two)))
faa = "!FDC 6/1234 ZKC AIRSPACE ROCKET LAUNCH 4012N09948E\n!FDC 6/1235 ZKC AIRSPACE ROCKET LAUNCH 4112N09948E"
check("FAA-Domestic-Format getrennt", len(app.split_pasted_notams(faa)) == 2, len(app.split_pasted_notams(faa)))
noid = "SPACE LAUNCH DEBRIS 1936N11057E SFC/UNL\n\nROCKET LAUNCH DEBRIS 4012N09948E SFC/UNL"
check("ohne Kennung an Leerzeilen getrennt", len(app.split_pasted_notams(noid)) == 2,
      len(app.split_pasted_notams(noid)))
check("leerer Text -> keine NOTAMs", app.split_pasted_notams("   \n  ") == [])

print("== 15. Freitext-Eingabe: Schreibweisen ==")
STYLES = {
    "mehrzeilig": "A1234/25 NOTAMN\nQ) ZJSA/QRTCA/IV/BO/W/000/999\nA) ZJSA B) 2509210130 C) 2509210430\n"
                  "E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH. FALLING DEBRIS WITHIN AREA\n"
                  "1936N11057E 1948N11212E 1902N11230E 1850N11115E\nF) SFC G) UNL",
    "einzeilig": "B0456/25 NOTAMN Q) ZWUQ/QRDCA/IV/BO/W/000/999 A) ZWUQ E) DANGER AREA DUE TO "
                 "ROCKET LAUNCH. DEBRIS WITHIN 50NM RADIUS OF 4012N09948E. SFC/UNL",
    "kleinschreibung": "c0777/25 notamn\na) uhpp b) 2509211200 c) 2509211500\n"
                       "e) temporary danger area due to space launch from vostochny. area bounded by\n"
                       "5330N15230E 5410N15410E 5250N15500E 5210N15320E\nf) gnd g) unl",
    "faa domestic": "!FDC 6/1234 ZKC AIRSPACE..TEMPORARY FLIGHT RESTRICTIONS WI AN AREA DEFINED AS "
                    "50NM RADIUS OF 4012N09948E SFC-UNL FOR SPACE LAUNCH ACT BY CHINA LONG MARCH "
                    "CARRIER ROCKET.",
    "typografisch": "V0099/25 NOTAMN A) VOMF E) RESTRICTED AREA FOR LAUNCH VEHICLE OPERATIONS FROM "
                    "SRIHARIKOTA \u2013 STAGE IMPACT 12\u00b030\u2032N 82\u00b010\u2032E\u00a011\u00b050\u2032N "
                    "83\u00b020\u2032E\u00a011\u00b010\u2032N 82\u00b040\u2032E F) SFC G) UNL",
    "freitext dezimal": "SPACE LAUNCH FROM XICHANG. FALLING DEBRIS 26.50N 103.20E 26.10N 104.40E "
                        "25.40N 103.80E. SFC/UNL",
}
for name, txt in STYLES.items():
    chunks = app.split_pasted_notams(txt)
    mdf = app.manual_entries_to_dataframe([{"text": c, "added": "x"} for c in chunks])
    evs, _ = app.analyze_notams(mdf, sp, fir, min_confidence="MEDIUM")
    good = len(evs) == 1 and evs[0].status == "OK" and evs[0].spaceport_code is not None
    check("Schreibweise '{}' wird zugeordnet".format(name), good,
          (evs[0].status, evs[0].review_reason) if evs else "kein Event")
    if evs:
        check("  ... und ist als Manuell markiert", evs[0].source == app.SOURCE_MANUAL, evs[0].source)

print("== 16. Import + Manuell kombiniert ==")
manual = app.manual_entries_to_dataframe(
    [{"text": STYLES["freitext dezimal"], "added": "21.09.2026 13:00Z"}], "NOTAM Text")
comb = app.combine_sources(app.build_demo_notams(), manual)
check("Tabellen zusammengefuehrt", len(comb) == len(app.build_demo_notams()) + 1, len(comb))
check("Quellspalte vorhanden", app.SOURCE_COLUMN in comb.columns)
ev_c, st_c = app.analyze_notams(comb, sp, fir, min_confidence="MEDIUM")
check("importierte Events unveraendert", st_c["ok"] == 6, st_c["ok"])
check("genau ein manuelles Event", st_c["manual"] == 1, st_c["manual"])
man_ev = [e for e in ev_c if e.source == app.SOURCE_MANUAL]
check("manuelles Event hat sprechende ID", man_ev[0].notam_id.startswith("MANUELL-"), man_ev[0].notam_id)
check("manuelles Event ist georeferenziert", man_ev[0].centroid_lat is not None)
check("Marker-Spalte nicht im Analysetext", app.SOURCE_COLUMN not in man_ev[0].raw_text)
tbl_c = app.events_to_dataframe(ev_c)
check("Spalte 'Quelle' in der Ergebnistabelle", "Quelle" in tbl_c.columns)
check("Import und Manuell unterscheidbar",
      set(tbl_c["Quelle"]) == {"Import", "Pasted"}, set(tbl_c["Quelle"]))

check("ID-Spalte greift nicht die Volltextspalte ab",
      app.map_notam_columns(manual)["id"] != "NOTAM Text",
      app.map_notam_columns(manual))
only_manual = app.combine_sources(None, manual)
ev_m, _ = app.analyze_notams(only_manual, sp, fir, min_confidence="MEDIUM")
check("Kennung aus reinem Freitext-Import korrekt",
      ev_m[0].notam_id.startswith("MANUELL-") or len(ev_m[0].notam_id) < 12, ev_m[0].notam_id)
withid = app.manual_entries_to_dataframe(
    [{"text": "Z9876/26 NOTAMN Q) ZLHW/QRTCA/IV/BO/W/000/999 A) ZLHW E) SPACE LAUNCH FROM "
              "JIUQUAN. FALLING DEBRIS 3830N10230E 3745N10410E 3650N10320E F) SFC G) UNL",
      "added": "x"}], "NOTAM Text")
ev_w, _ = app.analyze_notams(withid, sp, fir, min_confidence="MEDIUM")
check("Kennung aus dem Text uebernommen", ev_w[0].notam_id == "Z9876/26", ev_w[0].notam_id)
check("Manuell-only Lauf ordnet Jiuquan zu", ev_w[0].spaceport_code == "JSLC", ev_w[0].spaceport_code)

print("== 17. Manuelle Events in Karte und Export ==")
ok_c = tbl_c[tbl_c["Status"] == "OK"]
csv_c = ok_c.drop(columns=["_row", "_from", "_to"]).to_csv(index=False)
check("CSV-Export enthaelt Quelle-Spalte", "Quelle" in csv_c.splitlines()[0])
check("CSV-Export enthaelt den manuellen Eintrag",
      any("Pasted" in line for line in csv_c.splitlines()[1:]))
payload_c = [app.event_to_export_dict(e) for e in ev_c if e.source == app.SOURCE_MANUAL]
check("JSON-Export markiert die Quelle", payload_c[0]["source"] == "Pasted", payload_c[0]["source"])
html_c = app.build_event_map([e for e in ev_c if e.status == "OK"]).get_root().render()
check("Karte enthaelt Manuell-Markierung", "pasted by hand" in html_c)
check("Karte enthaelt weiterhin alle Events",
      html_c.count("Zone centroid") == len(ok_c), (html_c.count("Zone centroid"), len(ok_c)))

print("== 18. Koordinaten mit vorangestellter Hemisphaere ==")
for txt, exp in [("N380300E1071800", (38.05, 107.30)),
                 ("N3803E10718", (38.05, 107.30)),
                 ("S1230W03045", (-12.5, -30.75)),
                 ("N 12\u00b030' E 82\u00b010'", (12.5, 82.1666667))]:
    got = app.extract_coordinates(txt)
    check("Format {}".format(txt),
          bool(got) and abs(got[0][0]-exp[0]) < 1e-4 and abs(got[0][1]-exp[1]) < 1e-4, got)
poly_txt = ("BOUNDED BY: N380300E1071800-N380900E1074500-N375700E1074900-"
            "N375100E1072200 BACK TO START")
check("Polygon mit Bindestrich-Trennern", len(app.extract_coordinates(poly_txt)) == 4,
      app.extract_coordinates(poly_txt))
check("Komma-Trenner ebenfalls",
      len(app.extract_coordinates("N395800E0995300-N395600E1001500,N393900E1001200")) == 3)
check("beide Schreibrichtungen gemischt",
      len(app.extract_coordinates("1936N11057E und N380300E1071800")) == 2)

print("== 19. Hoehenlimit-Schreibweisen ==")
for variant in ("SFC-UNL", "SFC/UNL", "GND-UNL", "SFC - UNL", "SURFACE TO UNLIMITED"):
    txt = "DANGER AREA. VERTICAL LIMITS:{}.".format(variant)
    check("Hoehenlimit '{}' erkannt".format(variant),
          any(t.startswith("Hoehenlimit") for t in app.detect_triggers(txt, {})),
          app.detect_triggers(txt, {}))
check("Hoehenlimit aus F/G-Items ohne Freitext-Muster",
      any(t.startswith("Hoehenlimit") for t in app.detect_triggers("DANGER AREA", {"F": "SFC", "G": "UNL"})))
check("F) 500FT AGL loest kein Hoehenlimit aus",
      not any(t.startswith("Hoehenlimit") for t in app.detect_triggers("CRANE", {"F": "SFC", "G": "500FT AGL"})))

print("== 20. Q-Code und Startsignatur ==")
from datetime import datetime, timezone
it_q = app.extract_items("Q) ZLHW/QRDCA/IV/BO/W/000/999/3800N10733E013 A) ZLHW")
check("Q-Code gelesen", app.extract_qcode(it_q) == "QRDCA", app.extract_qcode(it_q))
check("Q-Code ohne Leerzeichen", app.extract_qcode(app.extract_items("Q)ZPKM/QRDCA/IV/BO/W/000/999")) == "QRDCA")
t0 = datetime(2026, 3, 15, 13, 14, tzinfo=timezone.utc)
t1 = datetime(2026, 3, 15, 13, 35, tzinfo=timezone.utc)
sig, note = app.has_launch_signature(
    {"Q": "ZLHW/QRDCA/IV/BO/W/000/999", "F": "SFC", "G": "UNL"}, "SFC-UNL", t0, t1)
check("Startsignatur bei 21-Minuten-Fenster", sig, note)
lang = datetime(2026, 6, 15, 13, 14, tzinfo=timezone.utc)
sig2, _ = app.has_launch_signature(
    {"Q": "RKRR/QRPCA/IV/NBO/W/000/999", "F": "SFC", "G": "UNL"}, "SFC/UNL", t0, lang)
check("keine Startsignatur bei 3-Monats-Sperrgebiet", not sig2)
sig3, _ = app.has_launch_signature(
    {"Q": "EGTT/QXXLW/IV/BO/AW/000/999", "F": "SFC", "G": "UNL"}, "SFC/UNL", t0, t1)
check("keine Startsignatur bei Nicht-QR-Code", not sig3)
sig4, _ = app.has_launch_signature({"Q": "ZLHW/QRDCA/IV/BO/W/000/999"}, "", t0, t1)
check("keine Startsignatur ohne Hoehenfenster", not sig4)

print("== 21. Startrichtungs-Pruefung ==")
port, plaus, note = app._find_spaceport((38.0, 107.56), sp, ["China"])
check("westlicher Nachbar wird uebersprungen", port["Kurzel"] == "JSLC", port["Kurzel"])
check("  ... mit Begruendung", "TSLC" in note and "westward" in note, note)
check("  ... und als plausibel markiert", plaus)
port2, plaus2, _ = app._find_spaceport((37.14, 83.87), sp, ["China"])
check("Zone westlich aller Startplaetze -> unplausibel", not plaus2)
port3, plaus3, note3 = app._find_spaceport((19.32, 111.72), sp, ["China"])
check("normale Zuordnung unveraendert", port3["Kurzel"] == "WSLC" and plaus3 and note3 == "",
      (port3["Kurzel"], plaus3, note3))

print("== 22. Beispiel-NOTAMs: Import- und Freitext-Weg ==")
CN = ["""A0611/26 NOTAMN
Q) ZLHW/QRDCA/IV/BO/W/000/999/3800N10733E013
A) ZLHW B) 2603151314 C) 2603151335
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N380300E1071800-N380900E1074500-N375700E1074900-N375100E1072200
BACK TO START.VERTICAL LIMITS:SFC-UNL.
AIRCRAFT ARE FORBIDDEN TO FLY INTO THE AREA.
F) SFC G) UNL""", """A4631/26 NOTAMN
Q)ZLHW/QRDCA/IV/BO/W/000/999/3948N10002E012
A)ZLHW B)2609200354 C)2609200415
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N395800E0995300-N395600E1001500-N393900E1001200-N394100E0995000,
BACK TO START.
VERTICAL LIMITS:SFC-UNL.
AIRCRAFT ARE FORBIDDEN TO FLY INTO THE AREA.
F)SFC G)UNL""", """A4632/26 NOTAMN
Q)ZPKM/QRDCA/IV/BO/W/000/999/2910N09814E029
A)ZPKM B)2609200356 C)2609200435
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N293700E0980200-N293400E0983400-N284400E0982700-N284800E0975500,
 BACK TO START.
VERTICAL LIMITS:SFC-UNL.
AIRCRAFT ARE FORBIDDEN TO FLY INTO THE AREA.
F)SFC G)UNL"""]

# Weg A: Freitext-Eingabe
man_cn = app.manual_entries_to_dataframe(
    [{"text": c, "added": "x"} for t in CN for c in app.split_pasted_notams(t)], "NOTAM Text")
ev_man, _ = app.analyze_notams(man_cn, sp, fir, min_confidence="MEDIUM")
check("Freitext: alle drei erkannt", len(ev_man) == 3, len(ev_man))
check("Freitext: alle mit Status OK", all(e.status == "OK" for e in ev_man),
      [(e.notam_id, e.review_reason) for e in ev_man])
check("Freitext: alle Konfidenz HIGH", all(e.confidence_level == "HIGH" for e in ev_man),
      [(e.notam_id, e.confidence_level) for e in ev_man])
check("Freitext: alle vier Polygonpunkte", all(len(e.coordinates) == 4 for e in ev_man),
      [len(e.coordinates) for e in ev_man])
check("Freitext: alle als Manuell markiert", all(e.source == app.SOURCE_MANUAL for e in ev_man))

# Weg B: Datei-Import (gleiche NOTAMs als Tabelle)
imp_cn = pd.DataFrame({"NOTAM ID": ["A0611/26", "A4631/26", "A4632/26"], "NOTAM Text": CN})
ev_imp, _ = app.analyze_notams(imp_cn, sp, fir, min_confidence="MEDIUM")
check("Import: alle drei mit Status OK", all(e.status == "OK" for e in ev_imp),
      [(e.notam_id, e.review_reason) for e in ev_imp])
check("Import: als Import markiert", all(e.source == app.SOURCE_IMPORT for e in ev_imp))
check("Import und Freitext liefern identische Zuordnung",
      [(e.spaceport_code, round(e.azimuth_deg, 1)) for e in ev_imp]
      == [(e.spaceport_code, round(e.azimuth_deg, 1)) for e in ev_man],
      [(e.notam_id, e.spaceport_code) for e in ev_imp])

by_cn = {e.notam_id: e for e in ev_imp}
check("A0611/26 -> Jiuquan statt Taiyuan", by_cn["A0611/26"].spaceport_code == "JSLC",
      by_cn["A0611/26"].spaceport_code)
check("A4631/26 -> Jiuquan, SSO", by_cn["A4631/26"].spaceport_code == "JSLC"
      and by_cn["A4631/26"].orbit_type == app.ORBIT_SSO,
      (by_cn["A4631/26"].spaceport_code, by_cn["A4631/26"].orbit_type))
check("A4632/26 -> Jiuquan statt Xichang", by_cn["A4632/26"].spaceport_code == "JSLC",
      by_cn["A4632/26"].spaceport_code)
check("A4631 und A4632 auf derselben Flugbahn (gleicher Start)",
      abs(by_cn["A4631/26"].azimuth_deg - by_cn["A4632/26"].azimuth_deg) < 2.0,
      (by_cn["A4631/26"].azimuth_deg, by_cn["A4632/26"].azimuth_deg))
check("kein Startfenster -> keine Signatur",
      app.score_confidence(CN[0], app.detect_triggers(CN[0], app.extract_items(CN[0])))[1] != "HOCH")

print("== 23. Hilfsfunktionen der Gruppierung ==")
check("Winkelstreuung einfach", abs(app._angular_spread([10.0, 30.0]) - 20.0) < 1e-9)
check("Winkelstreuung ueber 0 Grad hinweg", abs(app._angular_spread([350.0, 10.0]) - 20.0) < 1e-9,
      app._angular_spread([350.0, 10.0]))
check("Winkelstreuung Einzelwert = 0", app._angular_spread([42.0]) == 0.0)
check("Kreismittel ueber 0 Grad hinweg", abs(app._circular_mean([350.0, 10.0]) - 0.0) < 1e-6,
      app._circular_mean([350.0, 10.0]))
check("Kreismittel normal", abs(app._circular_mean([180.0, 190.0]) - 185.0) < 1e-6)

print("== 24. Gemeinsame Startplatzwahl ==")
zonen_taiyuan = [(33.36, 110.59), (30.25, 110.08)]
sel = app._select_spaceport_for_zones(zonen_taiyuan, sp, ["China"])
check("zwei Zonen einer Bahn -> Taiyuan", sel[0]["Kurzel"] == "TSLC", sel[0]["Kurzel"])
check("  ... mit sehr kleiner Streuung", sel[1] < 1.0, sel[1])
einzeln, _, _ = app._find_spaceport((30.25, 110.08), sp, ["China"])
check("  ... einzeln betrachtet waere es Xichang", einzeln["Kurzel"] == "XSLC", einzeln["Kurzel"])
check("Startplatz westlich aller Zonen ausgeschlossen",
      app._select_spaceport_for_zones([(37.14, 83.87)], sp, ["China"]) is None)

print("== 25. Gruppierung der Beispiel-NOTAMs ==")
PAAR = pd.DataFrame({"NOTAM Text": [CN[1], CN[2]]})
ev_p, st_p = app.analyze_notams(PAAR, sp, fir, min_confidence="MEDIUM")
check("beide NOTAMs in einer Gruppe", st_p["launches"] == 1 and st_p["grouped"] == 1,
      (st_p["launches"], st_p["grouped"]))
g = st_p["groups"][0]
check("Gruppe umfasst zwei Sperrzonen", g.zone_count == 2, g.zone_count)
check("Gruppe nennt beide Kennungen", set(g.notam_ids) == {"A4631/26", "A4632/26"}, g.notam_ids)
check("Gruppe -> Jiuquan", g.spaceport_code == "JSLC", g.spaceport_code)
check("Gruppe -> SSO", g.orbit_type == app.ORBIT_SSO, g.orbit_type)
check("Azimut-Streuung klein", g.azimuth_spread_deg < 2.0, g.azimuth_spread_deg)
check("Startfenster umspannt beide NOTAMs",
      g.window_from.strftime("%H:%M") == "03:54" and g.window_to.strftime("%H:%M") == "04:35",
      (g.window_from, g.window_to))
check("beide Events tragen dieselbe Start-Kennung",
      len({e.launch_group for e in ev_p}) == 1 and ev_p[0].launch_group.startswith("START-"),
      [e.launch_group for e in ev_p])
check("Hinweis nennt die gemeinsame Bahn", "Shared track" in ev_p[0].assignment_note,
      ev_p[0].assignment_note)

print("== 26. Gruppierung trennt korrekt ==")
FERN = pd.DataFrame({"NOTAM Text": [CN[1], """A9999/26 NOTAMN
Q)ZJSA/QRDCA/IV/BO/W/000/999/1930N11100E050
A)ZJSA B)2609200358 C)2609200420
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N193600E1105700-N194800E1121200-N190200E1123000-N185000E1111500,
BACK TO START. VERTICAL LIMITS:SFC-UNL.
F)SFC G)UNL"""]})
ev_f, st_f = app.analyze_notams(FERN, sp, fir, min_confidence="MEDIUM")
check("zeitgleiche, aber unvereinbare Zonen werden getrennt", st_f["launches"] == 2,
      st_f["launches"])
check("  ... jede Gruppe mit einer Zone",
      all(g.zone_count == 1 for g in st_f["groups"]), [g.zone_count for g in st_f["groups"]])
weit = pd.DataFrame({"NOTAM Text": [CN[1], CN[1].replace("2609200354", "2609210354")
                                             .replace("2609200415", "2609210415")
                                             .replace("A4631/26", "A4633/26")]})
ev_w, st_w = app.analyze_notams(weit, sp, fir, min_confidence="MEDIUM")
check("NOTAMs eines Tages Abstand werden nicht gruppiert", st_w["launches"] == 2, st_w["launches"])

print("== 27. Mehrfachlistungen ==")
dubl = pd.DataFrame({"NOTAM Text": [CN[1], CN[1], CN[1]]})
ev_d, st_d = app.analyze_notams(dubl, sp, fir, min_confidence="MEDIUM")
check("identische NOTAMs werden zusammengefasst", st_d["events"] == 1, st_d["events"])
check("  ... und gezaehlt", st_d["duplicates"] == 2, st_d["duplicates"])
check("  ... ergeben einen Start", st_d["launches"] == 1, st_d["launches"])

print("== 28. Start-Ebene in Tabelle, Karte und Export ==")
gt = app.groups_to_dataframe(st_p["groups"])
for col in ("Start", "Startnation", "Weltraumbahnhof", "Startfenster (UTC)", "Sperrzonen",
            "NOTAMs", "Launch Azimut (°)", "Est. Inklination (°)", "Orbit-Typ"):
    check("Start-Tabelle hat Spalte '{}'".format(col), col in gt.columns)
check("Start-Tabelle: eine Zeile fuer zwei NOTAMs", len(gt) == 1, len(gt))
check("NOTAM-Tabelle hat Spalte 'Start'", "Start" in app.events_to_dataframe(ev_p).columns)
check("NOTAM-Zeilen verweisen auf den Start",
      set(app.events_to_dataframe(ev_p)["Start"]) == {g.group_id},
      set(app.events_to_dataframe(ev_p)["Start"]))
gj = app.group_to_export_dict(g)
check("JSON-Export der Gruppe serialisierbar", _j.dumps(gj) and gj["zone_count"] == 2)
check("  ... mit ISO-Zeitfenster", gj["window_from"].startswith("2026-09-20"), gj["window_from"])
html_g = app.build_event_map(ev_p).get_root().render()
check("Karte: zwei Sperrzonen", html_g.count("Zone centroid") == 2, html_g.count("Zone centroid"))
check("Karte: nur eine Flugbahn", html_g.count("L.polyline") == 1, html_g.count("L.polyline"))
check("Karte: nur ein Startplatz-Marker", html_g.count('"icon": "rocket"') == 1,
      html_g.count('"icon": "rocket"'))

print("== 29. Echtdaten-Gruppierung ==")
if xls:
    ev_r, st_r = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    groups_r = {g.group_id: g for g in st_r["groups"] if g.spaceport_code}
    def gruppe_von(nid):
        for g in groups_r.values():
            if nid in g.notam_ids:
                return g
        return None

    g_tai = gruppe_von("A4456/26")
    check("A4456 und A4457 als ein Taiyuan-Start gruppiert",
          g_tai is not None and g_tai.spaceport_code == "TSLC" and "A4457/26" in g_tai.notam_ids,
          g_tai.notam_ids if g_tai else "nicht gruppiert")
    g_jiu = gruppe_von("A4631/26")
    check("A4631 und A4632 als ein Jiuquan-Start gruppiert",
          g_jiu is not None and g_jiu.spaceport_code == "JSLC" and "A4632/26" in g_jiu.notam_ids,
          g_jiu.notam_ids if g_jiu else "nicht gruppiert")
    check("  ... samt dritter Dropzone im Indischen Ozean (F3573/26)",
          g_jiu is not None and "F3573/26" in g_jiu.notam_ids, g_jiu.notam_ids if g_jiu else None)
    check("  ... alle drei Zonen auf derselben Bahn",
          g_jiu is not None and g_jiu.azimuth_spread_deg < 2.0,
          g_jiu.azimuth_spread_deg if g_jiu else None)
    check("Mehrfachlistungen im Echtbestand entfernt", st_r["duplicates"] > 0, st_r["duplicates"])
    check("kein Start mit unmoeglicher Startrichtung",
          all(not (225 <= (g.azimuth_deg or 0) <= 325) for g in groups_r.values()),
          [(g.group_id, g.azimuth_deg) for g in groups_r.values()])
else:
    print("  SKIP  keine .xls-Testdatei")

print("== 30. Weitere Koordinatenformate ==")
for txt, exp in [("59-42.60S 165-49.20E", (-59.71, 165.82)),
                 ("57-28.80S 126-01.20W", (-57.48, -126.02)),
                 ("59 03 00 S 131 00 00 W", (-59.05, -131.0)),
                 ("59 42 36 S 165 49 12 E", (-59.71, 165.82)),
                 ("621200S 1630000E", (-62.2, 163.0)),
                 ("724711N 0292753E", (72.7864, 29.4647)),
                 ("S1059E09207", (-10.9833, 92.1167))]:
    got = app.extract_coordinates(txt)
    check("Format {}".format(txt),
          bool(got) and abs(got[0][0] - exp[0]) < 2e-3 and abs(got[0][1] - exp[1]) < 2e-3, got)
check("Zeitangaben werden nicht als Koordinaten gelesen",
      app.extract_coordinates("13 2100-2359, 14-29 0000-1600") == [])
check("Q-Line-Radius bleibt aussen vor",
      app.extract_coordinates("W/000/999/3322N11036E013") == [],
      app.extract_coordinates("W/000/999/3322N11036E013"))

print("== 31. Kennungen und HTML-Entities ==")
check("Kennung ohne Buchstabe", app.RE_NOTAM_ID.search("4456/26 NOTAMN").group(1) == "4456/26")
check("Kennung mit Buchstabe", app.RE_NOTAM_ID.search("A4457/26 NOTAMN").group(1) == "A4457/26")
check("Hoehenfenster ist keine Kennung", app.RE_NOTAM_ID.search("W/000/999/33") is None)
check("NAVAREA-Kennung erkannt",
      app.RE_NAVAREA_ID.search("NAVAREA XIV WARNING 189/26").groups() == ("XIV", "189/26"))
check("HTML-Entity aufgeloest", app.normalize_notam_text("AREA &apos;RUS&apos;") == "AREA 'RUS'",
      app.normalize_notam_text("AREA &apos;RUS&apos;"))
check("&amp; aufgeloest", "&" in app.normalize_notam_text("A &amp; B"))
check("Trennung ohne Buchstabenpraefix",
      len(app.split_pasted_notams("4456/26 NOTAMN A) ZLHW\nA4457/26 NOTAMN A) ZHWH")) == 2)
check("NAVAREA als eigener Block erkannt",
      len(app.split_pasted_notams("A1/26 NOTAMN A) ZLHW\nNAVAREA XIV WARNING 189/26\nSPACE DEBRIS")) == 2)

print("== 32. Taegliche Zeitfenster (D-Item) ==")
for d, exp in [("24-28 1100-2100", 10.0), ("DAILY 0900-2100", 12.0),
               ("13 2100-2359, 14-29 0000-1600 2100-2359, 30 0000-1600", 16.0),
               ("0323 - 0453", 1.5), ("2200-0200", 4.0), (None, None), ("MON-FRI", None)]:
    check("D-Item {!r}".format(d), app.daily_window_hours(d) == exp, app.daily_window_hours(d))
t0 = datetime(2026, 4, 24, 11, 0, tzinfo=timezone.utc)
t1 = datetime(2026, 4, 28, 21, 0, tzinfo=timezone.utc)
sig, note = app.has_launch_signature(
    {"Q": "ULLL/QRTCA/IV/BO/W/000/999", "F": "SFC", "G": "UNL", "D": "24-28 1100-2100"},
    "AIRSPACE CLSD", t0, t1)
check("mehrtaegiges NOTAM mit Tagesfenster -> Startsignatur", sig, note)
sig2, _ = app.has_launch_signature(
    {"Q": "ULLL/QRTCA/IV/BO/W/000/999", "F": "SFC", "G": "UNL"}, "AIRSPACE CLSD", t0, t1)
check("dieselbe Laufzeit ohne Tagesfenster -> keine Signatur", not sig2)

print("== 33. NAVAREA-Zeitraum ==")
von, bis = app.extract_navarea_period(
    "SPACE DEBRIS FROM 142100 UTC TO 232100 UTC JUL 2026 IN AREA")
check("NAVAREA-Zeitraum gelesen",
      von.day == 14 and von.hour == 21 and bis.day == 23 and bis.hour == 21, (von, bis))
check("ohne Zeitraum -> None", app.extract_navarea_period("SPACE DEBRIS") == (None, None))

print("== 34. Mehrere Gebiete in einem NOTAM ==")
zwei = ("AIRSPACE CLSD WI AREA: 1. 625500N0470000E-625000N0485000E-622500N0484500E-"
        "623000N0470000E-625500N0470000E. 2. 621200N0510400E-615900N0522100E-"
        "622400N0524100E-623700N0512400E-621200N0510400E.")
z = app.extract_zones(zwei)
check("nummerierte Gebiete getrennt", len(z) == 2 and all(len(x) == 4 for x in z),
      [len(x) for x in z])
drei = ("ACTIVATED PSN 724711N 0292753E - 725238N 0300000E - 722911N 0300000E. "
        "SIMILAR ACTIVITIES ARE ALSO PLANNED AT PSN 725238N 0300000E - 730132N 0305414E - "
        "722300N 0320500E - 714500N 0320500E "
        "AND 705600N 0320500E - 701000N 0320500E - 700928N 0320152E - 701500N 0315000E")
check("'SIMILAR ACTIVITIES' und 'AND' trennen Gebiete", len(app.extract_zones(drei)) == 3,
      [len(x) for x in app.extract_zones(drei)])
punkte = ("IN AREA BOUNDED BY: A. 59-42.60S 165-49.20E B. 57-28.80S 126-01.20W "
          "C. 60-23.40S 122-04.80W D. 62-33.00S 162-33.60E")
check("Aufzaehlungspunkte bleiben ein Gebiet", len(app.extract_zones(punkte)) == 1,
      [len(x) for x in app.extract_zones(punkte)])
check("einfaches NOTAM bleibt ein Gebiet",
      len(app.extract_zones("BOUNDED BY 1936N11057E 1948N11212E 1902N11230E")) == 1)

print("== 35. Die neuen Beispiel-NOTAMs ==")
NEU = {
"CN-4456": """4456/26 NOTAMN
Q)ZXXX/QRDCA/IV/BO/W/000/999/3322N11036E013
A)ZLHW ZHWH B)2609191043 C)2609191106
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N333400E1103100-N333200E1104400-N331000E1104100-N331100E1102700,
BACK TO START.VERTICAL LIMITS:SFC-UNL.
AIRCRAFT ARE FORBIDDEN TO FLY INTO THE AREA.
F)SFC G)UNL""",
"CN-A4457": """A4457/26 NOTAMN
Q)ZHWH/QRDCA/IV/BO/W/000/999/3015N11005E022
A)ZHWH B)2609191044 C)2609191111
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N303500E1095700-N303300E1101900-N295400E1101300-N295700E1095100,
BACK TO START.VERTICAL LIMITS:SFC-UNL.
F)SFC G)UNL""",
"RU-Q3528": """Q3528/26 NOTAMN
Q) ULLL/QRTCA/IV/BO/W/000/999/6604N04250E021
A) ULLL B) 2604241100 C) 2604282100
D) 24-28 1100-2100
E) AIRSPACE CLSD WI AREA:
654800N0431000E-654500N0423000E-654700N0422500E-655500N0421300E-
660700N0421500E-661900N0423000E-662300N0425500E-662300N0431000E-
661500N0432800E-654800N0431000E
F) SFC  G) UNL""",
"RU-X1926": """X1926/26 NOTAMN Q)ULLL/QRTCA/IV/BO/W/000/999/6241N04952E082 A)ULLL B)2607140900 C)2607182059 E)AIRSPACE CLSD WI AREA: 1. 625500N0470000E-625000N0485000E-622500N0484500E- 623000N0470000E-625500N0470000E. 2. 621200N0510400E-615900N0522100E-622400N0524100E- 623700N0512400E-621200N0510400E. F)GND G)UNL""",
"NAVAREA": """NAVAREA XIV WARNING 189/26
SOUTHERN OCEAN
1. HAZARDOUS OPERATIONS, SPACE DEBRIS FROM 142100 UTC TO 232100 UTC JUL 2026 IN AREA BOUNDED BY:
A. 59-42.60S 165-49.20E
B. 57-28.80S 126-01.20W
C. 60-23.40S 122-04.80W
D. 62-33.00S 162-33.60E
2. CANCEL THIS MESSAGE 232200 UTC JUL 2026
NNNN""",
"AU-F2572": """F2572/26 NOTAMN
Q) YMMM/QWMLW/IV/BO/W/000/999/6230S16247E020
A) YMMM
B) 2607140900 C) 2607232100
D) DAILY 0900-2100
E) ROCKET LAUNCH FROM RUSSIA WILL TAKE PLACE
FLW RECEIVED FROM GOVERNMENT OF RUSSIA: THE RUSSIAN FEDERATION PLANS
TO LAUNCH MISSILE MISSION IN THE SPACE AND TO SINK ITS
FRAGMENTS IN THE WATERS OF THE OCEAN.
CHARACTERISTICS OF IMPACT AREA:
621200S 1630000E
624100S 1630000E
623300S 1623336E
621200S 1630000E
F) SFC G) UNL""",
"NZ-B3661": """B3661/26 NOTAMN
Q) NZZO/QRDCA/IV/BO /W /000/999/6106S16123W999
A) NZZO B) 2607150900 C) 2607232100
D) DAILY 0900-2100
E) TEMPO DANGER AREA NZD095 (AUCKLAND, SOUTH OCEANIC FIR) IS
PRESCRIBED AS FLW: ALL THAT AIRSPACE BOUNDED BY A LINE JOINING:
59 03 00 S 131 00 00 W
63 09 00 S 131 00 00 W
62 41 00 S 163 00 00 E
62 12 00 S 163 00 00 E
59 42 36 S 165 49 12 E
59 03 00 S 131 00 00 W
ACTIVITY: MISSILE LAUNCH AND SPACE DEBRIS RETURN
USING AGENCY: FOREIGN AGENCY
F) SFC G) UNL""",
"NO-A2410": """A2410/26 NOTAMN
Q) ENOB/QRDCA/IV/BO /W /000/999/7241N03000E012
A) ENOB B) 2604132100 C) 2604301600
D) 13 2100-2359, 14-29 0000-1600 2100-2359, 30 0000-1600
E) TEMPO DANGER AREA &apos;RUS SPACE LAUNCH AREA V APRIL 26&apos;
ACTIVATED PSN 724711N 0292753E - 725238N 0300000E - 722911N 0300000E - (724711N
0292753E). IMPACT AREA FOR RUSSIAN MISSILES.
SIMILAR ACTIVITIES ARE ALSO PLANNED WITHIN THE UNALLOCATED
INTERNATIONAL AIRSPACE AT PSN 725238N 0300000E - 730132N 0305414E -
722300N 0320500E - 714500N 0320500E - 713933N 0312513E - 721330N
0302700E - 722911N 0300000E - (725238N 0300000E)
AND 705600N 0320500E - 701000N 0320500E - 700928N 0320152E - 701500N 0315000E -
703007N 0315000E - 703622N 0314318E - (705600N 0320500E)
F) GND G) UNL""",
"NO-A2411": """A2411/26 NOTAMN
Q) ENOB/QRDCA/IV/BO /W /000/999/7537N02147E047
A) ENOB B) 2604132100 C) 2604301600
D) 13 2100-2359, 14-29 0000-1600 2100-2359, 30 0000-1600
E) TEMPO DANGER AREA &apos;RUS SPACE LAUNCH AREA G APRIL 26&apos; ACTIVATED PSN
762200N 0215500E - 752400N 0244300E - 745100N 0214500E - 755000N
0185000E - 762200N 0215500E - (762200N 0215500E). IMPACT AREA FOR
RUSSIAN MISSILES
F) GND G) UNL""",
}

# Weg A: Freitext-Eingabe
man_neu = app.manual_entries_to_dataframe(
    [{"text": t, "added": "x"} for t in NEU.values()], "NOTAM Text")
ev_neu, st_neu = app.analyze_notams(man_neu, sp, fir, min_confidence="MEDIUM")
check("alle {} Beispiele erzeugen ein Event".format(len(NEU)), len(ev_neu) == len(NEU), len(ev_neu))
nicht_ok = [(n, e.review_reason) for n, e in zip(NEU, ev_neu) if e.status != "OK"]
check("alle Beispiele erhalten Status OK", nicht_ok == [], nicht_ok)
ohne_koord = [n for n, e in zip(NEU, ev_neu) if not e.coordinates]
check("aus allen Beispielen werden Koordinaten gelesen", ohne_koord == [], ohne_koord)
by_neu = dict(zip(NEU, ev_neu))
check("4456/26 behaelt seine Kennung ohne Buchstabe", by_neu["CN-4456"].notam_id == "4456/26",
      by_neu["CN-4456"].notam_id)
check("NAVAREA bekommt sprechende Kennung",
      by_neu["NAVAREA"].notam_id.startswith("NAVAREA"), by_neu["NAVAREA"].notam_id)
check("X1926 hat zwei getrennte Gebiete", len(by_neu["RU-X1926"].zones) == 2,
      len(by_neu["RU-X1926"].zones))
check("A2410 hat drei getrennte Gebiete", len(by_neu["NO-A2410"].zones) == 3,
      len(by_neu["NO-A2410"].zones))
check("A2410/A2411 -> Plesetsk",
      by_neu["NO-A2410"].spaceport_code == "GIK-1" and by_neu["NO-A2411"].spaceport_code == "GIK-1",
      (by_neu["NO-A2410"].spaceport_code, by_neu["NO-A2411"].spaceport_code))
check("A2410/A2411 -> noerdliche Startrichtung (Plesetsk SSO)",
      330 < by_neu["NO-A2410"].azimuth_deg < 355, by_neu["NO-A2410"].azimuth_deg)
check("A2410 und A2411 als ein Start gruppiert",
      by_neu["NO-A2410"].launch_group == by_neu["NO-A2411"].launch_group,
      (by_neu["NO-A2410"].launch_group, by_neu["NO-A2411"].launch_group))
check("Q3528 und X1926 sind verschiedene Starts",
      by_neu["RU-Q3528"].launch_group != by_neu["RU-X1926"].launch_group,
      (by_neu["RU-Q3528"].launch_group, by_neu["RU-X1926"].launch_group))
check("F2572, NAVAREA und B3661 sind ein Start",
      by_neu["AU-F2572"].launch_group == by_neu["NAVAREA"].launch_group == by_neu["NZ-B3661"].launch_group,
      (by_neu["AU-F2572"].launch_group, by_neu["NAVAREA"].launch_group, by_neu["NZ-B3661"].launch_group))
check("  ... und werden Russland zugeordnet",
      by_neu["NAVAREA"].nation == "Russland" and by_neu["NZ-B3661"].nation == "Russland",
      (by_neu["NAVAREA"].nation, by_neu["NZ-B3661"].nation))
check("  ... mit gemindeter Zuverlaessigkeit (Fernzone)",
      by_neu["AU-F2572"].reliability == app.RELIABILITY_LOW, by_neu["AU-F2572"].reliability)
check("4456 und A4457 -> ein Taiyuan-Start",
      by_neu["CN-4456"].launch_group == by_neu["CN-A4457"].launch_group
      and by_neu["CN-4456"].spaceport_code == "TSLC",
      (by_neu["CN-4456"].launch_group, by_neu["CN-4456"].spaceport_code))

# Weg B: Datei-Import
imp_neu = pd.DataFrame({"NOTAM Text": list(NEU.values())})
ev_imp_neu, st_imp = app.analyze_notams(imp_neu, sp, fir, min_confidence="MEDIUM")
check("Import liefert dieselben Zuordnungen wie die Freitext-Eingabe",
      [(e.spaceport_code, e.launch_group) for e in ev_imp_neu]
      == [(e.spaceport_code, e.launch_group) for e in ev_neu],
      [(e.notam_id, e.spaceport_code) for e in ev_imp_neu])
check("Import markiert die Quelle als Import",
      all(e.source == app.SOURCE_IMPORT for e in ev_imp_neu))

print("== 36. Keine neuen Fehlalarme ==")
FALSCH = {
 "US-ADS-B-Ausfall": "!FDC 6/9360 ZLA AIRSPACE ADS-B, AUTO DEPENDENT SURVEILLANCE REBROADCAST "
                     "(ADS-R), TFC INFO SER BCST (TIS-B) SER MAY NOT BE AVBL WI AN AREA DEFINED "
                     "AS 90NM RADIUS OF 324554N1220754W. SFC-UNL. 2606200347-2612142200EST",
 "US-Hoehenreservierung": "!CARF 09/199 ZLA AIRSPACE DCC GRAY FLAG 2026 STNR ALT RESERVATION "
                          "BEAMER 26-2 WI AN AREA DEFINED AS 362000N1241900W TO 334700N1223800W "
                          "TO 334600N1224600W TO 331300N1222400W SFC-UNL",
 "Schiffsartillerie": "A2846/26 NOTAMN Q) VOXX/QWMLW/IV/BO/W/000/999/ A) VOMF VECF "
                      "B) 2609220130 C) 2609241130 D) 0130-0530 E) NAVAL SHIP FRNG WI THE AREA "
                      "BOUNDED BY THE COORD: 162006N0842918E-160148N0872318E-135224N0853130E-"
                      "144306N0823330E F) SFC G) UNL",
 "Wetterballon": "A2696/26 NOTAMN Q) VOMF/QWLLW/IV/BO/W/000/999/ A) VOMF B) 2609020001 "
                 "C) 2611262000 E) MET AIR BALLOON LAUNCH FM INDIAN NAVAL SHIP BTN COORD: "
                 "1700N07000E-1700N07318E-1400N07430E-1400N07000E F) SFC G) UNL",
 "Suchscheinwerfer": "A3622/26 NOTAMN Q) EGTT/QXXLW/IV/BO/AW/000/999 A) EGLL E) SEARCHLIGHT "
                     "DISPLAY WI 0.5NM RADIUS OF 512846N 0001745W (KEW). F) SFC G) UNL",
}
ev_f, st_f = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": list(FALSCH.values())}), sp, fir, min_confidence="MEDIUM")
treffer = [(n, e.nation, e.spaceport_code) for n, e in zip(FALSCH, ev_f) if e.status == "OK"]
check("keiner der fuenf Nicht-Starts wird als Start gewertet", treffer == [], treffer)
check("Fehlalarme bilden keine Startgruppe", st_f["launches"] == 0, st_f["launches"])

print("== 37. Echtdaten nach der Erweiterung ==")
if xls:
    ev_r2, st_r2 = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    check("Starts im Echtbestand erkannt", st_r2["launches"] >= 4, st_r2["launches"])
    # Mehrere Sperrzonen sind die Regel, aber kein Gesetz: ein Booster-
    # Wiedereintritt hat genau ein Splashdown-Gebiet.
    check("  ... die meisten mit mehreren Sperrzonen",
          sum(1 for g in st_r2["groups"] if g.spaceport_code and g.zone_count >= 2)
          >= sum(1 for g in st_r2["groups"] if g.spaceport_code) - 2,
          [(g.group_id, g.zone_count) for g in st_r2["groups"] if g.spaceport_code])
    g_r2 = [g for g in st_r2["groups"] if g.spaceport_code]
    check("jeder Start hat einen Startplatz", all(g.spaceport_code for g in g_r2))
    check("keine US-Inlandsmeldung als Start",
          not any("ZLA" in (by_r.raw_text if (by_r := next((e for e in ev_r2 if e.row_index == g.row_indices[0]), None)) else "")[:60]
                  for g in g_r2),
          [g.notam_ids for g in g_r2])
    check("alle Startrichtungen physikalisch moeglich",
          all(not (225 <= (g.azimuth_deg or 0) <= 325) or (g.max_range_km or 0) > app.FAR_ZONE_KM
              for g in g_r2),
          [(g.group_id, g.azimuth_deg) for g in g_r2])

print("== 38. Rueckfall auf den Q-Line-Bezugspunkt ==")
qp = app.extract_qline_point("ZBPE/QRDCA/IV/BO/W/000/999/3950N11625E099")
check("Q-Line-Punkt mit Radius gelesen",
      qp is not None and abs(qp[0] - 39.8333) < 1e-3 and abs(qp[1] - 116.4167) < 1e-3
      and abs(qp[2] - 183.3) < 1.0, qp)
check("ohne Radius-Suffix kein Q-Line-Punkt",
      app.extract_qline_point("W/000/999/3322N11036E") is None)
check("Q-Line-Punkt taucht nicht im Polygon auf",
      app.extract_coordinates("W/000/999/3950N11625E099") == [])
knapp = pd.DataFrame({
    "notam_id": ["A1234/26"], "icao_fir": ["ZBPE"], "q_code": ["QRDCA"],
    "start_date": ["2026-09-21 02:30:00"], "end_date": ["2026-09-21 05:30:00"],
    "coordinates_raw": ["3950N11625E099"], "lower_limit": ["SFC"], "upper_limit": ["UNL"],
    "text_raw": ["ROCKET LAUNCH, DEBRIS FALLING AREA ACTIVE."],
})
ev_q, st_q = app.analyze_notams(knapp, sp, fir, min_confidence="MEDIUM")
check("NOTAM ohne Gebietsgrenzen geht nicht verloren",
      len(ev_q) == 1 and ev_q[0].status == "OK",
      (len(ev_q), ev_q[0].review_reason if ev_q else None))
check("  ... Zone aus der Q-Line abgeleitet",
      len(ev_q[0].coordinates) == 1 and abs(ev_q[0].coordinates[0][0] - 39.8333) < 1e-3,
      ev_q[0].coordinates)
check("  ... Radius uebernommen", ev_q[0].radius_km and abs(ev_q[0].radius_km - 183.3) < 1.0,
      ev_q[0].radius_km)
check("  ... Herkunft der Zone wird ausgewiesen",
      "Q-line" in ev_q[0].assignment_note, ev_q[0].assignment_note)

print("== 39. Drittstaaten-FIRs: Nation wird nicht unterstellt ==")
NORWEGEN = {
 "Andoeya-Start": "A0123/26 NOTAMN Q) ENOR/QRTCA/IV/BO/W/000/999/6918N01601E020 A) ENOR "
   "B) 2605101200 C) 2605101400 E) TEMPORARY DANGER AREA FOR SOUNDING ROCKET LAUNCH FROM "
   "ANDOYA SPACE. IMPACT AREA 700000N0160000E-701500N0170000E-695000N0172000E-694500N0161000E "
   "F) SFC G) UNL",
 "ENOB ohne Nation": "A0124/26 NOTAMN Q) ENOB/QRDCA/IV/BO/W/000/999/7241N03000E012 A) ENOB "
   "B) 2604132100 C) 2604132300 E) TEMPORARY DANGER AREA ACTIVATED PSN 724711N 0292753E - "
   "725238N 0300000E - 722911N 0300000E - 724711N 0292753E F) GND G) UNL",
 "ENOB mit Nation": "A2411/26 NOTAMN Q) ENOB/QRDCA/IV/BO/W/000/999/7537N02147E047 A) ENOB "
   "B) 2604132100 C) 2604301600 D) 13 2100-2359 E) TEMPO DANGER AREA ACTIVATED PSN "
   "762200N 0215500E - 752400N 0244300E - 745100N 0214500E - 755000N 0185000E. "
   "IMPACT AREA FOR RUSSIAN MISSILES F) GND G) UNL",
 "Chinesische Inlands-FIR": "A4631/26 NOTAMN Q)ZLHW/QRDCA/IV/BO/W/000/999/3948N10002E012 "
   "A)ZLHW B)2609200354 C)2609200415 E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY: "
   "N395800E0995300-N395600E1001500-N393900E1001200-N394100E0995000 VERTICAL LIMITS:SFC-UNL. "
   "F)SFC G)UNL",
}
ev_no, _ = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": list(NORWEGEN.values())}), sp, fir, min_confidence="MEDIUM")
by_no = dict(zip(NORWEGEN, ev_no))
check("Start von Andoeya wird nicht Russland zugeordnet",
      by_no["Andoeya-Start"].status == "REVIEW" and by_no["Andoeya-Start"].nation is None,
      (by_no["Andoeya-Start"].status, by_no["Andoeya-Start"].nation))
check("  ... Begruendung nennt den Startplatz ausserhalb der Zielnationen",
      "ANDOYA" in by_no["Andoeya-Start"].review_reason, by_no["Andoeya-Start"].review_reason)
check("norwegische FIR ohne Nationsnennung -> kein russischer Start",
      by_no["ENOB ohne Nation"].status == "REVIEW" and by_no["ENOB ohne Nation"].nation is None,
      (by_no["ENOB ohne Nation"].status, by_no["ENOB ohne Nation"].nation))
check("  ... Begruendung nennt das Land der FIR",
      "Norwegen" in by_no["ENOB ohne Nation"].review_reason,
      by_no["ENOB ohne Nation"].review_reason)
check("norwegische FIR MIT Nationsnennung -> Russland",
      by_no["ENOB mit Nation"].status == "OK" and by_no["ENOB mit Nation"].nation == "Russland",
      (by_no["ENOB mit Nation"].status, by_no["ENOB mit Nation"].nation))
check("FIR im Gebiet der Zielnation braucht keine Nennung",
      by_no["Chinesische Inlands-FIR"].status == "OK"
      and by_no["Chinesische Inlands-FIR"].nation == "China",
      by_no["Chinesische Inlands-FIR"].status)
check("Land der FIR steht am Event",
      by_no["ENOB mit Nation"].fir_country == "Norwegen", by_no["ENOB mit Nation"].fir_country)
check("Spalte 'FIR liegt in' in der Ergebnistabelle",
      "FIR liegt in" in app.events_to_dataframe(ev_no).columns)

print("== 40. Gruppe braucht einen Anker mit gesicherter Nation ==")
HEBRIDEN = [
 "M6306/26 NOTAMN Q) EGPX/QRDCA/IV/BO/W/000/999/5743N00846W062 A) EGPX B) 2609180900 "
 "C) 2609182000 E) THE FOLLOWING HEBRIDES DANGER AREAS ARE ACTIVATED: EGD701A 0900-2000 "
 "SFC-UNL WITHIN AREA 574300N0084600W-575000N0083000W-573000N0082000W-572500N0085000W "
 "F) SFC G) UNL",
 "G0071/26 NOTAMN Q) EGGX/QRDCA/IV/BO/W/000/999/5809N01100W049 A) EGGX B) 2609180900 "
 "C) 2609182000 E) THE FLW EGD701 HEBRIDES COMPLEX DANGER AREAS ARE ACTIVATED: EGD701S "
 "0900-2000 SFC-UNL WITHIN AREA 580900N0110000W-581500N0104000W-575500N0103000W-"
 "575000N0111000W F) SFC G) UNL",
]
ev_h, st_h = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": HEBRIDEN}), sp, fir, min_confidence="MEDIUM")
check("zwei mehrdeutige Meldungen bestaetigen sich nicht gegenseitig",
      st_h["launches"] == 0 and all(e.status == "REVIEW" for e in ev_h),
      (st_h["launches"], [e.status for e in ev_h]))
ANKER = HEBRIDEN + [
 "A2411/26 NOTAMN Q) ENOB/QRDCA/IV/BO/W/000/999/7537N02147E047 A) ENOB B) 2609180900 "
 "C) 2609182000 E) TEMPO DANGER AREA ACTIVATED PSN 762200N 0215500E - 752400N 0244300E - "
 "745100N 0214500E - 755000N 0185000E. IMPACT AREA FOR RUSSIAN MISSILES F) GND G) UNL",
]
ev_a, st_a = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": ANKER}), sp, fir, min_confidence="MEDIUM")
check("mit einem Anker wird die Gruppe aufgeloest", st_a["launches"] >= 1, st_a["launches"])

print("== 41. Ozeanische FIRs wieder vorhanden ==")
for code in ("YMMM", "NZZO", "FIMM", "VCCF", "OMAE", "ORBB"):
    check("FIR {} in der Referenz".format(code), code in set(fir["ICAO Code"]))

print("== 42. Manuelle Bestaetigung aus dem Review ==")
check("Schluessel ist stabil gegen Leerraum",
      app.event_key("  A1/26   NOTAMN  ") == app.event_key("A1/26 NOTAMN"))
check("Schluessel unterscheidet verschiedene NOTAMs",
      app.event_key("A1/26 NOTAMN") != app.event_key("A2/26 NOTAMN"))
check("Markierung stellt das Hexagon voran",
      app.mark_id("A4457/26", True) == app.MANUAL_MARK + " A4457/26",
      app.mark_id("A4457/26", True))
check("ohne Bestaetigung keine Markierung", app.mark_id("A4457/26", False) == "A4457/26")
html_mark = app.mark_id_html("A4457/26", True)
check("HTML-Markierung ist hochgestellt", "vertical-align:super" in html_mark)
check("HTML-Markierung ist lila", app.MANUAL_COLOR in html_mark, html_mark[:40])
check("HTML-Markierung steht vor der Kennung", html_mark.endswith("A4457/26"))

PRUEFFAELLE = {
 "mehrdeutige FIR": "B4912/26 NOTAMN Q) RPHI/QWMLW/IV/BO/W/000/999/1945N12932E089 A) RPHI "
   "B) 2610070323 C) 2610140453 D) 0323 - 0453 E) SPECIAL OPS (AEROSPACE FLT ACT) WILL BE "
   "CONDUCTED BY KOREA. EST FALL AREA OF UNBURNED DEBRIS WI: 210000N 1284522E - "
   "210000N 1295838E - 182943N 1301736E - 182122N 1290634E F) SFC G) UNL",
 "ohne Koordinaten": "R0555/26 NOTAMN A) OIIX B) 2609210800 C) 2609211000 E) DANGER AREA "
   "ACTIVATED FOR ROCKET LAUNCH. COORDINATES NOT PUBLISHED. SFC/UNL",
 "niedrige Konfidenz": "Z1111/26 NOTAMN Q) ZBPE/QRDCA/IV/BO/W/000/999 A) ZBPE B) 2609210800 "
   "C) 2612210800 E) TEMPORARY DANGER AREA 3950N11625E 4010N11700E 3930N11720E F) SFC G) UNL",
}
df_p = pd.DataFrame({"NOTAM Text": list(PRUEFFAELLE.values())})
ev_p0, st_p0 = app.analyze_notams(df_p, sp, fir, min_confidence="MEDIUM")
by_p0 = dict(zip(PRUEFFAELLE, ev_p0))
check("mehrdeutige FIR steht zunaechst im Review",
      by_p0["mehrdeutige FIR"].status == "REVIEW", by_p0["mehrdeutige FIR"].status)
check("NOTAM ohne Koordinaten steht zunaechst im Review",
      by_p0["ohne Koordinaten"].status == "REVIEW", by_p0["ohne Koordinaten"].status)

alle_keys = {e.key for e in ev_p0}
ev_p1, st_p1 = app.analyze_notams(df_p, sp, fir, min_confidence="MEDIUM", confirmed_keys=alle_keys)
by_p1 = dict(zip(PRUEFFAELLE, ev_p1))
check("nach Bestaetigung sind alle drei in der Launch-Tabelle",
      all(e.status == "OK" for e in ev_p1), [(n, e.status) for n, e in by_p1.items()])
check("  ... und als manuell geprueft markiert",
      all(e.manual_override for e in ev_p1))
check("  ... Statistik zaehlt die Bestaetigungen", st_p1["confirmed"] == 3, st_p1["confirmed"])
check("mehrdeutige FIR erhaelt jetzt eine Nation",
      by_p1["mehrdeutige FIR"].nation in app.TARGET_NATIONS, by_p1["mehrdeutige FIR"].nation)
check("NOTAM ohne Koordinaten bleibt ohne Bahn, wird aber gefuehrt",
      by_p1["ohne Koordinaten"].azimuth_deg is None
      and "coordinates" in by_p1["ohne Koordinaten"].assignment_note,
      by_p1["ohne Koordinaten"].assignment_note)
tbl_p = app.events_to_dataframe(ev_p1)
check("Tabelle zeigt das Hexagon vor jeder Kennung",
      all(str(v).startswith(app.MANUAL_MARK) for v in tbl_p["NOTAM ID"]), list(tbl_p["NOTAM ID"]))
check("Tabelle hat die Spalte 'Geprüft'", "Geprüft" in tbl_p.columns)
check("Spalte weist die Pruefung aus",
      set(tbl_p["Geprüft"]) == {"by hand"}, set(tbl_p["Geprüft"]))

check("Bestaetigung einzelner NOTAMs wirkt gezielt",
      app.analyze_notams(df_p, sp, fir, min_confidence="MEDIUM",
                         confirmed_keys={by_p0["ohne Koordinaten"].key})[1]["confirmed"] == 1)

print("== 43. Start-Tabelle uebernimmt die Markierung ==")
gruppe = [g for g in st_p1["groups"] if g.spaceport_code and g.manual_override]
check("Gruppe ist als manuell geprueft markiert", gruppe != [], len(st_p1["groups"]))
if gruppe:
    gt_p = app.groups_to_dataframe(gruppe)
    check("Start-Tabelle hat die Spalte 'Geprüft'", "Geprüft" in gt_p.columns)
    check("Kennungen in der Start-Tabelle tragen das Hexagon",
          app.MANUAL_MARK in gt_p["NOTAMs"].iloc[0], gt_p["NOTAMs"].iloc[0])
check("Einfaerbung liefert einen Styler",
      type(app._style_manual(tbl_p)).__name__ == "Styler")
check("leere Tabelle bricht die Einfaerbung nicht",
      app._style_manual(pd.DataFrame()) is not None)

print("== 44. Bestaetigte Events koennen eine Gruppe verankern ==")
HEB = [
 "M6306/26 NOTAMN Q) EGPX/QRDCA/IV/BO/W/000/999/5743N00846W062 A) EGPX B) 2609180900 "
 "C) 2609182000 E) HEBRIDES DANGER AREAS ACTIVATED WITHIN AREA 574300N0084600W-"
 "575000N0083000W-573000N0082000W-572500N0085000W F) SFC G) UNL",
 "G0071/26 NOTAMN Q) EGGX/QRDCA/IV/BO/W/000/999/5809N01100W049 A) EGGX B) 2609180900 "
 "C) 2609182000 E) HEBRIDES COMPLEX DANGER AREAS ACTIVATED WITHIN AREA 580900N0110000W-"
 "581500N0104000W-575500N0103000W-575000N0111000W F) SFC G) UNL",
]
ev_h0, st_h0 = app.analyze_notams(pd.DataFrame({"NOTAM Text": HEB}), sp, fir, min_confidence="MEDIUM")
check("ohne Bestaetigung keine Gruppe", st_h0["launches"] == 0, st_h0["launches"])
ev_h1, st_h1 = app.analyze_notams(pd.DataFrame({"NOTAM Text": HEB}), sp, fir,
                                  min_confidence="MEDIUM", confirmed_keys={ev_h0[0].key})
check("ein bestaetigtes NOTAM verankert die Gruppe", st_h1["launches"] >= 1, st_h1["launches"])

print("== 45. USA als Zielnation ==")
check("USA in den Zielnationen", "USA" in app.TARGET_NATIONS)
check("US-Startplaetze geladen", len(sp[sp["Land"] == "USA"]) >= 12,
      len(sp[sp["Land"] == "USA"]))
check("US-FIRs geladen", len(fir[fir["Land"].astype(str).str.startswith("USA")]) >= 24,
      len(fir[fir["Land"].astype(str).str.startswith("USA")]))
check("keine Dublette Vandenberg", "KCEC" not in set(sp["Kurzel"]))
check("Oakland Oceanic deckt USA und Fremdnationen ab",
      "USA" in fir[fir["ICAO Code"] == "KZAK"]["Nationen"].iloc[0]
      and "Russland" in fir[fir["ICAO Code"] == "KZAK"]["Nationen"].iloc[0],
      fir[fir["ICAO Code"] == "KZAK"]["Nationen"].iloc[0])

print("== 46. Startplatz aus dem Traegersystem ==")
for text, erwartet in [
    ("SPACE X STARSHIP FTL-14", "KBRO"),
    ("FALCON 9 STARLINK MISSION FROM VANDENBERG SFB", "KVBG"),
    ("NEW SHEPARD SUBORBITAL FLIGHT", "K33"),
    ("ANTARES CYGNUS RESUPPLY FROM WALLOPS", "KLFI"),
    ("LAUNCH FROM JIUQUAN SATELLITE LAUNCH CENTER", "JSLC"),
    ("SOYUZ FROM PLESETSK COSMODROME", "GIK-1"),
]:
    codes, belege = app.detect_spaceport_hint(text)
    check("'{}' -> {}".format(text[:40], erwartet), erwartet in codes, (codes, belege))
check("ohne Nennung kein Startplatz-Hinweis",
      app.detect_spaceport_hint("A TEMPORARY DANGER AREA ESTABLISHED") == ([], []))

print("== 47. Starship-Wiedereintritt (A0096/26) ==")
A0096 = """A0096/26 NOTAMR A0095/26
Q) FIMM/QRALW/IV/NBO/AE/000/999/2025S07540E005
A) FIMM B) 2609281223 C) 2610041447 EST
D) 28 1223-1447
E) STATIONARY ALTITUDE RESERVATION FOR HAZARDOUS OPERATIONS FM SFC
TO UNL FOR ATMOSPHERIC RE-ENTRY AND SPLASHDOWN OF SPACE X STARSHIP
FTL-14 ROCKET WI AN AREA BOUNDED BY FLW COORD:
2630S 07500E  2704S 07318E  2436S 07206E  2342S 07500E TO BEGINNING
F) SFC G) UNL"""
ev_ss, st_ss = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": [A0096]}), sp, fir, min_confidence="MEDIUM")
e_ss = ev_ss[0]
check("wird als Start erkannt", e_ss.status == "OK", e_ss.review_reason)
check("Nation USA statt Indien", e_ss.nation == "USA", e_ss.nation)
check("Startplatz Starbase Boca Chica", e_ss.spaceport_code == "KBRO", e_ss.spaceport_code)
check("Startrichtung nach Osten", 45 < e_ss.azimuth_deg < 135, e_ss.azimuth_deg)
check("Herkunft des Startplatzes wird ausgewiesen",
      "STARSHIP" in " ".join(e_ss.spaceport_evidence), e_ss.spaceport_evidence)
check("Zuverlaessigkeit gemindert (Fernzone)", e_ss.reliability == app.RELIABILITY_LOW, e_ss.reliability)

print("== 48. Weitere US-Faelle ==")
US = {
 "Falcon 9 Vandenberg": "6/1234 NOTAMN Q) ZOA/QRTCA/IV/BO/W/000/999/3444N12034W050 A) ZOA "
   "B) 2609200400 C) 2609200600 E) TEMPORARY FLIGHT RESTRICTION FOR SPACE LAUNCH ACTIVITY. "
   "FALCON 9 STARLINK MISSION FROM VANDENBERG SFB. HAZARD AREA BOUNDED BY 343000N1203500W - "
   "341500N1201500W - 330000N1200000W - 331500N1204500W F) SFC G) UNL",
 "Amateurrakete": "!FDC 6/2736 ZLC AIRSPACE BLACK ROCK, NV..TEMPORARY FLIGHT RESTRICTIONS WI "
   "AN AREA DEFINED AS 15NM RADIUS OF 405242N1190233W SFC-UNL FOR ROCKET LAUNCH ACT. PURSUANT "
   "TO 14 CFR SECTION 91.143. ASSOCIATION OF EXPERIMENTAL ROCKETRY OF THE PACIFIC (AEROPAC).",
 "Ariane Kourou": "A1111/26 NOTAMN Q) SOOO/QRTCA/IV/BO/W/000/999 A) SOOO B) 2609200400 "
   "C) 2609200600 E) DANGER AREA FOR ARIANE 6 LAUNCH FROM KOUROU. AREA 050000N0523000W - "
   "045000N0521000W - 040000N0525000W F) SFC G) UNL",
}
ev_us, _ = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": list(US.values())}), sp, fir, min_confidence="MEDIUM")
by_us = dict(zip(US, ev_us))
check("Falcon 9 von Vandenberg -> USA",
      by_us["Falcon 9 Vandenberg"].status == "OK" and by_us["Falcon 9 Vandenberg"].nation == "USA",
      (by_us["Falcon 9 Vandenberg"].status, by_us["Falcon 9 Vandenberg"].nation))
check("  ... Startplatz Vandenberg", by_us["Falcon 9 Vandenberg"].spaceport_code == "KVBG",
      by_us["Falcon 9 Vandenberg"].spaceport_code)
check("  ... suedliche Startrichtung (SSO)",
      150 < by_us["Falcon 9 Vandenberg"].azimuth_deg < 220,
      by_us["Falcon 9 Vandenberg"].azimuth_deg)
check("Amateurrakete bleibt draussen", by_us["Amateurrakete"].status == "REVIEW",
      by_us["Amateurrakete"].status)
check("Ariane bleibt draussen", by_us["Ariane Kourou"].status == "REVIEW",
      by_us["Ariane Kourou"].review_reason[:50])

print("== 49. Start oder Wiedereintritt ==")
for text, erwartet in [
    ("ATMOSPHERIC RE-ENTRY AND SPLASHDOWN OF SPACE X STARSHIP", app.KIND_REENTRY),
    ("SPACE DEBRIS RETURN OF SPACEX STARLINK 15-27", app.KIND_REENTRY),
    ("ZONE IN WATERS PACIFIC OCEAN DUE TO SPACE VEHICLE RE-ENTRY", app.KIND_REENTRY),
    ("A TEMPORARY DANGER AREA ESTABLISHED FOR SPACE LAUNCH ACTIVITY", app.KIND_LAUNCH),
    ("AIRSPACE CLSD WI AREA", app.KIND_LAUNCH),
]:
    check("'{}' -> {}".format(text[:44], erwartet), app.classify_event_kind(text) == erwartet,
          app.classify_event_kind(text))
check("Wiedereintritt mindert die Zuverlaessigkeit",
      app.zone_reliability(500.0, app.KIND_REENTRY) == app.RELIABILITY_LOW,
      app.zone_reliability(500.0, app.KIND_REENTRY))
check("Start in Startplatznaehe bleibt hoch",
      app.zone_reliability(500.0, app.KIND_LAUNCH) == app.RELIABILITY_HIGH)
check("grosse Azimut-Streuung mindert die Zuverlaessigkeit",
      app.zone_reliability(500.0, app.KIND_LAUNCH, 120.0) == app.RELIABILITY_LOW)
check("Spalte 'Art' in der NOTAM-Tabelle",
      "Art" in app.events_to_dataframe(ev_ss).columns)

print("== 50. US-Wiedereintritte im Echtbestand ==")
if xls:
    ev_u, st_u = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    g_u = {g.group_id: g for g in st_u["groups"] if g.spaceport_code}
    usa = [g for g in g_u.values() if g.nation == "USA"]
    check("US-Ereignisse werden erkannt", len(usa) >= 2, len(usa))
    # Seit MMFR in der FIR-Referenz steht, sind auch die Start-Gefahrengebiete
    # von Boca Chica sichtbar - vorher kannte der Bestand nur Wiedereintritte.
    wieder = [g for g in usa if g.kind == app.KIND_REENTRY]
    starts = [g for g in usa if g.kind == app.KIND_LAUNCH]
    check("  ... Wiedereintritte darunter", wieder != [], [(g.group_id, g.kind) for g in usa])
    check("  ... und Starts darunter", starts != [], [(g.group_id, g.kind) for g in usa])
    check("  ... Wiedereintritte mit gemindeter Zuverlaessigkeit",
          all(g.reliability == app.RELIABILITY_LOW for g in wieder),
          [(g.group_id, g.reliability) for g in wieder])
    starship = [g for g in usa if g.spaceport_code == "KBRO"]
    check("Starship-Gruppen gefunden", len(starship) >= 2, [g.group_id for g in starship])
    check("  ... A0096/26 ist in einer davon",
          any("A0096/26" in n for g in starship for n in g.notam_ids),
          [g.notam_ids for g in starship])
    check("  ... und das Start-Gefahrengebiet aus MMFR in einer anderen",
          any("B1848/26" in n for g in starship for n in g.notam_ids),
          [g.notam_ids for g in starship])
    mmfr = [e for e in ev_u if e.fir_code == "MMFR"]
    spacex = [e for e in mmfr if "SPACEX" in e.raw_text.upper()]
    check("MMFR wird gefunden", len(mmfr) >= 3, len(mmfr))
    check("  ... drei SpaceX-Meldungen darunter", len(spacex) == 3,
          [e.notam_id for e in spacex])
    check("  ... alle den USA zugeordnet", all(e.nation == "USA" for e in spacex),
          [(e.notam_id, e.nation) for e in spacex])
    check("  ... ueber den Text, nicht ueber die FIR",
          all("SPACEX" in e.nation_evidence for e in spacex),
          [e.nation_evidence for e in spacex])
    # MMFR liegt in Mexiko: die Drittstaaten-Regel darf die USA nur zulassen,
    # wenn der Text sie nennt. Die uebrigen MMFR-Meldungen sind US-Advisories
    # ohne Startbezug und muessen im Review bleiben.
    ohne_beleg = [e for e in mmfr if e not in spacex]
    check("  ... Meldungen ohne Textbeleg bleiben im Review",
          all(e.status == "REVIEW" and e.nation is None for e in ohne_beleg),
          [(e.notam_id, e.status, e.nation) for e in ohne_beleg])
    chinesisch = [g for g in g_u.values() if g.nation == "China"]
    check("chinesische Starts bleiben Starts",
          all(g.kind == app.KIND_LAUNCH for g in chinesisch),
          [(g.group_id, g.kind) for g in chinesisch])
    check("  ... mit hoher Zuverlaessigkeit",
          all(g.reliability == app.RELIABILITY_HIGH for g in chinesisch),
          [(g.group_id, g.reliability) for g in chinesisch])
    check("keine chinesische Zone bei einem US-Startplatz",
          all(g.spaceport_code not in ("KBRO", "KVBG", "KXMR") for g in chinesisch))

print("== 51. Referenzdaten im Optionsmenue aendern ==")
ohne_tslc = app.apply_reference_overrides(sp, "Kurzel", ["TSLC"], [])
check("entfernter Startplatz faellt raus",
      "TSLC" not in set(ohne_tslc["Kurzel"]) and len(ohne_tslc) == len(sp) - 1,
      (len(sp), len(ohne_tslc)))
mit_neu = app.apply_reference_overrides(
    sp, "Kurzel",
    [],
    [{"Kurzel": "NEUX", "Latitude": 12.0, "Longitude": 34.0, "Name": "Testplatz", "Land": "China"}],
)
check("hinzugefuegter Startplatz kommt dazu",
      "NEUX" in set(mit_neu["Kurzel"]) and len(mit_neu) == len(sp) + 1, len(mit_neu))
check("  ... mit numerischen Koordinaten",
      float(mit_neu[mit_neu["Kurzel"] == "NEUX"]["Latitude"].iloc[0]) == 12.0)
wieder = app.apply_reference_overrides(
    sp, "Kurzel", [],
    [{"Kurzel": "TSLC", "Latitude": 1.0, "Longitude": 2.0, "Name": "Neu", "Land": "China"}],
)
check("wieder hinzugefuegter Eintrag ersetzt statt zu verdoppeln",
      (wieder["Kurzel"] == "TSLC").sum() == 1 and len(wieder) == len(sp),
      ((wieder["Kurzel"] == "TSLC").sum(), len(wieder)))
check("  ... und uebernimmt die neuen Werte",
      float(wieder[wieder["Kurzel"] == "TSLC"]["Latitude"].iloc[0]) == 1.0)

fir_ohne = app.apply_reference_overrides(fir, "ICAO Code", ["ZBPE"], [])
check("entfernte FIR faellt raus", "ZBPE" not in set(fir_ohne["ICAO Code"]))
fir_neu = app.apply_reference_overrides(
    fir, "ICAO Code", [],
    [{"ICAO Code": "XXXX", "Latitude": 5.0, "Longitude": 6.0,
      "Betroffene Region / FIR Name": "Test FIR", "Land": "China",
      "Zugehörige Startnation": "China;USA"}],
)
check("hinzugefuegte FIR kommt dazu", "XXXX" in set(fir_neu["ICAO Code"]))
check("  ... mit abgeleiteter Nationenliste",
      fir_neu[fir_neu["ICAO Code"] == "XXXX"]["Nationen"].iloc[0] == ["China", "USA"],
      fir_neu[fir_neu["ICAO Code"] == "XXXX"]["Nationen"].iloc[0])
check("unvollstaendige Zeilen werden verworfen",
      len(app.apply_reference_overrides(
          sp, "Kurzel", [], [{"Kurzel": "KAPUTT", "Latitude": None, "Longitude": None,
                              "Name": "x", "Land": "China"}])) == len(sp))

print("== 52. Aenderungen wirken auf die Berechnung ==")
TAIYUAN = ["""4456/26 NOTAMN
Q)ZXXX/QRDCA/IV/BO/W/000/999/3322N11036E013
A)ZLHW ZHWH B)2609191043 C)2609191106
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N333400E1103100-N333200E1104400-N331000E1104100-N331100E1102700,
BACK TO START.VERTICAL LIMITS:SFC-UNL. F)SFC G)UNL""", """A4457/26 NOTAMN
Q)ZHWH/QRDCA/IV/BO/W/000/999/3015N11005E022
A)ZHWH B)2609191044 C)2609191111
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N303500E1095700-N303300E1101900-N295400E1101300-N295700E1095100,
BACK TO START.VERTICAL LIMITS:SFC-UNL. F)SFC G)UNL"""]
df_t = pd.DataFrame({"NOTAM Text": TAIYUAN})
ev_t0, _ = app.analyze_notams(df_t, sp, fir, min_confidence="MEDIUM")
check("mit vollstaendiger Referenz -> Taiyuan", ev_t0[0].spaceport_code == "TSLC",
      ev_t0[0].spaceport_code)
ev_t1, _ = app.analyze_notams(df_t, ohne_tslc, fir, min_confidence="MEDIUM")
check("nach Entfernen von TSLC nicht mehr Taiyuan", ev_t1[0].spaceport_code != "TSLC",
      ev_t1[0].spaceport_code)
check("  ... aber weiterhin ein Ergebnis", ev_t1[0].status == "OK", ev_t1[0].review_reason)

# Naeher an der Zone als Taiyuan und mit suedlicher Startrichtung: der neue
# Eintrag muss die Zuordnung uebernehmen. (Bei beiden Zonen zusammen gewinnt
# Taiyuan zu Recht, weil es beide mit 0,0 Grad Streuung erklaert - deshalb hier
# nur die erste Zone.)
sp_erweitert = app.apply_reference_overrides(
    sp, "Kurzel", [],
    [{"Kurzel": "NEUX", "Latitude": 35.5, "Longitude": 110.5, "Name": "Neuer Platz",
      "Land": "China"}],
)
df_eine = pd.DataFrame({"NOTAM Text": [TAIYUAN[0]]})
ev_t2a, _ = app.analyze_notams(df_eine, sp, fir, min_confidence="MEDIUM")
check("einzelne Zone ohne den neuen Eintrag -> Taiyuan",
      ev_t2a[0].spaceport_code == "TSLC", ev_t2a[0].spaceport_code)
ev_t2, _ = app.analyze_notams(df_eine, sp_erweitert, fir, min_confidence="MEDIUM")
check("neu hinzugefuegter Startplatz wird sofort beruecksichtigt",
      ev_t2[0].spaceport_code == "NEUX", ev_t2[0].spaceport_code)
check("  ... Taiyuan bleibt bei zwei Zonen die bessere Erklaerung",
      app.analyze_notams(df_t, sp_erweitert, fir, min_confidence="MEDIUM")[0][0].spaceport_code
      == "TSLC")

fir_ohne_zhwh = app.apply_reference_overrides(fir, "ICAO Code", ["ZHWH", "ZLHW"], [])
ev_t3, _ = app.analyze_notams(df_t, sp, fir_ohne_zhwh, min_confidence="MEDIUM")
check("entfernte FIR entzieht dem NOTAM die Zuordnung",
      all(e.status == "REVIEW" for e in ev_t3), [(e.notam_id, e.status) for e in ev_t3])

print("== 53. Referenz-Export ==")
csv_sp = app.reference_to_csv(sp, app.SPACEPORT_EXPORT_COLUMNS)
check("Startplatz-CSV hat die Originalspalten",
      csv_sp.decode("utf-8-sig").splitlines()[0] == ",".join(app.SPACEPORT_EXPORT_COLUMNS),
      csv_sp.decode("utf-8-sig").splitlines()[0])
csv_fir = app.reference_to_csv(fir, app.FIR_EXPORT_COLUMNS)
check("FIR-CSV hat die Originalspalten",
      csv_fir.decode("utf-8-sig").splitlines()[0] == ",".join(app.FIR_EXPORT_COLUMNS))
check("Export enthaelt die Aenderungen",
      "NEUX" in app.reference_to_csv(sp_erweitert, app.SPACEPORT_EXPORT_COLUMNS).decode("utf-8-sig"))
check("Export laesst sich wieder einlesen",
      len(pd.read_csv(io.BytesIO(csv_sp))) == len(sp))

print("== 54. Persistenz in die Projektdateien ==")
import shutil, tempfile
from pathlib import Path
tmp = Path(tempfile.mkdtemp())
sp_datei = tmp / "sp.csv"
fir_datei = tmp / "fir.csv"
shutil.copy(app.SPACEPORT_CSV, sp_datei)
shutil.copy(app.FIR_CSV, fir_datei)

app.persist_reference(sp_datei, sp[sp["Kurzel"] != "TSLC"], app.SPACEPORT_EXPORT_COLUMNS)
app.load_spaceports.clear()
nach_entfernen = app.load_spaceports(str(sp_datei))
check("Entfernen landet in der Datei",
      "TSLC" not in set(nach_entfernen["Kurzel"]) and len(nach_entfernen) == len(sp) - 1,
      len(nach_entfernen))
check("  ... und ueberlebt erneutes Laden",
      "TSLC" not in set(pd.read_csv(sp_datei)["Kurzel"]))

zeile = {"Kurzel": "NEUX", "Latitude": 12.0, "Longitude": 34.0,
         "Name": "Testplatz", "Land": "China"}
app.persist_reference(
    sp_datei, pd.concat([nach_entfernen, pd.DataFrame([zeile])], ignore_index=True),
    app.SPACEPORT_EXPORT_COLUMNS)
app.load_spaceports.clear()
nach_hinzu = app.load_spaceports(str(sp_datei))
check("Hinzufuegen landet in der Datei", "NEUX" in set(nach_hinzu["Kurzel"]))
check("  ... mit den richtigen Werten",
      float(nach_hinzu[nach_hinzu["Kurzel"] == "NEUX"]["Latitude"].iloc[0]) == 12.0)
check("geschriebene Datei hat das Originalformat",
      list(pd.read_csv(sp_datei).columns) == list(app.SPACEPORT_EXPORT_COLUMNS),
      list(pd.read_csv(sp_datei).columns))

app.persist_reference(fir_datei, fir[fir["ICAO Code"] != "ZBPE"], app.FIR_EXPORT_COLUMNS)
app.load_firs.clear()
fir_neu = app.load_firs(str(fir_datei))
check("FIR-Entfernen landet in der Datei", "ZBPE" not in set(fir_neu["ICAO Code"]))
check("  ... abgeleitete Spalte wird nicht mitgeschrieben",
      "Nationen" not in list(pd.read_csv(fir_datei).columns),
      list(pd.read_csv(fir_datei).columns))
check("  ... entsteht beim Laden neu", "Nationen" in fir_neu.columns)

print("== 55. Arbeitsstand ueberlebt den Neustart ==")
ws_original = app.WORKSPACE_FILE
try:
    app.WORKSPACE_FILE = tmp / "workspace.json"
    check("ohne Datei ein leerer Stand", app.load_workspace() == {})
    app.save_workspace(
        [{"text": "A1/26 TEST NOTAM", "added": "21.09.2026 20:00Z"}],
        {"key-eins", "key-zwei"}, {"key-drei"},
    )
    geladen = app.load_workspace()
    check("manuelle NOTAMs gespeichert", len(geladen["manual_notams"]) == 1,
          geladen["manual_notams"])
    check("Bestaetigungen gespeichert",
          set(geladen["confirmed_launches"]) == {"key-eins", "key-zwei"},
          geladen["confirmed_launches"])
    check("Ausblendungen gespeichert", geladen["hidden_events"] == ["key-drei"],
          geladen["hidden_events"])
    check("Zeitstempel vermerkt", "gespeichert_utc" in geladen)
    app.WORKSPACE_FILE.write_text("kein json", encoding="utf-8")
    check("beschaedigte Datei bricht die App nicht", app.load_workspace() == {})
finally:
    app.WORKSPACE_FILE = ws_original
    app.load_spaceports.clear()
    app.load_firs.clear()
    shutil.rmtree(tmp, ignore_errors=True)

check("Projektdateien unveraendert geblieben",
      len(app.load_spaceports(str(app.SPACEPORT_CSV))) == len(sp)
      and len(app.load_firs(str(app.FIR_CSV))) == len(fir))

print("== 56. Einheitliche Markierung in allen Ansichten ==")
md = app.mark_id_markdown("A4457/26", True)
check("Markdown-Markierung faerbt violett", md.startswith(":violet["), md)
check("  ... enthaelt Symbol und Kennung",
      app.MANUAL_MARK in md and "A4457/26" in md, md)
check("  ... Symbol steht vor der Kennung",
      md.index(app.MANUAL_MARK) < md.index("A4457/26"))
check("ohne Bestaetigung keine Einfaerbung",
      app.mark_id_markdown("A4457/26", False) == "A4457/26")

check("Farbton folgt dem dunklen Theme", app.manual_color() == app.MANUAL_COLOR,
      app.manual_color())
check("Violett der manuellen Marke ist ein Signalton, keine Flaeche",
      app.MANUAL_COLOR.upper() == "#B7A8FF", app.MANUAL_COLOR)
check("  ... und das Theme fuehrt ein eigenes Signalviolett",
      'violetColor = "#A44DC4"' in Path(".streamlit/config.toml").read_text(encoding="utf-8"))
check("helles Theme nutzt den dunkleren Gegenpart",
      app.MANUAL_COLOR_LIGHT.upper() == "#6D4AE0", app.MANUAL_COLOR_LIGHT)
check("HTML-Markierung nutzt denselben Farbton",
      app.manual_color() in app.mark_id_html("A4457/26", True),
      app.mark_id_html("A4457/26", True)[:50])

# Alle drei Darstellungswege tragen dieselbe Kennung samt Symbol
ev_m, st_m = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": [PRUEFFAELLE["ohne Koordinaten"]]}), sp, fir,
    min_confidence="MEDIUM", confirmed_keys={by_p0["ohne Koordinaten"].key})
e_m = ev_m[0]
tabelle = app.events_to_dataframe(ev_m)
check("Tabelle zeigt Symbol + Kennung",
      str(tabelle["NOTAM ID"].iloc[0]).startswith(app.MANUAL_MARK),
      tabelle["NOTAM ID"].iloc[0])
check("Kopfzeile in NOTAM Data zeigt Symbol + Kennung eingefaerbt",
      app.mark_id_markdown(e_m.notam_id, e_m.manual_override).startswith(":violet["),
      app.mark_id_markdown(e_m.notam_id, e_m.manual_override))
check("beide zeigen dieselbe Kennung",
      e_m.notam_id in str(tabelle["NOTAM ID"].iloc[0])
      and e_m.notam_id in app.mark_id_markdown(e_m.notam_id, True))
styler = app._style_manual(tabelle)
check("Einfaerbung der Tabelle nutzt denselben Farbton",
      app.manual_color().lower() in styler.to_html().lower(),
      app.manual_color())

print("== 57. Start aus NOTAM Data zurueckstellen ==")
demo_r = app.build_demo_notams()
ev_r0, st_r0 = app.analyze_notams(demo_r, sp, fir, min_confidence="MEDIUM")
ok_r0 = [e for e in ev_r0 if e.status == "OK"]
ziel = ok_r0[0]
check("Ausgangslage: Start in der Launch-Tabelle", ziel.status == "OK", ziel.status)

ev_r1, st_r1 = app.analyze_notams(
    demo_r, sp, fir, min_confidence="MEDIUM", rejected_keys={ziel.key})
e_r1 = next(e for e in ev_r1 if e.key == ziel.key)
check("nach Zurueckstellung im Review", e_r1.status == "REVIEW", e_r1.status)
check("  ... mit sprechender Begruendung",
      "back to review" in e_r1.review_reason, e_r1.review_reason)
check("  ... ein Eintrag weniger in der Launch-Tabelle",
      st_r1["ok"] == st_r0["ok"] - 1, (st_r0["ok"], st_r1["ok"]))
check("  ... und ein Review-Fall mehr",
      st_r1["review"] == st_r0["review"] + 1, (st_r0["review"], st_r1["review"]))
check("  ... aus der Startgruppe entfernt", e_r1.launch_group == "", e_r1.launch_group)
check("  ... in keiner Gruppe mehr enthalten",
      all(ziel.row_index not in g.row_indices for g in st_r1["groups"] if g.spaceport_code))
check("  ... Statistik zaehlt die Zurueckstellung", st_r1["rejected"] == 1, st_r1["rejected"])
check("andere Starts bleiben unberuehrt",
      st_r1["launches"] == st_r0["launches"] - 1, (st_r0["launches"], st_r1["launches"]))

print("== 58. Zusammenspiel der manuellen Entscheidungen ==")
ev_r2, _ = app.analyze_notams(
    demo_r, sp, fir, min_confidence="MEDIUM",
    confirmed_keys={ziel.key}, rejected_keys={ziel.key})
e_r2 = next(e for e in ev_r2 if e.key == ziel.key)
check("Zurueckstellung sticht die Bestaetigung", e_r2.status == "REVIEW", e_r2.status)
check("  ... und entfernt die Markierung", not e_r2.manual_override)

ev_r3, st_r3 = app.analyze_notams(demo_r, sp, fir, min_confidence="MEDIUM")
check("Aufhebung stellt den Ausgangszustand her",
      st_r3["ok"] == st_r0["ok"] and st_r3["launches"] == st_r0["launches"],
      (st_r3["ok"], st_r0["ok"]))

review_ziel = [e for e in ev_r0 if e.status == "REVIEW"][0]
ev_r4, _ = app.analyze_notams(
    demo_r, sp, fir, min_confidence="MEDIUM", rejected_keys={review_ziel.key})
e_r4 = next(e for e in ev_r4 if e.key == review_ziel.key)
check("Zurueckstellung ueberschreibt keine echte Review-Begruendung",
      e_r4.review_reason == review_ziel.review_reason, e_r4.review_reason)

print("== 59. Arbeitsstand sichert die Zurueckstellungen ==")
ws_alt = app.WORKSPACE_FILE
try:
    import tempfile as _tf
    from pathlib import Path as _P
    app.WORKSPACE_FILE = _P(_tf.mkdtemp()) / "ws.json"
    app.save_workspace([], {"bestaetigt"}, {"versteckt"}, {"zurueckgestellt"})
    g = app.load_workspace()
    check("Zurueckstellungen gespeichert",
          g["rejected_launches"] == ["zurueckgestellt"], g.get("rejected_launches"))
    check("  ... neben Bestaetigungen und Ausblendungen",
          g["confirmed_launches"] == ["bestaetigt"] and g["hidden_events"] == ["versteckt"])
    check("alter Arbeitsstand ohne das Feld bleibt lesbar",
          app.load_workspace().get("rejected_launches") is not None)
finally:
    app.WORKSPACE_FILE = ws_alt

print("== 60. Sprung von der Launch Overview zum Volltext ==")
class _Auswahl:
    def __init__(self, zeilen):
        self.selection = type("S", (), {"rows": list(zeilen)})()

check("markierte Zeile wird gelesen", app._auswahl_zeilen(_Auswahl([2])) == [2])
check("ohne Markierung leere Liste", app._auswahl_zeilen(_Auswahl([])) == [])
check("unbekanntes Objekt bricht nicht", app._auswahl_zeilen(object()) == [])

ev_n, st_n = app.analyze_notams(app.build_demo_notams(), sp, fir, min_confidence="MEDIUM")
gruppen = [g for g in st_n["groups"] if g.spaceport_code]
tabelle_n = app.events_to_dataframe([e for e in ev_n if e.status == "OK"])
check("Start-Tabelle und Gruppenliste sind gleich lang",
      len(app.groups_to_dataframe(gruppen)) == len(gruppen), (len(gruppen),))
check("jede Gruppe kennt ihre NOTAM-Zeilen",
      all(g.row_indices for g in gruppen), [g.row_indices for g in gruppen])
zeile = 2
check("Zeilenposition fuehrt zur richtigen Gruppe",
      app.groups_to_dataframe(gruppen)["Start"].iloc[zeile] == gruppen[zeile].group_id,
      (app.groups_to_dataframe(gruppen)["Start"].iloc[zeile], gruppen[zeile].group_id))
check("NOTAM-Tabelle traegt die Zeilennummer fuer den Sprung",
      "_row" in tabelle_n.columns and tabelle_n["_row"].notna().all())
ziel_row = int(tabelle_n["_row"].iloc[1])
check("Zeilennummer zeigt auf ein Event",
      any(e.row_index == ziel_row for e in ev_n), ziel_row)

print("== 61. Navigation ist programmgesteuert ==")
quelle = Path("app.py").read_text(encoding="utf-8")
check("Hauptnavigation nutzt kein st.tabs mehr",
      "tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(" not in quelle,
      "Hauptnavigation noch auf st.tabs")
check("  ... im Optionsdialog bleibt st.tabs zulaessig",
      "reiter = st.tabs(titel)" in quelle)
check("Segmentleiste steuert die Bereiche", "st.segmented_control(" in quelle)
check("sechs Bereiche definiert", quelle.count("if bereich == reiter[") == 6,
      quelle.count("if bereich == reiter["))
check("Sprungkennzeichen wird gesetzt und verbraucht",
      'st.session_state["goto_notam_data"] = True' in quelle
      and 'st.session_state.pop("goto_notam_data", False)' in quelle)
check("gewaehlte Zeilen werden gemerkt", '"focus_rows"' in quelle)

print("== 62. Referenz der Traegersysteme ==")
veh = app.load_vehicles(str(app.VEHICLE_CSV))
check("Traegersysteme geladen", len(veh) >= 51, len(veh))
check("Spalten wie in der Quelldatei",
      list(veh.columns) == app.VEHICLE_COLUMNS, list(veh.columns))
check("Abkuerzungen sind eindeutig",
      veh["Abkürzung"].duplicated().sum() == 0,
      list(veh[veh["Abkürzung"].duplicated()]["Abkürzung"]))
check("keine leeren Abkuerzungen oder Namen",
      veh["Abkürzung"].str.strip().astype(bool).all() and veh["Name"].str.strip().astype(bool).all())
nationen = set(veh["Land"])
check("nur Zielnationen als Land", nationen <= set(app.TARGET_NATIONS), sorted(nationen))
check("  ... 'Amerika' auf 'USA' vereinheitlicht",
      "Amerika" not in nationen and "USA" in nationen, sorted(nationen))
check("alle sechs Nationen vertreten",
      nationen == set(app.TARGET_NATIONS), sorted(set(app.TARGET_NATIONS) - nationen))
for kuerzel, land in [("CZ-5B", "China"), ("Soyuz-2.1b", "Russland"), ("PSLV", "Indien"),
                      ("Simorgh", "Iran"), ("Chollima-1", "Nordkorea"), ("F9", "USA")]:
    zeile = veh[veh["Abkürzung"] == kuerzel]
    check("{} gefunden und {} zugeordnet".format(kuerzel, land),
          len(zeile) == 1 and zeile["Land"].iloc[0] == land,
          zeile["Land"].iloc[0] if len(zeile) else "fehlt")

print("== 63. Traegersysteme sind modular aenderbar ==")
ohne = app.apply_reference_overrides(veh, "Abkürzung", ["CZ-5B"], [])
check("Entfernen wirkt", "CZ-5B" not in set(ohne["Abkürzung"]) and len(ohne) == len(veh) - 1,
      len(ohne))
mit = app.apply_reference_overrides(
    veh, "Abkürzung", [],
    [{"Land": "China", "Name": "Chang Zheng 9", "Alternativname englisch": "Long March 9",
      "Abkürzung": "CZ-9"}],
)
check("Hinzufuegen wirkt", "CZ-9" in set(mit["Abkürzung"]) and len(mit) == len(veh) + 1,
      len(mit))
ersetzt = app.apply_reference_overrides(
    veh, "Abkürzung", [],
    [{"Land": "China", "Name": "Neuer Name", "Alternativname englisch": "New Name",
      "Abkürzung": "CZ-5B"}],
)
check("erneutes Hinzufuegen ersetzt statt zu verdoppeln",
      (ersetzt["Abkürzung"] == "CZ-5B").sum() == 1 and len(ersetzt) == len(veh),
      ((ersetzt["Abkürzung"] == "CZ-5B").sum(), len(ersetzt)))
check("  ... mit den neuen Werten",
      ersetzt[ersetzt["Abkürzung"] == "CZ-5B"]["Name"].iloc[0] == "Neuer Name")

print("== 64. Traegersysteme werden in die Datei geschrieben ==")
import shutil as _sh, tempfile as _tf
from pathlib import Path as _P
tmp_v = _P(_tf.mkdtemp())
veh_datei = tmp_v / "veh.csv"
_sh.copy(app.VEHICLE_CSV, veh_datei)
try:
    app.persist_reference(veh_datei, ohne, app.VEHICLE_EXPORT_COLUMNS)
    app.load_vehicles.clear()
    nach = app.load_vehicles(str(veh_datei))
    check("Entfernen landet in der Datei",
          "CZ-5B" not in set(nach["Abkürzung"]) and len(nach) == len(veh) - 1, len(nach))
    check("geschriebene Datei hat das Originalformat",
          list(pd.read_csv(veh_datei).columns) == list(app.VEHICLE_EXPORT_COLUMNS),
          list(pd.read_csv(veh_datei).columns))
    app.persist_reference(veh_datei, mit, app.VEHICLE_EXPORT_COLUMNS)
    app.load_vehicles.clear()
    check("Hinzufuegen landet in der Datei",
          "CZ-9" in set(app.load_vehicles(str(veh_datei))["Abkürzung"]))
    fehlerhaft = tmp_v / "kaputt.csv"
    fehlerhaft.write_text("Land,Name\nChina,Test\n", encoding="utf-8")
    app.load_vehicles.clear()
    try:
        app.load_vehicles(str(fehlerhaft))
        check("fehlende Spalten werden gemeldet", False, "keine Ausnahme")
    except ValueError as e:
        check("fehlende Spalten werden gemeldet", "Abkürzung" in str(e), str(e)[:60])
finally:
    app.load_vehicles.clear()
    _sh.rmtree(tmp_v, ignore_errors=True)
check("Projektdatei unveraendert",
      len(app.load_vehicles(str(app.VEHICLE_CSV))) == len(veh))

print("== 65. Einbindung wie die anderen Referenzen ==")
quelle_v = Path("app.py").read_text(encoding="utf-8")
check("eigener Pfad definiert", "VEHICLE_CSV = APP_DIR" in quelle_v)
check("Statuszeile in der Sidebar", '_reference_status("Traegersysteme", VEHICLE_CSV)' in quelle_v)
check("eigener Reiter im Optionsmenue", "_vehicle_editor(vehicles)" in quelle_v)
check("Entfernen schreibt in die Datei",
      "VEHICLE_CSV, vehicles, VEHICLE_EXPORT_COLUMNS" in quelle_v)
check("Sicherungs-Schaltflaeche vorhanden", "Download launch vehicles" in quelle_v)

def _ev_n(nation=None, hint=None, fir=None):
    e = app.LaunchEvent(row_index=0, notam_id="X", raw_text="x")
    e.nation, e.nation_hint, e.fir_country = nation, hint, fir
    return e

print("== 66. Traegersystem-Dropdown: gestaffelte Auswahlliste ==")
veh_ref = app.load_vehicles(str(app.VEHICLE_CSV))
opt = app.vehicle_options(veh_ref, "China")
check("erster Eintrag ist die leere Zuweisung", opt[0] == app.VEHICLE_NONE, opt[0])
check("Trennzeile vorhanden", app.VEHICLE_SEPARATOR in opt)
tr = opt.index(app.VEHICLE_SEPARATOR)
laender = dict(zip(veh_ref["Abkürzung"].astype(str), veh_ref["Land"].astype(str)))
check("vor dem Trenner nur China",
      all(laender.get(c) == "China" for c in opt[1:tr]), opt[1:tr][:3])
check("nach dem Trenner kein China",
      all(laender.get(c) != "China" for c in opt[tr + 1:]), opt[tr + 1:][:3])
check("Liste vollstaendig (51 + leer + Trenner)", len(opt) == len(veh_ref) + 2, len(opt))
check("keine harte Filterung - Falcon 9 bleibt waehlbar", "F9" in opt)
opt_ohne = app.vehicle_options(veh_ref, None)
check("ohne Nation kein Trenner", app.VEHICLE_SEPARATOR not in opt_ohne)
check("ohne Nation trotzdem vollstaendig", len(opt_ohne) == len(veh_ref) + 1, len(opt_ohne))
import pandas as _pd
check("leere Referenz liefert nur den leeren Eintrag",
      app.vehicle_options(_pd.DataFrame(columns=app.VEHICLE_COLUMNS), "China")
      == [app.VEHICLE_NONE])

check("Staffelung: festgestellte Nation zaehlt zuerst",
      app.vehicle_nation(_ev_n(nation="China", hint="Russland", fir="Iran")) == "China")
check("Staffelung: ohne Nation hilft der Textbeleg",
      app.vehicle_nation(_ev_n(nation=None, hint="Nordkorea", fir="Iran")) == "Nordkorea")
check("Staffelung: sonst die FIR - im Review der Regelfall",
      app.vehicle_nation(_ev_n(nation=None, hint=None, fir="Iran")) == "Iran")
check("Staffelung: Drittstaat bleibt aussen vor",
      app.vehicle_nation(_ev_n(nation=None, hint=None, fir="Norwegen")) is None)

print("== 67. Beschriftung der Traegersysteme ==")
check("Name und Kuerzel", app.vehicle_label("F9", veh_ref) == "Falcon 9 (F9)",
      app.vehicle_label("F9", veh_ref))
check("mit Nation", app.vehicle_label("F9", veh_ref, with_nation=True).endswith("USA"),
      app.vehicle_label("F9", veh_ref, with_nation=True))
check("leerer Code", app.vehicle_label("", veh_ref) == app.VEHICLE_NONE_LABEL)
check("entfernter Eintrag wird ausgewiesen",
      "no longer in the reference" in app.vehicle_label("CZ-99", veh_ref),
      app.vehicle_label("CZ-99", veh_ref))
check("ohne Referenz bleibt der Code stehen", app.vehicle_label("CZ-2D") == "CZ-2D")
check("Trennzeile ist beschriftet", "other nations" in app.vehicle_label(app.VEHICLE_SEPARATOR))

print("== 68. Zuweisung gilt fuer alle Zonen eines Starts ==")
def _ev(row, key, nation="China"):
    e = app.LaunchEvent(row_index=row, notam_id="A{:04d}/26".format(row), raw_text="x")
    e.key = key
    e.nation = nation
    return e

e1, e2, e3 = _ev(1, "k1"), _ev(2, "k2"), _ev(9, "k9")
g = app.LaunchGroup(group_id="START-01", row_indices=[1, 2])
g2 = app.LaunchGroup(group_id="START-02", row_indices=[9])
app.apply_vehicle_assignments([e1, e2, e3], [g, g2], {"k1": "CZ-2D"})
check("gesetzte Zone traegt das System", e1.vehicle == "CZ-2D", e1.vehicle)
check("Schwesterzone uebernimmt es", e2.vehicle == "CZ-2D", e2.vehicle)
check("der Start traegt es", g.vehicle == "CZ-2D", g.vehicle)
check("fremder Start bleibt leer", e3.vehicle == "" and g2.vehicle == "", (e3.vehicle, g2.vehicle))

app.apply_vehicle_assignments([e1, e2], [g], {"k1": "CZ-2D", "k2": "CZ-4C"})
check("Widerspruch: jede Zone behaelt ihre eigene",
      (e1.vehicle, e2.vehicle) == ("CZ-2D", "CZ-4C"), (e1.vehicle, e2.vehicle))
check("Widerspruch: der Start wird als uneinheitlich ausgewiesen",
      g.vehicle == app.MIXED_VALUE, g.vehicle)

app.apply_vehicle_assignments([e1, e2], [g], {})
check("leere Zuweisung raeumt auf",
      (e1.vehicle, e2.vehicle, g.vehicle) == ("", "", ""), (e1.vehicle, g.vehicle))

print("== 69. Traegersystem in den Tabellen ==")
e1.vehicle = "CZ-2D"
g.vehicle = "CZ-2D"
t_ev = app.events_to_dataframe([e1], veh_ref)
check("Spalte in der NOTAM-Tabelle", "Trägersystem" in t_ev.columns)
check("Beschriftung statt Code", t_ev["Trägersystem"].iloc[0] == "Chang Zheng 2D (CZ-2D)",
      t_ev["Trägersystem"].iloc[0])
t_gr = app.groups_to_dataframe([g], veh_ref)
check("Spalte in der Start-Tabelle", "Trägersystem" in t_gr.columns)
check("Start zeigt dasselbe System", t_gr["Trägersystem"].iloc[0] == "Chang Zheng 2D (CZ-2D)",
      t_gr["Trägersystem"].iloc[0])
e1.vehicle = ""
check("ohne Zuweisung steht ein Strich",
      app.events_to_dataframe([e1], veh_ref)["Trägersystem"].iloc[0] == "-")
check("ohne Referenz bleibt der Code lesbar",
      app.groups_to_dataframe([g])["Trägersystem"].iloc[0] == "CZ-2D")

print("== 70. Zuweisungen ueberleben den Neustart ==")
import json as _json, shutil as _shutil, tempfile as _tempfile
tmp_w = Path(_tempfile.mkdtemp())
echt_w = app.WORKSPACE_FILE
try:
    app.WORKSPACE_FILE = tmp_w / "notam_workspace.json"
    app.save_workspace([], [], [], vehicle_assignments={"k1": "CZ-2D", "k2": "CZ-2D", "k3": ""})
    daten = _json.loads(app.WORKSPACE_FILE.read_text(encoding="utf-8"))
    check("Zuweisungen stehen in der Datei",
          daten["vehicle_assignments"] == {"k1": "CZ-2D", "k2": "CZ-2D"},
          daten["vehicle_assignments"])
    check("leere Zuweisung wird nicht gespeichert", "k3" not in daten["vehicle_assignments"])
    check("gelesen wie geschrieben",
          app.load_workspace()["vehicle_assignments"]["k1"] == "CZ-2D")
    app.save_workspace([], [], [], [])
    check("ohne Argument bleibt der Eintrag leer",
          app.load_workspace()["vehicle_assignments"] == {})
    alt_stand = {"manual_notams": [], "confirmed_launches": []}
    app.WORKSPACE_FILE.write_text(_json.dumps(alt_stand), encoding="utf-8")
    check("alter Arbeitsstand ohne das Feld bricht nicht",
          app.load_workspace().get("vehicle_assignments", {}) == {})
finally:
    app.WORKSPACE_FILE = echt_w
    _shutil.rmtree(tmp_w, ignore_errors=True)

print("== 71. Einbindung in die Oberflaeche ==")
quelle_tr = Path("app.py").read_text(encoding="utf-8")
check("Dropdown unter NOTAM Data",
      '_vehicle_picker(event, vehicles, group_keys, "data")' in quelle_tr)
check("Dropdown unter Unassigned / Review",
      '_vehicle_picker(event, vehicles, group_keys, "review")' in quelle_tr)
check("Launch Overview bleibt lesbar (kein data_editor)", "st.data_editor(" not in quelle_tr)
check("Klick-Sprung unveraendert erhalten",
      quelle_tr.count('on_select="rerun"') == 2, quelle_tr.count('on_select="rerun"'))
check("Zuweisungen werden vor den Tabellen angewandt",
      quelle_tr.index("apply_vehicle_assignments(") < quelle_tr.index("group_table = groups_to_dataframe"))
check("Auswahl wird sofort gesichert",
      "_persist_workspace()" in quelle_tr.split("def _set_vehicle")[1].split("def _vehicle_picker")[0])
check("Trennzeile schaltet nicht um",
      "if gewaehlt == VEHICLE_SEPARATOR:" in quelle_tr)

print("== 72. Payload als Freitext ==")
pe1, pe2, pe3 = _ev(1, "p1"), _ev(2, "p2"), _ev(9, "p9")
pg = app.LaunchGroup(group_id="START-01", row_indices=[1, 2])
pg2 = app.LaunchGroup(group_id="START-02", row_indices=[9])
app.apply_payload_assignments([pe1, pe2, pe3], [pg, pg2], {"p1": "Yaogan-XX"})
check("Eintrag gilt fuer alle Zonen des Starts",
      (pe1.payload, pe2.payload, pg.payload) == ("Yaogan-XX",) * 3,
      (pe1.payload, pe2.payload, pg.payload))
check("fremder Start bleibt leer", (pe3.payload, pg2.payload) == ("", ""))
app.apply_payload_assignments([pe1, pe2], [pg], {"p1": "Yaogan-XX", "p2": "Shijian-YY"})
check("Widerspruch: jede Zone behaelt ihren Text",
      (pe1.payload, pe2.payload) == ("Yaogan-XX", "Shijian-YY"))
check("Widerspruch: der Start ist uneinheitlich", pg.payload == app.MIXED_VALUE)
check("Traegersystem bleibt davon unberuehrt", pe1.vehicle == "" and pg.vehicle == "")

pe1.payload = "Yaogan-XX"
pg.payload = "Yaogan-XX"
check("Spalte in der NOTAM-Tabelle",
      app.events_to_dataframe([pe1])["Payload"].iloc[0] == "Yaogan-XX")
check("Spalte in der Start-Tabelle",
      app.groups_to_dataframe([pg])["Payload"].iloc[0] == "Yaogan-XX")
pe1.payload = ""
check("ohne Eintrag steht ein Strich",
      app.events_to_dataframe([pe1])["Payload"].iloc[0] == "-")
check("Payload steht direkt hinter dem Traegersystem",
      list(app.events_to_dataframe([pe1]).columns).index("Payload")
      - list(app.events_to_dataframe([pe1]).columns).index("Trägersystem") == 1)

tmp_p = Path(_tempfile.mkdtemp())
echt_p = app.WORKSPACE_FILE
try:
    app.WORKSPACE_FILE = tmp_p / "notam_workspace.json"
    app.save_workspace([], [], [], vehicle_assignments={"p1": "CZ-2D"},
                   payload_assignments={"p1": "Yaogan-XX", "p2": ""})
    daten_p = _json.loads(app.WORKSPACE_FILE.read_text(encoding="utf-8"))
    check("Payload steht in der Arbeitsdatei",
          daten_p["payload_assignments"] == {"p1": "Yaogan-XX"}, daten_p["payload_assignments"])
    check("Traegersystem steht unabhaengig daneben",
          daten_p["vehicle_assignments"] == {"p1": "CZ-2D"})
    check("gelesen wie geschrieben",
          app.load_workspace()["payload_assignments"]["p1"] == "Yaogan-XX")
    app.WORKSPACE_FILE.write_text(_json.dumps({"manual_notams": []}), encoding="utf-8")
    check("alter Arbeitsstand ohne das Feld bricht nicht",
          app.load_workspace().get("payload_assignments", {}) == {})
finally:
    app.WORKSPACE_FILE = echt_p
    _shutil.rmtree(tmp_p, ignore_errors=True)

quelle_p = Path("app.py").read_text(encoding="utf-8")
check("Feld nur unter NOTAM Data", quelle_p.count("_payload_field(") == 2)
check("Feld steht unter dem Traegersystem-Dropdown",
      quelle_p.index('_vehicle_picker(event, vehicles, group_keys, "data")')
      < quelle_p.index('_payload_field(event, group_keys, "data")'))
check("kein Payload-Feld im Review", '_payload_field(event, group_keys, "review")' not in quelle_p)
check("Eintrag wird sofort gesichert",
      "_persist_workspace()" in quelle_p.split("def _set_payload")[1].split("def _payload_field")[0])

print("== 73. Startarchiv: Zeile je Start ==")
from datetime import datetime as _dt
check("Spalten in genau der vereinbarten Reihenfolge",
      app.ARCHIVE_COLUMNS == ("NOTAM", "Startdatum", "Startzeit", "Nation",
                              "Weltraumbahnhof", "Trägersystem", "Payload",
                              "Orbit", "Inklination", "Azimuth", "Dropzones"),
      app.ARCHIVE_COLUMNS)
check("Orbit als Kurzform", app.orbit_short(app.ORBIT_SSO) == "SSO")
check("Orbit GTO", app.orbit_short(app.ORBIT_GTO) == "GTO")
check("Orbit unbestimmt", app.orbit_short(app.ORBIT_UNKNOWN) == "-")
check("unbekannter Orbit bleibt stehen", app.orbit_short("Sonderbahn") == "Sonderbahn")

def _zone(row, key, lat, lon):
    e = app.LaunchEvent(row_index=row, notam_id="A{:04d}/26".format(row), raw_text="x")
    e.key, e.centroid_lat, e.centroid_lon = key, lat, lon
    return e

z1, z2 = _zone(1, "a1", 19.6, 110.95), _zone(2, "a2", 18.8333, 111.25)
ag = app.LaunchGroup(group_id="START-01", row_indices=[1, 2])
ag.nation, ag.spaceport_code = "China", "JSLC"
ag.vehicle, ag.payload = "CZ-2D", "Yaogan-XX"
ag.orbit_type, ag.inclination_deg, ag.azimuth_deg = app.ORBIT_SSO, 97.44, 190.31
ag.window_from = _dt(2026, 9, 21, 1, 30)
row = app.archive_row(ag, [z1, z2])
check("beide Kennungen in einer Zeile", row["NOTAM"] == "A0001/26, A0002/26", row["NOTAM"])
check("Datum mit vierstelligem Jahr", row["Startdatum"] == "21.09.2026", row["Startdatum"])
check("Startzeit", row["Startzeit"] == "01:30")
check("Startplatz als Kuerzel", row["Weltraumbahnhof"] == "JSLC")
check("Traegersystem als Kuerzel", row["Trägersystem"] == "CZ-2D")
check("Payload uebernommen", row["Payload"] == "Yaogan-XX")
check("Orbit kurz", row["Orbit"] == "SSO")
check("Inklination auf eine Stelle", row["Inklination"] == "97.4", row["Inklination"])
check("Azimuth auf eine Stelle", row["Azimuth"] == "190.3", row["Azimuth"])
check("beide Dropzones in einem Feld",
      row["Dropzones"] == "19.6000 110.9500; 18.8333 111.2500", row["Dropzones"])

leer_g = app.LaunchGroup(group_id="START-02", row_indices=[])
leer_row = app.archive_row(leer_g, [])
check("Start ohne Daten bricht nicht",
      leer_row["Startdatum"] == "" and leer_row["Inklination"] == "")

print("== 74. Archiv wird fortgeschrieben, nicht verdoppelt ==")
check("Schluessel ist reihenfolgeunabhaengig",
      app.archive_key({"NOTAM": "B/26, A/26", "Startdatum": "21.09.2026",
                       "Weltraumbahnhof": "JSLC"})
      == app.archive_key({"NOTAM": "A/26 , b/26", "Startdatum": "21.09.2026",
                          "Weltraumbahnhof": "jslc"}))
check("anderes Datum ist ein anderer Start",
      app.archive_key({"NOTAM": "A/26", "Startdatum": "21.09.2026", "Weltraumbahnhof": "JSLC"})
      != app.archive_key({"NOTAM": "A/26", "Startdatum": "22.09.2026", "Weltraumbahnhof": "JSLC"}))

leer_df = app.pd.DataFrame(columns=list(app.ARCHIVE_COLUMNS))
erst = app.merge_archive(leer_df, [row])
check("erster Lauf legt die Zeile an", len(erst) == 1)
zweit = app.merge_archive(erst, [row])
check("zweiter Lauf verdoppelt nicht", len(zweit) == 1, len(zweit))

ag.payload = ""
ag.inclination_deg = 97.9
ohne = app.merge_archive(erst, [app.archive_row(ag, [z1, z2])])
check("nachgetragene Payload bleibt erhalten",
      ohne["Payload"].iloc[0] == "Yaogan-XX", ohne["Payload"].iloc[0])
check("automatische Spalten werden aktualisiert",
      ohne["Inklination"].iloc[0] == "97.9", ohne["Inklination"].iloc[0])

ag.payload = "Shijian-YY"
mit = app.merge_archive(erst, [app.archive_row(ag, [z1, z2])])
check("neue Payload ueberschreibt die alte", mit["Payload"].iloc[0] == "Shijian-YY")

ag.payload = "Yaogan-XX"
geloescht = app.merge_archive(leer_df, [row], {app.archive_key(row)})
check("geloeschte Zeile kommt nicht zurueck", geloescht.empty, len(geloescht))

ag2 = app.LaunchGroup(group_id="START-03", row_indices=[1, 2])
ag2.nation, ag2.spaceport_code = "China", "XSLC"
ag2.window_from = _dt(2026, 9, 22, 4, 0)
zwei = app.merge_archive(erst, [app.archive_row(ag2, [z1, z2])])
check("ein anderer Start kommt hinzu", len(zwei) == 2, len(zwei))
check("Reihenfolge bleibt stabil", zwei["Weltraumbahnhof"].tolist() == ["JSLC", "XSLC"])

print("== 75. Archivdatei lesen und schreiben ==")
tmp_a = Path(_tempfile.mkdtemp())
try:
    datei = tmp_a / "startarchiv_updated.csv"
    check("fehlende Datei ergibt ein leeres Archiv",
          app.load_archive(datei).empty and list(app.load_archive(datei).columns)
          == list(app.ARCHIVE_COLUMNS))
    app.persist_archive(datei, zwei)
    zurueck = app.load_archive(datei)
    check("gelesen wie geschrieben", len(zurueck) == 2)
    check("Spaltenreihenfolge in der Datei bleibt",
          list(zurueck.columns) == list(app.ARCHIVE_COLUMNS))
    check("Payload ueberlebt den Dateiweg", zurueck["Payload"].iloc[0] == "Yaogan-XX")
    (tmp_a / "halb.csv").write_text("NOTAM,Payload\nA/26,Yaogan\n", encoding="utf-8")
    halb = app.load_archive(tmp_a / "halb.csv")
    check("unvollstaendige Datei wird ergaenzt statt verworfen",
          len(halb) == 1 and halb["Weltraumbahnhof"].iloc[0] == "", halb.to_dict("records"))
finally:
    _shutil.rmtree(tmp_a, ignore_errors=True)

print("== 76. Einbindung des Archivs ==")
quelle_a = Path("app.py").read_text(encoding="utf-8")
check("eigener Pfad definiert", "ARCHIVE_CSV = APP_DIR" in quelle_a)
check("wird bei jeder Auswertung fortgeschrieben",
      "_update_archive(events, stats.get(\"groups\", []), table)" in quelle_a)
check("Filter der Seitenleiste wirken nicht aufs Archiv",
      quelle_a.index("_update_archive(events") < quelle_a.index("nation_filter = st.multiselect"))
check("eigener Reiter im Optionsmenue", "_archive_editor()" in quelle_a)
check("Statuszeile in der Seitenleiste", "Launch archive: {} launch(es)" in quelle_a)
check("Statuszeile zeigt den Stand nach der Auswertung",
      quelle_a.count("_show_archive_status(") == 3, quelle_a.count("_show_archive_status("))
check("Loeschungen werden im Arbeitsstand gemerkt",
      '"archiv_removed": sorted(archiv_removed)' in quelle_a)
check("kein Anlege-Formular fuers Archiv", 'st.form("add_archive"' not in quelle_a)

tmp_w2 = Path(_tempfile.mkdtemp())
echt_w2 = app.WORKSPACE_FILE
try:
    app.WORKSPACE_FILE = tmp_w2 / "w.json"
    app.save_workspace([], [], [], archiv_removed=["k-a", "k-b"])
    check("geloeschte Archivzeilen ueberleben den Neustart",
          app.load_workspace()["archiv_removed"] == ["k-a", "k-b"])
finally:
    app.WORKSPACE_FILE = echt_w2
    _shutil.rmtree(tmp_w2, ignore_errors=True)

print("== 77. Anzeigesprache und Tabellenformat ==")
gt = app.groups_to_dataframe([pg])
cfg = app.table_config(gt)
check("jede sichtbare Spalte bekommt eine Konfiguration",
      set(cfg) == {c for c in gt.columns if not c.startswith("_")})
check("Zahlenspalten bekommen ein Format",
      app.COLUMN_FORMATS["Launch Azimut (°)"] == "%.1f°")
check("Entfernungen ohne Nachkommastellen", app.COLUMN_FORMATS["Reichweite (km)"] == "%.0f km")
check("Spaltenschluessel bleiben deutsch - sie sind ueberall verdrahtet",
      "Startnation" in gt.columns and "Nation" not in gt.columns)
check("uebersetzt wird nur das Label",
      app.COLUMN_LABELS["Startnation"] == "Nation"
      and app.COLUMN_LABELS["Weltraumbahnhof"] == "Launch Site"
      and app.COLUMN_LABELS["Zuverlässigkeit"] == "Reliability")
check("alle sichtbaren Spalten haben eine Uebersetzung",
      [c for c in gt.columns if not c.startswith("_") and c not in app.COLUMN_LABELS] == [],
      [c for c in gt.columns if not c.startswith("_") and c not in app.COLUMN_LABELS])
et = app.events_to_dataframe([pe1])
check("auch auf NOTAM-Ebene vollstaendig",
      [c for c in et.columns if not c.startswith("_") and c not in app.COLUMN_LABELS] == [],
      [c for c in et.columns if not c.startswith("_") and c not in app.COLUMN_LABELS])

ordnung = app.visible_order(gt, app.GROUP_COLUMN_ORDER)
check("interne Spalten bleiben aussen vor", not any(c.startswith("_") for c in ordnung))
check("keine Spalte geht verloren",
      set(ordnung) == {c for c in gt.columns if not c.startswith("_")})
check("Vehicle und Payload stehen weit vorn",
      ordnung.index("Trägersystem") < 5 and ordnung.index("Payload") < 6,
      (ordnung.index("Trägersystem"), ordnung.index("Payload")))
check("vor dem Azimut - vorher lagen sie dahinter",
      ordnung.index("Payload") < ordnung.index("Launch Azimut (°)"))
check("unbekannte Spalten fallen hinten an, statt zu verschwinden",
      app.visible_order(gt, ("Start",))[0] == "Start"
      and len(app.visible_order(gt, ("Start",))) == len(ordnung))

quelle_ui = Path("app.py").read_text(encoding="utf-8")
uebersicht = quelle_ui.split("if bereich == reiter[0]:")[1].split("if bereich == reiter[1]:")[0]
check("Launch Overview nutzt column_config", uebersicht.count("column_config=table_config(") == 2)
check("Launch Overview nutzt column_order", uebersicht.count("column_order=visible_order(") == 2)
check("Kennzahlen englisch und kurz",
      all(w in uebersicht for w in ('"Launches"', '"Drop Zones"', '"Nations"', '"Verified"')))
check("kein Emoji mehr in den Kennzahlen", "{} Geprüft" not in uebersicht)
check("Klick-Sprung unveraendert", uebersicht.count('on_select="rerun"') == 2)

print("== 78. Einheitliche Sprache und Symbolvokabular ==")
quelle_l = Path("app.py").read_text(encoding="utf-8")
check("keine Piktogramme mehr im Code",
      not __import__("re").search(
          r'[\U0001F300-\U0001FAFF⬀-⯿←-⇿☀-➿️]',
          quelle_l))
check("Theme-Datei vorhanden", Path(".streamlit/config.toml").exists())
theme = Path(".streamlit/config.toml").read_text(encoding="utf-8")
for name, wert in (("backgroundColor", "#141414"), ("secondaryBackgroundColor", "#1E1E1E"),
                   ("borderColor", "#757575"), ("primaryColor", "#ADAFAF")):
    check("  unbunter Ton {}".format(name), '{} = "{}"'.format(name, wert) in theme)
check("Bearbeiten-Knopf als Strichsymbol", 'icon=":material/edit:"' in quelle_l)
check("  ... ohne Rahmen", 'type="tertiary"' in quelle_l)

check("Stufenwerte englisch",
      app.CONFIDENCE_LEVELS == ("HIGH", "MEDIUM", "LOW"), app.CONFIDENCE_LEVELS)
check("Art englisch", (app.KIND_LAUNCH, app.KIND_REENTRY) == ("Launch", "Re-entry"))
check("Quelle englisch", (app.SOURCE_IMPORT, app.SOURCE_MANUAL) == ("Import", "Pasted"))
check("Zuverlaessigkeit englisch",
      (app.RELIABILITY_HIGH, app.RELIABILITY_MEDIUM, app.RELIABILITY_LOW)
      == ("high", "medium", "low"))

check("Nationen bleiben intern deutsch - Vertrag mit der FIR-Referenz",
      "Russland" in app.TARGET_NATIONS and "Russia" not in app.TARGET_NATIONS)
check("  ... und werden nur zur Anzeige uebersetzt",
      (app.nation_label("Russland"), app.nation_label("Nordkorea"), app.nation_label("China"))
      == ("Russia", "North Korea", "China"))
check("  ... in der Tabelle",
      app.groups_to_dataframe([ag])["Startnation"].iloc[0] == "China")
check("  ... und im Archiv", app.archive_row(ag, [z1, z2])["Nation"] == "China")
ru = app.LaunchGroup(group_id="START-09", row_indices=[])
ru.nation = "Russland"
check("  ... auch fuer Russland", app.archive_row(ru, [])["Nation"] == "Russia")
check("unbekannte Nation bleibt unveraendert", app.nation_label("Norwegen") == "Norwegen")
check("leere Nation ergibt leeren Text", app.nation_label(None) == "")

print("== 79. FIR-Zuordnung verzweigt auf Marken, nicht auf Prosa ==")
check("Marken sind kurz und sprachfrei",
      (app.FIR_BY_ICAO, app.FIR_TOO_FAR, app.FIR_OUTSIDE) == ("icao", "too_far", "outside"))
check("Anzeigetext steht getrennt", app.fir_method_label(app.FIR_BY_ICAO) == "ICAO code")
check("  ... mit Detail", "1969 km" in app.fir_method_label(app.FIR_TOO_FAR, "1969 km"))
check("Verzweigung nutzt die Marke",
      "method.startswith(FIR_TOO_FAR)" in quelle_l
      and "method.startswith(FIR_OUTSIDE)" in quelle_l)
check("keine Verzweigung auf uebersetzbaren Text",
      'startswith("Zu weit")' not in quelle_l and 'startswith("Ausserhalb")' not in quelle_l)
navarea_fir = app._find_fir("", None, fir, (-59.0, 165.0))[1]
check("weit entfernte Zone liefert die Marke",
      navarea_fir.startswith(app.FIR_TOO_FAR), navarea_fir)

def _em_dashes_in_ui():
    """Gedankenstriche in sichtbaren Zeichenketten - Docstrings zaehlen nicht."""
    import ast as _ast
    quelle = Path("app.py").read_text(encoding="utf-8")
    baum = _ast.parse(quelle)
    doc = set()
    for n in _ast.walk(baum):
        if isinstance(n, (_ast.FunctionDef, _ast.ClassDef, _ast.Module)):
            d = _ast.get_docstring(n, clean=False)
            if d and n.body and isinstance(n.body[0], _ast.Expr):
                for ln in range(n.body[0].lineno, (n.body[0].end_lineno or 0) + 1):
                    doc.add(ln)
    # Die Normalisierungstabelle wandelt Gedankenstriche aus NOTAM-Texten in
    # Bindestriche um - das ist Parsing, keine Oberflaeche.
    return [n.value[:60] for n in _ast.walk(baum)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)
            and n.lineno not in doc and "\u2014" in n.value and len(n.value) > 2]


print("== 80. Wortmarke und Gestaltungsregeln ==")
kopf = app.HEADER_HTML
stil = app.STYLE_HTML.format(
    grotesk=app.FONT_GROTESK, humanist=app.FONT_HUMANIST, leading=app.LEADING_REM,
    weiss=app.INK_WHITE, silber=app.INK_SILVER, coolgray=app.INK_COOLGRAY,
    anthrazit=app.INK_ANTHRACITE)

print("-- Logoaufbau --")
check("Akronym steht in der ersten Zeile", ">NOLA<" in kopf)
check("Langform steht darunter", kopf.index("Notam") > kopf.index(">NOLA<"))
check("keine Wortzwischenraeume in der Langform",
      "Notam Launch" not in kopf and "Launch Analyzer" not in kopf, kopf)
check("Versalbuchstaben trennen die Woerter, nicht Leerzeichen",
      "Notam<span" in kopf and "</span>Analyzer." in kopf,
      kopf[kopf.index("nola-lang"):][:120])
check("Schlusspunkt auf der zweiten Zeile",
      "Analyzer.</div>" in kopf.replace("\n", ""), kopf)
check("Reiterbeschriftung ist das Akronym", 'page_title="NOLA"' in quelle_l)
check("kein Farbverlauf mehr im Schriftzug",
      "linear-gradient" not in stil and "NEON" not in quelle_l)
check("Farbdifferenzierung der Wortteile bleibt unbunt",
      app.INK_SILVER == "#9A9B9C" and app.INK_COOLGRAY == "#ADAFAF")
check("  ... und das Akronym steht in Weiss", app.INK_WHITE == "#FFFFFF")

print("-- Typografie --")
check("Grotesk fuer Wortmarke und Ueberschriften",
      "Helvetica" in app.FONT_GROTESK and "h1, h2, h3" in stil)
check("humanistische Grotesk fuer den Mengensatz", "Myriad" in app.FONT_HUMANIST)
check("beide Stapel enden bei der Ersatzschrift",
      app.FONT_GROTESK.endswith("sans-serif") and "Arial" in app.FONT_GROTESK
      and "Arial" in app.FONT_HUMANIST)
check("keine Webschrift wird geladen", "@font-face" not in stil and "fonts.googleapis" not in stil)
check("Ligatur-Icons behalten ihre Schrift",
      'Material Symbols Rounded" !important' in stil
      and '[data-testid="stIconMaterial"]' in stil)
check("Durchschuss wiederholt sich",
      stil.count("var(--nola-durchschuss)") >= 2, stil.count("var(--nola-durchschuss)"))

print("-- Unbunte Buehne --")
theme = Path(".streamlit/config.toml").read_text(encoding="utf-8")
for name, wert in (("backgroundColor", "#141414"), ("secondaryBackgroundColor", "#1E1E1E"),
                   ("borderColor", "#757575"), ("textColor", "#F2F2F2"),
                   ("primaryColor", "#ADAFAF")):
    check("  unbunter Ton {}".format(name), '{} = "{}"'.format(name, wert) in theme)
def _kontrast(fg, bg):
    def lin(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    def lum(h):
        h = h.lstrip("#")
        return 0.2126*lin(h[0:2]) + 0.7152*lin(h[2:4]) + 0.0722*lin(h[4:6])
    a, b = lum(fg), lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)
check("Text erreicht 4,5:1", _kontrast("#F2F2F2", "#141414") >= 4.5,
      round(_kontrast("#F2F2F2", "#141414"), 2))
check("Rahmen erreicht 3:1 - vorher waren es 1,55:1",
      _kontrast("#757575", "#141414") >= 3.0, round(_kontrast("#757575", "#141414"), 2))
check("gedaempfter Text erreicht 4,5:1", _kontrast("#ADAFAF", "#141414") >= 4.5,
      round(_kontrast("#ADAFAF", "#141414"), 2))

print("-- Verbotene Muster --")
check("keine Piktogramme", not __import__("re").search(
    r'[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]', quelle_l))
check("keine Einblend- oder Hover-Effekte",
      not __import__("re").search(r'@keyframes|transition:|:hover', stil))
check("keine Gedankenstriche in sichtbaren Texten", _em_dashes_in_ui() == [], _em_dashes_in_ui())
check("keine deutschen Schaltflaechen mehr", '"Entfernen"' not in quelle_l)

print("-- Deckende Flaechen --")
# Entscheidung des Benutzers: kein Glasmorphismus. Ueber einer fast schwarzen
# Buehne war der Effekt nur ein hellerer Kasten, und auf dem Optionsmenue
# verdeckte dieses ohnehin fast das ganze Fenster.
check("keine Weichzeichnung", "backdrop-filter" not in stil)
check("keine halbdurchsichtigen Flaechen", "rgba" not in stil)
check("keine Eingriffe in Streamlits eigene Flaechen",
      "stDialog" not in stil and "stHeader" not in stil and "stSidebar" not in stil)
check("kein !important ausser fuer die Icon-Schrift",
      stil.count("!important") == 1)
check("die Auswahl stuetzt sich nicht auf erzeugte Klassennamen",
      "st-emotion-cache" not in stil)

print("== 81. Automatisches Ausblenden ==")
check("Ausschlussbegriffe kommen als Liste",
      app.exclusion_hits("AREA CLSD FOR BALLOON AND ADS-B TEST") == ["BALLOON", "ADS-B"],
      app.exclusion_hits("AREA CLSD FOR BALLOON AND ADS-B TEST"))
check("ohne Treffer leere Liste", app.exclusion_hits("SPACE LAUNCH DEBRIS AREA") == [])
check("leerer Text bricht nicht", app.exclusion_hits(None) == [])

check("LOW + Ausschlussbegriff blendet aus",
      app.auto_hide_reason("LOW", "BALLOON RELEASE").startswith("Low confidence"))
check("  ... und nennt den Begriff", "BALLOON" in app.auto_hide_reason("LOW", "BALLOON RELEASE"))
check("LOW ohne Ausschlussbegriff bleibt im Review",
      app.auto_hide_reason("LOW", "DANGER AREA ACTIVATED") == "")
check("MEDIUM mit Ausschlussbegriff bleibt - die Konfidenz ist die Bremse",
      app.auto_hide_reason("MEDIUM", "BALLOON RELEASE") == "")
check("HIGH mit Ausschlussbegriff bleibt erst recht",
      app.auto_hide_reason("HIGH", "BALLOON RELEASE") == "")

# Ein echtes Start-NOTAM mit zufaelligem Ausschlussbegriff darf nicht fallen.
echt = """A9999/26 NOTAMN
Q) ZLHW/QRTCA/IV/BO/W/000/999/3950N11625E099
A) ZLHW B) 2609210130 C) 2609210430
E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH. FALLING DEBRIS.
   WEATHER BALLOON ACTIVITY IN THE VICINITY.
   AREA 3936N11057E 3948N11212E 3902N11230E
F) SFC G) UNL"""
score_e, level_e, _ = app.score_confidence(
    echt, app.detect_triggers(echt, app.extract_items(echt)), app.extract_items(echt))
check("echtes Start-NOTAM mit BALLOON im Text erreicht nicht LOW",
      level_e != "LOW", (score_e, level_e))
check("  ... und wird deshalb nicht ausgeblendet",
      app.auto_hide_reason(level_e, echt) == "")

ev_h, st_h = app.analyze_notams(
    app.manual_entries_to_dataframe(
        [{"text": echt, "added": "x"},
         {"text": "B1111/26 NOTAMN\nQ) EGTT/QWLLW/IV/BO/W/000/999/5130N00010W005\n"
                  "A) EGTT B) 2609210130 C) 2609210430\n"
                  "E) LASER DISPLAY AND BALLOON RELEASE. RESTRICTED AREA.\nF) SFC G) UNL",
          "added": "x"}],
        "NOTAM Text"),
    sp, fir, min_confidence="MEDIUM")
markiert = [e for e in ev_h if e.auto_hidden_reason]
check("in der Auswertung wird genau das Laser-NOTAM markiert",
      len(markiert) == 1 and markiert[0].notam_id.startswith("B1111"),
      [(e.notam_id, bool(e.auto_hidden_reason)) for e in ev_h])

print("== 82. Zurueckholen gewinnt dauerhaft ==")
quelle_h = Path("app.py").read_text(encoding="utf-8")
check("Zurueckholen merkt sich den Schluessel",
      'st.session_state.setdefault("restored_events", set()).add(key)'
      in quelle_h.split("def _unhide_event")[1].split("def _unhide_all")[0])
check("  ... auch beim Zurueckholen aller",
      "def _unhide_all" in quelle_h and 'st.session_state["hidden_events"].clear()'
      in quelle_h.split("def _unhide_all")[1].split("def ")[0])
check("zurueckgeholte NOTAMs werden von der Regel uebergangen",
      "e.auto_hidden_reason and e.key not in zurueckgeholt" in quelle_h)
check("Regel greift erst in der Oberflaeche, nicht in der Auswertung",
      "auto_hidden_keys" in quelle_h and "auto_hidden_keys" not in
      quelle_h.split("def analyze_notams")[1].split("def events_to_dataframe")[0])
check("Excluded weist Urheber aus", '"Excluded by"' in quelle_h)
check("  ... und die Begruendung", "e.auto_hidden_reason if e.key in auto_hidden_keys" in quelle_h)

tmp_h = Path(_tempfile.mkdtemp()); echt_h = app.WORKSPACE_FILE
try:
    app.WORKSPACE_FILE = tmp_h / "w.json"
    app.save_workspace([], [], [], restored=["key-x"])
    check("zurueckgeholte NOTAMs ueberleben den Neustart",
          app.load_workspace()["restored_events"] == ["key-x"])
    app.WORKSPACE_FILE.write_text(_json.dumps({"manual_notams": []}), encoding="utf-8")
    check("alter Arbeitsstand ohne das Feld bricht nicht",
          app.load_workspace().get("restored_events", []) == [])
finally:
    app.WORKSPACE_FILE = echt_h
    _shutil.rmtree(tmp_h, ignore_errors=True)

print("== 83. Befunde der Fremdpruefung vom 25.09.2026 ==")

print("-- Befund 1: Stichwoerter treffen nur als ganzes Wort --")
falsch_positiv = [
    ("SMART DRAGON 3 CARRIER ROCKET LAUNCH", "chinesischer Traeger, nicht SpaceX Dragon"),
    ("AREA CLSD NEAR SHARJAH INTL", "Flughafen, nicht Sriharikota"),
    ("CASCADE VALLEY DANGER AREA ACT", "Tal, nicht CASC"),
    ("NASAL SPRAY TEST", "nicht NASA"),
    ("INDIAN OCEAN DANGER AREA", "Ozean, nicht Indien"),
]
for txt, warum in falsch_positiv:
    nation, belege = app.detect_nation_hint(txt)
    check("kein Treffer: {}".format(warum), nation is None, (txt, nation, belege))
check("LAS VEGAS ist kein Fremdbetreiber",
      app.detect_foreign_operator("LAS VEGAS TFR") == [],
      app.detect_foreign_operator("LAS VEGAS TFR"))

richtig_positiv = [
    ("SPACE LAUNCH FROM JIUQUAN", "China"),
    ("CZ-2D LAUNCH DEBRIS", "China"),
    ("FALCON 9 STARLINK FROM VANDENBERG", "USA"),
    ("PSLV LAUNCH FROM SDSC", "Indien"),
    ("NASA ARTEMIS LAUNCH", "USA"),
    ("CREW DRAGON DOCKING", "USA"),
    ("SOYUZ LAUNCH FROM PLESETSK", "Russland"),
]
for txt, erwartet in richtig_positiv:
    check("weiterhin erkannt: {}".format(txt[:34]),
          app.detect_nation_hint(txt)[0] == erwartet,
          (txt, app.detect_nation_hint(txt)))
check("Fremdbetreiber weiterhin erkannt",
      "VEGA" in app.detect_foreign_operator("VEGA C LAUNCH FROM KOUROU"))
check("Praefix-Begriffe behalten ihre Wirkung",
      app.detect_nation_hint("CZ-5B CORE STAGE REENTRY")[0] == "China")

print("-- Befund 4: Daueranordnung ist keine Startankuendigung --")
from datetime import datetime as _dtb, timezone as _tzb
def _zeit(h):
    return (_dtb(2026, 8, 17, 7, 9, tzinfo=_tzb.utc),
            _dtb(2026, 8, 17, 7, 9, tzinfo=_tzb.utc) + __import__("datetime").timedelta(hours=h))

dauer_txt = ("ALL VFR ACFT ARE REQUESTED TO AVOID FLYING IN FOLLOWING AIRSPACE DUE TO "
             "THE ANTIBALLISTIC MISSILES MAY BE LAUNCHED FOR THE DESTRUCTION OF AN "
             "OBJECT PROPELLED BY ROCKET LAUNCHED FROM NORTH KOREA")
von, bis = _zeit(2192)
sc, lvl, notes = app.score_confidence(dauer_txt, ["Keyword: ROCKET"], {}, von, bis)
check("91 Tage ohne Tagesfenster -> LOW", lvl == "LOW", (sc, lvl))
check("  ... mit sprechender Begruendung",
      any("Daueranordnung" in n for n in notes), notes)
check("  ... der Score bleibt sichtbar, nur die Stufe faellt", sc >= 3, sc)
check("  ... ohne Deckel waere es nicht LOW",
      app.score_confidence(dauer_txt, ["Keyword: ROCKET"], {}, None, None)[1] != "LOW",
      app.score_confidence(dauer_txt, ["Keyword: ROCKET"], {}, None, None))

von, bis = _zeit(216)
check("216 h ohne Tagesfenster bleiben unberuehrt (NAVAREA-Startwarnung)",
      app.score_confidence(dauer_txt, ["Keyword: ROCKET"], {}, von, bis)[1] != "LOW")
von, bis = _zeit(2192)
check("lange Laufzeit MIT Tagesfenster bleibt unberuehrt",
      app.score_confidence(dauer_txt, ["Keyword: ROCKET"], {"D": "DAILY 1200-1400"},
                           von, bis)[1] != "LOW")
check("Grenze ist an Messwerten gewaehlt", app.STANDING_ORDER_HOURS == 720.0)

print("-- Befund 2: die ausgewiesene Streuung ist die wahre --")
# Eigener Lauf statt der Ergebnisse aus Abschnitt 37: die Kopplung ueber
# 700 Zeilen hinweg ist schwer nachvollziehbar und war selbst schon Ursache
# eines irrefuehrenden Fehlschlags.
if xls:
    ev_r2, st_r2 = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
per_r = {e.row_index: e for e in ev_r2} if xls else {}
if xls:
    abweichung = []
    for g in st_r2["groups"]:
        if not g.spaceport_code: continue
        az = [per_r[r].azimuth_deg for r in g.row_indices
              if per_r.get(r) and per_r[r].azimuth_deg is not None]
        if len(az) < 2: continue
        echt = app._angular_spread(az)
        if abs(echt - g.azimuth_spread_deg) > 0.05:
            abweichung.append((g.group_id, g.azimuth_spread_deg, echt))
    check("gemeldete Streuung deckt sich mit der gerechneten", abweichung == [], abweichung)
    weit = [g for g in st_r2["groups"] if g.spaceport_code and g.azimuth_spread_deg > 60]
    check("  ... und weit gestreute Gruppen werden als solche sichtbar",
          weit != [] and all(g.reliability == app.RELIABILITY_LOW for g in weit),
          [(g.group_id, round(g.azimuth_spread_deg, 1), g.reliability) for g in weit])
    for g in weit:
        text = app.describe_launch(g, ev_r2)
        check("  ... der Klartext behauptet keine gemeinsame Richtung",
              "lie in the same direction" not in text, text[:160])
        check("  ... sondern weist den Mittelwert als bedeutungsarm aus",
              "without much meaning" in text)

print("-- Befund 4b: keine sich selbst widersprechenden Begruendungen --")
lang = app.LaunchGroup(group_id="START-99", row_indices=[1])
lang.nation, lang.spaceport_code, lang.spaceport_name = "Nordkorea", "KSS", "Sohae"
lang.kind, lang.reliability = app.KIND_LAUNCH, app.RELIABILITY_LOW
e_lang = app.LaunchEvent(row_index=1, notam_id="P0000/26", raw_text="ROCKET LAUNCH AREA")
e_lang.valid_from, e_lang.valid_to = _zeit(2192)
lang.window_from, lang.window_to = e_lang.valid_from, e_lang.valid_to
txt_lang = app.describe_launch(lang, [e_lang])
check("91 Tage werden nicht als 'kurze Zeit' verkauft",
      "for that short a time" not in txt_lang, txt_lang[:200])
check("  ... sondern als lang benannt", "long for a launch window" in txt_lang)

print("-- Befund 8: US-Bezirkszentralen und Textbeleg --")
check("ARTCC-Kennung wird als Luftraum erkannt",
      app._luftraum_kennungen("!FDC 6/2736 ZLC AIRSPACE") == ["ZLC"],
      app._luftraum_kennungen("!FDC 6/2736 ZLC AIRSPACE"))
check("  ... vierstellige ICAO weiterhin auch",
      "ZLHW" in app._luftraum_kennungen("A) ZLHW B) 2609210130"))
check("  ... beliebige Dreibuchstaben-Woerter nicht",
      app._luftraum_kennungen("ACT SFC UNL GND NOT AND FIR") == [],
      app._luftraum_kennungen("ACT SFC UNL GND NOT AND FIR"))
# RE_ICAO trifft im Freitext jedes vierbuchstabige Wort ("ZONE", "AREA") -
# das war immer so und ist harmlos, weil nur Treffer zaehlen, die auch in der
# FIR-Referenz stehen. Tragend ist, dass das neue ARTCC-Muster nicht jedes
# dreibuchstabige Wort dazunimmt.
check("  ... ARTCC-Muster bleibt auf Z plus zwei Buchstaben beschraenkt",
      app.RE_ARTCC.findall("ZONE ACT SFC AND NOT ZLA") == ["ZLA"],
      app.RE_ARTCC.findall("ZONE ACT SFC AND NOT ZLA"))
check("  ... und keiner dieser Treffer steht in der FIR-Referenz",
      not ({"ZONE", "AREA"} & set(fir["ICAO Code"].astype(str))))
artcc = [c for c in fir["ICAO Code"].astype(str) if len(c) == 3]
check("die 21 ARTCC-Zeilen der Referenz sind erreichbar",
      artcc != [] and all(app._luftraum_kennungen(c) == [c] for c in artcc),
      [c for c in artcc if app._luftraum_kennungen(c) != [c]])

vandenberg = """W1234/26 NOTAMN
Q) KVBG/QRDCA/IV/BO/W/000/999/3444N12034W020
A) KVBG B) 2609210130 C) 2609210430
E) SPACE LAUNCH FROM VANDENBERG. FALCON 9 STARLINK. DEBRIS AREA
   3400N12100W 3330N12200W 3300N12130W
F) SFC G) UNL"""
ev_vb, _ = app.analyze_notams(pd.DataFrame({"NOTAM Text": [vandenberg]}), sp, fir,
                              min_confidence="MEDIUM")
check("Flugplatzkennung blockiert den Textbeleg nicht mehr",
      ev_vb[0].status == "OK" and ev_vb[0].nation == "USA",
      (ev_vb[0].status, ev_vb[0].nation, ev_vb[0].review_reason[:60]))
check("  ... und der Startplatz wird gefunden", ev_vb[0].spaceport_code == "KVBG",
      ev_vb[0].spaceport_code)

# Gegenprobe: ohne Textbeleg bleibt eine fremde FIR im Review.
ohne_beleg = vandenberg.replace(
    "SPACE LAUNCH FROM VANDENBERG. FALCON 9 STARLINK.", "DANGER AREA ACTIVATED.")
ev_ob, _ = app.analyze_notams(pd.DataFrame({"NOTAM Text": [ohne_beleg]}), sp, fir,
                              min_confidence="MEDIUM")
check("  ... ohne Beleg bleibt es im Review",
      ev_ob[0].status == "REVIEW", (ev_ob[0].status, ev_ob[0].nation))
check("  ... das ist die Drittstaaten-Regel, nicht ihr Wegfall",
      ev_ob[0].nation is None, ev_ob[0].nation)

print("-- Befund 3: eine geratene FIR belegt keinen eigenen Luftraum --")
nicaragua = """MANUELL NOTAM
Q) /QRDCA/IV/BO/W/000/999/
E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH. FALLING DEBRIS.
   AREA BOUNDED BY 1300N08400W 1330N08330W 1230N08330W
F) SFC G) UNL"""
ev_ni, _ = app.analyze_notams(pd.DataFrame({"NOTAM Text": [nicaragua]}), sp, fir,
                              min_confidence="MEDIUM")
e_ni = ev_ni[0]
check("Zone ueber Nicaragua wird kein US-Start",
      e_ni.status == "REVIEW" and e_ni.nation is None,
      (e_ni.status, e_ni.nation, e_ni.spaceport_code))
check("  ... die Konfidenz bleibt hoch - es scheitert an der Zuordnung, nicht am Score",
      e_ni.confidence_level == "HIGH", e_ni.confidence_level)
check("  ... und die Begruendung nennt den Abstand",
      "nearest reference point" in e_ni.review_reason and "km" in e_ni.review_reason,
      e_ni.review_reason[:90])
check("  ... es bleibt ueber die Gruppe aufloesbar", e_ni.requires_group)
check("die Schwelle liegt zwischen Echtfall und Fehlfall",
      541 < app.FIR_OWN_AIRSPACE_KM < 1460, app.FIR_OWN_AIRSPACE_KM)
check("  ... und unter der Grenze, ab der ueberhaupt eine FIR gefunden wird",
      app.FIR_OWN_AIRSPACE_KM < app.MAX_FIR_FALLBACK_KM)
nah = """MANUELL NOTAM
E) ROCKET LAUNCH DEBRIS AREA 1936N11057E SFC/UNL"""
ev_nah, _ = app.analyze_notams(pd.DataFrame({"NOTAM Text": [nah]}), sp, fir,
                               min_confidence="MEDIUM")
check("eine nahe geratene FIR traegt weiterhin (213 km, Suedchinesisches Meer)",
      ev_nah[0].status == "OK" and ev_nah[0].nation == "China",
      (ev_nah[0].status, ev_nah[0].nation, ev_nah[0].fir_code))
check("  ... und die FIR wird im Fernfall trotzdem noch angezeigt",
      e_ni.fir_code is not None, e_ni.fir_code)

# Mit Textbeleg darf dieselbe Zone durchgehen - das ist die Regel des Massstabs.
mit_beleg = nicaragua.replace("FALLING DEBRIS.", "FALLING DEBRIS. FALCON 9 STARLINK.")
ev_mb, _ = app.analyze_notams(pd.DataFrame({"NOTAM Text": [mit_beleg]}), sp, fir,
                              min_confidence="MEDIUM")
check("  ... mit Nennung im Text dagegen schon",
      ev_mb[0].status == "OK" and ev_mb[0].nation == "USA",
      (ev_mb[0].status, ev_mb[0].nation))

if xls:
    ev_g, st_g = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    geo_ok = [e for e in ev_g if e.fir_match_method == app.FIR_BY_GEOMETRY
              and e.status == "OK" and not e.manual_override]
    check("kein Start im Echtbestand beruht allein auf einer geratenen FIR",
          geo_ok == [], [(e.notam_id, e.fir_code, e.nation) for e in geo_ok])
    check("  ... und die Starts bleiben vollzaehlig",
          len([g for g in st_g["groups"] if g.spaceport_code]) >= 8,
          len([g for g in st_g["groups"] if g.spaceport_code]))

print("== 84. Seestarts von beweglichen Plattformen ==")
# Realer Fall: chinesischer Start aus dem Ostchinesischen Meer am 22.07.2026.
# Fuenf NOTAMs aus drei Luftraumregionen; der Startpunkt steht als kleiner
# Kreis in chinesischer FIR, die Dropzones liegen in taiwanesischem und
# japanischem Luftraum.
SEE = {
"TW-A2371": """A2371/26 NOTAMN
Q) RCAA/QRALW/IV/NBO/W/000/999/2814N12349E024
A) RCAA
B) 2607210200 C) 2607270600
D) 0200-0600
E) AIRSPACE BLOCKED DUE TO AEROSPACE FLIGHT ACTIVITY:
3.AREA AS FLW:
2836N12400E
2753N12400E
2752N12339E
2835N12337E
F) SFC G) UNL""",
"JP-P3423": """P3423/26 NOTAMN
Q)RJJJ/QXXXX/IV/NBO/E/000/999/2125N12408E029
A)RJJJ B)2607210200 C)2607270600
D)0200/0600
E)DUE TO AN AEROSPACE FLIGHT ACTIVITY, THE FLIGHT SAFETY OF THE
AIRCRAFT IN FOLLOWING AREA MAY BE AFFECTED THRU JUL 21-27 2026
AREA:
2151N12417E - 2150N12354E - 2100N12354E - 2100N12422E
F)SFC G)UNL""",
"TW-A2385": """A2385/26 NOTAMN
Q) RCAA/QRALW/IV/NBO/W/000/999/2814N12349E025
A) RCAA
B) 2607220245 C) 2607220312
E) AIRSPACE BLOCKED DUE TO AEROSPACE FLIGHT ACTIVITY:
3.AREA AS FLW:
2835N12337E
2836N12400E
2752N12400E
2751N12339E
F) SFC G) UNL""",
"CN-A2827": """A2827/26 NOTAMN
Q)ZSHA/QRDCA/IV/BO/W/000/999/3112N12342E011
A)ZSHA B)2607220244 C)2607220309
E) A TEMPORARY DANGER AREA ESTABLISHED,THE AREA WITHIN A CIRCLE
CENTERED AT N311200E1234200 WITH RADIUS OF 20KM.
VERTICAL LIMITS:SFC-UNL.
F)SFC G)UNL""",
"JP-P3438": """P3438/26 NOTAMN
Q)RJJJ/QXXXX/IV/NBO/E/000/999/2448N12408E228
A)RJJJ B)2607220245 C)2607220321
E)DUE TO AN AEROSPACE FLIGHT ACTIVITY ON JUL 22 2026,0245-0321
AREA1:0245-0312
2836N12402E - 2836N12400E - 2752N12400E - 2752N12404E
FOUR-POINT CONNECTION RANGE
AREA2:0246-0321
2151N12418E - 2150N12354E - 2100N12355E - 2100N12420E
FOUR-POINT CONNECTION RANGE
F)SFC G)UNL""",
}

print("-- Mehrgebiets-NOTAMs werden getrennt --")
z_jp = app.extract_zones(app.extract_items(SEE["JP-P3438"])["E"])
check("AREA1/AREA2 ergeben zwei Zonen", len(z_jp) == 2, len(z_jp))
mitten = [app.polygon_centroid(z) for z in z_jp]
check("  ... mit Mittelpunkten 740 km auseinander",
      app.surface_distance_km(mitten[0][0], mitten[0][1], mitten[1][0], mitten[1][1]) > 700,
      round(app.surface_distance_km(mitten[0][0], mitten[0][1], mitten[1][0], mitten[1][1])))
check("  ... und keiner davon ist der frühere Phantompunkt",
      all(abs(m[0] - 21.904) > 0.1 for m in mitten), mitten)
for text in ("DEBRIS AREA 1936N11057E 1948N11212E 1902N11230E",
             "TEMPORARY RESTRICTED AREA 2836N12400E 2753N12400E 2752N12339E"):
    check("  ... 'AREA <Koordinate>' wird weiterhin nicht getrennt: {}".format(text[:28]),
          len(app.extract_zones(text)) == 1, len(app.extract_zones(text)))

print("-- Der Startpunkt wird aus der Geometrie abgeleitet --")
df_see = app.manual_entries_to_dataframe(
    [{"text": t, "added": "x"} for t in SEE.values()], "NOTAM Text")
ev_see, st_see = app.analyze_notams(df_see, sp, fir, min_confidence="MEDIUM")
by_see = dict(zip(SEE, ev_see))
g_see = [g for g in st_see["groups"] if g.spaceport_code]
check("genau ein Start erkannt", len(g_see) == 1,
      [(g.group_id, g.spaceport_code) for g in g_see])
g1 = g_see[0]
check("Startpunkt stammt aus der Geometrie", g1.site_from_geometry)
check("  ... Kennung traegt die Position", g1.spaceport_code == "SEA-31N124E",
      g1.spaceport_code)
check("  ... und liegt auf dem Kreismittelpunkt",
      abs(g1.spaceport_lat - 31.2) < 0.01 and abs(g1.spaceport_lon - 123.7) < 0.01,
      (g1.spaceport_lat, g1.spaceport_lon))
check("Nation ueber den Anker in chinesischer FIR", g1.nation == "China", g1.nation)
check("  ... obwohl die Dropzones in Taiwan und Japan liegen",
      {by_see["TW-A2385"].fir_country, by_see["JP-P3438"].fir_country} == {"Taiwan", "Japan"},
      [e.fir_country for e in ev_see])
check("die drei Starttag-NOTAMs bilden die Gruppe",
      sorted(n.replace(app.MANUAL_MARK, "").strip() for n in g1.notam_ids)
      == ["A2385/26", "A2827/26", "P3438/26"], g1.notam_ids)
check("Bahn ist schluessig: Streuung unter 5 Grad", g1.azimuth_spread_deg < 5.0,
      round(g1.azimuth_spread_deg, 2))
check("  ... Azimut nach Sueden", 170 < g1.azimuth_deg < 185, round(g1.azimuth_deg, 1))
check("  ... Inklination nahe polar", 85 < g1.inclination_deg < 90,
      round(g1.inclination_deg, 1))

print("-- Die Referenz haette den Start verfehlt --")
hyos = sp[sp["Kurzel"] == "HYOS"].iloc[0]
abstand = app.surface_distance_km(31.2, 123.7, hyos["Latitude"], hyos["Longitude"])
check("naechster verzeichneter Platz liegt weit weg", abstand > 400, round(abstand))
ref_az = [app.initial_bearing_deg(hyos["Latitude"], hyos["Longitude"], la, lo)
          for la, lo, _ in app.cluster_zone_points(
              [by_see["CN-A2827"], by_see["TW-A2385"], by_see["JP-P3438"]])]
check("  ... und ergaebe eine deutlich schlechtere Bahn",
      app._angular_spread(ref_az) > 3 * g1.azimuth_spread_deg,
      (round(app._angular_spread(ref_az), 1), round(g1.azimuth_spread_deg, 1)))

print("-- Die Ableitung bleibt zurueckhaltend --")
nah = app.derive_launch_point([by_see["CN-A2827"]], sp)
check("ein einzelnes NOTAM ergibt keinen Startpunkt", nah is None, nah)
check("zwei Zonen genuegen nicht",
      app.derive_launch_point([by_see["TW-A2371"], by_see["JP-P3423"]], sp) is None)
check("Schwellen sind benannt und eng",
      (app.SEA_LAUNCH_MAX_RADIUS_KM, app.SEA_LAUNCH_MAX_SPREAD_DEG,
       app.SEA_LAUNCH_MIN_SITE_DISTANCE_KM) == (60.0, 15.0, 150.0))
check("Kennung kodiert die Position", app.sea_launch_code(31.2, 123.7) == "SEA-31N124E")
check("  ... auch auf der Suedhalbkugel", app.sea_launch_code(-28.7, -121.2) == "SEA-29S121W",
      app.sea_launch_code(-28.7, -121.2))

print("-- Archiv und Protokoll --")
arc = app.archive_row(g1, ev_see)
check("der Startpunkt steht nicht unter Dropzones",
      "31.2000 123.7000" not in arc["Dropzones"], arc["Dropzones"])
check("  ... jede Sperrzone dagegen einzeln",
      len(arc["Dropzones"].split(";")) == 3, arc["Dropzones"])
see_row = app.sea_launch_row(g1, ev_see, sp)
check("Protokollzeile enthaelt die Position",
      see_row["Breite"] == "31.2000" and see_row["Länge"] == "123.7000", see_row)
check("  ... den Kreisradius", see_row["Radius (km)"] == "20", see_row["Radius (km)"])
check("  ... und den Abstand zum naechsten bekannten Platz",
      see_row["Nächster bekannter Platz"].startswith("HYOS"),
      see_row["Nächster bekannter Platz"])
leer_see = pd.DataFrame(columns=list(app.SEA_LAUNCH_COLUMNS))
check("zweiter Lauf verdoppelt nicht",
      len(app.merge_sea_launches(app.merge_sea_launches(leer_see, [see_row]), [see_row])) == 1)
check("geloeschte Zeile kommt nicht zurueck",
      app.merge_sea_launches(leer_see, [see_row], {app.sea_launch_key(see_row)}).empty)

quelle_see = Path("app.py").read_text(encoding="utf-8")
check("das Protokoll fliesst NICHT in die Startplatz-Suche zurueck",
      "load_sea_launches" not in quelle_see.split("def _find_spaceport")[1].split("\ndef ")[0]
      and "SEA_LAUNCH_CSV" not in quelle_see.split("def _select_spaceport_for_zones")[1].split("\ndef ")[0])
check("  ... und wird gesondert gefuehrt", "seestarts_updated.csv" in quelle_see)

print("== 85. Zweiter Seestart und die Bahnrechnung ==")
# Chinesischer Seestart aus dem Suedchinesischen Meer, 11. und 12.02.2026.
# Derselbe Versuch an zwei Tagen: vier Luftraumregionen, eine Zone 6000 km weit.
SEE2 = {
"CN-Kreis-T1": """A0436/26 NOTAMN
Q) ZGZU/QRDCA/IV/BO/W/000/999/2122N11208E006
A) ZGZU B) 2602110626 C) 2602110647
E) A TEMPORARY DANGER AREA ESTABLISHED,THE AREA WITHIN A CIRCLE
CENTERED AT N212200E1120800 WITH RADIUS OF 10KM.VERTICAL
LIMITS:SFC-UNL.
F) SFC G) UNL""",
"SG-T1": """A0433/26 NOTAMN
Q) WSJC/QRALW/IV/BO/W/000/999/0757N10937E021
A) WSJC B) 2602110629 C) 2602110705
E) UNBURNED DEBRIS IS EXPECTED TO FALL WI 074150N1094911E -
074630N1091943E - 080657N1095446E DUE TO AEROSPACE FLT ACT BY CHINA.
F) SFC G) UNL""",
"VN-T1": """A0430/26 NOTAMN
Q) VVHM/QAFXX/IV/BO/E/000/999/0841N10937E060
A) VVHM B) 2602110629 C) 2602110705
E) DUE TO AEROSPACE FLIGHT ACTIVITY FM CHINA, THE FLIGHT
SAFETY OF THE ACFT IN THE FLW AREAS MAY BE AFFECTED:
- AREA 1: 094049N1092600E - 093253N1100900E - 080734N1095300E
- 081528N1091010E
- AREA 2: 091503N1092206E - 090711N1100502E - 080728N1095355E
- 074715N1091937E - 074940N1090623E
F) SFC G) UNL""",
"AU-T1": """F0494/26 NOTAMN
Q) YMMM/QWMLW/IV/BO/W/000/999/3205S10303E100
A) YMMM
B) 2602110629 C) 2602110707
E) CHINESE AEROSPACE ACTIVITIES WILL TAKE PLACE
BOUNDED BY: 303945S 1025332E - 304618S 1034303E - 332646S 1031434E -
332202S 1022337E
F) SFC G) UNL""",
"CN-Kreis-T2": """A0465/26 NOTAMN
Q) ZGZU/QRDCA/IV/BO/W/000/999/2122N11208E006
A) ZGZU B) 2602120626 C) 2602120647
E) A TEMPORARY DANGER AREA ESTABLISHED,THE AREA WITHIN A CIRCLE
CENTERED AT N212200E1120800 WITH RADIUS OF 10KM.VERTICAL
LIMITS:SFC-UNL.
F) SFC G) UNL""",
"CN-Polygon-T2": """A0466/26 NOTAMN
Q) ZGZU/QRDCA/IV/BO/W/000/999/2038N11157E016
A) ZGZU B) 2602120627 C) 2602120648
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N205303E1115154-N204919E1120844-N202257E1120205-N202641E1114518,
BACK TO START.VERTICAL LIMITS:SFC-UNL.
F) SFC G) UNL""",
"VN-T2": """A0443/26 NOTAMN
Q) VVHM/QAFXX/IV/BO/E/000/999/0841N10937E060
A) VVHM B) 2602120629 C) 2602120705
E) DUE TO AEROSPACE FLIGHT ACTIVITY FM CHINA, THE FLIGHT
SAFETY OF THE ACFT IN THE FLW AREAS MAY BE AFFECTED:
- AREA 1: 094049N1092600E - 093253N1100900E - 080734N1095300E
- 081528N1091010E
- AREA 2: 091503N1092206E - 090711N1100502E - 080728N1095355E
- 074715N1091937E - 074940N1090623E
F) SFC G) UNL""",
"AU-T2": """F0511/26 NOTAMN
Q) YMMM/QWMLW/IV/BO/W/000/999/3204S10303E087
A) YMMM
B) 2602120629 C) 2602120707
E) CHINESE AEROSPACE ACTIVITIES WILL TAKE PLACE
BOUNDED BY: 303945S 1025332E - 304618S 1034303E - 332646S 1031434E -
332202S 1022337E
F) SFC G) UNL""",
}
df_s2 = app.manual_entries_to_dataframe(
    [{"text": t, "added": "x"} for t in SEE2.values()], "NOTAM Text")
ev_s2, st_s2 = app.analyze_notams(df_s2, sp, fir, min_confidence="MEDIUM")
g_s2 = [g for g in st_s2["groups"] if g.spaceport_code]
check("zwei Starttage, zwei Gruppen", len(g_s2) == 2,
      [(g.group_id, g.launch_window) for g in g_s2])
check("beide vom selben abgeleiteten Punkt",
      {g.spaceport_code for g in g_s2} == {"SEA-21N112E"},
      [g.spaceport_code for g in g_s2])
check("  ... und beide aus der Geometrie", all(g.site_from_geometry for g in g_s2))
check("die 6000-km-Zone zieht die Bahn nicht auseinander",
      all(g.azimuth_spread_deg < 5 for g in g_s2),
      [round(g.azimuth_spread_deg, 1) for g in g_s2])
check("  ... und wird als Reichweite ausgewiesen",
      all(g.max_range_km > 5000 for g in g_s2), [round(g.max_range_km) for g in g_s2])
check("derselbe Start ergibt an beiden Tagen dieselbe Orbitklasse",
      len({g.orbit_type for g in g_s2}) == 1, [(g.group_id, g.orbit_type) for g in g_s2])
check("  ... naemlich sonnensynchron",
      {g.orbit_type for g in g_s2} == {app.ORBIT_SSO}, [g.orbit_type for g in g_s2])
check("Nation ueber den Text, nicht ueber die FIR",
      all(e.nation == "China" for e in ev_s2), [(e.notam_id, e.nation) for e in ev_s2])
# Die Ableitung braucht mindestens drei Zonenpunkte. Zwei NOTAMs allein - etwa
# wenn an einem Tag nur Kreis und Fernzone veroeffentlicht werden - genuegen
# nicht, und dann entscheidet wieder die Referenz.
duenn = app.manual_entries_to_dataframe(
    [{"text": SEE2["CN-Kreis-T2"], "added": "x"}, {"text": SEE2["AU-T2"], "added": "x"}],
    "NOTAM Text")
ev_d, st_d = app.analyze_notams(duenn, sp, fir, min_confidence="MEDIUM")
check("zwei Zonen allein ergeben keinen abgeleiteten Startpunkt",
      not any(g.site_from_geometry for g in st_d["groups"]),
      [(g.group_id, g.spaceport_code, g.site_from_geometry) for g in st_d["groups"]])

print("-- Erdrotation in der Bahnrechnung --")
check("Startazimut und Bahnazimut unterscheiden sich",
      abs(app.orbital_azimuth_deg(21.3667, 190.4) - 190.4) > 2.0,
      round(app.orbital_azimuth_deg(21.3667, 190.4), 1))
check("  ... bei einem Start nach Osten dagegen nicht",
      abs(app.orbital_azimuth_deg(28.5, 90.0) - 90.0) < 1e-6)
check("  ... die Drehung schiebt immer nach Osten",
      app.orbital_azimuth_deg(45.0, 180.0) < 180.0,
      round(app.orbital_azimuth_deg(45.0, 180.0), 2))
check("Konstanten sind benannt",
      (app.ORBITAL_VELOCITY_MS, app.EARTH_ROTATION_MS) == (7800.0, 465.1))

print("-- Die Orbitbaender tragen die Genauigkeit der Abschaetzung --")
for name, lat, az in (("Taiyuan", 38.85, 188.8), ("Jiuquan", 40.96, 189.3),
                      ("Seestart Tag 1", 21.3667, 190.4), ("Seestart Tag 2", 21.3667, 191.3)):
    i = app.estimate_inclination_deg(lat, az)
    check("bekannter SSO-Start wird als SSO gefuehrt: {}".format(name),
          app.classify_orbit(i) == app.ORBIT_SSO, (name, round(i, 1), app.classify_orbit(i)))
for name, lat, az, erwartet in (
        ("Vandenberg polar", 34.74, 180.0, app.ORBIT_HIGH_INC),
        ("Baikonur ISS", 45.96, 44.9, app.ORBIT_LEO_MEO),
        ("Cape Canaveral GTO", 28.5, 90.0, app.ORBIT_GTO)):
    i = app.estimate_inclination_deg(lat, az)
    check("  ... und nichts anderes rutscht hinein: {}".format(name),
          app.classify_orbit(i) == erwartet, (name, round(i, 1), app.classify_orbit(i)))
check("echte Rueckwaertsbahnen bleiben moeglich",
      app.classify_orbit(110.0) == app.ORBIT_RETROGRADE)

print("== 86. CSV-Export der Starts ==")
quelle_x = Path("app.py").read_text(encoding="utf-8")
check("keine Klartext-Spalte mehr im Starts-Export",
      'starts_csv["Klartext"]' not in quelle_x)
check("  ... der Export nutzt die Tabelle unveraendert",
      "data=group_table.to_csv(index=False)" in quelle_x)
gt_x = app.groups_to_dataframe([pg])
check("  ... und die Tabelle fuehrt die Spalte nicht",
      "Klartext" not in gt_x.columns, list(gt_x.columns))
check("auch der JSON-Export fuehrt ihn nicht mehr",
      "klartext" not in quelle_x)
check("  ... und reicht die Startdaten unveraendert durch",
      '"launches": [group_to_export_dict(g) for g in visible_groups]' in quelle_x)
check("die Klartext-Auswertung in der Oberflaeche bleibt",
      quelle_x.count("st.markdown(describe_launch(group, events))") == 2)
check("  ... und ist weiterhin erzeugbar",
      app.describe_launch(pg, [pe1]).startswith("**What:**"),
      app.describe_launch(pg, [pe1])[:40])
check("der Startdatensatz im JSON hat kein Klartextfeld",
      "klartext" not in app.group_to_export_dict(pg),
      sorted(app.group_to_export_dict(pg))[:6])

print("== 87. Vorankuendigungen ==")

print("-- D-Item: beide Trennzeichen --")
# Gemessen an der Echtdatei vom 18.09.2026: von 100 D-Items mit Tagesfenster
# nutzen 8 den Schraegstrich. Vorher las der Parser nur den Bindestrich.
check("Bindestrich 0200-0600", app.daily_window_hours("0200-0600") == 4.0,
      app.daily_window_hours("0200-0600"))
check("Schraegstrich 0200/0600", app.daily_window_hours("0200/0600") == 4.0,
      app.daily_window_hours("0200/0600"))
check("Echtform 'DLY BTN 1700/0400' laeuft ueber Mitternacht",
      app.daily_window_hours("DLY BTN 1700/0400") == 11.0,
      app.daily_window_hours("DLY BTN 1700/0400"))
check("zwei Fenster: das laengere zaehlt",
      app.daily_window_hours("DLY BTN 1600/1900 AND BTN 2300/0200") == 3.0,
      app.daily_window_hours("DLY BTN 1600/1900 AND BTN 2300/0200"))
# Verstuemmelt - hier wird nicht geraten. 200 koennte 0200 oder 2000 meinen.
check("dreistellige Zeitangabe wird nicht geraten",
      app.daily_window_hours("DLY BTN 1700/200") is None,
      app.daily_window_hours("DLY BTN 1700/200"))
# "EVERY DAY, 24 HOURS" heisst durchgehend aktiv. Kein Fenster zu finden ist
# hier das richtige Ergebnis: der Daueranordnungs-Deckel soll greifen.
check("'EVERY DAY,24 HOURS' bleibt ohne Fenster - absichtlich",
      app.daily_window_hours("EVERY DAY,24 HOURS") is None)
check("Minutenbereiche kommen unveraendert heraus",
      app.daily_windows("0200/0600") == [(120, 360)], app.daily_windows("0200/0600"))
check("  ... und ein Fenster ueber Mitternacht behaelt die kleinere Endzeit",
      app.daily_windows("1700/0400") == [(1020, 240)], app.daily_windows("1700/0400"))

print("-- Liegt das Startfenster im Tagesfenster? --")
def _utc(tag, stunde, minute):
    return datetime(2026, 7, tag, stunde, minute, tzinfo=timezone.utc)
check("0245-0312 liegt in 0200-0600",
      app.window_within_daily(_utc(22, 2, 45), _utc(22, 3, 12), "0200-0600"))
check("0745 liegt nicht darin",
      not app.window_within_daily(_utc(22, 7, 45), _utc(22, 8, 12), "0200-0600"))
check("0245 liegt in 'DLY BTN 1700/0400' - das Fenster laeuft ueber Mitternacht",
      app.window_within_daily(_utc(22, 2, 45), _utc(22, 3, 12), "DLY BTN 1700/0400"))
check("1200 liegt nicht darin",
      not app.window_within_daily(_utc(22, 12, 0), _utc(22, 12, 30), "DLY BTN 1700/0400"))
check("ohne D-Item schraenkt nichts ein",
      app.window_within_daily(_utc(22, 2, 45), _utc(22, 3, 12), None))
check("ein Fenster, das aus dem Tagesfenster herauslaeuft, passt nicht",
      not app.window_within_daily(_utc(22, 5, 30), _utc(22, 6, 30), "0200-0600"))

print("-- Deckungsgleiche Zonen --")
kreis = app.LaunchEvent(row_index=0, notam_id="K", raw_text="", zones=[[(31.2, 123.7)]],
                        radius_km=20.0)
check("ein Kreis-NOTAM bringt seinen Radius als Ausdehnung mit",
      app.event_zone_shapes(kreis) == [(31.2, 123.7, 20.0)], app.event_zone_shapes(kreis))
check("zwei gleich grosse Zonen 1 km versetzt sind deckungsgleich",
      app.zones_congruent((28.2, 123.5, 45.0), (28.21, 123.5, 45.0)))
check("  ... 328 km versetzt nicht",
      not app.zones_congruent((28.2, 123.5, 45.0), (31.2, 123.7, 45.0)))
check("ein 20-km-Kreis im Mittelpunkt einer 45-km-Zone ist keine Paarung",
      not app.zones_congruent((28.2, 123.5, 45.0), (28.2, 123.5, 20.0)))
check("Zonen ohne Ausdehnung paaren nicht",
      not app.zones_congruent((28.2, 123.5, 0.0), (28.2, 123.5, 0.0)))
check("Schwellen sind benannt",
      (app.ADVANCE_ZONE_OFFSET_SHARE, app.ADVANCE_ZONE_SIZE_SHARE,
       app.ADVANCE_MIN_DURATION_FACTOR, app.ADVANCE_MIN_DURATION_HOURS)
      == (0.25, 0.6, 4.0, 24.0))

print("-- Der Echtfall: zwei Vorankuendigungen finden ihren Start --")
# Dieselben fuenf NOTAMs wie in Abschnitt 84. Vorher blieben A2371/26 und
# P3423/26 im Review: sie liegen in taiwanesischem und japanischem Luftraum,
# nennen weder China noch einen Startplatz, und die Drittstaaten-Regel laesst
# keine geratene Nation zu. Die Geometrie loest das.
va = [e for e in ev_see if e.kind == app.KIND_ADVANCE]
check("genau zwei Meldungen als Vorankuendigung gefuehrt", len(va) == 2,
      [e.notam_id.strip() for e in va])
check("  ... es sind die beiden mehrtaegigen",
      sorted(e.notam_id.replace(app.MANUAL_MARK, "").strip() for e in va)
      == ["A2371/26", "P3423/26"], [e.notam_id for e in va])
check("  ... sie haben das Review verlassen",
      all(e.status == "OK" and not e.review_reason for e in va),
      [(e.status, e.review_reason[:20]) for e in va])
check("  ... und tragen den Start", all(e.launch_group == g1.group_id for e in va),
      [e.launch_group for e in va])
check("  ... mit der Nation des Starts", all(e.nation == "China" for e in va),
      [e.nation for e in va])
check("  ... und seinem Startplatz",
      all(e.spaceport_code == "SEA-31N124E" for e in va), [e.spaceport_code for e in va])
check("der Hinweis nennt den Vorlauf",
      all("Advance notice for" in e.assignment_note for e in va),
      [e.assignment_note[:40] for e in va])

print("-- Die Gruppe bleibt unberuehrt --")
# Der entscheidende Punkt: die angekuendigte Flaeche IST die Sperrzone am
# Starttag. Als weitere Zone gezaehlt waere sie eine Doppelzaehlung und wuerde
# Azimut und Streuung verfaelschen.
check("drei Sperrzonen, nicht fuenf", g1.zone_count == 3, g1.zone_count)
check("  ... die Vorankuendigungen stehen nicht unter den NOTAMs des Starttags",
      not any("A2371" in n or "P3423" in n for n in g1.notam_ids), g1.notam_ids)
check("  ... sondern in einem eigenen Feld",
      sorted(n.replace(app.MANUAL_MARK, "").strip() for n in g1.advance_notam_ids)
      == ["A2371/26", "P3423/26"], g1.advance_notam_ids)
check("Streuung unveraendert schluessig", g1.azimuth_spread_deg < 5.0,
      round(g1.azimuth_spread_deg, 2))
check("Vorlauf wird gerechnet, nicht geschaetzt",
      abs((g1.advance_notice_hours or 0) - 24.733) < 0.01, g1.advance_notice_hours)

print("-- Anzeige, Klartext, Export --")
gt_va = app.groups_to_dataframe([g1])
check("die Startansicht fuehrt eine Spalte Vorankuendigung",
      "Vorank\u00fcndigung" in gt_va.columns)
check("  ... mit Kennungen und Vorlauf",
      "A2371/26" in gt_va["Vorank\u00fcndigung"].iloc[0]
      and "25 h" in gt_va["Vorank\u00fcndigung"].iloc[0],
      gt_va["Vorank\u00fcndigung"].iloc[0])
check("  ... und sie ist englisch beschriftet",
      app.COLUMN_LABELS["Vorank\u00fcndigung"] == "Advance Notice")
check("  ... und steht in der Spaltenreihenfolge",
      "Vorank\u00fcndigung" in app.GROUP_COLUMN_ORDER)
klartext_va = app.describe_launch(g1, ev_see)
check("der Klartext nennt die Vorankuendigung",
      "**Announced in advance:**" in klartext_va)
check("  ... und begruendet, warum sie keine weitere Zone ist",
      "not counted as further closure zones" in klartext_va)
check("  ... und zaehlt weiterhin drei Sperrzonen",
      "3 airspace closure(s)" in klartext_va)
exp_va = app.group_to_export_dict(g1)
import json as _json
_json.dumps(exp_va)  # darf nicht werfen - advance_from ist ein datetime
check("der JSON-Export fuehrt die Kennungen",
      exp_va["advance_notam_ids"] == g1.advance_notam_ids)
check("  ... das Datum als Text", exp_va["advance_from"].startswith("2026-07-21"),
      exp_va["advance_from"])
check("  ... und den Vorlauf gerundet", exp_va["advance_notice_hours"] == 24.7,
      exp_va["advance_notice_hours"])

print("-- Die Paarung bleibt zurueckhaltend --")
check("ein kurzes NOTAM ist nie eine Vorankuendigung",
      not app.is_advance_announcement(
          by_see["TW-A2385"], g1, app.event_zone_shapes(by_see["CN-A2827"])))
check("ohne deckungsgleiche Zone keine Paarung",
      not app.is_advance_announcement(
          by_see["TW-A2371"], g1, app.event_zone_shapes(by_see["CN-A2827"])))
# Die Nation der Gruppe muss unter den Kandidaten stehen. Die Paarung darf die
# Drittstaaten-Regel nicht aushebeln, sondern nur eine zulaessige belegen.
import copy as _copy
g_fremd = _copy.deepcopy(g1)
g_fremd.nation = "Iran"
check("eine fremde Nation wird nicht angehaengt",
      not app.is_advance_announcement(
          by_see["TW-A2371"], g_fremd,
          [f for e in (by_see["TW-A2385"],) for f in app.event_zone_shapes(e)]))
check("ausgeblendete Meldungen bleiben ausgeblendet",
      "event.auto_hidden_reason or not event.zones" in quelle_x)

print("-- Traegersystem und Nutzlast gelten startweit --")
# Die Vorankuendigung zaehlt nicht als Sperrzone, gehoert aber zum Start. Wer
# das Traegersystem auf ihrer Zeile waehlt, meint denselben Start.
app.apply_vehicle_assignments(ev_see, st_see["groups"], {va[0].key: "CZ-11"})
check("auf der Vorankuendigung gewaehlt, gilt fuer den ganzen Start",
      g1.vehicle == "CZ-11", g1.vehicle)
check("  ... und erreicht die NOTAMs des Starttags",
      all(by_see[k].vehicle == "CZ-11" for k in ("CN-A2827", "TW-A2385", "JP-P3438")),
      [by_see[k].vehicle for k in ("CN-A2827", "TW-A2385", "JP-P3438")])
app.apply_payload_assignments(ev_see, st_see["groups"], {by_see["CN-A2827"].key: "Yaogan"})
check("umgekehrt erreicht die Nutzlast die Vorankuendigung",
      all(e.payload == "Yaogan" for e in va), [e.payload for e in va])
check("  ... und die Zonenzahl bleibt davon unberuehrt", g1.zone_count == 3, g1.zone_count)
app.apply_vehicle_assignments(ev_see, st_see["groups"], {})
app.apply_payload_assignments(ev_see, st_see["groups"], {})
check("die Paarung laeuft nach der Gruppierung",
      quelle_x.index("groups = group_launches(events, spaceports)")
      < quelle_x.index("pair_advance_announcements(events, groups)"))

if xls:
    ev_v, st_v = app.analyze_notams(real, sp, fir, min_confidence="MEDIUM")
    print("-- Gegen den Echtbestand --")
    # Gemessen: 792 (NOTAM, Start)-Paare kaemen in Frage. Die Zeitbedingungen
    # bestehen einzeln 41 bis 73 Prozent davon - sie allein wuerden nichts
    # tragen. Die Deckungsgleichheit der Zonen schliesst alle 792 aus.
    paare_v = [e for e in ev_v if e.kind == app.KIND_ADVANCE]
    check("keine Paarung ohne deckungsgleiche Zone",
          all(any(app.zones_congruent(a, b)
                  for a in app.event_zone_shapes(e)
                  for gg in st_v["groups"] if gg.group_id == e.launch_group
                  for b in [f for o in ev_v if o.launch_group == gg.group_id
                            and o.kind != app.KIND_ADVANCE
                            for f in app.event_zone_shapes(o)])
              for e in paare_v),
          [e.notam_id for e in paare_v])
    check("  ... und keine gegen die Drittstaaten-Regel",
          all(e.nation in e.candidate_nations for e in paare_v),
          [(e.notam_id, e.nation, e.candidate_nations) for e in paare_v])
    check("im Bestand vom 18.09.2026 ergibt sich keine - gemessen, nicht geraten",
          st_v["advance"] == 0, st_v["advance"])
    check("  ... und die Starts bleiben vollzaehlig", st_v["launches"] >= 8,
          st_v["launches"])

print("== 88. Nebeneinanderliegende Startplaetze (Wenchang / Hainan) ==")

print("-- Die Referenz kennt beide --")
check("Hainan steht als eigener Platz", "HAIN" in set(sp["Kurzel"]), sorted(sp["Kurzel"])[:4])
check("  ... unter eigenem Namen",
      sp[sp["Kurzel"] == "HAIN"]["Name"].iloc[0] == "Hainan Commercial Launch Site",
      sp[sp["Kurzel"] == "HAIN"]["Name"].iloc[0])
check("  ... und Wenchang behaelt seinen",
      sp[sp["Kurzel"] == "WSLC"]["Name"].iloc[0] == "Wenchang Space Launch Site")
check("sie liegen unter 2 km auseinander",
      app.site_separation_km(["WSLC", "HAIN"], sp) < 2.0,
      round(app.site_separation_km(["WSLC", "HAIN"], sp), 2))

print("-- Die Geometrie darf hier nicht entscheiden --")
# Gemessen: 1,92 km ergeben 0,06 bis 0,22 Grad Azimutunterschied, gegen eine
# Auswahlschwelle von 15 Grad. Der Score rechnet Streuung x 100 - also wuerde
# verhundertfachtes Rauschen entscheiden. An vier Startkorridoren gemessen
# kippte das Ergebnis je nach Dropzone-Muster.
check("die Nachbarschaft wird erkannt",
      app.co_located_groups(sp).get("WSLC") == ("WSLC", "HAIN"),
      app.co_located_groups(sp).get("WSLC"))
check("  ... und sonst niemand - die Floridagruppe bleibt unberuehrt",
      set(app.co_located_groups(sp)) == {"WSLC", "HAIN"},
      sorted(app.co_located_groups(sp)))
check("der nachrangige Platz ist von der automatischen Wahl ausgenommen",
      "HAIN" not in set(app._auto_selectable(sp)["Kurzel"]))
check("  ... der erstverzeichnete nicht",
      "WSLC" in set(app._auto_selectable(sp)["Kurzel"]))
check("Schwelle ist benannt und gemessen", app.CO_LOCATED_SITE_KM == 5.0)
# Die Schwelle sitzt in der Luecke der Referenz: 1,92 km dann 10,45 km.
paare = []
for i in range(len(sp)):
    for j in range(i + 1, len(sp)):
        a, b = sp.iloc[i], sp.iloc[j]
        if a["Land"] == b["Land"]:
            paare.append(app.surface_distance_km(
                a["Latitude"], a["Longitude"], b["Latitude"], b["Longitude"]))
paare.sort()
check("  ... zwischen engstem und zweitengstem Paar",
      paare[0] < app.CO_LOCATED_SITE_KM < paare[1],
      (round(paare[0], 2), app.CO_LOCATED_SITE_KM, round(paare[1], 2)))
# Vier Startkorridore: ohne die Regel kippte die Wahl, mit ihr steht sie.
for name, zonen in (
    ("Suedkurs",   [(17.0, 112.0), (12.0, 113.5)]),
    ("Suedostkurs", [(18.2, 112.6), (14.0, 116.0)]),
    ("Ostkurs",    [(19.4, 113.0), (19.0, 118.5)]),
    ("eine Zone",  [(17.0, 112.0)]),
):
    wahl = app._select_spaceport_for_zones(zonen, sp, ["China"], [])
    check("  ... {} waehlt WSLC, nicht das Pad daneben".format(name),
          wahl is not None and wahl[0]["Kurzel"] == "WSLC",
          wahl[0]["Kurzel"] if wahl else None)

print("-- Nennt der Text den Platz, gilt er trotzdem --")
# Der Text ist die staerkere Quelle als die Geometrie - diese Regel darf die
# Ausnahme nicht aushebeln.
genannt = app._restrict_candidates(sp, ["China"], ["HAIN"])
check("ausdrueckliche Nennung erreicht auch den nachrangigen Platz",
      list(genannt["Kurzel"]) == ["HAIN"], list(genannt["Kurzel"]))

check("  ... und der Texthinweis WENCHANG laesst das Pad offen",
      app.SPACEPORT_HINTS.get("WENCHANG") == ("WSLC",),
      app.SPACEPORT_HINTS.get("WENCHANG"))
# Wuerde er beide nennen, duerfte die Geometrie zwischen ihnen waehlen - genau
# das soll die Regel verhindern.
check("  ... und damit bleibt der Nachbar vermerkt",
      app.site_alternatives_for("WSLC", sp) == ["HAIN"])

print("-- Ohne Zutun: unbestimmt, nicht geraten --")
WEN = {
 "W1": """A3301/26 NOTAMN
Q)ZJSA/QRDCA/IV/BO/W/000/999/1900N11100E050
A)ZJSA B)2610050230 C)2610050310
E) A TEMPORARY DANGER AREA ESTABLISHED FOR SPACE LAUNCH,THE AREA
BOUNDED BY 1830N11130E - 1800N11230E - 1700N11200E - 1730N11100E.
F)SFC G)UNL""",
 "W2": """A3302/26 NOTAMN
Q)ZJSA/QRDCA/IV/BO/W/000/999/1500N11300E090
A)ZJSA B)2610050235 C)2610050320
E) A TEMPORARY DANGER AREA ESTABLISHED FOR SPACE LAUNCH,THE AREA
BOUNDED BY 1300N11400E - 1230N11500E - 1130N11430E - 1200N11330E.
F)SFC G)UNL""",
}
df_w = app.manual_entries_to_dataframe(
    [{"text": t, "added": "x"} for t in WEN.values()], "NOTAM Text")
ev_w, st_w = app.analyze_notams(df_w, sp, fir, min_confidence="MEDIUM")
g_w = [x for x in st_w["groups"] if x.spaceport_code][0]
az_vorher, inkl_vorher = g_w.azimuth_deg, g_w.inclination_deg
check("der Start landet auf WSLC", g_w.spaceport_code == "WSLC", g_w.spaceport_code)
check("  ... mit vermerktem Nachbarn", g_w.site_alternatives == ["HAIN"],
      g_w.site_alternatives)
check("  ... und gilt als nicht bestimmt", not g_w.site_determined)
check("die Statistik zaehlt den Fall", st_w["site_ambiguous"] == 1, st_w["site_ambiguous"])
check("die Spalte Pad sagt es",
      app.groups_to_dataframe([g_w])["Pad"].iloc[0] == "not determined",
      app.groups_to_dataframe([g_w])["Pad"].iloc[0])
klar_w = app.describe_launch(g_w, ev_w)
check("der Klartext sagt es auch", "**Which pad:** Not determined." in klar_w)
check("  ... und begruendet es mit der Geometrie",
      "less than a quarter of a degree" in klar_w)
check("  ... und sagt, warum trotzdem WSLC dasteht",
      "longer-established site, not because it was established" in klar_w)
check("  ... und behauptet keine Eindeutigkeit mehr",
      "Apart from its immediate neighbour HAIN" in klar_w)

print("-- Von Hand gesetzt --")
app.apply_launch_site_assignments(ev_w, st_w["groups"], sp, {ev_w[0].key: "HAIN"})
check("der Platz wechselt", g_w.spaceport_code == "HAIN", g_w.spaceport_code)
check("  ... samt Namen", g_w.spaceport_name == "Hainan Commercial Launch Site")
check("  ... und Koordinaten", abs(g_w.spaceport_lat - 19.6310) < 1e-6)
check("  ... gilt nun als bestimmt", g_w.site_determined)
check("  ... und die Spalte zeigt es",
      app.groups_to_dataframe([g_w])["Pad"].iloc[0] == "by hand")
check("die Wahl gilt fuer alle Zonen des Starts",
      all(e.spaceport_code == "HAIN" for e in ev_w), [e.spaceport_code for e in ev_w])
# Entscheidend: keine Scheingenauigkeit. 1,92 km aendern den Azimut um 0,2 Grad,
# die Inklination gibt das Programm selbst nur auf wenige Grad an.
check("Azimut wird NICHT neu gerechnet", g_w.azimuth_deg == az_vorher,
      (az_vorher, g_w.azimuth_deg))
check("  ... und die Inklination auch nicht", g_w.inclination_deg == inkl_vorher)
app.apply_launch_site_assignments(ev_w, st_w["groups"], sp, {})
check("zuruecknehmen fuehrt auf WSLC zurueck", g_w.spaceport_code == "WSLC",
      g_w.spaceport_code)
check("  ... und wieder auf unbestimmt", not g_w.site_determined)

print("-- Der Hinweis kommt aus dem Archiv, nicht aus dem Code --")
# Eine Tabelle "Rakete X startet von Pad Y" waere eine Momentaufnahme der
# Praxis, keine Eigenschaft der Rakete - CZ-8 flog von Anfang an von beiden
# Gelaenden. Sie wuerde unbemerkt veralten. Diese Zaehlung nicht.
arc_h = pd.DataFrame([
    {"Trägersystem": "CZ-12", "Weltraumbahnhof": "HAIN"},
    {"Trägersystem": "CZ-12", "Weltraumbahnhof": "HAIN"},
    {"Trägersystem": "CZ-8",  "Weltraumbahnhof": "HAIN"},
    {"Trägersystem": "CZ-8",  "Weltraumbahnhof": "WSLC"},
])
check("eindeutige Historie wird gezaehlt",
      app.launch_site_history(arc_h, "CZ-12", "WSLC", sp)
      == "Your archive: CZ-12 flew 2x HAIN.",
      app.launch_site_history(arc_h, "CZ-12", "WSLC", sp))
gemischt = app.launch_site_history(arc_h, "CZ-8", "WSLC", sp)
check("gemischte Historie wird als gemischt gezeigt",
      "1x HAIN" in gemischt and "1x WSLC" in gemischt, gemischt)
check("  ... mit dem Vorbehalt zum erstverzeichneten Platz",
      "WSLC may also mean the pad was never determined" in gemischt, gemischt)
check("  ... und der Vorbehalt gilt nicht fuer den nachrangigen",
      "HAIN may also mean" not in gemischt, gemischt)
check("ohne Archivzeilen kein Hinweis",
      app.launch_site_history(arc_h, "CZ-5B", "WSLC", sp) == "")
check("ohne Traegersystem kein Hinweis",
      app.launch_site_history(arc_h, "", "WSLC", sp) == "")
check("an einem Platz ohne Nachbarn kein Hinweis",
      app.launch_site_history(arc_h, "CZ-12", "JSLC", sp) == "")
check("leeres Archiv bricht nicht",
      app.launch_site_history(pd.DataFrame(), "CZ-12", "WSLC", sp) == "")
# Keine Zeile darf ein Traegersystem auf ein Platzkuerzel abbilden - genau das
# waere die Momentaufnahme, die unbemerkt veraltet.
_platzcodes = set(sp["Kurzel"])
_verdrahtet = [
    z for z in quelle_x.splitlines()
    if not z.lstrip().startswith(("#", "*"))
    and re.search(r"\b(CZ|KZ|GSX|SD|ZQ|YL|SQX)-\w+", z)
    and any('"{}"'.format(c) in z or "'{}'".format(c) in z for c in _platzcodes)
]
check("keine Zeile bildet ein Traegersystem auf ein Platzkuerzel ab",
      _verdrahtet == [], _verdrahtet[:2])
check("  ... die Historie liest stattdessen die Archivspalten",
      'archiv["Trägersystem"]' in quelle_x and 'archiv["Weltraumbahnhof"]' in quelle_x
      or '{"Trägersystem", "Weltraumbahnhof"}' in quelle_x)

print("-- Bedienung und Arbeitsstand --")
check("Auswahlliste nur bei Nachbarplaetzen",
      "nachbarn = event.site_alternatives" in quelle_x
      and "if not nachbarn:" in quelle_x)
check("Vorgabe ist 'not determined'", '"not determined" if not code' in quelle_x)
check("die Wahl wird im Arbeitsstand gesichert",
      "launch_site_assignments" in quelle_x)
echt_w2 = app.WORKSPACE_FILE
app.WORKSPACE_FILE = Path("test_workspace_pad.json")
try:
    app.save_workspace([], [], [], launch_site_assignments={"kx": "HAIN", "ky": ""})
    wieder = app.load_workspace()
    check("gespeichert und wieder gelesen",
          wieder.get("launch_site_assignments") == {"kx": "HAIN"},
          wieder.get("launch_site_assignments"))
finally:
    app.WORKSPACE_FILE.unlink(missing_ok=True)
    app.WORKSPACE_FILE = echt_w2
check("save_workspace wird benannt aufgerufen - nicht nach Position",
      "launch_site_assignments=st.session_state" in quelle_x)
check("die Pad-Wahl greift vor Tabelle und Archiv",
      quelle_x.index("apply_launch_site_assignments(")
      < quelle_x.index("table = events_to_dataframe(visible_events, vehicles)"))
check("das Archiv wird einmal je Durchlauf gelesen, nicht je Zeile",
      quelle_x.count("pad_historie = load_archive(ARCHIVE_CSV)") == 1
      and quelle_x.count("pad_historie, group_keys") == 2)

print("== 89. Archivschluessel: Identitaet statt Momentaufnahme ==")
# Der Schluessel enthielt den Startplatz. Der aendert sich aber, wenn die
# Erkennung besser wird - und erzeugte dann eine zweite Zeile statt eines
# Updates. Im Bestand stehen dadurch drei Zeilen fuer den chinesischen Seestart
# vom 12.02.2026, F0511/26 in allen drei.

print("-- Der Startplatz gehoert nicht zur Identitaet --")
_a = {"NOTAM": "F0511/26, A0443/26", "Startdatum": "12.02.2026", "Weltraumbahnhof": "WSLC"}
_b = dict(_a, Weltraumbahnhof="SEA-21N112E")
check("Seestart-Ableitung verschiebt den Platz, nicht die Identitaet",
      app.archive_key(_a) == app.archive_key(_b), app.archive_key(_b))
check("  ... und erzeugt damit keine zweite Zeile",
      len(app.merge_archive(pd.DataFrame([_a]), [_b])) == 1)
_c = dict(_a, Weltraumbahnhof="HAIN")
check("eine Pad-Wahl verschiebt sie auch nicht",
      app.archive_key(_a) == app.archive_key(_c))
check("der Platz der NEUEREN Auswertung gewinnt",
      app.merge_archive(pd.DataFrame([_a]), [_c])["Weltraumbahnhof"].iloc[0] == "HAIN",
      app.merge_archive(pd.DataFrame([_a]), [_c])["Weltraumbahnhof"].iloc[0])
check("Datum und Kennungen tragen die Identitaet",
      app.archive_key(_a) == "12.02.2026|A0443/26,F0511/26", app.archive_key(_a))
check("verschiedene Tage bleiben verschieden",
      app.archive_key(_a) != app.archive_key(dict(_a, Startdatum="11.02.2026")))
check("verschiedene Kennungen bleiben verschieden",
      app.archive_key(_a) != app.archive_key(dict(_a, NOTAM="F0494/26")))
check("die Reihenfolge der Kennungen ist gleichgueltig",
      app.archive_key(_a) == app.archive_key(dict(_a, NOTAM="A0443/26, F0511/26")))

print("-- Der ganze Weg: Pad setzen verdoppelt nichts mehr --")
ev_k, st_k = app.analyze_notams(df_w, sp, fir, min_confidence="MEDIUM")
g_k = [x for x in st_k["groups"] if x.spaceport_code][0]
zeile1 = app.archive_row(g_k, ev_k)
app.apply_launch_site_assignments(ev_k, st_k["groups"], sp, {ev_k[0].key: "HAIN"})
zeile2 = app.archive_row(g_k, ev_k)
check("vor und nach der Pad-Wahl derselbe Schluessel",
      app.archive_key(zeile1) == app.archive_key(zeile2))
zusammen = app.merge_archive(pd.DataFrame([zeile1]), [zeile2])
check("  ... eine Zeile, nicht zwei", len(zusammen) == 1, len(zusammen))
check("  ... und sie traegt das gesetzte Pad",
      zusammen["Weltraumbahnhof"].iloc[0] == "HAIN")

print("-- Gespeicherte Loeschungen bleiben Loeschungen --")
# Alte Schluessel trugen den Platz als Mittelteil. Ohne Umstellung kaemen von
# Hand geloeschte Zeilen beim naechsten Durchlauf zurueck.
check("dreiteilige Altschluessel werden umgestellt",
      app.migrate_archive_keys(["21.09.2025|WSLC|A1234/25"]) == {"21.09.2025|A1234/25"},
      app.migrate_archive_keys(["21.09.2025|WSLC|A1234/25"]))
check("  ... zweiteilige bleiben unberuehrt",
      app.migrate_archive_keys(["12.02.2026|F0511/26"]) == {"12.02.2026|F0511/26"})
check("  ... die Umstellung ist wiederholbar",
      app.migrate_archive_keys(app.migrate_archive_keys(["21.09.2025|WSLC|A1234/25"]))
      == {"21.09.2025|A1234/25"})
check("  ... leere Eingabe bricht nicht", app.migrate_archive_keys([]) == set())
check("beim Laden des Arbeitsstands wird umgestellt",
      "migrate_archive_keys(" in quelle_x
      and quelle_x.count("migrate_archive_keys(") >= 2)
_geloescht = app.migrate_archive_keys(["12.02.2026|WSLC|A0443/26,F0511/26"])
check("eine geloeschte Zeile kommt auch nach einer Platzaenderung nicht zurueck",
      len(app.merge_archive(pd.DataFrame(columns=list(app.ARCHIVE_COLUMNS)),
                            [_b], entfernt=_geloescht)) == 0)

print("-- Was offen bleibt, steht im Code --")
# Ehrlichkeit statt Scheinloesung: die Kennungsmenge waechst, wenn die
# GRUPPIERUNG besser wird, und dann aendert sich der Schluessel trotzdem.
check("die verbleibende Haelfte ist benannt",
      "Kennungs-Ueberschneidung" in app.archive_key.__doc__,
      app.archive_key.__doc__ is not None)
_d = {"NOTAM": "F0511/26", "Startdatum": "12.02.2026", "Weltraumbahnhof": "WSLC"}
check("  ... und sie besteht nachweislich noch",
      app.archive_key(_d) != app.archive_key(_a),
      (app.archive_key(_d), app.archive_key(_a)))

print("== Archiv-Import ==")
import archiv_import as ai

AI_CN = CN  # A0611/26, A4631/26, A4632/26 aus Abschnitt 22
blk = ai.cut_block(AI_CN[1] + "\nprobably Starship from Boca Chica, see post above")
check("Kommentar unter G) gehoert nicht zum Block", "STARSHIP" not in blk.upper(), blk[-60:])
check("  ... der Block endet mit G)UNL", blk.rstrip().endswith("G)UNL"), blk[-20:])
nur_e = "Z1111/26 NOTAMN\nB) 2609200354 C) 2609200415\nE) DANGER AREA 3948N10002E\n\nnice launch!"
check("nur E): Ende an der Leerzeile", "nice" not in ai.cut_block(nur_e))

forum = "Hier die NOTAMs fuer morgen:\n\n" + "\n\n".join(AI_CN) + "\n\n" \
        "B9999/26 hat keinen Inhalt\n"
gef, unbr = ai.extract_notams(forum, "test.txt")
check("drei NOTAMs aus Forentext", [n.notam_id for n in gef] == ["A0611/26", "A4631/26", "A4632/26"],
      [n.notam_id for n in gef])
check("  ... B-Rohwert gemerkt", gef[1].b == "2609200354", gef[1].b)
check("  ... Quelle gemerkt", gef[0].quellen == ["test.txt"], gef[0].quellen)
check("  ... Block ohne E)/Q) als nicht verwertbar gezaehlt", unbr == 1, unbr)
check("Schluessel = Kennung|B", gef[1].schluessel == "A4631/26|2609200354", gef[1].schluessel)

SMF = """<html><head><script>var x = "A7777/26 Q) X E) Y";</script></head><body>
<div class="post_wrapper"><div class="inner" data-msgid="101" id="msg_101">
Two NOTAMs:<br>""" + AI_CN[1].replace("\n", "<br>\n") + """<br>""" + AI_CN[2].replace("\n", "<br>\n") + """
</div></div>
<div class="post_wrapper"><div class="inner" id="msg_102">
<blockquote class="bbc_standard_quote">""" + AI_CN[1].replace("\n", "<br>\n") + """</blockquote>
Looks like CZ-2D from Jiuquan.</div></div></body></html>"""
teile = ai.texts_from_upload("thread_p1.html", SMF.encode("utf-8"))
check("HTML: je Beitrag ein Text", [q for q, _ in teile] == ["thread_p1.html#msg_101", "thread_p1.html#msg_102"],
      [q for q, _ in teile])
check("HTML: Zitat verworfen", "A4631/26" not in teile[1][1], teile[1][1][:80])
check("HTML: Skript verworfen", all("A7777/26" not in t for _, t in teile))
check("HTML: Zeilenumbrueche aus <br>", "\nE)" in teile[0][1])
_n1 = "A1234/26 NOTAMN<br>B) 2609200354 C) 2609200415<br>E) DANGER AREA 3948N10002E"
_t = ai.texts_from_upload("s.html", ('<div class="inner" id="msg_1"><p>Intro</p></p>' + _n1 + '</div>').encode())
check("HTML: ueberzaehliges </p> schliesst den Beitrag nicht",
      len(_t) == 1 and ai.extract_notams(_t[0][1], "q")[0] != [], _t)
_t = ai.texts_from_upload("s.html", ('<div class="inner" id="msg_1">Mein Text <blockquote>ZITAT A9999/26</span> noch Zitat</blockquote> Ende</div>').encode())
check("HTML: ueberzaehliges </span> im Zitat: eigener Text bleibt, Zitat bleibt verdeckt",
      len(_t) == 1 and "Mein Text" in _t[0][1] and "Ende" in _t[0][1] and "ZITAT" not in _t[0][1]
      and "noch Zitat" not in _t[0][1], _t)
_t = ai.texts_from_upload("t.html", b'<div class="inner" id="msg_1">A1234/26 never closed')
check("HTML: nie geschlossener Beitrag wird geliefert",
      [q for q, _ in _t] == ["t.html#msg_1"] and "A1234/26 never closed" in _t[0][1], _t)
_g, _u = ai.extract_notams("A1234/26 NOTAMN\nB) XYZ\nE) DANGER AREA", "q")
check("Block mit E), aber unlesbarem B) gilt als nicht verwertbar", _g == [] and _u == 1, (_g, _u))
_g, _u = ai.extract_notams("Navarea IV 123/26\n\n!FDC 6/1234 ZZZ", "q")
check("NAVAREA-/!FDC-Bloecke ohne Kennung zaehlen als nicht verwertbar (ohne Schreibweise)", _g == [] and _u == 2, (_g, _u))
try:
    ai.texts_from_upload("gross.txt", b"x" * (ai.MAX_FILE_BYTES + 1))
    check("Datei ueber 5 MB abgelehnt", False)
except ValueError:
    check("Datei ueber 5 MB abgelehnt", True)

import tempfile
from pathlib import Path as _P
_tmp = _P(tempfile.mkdtemp())
korpus = {}
neu, dup = ai.merge_korpus(korpus, gef)
neu2, dup2 = ai.merge_korpus(korpus, ai.extract_notams(AI_CN[1], "seite2.txt")[0])
check("Korpus: drei neu, dann eine Dublette", (neu, dup, neu2, dup2) == (3, 0, 0, 1), (neu, dup, neu2, dup2))
check("  ... Quellen zusammengefuehrt",
      korpus["A4631/26|2609200354"].quellen == ["test.txt", "seite2.txt"],
      korpus["A4631/26|2609200354"].quellen)
ai.save_korpus(korpus, _tmp / "k.json")
_gel = ai.load_korpus(_tmp / "k.json")
check("Korpus: speichern und laden", set(_gel) == set(korpus))
check("  ... Quellen und Text ueberleben", all(
    _gel[k].quellen == korpus[k].quellen and _gel[k].text == korpus[k].text for k in korpus))
for _nm, _inhalt in (("kaputt_a.json", '{"notams":[{"x":1}]}'), ("kaputt_b.json", '{"notams":5}')):
    (_tmp / _nm).write_text(_inhalt, encoding="utf-8")
    try:
        ai.load_korpus(_tmp / _nm)
        check("Korpus mit kaputter Struktur bricht ab: " + _inhalt, False)
    except ai.ImportStateError as _e:
        check("Korpus mit kaputter Struktur bricht ab: " + _inhalt,
              _nm in str(_e) and (_tmp / _nm).read_text(encoding="utf-8") == _inhalt, str(_e))
    except Exception as _e:
        check("Korpus mit kaputter Struktur bricht ab: " + _inhalt, False, repr(_e))
_alt_replace = os.replace
def _boom(*a, **k):
    raise OSError("boom")
(_tmp / "atom.json").write_text("alt", encoding="utf-8")
os.replace = _boom
try:
    ai.write_json_atomic(_tmp / "atom.json", {"a": 1})
    _fehl = False
except OSError:
    _fehl = True
finally:
    os.replace = _alt_replace
check("write_json_atomic: Fehler vor dem Umbenennen laesst Original, raeumt Temp-Datei auf",
      _fehl and (_tmp / "atom.json").read_text(encoding="utf-8") == "alt"
      and not [f for f in os.listdir(_tmp) if f.startswith("atom") and f != "atom.json"], os.listdir(_tmp))
(_tmp / "kaputt.json").write_text("{ halb", encoding="utf-8")
try:
    ai.read_json(_tmp / "kaputt.json")
    check("unlesbare JSON bricht ab", False)
except ai.ImportStateError:
    check("unlesbare JSON bricht ab", (_tmp / "kaputt.json").read_text(encoding="utf-8") == "{ halb")
check("fehlende JSON ergibt leeren Stand", ai.read_json(_tmp / "fehlt.json") == {})

k2 = {}
bericht = ai.ingest(k2, [("thread_p1.html", SMF.encode("utf-8")), ("kaputt.bin", b"\xff" * 10)], AI_CN[0])
check("Ingest: drei NOTAMs, Zitat nicht als Dublette gezaehlt", (bericht.notams_neu, bericht.dubletten) == (3, 0),
      (bericht.notams_neu, bericht.dubletten))
check("  ... Dateien gezaehlt", bericht.dateien == 2, bericht.dateien)
bericht_klein = ai.ingest({}, [("a.txt", b"x" * 10)], "")
check("  ... kleiner Stapel ohne Fehler", bericht_klein.fehler == [], bericht_klein.fehler)
_alt_max = ai.MAX_BATCH_BYTES
ai.MAX_BATCH_BYTES = 15
try:
    bericht_zu_gross = ai.ingest({}, [("a.txt", b"x" * 10), ("b.txt", b"x" * 10)], "")
finally:
    ai.MAX_BATCH_BYTES = _alt_max
check("Stapel ueber der Grenze ganz abgelehnt",
      bericht_zu_gross.dateien == 0 and bericht_zu_gross.fehler, bericht_zu_gross.fehler)
_alt_file = ai.MAX_FILE_BYTES
ai.MAX_FILE_BYTES = len(AI_CN[1].encode("utf-8")) + 10
try:
    _b = ai.ingest({}, [("big.txt", b"x" * (ai.MAX_FILE_BYTES + 1)), ("ok.txt", AI_CN[1].encode("utf-8"))], "")
finally:
    ai.MAX_FILE_BYTES = _alt_file
check("Ingest: zu grosse Datei meldet Fehler, der Rest laeuft weiter",
      _b.dateien == 1 and len(_b.fehler) == 1 and _b.notams_neu > 0, (_b.dateien, _b.fehler, _b.notams_neu))
check("  ... Dateiname steht nur einmal in der Meldung", _b.fehler[0].count("big.txt") == 1, _b.fehler)
gi = (_P(app.APP_DIR) / ".gitignore").read_text(encoding="utf-8")
check(".gitignore: lokale Importdateien",
      all(n in gi for n in ("archiv_korpus.json", "archiv_import.json", "gcat_launch_cache.tsv")))

VB_GLEICHER_TAG = vandenberg.replace("2609210130", "2609200130").replace("2609210430", "2609200430")
# Ohne Textbeleg, aber in eigener US-FIR: die Nation folgt aus der Geografie -> USA.
US_ZOA = ("W1235/26 NOTAMN Q) ZOA/QRTCA/IV/BO/W/000/999/3444N12034W050 A) ZOA "
          "B) 2609200130 C) 2609200430 E) DANGER AREA ACTIVATED. AREA BOUNDED BY 343000N1203500W - "
          "341500N1201500W - 330000N1200000W - 331500N1204500W F) SFC G) UNL")
# Ohne Textbeleg in einer FIR, die die Referenz nicht kennt: nichts belegt USA -> Pruefliste.
VB_OHNE_BELEG = ohne_beleg.replace("W1234/26", "W1236/26").replace(
    "2609210130", "2609200130").replace("2609210430", "2609200430")
LANG = AI_CN[1].replace("A4631/26", "A4699/26").replace(
    "B)2609200354 C)2609200415", "B)2609010000 C)2611300000")
kt = {}
ai.merge_korpus(kt, ai.extract_notams("\n\n".join(AI_CN[1:] + [VB_GLEICHER_TAG, US_ZOA, VB_OHNE_BELEG, LANG]), "t")[0])
buendel = ai.bundle_days(kt)
from datetime import date as _d
check("Tagesbuendel: 20.09. enthaelt die fuenf kurzen", len(buendel[_d(2026, 9, 20)]) == 5, len(buendel[_d(2026, 9, 20)]))
check("  ... lange Meldung hoechstens 14 Tage",
      _d(2026, 9, 14) in buendel and _d(2026, 9, 15) not in buendel, sorted(buendel)[:3])
_ids19 = {n.notam_id for n in buendel[_d(2026, 9, 19)]}
check("  ... Nachlauf: 19.09. enthaelt die Meldungen vom 20.09. vor 06:00",
      {"A4631/26", "A4632/26", "W1234/26", "W1235/26", "W1236/26"} <= _ids19, sorted(_ids19))
check("  ... Nachlauf: 31.08. enthaelt die lange Meldung",
      "A4699/26" in {n.notam_id for n in buendel[_d(2026, 8, 31)]},
      [n.notam_id for n in buendel[_d(2026, 8, 31)]])
check("Fingerabdruck stabil gegen Reihenfolge",
      ai.day_fingerprint(buendel[_d(2026, 9, 20)]) == ai.day_fingerprint(list(reversed(buendel[_d(2026, 9, 20)]))))

tag20 = ai.analyze_day(_d(2026, 9, 20), buendel[_d(2026, 9, 20)], sp, fir, set(), set())
check("Tagesanalyse: ein chinesischer Kandidat",
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tag20.kandidaten] == [("China", "JSLC")],
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tag20.kandidaten])
check("  ... Kandidat traegt beide Kennungen",
      {"A4631/26", "A4632/26"} <= set(k for k in tag20.kandidaten[0]["notam_ids"]), tag20.kandidaten[0]["notam_ids"])
check("  ... US-Starts gezaehlt, nicht gefuehrt", tag20.usa == 2, tag20.usa)
check("  ... weder W1234/26 noch W1235/26 auf der Pruefliste",
      not {"W1234/26", "W1235/26"} & {p["notam_id"] for p in tag20.pruefliste},
      [p["notam_id"] for p in tag20.pruefliste])
check("  ... unbekannte FIR ohne Beleg bleibt auf der Pruefliste",
      [p["notam_id"] for p in tag20.pruefliste] == ["W1236/26"], [p["notam_id"] for p in tag20.pruefliste])
check("  ... Kandidatenschluessel = archive_key",
      tag20.kandidaten[0]["key"] == app.archive_key(tag20.kandidaten[0]["row"]))
tag19 = ai.analyze_day(_d(2026, 9, 19), buendel[_d(2026, 9, 19)], sp, fir, set(), set())
check("Vortag: Nachlauf mit A4631/26 erzeugt keinen Kandidaten",
      "A4631/26" in _ids19 and tag19.kandidaten == [] and len(tag20.kandidaten) == 1,
      ([k["notam_ids"] for k in tag19.kandidaten], len(tag20.kandidaten)))
check("  ... im Nachlauf weder US-Starts noch Ausgeblendete gezaehlt",
      tag19.usa == 0 and tag19.ausgeblendet == 0, (tag19.usa, tag19.ausgeblendet))
check("  ... Pruefposten nur im Buendel seines Starttags",
      "W1236/26" in {p["notam_id"] for p in tag20.pruefliste}
      and "W1236/26" not in {p["notam_id"] for p in tag19.pruefliste},
      [p["notam_id"] for p in tag19.pruefliste])

# Ausgeblendetes Mitglied: weder in den Kennungen noch in der Archivzeile.
_k4632 = app.event_key(AI_CN[2])
tag20_ohne = ai.analyze_day(_d(2026, 9, 20), buendel[_d(2026, 9, 20)], sp, fir, set(), {_k4632})
check("Ausgeblendetes Mitglied faellt aus Kandidat und Zeile",
      len(tag20_ohne.kandidaten) == 1
      and "A4632/26" not in tag20_ohne.kandidaten[0]["notam_ids"]
      and "A4632/26" not in tag20_ohne.kandidaten[0]["row"]["NOTAM"]
      and "A4631/26" in tag20_ohne.kandidaten[0]["notam_ids"],
      [(k["notam_ids"], k["row"]["NOTAM"]) for k in tag20_ohne.kandidaten])

# Start ueber Mitternacht: der Nachlauf liefert den vollstaendigen Start im
# Vortag, das eigene Buendel des 21.09. ein Bruchstueck. drop_subsumed raeumt auf.
MN1 = AI_CN[1].replace("B)2609200354 C)2609200415", "B)2609202345 C)2609202359")
MN2 = AI_CN[2].replace("B)2609200356 C)2609200435", "B)2609210005 C)2609210040")
kmn = {}
ai.merge_korpus(kmn, ai.extract_notams(MN1 + "\n\n" + MN2, "t")[0])
bmn = ai.bundle_days(kmn)
mn_alle = [k for t in (_d(2026, 9, 20), _d(2026, 9, 21))
           for k in ai.analyze_day(t, bmn[t], sp, fir, set(), set()).kandidaten]
check("Mitternacht: vor dem Aufraeumen zwei Kandidaten", len(mn_alle) == 2,
      [k["notam_ids"] for k in mn_alle])
mn_rest = ai.drop_subsumed(mn_alle)
check("  ... danach nur der vollstaendige Start",
      [set(k["notam_ids"]) for k in mn_rest] == [{"A4631/26", "A4632/26"}],
      [k["notam_ids"] for k in mn_rest])
_ds = ai.drop_subsumed([{"notam_ids": ["a", "b"]}, {"notam_ids": ["a"]}, {"notam_ids": ["c"]},
                        {"notam_ids": ["c"]}])
check("drop_subsumed: echte Teilmenge faellt, gleiche Mengen bleiben",
      [k["notam_ids"] for k in _ds] == [["a", "b"], ["c"], ["c"]], _ds)
check("  ... LANG bleibt auf 14 Tage begrenzt",
      max(t for t, l in buendel.items() if any(n.notam_id == "A4699/26" for n in l)) == _d(2026, 9, 14))

kommentiert = {}
ai.merge_korpus(kommentiert, ai.extract_notams(
    AI_CN[1] + "\nprobably Starship from Boca Chica\n\n" + AI_CN[2] + "\nSTARSHIP FLIGHT 12", "t")[0])
tk = ai.analyze_day(_d(2026, 9, 20), list(kommentiert.values()), sp, fir, set(), set())
check("Pflichtfall: Starship-Kommentar aendert die Zuordnung nicht",
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tk.kandidaten] == [("China", "JSLC")],
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tk.kandidaten])

GCAT_KOPF = "#Launch_Tag\tLaunch_JD\tLaunch_Date\tLV_Type\tVariant\tFairing\tFlight_ID\tFlight\tMission\tFlightCode\tPlatform\tLaunch_Site\tLaunch_Pad\tAscent_Site\tAscent_Pad\tPerigee\tApogee\tApoflag\tInc\tAzimuth\n# Updated\n"
def _gz(tag, datum, lv, flight, mission, site, inc="-", az="-", platform="-"):
    return "\t".join([tag, "0", datum, lv, "-", "-", "-", flight, mission, "-", platform, site, "-", "-", "-", "-", "-", " ", inc, az]) + "\n"
GCAT_TXT = GCAT_KOPF + "".join([
    _gz("2026-201 ", "2026 Sep 20 0356", "Chang Zheng 2D/YZ-3", "Yaogan 45", "-", "JQ", " 97.0 ", " 189.0"),
    _gz("2026-202 ", "2026 Sep 20 0354:12", "Falcon 9", "Starlink 11-2", "Starlink 11-2", "VSFBS"),
    _gz("2026-S12 ", "2026 Sep 20 0400", "Iran SRBM", "-", "-", "IRAN"),
    _gz("2025-E01 ", "2025 Mar  1", "Kuaizhou-1A", "Unknown", "-", "JQ"),
    _gz("2019-001 ", "2019 Jan 10 1611", "Chang Zheng 3B", "ChinaSat 2D", "-", "XSC"),
    _gz("2023-200 ", "2023 Dec  5 1924?", "Jielong-3", "WHJSW 03", "-", "YJ", platform="DFHT"),
])
gs = ai.parse_gcat(GCAT_TXT)
check("GCAT: Orbitalstarts 2020-2026, ohne Suborbital", [s.tag for s in gs] == ["2026-201", "2026-202", "2025-E01", "2023-200"],
      [s.tag for s in gs])
check("  ... Uhrzeit gelesen", gs[0].zeit.strftime("%Y-%m-%d %H:%M") == "2026-09-20 03:56" and not gs[0].nur_datum)
check("  ... nur Tagesdatum erkannt", gs[2].nur_datum, gs[2].zeit)
check("  ... Fragezeichen toleriert", gs[3].zeit.strftime("%H:%M") == "19:24", gs[3].zeit)
check("  ... Payload faellt auf Flight zurueck", gs[0].nutzlast == "Yaogan 45", gs[0].nutzlast)
check("  ... Inklination und Azimut", (gs[0].inklination, gs[0].azimut) == (97.0, 189.0))
check("  ... Sekunden gelesen", gs[1].zeit.second == 12, gs[1].zeit)
GCAT_TXT2 = GCAT_KOPF + "".join([
    _gz("2024-F01 ", "2024 Mar  3 1200", "Zhuque-3", "Test", "-", "SUNAN?"),
    _gz("2026-210 ", "2026 Feb 30 0100", "Falcon 9", "Unmoeglich", "-", "VSFBS"),
    _gz("2026-211 ", "2026 Sep 20 2460", "Falcon 9", "Unmoeglich 2", "-", "VSFBS"),
    _gz("2026-212 ", "2026 Sep 20 03", "Falcon 9", "Grob", "-", "VSFBS"),
    _gz("2026-213 ", "2026 Sep 20 0356:1", "Falcon 9", "Sekunde", "-", "VSFBS"),
    _gz("2026-214 ", "2026 Sep 21 0100", "Falcon 9", "Gut", "-", "VSFBS"),
])
gs2 = ai.parse_gcat(GCAT_TXT2)
check("GCAT: F-Tag bleibt, unmoegliche/grobe Datumsangaben werden uebersprungen",
      [s.tag for s in gs2] == ["2024-F01", "2026-214"], [s.tag for s in gs2])
check("  ... Fragezeichen am Startplatz entfernt", gs2[0].site == "SUNAN", gs2[0].site)
sites = ai.load_gcat_sites()
check("Referenz gcat_startplaetze.csv: JQ -> JSLC, China", sites.get("JQ") == (["JSLC"], "China"), sites.get("JQ"))
check("  ... Baikonur unter GIK-5", sites.get("GIK-5") == (["BAIK"], "Russland"), sites.get("GIK-5"))
check("  ... Seegebiet ohne festen Platz", sites.get("ECS") == ([], "China"), sites.get("ECS"))

aufgerufen = []
class _Antwort:
    def __init__(self, daten): self.daten = daten
    def read(self, n=-1): return self.daten
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _opener_ok(req, timeout=0):
    aufgerufen.append(req.full_url); return _Antwort(GCAT_TXT.encode("utf-8"))
def _opener_fehler(req, timeout=0):
    raise OSError("offline")
cache = _tmp / "gcat.tsv"
liste, status = ai.load_gcat(refresh=True, cache=cache, opener=_opener_ok)
check("GCAT-Abruf nur von der festen Adresse", aufgerufen == [ai.GCAT_URL], aufgerufen)
check("  ... Cache geschrieben", cache.exists() and len(liste) == 4, status)
liste2, status2 = ai.load_gcat(refresh=True, cache=cache, opener=_opener_fehler)
check("offline: Cache bleibt in Gebrauch", liste2 is not None and len(liste2) == 4, status2)
liste3, status3 = ai.load_gcat(refresh=True, cache=_tmp / "nichts.tsv", opener=_opener_fehler)
check("offline ohne Cache: nicht verfuegbar", liste3 is None, status3)

# Kaputte Daten: Cache mit unmoeglichem Datum, Muell-Refresh, Weiterleitung, Uebergroesse
cache_k = _tmp / "gcat_kaputt.tsv"
cache_k.write_text(GCAT_TXT2, encoding="utf-8")
lk, sk = ai.load_gcat(refresh=False, cache=cache_k)
check("GCAT: Cache mit unmoeglichem Datum bleibt ladbar", lk is not None and len(lk) == 2, sk)
cache_g = _tmp / "gcat_gut.tsv"
cache_g.write_bytes(GCAT_TXT.encode("utf-8"))
vorher = cache_g.read_bytes()
lj, sj = ai.load_gcat(refresh=True, cache=cache_g,
                      opener=lambda req, timeout=0: _Antwort(b"<html>captive portal</html>"))
check("GCAT: Muell-Download ersetzt guten Cache nicht",
      cache_g.read_bytes() == vorher and lj is not None and len(lj) == 4 and "Download failed" in sj, sj)
check("  ... keine tmp-Reste", not list(_tmp.glob("gcat_gut*tmp*")) and not list(_tmp.glob("*.tmp")), list(_tmp.iterdir()))
class _AntwortUmgeleitet(_Antwort):
    def geturl(self): return "https://evil.example/launch.tsv"
lu, su = ai.load_gcat(refresh=True, cache=cache_g,
                      opener=lambda req, timeout=0: _AntwortUmgeleitet(GCAT_TXT.encode("utf-8")))
check("GCAT: Weiterleitung auf anderen Host wird abgelehnt",
      cache_g.read_bytes() == vorher and "Download failed" in su, su)
_alt_max = ai.MAX_GCAT_BYTES
ai.MAX_GCAT_BYTES = 100
try:
    lm, sm = ai.load_gcat(refresh=True, cache=cache_g, opener=_opener_ok)
finally:
    ai.MAX_GCAT_BYTES = _alt_max
check("GCAT: uebergrosse Antwort wird abgelehnt",
      cache_g.read_bytes() == vorher and "Download failed" in sm, sm)
check("GCAT: Statustexte", "Download failed" in status2 and "GCAT (J. McDowell, CC-BY)" in status, (status, status2))

kand = dict(tag20.kandidaten[0])
abg = ai.match_candidate(kand, gs, sites)
check("Abgleich: eindeutig", abg.status == ai.STATUS_EINDEUTIG, (abg.status, abg.warnungen, abg.hinweise))
check("  ... Treffer ist der chinesische Start", abg.treffer[0].tag == "2026-201")
check("  ... keine Warnung bei passender Bahn", abg.warnungen == [], abg.warnungen)
schief = dict(kand, inklination=60.0)
check("Abweichung ueber 10 Grad wird gewarnt", ai.match_candidate(schief, gs, sites).warnungen != [])
check("ohne Startliste: kein Abgleich", ai.match_candidate(kand, None, sites).status == ai.STATUS_KEIN_ABGLEICH)
leer_tag = dict(kand, fenster=["2026-09-21T03:00:00+00:00", "2026-09-21T03:30:00+00:00"])
abg0 = ai.match_candidate(leer_tag, gs, sites)
check("kein Treffer: kein Flug", abg0.status == ai.STATUS_KEIN_FLUG, abg0.status)
nur_tag = dict(kand, fenster=["2025-03-01T10:00:00+00:00", "2025-03-01T10:20:00+00:00"])
check("nur Tagesdatum: nie eindeutig", ai.match_candidate(nur_tag, gs, sites).status == ai.STATUS_MEHRDEUTIG)
see = dict(kand, seestart=True, row=dict(kand["row"], Weltraumbahnhof=""),
           fenster=["2023-12-05T19:00:00+00:00", "2023-12-05T19:40:00+00:00"])
abg_see = ai.match_candidate(see, gs, sites)
check("Seestart: Treffer ueber Land, aber nie eindeutig",
      abg_see.status == ai.STATUS_SEESTART and len(abg_see.treffer) == 1, abg_see.status)
fremd = dict(kand, row=dict(kand["row"], Weltraumbahnhof="XSLC"))
abg_f = ai.match_candidate(fremd, gs, sites)
check("Hinweis nennt nicht zugeordnete GCAT-Plaetze im Fenster",
      any("VSFBS" in h for h in abg_f.hinweise), abg_f.hinweise)
veh = app.load_vehicles(str(app.VEHICLE_CSV))
check("Rakete: Chang Zheng 2D/YZ-3 -> CZ-2D", ai.vehicle_code_for("Chang Zheng 2D/YZ-3", veh) == "CZ-2D")
check("Rakete: Soyuz-2-1A -> Soyuz-2.1a", ai.vehicle_code_for("Soyuz-2-1A", veh) == "Soyuz-2.1a")
_alias = {ai._norm_name("PSLV-XL"): "PSLV", ai._norm_name("Cheonlima-1"): "Chollima-1",
          ai._norm_name("Geist-1"): "GEIST"}
check("Schreibweise: PSLV-XL -> PSLV", ai.vehicle_code_for("PSLV-XL", veh, _alias) == "PSLV")
check("Schreibweise: Cheonlima-1 -> Chollima-1", ai.vehicle_code_for("Cheonlima-1", veh, _alias) == "Chollima-1")
check("Alias auf unbekanntes Kuerzel bleibt leer", ai.vehicle_code_for("Geist-1", veh, _alias) == "")
check("Rakete ohne Entsprechung bleibt leer", ai.vehicle_code_for("NK Kerolox LV", veh, {}) == "")
_dateialias = ai.load_gcat_vehicle_aliases()
check("Referenz gcat_traegersysteme.csv: vier Schreibweisen",
      _dateialias.get(ai._norm_name("Zoljanah")) == "Zuljanah" and len(_dateialias) == 4, _dateialias)
check("Schreibweisen werden je Datei und Aenderungszeit nur einmal gelesen",
      ai.load_gcat_vehicle_aliases() is _dateialias)

# Fix-Runde 1: Warnpfade, Mehrdeutigkeit, schreibgeschuetzter Alias-Speicher, kaputte Alias-CSV
import dataclasses
from datetime import timedelta
_treffer0 = ai.match_candidate(kand, gs, sites).treffer[0]
_land0 = sites[_treffer0.site][1]
abg_nat = ai.match_candidate(dict(kand, nation="Russland"), gs, sites)
check("Warnung: Land weicht vom GCAT-Platz ab",
      any(_land0 in w and "Russland" in w for w in abg_nat.warnungen), abg_nat.warnungen)
_g_az = dataclasses.replace(_treffer0, azimut=5.0, inklination=None)
_k_az = dict(kand, inklination=None)
check("Azimut 355 vs 5 (10 Grad, Umlauf): keine Warnung",
      ai.match_candidate(dict(_k_az, azimut=355.0), [_g_az], sites).warnungen == [])
_w_az = ai.match_candidate(dict(_k_az, azimut=350.0), [_g_az], sites).warnungen
check("Azimut 350 vs 5 (15 Grad, Umlauf): Warnung", len(_w_az) == 1 and "Azimuth" in _w_az[0], _w_az)
_zweit = dataclasses.replace(_treffer0, tag="2026-999", zeit=_treffer0.zeit + timedelta(minutes=5))
abg_zwei = ai.match_candidate(kand, [_treffer0, _zweit], sites)
check("zwei Zeit-Treffer am Platz: mehrdeutig mit beiden",
      abg_zwei.status == ai.STATUS_MEHRDEUTIG and len(abg_zwei.treffer) == 2
      and {t.tag for t in abg_zwei.treffer} == {"2026-201", "2026-999"}, (abg_zwei.status, abg_zwei.treffer))
_dateialias2 = ai.load_gcat_vehicle_aliases()
try:
    _dateialias2["x"] = "y"
    _mut = "no error"
except TypeError:
    _mut = "TypeError"
check("Alias-Speicher ist schreibgeschuetzt", _mut == "TypeError", _mut)
check("Alias-Speicher: Explizites Dict funktioniert weiter",
      ai.vehicle_code_for("PSLV-XL", veh, {ai._norm_name("PSLV-XL"): "PSLV"}) == "PSLV")
check("Rakete: bekannte Namen unveraendert (Name, Alternativname, Kuerzel)",
      [ai.vehicle_code_for(n, veh, {}) for n in ("Chang Zheng 2D/YZ-3", "Soyuz-2-1A", "CZ-2D", "NK Kerolox LV")]
      == ["CZ-2D", "Soyuz-2.1a", "CZ-2D", ""])
_bad_alias = _tmp / "alias_kaputt.csv"
_bad_alias.write_text("GCAT,Name\nFoo,Bar\n", encoding="utf-8")
try:
    ai.load_gcat_vehicle_aliases(_bad_alias)
    _fehler = None
except ai.ImportStateError as exc:
    _fehler = str(exc)
except Exception as exc:
    _fehler = "wrong type: {!r}".format(exc)
check("kaputte Alias-CSV: ImportStateError mit Datei und Spalte",
      _fehler is not None and "alias_kaputt.csv" in _fehler and "Abkürzung" in _fehler, _fehler)

# Aufgabe 6: Importzustand, Wiederaufnahme, Bestaetigen, Sammelbestaetigung
zst = ai.load_state(_tmp / "s.json")
kx = {}
ai.merge_korpus(kx, ai.extract_notams("\n\n".join(AI_CN[1:] + [VB_GLEICHER_TAG]), "seite1.html#msg_1")[0])
check("Neuauswertung: zwei Tage (20.09. und Nachlauf im 19.09.)", ai.reevaluate(kx, zst, sp, fir) == 2)
_stand_json = _json.dumps(zst, sort_keys=True, default=str)
check("  ... zweiter Lauf wertet nichts neu aus", ai.reevaluate(kx, zst, sp, fir) == 0)
check("  ... und aendert den Zustand nicht", _json.dumps(zst, sort_keys=True, default=str) == _stand_json)
kl = ai.candidates(zst)
check("Kandidatenliste: ein Start", len(kl) == 1 and kl[0]["entscheidung"] is None, kl)
check("  ... US gezaehlt", ai.totals(zst)["usa"] == 1, ai.totals(zst))
sammel = ai.bulk_candidates(kl, gs, sites, veh)
check("Sammelbestaetigung waehlt den eindeutigen", [(k["key"], r, p) for k, r, p, _ in sammel]
      == [(kl[0]["key"], "CZ-2D", "Yaogan 45")], [(r, p) for _, r, p, _ in sammel])
check("  ... nicht mit Warnung", ai.bulk_candidates([dict(kl[0], inklination=60.0)], gs, sites, veh) == [])
check("  ... nicht mehrdeutig", ai.bulk_candidates(kl, [_treffer0, _zweit], sites, veh) == [])
archiv_t = _tmp / "archiv.csv"
check("Bestaetigen schreibt eine Zeile", ai.confirm_many(zst, sammel, archiv_t) == 1)
a1 = app.load_archive(archiv_t)
check("  ... mit Rakete und Payload", (a1.iloc[0]["Trägersystem"], a1.iloc[0]["Payload"]) == ("CZ-2D", "Yaogan 45"),
      a1.iloc[0].to_dict())
check("  ... Quelle im Nebenbestand", zst["entscheidungen"][kl[0]["key"]]["quellen"] == ["seite1.html#msg_1"])
check("  ... danach nicht mehr in der Sammelauswahl", ai.bulk_candidates(ai.candidates(zst), gs, sites, veh) == [])
ai.save_state(zst, _tmp / "s.json")
check("Zustand speichern und laden", ai.load_state(_tmp / "s.json")["entscheidungen"] == zst["entscheidungen"])
check("leere Auswahl schreibt nichts", ai.confirm_many(zst, [], _tmp / "nie.csv") == 0 and not (_tmp / "nie.csv").exists())

# Kaputte Zustandsdatei (gueltiges JSON, falsche Typen): Abbruch, Datei bleibt unberuehrt
for _nm, _inhalt in (("st_a.json", '{"tage": []}'), ("st_b.json", '{"entscheidungen": 5}'),
                     ("st_c.json", '{"review_bestaetigt": "abc"}'), ("st_d.json", '{"review_ausgeblendet": {"x": 1}}'),
                     ("st_e.json", '{"tage": {"2026-09-20": []}}'),
                     ("st_f.json", '{"tage": {"2026-09-20": {"fingerprint": "f", "kandidaten": [], "pruefliste": [5]}}}'),
                     ("st_g.json", '{"entscheidungen": {"k": "confirmed"}}')):
    (_tmp / _nm).write_text(_inhalt, encoding="utf-8")
    try:
        ai.load_state(_tmp / _nm)
        check("Zustand mit kaputter Struktur bricht ab: " + _inhalt, False)
    except ai.ImportStateError as _e:
        check("Zustand mit kaputter Struktur bricht ab: " + _inhalt,
              _nm in str(_e) and (_tmp / _nm).read_text(encoding="utf-8") == _inhalt, str(_e))
    except Exception as _e:
        check("Zustand mit kaputter Struktur bricht ab: " + _inhalt, False, repr(_e))

# Eine weitere Zone desselben Starts kommt spaeter dazu -> aktualisiert, ersetzt die alte Zeile
dritte = AI_CN[2].replace("A4632/26", "A4640/26").replace(
    "N293700E0980200-N293400E0983400-N284400E0982700-N284800E0975500",
    "N281000E0974500-N280800E0981500-N274000E0981000-N274200E0974000")
ai.merge_korpus(kx, ai.extract_notams(dritte, "seite2.html#msg_9")[0])
ai.reevaluate(kx, zst, sp, fir)
neu_k = [k for k in ai.candidates(zst) if k["entscheidung"] is None]
check("weitere Zone: Kandidat 'aktualisiert'",
      len(neu_k) == 1 and neu_k[0]["ersetzt"] == [kl[0]["key"]], [(k["key"], k["ersetzt"]) for k in neu_k])
check("  ... nicht in der Sammelauswahl", ai.bulk_candidates(neu_k, gs, sites, veh) == [])
ai.confirm_many(zst, [(neu_k[0], "CZ-2D", "Yaogan 45", None)], archiv_t)
a2 = app.load_archive(archiv_t)
check("  ... ersetzt die alte Archivzeile statt einer zweiten", len(a2) == 1 and "A4640/26" in a2.iloc[0]["NOTAM"],
      a2["NOTAM"].tolist())
check("  ... alter Schluessel als ersetzt vermerkt",
      zst["entscheidungen"][kl[0]["key"]] == {"status": "replaced", "durch": neu_k[0]["key"]})

# Bestaetigen wirkt auch fuer einen frueher entfernten Schluessel
check("Bestaetigen ignoriert archiv_removed", "entfernt=set()" in (_P(app.APP_DIR) / "archiv_import.py").read_text(encoding="utf-8"))

# Fixrunde 1: Bestaetigung erst nach geprueftem Schreiben, Ersatz mehrerer Vorgaenger
zf = ai.load_state(_tmp / "f.json")
ai.reevaluate(kx, zf, sp, fir)
kfl = ai.candidates(zf)
kf = kfl[0]
check("Sammelbestaetigung: GCAT-Rakete ohne Kuerzel -> einzeln bestaetigen",
      ai.bulk_candidates(kfl, [dataclasses.replace(_treffer0, rakete="Unbekannte Rakete XQ")], sites, veh) == [],
      [(r, p) for _, r, p, _ in ai.bulk_candidates(
          kfl, [dataclasses.replace(_treffer0, rakete="Unbekannte Rakete XQ")], sites, veh)])
_ord = _tmp / "archiv_ist_ordner"
_ord.mkdir()
_vorher = _copy.deepcopy(zf["entscheidungen"])
try:
    ai.confirm_many(zf, [(kf, "CZ-2D", "Yaogan 45", None)], _ord)
    _fehler = None
except ai.ImportStateError as exc:
    _fehler = str(exc)
except Exception as exc:
    _fehler = "wrong type: {!r}".format(exc)
check("Bestaetigen: Archiv nicht geschrieben -> ImportStateError mit Dateiname",
      _fehler is not None and _ord.name in _fehler and not _fehler.startswith("wrong type"), _fehler)
check("  ... Zustand unveraendert", zf["entscheidungen"] == _vorher, zf["entscheidungen"])
check("  ... kein Kandidat entschieden", all(k["entscheidung"] is None for k in ai.candidates(zf)))
_entfernt_args = []
_merge_orig = app.merge_archive
def _merge_spion(bestand, neue, entfernt=None):
    _entfernt_args.append(entfernt)
    return _merge_orig(bestand, neue, entfernt=entfernt)
archiv_f = _tmp / "archiv_f.csv"
app.merge_archive = _merge_spion
try:
    ai.confirm_many(zf, [(kf, "CZ-2D", "Yaogan 45", None)], archiv_f)
finally:
    app.merge_archive = _merge_orig
check("Bestaetigen uebergibt merge_archive kein archiv_removed", _entfernt_args == [set()], _entfernt_args)
_persist_orig = app.persist_archive
_vorher = _copy.deepcopy(zf["entscheidungen"])
app.persist_archive = lambda path, df: None
try:
    ai.remove_orphan(zf, kf["key"], archiv_f)
    _fehler = None
except ai.ImportStateError as exc:
    _fehler = str(exc)
except Exception as exc:
    _fehler = "wrong type: {!r}".format(exc)
finally:
    app.persist_archive = _persist_orig
check("Remove: Archiv nicht geschrieben -> ImportStateError mit Dateiname",
      _fehler is not None and archiv_f.name in _fehler and not _fehler.startswith("wrong type"), _fehler)
check("  ... Zustand unveraendert, Zeile noch da",
      zf["entscheidungen"] == _vorher and len(app.load_archive(archiv_f)) == 1, zf["entscheidungen"])
try:
    ai.keep_orphan(zf, "gibt-es-nicht")
    _fehler = None
except ai.ImportStateError as exc:
    _fehler = str(exc)
except Exception as exc:
    _fehler = "wrong type: {!r}".format(exc)
check("Keep mit unbekanntem Schluessel -> ImportStateError",
      _fehler is not None and not _fehler.startswith("wrong type"), _fehler)
zf["entscheidungen"][kf["key"]]["behalten"] = True
ai.reevaluate(kx, zf, sp, fir)
check("Keep verfaellt, sobald der Start wieder erkannt wird",
      "behalten" not in zf["entscheidungen"][kf["key"]], zf["entscheidungen"][kf["key"]])
_tage_f = zf["tage"]
zf["tage"] = {iso: dict(t, kandidaten=[]) for iso, t in _tage_f.items()}
check("  ... und erneut verloren steht er wieder auf der Liste",
      [k for k, _ in ai.orphans(zf)] == [kf["key"]], ai.orphans(zf))
zf["tage"] = _tage_f

# Zwei bestaetigte Vorgaenger fallen in einem neu gruppierten Kandidaten zusammen
_roh = zf["tage"]["2026-09-20"]["kandidaten"][0]
_r1 = dict(_roh["row"], NOTAM=_roh["notam_ids"][0])
_r2 = dict(_roh["row"], NOTAM=_roh["notam_ids"][1])
_k1, _k2 = app.archive_key(_r1), app.archive_key(_r2)
archiv_z = _tmp / "archiv_z.csv"
app.persist_archive(archiv_z, app.merge_archive(None, [_r1, _r2]))
zz = ai.load_state(_tmp / "z.json")
zz["tage"]["2026-09-20"] = {"fingerprint": "f", "kandidaten": [_roh], "pruefliste": [], "usa": 0, "ausgeblendet": 0}
for _k, _r in ((_k1, _r1), (_k2, _r2)):
    zz["entscheidungen"][_k] = {"status": "confirmed", "rakete": "CZ-2D", "payload": "", "gcat": "",
                                "notam_ids": [_r["NOTAM"]], "quellen": ["alt"]}
_kz = ai.candidates(zz)
check("zwei Vorgaenger: beide im Ersatzvermerk",
      len(_kz) == 1 and _kz[0]["ersetzt"] == sorted([_k1, _k2]), [k["ersetzt"] for k in _kz])
check("  ... nicht in der Sammelauswahl", ai.bulk_candidates(_kz, gs, sites, veh) == [])
ai.confirm_many(zz, [(_kz[0], "CZ-2D", "Yaogan 45", None)], archiv_z)
_az = app.load_archive(archiv_z)
check("  ... beide Zeilen durch eine ersetzt",
      [app.archive_key(dict(r)) for _, r in _az.iterrows()] == [_roh["key"]], _az["NOTAM"].tolist())
check("  ... beide als ersetzt vermerkt",
      all(zz["entscheidungen"][_k] == {"status": "replaced", "durch": _roh["key"]} for _k in (_k1, _k2)),
      zz["entscheidungen"])

# Verwerfen
zr = ai.load_state(_tmp / "r.json")
ai.reevaluate(kx, zr, sp, fir)
_kr = ai.candidates(zr)[0]["key"]
ai.reject(zr, _kr)
check("Verwerfen: Entscheidung gesetzt, nicht in der Sammelauswahl",
      ai.candidates(zr)[0]["entscheidung"] == {"status": "discarded"}
      and ai.bulk_candidates(ai.candidates(zr), gs, sites, veh) == [])

MITTERNACHT = [AI_CN[1].replace("B)2609200354 C)2609200415", "B)2609192350 C)2609200011"),
               AI_CN[2].replace("B)2609200356 C)2609200435", "B)2609200002 C)2609200041")]
km = {}
ai.merge_korpus(km, ai.extract_notams("\n\n".join(MITTERNACHT), "m")[0])
zm = ai.load_state(_tmp / "m.json")
ai.reevaluate(km, zm, sp, fir)
check("Start ueber Mitternacht: ein Kandidat mit beiden Zonen",
      [k["notam_ids"] for k in ai.candidates(zm)] == [["A4631/26", "A4632/26"]],
      [k["notam_ids"] for k in ai.candidates(zm)])
check("  ... mit dem Datum des ersten Tages",
      ai.candidates(zm)[0]["row"]["Startdatum"] == "19.09.2026")
# Bruchstueck aus einem anderen Tag wird ueber drop_subsumed verworfen
_kmn = ai.candidates(zm)[0]
zm2 = {"tage": {"2026-09-19": {"kandidaten": [dict(_kmn, notam_ids=["A1/26", "A2/26"], key="v1")]},
                "2026-09-20": {"kandidaten": [dict(_kmn, notam_ids=["A2/26"], key="v2")]}},
       "entscheidungen": {}}
check("candidates: Bruchstueck verworfen", [k["key"] for k in ai.candidates(zm2)] == ["v1"],
      [k["key"] for k in ai.candidates(zm2)])

# Erkennungsstand und nicht mehr erkannte Starts
check("Erkennungsstand nach dem ersten Lauf gesetzt", not ai.is_stale(zst), zst.get("erkennungsstand"))
check("  ... anderer Stand -> Neuauswertung faellig", ai.is_stale(zst, stamp="anders"))
check("  ... leerer Zustand ist nie veraltet", not ai.is_stale(ai.load_state(_tmp / "leer.json"), stamp="anders"))
_ref = _tmp / "ref.csv"
_ref.write_text("a", encoding="utf-8")
_st1 = ai.detection_stamp([_ref])
_ref.write_text("b", encoding="utf-8")
check("Erkennungsstand folgt dem Inhalt der Referenzen", ai.detection_stamp([_ref]) != _st1)
zst["erkennungsstand"] = "alt"
ai.reevaluate(kx, zst, sp, fir, erzwingen=["2026-09-20"])
check("  ... Teillauf setzt ihn nicht", zst["erkennungsstand"] == "alt")
_schritte = []
check("alle Tage neu ausgewertet", ai.reevaluate(kx, zst, sp, fir, alle=True,
      fortschritt=lambda n, g: _schritte.append((n, g))) == len(_schritte) and _schritte[-1][0] == _schritte[-1][1],
      _schritte)
check("  ... vollstaendiger Lauf setzt ihn", not ai.is_stale(zst), zst["erkennungsstand"])
check("keine verwaisten Starts, solange sie erkannt werden", ai.orphans(zst) == [], ai.orphans(zst))
_tage_vorher = zst["tage"]
zst["tage"] = {iso: dict(t, kandidaten=[]) for iso, t in _tage_vorher.items()}
_waisen = ai.orphans(zst)
check("nicht mehr erkannt -> 'No longer recognised'", [k for k, _ in _waisen] == [neu_k[0]["key"]], _waisen)
check("  ... Archiv bleibt ohne Entscheidung unberuehrt", len(app.load_archive(archiv_t)) == 1)
ai.keep_orphan(zst, neu_k[0]["key"])
check("  ... Keep nimmt ihn von der Liste, Archiv bleibt", ai.orphans(zst) == [] and len(app.load_archive(archiv_t)) == 1)
zst["entscheidungen"][neu_k[0]["key"]].pop("behalten")
ai.remove_orphan(zst, neu_k[0]["key"], archiv_t)
check("  ... Remove loescht die Archivzeile", app.load_archive(archiv_t).empty)
check("  ... und vermerkt es", zst["entscheidungen"][neu_k[0]["key"]] == {"status": "removed"})
zst["tage"] = _tage_vorher

# Pruefliste: reine Zustandsfunktionen, mit einem synthetischen Tag geprueft
zp = ai.load_state(_tmp / "p.json")
_p = {"event_key": "ek1", "schluessel": "X1/26|2609200000", "notam_id": "X1/26", "tag": "2026-09-20",
      "grund": "Foreign airspace without evidence.", "text": "X1/26 ...", "quellen": ["p"]}
zp["tage"]["2026-09-20"] = {"fingerprint": "f", "kandidaten": [], "pruefliste": [_p], "usa": 0, "ausgeblendet": 0}
zp["tage"]["2026-09-21"] = {"fingerprint": "g", "kandidaten": [], "pruefliste": [dict(_p, tag="2026-09-21")],
                            "usa": 0, "ausgeblendet": 0}
check("Pruefliste: mehrtaegiger Fall nur einmal", len(ai.review_items(zp)) == 1, ai.review_items(zp))
zp["review_bestaetigt"].append("ek1")
check("  ... bestaetigt verschwindet", ai.review_items(zp) == [])
zp["tage"]["2026-09-20"]["pruefliste"] = [dict(_p, grund=ai.GRUND_OHNE_PLATZ)]
check("  ... bestaetigt ohne Startplatz bleibt sichtbar", len(ai.review_items(zp)) == 1)
ai.review_hide(zp, "ek1")
check("  ... Ausblenden entfernt ihn", ai.review_items(zp) == [], ai.review_items(zp))
check("  ... und zaehlt ihn als ausgeblendet", ai.totals(zp)["ausgeblendet"] == 2, ai.totals(zp))

# Space Launch aus der Pruefliste: Bestaetigung gemerkt, Tag erzwungen neu ausgewertet
zl = ai.load_state(_tmp / "l.json")
ai.reevaluate(kx, zl, sp, fir)
zl["tage"]["2026-09-20"]["kandidaten"] = []
ai.review_launch(zl, kx, "ek9", "2026-09-20", sp, fir)
check("Space Launch: Bestaetigung gemerkt, Tag trotz gleichem Fingerabdruck neu ausgewertet",
      zl["review_bestaetigt"] == ["ek9"] and len(zl["tage"]["2026-09-20"]["kandidaten"]) == 1,
      (zl["review_bestaetigt"], zl["tage"]["2026-09-20"]["kandidaten"]))

quelle_ai = (_P(app.APP_DIR) / "archiv_import.py").read_text(encoding="utf-8")
check("Archiv-Import fasst die Tageslage nicht an",
      all(w not in quelle_ai for w in ("manual_notams", "WORKSPACE_FILE", "save_workspace", "session_state")))

# --- Aufgabe 7: Reiter "Archive Import", nur lokal sichtbar ---
check("oeffentliche Fassung erkannt", app.is_public_deployment(_P("/mount/src/notam-parser")))
check("lokal nicht oeffentlich", not app.is_public_deployment(_P("/Users/x/NOTAM Parser")))
quelle_app = (_P(app.APP_DIR) / "app.py").read_text(encoding="utf-8")
import inspect as _inspect
tab_src = _inspect.getsource(app._archive_import_tab)
kand_src = _inspect.getsource(app._archive_import_candidate)
check("Reiter ohne unsafe_allow_html", "unsafe_allow_html" not in tab_src)
check("Kandidat ohne unsafe_allow_html", "unsafe_allow_html" not in kand_src)
check("Reiter importiert das Modul erst beim Aufruf",
      "import archiv_import" in tab_src and "\nimport archiv_import" not in quelle_app)
check("Reiter nur bei erlaubtem Import",
      "archive_import_allowed()" in _inspect.getsource(app._reference_dialog))
for _host, _soll in (("localhost:8501", True), ("127.0.0.1:8501", True), ("[::1]:8501", True),
                     ("LOCALHOST", True), ("notam-space-analyzer.streamlit.app", False),
                     ("192.168.1.20:8501", False), ("localhost.evil.com", False), ("", False), (None, False)):
    check("Host {!r} -> lokal {}".format(_host, _soll), app.is_local_request(_host) == _soll)
check("ohne Streamlit-Kontext verborgen (fail-closed)", app.archive_import_allowed() is False)
check("GCAT-Treffer zeigt den Startplatz", "s.site" in kand_src)
check("Reiter fasst die Tageslage nicht an",
      all(w not in tab_src + kand_src
          for w in ("manual_notams", "WORKSPACE_FILE", "notam_workspace", "save_workspace")))

# Jeder schreibende/ladende Aufruf steht in einem try, das ai.ImportStateError faengt.
import ast as _ast
import textwrap as _tw


def _faengt_importfehler(handler):
    typen = handler.type.elts if isinstance(handler.type, _ast.Tuple) else [handler.type]
    return any(isinstance(t, _ast.Attribute) and t.attr == "ImportStateError"
               and isinstance(t.value, _ast.Name) and t.value.id == "ai" for t in typen)


def _ungeschuetzte_aufrufe(src, namen):
    baum = _ast.parse(_tw.dedent(src))
    eltern = {}
    for knoten in _ast.walk(baum):
        for kind in _ast.iter_child_nodes(knoten):
            eltern[kind] = knoten
    fehlend, gefunden = [], []
    for knoten in _ast.walk(baum):
        if (isinstance(knoten, _ast.Call) and isinstance(knoten.func, _ast.Attribute)
                and isinstance(knoten.func.value, _ast.Name) and knoten.func.value.id == "ai"
                and knoten.func.attr in namen):
            gefunden.append(knoten.func.attr)
            kind, p = knoten, eltern.get(knoten)
            geschuetzt = False
            while p is not None:
                if (isinstance(p, _ast.Try) and kind in p.body
                        and any(_faengt_importfehler(h) for h in p.handlers)):
                    geschuetzt = True
                    break
                kind, p = p, eltern.get(p)
            if not geschuetzt:
                fehlend.append("{} (Zeile {})".format(knoten.func.attr, knoten.lineno))
    return fehlend, gefunden


_kritisch = ("confirm_many", "remove_orphan", "keep_orphan", "save_state", "save_korpus",
             "load_korpus", "load_state")
_f1, _g1 = _ungeschuetzte_aufrufe(tab_src, _kritisch)
_f2, _g2 = _ungeschuetzte_aufrufe(kand_src, _kritisch)
check("Reiter: alle kritischen Aufrufe fangen ImportStateError",
      not _f1 and {"confirm_many", "remove_orphan", "keep_orphan", "save_state", "save_korpus",
                   "load_korpus", "load_state"} <= set(_g1), (_f1, sorted(set(_g1))))
check("Kandidat: alle kritischen Aufrufe fangen ImportStateError",
      not _f2 and {"confirm_many", "save_state"} <= set(_g2), (_f2, sorted(set(_g2))))

# Verhalten: kaputter Zustand -> Fehlermeldung, nichts geschrieben, keine Ausnahme
import archiv_import as _ai7
import types as _types
_meldungen, _geschrieben = [], []
_orig = (app.st, _ai7.load_state, _ai7.save_state, _ai7.save_korpus, _ai7.load_korpus)


def _kaputt(*a, **k):
    raise _ai7.ImportStateError("archiv_import.json is unreadable (test).")


try:
    app.st = _types.SimpleNamespace(error=_meldungen.append)
    _ai7.load_korpus = lambda *a, **k: {}
    _ai7.load_state = _kaputt
    _ai7.save_state = lambda *a, **k: _geschrieben.append("state")
    _ai7.save_korpus = lambda *a, **k: _geschrieben.append("korpus")
    _ausnahme = None
    try:
        app._archive_import_tab(sp, fir, app.load_vehicles(str(app.VEHICLE_CSV)))
    except Exception as exc:  # noqa: BLE001
        _ausnahme = exc
finally:
    app.st, _ai7.load_state, _ai7.save_state, _ai7.save_korpus, _ai7.load_korpus = _orig
check("ImportStateError beim Laden: angezeigt, nichts geschrieben",
      _ausnahme is None and _meldungen == ["archiv_import.json is unreadable (test)."]
      and not _geschrieben, (_ausnahme, _meldungen, _geschrieben))

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
