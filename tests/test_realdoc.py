"""Parse the real published schedules, when they are present locally.

The published PDFs are not redistributed from this repository, so these tests
skip unless the documents have been fetched. What is committed for the
documents this parser structures is the golden output: the structured result of
parsing them, with every value carrying its citation. Comparing against the
golden file is how a change in the parser that would alter a published price
gets caught.

A second publisher's schedules are here too, and they parse at 0%. No golden
file is committed for those, because nothing is recognized and the whole
document text would sit in ``notes``. What is asserted for them is the refusal:
no charge, no window, no holiday, and every content line reported.

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
#: A second publisher, whose schedules this parser does not structure at all.
#: No golden file is committed for them: nothing is recognized, so the whole
#: document text would be carried verbatim in ``notes`` and committing that
#: would republish the document. What is asserted instead is the refusal.
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


@pytest.mark.parametrize(("document_id", "filename"), SECOND_PUBLISHER_CASES)
def test_a_second_publisher_is_refused_rather_than_guessed_at(
    document_id: str, filename: str
) -> None:
    """Nothing is emitted from a document whose structure is not understood.

    These schedules carry no numbered outline, so the segmenter finds one
    section and the recognizers have nothing to key on. The honest result is
    zero coverage and an unparsed report naming the whole document. What must
    never happen is a value: a price, a window or a holiday read out of a
    document the parser cannot follow would be a plausible looking number with
    a citation that makes it look checked.
    """
    path = _require(document_id, filename)
    entry = find(load_manifest(MANIFEST), document_id)
    parsed = parse_manifest_document(entry, path)

    assert parsed.charges == ()
    assert parsed.tou_windows == ()
    assert parsed.holidays == ()
    assert parsed.coverage.line_ratio == 0.0
    assert parsed.coverage.fully_recognized is False
    # Nothing is dropped: every content line is reported and carried verbatim.
    assert len(parsed.notes) == parsed.coverage.content_lines
    assert sum(item.line_count for item in parsed.unparsed) == parsed.coverage.content_lines


def test_no_citation_names_a_sheet_the_publisher_cancelled() -> None:
    """Each page prints its own sheet number over the one it supersedes.

    Reading the second of the two made every citation on the page point at a
    withdrawn document.
    """
    path = _require("pge-e-1", "ELEC_SCHEDS_E-1.pdf")
    entry = find(load_manifest(MANIFEST), "pge-e-1")
    parsed = parse_manifest_document(entry, path)
    sheets = [sheet.value for sheet in parsed.identity.sheets]
    assert sheets == ["61362-E", "61097-E", "61098-E", "61099-E", "61100-E", "61101-E", "61102-E"]
    assert "61247-E" not in sheets
    assert all(note.provenance.sheet in sheets for note in parsed.notes)
