"""Layout extraction and section segmentation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ca_tariff_parse.extract import (
    Line,
    Word,
    cluster_lines,
    layout_from_monospace,
    layout_from_path,
    normalize,
    squash,
)
from ca_tariff_parse.recognizers.billing_periods import logical_rows
from ca_tariff_parse.segment import classify_heading, roman_to_int, segment


def test_normalize_straightens_quotes_and_collapses_leaders() -> None:
    assert normalize("Credit……… -$0.0150/kWh") == "Credit -$0.0150/kWh"
    assert normalize("a “month” is") == 'a "month" is'
    assert normalize("  spaced   out  ") == "spaced out"


def test_squash_survives_letter_spacing_artifacts() -> None:
    assert squash("Non-S ummer S eason") == squash("Non-Summer Season")
    assert squash("M id-Peak") == "mid-peak"


def test_cluster_lines_joins_words_split_by_sub_point_jitter() -> None:
    words = [
        (731.5, Word("Resolution", 54.0, 100.0)),
        (732.4, Word("Effective:", 400.0, 450.0)),
        (718.0, Word("SACRAMENTO", 54.0, 160.0)),
    ]
    clustered = cluster_lines(words)
    assert len(clustered) == 2
    assert [w.text for w in clustered[1][1]] == ["Resolution", "Effective:"]


def test_cluster_lines_handles_no_words() -> None:
    assert cluster_lines([]) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [("I", 1), ("II", 2), ("IV", 4), ("IX", 9), ("XIV", 14), ("nope", None), ("", None)],
)
def test_roman_to_int(text: str, expected: int | None) -> None:
    assert roman_to_int(text) == expected


def test_classify_heading_respects_indent() -> None:
    def line(text: str, x0: float) -> Line:
        return Line(
            page=1,
            index=1,
            top=100.0,
            words=tuple(
                Word(part, x0 + i * 10, x0 + i * 10 + 8) for i, part in enumerate(text.split())
            ),
            furniture=False,
        )

    assert classify_heading(line("II. Firm Service Rates", 57.6)) is not None
    # The same text indented as body copy is not a heading.
    assert classify_heading(line("II. Firm Service Rates", 300.0)) is None
    heading = classify_heading(line("A. Time-of-Day Rate", 90.0))
    assert heading is not None
    assert heading.level == 2


def test_classify_heading_ignores_furniture() -> None:
    line = Line(
        page=1,
        index=1,
        top=10.0,
        words=(Word("I.", 57.6, 62.0), Word("X", 70.0, 75.0)),
        furniture=True,
    )
    assert classify_heading(line) is None


def test_segmentation_assigns_every_content_line_to_one_section(
    complete_fixture: Path,
) -> None:
    doc = layout_from_path(complete_fixture)
    segmented = segment(doc)
    assigned = [line for section in segmented.sections for line in section.lines]
    content = [line for line in doc.all_lines() if not line.furniture]
    assert len(assigned) == len(content)
    assert {(line.page, line.index) for line in assigned} == {
        (line.page, line.index) for line in content
    }


def test_segmentation_rejects_an_out_of_order_roman_numeral() -> None:
    text = "\n".join(
        [
            "",
            "                                                            Example Header",
            "                                                            Rate Schedule SYN-9",
            "",
            "",
            "         I. Applicability",
            "               Example body text for the applicability part.",
            "         I. This repeated numeral is body copy, not a new part.",
            "         II. Example Rates",
            "               Example body text for the rates part.",
        ]
        + [""] * 44
    )
    segmented = segment(layout_from_monospace(text, "syn"))
    assert [s.section_id for s in segmented.sections] == ["I", "II"]


def test_monospace_front_end_marks_header_and_footer_as_furniture(
    complete_fixture: Path,
) -> None:
    doc = layout_from_path(complete_fixture)
    page = doc.pages[0]
    assert page.sheet == "SYN-1-1"
    furniture = [line.text for line in page.lines if line.furniture]
    assert any("Rate Schedule SYN-1" in text for text in furniture)
    assert any("Sheet No." in text for text in furniture)


def test_layout_from_path_flags_a_synthetic_fixture(complete_fixture: Path) -> None:
    assert layout_from_path(complete_fixture).synthetic is True


def test_logical_rows_merges_a_vertically_centred_cell() -> None:
    """A centred period label sits between the two wrapped halves of its row."""

    def line(index: int, top: float) -> Line:
        return Line(page=1, index=index, top=top, words=(Word("x", 10.0, 20.0),), furniture=False)

    lines = [
        line(1, 343.6),
        line(2, 356.7),
        line(3, 362.8),
        line(4, 367.9),
        line(5, 381.7),
        line(6, 395.5),
        line(7, 408.8),
    ]
    rows = logical_rows(lines)
    assert [[item.index for item in row] for row in rows] == [[1], [2, 3, 4], [5], [6], [7]]


def test_logical_rows_keeps_evenly_spaced_lines_separate() -> None:
    def line(index: int) -> Line:
        return Line(
            page=1,
            index=index,
            top=100.0 + index * 14.0,
            words=(Word("x", 1.0, 2.0),),
            furniture=False,
        )

    lines = [line(i) for i in range(5)]
    assert [len(row) for row in logical_rows(lines)] == [1, 1, 1, 1, 1]


def test_logical_rows_handles_a_single_line() -> None:
    line = Line(page=1, index=1, top=1.0, words=(Word("x", 1.0, 2.0),), furniture=False)
    assert logical_rows([line]) == [[line]]
    assert logical_rows([]) == []


def _page(rows: dict[int, str]) -> str:
    return "\n".join(rows.get(index, "") for index in range(max(rows) + 1)) + "\n"


def test_a_page_that_might_be_two_sheets_is_cited_as_neither() -> None:
    """A supersession header names the sheet this page replaces, not this one.

    Citing the withdrawn number would point every value on the page at a
    document the publisher has retired. Which word announces the withdrawal is
    the publisher's filing convention and comes from the document profile, so
    with no profile neither number is recorded. Reading it with one is covered
    in ``test_profile.py``.
    """
    doc = layout_from_monospace(
        _page(
            {
                0: "         Revised Example Sheet No. SYN-9-2",
                1: "         Cancelling Revised Example Sheet No. SYN-9-1",
                3: "         Example body line.",
            }
        ),
        "syn-cancel",
    )
    assert doc.pages[0].sheet is None


def test_no_sheet_is_recorded_when_a_page_asserts_two_different_ones() -> None:
    """Disagreement is not resolved by picking one of them."""
    doc = layout_from_monospace(
        _page(
            {
                0: "         Example Sheet No. SYN-9-2",
                1: "         Example Sheet No. SYN-9-7",
                3: "         Example body line.",
            }
        ),
        "syn-two-sheets",
    )
    assert doc.pages[0].sheet is None


def test_a_body_line_low_on_the_page_is_not_treated_as_a_footer() -> None:
    """The footer begins where the page leaves clear space, not at a fixed band.

    A publisher that runs body text further down the page than another would
    otherwise lose those lines: they would be excluded from the coverage
    denominator and never reported as unparsed.
    """
    rows = {index: f"         Example body line {index}." for index in range(2, 51)}
    rows[53] = "         Example Utility (SYNTHETIC) Sheet No. SYN-9-1"
    doc = layout_from_monospace(_page(rows), "syn-low-body")
    page = doc.pages[0]
    low = next(line for line in page.lines if line.text.endswith("line 50."))
    assert low.furniture is False
    footer = next(line for line in page.lines if "Sheet No." in line.text)
    assert footer.furniture is True
