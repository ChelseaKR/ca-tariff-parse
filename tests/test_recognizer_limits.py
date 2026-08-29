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
