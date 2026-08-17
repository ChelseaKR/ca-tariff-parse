"""Turn a source document into a positional layout model.

Rate schedules are laid out as tables. Reconstructing them from a flat string
loses the column alignment that says which price belongs to which effective
date, so this layer keeps the x coordinate of every word and lets the
recognizers align columns geometrically.

There are two front ends onto the same :class:`LayoutDoc`:

* :func:`layout_from_pdf` reads a real published PDF via ``pdfplumber``.
* :func:`layout_from_monospace` reads a plain text fixture, treating each
  character cell as a fixed width column. Test fixtures use this so the parser
  can be exercised in CI without redistributing a publisher's PDF.

Both produce identical structures, so a recognizer cannot tell them apart.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

#: Nominal width of one character cell in a monospace fixture, in points.
MONO_CHAR_WIDTH = 6.0
#: Nominal height of one text line in a monospace fixture, in points.
MONO_LINE_HEIGHT = 14.0
#: Nominal page height for a monospace fixture, in points.
MONO_PAGE_HEIGHT = 792.0

#: Fraction of page height below which a line counts as running header.
HEADER_BAND = 0.085
#: Fraction of page height above which a line counts as running footer.
FOOTER_BAND = 0.86
#: Multiple of a page's own median line gap that separates a running footer
#: from the last line of the body. A footer is set apart by clear space, so a
#: line inside the footer band that sits at ordinary body spacing under the
#: line above it is still body. Without this the band alone decides, and a
#: publisher who runs body text a little further down the page loses it: three
#: lines of one second publisher's schedules fell just past the band, one of
#: them carrying a published amount.
FOOTER_SEPARATION = 1.5
#: Vertical distance in points within which two words belong to the same line.
LINE_TOLERANCE = 3.0

_WS = re.compile(r"\s+")
_LEADERS = re.compile(r"[.…]{3,}")


def normalize(text: str) -> str:
    """Collapse whitespace and straighten quotes for stable matching."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = _LEADERS.sub(" ", text)
    return _WS.sub(" ", text).strip()


def squash(text: str) -> str:
    """Lowercase and remove every space.

    Some tariff PDFs carry letter spacing that extraction renders as
    ``"Non-S ummer S eason"``. Matching on a squashed form is immune to that
    without guessing where word boundaries really were.
    """
    return _WS.sub("", normalize(text)).lower()


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass(frozen=True, slots=True)
class Line:
    """One visual line of text, with the horizontal position of each word."""

    page: int
    index: int
    top: float
    words: tuple[Word, ...]
    furniture: bool

    @property
    def text(self) -> str:
        return normalize(" ".join(w.text for w in self.words))

    @property
    def squashed(self) -> str:
        return squash(self.text)

    @property
    def indent(self) -> float:
        return self.words[0].x0 if self.words else 0.0

    def words_right_of(self, x: float) -> tuple[Word, ...]:
        return tuple(w for w in self.words if w.x0 >= x)

    def words_left_of(self, x: float) -> tuple[Word, ...]:
        return tuple(w for w in self.words if w.x0 < x)


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    height: float
    lines: tuple[Line, ...]
    sheet: str | None


@dataclass(frozen=True, slots=True)
class LayoutDoc:
    document_id: str
    sha256: str
    filename: str
    byte_size: int
    pages: tuple[Page, ...]
    synthetic: bool

    @property
    def page_count(self) -> int:
        return len(self.pages)

    def all_lines(self) -> tuple[Line, ...]:
        return tuple(line for page in self.pages for line in page.lines)

    def sheet_for(self, page: int) -> str | None:
        for p in self.pages:
            if p.number == page:
                return p.sheet
        return None


_SHEET_RE = re.compile(r"Sheet\s*No\.?\s*([A-Za-z0-9][A-Za-z0-9\-]*)", re.IGNORECASE)
#: A supersession header. A sheet that replaces an earlier one prints both
#: numbers, as in "Revised Cal. P.U.C. Sheet No. 61362-E" over "Cancelling
#: Revised Cal. P.U.C. Sheet No. 61247-E". The cancelled number names the sheet
#: this page is *not*, so citing it would point every value on the page at a
#: superseded document.
CANCELS_RE = re.compile(r"\bcancel", re.IGNORECASE)


def sheet_numbers(line: Line) -> list[str]:
    """Sheet numbers this line asserts, ignoring any it cancels.

    Returns an empty list for a line that only names a cancelled sheet, so a
    caller never records a superseded sheet number as this page's own.
    """
    if CANCELS_RE.search(line.text):
        return []
    return _SHEET_RE.findall(line.text)


def _detect_sheet(lines: list[Line]) -> str | None:
    """Read the sheet number off the page furniture, if the document has one.

    Two publishers put the number in different places and one of them prints
    two of them, so the rule is to collect every number the page asserts as its
    own and to use it only when they agree. Disagreement means the page does
    not state a single sheet number, and none is recorded rather than one of
    them being picked.
    """
    found = [number for line in lines if line.furniture for number in sheet_numbers(line)]
    if not found or len(set(found)) != 1:
        return None
    return found[0]


def _median_gap(tops: list[float]) -> float:
    gaps = sorted(later - earlier for earlier, later in pairwise(tops))
    return gaps[len(gaps) // 2] if gaps else 0.0


def _mark_furniture(raw: list[tuple[float, tuple[Word, ...]]], height: float) -> list[bool]:
    """Flag running headers and footers.

    Page furniture is not content. It is still cited (the effective date lives
    there) but it is excluded from the coverage denominator so that a five page
    schedule is not credited for repeating its own title five times.

    The vertical bands say where furniture may be. Where the footer actually
    begins is read from the page's own line spacing: a footer is set apart from
    the body by clear space, so the footer starts at the first line in the band
    that is separated from the line above it by more than the page's ordinary
    line gap. A line in the band at body spacing is body, and is accounted for
    rather than silently dropped.
    """
    tops = [top for top, _words in raw]
    median = _median_gap(tops)
    flags: list[bool] = []
    in_footer = False
    for index, top in enumerate(tops):
        ratio = top / height if height else 0.0
        if ratio <= HEADER_BAND:
            flags.append(True)
            continue
        if ratio < FOOTER_BAND:
            flags.append(False)
            continue
        if not in_footer:
            gap = top - tops[index - 1] if index else float("inf")
            in_footer = median <= 0.0 or gap > median * FOOTER_SEPARATION
        flags.append(in_footer)
    return flags


def cluster_lines(words: list[tuple[float, Word]]) -> list[tuple[float, tuple[Word, ...]]]:
    """Group words into visual lines by vertical proximity.

    Rounding the y coordinate to the nearest point is not enough: a footer whose
    two halves are typeset a fraction of a point apart would split into two
    lines and break a citation that has to quote the whole line. Clustering with
    a tolerance keeps such a line intact.
    """
    if not words:
        return []
    ordered = sorted(words, key=lambda item: (item[0], item[1].x0))
    clusters: list[tuple[float, list[Word]]] = []
    for top, word in ordered:
        if clusters and abs(top - clusters[-1][0]) <= LINE_TOLERANCE:
            clusters[-1][1].append(word)
        else:
            clusters.append((top, [word]))
    return [(top, tuple(sorted(group, key=lambda w: w.x0))) for top, group in clusters]


def _build_pages(
    per_page: list[tuple[float, list[tuple[float, tuple[Word, ...]]]]],
) -> tuple[Page, ...]:
    pages: list[Page] = []
    for page_no, (height, raw) in enumerate(per_page, start=1):
        raw = [(top, words) for top, words in raw if words]
        raw.sort(key=lambda item: item[0])
        flags = _mark_furniture(raw, height)
        lines = tuple(
            Line(page=page_no, index=i, top=top, words=words, furniture=flag)
            for i, ((top, words), flag) in enumerate(zip(raw, flags, strict=True), start=1)
        )
        pages.append(
            Page(
                number=page_no,
                height=height,
                lines=lines,
                sheet=_detect_sheet(list(lines)),
            )
        )
    return tuple(pages)


def layout_from_pdf(path: Path, document_id: str | None = None) -> LayoutDoc:
    """Read a published PDF into the layout model.

    Import of ``pdfplumber`` is deferred so that fixture based tests, and the
    ``sources`` and ``verify-source`` commands, do not pay for it.
    """
    import pdfplumber

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    per_page: list[tuple[float, list[tuple[float, tuple[Word, ...]]]]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            collected: list[tuple[float, Word]] = [
                (
                    float(word["top"]),
                    Word(text=str(word["text"]), x0=float(word["x0"]), x1=float(word["x1"])),
                )
                for word in page.extract_words(
                    x_tolerance=1.5,
                    y_tolerance=2,
                    keep_blank_chars=False,
                    use_text_flow=False,
                )
            ]
            per_page.append((float(page.height), cluster_lines(collected)))

    return LayoutDoc(
        document_id=document_id or path.stem,
        sha256=digest,
        filename=path.name,
        byte_size=len(data),
        pages=_build_pages(per_page),
        synthetic=False,
    )


def layout_from_monospace(
    text: str,
    document_id: str,
    *,
    synthetic: bool = True,
    filename: str = "<inline>",
) -> LayoutDoc:
    """Read a monospace text fixture into the layout model.

    Pages are separated by a form feed. Each character column is treated as a
    fixed width cell, which reproduces the column alignment a real PDF carries
    in its word coordinates.
    """
    data = text.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()

    per_page: list[tuple[float, list[tuple[float, tuple[Word, ...]]]]] = []
    for chunk in text.split("\f"):
        if not chunk.strip():
            continue
        raw: list[tuple[float, tuple[Word, ...]]] = []
        rows = chunk.split("\n")
        # Pad short fixture pages so that the footer band lands where a real
        # page would put it, instead of drifting with the fixture's length.
        height = max(MONO_PAGE_HEIGHT, (len(rows) + 2) * MONO_LINE_HEIGHT)
        for row_no, row in enumerate(rows):
            if not row.strip():
                continue
            words: list[Word] = []
            for match in re.finditer(r"\S+", row):
                words.append(
                    Word(
                        text=match.group(0),
                        x0=match.start() * MONO_CHAR_WIDTH,
                        x1=match.end() * MONO_CHAR_WIDTH,
                    )
                )
            raw.append((row_no * MONO_LINE_HEIGHT, tuple(words)))
        per_page.append((height, raw))

    return LayoutDoc(
        document_id=document_id,
        sha256=digest,
        filename=filename,
        byte_size=len(data),
        pages=_build_pages(per_page),
        synthetic=synthetic,
    )


def layout_from_path(path: Path, document_id: str | None = None) -> LayoutDoc:
    """Dispatch on file extension: ``.pdf`` to the PDF reader, otherwise text."""
    if path.suffix.lower() == ".pdf":
        return layout_from_pdf(path, document_id=document_id)
    text = path.read_text(encoding="utf-8")
    synthetic = "SYNTHETIC" in text.upper() or "synthetic" in path.name.lower()
    return layout_from_monospace(
        text,
        document_id=document_id or path.stem,
        synthetic=synthetic,
        filename=path.name,
    )
