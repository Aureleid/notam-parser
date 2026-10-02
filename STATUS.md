# Projektstand — NOLA

Stand: 02.10.2026 · `app.py` 6347 Zeilen · `test_app.py` 719 Tests, alle grün

## Starten

```bash
cd "/Users/marioantic/Documents/Claude Code/NOTAM Parser" && .venv/bin/python -m streamlit run app.py
```

Tests: `.venv/bin/python test_app.py` — läuft ohne Streamlit-Server, dauert wenige Sekunden.

## Was fertig ist

| Bereich | Stand |
|---|---|
| Erkennung | 7 Koordinatenformate, Startsignatur (Q-Code + SFC-UNL + kurzes Fenster), D-Item-Tagesfenster, NAVAREA-Zeiträume, HTML-Entities, Kennungen mit/ohne Buchstabe |
| Eingabe | Datei-Import (CSV/XLS/XLSX mit Vorspann-Erkennung) und Freitext-Feld; beide identisch verarbeitet |
| Zuordnung | Drittstaaten-Regel über Spalte `Land`, Trägersystem → Startplatz, Startrichtungs-Prüfung (Sektor 225–325° ausgeschlossen), Fernzonen-Behandlung |
| Gruppierung | Mehrere Dropzonen eines Starts werden zusammengefasst, Anker-Regel gegen Selbstbestätigung, Ausreißer-Trennung |
| Nationen | China, Russland, Indien, Iran, Nordkorea, USA — 32 Startplätze, 130 FIRs, 51 Trägersysteme |
| Bedienung | 6 Reiter, Klartext-Auswertung, manuelle Prüfung (Space Launch / Ausblenden), Optionsmenü zur Referenzpflege |
| Trägersystem | Dropdown unter NOTAM Data und Review, gestaffelt nach Nation; gilt für alle Zonen eines Starts; lesbare Spalte in der Launch Overview |
| Prüfung | Externe Prüfung gegen `docs/intent/nola-massstab.md` am 25.09.2026; sechs Befunde behoben, einer als Vertragsfrage eingeordnet |
| Seestarts | Startpunkt aus der Geometrie abgeleitet, wenn eine kleine Kreiszone die übrigen Sperrgebiete auf einer Bahn erklärt; eigenes Protokoll `seestarts_updated.csv`, das bewusst nicht in die Startplatz-Suche zurückfließt |
| Startplätze am selben Ort | Wenchang (`WSLC`) und der kommerzielle Platz Hainan (`HAIN`) liegen 1,92 km auseinander — 0,06–0,22° Azimutunterschied gegen eine Auswahlschwelle von 15°. Die Geometrie darf dort nie entscheiden; gewählt wird von Hand, Vorgabe „nicht bestimmt". Der Hinweis wird aus dem eigenen Archiv gerechnet statt als Tabelle verdrahtet. |
| Vorankündigungen | Mehrtägige Meldungen, die denselben Luftraum vor dem Starttag reservieren, werden über Geometrie und Zeit an ihren Start gehängt — sechs Bedingungen, alle sprachfrei; Eindeutigkeit ist Bedingung. Die Gruppe bleibt unberührt: dieselbe Fläche ist keine weitere Zone. |
| Bahnrechnung | Inklination mit Erdrotation (`orbital_azimuth_deg`); Orbitbänder auf die Streuung der Abschätzung geweitet (SSO 93–103°) |
| Vorfilterung | `LOW` + Ausschlussbegriff → direkt unter *Excluded*; auf der Echtdatei 148 von 275 Review-Fällen, ohne einen Start zu verlieren. Zurückholen gewinnt dauerhaft. |
| Payload | Freitextfeld unter NOTAM Data, gilt für alle Zonen eines Starts; Spalte in Launch Overview und Export |
| Startarchiv | `startarchiv_updated.csv`, von der App geschrieben: eine Zeile je erkanntem Start, wird aktualisiert statt verdoppelt; eigener Reiter im Optionsmenü |
| Persistenz | Referenzänderungen direkt in die CSVs, Arbeitsstand (inkl. Trägersystem-Zuweisungen) in `notam_workspace.json` |
| Oberfläche | Zweizeilige Wortmarke nach festem Regelwerk, unbunte Bühne mit bunten Signalen, durchgehend deckende Flächen, durchgehend englische Fachsprache, geometrische Symbole statt Piktogramme, Farbschema aus einer Referenzoberfläche gemessen (`.streamlit/config.toml`) |
| Veröffentlichung | Repository `Aureleid/notam-parser`, Streamlit Community Cloud unter `notam-space-analyzer.streamlit.app` |

## Bekannte Grenzen

- Inklination ist eine Näherung (`cos i = cos φ · sin α`), Erdrotation nicht eingerechnet.
- Gruppierung stützt sich auf das Zeitfenster: mehr als 30 Minuten Abstand bei kurzen NOTAMs
  trennt, zwei gleichzeitige Starts vom selben Platz in ähnliche Richtung verschmelzen.
- Der Rückgängig-Stapel im Optionsmenü ist nach einem Neustart leer.
- `B4912/26` / `B4913/26` („CONDUCTED BY KOREA") bleiben bewusst im Review — der Text
  unterscheidet nicht zwischen Nord- und Südkorea.

## Offene Punkte

- **Demo-Modus** (schreibgeschützt) für die öffentliche Fassung — derzeit kann jeder Besucher
  der veröffentlichten App Referenzdaten über das Optionsmenü ändern.
- **`NATION_HINTS` / `SPACEPORT_HINTS`** sind in `app.py` fest kodiert und überschneiden sich
  inhaltlich mit `traegersysteme_updated.csv`; beide ließen sich aus der Referenz ableiten.
- **Archivspalten** (Befund 6): Azimut und Inklination werden auch dort gespeichert, wo
  die Anwendung sie selbst für bedeutungslos erklärt (Wiedereintritte, hohe Streuung).
  Ohne Spalten für Art und Zuverlässigkeit kann der künftige Ähnlichkeitsvergleich
  gemessene nicht von bedeutungslosen Werten unterscheiden. Offen, weil es die vom
  Benutzer festgelegte Spaltenliste berührt.
- **Zwei Archivzeilen** stammen aus behobenen Fehlern und stehen noch in
  `startarchiv_updated.csv` (die japanische Abwehranordnung als nordkoreanischer Start;
  ein Mittelwert aus 151,6° Streuung).
- **Schieberegler `LOW`** (Befund 9) erlaubt bewusst, den Review um den Preis von
  Zuordnungen zu leeren — Abwägung, keine Behebung.
- **Zwei Startversuche desselben Starts** werden als zwei Starts geführt. Der chinesische
  Seestart vom 11./12.02.2026 steht zweimal im Archiv — am 11. offenbar abgebrochen, am 12.
  geflogen. NOLA kann das nicht wissen; beide Tage hatten echte Luftraumsperrungen. Für die
  Tageslage richtig, für den geplanten Ähnlichkeitsvergleich irreführend.
- **Startazimut und Bahnazimut** unterscheiden sich seit der Rotationskorrektur um bis zu 3°.
  Angezeigt und archiviert wird nur der Startazimut.
- **Vorankündigung ohne Starttag**: Die Paarung arbeitet rückwärts — sie braucht den
  erkannten Start. Am Tag der Ankündigung selbst, wenn die kurzen Meldungen noch fehlen,
  gibt es nichts zu paaren, und die Meldung bleibt im Review. Die Information „Start in
  diesem Fenster erwartet" wäre damit noch nicht gewonnen; dafür müsste eine
  Vorankündigung aus sich heraus als solche gelten dürfen, ohne Gegenstück.
- **Das Startarchiv führt Vorankündigungen nicht.** Die Spalte `NOTAM` nennt nur die
  Meldungen des Starttags. Für den geplanten Ähnlichkeitsvergleich wäre der Vorlauf ein
  Merkmal — das würde aber den abgestimmten Spaltensatz ändern und ist offen.
- **`AEROSPACE FLIGHT ACTIVITY`** ist in keiner Stichwortliste. Beim Seestart-Fall war das
  folgenlos (die Meldungen erreichten HIGH über SFC/UNL und Q-Code), könnte aber in einem
  schwächeren Fall den Ausschlag geben.
- **Automatische `.bak`-Kopie** der Referenzdateien beim Start (angeboten, nicht umgesetzt).
  Eine einmalige, geprüfte Sicherung liegt unter
  `iCloud/Claude/Claude Code/NOTAM Parser Backups/`.
- **Das Pad eines Wenchang-Starts** bleibt `nicht bestimmt`, bis es von Hand gesetzt wird.
  NOLA kann es nicht wissen: nicht aus der Geometrie (1,92 km), nicht aus dem NOTAM-Text
  (chinesische Startmeldungen nennen kein Pad), nicht aus dem Trägersystem (CZ-8 fliegt von
  beiden). Die Archivzählung neben der Auswahlliste braucht erst eigene Einträge, um etwas
  zu sagen.
- **Altes Archiv kennt die Unterscheidung nicht.** Die 16 bestehenden Zeilen mit `WSLC`
  heißen weiter „Wenchang, Pad nicht unterschieden" — rückwirkend lässt sich das nicht
  klären.
- Lokale Änderungen erreichen die veröffentlichte App erst nach `git push`.
