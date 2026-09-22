# NOTAM Space-Launch Analyzer

Streamlit-Anwendung zur täglichen Auswertung von NOTAM-Dateien mit dem Ziel,
Raumfahrtstarts von **China, Russland, Indien, Iran, Nordkorea und den USA** zu
erkennen, einem Weltraumbahnhof zuzuordnen und die Flugbahn abzuschätzen.

## Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py
```

Die App läuft dann auf <http://localhost:8501>.

## Dateien

| Datei | Zweck |
|---|---|
| `app.py` | Gesamte Anwendung (Parser, Geodäsie, UI) |
| `weltraumbahnhoefe_koordinaten_updated.csv` | 31 Startplätze der sechs Zielnationen |
| `icao_fir_acc_coordinates_updated.csv` | 129 FIRs/ACCs mit Land und zugehöriger Startnation |
| `traegersysteme_updated.csv` | 51 aktive Trägersysteme mit Nation, Name und Abkürzung |
| `test_app.py` | Tests über Parser, Orbitmechanik, Pipeline, Freitext-Eingabe und Regressionen |
| `requirements.txt` | Abhängigkeiten |
| `notam_workspace.json` | Arbeitsstand: manuelle NOTAMs, Bestätigungen, Ausblendungen (wird automatisch angelegt) |

Tests ausführen:

```bash
.venv/bin/python test_app.py
```

## Zwei Eingabewege

**Datei-Import** – CSV, XLS oder XLSX über den Uploader.

**Freitext-Eingabe** – im Feld *NOTAM manuell einfügen* lässt sich ein NOTAM direkt
per Copy & Paste einsetzen. Unterstützt werden:

- mehrzeiliges ICAO-Format mit Q/A/B/C/D/E/F/G-Items
- einzeilige Schreibweise
- FAA-Domestic-Format (`!FDC 6/1234 ZKC AIRSPACE …`)
- Kleinschreibung
- reiner Freitext ohne Items und ohne Kennung
- aus Mails oder PDFs kopierter Text mit typografischen Sonderzeichen
  (geschützte Leerzeichen, `°`/`º`, `′`, `–`, CRLF, vorangestellte Etiketten wie `NOTAM:`)

Mehrere NOTAMs auf einmal werden an den Kennungen getrennt, bei fehlender Kennung an
Leerzeilen. Ein einzelnes NOTAM mit internen Leerzeilen bleibt dadurch zusammen.

Manuelle Einträge laufen durch dieselbe Pipeline wie importierte und sind überall als
`Manuell` gekennzeichnet: in der Spalte **Quelle** der Ergebnistabelle, mit eigenem
Stift-Marker und gestricheltem Polygon auf der Karte, mit `✍️ manuell` im Volltext-Tab
sowie im CSV- und JSON-Export. Fehlt eine Kennung, wird `MANUELL-01`, `MANUELL-02` … vergeben.
Über den Filter **Quelle** lassen sich beide Ströme getrennt betrachten.

Die manuellen Einträge werden in `notam_workspace.json` im Projektordner abgelegt und beim
Start wieder geladen — sie überleben Seitenneuladen und Serverneustart. *Alle manuellen
Einträge verwerfen* leert sie dauerhaft.

## Verarbeitungskette

1. **Einlesen** – CSV, XLS oder XLSX, oder Freitext aus dem Eingabefeld. Trennzeichen, Encoding und Vorspannzeilen
   werden automatisch erkannt (Magic Bytes, nicht nur Dateiendung), ebenso die
   Spaltenrollen (ID, Volltext, FIR, Gültigkeit).
2. **Trigger** (§2A der Spezifikation) – Schlüsselwörter, `SFC/UNL`-Varianten und
   Q-Code-Höhenfenster `000/999`.
3. **Konfidenz-Scoring** – bewertet raumfahrtspezifische Begriffe positiv,
   Ausschlussbegriffe (Wetterballon, Suchscheinwerfer, Schießübung …) negativ.
   Stufen: `HOCH` / `MITTEL` / `NIEDRIG`, einstellbar in der Sidebar.
4. **Nations-Attribution** – liest die Startnation aus dem Text (Länder, Startplätze,
   Trägersysteme). Fremde Betreiber (SpaceX, Ariane, Rocket Lab, Amateurraketen …)
   schließen ein Event aus.
5. **FIR-Filter** (§2B) – ein explizit genannter ICAO-Code ist bindend. Nur wenn gar
   kein Code vorhanden ist, greift eine geographische Zuordnung, begrenzt auf 1500 km.
   Liegt die FIR im Gebiet eines **Drittstaats**, wird die Startnation nicht unterstellt
   (siehe unten).
6. **Geometrie** (§2C) – sieben Koordinatenformate, siehe Tabelle unten.
   Polygon-Centroid über die Flächenformel, Radiusangaben in NM/KM. Beschreibt ein
   NOTAM **mehrere** Gebiete (nummeriert `1. … 2. …`, nach `SIMILAR ACTIVITIES` oder
   nach `AND` vor der nächsten Koordinate), werden sie als getrennte Polygone geführt
   statt zu einem Zickzack verschmolzen.
7. **Zuordnung & Trajektorie** (§3) – nächstgelegener Weltraumbahnhof per Haversine,
   Anfangskurs als Launch-Azimut, Inklination über `cos(i) = cos(φ) · sin(α)`,
   Klassifikation des Orbit-Typs.

### Unterstützte Koordinatenformate

| Format | Beispiel | Herkunft |
|---|---|---|
| Kompakt, Hemisphäre hinten | `1936N11057E`, `193612N1105730E` | ICAO-Standard |
| Kompakt, Hemisphäre vorn | `N380300E1071800`, `N3803E10718`, `S1059E09207` | China, Russland |
| Grad/Min/Sek mit Leerzeichen | `59 03 00 S 131 00 00 W` | Neuseeland |
| Grad + Dezimalminuten | `59-42.60S 165-49.20E` | maritime NAVAREA-Warnungen |
| Gradzeichen, Hemisphäre hinten | `19°36'N 110°57'E` | Freitext |
| Gradzeichen, Hemisphäre vorn | `N 12°30' E 82°10'` | Freitext |
| Dezimalgrad | `19.60N 110.95E` | Freitext |

Trenner zwischen Polygonpunkten: `-`, `,`, `/`, Leerzeichen oder Zeilenumbruch.
Die Q-Line wird bewusst übergangen – ihr Bezugspunkt gehört nicht zum Polygon.

### Weitere Schreibweisen

- **Kennungen** mit Buchstabe (`A4457/26`), ohne Buchstabe (`4456/26`),
  FAA-Domestic (`!FDC 6/1234 ZKC`) und maritim (`NAVAREA XIV WARNING 189/26`).
- **Mehrere FIRs im A-Item** (`A) ZLHW ZHWH`) sowie der Platzhalter `Q) ZXXX/…`.
- **HTML-Entities** aus Behörden-Portalen (`&apos;` → `'`).
- **Zeitangaben**: `YYMMDDHHMM`, mit `EST`-Zusatz (`2611161500EST`), `MM/DD/YYYY HHMM`,
  `PERM` sowie der Fließtext-Zeitraum maritimer Warnungen
  (`FROM 142100 UTC TO 232100 UTC JUL 2026`).
- **D-Item mit Tagesfenster** (`D) DAILY 0900-2100`): ein NOTAM kann zwei Wochen
  gültig und trotzdem täglich nur zehn Stunden aktiv sein – für die Startsignatur
  zählt das tatsächliche Fenster, nicht die Gesamtlaufzeit.
- **Meldungen ganz ohne Raumfahrt-Schlüsselwort**: chinesische NOTAMs lauten schlicht
  „A TEMPORARY DANGER AREA ESTABLISHED …", russische „AIRSPACE CLSD WI AREA: …".
  Sie werden über die Startsignatur erkannt.

### Startsignatur

Chinesische und russische Start-NOTAMs nennen weder `ROCKET` noch `LAUNCH`. Sie lauten
schlicht „A TEMPORARY DANGER AREA ESTABLISHED BOUNDED BY … VERTICAL LIMITS:SFC-UNL".
Erkannt werden sie über die Kombination aus

1. Q-Code der Gruppe `QR…` (Gefahren-, Sperr- oder Restricted Area) bzw. `QWM…`,
2. Höhenfenster über die gesamte Atmosphäre (`000/999` bzw. `SFC-UNL`),
3. Gültigkeit von höchstens 24 Stunden.

Ein Gefahrengebiet von der Erdoberfläche bis unbegrenzt, das nur Minuten aktiv ist,
ist praktisch immer ein Start. Dieselbe Signatur unterscheidet ihn von Dauer-Sperr­
gebieten, die dieselben Q-Codes tragen, aber monatelang gelten.

### Start-Gruppierung

Ein Start erzeugt mehrere Sperrzonen entlang der Flugbahn – erste Stufe, Booster,
Nutzlastverkleidung. Einzeln betrachtet gewinnt für eine weit abgelegene Zone der
geographisch nächste, aber falsche Startplatz. Gemeinsam betrachtet erklärt nur ein
Startplatz alle Zonen über denselben Azimut.

NOTAMs werden daher zusammengefasst, wenn ihre Aktivierungszeiten höchstens 30 Minuten
auseinanderliegen (Gesamtspanne ≤ 90 min) und sich ihre Kandidaten-Nationen überschneiden.
Für die Gruppe wird dann der Startplatz gewählt, der die **geringste Azimut-Streuung** über
alle Zonen ergibt – die Streuung wiegt hundertmal schwerer als die Entfernung. Liegt die
Streuung über 15°, gehören die NOTAMs nicht zusammen; das NOTAM, dessen Wegfall die Streuung
am stärksten senkt, wird entfernt und der Rest erneut geprüft. Aus drei zeitgleichen NOTAMs
bleibt so das echte Paar erhalten, während der Ausreißer eine eigene Gruppe bildet.

Jeder Start bekommt eine Kennung `START-01`, `START-02` … Die Ergebnistabelle hat zwei
Ansichten: **Nach Start gruppiert** (eine Zeile je Start, mit allen zugehörigen NOTAM-Kennungen,
Sperrzonen-Anzahl, gemeinsamem Startfenster und Azimut-Streuung) und **Einzelne NOTAMs**
(eine Zeile je Zone, mit Start-Kennung in der Spalte `Start`). Auf der Karte wird eine
Flugbahn je Start gezeichnet, nicht je NOTAM. Der Export liefert beide Ebenen als CSV,
das JSON enthält `launches` und `events`.

Die Metrik **Erfasste Launches** zählt Starts, **Aktive Sperrzonen** zählt NOTAMs.

### Ergebnis in Klartext

Über der Ergebnistabelle steht zu jedem Start eine Beschreibung ohne Fachbegriffe:
was passiert ist, wann, woran es erkannt wurde, woher die Nation stammt, warum dieser
Startplatz gewählt wurde, was die Bahn bedeutet und wie belastbar die Abschätzung ist.
Beispiel:

> **Was:** Ein Raumfahrtstart Chinas vom Weltraumbahnhof Taiyuan Satellite Launch Center.
>
> **Woran erkannt:** 2 Luftraumsperrungen von der Erdoberfläche bis unbegrenzt nach oben,
> jeweils nur rund 23 Minuten aktiv. Eine so hohe Sperrung für so kurze Zeit entsteht
> praktisch nur bei einem Raketenstart.
>
> **Was daraus folgt:** Die Rakete fliegt Richtung Süden (189°). Daraus ergibt sich eine
> Bahnneigung von rund 97° – sonnensynchron, eine nahezu polare Bahn, die jeden Ort immer
> zur gleichen Ortszeit überfliegt – typisch für Erdbeobachtungs- und Aufklärungssatelliten.

Die Beschreibung steht auch im JSON-Export und als Spalte `Klartext` in der Start-CSV.

### Zuverlässigkeit

Je weiter eine Sperrzone vom Startplatz entfernt liegt, desto unschärfer wird die
Abschätzung, weil die Erddrehung die Bodenspur verschiebt. Jeder Start trägt daher
eine Einstufung: `hoch` (nächste Zone unter 3 000 km), `mittel` (bis 8 000 km),
`gering` (darüber – Wiedereintritts- und Deorbit-Gebiete). Bei `gering` wird die
Richtungsprüfung ausgesetzt, weil der Anfangskurs dort nichts mehr über die Bahnlage aussagt.

### Drittstaaten-FIRs

Die Referenz unterscheidet zwei Fälle über die Spalte `Land`:

- **FIR im Gebiet einer Zielnation** (30 Einträge, z. B. `ZLHW` in China, `ULMM` in
  Russland): Die Startnation folgt direkt aus der FIR.
- **FIR in einem Drittstaat** (75 Einträge, z. B. `ENOB` in Norwegen, `RJJJ` in Japan,
  `EGPX` im Vereinigten Königreich): Dort steht in der Referenz nur, welche Startnation
  dieses Gebiet üblicherweise überfliegt. Ein NOTAM wird ihr **nicht allein deshalb**
  zugerechnet — der Text muss die Nation nennen, sonst geht die Meldung in den Review.

Ohne diese Unterscheidung wäre jeder norwegische Start ein russischer: Norwegen betreibt
mit Andøya einen eigenen Startplatz, und `ENOB`/`ENOR` sind in der Referenz Russland
zugeordnet, weil dort russische Wiedereintrittsgebiete liegen. Startplätze außerhalb der
fünf Zielnationen (Andøya, Esrange, SaxaVord, Naro, Alcântara, Māhia …) schließen ein
Event zusätzlich direkt aus.

### Auflösung mehrdeutiger Meldungen

Manche Meldungen tragen die Startnation nicht: eine maritime Warnung ohne FIR, ein
neuseeländisches NOTAM mit „USING AGENCY: FOREIGN AGENCY". Sie werden nicht verworfen,
sondern der Gruppierung angeboten. Gehören sie zeitlich und geometrisch zu einem Start,
dessen andere Meldungen die Nation nennen, übernehmen sie diese. Allein bleiben sie im
Review – und die Konfidenzschwelle gilt auch für sie, damit über diesen Weg keine
Fehlalarme hereinkommen.

Eine Gruppe braucht dafür einen **Anker**: mindestens ein Mitglied, dessen Nation gesichert
ist – durch Nennung im Text oder durch eine FIR im Gebiet der Startnation selbst. Sonst
würden sich zwei gleichermaßen mehrdeutige Meldungen gegenseitig bestätigen; zwei britische
Militärgebiete in der Hebriden-Sperrzone ergäben so einen russischen Start.

### Mehrfachlistungen

Behörden-Exporte führen dasselbe NOTAM oft einmal je betroffener FIR auf. Solche Dubletten
(gleiche Kennung, gleicher Zonen-Mittelpunkt) werden entfernt und in der Kopfzeile gezählt –
ohne diesen Schritt zählt die Statistik eine Zone mehrfach und die Gruppierung sieht
scheinbar zusätzliche Zonen auf derselben Bahn. Im FAA-FNS-Export betraf das 43 von 332 Zeilen.

### Startplatz aus dem Trägersystem

Der Startplatz steht praktisch nie im NOTAM, das Trägersystem dagegen oft. Nennt der
Text `STARSHIP`, `FALCON 9`, `NEW SHEPARD`, `ANTARES`, `JIUQUAN`, `PLESETSK` und
Ähnliches, wird die Auswahl auf die zugehörigen Startplätze beschränkt — sonst gewinnt
der geographisch nächste Startplatz der Nation.

Genau daran scheiterte `A0096/26`: ein Starship-Wiedereintritt im Indischen Ozean, gemeldet
über die Mauritius-FIR. Die FIR ist Indien zugeordnet, also wurde Sriharikota als
Startplatz gewählt. Mit der Trägersystem-Zuordnung greift stattdessen `SPACE X` +
`STARSHIP` → Starbase Boca Chica.

### Start oder Wiedereintritt

Nicht jede Sperrzone gehört zu einem Start. Wiedereintritts- und Splashdown-Gebiete
(`RE-ENTRY`, `SPLASHDOWN`, `DEBRIS RETURN`, `DEORBIT`) werden in der Spalte **Art** als
`Wiedereintritt` geführt. Dort kommt das Objekt aus der Umlaufbahn zurück, nicht vom
Startplatz — die Richtung vom Startplatz zur Zone sagt nichts über die Bahnlage aus.
Solche Ereignisse bekommen deshalb immer die Zuverlässigkeit `gering`, und die
Klartext-Auswertung sagt ausdrücklich, dass Azimut und Bahnneigung hier nicht
aussagekräftig sind. Dasselbe gilt, wenn die Zonen eines Ereignisses mehr als 60°
auseinanderliegen — dann beschreibt kein gemeinsamer Azimut mehr ihre Lage.

### Startrichtungs-Prüfung

Ein Start nach Westen arbeitet gegen die Erdrotation und kostet rund 900 m/s zusätzliches
Delta-v; bei den fünf Zielnationen kommt das operativ nicht vor. Startplätze, die nur über
den Azimut-Sektor 225°–325° zur Sperrzone passen würden, scheiden deshalb aus. Ohne diese
Prüfung gewinnt bei abgelegenen Dropzonen der geographisch nächste, aber falsche Startplatz.
Bleibt kein Kandidat übrig, geht das NOTAM in den Review – die Zone liegt dann westlich
aller Startplätze und beschreibt vermutlich kein Startgebiet.

Nicht zuordenbare NOTAMs gehen nicht verloren, sondern erscheinen mit Begründung
im Tab **Unassigned / Review**.

## Referenzdaten verwalten

Neben der Überschrift **Referenzdaten** in der Sidebar öffnet ein **⚙️**-Knopf ein
Optionsmenü mit drei Registern:

- **🚀 Weltraumbahnhöfe** – Kürzel, Name, Breite, Länge, Land
- **🗺️ ICAO FIR/ACC** – ICAO-Code, Region, Breite, Länge, Land der FIR, zugehörige Startnation
- **🛰️ Trägersysteme** – Abkürzung, Name, englischer Name, Land

Die Trägersysteme sind die dritte Referenz: 51 aktive Systeme von `CZ-5B` über `Soyuz-2.1b`
und `PSLV` bis `Starship`. Sie tragen keine Koordinaten, sondern ordnen jedem System seine
Nation zu — Grundlage für kommende Auswertungen der im NOTAM genannten Trägersysteme.

Neben jedem Eintrag steht ein **Entfernen**-Knopf, darunter ein Formular zum **Hinzufügen**.
Entfernte Einträge werden ab sofort nicht mehr zur Berechnung herangezogen, hinzugefügte
fließen unmittelbar ein — beide Tabellen haben ein Suchfeld, da die FIR-Referenz über
hundert Zeilen umfasst.

Ein wieder hinzugefügter Eintrag ersetzt den gleichnamigen aus der Datei, statt ihn zu
verdoppeln; die manuelle Angabe ist die jüngere. Die Statuszeile in der Sidebar weist die
Änderungen aus (`⚙️ 2 entfernt, 1 ergänzt`).

Jede Änderung wird **sofort in die Projektdatei geschrieben** und überlebt damit einen
Neustart. **↩️ Letzte Änderung rückgängig** stellt den Stand vor der jeweils letzten
Änderung wieder her (bis zu 20 Schritte, über alle drei Referenzen hinweg); die drei
Sicherungs-Schaltflächen laden je eine Kopie des aktuellen Stands herunter.

## Von der Übersicht zum Volltext

Ein Klick auf eine Zeile in der Launch-Overview-Tabelle — in beiden Ansichten — öffnet den
Bereich **NOTAM Data** und zeigt das zugehörige NOTAM dort ganz oben und aufgeklappt.
Gehören zu einem Start mehrere Sperrzonen, werden alle zugehörigen NOTAMs geöffnet.
Ein Hinweis über der Liste nennt die Auswahl, **Auswahl aufheben** stellt die normale
Reihenfolge wieder her.

> Streamlit-Tabellen melden keinen Doppelklick an das Programm — es gibt nur
> Zeilenauswahl. Ein einfacher Klick auf die Zeile löst den Sprung deshalb aus.

Die Bereichsnavigation ist aus demselben Grund eine Segmentleiste und keine klassische
Reiterleiste: bei `st.tabs` liegt der aktive Reiter im Browser und lässt sich nicht aus
dem Programm heraus umschalten. Nebeneffekt: es wird nur noch der sichtbare Bereich
gerendert statt aller sechs, was die Anwendung spürbar schneller macht.

## Manuelle Prüfung im Review

Jedes NOTAM im Review lässt sich aufklappen und einzeln entscheiden. Angezeigt werden
Originaltext, erkannte Merkmale, Konfidenz, Anzahl der Koordinaten, FIR samt Land und der
Grund für den Review. Dazu zwei Schaltflächen:

- **🚀 Space Launch** übernimmt das NOTAM in die Launch-Tabelle. Alle automatischen Hürden
  (Konfidenzschwelle, mehrdeutige Nation, Drittstaaten-FIR, fehlende FIR) werden dabei
  übergangen — die Entscheidung der prüfenden Person zählt. Startplatz, Azimut und
  Bahnneigung werden nachträglich berechnet, soweit Koordinaten vorhanden sind; fehlen sie,
  wird das NOTAM ohne Bahnabschätzung geführt und das ausdrücklich vermerkt.
- **❗ Ausblenden** verschiebt es in den Reiter **Ausgeblendet** direkt daneben. Dort
  liegen die geprüften und verworfenen Meldungen — sie zählen in keiner Auswertung mit,
  erscheinen nicht im Export und lassen sich einzeln oder gesammelt wieder einblenden.

Die Gegenrichtung gibt es im Reiter **NOTAM Data**: dort trägt jeder Eintrag die
Schaltflächen **⚠️ In den Review** und **❗ Ausblenden**. Ein Start, der automatisch erkannt
wurde, sich beim Lesen aber als etwas anderes entpuppt, lässt sich damit aus der
Launch-Tabelle nehmen. Er erscheint dann im Review mit der Begründung *„Manuell aus der
Launch-Tabelle in den Review zurückgestellt"* und fällt aus seiner Startgruppe heraus.
Dort hebt **↩️ Zurückstellung aufheben** die Entscheidung wieder auf — das NOTAM wird
danach wieder automatisch bewertet.

Die drei manuellen Entscheidungen schließen einander aus: Bestätigen, Zurückstellen und
Ausblenden setzen die jeweils anderen zurück. Eine Zurückstellung sticht dabei eine frühere
Bestätigung, weil sie die spätere Entscheidung ist.

Manuell bestätigte NOTAMs tragen ein **lilanes Hexagon ⬢ vor der Kennung** — durchgehend
im selben Farbton (`#B27EFF` im dunklen, `#803DF5` im hellen Theme, passend zu Streamlits
`:violet[]`):

| Ansicht | Darstellung |
|---|---|
| Launch Overview, Tabelle | Symbol und Kennung violett, zusätzlich Spalte `Geprüft` |
| Launch Overview, Klartext | Start-Kennung im Aufklapptitel violett |
| NOTAM Data | Symbol und Kennung im Aufklapptitel violett |
| Flightpath Map | Hinweis im Tooltip der Sperrzone |
| Unassigned / Review | eigener Abschnitt mit hochgestelltem Symbol |
Im Reiter *Unassigned / Review* listet ein eigener Abschnitt alle Bestätigungen mit einer
Schaltfläche zum Zurücknehmen.

Ein bestätigtes NOTAM kann außerdem als **Anker** einer Gruppe dienen: bestätigt man eine
Meldung, können zeitlich und geometrisch passende, für sich genommen mehrdeutige NOTAMs
darüber mit aufgelöst werden.

Bestätigungen und Ausblendungen werden wie die Freitext-Eingaben in `notam_workspace.json`
gespeichert und beim Start wieder eingelesen — sie überleben Seitenneuladen und Serverneustart.

## Wichtige Einschränkungen

- **Die Inklinationsformel ist eine Näherung.** `cos(i) = cos(φ) · sin(α)` vernachlässigt
  den Geschwindigkeitsbeitrag der Erdrotation. Bei ostwärtigen Starts liegt das Ergebnis
  einige Grad zu hoch, bei westwärtigen zu niedrig. Für die Orbit-Klassifikation reicht
  das, für Bahnbestimmung nicht.
- **Der Azimut zeigt zur Sperrzone, nicht zwingend zur Startrichtung.** Bei mehreren
  Dropzonen desselben Starts ergeben sich unterschiedliche Azimute; die erste Stufe
  liegt näher am Startplatz als die Nutzlastverkleidung.
- **Die Gruppierung stützt sich auf das Zeitfenster.** NOTAMs desselben Starts, deren
  Aktivierungszeiten mehr als 30 Minuten auseinanderliegen, bleiben getrennt. Umgekehrt
  können zwei unabhängige Starts im selben Zeitfenster nur dann getrennt werden, wenn
  ihre Zonen mehr als 15° Azimut auseinanderliegen – zwei gleichzeitige Starts vom selben
  Startplatz in ähnliche Richtung würden zusammengefasst.
- **Nur NOTAMs mit Koordinaten werden gruppiert.** Ein NOTAM ohne verwertbare Koordinaten
  landet im Review und wird keinem Start zugeordnet, auch wenn es zeitlich passt.
- **Die Referenzkoordinaten sind Näherungswerte.** Insbesondere die beiden chinesischen
  Seestart-Gebiete (`HIIS`, `HYOS`) sind mobil und nur grob verortet. Beide CSVs sind
  bewusst einfach gehalten, damit sie ohne Code-Änderung gepflegt werden können.
- **Die FIR-Liste ist ein Punktmodell**, keine Polygongeometrie. Die geographische
  Rückfallzuordnung misst Distanz zum FIR-Mittelpunkt, nicht die Lage im FIR-Gebiet.
- **Ohne Koordinaten im Text gibt es keine Trajektorie.** In realen Beständen betrifft
  das einen erheblichen Anteil der NOTAMs; sie landen im Review-Tab.

## Erfahrung mit Echtdaten

Ein zweiter Durchlauf über denselben FAA-FNS-Export nach Ergänzung der Startsignatur und
des `N380300E1071800`-Formats hob die Trefferzahl bei Stufe `MITTEL` von 2 auf 11 – die
zusätzlichen neun sind chinesische Start-NOTAMs, die zuvor mangels Schlüsselwort als
`NIEDRIG` verworfen wurden. Darunter `A4631/26` und `A4632/26`, die zum selben
Jiuquan-SSO-Start gehören und mit 189,5° bzw. 188,7° konsistent auf derselben Bahn liegen.


Gegen einen FAA-FNS-Export (332 Zeilen, Freitextsuche `SFC UNL` über ein Jahr) lieferte
eine erste Fassung 145 vermeintliche Starts, darunter 109 russische – tatsächlich waren
das Suchscheinwerfer über London, Wetterballons, UNIFIL-Schiffe und eine taiwanische
Luftwaffenübung. Ursache war die Kombination aus den bewusst breiten Triggern und einer
geographischen FIR-Rückfallzuordnung ohne Distanzgrenze. Mit Konfidenz-Scoring und
Nations-Attribution bleiben bei Stufe `MITTEL` zwei Treffer übrig, beide korrekt:
japanische NOTAMs zu einem nordkoreanischen Start (Azimut 179°, Inklination 89°).

Die Lehre für den Betrieb: Stufe `MITTEL` als Standard, `NIEDRIG` nur zur manuellen
Nachschau, und der Review-Tab gehört zur täglichen Auswertung dazu.

Nach Ergänzung der Start-Gruppierung und der weiteren Schreibweisen ergeben sich aus
denselben Daten **5 Starts aus 11 Sperrzonen** – jeder Start mit mindestens zwei Zonen:

| Start | Nation | Startplatz | NOTAMs | Azimut | Inklination | Streuung |
|---|---|---|---|---|---|---|
| START-01 | Nordkorea | Sohae | P3998/26, P3999/26 | 178,9° | 89,1° | 0,8° |
| START-02 | China | Taiyuan | A4456/26, A4457/26 | 188,8° | 96,8° | 0,0° |
| START-03 | China | Jiuquan | A4631/26, A4632/26, F3573/26 | 189,3° | 97,0° | 1,1° |
| START-04 | China | Jiuquan | A4694/26, A4695/26 | 108,9° | 44,4° | 8,9° |
| START-05 | Nordkorea | Tonghae | B4912/26, B4913/26 | 180,0° | 90,0° | 0,1° |

START-03 zeigt die Gruppierung am deutlichsten: drei Sperrzonen in 129 km, 1 320 km und
6 111 km Entfernung, alle innerhalb von 1,1° auf derselben Linie nach Süden – erste Stufe,
zweite Stufe und Nutzlastverkleidung eines sonnensynchronen Starts von Jiuquan. Die dritte
Zone liegt im Indischen Ozean und wurde über ein australisches NOTAM gemeldet, das
ausdrücklich „CHINESE AEROSPACE FLIGHT ACTIVITIES" nennt.
