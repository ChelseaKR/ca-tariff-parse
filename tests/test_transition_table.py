"""A priced table dated by a bare year in its own header, not a date column.

Shaped after Section VIII of the commercial and industrial schedule: a single
price column headed by nothing but a year and a footnote mark, a rate
category caption, and rows whose season, time-of-use period and unit are all
folded into the row's own label rather than split across headings above it.

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
    return parse_document(layout_from_monospace(text, "syn-transition"))


TABLE_ROWS = {
    5: [(9, "II. Transition Schedule")],
    7: [(20, "Season and Charge Component"), (60, "Unit"), (80, "2028*")],
    9: [(15, "CITS-0: C&I Secondary 0-20 kW")],
    10: [(20, "System Infrastructure Fixed Charge per month"), (80, "$44.45")],
    11: [(20, "Non-Summer Peak per kWh"), (80, "$0.1506")],
    12: [(20, "Summer Peak per kWh"), (80, "$0.3558")],
    14: [(9, "*Subject to future rate increases.")],
}


def test_a_bare_year_header_dates_every_row_in_the_table() -> None:
    parsed = parse(build(TABLE_ROWS))

    by_label = {c.label.value: c for c in parsed.charges}
    assert set(by_label) == {
        "System Infrastructure Fixed Charge per month",
        "Non-Summer Peak per kWh",
        "Summer Peak per kWh",
    }

    fixed = by_label["System Infrastructure Fixed Charge per month"]
    assert fixed.kind == "fixed_charge"
    assert fixed.price.amount.value == "44.45"
    assert fixed.price.unit.value == "per month"
    assert fixed.effective_from.value == "2028"
    assert fixed.rate_category is not None and fixed.rate_category.value == "CITS-0"
    assert fixed.season is None and fixed.tou_period is None

    peak = by_label["Non-Summer Peak per kWh"]
    assert peak.kind == "energy_usage"
    assert peak.price.amount.value == "0.1506"
    assert peak.effective_from.value == "2028"
    assert peak.season is not None and peak.season.value == "Non-Summer"
    assert peak.tou_period is not None and peak.tou_period.value == "Peak"

    summer_peak = by_label["Summer Peak per kWh"]
    assert summer_peak.season is not None and summer_peak.season.value == "Summer"
    assert summer_peak.tou_period is not None and summer_peak.tou_period.value == "Peak"

    # The footnote is prose, not a row of the table, and is left unparsed
    # rather than folded into the price above it.
    assert any("future rate increases" in note.value for note in parsed.notes)
    assert any(item.section == "II" for item in parsed.unparsed)


def test_the_footnote_asterisk_does_not_reach_the_effective_date() -> None:
    parsed = parse(build(TABLE_ROWS))
    assert all(c.effective_from.value == "2028" for c in parsed.charges)


def test_a_year_ending_header_with_no_unit_word_is_not_claimed() -> None:
    """ "Unit" has to be on the header line, or this is not that shape."""
    rows = {
        5: [(9, "II. Some Other Table")],
        7: [(20, "Season and Charge Component"), (80, "2028*")],
        9: [(15, "CITS-0: C&I Secondary 0-20 kW")],
        10: [(20, "System Infrastructure Fixed Charge per month"), (80, "$44.45")],
    }
    parsed = parse(build(rows))
    assert parsed.charges == ()


def test_a_row_with_no_readable_unit_is_refused_without_losing_its_neighbours() -> None:
    rows = dict(TABLE_ROWS)
    rows[10] = [(20, "Mystery Fee"), (80, "$44.45")]
    parsed = parse(build(rows))

    by_label = {c.label.value: c for c in parsed.charges}
    assert "Mystery Fee" not in by_label
    assert "Non-Summer Peak per kWh" in by_label
    assert any("Mystery Fee" in note.value for note in parsed.notes)
