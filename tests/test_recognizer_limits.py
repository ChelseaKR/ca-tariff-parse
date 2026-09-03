"""When a recognizer cannot read something with certainty, it emits nothing.

Each case here is a shape the parser deliberately refuses. Refusing is the
correct outcome: a guessed unit or an amount attributed to the wrong effective
date would be a fabricated tariff value, which is worse than a gap.

All fixtures in this module are synthetic and built inline.
"""

from __future__ import annotations

from ca_tariff_parse.extract import layout_from_monospace
from ca_tariff_parse.parser import parse_document

PAGE_ROWS = 54


def build(cells: dict[int, list[tuple[int, str]]], *, footer: bool = True) -> str:
    """Render one synthetic page from row and column positions."""
    grid = [[] for _ in range(PAGE_ROWS)]  # type: ignore[var-annotated]
    grid[1].append((60, "Example Service (SYNTHETIC)"))
    grid[2].append((60, "Rate Schedule SYN-X"))
    if footer:
        grid[50].append((9, "EXAMPLE MUNICIPAL UTILITY (SYNTHETIC)"))
        grid[50].append((70, "Sheet No. SYN-X-1"))
        grid[51].append(
            (9, "Resolution No. SYN-00-00 adopted January 1, 2026 Effective: February 1, 2026")
        )
    for row, entries in cells.items():
        grid[row].extend(entries)

    lines = []
    for entries in grid:
        line = ""
        for col, text in sorted(entries):
            line = line + " " * (col - len(line)) + text
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def parse(text: str):
    return parse_document(layout_from_monospace(text, "syn-limits"))


def test_a_priced_row_with_an_unreadable_unit_is_not_emitted() -> None:
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(58, "Effective as of")],
                9: [(58, "May 1, 2026")],
                10: [(20, "Mystery Charge per furlong"), (60, "$9.99")],
            }
        )
    )
    assert parsed.charges == ()
    assert any(item.section == "II.A" for item in parsed.unparsed)
    assert any("furlong" in note.value for note in parsed.notes)


def test_a_recognisable_unit_on_the_same_shape_is_emitted() -> None:
    """Control case: the refusal above is about the unit, not the layout."""
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(58, "Effective as of")],
                9: [(58, "May 1, 2026")],
                10: [(20, "Mystery Charge per month"), (60, "$9.99")],
            }
        )
    )
    assert [c.price.amount.value for c in parsed.charges] == ["9.99"]
    assert parsed.charges[0].price.unit.value == "per month"


def test_an_amount_under_no_column_is_not_emitted() -> None:
    """An amount that sits under no effective-date column is unattributable."""
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(58, "Effective as of")],
                9: [(58, "May 1, 2026")],
                10: [(20, "Fixed Charge per month"), (110, "$9.99")],
            }
        )
    )
    assert parsed.charges == ()
    assert parsed.unparsed


def test_a_dated_block_without_a_stated_unit_is_not_emitted() -> None:
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Standby Option")],
                8: [(26, "Effective May 1, 2026"), (58, "$1.234")],
                9: [(26, "Effective January 1, 2027"), (58, "$2.345")],
            }
        )
    )
    assert parsed.charges == ()
    assert parsed.unparsed


def test_a_dated_block_with_a_stated_unit_is_emitted() -> None:
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Standby Option")],
                8: [(20, "Example Standby Charge - all year")],
                9: [(20, "($/kW of Example Capacity per month)")],
                10: [(26, "Effective May 1, 2026"), (58, "$1.234")],
                11: [(26, "Effective January 1, 2027"), (58, "$2.345")],
            }
        )
    )
    assert [c.price.amount.value for c in parsed.charges] == ["1.234", "2.345"]


def test_a_credit_with_no_document_effective_date_is_not_emitted() -> None:
    """Without a printed effective date there is nothing to date the credit from."""
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Vehicle Credit")],
                8: [(26, "Example Vehicle Credit"), (60, "-$0.0100/kWh")],
            },
            footer=False,
        )
    )
    assert parsed.identity.effective is None
    assert parsed.charges == ()


def test_a_holiday_row_missing_a_cell_is_not_completed_by_guessing() -> None:
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Billing Periods")],
                6: [(15, "A. Example Time-of-Day Billing Periods")],
                8: [(36, "Peak"), (54, "Weekdays between 5:00 p.m. and 8:00 p.m.")],
                9: [(8, "Example Season")],
                10: [(15, "Off-Peak pricing shall apply during the following holidays:")],
                12: [(20, "Holiday"), (52, "Month"), (70, "Date")],
                13: [(20, "Example Complete Day"), (52, "January"), (70, "1")],
                14: [(20, "Example Incomplete Day"), (52, "March")],
            }
        )
    )
    assert [h.name.value for h in parsed.holidays] == ["Example Complete Day"]
    assert parsed.unparsed


def test_a_dated_row_of_several_amounts_needs_a_heading_for_each() -> None:
    """Two amounts under one heading cannot be told apart, so neither is emitted.

    Before this, everything after the first amount was swallowed into the
    effective date and the last amount was emitted as though it were the whole
    charge.
    """
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Standby Option")],
                8: [(20, "Example Standby Charge by Level"), (52, "Alpha")],
                9: [(20, "($/kW of Example Capacity per month)")],
                10: [(26, "Effective May 1, 2026"), (53, "$1.234"), (67, "$2.345")],
                11: [(26, "Effective January 1, 2027"), (53, "$3.456"), (67, "$4.567")],
            }
        )
    )
    assert parsed.charges == ()
    assert parsed.unparsed


def test_a_dated_row_of_several_amounts_is_split_by_its_headings() -> None:
    """Control case: with one heading per amount, each price keeps its category."""
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Standby Option")],
                8: [(20, "Example Standby Charge by Level"), (52, "Alpha"), (66, "Beta")],
                9: [(20, "($/kW of Example Capacity per month)")],
                10: [(26, "Effective May 1, 2026"), (53, "$1.234"), (67, "$2.345")],
                11: [(26, "Effective January 1, 2027"), (53, "$3.456"), (67, "$4.567")],
            }
        )
    )
    assert [
        (c.price.amount.value, c.applies_to.value if c.applies_to else None, c.effective_from.value)
        for c in parsed.charges
    ] == [
        ("1.234", "Alpha", "May 1, 2026"),
        ("2.345", "Beta", "May 1, 2026"),
        ("3.456", "Alpha", "January 1, 2027"),
        ("4.567", "Beta", "January 1, 2027"),
    ]
    assert all(c.label.value == "Example Standby Charge by Level" for c in parsed.charges)


def test_two_dated_blocks_in_one_section_keep_their_own_labels() -> None:
    """A section can price two things, and the second is not filed under the first."""
    parsed = parse(
        build(
            {
                5: [(9, "III. Example Options")],
                6: [(15, "A. Example Rates")],
                8: [(20, "Example First Rate per excess KVAR")],
                9: [(26, "Effective May 1, 2026"), (58, "$1.234")],
                10: [(26, "Effective January 1, 2027"), (58, "$2.345")],
                12: [(20, "Example Second Rate per excess KVAR")],
                13: [(26, "Effective May 1, 2026"), (58, "$3.456")],
                14: [(26, "Effective January 1, 2027"), (58, "$4.567")],
            }
        )
    )
    assert [(c.label.value, c.price.amount.value) for c in parsed.charges] == [
        ("Example First Rate", "1.234"),
        ("Example First Rate", "2.345"),
        ("Example Second Rate", "3.456"),
        ("Example Second Rate", "4.567"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"per excess KVAR"}


def test_a_unit_is_read_to_the_end_of_its_label() -> None:
    """ "per month" is a substring of "per monthly max kW" and must not win.

    Quoting a demand charge as a flat monthly amount would understate it by
    the whole demand, and nothing in the output would show that had happened.
    """
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(70, "Effective as of")],
                9: [(70, "May 1, 2026")],
                10: [(20, "Example Demand Charge $ per monthly max kW"), (72, "$9.99")],
            }
        )
    )
    assert [c.price.unit.value for c in parsed.charges] == ["$ per monthly max kW"]
    assert parsed.charges[0].kind == "fixed_charge"


def test_a_longer_period_name_is_not_truncated_to_a_shorter_one() -> None:
    """Off-Peak Saver is its own period with its own price, not an Off-Peak."""
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(58, "Effective as of")],
                9: [(58, "May 1, 2026")],
                10: [(20, "Off-Peak Saver $/kWh"), (60, "$9.99")],
            }
        )
    )
    assert [c.tou_period.value for c in parsed.charges if c.tou_period] == ["Off-Peak Saver"]


def test_a_priced_row_is_not_read_as_a_time_of_use_window() -> None:
    """A future price table lines up in the same columns as a window table.

    Its right hand cell holds a price, not a definition of when a period runs,
    and emitting it as a window would state a rule the document never wrote.
    """
    parsed = parse(
        build(
            {
                5: [(9, "VIII. Example Transition Schedule")],
                7: [(30, "Non-Summer"), (42, "Peak"), (56, "per kWh"), (70, "$1.5060")],
                8: [(30, "Non-Summer"), (42, "Off-Peak"), (56, "per kWh"), (70, "$1.2370")],
            }
        )
    )
    assert parsed.tou_windows == ()
    assert parsed.unparsed


def test_the_holiday_table_is_read_wherever_the_publisher_sets_it() -> None:
    """The three headings say where the cells divide, so fixed columns are wrong."""
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Billing Periods")],
                6: [(15, "A. Example Time-of-Day Billing Periods")],
                8: [(15, "Off-Peak pricing shall apply during the following holidays:")],
                10: [(20, "Holiday"), (45, "Month"), (60, "Date")],
                11: [(20, "Example New Year Day"), (45, "January"), (60, "1")],
            }
        )
    )
    assert [(h.name.value, h.month.value, h.day_rule.value) for h in parsed.holidays] == [
        ("Example New Year Day", "January", "1")
    ]


def test_a_season_date_range_without_brackets_stays_with_its_season() -> None:
    """One publisher brackets the range and another does not; both are one label."""
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Billing Periods")],
                6: [(15, "A. Example Time-of-Day Billing Periods")],
                8: [(36, "Peak"), (54, "Weekdays between 5:00 p.m. and 8:00 p.m.")],
                9: [(8, "Example Summer")],
                10: [(36, "Off-Peak"), (54, "All other hours, including holidays.")],
                11: [(8, "March 1 -April 30")],
            }
        )
    )
    assert [w.season.value for w in parsed.tou_windows] == [
        "Example Summer March 1 -April 30",
        "Example Summer March 1 -April 30",
    ]


def test_an_eligibility_section_is_read_as_applicability() -> None:
    """A schedule that files its conditions under another heading still states them."""
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Conditions of Service")],
                6: [(15, "A. Eligibility")],
                7: [(20, "1. The example facility must be on the example premises.")],
            }
        )
    )
    assert [(a.text.value, a.disposition) for a in parsed.applicability] == [
        ("The example facility must be on the example premises.", "required")
    ]


def test_a_table_caption_the_parser_cannot_read_is_reported() -> None:
    """A caption that is not a rate category must not be silently swallowed."""
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(58, "Effective as of")],
                9: [(58, "May 1, 2026")],
                10: [(15, "Example Metered Billing (Closed)")],
                11: [(20, "Fixed Charge per month"), (60, "$9.99")],
            }
        )
    )
    assert [c.price.amount.value for c in parsed.charges] == ["9.99"]
    assert parsed.charges[0].rate_category is None
    assert any("(Closed)" in note.value for note in parsed.notes)


def test_a_window_whose_season_is_not_a_season_is_not_emitted() -> None:
    """A column heading left of the period column is not the season.

    A second publisher heads that column "TIME PERIOD" and sets its real
    seasons further right. Reading the heading as a season published two
    windows belonging to a season nobody wrote.
    """
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Billing Periods")],
                6: [(15, "A. Example Time-of-Day Billing Periods")],
                8: [(8, "PERIOD")],
                9: [(36, "Peak"), (54, "Weekdays between 5:00 p.m. and 8:00 p.m.")],
                10: [(36, "Off-Peak"), (54, "All other hours, including holidays.")],
            }
        )
    )
    assert parsed.tou_windows == ()
    assert any("PERIOD" in note.value for note in parsed.notes)


def test_the_same_table_under_a_stated_season_is_emitted() -> None:
    """Control case: the refusal above is about the label, not the layout."""
    parsed = parse(
        build(
            {
                5: [(9, "IV. Example Billing Periods")],
                6: [(15, "A. Example Time-of-Day Billing Periods")],
                8: [(8, "Example Summer (Mar - Apr)")],
                9: [(36, "Peak"), (54, "Weekdays between 5:00 p.m. and 8:00 p.m.")],
                10: [(36, "Off-Peak"), (54, "All other hours, including holidays.")],
            }
        )
    )
    assert [(w.season.value, w.period.value) for w in parsed.tou_windows] == [
        ("Example Summer (Mar - Apr)", "Peak"),
        ("Example Summer (Mar - Apr)", "Off-Peak"),
    ]


def test_a_row_with_a_cell_the_parser_cannot_read_is_refused_whole() -> None:
    """Publishing the readable half of a row would understate the row.

    A second publisher writes a negative amount in accounting brackets, as
    "($0.0500)". That is a real published price in a form this parser does not
    read, and emitting the row without it would present one price as though it
    were the whole row.
    """
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Rates")],
                6: [(15, "A. Example Rate")],
                8: [(50, "Effective as of"), (68, "Effective as of")],
                9: [(50, "May 1, 2026"), (68, "January 1, 2027")],
                10: [(20, "Fixed Charge per month"), (52, "($0.0500)"), (70, "$9.99")],
            }
        )
    )
    assert parsed.charges == ()
    assert any("($0.0500)" in note.value for note in parsed.notes)


def test_two_credits_in_one_section_keep_their_own_windows() -> None:
    """A section can state two credits, each with its own applicability window.

    The window is a verbatim quote from the document with real provenance, so
    a window borrowed from the credit below it is fully cited and still wrong:
    it says a price applies during hours the publisher gave to another credit.
    """
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Credits")],
                6: [(15, "A. Example Credit")],
                8: [(20, "Credit applies to all example usage from midnight to 6:00 a.m. daily.")],
                9: [(20, "Example Vehicle Credit"), (60, "-$0.0100/kWh")],
                10: [(20, "Credit applies to all example usage from noon to 6:00 p.m. daily.")],
                11: [(20, "Example Solar Export Credit"), (60, "-$0.0200/kWh")],
            }
        )
    )
    assert [
        (c.label.value, c.price.amount.value, c.tou_period.value if c.tou_period else None)
        for c in parsed.charges
    ] == [
        ("Example Vehicle Credit", "-0.0100", "midnight to 6:00 a.m. daily"),
        ("Example Solar Export Credit", "-0.0200", "noon to 6:00 p.m. daily"),
    ]


def test_a_credit_above_every_applicability_sentence_takes_no_window() -> None:
    """No sentence precedes it, so there is no window of its own to take.

    Reading downward for one would attach the following credit's hours; this
    is the same refusal as any other, applied to scope instead of to price.
    """
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Credits")],
                6: [(15, "A. Example Credit")],
                8: [(20, "Example Vehicle Credit"), (60, "-$0.0100/kWh")],
                9: [(20, "Credit applies to all example usage from noon to 6:00 p.m. daily.")],
                10: [(20, "Example Solar Export Credit"), (60, "-$0.0200/kWh")],
            }
        )
    )
    assert [
        (c.label.value, c.tou_period.value if c.tou_period else None) for c in parsed.charges
    ] == [
        ("Example Vehicle Credit", None),
        ("Example Solar Export Credit", "noon to 6:00 p.m. daily"),
    ]


def test_one_credit_under_one_sentence_still_takes_its_window() -> None:
    """Control case: the two above are about which sentence, not about reading one."""
    parsed = parse(
        build(
            {
                5: [(9, "II. Example Credits")],
                6: [(15, "A. Example Credit")],
                8: [(20, "Credit applies to all example usage from midnight to 6:00 a.m. daily.")],
                9: [(20, "Example Vehicle Credit"), (60, "-$0.0100/kWh")],
            }
        )
    )
    assert [
        (c.label.value, c.tou_period.value if c.tou_period else None) for c in parsed.charges
    ] == [("Example Vehicle Credit", "midnight to 6:00 a.m. daily")]


#: A page that names two columns over its amounts, in the shape a regulated
#: publisher sets a rate sheet: the names on a line of their own over the
#: table, the unit on the block's own heading, the labels in a column clear of
#: the values. Every number here is synthetic.
NAMED_COLUMNS = {
    5: [(9, "II. Example Rates")],
    6: [(15, "A. Example Table")],
    8: [(9, "Example Table Rates"), (45, "Alpha Rates"), (62, "Beta Rates")],
    9: [(12, "Example Energy Rates ($ per kWh)")],
    10: [(15, "Example Peak Summer"), (47, "$0.1000"), (64, "$0.2000")],
    11: [(15, "Example Off-Peak Summer"), (47, "$0.3000"), (64, "$0.4000")],
}


def _named(**changes: list[tuple[int, str]] | None) -> dict[int, list[tuple[int, str]]]:
    """The named-column page with rows replaced or removed by row number."""
    page = {row: list(cells) for row, cells in NAMED_COLUMNS.items()}
    for key, value in changes.items():
        row = int(key.removeprefix("row"))
        if value is None:
            page.pop(row, None)
        else:
            page[row] = value
    return page


def test_a_page_that_names_its_columns_is_read_across_them() -> None:
    parsed = parse(build(_named()))
    assert [
        (c.label.value, c.price.amount.value, c.applies_to.value if c.applies_to else None)
        for c in parsed.charges
    ] == [
        ("Example Peak Summer", "0.1000", "Alpha Rates"),
        ("Example Peak Summer", "0.2000", "Beta Rates"),
        ("Example Off-Peak Summer", "0.3000", "Alpha Rates"),
        ("Example Off-Peak Summer", "0.4000", "Beta Rates"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"$ per kWh"}
    assert {c.group.value for c in parsed.charges if c.group} == {"Example Energy Rates"}


def test_the_same_page_naming_nothing_is_refused_whole() -> None:
    """Control case: what makes the table readable is the line that names it."""
    parsed = parse(build(_named(row8=None)))
    assert parsed.charges == ()
    assert any(item.section == "II.A" for item in parsed.unparsed)


def test_a_row_holding_fewer_cells_than_the_table_has_columns_is_refused() -> None:
    """Its one price may be a column's or the whole row's; the page does not say."""
    page = _named(row12=[(15, "Example Single Amount Row"), (47, "$0.9000")])
    parsed = parse(build(page))
    assert "Example Single Amount Row" not in {c.label.value for c in parsed.charges}
    assert len(parsed.charges) == 4


def test_an_unpriced_cell_prices_the_column_beside_it_and_not_itself() -> None:
    """A dash under a named column says that column has no price for this row."""
    page = _named(row11=[(15, "Example Beta Only Row"), (47, "---"), (64, "$0.4000")])
    parsed = parse(build(page))
    beta = [c for c in parsed.charges if c.label.value == "Example Beta Only Row"]
    assert [(c.price.amount.value, c.applies_to.value if c.applies_to else None) for c in beta] == [
        ("0.4000", "Beta Rates")
    ]


def test_a_row_of_nothing_but_unpriced_cells_prices_nothing() -> None:
    """And is reported, rather than counted as a line this parser understood."""
    page = _named(row11=[(15, "Example Empty Row"), (47, "---"), (64, "---")])
    parsed = parse(build(page))
    assert "Example Empty Row" not in {c.label.value for c in parsed.charges}
    assert any("Example Empty Row" in sample for item in parsed.unparsed for sample in item.sample)


def test_a_sentence_ending_in_two_amounts_is_not_a_row_of_the_table() -> None:
    """A table sets its label and its prices in separate columns; prose does not."""
    page = _named(row11=[(15, "Example label just past values"), (47, "$0.3000"), (64, "$0.4000")])
    parsed = parse(build(page))
    assert not [c for c in parsed.charges if c.label.value.startswith("Example label")]


def test_a_cell_under_no_named_column_refuses_its_whole_row() -> None:
    """An amount set between two columns belongs to neither by position."""
    page = _named(row11=[(15, "Example Adrift Row"), (47, "$0.3000"), (55, "$0.4000")])
    parsed = parse(build(page))
    assert "Example Adrift Row" not in {c.label.value for c in parsed.charges}


def test_a_filing_marker_between_two_cells_is_not_read_as_one() -> None:
    """The letters a regulated publisher sets beside a changed cell (ADR 0010)."""
    page = _named(row11=[(15, "Example Marked Row"), (47, "$0.3000"), (56, "(R)"), (64, "$0.4000")])
    parsed = parse(build(page))
    marked = [c for c in parsed.charges if c.label.value == "Example Marked Row"]
    assert [
        (c.price.amount.value, c.applies_to.value if c.applies_to else None) for c in marked
    ] == [
        ("0.3000", "Alpha Rates"),
        ("0.4000", "Beta Rates"),
    ]


def test_a_named_column_price_cites_the_line_that_named_it() -> None:
    """The column name is a quote from the page, not a label this parser wrote."""
    parsed = parse(build(_named()))
    charge = parsed.charges[0]
    assert charge.applies_to is not None
    assert charge.applies_to.value == "Alpha Rates"
    assert "Alpha Rates" in charge.applies_to.provenance.snippet
    # Cited to the line that names the columns, not to the row it prices.
    assert charge.applies_to.provenance.line != charge.price.amount.provenance.line


#: A table that states its unit once and then names each component of it on a
#: line of its own, the way both publishers set an unbundling sheet. The unit
#: heading is set left of the component names, and they are set left of the
#: rows they group; that nesting is the whole of what says which rows a unit
#: reaches. Synthetic throughout.
COMPONENT_TABLE = {
    5: [(9, "II. Example Rates")],
    6: [(15, "A. Example Table")],
    8: [(9, "Example Table Rates"), (45, "Alpha Rates"), (62, "Beta Rates")],
    9: [(9, "Example Component Rates ($ per kWh)")],
    10: [(12, "Example First Component:")],
    11: [(15, "Example Peak Summer"), (47, "$0.1000"), (64, "$0.2000")],
    12: [(15, "Example Off-Peak Summer"), (47, "$0.3000"), (64, "$0.4000")],
    13: [(12, "Example Second Component:")],
    14: [(15, "Example Peak Winter"), (47, "$0.5000"), (64, "$0.6000")],
    15: [(15, "Example Off-Peak Winter"), (47, "$0.7000"), (64, "$0.8000")],
}


def _components(**changes: list[tuple[int, str]] | None) -> dict[int, list[tuple[int, str]]]:
    page = {row: list(cells) for row, cells in COMPONENT_TABLE.items()}
    for key, value in changes.items():
        row = int(key.removeprefix("row"))
        if value is None:
            page.pop(row, None)
        else:
            page[row] = value
    return page


def _grouped(parsed) -> list[tuple[str, str, str]]:
    return [
        (c.group.value if c.group else "", c.label.value, c.price.amount.value)
        for c in parsed.charges
    ]


def test_a_unit_reaches_over_the_components_of_its_own_table() -> None:
    parsed = parse(build(_components()))
    assert _grouped(parsed) == [
        ("Example First Component:", "Example Peak Summer", "0.1000"),
        ("Example First Component:", "Example Peak Summer", "0.2000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.3000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.4000"),
        ("Example Second Component:", "Example Peak Winter", "0.5000"),
        ("Example Second Component:", "Example Peak Winter", "0.6000"),
        ("Example Second Component:", "Example Off-Peak Winter", "0.7000"),
        ("Example Second Component:", "Example Off-Peak Winter", "0.8000"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"$ per kWh"}


def test_the_unit_is_cited_to_the_line_that_states_it() -> None:
    """Not to the component name, which does not contain the words quoted."""
    parsed = parse(build(_components()))
    unit = parsed.charges[0].price.unit
    assert unit.value == "$ per kWh"
    assert unit.value in unit.provenance.snippet


def test_a_heading_level_with_its_own_first_line_still_heads_it() -> None:
    """One publisher sets a heading's first-level lines level with the heading.

    Its residential sheet prints ``Energy Rates by Component ($ per kWh)`` and,
    level with it, ``Generation: $0.12855``. A line level with a heading is not
    thereby the heading's sibling: how far the heading reaches is read off its
    own first line, and nothing set further left than that line is in the
    table (ADR 0017, revising ADR 0013's second fence).
    """
    parsed = parse(build(_components(row9=[(12, "Example Component Rates ($ per kWh)")])))
    assert _grouped(parsed) == [
        ("Example First Component:", "Example Peak Summer", "0.1000"),
        ("Example First Component:", "Example Peak Summer", "0.2000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.3000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.4000"),
        ("Example Second Component:", "Example Peak Winter", "0.5000"),
        ("Example Second Component:", "Example Peak Winter", "0.6000"),
        ("Example Second Component:", "Example Off-Peak Winter", "0.7000"),
        ("Example Second Component:", "Example Off-Peak Winter", "0.8000"),
    ]


def test_a_heading_set_right_of_its_own_first_line_heads_nothing() -> None:
    """A first line set left of the heading is outside it, and so is everything after."""
    parsed = parse(build(_components(row9=[(13, "Example Component Rates ($ per kWh)")])))
    assert parsed.charges == ()


def test_two_lines_that_are_not_rows_end_the_reach() -> None:
    """One line above a block is its heading. Two are prose, and end the reach."""
    page = _components(
        row13=[(12, "Example sentence about the table.")],
        row14=[(12, "Example Second Component:")],
        row15=[(15, "Example Peak Winter"), (47, "$0.5000"), (64, "$0.6000")],
        row16=[(15, "Example Off-Peak Winter"), (47, "$0.7000"), (64, "$0.8000")],
    )
    labels = {label for _, label, _ in _grouped(parse(build(page)))}
    assert "Example Peak Summer" in labels
    assert "Example Peak Winter" not in labels


def test_a_row_outdented_to_the_tables_first_line_is_priced_under_the_heading_itself() -> None:
    """A row that leaves a component's rows but stays in the table.

    Read as part of the block above, it would be published under a component
    name the publisher gave to something else. Set level with the table's
    first line, it is one of the heading's own rows and takes the heading's
    own name (ADR 0017).
    """
    page = _components(
        row16=[(12, "Example Outdented Row"), (47, "$0.9000"), (64, "$0.9500")],
        row17=[(12, "Example Second Outdented Row"), (47, "$0.9600"), (64, "$0.9700")],
    )
    grouped = _grouped(parse(build(page)))
    assert ("Example Component Rates", "Example Outdented Row", "0.9000") in grouped
    assert ("Example Component Rates", "Example Second Outdented Row", "0.9700") in grouped
    assert ("Example Second Component:", "Example Off-Peak Winter", "0.7000") in grouped
    assert not any(
        label == "Example Outdented Row" and group != "Example Component Rates"
        for group, label, _ in grouped
    )


def test_a_row_set_left_of_the_tables_first_line_is_outside_it() -> None:
    """The commercial sheet's shape: the components indented under the heading,
    then the remaining component rows back at the heading's own level.

    The heading's first line is indented, so a row at the heading's level has
    left the table, and nothing on the page says what it is priced per.
    """
    page = _components(
        row16=[(9, "Example Outdented Row"), (47, "$0.9000"), (64, "$0.9500")],
        row17=[(9, "Example Second Outdented Row"), (47, "$0.9600"), (64, "$0.9700")],
    )
    grouped = _grouped(parse(build(page)))
    assert "Example Outdented Row" not in {label for _, label, _ in grouped}
    assert ("Example Second Component:", "Example Off-Peak Winter", "0.7000") in grouped


def test_a_component_name_level_with_its_rows_groups_nothing() -> None:
    """A line set level with the rows below it is not a heading over them.

    The rows are still in the table the unit heading began, so they are priced
    under the heading's own name. That level line is the table's first line;
    the second component, set left of it, is outside the table, and its rows
    are refused.
    """
    grouped = _grouped(parse(build(_components(row10=[(15, "Example First Component:")]))))
    assert ("Example Component Rates", "Example Peak Summer", "0.1000") in grouped
    assert "Example Peak Winter" not in {label for _, label, _ in grouped}


def test_a_heading_line_carrying_both_the_unit_and_the_column_names() -> None:
    """One publisher heads an unbundling sheet this way, on a single line.

    The words naming the columns are not part of the heading's own text. Read
    as though they were, the unit comes out as "$ per kWh) Alpha Rates Beta
    Rates" or not at all.
    """
    page = {
        5: [(9, "II. Example Rates")],
        6: [(15, "A. Example Table")],
        8: [
            (9, "Example Component Rates ($ per kWh)"),
            (47, "Alpha Rates"),
            (64, "Beta Rates"),
        ],
        9: [(12, "Example First Component:")],
        10: [(15, "Example Peak Summer"), (47, "$0.1000"), (64, "$0.2000")],
        11: [(15, "Example Off-Peak Summer"), (47, "$0.3000"), (64, "$0.4000")],
    }
    parsed = parse(build(page))
    assert _grouped(parsed) == [
        ("Example First Component:", "Example Peak Summer", "0.1000"),
        ("Example First Component:", "Example Peak Summer", "0.2000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.3000"),
        ("Example First Component:", "Example Off-Peak Summer", "0.4000"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"$ per kWh"}
    assert {c.applies_to.value for c in parsed.charges if c.applies_to} == {
        "Alpha Rates",
        "Beta Rates",
    }


#: A heading whose unit the publisher broke across a line ending: the bracket
#: opens on one line and closes on the next, so neither line states a unit on
#: its own. Synthetic.
WRAPPED_UNIT = {
    5: [(9, "II. Example Rates")],
    6: [(15, "A. Example Table")],
    8: [(12, "Example Charge Rates ($ per")],
    9: [(12, "customer per day)")],
    10: [(15, "Example Tier One"), (50, "$0.1000")],
    11: [(15, "Example Tier Two"), (50, "$0.2000")],
}


def _wrapped(**changes: list[tuple[int, str]] | None) -> dict[int, list[tuple[int, str]]]:
    page = {row: list(cells) for row, cells in WRAPPED_UNIT.items()}
    for key, value in changes.items():
        row = int(key.removeprefix("row"))
        if value is None:
            page.pop(row, None)
        else:
            page[row] = value
    return page


def test_a_unit_broken_across_a_line_ending_is_read() -> None:
    parsed = parse(build(_wrapped()))
    assert [(c.label.value, c.price.amount.value) for c in parsed.charges] == [
        ("Example Tier One", "0.1000"),
        ("Example Tier Two", "0.2000"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"$ per customer per day"}
    assert {c.group.value for c in parsed.charges if c.group} == {"Example Charge Rates"}


def test_the_joined_unit_is_cited_to_both_lines_it_was_printed_on() -> None:
    """Half of it appears on each line and the whole of it on neither."""
    unit = parse(build(_wrapped())).charges[0].price.unit
    assert unit.value == "$ per customer per day"
    assert unit.value in " ".join(unit.provenance.snippet.split())
    assert unit.provenance.end_line == unit.provenance.line + 1


def test_a_bracket_that_never_closes_joins_to_nothing() -> None:
    """An open bracket states no unit, and there is nothing to complete it."""
    parsed = parse(build(_wrapped(row9=[(12, "customer per day")])))
    assert parsed.charges == ()


def test_a_bracket_taking_two_line_endings_to_close_is_refused() -> None:
    """The join is made where the very next line closes the bracket, and there.

    Reaching further would be reconstructing the heading rather than reading
    it, and nothing on the page says how far to reach.
    """
    page = _wrapped(
        row9=[(12, "customer per")],
        row10=[(12, "day)")],
        row11=[(15, "Example Tier One"), (50, "$0.1000")],
        row12=[(15, "Example Tier Two"), (50, "$0.2000")],
    )
    assert parse(build(page)).charges == ()


def test_a_wrapped_unit_reaches_over_its_components_like_any_other() -> None:
    """The publisher's sheets do both at once: a wrapped unit over components."""
    page = {
        5: [(9, "II. Example Rates")],
        6: [(15, "A. Example Table")],
        8: [(9, "Example Component Rates ($ per")],
        9: [(9, "customer per day)")],
        10: [(12, "Example First Component")],
        11: [(15, "Example Tier One"), (50, "$0.1000")],
        12: [(15, "Example Tier Two"), (50, "$0.2000")],
    }
    parsed = parse(build(page))
    assert [
        (c.group.value if c.group else None, c.label.value, c.price.amount.value)
        for c in parsed.charges
    ] == [
        ("Example First Component", "Example Tier One", "0.1000"),
        ("Example First Component", "Example Tier Two", "0.2000"),
    ]
    assert {c.price.unit.value for c in parsed.charges} == {"$ per customer per day"}


def test_a_stray_closing_bracket_does_not_pull_the_line_above_into_the_heading() -> None:
    """The join is for a unit broken across a line ending, not for any bracket.

    A line can close a bracket it did not open and still state its own unit
    whole. Joined to the line above it anyway, the block would be labelled with
    a line that is not part of its heading, and that line would be counted as
    one this parser understood.
    """
    page = {
        5: [(9, "II. Example Rates")],
        6: [(15, "A. Example Table")],
        8: [(12, "Example Unrelated Line")],
        9: [(12, "surplus) ($ per kWh)")],
        10: [(15, "Example Tier One"), (50, "$0.1000")],
        11: [(15, "Example Tier Two"), (50, "$0.2000")],
    }
    parsed = parse(build(page))
    assert {c.group.value for c in parsed.charges if c.group} == {"surplus)"}
    assert any("Example Unrelated Line" in note.value for note in parsed.notes)


def test_a_line_that_does_not_close_the_bracket_above_it_is_not_joined_to_it() -> None:
    """A line stating its own whole unit completes nothing above it.

    Joined to a line that left a bracket open, it would take that line's text
    into its label and count it as understood, while the bracket the line above
    opened is still open and still says nothing.
    """
    page = {
        5: [(9, "II. Example Rates")],
        6: [(15, "A. Example Table")],
        8: [(12, "Example Charge Rates ($ per")],
        9: [(12, "customer ($ per day)")],
        10: [(15, "Example Tier One"), (50, "$0.1000")],
        11: [(15, "Example Tier Two"), (50, "$0.2000")],
    }
    parsed = parse(build(page))
    assert {c.group.value for c in parsed.charges if c.group} == {"customer"}
    assert {c.price.unit.value for c in parsed.charges} == {"$ per day"}
    assert any("Example Charge Rates" in note.value for note in parsed.notes)


#: A single-column table in the residential sheet's shape: the heading's own
#: rows level with it, a component set level with those rows grouping rows
#: indented under it, one of those rows with its label broken at a line
#: ending, and more of the heading's own rows after, the last of them followed
#: by a line that may be the rest of its label. Synthetic throughout.
LEVEL_TABLE = {
    5: [(9, "II. Example Rates")],
    9: [(12, "Example Rates by Component ($ per kWh)")],
    10: [(12, "Example Generation:"), (52, "$0.1000")],
    11: [(12, "Example Distribution:"), (52, "$0.2000")],
    12: [(12, "Example Adjustment:")],
    13: [(15, "Example Tier 1 Usage"), (52, "$0.3000")],
    14: [(15, "Example Tier 2 (Over 400% of"), (52, "$0.4000")],
    15: [(18, "Baseline)")],
    16: [(12, "Example Transmission (all usage)"), (52, "$0.5000")],
    17: [(12, "Example Public Purpose (all usage)"), (52, "$0.6000")],
    18: [(12, "Example Indifference"), (52, "$0.7000")],
    19: [(12, "Example Adjustment (all usage)")],
}


def _level(**changes: list[tuple[int, str]] | None) -> dict[int, list[tuple[int, str]]]:
    page = {row: list(cells) for row, cells in LEVEL_TABLE.items()}
    for key, value in changes.items():
        row = int(key.removeprefix("row"))
        if value is None:
            page.pop(row, None)
        else:
            page[row] = value
    return page


def test_the_residential_sheets_shape_is_read_as_the_page_sets_it() -> None:
    """Rows level with the heading are its own; a component level with them
    groups the rows indented under it; a row whose label may go on is refused."""
    assert _grouped(parse(build(_level()))) == [
        ("Example Rates by Component", "Example Generation:", "0.1000"),
        ("Example Rates by Component", "Example Distribution:", "0.2000"),
        ("Example Adjustment:", "Example Tier 1 Usage", "0.3000"),
        ("Example Adjustment:", "Example Tier 2 (Over 400% of Baseline)", "0.4000"),
        ("Example Rates by Component", "Example Transmission (all usage)", "0.5000"),
        ("Example Rates by Component", "Example Public Purpose (all usage)", "0.6000"),
    ]


def test_a_label_broken_at_a_line_ending_is_joined_where_its_brackets_say_so() -> None:
    """The same rule ADR 0014 reads a wrapped unit by, applied to a label, and
    cited to both lines with the label's own words as the quote: the amount
    that sits between the two halves on the page is not part of the label."""
    parsed = parse(build(_level()))
    (charge,) = [c for c in parsed.charges if c.label.value.startswith("Example Tier 2")]
    assert charge.label.value == "Example Tier 2 (Over 400% of Baseline)"
    assert charge.label.provenance.end_line == charge.label.provenance.line + 1
    assert charge.label.provenance.snippet == charge.label.value
    assert charge.price.amount.provenance.end_line is None


def test_a_row_whose_label_may_go_on_is_refused_rather_than_cut() -> None:
    """An unpriced line set as a row, stating no unit and heading nothing, may
    finish the label above it. The page does not say, so the row is refused."""
    labels = {label for _, label, _ in _grouped(parse(build(_level())))}
    assert "Example Indifference" not in labels
    assert "Example Public Purpose (all usage)" in labels


def test_a_tail_that_heads_rows_finishes_no_label() -> None:
    """``Example Adjustment:`` follows a row and heads rows of its own; the row
    above it is a whole row."""
    labels = {label for _, label, _ in _grouped(parse(build(_level())))}
    assert "Example Distribution:" in labels


def test_a_tail_carrying_an_amount_the_profile_cannot_read_finishes_no_label() -> None:
    """A bracketed amount is a row of some table whether or not the profile
    reads brackets; it is never the rest of a label."""
    page = _level(row19=[(12, "Example Bracketed"), (52, "($0.0500)")])
    labels = {label for _, label, _ in _grouped(parse(build(page)))}
    assert "Example Indifference" in labels
    assert "Example Bracketed" not in labels


def test_a_tail_set_left_of_the_label_finishes_no_label() -> None:
    page = _level(row19=[(9, "Example note about the table.")])
    assert "Example Indifference" in {label for _, label, _ in _grouped(parse(build(page)))}


def test_a_tail_stating_a_unit_finishes_no_label() -> None:
    page = _level(row19=[(12, "Example Other Rates ($ per kWh)")])
    assert "Example Indifference" in {label for _, label, _ in _grouped(parse(build(page)))}


def test_a_label_whose_bracket_never_closes_on_the_next_line_is_not_joined() -> None:
    """``Baseline`` without its bracket closes nothing; the row above is then a
    row whose label may go on, and is refused rather than joined at a guess."""
    page = _level(row15=[(18, "Baseline")])
    labels = {label for _, label, _ in _grouped(parse(build(page)))}
    assert not any(label.startswith("Example Tier 2") for label in labels)
    # One row is left under "Example Adjustment:", and one row is not a table.
    assert "Example Tier 1 Usage" not in labels
    assert "Example Transmission (all usage)" in labels
