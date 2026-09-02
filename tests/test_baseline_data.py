"""The committed baselines are the reviewed parse of every pinned document.

`data/parsed/` is what the watch compares a revision against. A pinned document
with no baseline cannot be watched; a baseline that carries `notes` republishes
prose this repository deliberately does not; a baseline whose digest is not the
manifest's describes bytes nobody pinned. The realdoc test is the one that
matters most and skips where the documents are absent: with them present, the
committed file has to be byte for byte what the current parser writes.
"""

from __future__ import annotations

import json

import pytest

from ca_tariff_parse.parser import parse_manifest_document
from ca_tariff_parse.sources import DEFAULT_MANIFEST, load_manifest, local_state
from ca_tariff_parse.watch import BASELINE_SCHEMA, baseline_path, dump, project

from .conftest import REPO_ROOT, SOURCES

BASELINES = REPO_ROOT / "data" / "parsed"
ENTRIES = load_manifest(REPO_ROOT / DEFAULT_MANIFEST)


@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.id for entry in ENTRIES])
def test_every_pinned_document_has_an_honest_baseline(entry) -> None:
    path = baseline_path(BASELINES, entry.id)
    assert path.is_file(), f"{entry.id} has no baseline; run `make watch-baseline`"
    baseline = json.loads(path.read_text(encoding="utf-8"))
    assert baseline["schema"] == BASELINE_SCHEMA
    assert baseline["source"]["document_id"] == entry.id
    assert baseline["source"]["sha256"].lower() == entry.sha256.lower()
    assert baseline["source"]["byte_size"] == entry.bytes
    assert "notes" not in baseline
    assert all("sample" not in item for item in baseline["unparsed"])
    assert baseline["omitted"]["fields"] == ["notes", "unparsed[].sample"]


@pytest.mark.realdoc
@pytest.mark.parametrize("entry", ENTRIES, ids=[entry.id for entry in ENTRIES])
def test_the_committed_baseline_is_the_current_parse(entry) -> None:
    if local_state(entry, SOURCES) != "present":
        pytest.skip(f"{entry.id} is not fetched; run `make fetch`")
    parsed = parse_manifest_document(entry, entry.path(SOURCES))
    expected = dump(project(parsed.to_json()))
    actual = baseline_path(BASELINES, entry.id).read_text(encoding="utf-8")
    assert actual == expected, f"{entry.id}: baseline is stale; run `make watch-baseline`"
