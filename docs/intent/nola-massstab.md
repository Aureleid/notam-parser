# Maßstab NOLA

Festgehalten am 25.09.2026 im Gespräch mit Mario Antic.

Dieses Dokument beschreibt, **was NOLA leisten soll** — aus Sicht des Benutzers, nicht aus
Sicht des Codes. Es ist bewusst frei von Implementierungsdetails: Es dient als unabhängiger
Maßstab, gegen den der gebaute Stand geprüft werden kann. Wer prüft, darf dieses Dokument
und den Code sehen, aber nicht die Begründungen der Entwicklungsgespräche — sonst misst die
Prüfung die Umsetzung an ihrer eigenen Beschreibung.

## Zweck

Eine tägliche Lage: welche Raumfahrtstarts der sechs Zielnationen — China, Russland,
Indien, Iran, Nordkorea, USA — stehen an.

## Arbeitsablauf

Dieselbe NOTAM-CSV wird jeden Tag heruntergeladen und eingepflegt. Parallel liest der
Benutzer ein Forum, das Zugang zu russischen und chinesischen Meldungen hat, und trägt
NOTAMs von dort manuell nach.

## Was NOLA je Start zeigen muss

- **Wann** der Start ansteht
- **Von wo** er ausgeht
- **Welchen Weg** er nimmt — die Dropzones entlang der Bahn
- **Wohin die Nutzlast geht** — Inklination und Orbitregime

Dazu, von Hand zu ergänzen: **Trägersystem** und **Payload**.

## Die Fehlerabwägung

**Eine falsche Zuordnung ist deutlich schlimmer als ein übersehener oder ein zu prüfender
Start.**

Der Bezugsfall: „Starship als indischer Start". So etwas darf nicht wieder vorkommen.

Die Begründung liegt im Arbeitsablauf. Für einen übersehenen Start gibt es ein zweites
Netz — das Forum. Für eine falsche Zuordnung gibt es keins: Sie geht ungeprüft in die
Tageslage und später in die Datenbank, gegen die künftige Starts verglichen werden.

Daraus folgt: **Ein Fall im Review ist gewünschtes Verhalten, kein Mangel.** Eine Zuordnung
ohne Beleg ist ein Fehler, auch wenn sie zufällig stimmt.

## Die Zuordnungsgrenze

Nennt der Text die Nation nicht, darf sie nur dann aus der Geografie folgen, wenn der
betroffene Luftraum der Nation **selbst** gehört. Ist fremdes Gebiet betroffen, braucht es
einen Beleg in der Meldung.

Diese Grenze ist das Herzstück. Sie muss beide Seiten aushalten:

- Chinesische und russische Start-NOTAMs nennen oft **nichts** — kein Raumfahrtwort, keinen
  Betreiber, keine Rakete. Eine Regel „der Text muss es belegen" würde genau diese verlieren.
- Eine Regel „die Geografie genügt" hätte Starship als indischen Start stehen lassen.

## Bekannte Lücke

**Bewegliche Seestartplattformen.** China nutzt sie zunehmend, etwa im Gelben Meer. Solche
NOTAMs nennen keinen Startplatz, und eine bewegliche Plattform lässt sich nicht als fester
Punkt führen. Es braucht dafür einen eigenen Weg der Zuordnung — noch nicht entworfen.

## Langfristiges Ziel

Das Startarchiv als Datenbank. Bei einem neu eingespeisten Start — aus der Datei oder von
Hand — zeigt NOLA die **Ähnlichkeit in Prozent** zu früheren Starts derselben Nation und
leitet daraus eine Vermutung ab, welche Payload verbracht werden könnte und in welches
Orbitregime bei welcher Inklination.

## Ausdrücklich nicht

- **Kein automatisches Erraten des Trägersystems.** Es wird von Hand gesetzt.
- **Keine weiteren Startnationen.** Die sechs sind der Auftrag.
- **Der Review wird nicht um den Preis von Zuordnungen geleert.** Weniger Fälle im Review
  sind kein Ziel an sich.
