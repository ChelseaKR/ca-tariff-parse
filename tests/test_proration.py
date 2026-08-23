"""The billing-proration table: read from ruled cells, not from line order.

The parser cannot tell a merged basis cell from an unrelated blank one by
word order or spacing; the two look identical as text. What distinguishes
them is the ruled border the publisher drew, so these tests build that
border by hand: a fake ``pdfplumber`` page for the extraction layer, and a
hand built :class:`ExtractedTable` for the recognizer above it.
"""

from __future__ import annotations

from ca_tariff_parse.extract import (
    ExtractedTable,
    LayoutDoc,
    Line,
    Page,
    TableCell,
    Word,
    _extract_tables,
)
from ca_tariff_parse.recognizers import proration
from ca_tariff_parse.recognizers.base import Citer
from ca_tariff_parse.segment import Section


class _FakeRow:
    def __init__(self, cells: list[tuple[float, float, float, float] | None]) -> None:
        self.cells = cells


class _FakeTable:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self.rows = rows


class _FakePdfPage:
    def __init__(self, tables: list[_FakeTable]) -> None:
        self._tables = tables

    def find_tables(self) -> list[_FakeTable]:
        return self._tables


def _line(index: int, top: float, *words: tuple[str, float, float]) -> Line:
    return Line(
        page=1,
        index=index,
        top=top,
        words=tuple(Word(text=t, x0=x0, x1=x1) for t, x0, x1 in words),
        furniture=False,
    )


# A table shaped like the real one: two circumstances share one merged basis
# cell (rows 1-2), a third circumstance has its own (row 3). Row bands are
# generously spaced (30pt) so the fixture cannot pass by accident of
# CELL_TOLERANCE reaching into a neighbouring band.
LINES = (
    _line(1, 5.0, ("Billing", 100.0, 140.0), ("Circumstance", 145.0, 200.0)),
    _line(1, 5.5, ("Basis", 260.0, 290.0), ("for", 295.0, 310.0), ("Proration", 315.0, 370.0)),
    _line(2, 35.0, ("Bill", 100.0, 120.0), ("period", 125.0, 160.0), ("A", 165.0, 175.0)),
    _line(3, 40.0, ("Relationship", 260.0, 330.0), ("to", 335.0, 350.0), ("30", 355.0, 370.0)),
    _line(4, 65.0, ("Bill", 100.0, 120.0), ("period", 125.0, 160.0), ("B", 165.0, 175.0)),
    _line(5, 95.0, ("Price", 100.0, 130.0), ("changes", 135.0, 175.0)),
    _line(6, 100.0, ("number", 260.0, 300.0), ("of", 305.0, 315.0), ("days", 320.0, 350.0)),
)


def _table() -> _FakeTable:
    return _FakeTable(
        rows=[
            _FakeRow([(90.0, 0.0, 250.0, 20.0), (250.0, 0.0, 400.0, 20.0)]),  # header
            _FakeRow(
                [(90.0, 20.0, 250.0, 50.0), (250.0, 20.0, 400.0, 80.0)]
            ),  # A | basis1 (spans A+B)
            _FakeRow([(90.0, 50.0, 250.0, 80.0), None]),  # B | (covered by basis1)
            _FakeRow([(90.0, 80.0, 250.0, 110.0), (250.0, 80.0, 400.0, 110.0)]),  # C | basis2
        ]
    )


def _extracted_table() -> ExtractedTable:
    tables = _extract_tables(_FakePdfPage([_table()]), LINES)
    assert len(tables) == 1
    return tables[0]


def test_extract_tables_reads_a_merged_cell_from_its_own_border() -> None:
    table = _extracted_table()
    assert tuple(c.text for c in table.header) == ("Billing Circumstance", "Basis for Proration")
    circumstances, bases = table.columns
    assert [c.text for c in circumstances] == ["Bill period A", "Bill period B", "Price changes"]
    # Exactly one basis cell: the row that would sit "under" B produced no
    # cell of its own, because the border drew none there.
    assert [b.text for b in bases] == ["Relationship to 30", "number of days"]
    assert bases[0].first_line == 3 and bases[0].last_line == 3


def test_extract_tables_ignores_a_table_with_no_text_in_a_cell() -> None:
    """A cell whose bbox exists but matches no word is not fabricated as ''."""
    empty_row = _FakeRow([(90.0, 200.0, 250.0, 210.0), (250.0, 200.0, 400.0, 210.0)])
    table = _extract_tables(_FakePdfPage([_FakeTable(rows=[_table().rows[0], empty_row])]), LINES)[
        0
    ]
    assert table.columns == ((), ())


def _doc_with_table(table: ExtractedTable) -> LayoutDoc:
    page = Page(number=1, height=800.0, lines=LINES, sheet="SYN-1", tables=(table,))
    return LayoutDoc(
        document_id="syn-proration",
        sha256="a" * 64,
        filename="<inline>",
        byte_size=0,
        pages=(page,),
        synthetic=True,
    )


def _section() -> Section:
    return Section(section_id="VI.A", level=2, heading="Proration of Charges", lines=list(LINES))


def test_a_basis_cell_spanning_two_rows_is_shared_by_both() -> None:
    doc = _doc_with_table(_extracted_table())
    section = _section()
    citer = Citer(doc)

    assert proration.claims(section, doc)
    emission = proration.parse(section, citer)

    rules = {rule.circumstance.value: rule.basis.value for rule in emission.proration}
    assert rules == {
        "Bill period A": "Relationship to 30",
        "Bill period B": "Relationship to 30",
        "Price changes": "number of days",
    }
    # Every cell that contributed to a rule is accounted for, header included.
    assert (1, 1) in emission.consumed and (1, 2) in emission.consumed
    for index in (2, 3, 4, 5, 6):
        assert (1, index) in emission.consumed


def test_a_table_with_the_wrong_header_is_not_claimed() -> None:
    header_only = _extracted_table()
    other = ExtractedTable(
        header=(
            TableCell(text="Rate Category", first_line=1, last_line=1, top=0.0, bottom=1.0),
            TableCell(text="Amount", first_line=1, last_line=1, top=0.0, bottom=1.0),
        ),
        columns=header_only.columns,
    )
    doc = _doc_with_table(other)
    section = _section()
    assert not proration.claims(section, doc)
    assert proration.parse(section, Citer(doc)).proration == []


def test_a_circumstance_with_no_overlapping_basis_is_refused_not_guessed() -> None:
    """An orphan circumstance is left unparsed rather than paired at random."""
    circumstances = (
        TableCell(text="Bill period A", first_line=2, last_line=2, top=20.0, bottom=50.0),
        TableCell(text="Bill period B", first_line=4, last_line=4, top=65.0, bottom=95.0),
    )
    bases = (
        TableCell(text="Relationship to 30", first_line=3, last_line=3, top=20.0, bottom=50.0),
    )
    table = ExtractedTable(
        header=(
            TableCell(text="Billing Circumstance", first_line=1, last_line=1, top=0.0, bottom=1.0),
            TableCell(text="Basis for Proration", first_line=1, last_line=1, top=0.0, bottom=1.0),
        ),
        columns=(circumstances, bases),
    )
    doc = _doc_with_table(table)
    section = _section()
    emission = proration.parse(section, Citer(doc))

    assert len(emission.proration) == 1
    assert emission.proration[0].circumstance.value == "Bill period A"
    # "Bill period B" (line 4) found no basis at all and was not consumed.
    assert (1, 4) not in emission.consumed
