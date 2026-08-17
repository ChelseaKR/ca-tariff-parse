"""Parse the column tables that carry the actual prices.

A rate table looks like this on the page::

                                   Effective as of   Effective as of
                                     May 1, 2025     January 1, 2026
    Time-of-Day (5-8 p.m.) Rate (RT02)
    Non-Summer Season (October - May)
        System Infrastructure Fixed Charge per meter    $26.20    $27.00
        Electricity Usage Charge
            Peak $/kWh                                 $0.1724   $0.1776

Which price belongs to which effective date is carried entirely by horizontal
position, so the columns are recovered from the x coordinates of the date row
and every amount is assigned to the column it sits under. An amount that does
not sit clearly under one column is not emitted at all: the line is left
unconsumed and surfaces as unparsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import Line, Word
from ..model import Charge, Cited, Money
from ..segment import Section
from .base import MONEY_RE, NA_RE, Citer, Emission

#: Horizontal gap, in points, that separates two column headings.
COLUMN_GAP = 8.0
#: Distance, in points, an amount may sit from a column centre and still be
#: assigned to it. Beyond this the assignment is treated as ambiguous.
COLUMN_TOLERANCE = 45.0
#: Clear space left of the first column, used to split label from values.
LABEL_MARGIN = 20.0

HEADER_SQUASHED = "effectiveasof"
CATEGORY_IN_HEADING_RE = re.compile(r"rate\s+categor(?:y|ies)\s+([A-Z0-9]+)", re.IGNORECASE)
CATEGORY_IN_CAPTION_RE = re.compile(r"\((?P<code>[A-Z]{2,6}\d{0,2})\)\s*\Z")
TOU_PREFIX_RE = re.compile(r"\A(Super\s+Off-Peak|Off-Peak|Mid-Peak|Peak|On-Peak)\b", re.IGNORECASE)
GROUP_LABEL_RE = re.compile(r"charge\s*\Z", re.IGNORECASE)

#: Unit expressions recognised in a charge label, longest first. Each is a
#: verbatim substring of the source label, never a synthesised unit string.
UNIT_PATTERNS = (
    "$/kWh",
    "per month per meter",
    "per month per unit",
    "per month",
)


class Column:
    """One effective-date column of a rate table."""

    __slots__ = ("label", "x0", "x1")

    def __init__(self, words: list[Word]) -> None:
        self.label = " ".join(word.text for word in words)
        self.x0 = min(word.x0 for word in words)
        self.x1 = max(word.x1 for word in words)

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2.0


def _columns(date_line: Line) -> list[Column]:
    """Split a date row into columns on horizontal whitespace."""
    groups: list[list[Word]] = []
    for word in date_line.words:
        if groups and word.x0 - groups[-1][-1].x1 <= COLUMN_GAP:
            groups[-1].append(word)
        else:
            groups.append([word])
    return [Column(group) for group in groups]


def _find_header(section: Section) -> int | None:
    for position, line in enumerate(section.content_lines):
        if HEADER_SQUASHED in line.squashed:
            return position
    return None


def claims(section: Section) -> bool:
    return _find_header(section) is not None


def _unit_of(label: str) -> str | None:
    for pattern in UNIT_PATTERNS:
        if pattern.lower() in label.lower():
            return pattern
    return None


def _assign(word: Word, columns: list[Column]) -> Column | None:
    best = min(columns, key=lambda column: abs(column.center - word.center))
    if abs(best.center - word.center) > COLUMN_TOLERANCE:
        return None
    return best


@dataclass(slots=True)
class _TableState:
    """Context a row inherits from the rows above it."""

    section: str
    category: Cited[str] | None = None
    season: Cited[str] | None = None


def _read_context_row(line: Line, citer: Citer, state: _TableState) -> bool:
    """Absorb a rate category, season, or group heading. False if unrecognised."""
    caption = CATEGORY_IN_CAPTION_RE.search(line.text)
    if caption:
        state.category = citer.text(line, state.section, caption.group("code"))
        return True
    if "season" in line.squashed:
        state.season = citer.text(line, state.section, line.text)
        return True
    return bool(GROUP_LABEL_RE.search(line.text))


def _read_value_row(
    line: Line,
    label: str,
    values: list[Word],
    columns: list[Column],
    effective_by_column: dict[str, Cited[str]],
    citer: Citer,
    state: _TableState,
) -> list[Charge] | None:
    """Read one priced row, or return None if it cannot be read with certainty.

    The row is built up locally and returned whole. A row is never emitted
    partially: if any amount cannot be attributed to exactly one effective-date
    column, the entire row is refused.
    """
    unit_text = _unit_of(label)
    if unit_text is None:
        # A priced row whose unit the parser cannot read is never emitted with a
        # guessed unit.
        return None

    kind = "energy_usage" if unit_text == "$/kWh" else "fixed_charge"
    tou_match = TOU_PREFIX_RE.match(label)
    tou_period = citer.text(line, state.section, tou_match.group(1)) if tou_match else None

    row: list[Charge] = []
    accounted = False
    for word in values:
        if NA_RE.match(word.text):
            # The publisher printed "n/a": there is no price for this cell, so
            # no charge is emitted. Inventing one would be a fabrication.
            accounted = True
            continue
        money = MONEY_RE.match(word.text)
        if not money:
            continue
        column = _assign(word, columns)
        if column is None:
            return None
        row.append(
            Charge(
                label=citer.text(line, state.section, label),
                kind=kind,
                price=Money(
                    amount=Cited(
                        value=f"{money.group('sign')}{money.group('num')}",
                        provenance=citer.cite(line, state.section),
                    ),
                    currency="USD",
                    unit=citer.text(line, state.section, unit_text),
                ),
                effective_from=effective_by_column[column.label],
                rate_category=state.category,
                season=state.season,
                tou_period=tou_period,
            )
        )
        accounted = True

    return row if accounted else None


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    header_at = _find_header(section)
    if header_at is None or header_at + 1 >= len(lines):
        return emission

    date_line = lines[header_at + 1]
    columns = _columns(date_line)
    if not columns:
        return emission

    boundary = min(column.x0 for column in columns) - LABEL_MARGIN
    effective_by_column = {
        column.label: Cited(
            value=column.label,
            provenance=citer.cite(date_line, section.section_id),
        )
        for column in columns
    }
    emission.take(lines[header_at], date_line)

    state = _TableState(section=section.section_id)
    heading_match = CATEGORY_IN_HEADING_RE.search(section.heading)
    if heading_match:
        state.category = citer.text(lines[0], section.section_id, heading_match.group(1))

    for line in lines[header_at + 2 :]:
        values = list(line.words_right_of(boundary))
        label = " ".join(word.text for word in line.words_left_of(boundary)).strip()
        priced = any(MONEY_RE.match(word.text) or NA_RE.match(word.text) for word in values)

        if not priced:
            if _read_context_row(line, citer, state):
                emission.take(line)
            # Otherwise leave it unconsumed so it is reported as unparsed.
            continue

        row = _read_value_row(line, label, values, columns, effective_by_column, citer, state)
        if row is None:
            continue
        emission.charges.extend(row)
        emission.take(line)

    return emission
