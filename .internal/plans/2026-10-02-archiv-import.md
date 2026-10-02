# Archiv-Import historischer NOTAMs: Umsetzungsplan

> **Für ausführende Agenten:** PFLICHT-SKILL: `beads-superpowers:subagent-driven-development`
> (empfohlen) oder `beads-superpowers:executing-plans`. Jede Aufgabe wird ein Bead
> (`bd create -t task --parent <epic-id>`). Die Schritte nutzen Checkboxen (`- [ ]`).
> Hinweis: `bd` ist auf diesem Rechner derzeit **nicht installiert**. Vor der Ausführung
> installieren oder die Aufgaben in diesem Dokument abhaken.

**Ziel:** Die Starts von China, Russland, Indien, Iran und Nordkorea aus 2020–2026 kommen ins
Startarchiv. Dazu werden gespeicherte NSF-Forenseiten stapelweise eingespielt, mit derselben
Erkennung wie im Tagesbetrieb ausgewertet und mit GCAT-Vorschlägen für Rakete und Payload zur
Bestätigung vorgelegt.

**Architektur:** Die reine Logik steht im neuen Modul `archiv_import.py` ohne Streamlit.
Es importiert `app` und baut nichts nach: `analyze_notams`, `archive_row`, `archive_key`,
`merge_archive`. In `app.py` kommen nur ein Reiter im Optionsmenü und eine Erkennung der
öffentlichen Fassung hinzu. Der Zustand liegt in zwei lokalen JSON-Dateien neben dem Archiv.

**Technik:** Python 3, pandas, Standardbibliothek (`html.parser`, `urllib.request`, `json`),
Streamlit nur im Reiter.

**Spec:** `.internal/specs/2026-10-02-archiv-import-design.md`

## Globale Vorgaben

- Nationen im Import: `("China", "Russland", "Indien", "Iran", "Nordkorea")`. Die USA werden
  **nach** der Erkennung verworfen und gezählt. Die Erkennung selbst kennt weiter alle sechs.
- Für den Import gibt es keine eigenen Erkennungsregeln. `analyze_notams` wird mit
  `min_confidence="MEDIUM"` aufgerufen.
- Aus GCAT werden nur Rakete und Payload übernommen, nie Inklination, Azimut oder Nation.
- Ins Archiv wird nur nach Bestätigung geschrieben. Der Spaltensatz `ARCHIVE_COLUMNS` bleibt
  unverändert.
- Grenzwerte: 5 MB je Datei, 200 MB je Stapel, höchstens 14 Tagesbündel je NOTAM,
  ±30 min Spielraum beim Abgleich, Abweichungsschwelle 10°.
- Netzzugriff nur auf `https://planet4589.org/space/gcat/tsv/launch/launch.tsv`.
- Forentext erscheint nie über `unsafe_allow_html`.
- Lokale Dateien in `.gitignore`: `archiv_korpus.json`, `archiv_import.json`,
  `gcat_launch_cache.tsv`.
- UI-Beschriftungen auf Englisch, Code-Kommentare auf Deutsch, wie im Rest von `app.py`.
- **Kein Commit**, solange der Benutzer es nicht verlangt (`CLAUDE.md`). Wo eine
  Aufgabe sonst committen würde, steht „Stand prüfen".
- `app.py` und `test_app.py` werden parallel weiterentwickelt. Funktionen deshalb über den
  Namen suchen, nie über Zeilennummern.
- Tests: `.venv/bin/python test_app.py` (eigener `check()`-Runner). Alle neuen Prüfungen
  kommen in einen neuen Abschnitt `== Archiv-Import ==` **direkt vor** der Schlusszeile
  `print("ERGEBNIS:" ...)`.

## Dateien

| Datei | Aufgabe |
|---|---|
| `archiv_import.py` (neu) | Extraktion, Korpus, Tagesbündel, Tagesanalyse, GCAT, Abgleich, Importzustand |
| `gcat_startplaetze.csv` (neu) | Referenz: GCAT-Startplatzcode → NOLA-Kürzel und Land |
| `app.py` | `is_public_deployment`, Reiter `_archive_import_tab`, Eintrag in `_reference_dialog` |
| `test_app.py` | Abschnitt `== Archiv-Import ==` |
| `.gitignore` | drei lokale Dateien |
| `docs/projektplan.html`, `STATUS.md`, `README.md`, Artifact | Doku laut `CLAUDE.md` |

---

### Aufgabe 1: Modulgerüst und Extraktion von NOTAM-Blöcken

**Dateien:**
- Neu: `archiv_import.py`
- Ändern: `test_app.py` (neuer Abschnitt vor `print("ERGEBNIS:"`)

**Schnittstellen:**
- Nutzt: `app.normalize_pasted_text`, `app.RE_PASTE_BOUNDARY`, `app.extract_items`,
  `app.parse_notam_datetime`
- Liefert:
  - `KorpusNotam(notam_id: str, b: str, text: str, quellen: List[str])` mit Eigenschaft
    `schluessel -> str` (`"<id>|<b>"`)
  - `cut_block(chunk: str) -> str`
  - `extract_notams(text: str, quelle: str) -> Tuple[List[KorpusNotam], int]`
    (zweiter Wert: Anzahl nicht verwertbarer Blöcke)
  - `texts_from_upload(name: str, data: bytes) -> List[Tuple[str, str]]`
    (Paare aus Quelle und Text, je Beitrag eins)
  - Konstanten wie unten

**Abnahmekriterien:**
- Ein Kommentar unter `G)` gehört nicht zum Block, auch ohne Leerzeile dazwischen.
- Bei Blöcken nur mit `E)` endet der Block an der ersten Leerzeile.
- Blöcke ohne `E)`/`Q)` oder ohne lesbares `B)` werden als nicht verwertbar gezählt.
- Vortext vor der ersten Kennung zählt nicht als Block.
- HTML wird beitragsweise gelesen, Zitatblöcke und `script`/`style` werden verworfen.
- Dateien über 5 MB werden mit `ValueError` abgelehnt.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben** (in `test_app.py` vor `print("ERGEBNIS:"`)

```python
print("== Archiv-Import ==")
import archiv_import as ai

AI_CN = CN  # A0611/26, A4631/26, A4632/26 aus Abschnitt 22
blk = ai.cut_block(AI_CN[1] + "\nprobably Starship from Boca Chica, see post above")
check("Kommentar unter G) gehoert nicht zum Block", "STARSHIP" not in blk.upper(), blk[-60:])
check("  ... der Block endet mit G)UNL", blk.rstrip().endswith("G)UNL"), blk[-20:])
nur_e = "Z1111/26 NOTAMN\nB) 2609200354 C) 2609200415\nE) DANGER AREA 3948N10002E\n\nnice launch!"
check("nur E): Ende an der Leerzeile", "nice" not in ai.cut_block(nur_e))

forum = "Hier die NOTAMs fuer morgen:\n\n" + "\n\n".join(AI_CN) + "\n\n" \
        "B9999/26 hat keinen Inhalt\n"
gef, unbr = ai.extract_notams(forum, "test.txt")
check("drei NOTAMs aus Forentext", [n.notam_id for n in gef] == ["A0611/26", "A4631/26", "A4632/26"],
      [n.notam_id for n in gef])
check("  ... B-Rohwert gemerkt", gef[1].b == "2609200354", gef[1].b)
check("  ... Quelle gemerkt", gef[0].quellen == ["test.txt"], gef[0].quellen)
check("  ... Block ohne E)/Q) als nicht verwertbar gezaehlt", unbr == 1, unbr)
check("Schluessel = Kennung|B", gef[1].schluessel == "A4631/26|2609200354", gef[1].schluessel)

SMF = """<html><head><script>var x = "A7777/26 Q) X E) Y";</script></head><body>
<div class="post_wrapper"><div class="inner" data-msgid="101" id="msg_101">
Two NOTAMs:<br>""" + AI_CN[1].replace("\n", "<br>\n") + """<br>""" + AI_CN[2].replace("\n", "<br>\n") + """
</div></div>
<div class="post_wrapper"><div class="inner" id="msg_102">
<blockquote class="bbc_standard_quote">""" + AI_CN[1].replace("\n", "<br>\n") + """</blockquote>
Looks like CZ-2D from Jiuquan.</div></div></body></html>"""
teile = ai.texts_from_upload("thread_p1.html", SMF.encode("utf-8"))
check("HTML: je Beitrag ein Text", [q for q, _ in teile] == ["thread_p1.html#msg_101", "thread_p1.html#msg_102"],
      [q for q, _ in teile])
check("HTML: Zitat verworfen", "A4631/26" not in teile[1][1], teile[1][1][:80])
check("HTML: Skript verworfen", all("A7777/26" not in t for _, t in teile))
check("HTML: Zeilenumbrueche aus <br>", "\nE)" in teile[0][1] or "\nE) " in teile[0][1])
try:
    ai.texts_from_upload("gross.txt", b"x" * (ai.MAX_FILE_BYTES + 1))
    check("Datei ueber 5 MB abgelehnt", False)
except ValueError:
    check("Datei ueber 5 MB abgelehnt", True)
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python test_app.py 2>&1 | tail -5`
Erwartet: `ModuleNotFoundError: No module named 'archiv_import'`

- [ ] **Schritt 3: `archiv_import.py` anlegen**

```python
"""
Archiv-Import historischer NOTAMs.

Spec: .internal/specs/2026-10-02-archiv-import-design.md

Reine Logik ohne Streamlit. Erkannt wird mit genau der Pipeline des
Tagesbetriebs (app.analyze_notams); dieses Modul liefert nur, was der
Tagesbetrieb nicht braucht: NOTAMs aus Forenseiten loesen, nach Tagen
buendeln, mit der GCAT-Startliste abgleichen und den Stand der Bestaetigung
fuehren. Die Tageslage (manuelle NOTAMs, notam_workspace.json) wird nie
beruehrt.

Unter Streamlit laeuft app.py als __main__; `import app` laedt dann eine
zweite Modulkopie. Das ist unschaedlich, solange hier nur reine Funktionen und
Konstanten daraus genutzt werden - nie den Sitzungszustand von Streamlit.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

import app

KORPUS_JSON = app.APP_DIR / "archiv_korpus.json"
IMPORT_JSON = app.APP_DIR / "archiv_import.json"
GCAT_SITES_CSV = app.APP_DIR / "gcat_startplaetze.csv"
GCAT_CACHE = app.APP_DIR / "gcat_launch_cache.tsv"
GCAT_URL = "https://planet4589.org/space/gcat/tsv/launch/launch.tsv"

#: Nationen des Archiv-Imports. Die USA bleiben bewusst draussen (Starlink),
#: die Erkennung kennt sie trotzdem - sonst koennte ein US-Start einer anderen
#: Nation zugeschlagen werden.
IMPORT_NATIONS = ("China", "Russland", "Indien", "Iran", "Nordkorea")
EXCLUDED_NATION = "USA"
YEARS = (2020, 2026)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_BATCH_BYTES = 200 * 1024 * 1024
MAX_GCAT_BYTES = 50 * 1024 * 1024
#: Hoechstens so viele Tagesbuendel je NOTAM - Dauer-Sperrgebiete wuerden
#: sonst hunderte Buendel fuellen.
MAX_BUNDLE_DAYS = 14
MATCH_SLACK = timedelta(minutes=30)
DEVIATION_DEG = 10.0
SOURCE_ARCHIVE = "Archive import"
#: Begruendung fuer einen erkannten Start ohne Startplatz (siehe analyze_day).
GRUND_OHNE_PLATZ = "Recognised as a launch, but no launch site could be determined."


class ImportStateError(RuntimeError):
    """Eine Zustandsdatei ist unlesbar; sie wird dann nicht ueberschrieben."""


@dataclass
class KorpusNotam:
    """Ein NOTAM im Rohkorpus, mit allen Stellen, an denen es gefunden wurde."""

    notam_id: str
    b: str
    text: str
    quellen: List[str] = field(default_factory=list)

    @property
    def schluessel(self) -> str:
        return "{}|{}".format(self.notam_id, self.b)


# --------------------------------------------------------------------------- #
# Extraktion
# --------------------------------------------------------------------------- #
_RE_BLOCK_ID = re.compile(r"\s*\(?([A-Z]?\d{3,4}/\d{2})\b", re.IGNORECASE)
_RE_END_ITEM = re.compile(r"\b([EFG])\)")


def cut_block(chunk: str) -> str:
    """
    Schneidet einen NOTAM-Block hinter seinem letzten Item ab.

    G) und F) sind einzeilig: der Block endet am Zeilenende. Hat er nur E),
    endet er an der ersten Leerzeile. Grund: Forenkommentare direkt unter dem
    NOTAM ("probably Starship") duerfen nie in die Erkennung gelangen.
    """
    chunk = chunk.strip()
    letzte: Dict[str, "re.Match[str]"] = {}
    for m in _RE_END_ITEM.finditer(chunk):
        letzte[m.group(1)] = m
    for item in ("G", "F"):
        m = letzte.get(item)
        if m:
            eol = chunk.find("\n", m.end())
            return chunk if eol < 0 else chunk[:eol].strip()
    m = letzte.get("E")
    if m:
        leer = re.search(r"\n\s*\n", chunk[m.end():])
        return chunk if not leer else chunk[: m.end() + leer.start()].strip()
    return chunk


def extract_notams(text: str, quelle: str) -> Tuple[List[KorpusNotam], int]:
    """
    Loest alle NOTAMs aus einem Forenbeitrag oder Langtext.

    Rueckgabe: die verwertbaren NOTAMs und die Zahl der Bloecke, die mit einer
    Kennung beginnen, aber kein E)/Q) oder kein lesbares B) haben. Vortext ohne
    Kennung ist Forengespraech und zaehlt nicht.
    """
    gefunden: List[KorpusNotam] = []
    unbrauchbar = 0
    for teil in app.RE_PASTE_BOUNDARY.split(app.normalize_pasted_text(text)):
        if not teil.strip():
            continue
        kopf = _RE_BLOCK_ID.match(teil)
        if not kopf:
            if teil.lstrip().startswith(("!", "NAVAREA", "navarea")):
                unbrauchbar += 1
            continue
        block = cut_block(teil)
        items = app.extract_items(block)
        b_roh = (items.get("B") or "").split()
        if not ({"E", "Q"} & set(items)) or not b_roh or app.parse_notam_datetime(b_roh[0]) is None:
            unbrauchbar += 1
            continue
        gefunden.append(
            KorpusNotam(kopf.group(1).upper(), b_roh[0], block, [quelle])
        )
    return gefunden, unbrauchbar


class _PostParser(HTMLParser):
    """
    Liest gespeicherte Forenseiten (NSF laeuft auf SMF) beitragsweise.

    Beitraege sind <div class="inner" id="msg_...">. Zitate (<blockquote>)
    werden verworfen - sonst kaeme jedes zitierte NOTAM doppelt -, ebenso
    script und style. Ohne Beitrags-Divs bleibt der ganze Text als ein Beitrag.
    """

    VOID = {"br", "img", "hr", "input", "meta", "link", "area", "base", "col", "wbr", "source"}
    BLOCK = {"p", "div", "li", "tr", "pre", "code", "blockquote", "h1", "h2", "h3", "h4", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.beitraege: List[Tuple[str, str]] = []
        self.ganz: List[str] = []
        self._stack: List[Tuple[str, str]] = []  # (Tag, Rolle: "", "post", "quote", "skip")
        self._post_id = ""
        self._post: Optional[List[str]] = None
        self._verdeckt = 0

    def _ziel(self) -> List[str]:
        return self._post if self._post is not None else self.ganz

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag == "br":
            if not self._verdeckt:
                self._ziel().append("\n")
            return
        if tag in self.VOID:
            return
        rolle = ""
        klassen = a.get("class", "").split()
        if tag in ("script", "style") or tag == "blockquote":
            rolle = "skip"
            self._verdeckt += 1
        elif tag == "div" and self._post is None and (
            "inner" in klassen or a.get("id", "").startswith("msg_")
        ):
            rolle = "post"
            self._post = []
            self._post_id = a.get("id", "") or "msg_{}".format(len(self.beitraege) + 1)
        if tag in self.BLOCK and not self._verdeckt:
            self._ziel().append("\n")
        self._stack.append((tag, rolle))

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        while self._stack:
            offen, rolle = self._stack.pop()
            if rolle == "skip":
                self._verdeckt -= 1
            elif rolle == "post" and self._post is not None:
                self.beitraege.append((self._post_id, "".join(self._post)))
                self._post = None
            if offen == tag:
                break
        if tag in self.BLOCK and not self._verdeckt:
            self._ziel().append("\n")

    def handle_data(self, data: str) -> None:
        if not self._verdeckt:
            self._ziel().append(data)


def texts_from_upload(name: str, data: bytes) -> List[Tuple[str, str]]:
    """Zerlegt eine hochgeladene Datei in (Quelle, Text)-Paare, je Beitrag eins."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("{}: larger than {} MB".format(name, MAX_FILE_BYTES // (1024 * 1024)))
    text = data.decode("utf-8", errors="replace")
    kopf = text.lstrip()[:200].lower()
    if not (name.lower().endswith((".html", ".htm")) or kopf.startswith(("<!doctype", "<html"))):
        return [(name, text)]
    parser = _PostParser()
    parser.feed(text)
    parser.close()
    if parser.beitraege:
        return [("{}#{}".format(name, pid), t) for pid, t in parser.beitraege]
    return [(name, "".join(parser.ganz))]
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|ERGEBNIS"`
Erwartet: nur `ERGEBNIS: ALLE TESTS BESTANDEN`

- [ ] **Schritt 5: Stand prüfen** (`git status --short`; kein Commit)

---

### Aufgabe 2: Rohkorpus, Entdoppeln, Zustandsdateien, Stapelgrenzen

**Dateien:**
- Ändern: `archiv_import.py`, `test_app.py`, `.gitignore`

**Schnittstellen:**
- Nutzt: `KorpusNotam`, `extract_notams`, `texts_from_upload` aus Aufgabe 1
- Liefert:
  - `merge_korpus(korpus: Dict[str, KorpusNotam], neue: Iterable[KorpusNotam]) -> Tuple[int, int]`
    (Rückgabe: neu, Dubletten)
  - `read_json(path: Path) -> Dict[str, Any]`, `write_json_atomic(path: Path, data: Dict[str, Any]) -> None`
  - `load_korpus(path: Path = KORPUS_JSON) -> Dict[str, KorpusNotam]`,
    `save_korpus(korpus: Dict[str, KorpusNotam], path: Path = KORPUS_JSON) -> None`
  - `ImportReport` (Datenklasse, Felder unten)
  - `ingest(korpus, dateien: Sequence[Tuple[str, bytes]], eingefuegt: str = "") -> ImportReport`

**Abnahmekriterien:**
- Gleiche Kennung mit gleichem `B)` ergibt einen Eintrag mit allen Quellen.
- Eine unlesbare JSON-Datei löst `ImportStateError` aus und bleibt unverändert.
- Ein Stapel über 200 MB wird ganz abgelehnt. Eine einzelne fehlerhafte Datei steht im
  Bericht, der Rest läuft weiter.
- Das Speichern ist atomar (temporäre Datei, dann `os.replace`).

- [ ] **Schritt 1: Fehlschlagende Tests schreiben** (an den Abschnitt anhängen)

```python
import tempfile
from pathlib import Path as _P
_tmp = _P(tempfile.mkdtemp())
korpus = {}
neu, dup = ai.merge_korpus(korpus, gef)
neu2, dup2 = ai.merge_korpus(korpus, ai.extract_notams(AI_CN[1], "seite2.txt")[0])
check("Korpus: drei neu, dann eine Dublette", (neu, dup, neu2, dup2) == (3, 0, 0, 1), (neu, dup, neu2, dup2))
check("  ... Quellen zusammengefuehrt",
      korpus["A4631/26|2609200354"].quellen == ["test.txt", "seite2.txt"],
      korpus["A4631/26|2609200354"].quellen)
ai.save_korpus(korpus, _tmp / "k.json")
check("Korpus: speichern und laden", set(ai.load_korpus(_tmp / "k.json")) == set(korpus))
(_tmp / "kaputt.json").write_text("{ halb", encoding="utf-8")
try:
    ai.read_json(_tmp / "kaputt.json")
    check("unlesbare JSON bricht ab", False)
except ai.ImportStateError:
    check("unlesbare JSON bricht ab", (_tmp / "kaputt.json").read_text(encoding="utf-8") == "{ halb")
check("fehlende JSON ergibt leeren Stand", ai.read_json(_tmp / "fehlt.json") == {})

k2 = {}
bericht = ai.ingest(k2, [("thread_p1.html", SMF.encode("utf-8")), ("kaputt.bin", b"\xff" * 10)], AI_CN[0])
check("Ingest: drei NOTAMs, eine Dublette", (bericht.notams_neu, bericht.dubletten) == (3, 0),
      (bericht.notams_neu, bericht.dubletten))
check("  ... Dateien gezaehlt", bericht.dateien == 2, bericht.dateien)
bericht_gross = ai.ingest({}, [("a.txt", b"x" * 10)] * 1, "")
check("  ... kleiner Stapel ohne Fehler", bericht_gross.fehler == [], bericht_gross.fehler)
_alt_max = ai.MAX_BATCH_BYTES
ai.MAX_BATCH_BYTES = 15
bericht_zu_gross = ai.ingest({}, [("a.txt", b"x" * 10), ("b.txt", b"x" * 10)], "")
ai.MAX_BATCH_BYTES = _alt_max
check("Stapel ueber der Grenze ganz abgelehnt",
      bericht_zu_gross.dateien == 0 and bericht_zu_gross.fehler, bericht_zu_gross.fehler)
gi = (_P(app.APP_DIR) / ".gitignore").read_text(encoding="utf-8")
check(".gitignore: lokale Importdateien",
      all(n in gi for n in ("archiv_korpus.json", "archiv_import.json", "gcat_launch_cache.tsv")))
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

Run: `.venv/bin/python test_app.py 2>&1 | tail -5`
Erwartet: `AttributeError: module 'archiv_import' has no attribute 'merge_korpus'`

- [ ] **Schritt 3: Implementierung** (an `archiv_import.py` anhängen)

```python
# --------------------------------------------------------------------------- #
# Rohkorpus und Zustandsdateien
# --------------------------------------------------------------------------- #
def merge_korpus(
    korpus: Dict[str, KorpusNotam], neue: Iterable[KorpusNotam]
) -> Tuple[int, int]:
    """Fuegt NOTAMs hinzu; Dubletten (Kennung + B) sammeln nur ihre Quelle."""
    neu = dup = 0
    for n in neue:
        alt = korpus.get(n.schluessel)
        if alt is None:
            korpus[n.schluessel] = KorpusNotam(n.notam_id, n.b, n.text, list(n.quellen))
            neu += 1
            continue
        dup += 1
        for q in n.quellen:
            if q not in alt.quellen:
                alt.quellen.append(q)
    return neu, dup


def read_json(path: Path) -> Dict[str, Any]:
    """Liest eine Zustandsdatei; fehlt sie, ist der Stand leer."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ImportStateError(
            "{} is unreadable ({}). It is left untouched - please check it.".format(path.name, exc)
        ) from exc
    if not isinstance(data, dict):
        raise ImportStateError("{} has an unexpected format.".format(path.name))
    return data


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Schreibt erst eine temporaere Datei und benennt sie dann um."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_korpus(path: Path = KORPUS_JSON) -> Dict[str, KorpusNotam]:
    data = read_json(path)
    korpus: Dict[str, KorpusNotam] = {}
    for e in data.get("notams", []):
        n = KorpusNotam(e["notam_id"], e["b"], e["text"], list(e.get("quellen", [])))
        korpus[n.schluessel] = n
    return korpus


def save_korpus(korpus: Dict[str, KorpusNotam], path: Path = KORPUS_JSON) -> None:
    write_json_atomic(
        path,
        {
            "version": 1,
            "notams": [
                {"notam_id": n.notam_id, "b": n.b, "text": n.text, "quellen": n.quellen}
                for n in sorted(korpus.values(), key=lambda n: n.schluessel)
            ],
        },
    )


@dataclass
class ImportReport:
    """Was ein Stapel gebracht hat - auch das, was nicht verwertbar war."""

    dateien: int = 0
    notams_neu: int = 0
    dubletten: int = 0
    unbrauchbar: int = 0
    fehler: List[str] = field(default_factory=list)
    tage_ausgewertet: int = 0
    usa_ausgenommen: int = 0
    ausgeblendet: int = 0


def ingest(
    korpus: Dict[str, KorpusNotam],
    dateien: Sequence[Tuple[str, bytes]],
    eingefuegt: str = "",
) -> ImportReport:
    """Liest einen Stapel in den Korpus. Eine fehlerhafte Datei haelt den Rest nicht auf."""
    bericht = ImportReport()
    gesamt = sum(len(d) for _, d in dateien) + len(eingefuegt.encode("utf-8"))
    if gesamt > MAX_BATCH_BYTES:
        bericht.fehler.append(
            "Batch refused: larger than {} MB.".format(MAX_BATCH_BYTES // (1024 * 1024))
        )
        return bericht
    paare: List[Tuple[str, str]] = []
    for name, data in dateien:
        try:
            paare.extend(texts_from_upload(name, data))
            bericht.dateien += 1
        except Exception as exc:  # jede Datei einzeln - der Stapel laeuft weiter
            bericht.fehler.append("{}: {}".format(name, exc))
    if eingefuegt.strip():
        paare.append(("pasted {}".format(datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%MZ")), eingefuegt))
    for quelle, text in paare:
        notams, unbrauchbar = extract_notams(text, quelle)
        bericht.unbrauchbar += unbrauchbar
        neu, dup = merge_korpus(korpus, notams)
        bericht.notams_neu += neu
        bericht.dubletten += dup
    return bericht
```

Hinweis zum Test „kaputt.bin": `texts_from_upload` dekodiert mit `errors="replace"`, die Datei
zählt also als gelesen und liefert keine NOTAMs. Das ist gewollt: Eine fremde Datei bricht
nichts ab und steht im Bericht als „0 NOTAMs".

`.gitignore` ergänzen (am Ende):

```
# Archiv-Import - aus Forenseiten abgeleitet, bleibt wie das Archiv lokal
archiv_korpus.json
archiv_import.json
gcat_launch_cache.tsv
*.json.tmp
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen** (`.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|ERGEBNIS"`)

- [ ] **Schritt 5: Stand prüfen** (kein Commit)

---

### Aufgabe 3: Tagesbündel und Tagesanalyse mit USA-Filter

**Dateien:**
- Ändern: `archiv_import.py`, `test_app.py`

**Schnittstellen:**
- Nutzt: `app.analyze_notams`, `app.archive_row`, `app.archive_key`, `app.SOURCE_COLUMN`,
  `app.extract_items`, `app.parse_notam_datetime`
- Liefert:
  - `bundle_days(korpus: Dict[str, KorpusNotam]) -> Dict[date, List[KorpusNotam]]`
  - `day_fingerprint(notams: Sequence[KorpusNotam]) -> str`
  - `DayResult(kandidaten: List[Dict], pruefliste: List[Dict], usa: int, ausgeblendet: int)`
  - `analyze_day(tag: date, notams, spaceports, firs, bestaetigt: Set[str], ausgeblendet: Set[str]) -> DayResult`
  - Kandidat (dict): `key, row (Archivzeile), tag (ISO), nation (deutsch), seestart (bool),
    fenster ([ISO von, ISO bis]), notam_ids, quellen, inklination, azimut`
  - Prüflisteneintrag (dict): `event_key, schluessel, notam_id, tag, grund, text, quellen`

**Abnahmekriterien:**
- NOTAMs landen im Bündel jedes Tages ihres `B)`–`C)`-Fensters, höchstens 14 Tage.
  `C) PERM` oder fehlendes `C)` ergibt nur den `B)`-Tag.
- Ein Bündel ergibt nur Kandidaten, deren Startdatum der Bündeltag ist.
- Ein US-Start wird gezählt, nie Kandidat. Ein chinesischer Start am selben Tag bleibt erhalten.
- Unsichere Fälle in US-FIRs werden gezählt, nicht auf die Prüfliste gesetzt.
- Ein OK-Fall ohne Startplatz kommt mit Begründung auf die Prüfliste.
- Automatisch und von Hand ausgeblendete Fälle werden gezählt.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
VB_GLEICHER_TAG = vandenberg.replace("2609210130", "2609200130").replace("2609210430", "2609200430")
# Ohne Textbeleg, aber in eigener US-FIR: die Nation folgt aus der Geografie -> USA.
US_ZOA = ("W1235/26 NOTAMN Q) ZOA/QRTCA/IV/BO/W/000/999/3444N12034W050 A) ZOA "
          "B) 2609200130 C) 2609200430 E) DANGER AREA ACTIVATED. AREA BOUNDED BY 343000N1203500W - "
          "341500N1201500W - 330000N1200000W - 331500N1204500W F) SFC G) UNL")
# Ohne Textbeleg in einer FIR, die die Referenz nicht kennt: nichts belegt USA -> Pruefliste.
VB_OHNE_BELEG = ohne_beleg.replace("W1234/26", "W1236/26").replace(
    "2609210130", "2609200130").replace("2609210430", "2609200430")
LANG = AI_CN[1].replace("A4631/26", "A4699/26").replace(
    "B)2609200354 C)2609200415", "B)2609010000 C)2611300000")
kt = {}
ai.merge_korpus(kt, ai.extract_notams("\n\n".join(AI_CN[1:] + [VB_GLEICHER_TAG, US_ZOA, VB_OHNE_BELEG, LANG]), "t")[0])
buendel = ai.bundle_days(kt)
from datetime import date as _d
check("Tagesbuendel: 20.09. enthaelt die fuenf kurzen", len(buendel[_d(2026, 9, 20)]) == 5, len(buendel[_d(2026, 9, 20)]))
check("  ... lange Meldung hoechstens 14 Tage",
      _d(2026, 9, 14) in buendel and _d(2026, 9, 15) not in buendel, sorted(buendel)[:3])
check("Fingerabdruck stabil gegen Reihenfolge",
      ai.day_fingerprint(buendel[_d(2026, 9, 20)]) == ai.day_fingerprint(list(reversed(buendel[_d(2026, 9, 20)]))))

tag20 = ai.analyze_day(_d(2026, 9, 20), buendel[_d(2026, 9, 20)], sp, fir, set(), set())
check("Tagesanalyse: ein chinesischer Kandidat",
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tag20.kandidaten] == [("China", "JSLC")],
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tag20.kandidaten])
check("  ... Kandidat traegt beide Kennungen",
      {"A4631/26", "A4632/26"} <= set(k for k in tag20.kandidaten[0]["notam_ids"]), tag20.kandidaten[0]["notam_ids"])
check("  ... US-Starts gezaehlt, nicht gefuehrt", tag20.usa >= 1, tag20.usa)
check("  ... weder W1234/26 noch W1235/26 auf der Pruefliste",
      not {"W1234/26", "W1235/26"} & {p["notam_id"] for p in tag20.pruefliste},
      [p["notam_id"] for p in tag20.pruefliste])
check("  ... unbekannte FIR ohne Beleg bleibt auf der Pruefliste",
      [p["notam_id"] for p in tag20.pruefliste] == ["W1236/26"], [p["notam_id"] for p in tag20.pruefliste])
check("  ... Kandidatenschluessel = archive_key",
      tag20.kandidaten[0]["key"] == app.archive_key(tag20.kandidaten[0]["row"]))
spaeter = ai.analyze_day(_d(2026, 9, 5), buendel[_d(2026, 9, 5)], sp, fir, set(), set())
check("Folgetag: lange Meldung erzeugt keinen Start mit fremdem Datum",
      all(k["row"]["Startdatum"] == "05.09.2026" for k in spaeter.kandidaten),
      [k["row"]["Startdatum"] for k in spaeter.kandidaten])

kommentiert = {}
ai.merge_korpus(kommentiert, ai.extract_notams(
    AI_CN[1] + "\nprobably Starship from Boca Chica\n\n" + AI_CN[2] + "\nSTARSHIP FLIGHT 12", "t")[0])
tk = ai.analyze_day(_d(2026, 9, 20), list(kommentiert.values()), sp, fir, set(), set())
check("Pflichtfall: Starship-Kommentar aendert die Zuordnung nicht",
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tk.kandidaten] == [("China", "JSLC")],
      [(k["nation"], k["row"]["Weltraumbahnhof"]) for k in tk.kandidaten])
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen** (`AttributeError: ... 'bundle_days'`)

- [ ] **Schritt 3: Implementierung**

```python
# --------------------------------------------------------------------------- #
# Tagesbuendel und Tagesanalyse
# --------------------------------------------------------------------------- #
def _utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fenster(n: KorpusNotam) -> Tuple[datetime, Optional[datetime]]:
    von = _utc(app.parse_notam_datetime(n.b))
    c_roh = (app.extract_items(n.text).get("C") or "").split()
    bis = _utc(app.parse_notam_datetime(c_roh[0])) if c_roh else None
    return von, bis


def bundle_days(korpus: Dict[str, KorpusNotam]) -> Dict[date, List[KorpusNotam]]:
    """
    Buendelt den Korpus nach Aktivierungstagen.

    Ein NOTAM gehoert in jedes Buendel eines Tages seines B-C-Fensters, damit
    eine mehrtaegige Vorankuendigung am Starttag neben den kurzen Meldungen
    liegt - so wie in der taeglichen FNS-Datei. Hoechstens MAX_BUNDLE_DAYS.
    """
    buendel: Dict[date, List[KorpusNotam]] = defaultdict(list)
    for n in korpus.values():
        von, bis = _fenster(n)
        if von is None:
            continue
        start = von.date()
        ende = bis.date() if bis is not None and bis >= von else start
        ende = min(ende, start + timedelta(days=MAX_BUNDLE_DAYS - 1))
        tag = start
        while tag <= ende:
            buendel[tag].append(n)
            tag += timedelta(days=1)
    for liste in buendel.values():
        liste.sort(key=lambda n: n.schluessel)
    return dict(buendel)


def day_fingerprint(notams: Sequence[KorpusNotam]) -> str:
    """Aendert sich nur, wenn ein NOTAM dazukommt oder wegfaellt."""
    roh = "\n".join(sorted(n.schluessel for n in notams))
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


@dataclass
class DayResult:
    kandidaten: List[Dict[str, Any]] = field(default_factory=list)
    pruefliste: List[Dict[str, Any]] = field(default_factory=list)
    usa: int = 0
    ausgeblendet: int = 0


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _utc(dt).isoformat() if dt else None


def analyze_day(
    tag: date,
    notams: Sequence[KorpusNotam],
    spaceports: pd.DataFrame,
    firs: pd.DataFrame,
    bestaetigt: Set[str],
    ausgeblendet: Set[str],
) -> DayResult:
    """
    Wertet ein Tagesbuendel mit der Pipeline des Tagesbetriebs aus.

    `bestaetigt` und `ausgeblendet` sind Event-Schluessel aus der Pruefliste des
    Imports - getrennt von den Entscheidungen der Tageslage.
    """
    ergebnis = DayResult()
    if not notams:
        return ergebnis
    df = pd.DataFrame(
        {"NOTAM Text": [n.text for n in notams], app.SOURCE_COLUMN: SOURCE_ARCHIVE}
    )
    events, stats = app.analyze_notams(
        df, spaceports, firs, min_confidence="MEDIUM", confirmed_keys=set(bestaetigt)
    )
    groups = stats.get("groups", [])
    weg = {
        e.row_index for e in events if e.auto_hidden_reason or e.key in ausgeblendet
    }
    ergebnis.ausgeblendet = len(weg)
    tag_text = tag.strftime("%d.%m.%Y")
    belegt: Set[int] = set()
    ohne_platz: Set[int] = set()

    for g in groups:
        ok = [
            e for e in events
            if e.row_index in g.row_indices and e.status == "OK" and e.row_index not in weg
        ]
        if not ok:
            continue
        if g.nation == EXCLUDED_NATION:
            ergebnis.usa += 1
            belegt |= set(g.row_indices) | set(g.advance_row_indices)
            continue
        if not g.spaceport_code:
            ohne_platz |= {e.row_index for e in ok}
            continue
        if g.nation not in IMPORT_NATIONS:
            continue
        row = app.archive_row(g, events)
        belegt |= set(g.row_indices) | set(g.advance_row_indices)
        if row["Startdatum"] != tag_text:
            continue  # gehoert in das Buendel seines eigenen Starttags
        mitglieder = sorted(set(g.row_indices) | set(g.advance_row_indices))
        ergebnis.kandidaten.append(
            {
                "key": app.archive_key(row),
                "row": row,
                "tag": tag.isoformat(),
                "nation": g.nation,
                "seestart": bool(g.site_from_geometry),
                "fenster": [_iso(g.window_from), _iso(g.window_to or g.window_from)],
                "notam_ids": [notams[i].notam_id for i in mitglieder],
                "quellen": sorted({q for i in mitglieder for q in notams[i].quellen}),
                "inklination": g.inclination_deg,
                "azimut": g.azimuth_deg,
            }
        )

    for e in events:
        if e.row_index in weg or e.row_index in belegt:
            continue
        if e.status == "OK" and e.row_index not in ohne_platz:
            continue
        if e.nation == EXCLUDED_NATION or (not e.nation and e.fir_country == EXCLUDED_NATION):
            ergebnis.usa += 1
            continue
        n = notams[e.row_index]
        grund = e.review_reason
        if e.row_index in ohne_platz:
            grund = GRUND_OHNE_PLATZ
        ergebnis.pruefliste.append(
            {
                "event_key": e.key,
                "schluessel": n.schluessel,
                "notam_id": n.notam_id,
                "tag": tag.isoformat(),
                "grund": grund,
                "text": n.text,
                "quellen": list(n.quellen),
            }
        )
    return ergebnis
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Schritt 5: Stand prüfen** (kein Commit)

---

### Aufgabe 4: GCAT-Startliste und Startplatz-Referenz

**Dateien:**
- Neu: `gcat_startplaetze.csv`
- Ändern: `archiv_import.py`, `test_app.py`

**Schnittstellen:**
- Liefert:
  - `GcatStart(tag: str, zeit: datetime, nur_datum: bool, rakete: str, nutzlast: str, site: str, inklination: Optional[float], azimut: Optional[float])`
  - `parse_gcat(text: str) -> List[GcatStart]` (nur Orbitalstarts 2020–2026)
  - `load_gcat_sites(path: Path = GCAT_SITES_CSV) -> Dict[str, Tuple[List[str], str]]`
    (GCAT-Code → Liste der NOLA-Kürzel, Land)
  - `load_gcat(refresh: bool = False, cache: Path = GCAT_CACHE, opener=urllib.request.urlopen) -> Tuple[Optional[List[GcatStart]], str]`
    (`None` = nicht verfügbar; zweiter Wert ist der Status für die Oberfläche)

**Abnahmekriterien:**
- Nur Startnummern der Form `JJJJ-NNN`, `JJJJ-ENN` und `JJJJ-FNN`, keine Suborbitalflüge.
- Datumsformen mit Sekunden, ohne Sekunden, nur Tag und mit `?` werden gelesen.
- Payload aus `Mission`, ersatzweise `Flight`. `-` wird leer.
- Ohne Netz bleibt der vorhandene Cache in Gebrauch. Ohne Cache gilt die Liste als nicht verfügbar.
- Abgerufen wird ausschließlich `GCAT_URL`.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
GCAT_KOPF = "#Launch_Tag\tLaunch_JD\tLaunch_Date\tLV_Type\tVariant\tFairing\tFlight_ID\tFlight\tMission\tFlightCode\tPlatform\tLaunch_Site\tLaunch_Pad\tAscent_Site\tAscent_Pad\tPerigee\tApogee\tApoflag\tInc\tAzimuth\n# Updated\n"
def _gz(tag, datum, lv, flight, mission, site, inc="-", az="-", platform="-"):
    return "\t".join([tag, "0", datum, lv, "-", "-", "-", flight, mission, "-", platform, site, "-", "-", "-", "-", "-", " ", inc, az]) + "\n"
GCAT_TXT = GCAT_KOPF + "".join([
    _gz("2026-201 ", "2026 Sep 20 0356", "Chang Zheng 2D/YZ-3", "Yaogan 45", "-", "JQ", " 97.0 ", " 189.0"),
    _gz("2026-202 ", "2026 Sep 20 0354:12", "Falcon 9", "Starlink 11-2", "Starlink 11-2", "VSFBS"),
    _gz("2026-S12 ", "2026 Sep 20 0400", "Iran SRBM", "-", "-", "IRAN"),
    _gz("2025-E01 ", "2025 Mar  1", "Kuaizhou-1A", "Unknown", "-", "JQ"),
    _gz("2019-001 ", "2019 Jan 10 1611", "Chang Zheng 3B", "ChinaSat 2D", "-", "XSC"),
    _gz("2023-200 ", "2023 Dec  5 1924?", "Jielong-3", "WHJSW 03", "-", "YJ", platform="DFHT"),
])
gs = ai.parse_gcat(GCAT_TXT)
check("GCAT: Orbitalstarts 2020-2026, ohne Suborbital", [s.tag for s in gs] == ["2026-201", "2026-202", "2025-E01", "2023-200"],
      [s.tag for s in gs])
check("  ... Uhrzeit gelesen", gs[0].zeit.strftime("%Y-%m-%d %H:%M") == "2026-09-20 03:56" and not gs[0].nur_datum)
check("  ... nur Tagesdatum erkannt", gs[2].nur_datum, gs[2].zeit)
check("  ... Fragezeichen toleriert", gs[3].zeit.strftime("%H:%M") == "19:24", gs[3].zeit)
check("  ... Payload faellt auf Flight zurueck", gs[0].nutzlast == "Yaogan 45", gs[0].nutzlast)
check("  ... Inklination und Azimut", (gs[0].inklination, gs[0].azimut) == (97.0, 189.0))
sites = ai.load_gcat_sites()
check("Referenz gcat_startplaetze.csv: JQ -> JSLC, China", sites.get("JQ") == (["JSLC"], "China"), sites.get("JQ"))
check("  ... Baikonur unter GIK-5", sites.get("GIK-5") == (["BAIK"], "Russland"), sites.get("GIK-5"))
check("  ... Seegebiet ohne festen Platz", sites.get("ECS") == ([], "China"), sites.get("ECS"))

aufgerufen = []
class _Antwort:
    def __init__(self, daten): self.daten = daten
    def read(self, n=-1): return self.daten
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _opener_ok(req, timeout=0):
    aufgerufen.append(req.full_url); return _Antwort(GCAT_TXT.encode("utf-8"))
def _opener_fehler(req, timeout=0):
    raise OSError("offline")
cache = _tmp / "gcat.tsv"
liste, status = ai.load_gcat(refresh=True, cache=cache, opener=_opener_ok)
check("GCAT-Abruf nur von der festen Adresse", aufgerufen == [ai.GCAT_URL], aufgerufen)
check("  ... Cache geschrieben", cache.exists() and len(liste) == 4, status)
liste2, status2 = ai.load_gcat(refresh=True, cache=cache, opener=_opener_fehler)
check("offline: Cache bleibt in Gebrauch", liste2 is not None and len(liste2) == 4, status2)
liste3, status3 = ai.load_gcat(refresh=True, cache=_tmp / "nichts.tsv", opener=_opener_fehler)
check("offline ohne Cache: nicht verfuegbar", liste3 is None, status3)
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

- [ ] **Schritt 3: `gcat_startplaetze.csv` anlegen**

Die Belegung stammt aus GCAT 2020–2026 (Orbitalstarts der fünf Nationen), Stand
01.10.2026. Mehrere Kürzel werden mit `;` getrennt.

```
GCAT,Kurzel,Land
JQ,JSLC,China
TYSC,TSLC,China
XSC,XSLC,China
WEN,WSLC,China
HCSLS,HAIN,China
HHAI,HIIS;HYOS,China
YJ,HYOS;HIIS,China
ECS,,China
GIK-1,GIK-1,Russland
GIK-5,BAIK,Russland
VOST,VOSC,Russland
SHAR,SDSC,Indien
SDSC,SDSC,Indien
SEM,SSSC,Iran
SHAHR,SCSL,Iran
SOHAE,KSS,Nordkorea
```

- [ ] **Schritt 4: Implementierung**

```python
# --------------------------------------------------------------------------- #
# GCAT-Startliste (J. McDowell, CC-BY)
# --------------------------------------------------------------------------- #
@dataclass
class GcatStart:
    tag: str
    zeit: datetime
    nur_datum: bool
    rakete: str
    nutzlast: str
    site: str
    inklination: Optional[float]
    azimut: Optional[float]


_RE_ORBITAL_TAG = re.compile(r"^\d{4}-(\d{3}|[EF]\d{2})$")
_RE_GCAT_DATE = re.compile(
    r"^(\d{4}) ([A-Z][a-z]{2}) +(\d{1,2})(?: (\d{2})(\d{2})(?::(\d{2}))?)?"
)
_MONATE = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _zahl(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except ValueError:
        return None


def _leer(text: str) -> str:
    t = text.strip()
    return "" if t in ("", "-") else t


def parse_gcat(text: str) -> List[GcatStart]:
    """Liest launch.tsv; behalten werden nur Orbitalstarts der Jahre YEARS."""
    starts: List[GcatStart] = []
    for zeile in text.splitlines():
        if not zeile or zeile.startswith("#"):
            continue
        r = zeile.split("\t")
        if len(r) < 20 or not _RE_ORBITAL_TAG.match(r[0].strip()):
            continue
        m = _RE_GCAT_DATE.match(r[2].strip())
        if not m or m.group(2) not in _MONATE:
            continue
        jahr = int(m.group(1))
        if not YEARS[0] <= jahr <= YEARS[1]:
            continue
        nur_datum = m.group(4) is None
        zeit = datetime(
            jahr, _MONATE[m.group(2)], int(m.group(3)),
            int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
            tzinfo=timezone.utc,
        )
        starts.append(
            GcatStart(
                tag=r[0].strip(),
                zeit=zeit,
                nur_datum=nur_datum,
                rakete=_leer(r[3]),
                nutzlast=_leer(r[8]) or _leer(r[7]),
                site=r[11].strip().rstrip("?"),
                inklination=_zahl(r[18]),
                azimut=_zahl(r[19]),
            )
        )
    return starts


def load_gcat_sites(path: Path = GCAT_SITES_CSV) -> Dict[str, Tuple[List[str], str]]:
    """GCAT-Startplatzcode -> (NOLA-Kuerzel, Land). Fehlt die Datei, ist sie leer."""
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    return {
        r["GCAT"].strip(): (
            [k.strip() for k in r["Kurzel"].split(";") if k.strip()],
            r["Land"].strip(),
        )
        for _, r in df.iterrows()
        if r["GCAT"].strip()
    }


_GCAT_MEMO: Dict[Tuple[str, float], List[GcatStart]] = {}


def load_gcat(
    refresh: bool = False, cache: Path = GCAT_CACHE, opener: Any = urllib.request.urlopen
) -> Tuple[Optional[List[GcatStart]], str]:
    """
    Startliste aus dem Cache; mit refresh vorher neu abrufen.

    Abgerufen wird nur GCAT_URL. Scheitert der Abruf, bleibt ein vorhandener
    Cache in Gebrauch; ohne Cache gibt es keinen Abgleich (None).
    """
    hinweis = ""
    if refresh or not cache.exists():
        try:
            anfrage = urllib.request.Request(GCAT_URL, headers={"User-Agent": "NOLA archive import"})
            with opener(anfrage, timeout=60) as antwort:
                daten = antwort.read(MAX_GCAT_BYTES + 1)
            if len(daten) > MAX_GCAT_BYTES:
                raise ValueError("launch list larger than expected")
            tmp = cache.with_name(cache.name + ".tmp")
            tmp.write_bytes(daten)
            os.replace(tmp, cache)
        except Exception as exc:
            hinweis = "Download failed ({}). ".format(exc)
    if not cache.exists():
        return None, hinweis + "Launch list not available - no suggestions."
    mtime = cache.stat().st_mtime
    stand = datetime.fromtimestamp(mtime, timezone.utc).strftime("%d.%m.%Y")
    # 13 MB bei jedem Streamlit-Durchlauf neu zu lesen waere spuerbar - je
    # Datei und Aenderungszeit wird nur einmal gelesen.
    memo_key = (str(cache), mtime)
    if memo_key not in _GCAT_MEMO:
        _GCAT_MEMO.clear()
        _GCAT_MEMO[memo_key] = parse_gcat(cache.read_text(encoding="utf-8", errors="replace"))
    starts = _GCAT_MEMO[memo_key]
    return starts, hinweis + "GCAT (J. McDowell, CC-BY), copy from {}: {} launches.".format(stand, len(starts))
```

- [ ] **Schritt 5: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Schritt 6: Stand prüfen** (kein Commit)

---

### Aufgabe 5: Abgleich, Trägersystem-Zuordnung, Plausibilitätsprüfung

**Dateien:**
- Ändern: `archiv_import.py`, `test_app.py`

**Schnittstellen:**
- Nutzt: Kandidat-dict (Aufgabe 3), `GcatStart`, `load_gcat_sites` (Aufgabe 4)
- Liefert:
  - Konstanten `STATUS_EINDEUTIG = "unique"`, `STATUS_MEHRDEUTIG = "ambiguous"`,
    `STATUS_KEIN_FLUG = "no flight in GCAT"`, `STATUS_SEESTART = "sea launch"`,
    `STATUS_KEIN_ABGLEICH = "no comparison"`
  - `Abgleich(status: str, treffer: List[GcatStart], warnungen: List[str], hinweise: List[str])`
  - `match_candidate(kand: Dict, gcat: Optional[List[GcatStart]], sites: Dict) -> Abgleich`
  - `vehicle_code_for(gcat_rakete: str, vehicles: pd.DataFrame) -> str`

**Abnahmekriterien:**
- Genau ein Treffer mit Uhrzeit im Fenster ±30 min am zugeordneten Platz ergibt *unique*.
- Ein Treffer nur mit Tagesdatum ergibt *ambiguous*.
- Seestarts werden nur über Land und Fenster gepaart und sind nie *unique*.
- Abweichungen bei Inklination oder Azimut über 10° sowie eine abweichende Nation erzeugen
  eine Warnung.
- Ohne Treffer nennt der Hinweis die GCAT-Starts im Fenster an nicht zugeordneten Plätzen.
- GCAT-Raketennamen werden auf `Abkürzung` abgebildet. Ohne Entsprechung bleibt das Feld leer.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
kand = dict(tag20.kandidaten[0])
abg = ai.match_candidate(kand, gs, sites)
check("Abgleich: eindeutig", abg.status == ai.STATUS_EINDEUTIG, (abg.status, abg.warnungen, abg.hinweise))
check("  ... Treffer ist der chinesische Start", abg.treffer[0].tag == "2026-201")
check("  ... keine Warnung bei passender Bahn", abg.warnungen == [], abg.warnungen)
schief = dict(kand, inklination=60.0)
check("Abweichung ueber 10 Grad wird gewarnt", ai.match_candidate(schief, gs, sites).warnungen != [])
check("ohne Startliste: kein Abgleich", ai.match_candidate(kand, None, sites).status == ai.STATUS_KEIN_ABGLEICH)
leer_tag = dict(kand, fenster=["2026-09-21T03:00:00+00:00", "2026-09-21T03:30:00+00:00"])
abg0 = ai.match_candidate(leer_tag, gs, sites)
check("kein Treffer: kein Flug", abg0.status == ai.STATUS_KEIN_FLUG, abg0.status)
nur_tag = dict(kand, fenster=["2025-03-01T10:00:00+00:00", "2025-03-01T10:20:00+00:00"])
check("nur Tagesdatum: nie eindeutig", ai.match_candidate(nur_tag, gs, sites).status == ai.STATUS_MEHRDEUTIG)
see = dict(kand, seestart=True, row=dict(kand["row"], Weltraumbahnhof=""),
           fenster=["2023-12-05T19:00:00+00:00", "2023-12-05T19:40:00+00:00"])
abg_see = ai.match_candidate(see, gs, sites)
check("Seestart: Treffer ueber Land, aber nie eindeutig",
      abg_see.status == ai.STATUS_SEESTART and len(abg_see.treffer) == 1, abg_see.status)
fremd = dict(kand, row=dict(kand["row"], Weltraumbahnhof="XSLC"))
abg_f = ai.match_candidate(fremd, gs, sites)
check("Hinweis nennt nicht zugeordnete GCAT-Plaetze im Fenster",
      any("VSFBS" in h for h in abg_f.hinweise), abg_f.hinweise)
veh = app.load_vehicles(str(app.VEHICLE_CSV))
check("Rakete: Chang Zheng 2D/YZ-3 -> CZ-2D", ai.vehicle_code_for("Chang Zheng 2D/YZ-3", veh) == "CZ-2D")
check("Rakete: Soyuz-2-1A -> Soyuz-2.1a", ai.vehicle_code_for("Soyuz-2-1A", veh) == "Soyuz-2.1a")
check("Rakete ohne Entsprechung bleibt leer", ai.vehicle_code_for("Cheonlima-1", veh) == "")
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

- [ ] **Schritt 3: Implementierung**

```python
# --------------------------------------------------------------------------- #
# Abgleich mit GCAT
# --------------------------------------------------------------------------- #
STATUS_EINDEUTIG = "unique"
STATUS_MEHRDEUTIG = "ambiguous"
STATUS_KEIN_FLUG = "no flight in GCAT"
STATUS_SEESTART = "sea launch"
STATUS_KEIN_ABGLEICH = "no comparison"


@dataclass
class Abgleich:
    status: str
    treffer: List[GcatStart] = field(default_factory=list)
    warnungen: List[str] = field(default_factory=list)
    hinweise: List[str] = field(default_factory=list)


def _winkel(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def match_candidate(
    kand: Dict[str, Any],
    gcat: Optional[List[GcatStart]],
    sites: Dict[str, Tuple[List[str], str]],
) -> Abgleich:
    """
    Paart einen Kandidaten mit GCAT-Starts. Liefert nur Vorschlaege: was
    uebernommen wird, entscheidet der Benutzer. NOLAs eigene Werte bleiben.
    """
    if gcat is None:
        return Abgleich(STATUS_KEIN_ABGLEICH)
    von = datetime.fromisoformat(kand["fenster"][0])
    bis = datetime.fromisoformat(kand["fenster"][1] or kand["fenster"][0])
    platz = kand["row"].get("Weltraumbahnhof", "")
    treffer: List[GcatStart] = []
    unzugeordnet: List[GcatStart] = []
    for s in gcat:
        im_fenster = (
            von.date() <= s.zeit.date() <= bis.date()
            if s.nur_datum
            else von - MATCH_SLACK <= s.zeit <= bis + MATCH_SLACK
        )
        if not im_fenster:
            continue
        zuordnung = sites.get(s.site)
        if zuordnung is None:
            unzugeordnet.append(s)
            continue
        kuerzel, land = zuordnung
        if kand["seestart"]:
            if land == kand["nation"]:
                treffer.append(s)
        elif platz in kuerzel:
            treffer.append(s)

    abgleich = Abgleich(STATUS_KEIN_FLUG, treffer)
    if not treffer:
        if unzugeordnet:
            abgleich.hinweise.append(
                "GCAT launches in this window at sites without a row in {}: {}".format(
                    GCAT_SITES_CSV.name,
                    ", ".join("{} ({})".format(s.site, s.rakete) for s in unzugeordnet),
                )
            )
        return abgleich
    if kand["seestart"]:
        abgleich.status = STATUS_SEESTART
    elif len(treffer) == 1 and not treffer[0].nur_datum:
        abgleich.status = STATUS_EINDEUTIG
    else:
        abgleich.status = STATUS_MEHRDEUTIG
    if len(treffer) == 1:
        s = treffer[0]
        land = sites[s.site][1]
        if land != kand["nation"]:
            abgleich.warnungen.append("GCAT site belongs to {}, NOLA says {}.".format(land, kand["nation"]))
        if kand.get("inklination") is not None and s.inklination is not None:
            if abs(kand["inklination"] - s.inklination) > DEVIATION_DEG:
                abgleich.warnungen.append(
                    "Inclination {:.1f}° vs. GCAT {:.1f}°.".format(kand["inklination"], s.inklination))
        if kand.get("azimut") is not None and s.azimut is not None:
            if _winkel(kand["azimut"], s.azimut) > DEVIATION_DEG:
                abgleich.warnungen.append(
                    "Azimuth {:.1f}° vs. GCAT {:.1f}°.".format(kand["azimut"], s.azimut))
    return abgleich


def _norm_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def vehicle_code_for(gcat_rakete: str, vehicles: pd.DataFrame) -> str:
    """
    GCAT-Raketenname -> Kuerzel aus traegersysteme_updated.csv.

    Die Oberstufe hinter '/' zaehlt nicht. Ohne Entsprechung bleibt es leer -
    ein unbekannter Wert wuerde das Dropdown des Tagesbetriebs unterlaufen.
    """
    basis = _norm_name(gcat_rakete.split("/")[0])
    if not basis or vehicles is None or vehicles.empty:
        return ""
    for _, v in vehicles.iterrows():
        namen = {_norm_name(v["Name"]), _norm_name(v["Alternativname englisch"]), _norm_name(v["Abkürzung"])}
        if basis in namen:
            return str(v["Abkürzung"])
    return ""
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Schritt 5: Stand prüfen** (kein Commit)

---

### Aufgabe 6: Importzustand, Wiederaufnahme, Bestätigen und Sammelbestätigung

**Dateien:**
- Ändern: `archiv_import.py`, `test_app.py`

**Schnittstellen:**
- Nutzt: alles aus Aufgaben 2–5, `app.load_archive`, `app.persist_archive`,
  `app.merge_archive`, `app.archive_key`
- Liefert:
  - `load_state(path: Path = IMPORT_JSON) -> Dict` mit `tage, entscheidungen,
    review_bestaetigt, review_ausgeblendet`, und `save_state(state: Dict, path: Path = IMPORT_JSON) -> None`
  - `reevaluate(korpus, state, spaceports, firs, erzwingen: Iterable[str] = ()) -> int`
    (Anzahl neu ausgewerteter Tage)
  - `candidates(state) -> List[Dict]` (entdoppelt, mit `entscheidung` und `ersetzt`)
  - `review_items(state) -> List[Dict]` (entdoppelt nach `schluessel`)
  - `confirm_many(state, auswahl: Sequence[Tuple[Dict, str, str, Optional[GcatStart]]], archiv: Path = app.ARCHIVE_CSV) -> int`
  - `reject(state, key: str) -> None`
  - `bulk_candidates(kandidaten, gcat, sites, vehicles) -> List[Tuple[Dict, str, str, GcatStart]]`
  - `review_launch(state, korpus, event_key, tag_iso, spaceports, firs) -> None`,
    `review_hide(state, event_key) -> None`
  - `totals(state) -> Dict[str, int]` (`usa`, `ausgeblendet`)

**Abnahmekriterien:**
- Ein zweiter Durchlauf mit unverändertem Korpus wertet keinen Tag neu aus und ändert keine Datei.
- Bestätigen schreibt über `merge_archive` mit `entfernt=set()`, also auch für Schlüssel,
  die früher entfernt wurden.
- Ein neuer Kandidat, der eine NOTAM-Kennung mit einem bestätigten Start teilt, aber einen
  anderen Schlüssel hat, wird *aktualisiert* (`ersetzt` = alter Schlüssel). Bestätigt ersetzt
  er die alte Archivzeile.
- Die Sammelbestätigung erfasst nur *unique* ohne Warnung, unentschieden und nicht *aktualisiert*.
- „Space Launch" in der Prüfliste wertet den Tag mit der Bestätigung neu aus. Kommt der
  Fall ohne Startplatz zurück, bleibt er mit `GRUND_OHNE_PLATZ` sichtbar. „Ausblenden"
  entfernt ihn. Ein mehrtägiger Fall steht nur einmal da.
- `archiv_import.py` greift weder auf `manual_notams` noch auf `WORKSPACE_FILE` oder
  `save_workspace` zu.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
zst = ai.load_state(_tmp / "s.json")
kx = {}
ai.merge_korpus(kx, ai.extract_notams("\n\n".join(AI_CN[1:] + [VB_GLEICHER_TAG]), "seite1.html#msg_1")[0])
check("Neuauswertung: ein Tag", ai.reevaluate(kx, zst, sp, fir) == 1)
check("  ... zweiter Lauf wertet nichts neu aus", ai.reevaluate(kx, zst, sp, fir) == 0)
kl = ai.candidates(zst)
check("Kandidatenliste: ein Start", len(kl) == 1 and kl[0]["entscheidung"] is None, kl)
check("  ... US gezaehlt", ai.totals(zst)["usa"] == 1, ai.totals(zst))
sammel = ai.bulk_candidates(kl, gs, sites, veh)
check("Sammelbestaetigung waehlt den eindeutigen", [(k["key"], r, p) for k, r, p, _ in sammel]
      == [(kl[0]["key"], "CZ-2D", "Yaogan 45")], [(r, p) for _, r, p, _ in sammel])
archiv_t = _tmp / "archiv.csv"
check("Bestaetigen schreibt eine Zeile", ai.confirm_many(zst, sammel, archiv_t) == 1)
a1 = app.load_archive(archiv_t)
check("  ... mit Rakete und Payload", (a1.iloc[0]["Trägersystem"], a1.iloc[0]["Payload"]) == ("CZ-2D", "Yaogan 45"),
      a1.iloc[0].to_dict())
check("  ... Quelle im Nebenbestand", zst["entscheidungen"][kl[0]["key"]]["quellen"] == ["seite1.html#msg_1"])
check("  ... danach nicht mehr in der Sammelauswahl", ai.bulk_candidates(ai.candidates(zst), gs, sites, veh) == [])
ai.save_state(zst, _tmp / "s.json")
check("Zustand speichern und laden", ai.load_state(_tmp / "s.json")["entscheidungen"] == zst["entscheidungen"])

# Eine weitere Zone desselben Starts kommt spaeter dazu -> aktualisiert, ersetzt die alte Zeile
# Dritte Zone weiter auf derselben Bahn (Azimut ~189 Grad), noch in ZPKM. Gruppiert
# sie nicht mit dem Start, liegt das an der Geometrie des Beispiels: dann einen
# Punkt naeher an A4632/26 waehlen, nicht die Gruppierung aendern.
dritte = AI_CN[2].replace("A4632/26", "A4640/26").replace(
    "N293700E0980200-N293400E0983400-N284400E0982700-N284800E0975500",
    "N281000E0974500-N280800E0981500-N274000E0981000-N274200E0974000")
ai.merge_korpus(kx, ai.extract_notams(dritte, "seite2.html#msg_9")[0])
ai.reevaluate(kx, zst, sp, fir)
neu_k = [k for k in ai.candidates(zst) if k["entscheidung"] is None]
check("weitere Zone: Kandidat 'aktualisiert'",
      len(neu_k) == 1 and neu_k[0]["ersetzt"] == kl[0]["key"], [(k["key"], k["ersetzt"]) for k in neu_k])
ai.confirm_many(zst, [(neu_k[0], "CZ-2D", "Yaogan 45", None)], archiv_t)
a2 = app.load_archive(archiv_t)
check("  ... ersetzt die alte Archivzeile statt einer zweiten", len(a2) == 1 and "A4640/26" in a2.iloc[0]["NOTAM"],
      a2["NOTAM"].tolist())

# Bestaetigen wirkt auch fuer einen frueher entfernten Schluessel
check("Bestaetigen ignoriert archiv_removed", "entfernt=set()" in (_P(app.APP_DIR) / "archiv_import.py").read_text(encoding="utf-8"))

# Pruefliste: reine Zustandsfunktionen, mit einem synthetischen Tag geprueft
zp = ai.load_state(_tmp / "p.json")
_p = {"event_key": "ek1", "schluessel": "X1/26|2609200000", "notam_id": "X1/26", "tag": "2026-09-20",
      "grund": "Foreign airspace without evidence.", "text": "X1/26 ...", "quellen": ["p"]}
zp["tage"]["2026-09-20"] = {"fingerprint": "f", "kandidaten": [], "pruefliste": [_p], "usa": 0, "ausgeblendet": 0}
zp["tage"]["2026-09-21"] = {"fingerprint": "g", "kandidaten": [], "pruefliste": [dict(_p, tag="2026-09-21")],
                            "usa": 0, "ausgeblendet": 0}
check("Pruefliste: mehrtaegiger Fall nur einmal", len(ai.review_items(zp)) == 1, ai.review_items(zp))
zp["review_bestaetigt"].append("ek1")
check("  ... bestaetigt verschwindet", ai.review_items(zp) == [])
zp["tage"]["2026-09-20"]["pruefliste"] = [dict(_p, grund=ai.GRUND_OHNE_PLATZ)]
check("  ... bestaetigt ohne Startplatz bleibt sichtbar", len(ai.review_items(zp)) == 1)
ai.review_hide(zp, "ek1")
check("  ... Ausblenden entfernt ihn", ai.review_items(zp) == [], ai.review_items(zp))
check("  ... und zaehlt ihn als ausgeblendet", ai.totals(zp)["ausgeblendet"] == 2, ai.totals(zp))

quelle_ai = (_P(app.APP_DIR) / "archiv_import.py").read_text(encoding="utf-8")
check("Archiv-Import fasst die Tageslage nicht an",
      all(w not in quelle_ai for w in ("manual_notams", "WORKSPACE_FILE", "save_workspace", "session_state")))
```

Hinweis zum Test „Pflichtfall Space Launch": Ob ein von Hand bestätigtes Review-NOTAM einen
Startplatz bekommt, hängt an der bestehenden Bestätigungslogik von `analyze_notams`. Der Test
prüft deshalb nur Ausblenden. „Space Launch" prüft Schritt 4 von Aufgabe 8 am echten Fall.
Dort wird das Ergebnis berichtet, ob Kandidat oder „kein Startplatz".

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

- [ ] **Schritt 3: Implementierung**

```python
# --------------------------------------------------------------------------- #
# Importzustand
# --------------------------------------------------------------------------- #
def load_state(path: Path = IMPORT_JSON) -> Dict[str, Any]:
    data = read_json(path)
    return {
        "version": 1,
        "tage": data.get("tage", {}),
        "entscheidungen": data.get("entscheidungen", {}),
        "review_bestaetigt": list(data.get("review_bestaetigt", [])),
        "review_ausgeblendet": list(data.get("review_ausgeblendet", [])),
    }


def save_state(state: Dict[str, Any], path: Path = IMPORT_JSON) -> None:
    write_json_atomic(path, state)


def reevaluate(
    korpus: Dict[str, KorpusNotam],
    state: Dict[str, Any],
    spaceports: pd.DataFrame,
    firs: pd.DataFrame,
    erzwingen: Iterable[str] = (),
) -> int:
    """Wertet nur Tage neu aus, deren NOTAM-Bestand sich geaendert hat (oder erzwungen)."""
    erzwingen = set(erzwingen)
    bestaetigt = set(state["review_bestaetigt"])
    ausgeblendet = set(state["review_ausgeblendet"])
    neu = 0
    for tag, notams in sorted(bundle_days(korpus).items()):
        iso = tag.isoformat()
        fp = day_fingerprint(notams)
        alt = state["tage"].get(iso)
        if alt and alt.get("fingerprint") == fp and iso not in erzwingen:
            continue
        ergebnis = analyze_day(tag, notams, spaceports, firs, bestaetigt, ausgeblendet)
        state["tage"][iso] = {
            "fingerprint": fp,
            "kandidaten": ergebnis.kandidaten,
            "pruefliste": ergebnis.pruefliste,
            "usa": ergebnis.usa,
            "ausgeblendet": ergebnis.ausgeblendet,
        }
        neu += 1
    return neu


def candidates(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Alle Kandidaten, je Schluessel einmal, mit Entscheidung und Ersatzvermerk."""
    entscheidungen = state["entscheidungen"]
    bestaetigte_ids = {
        key: set(e.get("notam_ids", []))
        for key, e in entscheidungen.items()
        if e.get("status") == "confirmed"
    }
    gesehen: Dict[str, Dict[str, Any]] = {}
    for iso in sorted(state["tage"]):
        for k in state["tage"][iso]["kandidaten"]:
            if k["key"] in gesehen:
                continue
            eintrag = dict(k)
            eintrag["entscheidung"] = entscheidungen.get(k["key"])
            eintrag["ersetzt"] = None
            if eintrag["entscheidung"] is None:
                for alt_key, ids in bestaetigte_ids.items():
                    if alt_key != k["key"] and ids & set(k["notam_ids"]):
                        eintrag["ersetzt"] = alt_key
                        break
            gesehen[k["key"]] = eintrag
    return list(gesehen.values())


def review_items(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Offene Prueffaelle, je NOTAM einmal (mehrtaegige stehen sonst mehrfach da)."""
    ausgeblendet = set(state["review_ausgeblendet"])
    bestaetigt = set(state["review_bestaetigt"])
    gesehen: Dict[str, Dict[str, Any]] = {}
    for iso in sorted(state["tage"]):
        for p in state["tage"][iso]["pruefliste"]:
            if p["event_key"] in ausgeblendet or p["schluessel"] in gesehen:
                continue
            # Bestaetigt, aber ohne Startplatz zurueckgekommen: bleibt sichtbar.
            if p["event_key"] in bestaetigt and p["grund"] != GRUND_OHNE_PLATZ:
                continue
            gesehen[p["schluessel"]] = p
    return list(gesehen.values())


def totals(state: Dict[str, Any]) -> Dict[str, int]:
    return {
        "usa": sum(t.get("usa", 0) for t in state["tage"].values()),
        "ausgeblendet": sum(t.get("ausgeblendet", 0) for t in state["tage"].values()),
    }


def confirm_many(
    state: Dict[str, Any],
    auswahl: Sequence[Tuple[Dict[str, Any], str, str, Optional[GcatStart]]],
    archiv: Path = app.ARCHIVE_CSV,
) -> int:
    """
    Schreibt bestaetigte Kandidaten ins Startarchiv - in einem Schreibvorgang.

    Bestaetigen ist eine ausdrueckliche Handlung: ein frueher im Optionsmenue
    entfernter Schluessel wird deshalb nicht gefiltert (entfernt=set()).
    Ein 'aktualisierter' Kandidat ersetzt die Zeile seines Vorgaengers.
    """
    if not auswahl:
        return 0
    bestand = app.load_archive(archiv)
    ersetzt = {k["ersetzt"] for k, _, _, _ in auswahl if k.get("ersetzt")}
    if ersetzt and not bestand.empty:
        bestand = bestand[
            [app.archive_key(dict(r)) not in ersetzt for _, r in bestand.iterrows()]
        ].reset_index(drop=True)
    zeilen = []
    for kand, rakete, payload, treffer in auswahl:
        row = dict(kand["row"])
        row["Trägersystem"] = rakete
        row["Payload"] = payload
        zeilen.append(row)
        state["entscheidungen"][kand["key"]] = {
            "status": "confirmed",
            "rakete": rakete,
            "payload": payload,
            "gcat": treffer.tag if treffer else "",
            "notam_ids": list(kand["notam_ids"]),
            "quellen": list(kand["quellen"]),
        }
        if kand.get("ersetzt"):
            state["entscheidungen"][kand["ersetzt"]] = {"status": "replaced", "durch": kand["key"]}
    app.persist_archive(archiv, app.merge_archive(bestand, zeilen, entfernt=set()))
    return len(zeilen)


def reject(state: Dict[str, Any], key: str) -> None:
    state["entscheidungen"][key] = {"status": "discarded"}


def bulk_candidates(
    kandidaten: Sequence[Dict[str, Any]],
    gcat: Optional[List[GcatStart]],
    sites: Dict[str, Tuple[List[str], str]],
    vehicles: pd.DataFrame,
) -> List[Tuple[Dict[str, Any], str, str, GcatStart]]:
    """Nur unentschiedene, eindeutige Kandidaten ohne Warnung und ohne Ersatzvermerk."""
    auswahl = []
    for k in kandidaten:
        if k["entscheidung"] is not None or k["ersetzt"]:
            continue
        abgleich = match_candidate(k, gcat, sites)
        if abgleich.status != STATUS_EINDEUTIG or abgleich.warnungen:
            continue
        s = abgleich.treffer[0]
        auswahl.append((k, vehicle_code_for(s.rakete, vehicles), s.nutzlast, s))
    return auswahl


def review_launch(
    state: Dict[str, Any],
    korpus: Dict[str, KorpusNotam],
    event_key: str,
    tag_iso: str,
    spaceports: pd.DataFrame,
    firs: pd.DataFrame,
) -> None:
    """'Space Launch' aus der Pruefliste: der Tag wird mit der Bestaetigung neu ausgewertet."""
    if event_key not in state["review_bestaetigt"]:
        state["review_bestaetigt"].append(event_key)
    reevaluate(korpus, state, spaceports, firs, erzwingen=[tag_iso])


def review_hide(state: Dict[str, Any], event_key: str) -> None:
    if event_key not in state["review_ausgeblendet"]:
        state["review_ausgeblendet"].append(event_key)
    for tag in state["tage"].values():
        vorher = len(tag["pruefliste"])
        tag["pruefliste"] = [p for p in tag["pruefliste"] if p["event_key"] != event_key]
        tag["ausgeblendet"] = tag.get("ausgeblendet", 0) + (vorher - len(tag["pruefliste"]))
```

- [ ] **Schritt 4: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Schritt 5: Stand prüfen** (kein Commit)

---

### Aufgabe 7: Reiter „Archive Import" und Ausblenden in der öffentlichen Fassung

**Dateien:**
- Ändern: `app.py` (Funktion `_reference_dialog`, neue Funktionen `is_public_deployment`,
  `_archive_import_tab`), `test_app.py`

**Schnittstellen:**
- Nutzt: alle öffentlichen Funktionen aus `archiv_import.py`, `vehicle_options`,
  `vehicle_label`, `nation_label`
- Liefert: `is_public_deployment(app_dir: Path = APP_DIR) -> bool`

**Abnahmekriterien:**
- Lokal erscheint ein sechster Reiter „Archive Import". Unter `/mount/src/…` (Streamlit
  Community Cloud) fehlt er.
- Der Reiter importiert `archiv_import` erst beim Aufruf.
- Kein `unsafe_allow_html` im Reiter. NOTAM-Texte erscheinen über `st.code`.
- Eine `ImportStateError` wird angezeigt, ohne dass eine Datei geschrieben wird.
- Ein Upload mit mehreren Dateien, Bericht, Kandidaten je Jahr, Sammelbestätigung,
  Einzelbestätigung (Treffer, Rakete, Payload), Verwerfen und Prüfliste mit
  „Space Launch" und „Hide" funktionieren.

- [ ] **Schritt 1: Fehlschlagende Tests schreiben**

```python
check("oeffentliche Fassung erkannt", app.is_public_deployment(_P("/mount/src/notam-parser")))
check("lokal nicht oeffentlich", not app.is_public_deployment(_P("/Users/x/NOTAM Parser")))
quelle_app = (_P(app.APP_DIR) / "app.py").read_text(encoding="utf-8")
import inspect as _inspect
tab_src = _inspect.getsource(app._archive_import_tab)
check("Reiter ohne unsafe_allow_html", "unsafe_allow_html" not in tab_src)
check("Reiter importiert das Modul erst beim Aufruf",
      "import archiv_import" in tab_src and "\nimport archiv_import" not in quelle_app)
check("Reiter nur ausserhalb der oeffentlichen Fassung",
      "is_public_deployment()" in _inspect.getsource(app._reference_dialog))
```

- [ ] **Schritt 2: Tests laufen lassen, Fehlschlag bestätigen**

- [ ] **Schritt 3: `is_public_deployment` in `app.py` neben `ARCHIVE_CSV` einfügen**

```python
def is_public_deployment(app_dir: Path = APP_DIR) -> bool:
    """
    Laeuft die Anwendung als oeffentliche Fassung?

    Streamlit Community Cloud legt die Repositories unter /mount/src ab. Dort
    darf der Archiv-Import nicht erscheinen, solange es keinen Demo-Modus gibt.
    """
    return Path(app_dir).resolve().parts[:3] == ("/", "mount", "src")
```

- [ ] **Schritt 4: `_reference_dialog` erweitern**

Die Reiterliste wird um einen sechsten Eintrag ergänzt, aber nur außerhalb der öffentlichen
Fassung. Ersetze die Zeile `tab_sp, tab_fir, tab_veh, tab_arc, tab_sea = st.tabs(` samt
Liste und die `with`-Blöcke durch:

```python
    titel = [
        "Launch Sites ({})".format(len(spaceports)),
        "ICAO FIR / ACC ({})".format(len(firs)),
        "Launch Vehicles ({})".format(len(vehicles)),
        "Launch Archive ({})".format(len(load_archive(ARCHIVE_CSV))),
        "Sea Launches ({})".format(len(load_sea_launches(SEA_LAUNCH_CSV))),
    ]
    mit_import = not is_public_deployment()
    if mit_import:
        titel.append("Archive Import")
    reiter = st.tabs(titel)
    with reiter[0]:
        _spaceport_editor(spaceports)
    with reiter[1]:
        _fir_editor(firs)
    with reiter[2]:
        _vehicle_editor(vehicles)
    with reiter[3]:
        _archive_editor()
    with reiter[4]:
        _sea_launch_editor()
    if mit_import:
        with reiter[5]:
            _archive_import_tab(spaceports, firs, vehicles)
```

- [ ] **Schritt 5: `_archive_import_tab` direkt nach `_archive_editor` einfügen**

```python
def _archive_import_tab(
    spaceports: pd.DataFrame, firs: pd.DataFrame, vehicles: pd.DataFrame
) -> None:
    """
    Archiv-Import historischer NOTAMs (China, Russland, Indien, Iran, Nordkorea).

    Getrennt von der Tageslage: nichts hier beruehrt die eingefuegten NOTAMs
    oder notam_workspace.json. Ins Archiv kommt nur, was bestaetigt wird.
    """
    import archiv_import as ai  # erst hier - siehe Modulkopf von archiv_import

    try:
        korpus = ai.load_korpus()
        zustand = ai.load_state()
    except ai.ImportStateError as exc:
        st.error(str(exc))
        return
    st.caption(
        "Historic launches of China, Russia, India, Iran and North Korea. "
        "Save NSF thread pages in your browser (or copy a whole page) and import "
        "them here. Detection is the same as in daily use; nothing is written to "
        "the archive until you confirm it. US launches are left out."
    )

    with st.form("archiv_import_form", clear_on_submit=True):
        dateien = st.file_uploader(
            "Forum pages", type=["html", "htm", "txt"], accept_multiple_files=True
        )
        text = st.text_area("Or paste a whole page", height=120)
        los = st.form_submit_button("Import", type="primary")
    if los:
        bericht = ai.ingest(korpus, [(d.name, d.getvalue()) for d in dateien or []], text or "")
        bericht.tage_ausgewertet = ai.reevaluate(korpus, zustand, spaceports, firs)
        ai.save_korpus(korpus)
        ai.save_state(zustand)
        st.session_state["archiv_import_bericht"] = bericht
    bericht = st.session_state.get("archiv_import_bericht")
    if bericht is not None:
        summen = ai.totals(zustand)
        st.info(
            "{} file(s) · {} new NOTAM(s) · {} duplicate(s) · {} not usable · "
            "{} day(s) analysed · {} US case(s) left out in total · {} hidden in total".format(
                bericht.dateien, bericht.notams_neu, bericht.dubletten, bericht.unbrauchbar,
                bericht.tage_ausgewertet, summen["usa"], summen["ausgeblendet"],
            )
        )
        for fehler in bericht.fehler:
            st.warning(fehler)

    links, rechts = st.columns([3, 1])
    gcat, gcat_status = ai.load_gcat(refresh=rechts.button("Refresh launch list"))
    links.caption(gcat_status)
    sites = ai.load_gcat_sites()

    kandidaten = ai.candidates(zustand)
    offen = [k for k in kandidaten if k["entscheidung"] is None]
    st.subheader("Candidates ({} open of {})".format(len(offen), len(kandidaten)))
    sammel = ai.bulk_candidates(kandidaten, gcat, sites, vehicles)
    if st.button(
        "Confirm all unique matches ({})".format(len(sammel)), disabled=not sammel
    ):
        ai.confirm_many(zustand, sammel)
        ai.save_state(zustand)
        st.rerun(scope="app")

    jahre = sorted({k["tag"][:4] for k in offen}, reverse=True)
    if jahre:
        jahr = st.selectbox("Year", jahre, key="archiv_import_jahr")
        for k in [k for k in offen if k["tag"].startswith(jahr)][:40]:
            _archive_import_candidate(ai, zustand, k, gcat, sites, vehicles)

    pruef = ai.review_items(zustand)
    st.subheader("Review list ({})".format(len(pruef)))
    for p in pruef[:40]:
        with st.expander("{} · {} · {}".format(p["tag"], p["notam_id"], p["grund"][:80])):
            st.code(p["text"], language=None)
            st.caption("Source: " + ", ".join(p["quellen"]))
            a, b = st.columns(2)
            if a.button("Space Launch", key="ai_sl_" + p["event_key"]):
                ai.review_launch(zustand, korpus, p["event_key"], p["tag"], spaceports, firs)
                ai.save_state(zustand)
                st.rerun(scope="app")
            if b.button("Hide", key="ai_hide_" + p["event_key"]):
                ai.review_hide(zustand, p["event_key"])
                ai.save_state(zustand)
                st.rerun(scope="app")


def _archive_import_candidate(
    ai: Any,
    zustand: Dict[str, Any],
    k: Dict[str, Any],
    gcat: Any,
    sites: Dict[str, Any],
    vehicles: pd.DataFrame,
) -> None:
    """Ein Kandidat mit Vorschlag, Auswahl und den beiden Entscheidungen."""
    abgleich = ai.match_candidate(k, gcat, sites)
    row = k["row"]
    kopf = "{} {} · {} · {} · {} · {}".format(
        row["Startdatum"], row["Startzeit"], nation_label(k["nation"]),
        row["Weltraumbahnhof"] or "sea", row["Orbit"],
        "updated" if k["ersetzt"] else abgleich.status,
    )
    with st.expander(kopf):
        st.caption("NOTAM: {} · Source: {}".format(row["NOTAM"], ", ".join(k["quellen"])))
        for w in abgleich.warnungen:
            st.warning(w)
        for h in abgleich.hinweise:
            st.caption(h)
        treffer = None
        if abgleich.treffer:
            beschriftung = [
                "{} · {} · {} · {}".format(s.tag, s.zeit.strftime("%d.%m.%Y %H:%M"), s.rakete, s.nutzlast)
                for s in abgleich.treffer
            ] + ["none of these"]
            wahl = st.radio("GCAT", beschriftung, key="ai_gcat_" + k["key"])
            if wahl != "none of these":
                treffer = abgleich.treffer[beschriftung.index(wahl)]
        vorschlag = ai.vehicle_code_for(treffer.rakete, vehicles) if treffer else ""
        optionen = vehicle_options(vehicles, k["nation"])
        rakete = st.selectbox(
            "Launch vehicle",
            optionen,
            index=optionen.index(vorschlag) if vorschlag in optionen else 0,
            format_func=lambda c: vehicle_label(c, vehicles),
            key="ai_veh_{}_{}".format(k["key"], treffer.tag if treffer else ""),
        )
        if treffer and not vorschlag and treffer.rakete:
            st.caption("GCAT vehicle '{}' has no entry in the vehicle reference.".format(treffer.rakete))
        payload = st.text_input(
            "Payload", value=treffer.nutzlast if treffer else "",
            key="ai_pay_{}_{}".format(k["key"], treffer.tag if treffer else ""),
        )
        a, b = st.columns(2)
        if a.button("Confirm", key="ai_ok_" + k["key"], type="primary"):
            wert = "" if rakete == VEHICLE_SEPARATOR else rakete
            ai.confirm_many(zustand, [(k, wert, payload.strip(), treffer)])
            ai.save_state(zustand)
            st.rerun(scope="app")
        if b.button("Discard", key="ai_no_" + k["key"]):
            ai.reject(zustand, k["key"])
            ai.save_state(zustand)
            st.rerun(scope="app")
```

- [ ] **Schritt 6: Tests laufen lassen, Erfolg bestätigen**

- [ ] **Schritt 7: In der App prüfen** (Vorschau-Werkzeuge, nicht Bash). Server über
  `.claude/launch.json` mit `.venv/bin/python -m streamlit run app.py` (Port 8501) starten.
  Dann: Optionsmenü öffnen, Reiter „Archive Import" aufrufen, die drei chinesischen
  Beispiel-NOTAMs als Text einfügen, „Import" drücken, Bericht und Kandidaten prüfen.
  Bildschirmfoto zum Nachweis. **Vorher** `startarchiv_updated.csv`,
  `archiv_import.json` und `archiv_korpus.json` sichern und danach zurückspielen. Der
  Probelauf darf das echte Archiv nicht verändern.

- [ ] **Schritt 8: Stand prüfen** (kein Commit)

---

### Aufgabe 8: Gegenprobe Tageslage und Dokumentation

**Dateien:**
- Ändern: `test_app.py`, `docs/projektplan.html`, `STATUS.md`, `README.md`
- Artifact: `https://claude.ai/artifact/SR4YwYSqPceEBzsiPwVPhe`

**Abnahmekriterien:**
- Die Tageslage aus der echten FNS-Datei ist vor und nach einem Import-Durchlauf identisch
  (Events, Status, Startplätze).
- Der Projektplan hat einen neuen Schritt und einen Ast mit echten Funktionsnamen. Die
  Kennzahlen stimmen mit `STATUS.md` überein.
- Das Artifact ist erst gelesen und dann mit `url` veröffentlicht worden.

- [ ] **Schritt 1: Gegenprobe als Test**

```python
import glob as _glob
_fns = sorted(_glob.glob(str(_P(app.APP_DIR) / "fnsNotams_*.xls")))
if _fns:
    def _lage():
        df = app.read_notam_table(_fns[-1], _fns[-1])
        ev, _ = app.analyze_notams(df, sp, fir, min_confidence="MEDIUM")
        return [(e.notam_id, e.status, e.spaceport_code, e.nation) for e in ev]
    vorher = _lage()
    zg = ai.load_state(_tmp / "g.json")
    kg = {}
    ai.merge_korpus(kg, ai.extract_notams("\n\n".join(AI_CN), "g")[0])
    ai.reevaluate(kg, zg, sp, fir)
    check("Tageslage nach Archiv-Import unveraendert", _lage() == vorher)
else:
    check("Tageslage-Gegenprobe (FNS-Datei fehlt - uebersprungen)", True)
```

- [ ] **Schritt 2: Volle Testsuite laufen lassen**

Run: `.venv/bin/python test_app.py 2>&1 | grep -E "FAIL|ERGEBNIS"`
Erwartet: `ERGEBNIS: ALLE TESTS BESTANDEN`. Neue Testzahl notieren:
`.venv/bin/python test_app.py | grep -c "PASS"`.

- [ ] **Schritt 3: Projektplan nachtragen** (`docs/projektplan.html`, Daten in `STEPS` und `TREE`)
  - In `STEPS` einen neuen Schritt mit nächster freier Nummer, Name „Archiv-Import",
    Überschrift „Historische NOTAMs aus Forenseiten ins Startarchiv",
    Beschreibung (Stapelimport, Tagesbündel, GCAT-Vorschläge, Bestätigung, USA ausgenommen)
    und Ergebnis.
  - In `TREE` unter „Referenzdaten und Archiv" einen Ast „Archiv-Import" mit `s` auf den
    neuen Schritt und Unterästen mit `f`:
    `extract_notams, texts_from_upload`; `bundle_days, analyze_day`;
    `parse_gcat, match_candidate, vehicle_code_for`; `confirm_many, bulk_candidates`;
    `_archive_import_tab`; Referenz `gcat_startplaetze.csv`.
  - Unter „Offene Punkte" ergänzen: „Echte NSF-Seite als Testfixture" (der Test nutzt bisher
    nachgebautes SMF-Markup) und „Archivspalte Quelle" (die Quelle steht vorerst im
    Nebenbestand).
  - Kopfkennzahlen (Zeilen, Tests, Startplätze, FIRs, Trägersysteme) aus `STATUS.md` übernehmen.

- [ ] **Schritt 4: Prüflisten-Fall „Space Launch" am echten Beispiel**
  Einen Prüflisten-Fall aus einer echten gespeicherten Seite in der App mit „Space Launch"
  bestätigen. Berichten, ob er Kandidat wird oder mit „no launch site" zurückkommt. Das
  Ergebnis kommt in `STATUS.md`.

- [ ] **Schritt 5: `STATUS.md` und `README.md`**
  - `STATUS.md`: Kopfzeile (Zeilen von `app.py`, Testzahl). Tabellenzeile „Archiv-Import"
    (Stapelimport von NSF-Seiten, Tagesbündel, GCAT-Vorschläge, Sammelbestätigung, USA
    ausgenommen, lokal). Unter „Bekannte Grenzen": NSF nicht automatisch abrufbar
    (Cloudflare), kopierter Text kann zitierte NOTAMs enthalten (entdoppelt, aber nicht
    erkannt).
  - `README.md`: kurzer Abschnitt „Archive Import" mit Ablauf in vier Schritten (Seiten
    speichern → hochladen → eindeutige bestätigen → Prüfliste) und GCAT-Quellenvermerk.

- [ ] **Schritt 6: Artifact aktualisieren**
  Artifact `https://claude.ai/artifact/SR4YwYSqPceEBzsiPwVPhe` erst lesen (`action: "read"`).
  Dann die aktualisierte Seite **ohne** `<!doctype>`/`<html>`/`<head>`/`<body>`-Hülle mit
  `url` veröffentlichen.

- [ ] **Schritt 7: Stand prüfen und berichten** (kein Commit; geänderte Dateien auflisten)

---

## Abdeckung der Spec

| Spec-Anforderung | Aufgabe |
|---|---|
| Nur fünf Nationen, USA nach der Erkennung gezählt | 3 (Filter), 6 (`totals`), 7 (Bericht) |
| Getrennt von der Tageslage | 6 (Quelltextprüfung), 8 (Gegenprobe) |
| Dieselbe Erkennung, MEDIUM | 3 |
| Tagesbündel, höchstens 14 Tage | 3 |
| Kandidaten statt direkt schreiben, Quelle mitführen | 3, 6 |
| Extraktion: Beiträge, Zitate, Blockende, nicht verwertbar, Dubletten, Datierung aus B) | 1, 2 |
| NOTAMR/NOTAMC wie im Tagesbetrieb | 3 (Durchreichen an `analyze_notams`, keine eigene Logik) |
| GCAT-Cache, Knopf, Quellenvermerk, `.gitignore` | 2, 4, 7 |
| `gcat_startplaetze.csv`, Hinweis bei unbekanntem Platz | 4, 5 |
| Paarung ±30 min, nur Tagesdatum, Seestart, kein Flug | 5 |
| Abweichung > 10°, Nation, keine Übernahme von Bahnwerten | 5 |
| Bedienung: Mehrfach-Upload, Bericht, Jahrestabelle, Sammel- und Einzelbestätigung, Rakete gegen Referenz, Prüfliste | 7 |
| Bestätigen trotz `archiv_removed` | 6 |
| Wiederaufnahme, „aktualisiert" ersetzt die alte Zeile | 6 |
| Reiter in der öffentlichen Fassung ausgeblendet | 7 |
| Speicherung lokal, atomar, unlesbare JSON bleibt unangetastet | 2 |
| Code-Aufbau: eigenes Modul, kein Zirkelimport | 1, 7 |
| Sicherheit: nur lesen, kein `unsafe_allow_html`, Größengrenzen, feste URL | 1, 2, 4, 7 |
| Tests laut Spec §8 | 1–8 |
| Projektplan, `STATUS.md`, Artifact | 8 |

**Abweichung von der Spec, offen benannt:** Spec §8 verlangt einen „gekürzten echten
NSF-Seitenausschnitt". NSF ist für automatische Abrufe gesperrt, deshalb nutzt Aufgabe 1
nachgebautes SMF-Markup. Ersetzt wird es, sobald der Benutzer eine echte Seite gespeichert
hat. Bis dahin steht das unter „Offene Punkte" (Aufgabe 8, Schritt 3).

---

## Nachtrag vom 02.10.2026: Der Archivschlüssel trägt die Identität nicht

Nachgetragen aus einer parallelen Sitzung. Dieser Plan baut die Identität der
Importkandidaten auf `app.archive_key` — in `kandidaten[…]["key"]`, im Vergleich
`kandidaten[0]["key"] == app.archive_key(…)` und im `ersetzt`-Mechanismus
(`[app.archive_key(dict(r)) not in ersetzt for _, r in bestand.iterrows()]`). Damit erbt er,
was dieser Schlüssel leistet und was nicht.

### Was der Schlüssel enthielt und warum das falsch war

```
archive_key = Startdatum | Weltraumbahnhof | sortierte NOTAM-Kennungen
```

Der Startplatz ist eine **Eigenschaft** des Starts, nicht seine **Identität** — und er ändert
sich, wenn die Erkennung besser wird. Belegt im Bestand:

| Zeile | NOTAM | Platz | Inkl. |
|---|---|---|---|
| 10 | `F0511/26` | WSLC | 95,0 |
| 11 | `F0511/26, A0443/26` | WSLC | 94,2 |
| 12 | `A0465/26, A0466/26, F0511/26, …` | **SEA-21N112E** | 97,6 |

Drei Zeilen, ein Start. `F0511/26` steht in allen drei. Dasselbe für den 11.02. (`F0494/26`
dreimal). Von 16 Archivzeilen sind **5 falsch**: eine sachlich (ein nordkoreanischer Start,
der keiner war) und vier als überholte Dubletten.

„Aktualisiert statt verdoppelt" funktionierte also nur, solange die Analyse ihre Meinung
nie ändert.

### Was am 02.10.2026 behoben wurde

Der Startplatz ist aus dem Schlüssel entfernt:

```
archive_key = Startdatum | sortierte NOTAM-Kennungen
```

Gemessen am Bestand: 16 Zeilen ergeben mit und ohne Startplatz je 16 Schlüssel — **keine
bestehende Zeile fällt zusammen**. Behoben sind damit zwei Fälle:

- Die Seestart-Ableitung verschob einen Start von `WSLC` auf `SEA-21N112E`.
- Eine von Hand gesetzte Pad-Wahl verschiebt ihn von `WSLC` auf `HAIN` (neu seit heute, siehe
  „Zwei Startplätze an einem Ort" in der README). Das erzeugte vor der Korrektur
  nachweislich eine zweite Zeile mit identischen NOTAM-Kennungen.

Gespeicherte Löschschlüssel werden beim Laden des Arbeitsstands umgestellt
(`migrate_archive_keys`, dreiteilig → zweiteilig). Ohne das wären von Hand gelöschte
Archivzeilen zurückgekommen. Abschnitt 89 der Tests hält beides fest.

**Für diesen Plan heißt das: nichts zu ändern.** Er importiert `app` und baut nichts nach,
also erbt er die Korrektur. Die Aussage „`aktualisiert` ersetzt die alte Zeile" trägt jetzt
auch dann, wenn sich zwischen zwei Durchläufen der erkannte Startplatz verschiebt.

### Was offen bleibt — und beim Import stärker wiegt

Wird die **Gruppierung** besser, wächst die Kennungsmenge (`F0511/26` → `F0511/26, A0443/26`
→ drei Kennungen) und der Schlüssel ändert sich trotzdem. Genau so sind die vier Dubletten
oben entstanden.

Im Tagesbetrieb betrifft das eine Handvoll Zeilen. **Bei 500–650 importierten Starts wiegt
es deutlich schwerer**, und zwar aus einem Grund, der diesem Plan eigen ist: ein Massenimport
wird mit verbesserter Erkennung **wiederholt**. Jede Verbesserung der Gruppierung — und
dieser Plan verbessert sie nicht, aber der Tagesbetrieb tut es laufend — verschiebt dann
einen Teil der Schlüssel, und der `ersetzt`-Mechanismus findet die alte Zeile nicht mehr.

**Vorschlag, noch nicht entschieden:** Statt auf Gleichheit zu prüfen, über
**Kennungs-Überschneidung** suchen — teilt eine neue Zeile mindestens eine NOTAM-Kennung mit
einer vorhandenen, ist es derselbe Start. Das löst den Fall nachweislich: `F0511/26` steht in
allen drei Zeilen.

Geprüft werden muss dabei:

- **Der Abbruch-Fall bleibt getrennt.** Die Zeilen vom 11.02. (`F0494/26`, `A0433/26`,
  `A0430/26`, `A0436/26`) und vom 12.02. (`F0511/26`, `A0443/26`, `A0465/26`, `A0466/26`)
  teilen **keine** Kennung. Überschneidungs-Suche führt sie also nicht zusammen — richtig,
  denn beide Tage hatten echte Luftraumsperrungen.
- **Ein Datumsschutz** gegen entfernte Treffer, falls eine Kennung je wiederverwendet wird.
- **`archiv_removed`** müsste mitziehen: Löschschlüssel sind dann keine exakten Schlüssel mehr.

Das ändert die Semantik von `merge_archive` und ist deshalb eine Entscheidung des Benutzers,
keine Nacharbeit. Bis sie getroffen ist, bleibt der Defekt bestehen — benannt im Docstring
von `archive_key` und in `STATUS.md`.
