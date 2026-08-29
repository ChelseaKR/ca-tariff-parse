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
* **A page setting amounts in more than one column and naming none of them.**
  A row carrying one amount in a two column table has to say which column it
  sits under, and a page that sets no words over its columns cannot. This is
  the ADR 0004 standby charge again: three prices on one row, one of them
  published as the whole. Where the page does name them, the names are read
  off it and each amount is attributed to the column it sits under; see
  ADR 0012, and the refusals that come with it below.
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

On a page that names its columns, a row is read across them, and what it
refuses is the point of it::

    Total Bundled Time-of-Use Rates          B-1 Rates    B1-ST Rates
    Total TOU Energy Rates ($ per kWh)
        Peak Summer                           $0.47087       $0.49377
        Partial-Peak Winter (for B1-ST only)       ---       $0.36632

* A row carries one cell per named column, each sitting under exactly one of
  them, or it is refused whole. A row holding fewer cells than the table has
  columns is refused, because its single price may be one column's or the whole
  row's and the page does not say which.
* A cell the publisher marked with dashes is read as that column having no
  price for that row, rather than as a reason to refuse the row. It emits
  nothing itself; a row of nothing but dashes prices nothing and is refused.
* The filing markers a regulated publisher sets beside a changed cell are
  skipped inside the value area for the same reason they are skipped at the end
  of it, and under the same rule (ADR 0010). They are not cells and are never
  read as prices.
"""

from __future__ import annotations

import re
from collections.abc import Callable
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
    Column,
    Emission,
    assign,
    columns_from,
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
#: Fewest columns a line has to set words over before it is read as naming a
#: table's columns. One is a heading over a single column of amounts, which
#: this module already reads without needing anything named.
MINIMUM_NAMED_COLUMNS = 2


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
    unit_line: Line | None = None
    """The line the unit was read from, when it is not the label's own line.

    A table can head its components with one unit and then name each component
    on a line of its own, in which case the block's label and its unit are on
    different lines and the unit has to be cited to the line that states it.
    """
    unit_lines: tuple[Line, ...] | None = None
    """The lines the unit was read from, when the publisher broke it across a
    line ending. Cited as the span it is: half of "($ per customer per day)"
    appears on each line and the whole of it on neither."""

    @property
    def unit_source(self) -> Line:
        return self.unit_line if self.unit_line is not None else self.label


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


def _heading_text(
    line: Line, profile: DocumentProfile, naming: _Naming | None = None
) -> str | None:
    """A heading line's text, or ``None`` when the line carries a price.

    A line holding an amount is a row of some table, not a heading over one.
    Reading one as a heading would label a whole block with another block's
    priced row.

    A page can set its column names on the same line as the heading that states
    the unit, which is how one of these publishers heads its unbundling sheets.
    Those words name the columns, not the table, so where this line is the one
    naming them they are not part of its text: without that, the unit ends up
    read as "$ per kWh) PEAK OFF-PEAK" or not read at all.
    """
    if _priced(line, profile):
        return None
    words = _without_margin(line.words)
    if naming is not None and line is naming.line:
        edge = min(column.x0 for column in naming.columns)
        words = [word for word in words if word.x1 <= edge]
    return normalize(" ".join(word.text for word in words))


def _opens_one_bracket(text: str) -> bool:
    """True when the line leaves exactly one bracket open at its end."""
    return text.count("(") - text.count(")") == 1


def _closes_one_bracket(text: str) -> bool:
    """True when the line closes exactly one bracket it did not open."""
    return text.count(")") - text.count("(") == 1


def _heading_at(
    lines: list[Line], position: int, profile: DocumentProfile, naming: _Naming | None = None
) -> tuple[str, tuple[Line, ...]] | None:
    """The heading text at ``position``, joined across a line ending if it is.

    A publisher can open the bracket its unit is written in on one line and
    close it on the next::

        Base Services Charge Rates by Component ($ per customer
        per day)
            Distribution
                Income Tier 1                          ($0.10751)

    Neither line states a unit on its own: the first opens a bracket it never
    closes and the second closes one it never opened. What settles the join is
    the publisher's own punctuation, not a guess about the line ending, so the
    join is only made where the bracket count says a bracket is open and where
    the very next line closes it. A bracket that stays open is not joined to
    anything, and neither is one that takes more than one line ending to close:
    both leave the heading unread, and the block refused.
    """
    text = _heading_text(lines[position], profile, naming)
    if text is None:
        return None
    if position > 0 and _closes_one_bracket(text):
        above = _heading_text(lines[position - 1], profile, naming)
        if above is not None and _opens_one_bracket(above):
            joined = normalize(f"{above} {text}")
            return joined, (lines[position - 1], lines[position])
    return text, (lines[position],)


def _read_heading(
    lines: list[Line], at: int, profile: DocumentProfile, naming: _Naming | None = None
) -> _Heading | None:
    """Read the heading that opens a block of rows starting at ``lines[at]``.

    The heading is the line above, either as "<label> (<unit>)" or as a bare
    "(<unit>)" whose label is the line above that. Either way the unit is the
    publisher's own parenthesis and the label is the text beside it, verbatim.
    """
    if at == 0:
        return None
    read = _heading_at(lines, at - 1, profile, naming)
    if read is None:
        return None
    text, span = read
    above = span[0]
    match = TRAILING_UNIT_RE.search(text)
    if match is None:
        return None
    unit = unit_tail(match.group("unit").strip())
    if unit is None:
        return None
    label_text = text[: match.start()].strip()
    if label_text:
        return _Heading(
            label=above,
            label_text=label_text,
            unit=unit,
            lines=span,
            unit_lines=span if len(span) > 1 else None,
        )
    if at < 2 or len(span) > 1:
        return None
    label_line = lines[at - 2]
    label_text = _heading_text(label_line, profile, naming) or ""
    if not label_text or TRAILING_UNIT_RE.search(label_text):
        return None
    # The unit is stated on ``above`` and the label on the line over it, so the
    # unit is cited to the line that prints it. Cited to the label's line, the
    # snippet would not contain the words the citation is for.
    return _Heading(
        label=label_line,
        label_text=label_text,
        unit=unit,
        lines=(label_line, above),
        unit_line=above,
    )


def _is_sub_heading(line: Line, text: str, row_start: float) -> bool:
    """True when this line heads the rows below it rather than being one of them.

    Read off the indentation the publisher set: a component's name starts left
    of the rows it groups, which is how the page says the rows are under it. A
    line starting level with its rows, or right of them, groups nothing.
    """
    return bool(text) and bool(line.words) and line.words[0].x0 < row_start


def _reaching_heading(
    lines: list[Line],
    at: int,
    profile: DocumentProfile,
    row_start: float,
    is_row: Callable[[Line], bool],
    naming: _Naming | None = None,
) -> _Heading | None:
    """The heading of a block whose own line above it states no unit.

    A rate sheet heads a table once, with its unit, and then names each
    component of it on a line of its own::

        Energy Rates by Component ($ per kWh)          PEAK      OFF-PEAK
        Generation:
            Summer (all usage)                      $0.20782    $0.10482
        Distribution**:
            Summer (all usage)                      $0.20388    $0.18388

    The unit reaches over the table it heads, and the table is what sits under
    it: its own rows, and the lines that name the components grouping them.
    Anything else ends the reach, and the block is refused rather than priced
    in a unit stated over something else.

    The nearest of those component lines is the block's own label. The unit
    comes from the first line above that states one, and it has to be set left
    of every component line it reaches over: a heading level with them is
    another heading like them rather than one over them, and taking its unit
    would price a block under a unit stated for a different table.
    """
    label_line: Line | None = None
    label_text = ""
    passed: list[Line] = []
    position = at - 1
    previous_was_heading = False
    while position >= 0:
        line = lines[position]
        read = _heading_at(lines, position, profile, naming)
        if read is None:
            # A priced line. It belongs to this table, or the reach ends here.
            if not is_row(line):
                return None
            previous_was_heading = False
            position -= 1
            continue
        text, span = read
        line = span[0]
        match = TRAILING_UNIT_RE.search(text)
        if match is not None:
            unit = unit_tail(match.group("unit").strip())
            stem = text[: match.start()].strip()
            if unit is None or not stem or label_line is None:
                return None
            if line.words and line.words[0].x0 >= min(
                heading.words[0].x0 for heading in passed if heading.words
            ):
                # A heading that groups the component names below it is set
                # left of them. One set level with them is their sibling, not
                # their parent, and its unit is a statement about its own rows.
                return None
            return _Heading(
                label=label_line,
                label_text=label_text,
                unit=unit,
                lines=(*span, label_line),
                unit_line=line,
                unit_lines=span if len(span) > 1 else None,
            )
        if previous_was_heading or not _is_sub_heading(line, text, row_start):
            # Two lines running that are neither rows nor a unit heading are
            # prose or another table's furniture, and a line that does not sit
            # left of the rows heads nothing. Either way the reach stops rather
            # than being guessed past.
            return None
        if label_line is None:
            label_line, label_text = line, text
        passed.append(line)
        previous_was_heading = True
        position -= len(span)
    return None


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
        heading = _read_heading(lines, start, profile) or _reaching_heading(
            lines,
            start,
            profile,
            min(row.label_words[0].x0 for row in rows if row.label_words),
            lambda line: _read_row(line, profile) is not None,
        )
        if (
            heading is not None
            and len(rows) >= MINIMUM_ROWS
            and _one_amount_column(rows)
            and _labels_clear_the_values(rows)
        ):
            found.append((heading, rows))
    return found


#: One cell of a row read across named columns: the column it sits under, the
#: amount it states, and the word it was read from. ``amount`` is ``None`` for
#: a cell the publisher marked as carrying no price.
@dataclass(frozen=True, slots=True)
class _Cell:
    column: Column
    amount: str | None
    word: Word


@dataclass(frozen=True, slots=True)
class _WideRow:
    """One row of a table whose columns the page names."""

    line: Line
    label: str
    cells: tuple[_Cell, ...]
    label_words: tuple[Word, ...]


@dataclass(frozen=True, slots=True)
class _Naming:
    """The line a page sets its column names on, and the columns it names."""

    line: Line
    columns: tuple[Column, ...]


def _cell_kind(word: Word, profile: DocumentProfile) -> str | None:
    """What a word is inside a row's value area, or ``None`` if it is not in one.

    The unpriced cell is tested before the filing marker because a run of
    dashes matches both, and it is a cell: it says this column has no price for
    this row, which is a fact the publisher printed.
    """
    if read_amount(word.text, profile) is not None:
        return "amount"
    if UNPRICED_CELL_RE.match(word.text):
        return "unpriced"
    if MARGIN_TOKEN_RE.match(word.text):
        return "marker"
    return None


def _naming_line(lines: list[Line], profile: DocumentProfile) -> _Naming | None:
    """The first line on this page that sets words over the amounts below it.

    A table names its columns by printing their names above them, so the line
    that names them is the one whose words sit over the amounts. Which words
    those are is read off the page: a group of the line is a column name when
    an amount on the page sits closer to it than to any other group, and within
    the tolerance every other column reading here uses.

    A line carrying an amount itself is never a naming line: it is a row of some
    table rather than a heading over one. The first such line wins, because a
    table's own header is the nearest thing above its rows that sits over its
    columns, and a page that sets two of them names its columns twice and is
    left alone rather than guessed at.
    """
    amounts = [
        word for line in lines for word in line.words if read_amount(word.text, profile) is not None
    ]
    if not amounts:
        return None
    for line in lines:
        if _priced(line, profile):
            continue
        groups = columns_from(line.words)
        if len(groups) < MINIMUM_NAMED_COLUMNS:
            continue
        named = [
            group for group in groups if any(assign(word, groups) is group for word in amounts)
        ]
        if len(named) >= MINIMUM_NAMED_COLUMNS:
            return _Naming(line=line, columns=tuple(named))
    return None


def _read_wide_row(
    line: Line, profile: DocumentProfile, columns: tuple[Column, ...]
) -> _WideRow | None:
    """Read a row of ``label`` and one cell per named column, or refuse it.

    Everything this returns ``None`` for is a row that could otherwise be
    published with a price under a heading the publisher did not put it under.
    """
    words = list(line.words)
    at = len(words)
    while at > 0 and _cell_kind(words[at - 1], profile) is not None:
        at -= 1
    label_words = words[:at]
    values = [word for word in words[at:] if _cell_kind(word, profile) != "marker"]
    if not label_words or len(values) != len(columns):
        # Fewer cells than the table has columns: this row's price could be one
        # column's or the whole row's, and the page does not say which.
        return None
    cells: list[_Cell] = []
    for word, column in zip(values, columns, strict=True):
        if assign(word, columns) is not column:
            # A cell that does not sit under the column its position in the row
            # would give it. Reading it anyway is attribution by counting.
            return None
        cells.append(_Cell(column=column, amount=read_amount(word.text, profile), word=word))
    if not any(cell.amount is not None for cell in cells):
        # Every column marked as carrying no price. There is nothing to emit,
        # and the line is left for the unparsed report.
        return None
    boundary = min(cell.word.x0 for cell in cells) - LABEL_MARGIN
    if any(word.x1 > boundary for word in label_words):
        return None
    label = normalize(" ".join(word.text for word in label_words))
    if not label or DATED_ROW_RE.match(label):
        return None
    return _WideRow(
        line=line,
        label=label,
        cells=tuple(cells),
        label_words=tuple(label_words),
    )


def _outdented(row: _WideRow, first: _WideRow) -> bool:
    """True when ``row`` starts left of the first row of its run."""
    if not row.label_words or not first.label_words:
        return False
    return row.label_words[0].x0 < first.label_words[0].x0


def _wide_blocks(
    lines: list[Line], profile: DocumentProfile, naming: _Naming
) -> list[tuple[_Heading, list[_WideRow]]]:
    """Cut a page of one section into heading-and-rows blocks, read across columns.

    The same cut as :func:`_blocks`, over rows that carry one cell per named
    column instead of one amount.
    """
    columns = naming.columns
    found: list[tuple[_Heading, list[_WideRow]]] = []
    position = 0
    while position < len(lines):
        row = _read_wide_row(lines[position], profile, columns)
        if row is None:
            position += 1
            continue
        start = position
        rows = [row]
        position += 1
        while position < len(lines):
            following = _read_wide_row(lines[position], profile, columns)
            if following is None or _outdented(following, row):
                # A row set further left than the rows above it is not one of
                # them. On a table naming its components, that outdent is how
                # the page leaves one component's rows and starts something
                # else, and reading them as one block would file every row
                # under the first component's name.
                break
            rows.append(following)
            position += 1
        heading = _read_heading(lines, start, profile, naming) or _reaching_heading(
            lines,
            start,
            profile,
            min(row.label_words[0].x0 for row in rows if row.label_words),
            lambda line: _read_wide_row(line, profile, columns) is not None,
            naming,
        )
        if heading is not None and len(rows) >= MINIMUM_ROWS:
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


def _wide_candidates(
    section: Section, profile: DocumentProfile
) -> list[tuple[_Naming, _Heading, list[_WideRow]]]:
    """The blocks on pages that set amounts in more than one column and name them.

    A page setting them in one column is left to :func:`_candidates`, whose
    reading of it does not change: there is nothing there for a column name to
    settle. A page setting them in several and naming none is read by neither.
    """
    found: list[tuple[_Naming, _Heading, list[_WideRow]]] = []
    for lines in _by_page(section):
        if _page_has_one_amount_column(lines, profile):
            continue
        naming = _naming_line(lines, profile)
        if naming is None:
            continue
        for heading, rows in _wide_blocks(lines, profile, naming):
            found.append((naming, heading, rows))
    return found


def _cited_unit(heading: _Heading, citer: Citer, section_id: str) -> Cited[str]:
    """The unit, cited to what the publisher printed it on.

    One line, ordinarily. A span of two where the publisher broke the bracket
    across a line ending, because half the unit appears on each line and the
    whole of it on neither, and a citation whose snippet does not contain what
    it cites cannot be checked.
    """
    if heading.unit_lines is not None:
        return Cited(
            value=heading.unit,
            provenance=citer.cite_span(heading.unit_lines, section_id),
        )
    return citer.text(heading.unit_source, section_id, heading.unit)


def claims(section: Section, profile: DocumentProfile) -> bool:
    return bool(_candidates(section, profile)) or bool(_wide_candidates(section, profile))


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
        unit = _cited_unit(heading, citer, section.section_id)
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

    for naming, heading, wide_rows in _wide_candidates(section, profile):
        effective = effective_by_page.get(wide_rows[0].line.page)
        if effective is None:
            continue
        label = citer.text(heading.label, section.section_id, heading.label_text)
        unit = _cited_unit(heading, citer, section.section_id)
        kind = "energy_usage" if squash(heading.unit) in ENERGY_UNITS else "fixed_charge"
        for wide_row in wide_rows:
            for cell in wide_row.cells:
                if cell.amount is None:
                    # The publisher marked this column as carrying no price for
                    # this row, which is a fact about the row rather than a
                    # price to publish.
                    continue
                emission.charges.append(
                    Charge(
                        label=citer.text(wide_row.line, section.section_id, wide_row.label),
                        kind=kind,
                        price=Money(
                            amount=Cited(
                                value=cell.amount,
                                provenance=citer.cite(wide_row.line, section.section_id),
                            ),
                            currency="USD",
                            unit=unit,
                        ),
                        effective_from=effective,
                        applies_to=citer.text(naming.line, section.section_id, cell.column.label),
                        group=label,
                    )
                )
            emission.take(wide_row.line)
        emission.take(naming.line, *heading.lines)
    return emission
