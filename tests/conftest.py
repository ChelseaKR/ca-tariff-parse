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
#: A fixture in the second publisher's shape: a keyword column outline,
#: negatives in accounting brackets and a supersession header. Used to exercise
#: the document profile offline, without redistributing anyone's document.
KEYWORD = FIXTURES / "SYNTHETIC-example-keyword-schedule.txt"


@pytest.fixture
def complete_fixture() -> Path:
    return COMPLETE


@pytest.fixture
def unknown_fixture() -> Path:
    return UNKNOWN


@pytest.fixture
def keyword_fixture() -> Path:
    return KEYWORD


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


#: The cited string fields a charge can carry, beside its price.
CHARGE_CITED_FIELDS = (
    "label",
    "effective_from",
    "rate_category",
    "season",
    "tou_period",
    "applies_to",
    "group",
)


def _squash(text: str) -> str:
    return "".join(text.split())


def unquoted_values(parsed: object) -> list[tuple[str, str, str]]:
    """Every cited value that does not appear on the line its citation names.

    A citation exists so a reader can check a value against the document. One
    whose snippet does not contain what it cites cannot be checked without
    finding the page by hand, and a value quoted from the wrong line looks
    exactly like a value quoted from the right one.

    Returns ``(field, value, snippet)`` for each. The caller decides which are
    defects: a credit's unit is composed from the row's own "/kWh" tail rather
    than quoted, and is the one composition in the parser today.
    """
    found: list[tuple[str, str, str]] = []
    for charge in parsed.charges:  # type: ignore[attr-defined]
        printed = charge.price.amount.value.lstrip("-")
        amount = charge.price.amount
        if not any(
            form in _squash(amount.provenance.snippet)
            for form in (f"${printed}", f"(${printed})", f"-${printed}")
        ):
            found.append(("price.amount", amount.value, amount.provenance.snippet))
        unit = charge.price.unit
        if _squash(unit.value) not in _squash(unit.provenance.snippet):
            found.append((f"price.unit:{charge.kind}", unit.value, unit.provenance.snippet))
        for name in CHARGE_CITED_FIELDS:
            cited = getattr(charge, name)
            if cited is not None and _squash(cited.value) not in _squash(cited.provenance.snippet):
                found.append((name, cited.value, cited.provenance.snippet))
    return found


def cited_value_count(parsed: object) -> int:
    """How many cited values :func:`unquoted_values` actually looked at."""
    total = 0
    for charge in parsed.charges:  # type: ignore[attr-defined]
        total += 2  # the amount and its unit
        total += sum(1 for name in CHARGE_CITED_FIELDS if getattr(charge, name) is not None)
    return total
