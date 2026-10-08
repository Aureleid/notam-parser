# Vergangene Starts aus der Tageslage ausblenden — Design

Stand: 08.10.2026 · im Brainstorming mit Mario Antic abgestimmt · Bead `nola-ff4`

## Ausgangslage

- Erkannte Starts kommen bereits heute automatisch ins Startarchiv: `_update_archive` schreibt bei
  jedem Lauf jeden Start mit Status OK und Startplatz nach `startarchiv_updated.csv` — sofort, nicht
  erst nach Ablauf.
- Was fehlt: NOLA kennt kein „abgelaufen". Es gibt keinen Vergleich mit der aktuellen Zeit, und
  eingefügte NOTAMs bleiben im Arbeitsstand, bis sie von Hand verworfen werden. Am 08.10.2026 stehen
  15 eingefügte Meldungen im Arbeitsstand, darunter die Seestarts vom 11. und 12.02.2026. Die Launch
  Overview zeigt sie neben Starts vom Oktober.

## Ziel

Vergangene Starts verlassen die Tageslage und sind dann nur noch im Archiv zu finden.
**Ausgeblendet wird, gelöscht wird nichts.**

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Was passiert mit einem vergangenen Start? | Ausblenden, nicht löschen. Ein Schalter holt ihn zurück; der Arbeitsstand bleibt unverändert. |
| Ab wann gilt ein Start als vergangen? | Spätestes Fensterende aller zugehörigen Meldungen + 24 h Karenz < jetzt (UTC). |
| Was passiert mit nicht archivierten Fällen? | Nur Archiviertes wird ausgeblendet. Abgelaufene Review-Fälle und Starts ohne Startplatz bleiben sichtbar, Review-Fälle mit der Marke „expired". |
| Wie wird es umgesetzt? | Ansatz A: Ansichtsfilter nach der Auswertung. Kein neuer Status in `analyze_notams`, damit der Archiv-Import für historische Tage unberührt bleibt. |

## Regel

Neue reine Funktion in `app.py`:

```
past_launch_rows(groups, events, archiv_keys, now, karenz=PAST_LAUNCH_GRACE) -> Set[int]
```

`PAST_LAUNCH_GRACE = timedelta(hours=24)` ist eine feste Konstante in `app.py` mit kurzem
Kommentar zur Wahl. Einen Regler gibt es nicht.

Sie liefert die Tabellenzeilen (`row_index`) vergangener Starts. Eine Gruppe ist vergangen, wenn
**alle** Bedingungen erfüllt sind:

1. Sie hat einen Startplatz (`spaceport_code`) und mindestens eine Zone mit Status OK — also
   genau die Gruppen, die `_update_archive` archiviert.
2. **Abgelaufen:** Das späteste Ende über alle Meldungen der Gruppe (`row_indices` und
   `advance_row_indices`) liegt mehr als `karenz` vor `now`. Ende einer Meldung = `valid_to`,
   ersatzweise `valid_from`. Hat keine Meldung eine Zeit, ist die Gruppe nie vergangen. Zeiten
   ohne Zeitzone gelten als UTC.
3. **Im Archiv:** `archive_key(archive_row(g, events))` ist in `archiv_keys` enthalten. Der
   Schlüssel wird genau so gebildet wie in `_update_archive`: mit `archive_row(g, events)` über
   alle Meldungen.

Zurückgegeben werden die `row_indices` und `advance_row_indices` vergangener Gruppen: Eine
Vorankündigung verschwindet mit ihrem Start. Review-Fälle, Gruppen ohne Startplatz und nicht
archivierte Gruppen liefern nie Zeilen.

`now` wird übergeben und nicht in der Funktion gelesen; im Tagesbetrieb ist es
`datetime.now(timezone.utc)`.

## Einbindung in `main`

- Direkt **nach** `_update_archive` (das Archiv ist dann bereits geschrieben): Archiv streng lesen
  (`read_archive_strict`), Schlüsselmenge bilden, `past_launch_rows` aufrufen.
- Bei `ArchiveUnreadable`: leere Menge — es wird nichts ausgeblendet — und eine Meldung in der
  Seitenleiste (englisch), z. B. „Past launches are not hidden: the launch archive could not be
  read."
- Die vergangenen Zeilen fließen in die bestehende Filtermaske ein
  (`mask &= ~table["_row"].isin(past_rows)`), solange der Schalter aus ist. Launch Overview,
  Flightpath Map, NOTAM Data, Export, Klartext-Auswertung und die Zähler folgen dieser Maske
  bereits. Der Datumsfilter richtet seinen Bereich nach den verbleibenden Zeilen.
- Unverändert bleiben: Erkennung, Archivschreiben, Seestart-Protokoll, Arbeitsstand
  (`notam_workspace.json`, eingefügte NOTAMs), der Reiter „Excluded" und der Archiv-Import.

## Bedienung

- Seitenleiste, Abschnitt „Filter": Schalter **„Show past launches"**, standardmäßig aus und nicht
  gespeichert. Nach einem Neustart zeigt NOLA wieder die aktuelle Lage.
- Darunter, nur wenn etwas ausgeblendet ist: „N past launch(es) hidden – in the launch archive".
- Bei eingeschaltetem Schalter sind vergangene Starts in der Launch Overview als „past" erkennbar.
- Liste „Pasted entries" in der Seitenleiste: Einträge, die zu einem ausgeblendeten Start gehören,
  werden mit „(past)" markiert und ans Ende sortiert. Die Überschrift zählt sie getrennt, z. B.
  „Pasted entries (15 · 11 past)". Gelöscht wird nichts.
- Launch Overview: Ein Start, dessen Schlüssel in `archiv_removed` steht (im Archiv-Editor
  entfernt), wird nie ausgeblendet. Er trägt den Hinweis „removed from archive"; ausblenden lässt er
  sich wie bisher über „Excluded".
- Im Review tragen Fälle, deren spätestes Fensterende mehr als 24 h zurückliegt, die Marke
  „expired". Sie werden weder ausgeblendet noch automatisch entschieden.

## Fehlerfälle

- Archiv unlesbar: nichts ausblenden, Meldung (siehe oben).
- Start nicht im Archiv, etwa weil er im Archiv-Editor entfernt wurde (`archiv_removed`): bleibt
  sichtbar.
- Fensterende in der Zukunft, innerhalb der Karenz oder keine Zeit vorhanden: bleibt sichtbar.
- Ein ersetztes NOTAM (NOTAMR), von dem nur die alte Fassung im Arbeitsstand liegt, wird
  ausgeblendet, sobald sein altes Fenster samt Karenz vorbei ist. Das ist gewollt: Die alte Fassung
  beschreibt keinen anstehenden Start mehr, und die neue Fassung kommt als eigener Start (Datei
  oder Einfügen) und bleibt sichtbar. Der abgesagte Versuch steht wie bisher im Archiv (offener
  Punkt „zwei Startversuche desselben Starts").

## Tests (`test_app.py`)

`past_launch_rows` mit festem `now`:
- Fensterende 25 h zurück und archiviert → vergangen.
- Fensterende 23 h zurück → sichtbar.
- Ohne `valid_to` zählt `valid_from`; ohne beide Zeiten → nie vergangen.
- Nicht im Archiv → sichtbar.
- Die Vorankündigung wird mit ihrem Start ausgeblendet. Endet sie später als der Start, zählt ihr
  Ende.
- Gruppe ohne Startplatz und Review-Fall → nie vergangen.

Außerdem:
- Unlesbares Archiv: Die Einbindung liefert eine leere Menge und wirft keine Ausnahme. Dafür wird
  die Einbindung als kleine Hilfsfunktion gekapselt und getestet.
- Quelltextprüfung: Die Berechnung steht nach `_update_archive`, und der Arbeitsstand wird dabei
  nicht verändert.
- Marke „expired" im Review für einen abgelaufenen Review-Fall.
- Ein Start mit Schlüssel in `archiv_removed` bleibt sichtbar und trägt „removed from archive".
- „Pasted entries": Markierung „(past)", Sortierung ans Ende und getrennte Zählung.
- Ein Echtbestand-Test: Mit der FNS-Datei und einem `now` weit nach deren Fenstern werden alle
  archivierten Starts ausgeblendet; mit einem `now` davor keiner.

## Nicht Teil dieses Vorhabens

- Endgültiges Löschen eingefügter NOTAMs aus dem Arbeitsstand. Ein Knopf „Discard pasted entries
  of past launches" kommt als offener Punkt in den Projektplan.
- Automatisches Entscheiden abgelaufener Review-Fälle.
- Änderungen an Erkennung oder Archiv-Import.

## Nach der Umsetzung

Laut `CLAUDE.md`: neuer Schritt im Projektplan `docs/projektplan.html`, Ast mit
`past_launch_rows` unter „Bedienoberfläche", `STATUS.md` aktualisieren und das Artifact
veröffentlichen.

## Ergebnisse des Gegentests: vergangene Starts

Durchgeführt am 08.10.2026, 5 von 5 Punkten gelöst, alle wie empfohlen angenommen.

### Entscheidungen
- **Aus dem Archiv entfernte Starts** (`archiv_removed`) werden nie ausgeblendet und tragen den
  Hinweis „removed from archive". Ausblenden geht wie bisher über „Excluded".
- **Wachsender Arbeitsstand:** Einträge vergangener Starts werden in „Pasted entries" mit „(past)"
  markiert, ans Ende sortiert und getrennt gezählt. Gelöscht wird nichts; der Aufräum-Knopf ist
  ein offener Punkt.
- **Ersetzte NOTAMs** im Arbeitsstand werden nach ihrem alten Fenster ausgeblendet. Das ist
  gewollt und in den Fehlerfällen dokumentiert.
- **Karenz:** feste Konstante `PAST_LAUNCH_GRACE` = 24 h, kein Regler.
- **Sicherheit:** Es gibt keine Sicherheitsfläche; die Änderung schreibt nichts. Das Risiko, dass
  ein Start aus dem Blick gerät, ist durch drei Schranken abgedeckt: Ausgeblendet wird nur
  Archiviertes, ein unlesbares Archiv blendet nichts aus, und der Schalter holt alles zurück.

### Änderungen an der Spec
Schlüsselbildung präzisiert; Konstante; Markierung in „Pasted entries"; Hinweis „removed from
archive"; NOTAMR-Fall unter „Fehlerfälle"; Tests dazu; Aufräum-Knopf als offener Punkt.

### Zurückgestellt
- Knopf „Discard pasted entries of past launches".

### Einschätzung
- Gesamt: hoch. Die Änderung ist ein reiner Ansichtsfilter an einer einzigen Maske, ohne
  Schreibzugriff.
