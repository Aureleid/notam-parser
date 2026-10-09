# Projektstand — NOLA

Stand: 09.10.2026 · `app.py` 8374 Zeilen · 1783 Tests in beiden Läufen (`test_app.py` 1493, `test_nola_db.py` 290), alle grün

## Starten

```bash
cd "/Users/marioantic/Documents/Claude Code/NOTAM Parser" && .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Tests: `.venv/bin/python test_nola_db.py` und `.venv/bin/python test_app.py` — laufen ohne
Streamlit-Server unter `NOLA_TEST=1` nur in Temp-Ordnern.

## Was fertig ist

| Bereich | Stand |
|---|---|
| Erkennung | 7 Koordinatenformate, Startsignatur (Q-Code + SFC-UNL + kurzes Fenster), D-Item-Tagesfenster, NAVAREA-Zeiträume, HTML-Entities, Kennungen mit/ohne Buchstabe |
| Eingabe | Datei-Import (CSV/XLS/XLSX mit Vorspann-Erkennung) und Freitext-Feld; beide identisch verarbeitet |
| Zuordnung | Drittstaaten-Regel über Spalte `Land`, Trägersystem → Startplatz, Startrichtungs-Prüfung (Sektor 225–325° ausgeschlossen), Fernzonen-Behandlung |
| Gruppierung | Mehrere Dropzonen eines Starts werden zusammengefasst, Anker-Regel gegen Selbstbestätigung, Ausreißer-Trennung |
| Nationen | China, Russland, Indien, Iran, Nordkorea, USA — 32 Startplätze, 130 FIRs, 65 Trägersysteme (13 am 06.10.2026 nach Freigabe ergänzt) |
| Bedienung | 6 Reiter, Klartext-Auswertung, manuelle Prüfung (Space Launch / Ausblenden), Optionsmenü zur Referenzpflege |
| Trägersystem | Dropdown unter NOTAM Data und Review, gestaffelt nach Nation; gilt für alle Zonen eines Starts; lesbare Spalte in der Launch Overview |
| Prüfung | Externe Prüfung gegen `docs/intent/nola-massstab.md` am 25.09.2026; sechs Befunde behoben, einer als Vertragsfrage eingeordnet |
| Seestarts | Startpunkt aus der Geometrie abgeleitet, wenn eine kleine Kreiszone die übrigen Sperrgebiete auf einer Bahn erklärt; eigenes Protokoll, seit dem 09.10.2026 als Tabelle `seestarts` in `nola.db` (die alte `seestarts_updated.csv` wird nur beim ersten Start einmal gelesen und vom Export geschrieben), das bewusst nicht in die Startplatz-Suche zurückfließt |
| Startplätze am selben Ort | Wenchang (`WSLC`) und der kommerzielle Platz Hainan (`HAIN`) liegen 1,92 km auseinander — 0,06–0,22° Azimutunterschied gegen eine Auswahlschwelle von 15°. Die Geometrie darf dort nie entscheiden; gewählt wird von Hand, Vorgabe „nicht bestimmt". Der Hinweis wird aus dem eigenen Archiv gerechnet statt als Tabelle verdrahtet. |
| Vorankündigungen | Mehrtägige Meldungen, die denselben Luftraum vor dem Starttag reservieren, werden über Geometrie und Zeit an ihren Start gehängt — sechs Bedingungen, alle sprachfrei; Eindeutigkeit ist Bedingung. Die Gruppe bleibt unberührt: dieselbe Fläche ist keine weitere Zone. |
| Bahnrechnung | Inklination mit Erdrotation (`orbital_azimuth_deg`); Orbitbänder auf die Streuung der Abschätzung geweitet (SSO 93–103°) |
| Vorfilterung | `LOW` + Ausschlussbegriff → direkt unter *Excluded*; auf der Echtdatei 148 von 275 Review-Fällen, ohne einen Start zu verlieren. Zurückholen gewinnt dauerhaft. |
| Payload | Freitextfeld unter NOTAM Data, gilt für alle Zonen eines Starts; Spalte in Launch Overview und Export |
| Startarchiv | Tabelle `startarchiv` in `nola.db` (seit 09.10.2026; die frühere `startarchiv_updated.csv` ist nur noch Quelle des Umzugs und Format des Exports), von der App geschrieben: eine Zeile je erkanntem Start, wird aktualisiert statt verdoppelt; eigener Reiter im Optionsmenü. Erkennungsmerkmal ist Startdatum + NOTAM-Kennungen — der Startplatz gehört seit dem 02.10.2026 nicht dazu, weil er sich mit besserer Erkennung ändert. Gelesen und geschrieben wird über `archiv_lesen` und `archiv_schreiben`: geschrieben wird in einer Transaktion und nur, solange das Archiv dem gelesenen Stand entspricht; bei einem Konflikt liest der Tageslauf neu und versucht es einmal wieder. Ist die Datenbank unlesbar, wird nichts geschrieben und eine Meldung erscheint. Starts ohne Startdatum, NOTAM oder Nation werden mit Hinweis übersprungen. Trägersystem und Payload bleiben beim Tageslauf stehen, wenn der neue Wert leer ist (`merge_archive`, seit 06.10.2026 auch das Trägersystem). Rückgängig im Startarchiv läuft als Transaktion mit Standvergleich in der Datenbank und wird nur ausgeführt, solange das Archiv seit der Änderung unverändert ist — sonst wird es mit Meldung verweigert, damit neuere Zeilen (Import, Tageslauf) nicht still verschwinden. |
| Archiv-Import | Reiter *Archive Import* im Optionsmenü, **nur lokal** sichtbar (nicht unter `/mount/src`, Host lokal, TCP-Gegenstelle Loopback). Gespeicherte NSF-Forenseiten (HTML/TXT) oder eingefügter Text werden stapelweise gelesen, Zitate und Skripte verworfen, NOTAMs im lokalen Korpus entdoppelt (Tabelle in `nola.db`; die alte `archiv_korpus.json` wird nur beim ersten Start einmal gelesen und vom Export geschrieben). Je Tag ein Bündel mit Nachlauf bis 06:00 UTC des Folgetags, ausgewertet mit derselben Erkennung wie im Tagesbetrieb (`MEDIUM`); US-Starts werden nach der Erkennung verworfen und gezählt. GCAT (J. McDowell) schlägt nur Rakete und Payload vor; der Abruf läuft nur auf Knopfdruck. Ins Archiv kommt nur Bestätigtes — einzeln oder als Sammelbestätigung eindeutiger Treffer, mit Prüfung nach dem Schreiben. Steht der Start schon aus dem Tagesbetrieb im Archiv, werden nur Trägersystem und Payload ergänzt; die vorherigen Werte bleiben im Importzustand (ebenfalls Tabelle in `nola.db`, alte `archiv_import.json` nur Einmal-Import bzw. Export). „Derselbe Start“ heißt überall: gemeinsame NOTAM-Kennung, Startdatum ±1 Tag und gleiche Nation (`_gleicher_start`) — Kennungen allein sind über Nationen und Monate nicht eindeutig. Ein aktualisierter Kandidat nennt vor dem Bestätigen jede Importzeile, die er ersetzt (löscht), und übernimmt deren Trägersystem und Payload; die ersetzte Entscheidung behält ihre Werte. Eine entfernte Waise wird wieder angeboten, sobald sie wieder erkannt wird. NOTAMs, die die Erkennung zur Prüfung stellt oder ohne Startplatz lässt, gehen in eine Prüfliste (Space Launch / Hide). Die Tageslage bleibt unberührt (Gegenprobe in `test_app.py`). Entscheidung: `docs/decisions/ADR-0001-archiv-import-nola-erkennt-gcat-schlaegt-vor.md`. Browser-Test 06.10.2026: 3 eingefügte NOTAMs ergaben 3 Tage und 2 Kandidaten; ein Forenkommentar „Starship“ blieb ohne Wirkung; der 20.09.2026 wurde eindeutig mit GCAT 2026-220 (Lijian-1, Payload Pengcheng) gepaart; die bestätigte Zeile trug NOLAs eigene Inklination. |
| Vergangene Starts | Ein Start verschwindet aus der Tageslage, wenn das späteste Ende aller seiner Meldungen (Zonen und Vorankündigungen) plus 24 h (`PAST_LAUNCH_GRACE`) vor jetzt (UTC) liegt **und** er im Startarchiv steht — nur Archiviertes wird ausgeblendet (`past_launch_rows`, `event_expired`). Ein aus dem Archiv entfernter Start bleibt sichtbar und trägt den Hinweis „removed from archive“. Review-Fälle und Gruppen ohne Startplatz bleiben sichtbar; abgelaufene Review-Fälle tragen die Marke „expired“ (Spalte „Expired“). Unlesbares Archiv → nichts wird ausgeblendet, Meldung in der Seitenleiste (`archiv_schluessel_oder_grund`). Schalter „Show past launches“ in der Seitenleiste (nicht gespeichert) holt sie zurück; Hinweis „N past launch(es) hidden – in the launch archive“. Gelöscht wird nichts; Archiv, Arbeitsstand und Seestart-Protokoll werden nicht geschrieben. Unter „Pasted entries“ stehen vergangene Einträge mit „(past)“ (`order_pasted_entries`, `_render_pasted_entries`). Eine Zone ohne Endzeit (z. B. PERM) gilt als endend zu ihrem Beginn (`valid_to`, sonst `valid_from`). Der Zähler im Hinweis zählt nur Starts, die sonst sichtbar wären (`count_hidden_past`); die Ersatzkarte ohne folium zeigt nur Zeilen der Maske (`fallback_points`); die Hinweise je Start kommen aus `archive_hints`. Die Spalte „Archiv“ im gruppierten CSV-Export trägt die Hinweise (auf dem Bildschirm „Archive“). Echtbestand: 8 Starts (16 Tabellenzeilen) bei spätem `now` vergangen, bei frühem keiner. |
| Persistenz | Seit 09.10.2026 alles Eingepflegte in einer lokalen SQLite-Datei `nola.db` (`nola_db.py`, `nola_umzug.py`): Referenzen, Startarchiv, Seestart-Protokoll, Arbeitsstand (manuelle NOTAMs mit fester `id`, Entscheidungen, Zuweisungen) und Archiv-Import-Zustand. Jeder Durchlauf liest neu (`_arbeitsstand_laden`, `referenz_lesen`), geschrieben werden nur Abweichungen (`_persist_workspace` → `schreibe_unterschiede`) bzw. ganze Tabellen mit Standprüfung (`ersetze_tabelle`); zwei Tabs oder DB Browser überschreiben einander nicht still — Konfliktmeldung „Changed by someone else meanwhile …“, Sperrmeldung nach 5 s bei Klick-Aktionen; das automatische Fortschreiben von Archiv und Seestart-Protokoll wartet nur 0,5 s (`WARTEZEIT_AUTOMATISCH`), meldet „database is busy - … tries again on the next run“ und schreibt im nächsten Durchlauf nach. Korpus und Importzustand des Archiv-Imports werden ebenfalls mit Standvergleich geschrieben (`lade_*_mit_stand`, `MitStand`, Import-Klick über `speichere_import`); Bestätigen und „Remove from archive“ im Import schreiben Startarchiv und Importzustand in einer Transaktion (`ersetze_archiv_und_importzustand`). Erster Start zieht die alten CSV/JSON-Dateien um (`umziehen`, Zählprüfung, alte Dateien bleiben liegen). Sicherung beim Start, täglich und vor Schema-Änderungen in den iCloud-Ordner `NOTAM Parser Backups` (`sichere`, geprüft, 30 behalten, Namen mit Sekunden `nola-JJJJ-MM-TT-HHMMSS.db`, alte Namen ohne Sekunden werden weiter erkannt); fehlt `nola.db`, wählt man eine Sicherung (`stelle_wieder_her`, überschreibt nie) oder den Neuaufbau; Export in die alten Formate nach `export/` (`exportieren`, alle Tabellen aus einer Lesetransaktion). Liegen neben einer fehlenden `nola.db` noch alte `-wal`/`-shm`, legen Umzug und Wiederherstellen keine neue Datei an (`alte_nebendateien`, Meldung „… Move them away …“, nichts wird verschoben). Die Meldung „Data moved to nola.db (…)“ erscheint nach jedem Umzug, auch nach Neuaufbau im Betrieb und „Rebuild from old files“. Konflikt-, Sperr- und Fehlermeldungen aus dem Optionsdialog erscheinen nur im Dialog selbst (`_melde_db_dialog`, `_zeige_dialog_meldungen`), alle DB-Meldungen entschärft (`_zeige_db_meldung`); X/Escape schließen den Dialog dauerhaft (`on_dismiss=_ref_dialog_geschlossen`). In der öffentlichen Fassung gilt der Arbeitsstand je Browser-Sitzung (`_cloud_arbeitsstand`). Gelingt das Schreiben, scheitert aber das Neuladen, setzt `_persist_workspace` die Momentaufnahme auf den geschriebenen Stand und nimmt die neuen NOTAMs ohne `id` aus der Sitzung – kein zweites Einfügen beim nächsten Klick. Öffentliche Fassung: `stelle_bereit(…, referenzen_aus_dateien=True)` vergleicht die SHA-256 der drei Referenz-CSVs mit `meta.referenz_quellen_sha` und ersetzt bei Abweichung nur die drei Referenztabellen in einer Transaktion (`_referenzen_auffrischen`, `ersetze_tabellen`). Unter `NOLA_TEST` sperren `umziehen` und `stelle_bereit` die echte `nola.db` vor jedem Lesen. Die alten Datei-Helfer sind entfernt; für Umzug/Export bleiben nur `read_archive_strict`, `persist_reference` und `ai.load_korpus`. Speicher-Aktionen nur lokal, Hinweis wenn nicht an `127.0.0.1` gebunden. Browser-Test 09.10.2026 auf einer Kopie: Umzug (32/130/65/3/16/15 …), externe Änderung sichtbar, Konflikt zweier Tabs, Sperre, Konsole fehlerfrei. Tempo je Durchlauf +2 ms gegenüber den ungecachten CSV-Lesern. Entscheidung: `docs/decisions/ADR-0002-sqlite-als-lokaler-speicher.md`. |
| Oberfläche | Zweizeilige Wortmarke nach festem Regelwerk, unbunte Bühne mit bunten Signalen, durchgehend deckende Flächen, durchgehend englische Fachsprache, geometrische Symbole statt Piktogramme, Farbschema aus einer Referenzoberfläche gemessen (`.streamlit/config.toml`) |
| Veröffentlichung | Repository `Aureleid/notam-parser`, Streamlit Community Cloud unter `notam-space-analyzer.streamlit.app` |

## Bekannte Grenzen

- Inklination ist eine Näherung (`cos i = cos φ · sin α`), Erdrotation nicht eingerechnet.
- Gruppierung stützt sich auf das Zeitfenster: mehr als 30 Minuten Abstand bei kurzen NOTAMs
  trennt, zwei gleichzeitige Starts vom selben Platz in ähnliche Richtung verschmelzen.
- Der Rückgängig-Stapel im Optionsmenü ist nach einem Neustart leer.
- `B4912/26` / `B4913/26` („CONDUCTED BY KOREA") bleiben bewusst im Review — der Text
  unterscheidet nicht zwischen Nord- und Südkorea.
- NSF-Forenseiten lassen sich nicht automatisch abrufen (Cloudflare). Für den Archiv-Import
  werden sie im Browser gespeichert oder als Text kopiert.
- Kopierter Forentext kann zitierte NOTAMs enthalten. Sie werden über Kennung und B-Zeit
  entdoppelt; als Zitat erkannt werden sie nur in gespeichertem HTML, nicht in kopiertem Text.

- Ein ersetztes NOTAM (NOTAMR), dessen alte Fassung im Arbeitsstand liegt, wird ausgeblendet, sobald deren altes Fenster plus 24 h vorbei ist — gewollt.

## Offene Punkte

- **Knopf „Discard pasted entries of past launches“**: Eingefügte Einträge vergangener Starts bleiben im Arbeitsstand, bis sie einzeln entfernt werden; nur markiert mit „(past)“, kein Sammelknopf.
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
- **Der Archivschlüssel hält eine wachsende Kennungsmenge nicht aus.** Wird die
  Gruppierung besser, kommen NOTAM-Kennungen hinzu und der Schlüssel ändert sich — es
  entsteht eine neue Zeile statt eines Updates. So sind die vier überholten Dubletten
  entstanden (`F0511/26` in drei Zeilen, `F0494/26` in drei). Der Startplatz ist seit dem
  02.10.2026 aus dem Schlüssel entfernt, was die Seestart- und die Pad-Verschiebung behebt;
  die Kennungsmenge bleibt offen. Lösung wäre eine Suche über Kennungs-Überschneidung —
  ändert die Semantik von `merge_archive` und braucht eine Entscheidung. Mit dem
  Archiv-Import (500–650 historische Starts) wiegt das deutlich schwerer als vorher.
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
- **Das Pad eines Wenchang-Starts** bleibt `nicht bestimmt`, bis es von Hand gesetzt wird.
  NOLA kann es nicht wissen: nicht aus der Geometrie (1,92 km), nicht aus dem NOTAM-Text
  (chinesische Startmeldungen nennen kein Pad), nicht aus dem Trägersystem (CZ-8 fliegt von
  beiden). Die Archivzählung neben der Auswahlliste braucht erst eigene Einträge, um etwas
  zu sagen.
- **Altes Archiv kennt die Unterscheidung nicht.** Die 16 bestehenden Zeilen mit `WSLC`
  heißen weiter „Wenchang, Pad nicht unterschieden" — rückwirkend lässt sich das nicht
  klären.
- **Zusatzfeld in der ersten Archivzeile** (Bead `nola-djk`): Hat die erste Datenzeile von
  `startarchiv_updated.csv` ein Feld mehr als die Kopfzeile, verschieben sich beim Einlesen
  alle Spalten. Bestand schon vor dem Archiv-Import; Risiko von Datenverlust.
- **Echte NSF-Seite als Testfixture**: Die HTML-Extraktion ist bisher nur gegen
  nachgebautes SMF-Markup getestet.
- **Archivspalte Quelle**: Woher eine Importzeile stammt, steht vorerst nur im Nebenbestand
  `archiv_import.json`, nicht im Archiv selbst — das würde den Spaltensatz ändern.
- **Referenzdialog nach X/Escape im Browser**: `on_dismiss` ist verdrahtet und getestet
  (`_ref_dialog_geschlossen`); der Nachweis im echten Browser steht noch aus.
- **Prüfsummen des Archiv-Imports**: Korpus- und Zustands-Prüfsumme (SHA-256 über alle Zeilen)
  werden bei jedem Laden und Speichern neu berechnet — bei einem stark wachsenden Korpus
  messen und ggf. eine Versionsnummer statt der Prüfsumme führen.
- **Importzustand ohne Stand**: Ein gewöhnliches `dict` (z. B. eine Kopie per `dict(zustand)`)
  verliert `nola_stand` und schreibt ohne Vergleich; im App-Pfad kommen Korpus und Zustand
  immer aus `korpus_laden`/`zustand_laden`.
- **Sicherungen derselben Sekunde** überschreiben sich weiterhin (`os.replace`) — praktisch
  kaum erreichbar.
- **Cloud: Arbeitsstand je Sitzung**: In der öffentlichen Fassung gilt der Arbeitsstand je
  Browser-Sitzung und ist flüchtig (`_cloud_arbeitsstand`); Referenzen, Archiv und Seestarts
  teilen sich alle Besucher in einer `nola.db`. Eine entfernte Archiv-/Seestartzeile kann in
  einer anderen Sitzung wiederkommen (Löschschlüssel nur in der entfernenden Sitzung).
- **Fehlender Sicherungsordner**: Fehlt der iCloud-Ordner, steht „Daily backup failed: Backup
  folder … is missing.“ bei jedem Durchlauf in der Seitenleiste (gewollt laut „keine stillen
  Fehler“, aber dauerhaft sichtbar).
- **Wiederherstellen-Auswahl**: Defekte oder ausgelagerte Sicherungen sind in der Liste
  wählbar, nur der Knopf ist dann gesperrt — Streamlit-Radio kennt keine einzeln gesperrten
  Optionen.
- **Maskierte Schrägstriche** in Rohmeldungen (`Z8002\/26`) sind nur in der Markdown-Anzeige
  unsichtbar.
- **Alte Dubletten**: Doppelte Zeilen, die vor dem Archiv-Import entstanden sind, werden nicht
  bereinigt.
- **Tagesbetrieb neben Importzeile**: Ist die NOTAM-Menge im Tagesbetrieb größer als beim
  Import, legt er neben der Importzeile eine zweite an — Teil des offenen Punkts zum
  Archivschlüssel (`archive_key`).
- **Kein Rückgängig für ergänzte Zeilen**: Beim Ergänzen einer Tagesbetriebs-Zeile werden die
  vorherigen Werte von Trägersystem und Payload unter `vorher` gespeichert, eine Aktion zum
  Zurücknehmen gibt es noch nicht.
- Lokale Änderungen erreichen die veröffentlichte App erst nach `git push`.
