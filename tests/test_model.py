"""A value must be impossible to emit without a citation."""

from __future__ import annotations

import pytest

from ca_tariff_parse.model import Cited, Provenance, ProvenanceError

from .conftest import provenance


def test_provenance_accepts_a_complete_citation() -> None:
    prov = Provenance(**provenance())  # type: ignore[arg-type]
    assert prov.locator == "synthetic-doc p.1 sheet SYN-1 II.A L3"


def test_provenance_renders_a_span_locator() -> None:
    prov = Provenance(**provenance(line=3, end_line=5))  # type: ignore[arg-type]
    assert prov.locator.endswith("II.A L3-5")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", ""),
        ("document_id", "   "),
        ("document_sha256", ""),
        ("document_sha256", "not-a-digest"),
        ("document_sha256", "A" * 64),
        ("page", 0),
        ("page", -1),
        ("page", True),
        ("sheet", "  "),
        ("section", ""),
        ("section", "II A"),
        ("section", "II..A"),
        ("line", 0),
        ("line", False),
        ("snippet", ""),
        ("snippet", "   "),
    ],
)
def test_provenance_rejects_an_incomplete_citation(field: str, value: object) -> None:
    with pytest.raises(ProvenanceError):
        Provenance(**provenance(**{field: value}))  # type: ignore[arg-type]


def test_provenance_rejects_a_backwards_span() -> None:
    with pytest.raises(ProvenanceError):
        Provenance(**provenance(line=9, end_line=4))  # type: ignore[arg-type]


def test_sheet_may_be_absent() -> None:
    prov = Provenance(**provenance(sheet=None))  # type: ignore[arg-type]
    assert prov.sheet is None
    assert "sheet" not in prov.locator


def test_cited_requires_a_provenance_instance() -> None:
    with pytest.raises(ProvenanceError, match="cannot be emitted"):
        Cited(value="0.1724", provenance=None)  # type: ignore[arg-type]


def test_cited_rejects_a_provenance_shaped_dict() -> None:
    with pytest.raises(ProvenanceError):
        Cited(value="0.1724", provenance=provenance())  # type: ignore[arg-type]


def test_cited_round_trips_to_json() -> None:
    cited = Cited(value="0.1724", provenance=Provenance(**provenance()))  # type: ignore[arg-type]
    payload = cited.to_json()
    assert payload["value"] == "0.1724"
    assert payload["provenance"]["document_sha256"] == "a" * 64  # type: ignore[index]
