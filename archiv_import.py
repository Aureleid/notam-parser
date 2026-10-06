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
import re
import types
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

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


def _write_bytes_atomic(path: Path, daten: bytes) -> None:
    """Schreibt atomar - die eine Umsetzung steht in app._write_bytes_atomic."""
    app._write_bytes_atomic(path, daten)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Schreibt JSON atomar (siehe _write_bytes_atomic)."""
    _write_bytes_atomic(path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def load_korpus(path: Path = KORPUS_JSON) -> Dict[str, KorpusNotam]:
    data = read_json(path)
    korpus: Dict[str, KorpusNotam] = {}
    try:
        for e in data.get("notams", []):
            quellen = e.get("quellen", [])
            felder = [e["notam_id"], e["b"], e["text"]]
            if not all(isinstance(v, str) for v in felder) or not isinstance(quellen, list) \
                    or not all(isinstance(q, str) for q in quellen):
                raise TypeError("wrong value type in a NOTAM entry")
            n = KorpusNotam(felder[0], felder[1], felder[2], list(quellen))
            korpus[n.schluessel] = n
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ImportStateError(
            "{} has an unexpected structure ({!r}). It is left untouched - please check it.".format(
                path.name, exc)
        ) from exc
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
            msg = str(exc)  # texts_from_upload nennt den Dateinamen schon selbst
            bericht.fehler.append(msg if msg.startswith(name) else "{}: {}".format(name, msg))
    if eingefuegt.strip():
        paare.append(("pasted {}".format(datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%MZ")), eingefuegt))
    for quelle, text in paare:
        notams, unbrauchbar = extract_notams(text, quelle)
        bericht.unbrauchbar += unbrauchbar
        neu, dup = merge_korpus(korpus, notams)
        bericht.notams_neu += neu
        bericht.dubletten += dup
    return bericht


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
    liegt - so wie in der taeglichen FNS-Datei. Hoechstens MAX_BUNDLE_DAYS,
    dazu der Nachlauf bis BUNDLE_TAIL des Folgetags.
    """
    buendel: Dict[date, List[KorpusNotam]] = defaultdict(list)
    for n in korpus.values():
        von, bis = _fenster(n)
        if von is None:
            continue
        start = von.date()
        ende = bis.date() if bis is not None and bis >= von else start
        ende = min(ende, start + timedelta(days=MAX_BUNDLE_DAYS - 1))
        # Nachlauf: ein Start ueber Mitternacht (UTC) soll im Buendel seines
        # Starttags vollstaendig liegen. Was vor BUNDLE_TAIL beginnt, gehoert
        # deshalb auch in das Buendel des Vortags.
        if von.time() < BUNDLE_TAIL:
            start -= timedelta(days=1)
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
    """
    Ergebnis eines Tagesbuendels.

    Einheiten der Zaehler: `usa` zaehlt US-Starts (einen je Gruppe) plus lose
    US-Meldungen ohne Gruppe (eine je NOTAM). `ausgeblendet` zaehlt NOTAMs.
    Beide nur fuer NOTAMs bzw. Gruppen, die an diesem Tag beginnen.
    """

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

    def eigener_tag(dt: Optional[datetime]) -> bool:
        # Gezaehlt wird nur im Buendel des eigenen Tages - mehrtaegige Meldungen
        # und der Nachlauf legen dasselbe NOTAM in mehrere Buendel.
        return dt is not None and _utc(dt).date() == tag

    ergebnis.ausgeblendet = sum(
        1 for e in events if e.row_index in weg and eigener_tag(e.valid_from)
    )
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
            ergebnis.usa += 1 if eigener_tag(g.window_from) else 0
            belegt |= set(g.row_indices) | set(g.advance_row_indices)
            continue
        if not g.spaceport_code:
            ohne_platz |= {e.row_index for e in ok}
            continue
        if g.nation not in IMPORT_NATIONS:
            continue
        # Ausgeblendete Mitglieder gehoeren weder in die Zeile noch in den Schluessel.
        # Start und Fenster nur aus den uebrigen Mitgliedern (Kopie, app-Objekt bleibt unberuehrt).
        rest = [e for e in ok if e.valid_from is not None]
        if weg & set(g.row_indices) and rest:
            g = replace(
                g,
                window_from=min(e.valid_from for e in rest),
                window_to=max(e.valid_to or e.valid_from for e in rest),
            )
        row = app.archive_row(g, [e for e in events if e.row_index not in weg])
        belegt |= set(g.row_indices) | set(g.advance_row_indices)
        if row["Startdatum"] != tag_text:
            continue  # gehoert in das Buendel seines eigenen Starttags
        mitglieder = sorted((set(g.row_indices) | set(g.advance_row_indices)) - weg)
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
            ergebnis.usa += 1 if eigener_tag(e.valid_from) else 0
            continue
        if not eigener_tag(e.valid_from):
            continue  # Pruefposten nur im Buendel seines eigenen Tages
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


def drop_subsumed(kandidaten: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Entfernt Kandidaten, deren NOTAM-Kennungen eine echte Teilmenge eines
    anderen Kandidaten sind.

    Solche Bruchstuecke entstehen ueber Tagesgrenzen hinweg: Der Nachlauf legt
    einen Start ueber Mitternacht vollstaendig in das Buendel des Vortags, im
    eigenen Buendel des Folgetags bildet der Rest eine zweite, kleinere Gruppe.
    Ebenso koennen mehrtaegige Meldungen an einem Tag ohne ihre Partner liegen.
    Gleiche Mengen bleiben stehen - exakte Doppel entfernt spaeter der Schluessel.
    Verworfen wird nur, wenn die Obermenge derselbe Start ist (_gleicher_start):
    eine fremde Nation oder ein anderer Monat mit derselben Kennung zaehlt nicht.
    Die Reihenfolge bleibt erhalten.
    """
    mengen = [frozenset(k["notam_ids"]) for k in kandidaten]
    starts = [_start_des_kandidaten(k) for k in kandidaten]
    return [
        k
        for i, (k, m) in enumerate(zip(kandidaten, mengen))
        if not any(
            m < andere and _gleicher_start(starts[i], starts[j])
            for j, andere in enumerate(mengen)
        )
    ]


#: Ein Start fuer den Vergleich: (NOTAM-Kennungen, Startdatum TT.MM.JJJJ, Nation).
Start = Tuple[Set[str], str, str]


def _start_des_kandidaten(k: Mapping[str, Any]) -> Start:
    return (
        {str(i).upper() for i in k.get("notam_ids", [])},
        str((k.get("row") or {}).get("Startdatum", "")),
        str(k.get("nation") or ""),
    )


def _start_der_entscheidung(key: str, e: Mapping[str, Any]) -> Start:
    """Startdatum steht vorn im Schluessel; Nation erst in neueren Entscheidungen."""
    return (
        {str(i).upper() for i in e.get("notam_ids", [])},
        key.split("|")[0],
        str(e.get("nation") or ""),
    )


def _gleicher_start(a: Start, b: Start) -> bool:
    """
    Derselbe Start: mindestens eine gemeinsame NOTAM-Kennung UND Startdaten
    hoechstens einen Tag auseinander (_nahe_datum) UND gleiche Nation - die nur,
    wenn beide sie kennen (aeltere Entscheidungen haben keine; dann zaehlt das
    Datum allein).

    Kennungen allein reichen nicht: China, Russland und Indien vergeben ihre
    A-Nummern je Jahr neu, A0500/24 kann im Februar ein chinesischer und im
    November ein russischer Start sein. Verglichen wird der englische Name
    (app.nation_label), weil Archivzeilen die Nation englisch fuehren.
    """
    ids_a, datum_a, nation_a = a
    ids_b, datum_b, nation_b = b
    if not ids_a & ids_b or not _nahe_datum(datum_a, datum_b):
        return False
    if nation_a and nation_b and app.nation_label(nation_a) != app.nation_label(nation_b):
        return False
    return True


def _start_index(starts: Iterable[Start]) -> Dict[str, List[Start]]:
    """Kennung -> Starts mit dieser Kennung, damit nicht jeder mit jedem verglichen wird."""
    index: Dict[str, List[Start]] = defaultdict(list)
    for s in starts:
        for i in s[0]:
            index[i].append(s)
    return index


def _im_index(index: Mapping[str, List[Start]], start: Start) -> bool:
    return any(_gleicher_start(start, s) for i in start[0] for s in index.get(i, ()))


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
    r"^(\d{4}) ([A-Z][a-z]{2}) +(\d{1,2})"
    r"(?: (\d{2})(\d{2})(?::(\d{2}))?(?=\s|\?|$)|(?=\s*\??$))"
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
        try:
            zeit = datetime(
                jahr, _MONATE[m.group(2)], int(m.group(3)),
                int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue  # unmoegliches Datum (z.B. 30. Feb): nur diese Zeile ueberspringen
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
    refresh: bool = False,
    cache: Path = GCAT_CACHE,
    opener: Any = urllib.request.urlopen,
    auto_download: bool = True,
) -> Tuple[Optional[List[GcatStart]], str]:
    """
    Startliste aus dem Cache; mit refresh vorher neu abrufen.

    Abgerufen wird nur GCAT_URL. Scheitert der Abruf, bleibt ein vorhandener
    Cache in Gebrauch; ohne Cache gibt es keinen Abgleich (None).
    Mit auto_download=False wird ohne Cache nur auf refresh hin geladen - der
    Reiter laeuft bei jedem Streamlit-Durchlauf und darf nicht blockieren.
    """
    hinweis = ""
    if not cache.exists() and not refresh and not auto_download:
        return None, (
            "No launch list yet - press 'Refresh launch list' to download it "
            "(about 13 MB). Until then there are no suggestions."
        )
    if refresh or not cache.exists():
        try:
            anfrage = urllib.request.Request(GCAT_URL, headers={"User-Agent": "NOLA archive import"})
            with opener(anfrage, timeout=60) as antwort:
                daten = antwort.read(MAX_GCAT_BYTES + 1)
            if len(daten) > MAX_GCAT_BYTES:
                raise ValueError("launch list larger than expected")
            # Nur Abrufe von GCAT_URL: Weiterleitung auf anderen Host ablehnen
            endurl = getattr(antwort, "geturl", lambda: GCAT_URL)()
            if urllib.parse.urlparse(endurl).hostname != urllib.parse.urlparse(GCAT_URL).hostname:
                raise ValueError("redirected to another host")
            # Muell (z.B. Captive-Portal-Seite) darf den guten Cache nicht ersetzen
            text = daten.decode("utf-8", errors="replace")
            if not text.startswith("#Launch_Tag") or not parse_gcat(text):
                raise ValueError("not a launch list")
            _write_bytes_atomic(cache, daten)
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


_ALIAS_MEMO: Dict[Tuple[str, float], Mapping[str, str]] = {}


def load_gcat_vehicle_aliases(path: Path = GCAT_VEHICLES_CSV) -> Mapping[str, str]:
    """
    GCAT-Schreibweise -> Kuerzel (nur fuer den Import). Fehlt die Datei, ist sie leer.

    Je Datei und Aenderungszeit nur einmal gelesen: vehicle_code_for ruft das
    je Kandidat auf. Das Ergebnis ist geteilt und deshalb schreibgeschuetzt.
    """
    if not path.exists():
        return types.MappingProxyType({})
    key = (str(path), path.stat().st_mtime)
    if key not in _ALIAS_MEMO:
        df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
        fehlend = [c for c in ("GCAT", "Abkürzung") if c not in df.columns]
        if fehlend:
            raise ImportStateError(
                "{} is missing the column {}. It is left untouched - please check it.".format(
                    path.name, ", ".join(fehlend))
            )
        _ALIAS_MEMO.clear()
        _ALIAS_MEMO[key] = types.MappingProxyType({
            _norm_name(r["GCAT"]): r["Abkürzung"].strip()
            for _, r in df.iterrows()
            if r["GCAT"].strip() and r["Abkürzung"].strip()
        })
    return _ALIAS_MEMO[key]


_VEHICLE_NAME_MEMO: Dict[Tuple[Tuple[str, ...], ...], Dict[str, str]] = {}


def _vehicle_name_lookup(vehicles: pd.DataFrame) -> Dict[str, str]:
    """
    Normalisierter Name/Alternativname/Kuerzel -> Kuerzel; bei Doppelungen
    gewinnt die erste Zeile der Referenz. Je Inhalt der drei Spalten nur
    einmal gebaut (Schluessel: die Spalteninhalte selbst, ~50 Zeilen).
    """
    spalten = ("Name", "Alternativname englisch", "Abkürzung")
    key = tuple(tuple(str(x) for x in vehicles[c]) for c in spalten)
    if key not in _VEHICLE_NAME_MEMO:
        _VEHICLE_NAME_MEMO.clear()
        lookup: Dict[str, str] = {}
        for name, alt, code in zip(*key):
            for n in (_norm_name(name), _norm_name(alt), _norm_name(code)):
                lookup.setdefault(n, code)
        _VEHICLE_NAME_MEMO[key] = lookup
    return _VEHICLE_NAME_MEMO[key]


def vehicle_code_for(
    gcat_rakete: str, vehicles: pd.DataFrame, aliases: Optional[Mapping[str, str]] = None
) -> str:
    """
    GCAT-Raketenname -> Kuerzel aus traegersysteme_updated.csv.

    Die Oberstufe hinter '/' zaehlt nicht. Erst die Schreibweisen aus
    gcat_traegersysteme.csv, dann Name, Alternativname und Kuerzel der
    Referenz. Ohne Entsprechung - auch wenn ein Alias auf ein Kuerzel zeigt,
    das nicht (mehr) in der Referenz steht - bleibt es leer: ein unbekannter
    Wert wuerde das Dropdown des Tagesbetriebs unterlaufen.
    """
    basis = _norm_name(gcat_rakete.split("/")[0])
    if not basis or vehicles is None or vehicles.empty:
        return ""
    codes = [str(c) for c in vehicles["Abkürzung"]]
    alias = (aliases if aliases is not None else load_gcat_vehicle_aliases()).get(basis)
    if alias:
        return alias if alias in codes else ""
    return _vehicle_name_lookup(vehicles).get(basis, "")


# --------------------------------------------------------------------------- #
# Importzustand
# --------------------------------------------------------------------------- #
_STATE_TYPEN = (
    ("tage", dict),
    ("entscheidungen", dict),
    ("review_bestaetigt", list),
    ("review_ausgeblendet", list),
)


def load_state(path: Path = IMPORT_JSON) -> Dict[str, Any]:
    """
    Liest den Importzustand. Wie load_korpus: eine Datei mit unerwarteter
    Struktur bricht ab (ImportStateError) und wird nie ueberschrieben.
    """
    data = read_json(path)

    def kaputt(was: str) -> ImportStateError:
        return ImportStateError(
            "{} has an unexpected structure ({}). It is left untouched - "
            "please check it.".format(path.name, was)
        )

    for name, typ in _STATE_TYPEN:
        if name in data and not isinstance(data[name], typ):
            raise kaputt("{} is not a {}".format(name, typ.__name__))
    for iso, tag in data.get("tage", {}).items():
        if not isinstance(tag, dict) or not isinstance(tag.get("fingerprint"), str):
            raise kaputt("day {} is not a day entry".format(iso))
        for liste in ("kandidaten", "pruefliste"):
            werte = tag.get(liste)
            if not isinstance(werte, list) or not all(isinstance(w, dict) for w in werte):
                raise kaputt("day {}: {} is not a list of entries".format(iso, liste))
        for zahl in ("usa", "ausgeblendet"):
            if zahl in tag and (not isinstance(tag[zahl], int) or isinstance(tag[zahl], bool)):
                raise kaputt("day {}: {} is not a number".format(iso, zahl))
    for key, e in data.get("entscheidungen", {}).items():
        if not isinstance(e, dict):
            raise kaputt("decision {} is not an entry".format(key))
    return {
        "version": 1,
        "tage": data.get("tage", {}),
        "entscheidungen": data.get("entscheidungen", {}),
        "review_bestaetigt": list(data.get("review_bestaetigt", [])),
        "review_ausgeblendet": list(data.get("review_ausgeblendet", [])),
        "erkennungsstand": data.get("erkennungsstand", ""),
    }


def save_state(state: Dict[str, Any], path: Path = IMPORT_JSON) -> None:
    write_json_atomic(path, state)


def detection_stamp(
    paths: Sequence[Path] = (
        app.APP_DIR / "app.py", app.SPACEPORT_CSV, app.FIR_CSV, app.VEHICLE_CSV
    ),
) -> str:
    """Erkennungsstand: aendert sich mit der Pipeline oder einer ihrer Referenzen."""
    h = hashlib.sha256()
    for path in paths:
        h.update(path.name.encode("utf-8"))
        h.update(path.read_bytes() if path.exists() else b"-")
    return h.hexdigest()[:16]


def is_stale(state: Dict[str, Any], stamp: Optional[str] = None) -> bool:
    """Wurde zuletzt mit einem anderen Erkennungsstand ausgewertet?"""
    return bool(state["tage"]) and state.get("erkennungsstand") != (stamp or detection_stamp())


def reevaluate(
    korpus: Dict[str, KorpusNotam],
    state: Dict[str, Any],
    spaceports: pd.DataFrame,
    firs: pd.DataFrame,
    erzwingen: Iterable[str] = (),
    alle: bool = False,
    fortschritt: Optional[Any] = None,
) -> int:
    """
    Wertet Tage neu aus, deren NOTAM-Bestand sich geaendert hat, die erzwungen
    sind, oder - mit alle=True - jeden Tag. Nur ein vollstaendiger Lauf (oder
    der allererste) setzt den Erkennungsstand; nach einem Teillauf mit neuem
    Code bleibt der Hinweis auf die faellige Neuauswertung also stehen.
    `fortschritt(erledigt, gesamt)` wird je Tag aufgerufen.
    """
    erzwingen = set(erzwingen)
    bestaetigt = set(state["review_bestaetigt"])
    ausgeblendet = set(state["review_ausgeblendet"])
    erster_lauf = not state["tage"]
    buendel = sorted(bundle_days(korpus).items())
    neu = 0
    for nr, (tag, notams) in enumerate(buendel, 1):
        if fortschritt is not None:
            fortschritt(nr, len(buendel))
        iso = tag.isoformat()
        fp = day_fingerprint(notams)
        alt = state["tage"].get(iso)
        if alt and alt.get("fingerprint") == fp and iso not in erzwingen and not alle:
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
    if alle or erster_lauf:
        state["erkennungsstand"] = detection_stamp()
    # Wieder erkannt: 'Keep' verfaellt, damit ein spaeterer Verlust erneut gemeldet wird.
    # Wieder erkannt heisst: derselbe Start (_gleicher_start), nicht nur dieselbe Kennung.
    aktuelle = _aktuelle_starts(state)
    for key, e in state["entscheidungen"].items():
        if e.get("behalten") and _im_index(aktuelle, _start_der_entscheidung(key, e)):
            del e["behalten"]
    return neu


def _aktuelle_starts(state: Dict[str, Any]) -> Dict[str, List[Start]]:
    """Alle aktuellen Kandidaten als Start-Index (siehe _start_index)."""
    return _start_index(
        _start_des_kandidaten(k) for t in state["tage"].values() for k in t["kandidaten"]
    )


def orphans(state: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Bestaetigte Starts, die kein aktueller Kandidat mehr als denselben Start
    fuehrt (_gleicher_start - eine fremde Kollision der Kennung verdeckt nichts).

    Nach einer Neuauswertung mit geaenderter Erkennung belegt NOLA solche
    Archivzeilen nicht mehr. Geloescht wird nie automatisch - der Benutzer
    entscheidet (keep_orphan / remove_orphan).
    """
    aktuelle = _aktuelle_starts(state)
    return [
        (key, e)
        for key, e in sorted(state["entscheidungen"].items())
        if _ist_importzeile(e)  # eine ergaenzte Fremdzeile loescht der Import nie
        and not e.get("behalten")
        and not _im_index(aktuelle, _start_der_entscheidung(key, e))
    ]


def keep_orphan(state: Dict[str, Any], key: str) -> None:
    if key not in state["entscheidungen"]:
        raise ImportStateError("No decision is recorded for {}.".format(key))
    state["entscheidungen"][key]["behalten"] = True


def _archiv_lesen(archiv: Path) -> pd.DataFrame:
    """
    Liest das Startarchiv strikt: eine vorhandene, aber unlesbare Datei bricht
    mit ImportStateError ab, statt als leeres Archiv zu gelten - sonst
    ueberschriebe der naechste Schreibvorgang den ganzen Bestand.
    """
    try:
        return app.read_archive_strict(archiv)
    except app.ArchiveUnreadable as exc:
        raise ImportStateError(str(exc)) from exc


def _archiv_pruefen(
    archiv: Path,
    vorhanden: Set[str],
    fehlend: Set[str],
    werte: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> None:
    """
    Liest das Archiv nach dem Schreiben zurueck. app.persist_archive schluckt
    Schreibfehler; erst dieser Abgleich zeigt, ob die Aenderung angekommen ist.
    `werte`: je Schluessel Spalten, die jede Zeile dieses Schluessels tragen muss.
    """
    zeilen = [(app.archive_key(dict(r)), r) for _, r in _archiv_lesen(archiv).iterrows()]
    keys = {key for key, _ in zeilen}
    falsch = any(
        r[spalte] != wert
        for key, r in zeilen
        for spalte, wert in (werte or {}).get(key, {}).items()
    )
    if not vorhanden <= keys or fehlend & keys or falsch:
        raise ImportStateError(
            "{} could not be written. Nothing was recorded - please check the file "
            "and try again.".format(archiv.name)
        )


def remove_orphan(state: Dict[str, Any], key: str, archiv: Path = app.ARCHIVE_CSV) -> None:
    """Die einzige Stelle, an der der Import eine Archivzeile loescht - nur auf Anweisung."""
    bestand = _archiv_lesen(archiv)
    if not bestand.empty:
        bestand = bestand[
            [app.archive_key(dict(r)) != key for _, r in bestand.iterrows()]
        ].reset_index(drop=True)
        app.persist_archive(archiv, bestand)
    _archiv_pruefen(archiv, set(), {key})
    state["entscheidungen"][key] = {"status": "removed"}


def _ist_importzeile(e: Dict[str, Any]) -> bool:
    """Bestaetigt UND vom Import selbst geschrieben (nicht nur eine fremde Zeile ergaenzt)."""
    return e.get("status") == "confirmed" and not e.get("ergaenzt")


def _kennungen(notam: str) -> Set[str]:
    """NOTAM-Kennungen einer Archivzeile, wie archive_key sie liest."""
    return {t.strip().upper() for t in str(notam).split(",") if t.strip()}


def _nahe_datum(a: str, b: str) -> bool:
    """
    Startdaten (TT.MM.JJJJ) hoechstens einen Tag auseinander - ein Start kann
    ueber Mitternacht laufen. Unlesbares Datum zaehlt als nah: lieber den
    Benutzer die Zielzeile pruefen lassen als eine Dublette anlegen.
    """
    try:
        da = datetime.strptime(str(a).strip(), "%d.%m.%Y").date()
        db = datetime.strptime(str(b).strip(), "%d.%m.%Y").date()
    except ValueError:
        return True
    return abs((da - db).days) <= 1


def _werte_des_vorgaengers(
    key: str, e: Mapping[str, Any], zeile: Optional[Mapping[str, Any]]
) -> Dict[str, str]:
    """Traegersystem und Payload einer Importzeile: aus dem Archiv, sonst aus der Entscheidung."""
    if zeile is not None:
        return {
            "key": key,
            "Tr\u00e4gersystem": str(zeile["Tr\u00e4gersystem"]),
            "Payload": str(zeile["Payload"]),
        }
    return {
        "key": key,
        "Tr\u00e4gersystem": str(e.get("rakete", "")),
        "Payload": str(e.get("payload", "")),
    }


def candidates(state: Dict[str, Any], archiv: Path = app.ARCHIVE_CSV) -> List[Dict[str, Any]]:
    """
    Alle Kandidaten, je Schluessel einmal, mit Entscheidung und zwei Vermerken:

    - ersetzt: vom Import bestaetigte Vorgaenger desselben Starts.
    - im_archiv: andere Archivzeilen (etwa aus dem Tagesbetrieb) desselben Starts.
      Bestaetigen ergaenzt dann nur
      deren Traegersystem und Payload, statt denselben Start ein zweites Mal
      anzulegen. archiv_werte nennt je Zielzeile deren aktuelle Werte,
      ersetzt_werte ebenso je Vorgaenger.

    Derselbe Start heisst ueberall: gemeinsame Kennung, Startdatum innerhalb
    eines Tages und gleiche Nation (_gleicher_start).
    """
    entscheidungen = state["entscheidungen"]
    bestaetigte = {
        key: _start_der_entscheidung(key, e)
        for key, e in entscheidungen.items()
        if _ist_importzeile(e)
    }
    alle_zeilen = [(app.archive_key(dict(r)), r) for _, r in _archiv_lesen(archiv).iterrows()]
    archivzeilen = [
        (key, (_kennungen(r["NOTAM"]), str(r["Startdatum"]), str(r["Nation"])), r)
        for key, r in alle_zeilen
        if key not in bestaetigte  # eigene Zeilen laufen ueber ersetzt
    ]
    eigene_zeilen = {key: r for key, r in alle_zeilen if key in bestaetigte}
    gesehen: Dict[str, Dict[str, Any]] = {}
    alle = [k for iso in sorted(state["tage"]) for k in state["tage"][iso]["kandidaten"]]
    # Bruchstuecke (Nachlauf ueber Mitternacht, mehrtaegige Meldungen) verwerfen,
    # siehe drop_subsumed.
    for k in drop_subsumed(alle):
        if k["key"] in gesehen:
            continue
        eintrag = dict(k)
        eintrag["entscheidung"] = entscheidungen.get(k["key"])
        # alle bestaetigten Vorgaenger mit gemeinsamer Kennung; leer = keiner
        eintrag["ersetzt"] = []
        # vorhandene fremde Archivzeilen desselben Starts; leer = keine
        eintrag["im_archiv"] = []
        eintrag["archiv_werte"] = []
        # aktuelle Werte jedes Vorgaengers (Archivzeile, sonst Entscheidung)
        eintrag["ersetzt_werte"] = []
        if eintrag["entscheidung"] is None:
            eigener = _start_des_kandidaten(k)
            eintrag["ersetzt"] = sorted(
                alt_key
                for alt_key, start in bestaetigte.items()
                if alt_key != k["key"] and _gleicher_start(start, eigener)
            )
            eintrag["ersetzt_werte"] = [
                _werte_des_vorgaengers(alt_key, entscheidungen[alt_key], eigene_zeilen.get(alt_key))
                for alt_key in eintrag["ersetzt"]
            ]
            ziele = {
                key: r
                for key, start, r in archivzeilen
                if _gleicher_start(start, eigener)
            }
            eintrag["im_archiv"] = sorted(ziele)
            eintrag["archiv_werte"] = [
                {
                    "key": key,
                    "Tr\u00e4gersystem": str(ziele[key]["Tr\u00e4gersystem"]),
                    "Payload": str(ziele[key]["Payload"]),
                }
                for key in sorted(ziele)
            ]
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
    Ein 'aktualisierter' Kandidat ersetzt die Zeilen aller seiner Vorgaenger.
    Ein Kandidat mit im_archiv legt keine Zeile an: er traegt nur Traegersystem
    und Payload in die vorhandene(n) Zeile(n) ein (leere Werte ueberschreiben
    nichts). Seinen Ersatzvermerk wendet er nicht an - keine neue Zeile heisst
    auch keine geloeschte, die Importzeile des Vorgaengers bleibt stehen.
    Der Zustand aendert sich erst, wenn das zurueckgelesene Archiv die
    Aenderung enthaelt; sonst ImportStateError und nichts ist vermerkt.
    Die vorherigen Werte jeder ergaenzten Zeile stehen in der Entscheidung
    unter vorher ({Schluessel: {Traegersystem, Payload}}), damit die Aenderung
    nachvollziehbar und rueckgaengig zu machen bleibt.
    Rueckgabe: Zahl der bestaetigten Kandidaten - neu angelegte UND ergaenzte,
    also len(auswahl); nicht die Zahl der geschriebenen Zeilen.
    """
    if not auswahl:
        return 0
    bestand = _archiv_lesen(archiv)
    ergaenzen = [a for a in auswahl if a[0].get("im_archiv")]
    anlegen = [a for a in auswahl if not a[0].get("im_archiv")]
    # Ergaenzen: nur Traegersystem und Payload der vorhandenen Zeile(n)
    schluessel = [app.archive_key(dict(r)) for _, r in bestand.iterrows()]
    werte: Dict[str, Dict[str, str]] = {}
    # Werte vor dem Ergaenzen, fuer die Entscheidung (nachvollziehbar, umkehrbar)
    alt: Dict[str, Dict[str, str]] = {}
    for key, (_, r) in zip(schluessel, bestand.iterrows()):
        alt.setdefault(key, {s: str(r[s]) for s in ("Tr\u00e4gersystem", "Payload")})
    for kand, rakete, payload, _ in ergaenzen:
        for ziel in kand["im_archiv"]:
            if ziel not in schluessel:
                raise ImportStateError(
                    "The archive row {} is no longer in {}. Nothing was written - "
                    "please reload the tab.".format(ziel, archiv.name)
                )
            for spalte, wert in (("Tr\u00e4gersystem", rakete), ("Payload", payload)):
                if wert:
                    werte.setdefault(ziel, {})[spalte] = wert
    if werte:
        bestand = bestand.copy()
        for pos, key in enumerate(schluessel):
            for spalte, wert in werte.get(key, {}).items():
                bestand.iat[pos, bestand.columns.get_loc(spalte)] = wert
    ersetzt = {alt for k, _, _, _ in anlegen for alt in (k.get("ersetzt") or [])}
    if ersetzt and not bestand.empty:
        bestand = bestand[
            [app.archive_key(dict(r)) not in ersetzt for _, r in bestand.iterrows()]
        ].reset_index(drop=True)
    zeilen = []
    neu: Dict[str, Dict[str, Any]] = {}
    for kand, rakete, payload, treffer in anlegen:
        row = dict(kand["row"])
        row["Trägersystem"] = rakete
        row["Payload"] = payload
        zeilen.append(row)
        for alt in kand.get("ersetzt") or []:
            neu[alt] = {"status": "replaced", "durch": kand["key"]}
    # Bestaetigte zuletzt: ein Schluessel der Auswahl bleibt bestaetigt, auch wenn
    # ein anderer Kandidat ihn als Vorgaenger fuehrt.
    for kand, rakete, payload, treffer in auswahl:
        neu[kand["key"]] = {
            "status": "confirmed",
            "rakete": rakete,
            "payload": payload,
            "gcat": treffer.tag if treffer else "",
            "notam_ids": list(kand["notam_ids"]),
            "quellen": list(kand["quellen"]),
            # Nation fuer _gleicher_start (aeltere Entscheidungen haben keine)
            "nation": kand.get("nation", ""),
        }
        if kand.get("im_archiv"):
            neu[kand["key"]]["ergaenzt"] = list(kand["im_archiv"])
            neu[kand["key"]]["vorher"] = {z: dict(alt[z]) for z in kand["im_archiv"]}
    app.persist_archive(archiv, app.merge_archive(bestand, zeilen, entfernt=set()))
    geschrieben = {app.archive_key(r) for r in zeilen}
    _archiv_pruefen(archiv, geschrieben | set(werte), ersetzt - geschrieben, werte)
    state["entscheidungen"].update(neu)
    return len(auswahl)


def reject(state: Dict[str, Any], key: str) -> None:
    state["entscheidungen"][key] = {"status": "discarded"}


def bulk_candidates(
    kandidaten: Sequence[Dict[str, Any]],
    gcat: Optional[List[GcatStart]],
    sites: Dict[str, Tuple[List[str], str]],
    vehicles: pd.DataFrame,
    abgleiche: Optional[Mapping[str, Abgleich]] = None,
) -> List[Tuple[Dict[str, Any], str, str, GcatStart]]:
    """
    Nur unentschiedene, eindeutige Kandidaten ohne Warnung, ohne Ersatz- oder
    Archivvermerk und mit Traeger-Kuerzel.

    abgleiche: schon berechnete Abgleiche je Kandidatenschluessel (spart den
    zweiten Abgleich im Reiter); fehlt einer, wird er hier berechnet.
    """
    auswahl = []
    for k in kandidaten:
        if k["entscheidung"] is not None or k["ersetzt"] or k.get("im_archiv"):
            continue
        abgleich = (abgleiche or {}).get(k["key"]) or match_candidate(k, gcat, sites)
        if abgleich.status != STATUS_EINDEUTIG or abgleich.warnungen:
            continue
        s = abgleich.treffer[0]
        code = vehicle_code_for(s.rakete, vehicles)
        if not code:  # Rakete ohne Kuerzel: nur einzeln, mit sichtbarem Feld
            continue
        auswahl.append((k, code, s.nutzlast, s))
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
