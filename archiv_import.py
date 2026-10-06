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
import tempfile
import urllib.parse
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
    """Schreibt erst eine temporaere Datei und benennt sie dann um."""
    # eindeutiger Name im selben Ordner, damit os.replace atomar bleibt
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(daten)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Schreibt JSON atomar (siehe _write_bytes_atomic)."""
    _write_bytes_atomic(path, json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def load_korpus(path: Path = KORPUS_JSON) -> Dict[str, KorpusNotam]:
    data = read_json(path)
    korpus: Dict[str, KorpusNotam] = {}
    try:
        for e in data.get("notams", []):
            n = KorpusNotam(e["notam_id"], e["b"], e["text"], list(e.get("quellen", [])))
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
    Die Reihenfolge bleibt erhalten.
    """
    mengen = [frozenset(k["notam_ids"]) for k in kandidaten]
    return [
        k
        for k, m in zip(kandidaten, mengen)
        if not any(m < andere for andere in mengen)
    ]


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
