# Vergangene Starts ausblenden — Umsetzungsplan

> **Für ausführende Agenten:** PFLICHT-SKILL: `beads-superpowers:subagent-driven-development`
> (empfohlen) oder `beads-superpowers:executing-plans`. Jede Aufgabe wird ein Bead
> (`bd create -t task --parent <epic-id>`). Schritte mit Checkboxen (`- [ ]`).

**Ziel:** Starts, deren spätestes Fenster mehr als 24 h vorbei ist und die im Startarchiv
stehen, verschwinden aus der Tageslage. Gelöscht wird nichts; ein Schalter holt sie zurück.

**Architektur:** Reine Funktionen in `app.py` (`past_launch_rows`, `event_expired`,
`archive_keys_or_reason`, `order_pasted_entries`) plus eine Einbindung in `main` direkt nach
`_update_archive`. Die vergangenen Zeilen fließen in die bestehende Filtermaske; alle Ansichten
folgen ihr bereits. Erkennung, Archivschreiben, Arbeitsstand und Archiv-Import bleiben unverändert.

**Technik:** Python 3, pandas, Streamlit (nur in `main`).

**Spec:** `.internal/specs/2026-10-08-vergangene-starts-design.md` (inkl. „Ergebnisse des
Gegentests"). Brainstorming-Bead: `nola-ff4`.

## Globale Vorgaben

- Gelöscht wird nichts. Arbeitsstand (`notam_workspace.json`, eingefügte NOTAMs), Archiv,
  Seestart-Protokoll und Referenzen werden durch diese Änderung nie geschrieben.
- „Vergangen" = Gruppe mit Startplatz und mindestens einer OK-Zone, spätestes Ende aller Meldungen
  (`row_indices` + `advance_row_indices`; `valid_to`, sonst `valid_from`) + `PAST_LAUNCH_GRACE`
  (24 h) < jetzt (UTC), und `archive_key(archive_row(g, events))` steht im Archiv.
- Ein Start mit Schlüssel in `st.session_state["archiv_removed"]` wird nie ausgeblendet und trägt
  den Hinweis „removed from archive".
- Archiv unlesbar (`ArchiveUnreadable`) → nichts ausblenden, Meldung in der Seitenleiste.
- Review-Fälle und Gruppen ohne Startplatz werden nie ausgeblendet; abgelaufene Review-Fälle
  tragen die Marke „expired".
- UI-Texte englisch, Code-Kommentare deutsch ohne Umlaute; kein `unsafe_allow_html` für neue
  Ausgaben.
- „Jetzt" wird übergeben (`now`), nie in den reinen Funktionen gelesen.
- Tests: `.venv/bin/python test_app.py` (eigener `check()`-Runner). Neuer Abschnitt
  `print("== Vergangene Starts ==")` direkt vor den Schlusszeilen `print()` /
  `print("ERGEBNIS:" ...)`. Funktionen über den Namen suchen, nie über Zeilennummern.
- Keine echten Datendateien in Tests schreiben (temporäre Pfade).
- Commits nur auf dem Feature-Branch `vergangene-starts`, eine je Aufgabe (vom Benutzer am
  08.10.2026 erlaubt). Merge und Push erst auf sein Wort. Commit-Zeile am Ende:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Dateien

| Datei | Änderung |
|---|---|
| `app.py` | Konstante `PAST_LAUNCH_GRACE`; Funktionen `latest_end`, `event_expired`, `past_launch_rows`, `archive_keys_or_reason`, `order_pasted_entries`; Spalte „Archiv" in `groups_to_dataframe`; Einbindung in `main` |
| `test_app.py` | Abschnitt `== Vergangene Starts ==` |
| `STATUS.md`, `docs/projektplan.html` | Doku laut `CLAUDE.md` |

---

### Aufgabe 1: Regel als reine Funktionen

**Dateien:** Ändern: `app.py` (neue Funktionen direkt nach `archive_key`), `test_app.py`.

**Schnittstellen:**
- Liefert:
  - `PAST_LAUNCH_GRACE: timedelta` = 24 h
  - `latest_end(events: Sequence[LaunchEvent]) -> Optional[datetime]`
  - `event_expired(event: LaunchEvent, now: datetime, karenz: timedelta = PAST_LAUNCH_GRACE) -> bool`
  - `past_launch_rows(groups, events, archiv_keys: Set[str], now: datetime, karenz: timedelta = PAST_LAUNCH_GRACE, entfernt: Optional[Set[str]] = None) -> Set[int]`
  - `archive_keys_or_reason(path: Path) -> Tuple[Optional[Set[str]], str]` (`None` + englische
    Begründung, wenn das Archiv unlesbar ist; leere Menge bei fehlender Datei)

**Abnahmekriterien:**
- Fensterende 25 h zurück und archiviert → Zeilen der Gruppe (inkl. Vorankündigung) im Ergebnis.
- Fensterende 23 h zurück → nicht im Ergebnis.
- Ohne `valid_to` zählt `valid_from`; ohne beide Zeiten → nie im Ergebnis.
- Nicht im Archiv oder Schlüssel in `entfernt` → nicht im Ergebnis.
- Gruppe ohne Startplatz oder ohne OK-Zone → nie im Ergebnis.
- Endet die Vorankündigung später als der Start, zählt ihr Ende.
- Zeiten ohne Zeitzone gelten als UTC.
- `archive_keys_or_reason`: fehlende Datei → `(set(), "")`; unlesbare Datei → `(None, <Grund>)`;
  echtes Archiv (Kopie in `/tmp`) → Menge mit so vielen Schlüsseln wie Zeilen.

- [ ] **Schritt 1: Fehlschlagende Tests** (Abschnitt `== Vergangene Starts ==`)

```python
print("== Vergangene Starts ==")
from datetime import datetime as _dt, timedelta as _td, timezone as _tz
import tempfile as _tf, shutil as _sh
from pathlib import Path as _Pv

_jetzt = _dt(2026, 10, 8, 12, 0, tzinfo=_tz.utc)
def _ev(row, von, bis, status="OK"):
    return app.LaunchEvent(row_index=row, notam_id="A{:04d}/26".format(row), raw_text="x",
                           valid_from=von, valid_to=bis, status=status)
def _grp(rows, advance=(), platz="JSLC"):
    return app.LaunchGroup(group_id="G", notam_ids=["A{:04d}/26".format(r) for r in rows],
                           row_indices=list(rows), advance_row_indices=list(advance),
                           spaceport_code=platz,
                           window_from=_jetzt - _td(days=3), window_to=_jetzt - _td(days=3))
def _schluessel(g, evs):
    return {app.archive_key(app.archive_row(g, evs))}

alt = _jetzt - _td(hours=25)
e1 = [_ev(0, alt - _td(minutes=20), alt)]
g1 = _grp([0])
check("25 h vorbei und archiviert -> vergangen",
      app.past_launch_rows([g1], e1, _schluessel(g1, e1), _jetzt) == {0})
e2 = [_ev(0, _jetzt - _td(hours=23, minutes=20), _jetzt - _td(hours=23))]
check("23 h vorbei -> sichtbar", app.past_launch_rows([g1], e2, _schluessel(g1, e2), _jetzt) == set())
e3 = [_ev(0, alt, None)]
check("ohne valid_to zaehlt valid_from", app.past_launch_rows([g1], e3, _schluessel(g1, e3), _jetzt) == {0})
e4 = [_ev(0, None, None)]
check("ohne Zeiten nie vergangen", app.past_launch_rows([g1], e4, _schluessel(g1, e4), _jetzt) == set())
check("nicht im Archiv -> sichtbar", app.past_launch_rows([g1], e1, set(), _jetzt) == set())
check("im Archiv-Editor entfernt -> sichtbar",
      app.past_launch_rows([g1], e1, _schluessel(g1, e1), _jetzt, entfernt=_schluessel(g1, e1)) == set())
g_ohne = _grp([0], platz=None)
check("ohne Startplatz nie vergangen", app.past_launch_rows([g_ohne], e1, _schluessel(g_ohne, e1), _jetzt) == set())
e_rev = [_ev(0, alt - _td(minutes=20), alt, status="REVIEW")]
check("ohne OK-Zone nie vergangen", app.past_launch_rows([g1], e_rev, _schluessel(g1, e_rev), _jetzt) == set())
g_vor = _grp([0], advance=[1])
e_vor = e1 + [_ev(1, alt - _td(days=3), _jetzt - _td(hours=2))]
check("Vorankuendigung endet spaeter -> ihr Ende zaehlt",
      app.past_launch_rows([g_vor], e_vor, _schluessel(g_vor, e_vor), _jetzt) == set())
e_vor2 = e1 + [_ev(1, alt - _td(days=3), alt - _td(hours=1))]
check("Vorankuendigung verschwindet mit ihrem Start",
      app.past_launch_rows([g_vor], e_vor2, _schluessel(g_vor, e_vor2), _jetzt) == {0, 1})
e_naiv = [_ev(0, (alt - _td(minutes=20)).replace(tzinfo=None), alt.replace(tzinfo=None))]
check("naive Zeiten gelten als UTC", app.past_launch_rows([g1], e_naiv, _schluessel(g1, e_naiv), _jetzt) == {0})
check("event_expired: abgelaufener Review-Fall",
      app.event_expired(_ev(5, alt - _td(minutes=5), alt, status="REVIEW"), _jetzt))
check("event_expired: laufender Fall nicht",
      not app.event_expired(_ev(5, _jetzt, _jetzt + _td(hours=1)), _jetzt))

_dv = _Pv(_tf.mkdtemp())
check("Archiv fehlt -> leere Menge", app.archive_keys_or_reason(_dv / "fehlt.csv") == (set(), ""))
(_dv / "kaputt.csv").write_bytes(b"\x00\x00\x00")
_k, _grund = app.archive_keys_or_reason(_dv / "kaputt.csv")
check("Archiv unlesbar -> None mit Grund", _k is None and "kaputt.csv" in _grund, _grund)
if app.ARCHIVE_CSV.exists():
    _sh.copy(app.ARCHIVE_CSV, _dv / "echt.csv")
    _k2, _ = app.archive_keys_or_reason(_dv / "echt.csv")
    check("echtes Archiv -> ein Schluessel je Zeile",
          _k2 is not None and len(_k2) == len(app.read_archive_strict(_dv / "echt.csv")))
```

- [ ] **Schritt 2:** `.venv/bin/python test_app.py 2>&1 | tail -3` → `AttributeError: … past_launch_rows`.

- [ ] **Schritt 3: Implementierung** (in `app.py` direkt nach `archive_key`)

```python
#: Karenz, bevor ein abgelaufener Start die Tageslage verlaesst. 24 Stunden:
#: ein Start von heute frueh bleibt bis morgen sichtbar, und ein verschobener
#: Start mit neuem NOTAM taucht nicht kurz auf und wieder ab.
PAST_LAUNCH_GRACE = timedelta(hours=24)


def _als_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def latest_end(events: Sequence["LaunchEvent"]) -> Optional[datetime]:
    """Spaetestes Ende der Meldungen: valid_to, ersatzweise valid_from (UTC)."""
    enden = [
        _als_utc(e.valid_to or e.valid_from)
        for e in events
        if (e.valid_to or e.valid_from) is not None
    ]
    return max(enden) if enden else None


def event_expired(
    event: "LaunchEvent", now: datetime, karenz: timedelta = PAST_LAUNCH_GRACE
) -> bool:
    """Ist die Meldung laenger als die Karenz abgelaufen? Ohne Zeiten nie."""
    ende = latest_end([event])
    return ende is not None and ende + karenz < _als_utc(now)


def past_launch_rows(
    groups: Sequence["LaunchGroup"],
    events: Sequence["LaunchEvent"],
    archiv_keys: Set[str],
    now: datetime,
    karenz: timedelta = PAST_LAUNCH_GRACE,
    entfernt: Optional[Set[str]] = None,
) -> Set[int]:
    """
    Tabellenzeilen vergangener Starts.

    Vergangen ist ein Start nur, wenn er archiviert ist (derselbe Schluessel,
    den _update_archive schreibt) und sein spaetestes Fenster - Zonen und
    angehaengte Vorankuendigungen - laenger als die Karenz vorbei ist. Review-
    Faelle, Starts ohne Platz und im Archiv-Editor entfernte Starts bleiben
    sichtbar: ausgeblendet wird nur, was nachweislich im Archiv steht.
    """
    entfernt = entfernt or set()
    per_row = {e.row_index: e for e in events}
    vergangen: Set[int] = set()
    for g in groups:
        if not g.spaceport_code:
            continue
        zonen = [per_row[r] for r in g.row_indices if r in per_row]
        if not any(e.status == "OK" for e in zonen):
            continue
        zeilen = list(g.row_indices) + list(g.advance_row_indices)
        ende = latest_end([per_row[r] for r in zeilen if r in per_row])
        if ende is None or ende + karenz >= _als_utc(now):
            continue
        schluessel = archive_key(archive_row(g, events))
        if schluessel not in archiv_keys or schluessel in entfernt:
            continue
        vergangen.update(zeilen)
    return vergangen


def archive_keys_or_reason(path: Path) -> Tuple[Optional[Set[str]], str]:
    """Schluessel des Archivs; bei unlesbarer Datei None und der Grund."""
    try:
        bestand = read_archive_strict(path)
    except ArchiveUnreadable as exc:
        return None, str(exc)
    return {archive_key(dict(r)) for _, r in bestand.iterrows()}, ""
```

`app.py` importiert bisher nur `from datetime import datetime, timezone`: auf
`from datetime import datetime, timedelta, timezone` erweitern. `archive_row` ist vor `archive_key`
definiert, die Platzierung direkt nach `archive_key` passt. Der Plancode dieser Aufgabe wurde am
08.10.2026 im Speicher gegen das echte `app.py` geprüft: alle 16 Prüfungen bestanden.

- [ ] **Schritt 4:** Volle Suite → nur `ERGEBNIS: ALLE TESTS BESTANDEN`.
- [ ] **Schritt 5:** Commit (siehe Globale Vorgaben), Betreff „Vergangene Starts: Regel als reine Funktionen".

---

### Aufgabe 2: Einbindung in die Oberfläche

**Dateien:** Ändern: `app.py` (`groups_to_dataframe`, `main`), `test_app.py`.

**Schnittstellen:**
- Nutzt: alles aus Aufgabe 1.
- Liefert:
  - `groups_to_dataframe(groups, vehicles=None, archiv_hinweis: Optional[Dict[str, str]] = None)` —
    neue letzte Spalte „Archiv" (`"past"`, `"removed from archive"` oder `"-"`, je `group_id`).
  - `order_pasted_entries(n: int, offset: int, past_rows: Set[int]) -> List[Tuple[int, bool]]`
    — Indizes der eingefügten Einträge mit Vergangen-Flag; nicht vergangene zuerst, jeweils in
    ursprünglicher Reihenfolge.
  - `_render_pasted_entries(slot, items, flags: Optional[List[Tuple[int, bool]]] = None) -> None`
    — zeichnet „Pasted entries" in den Platzhalter; ohne `flags` unmarkiert in ursprünglicher
    Reihenfolge (wie bisher).

**Abnahmekriterien:**
- In `main` steht die Berechnung direkt nach `_update_archive(...)` und vor dem Filterabschnitt.
- Schalter „Show past launches" (Seitenleiste, Abschnitt „Filter", Vorgabe aus, kein Speichern im
  Arbeitsstand). Ist er aus, werden die Zeilen aus `past_rows` per Maske entfernt; der Datumsfilter
  bildet seinen Bereich nur aus den nicht ausgeblendeten Zeilen.
- Hinweis „N past launch(es) hidden – in the launch archive" nur, wenn N > 0 und der Schalter aus
  ist. Bei unlesbarem Archiv stattdessen „Past launches are not hidden: …" mit dem Grund (als
  reiner Text).
- Launch Overview: Spalte „Archiv" zeigt „past" für vergangene (bei eingeschaltetem Schalter
  sichtbare) und „removed from archive" für Starts mit Schlüssel in `archiv_removed`.
- Review: Abgelaufene Fälle (`event_expired`) tragen „expired · " vor dem Expander-Titel und in einer
  Tabellenspalte „Expired" (yes/-).
- „Pasted entries": Einträge vergangener Starts mit „(past)" markiert und ans Ende sortiert;
  Überschrift „Pasted entries (N · M past)" bzw. „(N)" ohne vergangene. Umgesetzt mit einem
  Platzhalter (`st.sidebar.container()` an der bisherigen Stelle), der nach der Berechnung gefüllt
  wird. `_remove_manual` bekommt weiter den ursprünglichen Index.
- Die Liste wird nicht im Arbeitsstand umsortiert (`manual_notams` bleibt unverändert).
- Die Liste verschwindet nie: Beim Upload-Fehler wird sie direkt vor `st.stop()` unmarkiert
  gezeichnet. Läuft die Berechnung der vergangenen Starts auf einen unerwarteten Fehler, wird sie
  unmarkiert gezeichnet und der Fehler weitergereicht (nicht verschluckt).

- [ ] **Schritt 1: Fehlschlagende Tests**

```python
_t = app.groups_to_dataframe([g1], None, {"G": "past"})
check("Overview: Spalte Archiv", "Archiv" in _t.columns and _t.iloc[0]["Archiv"] == "past")
check("Overview: ohne Hinweis '-'", app.groups_to_dataframe([g1])["Archiv"].iloc[0] == "-")
check("Pasted: nicht vergangene zuerst, Reihenfolge stabil",
      app.order_pasted_entries(4, 10, {11, 13}) == [(0, False), (2, False), (1, True), (3, True)])
check("Pasted: ohne Datei-Offset", app.order_pasted_entries(2, 0, {0}) == [(1, False), (0, True)])
import inspect as _ins
_main = _ins.getsource(app.main)
check("Berechnung nach _update_archive",
      _main.index("_update_archive(") < _main.index("past_launch_rows("))
check("Berechnung vor dem Filterabschnitt",
      _main.index("past_launch_rows(") < _main.index('st.header("Filter")'))
check("Schalter Show past launches vorhanden", '"Show past launches"' in _main)
check("Arbeitsstand wird dabei nicht geschrieben",
      "_persist_workspace" not in _main[_main.index("past_launch_rows("):_main.index('st.header("Filter")')])
check("Review markiert abgelaufene Faelle", "event_expired(" in _main and '"expired · "' in _main)
_stop = _main.index("Could not read the upload")
check("Upload-Fehler zeichnet die Liste vor st.stop()",
      "_render_pasted_entries(" in _main[_stop:_main.index("st.stop()", _stop)])
check("Liste wird auch bei Fehler in der Berechnung gezeichnet",
      _main.count("_render_pasted_entries(") >= 3)
```

- [ ] **Schritt 2:** Suite → FAIL (`Archiv` fehlt, `order_pasted_entries` fehlt).

- [ ] **Schritt 3: Implementierung**

`groups_to_dataframe`: Parameter `archiv_hinweis: Optional[Dict[str, str]] = None` ergänzen, im
Datensatz `"Archiv": (archiv_hinweis or {}).get(g.group_id, "-")`, in `columns` „Archiv" als
letzte Spalte.

`order_pasted_entries` (neben `manual_entries_to_dataframe`):

```python
def order_pasted_entries(
    n: int, offset: int, past_rows: Set[int]
) -> List[Tuple[int, bool]]:
    """
    Reihenfolge der eingefuegten Eintraege in der Seitenleiste.

    Eintrag i liegt in Tabellenzeile offset + i (combine_sources haengt die
    eingefuegten Eintraege hinter die Datei). Vergangene ans Ende, sonst bleibt
    die Reihenfolge - der Arbeitsstand selbst wird nicht umsortiert.
    """
    paare = [(i, (offset + i) in past_rows) for i in range(n)]
    return [p for p in paare if not p[1]] + [p for p in paare if p[1]]
```

In `main`:
1. Seitenleiste, an der Stelle der bisherigen „Pasted entries"-Ausgabe: statt des Expanders nur
   `pasted_slot = st.container()` anlegen (der Knopf „Discard all pasted entries" bleibt, wo er ist).
2. Nach `_update_archive(...)` / `_update_sea_launches(...)`:

```python
    # Vergangene Starts: erst jetzt, das Archiv ist geschrieben. Ausgeblendet
    # wird nur Archiviertes; geloescht wird nichts.
    archiv_keys, archiv_grund = archive_keys_or_reason(ARCHIVE_CSV)
    entfernt = set(st.session_state.get("archiv_removed", set()))
    jetzt = datetime.now(timezone.utc)
    past_rows = (
        past_launch_rows(stats.get("groups", []), events, archiv_keys, jetzt, entfernt=entfernt)
        if archiv_keys is not None
        else set()
    )
    past_groups = {
        g.group_id for g in stats.get("groups", []) if set(g.row_indices) & past_rows
    }
    archiv_hinweis = {gid: "past" for gid in past_groups}
    for g in stats.get("groups", []):
        if g.spaceport_code and archive_key(archive_row(g, events)) in entfernt:
            archiv_hinweis[g.group_id] = "removed from archive"
```

3. Pasted-Liste über `_render_pasted_entries(pasted_slot, manual_items, flags)` zeichnen
   (Offset = Zeilen der Datei: `len(imported)`, wenn vorhanden und nicht leer, sonst 0;
   `flags = order_pasted_entries(...)`). Titel mit Zählung, „ (past)" im Caption-Text, „Remove"
   mit ursprünglichem Index `i` und Key `del_manual_{i}` wie bisher. Die Berechnung aus Punkt 2
   samt diesem Aufruf steht in `try`; im `except Exception` zuerst
   `_render_pasted_entries(pasted_slot, manual_items)` (unmarkiert), dann `raise`. Im Upload-
   Fehlerzweig vor `st.stop()` ebenfalls `_render_pasted_entries(pasted_slot, manual_items)`.
4. Im Filterabschnitt: `show_past = st.toggle("Show past launches", value=False)`; Hinweistext
   (`st.caption` mit Zahl bzw. `st.text` mit `archiv_grund`). `valid_dates` nur aus Zeilen, deren
   `_row` nicht in `past_rows` liegt, wenn `show_past` aus ist.
5. Maske: `if not show_past: mask &= ~table["_row"].astype(int).isin(past_rows)`.
6. `group_table = groups_to_dataframe(visible_groups, vehicles, archiv_hinweis)`.
7. Review: `abgelaufen = {e.key for e in review_events if event_expired(e, jetzt)}`; Expander-Titel
   `("expired · " if event.key in abgelaufen else "") + …`; Spalte „Expired" in `review_table`
   (`"yes"`/`"-"`), in die angezeigte Spaltenliste aufnehmen.

- [ ] **Schritt 4:** Suite grün, `.venv/bin/python -c "import app"` ohne neue Warnungen.
- [ ] **Schritt 5:** In der App prüfen (Controller, Vorschau-Werkzeuge): Archiv, Arbeitsstand und
  Seestart-Protokoll vorher sichern und danach vergleichen. Mit dem echten Arbeitsstand
  (15 eingefügte Meldungen, Seestarts vom Februar) müssen die Februar-Starts verschwinden. Der
  Schalter muss sie zurückholen, und „Pasted entries" muss „(past)" zeigen. Bildschirmfoto als
  Nachweis.
- [ ] **Schritt 6:** Commit, Betreff „Vergangene Starts: Ansicht, Schalter, Markierungen".

---

### Aufgabe 3: Echtbestand-Test und Dokumentation

**Dateien:** Ändern: `test_app.py`, `STATUS.md`, `docs/projektplan.html`. Artifact veröffentlicht
der Controller.

**Abnahmekriterien:**
- Echtbestand-Test mit der FNS-Datei (falls vorhanden, sonst mit „SKIP" gekennzeichnet):
  - Mit einem `now` 30 Tage nach dem spätesten Fenster und allen Archiv-Schlüsseln der eigenen
    Gruppen ist jede archivierbare Gruppe vergangen (Anzahl > 0).
  - Mit einem `now` vor dem frühesten Fenster ist keine vergangen.
- `STATUS.md`: Tabellenzeile „Vergangene Starts" (Regel, 24 h, nur Archiviertes, Schalter, nichts
  gelöscht), Kopfzeile (Zeilen, Tests), offener Punkt „Discard pasted entries of past launches".
- `docs/projektplan.html`: neuer Schritt in `STEPS`; Ast unter „Bedienoberfläche" mit
  `f:"past_launch_rows, event_expired, archive_keys_or_reason, order_pasted_entries"`; offener
  Punkt; Kopfzahlen wie `STATUS.md`; Skript geprüft (`osascript -l JavaScript` oder `node --check`).

- [ ] **Schritt 1: Test**

```python
import glob as _gv
_fns_v = sorted(_gv.glob(str(_Pv(app.APP_DIR) / "fnsNotams_*.xls")))
if _fns_v:
    _df_v = app.read_notam_table(_fns_v[-1], _fns_v[-1])
    _ev_v, _st_v = app.analyze_notams(_df_v, sp, fir, min_confidence="MEDIUM")
    _gr_v = [g for g in _st_v["groups"] if g.spaceport_code]
    _keys_v = {app.archive_key(app.archive_row(g, _ev_v)) for g in _gr_v}
    _enden = [app.latest_end([e for e in _ev_v if e.row_index in g.row_indices]) for g in _gr_v]
    _enden = [x for x in _enden if x is not None]
    _spaet = max(_enden) + _td(days=30)
    _frueh = min(_enden) - _td(days=30)
    _alle = app.past_launch_rows(_st_v["groups"], _ev_v, _keys_v, _spaet)
    check("Echtbestand: spaeter Zeitpunkt -> archivierte Starts vergangen", len(_alle) > 0, len(_alle))
    check("Echtbestand: frueher Zeitpunkt -> nichts vergangen",
          app.past_launch_rows(_st_v["groups"], _ev_v, _keys_v, _frueh) == set())
else:
    print("  SKIP  Echtbestand vergangene Starts (keine FNS-Datei)")
```

- [ ] **Schritt 2:** Suite grün; Zahlen notieren (`wc -l app.py test_app.py`, `grep -c PASS`).
- [ ] **Schritt 3:** `STATUS.md` und `docs/projektplan.html` wie in den Abnahmekriterien.
- [ ] **Schritt 4:** Commit, Betreff „Vergangene Starts: Echtbestand-Test und Doku".

---

## Abdeckung der Spec

| Spec-Anforderung | Aufgabe |
|---|---|
| Regel (Startplatz, OK-Zone, spätestes Ende inkl. Vorankündigung, Karenz, im Archiv) | 1 |
| `PAST_LAUNCH_GRACE` 24 h, kein Regler | 1 |
| Schlüssel wie `_update_archive` | 1 |
| Unlesbares Archiv → nichts ausblenden, Meldung | 1, 2 |
| Einbindung nach `_update_archive`, Maske, Datumsfilter | 2 |
| Schalter „Show past launches", nicht gespeichert, Hinweis mit Zahl | 2 |
| Kennzeichnung „past" in der Launch Overview | 2 |
| „removed from archive" für `archiv_removed` | 1, 2 |
| „expired" im Review | 1, 2 |
| „Pasted entries": „(past)", Sortierung, getrennte Zählung, nichts gelöscht | 2 |
| Erkennung, Archiv, Arbeitsstand, Import unverändert | 2 (Quelltextprüfung) |
| NOTAMR-Fall (dokumentiert, keine Sonderlogik) | 3 (STATUS) |
| Echtbestand-Test | 3 |
| Projektplan, `STATUS.md`, offener Punkt Aufräum-Knopf, Artifact | 3 (+ Controller) |

## Ergebnisse des Gegentests (Plan)

Durchgeführt am 08.10.2026, 2 von 2 Punkten gelöst, beide wie empfohlen angenommen.

- **Liste „Pasted entries" darf nie verschwinden:** Der Platzhalter würde bei `st.stop()` (Upload-
  Fehler) oder einem Fehler in der Berechnung leer bleiben. Abhilfe: `_render_pasted_entries` an
  drei Stellen (Normalfall markiert, Upload-Fehler und Fehlerfall unmarkiert), Fehler werden
  weitergereicht. Tests ergänzt (Aufgabe 2).
- **Commits:** Feature-Branch `vergangene-starts`, ein Commit je Aufgabe; Merge und Push nur auf
  Wort des Benutzers.
- **Selbstprüfung, ohne Änderung:** Eine offene Seite rechnet erst bei Interaktion neu, wie alle
  Ansichten. Die Kennzahlen folgen `visible_groups`. Ein zusätzlicher Archiv-Lesevorgang je Lauf
  fällt nicht ins Gewicht.
- **Einschätzung:** hoch.
