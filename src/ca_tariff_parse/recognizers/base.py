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
from itertools import pairwise

from ..extract import LayoutDoc, Line, Word, normalize
from ..model import (
    Applicability,
    Charge,
    Cited,
    Condition,
    CrossReference,
    Holiday,
    ProrationRule,
    Provenance,
    TouWindow,
)
from ..profiles import DocumentProfile
from ..segment import Section

LineKey = tuple[int, int]

#: Matches a currency amount, optionally negative, as printed in a tariff table.
MONEY_RE = re.compile(r"\A(?P<sign>-?)\$(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\Z")
#: The same amount wrapped in accounting brackets, as in ``($0.08140)``. What
#: the brackets mean is the publisher's convention rather than anything the
#: page states, so this is only read when a profile says the publisher uses it.
BRACKET_MONEY_RE = re.compile(
    r"\A\(\$(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\)\Z",
)
#: Matches a cell the publisher marked as not applicable.
NA_RE = re.compile(r"\A(n/a|na|--|—)\Z", re.IGNORECASE)


def read_amount(token: str, profile: DocumentProfile) -> str | None:
    """The signed decimal a token states, or ``None`` when it states none.

    The returned string is the printed decimal with its sign, never a float:
    an exact printed price must not be rounded on the way through.

    A bracketed amount is read as a negative only for a publisher whose profile
    says brackets are how it writes one. For any other document ``($0.08140)``
    is not an amount, which makes the caller refuse the row rather than publish
    a credit as though it were a charge.
    """
    plain = MONEY_RE.match(token)
    if plain:
        return f"{plain.group('sign')}{plain.group('num')}"
    if not profile.bracket_negative_amounts:
        return None
    bracketed = BRACKET_MONEY_RE.match(token)
    return f"-{bracketed.group('num')}" if bracketed else None


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
    proration: list[ProrationRule] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    notes: list[Cited[str]] = field(default_factory=list)

    def take(self, *lines: Line) -> None:
        for line in lines:
            self.consumed.add((line.page, line.index))

    def take_span(self, page: int, first_line: int, last_line: int) -> None:
        """Mark every line in ``[first_line, last_line]`` on ``page`` consumed.

        For a table cell read off a ruled border, whose span is a pair of
        integers rather than a run of :class:`Line` objects on hand to pass
        to :meth:`take`.
        """
        for index in range(first_line, last_line + 1):
            self.consumed.add((page, index))

    def extend(self, other: Emission) -> None:
        self.consumed |= other.consumed
        self.charges += other.charges
        self.applicability += other.applicability
        self.tou_windows += other.tou_windows
        self.holidays += other.holidays
        self.cross_references += other.cross_references
        self.proration += other.proration
        self.conditions += other.conditions
        self.notes += other.notes

    def __bool__(self) -> bool:
        return bool(
            self.charges
            or self.applicability
            or self.tou_windows
            or self.holidays
            or self.cross_references
            or self.proration
            or self.conditions
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

    def cite_cell(
        self, page: int, section: str, first_line: int, last_line: int, snippet: str
    ) -> Provenance:
        """Cite a table cell whose span was read off a ruled table, not a Line.

        A cell built from :class:`~ca_tariff_parse.extract.ExtractedTable`
        carries its line span as bare integers rather than :class:`Line`
        objects, because a merged cell's span was measured from its own
        border and does not necessarily match one contiguous run of lines
        assigned to it elsewhere. This is otherwise identical to
        :meth:`cite_span`.
        """
        return Provenance(
            document_id=self.doc.document_id,
            document_sha256=self.doc.sha256,
            page=page,
            sheet=self.doc.sheet_for(page),
            section=section,
            line=first_line,
            snippet=snippet,
            end_line=last_line if last_line != first_line else None,
        )


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


#: Multiple of a section's own median line gap that separates one paragraph
#: from the next. A tolerance, not a position: it says how much clearer than
#: ordinary leading a break has to be, and the leading itself is measured on
#: the page.
PARAGRAPH_SEPARATION = 1.4


def _paragraphs_by_spacing(lines: list[Line]) -> list[list[Line]]:
    """Group lines into paragraphs using the section's own line spacing.

    Under a keyword outline the body sits in one column with no hanging indent,
    so the left edge says nothing about where one paragraph ends. What the
    publisher does set is the vertical space: a paragraph break is a wider gap
    than the leading inside a paragraph. Reading the break off that spacing is
    the same rule the footer band already uses.

    Merging the paragraphs instead would be worse than untidy. Each carries a
    coarse eligibility label, and one paragraph saying who is excluded folded
    into another saying who is included produces a label that is true of
    neither.
    """
    if len(lines) < 2:
        return [list(lines)]
    gaps = sorted(
        later.top - earlier.top for earlier, later in pairwise(lines) if later.page == earlier.page
    )
    median = gaps[len(gaps) // 2] if gaps else 0.0
    groups: list[list[Line]] = [[lines[0]]]
    for earlier, later in pairwise(lines):
        broken = (
            later.page != earlier.page or later.top - earlier.top > median * PARAGRAPH_SEPARATION
        )
        if broken:
            groups.append([later])
        else:
            groups[-1].append(later)
    return groups


def paragraphs(section: Section, *, skip_heading: bool = True) -> list[list[Line]]:
    """Group a section's content lines into logical paragraphs.

    A wrapped continuation line is always indented further than the line that
    began the paragraph, so the left edge plus the numbering pattern is enough
    to rebuild the paragraph structure without guessing.
    """
    lines = section.content_lines
    if skip_heading and lines and section.level > 0 and not section.heading_inline:
        # An inline heading shares its line with the body of the part, so
        # dropping that line would drop text the document put there.
        lines = lines[1:]
    if not lines:
        return []
    if section.heading_inline:
        return _paragraphs_by_spacing(lines)

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
