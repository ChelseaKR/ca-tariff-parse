"""The published JSON Schema actually describes what `parse` emits.

`schemas/parsed-schedule-v1.schema.json` is the stable, documented shape of
`parsed-schedule/v1`. This module is what keeps it honest: every output this
suite produces, synthetic and real, is validated against it, so a field added
to the model without a matching schema update fails here rather than shipping
silently out of date.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ca_tariff_parse.extract import layout_from_path
from ca_tariff_parse.parser import parse_document, parse_manifest_document
from ca_tariff_parse.profiles import resolve
from ca_tariff_parse.sources import find, load_manifest

from .conftest import COMPLETE, GOLDEN, KEYWORD, REPO_ROOT, SOURCES, UNKNOWN

SCHEMA_PATH = REPO_ROOT / "schemas" / "parsed-schedule-v1.schema.json"
MANIFEST = REPO_ROOT / "sources" / "sources.toml"


@pytest.fixture(scope="module")
def schema() -> dict[str, object]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_is_itself_a_valid_draft_2020_12_schema(schema: dict[str, object]) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize(
    ("fixture", "profile_name"),
    [(COMPLETE, None), (UNKNOWN, None), (KEYWORD, "pge-tariff-book")],
)
def test_synthetic_output_matches_the_schema(
    schema: dict[str, object], fixture: Path, profile_name: str | None
) -> None:
    profile = resolve(profile_name)
    doc = layout_from_path(fixture, profile=profile)
    payload = parse_document(doc, profile=profile).to_json()
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_every_committed_golden_file_matches_the_schema(schema: dict[str, object]) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    golden_files = sorted(GOLDEN.glob("*.json"))
    assert golden_files, "expected at least one committed golden file"
    for path in golden_files:
        validator.validate(json.loads(path.read_text(encoding="utf-8")))


REALDOC_CASES = [
    ("smud-r-tod", "1-R-TOD.pdf"),
    ("smud-r", "1-R.pdf"),
    ("smud-ci-tod1", "CI-TOD1.pdf"),
    ("smud-ssr", "01_SSR.pdf"),
    ("pge-e-1", "ELEC_SCHEDS_E-1.pdf"),
    ("pge-e-tou-c", "ELEC_SCHEDS_E-TOU-C.pdf"),
    ("pge-b-1", "ELEC_SCHEDS_B-1.pdf"),
]


@pytest.mark.realdoc
@pytest.mark.parametrize(("document_id", "filename"), REALDOC_CASES)
def test_real_document_output_matches_the_schema(
    schema: dict[str, object], document_id: str, filename: str
) -> None:
    path = SOURCES / filename
    if not path.exists():
        pytest.skip(f"{document_id} ({filename}) not fetched; run `make fetch`")
    entry = find(load_manifest(MANIFEST), document_id)
    payload = parse_manifest_document(entry, path).to_json()
    jsonschema.Draft202012Validator(schema).validate(payload)
