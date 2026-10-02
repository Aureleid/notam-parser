# Archiv-Import historischer NOTAMs (2020–2026) — Design

Stand: 02.10.2026 · im Brainstorming mit Mario Antic abgestimmt

## Ziel

Das Startarchiv (`startarchiv_updated.csv`) soll mit den Starts von China, Russland, Indien, Iran und Nordkorea aus den
Jahren 2020–2026 gefüllt werden, als Grundlage für den späteren Ähnlichkeitsvergleich
(`docs/intent/nola-massstab.md`, „Langfristiges Ziel"). Bisher dauert das zu lange. Drei
Engpässe bremsen:

1. NOTAMs im NSF-Forum zusammensuchen und Beitrag für Beitrag herauskopieren.
2. Einzeln über das Freitextfeld einfügen. Die Einträge landen dabei im Arbeitsstand der
   Tageslage.
3. Trägersystem und Payload je Start von Hand nachtragen.

**Umfang: nur China, Russland, Indien, Iran und Nordkorea.** Die USA sind ausgenommen. Wegen
Starlink wären es zu viele Starts, und sie interessieren für den Archiv-Aufbau derzeit nicht.
Größenordnung damit: rund 500–650 Starts. Der Tagesbetrieb bleibt davon unberührt; dort
werden die USA weiter erkannt.

## Rahmenbedingungen

- **Quelle der NOTAMs:** NASASpaceflight-Forum, öffentlich lesbar. Das Forum steht hinter einer
  Cloudflare-Bot-Abwehr; ein automatischer Abruf ist ausgeschlossen. Die Seiten werden im
  Browser gespeichert oder seitenweise kopiert.
- **Quelle für Trägersystem und Payload:** GCAT von Jonathan McDowell
  (`https://planet4589.org/space/gcat/tsv/launch/launch.tsv`, CC-BY). Die Liste enthält
  Startzeit (UTC), Rakete, Mission, Startplatz, Inklination und Azimut.
- **Maßstab bleibt:** Eine falsche Zuordnung ist schlimmer als ein Fall im Review. Für den
  Import gibt es keine eigenen Erkennungsregeln.
- **Trägersystem wird nicht erraten.** Ein Vorschlag aus einem dokumentierten Flug ist
  zulässig, ins Archiv geht er aber erst nach Bestätigung durch den Benutzer.
- `analyze_notams` hängt nicht vom heutigen Datum ab; alte NOTAMs laufen unverändert durch.

## Datenfluss

```
NSF-Seiten (.html/.htm/.txt) oder eingefügter Langtext
  → 1. Extraktion            → Rohkorpus (NOTAM-Text + Quelle)
  → 2. Entdoppeln            (Kennung + B-Zeit)
  → 3. Tagesweise Analyse    (analyze_notams / group_launches, Bündel je Aktivierungstag)
       ├─ sichere Starts (Status OK, Startplatz vorhanden) → 4. GCAT-Abgleich → Kandidat
       ├─ unsichere Fälle                                  → Import-Prüfliste
       └─ nichts erkannt                                   → nur im Bericht gezählt
  → 5. Bestätigung durch den Benutzer → merge_archive → startarchiv_updated.csv
```

Festlegungen:

- **Getrennt von der Tageslage.** Der Import nutzt weder `manual_notams` noch den
  Arbeitsstand in `notam_workspace.json`. Die Tageslage bleibt unverändert.
- **Dieselbe Erkennung wie im Tagesbetrieb**, kein Sonderweg.
- **Tagesbündel:** NOTAMs werden nach dem Datum aus `B)` gebündelt und je Tag analysiert.
  Mehrtägige Meldungen (Vorankündigungen) kommen in jedes Bündel eines Tages innerhalb ihres
  `B)`–`C)`-Fensters, höchstens in die ersten 14 Tage. Länger gültige Meldungen (Dauer-
  Sperrgebiete) würden sonst hunderte Bündel füllen. So greift die bestehende Vorankündigungs-Paarung am Starttag. Erzeugt
  eine solche Meldung allein, ohne Starttag-NOTAMs, einen Start, verhält sie sich wie im
  Tagesbetrieb.
- **USA-Filter nach der Erkennung:** Die Analyse läuft unverändert mit allen sechs Nationen.
  Würde sie die USA nicht kennen, könnte ein US-Start falsch einer anderen Nation zugeschlagen
  werden. Erst danach werden Gruppen mit der Nation USA verworfen und im Bericht als
  „USA, ausgenommen: N" gezählt. Sie werden weder Kandidat noch Prüflistenfall. Unsichere
  Fälle ohne Nation kommen auf die Prüfliste, außer jeder ihrer NOTAMs liegt in einer FIR mit
  `Land` = USA. Solche Fälle werden ebenfalls als ausgenommen gezählt. Auch der GCAT-Abgleich
  lädt nur Einträge der fünf Nationen.
- **Kandidaten statt Direktschreiben:** Ein historischer Start kommt erst nach Bestätigung ins
  Archiv.
- **Quelle wird mitgeführt:** Jeder Kandidat behält Datei bzw. URL seiner NOTAMs.

## 1. Extraktion

- Gespeichertes HTML wird mit dem Standardparser (`html.parser`) beitragsweise ausgelesen.
  Zitatblöcke werden verworfen, sonst würde jedes zitierte NOTAM doppelt gezählt.
- `.txt` und eingefügter Text werden wie ein einziger Beitrag behandelt.
- Ein NOTAM-Block beginnt an einer Kennung (`RE_PASTE_BOUNDARY`). Er endet am Zeilenende
  des Items `G)` bzw., wenn es fehlt, `F)`. Diese Items sind einzeilig. Hat der Block nur
  `E)`, endet er an der ersten Leerzeile danach. Spätestens endet er an der nächsten
  Kennung. **Freitext nach dem Block gehört nicht zum
  NOTAM.** Grund: Forenkommentare wie „probably Starship" dürfen Nation oder Startplatz nicht
  beeinflussen.
- Übernommen wird nur ein Block mit Kennung und mindestens `E)` oder `Q)`. Alle anderen
  Blöcke zählt der Importbericht als „nicht verwertbar". Sie werden gezählt, nicht still
  verworfen.
- Die Texte durchlaufen `normalize_pasted_text`.
- **Dubletten:** Gleiche Kennung und gleiche `B)`-Zeit gelten als dasselbe NOTAM. Es bleibt
  ein Eintrag mit allen Quellen.
- **NOTAMR/NOTAMC** werden behandelt wie im Tagesbetrieb.
- **Datierung:** maßgeblich ist `B)`. Das Datum des Forenbeitrags wird nicht verwendet.
  Blöcke ohne lesbares `B)` gelten als nicht verwertbar.

## 2. GCAT-Abgleich

- **Lokale Cache-Kopie** der Startliste mit dem Knopf „Startliste aktualisieren". Die Datei ist
  per `.gitignore` aus dem Repository ausgeschlossen. Quellenvermerk in der Oberfläche:
  „GCAT, J. McDowell, CC-BY".
- **Neue Referenzdatei `gcat_startplaetze.csv`** mit den Spalten `GCAT`, `Kurzel`. Sie ordnet
  GCAT-Startplatzcodes (z. B. `JQ`) den NOLA-Kürzeln (`JSLC`) zu und wird wie die übrigen
  Referenzen gepflegt. Ein unbekannter GCAT-Code ergibt keinen Treffer, und der Bericht nennt
  die fehlende Zeile.
- **Paarungsregel:** Die GCAT-Startzeit liegt im Aktivierungsfenster der Gruppe
  (`window_from`–`window_to`) ± 30 min, und der GCAT-Startplatz entspricht nach Zuordnung dem
  NOLA-Startplatz. Hat ein GCAT-Eintrag nur ein Tagesdatum, gilt der ganze Tag als Fenster;
  ein solcher Treffer ist nie eindeutig.
- **Ergebnis je Kandidat:**
  - *eindeutig:* genau ein Treffer → Rakete (`LV_Type`) und Payload (`Mission`, ersatzweise
    `Flight`) werden vorgeschlagen.
  - *mehrdeutig:* mehrere Treffer → der Benutzer wählt.
  - *kein Flug:* kein Treffer. Hinweis „kein Flug in GCAT", etwa ein verschobener Startversuch.
  - *Seestart* (`site_from_geometry`): Paarung nur über Nation und Zeitfenster, nie eindeutig.
  - *kein Abgleich:* GCAT nicht verfügbar.
- **Plausibilitätsprüfung (nur Warnung):** Weicht NOLAs Inklination oder Azimut um mehr als
  10° von GCAT ab, wird der Kandidat als *Abweichung* markiert. Der Vergleich findet nur
  statt, wenn beide Seiten einen Wert haben. NOLAs eigene Werte werden **nie** überschrieben;
  aus GCAT stammen ausschließlich Rakete und Payload.
- **Nation:** GCAT wird nicht zur Nationsbestimmung herangezogen. Passt die Nation des
  Treffers nicht zum NOLA-Kandidaten (über die Startplatz-Referenz), gilt das als *Abweichung*.

## 3. Bedienung — neuer Reiter „Archive Import" im Optionsmenü

1. **Einspielen:** mehrere Dateien gleichzeitig hochladen (`.html`, `.htm`, `.txt`) oder Text
   einfügen. Danach erscheint ein Importbericht: X NOTAMs gefunden, Y Dubletten, Z nicht
   verwertbar, N Starttage, Fehler je Datei.
2. **Kandidaten:** eine Tabelle je Jahr mit Datum, Nation, Startplatz, Orbit, Inklination,
   GCAT-Vorschlag (Rakete und Payload), Status und Quelle.
   - „Alle eindeutigen bestätigen" erfasst nur Kandidaten mit dem Status *eindeutig* ohne
     Warnung.
   - Alle übrigen Kandidaten werden einzeln bestätigt (bei *mehrdeutig* mit Auswahl des
     Treffers), ohne Vorschlag bestätigt oder verworfen.
   - Bei der Bestätigung kann der Benutzer Rakete und Payload ändern. Die Rakete wird gegen
     `traegersysteme_updated.csv` geführt wie das Dropdown im Tagesbetrieb. Ein GCAT-Name ohne
     Entsprechung bleibt leer, mit Hinweis, statt einen unbekannten Wert zu schreiben.
3. **Prüfliste:** unsichere Fälle mit der Begründung aus der Erkennung und denselben
   Entscheidungen wie im Review (Space Launch / Ausblenden). Nach „Space Launch" wird der Fall
   zum Kandidaten.

**Bestätigen wirkt ausdrücklich:** Ein bestätigter Kandidat wird auch dann ins Archiv
geschrieben, wenn sein Schlüssel früher im Optionsmenü entfernt wurde (`archiv_removed`).

**Wiederaufnahme:** Der Rohkorpus bleibt gespeichert. Ein weiterer Import ergänzt ihn, danach
werden nur die Tage neu ausgewertet, deren NOTAM-Bestand sich geändert hat. Bestätigte und
verworfene Kandidaten bleiben unberührt; Schlüssel ist `archive_key`. Der zweite Import
derselben Seite ändert nichts. Kommt durch neue NOTAMs eine Zone zu einem schon bestätigten
Start hinzu, ändert sich dessen `archive_key`. Der neue Kandidat erhält dann den Status
*aktualisiert*. Bestätigst du ihn, ersetzt er die alte Archivzeile, statt eine zweite
anzulegen. Erkannt wird das an einer gemeinsamen NOTAM-Kennung.

**Öffentliche Fassung:** Der Reiter wird auf Streamlit Cloud ausgeblendet, solange der
Demo-Modus fehlt. Erkannt wird das über die Umgebung, wie beim Demo-Modus vorgesehen.

## 4. Speicherung

| Datei | Inhalt | Im Repository |
|---|---|---|
| `archiv_korpus.json` | Rohtexte der NOTAMs mit Quellen; Grundlage für Neuauswertungen | nein (`.gitignore`, wie das Archiv) |
| `archiv_import.json` | Kandidaten, Entscheidungen, Prüfliste, Quelle je `archive_key` | nein (`.gitignore`) |
| `gcat_startplaetze.csv` | Zuordnung GCAT-Startplatz → NOLA-Kürzel | ja |
| GCAT-Cache | Kopie von `launch.tsv` | nein (`.gitignore`) |
| `startarchiv_updated.csv` | **Spaltensatz unverändert**; bestätigte Starts über `merge_archive` | nein (schon heute in `.gitignore`) |

Eine Spalte „Quelle" im Archiv würde den abgestimmten Spaltensatz ändern und fällt unter den
offenen Punkt „Archivspalten". Deshalb steht die Quelle im Nebenbestand.

## 5. Code-Aufbau

- Neues Modul **`archiv_import.py`** ohne Streamlit. Es enthält Extraktion, Entdoppeln,
  Tagesbündel, GCAT-Laden, GCAT-Paarung, Kandidaten- und Prüflistenverwaltung sowie
  Laden/Speichern der beiden JSON-Dateien. Es ruft `analyze_notams`, `group_launches`,
  `archive_row` und `merge_archive` aus `app.py` auf und baut nichts davon nach.
- `app.py` bekommt nur den Reiter `_archive_import_tab` im Optionsmenü.
- Kein Zirkelimport: `archiv_import.py` importiert `app` (import-sicher dank
  `if __name__ == "__main__"`, wie in `test_app.py`), und `app.py` importiert das Modul erst
  innerhalb des Reiters. Unter Streamlit läuft `app.py` als `__main__`; `import app` lädt
  dann eine zweite Modulkopie. Das ist unschädlich, solange `archiv_import.py` nur reine
  Funktionen und Konstanten daraus nutzt, nie `st.session_state`. Den Zustand übergibt der
  Reiter als Argument.

## 6. Fehlerbehandlung

- Eine unlesbare oder fremde Datei wird im Bericht genannt; der übrige Stapel läuft weiter.
- Ist GCAT nicht erreichbar, geht es mit vorhandenem Cache weiter. Ohne Cache stehen alle
  Kandidaten auf *kein Abgleich*: einzeln bestätigbar, ohne Sammelbestätigung.
- Eine unvollständige JSON-Datei wird nicht überschrieben. Der Import bricht dann mit einer
  Meldung ab; geschrieben wird atomar (temporäre Datei + Umbenennen).

## 7. Sicherheit

- HTML wird nur gelesen, nie ausgeführt oder gerendert. Forentext erscheint ausschließlich
  als reiner Text, nie über `unsafe_allow_html`.
- Größengrenzen: 5 MB je Datei und 200 MB je Stapel.
- Netzzugriff nur auf die feste GCAT-Adresse. Adressen aus dem Forentext werden nie
  aufgerufen.
- Auf Streamlit Cloud ist der Reiter ausgeblendet (siehe oben).

## 8. Tests (`test_app.py`)

- Extraktion aus einem gekürzten echten NSF-Seitenausschnitt (Fixture).
- **Pflichtfall:** Ein Kommentar mit „Starship" unter einem chinesischen NOTAM ändert weder
  Nation noch Startplatz.
- Ein zitiertes NOTAM wird nicht doppelt gezählt.
- Ein Block ohne `E)`/`Q)` oder ohne lesbares `B)` erscheint im Bericht als „nicht verwertbar".
- Tagesbündel über einen Monats- und einen Jahreswechsel; eine Vorankündigung wird am Starttag
  gepaart.
- GCAT-Paarung: eindeutig, mehrdeutig, kein Flug, nur Tagesdatum, Seestart, Abweichung über
  10°, unbekannter GCAT-Startplatz.
- Sammelbestätigung erfasst nur *eindeutig* ohne Warnung.
- USA-Ausnahme: Ein Falcon-9-NOTAM wird gezählt, aber weder Kandidat noch Prüflistenfall. Ein
  chinesischer Start am selben Tag bleibt unberührt.
- Wiederaufnahme: Ein zweiter Import derselben Seite ändert keine Datei.
- Gegenprobe mit der echten FNS-Datei: Die Tageslage ist vor und nach einem Archiv-Import
  identisch.

## Nicht Teil dieses Vorhabens

- Automatischer Abruf aus dem NSF-Forum (Cloudflare-Bot-Abwehr).
- Übernahme von Inklination, Azimut oder Nation aus GCAT.
- Neue Archivspalten (offener Punkt „Archivspalten").
- Historische US-Starts.
- Der Ähnlichkeitsvergleich selbst. Er ist das nächste Teilprojekt.

## Nach der Umsetzung

Laut `CLAUDE.md`: Projektplan `docs/projektplan.html` (neuer Schritt, Ast unter „Referenzdaten
und Archiv", Funktionsnamen aus `archiv_import.py`/`app.py`), `STATUS.md` und das Artifact
nachziehen.
