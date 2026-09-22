# Projektstand

Stand: 21.09.2026 · `app.py` 4347 Zeilen · `test_app.py` 391 Tests, alle grün

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
| Nationen | China, Russland, Indien, Iran, Nordkorea, USA — 31 Startplätze, 129 FIRs, 51 Trägersysteme |
| Bedienung | 6 Reiter, Klartext-Auswertung, manuelle Prüfung (Space Launch / Ausblenden), Optionsmenü zur Referenzpflege |
| Persistenz | Referenzänderungen direkt in die CSVs, Arbeitsstand in `notam_workspace.json` |

## Bekannte Grenzen

- Inklination ist eine Näherung (`cos i = cos φ · sin α`), Erdrotation nicht eingerechnet.
- Gruppierung stützt sich auf das Zeitfenster: mehr als 30 Minuten Abstand bei kurzen NOTAMs
  trennt, zwei gleichzeitige Starts vom selben Platz in ähnliche Richtung verschmelzen.
- Der Rückgängig-Stapel im Optionsmenü ist nach einem Neustart leer.
- `B4912/26` / `B4913/26` („CONDUCTED BY KOREA") bleiben bewusst im Review — der Text
  unterscheidet nicht zwischen Nord- und Südkorea.

## Offene Punkte

- **Git / erster Pull Request** — ursprüngliches Ziel, noch nicht begonnen. Das Projekt ist
  kein Repository; `gh` und Homebrew sind nicht installiert.
- **Automatische `.bak`-Kopie** der Referenzdateien beim Start (angeboten, nicht umgesetzt).
- **Streamlit Community Cloud** als Weg zu einem teilbaren Link (setzt ein GitHub-Repo voraus).
