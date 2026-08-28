"""A schedule names itself on the line that runs across its sheets.

Two publishers write that line differently. One prints "Rate Schedule R-TOD" in
the header band with the title above it; the other prints "ELECTRIC SCHEDULE
B-1 Sheet 3" in the body with the title below it and a regulatory identifier
above. Neither of those is something a document cannot state about itself, so
neither belongs in a document profile: what tells them apart is on the page.

All fixtures here are synthetic and built inline.
"""

from __future__ import annotations

from ca_tariff_parse.extract import layout_from_monospace
from ca_tariff_parse.parser import parse_document

PAGE_ROWS = 54


def page(cells: dict[int, str], *, sheet: str) -> str:
    """One synthetic sheet, with the footer a real one carries."""
    grid = [""] * PAGE_ROWS
    for row, text in cells.items():
        grid[row] = " " * 9 + text
    grid[50] = " " * 9 + f"EXAMPLE MUNICIPAL UTILITY (SYNTHETIC) Sheet No. {sheet}"
    grid[51] = (
        " " * 9 + "Resolution No. SYN-00-00 adopted January 1, 2026 Effective: February 1, 2026"
    )
    return "\n".join(line.rstrip() for line in grid)


def parse(*sheets: str):
    return parse_document(layout_from_monospace("\f".join(sheets), "syn-identity"))


def identity(*sheets: str) -> tuple[str | None, str | None]:
    parsed = parse(*sheets)
    code = parsed.identity.schedule_code
    title = parsed.identity.title
    return (code.value if code else None, title.value if title else None)


def test_the_title_above_the_schedule_line_is_read_when_it_runs() -> None:
    """One publisher's shape: title above, body below, and the body changes."""
    assert identity(
        page(
            {1: "Example Service Title", 2: "Rate Schedule SYN-X", 4: "Example first body line."},
            sheet="SYN-X-1",
        ),
        page(
            {1: "Example Service Title", 2: "Rate Schedule SYN-X", 4: "Example second body line."},
            sheet="SYN-X-2",
        ),
    ) == ("SYN-X", "Example Service Title")


def test_the_title_below_the_schedule_line_is_read_when_it_runs() -> None:
    """The other publisher's shape, with the line above changing sheet to sheet."""
    assert identity(
        page(
            {
                1: "U 39 Example City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 1",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-1",
        ),
        page(
            {
                1: "U 39 Other City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 2",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-2",
        ),
    ) == ("SYN-X", "EXAMPLE GENERAL SERVICE")


def test_when_both_neighbours_run_neither_is_read_as_the_title() -> None:
    """Nothing on the page says which of two repeating lines names the schedule."""
    assert identity(
        page(
            {
                1: "U 39 Example City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 1",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-1",
        ),
        page(
            {
                1: "U 39 Example City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 2",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-2",
        ),
    ) == ("SYN-X", None)


def test_a_sentence_ending_in_the_word_schedule_is_not_a_running_head() -> None:
    """A real line of one of these documents ends "... or agricultural schedule is".

    It matches the shape exactly once, on one sheet, which is what tells it
    from the line that names the schedule on every sheet.
    """
    assert identity(
        page(
            {
                1: "Example Service Title",
                2: "Rate Schedule SYN-X",
                4: "Example customers taking service under another schedule is",
            },
            sheet="SYN-X-1",
        ),
        page(
            {1: "Example Service Title", 2: "Rate Schedule SYN-X", 4: "Example second body line."},
            sheet="SYN-X-2",
        ),
    ) == ("SYN-X", "Example Service Title")


def test_a_schedule_named_on_one_sheet_only_is_not_read() -> None:
    """A running head runs. One appearance is a sentence until proven otherwise."""
    assert identity(
        page(
            {1: "Example Service Title", 2: "Rate Schedule SYN-X", 4: "Example first body line."},
            sheet="SYN-X-1",
        ),
        page({1: "Example Service Title", 4: "Example second body line."}, sheet="SYN-X-2"),
    ) == (None, None)


def test_two_schedules_running_equally_are_both_refused() -> None:
    """A document whose sheets name two schedules is described by neither."""
    assert identity(
        page({2: "Rate Schedule SYN-X", 3: "Rate Schedule SYN-Y"}, sheet="SYN-X-1"),
        page({2: "Rate Schedule SYN-X", 3: "Rate Schedule SYN-Y"}, sheet="SYN-X-2"),
    ) == (None, None)


def test_the_schedule_line_is_accounted_for_rather_than_left_unread() -> None:
    """It is content on one publisher's sheets, and now it is understood content."""
    parsed = parse(
        page(
            {
                1: "U 39 Example City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 1",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-1",
        ),
        page(
            {
                1: "U 39 Other City, California",
                2: "EXAMPLE SCHEDULE SYN-X Sheet 2",
                3: "EXAMPLE GENERAL SERVICE",
            },
            sheet="SYN-X-2",
        ),
    )
    unread = " ".join(sample for item in parsed.unparsed for sample in item.sample)
    assert "EXAMPLE SCHEDULE SYN-X" not in unread
    assert "EXAMPLE GENERAL SERVICE" not in unread
