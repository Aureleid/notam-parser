# Startarchiv von Hand bearbeiten — Design

Stand: 09.10.2026 · im Brainstorming mit Mario Antic abgestimmt · Bead `nola-8lv`

## Ausgangslage

- Der Reiter *Launch Archive* im Optionsmenü (`_archive_editor`) kann Zeilen nur anzeigen und
  entfernen.
- `merge_archive` (Tagesbetrieb, `_update_archive`) überschreibt eine bekannte Zeile (gleicher
  `archive_key` = Startdatum + NOTAM-Kennungen) bei jedem Lauf vollständig — nur `Trägersystem` und
  `Payload` bleiben, wenn der neue Lauf sie leer liefert.
- Der Archiv-Import (`confirm_many`) ergänzt bei vorhandener Zeile Trägersystem und Payload.
- Seit dem Import 2026 stehen Zeilen im Archiv, deren Nation, Platz, Orbit usw. der Benutzer
  korrigieren können muss (siehe `nola-3zh`, `nola-9hg`).

## Ziel

Nation, Platz (Weltraumbahnhof), Vehicle (Trägersystem), Payload und Orbit einer Archivzeile lassen
sich von Hand ändern. Eine Handänderung überlebt jeden späteren Lauf, ist sichtbar, rücknehmbar und
gegen gleichzeitige Änderungen geschützt.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Vorrang | **Hand gewinnt je Feld.** Genau die von Hand geänderten Felder überschreibt kein späterer Lauf; alle anderen aktualisiert NOLA weiter. |
| Platzwechsel | Azimut, Inklination und Orbitklasse werden aus dem neuen Platz und den gespeicherten Dropzones **neu berechnet**; ein im selben Formular von Hand gesetzter Orbit bleibt. |
| Bedienung | **Formular je Zeile** (Knopf „Edit“) im Reiter Launch Archive. |

## Speicherung

- Der gültige Wert steht **in `startarchiv`** (Export, DB Browser, Vergleich sehen immer den gültigen
  Wert).
- Neue Tabelle **`archiv_handwerte`**:

  | Spalte | Bedeutung |
  |---|---|
  | `schluessel` | `archive_key` der Zeile |
  | `spalte` | ∈ {`Nation`, `Weltraumbahnhof`, `Trägersystem`, `Payload`, `Orbit`, `Inklination`, `Azimuth`} (CHECK) |
  | `nola_wert` | Wert, den NOLA vor der ersten Handänderung dort hatte (für „Reset“; NULL = leer) |
  | `herkunft` | `hand` (von Hand gesetzt) oder `berechnet` (nach Platzwechsel neu berechnet) (CHECK) |
  | `geaendert_utc` | Zeitpunkt der letzten Handänderung |

  PRIMARY KEY (`schluessel`, `spalte`). `Inklination`/`Azimuth` werden nur markiert, wenn sie durch
  einen Platzwechsel neu berechnet wurden (`berechnet`); ebenso ein neu berechneter `Orbit`. Sonst
  überschriebe der Tageslauf sie mit den Werten des alten Platzes.
- **Schema-Version 2**: `nola_db.SCHRITTE[1]` legt die Tabelle an (`CREATE TABLE … IF NOT EXISTS`).
  Der vorhandene Mechanismus sichert vorher (`nola-…-vor-schema-2.db`); scheitert die Sicherung, wird
  nicht umgebaut. `lege_schema_an` legt die Tabelle für neue Datenbanken direkt an und setzt Version 2.
  Die Tabelle steht in **`FACHTABELLEN`** (neben `startarchiv`), damit `lese_tabelle`/`ersetze_tabelle`
  (Stand, Standvergleich), Undo, Export, `zaehle` und `pruefe_sicherung` sie über die vorhandenen Wege
  kennen. **Nicht** in `ARBEITSTABELLEN`: das ist der Arbeitsstand (Differenz-Speicherung, in der Cloud
  je Sitzung), die Handwerte gehören aber zum gemeinsamen Archiv. Fehlt `archiv_handwerte.csv` beim
  Umzug (alte Exporte), gilt die Tabelle als leer.
- Ältere NOLA-Fassungen verweigern eine Datei mit Version 2 („schema too new“) - gewollt. Zurück zu
  einer älteren Fassung nur über die Sicherung `…-vor-schema-2.db` (Satz im README). Die Cloud baut
  ihre Datenbank aus den Repo-CSVs und ist nicht betroffen. Tests nur an Kopien, auch „ältere
  Fassung verweigert Version 2“.

## Vorrang beim Schreiben

- `merge_archive(bestand, neue, entfernt, handwerte)` bekommt die Menge
  `{schluessel: {spalte, …}}`: Für eine bekannte Zeile übernimmt ein Lauf die markierten Spalten aus
  dem Bestand statt aus dem neuen Lauf. Unmarkierte Spalten verhalten sich wie heute.
- `_update_archive` liest die Markierungen in derselben Lesetransaktion wie das Archiv und schreibt
  das Archiv mit Standvergleich **beider** Tabellen (eine zwischenzeitlich gesetzte oder entfernte
  Markierung gilt als Konflikt → neu lesen wie heute).
- **Gemeinsames Schreiben:** neue Funktion `nola_db.ersetze_tabellen_geprueft(conn, {tabelle: (df,
  erwartet)})` prüft alle Stände unter einem `BEGIN IMMEDIATE` und schreibt alle oder keine
  (`Konflikt`). Speichern, Reset, Entfernen und Undo nutzen sie. `ersetze_archiv_und_importzustand`
  prüft zusätzlich den Stand der Markierungen.
- Archiv-Import `confirm_many`: Beim Ergänzen einer vorhandenen Zeile werden markierte Felder nicht
  überschrieben; beim Anlegen einer Zeile, deren Schlüssel schon Markierungen hat, gilt dasselbe.
- Entfernen einer Zeile (`_remove_archive_row`, `remove_orphan`) löscht ihre Markierungen in derselben
  Transaktion.
- Bekannte Grenze: Wächst die Kennungsliste eines Starts (bessere Gruppierung), ändert sich der
  Schlüssel; dann entsteht wie heute eine zweite Zeile und die Markierungen bleiben an der alten.
  Nicht Teil dieses Vorhabens (offene Entscheidung im Docstring von `archive_key`, eigener Bead).
  Mit Handwerten wiegt das schwerer (Korrektur an einem bevorstehenden Start, am Folgetag neue
  Zeile mit dem alten Wert). **Sicherung:** Der Reiter zeigt ⚠ an Zeilen, die mit einer anderen Zeile
  desselben Startdatums mindestens eine NOTAM-Kennung teilen („shares NOTAM ids with another row –
  possible duplicate“). Nur Anzeige, keine Änderung der Zusammenführung.

## Formular

Im Reiter *Launch Archive*: je Zeile ein Knopf **„Edit“** neben „Remove“; Felder mit Handwert tragen
in der Tabelle ein ✎ (`hand`) bzw. ↻ (`berechnet`, „recomputed from site“) – umgesetzt als Material-Icons (`:material/edit:`, `:material/autorenew:`, `:material/warning:`), weil das Projekt keine Piktogramm-Zeichen im Code zulässt (Tests). Das Formular erscheint unter der Zeile, höchstens eines gleichzeitig offen.
**Kein `st.form`**: normale Widgets mit eigenen Schlüsseln plus Knöpfe „Save“ und „Cancel“, damit
Platz- und Vehicle-Liste der gewählten Nation sofort folgen; geschrieben wird erst bei „Save“.

| Feld | Eingabe | Erlaubte Werte |
|---|---|---|
| Nation | Auswahl | `TARGET_NATIONS`, angezeigt über `NATION_LABELS`, gespeichert deutsch wie im Archiv |
| Platz | Auswahl | alle `Kurzel` der Startplatz-Referenz, Plätze der gewählten Nation zuerst |
| Vehicle | Auswahl | Trägersysteme der gewählten Nation zuerst, darunter die übrigen (wie `vehicle_options`), dazu „none“ (= leer); die Trennzeile ist nicht speicherbar |
| Payload | Text | höchstens 200 Zeichen, Zeilenumbrüche werden zu Leerzeichen; beginnt der Wert mit `=`, `+`, `@`, Tab oder CR, wird er abgelehnt (Formel-Einschleusung beim Öffnen des Exports in Excel); `-` bleibt erlaubt |
| Orbit | Auswahl | `SSO`, `HIGH-INC`, `LEO/MEO`, `GTO`, `RETRO`, `-` |

**Speichern:**
- Nur geänderte Felder werden geschrieben und markiert. Beim ersten Markieren eines Feldes wird der
  bisherige Wert als `nola_wert` gemerkt; ist das Feld schon markiert, bleibt der gemerkte NOLA-Wert.
- Bekannte Grenze: Wählt der Benutzer nach einem Platzwechsel bewusst den ursprünglichen Orbit, entfällt dessen
  Markierung (Regel unten); ein späterer Platzwechsel berechnet den Orbit dann neu.
- Wird ein Feld genau auf seinen gemerkten `nola_wert` zurückgesetzt, **entfällt die Markierung**
  (ebenso Inklination/Azimuth, wenn der Platz auf den ursprünglichen zurückkehrt).
- Eine Transaktion (`BEGIN IMMEDIATE`) für Archivzeile und Markierungen mit Standvergleich beider
  Tabellen; Abweichung → Konfliktmeldung im Dialog, nichts geschrieben.
- Ein Undo-Eintrag (bestehender Stapel), der Zeile **und** Markierungen zurücknimmt.
- Der **aktuelle Wert** jedes Feldes bleibt immer wählbar, auch außerhalb der Liste (z. B.
  `SEA-21N112E`, ein Vehicle, das nicht mehr in der Referenz steht). Erlaubt ist also „Liste ∪
  aktueller Wert der Zeile“; alles andere wird vor dem Schreiben abgelehnt (Meldung im Dialog).
- Passt der Platz nicht zur Nation (Land des Platzes ≠ Nation), erscheint nur ein **Hinweis**, keine
  Sperre.

**Platzwechsel:**
- Neuer Azimut = Kreismittelwert (`_circular_mean`) der Richtungen (`initial_bearing_deg`) vom neuen
  Platz zu jeder Dropzone der Zeile (`Dropzones` = „lat lon; lat lon …“); Inklination =
  `estimate_inclination_deg(platz_lat, azimut)`; Orbit = `orbit_short(classify_orbit(inklination))`.
- Inklination, Azimuth und Orbit werden als `berechnet` markiert, der Platz als `hand`.
- Ein im selben Formular von Hand gewählter Orbit hat Vorrang vor dem berechneten und wird `hand`.
- Keine Dropzones, keine gültigen Koordinaten oder eine Zone < 1 km vom Platz → Inklination/Azimuth
  leer, Hinweis im Dialog („no drop zones to compute the orbit from“ bzw. „zone on the launch site“).
- Der Platz muss Koordinaten in der Referenz haben, sonst keine Neuberechnung (Hinweis).
- Format wie im Archiv: eine Nachkommastelle (`"96.8"`).
- Dasselbe Verfahren wie die Pipeline (`app.py`, Gruppen-Azimut = Kreismittel aller Zonen-Azimute).
- Bekannte Näherung: Die Pipeline rechnet über Zonen-Mittelpunkte je NOTAM, das Archiv speichert
  Cluster-Punkte; der neu berechnete Wert kann um wenige Grad vom Pipeline-Wert abweichen (Test mit
  Toleranz).

**Reset:** Je markiertem Feld ein Knopf „Reset to NOLA value“ (kein Reset der ganzen Zeile; den
letzten Schritt nimmt Undo zurück). Das ✎ zeigt als Tooltip den gemerkten Wert („NOLA: WSLC“). Der
Knopf schreibt `nola_wert` zurück und entfernt die
Markierung (gleiche Transaktion, Standvergleich, Undo). „Reset“ beim Platz setzt auch alle
`berechnet`-Markierungen der Zeile auf ihre gemerkten NOLA-Werte zurück; `hand`-Markierungen bleiben.

**Anzeige:** Alle angezeigten Werte durch `_md_plain`; Meldungen über `_melde_db_dialog`.

**Seiten:** Statt der harten Grenze `head(60)` (heute schon 61 Zeilen) blättert der Reiter: 50 Zeilen je
Seite, neuestes Startdatum zuerst (Datum geparst, nicht als Text sortiert), „◀ Prev / Page n of m /
Next ▶“; die Suche filtert vor dem Blättern, die Seite steht in `session_state`. Nur der Archiv-Reiter.

## Weitere Wirkungen

- **Undo**: Ein Eintrag von `_push_undo` enthält künftig eine **Liste** von Tabellen (Inhalt vorher,
  Stand nachher); `_undo_reference` stellt alle über `ersetze_tabellen_geprueft` zurück. Einträge mit
  einer Tabelle funktionieren unverändert.
- **Export** (`exportieren`): zusätzlich `archiv_handwerte.csv` (alle Spalten der neuen Tabelle).
  Der Umzug liest diese Datei, wenn vorhanden (Rückweg vollständig).
- **Cloud**: „Edit“ und „Reset“ nur, wenn `local_admin_allowed()` (fail-closed wie Import und Export).
  In der öffentlichen Fassung zeigt der Reiter das Archiv ohne Bearbeiten-Knöpfe (✎ und ⚠ bleiben
  sichtbar). Begründung: dort teilen sich alle Besucher das Archiv; Freitext von Fremden wäre für alle
  sichtbar. „Remove“ und die Referenz-Editoren bleiben dort wie heute (eigener Bead).
- **Kein Einfluss** auf Tageslage, Erkennung und Arbeitsstand.

## Tests (TDD, `check()`-Stil)

- `merge_archive` mit Markierungen: markierte Spalte bleibt, unmarkierte wird aktualisiert;
  Trägersystem/Payload-Sonderregel unverändert.
- `_update_archive` über die DB: Handwert überlebt einen Lauf.
- `confirm_many`: ergänzt keine markierten Felder.
- Speichern: nur geänderte Felder markiert, `nola_wert` = alter Wert, zweite Änderung behält den
  ersten `nola_wert`.
- Selbstprobe: jede Archivzeile am **eigenen** Platz neu berechnet ergibt die gespeicherte
  Inklination/Azimuth (±1°).
- Zurück auf den NOLA-Wert entfernt die Markierung.
- Platzwechsel: bekannter Start (z. B. Hainan → HAIN statt WSLC; Yaogan-50 auf TSLC) ergibt eine
  plausible Inklination (Toleranz ±3° zum Pipeline-Wert am gleichen Platz); ohne Dropzones leer;
  von Hand gesetzter Orbit bleibt.
- Reset stellt Wert(e) und Markierung zurück, auch die Bahnwerte nach Platzwechsel; ein von Hand
  gesetzter Orbit bleibt beim Reset des Platzes.
- Nach Platzwechsel überlebt der neu berechnete Orbit einen Tageslauf.
- Konflikt (fremde Änderung an Archiv oder Markierungen) → nichts geschrieben, Meldung im Dialog.
- Undo nimmt Wert und Markierung zurück.
- Entfernen löscht Markierungen mit.
- Blättern: alle Zeilen erreichbar, Suche filtert vor dem Blättern, Sortierung nach Datum.
- ⚠ erscheint genau an Zeilen mit gemeinsamer NOTAM-Kennung am selben Startdatum.
- Ungültige Werte (Nation/Platz/Vehicle/Orbit außerhalb von Liste ∪ aktuellem Wert, Payload > 200,
  Payload mit `=`/`+`/`@`/Tab/CR am Anfang) → abgelehnt; die Prüfung liegt in der Schreibfunktion,
  nicht nur im Widget.
- Ohne `local_admin_allowed()` keine Edit-/Reset-Knöpfe, und die Schreibfunktion verweigert.
- Schema 1 → 2: Sicherung vorher, Tabelle angelegt, vorhandene Daten unverändert, Version 2.
- Export enthält `archiv_handwerte.csv`; Umzug liest sie zurück.
- Browser-Test an einer Kopie: Edit öffnen, Platz ändern, Inklination neu, ✎ sichtbar, Reset, Undo.

## Abschluss

README (Archiv bearbeiten), STATUS, `docs/projektplan.html` (neuer Schritt, TREE mit den neuen
Funktionen, Kopfzahlen) und Artifact aktualisieren. Commit nur auf Wort des Benutzers; Arbeit auf
eigenem Zweig.

## Nicht Teil

Startdatum, Startzeit, NOTAM-Kennungen oder Dropzones bearbeiten; neue Zeilen von Hand anlegen;
Massenbearbeitung in einer Tabelle; Lösung des Schlüsselproblems bei wachsender Kennungsliste.

## Stress Test Results: Archiv-Handbearbeitung (Bead `nola-efj`, 15.10.2026)

### Resolved Decisions
- Tabelle `archiv_handwerte` gehört zu `FACHTABELLEN`, nicht zu `ARBEITSTABELLEN` (Arbeitsstand wäre
  in der Cloud je Sitzung, Handwerte gehören zum gemeinsamen Archiv).
- Ein generisches Alles-oder-nichts-Schreiben `ersetze_tabellen_geprueft` für Speichern, Reset,
  Entfernen und Undo; Undo-Einträge mit mehreren Tabellen; Tageslauf und Import prüfen den Stand der
  Markierungen mit.
- Formular ohne `st.form` (Listen folgen der Nation sofort); aktueller Wert immer wählbar; Platz ≠
  Nation nur Hinweis.
- Neuberechnung wie in der Pipeline; Selbstprobe am eigenen Platz (±1°); Rückkehr zum NOLA-Wert
  entfernt die Markierung.
- Schlüsselproblem bleibt draußen (`nola-8m4`), aber ⚠ an Zeilen mit gemeinsamen NOTAM-Kennungen.
- Edit/Reset nur lokal (`local_admin_allowed`), Cloud nur lesend; Payload-Formelschutz.
- Reset je Feld („Reset to NOLA value“), Tooltip mit gemerktem Wert, kein Zeilen-Reset.
- Schema 2 additiv mit Sicherung vorher; ältere Fassungen verweigern sauber; README-Satz.
- Spalte `herkunft` (`hand`/`berechnet`); Orbit nach Platzwechsel als `berechnet` geschützt.
- Blättern im Archiv-Reiter statt `head(60)`.

### Changes Made
- Speicherung, Vorrang, Formular, Platzwechsel, Reset, Anzeige, Cloud und Tests entsprechend ergänzt.

### Deferred / Parking Lot
- `nola-8m4`: Zusammenführung über Kennungs-Überschneidung (Handwerte übertragen).
- `nola-fqz`: Remove und Referenz-Editoren in der Cloud absichern.

### Confidence Assessment
- Overall: High
- Areas of concern: Abweichung der Neuberechnung (Cluster-Punkte statt Zonen-Mittelpunkte) - durch
  Selbstprobe abgesichert; Undo über zwei Tabellen ist neuer Code im empfindlichsten Pfad.
