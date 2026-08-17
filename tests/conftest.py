"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCES = REPO_ROOT / "sources"

COMPLETE = FIXTURES / "SYNTHETIC-example-schedule-complete.txt"
UNKNOWN = FIXTURES / "SYNTHETIC-example-schedule-unknown-section.txt"


@pytest.fixture
def complete_fixture() -> Path:
    return COMPLETE


@pytest.fixture
def unknown_fixture() -> Path:
    return UNKNOWN


def provenance(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "document_id": "synthetic-doc",
        "document_sha256": "a" * 64,
        "page": 1,
        "sheet": "SYN-1",
        "section": "II.A",
        "line": 3,
        "snippet": "Peak $/kWh $1.0000",
    }
    base.update(overrides)
    return base
