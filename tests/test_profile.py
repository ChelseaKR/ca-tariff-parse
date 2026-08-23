"""The document profile carries only what a document cannot state itself.

Every test here runs against a labelled synthetic fixture written in the second
publisher's shape: a keyword column instead of a numbered outline, negatives in
accounting brackets, and a supersession header naming the sheet each page
replaces. The same fixture parsed without a profile has to refuse all three,
which is what makes the seam a seam rather than a switch.
"""

from __future__ import annotations

import pytest

from ca_tariff_parse.extract import layout_from_monospace, layout_from_path
from ca_tariff_parse.parser import parse_path
from ca_tariff_parse.profiles import (
    DEFAULT,
    NUMBERED,
    DocumentProfile,
    UnknownProfileError,
    names,
    resolve,
)
from ca_tariff_parse.recognizers.base import read_amount
from ca_tariff_parse.segment import segment

from .conftest import KEYWORD

PGE = resolve("pge-tariff-book")


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_a_document_naming_no_profile_gets_the_default() -> None:
    assert resolve(None) is DEFAULT
    assert DEFAULT.outline == NUMBERED
    assert DEFAULT.bracket_negative_amounts is False
    assert DEFAULT.supersession_word is None


def test_an_unknown_profile_is_an_error_rather_than_a_fallback() -> None:
    with pytest.raises(UnknownProfileError, match="unknown document profile"):
        resolve("no-such-publisher")


def test_every_registered_profile_resolves() -> None:
    assert "default" in names()
    for name in names():
        assert resolve(name).name == name


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": " "},
        {"name": "x", "outline": "sideways"},
        {"name": "x", "supersession_word": "  "},
        {"name": "x", "change_markers": frozenset({"Rev"})},
        {"name": "x", "change_markers": frozenset({"r"})},
    ],
)
def test_a_malformed_profile_cannot_be_built(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        DocumentProfile(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Amount notation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "expected"),
    [("$1.2500", "1.2500"), ("-$1.2500", "-1.2500"), ("$1,250", "1,250"), ("n/a", None)],
)
def test_a_plain_amount_reads_the_same_under_any_profile(token: str, expected: str) -> None:
    assert read_amount(token, DEFAULT) == expected
    assert read_amount(token, PGE) == expected


def test_a_bracketed_amount_is_a_negative_only_where_a_profile_says_so() -> None:
    """Reading it anywhere else would publish a credit as though it were a charge."""
    assert read_amount("($0.08140)", DEFAULT) is None
    assert read_amount("($0.08140)", PGE) == "-0.08140"


# ---------------------------------------------------------------------------
# Supersession
# ---------------------------------------------------------------------------


def _sheet_page(profile: DocumentProfile) -> str | None:
    doc = layout_from_monospace(
        "\n".join(
            [
                "         Revised Example Sheet No. SYN-9-2",
                "         Cancelling Revised Example Sheet No. SYN-9-1",
                "",
                "         Example body line.",
            ]
        ),
        "syn-cancel",
        profile=profile,
    )
    return doc.pages[0].sheet


def test_a_profile_says_which_word_withdraws_a_sheet() -> None:
    assert _sheet_page(PGE) == "SYN-9-2"


def test_without_that_word_a_page_asserting_two_sheets_records_neither() -> None:
    """Fail closed. No citation names a sheet, rather than naming the wrong one."""
    assert _sheet_page(DEFAULT) is None


# ---------------------------------------------------------------------------
# Filing change markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("glyph", "expected"),
    [
        ("(R)", True),
        ("(N)", False),  # a real marker letter, just not one this profile names
        ("(r)", False),  # lower case is not the glyph a publisher sets
        ("|", True),
        ("Revised", False),
        ("(Revised)", False),
    ],
)
def test_is_change_marker_reads_only_the_letters_the_profile_names(
    glyph: str, expected: bool
) -> None:
    marks_r_only = DocumentProfile(name="x", change_markers=frozenset({"R"}))
    assert marks_r_only.is_change_marker(glyph) is expected


def test_a_change_bar_means_nothing_to_a_profile_naming_no_letters() -> None:
    """The bar is the same right margin glyph as the bracketed letters.

    Naming none is what a document with no marker convention gets by
    default, and a bare "|" is then just a bare "|": not read as furniture.
    """
    assert DEFAULT.is_change_marker("|") is False
    assert DEFAULT.is_change_marker("(R)") is False


def _marker_page(profile: DocumentProfile) -> tuple[bool, ...]:
    """Furniture flags, one per content line, of a tiny fixture page.

    Padded well clear of the header and footer bands, so what is being read
    is the change marker logic and not that banding. Line 2 is a bracketed
    marker this profile may or may not name; line 3 is a bare change bar;
    line 4 is a marker attached to real text, which must never be read as
    furniture -- stripping it would edit a quotation.
    """
    doc = layout_from_monospace(
        "\n".join(
            [
                *([""] * 6),
                "APPLICABILITY: This SYNTHETIC schedule applies to example customers.",
                "(R)",
                "|",
                "Example Tier 1 Usage $1.10 (R)",
            ]
        ),
        "syn-marker",
        profile=profile,
    )
    return tuple(line.furniture for line in doc.pages[0].lines)


def test_a_bare_marker_and_change_bar_become_furniture_under_a_naming_profile() -> None:
    marks_r = DocumentProfile(name="x", change_markers=frozenset({"R"}))
    flags = _marker_page(marks_r)
    assert flags == (False, True, True, False)


def test_the_same_page_keeps_every_line_as_content_under_the_default_profile() -> None:
    assert _marker_page(DEFAULT) == (False, False, False, False)


# ---------------------------------------------------------------------------
# Outline
# ---------------------------------------------------------------------------


def test_the_keyword_outline_recovers_the_parts_the_page_sets_in_column() -> None:
    doc = layout_from_path(KEYWORD, profile=PGE)
    sections = segment(doc, PGE).sections
    assert [section.section_id for section in sections] == [
        "preamble",
        "APPLICABILITY",
        "RATES",
        "SPECIALCONDITIONS",
    ]
    assert [section.heading for section in sections][1:] == [
        "APPLICABILITY",
        "RATES",
        "SPECIAL CONDITIONS",
    ]
    assert all(section.heading_inline for section in sections[1:])


def test_a_part_continued_onto_the_next_sheet_is_not_opened_again() -> None:
    """The third sheet reprints "SPECIAL CONDITIONS:" with "(Cont'd.)" beneath."""
    doc = layout_from_path(KEYWORD, profile=PGE)
    conditions = [s for s in segment(doc, PGE).sections if s.section_id == "SPECIALCONDITIONS"]
    assert len(conditions) == 1
    assert sorted({line.page for line in conditions[0].lines}) == [2, 3]


def test_the_sheet_banner_is_not_read_as_part_of_the_part_above_it() -> None:
    """Each sheet reprints its own heading, which belongs to no part.

    Attributing it to the part continued from the sheet before published a page
    banner as an eligibility statement.
    """
    doc = layout_from_path(KEYWORD, profile=PGE)
    preamble = next(s for s in segment(doc, PGE).sections if s.section_id == "preamble")
    assert [line.text for line in preamble.lines] == [
        "EXAMPLE SERVICE (SYNTHETIC) SHEET 1",
        "EXAMPLE SERVICE (SYNTHETIC) SHEET 2",
        "EXAMPLE SERVICE (SYNTHETIC) SHEET 3",
    ]


def test_without_the_profile_the_same_document_has_no_outline_at_all() -> None:
    doc = layout_from_path(KEYWORD, profile=DEFAULT)
    sections = segment(doc, DEFAULT).sections
    assert [section.section_id for section in sections] == ["preamble"]


def test_an_inline_heading_keeps_the_text_set_beside_it() -> None:
    """The keyword shares its line with the body, so that line cannot be skipped."""
    parsed = parse_path(KEYWORD, profile=PGE)
    first = parsed.applicability[0].text.value
    assert first.startswith("APPLICABILITY: This SYNTHETIC schedule applies")


def test_paragraphs_under_a_keyword_are_split_on_the_spacing_the_page_sets() -> None:
    """One paragraph saying who is eligible must not absorb the one saying who is not."""
    parsed = parse_path(KEYWORD, profile=PGE)
    assert [item.disposition for item in parsed.applicability] == ["included", "excluded"]


# ---------------------------------------------------------------------------
# Prices dated by the sheet rather than by the row
# ---------------------------------------------------------------------------


def _prices(profile: DocumentProfile) -> dict[str, str]:
    parsed = parse_path(KEYWORD, profile=profile)
    return {charge.label.value: charge.price.amount.value for charge in parsed.charges}


def test_every_price_in_the_fixture_is_read_exactly_as_printed() -> None:
    assert _prices(PGE) == {
        "Example Tier 1 Usage": "1.1000",
        "Example Tier 2 Usage": "1.2000",
        "Example Adjustment": "-0.0500",
        "Example 2024 Vintage": "5.0000",
        "Example 2025 Vintage": "5.2500",
        "Example 2026 Vintage": "-5.5000",
    }


def test_a_bracketed_price_is_withheld_from_a_document_with_no_profile() -> None:
    """Not guessed at, and not read as a positive: simply not emitted."""
    assert "Example Adjustment" not in _prices(DEFAULT)
    assert "Example 2026 Vintage" not in _prices(DEFAULT)
    assert _prices(DEFAULT)["Example Tier 1 Usage"] == "1.1000"


def test_a_price_takes_the_date_of_the_sheet_it_is_printed_on() -> None:
    """The sheets of one schedule take effect on different days."""
    parsed = parse_path(KEYWORD, profile=PGE)
    dated = {charge.label.value: charge.effective_from.value for charge in parsed.charges}
    assert dated["Example Tier 1 Usage"] == "February 1, 2026"
    assert dated["Example 2024 Vintage"] == "March 1, 2026"


def test_each_price_carries_the_unit_and_heading_its_block_states() -> None:
    parsed = parse_path(KEYWORD, profile=PGE)
    tier = next(c for c in parsed.charges if c.label.value == "Example Tier 1 Usage")
    assert tier.price.unit.value == "$ per kWh"
    assert tier.group is not None
    assert tier.group.value == "Example Energy Rates"
    assert tier.kind == "energy_usage"
    vintage = next(c for c in parsed.charges if c.label.value == "Example 2024 Vintage")
    assert vintage.price.unit.value == "per kWh"
    assert vintage.group is not None
    assert vintage.group.value == "Example Vintage Rate"


def test_a_block_whose_heading_states_no_unit_is_refused() -> None:
    """A price with no stated unit says nothing about what it is a price for."""
    assert not [label for label in _prices(PGE) if label.startswith("Example Refused")]


def test_nothing_is_read_from_a_page_that_sets_amounts_in_two_columns() -> None:
    """A single amount in a two column table has to say which column it is in.

    The second sheet of the fixture prices two categories side by side, and
    also carries a block of single amounts under the first of them. Neither is
    read: the two column rows because this shape names no columns, and the
    single ones because the page proves there is more than one to choose from.
    """
    emitted = _prices(PGE)
    assert not [label for label in emitted if label.startswith("Example Peak")]
    assert not [label for label in emitted if label.startswith("Example Single")]


def test_what_is_refused_is_reported_rather_than_dropped() -> None:
    parsed = parse_path(KEYWORD, profile=PGE)
    refused = " ".join(note.value for note in parsed.notes)
    assert "Example Refused Row One" in refused
    assert "Example Peak Usage" in refused
    assert "Example Single One" in refused
    assert parsed.coverage.fully_recognized is False
