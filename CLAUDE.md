# NOLA – Arbeitsregeln

## Projektplan fortschreiben (verbindlich)

Jedes neue Feature und jede große Änderung (neue Erkennungsregel, neue Funktion, neuer Reiter,
neue Referenzdatei, Änderung der Zuordnungs- oder Gruppierungslogik, Veröffentlichung)
wird im Projektplan nachgetragen, bevor die Aufgabe als erledigt gemeldet wird.

- Quelle der Wahrheit: `docs/projektplan.html` (Daten in `STEPS` und `TREE` im Skript).
- Neuer Ast oder neue Funktion: in `TREE` unter dem passenden Hauptast eintragen, mit echtem
  Funktionsnamen aus `app.py` im Feld `f`.
- Große Änderung: als neuen Schritt in `STEPS` anfügen (Nummer, Name, eindeutige Überschrift,
  Beschreibung, Ergebnis) und die betroffenen Äste mit `s` darauf verweisen lassen.
- Erledigte offene Punkte aus dem Ast "Offene Punkte" entfernen, neue dort ergänzen.
- Kennzahlen im Kopf (Zeilen, Tests, Startplätze, FIRs, Trägersysteme) mit `STATUS.md` abgleichen.
- Danach die Online-Fassung aktualisieren: Artifact `https://claude.ai/artifact/SR4YwYSqPceEBzsiPwVPhe`
  (erst lesen, dann mit `url` veröffentlichen). Das Artifact enthält dieselbe Seite ohne
  `<!doctype>`, `<html>`, `<head>`, `<body>`-Hülle.
- Nicht committen, solange der Benutzer es nicht verlangt.
