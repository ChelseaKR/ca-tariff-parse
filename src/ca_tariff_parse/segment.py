"""Split a layout document into the document's own outline.

Two outlines are known, and which one a document uses comes from its profile
because the page does not say (see :mod:`ca_tariff_parse.profiles`).

**Numbered.** Tariff sheets are often numbered like statutes: roman numerals
for top level parts, capital letters beneath those, arabic numerals beneath
those.

**Keyword column.** Other publishers set a keyword in a column of its own with
the body of the part beside it, so a line reads ``APPLICABILITY: This schedule
is applicable to ...``. The keyword can be broken across lines, and a part
continued onto the next sheet reprints its keyword with ``(Cont'd.)`` beneath.

Either way the segmenter recovers the outline so every value can be cited to a
part, and so that a part nobody wrote a recognizer for can be reported as an
identifiable unit rather than vanishing.

Every content line lands in exactly one section. Nothing is discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import LayoutDoc, Line, Page
from .profiles import DEFAULT, KEYWORD_COLUMN, DocumentProfile

ROMAN_RE = re.compile(r"\A(?P<num>[IVXLC]{1,7})\.\s+(?P<title>\S.*)\Z")
LETTER_RE = re.compile(r"\A(?P<num>[A-Z])\.\s+(?P<title>\S.*)\Z")

#: Indent bands, in points, that distinguish heading levels on a tariff sheet.
#: These are compared against the leftmost word of a line, and a heading is only
#: accepted if it also matches the numbering pattern for that level.
ROMAN_MAX_INDENT = 75.0
LETTER_MAX_INDENT = 100.0

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(text: str) -> int | None:
    """Convert a roman numeral to an int, or return None if it is not one.

    Used to reject false positives. A line beginning ``"I. "`` is a heading, but
    a line beginning ``"IV. "`` is only a heading if it follows ``III``, and a
    stray ``"CC. "`` is not a heading at all.
    """
    total = 0
    previous = 0
    for char in reversed(text.upper()):
        value = _ROMAN_VALUES.get(char)
        if value is None:
            return None
        if value < previous:
            total -= value
        else:
            total += value
            previous = value
    return total if total > 0 else None


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    number: str
    title: str


def classify_heading(line: Line) -> Heading | None:
    """Return the heading this line opens, if it opens one."""
    if line.furniture or not line.words:
        return None
    text = line.text
    indent = line.indent

    if indent <= ROMAN_MAX_INDENT:
        match = ROMAN_RE.match(text)
        if match and roman_to_int(match.group("num")) is not None:
            return Heading(level=1, number=match.group("num"), title=match.group("title").strip())

    if indent <= LETTER_MAX_INDENT:
        match = LETTER_RE.match(text)
        if match:
            return Heading(level=2, number=match.group("num"), title=match.group("title").strip())

    return None


@dataclass(slots=True)
class Section:
    """A contiguous run of lines under one heading."""

    section_id: str
    level: int
    heading: str
    lines: list[Line] = field(default_factory=list)
    heading_inline: bool = False
    """True when the heading shares its line with the body of the part, which
    is what a keyword column does. A numbered heading owns its line, so the
    engine can credit that line as understood by segmentation alone; an inline
    heading cannot be credited, because the same line carries text no
    recognizer has read yet."""

    @property
    def page(self) -> int:
        return self.lines[0].page if self.lines else 0

    @property
    def first_line(self) -> int:
        return self.lines[0].index if self.lines else 0

    @property
    def last_line(self) -> int:
        return self.lines[-1].index if self.lines else 0

    @property
    def content_lines(self) -> list[Line]:
        return [line for line in self.lines if not line.furniture]

    def key(self, line: Line) -> tuple[int, int]:
        return (line.page, line.index)


@dataclass(slots=True)
class SegmentedDoc:
    doc: LayoutDoc
    sections: list[Section]
    furniture: list[Line]

    def content_line_count(self) -> int:
        return sum(len(section.content_lines) for section in self.sections)


#: Section id given to page furniture, which belongs to no numbered part.
FURNITURE_SECTION = "front"
#: Section id given to content that appears before the first numbered heading.
PREAMBLE_SECTION = "preamble"


def _segment_numbered(doc: LayoutDoc) -> SegmentedDoc:
    """Split every content line of ``doc`` into exactly one numbered section."""
    sections: list[Section] = []
    furniture: list[Line] = []

    current_roman: str | None = None
    current: Section | None = None
    seen_romans: list[int] = []

    def open_section(section_id: str, level: int, heading: str) -> Section:
        nonlocal current
        current = Section(section_id=section_id, level=level, heading=heading)
        sections.append(current)
        return current

    for line in doc.all_lines():
        if line.furniture:
            furniture.append(line)
            continue

        heading = classify_heading(line)

        if heading is not None and heading.level == 1:
            value = roman_to_int(heading.number)
            # Reject an out of order roman numeral: on a tariff sheet the parts
            # run in order, so a jump backwards means this is body text that
            # merely looks like a heading.
            if value is not None and (not seen_romans or value > seen_romans[-1]):
                seen_romans.append(value)
                current_roman = heading.number
                open_section(heading.number, 1, heading.title)
                current.lines.append(line)  # type: ignore[union-attr]
                continue

        if heading is not None and heading.level == 2 and current_roman is not None:
            open_section(f"{current_roman}.{heading.number}", 2, heading.title)
            current.lines.append(line)  # type: ignore[union-attr]
            continue

        if current is None:
            current = open_section(PREAMBLE_SECTION, 0, "(preamble)")
        current.lines.append(line)

    return SegmentedDoc(doc=doc, sections=sections, furniture=furniture)


# ---------------------------------------------------------------------------
# Keyword column outline
# ---------------------------------------------------------------------------

#: Horizontal clear space, in points, that separates the keyword column from
#: the body beside it. A word space in these documents is three to five points,
#: so this distinguishes a column boundary from an ordinary gap between words.
#: It is a tolerance rather than a position: the column's own left edge is read
#: off the page, because the same publisher sets it anywhere from 72 to 101
#: points across three schedules.
KEYWORD_GAP = 8.0
#: How far right of the leftmost content on its own page a keyword may start.
#: A footnote marker often sits a few points further left than the keyword
#: column, and the running utility identifier a few points to its right, so the
#: leftmost line on a page is not always the keyword itself.
KEYWORD_MARGIN = 20.0
#: How many lines a keyword may be broken across before the parser stops
#: waiting for the colon that ends it. "COMMON- AREA ACCOUNTS:" takes three.
KEYWORD_MAX_LINES = 3

#: A keyword is set in capitals. Digits, ampersands and hyphens appear in them
#: ("B1-ST FOR STORAGE:", "PG&E"), lower case letters do not, which is what
#: separates a keyword from a table's row label such as "Generation:".
_UPPERCASE_TOKEN_RE = re.compile(r"\A[^a-z]*[A-Z][^a-z]*\Z")


def _keyword_cell(line: Line) -> tuple[str, float] | None:
    """The keyword this line sets in its left-hand column, and where it starts.

    The cell is the line's first run of words, cut at the first clear space
    wide enough to be a column boundary. It counts as a keyword only when every
    word in it is set in capitals. Requiring the capitals is what keeps a
    priced table's own row label out: one publisher writes "Generation:
    $0.12855" in the same geometry, and reading that as a heading would put
    every rate under a part the document never declared.
    """
    if not line.words:
        return None
    cell = [line.words[0]]
    for previous, word in zip(line.words, line.words[1:], strict=False):
        if word.x0 - previous.x1 > KEYWORD_GAP:
            break
        cell.append(word)
    if not all(_UPPERCASE_TOKEN_RE.match(word.text) for word in cell):
        return None
    return " ".join(word.text for word in cell), cell[0].x0


def _leftmost_content(page: Page) -> float:
    return min(
        (line.words[0].x0 for line in page.lines if not line.furniture and line.words),
        default=0.0,
    )


def _keyword_at(lines: list[Line], start: int, margin: float) -> tuple[str, int] | None:
    """Read the keyword opening at ``lines[start]``, or ``None`` if none does.

    A keyword may be broken across lines, so up to
    :data:`KEYWORD_MAX_LINES` are joined until one ends with the colon that
    closes it. Returns the joined keyword and how many lines it occupied.
    """
    parts: list[str] = []
    for offset in range(KEYWORD_MAX_LINES):
        if start + offset >= len(lines):
            break
        cell = _keyword_cell(lines[start + offset])
        if cell is None or cell[1] > margin:
            break
        parts.append(cell[0])
        if parts[-1].endswith(":"):
            return " ".join(parts).removesuffix(":").strip(), offset + 1
    return None


def _section_id(keyword: str) -> str:
    """A section id for a keyword: the letters and digits it is spelled with.

    A section id is a dotted run of alphanumerics, because it has to survive
    into a citation. The heading beside it keeps the keyword verbatim.
    """
    return re.sub(r"[^A-Za-z0-9]", "", keyword) or PREAMBLE_SECTION


def _keywords_on(content: list[Line], margin: float) -> dict[int, tuple[str, int]]:
    """Every keyword this page opens, by the line position it starts at."""
    found: dict[int, tuple[str, int]] = {}
    position = 0
    while position < len(content):
        keyword = _keyword_at(content, position, margin)
        if keyword is None:
            position += 1
            continue
        found[position] = keyword
        position += keyword[1]
    return found


def _sheet_heading_depth(per_page: list[dict[int, tuple[str, int]]]) -> int:
    """How many lines at the top of every sheet are the sheet's own heading.

    Each sheet of a tariff book repeats a banner of the same height above the
    first part it carries: the utility identifier, the schedule and the sheet
    number. That banner is not part of the part continued from the sheet
    before, and attributing it to one read a page banner as an eligibility
    statement.

    The height is read off the document as the smallest run any sheet sets
    above its first keyword. Taking the smallest is what keeps the rule from
    swallowing body text on a sheet whose first keyword the parser could not
    read: it can only ever divert as many lines as the shallowest sheet proves
    are heading.
    """
    depths = [min(keywords) for keywords in per_page if keywords]
    return min(depths, default=0)


def _segment_keyword_column(doc: LayoutDoc) -> SegmentedDoc:
    """Split every content line of ``doc`` at the keywords it sets in column."""
    sections: list[Section] = []
    furniture: list[Line] = []
    content_by_page = [[line for line in page.lines if not line.furniture] for page in doc.pages]
    for page in doc.pages:
        furniture.extend(line for line in page.lines if line.furniture)
    keywords_by_page = [
        _keywords_on(content, _leftmost_content(page) + KEYWORD_MARGIN)
        for page, content in zip(doc.pages, content_by_page, strict=True)
    ]
    heading_depth = _sheet_heading_depth(keywords_by_page)

    current: Section | None = None
    preamble: Section | None = None

    def open_section(section_id: str, level: int, heading: str, inline: bool) -> Section:
        opened = Section(section_id=section_id, level=level, heading=heading, heading_inline=inline)
        sections.append(opened)
        return opened

    for content, keywords in zip(content_by_page, keywords_by_page, strict=True):
        for position, line in enumerate(content):
            keyword = keywords.get(position)
            if keyword is not None and (current is None or current.heading != keyword[0]):
                current = open_section(_section_id(keyword[0]), 1, keyword[0], True)
            if position < heading_depth or current is None:
                if preamble is None:
                    preamble = open_section(PREAMBLE_SECTION, 0, "(preamble)", False)
                preamble.lines.append(line)
                continue
            current.lines.append(line)

    return SegmentedDoc(doc=doc, sections=sections, furniture=furniture)


def segment(doc: LayoutDoc, profile: DocumentProfile = DEFAULT) -> SegmentedDoc:
    """Split every content line of ``doc`` into exactly one section."""
    if profile.outline == KEYWORD_COLUMN:
        return _segment_keyword_column(doc)
    return _segment_numbered(doc)
