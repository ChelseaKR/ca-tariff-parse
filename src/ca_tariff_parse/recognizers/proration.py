"""Read the billing-proration table from its own ruled cells.

Every schedule with a proration table prices the same idea: a circumstance
("Bill period is shorter than 27 days") paired with the basis the publisher
uses to prorate a charge under it. Reading it line by line does not work,
because the "Basis for Proration" column is sometimes one cell tall and
sometimes drawn to span two or three circumstances at once, and which is
which is not visible from word order or spacing: it is visible only in the
ruled lines the publisher drew. See
:class:`~ca_tariff_parse.extract.ExtractedTable`, which reads exactly those
lines and nothing else.

This recognizer looks for a table whose own header cells read "Billing
Circumstance" and "Basis for Proration", wherever it sits. It does not key
off the surrounding section's heading, because the same table sits under a
subsection literally called "Proration of Charges" on one schedule and under
a section called "Billing" on another: the table names itself, and the
heading around it does not have to.
"""

from __future__ import annotations

from ..extract import ExtractedTable, LayoutDoc, TableCell, squash
from ..model import Cited, ProrationRule
from ..segment import Section
from .base import Citer, Emission

#: The table's own header, squashed. Matching this instead of a section
#: heading is what lets the same table be found regardless of which part of
#: the document it is filed under.
HEADER = ("billingcircumstance", "basisforproration")


def _is_proration_table(table: ExtractedTable) -> bool:
    if len(table.header) < 2 or len(table.columns) < 2:
        return False
    return tuple(squash(cell.text) for cell in table.header[:2]) == HEADER


def _tables_in_section(doc: LayoutDoc, section: Section) -> list[tuple[int, ExtractedTable]]:
    """Every proration table whose cells fall inside ``section``."""
    section_lines = {(line.page, line.index) for line in section.content_lines}
    if not section_lines:
        return []
    pages = {page for page, _ in section_lines}
    found: list[tuple[int, ExtractedTable]] = []
    for page in doc.pages:
        if page.number not in pages:
            continue
        for table in page.tables:
            if not _is_proration_table(table):
                continue
            cells = [*table.header, *(cell for column in table.columns for cell in column)]
            table_lines = {
                (page.number, index)
                for cell in cells
                for index in range(cell.first_line, cell.last_line + 1)
            }
            if table_lines & section_lines:
                found.append((page.number, table))
    return found


def claims(section: Section, doc: LayoutDoc) -> bool:
    return bool(_tables_in_section(doc, section))


def _overlaps(a: TableCell, b: TableCell) -> bool:
    return a.top < b.bottom and b.top < a.bottom


def _parse_table(page: int, table: ExtractedTable, section: Section, citer: Citer) -> Emission:
    emission = Emission()
    circumstances, bases = table.columns[0], table.columns[1]

    def cite(cell: TableCell) -> Cited[str]:
        provenance = citer.cite_cell(
            page, section.section_id, cell.first_line, cell.last_line, cell.text
        )
        return Cited(value=cell.text, provenance=provenance)

    for circumstance in circumstances:
        matches = [basis for basis in bases if _overlaps(circumstance, basis)]
        if len(matches) != 1:
            # No basis cell overlaps this circumstance's rows, or more than
            # one does. Either way this row is not published with certainty:
            # attaching the wrong basis to a circumstance is worse than
            # leaving it unparsed, so it is left for the fallback accounting
            # to report rather than guessed at here.
            continue
        emission.proration.append(
            ProrationRule(circumstance=cite(circumstance), basis=cite(matches[0]))
        )
        emission.take_span(page, circumstance.first_line, circumstance.last_line)
        emission.take_span(page, matches[0].first_line, matches[0].last_line)

    if emission.proration:
        # The header row is only credited once the table actually produced a
        # rule: a table this recognizer found but could not pair a single row
        # from is not "understood", and its header should not look otherwise.
        for cell in table.header:
            emission.take_span(page, cell.first_line, cell.last_line)
    return emission


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    for page, table in _tables_in_section(citer.doc, section):
        emission.extend(_parse_table(page, table, section, citer))
    return emission
