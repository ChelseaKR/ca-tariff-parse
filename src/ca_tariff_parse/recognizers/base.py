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
from collections.abc import Iterable
from dataclasses import dataclass, field

from ..extract import LayoutDoc, Line, normalize
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
