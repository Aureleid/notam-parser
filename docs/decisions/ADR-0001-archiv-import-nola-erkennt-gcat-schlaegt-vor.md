# ADR-0001: Archiv-Import – NOLA erkennt, GCAT schlägt vor, ins Archiv nur nach Bestätigung

Status: angenommen · Datum: 06.10.2026 · Spec: `.internal/specs/2026-10-02-archiv-import-design.md`
· Plan: `.internal/plans/2026-10-02-archiv-import.md`

## Kontext

Das Startarchiv (`startarchiv_updated.csv`) soll mit den Starts von China, Russland, Indien,
Iran und Nordkorea aus 2020–2026 gefüllt werden, rund 600 Starts. Später werden neue Starts
dagegen verglichen (Ähnlichkeit in Prozent, `docs/intent/nola-massstab.md`). Die NOTAMs
stammen aus dem NSF-Forum. Die Startliste GCAT (J. McDowell) kennt zu jedem Flug Rakete,
Nutzlast, Inklination und Azimut.

Am schnellsten wäre es, das Archiv direkt aus GCAT zu füllen oder GCAT-Werte über NOLAs
Schätzungen zu legen. Dann stünde im Archiv aber nicht mehr, was NOLA aus NOTAMs ableitet.
Der spätere Vergleich würde einen neuen, aus NOTAMs geschätzten Start mit fremden Messwerten
vergleichen.

## Entscheidung

1. **Erkannt wird ausschließlich mit der Pipeline des Tagesbetriebs** (`analyze_notams`). Für
   den Import gibt es keine Sonderregeln.
2. **Aus GCAT kommen nur Rakete und Payload, und nur als Vorschlag.** Inklination, Azimut und
   Nation bleiben NOLAs eigene Werte. GCAT dient bei ihnen nur als Plausibilitätsprüfung
   (Warnung ab 10° Abweichung).
3. **Ins Archiv kommt ein historischer Start erst nach Bestätigung durch den Benutzer.** Die
   Sammelbestätigung erfasst nur eindeutige Treffer ohne Warnung. Seestarts und Treffer nur
   mit Tagesdatum werden immer einzeln bestätigt.
4. **Bestätigte Starts, die NOLA nach einer Neuauswertung nicht mehr erkennt, werden
   angezeigt, nie automatisch gelöscht.**
5. **Der Import ist nur lokal sichtbar (fail-closed).** Er erscheint nicht unter `/mount/src`
   und nur bei Host `localhost`, `127.0.0.1` oder `[::1]`.
6. **Die USA sind ausgenommen, werden aber erkannt.** Sie fallen erst nach der Erkennung
   heraus, damit ein US-Start keiner anderen Nation zugeschlagen wird.

## Begründung

- Laut Maßstab ist eine falsche Zuordnung schlimmer als ein Fall im Review. Eine aus GCAT
  übernommene Zahl wäre eine Zuordnung ohne Beleg aus den NOTAMs.
- Der Ähnlichkeitsvergleich braucht vergleichbare Größen: NOLA-Schätzung gegen
  NOLA-Schätzung.
- Rakete und Payload kann NOLA aus NOTAMs grundsätzlich nicht ableiten. Dort ist ein
  dokumentierter Flug die beste Quelle, solange ein Mensch die Paarung bestätigt. Laut Maßstab
  darf das Trägersystem nicht automatisch erraten werden.
- Im Netz könnte jeder Besucher ins Archiv schreiben. Eine Ausschlussliste (fail-open) würde
  bei einem geänderten Hosting-Pfad still versagen.

## Folgen

- Das Füllen dauert länger: Jede Paarung braucht einen Klick, bei eindeutigen Treffern einen
  für alle.
- Starts mit unsicherer Erkennung fehlen, bis die Import-Prüfliste abgearbeitet ist.
- Ändert sich NOLAs Erkennung, wird neu ausgewertet. Bestätigungen bleiben erhalten, und
  Abweichungen werden sichtbar statt still übernommen.
- Wer das Archiv später schneller füllen will, etwa durch Übernahme der GCAT-Inklination,
  muss dieses ADR ersetzen. Bestehende Zeilen ließen sich danach nicht mehr nach Herkunft
  trennen.
- Im Netz gibt es keinen Import, auch nicht im Heimnetz über die IP.
