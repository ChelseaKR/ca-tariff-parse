"""The provenance audit is the second, independent guard."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from ca_tariff_parse.audit import UncitedValueError, assert_fully_cited
from ca_tariff_parse.parser import parse_path


@pytest.fixture
def payload(complete_fixture: Path) -> dict[str, object]:
    return parse_path(complete_fixture).to_json()


def test_a_real_parse_passes_the_audit(payload: dict[str, object]) -> None:
    assert_fully_cited(payload)


def test_a_bare_scalar_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["smuggled_price"] = 0.1724  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="bare float"):
        assert_fully_cited(broken)


def test_a_bare_string_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["label"] = "Peak $/kWh"  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="bare str"):
        assert_fully_cited(broken)


def test_a_citation_with_an_empty_field_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["price"]["amount"]["provenance"]["snippet"] = ""  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="snippet"):
        assert_fully_cited(broken)


def test_a_citation_with_a_missing_digest_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    del broken["charges"][0]["price"]["amount"]["provenance"]["document_sha256"]  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="document_sha256"):
        assert_fully_cited(broken)


def test_a_value_outside_the_controlled_vocabulary_is_rejected(
    payload: dict[str, object],
) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["kind"] = "surge_pricing"  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="controlled vocabulary"):
        assert_fully_cited(broken)


def test_a_non_boolean_residual_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["tou_windows"][0]["residual"] = "maybe"  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="must be a bool"):
        assert_fully_cited(broken)


def test_a_currency_change_is_rejected(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["price"]["currency"] = "EUR"  # type: ignore[index]
    with pytest.raises(UncitedValueError, match="controlled vocabulary"):
        assert_fully_cited(broken)


def test_structural_metadata_blocks_are_not_required_to_be_cited(
    payload: dict[str, object],
) -> None:
    """source, coverage and unparsed describe the parse, not the tariff."""
    assert isinstance(payload["source"], dict)
    assert isinstance(payload["coverage"], dict)
    assert_fully_cited(payload)


def test_null_fields_are_allowed(payload: dict[str, object]) -> None:
    broken = copy.deepcopy(payload)
    broken["charges"][0]["rate_category"] = None  # type: ignore[index]
    assert_fully_cited(broken)
