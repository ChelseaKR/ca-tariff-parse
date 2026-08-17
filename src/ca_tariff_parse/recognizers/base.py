"""Shared plumbing for recognizers.

A recognizer looks at one :class:`~ca_tariff_parse.segment.Section` and either
declines it or returns an :class:`Emission` describing what it understood and
exactly which lines it consumed.

Consumption is tracked per line so the engine can tell the difference between
"this section was understood" and "the first half of this section was
understood and the rest was quietly ignored". The second case is the dangerous
one, and it is reported as unparsed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..extract import LayoutDoc, Line, Word, normalize
from ..model import (
    Applicability,
    Charge,
    Cited,
    CrossReference,
    Holiday,
    Provenance,
    TouWindow,
)
from ..segment import Section

LineKey = tuple[int, int]

#: Matches a currency amount, optionally negative, as printed in a tariff table.
MONEY_RE = re.compile(r"\A(?P<sign>-?)\$(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\Z")
#: Matches a cell the publisher marked as not applicable.
NA_RE = re.compile(r"\A(n/a|na|--|—)\Z", re.IGNORECASE)

#: Time-of-use period names as the published schedules write them, longest
#: first so that "Off-Peak Saver" is never truncated to "Off-Peak". These are
#: distinct periods with distinct prices, and labelling one as the other would
#: attach a price to the wrong window.
PERIOD_NAMES = (
    "Super Off-Peak",
    "Off-Peak Saver",
    "Off-Peak",
    "Mid-Peak",
    "On-Peak",
    "Peak",
)
PERIOD_ALTERNATION = "|".join(name.replace(" ", r"\s+") for name in PERIOD_NAMES)

#: A unit phrase anchored on a currency sign, e.g. "$/kWh" or "$ per monthly
#: max kW". When a label carries one, it is the unit, because the publisher
#: wrote the currency in it.
_UNIT_DOLLAR_RE = re.compile(r"\$\s*/|\$\s+per\b")
#: Otherwise the unit phrase begins at the first "per".
_UNIT_PER_RE = re.compile(r"\bper\b")
#: A unit has to measure something. Requiring one of these tokens stops a label
#: that merely happens to contain the word "per" from being read as a unit.
_UNIT_MEASURE_RE = re.compile(
    r"\b(kWh|kW|kVA|kVAR|KVAR|kV|Wh|meter|meters|month|months|unit|units|day|days|"
    r"year|years|customer|customers|account|accounts|premise|premises|therm|therms)\b",
    re.IGNORECASE,
)


def unit_tail(label: str) -> str | None:
    """Read the unit a priced row is quoted in, verbatim from its own label.

    The unit is the trailing phrase of the label, running to the end of it: the
    ``$/kWh`` of ``"Peak $/kWh"``, the ``$ per monthly max kW`` of
    ``"Maximum Demand Charge $ per monthly max kW"``, the ``per month per
    meter`` of ``"System Infrastructure Fixed Charge per month per meter"``.

    Matching a fixed list of known unit strings anywhere in the label looked
    correct on two residential schedules and misread a commercial one: "per
    month" is a substring of "per monthly max kW", so a demand charge came out
    quoted as a flat monthly amount. Taking the tail cannot do that, because
    what it emits is exactly what the label says, ending where the label ends.

    Returns ``None`` when no unit can be read, which makes the caller refuse
    the row rather than price it in a unit nobody printed.
    """
    match = _UNIT_DOLLAR_RE.search(label) or _UNIT_PER_RE.search(label)
    if match is None:
        return None
    tail = label[match.start() :].strip()
    if not _UNIT_MEASURE_RE.search(tail):
        return None
    return tail


@dataclass(slots=True)
class Emission:
    """What a recognizer understood, and which lines it accounted for."""

    consumed: set[LineKey] = field(default_factory=set)
    charges: list[Charge] = field(default_factory=list)
    applicability: list[Applicability] = field(default_factory=list)
    tou_windows: list[TouWindow] = field(default_factory=list)
    holidays: list[Holiday] = field(default_factory=list)
    cross_references: list[CrossReference] = field(default_factory=list)
    notes: list[Cited[str]] = field(default_factory=list)

    def take(self, *lines: Line) -> None:
        for line in lines:
            self.consumed.add((line.page, line.index))

    def extend(self, other: Emission) -> None:
        self.consumed |= other.consumed
        self.charges += other.charges
        self.applicability += other.applicability
        self.tou_windows += other.tou_windows
        self.holidays += other.holidays
        self.cross_references += other.cross_references
        self.notes += other.notes

    def __bool__(self) -> bool:
        return bool(
            self.charges
            or self.applicability
            or self.tou_windows
            or self.holidays
            or self.cross_references
            or self.notes
        )


class Citer:
    """Builds citations against one source document."""

    __slots__ = ("doc",)

    def __init__(self, doc: LayoutDoc) -> None:
        self.doc = doc

    def cite(self, line: Line, section: str, *, snippet: str | None = None) -> Provenance:
        return Provenance(
            document_id=self.doc.document_id,
            document_sha256=self.doc.sha256,
            page=line.page,
            sheet=self.doc.sheet_for(line.page),
            section=section,
            line=line.index,
            snippet=snippet if snippet is not None else line.text,
        )

    def cite_span(self, lines: Iterable[Line], section: str) -> Provenance:
        group = list(lines)
        if not group:
            raise ValueError("cannot cite an empty span")
        first, last = group[0], group[-1]
        snippet = normalize(" ".join(line.text for line in group))
        return Provenance(
            document_id=self.doc.document_id,
            document_sha256=self.doc.sha256,
            page=first.page,
            sheet=self.doc.sheet_for(first.page),
            section=section,
            line=first.index,
            snippet=snippet,
            end_line=last.index if last.index != first.index else None,
        )

    def text(self, line: Line, section: str, value: str) -> Cited[str]:
        return Cited(value=value, provenance=self.cite(line, section))


#: Horizontal gap, in points, that separates two column headings.
COLUMN_GAP = 8.0
#: Distance, in points, a value may sit from a column centre and still be read
#: as belonging to it. Beyond this the assignment is treated as ambiguous.
COLUMN_TOLERANCE = 45.0
#: Clear space, in points, left of the first column of values, used to split a
#: row's label from the values on it.
LABEL_MARGIN = 20.0


class Column:
    """One column of a table, named by the heading words set over it."""

    __slots__ = ("label", "x0", "x1")

    def __init__(self, words: Sequence[Word]) -> None:
        self.label = " ".join(word.text for word in words)
        self.x0 = min(word.x0 for word in words)
        self.x1 = max(word.x1 for word in words)

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2.0


def columns_from(words: Sequence[Word]) -> list[Column]:
    """Split a heading row into columns on horizontal whitespace."""
    groups: list[list[Word]] = []
    for word in words:
        if groups and word.x0 - groups[-1][-1].x1 <= COLUMN_GAP:
            groups[-1].append(word)
        else:
            groups.append([word])
    return [Column(group) for group in groups]


def assign(word: Word, columns: Sequence[Column]) -> Column | None:
    """The column a value sits under, or ``None`` when that is ambiguous.

    Which price belongs to which heading is carried entirely by horizontal
    position, so a value that does not sit clearly under one column cannot be
    attributed at all, and the caller refuses the whole row.
    """
    if not columns:
        return None
    best = min(columns, key=lambda column: abs(column.center - word.center))
    if abs(best.center - word.center) > COLUMN_TOLERANCE:
        return None
    return best


def paragraphs(section: Section, *, skip_heading: bool = True) -> list[list[Line]]:
    """Group a section's content lines into logical paragraphs.

    A wrapped continuation line is always indented further than the line that
    began the paragraph, so the left edge plus the numbering pattern is enough
    to rebuild the paragraph structure without guessing.
    """
    lines = section.content_lines
    if skip_heading and lines and section.level > 0:
        lines = lines[1:]
    if not lines:
        return []

    starts = [line for line in lines if not _looks_like_continuation(line, lines)]
    base = min((line.indent for line in starts), default=lines[0].indent)

    groups: list[list[Line]] = []
    for line in lines:
        begins = line.indent <= base + 1.0 or bool(re.match(r"\A\d+\.\s", line.text))
        if begins or not groups:
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


def _looks_like_continuation(line: Line, lines: list[Line]) -> bool:
    lowest = min(candidate.indent for candidate in lines)
    return line.indent > lowest + 1.0 and not re.match(r"\A\d+\.\s", line.text)


def money_tokens(words: Iterable[object]) -> bool:
    """True when any word in the run is a currency amount."""
    return any(MONEY_RE.match(getattr(word, "text", "")) for word in words)


def strip_item_number(text: str) -> str:
    """Drop a leading ``1.`` / ``A.`` enumerator from an item's text."""
    return re.sub(r"\A(?:\d+|[A-Z])\.\s+", "", text).strip()
