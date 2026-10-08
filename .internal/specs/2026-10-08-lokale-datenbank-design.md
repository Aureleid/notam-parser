# Dauerhafter lokaler Speicher (SQLite) — Design

Stand: 08.10.2026 · im Brainstorming mit Mario Antic abgestimmt, Stresstest durchlaufen ·
Beads `nola-xed` (Brainstorming), `nola-b3e` (Stresstest)

## Ausgangslage

NOLA hat keine Datenbank. Eingepflegte Daten liegen in Einzeldateien im Projektordner:

| Daten | Datei heute | Schreibweg heute |
|---|---|---|
| Arbeitsstand (manuelle NOTAMs, Bestätigt/Ausgeblendet/Abgelehnt/Wiederhergestellt, Archiv- und Seestart-Löschungen, Zuweisungen Trägersystem/Payload/Startplatz) | `notam_workspace.json` | `_persist_workspace` → `save_workspace` schreibt die ganze Datei neu; `main()` liest sie einmal je Sitzung |
| Referenzen Startplätze, FIRs, Trägersysteme | `*_updated.csv` (im Git) | `persist_reference` über `_write_reference`, Undo mit 20 Schritten (`_push_undo`) |
| Startarchiv | `startarchiv_updated.csv` | `persist_archive`, atomar |
| Seestarts | `seestarts_updated.csv` | `persist_sea_launches`, nicht atomar |
| Archiv-Import | `archiv_korpus.json`, `archiv_import.json` | `save_korpus`, `save_state` (atomar) |

Schwächen: ein fehlender oder kaputter Arbeitsstand führt still zu einem leeren Start; Schreibfehler
werden verschluckt (`except OSError: pass`); die Daten liegen verteilt; extern lassen sie sich nur
als Rohdatei ansehen; Sicherungen gibt es nur von Hand.

## Ziel

Eine einzige, dauerhafte, lokale Datenbankdatei, wie eine Access-Datenbank: NOLA arbeitet mit
ihr, sie lässt sich zusätzlich in „DB Browser for SQLite“ ansehen, abfragen und bearbeiten, und
mehrere Personen bzw. Tabs am eigenen Rechner können gleichzeitig prüfen, ohne sich still zu
überschreiben.

## Entscheidungen

| Frage | Entscheidung |
|---|---|
| Was kommt in die Datenbank? | Alles Eingepflegte, **einschließlich der drei Referenzen**. Nicht: GCAT-Cache (Fremdkopie, bleibt `gcat_launch_cache.tsv`), hochgeladene Tages-NOTAMs (werden weiter nicht gespeichert). |
| Cloud-Fassung? | Vorerst egal. Die Referenz-CSVs im Repo bleiben stehen und werden nicht mehr fortgeschrieben; die Cloud baut sich beim Start daraus eine flüchtige Datenbank. Aktualisieren über den Export (siehe Rückweg). |
| Art der Datenbank | SQLite-Datei, auch extern zu öffnen. Ansatz A: echte Tabellen mit Prüfregeln, Pythons `sqlite3`, keine neue Abhängigkeit. |
| Altdateien | Beim ersten Start einmal übernehmen, dann unverändert ruhen lassen. |
| Ort und Sicherung | `nola.db` im Projektordner (nicht im Git); Sicherungen in iCloud, Start + täglich, die letzten 30. |
| Mehrbenutzer | Ja, mit Konfliktschutz (Vergleich mit der Momentaufnahme), ohne Personen/Anmeldung. |
| Netzzugang | **Nur lokal**: Streamlit wird lokal an `127.0.0.1` gebunden. Mehrere Personen arbeiten am eigenen Rechner. |

## Aufbau

Neues Modul `nola_db.py`. Nur dieses Modul spricht SQL. `app.py` und `archiv_import.py` rufen
fachliche Funktionen auf und sehen weder SQL noch Pfade. Die heutigen Funktionen `load_workspace`,
`save_workspace`, `persist_reference`, `persist_archive`, `load_archive`/`read_archive_strict`,
`load_sea_launches`, `persist_sea_launches`, `load_korpus`, `save_korpus`, `load_state`,
`save_state` werden zu dünnen Aufrufen in dieses Modul oder durch dessen Funktionen ersetzt. Die
CSV/JSON-**Leser** bleiben erhalten: Sie werden für Umzug, Export-Rundlauf und Tests gebraucht.

Schnittstelle (Namen verbindlich für den Plan, Feinschnitt dort):

- `verbinde(pfad) -> sqlite3.Connection`: öffnet **immer** mit `file:<pfad>?mode=rw` (URI) — eine
  fehlende Datei ist ein Fehler, nie eine neue leere Datenbank. `busy_timeout = 5000`,
  `foreign_keys = ON`. Ist `NOLA_TEST` gesetzt und zeigt `pfad` auf die Projektdatei `nola.db`,
  wirft `verbinde` eine Ausnahme.
- `stelle_bereit(pfad, altdateien, sicherungsordner) -> Startzustand`: Schema prüfen/heben, ggf.
  Umzug. Ergebnis `bereit | umgezogen | fehlt_mit_sicherungen | fehlgeschlagen` + Grund.
- `lade_referenz(conn, art) -> DataFrame` / `schreibe_referenz(conn, art, df, erwartete_pruefsumme)`;
  `art` aus fester Liste `startplaetze | firs | traegersysteme`.
- `lade_archiv`, `fuehre_archiv_fort(conn, neue_zeilen)` (liest in der Schreibtransaktion neu),
  `entferne_archivzeile`; entsprechend für Seestarts.
- `lade_arbeitsstand(conn) -> Dict` (Form wie heute `load_workspace`, manuelle NOTAMs zusätzlich mit
  `id`), `schreibe_unterschiede(conn, momentaufnahme, aktuell) -> None | Konflikt`.
- `lade_korpus`/`speichere_korpus`, `lade_importzustand`/`speichere_importzustand`.
- `sichere(conn, zielordner, behalten=30, zusatz="") -> Optional[Path]`,
  `liste_sicherungen(zielordner)`, `stelle_wieder_her(sicherung, pfad)`.
- `exportiere(conn, zielordner) -> Path` (alte Formate).

### Verbindungen

- Eine eigene Verbindung je Streamlit-Durchlauf (zu Beginn von `main()` geöffnet, am Ende
  geschlossen) und je Callback. **Keine** geteilte Verbindung über Threads (`check_same_thread`
  bleibt an).
- `st.cache_resource` nur für das *Ergebnis* von `stelle_bereit` und der Startsicherung, nie für
  eine Verbindung. Streamlit 1.50 sperrt `cache_resource` je Schlüssel; innerhalb eines Prozesses
  läuft der Umzug also nur einmal. Gegen einen zweiten Prozess schützt `os.link` (siehe Umzug).
- WAL-Modus wird einmal in der Datei gesetzt.

### Tabellen

Spaltennamen der Referenz-, Archiv- und Seestarttabellen sind **genau** die heutigen CSV-Spalten
(`Kurzel`, `Zugehörige Startnation`, `Trägersystem`, `Länge` …), in SQL in Anführungszeichen.
Alle Fachspalten sind `TEXT`, weil `_read_csv_any` heute jede Spalte als Text liest
(`dtype=str`) — so kommt jeder Wert byte-gleich zurück. Zahlenspalten prüfen ihren Zahlwert per
`CHECK` (`CAST(… AS REAL)` im Bereich und mindestens eine Ziffer). **Datum und Uhrzeit bleiben Text
im heutigen Format** (`TT.MM.JJJJ`, `HH:MM`). (Korrektur beim Planschreiben: statt REAL/INTEGER.)

| Tabelle | Spalten | Schlüssel und Prüfregeln |
|---|---|---|
| `startplaetze` | `SPACEPORT_EXPORT_COLUMNS` | `Kurzel` PRIMARY KEY, nicht leer; `Latitude` −90…90, `Longitude` −180…180 |
| `firs` | `FIR_EXPORT_COLUMNS` | `ICAO Code` PRIMARY KEY, Länge 3–4 (US-ARTCC wie `ZAB` haben 3 Zeichen; Korrektur in der Umsetzung); Koordinaten wie oben |
| `traegersysteme` | `VEHICLE_EXPORT_COLUMNS` | `Abkürzung` PRIMARY KEY (der Referenzeditor schlüsselt danach), `Name` nicht leer |
| `startarchiv` | `id` + `ARCHIVE_COLUMNS` | `id` INTEGER PRIMARY KEY; `NOTAM`, `Startdatum`, `Nation` NOT NULL |
| `seestarts` | `id` + `SEA_LAUNCH_COLUMNS` | `id` INTEGER PRIMARY KEY; `Datum`, `Nation` NOT NULL |
| `manuelle_notams` | `id`, `text`, `added`, `geaendert_utc` | `text` NOT NULL, nicht leer |
| `entscheidungen` | `schluessel`, `art`, `geaendert_utc` | UNIQUE(`schluessel`, `art`); `art` ∈ {`bestaetigt`, `ausgeblendet`, `abgelehnt`, `wiederhergestellt`, `archiv_entfernt`, `seestart_entfernt`} |
| `zuweisungen` | `schluessel`, `feld`, `wert`, `geaendert_utc` | PRIMARY KEY(`schluessel`, `feld`); `feld` ∈ {`traegersystem`, `payload`, `startplatz`}; `wert` nicht leer (leer = Zeile löschen) |
| `archiv_korpus` | `schluessel`, `notam_id`, `b`, `text`, `quellen_json` | `schluessel` PRIMARY KEY |
| `archiv_import_tage` | `iso`, `fingerprint`, `inhalt_json` (der ganze Tageseintrag, verlustfrei) | `iso` PRIMARY KEY |
| `archiv_import_entscheidungen` | `schluessel`, `wert_json` | `schluessel` PRIMARY KEY |
| `archiv_import_review` | `art`, `pos`, `schluessel` | PRIMARY KEY(`art`, `pos`) — Reihenfolge bleibt; `art` ∈ {`bestaetigt`, `ausgeblendet`} |
| `meta` | `schluessel`, `wert` | `schema_version`, `umgezogen_utc`, `umzug_quellen`, `erkennungsstand` |

**Datentypen beim Lesen:** `lese_tabelle` liefert Text-Spalten (`object`) wie `_read_csv_any`:
NULL **und** `''` (extern im DB Browser eingetragen) werden zu `NaN`. Die fachliche Aufbereitung
(Strip, Großschreibung, `Nationen`) bleibt in `app.py` und wird für Datei und Datenbank gemeinsam
genutzt.

Abwägung Archiv-Import: Kandidaten, Prüfliste und Import-Entscheidungen sind maschinell erzeugte,
verschachtelte Einträge. Sie bleiben als JSON-Text je Zeile. Die fachlich wichtigen Daten (Archiv,
Referenzen, Arbeitsstand) liegen vollständig als Spalten vor. `load_state`s heutige
Strukturprüfung (`ImportStateError`) gilt unverändert für den Inhalt dieser Felder.

### Schema-Version

`meta.schema_version` (Start: 1). Vor jeder Schema-Änderung wird gesichert
(`nola-…-vor-schema-<n>.db`, zählt nicht zu den 30); **scheitert die Sicherung, wird nicht
umgebaut**. Der Umbau läuft in nummerierten Schritten in einer Transaktion. Eine **neuere** Version
als die bekannte führt zum Abbruch mit Meldung (nie überschreiben).

## Datenfluss

**Die Datenbank ist bei jedem Durchlauf die Quelle der Wahrheit; `session_state` ist ihr Spiegel.**

- **Lesen:** Zu Beginn jedes Durchlaufs füllt `main()` die bisherigen `session_state`-Schlüssel
  (`manual_notams`, `confirmed_launches`, `hidden_events`, `rejected_launches`, `*_assignments`,
  `archiv_removed`, `restored_events`, `seestarts_removed`) aus der Datenbank und legt eine
  **Momentaufnahme** dieses Stands ab. Lesende Stellen im Code bleiben unverändert. Referenzen und
  Archiv werden ebenfalls je Durchlauf frisch gelesen; der mtime-Cache von
  `load_spaceports`/`load_firs`/`load_vehicles` entfällt, `Nationen` entsteht wie heute beim Laden.
- **Schreiben (Arbeitsstand):** Alle Änderungen laufen heute schon durch `_persist_workspace()` (16
  Aufrufe aus `on_click`/`on_change`-Callbacks). `_persist_workspace` vergleicht den aktuellen
  `session_state` mit der Momentaufnahme und schreibt **nur die Unterschiede** über
  `schreibe_unterschiede`. Die 16 Aufrufstellen ändern sich nicht. Callbacks laufen vor dem
  nächsten Durchlauf; die Änderung steht also in der Datenbank, bevor neu geladen wird.
  **Regel:** Jede Änderung am Arbeitsstand muss `_persist_workspace()` aufrufen — ein Test prüft
  das für alle Aktionsfunktionen.
- **Manuelle NOTAMs** tragen im `session_state` ihre Datenbank-`id`. `_remove_manual` löscht über
  die `id`, nicht über die Listenposition; der Abgleich erkennt NOTAMs an der `id`.
- **Konfliktschutz:** `schreibe_unterschiede` öffnet `BEGIN IMMEDIATE` und prüft für jede zu
  ändernde Zeile, ob die Datenbank noch den Wert der Momentaufnahme hat. Weicht eine Zeile ab, wird
  die **ganze** Aktion zurückgerollt und NOLA meldet „Changed by someone else meanwhile – the view
  has been reloaded, please check again“. Änderungen an verschiedenen Zeilen kommen beide durch.
- **Referenzen (Optionsmenü, Undo):** `schreibe_referenz` prüft in der Schreibtransaktion die
  Prüfsumme des Tabelleninhalts gegen die Momentaufnahme; bei Abweichung wird nicht geschrieben
  (gleiche Meldung). `_push_undo` merkt den Tabelleninhalt statt des Dateiinhalts; Zurücknehmen
  ist eine Referenzschreibung mit Prüfsumme. 20 Schritte wie heute.
- **Archiv und Seestarts (alle Schreiber: `_update_archive`, `_remove_archive_row`,
  `_update_sea_launches`, `_remove_sea_launch_row`, Archiv-Import `confirm_many`/`remove_orphan`):**
  gelesen wird mit Stand (Prüfsumme in `df.attrs["nola_stand"]`), zusammengeführt wie heute
  (`merge_archive`, `merge_sea_launches`), geschrieben mit Vergleich gegen diesen Stand in einer
  Schreibtransaktion. Bei Abweichung: `_update_archive`/`_update_sea_launches` lesen einmal neu und
  wiederholen; Benutzeraktionen melden den Konflikt. Zwei gleichzeitige Durchläufe können denselben
  Start so nicht doppelt eintragen. (Korrektur beim Planschreiben: ganze Tabelle mit Prüfsumme statt
  Einzelzeilen — die Zusammenführungsregeln bleiben dadurch unverändert.)
- **Undo einheitlich:** Jeder Undo-Eintrag (Referenzen, Archiv, Seestarts) merkt Tabelleninhalt vorher
  und Stand nachher; Zurücknehmen nur, wenn der Stand noch der von nachher ist (heute nur beim
  Archiv so, künftig für alle).
- **Erkennungsstand** (`detection_stamp` in `archiv_import.py`): Statt der drei Referenz-CSVs gehen
  die Inhalte der drei Referenztabellen (sortiert, als Text) in die Prüfsumme ein.
- **Sperre:** Hält ein externes Werkzeug eine Schreibtransaktion offen (DB Browser bis „Änderungen
  schreiben“), wartet NOLA 5 s und meldet dann „Database is locked – write or revert the changes in
  DB Browser“.

## Fehlerbehandlung

Kein stilles Verschlucken mehr (die heutigen `except OSError: pass` entfallen). Jeder
`sqlite3`-Fehler beim Schreiben rollt die Transaktion zurück, erscheint als Fehlermeldung mit
Ursache (`locked`, `disk full`, `constraint failed: <Regel>`, `database corrupt`), und der nächste
Durchlauf zeigt den echten Datenbankstand. Ausnahme: Das automatische Fortschreiben des Archivs je
Durchlauf meldet sich als **Warnung** und hält die Seite nicht an, damit die Tageslage lesbar bleibt.
Werte, die nach externer Bearbeitung fachlich nicht passen (z. B. unbekanntes Land), meldet NOLA
wie heute als Hinweis.

## Erster Start und Umzug

`stelle_bereit` beim App-Start (einmal je Serverprozess, `st.cache_resource`):

1. `nola.db` vorhanden → Schema prüfen/heben → `bereit`.
2. `nola.db` fehlt, **keine** Sicherung im Sicherungsordner → Umzug:
   - in eine temporäre Datei `nola.db.<zufall>.tmp` im selben Ordner, eine Transaktion;
   - jede Altdatei mit den heutigen Lesern einlesen (`migrate_archive_keys` greift);
   - fehlende Altdatei → leere Tabelle; **unlesbare** Altdatei → Abbruch, temporäre Datei löschen,
     NOLA nennt die Datei und stoppt (`st.stop`), statt leer zu starten;
   - Zeilenzahl je Quelle gegen die Tabelle prüfen; Abweichung → Abbruch wie oben;
   - `meta` füllen, dann **`os.link(tmp, nola.db)`** (schlägt fehl, wenn `nola.db` inzwischen
     existiert — ein zweiter Prozess überschreibt so nie eine Datenbank; der unterlegene verwirft
     seine temporäre Datei und öffnet die vorhandene), dann `tmp` löschen → `umgezogen`.
   - Die Altdateien werden nicht verändert, nicht verschoben, nicht mehr geschrieben.
3. `nola.db` fehlt, **es gibt Sicherungen** (auch: Datei verschwindet im laufenden Betrieb, erkannt
   über `mode=rw`) → kein stiller Neuaufbau. NOLA zeigt die Auswahl „Restore backup“ (Liste der
   Sicherungen mit Datum und Zeilenzahlen, vorausgewählt die jüngste, die `integrity_check`
   besteht; Wiederherstellen über temporäre Datei + `os.link`) oder „Rebuild from old files“ (Umzug
   wie 2.) und stoppt bis zur Entscheidung.

## Sicherung

- Beim App-Start und zusätzlich beim ersten Durchlauf jedes neuen Tages (gemessen am Datum der
  jüngsten Sicherung); vor jeder Schema-Änderung zusätzlich (siehe oben).
- `sqlite3.Connection.backup()` nach
  `~/Library/Mobile Documents/com~apple~CloudDocs/Claude/Claude Code/NOTAM Parser Backups/`:
  erst `.nola-JJJJ-MM-TT-HHMM.db.tmp` schreiben, dann `PRAGMA integrity_check`, dann umbenennen in
  `nola-JJJJ-MM-TT-HHMM.db`. Scheitert die Prüfung, wird die Kopie gelöscht (Warnung). Die
  Datenbank selbst liegt nie in iCloud.
- Danach nur Dateien nach dem Muster `nola-????-??-??-????.db` zählen; über 30 → die ältesten löschen.
- Ordner fehlt (z. B. Cloud) oder Kopie scheitert → Warnung in der Seitenleiste, App läuft weiter.
- Erledigt den offenen Punkt „Automatische `.bak`-Kopie der Referenzdateien beim Start“.

## Rückweg (Export)

Knopf „Export to files“ im Optionsmenü: schreibt alle Tabellen in den bisherigen Formaten (drei
Referenz-CSVs, `startarchiv_updated.csv`, `seestarts_updated.csv`, `notam_workspace.json`,
`archiv_korpus.json`, `archiv_import.json`) nach `export/JJJJ-MM-TT-HHMM/`. Die Altdateien im
Projektordner bleiben unberührt. Rückweg: exportieren, zurückkopieren, alte Fassung starten. Für die
Cloud: die drei Referenz-CSVs aus dem Export zurückkopieren und committen. Die heutigen
Einzel-Downloads (`reference_to_csv`) bleiben.

## Cloud

Unter `/mount/src` gibt es keine `nola.db` und keine Sicherungen → Umzug aus den CSVs im Repo in eine
flüchtige Datenbank; Referenzen auf eingefrorenem Stand, Arbeitsstand nicht dauerhaft (wie heute).
Sicherung, Export, Wiederherstellen und der Adresshinweis entfallen dort. Der Archiv-Import bleibt
verborgen (`archive_import_allowed` unverändert).

## Sicherheit

- **Nur lokal erreichbar:** `--server.address 127.0.0.1` im lokalen Startbefehl
  (`.claude/launch.json`, README). Bewusst **nicht** in `.streamlit/config.toml`, weil diese Datei
  auch die Cloud-Fassung steuert. Läuft NOLA lokal (nicht `/mount/src`) und ist
  `server.address` nicht Loopback, zeigt die Seitenleiste einen deutlichen Hinweis.
- **Speicher-Aktionen nur über Loopback:** „Restore backup“, „Rebuild from old files“ und „Export
  to files“ erscheinen nur, wenn `import_gate` erfüllt ist (wie der Archiv-Import).
- **Werte aus der Datenbank** (extern oder von anderen Personen eingetragen) laufen vor der Anzeige
  in Markdown-Elementen durch den vorhandenen Entschärfer für Fremdtext.
- SQL nur mit `?`-Platzhaltern. Tabellen- und Spaltennamen ausschließlich aus festen Listen in
  `nola_db.py`, nie aus Eingaben, NOTAM-Text, Forenseiten oder GCAT.
- `.gitignore`: `*.db` steht schon; ergänzt werden `nola.db-wal`, `nola.db-shm`, `nola.db.*.tmp`,
  `export/`.
- Sicherungen nur im iCloud-Ordner des Benutzers, nie im Repository.

## Tests

Gleicher Stil wie `test_app.py`: Skript mit `check()`, Temp-Ordner über `tempfile.mkdtemp()`.
Beide Testskripte setzen als Erstes `os.environ["NOLA_TEST"] = "1"` und `app.DB_PATH` auf eine
Temp-Datenbank. Vor dem Umbau wird die Zahl der `PASS`-Zeilen von `test_app.py` festgehalten;
danach müssen es mindestens gleich viele sein. Prüfungen, deren Ein-/Ausgabe sich ändert, werden mit
derselben fachlichen Aussage umgeschrieben — keine wird gelöscht oder auf `SKIP` gesetzt.

Neue Datei `test_nola_db.py`:

- **Schutz:** `verbinde` auf die echte `nola.db` unter `NOLA_TEST` → Ausnahme.
- **Umzug** mit Kopien der echten Dateien: Zeilenzahlen gleich; Rundlauf CSV → DB → DataFrame mit
  `pd.testing.assert_frame_equal` **inklusive Datentypen**; Umlaute in Spaltennamen;
  `migrate_archive_keys` greift; extern eingetragenes `''` gilt als leer.
- **Gegenproben Umzug:** unlesbare Altdatei → Abbruch, keine `nola.db`; DB fehlt bei vorhandenen
  Sicherungen → kein Neuaufbau ohne Wahl; neuere Schema-Version → Abbruch ohne Schreiben;
  `nola.db` entsteht zwischen Umzugsbeginn und `os.link` → vorhandene Datei bleibt unverändert;
  `nola.db` wird im Betrieb gelöscht → keine neue leere Datei (`mode=rw`).
- **Abgleich/Konflikt:** zweite Verbindung ändert Zeile X, NOLA schreibt Zeile Y → beide vorhanden;
  gleiche Zeile mit veralteter Momentaufnahme → abgewiesen, nichts halb geschrieben; Referenz mit
  veralteter Prüfsumme → abgewiesen; zwei gleichzeitige Archiv-Fortschreibungen → genau eine Zeile.
- **Manuelle NOTAMs:** ein NOTAM extern gelöscht, dann in NOLA ein anderes entfernt → genau das
  gewählte ist weg; zwei gleichlautende NOTAMs bleiben unterscheidbar.
- **Regel `_persist_workspace`:** jede Aktionsfunktion schreibt ihre Änderung in die Datenbank.
- **Sperre:** zweite Verbindung hält `BEGIN IMMEDIATE` → Fehler „gesperrt“, keine Teiländerung.
- **Fehler:** Prüfregeln (Breite 95°, leerer `Name`, unbekannte `art`) → abgelehnt mit Meldung;
  schreibgeschützte Datei → Meldung statt Stille.
- **Sicherung:** Kopie besteht `integrity_check` und ist vollständig; Tageswechsel löst eine weitere
  aus; nach der 31. fällt die älteste; `vor-schema`-Kopien zählen nicht mit; scheiternde Sicherung
  verhindert die Schema-Änderung; fehlender Ordner → nur Warnung; Wiederherstellen überschreibt nie.
- **Export:** Export → alte Leser → gleich der Datenbank.
- **Undo:** Hinzufügen, Entfernen, Zurücknehmen → exakt der Ausgangsstand.
- **Erkennungsstand** ändert sich bei Referenzänderung in der Datenbank.
- **Browser-Test:** zwei Tabs, gleiche Entscheidung → Konfliktmeldung; eine extern im DB Browser
  geänderte Zeile erscheint beim nächsten Klick.

## Abschluss

- `docs/projektplan.html`: neuer Schritt, Äste mit echten Funktionsnamen aus `nola_db.py`/`app.py`,
  „.bak beim Start“ aus den offenen Punkten entfernen, Kennzahlen mit `STATUS.md` abgleichen,
  Artifact aktualisieren (CLAUDE.md).
- README und STATUS: Abschnitt „Persistenz“ neu, Startbefehl mit `--server.address 127.0.0.1`.
- ADR „SQLite als lokaler Speicher“ anbieten (schwer umkehrbar).
- Reihenfolge: nach Abschluss des Zweigs `vergangene-starts`, auf eigenem Zweig.
- Commit nur auf Aufforderung (CLAUDE.md).

## Nicht Teil dieses Vorhabens

- Speichern der hochgeladenen Tages-NOTAMs bzw. eine NOTAM-Historie.
- Zugriff aus dem Netz, Anmeldung, Personen und Verlauf „wer hat was bestätigt“.
- Live-Aktualisierung der Ansicht bei Änderungen anderer (sichtbar beim nächsten Klick).
- Dauerhafter Speicher in der Cloud.
- Eigene Formulare oder Berichte außerhalb von NOLA.

## Stress Test Results: lokale Datenbank

### Resolved Decisions
- **Umbau `app.py`:** `session_state` bleibt Spiegel, je Durchlauf aus der DB gefüllt;
  `_persist_workspace` schreibt nur Unterschiede zur Momentaufnahme; die 16 Aufrufstellen bleiben.
- **Manuelle NOTAMs:** Löschen über DB-`id` statt Listenposition (sonst trifft ein Klick nach
  externer Löschung das falsche NOTAM).
- **Verbindungen:** je Durchlauf/Callback, keine geteilte Verbindung; `cache_resource` nur für
  Ergebnisse.
- **Mehrbenutzer:** gewollt, mit Konfliktschutz über Vergleich mit der Momentaufnahme
  (Arbeitsstand zeilenweise, Referenzen per Prüfsumme, Archiv mit erneutem Lesen in der Transaktion).
- **Dateischutz:** Umzug und Wiederherstellen enden mit `os.link` (überschreibt nie); alle
  Verbindungen mit `mode=rw` (keine stille leere Datenbank).
- **Datentypen:** feste Spaltentypen, Datum/Zeit als Text im heutigen Format, Nachbearbeitung auf
  heutige Typen, Rundlauf-Test mit Typprüfung.
- **Rückweg:** Export in die alten Formate nach `export/<Zeitstempel>/`.
- **Sicherung:** Start + täglich + vor Schema-Änderung; temp + `integrity_check` + Umbenennen;
  Wiederherstellen aus einer Auswahl geprüfter Sicherungen.
- **Netz:** nur lokal (`127.0.0.1` im Startbefehl, nicht in `config.toml`); Speicher-Aktionen nur
  über Loopback; DB-Werte entschärft anzeigen.
- **Tests:** `check()`-Stil, harter Schutz der echten `nola.db` über `NOLA_TEST`, PASS-Zahl darf
  nicht sinken.
- **Fehlerbehandlung** (aus der Selbstprüfung): keine verschluckten Schreibfehler mehr.

### Changes Made
- Alle oben genannten Punkte in die jeweiligen Abschnitte eingearbeitet; neue Abschnitte
  „Verbindungen“, „Fehlerbehandlung“, „Rückweg (Export)“; Tests von pytest-Annahme auf den
  vorhandenen `check()`-Stil korrigiert; Ziel um Mehrbenutzer am eigenen Rechner erweitert.

### Deferred / Parking Lot
- Zugriff aus dem Netz mit Zugangskennwort (verworfen zugunsten „nur lokal“; Entwurf der drei
  Schichten liegt im Stresstest-Verlauf, falls später gewünscht).
- Personen und Verlauf „wer hat was bestätigt“.
- Live-Aktualisierung.

### Confidence Assessment
- Overall: **Mittel bis hoch.** Die Speicherschicht ist gut abgegrenzt; das Risiko liegt im Umbau
  von `main()`/`_persist_workspace` in einer 7 800-Zeilen-Datei, die parallel auf
  `vergangene-starts` bearbeitet wird.
- Areas of concern: (1) Der Abgleich der Unterschiede muss jeden heutigen Schlüssel im
  `session_state` vollständig abdecken — fehlt einer, gehen dessen Änderungen beim nächsten
  Durchlauf verloren; der Regel-Test ist dafür die Absicherung. (2) Der Zeitbedarf, die >1 000
  bestehenden Prüfungen auf die Temp-Datenbank umzustellen.
