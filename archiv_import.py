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
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd

import app

KORPUS_JSON = app.APP_DIR / "archiv_korpus.json"
IMPORT_JSON = app.APP_DIR / "archiv_import.json"
GCAT_SITES_CSV = app.APP_DIR / "gcat_startplaetze.csv"
GCAT_VEHICLES_CSV = app.APP_DIR / "gcat_traegersysteme.csv"
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
#: Nachlauf eines Tagesbuendels in den Folgetag (UTC), siehe bundle_days.
BUNDLE_TAIL = time(6, 0)
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
    Kennung beginnen, aber kein E)/Q) oder kein lesbares B) haben. Ebenfalls als nicht
    verwertbar zaehlen !FDC- und NAVAREA-Bloecke (ohne ICAO-Kennung). Sonstiger
    Vortext ohne Kennung ist Forengespraech und zaehlt nicht.
    """
    gefunden: List[KorpusNotam] = []
    unbrauchbar = 0
    for teil in app.RE_PASTE_BOUNDARY.split(app.normalize_pasted_text(text)):
        if not teil.strip():
            continue
        kopf = _RE_BLOCK_ID.match(teil)
        if not kopf:
            if teil.lstrip().upper().startswith(("!", "NAVAREA")):
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
        self._stack: List[Tuple[str, str]] = []  # (Tag, Rolle: "", "post", "skip")
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
        # Ein Endtag ohne passendes offenes Tag wird ignoriert; sonst wuerde er
        # den ganzen Stapel (Beitrag, Zitat) vorzeitig schliessen.
        if any(offen == tag for offen, _ in self._stack):
            while self._stack:
                offen, rolle = self._stack.pop()
                if rolle == "skip":
                    self._verdeckt -= 1
                elif rolle == "post":
                    self._flush_post()
                if offen == tag:
                    break
        if tag in self.BLOCK and not self._verdeckt:
            self._ziel().append("\n")

    def handle_data(self, data: str) -> None:
        if not self._verdeckt:
            self._ziel().append(data)

    def _flush_post(self) -> None:
        if self._post is not None:
            self.beitraege.append((self._post_id, "".join(self._post)))
            self._post = None

    def close(self) -> None:
        super().close()
        # Abgeschnittene Seite: ein nie geschlossener Beitrag bleibt erhalten.
        self._flush_post()


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
