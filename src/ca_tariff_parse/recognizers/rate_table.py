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

from ..extract import Line, Word, squash
from ..model import Charge, Cited, Money
from ..segment import Section
from ..trace import fence, refuse
from .base import (
    LABEL_MARGIN,
    MONEY_RE,
    NA_RE,
    PERIOD_ALTERNATION,
    Citer,
    Column,
    Emission,
    assign,
    category_code,
    columns_from,
    unit_tail,
)

HEADER_SQUASHED = "effectiveasof"
CATEGORY_IN_HEADING_RE = re.compile(r"rate\s+categor(?:y|ies)\s+([A-Z0-9]+)", re.IGNORECASE)
TOU_PREFIX_RE = re.compile(rf"\A(?P<period>{PERIOD_ALTERNATION})\b", re.IGNORECASE)
GROUP_LABEL_RE = re.compile(r"charge\s*\Z", re.IGNORECASE)
#: A row naming the part of the year the rows beneath it apply to. Residential
#: sheets write "Non-Summer Season (October - May)"; the nondemand commercial
#: table writes "All Year".
ALL_YEAR_RE = re.compile(r"\A(All Year|All Seasons)\Z", re.IGNORECASE)
#: Squashed unit that makes a row an energy charge rather than a fixed one.
ENERGY_UNIT_SQUASHED = "$/kwh"


#: Named refusal points. `explain` reports these by identifier, and the ADR on
#: each is the decision a reader who disagrees with a refusal should argue
#: with rather than the call site.
UNIT_NOT_IN_LABEL = fence(
    "rate_table.unit-not-in-label",
    adr="ADR 0002",
    reason=(
        "the row is priced but its label states no unit, and a price quoted in "
        "a unit nobody printed is a value this parser did not read"
    ),
)
CELL_NOT_AN_AMOUNT = fence(
    "rate_table.cell-not-an-amount",
    adr="ADR 0002",
    reason=(
        "a cell in the value area is neither a currency amount nor an explicit "
        "n/a, so the row is refused whole: skipping the cell would publish the "
        "rest of the row as though it were the whole row"
    ),
)
VALUE_NOT_UNDER_ONE_COLUMN = fence(
    "rate_table.value-not-under-one-column",
    adr="ADR 0004",
    reason=(
        "the amount does not sit clearly under one effective-date column, and "
        "which date a price belongs to is carried entirely by its horizontal "
        "position on the page"
    ),
)
NO_EFFECTIVE_DATE_HEADER = fence(
    "rate_table.no-effective-date-header",
    adr="ADR 0004",
    reason=(
        "the section carries the table keyword but no readable row of "
        "effective-date column headings beneath it, so no amount under it can "
        "be dated"
    ),
)


def _find_header(section: Section) -> int | None:
    for position, line in enumerate(section.content_lines):
        if HEADER_SQUASHED in line.squashed:
            return position
    return None


def claims(section: Section) -> bool:
    return _find_header(section) is not None


@dataclass(slots=True)
class _TableState:
    """Context a row inherits from the rows above it."""

    section: str
    category: Cited[str] | None = None
    season: Cited[str] | None = None


def _read_context_row(line: Line, citer: Citer, state: _TableState) -> bool:
    """Absorb a rate category, season, or group heading. False if unrecognised."""
    code = category_code(line.text)
    if code is not None:
        state.category = citer.text(line, state.section, code)
        return True
    if "season" in line.squashed or ALL_YEAR_RE.match(line.text):
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
    unit_text = unit_tail(label)
    if unit_text is None:
        # A priced row whose unit the parser cannot read is never emitted with a
        # guessed unit.
        refuse(
            "rate_table",
            UNIT_NOT_IN_LABEL,
            page=line.page,
            line=line.index,
            detail=label or line.text,
        )
        return None

    kind = "energy_usage" if squash(unit_text) == ENERGY_UNIT_SQUASHED else "fixed_charge"
    tou_match = TOU_PREFIX_RE.match(label)
    tou_period = citer.text(line, state.section, tou_match.group("period")) if tou_match else None

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
            # A cell in the value area that is neither an amount nor an
            # explicit "n/a" cannot be read. Skipping it would publish the rest
            # of the row as though it were the whole row, which is how a table
            # of three prices comes out carrying two. A second publisher writes
            # a negative as "($0.08140)", which is a real price in a form this
            # parser does not read, so the whole row is refused instead.
            refuse(
                "rate_table",
                CELL_NOT_AN_AMOUNT,
                page=line.page,
                line=line.index,
                detail=word.text,
            )
            return None
        column = assign(word, columns)
        if column is None:
            refuse(
                "rate_table",
                VALUE_NOT_UNDER_ONE_COLUMN,
                page=line.page,
                line=line.index,
                detail=word.text,
            )
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

    # No fence is registered here, and the reason is worth stating rather than
    # leaving as an omission. `parse` calls this only when some word in the
    # value area matched an amount or an explicit n/a, and every path through
    # the loop for such a word either returns early or sets `accounted`. So
    # this branch cannot be reached from the only caller, and a fence on it
    # would be a name `explain` could print in a table and never report --
    # exactly what `test_explain.py`'s fence census refuses.
    return row if accounted else None


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    header_at = _find_header(section)
    if header_at is None or header_at + 1 >= len(lines):
        if lines:
            refuse(
                "rate_table",
                NO_EFFECTIVE_DATE_HEADER,
                page=lines[0].page,
                line=lines[0].index,
                detail=section.heading,
            )
        return emission

    date_line = lines[header_at + 1]
    columns = columns_from(date_line.words)
    if not columns:
        refuse(
            "rate_table",
            NO_EFFECTIVE_DATE_HEADER,
            page=date_line.page,
            line=date_line.index,
            detail=date_line.text,
        )
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
