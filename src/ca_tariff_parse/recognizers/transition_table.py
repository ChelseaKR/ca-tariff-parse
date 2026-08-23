"""Parse a table that states its unit in a column of its own.

Every other priced table this parser reads states a row's unit inside its
label, or once in a heading over the whole block. One SMUD commercial
schedule prices its post-2027 rates differently::

    Season and Charge Component               Unit      2028*
    CITS-0: C&I Secondary 0-20 kW
    System Infrastructure Fixed Charge         per month  $44.45
    Maximum Demand Charge                      per kW     $4.101
    Non-Summer Peak                            per kWh    $0.1506
    ...
    *Subject to future rate increases.
    **Time-of-Day periods apply as described in Section VII.

The unit sits in its own column, headed literally "Unit", and the price is
dated to a bare year the header states rather than to a date printed on the
row or read from the sheet's footer -- this table pre-dates when the sheet
itself takes effect, so nothing but the header names the year the price is
for. Both are unlike every table `sheet_rates.py`, `rate_table.py` and
`dated_charge.py` already read, which is why none of them claims this shape.

The table carries no ruled border (see the "still open" note in
[ADR 0007](../../docs/adr/0007-read-a-merged-cell-from-its-own-border.md)),
so its columns are read the way [ADR
0004](../../docs/adr/0004-read-table-geometry-from-the-document.md) already
reads any other unruled table: from the x positions of the header's own
words. Finding both a column literally headed "Unit" and at least one headed
with a bare year is the claim -- a table lacking either is left alone, which
keeps this from firing on an ordinary priced table that merely happens to
end a row in a number.

A rate category caption above a run of rows, e.g. "CITS-0: C&I Secondary
0-20 kW", is the same shape `rate_table.py` already reads off a caption row;
its code is read the same way here rather than duplicated.
"""

from __future__ import annotations

import re

from ..extract import Line, normalize, squash
from ..model import Charge, Cited, Money
from ..profiles import DocumentProfile
from ..segment import Section
from .base import (
    ENERGY_UNITS,
    LABEL_MARGIN,
    NA_RE,
    Citer,
    Column,
    Emission,
    assign,
    category_code,
    columns_from,
    read_amount,
)

#: The column literally headed "Unit", squashed for comparison.
UNIT_HEADER = "unit"
#: A column headed with a bare year, optionally carrying a footnote asterisk,
#: e.g. "2028*". Not a date: the table dates a whole column at once, and the
#: printed year is carried exactly as the header states it, footnote and all.
YEAR_HEADER_RE = re.compile(r"\A(?:19|20)\d{2}\*{0,3}\Z")


def _find_header(section: Section) -> tuple[int, list[Column]] | None:
    """The header line and its columns, or ``None`` when this section has none."""
    for position, line in enumerate(section.content_lines):
        columns = columns_from(line.words)
        if len(columns) < 3:
            continue
        unit_at = next((i for i, c in enumerate(columns) if squash(c.label) == UNIT_HEADER), None)
        if unit_at is None:
            continue
        year_columns = columns[unit_at + 1 :]
        if year_columns and all(YEAR_HEADER_RE.match(c.label) for c in year_columns):
            return position, columns
    return None


def claims(section: Section) -> bool:
    return _find_header(section) is not None


def _read_row(
    line: Line, value_columns: list[Column], boundary: float
) -> tuple[str, dict[str, list[str]]] | None:
    """The row's label and, per value column label, the token(s) sitting under it.

    Every word right of ``boundary`` must be assignable to exactly one value
    column; a word that is not is what tells a row of this table apart from
    an unrelated line sharing its page, and refuses the row rather than
    guessing which column it belongs to.
    """
    label = normalize(" ".join(word.text for word in line.words_left_of(boundary)))
    if not label:
        return None
    by_column: dict[str, list[str]] = {column.label: [] for column in value_columns}
    for word in line.words_right_of(boundary):
        column = assign(word, value_columns)
        if column is None:
            return None
        by_column[column.label].append(word.text)
    if not any(by_column.values()):
        return None
    return label, by_column


def _row_charges(
    line: Line,
    label: str,
    unit_text: str,
    by_column: dict[str, list[str]],
    year_columns: list[Column],
    year_dates: dict[str, Cited[str]],
    category: Cited[str] | None,
    citer: Citer,
    section: str,
    profile: DocumentProfile,
) -> list[Charge] | None:
    """Every year's charge for one row, or ``None`` if any year cannot be read.

    A row is committed whole or not at all: pricing some of its years and
    silently skipping the rest would publish a table that looks complete
    when a year of it was not read with certainty.
    """
    kind = "energy_usage" if squash(unit_text) in ENERGY_UNITS else "fixed_charge"
    charges: list[Charge] = []
    for column in year_columns:
        tokens = by_column[column.label]
        if len(tokens) != 1:
            # Either nothing sits under this year, or more than one token
            # does, and either way one amount cannot be read with certainty.
            return None
        token = tokens[0]
        if NA_RE.match(token):
            continue
        amount = read_amount(token, profile)
        if amount is None:
            return None
        charges.append(
            Charge(
                label=citer.text(line, section, label),
                kind=kind,
                price=Money(
                    amount=Cited(value=amount, provenance=citer.cite(line, section)),
                    currency="USD",
                    unit=citer.text(line, section, unit_text),
                ),
                effective_from=year_dates[column.label],
                rate_category=category,
            )
        )
    return charges


def parse(section: Section, citer: Citer, profile: DocumentProfile) -> Emission:
    emission = Emission()
    found = _find_header(section)
    if found is None:
        return emission
    header_at, columns = found
    lines = section.content_lines
    header_line = lines[header_at]

    _label_column, unit_column, *year_columns = columns
    value_columns = [unit_column, *year_columns]
    boundary = unit_column.x0 - LABEL_MARGIN
    year_dates = {
        column.label: citer.text(header_line, section.section_id, column.label)
        for column in year_columns
    }

    category: Cited[str] | None = None
    for line in lines[header_at + 1 :]:
        code = category_code(line.text)
        if code is not None:
            category = citer.text(line, section.section_id, code)
            emission.take(line)
            continue

        row = _read_row(line, value_columns, boundary)
        if row is None:
            continue
        label, by_column = row
        unit_tokens = by_column[unit_column.label]
        if not unit_tokens:
            continue

        charges = _row_charges(
            line,
            label,
            normalize(" ".join(unit_tokens)),
            by_column,
            year_columns,
            year_dates,
            category,
            citer,
            section.section_id,
            profile,
        )
        if charges is None:
            # The row could not be read with certainty. An empty list is a
            # different outcome from this and is not it: that is every year
            # column explicitly marked "n/a", which is understood, just
            # priced at nothing, and still credited below.
            continue
        emission.charges.extend(charges)
        emission.take(line)

    if emission.charges:
        # The header is only credited once it actually dated a row: a table
        # this recognizer found the shape of but could not read a single
        # price from is not "understood", and its header should not look
        # otherwise.
        emission.take(header_line)
    return emission
