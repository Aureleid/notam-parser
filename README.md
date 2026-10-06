# NOLA — NOTAM Launch Analyzer

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
| `weltraumbahnhoefe_koordinaten_updated.csv` | 32 Startplätze der sechs Zielnationen |
| `icao_fir_acc_coordinates_updated.csv` | 130 FIRs/ACCs mit Land und zugehöriger Startnation |
| `traegersysteme_updated.csv` | 65 Trägersysteme mit Nation, Name und Abkürzung |
| `archiv_import.py` | Archiv-Import historischer NOTAMs (Logik ohne Streamlit) |
| `gcat_startplaetze.csv` | GCAT-Startplatzcode → NOLA-Kürzel und Land (nur Archiv-Import) |
| `gcat_traegersysteme.csv` | GCAT-Schreibweise → Trägerkürzel (nur Archiv-Import) |
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

Die Beschreibung steht ausschließlich in der Oberfläche. Weder die Start-CSV noch der
JSON-Export führen sie — in einer Tabellenspalte wäre sie ein mehrzeiliger Fließtext,
und im JSON blähte sie jeden Startdatensatz um ein Vielfaches auf.

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

## Trägersystem zuweisen

Welche Rakete hinter einem Start steckt, lässt sich aus einem NOTAM nicht ableiten — die
Meldung sperrt Luftraum, sie nennt kein Fluggerät. Deshalb wird das Trägersystem nicht
geraten, sondern von Hand gesetzt.

Das Dropdown **Trägersystem** steht an zwei Stellen: in jedem aufgeklappten NOTAM unter
**NOTAM Data** und in jedem Prüffall unter **Unassigned / Review**. Es bietet alle 51
Einträge der Referenz `traegersysteme_updated.csv`, gestaffelt:

```
— ohne Zuweisung —
Chang Zheng 2C (CZ-2C)          ← Träger der erkannten Nation zuerst
Chang Zheng 2D (CZ-2D)
…
──────── andere Nationen ────────
Soyuz-2.1a (Soyuz-2.1a) · Russland   ← übrige mit Nation dahinter
…
```

Eine harte Filterung nach Nation wäre falsch: im Review korrigiert man gerade eine
möglicherweise falsche Zuordnung und braucht dort die volle Liste. Steht die Startnation
noch nicht fest — im Review der Regelfall, weil ohne Koordinaten keine Zuordnung möglich
ist —, staffelt die Liste nach dem Textbeleg oder der FIR, sofern diese auf eine Zielnation
zeigen. Das ist reine Sortierhilfe und präjudiziert nichts.

Die Trennzeile ist technisch wählbar, weil Streamlit keine inaktiven Einträge kennt. Wird
sie gewählt, bleibt die bisherige Zuweisung stehen und das Dropdown springt zurück.

**Die Wahl gilt für den ganzen Start.** Gehören mehrere Sperrzonen zu einem erkannten
Start, übernehmen alle dasselbe Trägersystem — dieselbe Rakete kann nicht in einer Zone
eine andere sein als in der nächsten. Gespeichert wird trotzdem je NOTAM, weil dessen
Schlüssel über Sitzungen hinweg stabil ist, die Start-Kennung (`START-01`) dagegen nicht.
Tragen zwei NOTAMs desselben Starts verschiedene Systeme — möglich, wenn eine spätere
Gruppierung zwei zuvor getrennte Starts zusammenfasst —, behält jedes NOTAM seine eigene
Zuweisung und der Start wird als *uneinheitlich* ausgewiesen statt stillschweigend eine der
beiden zu bevorzugen.

In der **Launch Overview** erscheint das Ergebnis als Spalte `Trägersystem` — dort nur
lesbar. Grund: `st.dataframe` beherrscht Zeilenauswahl, aber keine editierbaren Zellen;
`st.data_editor` beherrscht editierbare Zellen, aber keine Zeilenauswahl. Beides zugleich
gibt Streamlit nicht her, und der Klick-Sprung zum NOTAM-Volltext ist die wertvollere
Funktion.

Die Zuweisung ist ein Etikett: sie ändert **nichts** an der Erkennung — weder Nation noch
Startplatz, Azimut oder Orbit. Sie steht in beiden CSV-Exporten und im JSON-Export und wird
wie die übrigen Entscheidungen in `notam_workspace.json` gespeichert. Wird ein zugewiesenes
Trägersystem später über das Optionsmenü aus der Referenz entfernt, bleibt die Zuweisung
sichtbar und wird als *„nicht mehr in der Referenz"* gekennzeichnet, statt unbemerkt zu
verschwinden.

## Nutzlast eintragen

Unter dem Trägersystem-Dropdown steht in *NOTAM Data* ein Freitextfeld **Payload**. Bewusst
kein Auswahlfeld: welche Nutzlast an Bord war, steht in keiner Referenz und ist bei
chinesischen Starts oft erst Tage später bekannt. Das Feld darf leer bleiben und lässt sich
jederzeit nachtragen.

Es steht nur unter *NOTAM Data*, nicht im Review — dort ist erst die Frage, *ob* die Meldung
überhaupt einen Start beschreibt. Wie beim Trägersystem gilt der Eintrag für alle Sperrzonen
desselben Starts; widersprechen sich zwei Texte nach einer Umgruppierung, wird der Start als
*uneinheitlich* ausgewiesen. Der Wert erscheint als Spalte `Payload` in der Launch Overview
(nur lesbar) und in beiden CSV-Exporten sowie im JSON.

## Startarchiv

Die vierte Referenz unterscheidet sich von den drei anderen: sie wird nicht eingelesen,
sondern von der Anwendung selbst geschrieben. `startarchiv_updated.csv` hält fest, was zu
jedem erkannten Start bekannt ist — eine Zeile je Start, nicht je NOTAM:

| Spalte | Beispiel |
|---|---|
| `NOTAM` | `A4631/26, A4632/26, F3573/26` |
| `Startdatum` | `21.09.2026` |
| `Startzeit` | `01:30` |
| `Nation` | `China` |
| `Weltraumbahnhof` | `JSLC` |
| `Trägersystem` | `CZ-2D` |
| `Payload` | `Yaogan-XX` |
| `Orbit` | `SSO` |
| `Inklination` | `97.4` |
| `Azimuth` | `190.3` |
| `Dropzones` | `19.6000 110.9500; 18.8333 111.2500` |

Eine Zeile entsteht für jeden Start, den die Anwendung als solchen führt — auch ohne
Nutzlast. Die Filter der Seitenleiste wirken dabei bewusst **nicht**: ob ein Start ins Archiv
gelangt, soll nicht davon abhängen, was man sich gerade anzeigen lässt.

Beim nächsten Import wird derselbe Start **aktualisiert statt doppelt angelegt**;
Erkennungsmerkmal ist die Kombination aus **Startdatum und NOTAM-Kennungen**. Die
automatischen Spalten werden dabei überschrieben, die Nutzlast nicht: sie ist das Einzige,
was kein Automat kennt, und bleibt stehen, wenn der neue Durchlauf nichts dazu weiß.

### Warum der Startplatz nicht zum Erkennungsmerkmal gehört

Er stand einmal darin, und das war ein Konstruktionsfehler. Der Startplatz ist eine
**Eigenschaft** des Starts, nicht seine **Identität** — und er ändert sich, wenn die
Erkennung besser wird. Belegt im eigenen Bestand:

| Zeile | NOTAM | Platz | Inklination |
|---|---|---|---|
| 10 | `F0511/26` | WSLC | 95,0 |
| 11 | `F0511/26, A0443/26` | WSLC | 94,2 |
| 12 | `A0465/26, A0466/26, F0511/26, …` | **SEA-21N112E** | 97,6 |

Drei Zeilen, ein Start, `F0511/26` in allen drei. Dasselbe für den 11.02. mit `F0494/26`.
Jede Verbesserung — die Seestart-Ableitung, die `AREA1/AREA2`-Trennung — erzeugte einen neuen
Schlüssel und damit eine neue Zeile statt eines Updates. Von 16 Zeilen sind dadurch **fünf
falsch**: eine sachlich, vier als überholte Dubletten.

Seit dem 02.10.2026 ist der Platz aus dem Schlüssel entfernt. Gemessen: 16 Zeilen ergeben mit
und ohne Platz je 16 Schlüssel, **keine bestehende Zeile fällt zusammen**. Damit sind zwei
Fälle behoben — die Seestart-Ableitung und die manuelle Pad-Wahl, die einen Start von `WSLC`
auf `HAIN` verschiebt und vorher nachweislich eine zweite Zeile erzeugte.

Gespeicherte Löschschlüssel werden beim Laden umgestellt (`migrate_archive_keys`), sonst
wären von Hand gelöschte Zeilen zurückgekommen.

**Was offen bleibt:** Wird die *Gruppierung* besser, wächst die Kennungsmenge und der
Schlüssel ändert sich trotzdem — genau so sind die vier Dubletten entstanden. Das zu lösen
heißt, über **Kennungs-Überschneidung** zu suchen statt auf Gleichheit zu prüfen: teilt eine
neue Zeile mindestens eine Kennung mit einer vorhandenen, ist es derselbe Start. Der
Abbruch-Fall bliebe dabei korrekt getrennt — die Zeilen vom 11. und 12.02. teilen keine
einzige Kennung. Das ändert aber die Semantik von `merge_archive` und ist deshalb eine
Entscheidung, keine Nacharbeit.

Im Optionsmenü hat das Archiv einen eigenen Reiter — mit Suche und **Entfernen** je Zeile,
aber ohne Formular zum Anlegen: Zeilen entstehen aus der Auswertung, die Nutzlast trägt man
unter *NOTAM Data* nach. Eine gelöschte Zeile bleibt gelöscht, auch wenn ihr NOTAM noch in
der Tagesdatei steht — der Schlüssel wandert dafür in `notam_workspace.json`.

Die Datei ist in `.gitignore` aufgeführt: sie leitet sich aus den lokalen NOTAM-Rohdaten ab
und bleibt wie diese lokal.

## Archiv-Import

Historische Starts von China, Russland, Indien, Iran und Nordkorea kommen über den Reiter
*Archive Import* im Optionsmenü ins Startarchiv. Quelle sind die NOTAM-Sammlungen im
NASASpaceflight-Forum (NSF). Der Ablauf in vier Schritten:

1. **Seiten speichern** — die Forenseiten im Browser als HTML sichern oder eine ganze Seite
   als Text kopieren. Ein automatischer Abruf ist nicht möglich, NSF steht hinter Cloudflare.
2. **Hochladen oder einfügen** — beliebig viele Seiten auf einmal (5 MB je Datei, 200 MB je
   Stapel). Zitate, Skripte und Forenkommentare werden verworfen, doppelte NOTAMs über
   Kennung und B-Zeit zusammengeführt. Jeder Tag wird mit derselben Erkennung ausgewertet wie
   im Tagesbetrieb; US-Starts werden danach verworfen und nur gezählt.
3. **Eindeutige Treffer bestätigen** — zu jedem erkannten Start schlägt GCAT Rakete und
   Payload vor, nie Inklination, Azimut oder Nation. *Confirm all unique matches* übernimmt
   alle eindeutigen Paarungen auf einmal, die übrigen werden nach Jahr gefiltert einzeln
   bestätigt oder verworfen.
   Erst dann wird ins Archiv geschrieben. Steht ein Start schon aus dem Tagesbetrieb im
   Archiv, werden nur Trägersystem und Payload ergänzt.
4. **Prüfliste abarbeiten** — NOTAMs, die die Erkennung zur Prüfung stellt oder ohne
   Startplatz lässt, werden mit *Space Launch* oder *Hide* entschieden.

Der Reiter ist **nur lokal** sichtbar: nicht in der veröffentlichten Fassung und nur, wenn
die Anfrage vom eigenen Rechner kommt. Korpus und Importzustand liegen in
`archiv_korpus.json` und `archiv_import.json`, die GCAT-Liste im Cache
`gcat_launch_cache.tsv` — alle drei lokal und in `.gitignore`. Die Begründung steht in
`docs/decisions/ADR-0001-archiv-import-nola-erkennt-gcat-schlaegt-vor.md`.

Startliste: GCAT (J. McDowell, CC-BY), `planet4589.org/space/gcat`.

## Warum mehr Referenzdaten den Review nicht leeren

Naheliegende Annahme: mehr FIRs in der Referenz → weniger unzugeordnete NOTAMs → weniger
Review. **Gemessen stimmt das nicht.** Auf der Echtdatei vom 18.09.2026 alle 19 fehlenden
ICAO-Codes testweise ergänzt:

```
ohne Ergänzung              Review 127 | Starts 14
mit 19 zusätzlichen FIRs    Review 127 | Starts 14
```

Die Ergänzung verschiebt nur die Begründung, sie löst keinen Fall auf. Denn ein NOTAM
scheitert nicht daran, dass seine FIR unbekannt ist, sondern daran, dass nichts es mit
einer Zielnation verbindet.

Auch **weitere Startnationen** leeren den Review nicht — sie schichten ihn um. Die vier
neuseeländischen `NZZO`-Dropzones (vermutlich Rocket Lab von Māhia) verschwänden nicht, sie
würden zu vier Starts, die geprüft und eingeordnet werden wollen.

### Was dabei doch herauskam: MMFR

Bei der Prüfung fiel eine echte Lücke auf. Unter den 48 Fällen mit unbekannter FIR hatten
19 **hohe** Konfidenz, darunter:

```
B1848/26  MMFR  Score  9  "DANGEROUS AREA FOR LAUNCH OF ROCKET SPACEX STARSHIP FLT-14"
B1847/26  MMFR  Score  9  dieselbe Aktivität, zweites Gebiet
B1862/26  MMFR  Score 12  "REENTRY OF ROCKET SPACEX SL 15-27 STAGE 1"
```

Mexiko hat kein eigenes Weltraumprogramm — und trägt trotzdem SpaceX-Meldungen, weil
Starship von Boca Chica mexikanischen Luftraum überfliegt. `MMFR` steht seit dem in der
Referenz (Mexico City ACC, Startnation `USA`), und die Erkennung stieg von **14 auf 17
Starts**.

Das ist zugleich die Widerlegung der Regel „Land ohne Startprogramm → aussortieren": Ein
Land braucht kein eigenes Programm, um von fremden Starts überflogen zu werden.

Die Drittstaaten-Regel bleibt dabei wirksam: MMFR liegt in Mexiko, die USA werden nur
zugelassen, weil `SPACEX` im Text steht. Zwei weitere MMFR-Meldungen — US-Daueradvisories
mit Laufzeit bis 2027 — bleiben korrekt im Review.

> `SCCZ` (Chile) wurde **nicht** aufgenommen. Die dortige Wiedereintrittszone bei
> 59°S 127°W wurde im Test *Russland/Vostochny* zugeordnet; bei einer Zone im Südpazifik
> ist das nicht belastbar, solange nicht entschieden ist, welche Nationen dort plausibel
> wiedereintreten.

## Seestarts von beweglichen Plattformen

China startet zunehmend von Schiffen und Plattformen. Solche NOTAMs nennen keinen
Startplatz, und die Plattform steht nicht dort, wo eine Referenztabelle sie vermutet. Für
diesen Fall entscheidet nicht die Referenz, sondern die **Geometrie des NOTAM-Satzes**.

### Der Fall, an dem es entwickelt wurde

Ein chinesischer Start am 22.07.2026, fünf NOTAMs aus drei Luftraumregionen:

| NOTAM | FIR | Rolle |
|---|---|---|
| `A2371/26`, `P3423/26` | Taiwan, Japan | Vorankündigung 21.–27. Juli, täglich 0200–0600 — siehe [Vorankündigungen](#vorankündigungen) |
| `A2827/26` | Shanghai (China) | **Startpunkt** — Kreis um 31,20N 123,70E, Radius 20 km |
| `A2385/26` | Taiwan | Dropzone bei 28,2N |
| `P3438/26` | Japan | zwei Dropzones bei 28,2N und 21,4N |

Die Rechnung entscheidet:

```
vom Kreismittelpunkt aus   178,0° · 174,7° · 177,7°   Streuung  3,3°
von HYOS aus (473 km weg)  149,7° · 160,8° · 168,5°   Streuung   19°
```

Vom Kreis aus ist es eine saubere Bahn mit Inklination 87,9° — eine SSO-Mission. Vorher
führte NOLA den Startpunkt selbst als Dropzone und schrieb den Start dem 473 km entfernten
`HYOS` zu.

### Wie die Ableitung arbeitet

`derive_launch_point()` sucht in einem Zeit-Cluster die Zone, von der aus sich die übrigen
auf einer Bahn aufreihen. Zuerst kreisförmige Zonen — eine Plattformsperrung ist ein
kleiner Kreis —, danach als Auffangnetz jede Zone des Clusters. Übernommen wird das
Ergebnis nur, wenn

- die Streuung ≤ 15° beträgt (`SEA_LAUNCH_MAX_SPREAD_DEG`),
- der abgeleitete Punkt ≥ 150 km von jedem verzeichneten Startplatz entfernt liegt
  (`SEA_LAUNCH_MIN_SITE_DISTANCE_KM`) — darunter erklärt die gepflegte Referenz den Start
  besser als eine Schätzung aus drei Zonen,
- und die Bahn die der Referenz um mindestens 5° schlägt (`SEA_LAUNCH_SPREAD_MARGIN_DEG`).

Die Kennung kodiert die Position: `SEA-31N124E`. Kein Verzeichnis zu pflegen, und zwei
Starts von derselben Stelle bekommen dieselbe Kennung.

Die Nation kommt aus dem Luftraum des **Ursprungs**-NOTAMs, nicht aus der Geometrie: Der
Startpunkt liegt in chinesischer FIR, die Dropzones berühren taiwanesischen und japanischen
Luftraum. Genau dafür gibt es die Anker-Regel — der Ursprung trägt die Nation, die übrigen
Zonen erben sie.

> **Zwei Fehler mussten dafür erst weichen.** Der Splitter zerlegte den Cluster anhand der
> Referenz-Streuung und warf dabei ausgerechnet das NOTAM heraus, das den Startpunkt
> beschrieb — er sah die 19° und nicht die 3,3°. Und `AREA1:`/`AREA2:` wurde nicht
> getrennt, weil das Trennmuster `AREA\s+\d` ein Leerzeichen verlangte und
> `extract_items` die Zeilenumbrüche faltet; aus zwei Gebieten 740 km auseinander wurde ein
> Polygon mit einem Mittelpunkt, der nirgends liegt.

### Zweiter belegter Fall: Südchinesisches Meer, 11./12.02.2026

Acht NOTAMs aus vier Luftraumregionen, derselbe Versuch an zwei Tagen — am 11. abgebrochen,
am 12. wiederholt. Startpunkt als Kreis mit 10 km Radius bei 21,37N 112,13E in der
Guangzhou-FIR; Dropzones in Singapur und Vietnam (~1400–1500 km), eine weitere im Indischen
Ozean vor Australien (**5991 km**).

Dieser Fall brauchte keine neue Erkennungslogik — er lief mit dem gebauten Verfahren
durch — legte aber einen Fehler in der Bahnrechnung frei:

```
Tag 1   Azimut 190,4°   Inklination 99,7°   ->  Sun-synchronous
Tag 2   Azimut 191,3°   Inklination 100,5°  ->  Retrograde
```

Derselbe Start, zwei Orbitklassen. Ursache: Die Inklination wurde ohne Erdrotation
gerechnet.

### Die Erdrotation in der Bahnrechnung

Zur Startgeschwindigkeit addiert sich die Ostkomponente der Erddrehung,
`V_erde · cos φ` (465,1 m/s am Äquator). `orbital_azimuth_deg()` rechnet daraus den
**Bahnazimut**, und erst dieser geht in `cos(i) = cos φ · sin(Bahnazimut)`:

```
Startazimut 190,4°  ->  Bahnazimut 187,2°  ->  Inklination 96,7°
Startazimut 191,3°  ->  Bahnazimut 188,1°  ->  Inklination 97,6°
```

Beide Tage ergeben jetzt SSO — und 96–98° ist das Band, in dem sonnensynchrone Bahnen
tatsächlich liegen. Bei einem Start nach Osten ändert die Drehung nichts an der Richtung,
dort bleibt die Rechnung unverändert.

### Warum die Orbitbänder breit sind

Die Korrektur legte offen, dass die Bänder auf die *unkorrigierte* Formel geeicht waren:
Taiyuan und Jiuquan, beides echte SSO-Starts, fielen danach mit 94,8° und 95,1° aus dem
alten Band 96–100 heraus.

Die Inklination ist eine Abschätzung aus Startplatzbreite und einem Azimut, der selbst aus
der Richtung zu einer Dropzone stammt. Gemessen an vier bekannten SSO-Starts streut sie um
rund drei Grad. Das SSO-Band liegt deshalb bei **93–103°**, retrograd beginnt bei 103°. Ein
schmaleres Band hätte denselben Start je nach Tag anders eingeordnet.

### Das Seestart-Protokoll

`seestarts_updated.csv` wird von der Anwendung geschrieben, wie das Startarchiv. Eine Zeile
je abgeleitetem Start, mit Position, Radius, Bahn, Dropzones — und einer Spalte
**`Nächster bekannter Platz`** (`HYOS, 473 km`). Diese letzte Spalte zeigt über die Zeit, ob
sich ein neues Startgebiet herausbildet oder ob eine vorhandene Referenz nur ungenau liegt.

**Das Protokoll ist ein Protokoll, kein Nachschlagewerk.** Es fließt ausdrücklich *nicht* in
die Startplatz-Suche zurück: Eine Plattform steht beim nächsten Mal woanders, und alte
Positionen als Kandidaten zu führen hieße, genau den Fehler nachzubauen, den die Ableitung
behebt. Ein Test wacht darüber.

`HIIS` und `HYOS` bleiben in der Startplatz-Referenz, sind aber als **Heimathäfen** zu
lesen, nicht als Startpunkte — bei diesem Start hat `HYOS` die falsche Antwort geliefert.

## Zwei Startplätze an einem Ort: Wenchang und Hainan

In Wenchang liegen zwei Startgelände: die staatlichen Pads (`WSLC`) und der kommerzielle
Platz unmittelbar nördlich davon (`HAIN`, *Hainan Commercial Launch Site*).

### Warum die Geometrie das nicht entscheiden darf

Sie liegen **1,92 km** auseinander.

| Abstand der Plätze | Zone 500 km | Zone 1000 km | Zone 2000 km |
|---|---|---|---|
| 1,92 km (WSLC/HAIN) | 0,220° | 0,110° | 0,055° |

Die Auswahlschwelle des Programms liegt bei **15°**. Drei Größenordnungen zu grob.

Schlimmer: die Startplatzwahl rechnet `Streuung × 100 + mittlere Entfernung`. Bei diesem
Abstand entscheidet also **verhundertfachtes Rauschen**. Ein Versuch mit einer zweiten
gewöhnlichen Referenzzeile, gemessen an vier realistischen Startkorridoren:

| Korridor | gewählter Platz | Score-Vorsprung |
|---|---|---|
| Südkurs, 2 Zonen | Hainan | 0,5 |
| Südostkurs, 2 Zonen | Hainan | 17,2 |
| Ostkurs, 2 Zonen | Wenchang | 34,7 |
| eine Zone südlich | Wenchang | 1,9 |

Es kippt mit dem Dropzone-Muster. Zwei Starts derselben Rakete vom selben Pad wären auf
verschiedene Plätze gebucht worden — die falsche Zuordnung, die in diesem Programm
schwerer wiegt als ein Fall im Review.

**Deshalb ist `HAIN` von der automatischen Wahl ausgenommen.** Nennt ein NOTAM den Platz
ausdrücklich im Text, gilt er trotzdem: der Text ist die stärkere Quelle als die Geometrie.

Die Regel ist allgemein, nicht auf Wenchang verdrahtet: Plätze derselben Nation, die näher
als `CO_LOCATED_SITE_KM` = **5 km** beieinanderliegen, bilden eine Nachbarschaftsgruppe; der
zuerst verzeichnete bleibt automatisch wählbar, spätere nur von Hand. Die Schwelle sitzt in
der gemessenen Lücke der Referenz: engstes Paar 1,92 km, nächstes 10,45 km (`KXMR`/`KTTS`).

> Die Floridagruppe bei 10–20 km ist mit 0,3–2,3° **ebenfalls** schwach getrennt. Sie bleibt
> bewusst unberührt: dort steht keine Zuordnung zur Debatte, und eine Änderung würde
> Ergebnisse betreffen, die niemand in Frage gestellt hat.

### Was keine Lösung war

Eine Tabelle *Trägersystem → Pad* lag nahe und ist falsch. **CZ-8 flog von Anfang an von
beiden Geländen** — Debüt 2020 von `WSLC`, erster Start vom kommerziellen Pad 1 ebenfalls
eine CZ-8. Die Tabelle wäre am Tag ihrer Entstehung schon gebrochen.

Der allgemeine Fall ist schlimmer: welche Rakete von welchem Pad fliegt, ist **keine
Eigenschaft der Rakete, sondern eine Momentaufnahme der Praxis**. Derselbe Fehlertyp wie der
Archivschlüssel, der den Analysestand einfror, und wie die Verzweigung auf übersetzten Text.
Und er verrottet **lautlos**: fliegt CZ-12 nächstes Jahr von Jiuquan, sagt NOLA „Hainan" und
niemand merkt es. Ein Test verbietet deshalb jede Zeile, die ein Trägersystem auf ein
Platzkürzel abbildet.

### Wie es stattdessen geht

**Von Hand, mit Vorgabe „nicht bestimmt".** Eine Auswahlliste erscheint unter NOTAM Data und
Review — aber nur bei Startplätzen mit Nachbarn; überall sonst wäre sie eine Scheinfrage.
Die Wahl gilt für alle Sperrzonen desselben Starts, wird im Arbeitsstand gesichert und ist
zurücknehmbar: ohne Wahl gilt wieder, was die Geometrie ergeben hatte.

Die Vorgabe ist **nicht** der naheliegende Platz. Eine Vorgabe, die zufällig oft richtig ist,
wäre eine Behauptung ohne Beleg — und später nicht mehr von einer geprüften Angabe zu
unterscheiden. Die Spalte `Pad` in der Startansicht sagt deshalb `not determined`, `by hand`
oder `-` (kein Nachbar vorhanden), und der Klartext schreibt es aus.

**Azimut und Inklination werden bei einer Pad-Wahl nicht neu gerechnet.** Der Unterschied
liegt bei 0,06–0,22° und damit weit unter der Genauigkeit einer Abschätzung, die ihre
Inklination selbst nur auf wenige Grad angibt. Sonst gäbe es zwei Zahlen für dieselbe Bahn,
je nachdem ob jemand das Pad gesetzt hat.

### Der Hinweis rechnet, statt zu behaupten

Neben der Auswahlliste steht, was das **eigene Archiv** sagt:

```
Your archive: CZ-12 flew 2x HAIN.
Your archive: CZ-8 flew 1x HAIN, 1x WSLC. WSLC may also mean the pad was never determined.
```

Keine Tabelle im Code, sondern eine Zählung über `Trägersystem` und `Weltraumbahnhof` im
Startarchiv — zwei Spalten, die es schon gibt, also **ohne Schemaänderung**. Sie aktualisiert
sich selbst: fliegt ein Träger einmal von woanders, verschiebt sich die Zahl und man sieht es.

Eine Schieflage gehört dazugesagt und steht im Hinweis: `HAIN` kann nur von Hand gesetzt
worden sein, denn die Geometrie wählt es nie. `WSLC` kann dagegen auch bedeuten, dass das Pad
nie bestimmt wurde. Beim ersten Durchlauf sagt die Zählung noch nichts — sie verdient sich
die Aussage.

## Vorankündigungen

Derselbe Luftraum wird oft Tage vor dem Start reserviert: eine mehrtägige Meldung mit
täglichem Fenster, dann am Starttag eine kurze Meldung für dieselbe Fläche. Das sind nicht
zwei Vorgänge, sondern einer.

Im Seestart-Fall sind das `A2371/26` (Taiwan) und `P3423/26` (Japan), gültig 21.–27. Juli,
täglich 0200–0600. Sie blieben im Review — zu Recht: sie liegen in taiwanesischem und
japanischem Luftraum, nennen weder China noch einen Startplatz, und die Drittstaaten-Regel
lässt keine geratene Nation zu.

### Der Text hilft hier nicht, die Geometrie schon

| Vergleich | Mittelpunkte | Zonengrößen |
|---|---|---|
| Vorankündigung Taiwan ↔ Starttag Taiwan | **0,91 km** | 44 / 45 km |
| Vorankündigung Japan ↔ Starttag Japan | **1,20 km** | 52 / 52 km |
| nächster Nicht-Treffer | 328,44 km | 44 / 0 km |

Die Mittelpunkte liegen auf **zwei Prozent** des Zonenradius zusammen. Das ist kein Zufall,
sondern dieselbe im Text ausbuchstabierte Fläche.

### Sechs Bedingungen, alle sprachfrei

Gepaart wird nur, wenn **alle** zutreffen:

1. Die Nation des Starts steht unter den Kandidaten der Meldung. Die Paarung hebelt die
   Drittstaaten-Regel nicht aus, sie belegt nur eine zulässige Kandidatin — genau das, was
   Gruppierung auch sonst tut.
2. Die Meldung läuft mindestens 24 h.
3. … und mindestens das Vierfache des Startfensters, das sie ankündigt. Sonst würde eine
   zweite kurze Meldung desselben Starts als dessen eigene Vorankündigung gelten.
4. Das Startfenster liegt vollständig in ihrer Laufzeit.
5. Nennt sie ein tägliches Fenster, liegt das Startfenster darin.
6. Mindestens eine ihrer Zonen ist deckungsgleich mit einer Zone des Starts.

Die Schwellen für Bedingung 6 sind **relativ**, nicht absolut: zulässiger Versatz höchstens
25 % der kleineren Zone, und die kleinere muss mindestens 60 % der größeren halten. Ein
fester Kilometerwert wäre einem 20-km-Kreis zu weit und einer 500-km-Dropzone zu eng.

**Welche Bedingung trägt?** Gemessen am Bestand vom 18.09.2026: 792 (NOTAM, Start)-Paare
kämen in Frage. Die Zeitbedingungen bestehen einzeln 41 bis 73 % davon — sie allein würden
nichts tragen. Die Deckungsgleichheit der Zonen schließt **alle 792** aus. Es gab dort keine
einzige Paarung, auch keine falsche.

**Eindeutigkeit ist Bedingung.** Passt eine Meldung auf zwei Starts, bleibt sie liegen. Eine
falsche Zuordnung wägt in diesem Programm schwerer als ein Fall mehr zur Durchsicht.

### Was die Paarung ändert — und was nicht

Die Meldung erhält Nation und Startplatz des Starts, bekommt die Art `Advance notice` und
verlässt das Review. Der **Start selbst bleibt unberührt**: die angekündigte Fläche *ist*
die Sperrzone vom Starttag, als weitere Zone gezählt wäre sie eine Doppelzählung und würde
Azimut und Streuung verfälschen. Die Paarung läuft deshalb erst *nach* der Gruppierung, und
die Kennungen stehen in einem eigenen Feld, nicht unter den NOTAMs des Starttags.

In der Startansicht steht dafür die Spalte **`Advance Notice`** mit Kennungen und Vorlauf
(`A2371/26, P3423/26 (25 h)`). Der Klartext nennt sie und begründet, warum sie keine weitere
Zone ist. Der JSON-Export führt `advance_notam_ids`, `advance_from` und
`advance_notice_hours`.

Trägersystem und Nutzlast gelten startweit und erreichen die Vorankündigung mit — in beide
Richtungen. Wer auf ihrer Zeile das Trägersystem wählt, meint denselben Start.

**Automatisch ausgeblendete Meldungen bleiben ausgeblendet.** Diese Liste ist die Kuration
des Benutzers, kein Zwischenergebnis.

### Ein Parserfehler, der dabei auffiel

Das D-Item kennt beide Trennzeichen: `0200-0600` und `0200/0600`. Gelesen wurde nur der
Bindestrich. Gemessen am Bestand vom 18.09.2026: von 100 D-Items mit Tagesfenster nutzen
**acht** den Schrägstrich, meist in der Form `DLY BTN 1700/0400`. Für diese acht fand der
Parser kein Fenster — und ohne Fenster greift der Daueranordnungs-Deckel und stuft auf
`LOW` zurück. Im Bestand vom 18.09. lief keine davon über 720 h, die Fehlwirkung blieb also
aus; die japanische Vorankündigung `P3423/26` schreibt ihr Fenster aber genau so.

Drei Formen bleiben absichtlich unlesbar: `EVERY DAY,24 HOURS` heißt durchgehend aktiv, dort
*soll* der Deckel greifen. `DLY BTN 1700/200` ist verstümmelt — `200` könnte `0200` oder
`2000` meinen, und hier wird nicht geraten. Und volle Datum-Zeit-Paare (`2609170900 TO
2609171500 …`) sind ein Terminplan, keine tägliche Wiederholung.

## Automatisches Ausblenden

NOTAMs mit Konfidenz `LOW` **und** mindestens einem Ausschlussbegriff landen beim Import
direkt unter *Excluded*, nicht im Review.

Der Anlass: Auf der echten FAA-FNS-Datei vom 18.09.2026 landeten **275 von 332** NOTAMs im
Review — als Arbeitsmittel unbrauchbar. Die Regel nimmt **148** davon heraus, der Review
sinkt auf 127. Die 14 erkannten Starts bleiben unverändert.

**Die Konfidenzstufe ist die Bremse, nicht der Ausschlussbegriff.** Ein echtes
Start-NOTAM, in dem zufällig `BALLOON` oder `ALT RESERVATION` auftaucht, erreicht über
Q-Code, SFC-UNL und kurzes Aktivierungsfenster trotzdem `MEDIUM` oder `HIGH` und bleibt
unangetastet. Der Ausschlussbegriff allein als Auslöser hätte diese Bremse nicht.

Zehn der 148 tragen gleichzeitig eine Startsignatur oder einen Raumfahrt-Begriff. Alle
wurden einzeln geprüft: Schießübungen (Taiwan, Türkei, Portugal, Indien), Amateurraketen
in Black Rock (`AEROPAC`, `EXPERIMENTAL ROCKETRY`), ein indischer Luftraumplan und eine
spanische Militärübung mit `MISSILE LAUNCH`. Kein Orbitalstart darunter.

**Deine Entscheidung gewinnt dauerhaft.** Holst du ein automatisch ausgeblendetes NOTAM
zurück, wandert sein Schlüssel nach `restored_events` in `notam_workspace.json` — der
nächste Import blendet es nicht erneut aus. Ohne das wäre der Knopf wirkungslos: Solange
die Meldung in der Tagesdatei steht, fiele sie beim nächsten Durchlauf sofort wieder heraus.

Unter *Excluded* steht bei jedem Eintrag in der Spalte `Excluded by`, ob die Regel oder du
entschieden hat, und daneben die Begründung mit den gefundenen Begriffen.

> Die Regel greift bewusst **nicht** in `analyze_notams`, sondern erst in der Oberfläche.
> So liegt die Entscheidung an einer Stelle — zusammen mit der Liste der von Hand
> zurückgeholten Fälle. `exclusion_hits()` liefert die Begriffe als Liste, nicht als Satz:
> das Scoring baut daraus eine Begründung, die Regel prüft nur, ob überhaupt einer da ist.
> Beides auf denselben Prosatext zu stützen wäre dieselbe Falle wie bei der
> FIR-Zuordnung.

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

## Oberfläche: Gestaltungsregeln

Die Oberfläche folgt einem festen Regelwerk statt dem Vorgabeaussehen des Baukastens.

### Sprache

Englische Fachbegriffe der Luft- und Raumfahrt statt Übersetzungen: `Launch Site`,
`Launch Window`, `Confidence`, `Reliability`, `Drop Zone`. Das ist die Sprache, in der die
NOTAM-Texte selbst geschrieben sind. Code, Kommentare und diese Datei bleiben deutsch.

**Was bewusst deutsch bleibt:** die Spaltennamen der Dataframes (`Startnation`,
`Weltraumbahnhof`, `Trägersystem` …) und die Werte der Nationen (`Russland`, `Nordkorea`).
Erstere sind über Filter, Export und Review verdrahtet; letztere müssen die Spalte `Land`
der FIR-Referenz treffen. Übersetzt wird beides erst bei der Anzeige, über `COLUMN_LABELS`
beziehungsweise `nation_label()`.

### Wortmarke

```
NOLA
NotamLaunchAnalyzer.
```

Zweizeilig, ohne Wortzwischenräume, Versalbuchstaben trennen die Wörter, Schlusspunkt auf
der zweiten Zeile. Die Wortteile sind farblich differenziert, damit sie trotz fehlender
Zwischenräume lesbar bleiben — aber unbunt: Weiß für das Akronym, Silber und Cool Gray für
die Langform. Darunter folgt mit demselben Durchschuss die Beschreibungszeile; diese
Wiederholung hält den Kopf zusammen.

Die Marke steht groß und mit viel ruhigem Umraum. Das ist keine Geschmacksfrage: Ruhe um
eine Wortmarke herum lässt sie hochwertig wirken und ist Teil der Regel.

### Typografie

Zwei Stapel, beide ohne geladene Webschrift — das spart Lizenz und Netzzugriff:

| Rolle | Stapel |
|---|---|
| Wortmarke, Überschriften | `"Helvetica Neue", Helvetica, Arial, "Liberation Sans", sans-serif` |
| Mengensatz | `"Myriad Pro", Myriad, "Segoe UI", Arial, "Liberation Sans", sans-serif` |

Die Grotesk tritt **nur** in Wortmarke und Überschriften auf, groß und mit Fläche, nie im
Fließtext. Beide Stapel enden bei Arial als Ersatzschrift.

> **Eine Falle dabei:** Streamlits Aufklapp-Pfeile sind Ligatur-Icons — im DOM steht ihr
> Name als Text (`keyboard_arrow_down`), erst die Icon-Schrift macht daraus ein Zeichen.
> Ein breiter `font-family`-Selektor über `[class*="st-"]` trifft diese Spans mit und
> zeigt den Rohtext an. Die Icon-Schrift wird deshalb ausdrücklich wieder gesetzt.

### Farben: unbunte Bühne, bunte Signale

Flächen, Rahmen und Schrift sind neutral. Farbe trägt ausschließlich Information — Status,
Konfidenz, die Marke manuell bestätigter Meldungen. Dadurch gewinnt jedes farbige Zeichen
an Gewicht.

| Rolle | Wert | Kontrast gegen `#141414` |
|---|---|---|
| Hintergrund | `#141414` | — |
| Flächen | `#1E1E1E` | — |
| Rahmen | `#757575` | **4,0:1** |
| Text | `#F2F2F2` | 16,5:1 |
| gedämpfter Text | `#ADAFAF` | 8,4:1 |

Der Rahmenton ist bewusst hell: Vorher lag er bei **1,55:1** und damit unter der 3:1-Grenze
für nicht-textliche Bedienelemente.

### Was nicht vorkommt

Keine Piktogramme. Keine Einblend- oder Hover-Effekte, kein Cursor-Strahl, keine
Scroll-Animation. Keine farbigen Rahmenkarten, keine Icon-Dreier, kein Badge über der
Überschrift. Keine Gedankenstriche in sichtbaren Texten — ausgenommen die
Normalisierungstabelle, die sie aus eingehenden NOTAM-Texten in Bindestriche wandelt. Keine
geladene Webschrift, keine Serif-Kursiv-Akzente, kein Grain über einem Verlauf.

**Auch kein Milchglas.** Es war gebaut und wurde wieder entfernt. Der Grund ist nicht
Geschmack: Glas lebt davon, dass etwas dahinterliegt. Über einer fast schwarzen Bühne
bleibt nur ein hellerer Kasten mit Rahmen. Und das Optionsmenü, die einzige wirklich
überlagernde Fläche, deckt bei `width="large"` fast das ganze Fenster ab — dahinter ist
nichts mehr, was durchscheinen könnte. Dazu setzt Streamlit Fläche und Filter auf diesen
Elementen teilweise selbst; dagegen anzukommen hieß, Spezifität gegen zur Laufzeit erzeugte
Klassennamen zu bieten. Alle Flächen sind deshalb deckend, und die Gestaltungsregeln
greifen nirgends in Streamlits eigene Container ein — das einzige `!important` im
Stylesheet sichert die Icon-Schrift.

Abschnitt 80 der Tests hält diese Regeln fest, damit sie nicht unbemerkt zurückkehren.

## Was die Fremdprüfung vom 25.09.2026 gefunden hat

Der Stand wurde gegen `docs/intent/nola-massstab.md` geprüft — von einem Prüfer mit
**kaltem Kontext**, der weder diese README noch die Entwicklungsgespräche kennen durfte.
Der Grund: Wer die Begründung des Autors liest, misst den Code an seiner eigenen
Beschreibung statt am Maßstab. 639 grüne Tests hatten keinen dieser Fehler gefunden — sie
prüften, dass der Code tut, was der Autor dachte, nicht was der Maßstab verlangt.

### Behoben

**Stichwörter trafen mitten in fremde Wörter.** `detect_nation_hint` verglich mit
`begriff in text`, ohne Wortgrenzen. `SMART DRAGON 3` — ein **chinesischer** Träger, der in
`traegersysteme_updated.csv` auch als solcher steht — wurde über `DRAGON` den USA
zugeordnet; `SHARJAH` ergab Indien, `CASCADE` China, `NASAL` die USA, `LAS VEGAS` den
Fremdbetreiber `VEGA`. Und dieser Treffer sticht die Drittstaaten-Regel, weil er vorher
ausgewertet wird. Jetzt setzt `_hint_pattern()` Wortgrenzen, mit Ausnahme von Präfixen wie
`CZ-`. Zusätzlich entfernt: `DRAGON` (mehrdeutig, `CREW DRAGON` bleibt) und `SHAR`
(`SDSC` und `SRIHARIKOTA` decken es ab).

**Daueranordnungen wurden zu Starts.** Ein japanisches NOTAM über Okinawa — *Abfangraketen
könnten gegen ein aus Nordkorea gestartetes Objekt eingesetzt werden*, gültig 91 Tage —
erreichte über das Wort `ROCKET` die Stufe `HIGH` und stand als nordkoreanischer Start im
Archiv. `STANDING_ORDER_HOURS = 720.0` deckelt die Stufe auf `LOW`, wenn eine Meldung
länger als 30 Tage **ohne** tägliches Fenster gilt. Die Grenze ist gemessen: längste
belegte Startmeldung ohne Tagesfenster 216 h (NAVAREA), längste überhaupt 403 h (mit
Fenster), Gegenfall 2192 h.

**Die Gruppierung wies ihre Unsicherheit als Gewissheit aus.** `azimuth_spread_deg` wurde
nur über Zonen innerhalb 8000 km gerechnet; lag höchstens eine dort, war das Ergebnis
definitionsgemäß `0.0` statt „unbekannt". Ein Starship-Wiedereintritt mit Azimuten von
87°, 331° und 180° meldete Streuung `0.0°`. Ausgewiesen wird jetzt die Streuung über alle
Zonen — dieselbe Zahl, mit der die Zuverlässigkeit ohnehin schon rechnete.

**Zwei Begründungen widersprachen sich selbst:** „all zones lie in the same direction
(spread 151.6°)" und „each active for only about 91 days. A closure that high for that
short a time…". Beide Texte sagen jetzt, was zutrifft.

**US-Bezirkszentralen waren unerreichbar.** `RE_ICAO` verlangt vier Buchstaben, die 21
ARTCC-Zeilen der FIR-Referenz (`ZLA`, `ZOA`, `ZAB` …) haben drei. Jedes US-Inlands-NOTAM
fiel still auf den Geometrie-Weg. `RE_ARTCC` (`Z` plus zwei Buchstaben) schließt die Lücke,
ohne jedes dreibuchstabige Freitextwort einzusammeln. Wirkung: der Geometrie-Weg schrumpfte
von 49 auf 6 Fälle.

**Eine Flugplatzkennung blockierte den Textbeleg.** Ein NOTAM mit Location `KVBG` und Text
*„SPACE LAUNCH FROM VANDENBERG. FALCON 9 STARLINK"* ging in den Review, weil `KVBG` keine
FIR der Referenz ist — der Textbeleg wurde gar nicht erst betrachtet. Er zählt jetzt, was
genau der Regel des Maßstabs entspricht.

**Eine geratene FIR galt als eigener Luftraum.** Ohne genannten ICAO-Code gewann die
nächstgelegene Referenzzeile bis 1500 km. Die Referenz kennt aber keine FIR-Grenzen, nur
den Sitz der Bezirkszentrale. Eine Sperrzone über **Nicaragua** landete so bei Miami und
wurde ein Start von Cape Canaveral. `FIR_OWN_AIRSPACE_KM = 800.0` trennt jetzt zwei Dinge:
Die FIR wird weiterhin gefunden und angezeigt, belegt aber jenseits von 800 km keine
Staatszugehörigkeit mehr. Auch diese Grenze ist gemessen — Hainan 213 km, US-Inlandsfälle
477–541 km, Nicaragua 1460 km.

### Nicht behoben, weil kein Codefehler

Der Prüfer meldete, der Bezugsfall *„Starship als indischer Start"* sei weiterhin
erreichbar, und zeigte eine Trümmerzone in **indischer** FIR ohne Betreibernennung. Das
echte `A0096/26` liegt jedoch in `FIMM` (Mauritius) und geht ohne Betreibernennung korrekt
in den Review — die Drittstaaten-Regel greift. Der konstruierte Fall liegt in Indiens
eigenem Luftraum, wo der Maßstab Geografie ausdrücklich zulässt, und ist von einem echten
GSLV-Start nicht unterscheidbar. Eingeordnet als **Vertrag missverstanden**: Wer das enger
will, muss den Maßstab präzisieren, nicht den Code.

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
