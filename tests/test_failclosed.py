"""A section the parser did not understand must change the output.

This is the load-bearing test for the whole project. If a document containing
an unrecognised part could produce the same output as one the parser fully
understands, then coverage would be an unfalsifiable claim and a caller would
have no way to tell a complete parse from a partial one.
"""

from __future__ import annotations

from pathlib import Path

from ca_tariff_parse.parser import parse_path


def test_an_unknown_section_changes_the_output(
    complete_fixture: Path, unknown_fixture: Path
) -> None:
    understood = parse_path(complete_fixture).to_json()
    partial = parse_path(unknown_fixture).to_json()

    assert understood != partial, (
        "a document with an unrecognised section produced output identical to a "
        "fully understood one, which would make the coverage report meaningless"
    )
    assert understood["coverage"] != partial["coverage"]


def test_a_fully_understood_document_reports_full_coverage(complete_fixture: Path) -> None:
    parsed = parse_path(complete_fixture)
    assert parsed.coverage.fully_recognized is True
    assert parsed.coverage.unrecognized_lines == 0
    assert parsed.coverage.line_ratio == 1.0
    assert parsed.unparsed == ()


def test_an_unknown_section_is_reported_not_dropped(unknown_fixture: Path) -> None:
    parsed = parse_path(unknown_fixture)

    assert parsed.coverage.fully_recognized is False
    assert parsed.coverage.unrecognized_lines > 0
    assert parsed.unparsed, "the unrecognised section vanished from the report"

    reported = {item.section for item in parsed.unparsed}
    assert "V" in reported

    entry = next(item for item in parsed.unparsed if item.section == "V")
    assert entry.line_count == entry.last_line - entry.first_line + 1
    assert entry.reason
    assert entry.sample


def test_unrecognized_text_is_still_carried_verbatim(unknown_fixture: Path) -> None:
    """Fail closed means surfaced, not discarded."""
    parsed = parse_path(unknown_fixture)
    notes = [note.value for note in parsed.notes]
    assert any("furlongs per fortnight" in note for note in notes), (
        "text the parser could not structure was dropped instead of carried"
    )


def test_every_unparsed_line_has_a_note_with_provenance(unknown_fixture: Path) -> None:
    parsed = parse_path(unknown_fixture)
    unparsed_sections = {item.section for item in parsed.unparsed}
    noted_sections = {note.provenance.section for note in parsed.notes}
    assert unparsed_sections <= noted_sections


def test_coverage_counts_are_internally_consistent(unknown_fixture: Path) -> None:
    coverage = parse_path(unknown_fixture).coverage
    assert coverage.recognized_lines + coverage.unrecognized_lines == coverage.content_lines
    assert coverage.sections_recognized + coverage.sections_unrecognized == (
        coverage.sections_total
    )
    assert 0.0 <= coverage.line_ratio <= 1.0
    assert 0.0 <= coverage.section_ratio <= 1.0


def test_the_extra_section_does_not_perturb_what_was_understood(
    complete_fixture: Path, unknown_fixture: Path
) -> None:
    """The unknown part must not silently change the values already parsed.

    Citations legitimately differ between the two fixtures, because they are
    different files with different digests. What must not change is the tariff
    content itself.
    """
    understood = parse_path(complete_fixture)
    partial = parse_path(unknown_fixture)

    def prices(parsed) -> list[tuple[str, str, str, str]]:
        return [
            (
                charge.label.value,
                charge.kind,
                charge.price.amount.value,
                charge.effective_from.value,
            )
            for charge in parsed.charges
        ]

    def windows(parsed) -> list[tuple[str, str, bool]]:
        return [
            (window.season.value, window.period.value, window.residual)
            for window in parsed.tou_windows
        ]

    assert prices(understood) == prices(partial)
    assert windows(understood) == windows(partial)
    assert [h.name.value for h in understood.holidays] == [h.name.value for h in partial.holidays]
    assert [x.target.value for x in understood.cross_references] == [
        x.target.value for x in partial.cross_references
    ]


def test_an_unparsed_span_is_readable_across_a_page_break() -> None:
    """Line numbers are per page, so a span needs a page at each end.

    Without this a section running over a page break reports "lines 35-5",
    which a reader cannot use to find the text being reported.
    """
    from ca_tariff_parse.model import UnparsedSection

    same_page = UnparsedSection(
        section="II.C",
        heading="Example",
        page=2,
        sheet="X-2",
        first_line=3,
        last_line=9,
        line_count=7,
        reason="example",
    )
    assert same_page.span == "p.2 lines 3-9"
    assert same_page.to_json()["last_page"] == 2

    across = UnparsedSection(
        section="II.C",
        heading="Example",
        page=2,
        sheet="X-2",
        first_line=35,
        last_line=5,
        line_count=7,
        reason="example",
        last_page=3,
        last_sheet="X-3",
    )
    assert across.span == "p.2 L35 to p.3 L5"
    assert across.to_json()["last_sheet"] == "X-3"


def test_a_real_cross_page_section_reports_both_pages(unknown_fixture: Path) -> None:
    for item in parse_path(unknown_fixture).unparsed:
        assert item.end_page >= item.page
        if item.end_page == item.page:
            assert item.last_line >= item.first_line
