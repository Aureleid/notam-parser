# Folgepunkte lokale Datenbank — Umsetzungsplan

> **Für ausführende Agenten:** PFLICHT-SKILL: `beads-superpowers:subagent-driven-development`.
> Jede Aufgabe wird ein Bead (`bd create -t task --parent <epic-id>`).

**Ziel:** Die offenen Review-Folgepunkte des Datenbank-Umbaus (Beads `nola-a6c.1`–`.6`, `nola-o25`)
beheben oder begründet verwerfen, ohne Verhalten an anderer Stelle zu ändern.

**Grundlage:** Spec `.internal/specs/2026-10-08-lokale-datenbank-design.md`, ADR-0002, die Notizen der
genannten Beads (`bd show <id>`), Abschlussbericht `.internal/sdd/2026-10-08-lokale-datenbank/final-fix-report.md`.

**Entscheidungen des Benutzers (09.10.2026):**
1. Cloud (`is_public_deployment()`): Arbeitsstand **je Browser-Sitzung getrennt** und flüchtig;
   Referenzen und Archiv bleiben gemeinsam.
2. Automatisches Archiv-/Seestart-Fortschreiben wartet bei fremder Sperre nur **~0,5 s** und versucht es
   beim nächsten Durchlauf erneut; Klick-Aktionen behalten 5 s.
3. Meldungen aus dem Referenzdialog **nur im Dialog**, nicht zusätzlich auf der Hauptseite.
4. Alte Datei-Helfer: **nur wirklich Ungenutztes entfernen**; was Umzug/Export braucht, bleibt mit
   klarem Kommentar.

## Globale Vorgaben

- Zweig `folgepunkte` von `main` (2956269 + f0fdc37). Commit je Aufgabe erlaubt; Merge/Push nur auf Wort
  des Benutzers. Co-Authored-By aus der eigenen System-Attribution.
- NOLA nicht starten. Die echte `nola.db` im Projektordner existiert jetzt und darf nie berührt werden
  (Tests laufen unter `NOLA_TEST`, das sperrt sie).
- Tests: `.venv/bin/python test_nola_db.py` / `test_app.py`, Ausgangswerte **214** / **1436** PASS — dürfen
  nur sinken, wenn ein Test wegen einer entfernten Funktion bewusst entfällt (im Bericht mit Rechnung).
- TDD für jedes Verhaltens-Fix (RED zeigen). Monkeypatches im `finally` zurück. Nur `tempfile.mkdtemp()`.
- Kommentare deutsch ohne Umlaute, UI englisch. SQL nur mit Platzhaltern.
- „Begründet verwerfen“ ist erlaubt, wenn ein Punkt bei genauer Prüfung kein Defekt ist — mit Beleg.

---

### Task 1: Speicherschicht und Sicherung (Beads nola-a6c.1, nola-a6c.2)

**Files:** `nola_db.py`, `test_nola_db.py`

**Punkte:**
- `_uebersetze`: Fehler werden per Textsuche zugeordnet. Python 3.9 hat kein `sqlite_errorcode` → prüfen,
  ob `exc.args`/Klasse (`sqlite3.IntegrityError` → constraint, `OperationalError` + „locked“/„busy“) robuster
  ist; Zuordnung über Klasse zuerst, Text nur als Rest. Tests je Fehlerart (locked, constraint, disk full,
  corrupt, readonly).
- `zaehle`: Tabellenliste nicht doppelt pflegen — aus einer Konstante ableiten, die auch `_schema_sql` /
  `pruefe_sicherung` nutzen (eine Quelle). Test: jede Tabelle des Schemas ist zählbar.
- Sperrtest-Toleranz: Akzeptanz war „≤ 6 s“; Test so fassen, dass er die Sperrwartezeit (5 s) belegt, ohne
  wackelig zu werden (z. B. ≥ 4,5 s und ≤ 6,5 s, Begründung im Kommentar) — oder Akzeptanz begründet anpassen.
- Fehlende Tests: `setze_wal` (Modus `wal` danach), `setze_meta`/`lese_meta` Rundlauf und Überschreiben,
  explizites SQL-`NULL` → `NaN` in `lese_tabelle`.
- `sichere`: Fehlerpfad-Aufräumen testen (Backup-Fehler und `integrity_check`-Fehler → keine `.tmp`/Nebendateien).
- Zwei Sicherungen derselben Minute überschreiben sich: Zeitstempel mit Sekunden (`%H%M%S`); das Muster
  `_SICHERUNG` erkennt weiter alte Namen mit 4 Ziffern; Sortierung „neueste zuerst“ bleibt korrekt über beide
  Formate (Test mit gemischten Namen). `sicherung_faellig` unverändert gültig (Test).
- `behalten <= 0` → `ValueError`.
- `schuetze_echte_orte`: zusätzlich alles **unterhalb** des echten Sicherungsordners sperren und Pfade vor dem
  Vergleich auflösen (Symlinks). Test mit Unterordner und Symlink in einen Temp-Ordner, der per Monkeypatch als
  „echter“ Ordner gilt.

**Abnahme:** Jeder Punkt behoben oder begründet verworfen; Suite grün; echter Sicherungsordner unverändert.

### Task 2: Referenzen (Bead nola-a6c.3)

**Files:** `app.py`, `archiv_import.py`, `test_app.py`

**Punkte:**
- Entschärfung als **Verhaltenstest** statt Quelltextsuche: alle drei Editoren (`_spaceport_editor`,
  `_fir_editor`, `_vehicle_editor`) mit Fake-st aufrufen, einen DB-Wert mit `**x**` und Backtick einspeisen,
  prüfen, dass das Gezeichnete entschärft ist.
- Tests für die `ValueError`-Wache in `_write_reference` (Tabelle ohne `nola_stand`) und die `DbFehler`-Zweige in
  `_write_reference` und `_undo_reference` (Meldung im Dialog, Undo-Eintrag bleibt).
- Flash-Labels sind seit dem Abschlussreview über `_zeige_dialog_meldungen` entschärft → nur verifizieren
  (Test vorhanden?) und im Bericht belegen.
- `archiv_import.detection_stamp` fängt `Exception` breit → auf die erwartbaren Fehler (`nola_db.DbFehler`,
  `OSError`, `KeyError` für fehlendes `nola_stand`) einengen; Test: ein Programmierfehler (z. B. `TypeError` aus
  einem Monkeypatch) wird nicht verschluckt.
- `prepare_vehicles`: `astype(str)` macht aus `NaN` den Text `"nan"`, der beim Rückschreiben als Wert in der DB
  landet. Fix: leere Felder vor `astype(str)` zu `""` (gilt für CSV- und DB-Weg gleich). Prüfen, dass die Filter-
  regel (Zeilen ohne `Abkürzung`/`Name` fallen weg) dann richtig greift. Test mit einer Zeile mit leerem
  Alternativnamen: nach Hinzufügen/Rückschreiben steht in der DB `NULL`, nicht `"nan"`.

**Abnahme:** wie oben.

### Task 3: Arbeitsstand und Cloud je Sitzung (Bead nola-a6c.4 + Entscheidung 1)

**Files:** `app.py`, `test_app.py`, README/STATUS nur für Cloud-Satz (oder Task 5)

**Punkte:**
- `_add_manual_notams`: Eingabefeld (`manual_input`) **nur leeren, wenn gespeichert**. Schlägt das Speichern fehl
  (Konflikt oder `DbFehler`), bleibt der Text im Feld und die Meldung erscheint. Test mit Monkeypatch von
  `nola_db.schreibe_unterschiede` (wirft) → `manual_input` unverändert, keine neuen NOTAMs in der DB.
  Hinweis: Das Widget `manual_input` darf im Callback gesetzt werden (vorhandenes Muster prüfen).
- Konflikttest erweitern: nach dem Konflikt entspricht auch `confirmed_launches` im `session_state` dem DB-Stand.
- Testname „save_workspace wird benannt aufgerufen …“ an den Inhalt anpassen (Aussage unverändert).
- Testzustand in der gemeinsamen Temp-DB: die Abschnitte, die Aktionsfunktionen aufrufen, bekommen eine eigene
  Temp-DB (Helfer, der `app.DB_PATH` für den Abschnitt umbiegt und im `finally` zurücksetzt) — mindestens für die
  neuen und die Arbeitsstand-Abschnitte; oder begründen, warum der gemeinsame Zustand unschädlich ist.
- **Cloud je Sitzung (Entscheidung 1):** Unter `is_public_deployment()` lesen und schreiben `_arbeitsstand_laden`
  und `_persist_workspace` **nicht** die DB-Tabellen des Arbeitsstands, sondern einen flüchtigen Stand je Sitzung
  in `st.session_state` (beim ersten Durchlauf leer, über Durchläufe der Sitzung erhalten). Lokal unverändert.
  Folgen prüfen und im Bericht nennen: `_remove_archive_row`/`_remove_sea_launch_row` schreiben das (gemeinsame)
  Archiv, der Lösch-Schlüssel landet nur im Sitzungsstand — in der Cloud kann eine entfernte Zeile in einer anderen
  Sitzung wiederkommen; das ist hinzunehmen (Cloud-Archiv ist ohnehin flüchtig) und wird im README-Cloud-Absatz
  erwähnt. Tests: mit `is_public_deployment` → True zwei getrennte Fake-Sitzungen → eine Bestätigung in Sitzung A ist
  in Sitzung B nicht sichtbar, die DB-Tabelle `entscheidungen` bleibt unverändert; lokal (False) wie bisher.

**Abnahme:** wie oben.

### Task 4: Restpunkte Abschlussreview (Bead nola-a6c.6 + Entscheidungen 2, 3)

**Files:** `nola_db.py`, `app.py`, `archiv_import.py`, `test_app.py`, `test_nola_db.py`

**Punkte:**
- Archiv-Import-Zustand und Korpus ohne Standvergleich: `speichere_importzustand`/`speichere_korpus` bekommen wie
  `ersetze_tabelle` einen erwarteten Stand (Prüfsumme der beteiligten Tabellen, beim Laden mitgegeben, z. B. als
  Schlüssel im zurückgegebenen Zustand oder als zweiter Rückgabewert der Lade-Funktionen in `archiv_import`).
  Abweichung → `Konflikt` → im Import-Reiter `ImportStateError` mit „changed meanwhile … reload the tab“, nichts
  geschrieben. Tests: zwei Verbindungen, veralteter Stand → abgelehnt; Umzug (`erwartet=None`) weiter möglich.
- Entscheidung 2: automatisches Fortschreiben (`_update_archive`, `_update_sea_launches`) mit kurzer Wartezeit
  (~0,5 s): z. B. `verbinde(..., timeout=...)` / `busy_timeout`-Parameter für diese Aufrufe; Klick-Aktionen behalten
  5 s. Test: zweite Verbindung hält `BEGIN IMMEDIATE` → `_update_archive` kehrt in < 1,5 s mit Warnung zurück.
- Entscheidung 3: Meldungen aus dem Referenzdialog (`_melde_db_dialog`-Fälle) nicht zusätzlich als `db_meldung`
  auf der Hauptseite. Test: nach einer Dialog-Konfliktmeldung ist `db_meldung` nicht gesetzt.
- Projektplan-TREE: Knoten `test_nola_db.py` hat `s:13` → auf den passenden Schritt setzen (prüfen, ob 13 oder 14).

**Abnahme:** wie oben.

### Task 5: Aufräumen, Dialogfehler, Doku (Beads nola-a6c.5, nola-o25)

**Files:** `app.py`, `archiv_import.py`, `nola_umzug.py`, `test_app.py`, `README.md`, `STATUS.md`, `docs/projektplan.html`

**Punkte:**
- Entscheidung 4: für jeden alten Datei-Helfer (`archive_keys_or_reason`, `load_archive`, `load_sea_launches`,
  `persist_sea_launches`, `persist_archive`, `save_workspace`, `load_workspace`, `load_spaceports`, `load_firs`,
  `load_vehicles`, `persist_reference`, `ai.load_korpus`, `ai.save_korpus`, `ai.load_state`, `ai.save_state`,
  `read_archive_strict`) per `grep` feststellen, ob App, `nola_umzug` (Umzug/Export) oder `archiv_import` ihn
  brauchen. Wirklich ungenutzte entfernen (samt ihrer Tests — Rechnung im Bericht); gebrauchte bleiben mit einem
  Kommentar „nur fuer Umzug/Export“. Keine Verhaltensänderung an Umzug/Export (deren Tests bleiben grün).
- `nola-o25`: Referenzdialog bleibt nach X/Escape zu. Streamlit 1.50: `st.dialog(..., on_dismiss=<callback>)` —
  Callback setzt `ref_dialog_open = False`. Test: die Dekoration trägt den Callback (Signatur/Attribut), und der
  Callback setzt das Flag; Browser-Nachweis übernimmt der Controller.
- Doku: README (Cloud je Sitzung, kurze Wartezeit beim automatischen Fortschreiben, Sicherungsnamen mit Sekunden),
  STATUS (offene Punkte entfernen/ergänzen, Zahlen), Projektplan (neuer Schritt „Folgepunkte“, TREE-Namen,
  offene Punkte, Kopfzahlen „beide Läufe“). Artifact veröffentlicht der Controller.

**Abnahme:** wie oben; dazu `grep` belegt, dass keine entfernte Funktion mehr aufgerufen wird.
