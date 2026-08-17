"""Parse standalone charge blocks stated as one price per effective date.

These appear as an option inside a schedule rather than in the main table::

    Standby Service Charge - January 1 through December 31
    ($/kW of Contract Capacity per month)
        Effective May 1, 2025          $8.597
        Effective January 1, 2026      $8.855

A commercial sheet prices the same charge across several categories at once,
setting the category names as column headings on the label line::

    Standby Service Charge by Voltage Level  Secondary  Primary  Subtransmission
    ($/kW of Contract Capacity per month)
        Effective May 1, 2025             $8.597    $6.832       $3.451

Reading that shape one price per row swallowed two of the three amounts into
the effective date and emitted the third as though it were the whole charge.
Each amount is now assigned to the heading it sits under and carried in
``applies_to``, and a block whose amounts do not line up with exactly one
heading each is refused outright rather than attributed by position.

One section can hold more than one such block, each with its own label, so
blocks are cut at the first row that is not a dated row. Attributing every
dated row in a section to the first label above it priced a waiver at the
adjustment's name.

The unit is whatever the document states, carried verbatim: a parenthetical
line of its own, or the tail of the label line ("Waiver Rate per excess
KVAR"). A block with no stated unit is not emitted, because the number alone
would not say what it is a price for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import Line, Word, normalize
from ..model import Charge, Cited, Money
from ..segment import Section
from .base import (
    LABEL_MARGIN,
    MONEY_RE,
    Citer,
    Column,
    Emission,
    assign,
    columns_from,
    unit_tail,
)

#: The dating half of a dated row, everything left of its first amount.
EFFECTIVE_RE = re.compile(r"\AEffective\s+(?P<when>\S.*?)\s*\Z")
#: A unit stated on a line of its own, e.g. "($/kW of Contract Capacity per month)".
UNIT_RE = re.compile(r"\A\((?P<unit>[^)]+)\)\s*\Z")


@dataclass(frozen=True, slots=True)
class _Row:
    """One dated row: the line, when it takes effect, and its amounts."""

    line: Line
    when: str
    amounts: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class _Heading:
    """The label and unit that price one block of dated rows."""

    label: Cited[str]
    unit: Cited[str]
    line: Line
    consumed: tuple[Line, ...]


def _read_row(line: Line) -> _Row | None:
    """Read a dated row, or ``None`` when the line is not one.

    Everything from the first amount onwards must itself be an amount. A line
    with prose between its amounts is not a row of a priced table, and reading
    it as one would fold whatever sat in between into the effective date.
    """
    words = line.words
    first = next((at for at, word in enumerate(words) if MONEY_RE.match(word.text)), None)
    if first is None or first == 0:
        return None
    if not all(MONEY_RE.match(word.text) for word in words[first:]):
        return None
    match = EFFECTIVE_RE.match(" ".join(word.text for word in words[:first]))
    if match is None:
        return None
    return _Row(line=line, when=match.group("when"), amounts=tuple(words[first:]))


def _dated_rows(section: Section) -> list[tuple[int, _Row]]:
    found: list[tuple[int, _Row]] = []
    for position, line in enumerate(section.content_lines):
        row = _read_row(line)
        if row is not None:
            found.append((position, row))
    return found


def claims(section: Section) -> bool:
    return len(_dated_rows(section)) >= 2


def _blocks(rows: list[tuple[int, _Row]]) -> list[list[tuple[int, _Row]]]:
    """Cut the dated rows into contiguous blocks, one per priced item."""
    blocks: list[list[tuple[int, _Row]]] = []
    for position, row in rows:
        if blocks and position == blocks[-1][-1][0] + 1:
            blocks[-1].append((position, row))
        else:
            blocks.append([(position, row)])
    return blocks


def _left_text(line: Line, boundary: float) -> str:
    return normalize(" ".join(word.text for word in line.words_left_of(boundary)))


def _heading_for(
    lines: list[Line], first_row: int, boundary: float, citer: Citer, section: str
) -> _Heading | None:
    """Read the label and unit sitting immediately above one block."""
    if first_row == 0:
        return None
    above = lines[first_row - 1]

    parenthetical = UNIT_RE.match(above.text)
    if parenthetical:
        if first_row < 2:
            return None
        label_line = lines[first_row - 2]
        label = _left_text(label_line, boundary)
        if not label:
            return None
        return _Heading(
            label=citer.text(label_line, section, label),
            unit=citer.text(above, section, parenthetical.group("unit").strip()),
            line=label_line,
            consumed=(label_line, above),
        )

    text = _left_text(above, boundary)
    unit = unit_tail(text)
    if unit is None:
        return None
    stem = text.removesuffix(unit).strip()
    if not stem:
        return None
    return _Heading(
        label=citer.text(above, section, stem),
        unit=citer.text(above, section, unit),
        line=above,
        consumed=(above,),
    )


def _assigned(row: _Row, columns: list[Column]) -> list[Column | None] | None:
    """One column per amount, or ``None`` when the alignment is not one to one."""
    if not columns:
        return [None for _ in row.amounts]
    if len(columns) != len(row.amounts):
        return None
    seen: list[Column] = []
    for word in row.amounts:
        column = assign(word, columns)
        if column is None or column in seen:
            return None
        seen.append(column)
    return list(seen)


def _charge(
    row: _Row, word: Word, column: Column | None, heading: _Heading, citer: Citer, section: str
) -> Charge | None:
    money = MONEY_RE.match(word.text)
    if money is None:  # pragma: no cover - _read_row already required this
        return None
    return Charge(
        label=heading.label,
        kind="fixed_charge",
        price=Money(
            amount=Cited(
                value=f"{money.group('sign')}{money.group('num')}",
                provenance=citer.cite(row.line, section),
            ),
            currency="USD",
            unit=heading.unit,
        ),
        effective_from=citer.text(row.line, section, row.when),
        applies_to=(
            citer.text(heading.line, section, column.label) if column is not None else None
        ),
    )


def _parse_block(
    block: list[tuple[int, _Row]], lines: list[Line], citer: Citer, section: str
) -> Emission | None:
    """Read one block whole, or return ``None`` and leave it reported unparsed."""
    widths = {len(row.amounts) for _, row in block}
    if len(widths) != 1:
        # The rows of one block do not price the same number of categories, so
        # which amount belongs to which cannot be read off the page.
        return None
    width = widths.pop()

    # A block that prices one amount per row carries no column headings, so the
    # whole line above it is the label. Only a block pricing several at once is
    # split, and then only at the first amount's own column.
    boundary = (
        min(word.x0 for _, row in block for word in row.amounts) - LABEL_MARGIN
        if width > 1
        else float("inf")
    )
    heading = _heading_for(lines, block[0][0], boundary, citer, section)
    if heading is None:
        # Without a stated label and unit the numbers mean nothing on their
        # own, so nothing is emitted and the block reports as unparsed.
        return None

    columns = columns_from(heading.line.words_right_of(boundary)) if width > 1 else []
    if width != max(len(columns), 1):
        # There is not exactly one heading per amount, so no amount can be said
        # to belong to one category rather than another.
        return None

    emission = Emission()
    for _, row in block:
        assigned = _assigned(row, columns)
        if assigned is None:
            return None
        for word, column in zip(row.amounts, assigned, strict=True):
            charge = _charge(row, word, column, heading, citer, section)
            if charge is None:  # pragma: no cover - defensive
                return None
            emission.charges.append(charge)
        emission.take(row.line)
    emission.take(*heading.consumed)
    return emission


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    for block in _blocks(_dated_rows(section)):
        parsed = _parse_block(block, lines, citer, section.section_id)
        if parsed is not None:
            emission.extend(parsed)

    if emission and section.level > 0 and lines and not section.heading_inline:
        emission.take(lines[0])
    return emission
