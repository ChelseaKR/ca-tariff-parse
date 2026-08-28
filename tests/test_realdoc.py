"""Parse the real published schedules, when they are present locally.

The published PDFs are not redistributed from this repository, so these tests
skip unless the documents have been fetched. What is committed for the
documents this parser structures is the golden output: the structured result of
parsing them, with every value carrying its citation. Comparing against the
golden file is how a change in the parser that would alter a published price
gets caught.

A second publisher's schedules are here too. They are read through a document
profile and parse in part. No golden file is committed for those, because most
of each document still sits verbatim in ``notes`` and committing that would
republish it. What is committed instead is a spot check: a handful of prices
quoted from the sheets, so that a parser change altering one of them fails
here rather than passing quietly.

Run ``make fetch`` first to exercise these.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_tariff_parse.parser import parse_manifest_document
from ca_tariff_parse.sources import find, load_manifest, verify

from .conftest import GOLDEN, REPO_ROOT, SOURCES, cited_value_count, unquoted_values

pytestmark = pytest.mark.realdoc

MANIFEST = REPO_ROOT / "sources" / "sources.toml"
CASES = [
    ("smud-r-tod", "1-R-TOD.pdf"),
    ("smud-r", "1-R.pdf"),
    ("smud-ci-tod1", "CI-TOD1.pdf"),
    ("smud-ssr", "01_SSR.pdf"),
]
#: A second publisher, read through the ``pge-tariff-book`` profile. No golden
#: file is committed for these: most of each document is still carried verbatim
#: in ``notes`` and committing that would republish it.
SECOND_PUBLISHER_CASES = [
    ("pge-e-1", "ELEC_SCHEDS_E-1.pdf"),
    ("pge-e-tou-c", "ELEC_SCHEDS_E-TOU-C.pdf"),
    ("pge-b-1", "ELEC_SCHEDS_B-1.pdf"),
]


def _require(document_id: str, filename: str) -> Path:
    path = SOURCES / filename
    if not path.exists():
        pytest.skip(f"{document_id} ({filename}) not fetched; run `make fetch`")
    return path


@pytest.mark.parametrize(("document_id", "filename"), CASES)
def test_local_document_matches_the_manifest_digest(document_id: str, filename: str) -> None:
    path = _require(document_id, filename)
    entry = find(load_manifest(MANIFEST), document_id)
    assert verify(entry, path) == entry.sha256


@pytest.mark.parametrize(("document_id", "filename"), CASES)
def test_parse_matches_the_committed_golden_output(document_id: str, filename: str) -> None:
    path = _require(document_id, filename)
    golden_path = GOLDEN / f"{document_id}.json"
    if not golden_path.exists():
        pytest.skip(f"no golden file for {document_id}")

    entry = find(load_manifest(MANIFEST), document_id)
    actual = parse_manifest_document(entry, path).to_json()
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert actual == expected, (
        f"parsing {filename} no longer reproduces {golden_path.name}. "
        "If this change is intended, regenerate with `make golden` and review "
        "every changed price before committing."
    )


def test_the_real_schedule_is_not_flagged_synthetic() -> None:
    path = _require("smud-r-tod", "1-R-TOD.pdf")
    entry = find(load_manifest(MANIFEST), "smud-r-tod")
    assert parse_manifest_document(entry, path).source.synthetic is False


@pytest.mark.parametrize(("document_id", "filename"), CASES)
def test_real_coverage_is_reported_honestly(document_id: str, filename: str) -> None:
    """Every real document is only partly structured, and says so."""
    path = _require(document_id, filename)
    entry = find(load_manifest(MANIFEST), document_id)
    parsed = parse_manifest_document(entry, path)
    assert parsed.coverage.fully_recognized is False
    assert parsed.unparsed
    assert 0.0 < parsed.coverage.line_ratio < 1.0


def test_a_prose_only_schedule_emits_no_charge() -> None:
    """SSR states its one price inside a sentence, and no price is invented.

    Coverage on that document is real, but it comes entirely from eligibility
    and applicability text. A schedule with no rate table produces no charges,
    which is the honest outcome and not a silent zero.
    """
    path = _require("smud-ssr", "01_SSR.pdf")
    entry = find(load_manifest(MANIFEST), "smud-ssr")
    parsed = parse_manifest_document(entry, path)
    assert parsed.charges == ()
    assert parsed.applicability
    assert any(item.section == "VI" for item in parsed.unparsed)


def test_a_multi_column_dated_block_keeps_its_amounts_apart() -> None:
    """The commercial standby block prices three voltage levels on one row."""
    path = _require("smud-ci-tod1", "CI-TOD1.pdf")
    entry = find(load_manifest(MANIFEST), "smud-ci-tod1")
    parsed = parse_manifest_document(entry, path)
    standby = [c for c in parsed.charges if c.label.value.startswith("Standby Service Charge")]
    assert len(standby) == 9
    assert {c.applies_to.value for c in standby if c.applies_to} == {
        "Secondary",
        "Primary",
        "Subtransmission",
    }
    # No amount ever leaks into the effective date it is filed under.
    assert all("$" not in c.effective_from.value for c in parsed.charges)


@pytest.mark.parametrize(("document_id", "filename"), SECOND_PUBLISHER_CASES)
def test_second_publisher_document_matches_the_manifest_digest(
    document_id: str, filename: str
) -> None:
    path = _require(document_id, filename)
    entry = find(load_manifest(MANIFEST), document_id)
    assert verify(entry, path) == entry.sha256


def _parse(document_id: str, filename: str):
    path = _require(document_id, filename)
    entry = find(load_manifest(MANIFEST), document_id)
    return parse_manifest_document(entry, path)


@pytest.mark.parametrize(("document_id", "filename"), SECOND_PUBLISHER_CASES)
def test_a_second_publisher_is_accounted_for_line_by_line(document_id: str, filename: str) -> None:
    """Partly structured, and every line of the rest reported.

    Reading a second publisher at all depends on a document profile. What must
    not change is the accounting: no window or holiday is claimed from a shape
    the parser cannot follow, and every content line is either consumed by a
    recognizer or carried verbatim with its location.
    """
    parsed = _parse(document_id, filename)

    assert parsed.tou_windows == ()
    assert parsed.holidays == ()
    assert 0.0 < parsed.coverage.line_ratio < 1.0
    assert parsed.coverage.fully_recognized is False
    unread = parsed.coverage.content_lines - parsed.coverage.recognized_lines
    assert len(parsed.notes) == unread
    assert sum(item.line_count for item in parsed.unparsed) == unread


#: Prices quoted from the second publisher's sheets, each with the unit and the
#: effective date the sheet states, checked against the PDF by hand. These
#: stand in for a golden file, which cannot be committed without republishing
#: the document.
SPOT_CHECKS = [
    (
        "pge-e-1",
        "ELEC_SCHEDS_E-1.pdf",
        "Tier 1 Usage (0% - 100% of Baseline)",
        "0.32561",
        "$ per kWh",
        "June 1, 2026",
        "Total Energy Rates",
    ),
    (
        "pge-e-1",
        "ELEC_SCHEDS_E-1.pdf",
        "Income Tier 3",
        "0.79343",
        "$ per customer per day",
        "June 1, 2026",
        "Base Services Charge Rates",
    ),
    (
        "pge-e-1",
        "ELEC_SCHEDS_E-1.pdf",
        "Generation:",
        "0.12855",
        "$ per kWh",
        "March 1, 2026",
        "Energy Rates by Component",
    ),
    # An accounting-bracket negative, which is only readable through a profile.
    (
        "pge-e-1",
        "ELEC_SCHEDS_E-1.pdf",
        "2026 Vintage",
        "-0.01011",
        "per kWh",
        "March 1, 2026",
        "Vintage Power Charge Indifference Adjustment Rate",
    ),
    (
        "pge-e-tou-c",
        "ELEC_SCHEDS_E-TOU-C.pdf",
        "2009 Vintage",
        "0.02973",
        "per kWh",
        "March 1, 2026",
        "Vintage Power Charge Indifference Adjustment Rate",
    ),
    (
        "pge-b-1",
        "ELEC_SCHEDS_B-1.pdf",
        "2025 Vintage",
        "-0.00990",
        "per kWh",
        "January 1, 2026",
        "Vintaged Power Charge Indifference Adjustment Rate",
    ),
]


@pytest.mark.parametrize(
    ("document_id", "filename", "label", "amount", "unit", "effective", "group"), SPOT_CHECKS
)
def test_a_quoted_price_is_still_read_exactly_as_published(
    document_id: str,
    filename: str,
    label: str,
    amount: str,
    unit: str,
    effective: str,
    group: str,
) -> None:
    parsed = _parse(document_id, filename)
    # A label is unique only inside its own block: the unbundling sheets state
    # "Income Tier 3" once per component, at four different prices. What names
    # one row of one document is the pair the sheet itself prints.
    matching = [
        charge
        for charge in parsed.charges
        if charge.label.value == label and charge.group is not None and charge.group.value == group
    ]
    assert len(matching) == 1, f"{label} under {group} appears {len(matching)} times"
    charge = matching[0]
    assert charge.price.amount.value == amount
    assert charge.price.unit.value == unit
    assert charge.effective_from.value == effective
    # The citation has to lead back to the printed line.
    assert amount.lstrip("-") in charge.price.amount.provenance.snippet


def test_the_sheets_of_one_schedule_are_dated_one_by_one() -> None:
    """Sheet 1 of E-1 takes effect three months after the sheets behind it.

    Dating every price to the document rather than to its own sheet would file
    most of this schedule under a day it did not take effect.
    """
    parsed = _parse("pge-e-1", "ELEC_SCHEDS_E-1.pdf")
    by_page = {
        charge.price.amount.provenance.page: charge.effective_from.value
        for charge in parsed.charges
    }
    assert by_page[1] == "June 1, 2026"
    assert by_page[2] == "March 1, 2026"


def test_a_two_column_sheet_prices_the_rows_that_fill_both_columns() -> None:
    """B-1 prices two rate options side by side and names them over the table.

    A row carrying one cell per named column is read across them, and every
    price says which column it came from. A row carrying fewer is still
    refused: its single amount may be one column's or the whole row's, and the
    page does not say which. That is what keeps the PDP tables further down the
    same sheet, which price one amount under a two column table, unread.
    """
    parsed = _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf")
    wide = [charge for charge in parsed.charges if charge.applies_to is not None]
    assert {charge.price.amount.provenance.page for charge in wide} == {3, 4}
    assert len(wide) == 41
    assert {charge.applies_to.value for charge in wide if charge.applies_to} == {
        "B-1 Rates",
        "B1-ST Rates",
        "B-1 Rate",
        "B1-ST Rate",
    }
    assert {charge.group.value for charge in wide if charge.group} == {
        "Total TOU Energy Rates",
        "Total Demand Rate",
        "Generation:",
        "Distribution**:",
    }

    # The single column table on the billing sheet reads exactly as before.
    single = [charge for charge in parsed.charges if charge.applies_to is None]
    assert {charge.price.amount.provenance.page for charge in single} == {6}
    assert all(charge.price.unit.value == "per kWh" for charge in single)

    # Still refused on the same sheet: a row with one amount under two columns.
    assert "All Usage During PDP Event" not in {charge.label.value for charge in parsed.charges}


def test_a_row_whose_column_carries_no_price_prices_only_the_other() -> None:
    """B-1's winter partial-peak rate is published for one rate option only.

    The publisher marks the other column with dashes. Reading that row as
    though its single amount were the whole row would price a rate option the
    sheet does not price at all.
    """
    parsed = _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf")
    partial = [
        charge for charge in parsed.charges if charge.label.value.startswith("Partial-Peak Winter")
    ]
    assert [
        (
            charge.price.amount.value,
            charge.applies_to.value if charge.applies_to else None,
            charge.group.value if charge.group else None,
        )
        for charge in partial
    ] == [
        ("0.36632", "B1-ST Rates", "Total TOU Energy Rates"),
        ("0.12812", "B1-ST Rate", "Generation:"),
        ("0.16787", "B1-ST Rate", "Distribution**:"),
    ]


def test_no_citation_names_a_sheet_the_publisher_cancelled() -> None:
    """Each page prints its own sheet number over the one it supersedes.

    Reading the second of the two made every citation on the page point at a
    withdrawn document. Which word announces the supersession comes from the
    manifest's profile.
    """
    parsed = _parse("pge-e-1", "ELEC_SCHEDS_E-1.pdf")
    sheets = [sheet.value for sheet in parsed.identity.sheets]
    assert sheets == ["61362-E", "61097-E", "61098-E", "61099-E", "61100-E", "61101-E", "61102-E"]
    assert "61247-E" not in sheets
    assert all(note.provenance.sheet in sheets for note in parsed.notes)


@pytest.mark.parametrize(("document_id", "filename"), CASES + SECOND_PUBLISHER_CASES)
def test_every_cited_value_appears_on_the_line_it_cites(document_id: str, filename: str) -> None:
    """A citation a reader cannot check is not much of a citation.

    Every value this parser emits carries the document, page, section and line
    it was read from, and a snippet of that line. When the snippet does not
    contain the value, either the value was composed rather than quoted or it
    was quoted from the wrong line, and from the output alone those look the
    same.

    The one composition in the parser today is a credit's unit: the row prints
    "-$0.0150/kWh" and the unit is written "$/kWh" from it. It is named here
    rather than skipped, so a second composition cannot appear quietly.
    """
    path = _require(document_id, filename)
    parsed = parse_manifest_document(find(load_manifest(MANIFEST), document_id), path)
    if not parsed.charges:
        pytest.skip(f"{document_id} emits no charges to check")

    unquoted = unquoted_values(parsed)
    assert [field for field, _, _ in unquoted] == [
        "price.unit:credit" for field, _, _ in unquoted
    ], unquoted
    # The check has to have looked at something: one silent zero here would
    # make every assertion above vacuous.
    assert cited_value_count(parsed) >= 4 * len(parsed.charges)


def test_a_component_table_prices_each_component_under_its_own_name() -> None:
    """The unbundling sheets state one unit and then name each component.

    Every row of both components carries the same two labels, so filing them
    all under the table's own heading would publish four different prices for
    "Peak Summer" with nothing to tell them apart.
    """
    parsed = _parse("pge-e-tou-c", "ELEC_SCHEDS_E-TOU-C.pdf")
    unbundled = [
        (
            charge.group.value if charge.group else None,
            charge.label.value,
            charge.price.amount.value,
            charge.applies_to.value if charge.applies_to else None,
        )
        for charge in parsed.charges
        if charge.price.amount.provenance.page == 3
    ]
    assert unbundled == [
        ("Generation:", "Summer (all usage)", "0.20782", "PEAK"),
        ("Generation:", "Summer (all usage)", "0.10482", "OFF-PEAK"),
        ("Generation:", "Winter (all usage)", "0.13710", "PEAK"),
        ("Generation:", "Winter (all usage)", "0.11042", "OFF-PEAK"),
        ("Distribution**:", "Summer (all usage)", "0.20388", "PEAK"),
        ("Distribution**:", "Summer (all usage)", "0.18388", "OFF-PEAK"),
        ("Distribution**:", "Winter (all usage)", "0.14977", "PEAK"),
        ("Distribution**:", "Winter (all usage)", "0.14645", "OFF-PEAK"),
    ]
    assert {charge.price.unit.value for charge in parsed.charges} == {
        "$ per kWh",
        "per kWh",
        "$ per customer per day",
    }


def test_the_rows_a_component_table_sets_level_with_its_own_heading_stay_unread() -> None:
    """Below the components, the same sheets set component rows at the table's
    own indentation, with the unit heading seventeen lines and a whole
    sub-table above them. Nothing on the page settles whether those rows belong
    to the component above them or to the table, so they are left unread and
    reported rather than filed under a component name the publisher did not
    give them.
    """
    parsed = _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf")
    labels = {charge.label.value for charge in parsed.charges}
    assert "Transmission* (all usage)" not in labels
    assert "Reliability Services* (all usage)" not in labels
    # Nothing is dropped: what no recognizer claimed is still carried verbatim.
    reported = " ".join(note.value for note in parsed.notes)
    assert "Transmission* (all usage)" in reported


def test_the_second_publisher_names_its_own_schedule() -> None:
    """Its schedule line sits in the body, over the title, not in the header band.

    What identifies it is that it runs: on `pge-b-1` a body sentence ends "...
    or agricultural schedule is" and matches the same shape, on one sheet only.
    """
    for document_id, filename, code in (
        ("pge-b-1", "ELEC_SCHEDS_B-1.pdf", "B-1"),
        ("pge-e-1", "ELEC_SCHEDS_E-1.pdf", "E-1"),
        ("pge-e-tou-c", "ELEC_SCHEDS_E-TOU-C.pdf", "E-TOU-C"),
    ):
        parsed = _parse(document_id, filename)
        assert parsed.identity.schedule_code is not None, document_id
        assert parsed.identity.schedule_code.value == code
        assert code in parsed.identity.schedule_code.provenance.snippet


def test_a_title_is_read_only_where_one_neighbour_runs_and_the_other_does_not() -> None:
    """Two of the second publisher's documents repeat both neighbours.

    They print a regulatory identifier above the schedule line and the title
    below it, and both are the same on every sheet, so nothing on the page says
    which of them names the schedule. The third prints two different cities
    above, so only one neighbour runs and that one is the title.
    """
    assert _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf").identity.title is not None
    assert _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf").identity.title.value == "SMALL GENERAL SERVICE"
    assert _parse("pge-e-1", "ELEC_SCHEDS_E-1.pdf").identity.title is None
    assert _parse("pge-e-tou-c", "ELEC_SCHEDS_E-TOU-C.pdf").identity.title is None


def test_the_second_publisher_states_no_resolution_and_none_is_invented() -> None:
    """Its footer prints the word Resolution with nothing after it.

    The schedule-level effective date is null for the same kind of reason: the
    sheets of one schedule take effect on different days, and this document
    states no single date for the schedule as a whole.
    """
    parsed = _parse("pge-e-1", "ELEC_SCHEDS_E-1.pdf")
    assert parsed.identity.resolution is None
    assert parsed.identity.adopted is None
    assert parsed.identity.effective is None
    # It does state a date per sheet, and those are read.
    assert {charge.effective_from.value for charge in parsed.charges} == {
        "June 1, 2026",
        "March 1, 2026",
    }
