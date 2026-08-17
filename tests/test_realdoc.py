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
CASES = [("smud-r-tod", "1-R-TOD.pdf"), ("smud-r", "1-R.pdf")]


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


def test_real_coverage_is_reported_honestly() -> None:
    """The real document is only partly structured, and says so."""
    path = _require("smud-r-tod", "1-R-TOD.pdf")
    entry = find(load_manifest(MANIFEST), "smud-r-tod")
    parsed = parse_manifest_document(entry, path)
    assert parsed.coverage.fully_recognized is False
    assert parsed.unparsed
    assert 0.0 < parsed.coverage.line_ratio < 1.0
