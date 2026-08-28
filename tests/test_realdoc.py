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

from .conftest import GOLDEN, REPO_ROOT, SOURCES

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
    matching = [charge for charge in parsed.charges if charge.label.value == label]
    assert len(matching) == 1, f"{label} appears {len(matching)} times in {document_id}"
    charge = matching[0]
    assert charge.price.amount.value == amount
    assert charge.price.unit.value == unit
    assert charge.effective_from.value == effective
    assert charge.group is not None
    assert charge.group.value == group
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


def test_a_two_column_sheet_yields_no_price_at_all() -> None:
    """B-1 prices two rate options side by side and names neither in the block.

    Every price on those sheets is refused rather than attributed to a column
    the block does not state. The eighteen it does emit all come from the
    single column table on the billing sheet.
    """
    parsed = _parse("pge-b-1", "ELEC_SCHEDS_B-1.pdf")
    assert {charge.price.amount.provenance.page for charge in parsed.charges} == {6}
    assert all(charge.price.unit.value == "per kWh" for charge in parsed.charges)


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


#: What each of the second publisher's schedules calls itself, quoted from the
#: line every one of its sheets prints under the sheet number.
SECOND_PUBLISHER_IDENTITY = [
    ("pge-e-1", "ELEC_SCHEDS_E-1.pdf", "E-1", "RESIDENTIAL SERVICES"),
    (
        "pge-e-tou-c",
        "ELEC_SCHEDS_E-TOU-C.pdf",
        "E-TOU-C",
        "RESIDENTIAL TIME-OF-USE (PEAK PRICING 4 - 9 p.m. EVERY DAY)",
    ),
    ("pge-b-1", "ELEC_SCHEDS_B-1.pdf", "B-1", "SMALL GENERAL SERVICE"),
]


@pytest.mark.parametrize(("document_id", "filename", "code", "title"), SECOND_PUBLISHER_IDENTITY)
def test_the_second_publisher_names_its_own_schedule(
    document_id: str, filename: str, code: str, title: str
) -> None:
    """Both halves are quotes from the running head, not from the manifest.

    The code the manifest records for each of these is the same string, which
    is exactly why it is worth asserting that the parser reads it off the page:
    a code copied from the manifest would look identical and cite nothing.
    """
    parsed = _parse(document_id, filename)
    identity = parsed.identity
    assert identity.schedule_code is not None
    assert identity.schedule_code.value == code
    assert identity.schedule_code.value in identity.schedule_code.provenance.snippet
    assert identity.title is not None
    assert identity.title.value == title
    assert identity.title.value in identity.title.provenance.snippet


@pytest.mark.parametrize(("document_id", "filename"), SECOND_PUBLISHER_CASES)
def test_the_second_publisher_states_no_resolution_and_none_is_invented(
    document_id: str, filename: str
) -> None:
    """These sheets print "Resolution" and "Decision" as labels with no value.

    The schedule-wide effective date stays null for a different reason: this
    publisher files sheet by sheet, so the sheets of one schedule take effect
    on different days and there is no one date the document states about
    itself. Each price carries its own sheet's date instead.
    """
    parsed = _parse(document_id, filename)
    assert parsed.identity.resolution is None
    assert parsed.identity.adopted is None
    assert parsed.identity.effective is None
