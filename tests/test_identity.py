"""A schedule names itself, and this reads only the name it prints.

The identity block is the one part of the output that describes the document
as a whole rather than a value inside it. Every field in it is either a quote
from a line the document prints or ``None``. There is no inference from the
filename, from the manifest, or from a neighbouring field, because a schedule
code guessed from a filename would be a citation to something the publisher
never wrote.

The fixtures here are synthetic and built inline.
"""

from __future__ import annotations

from ca_tariff_parse.extract import layout_from_monospace
from ca_tariff_parse.parser import parse_document

PAGE_ROWS = 54


def page(cells: dict[int, list[tuple[int, str]]], *, footer: bool = True) -> str:
    """Render one synthetic page from row and column positions."""
    grid: list[list[tuple[int, str]]] = [[] for _ in range(PAGE_ROWS)]
    grid[1].append((40, "Revised Example Sheet No. SYN-9-1"))
    if footer:
        grid[50].append((9, "EXAMPLE MUNICIPAL UTILITY (SYNTHETIC)"))
        grid[51].append((9, "Effective: February 1, 2026"))
    for row, entries in cells.items():
        grid[row].extend(entries)
    lines = []
    for entries in grid:
        line = ""
        for col, text in sorted(entries):
            line = line + " " * (col - len(line)) + text
        lines.append(line.rstrip())
    return "\n".join(lines) + "\n"


def parse(*pages: str):
    return parse_document(layout_from_monospace("\f".join(pages), "syn-identity"))


#: A running head in the second publisher's shape: the schedule names itself
#: and its sheet on one line, with the schedule's title on the line under it,
#: repeated in the same place on every sheet.
def head(
    sheet: int, *, title: str = "EXAMPLE SYNTHETIC SERVICE"
) -> dict[int, list[tuple[int, str]]]:
    return {
        5: [(10, f"ELECTRIC SCHEDULE SYN-X Sheet {sheet}")],
        6: [(10, title)],
        8: [(9, "I. Example Part")],
        9: [(12, "Example body text that no recognizer claims.")],
    }


def test_a_schedule_that_names_itself_on_every_sheet_is_read_from_it() -> None:
    """Both halves are quotes: the code from its line, the title from the next."""
    parsed = parse(page(head(1)), page(head(2)))
    identity = parsed.identity
    assert identity.schedule_code is not None
    assert identity.schedule_code.value == "SYN-X"
    assert "ELECTRIC SCHEDULE SYN-X Sheet 1" in identity.schedule_code.provenance.snippet
    assert identity.title is not None
    assert identity.title.value == "EXAMPLE SYNTHETIC SERVICE"
    assert "EXAMPLE SYNTHETIC SERVICE" in identity.title.provenance.snippet


def test_a_running_head_that_does_not_run_names_no_title() -> None:
    """The line under the schedule line is a title because it repeats.

    On a single sheet it is just the next line, and reading it would make the
    first sentence of the body the schedule's name.
    """
    parsed = parse(page(head(1)), page(head(2, title="Example body sentence, not a title.")))
    assert parsed.identity.schedule_code is not None
    assert parsed.identity.schedule_code.value == "SYN-X"
    assert parsed.identity.title is None


def test_sheets_naming_two_different_schedules_name_none() -> None:
    """A document whose own sheets disagree describes itself with neither."""
    other = head(2)
    other[5] = [(10, "ELECTRIC SCHEDULE SYN-Y Sheet 2")]
    parsed = parse(page(head(1)), page(other))
    assert parsed.identity.schedule_code is None
    assert parsed.identity.title is None


def test_a_document_printing_neither_shape_keeps_a_null_identity() -> None:
    """Neither publisher's wording, so no code and no title, rather than a guess."""
    plain = {
        5: [(10, "Example Heading With No Self Naming Line")],
        8: [(9, "I. Example Part")],
        9: [(12, "Example body text that no recognizer claims.")],
    }
    parsed = parse(page(plain), page(plain))
    assert parsed.identity.schedule_code is None
    assert parsed.identity.title is None
    assert parsed.identity.resolution is None
    assert parsed.identity.adopted is None
    assert parsed.identity.effective is None


def test_the_lines_a_running_head_names_are_accounted_for() -> None:
    """A line the parser read the schedule's name off is not unrecognized content."""
    parsed = parse(page(head(1)), page(head(2)))
    unread = {sample for item in parsed.unparsed for sample in item.sample}
    assert not any(sample.startswith("ELECTRIC SCHEDULE") for sample in unread)
    assert "EXAMPLE SYNTHETIC SERVICE" not in unread


def test_one_sheet_alone_names_a_schedule_but_no_title() -> None:
    """The code is on its own line; the title is only a title because it runs."""
    parsed = parse(page(head(1)))
    assert parsed.identity.schedule_code is not None
    assert parsed.identity.schedule_code.value == "SYN-X"
    assert parsed.identity.title is None


def test_a_schedule_line_with_nothing_under_it_names_no_title() -> None:
    """Last line on its sheet, so the page states no line to read a title from."""
    last = {
        5: [(9, "I. Example Part")],
        6: [(12, "Example body text that no recognizer claims.")],
        8: [(10, "ELECTRIC SCHEDULE SYN-X Sheet 1")],
    }
    parsed = parse(page(last, footer=False), page(last, footer=False))
    assert parsed.identity.schedule_code is not None
    assert parsed.identity.schedule_code.value == "SYN-X"
    assert parsed.identity.title is None
