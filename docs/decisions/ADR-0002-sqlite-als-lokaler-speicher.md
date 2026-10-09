# ADR-0002: SQLite als lokaler Speicher – eine Datei, nur lokal, Konfliktschutz statt stillem Überschreiben

Status: angenommen · Datum: 09.10.2026 · Spec: `.internal/specs/2026-10-08-lokale-datenbank-design.md`
· Plan: `.internal/plans/2026-10-08-lokale-datenbank.md` · Epic: `nola-a6c`

## Kontext

Bis Oktober 2026 lagen die eingepflegten Daten in Einzeldateien: die Referenzen in drei CSVs
(im Git), Startarchiv und Seestarts in CSVs, der Arbeitsstand in `notam_workspace.json`, der
Archiv-Import in zwei JSONs. Damit waren mehrere Schwächen verbunden:

- Ein fehlender oder kaputter Arbeitsstand führte ohne Meldung zu einem leeren Start.
- Schreibfehler wurden verschluckt (`except OSError: pass`).
- Zwei offene Tabs überschrieben sich gegenseitig.
- Extern ließ sich nichts außer der Rohdatei ansehen, und Sicherungen gab es nur von Hand.

Gewünscht war ein dauerhafter, vorerst lokaler Speicher „wie eine Access-Datenbank“: eine
Datei, die NOLA nutzt und die man zusätzlich in einem Werkzeug öffnen und bearbeiten kann.

## Entscheidung

1. **Eine SQLite-Datei `nola.db` im Projektordner** (nicht im Git) enthält alles Eingepflegte,
   einschließlich der Referenzen. Ausgenommen sind der GCAT-Cache (eine Fremdkopie) und die
   Tages-NOTAMs, die weiterhin nicht gespeichert werden. Es gibt nur ein SQL-Modul, `nola_db.py`.
   Umzug, Export und die Entscheidung beim Start stehen in `nola_umzug.py`.
2. **Echte Tabellen mit Prüfregeln, Spalten als Text.** Die Spaltennamen sind die der bisherigen
   CSVs, und jeder Wert wird als Text gespeichert, so wie `_read_csv_any` ihn liest. Zahlenregeln
   (Breite, Länge) und Pflichtfelder sind als `CHECK` hinterlegt. So kommen die Werte unverändert
   zurück, und ungültige Daten werden auch im DB Browser abgelehnt.
3. **Die Datenbank ist bei jedem Durchlauf die Quelle der Wahrheit.** `session_state` ist nur
   noch ihr Spiegel und wird in jedem Durchlauf neu gefüllt. Beim Schreiben gilt:
   - Der Arbeitsstand wird als Unterschied zu einer Momentaufnahme geschrieben, je Schlüssel geprüft.
   - Ganze Tabellen (Referenzen, Archiv, Seestarts, Undo) werden nur ersetzt, wenn ihre Prüfsumme
     noch der beim Lesen entspricht.
   - Bei einer Abweichung wird nichts geschrieben, und NOLA meldet einen Konflikt.
4. **Nie eine leere Datenbank, nie ein Überschreiben.**
   - Jede Verbindung öffnet mit `mode=rw`.
   - Umzug und Wiederherstellen enden mit `os.link`.
   - Unlesbare Altdateien, eine neuere Schema-Version oder liegengebliebene `-wal`/`-shm`-Dateien
     brechen ab, statt etwas still neu anzulegen.
   - Fehlt die Datenbank, obwohl es Sicherungen gibt, entscheidet der Benutzer.
5. **Sicherungen in iCloud, die Datenbank selbst nie.** Gesichert wird beim Start, täglich und vor
   jeder Änderung am Schema. Die Kopie entsteht als temporäre Datei mit `integrity_check` und wird
   dann umbenannt. Die letzten 30 regulären Sicherungen bleiben erhalten.
6. **Nur lokal erreichbar.** Die Bindung an `--server.address 127.0.0.1` steht im lokalen
   Startbefehl, bewusst nicht in `config.toml`, weil diese Datei auch die Cloud steuert.
   Wiederherstellen, Neuaufbau und Export sind nur über Loopback erlaubt.
7. **Die alten Dateien bleiben der Rückweg.** Sie werden beim ersten Start einmal gelesen und
   danach nicht mehr geschrieben. „Export to files“ erzeugt sie jederzeit neu. In der Cloud
   entsteht die Datenbank aus den Repo-CSVs; geänderte Referenz-CSVs werden dort per SHA-256
   erkannt und neu eingelesen.

## Begründung

- Der Kernwunsch „eine Datei, auch extern bearbeitbar“ schließt Speicher aus, die die Datei während
  der Laufzeit sperren (DuckDB) oder Inhalte als Textblock ablegen (JSON in SQLite). SQLite gehört
  zur Standardbibliothek und bringt keine neue Abhängigkeit.
- Text-Spalten statt REAL/INTEGER: Der Rundlauf CSV → SQLite → DataFrame war an allen fünf echten
  Dateien byte- und typgleich. Typisierte Spalten hätten Werte wie „40.9583“ verändert und die
  Erkennungslogik berührt.
- Konfliktschutz statt „wer zuletzt schreibt, gewinnt“: Mehrere Tabs oder Personen am eigenen
  Rechner sollen gefahrlos parallel prüfen können. Ein stiller Verlust wiegt hier schwerer als
  eine Meldung.
- Nur lokal statt Netz mit Kennwort: Ohne Anmeldung hätte jedes Gerät im WLAN Referenzen ändern
  oder Sicherungen zurückspielen können. Unverschlüsseltes HTTP mit Kennwort wäre ein Restrisiko
  gewesen.

## Folgen

- Gemessen kostet ein Durchlauf etwa 2–9 ms mehr. Es gibt keinen Cache; zu Grenze und Messung
  siehe Projektplan, Schritt 13.
- Wer die Datei extern bearbeitet, muss im DB Browser „Änderungen schreiben“, sonst meldet NOLA
  nach 5 s eine Sperre.
- Die Cloud-Fassung hält keinen dauerhaften Arbeitsstand. Ihre Referenzen folgen den Repo-CSVs.
  Wer lokal Referenzen ändert, bringt sie per Export und Commit in die Cloud.
- Unvollständige Archiv- und Seestartzeilen (ohne Datum oder Nation) werden mit einer Warnung
  übersprungen, statt die ganze Fortschreibung zu blockieren.
- Der Archiv-Import-Zustand wird noch ohne Standvergleich ersetzt (nur lokal). Das ist als
  Folgepunkt notiert.
- Ein späterer Umbau des Schemas läuft über `SCHEMA_VERSION` und `SCHRITTE`, mit Sicherung vorab.
- Rücknahme dieser Entscheidung: exportieren, die Altdateien zurückkopieren und die alte Fassung
  starten. Danach eingepflegte Daten müssen exportiert werden, sonst gehen sie für die alte
  Fassung verloren.
