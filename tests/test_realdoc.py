"""Parse the real published schedules, when they are present locally.

The published PDFs are not redistributed from this repository, so these tests
skip unless the documents have been fetched. What is committed is the golden
output: the structured result of parsing them, with every value carrying its
citation. Comparing against the golden file is how a change in the parser that
would alter a published price gets caught.

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
