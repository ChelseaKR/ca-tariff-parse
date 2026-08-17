"""Split a layout document into numbered sections.

Tariff sheets are numbered like statutes: roman numerals for top level parts,
capital letters beneath those, arabic numerals beneath those. The segmenter
recovers that outline so every value can be cited to a section, and so that a
part of the document nobody wrote a recognizer for can be reported as an
identifiable unit rather than vanishing.

Every content line lands in exactly one section. Nothing is discarded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import LayoutDoc, Line

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


def segment(doc: LayoutDoc) -> SegmentedDoc:
    """Split every content line of ``doc`` into exactly one section."""
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
