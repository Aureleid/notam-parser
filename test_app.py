import os, sys, math
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
check("Azimut 180 -> i=90", abs(i-90)<1e-6, round(i,3))
check("Klassifikation SSO", app.classify_orbit(98.0).startswith("Sonnensynchron"))
check("Klassifikation retrograd", app.classify_orbit(108.0) == "Retrograder Orbit")
check("Klassifikation LEO", app.classify_orbit(51.6).startswith("Standard LEO"))
check("Klassifikation aequatorial", app.classify_orbit(20.0).startswith("Aequatorial"))
check("Klassifikation None", app.classify_orbit(None) == "Unbestimmt")
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
check("Wetterballon -> NIEDRIG", lvl == "NIEDRIG", (sc, lvl))
launch = ("E) TEMPORARY RESTRICTED AREA FOR SPACE LAUNCH ACTIVITY. FALLING DEBRIS "
          "EXPECTED. ROCKET STAGE IMPACT 1936N11057E SFC/UNL")
sc, lvl, notes = app.score_confidence(launch, app.detect_triggers(launch, {"Q": "W/000/999"}))
check("echtes Launch-NOTAM -> HOCH", lvl == "HOCH", (sc, lvl))
searchlight = "E) SEARCHLIGHT DISPLAY WI 0.5NM RADIUS OF 512846N 0001745W F) SFC G) UNL"
check("Suchscheinwerfer -> NIEDRIG",
      app.score_confidence(searchlight, app.detect_triggers(searchlight, {}))[1] == "NIEDRIG")

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
                           ["Keyword: ROCKET"])[1] == "NIEDRIG")
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
ev, _ = app.analyze_notams(cases, sp, fir, min_confidence="MITTEL")
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
    ev_real, st_real = app.analyze_notams(real, sp, fir, min_confidence="MITTEL")
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
    evs, _ = app.analyze_notams(mdf, sp, fir, min_confidence="MITTEL")
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
ev_c, st_c = app.analyze_notams(comb, sp, fir, min_confidence="MITTEL")
check("importierte Events unveraendert", st_c["ok"] == 6, st_c["ok"])
check("genau ein manuelles Event", st_c["manual"] == 1, st_c["manual"])
man_ev = [e for e in ev_c if e.source == app.SOURCE_MANUAL]
check("manuelles Event hat sprechende ID", man_ev[0].notam_id.startswith("MANUELL-"), man_ev[0].notam_id)
check("manuelles Event ist georeferenziert", man_ev[0].centroid_lat is not None)
check("Marker-Spalte nicht im Analysetext", app.SOURCE_COLUMN not in man_ev[0].raw_text)
tbl_c = app.events_to_dataframe(ev_c)
check("Spalte 'Quelle' in der Ergebnistabelle", "Quelle" in tbl_c.columns)
check("Import und Manuell unterscheidbar",
      set(tbl_c["Quelle"]) == {"Import", "Manuell"}, set(tbl_c["Quelle"]))

check("ID-Spalte greift nicht die Volltextspalte ab",
      app.map_notam_columns(manual)["id"] != "NOTAM Text",
      app.map_notam_columns(manual))
only_manual = app.combine_sources(None, manual)
ev_m, _ = app.analyze_notams(only_manual, sp, fir, min_confidence="MITTEL")
check("Kennung aus reinem Freitext-Import korrekt",
      ev_m[0].notam_id.startswith("MANUELL-") or len(ev_m[0].notam_id) < 12, ev_m[0].notam_id)
withid = app.manual_entries_to_dataframe(
    [{"text": "Z9876/26 NOTAMN Q) ZLHW/QRTCA/IV/BO/W/000/999 A) ZLHW E) SPACE LAUNCH FROM "
              "JIUQUAN. FALLING DEBRIS 3830N10230E 3745N10410E 3650N10320E F) SFC G) UNL",
      "added": "x"}], "NOTAM Text")
ev_w, _ = app.analyze_notams(withid, sp, fir, min_confidence="MITTEL")
check("Kennung aus dem Text uebernommen", ev_w[0].notam_id == "Z9876/26", ev_w[0].notam_id)
check("Manuell-only Lauf ordnet Jiuquan zu", ev_w[0].spaceport_code == "JSLC", ev_w[0].spaceport_code)

print("== 17. Manuelle Events in Karte und Export ==")
ok_c = tbl_c[tbl_c["Status"] == "OK"]
csv_c = ok_c.drop(columns=["_row", "_from", "_to"]).to_csv(index=False)
check("CSV-Export enthaelt Quelle-Spalte", "Quelle" in csv_c.splitlines()[0])
check("CSV-Export enthaelt den manuellen Eintrag",
      any("Manuell" in line for line in csv_c.splitlines()[1:]))
payload_c = [app.event_to_export_dict(e) for e in ev_c if e.source == app.SOURCE_MANUAL]
check("JSON-Export markiert die Quelle", payload_c[0]["source"] == "Manuell", payload_c[0]["source"])
html_c = app.build_event_map([e for e in ev_c if e.status == "OK"]).get_root().render()
check("Karte enthaelt Manuell-Markierung", "manuell hinzugefuegt" in html_c)
check("Karte enthaelt weiterhin alle Events",
      html_c.count("Centroid Sperrzone") == len(ok_c), (html_c.count("Centroid Sperrzone"), len(ok_c)))

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
check("  ... mit Begruendung", "TSLC" in note and "Westen" in note, note)
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
ev_man, _ = app.analyze_notams(man_cn, sp, fir, min_confidence="MITTEL")
check("Freitext: alle drei erkannt", len(ev_man) == 3, len(ev_man))
check("Freitext: alle mit Status OK", all(e.status == "OK" for e in ev_man),
      [(e.notam_id, e.review_reason) for e in ev_man])
check("Freitext: alle Konfidenz HOCH", all(e.confidence_level == "HOCH" for e in ev_man),
      [(e.notam_id, e.confidence_level) for e in ev_man])
check("Freitext: alle vier Polygonpunkte", all(len(e.coordinates) == 4 for e in ev_man),
      [len(e.coordinates) for e in ev_man])
check("Freitext: alle als Manuell markiert", all(e.source == app.SOURCE_MANUAL for e in ev_man))

# Weg B: Datei-Import (gleiche NOTAMs als Tabelle)
imp_cn = pd.DataFrame({"NOTAM ID": ["A0611/26", "A4631/26", "A4632/26"], "NOTAM Text": CN})
ev_imp, _ = app.analyze_notams(imp_cn, sp, fir, min_confidence="MITTEL")
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
      and by_cn["A4631/26"].orbit_type.startswith("Sonnensynchron"),
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
ev_p, st_p = app.analyze_notams(PAAR, sp, fir, min_confidence="MITTEL")
check("beide NOTAMs in einer Gruppe", st_p["launches"] == 1 and st_p["grouped"] == 1,
      (st_p["launches"], st_p["grouped"]))
g = st_p["groups"][0]
check("Gruppe umfasst zwei Sperrzonen", g.zone_count == 2, g.zone_count)
check("Gruppe nennt beide Kennungen", set(g.notam_ids) == {"A4631/26", "A4632/26"}, g.notam_ids)
check("Gruppe -> Jiuquan", g.spaceport_code == "JSLC", g.spaceport_code)
check("Gruppe -> SSO", g.orbit_type.startswith("Sonnensynchron"), g.orbit_type)
check("Azimut-Streuung klein", g.azimuth_spread_deg < 2.0, g.azimuth_spread_deg)
check("Startfenster umspannt beide NOTAMs",
      g.window_from.strftime("%H:%M") == "03:54" and g.window_to.strftime("%H:%M") == "04:35",
      (g.window_from, g.window_to))
check("beide Events tragen dieselbe Start-Kennung",
      len({e.launch_group for e in ev_p}) == 1 and ev_p[0].launch_group.startswith("START-"),
      [e.launch_group for e in ev_p])
check("Hinweis nennt die gemeinsame Bahn", "Gemeinsame Bahn" in ev_p[0].assignment_note,
      ev_p[0].assignment_note)

print("== 26. Gruppierung trennt korrekt ==")
FERN = pd.DataFrame({"NOTAM Text": [CN[1], """A9999/26 NOTAMN
Q)ZJSA/QRDCA/IV/BO/W/000/999/1930N11100E050
A)ZJSA B)2609200358 C)2609200420
E) A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY:
N193600E1105700-N194800E1121200-N190200E1123000-N185000E1111500,
BACK TO START. VERTICAL LIMITS:SFC-UNL.
F)SFC G)UNL"""]})
ev_f, st_f = app.analyze_notams(FERN, sp, fir, min_confidence="MITTEL")
check("zeitgleiche, aber unvereinbare Zonen werden getrennt", st_f["launches"] == 2,
      st_f["launches"])
check("  ... jede Gruppe mit einer Zone",
      all(g.zone_count == 1 for g in st_f["groups"]), [g.zone_count for g in st_f["groups"]])
weit = pd.DataFrame({"NOTAM Text": [CN[1], CN[1].replace("2609200354", "2609210354")
                                             .replace("2609200415", "2609210415")
                                             .replace("A4631/26", "A4633/26")]})
ev_w, st_w = app.analyze_notams(weit, sp, fir, min_confidence="MITTEL")
check("NOTAMs eines Tages Abstand werden nicht gruppiert", st_w["launches"] == 2, st_w["launches"])

print("== 27. Mehrfachlistungen ==")
dubl = pd.DataFrame({"NOTAM Text": [CN[1], CN[1], CN[1]]})
ev_d, st_d = app.analyze_notams(dubl, sp, fir, min_confidence="MITTEL")
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
check("Karte: zwei Sperrzonen", html_g.count("Centroid Sperrzone") == 2, html_g.count("Centroid Sperrzone"))
check("Karte: nur eine Flugbahn", html_g.count("L.polyline") == 1, html_g.count("L.polyline"))
check("Karte: nur ein Startplatz-Marker", html_g.count('"icon": "rocket"') == 1,
      html_g.count('"icon": "rocket"'))

print("== 29. Echtdaten-Gruppierung ==")
if xls:
    ev_r, st_r = app.analyze_notams(real, sp, fir, min_confidence="MITTEL")
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
ev_neu, st_neu = app.analyze_notams(man_neu, sp, fir, min_confidence="MITTEL")
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
      by_neu["AU-F2572"].reliability == "gering", by_neu["AU-F2572"].reliability)
check("4456 und A4457 -> ein Taiyuan-Start",
      by_neu["CN-4456"].launch_group == by_neu["CN-A4457"].launch_group
      and by_neu["CN-4456"].spaceport_code == "TSLC",
      (by_neu["CN-4456"].launch_group, by_neu["CN-4456"].spaceport_code))

# Weg B: Datei-Import
imp_neu = pd.DataFrame({"NOTAM Text": list(NEU.values())})
ev_imp_neu, st_imp = app.analyze_notams(imp_neu, sp, fir, min_confidence="MITTEL")
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
    pd.DataFrame({"NOTAM Text": list(FALSCH.values())}), sp, fir, min_confidence="MITTEL")
treffer = [(n, e.nation, e.spaceport_code) for n, e in zip(FALSCH, ev_f) if e.status == "OK"]
check("keiner der fuenf Nicht-Starts wird als Start gewertet", treffer == [], treffer)
check("Fehlalarme bilden keine Startgruppe", st_f["launches"] == 0, st_f["launches"])

print("== 37. Echtdaten nach der Erweiterung ==")
if xls:
    ev_r2, st_r2 = app.analyze_notams(real, sp, fir, min_confidence="MITTEL")
    check("Starts im Echtbestand erkannt", st_r2["launches"] >= 4, st_r2["launches"])
    check("  ... jeder mit mindestens zwei Sperrzonen",
          all(g.zone_count >= 2 for g in st_r2["groups"] if g.spaceport_code),
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
ev_q, st_q = app.analyze_notams(knapp, sp, fir, min_confidence="MITTEL")
check("NOTAM ohne Gebietsgrenzen geht nicht verloren",
      len(ev_q) == 1 and ev_q[0].status == "OK",
      (len(ev_q), ev_q[0].review_reason if ev_q else None))
check("  ... Zone aus der Q-Line abgeleitet",
      len(ev_q[0].coordinates) == 1 and abs(ev_q[0].coordinates[0][0] - 39.8333) < 1e-3,
      ev_q[0].coordinates)
check("  ... Radius uebernommen", ev_q[0].radius_km and abs(ev_q[0].radius_km - 183.3) < 1.0,
      ev_q[0].radius_km)
check("  ... Herkunft der Zone wird ausgewiesen",
      "Q-Line" in ev_q[0].assignment_note, ev_q[0].assignment_note)

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
    pd.DataFrame({"NOTAM Text": list(NORWEGEN.values())}), sp, fir, min_confidence="MITTEL")
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
    pd.DataFrame({"NOTAM Text": HEBRIDEN}), sp, fir, min_confidence="MITTEL")
check("zwei mehrdeutige Meldungen bestaetigen sich nicht gegenseitig",
      st_h["launches"] == 0 and all(e.status == "REVIEW" for e in ev_h),
      (st_h["launches"], [e.status for e in ev_h]))
ANKER = HEBRIDEN + [
 "A2411/26 NOTAMN Q) ENOB/QRDCA/IV/BO/W/000/999/7537N02147E047 A) ENOB B) 2609180900 "
 "C) 2609182000 E) TEMPO DANGER AREA ACTIVATED PSN 762200N 0215500E - 752400N 0244300E - "
 "745100N 0214500E - 755000N 0185000E. IMPACT AREA FOR RUSSIAN MISSILES F) GND G) UNL",
]
ev_a, st_a = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": ANKER}), sp, fir, min_confidence="MITTEL")
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
ev_p0, st_p0 = app.analyze_notams(df_p, sp, fir, min_confidence="MITTEL")
by_p0 = dict(zip(PRUEFFAELLE, ev_p0))
check("mehrdeutige FIR steht zunaechst im Review",
      by_p0["mehrdeutige FIR"].status == "REVIEW", by_p0["mehrdeutige FIR"].status)
check("NOTAM ohne Koordinaten steht zunaechst im Review",
      by_p0["ohne Koordinaten"].status == "REVIEW", by_p0["ohne Koordinaten"].status)

alle_keys = {e.key for e in ev_p0}
ev_p1, st_p1 = app.analyze_notams(df_p, sp, fir, min_confidence="MITTEL", confirmed_keys=alle_keys)
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
      and "Koordinaten" in by_p1["ohne Koordinaten"].assignment_note,
      by_p1["ohne Koordinaten"].assignment_note)
tbl_p = app.events_to_dataframe(ev_p1)
check("Tabelle zeigt das Hexagon vor jeder Kennung",
      all(str(v).startswith(app.MANUAL_MARK) for v in tbl_p["NOTAM ID"]), list(tbl_p["NOTAM ID"]))
check("Tabelle hat die Spalte 'Geprüft'", "Geprüft" in tbl_p.columns)
check("Spalte weist die Pruefung aus",
      set(tbl_p["Geprüft"]) == {"manuell bestätigt"}, set(tbl_p["Geprüft"]))

check("Bestaetigung einzelner NOTAMs wirkt gezielt",
      app.analyze_notams(df_p, sp, fir, min_confidence="MITTEL",
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
ev_h0, st_h0 = app.analyze_notams(pd.DataFrame({"NOTAM Text": HEB}), sp, fir, min_confidence="MITTEL")
check("ohne Bestaetigung keine Gruppe", st_h0["launches"] == 0, st_h0["launches"])
ev_h1, st_h1 = app.analyze_notams(pd.DataFrame({"NOTAM Text": HEB}), sp, fir,
                                  min_confidence="MITTEL", confirmed_keys={ev_h0[0].key})
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
    pd.DataFrame({"NOTAM Text": [A0096]}), sp, fir, min_confidence="MITTEL")
e_ss = ev_ss[0]
check("wird als Start erkannt", e_ss.status == "OK", e_ss.review_reason)
check("Nation USA statt Indien", e_ss.nation == "USA", e_ss.nation)
check("Startplatz Starbase Boca Chica", e_ss.spaceport_code == "KBRO", e_ss.spaceport_code)
check("Startrichtung nach Osten", 45 < e_ss.azimuth_deg < 135, e_ss.azimuth_deg)
check("Herkunft des Startplatzes wird ausgewiesen",
      "STARSHIP" in " ".join(e_ss.spaceport_evidence), e_ss.spaceport_evidence)
check("Zuverlaessigkeit gemindert (Fernzone)", e_ss.reliability == "gering", e_ss.reliability)

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
    pd.DataFrame({"NOTAM Text": list(US.values())}), sp, fir, min_confidence="MITTEL")
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
      app.zone_reliability(500.0, app.KIND_REENTRY) == "gering",
      app.zone_reliability(500.0, app.KIND_REENTRY))
check("Start in Startplatznaehe bleibt hoch",
      app.zone_reliability(500.0, app.KIND_LAUNCH) == "hoch")
check("grosse Azimut-Streuung mindert die Zuverlaessigkeit",
      app.zone_reliability(500.0, app.KIND_LAUNCH, 120.0) == "gering")
check("Spalte 'Art' in der NOTAM-Tabelle",
      "Art" in app.events_to_dataframe(ev_ss).columns)

print("== 50. US-Wiedereintritte im Echtbestand ==")
if xls:
    ev_u, st_u = app.analyze_notams(real, sp, fir, min_confidence="MITTEL")
    g_u = {g.group_id: g for g in st_u["groups"] if g.spaceport_code}
    usa = [g for g in g_u.values() if g.nation == "USA"]
    check("US-Ereignisse werden erkannt", len(usa) >= 2, len(usa))
    check("  ... als Wiedereintritt eingestuft",
          all(g.kind == app.KIND_REENTRY for g in usa), [(g.group_id, g.kind) for g in usa])
    check("  ... mit gemindeter Zuverlaessigkeit",
          all(g.reliability == "gering" for g in usa), [(g.group_id, g.reliability) for g in usa])
    starship = [g for g in usa if g.spaceport_code == "KBRO"]
    check("Starship-Gruppe gefunden", starship != [], [g.spaceport_code for g in usa])
    if starship:
        check("  ... umfasst A0096/26", any("A0096/26" in n for n in starship[0].notam_ids),
              starship[0].notam_ids)
    chinesisch = [g for g in g_u.values() if g.nation == "China"]
    check("chinesische Starts bleiben Starts",
          all(g.kind == app.KIND_LAUNCH for g in chinesisch),
          [(g.group_id, g.kind) for g in chinesisch])
    check("  ... mit hoher Zuverlaessigkeit",
          all(g.reliability == "hoch" for g in chinesisch),
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
ev_t0, _ = app.analyze_notams(df_t, sp, fir, min_confidence="MITTEL")
check("mit vollstaendiger Referenz -> Taiyuan", ev_t0[0].spaceport_code == "TSLC",
      ev_t0[0].spaceport_code)
ev_t1, _ = app.analyze_notams(df_t, ohne_tslc, fir, min_confidence="MITTEL")
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
ev_t2a, _ = app.analyze_notams(df_eine, sp, fir, min_confidence="MITTEL")
check("einzelne Zone ohne den neuen Eintrag -> Taiyuan",
      ev_t2a[0].spaceport_code == "TSLC", ev_t2a[0].spaceport_code)
ev_t2, _ = app.analyze_notams(df_eine, sp_erweitert, fir, min_confidence="MITTEL")
check("neu hinzugefuegter Startplatz wird sofort beruecksichtigt",
      ev_t2[0].spaceport_code == "NEUX", ev_t2[0].spaceport_code)
check("  ... Taiyuan bleibt bei zwei Zonen die bessere Erklaerung",
      app.analyze_notams(df_t, sp_erweitert, fir, min_confidence="MITTEL")[0][0].spaceport_code
      == "TSLC")

fir_ohne_zhwh = app.apply_reference_overrides(fir, "ICAO Code", ["ZHWH", "ZLHW"], [])
ev_t3, _ = app.analyze_notams(df_t, sp, fir_ohne_zhwh, min_confidence="MITTEL")
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
check("dunkles Violett entspricht Streamlits :violet[]",
      app.MANUAL_COLOR.upper() == "#B27EFF", app.MANUAL_COLOR)
check("helles Theme nutzt Streamlits hellen Ton",
      app.MANUAL_COLOR_LIGHT.upper() == "#803DF5", app.MANUAL_COLOR_LIGHT)
check("HTML-Markierung nutzt denselben Farbton",
      app.manual_color() in app.mark_id_html("A4457/26", True),
      app.mark_id_html("A4457/26", True)[:50])

# Alle drei Darstellungswege tragen dieselbe Kennung samt Symbol
ev_m, st_m = app.analyze_notams(
    pd.DataFrame({"NOTAM Text": [PRUEFFAELLE["ohne Koordinaten"]]}), sp, fir,
    min_confidence="MITTEL", confirmed_keys={by_p0["ohne Koordinaten"].key})
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
ev_r0, st_r0 = app.analyze_notams(demo_r, sp, fir, min_confidence="MITTEL")
ok_r0 = [e for e in ev_r0 if e.status == "OK"]
ziel = ok_r0[0]
check("Ausgangslage: Start in der Launch-Tabelle", ziel.status == "OK", ziel.status)

ev_r1, st_r1 = app.analyze_notams(
    demo_r, sp, fir, min_confidence="MITTEL", rejected_keys={ziel.key})
e_r1 = next(e for e in ev_r1 if e.key == ziel.key)
check("nach Zurueckstellung im Review", e_r1.status == "REVIEW", e_r1.status)
check("  ... mit sprechender Begruendung",
      "zurückgestellt" in e_r1.review_reason, e_r1.review_reason)
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
    demo_r, sp, fir, min_confidence="MITTEL",
    confirmed_keys={ziel.key}, rejected_keys={ziel.key})
e_r2 = next(e for e in ev_r2 if e.key == ziel.key)
check("Zurueckstellung sticht die Bestaetigung", e_r2.status == "REVIEW", e_r2.status)
check("  ... und entfernt die Markierung", not e_r2.manual_override)

ev_r3, st_r3 = app.analyze_notams(demo_r, sp, fir, min_confidence="MITTEL")
check("Aufhebung stellt den Ausgangszustand her",
      st_r3["ok"] == st_r0["ok"] and st_r3["launches"] == st_r0["launches"],
      (st_r3["ok"], st_r0["ok"]))

review_ziel = [e for e in ev_r0 if e.status == "REVIEW"][0]
ev_r4, _ = app.analyze_notams(
    demo_r, sp, fir, min_confidence="MITTEL", rejected_keys={review_ziel.key})
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

ev_n, st_n = app.analyze_notams(app.build_demo_notams(), sp, fir, min_confidence="MITTEL")
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
      "tab_sp, tab_fir, tab_veh = st.tabs(" in quelle)
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
check("Sicherungs-Schaltflaeche vorhanden", "💾 Trägersysteme sichern" in quelle_v)

print()
print("ERGEBNIS:", "ALLE TESTS BESTANDEN" if ok else "FEHLER VORHANDEN")
sys.exit(0 if ok else 1)
