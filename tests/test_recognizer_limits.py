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
