"""Parse a priced table that dates itself from the sheet rather than the row.

One publisher's tables head every price column with the date it takes effect.
Another's do not: they set one amount per row, state the unit once in a heading
over the block, and let the sheet's own footer date the lot::

    Total Energy Rates ($ per kWh)
        Tier 1 Usage (0% - 100% of Baseline)          $0.32561 (R)
        Tier 2 Usage (101% - 400% of Baseline)        $0.40702 (R)

    Vintage Power Charge Indifference Adjustment Rate
    (per kWh)
        2009 Vintage                                  $0.02973 (I)
        2025 Vintage                                 ($0.01011) (I)

Everything here is read off the page: the unit from the heading's own
parenthesis, the label from the row, the amount column from the alignment the
amounts share, the date from the footer of the sheet the row is printed on.
The one thing that is not on the page is what a bracket means, and that comes
from the document profile: for a publisher who writes negatives in accounting
brackets ``($0.01011)`` is a credit of a penny, and for anyone else it is a
token this parser cannot read and the row is refused whole.

What this refuses is most of what it sees, on purpose.

* **A block with no heading stating its unit.** A run of prices under
  "Conservation Incentive Adjustment:" says nothing about what it is a price
  per, and the heading two blocks above may be for another unit entirely.
* **A page setting amounts in more than one column.** A row carrying one amount
  in a two column table has to say which column it sits under, and a block that
  has no column headings of its own cannot. This is the ADR 0004 standby charge
  again: three prices on one row, one of them published as the whole.
* **A row dating itself.** "Effective May 1, 2025 $8.597" is a dated row and
  belongs to the dated-charge shape. Read here it would be labelled with its
  own date and then dated a second time from the footer.
* **Anything but an amount in the value area**, and any amount outside it. A
  row is committed whole or not at all.
* **A sheet whose footer states no effective date**, because there is then
  nothing to date the price from.

The right margin is not the value area. These sheets flag a changed line there
with a bracketed capital and a change bar, so the tokens right of the amount
are neither read nor treated as cells; they are checked to be sure none of them
is a price, and the row is refused if any is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import Line, Word, normalize, squash
from ..model import Charge, Cited, Money
from ..profiles import DocumentProfile
from ..segment import Section
from .base import (
    COLUMN_TOLERANCE,
    ENERGY_UNITS,
    LABEL_MARGIN,
    Citer,
    Emission,
    read_amount,
    unit_tail,
)

#: A unit the publisher prints in brackets at the end of a heading line, as in
#: "Total Energy Rates ($ per kWh)" or on a line of its own, "(per kWh)".
TRAILING_UNIT_RE = re.compile(r"\((?P<unit>[^()]+)\)\s*\Z")
#: A row that states its own effective date. Kept out of this shape entirely.
DATED_ROW_RE = re.compile(r"\AEffective\s+\S", re.IGNORECASE)
#: A right-margin annotation: a single capital in brackets, which is how a
#: changed line is flagged, or a token with no letter or digit in it at all,
#: which is how the change bar beside it prints. Nothing else may follow the
#: amount, so a trailing word that might qualify the price refuses the row.
MARGIN_TOKEN_RE = re.compile(r"\A(?:\([A-Z]\)|[^0-9A-Za-z]+)\Z")
#: A cell the publisher marked as carrying no price, written here as a run of
#: dashes. A row holding one is priced across columns this block does not name,
#: so it is refused rather than read as though the remaining amount were the
#: whole row.
UNPRICED_CELL_RE = re.compile(r"\A(?:n/a|na|-{2,}|\u2014+|\u2013+)\Z", re.IGNORECASE)
#: Fewest priced rows a heading must be followed by before this shape is
#: claimed. One priced line under a heading is as likely to be a sentence.
MINIMUM_ROWS = 2


def _without_margin(words: tuple[Word, ...]) -> list[Word]:
    """The line's words with its right-margin annotation removed."""
    kept = list(words)
    while kept and MARGIN_TOKEN_RE.match(kept[-1].text):
        kept.pop()
    return kept


@dataclass(frozen=True, slots=True)
class _Row:
    """One priced row: the line, its label, and the amount it states."""

    line: Line
    label: str
    amount: str
    word: Word
    label_words: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class _Heading:
    """The label and unit a block of rows is priced under."""

    label: Line
    label_text: str
    unit: str
    lines: tuple[Line, ...]


def _read_row(line: Line, profile: DocumentProfile) -> _Row | None:
    """Read a row of ``label ... amount``, or ``None`` when the line is not one."""
    if any(UNPRICED_CELL_RE.match(word.text) for word in line.words):
        return None
    words = _without_margin(line.words)
    if not words:
        return None
    amounts = [(position, read_amount(word.text, profile)) for position, word in enumerate(words)]
    priced = [(position, value) for position, value in amounts if value is not None]
    if len(priced) != 1:
        # No amount means this is not a row; more than one means the table has
        # columns, and which heading each amount sits under cannot be read from
        # a block that states none.
        return None
    at, value = priced[0]
    if at != len(words) - 1 or at == 0:
        # The amount ends the row. Anything after it that is not margin
        # annotation is unread text beside a price, and anything before the
        # first word is not a label.
        return None
    label = normalize(" ".join(word.text for word in words[:at]))
    if not label or DATED_ROW_RE.match(label):
        return None
    return _Row(
        line=line,
        label=label,
        amount=value,
        word=words[at],
        label_words=tuple(words[:at]),
    )


def _priced(line: Line, profile: DocumentProfile) -> bool:
    return any(read_amount(word.text, profile) is not None for word in line.words)


def _heading_text(line: Line, profile: DocumentProfile) -> str | None:
    """A heading line's text, or ``None`` when the line carries a price.

    A line holding an amount is a row of some table, not a heading over one.
    Reading one as a heading would label a whole block with another block's
    priced row.
    """
    if _priced(line, profile):
        return None
    return normalize(" ".join(word.text for word in _without_margin(line.words)))


def _read_heading(lines: list[Line], at: int, profile: DocumentProfile) -> _Heading | None:
    """Read the heading that opens a block of rows starting at ``lines[at]``.

    The heading is the line above, either as "<label> (<unit>)" or as a bare
    "(<unit>)" whose label is the line above that. Either way the unit is the
    publisher's own parenthesis and the label is the text beside it, verbatim.
    """
    if at == 0:
        return None
    above = lines[at - 1]
    text = _heading_text(above, profile)
    if text is None:
        return None
    match = TRAILING_UNIT_RE.search(text)
    if match is None:
        return None
    unit = unit_tail(match.group("unit").strip())
    if unit is None:
        return None
    label_text = text[: match.start()].strip()
    if label_text:
        return _Heading(label=above, label_text=label_text, unit=unit, lines=(above,))
    if at < 2:
        return None
    label_line = lines[at - 2]
    label_text = _heading_text(label_line, profile) or ""
    if not label_text or TRAILING_UNIT_RE.search(label_text):
        return None
    return _Heading(label=label_line, label_text=label_text, unit=unit, lines=(label_line, above))


def _one_amount_column(rows: list[_Row]) -> bool:
    """True when every amount in the block sits in the same column."""
    centers = [row.word.center for row in rows]
    return max(centers) - min(centers) <= COLUMN_TOLERANCE


def _page_has_one_amount_column(lines: list[Line], profile: DocumentProfile) -> bool:
    """True when this page of this section sets its amounts in one column.

    A page that sets them in two is a table with columns. A block on such a
    page that states no column headings of its own cannot say which column its
    single amount belongs to, so nothing is read from that page at all.
    """
    centers = [
        word.center
        for line in lines
        for word in line.words
        if read_amount(word.text, profile) is not None
    ]
    if not centers:
        return False
    return max(centers) - min(centers) <= COLUMN_TOLERANCE


def _labels_clear_the_values(rows: list[_Row]) -> bool:
    """True when every label stops clear of the column the amounts sit in.

    A table sets its label and its price in separate columns. A sentence that
    happens to end in a price does not, and would otherwise be read as a row
    whose label is the first half of the sentence.
    """
    boundary = min(row.word.x0 for row in rows) - LABEL_MARGIN
    return all(word.x1 <= boundary for row in rows for word in row.label_words)


def _blocks(lines: list[Line], profile: DocumentProfile) -> list[tuple[_Heading, list[_Row]]]:
    """Cut a page of one section into heading-and-rows blocks.

    A block runs from a heading stating a unit to the first line that is not a
    priced row. A run of rows whose preceding line states no unit opens no
    block and is left for the unparsed report.
    """
    found: list[tuple[_Heading, list[_Row]]] = []
    position = 0
    while position < len(lines):
        row = _read_row(lines[position], profile)
        if row is None:
            position += 1
            continue
        start = position
        rows = [row]
        position += 1
        while position < len(lines):
            following = _read_row(lines[position], profile)
            if following is None:
                break
            rows.append(following)
            position += 1
        heading = _read_heading(lines, start, profile)
        if (
            heading is not None
            and len(rows) >= MINIMUM_ROWS
            and _one_amount_column(rows)
            and _labels_clear_the_values(rows)
        ):
            found.append((heading, rows))
    return found


def _by_page(section: Section) -> list[list[Line]]:
    """The section's content lines, split at every page break.

    A block never spans a sheet, because the sheet is what dates it.
    """
    pages: list[list[Line]] = []
    for line in section.content_lines:
        if pages and pages[-1][-1].page == line.page:
            pages[-1].append(line)
        else:
            pages.append([line])
    return pages


def _candidates(section: Section, profile: DocumentProfile) -> list[tuple[_Heading, list[_Row]]]:
    return [
        block
        for lines in _by_page(section)
        if _page_has_one_amount_column(lines, profile)
        for block in _blocks(lines, profile)
    ]


def claims(section: Section, profile: DocumentProfile) -> bool:
    return bool(_candidates(section, profile))


def parse(
    section: Section,
    citer: Citer,
    profile: DocumentProfile,
    effective_by_page: dict[int, Cited[str]],
) -> Emission:
    emission = Emission()
    for heading, rows in _candidates(section, profile):
        effective = effective_by_page.get(rows[0].line.page)
        if effective is None:
            # The sheet's footer does not state when it takes effect, so there
            # is nothing to date these prices from and none is emitted.
            continue
        label = citer.text(heading.label, section.section_id, heading.label_text)
        unit = citer.text(heading.label, section.section_id, heading.unit)
        kind = "energy_usage" if squash(heading.unit) in ENERGY_UNITS else "fixed_charge"
        for row in rows:
            emission.charges.append(
                Charge(
                    label=citer.text(row.line, section.section_id, row.label),
                    kind=kind,
                    price=Money(
                        amount=Cited(
                            value=row.amount,
                            provenance=citer.cite(row.line, section.section_id),
                        ),
                        currency="USD",
                        unit=unit,
                    ),
                    effective_from=effective,
                    group=label,
                )
            )
            emission.take(row.line)
        emission.take(*heading.lines)
    return emission
