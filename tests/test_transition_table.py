"""A table with no ruled border that states its unit in a column of its own.

Built from hand positioned words, the same way ``test_proration.py`` and
``test_condition_list.py`` are: what this recognizer reads is column
geometry, and a monospace fixture's fixed character grid cannot place a
right-aligned label column the way a real sheet does.
"""

from __future__ import annotations

from ca_tariff_parse.extract import LayoutDoc, Line, Page, Word
from ca_tariff_parse.profiles import DEFAULT
from ca_tariff_parse.recognizers import transition_table
from ca_tariff_parse.recognizers.base import Citer
from ca_tariff_parse.segment import Section

#: x0/x1 for each of the three columns this fixture uses throughout: a label
#: column ending well clear of "Unit", "Unit" itself, and a single year.
LABEL_X1 = 175.0
UNIT_X0, UNIT_X1 = 200.0, 225.0
YEAR_X0, YEAR_X1 = 280.0, 310.0


def _line(index: int, *words: tuple[str, float, float]) -> Line:
    return Line(
        page=1,
        index=index,
        top=float(index) * 14.0,
        words=tuple(Word(text=t, x0=x0, x1=x1) for t, x0, x1 in words),
        furniture=False,
    )


HEADER = _line(
    1,
    ("Season", 100.0, 130.0),
    ("Component", 133.0, LABEL_X1),
    ("Unit", UNIT_X0, UNIT_X1),
    ("2028*", YEAR_X0, YEAR_X1),
)
CATEGORY = _line(2, ("CAT-0:", 50.0, 80.0), ("Category", 83.0, 120.0), ("Name", 123.0, 160.0))
FIXED_ROW = _line(
    3,
    ("System", 100.0, 140.0),
    ("Charge", 143.0, LABEL_X1),
    ("per", UNIT_X0, 215.0),
    ("month", 218.0, UNIT_X1),
    ("$44.45", YEAR_X0, YEAR_X1),
)
ENERGY_ROW = _line(
    4,
    ("Peak", 100.0, 130.0),
    ("per", UNIT_X0, 215.0),
    ("kWh", 218.0, UNIT_X1),
    ("$0.1506", YEAR_X0, YEAR_X1),
)


def _doc(lines: tuple[Line, ...]) -> LayoutDoc:
    page = Page(number=1, height=792.0, lines=lines, sheet="SYN-1")
    return LayoutDoc(
        document_id="syn-transition",
        sha256="a" * 64,
        filename="<inline>",
        byte_size=0,
        pages=(page,),
        synthetic=True,
    )


def _section(lines: tuple[Line, ...]) -> Section:
    return Section(section_id="VIII", level=1, heading="Transition Schedule", lines=list(lines))


def test_a_row_is_dated_from_the_year_header_and_grouped_by_category() -> None:
    lines = (HEADER, CATEGORY, FIXED_ROW, ENERGY_ROW)
    section = _section(lines)
    citer = Citer(_doc(lines))

    assert transition_table.claims(section)
    emission = transition_table.parse(section, citer, DEFAULT)

    assert len(emission.charges) == 2
    fixed, energy = emission.charges
    assert fixed.label.value == "System Charge"
    assert fixed.kind == "fixed_charge"
    assert fixed.price.amount.value == "44.45"
    assert fixed.price.unit.value == "per month"
    assert fixed.effective_from.value == "2028*"
    assert fixed.effective_from.provenance.line == 1  # dated from the header, not the row
    assert fixed.rate_category is not None
    assert fixed.rate_category.value == "CAT-0"

    assert energy.label.value == "Peak"
    assert energy.kind == "energy_usage"
    assert energy.price.amount.value == "0.1506"
    assert energy.price.unit.value == "per kWh"

    for index in (1, 2, 3, 4):
        assert (1, index) in emission.consumed


def test_a_header_with_no_unit_column_is_not_claimed() -> None:
    header = _line(1, ("Season", 100.0, 130.0), ("2028*", YEAR_X0, YEAR_X1))
    section = _section((header, FIXED_ROW))
    assert not transition_table.claims(section)


def test_a_header_whose_last_column_is_not_a_year_is_not_claimed() -> None:
    header = _line(
        1,
        ("Season", 100.0, 130.0),
        ("Unit", UNIT_X0, UNIT_X1),
        ("TBD", YEAR_X0, YEAR_X1),
    )
    section = _section((header, FIXED_ROW))
    assert not transition_table.claims(section)


def test_a_word_that_fits_no_column_refuses_the_whole_row() -> None:
    """An amount cannot be attributed to a column it does not sit near."""
    stray_row = _line(
        3,
        ("System", 100.0, 140.0),
        ("Charge", 143.0, LABEL_X1),
        ("per", UNIT_X0, 215.0),
        ("month", 218.0, UNIT_X1),
        ("$44.45", 700.0, 730.0),  # nowhere near the year column
    )
    lines = (HEADER, stray_row)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed
    # The header itself is not credited either: nothing was read from this
    # table at all.
    assert (1, 1) not in emission.consumed


def test_a_footnote_line_with_nothing_past_the_label_is_left_alone() -> None:
    """A footnote sits entirely left of the boundary and states no unit."""
    footnote = _line(
        3, ("*Subject", 100.0, 140.0), ("to", 143.0, 155.0), ("increases.", 158.0, 174.0)
    )
    lines = (HEADER, footnote)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed


def test_a_row_with_nothing_left_of_the_boundary_has_no_label() -> None:
    """A price with no label naming it is not a row this recognizer reads."""
    labelless_row = _line(
        3, ("per", UNIT_X0, 215.0), ("month", 218.0, UNIT_X1), ("$44.45", YEAR_X0, YEAR_X1)
    )
    lines = (HEADER, labelless_row)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed


def test_a_row_with_no_unit_words_at_all_is_left_alone() -> None:
    """An amount with nothing in the unit column names no price for anything."""
    unitless_row = _line(
        3, ("System", 100.0, 140.0), ("Charge", 143.0, LABEL_X1), ("$44.45", YEAR_X0, YEAR_X1)
    )
    lines = (HEADER, unitless_row)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed


def test_two_amounts_under_one_year_refuse_the_row() -> None:
    """Two tokens under one year column cannot both be that year's price."""
    two_amounts = _line(
        3,
        ("System", 100.0, 140.0),
        ("Charge", 143.0, LABEL_X1),
        ("per", UNIT_X0, 215.0),
        ("month", 218.0, UNIT_X1),
        ("$44.45", YEAR_X0, 295.0),
        ("$45.00", 296.0, YEAR_X1),
    )
    lines = (HEADER, two_amounts)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed


def test_a_token_that_is_neither_an_amount_nor_na_refuses_the_row() -> None:
    garbled = _line(
        3,
        ("System", 100.0, 140.0),
        ("Charge", 143.0, LABEL_X1),
        ("per", UNIT_X0, 215.0),
        ("month", 218.0, UNIT_X1),
        ("TBD", YEAR_X0, YEAR_X1),
    )
    lines = (HEADER, garbled)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    assert (1, 3) not in emission.consumed


def test_parse_without_a_header_emits_nothing() -> None:
    lines = (FIXED_ROW,)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)
    assert emission.charges == []
    assert emission.consumed == set()


def test_a_row_marked_not_applicable_is_understood_but_prices_nothing() -> None:
    na_row = _line(
        3,
        ("System", 100.0, 140.0),
        ("Charge", 143.0, LABEL_X1),
        ("per", UNIT_X0, 215.0),
        ("month", 218.0, UNIT_X1),
        ("n/a", YEAR_X0, YEAR_X1),
    )
    lines = (HEADER, na_row)
    section = _section(lines)
    emission = transition_table.parse(section, Citer(_doc(lines)), DEFAULT)

    assert emission.charges == []
    # Understood -- explicitly marked n/a -- so the row is still accounted
    # for, unlike the unreadable row above.
    assert (1, 3) in emission.consumed
