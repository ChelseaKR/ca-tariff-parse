"""Reconciling a user-supplied URDB record against a cited parse.

The three states this module has to keep apart are the whole point of it:
a value the document states, a value it states differently, and a value it
does not state at all. The tests below pin each, and pin the boundary that
matters most --- that a parse with nothing to compare reports silence rather
than agreement.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ca_tariff_parse.cli import main
from ca_tariff_parse.parser import parse_path
from ca_tariff_parse.reconcile import (
    CONFIRMS,
    CONTRADICTS,
    DEMAND,
    ENERGY,
    MONTHLY,
    NO_STATEMENT,
    NOT_COMPARABLE,
    ReconcileError,
    as_date,
    family,
    read_record,
    reconcile,
    render_json,
    render_text,
)

from .conftest import COMPLETE, REPO_ROOT

RECORD = Path(__file__).parent / "fixtures" / "SYNTHETIC-urdb-record.json"

#: The priced fields of the fixture record, as `reconcile` names them.
PRICED = (
    "fixedchargefirstmeter",
    "energyratestructure[0][0].rate",
    "demandratestructure[0][0].rate",
)

#: Every field of the fixture record that the mapping actually compares.
MAPPED = ("startdate", *PRICED)


@pytest.fixture(scope="module")
def parsed() -> dict[str, Any]:
    """The synthetic fixture, parsed once."""
    return parse_path(COMPLETE, document_id="synthetic").to_json()


@pytest.fixture
def record() -> dict[str, Any]:
    return read_record(RECORD.read_text(encoding="utf-8"))


def verdicts(result: Any) -> dict[str, str]:
    return {finding.field: finding.verdict for finding in result.findings}


# --------------------------------------------------------------------------
# The three states
# --------------------------------------------------------------------------


def test_a_matching_record_confirms_every_mapped_field_with_a_citation(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    result = reconcile(parsed, record)
    found = verdicts(result)
    for field in MAPPED:
        assert found[field] == CONFIRMS, f"{field} came back {found[field]}"
    # A confirmation with no citation behind it would be this tool asserting
    # agreement it cannot show, which is the failure mode the project exists
    # to avoid.
    for finding in result.findings:
        if finding.verdict != CONFIRMS:
            continue
        assert finding.evidence, f"{finding.field} confirmed nothing citable"
        for item in finding.evidence:
            assert item.cite is not None
            assert item.cite["locator"]


def test_one_altered_price_is_exactly_one_contradiction(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    altered = copy.deepcopy(record)
    altered["energyratestructure"][0][0]["rate"] = read_record('{"r": 9.9}')["r"]
    result = reconcile(parsed, altered)

    contradicted = result.contradicted()
    assert len(contradicted) == 1
    finding = contradicted[0]
    assert finding.field == "energyratestructure[0][0].rate"
    # Both values, and the page the parse read its own from.
    assert finding.stated == "9.9"
    assert "1.1000" in finding.detail
    assert finding.evidence
    assert finding.evidence[0].cite is not None
    assert finding.evidence[0].cite["locator"] == "synthetic p.2 sheet SYN-1-2 II.A L11"
    # Nothing else moved.
    assert verdicts(result)["fixedchargefirstmeter"] == CONFIRMS


def test_a_parse_with_no_charges_states_nothing_rather_than_agreeing(
    record: dict[str, Any],
) -> None:
    """`smud-ssr` emits zero charges (ADR 0011). Silence is not a verdict."""
    baseline = json.loads(
        (REPO_ROOT / "data" / "parsed" / "smud-ssr.json").read_text(encoding="utf-8")
    )
    assert baseline["charges"] == [], "this test needs a parse that emitted no charges"

    result = reconcile(baseline, record)
    priced = [finding for finding in result.findings if finding.field in PRICED]
    assert len(priced) == len(PRICED), "the record has to state every priced field"
    for finding in priced:
        assert finding.verdict == NO_STATEMENT, f"{finding.field} came back {finding.verdict}"

    # The date is a separate matter and is allowed to disagree: this document
    # states June 1 2026 and the record states May 1 2026. That is a real
    # finding about the record, not about the absent prices.
    assert {f.field for f in result.contradicted()} == {"startdate"}


def test_a_priced_field_is_never_confirmed_by_an_empty_pool(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    """A record naming a unit family the parse never states says so."""
    daily = copy.deepcopy(record)
    daily["fixedchargeunits"] = "$/day"
    result = reconcile(parsed, daily)
    assert verdicts(result)["fixedchargefirstmeter"] == NO_STATEMENT


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_an_adjusted_tier_is_refused_rather_than_compared(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    adjusted = copy.deepcopy(record)
    adjusted["energyratestructure"][0][0]["adj"] = read_record('{"a": 0.02}')["a"]
    result = reconcile(parsed, adjusted)
    finding = next(f for f in result.findings if f.field == "energyratestructure[0][0].rate")
    assert finding.verdict == NOT_COMPARABLE
    assert "0.02" in finding.detail


def test_a_zero_adjustment_does_not_block_the_comparison(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    zeroed = copy.deepcopy(record)
    zeroed["energyratestructure"][0][0]["adj"] = read_record('{"a": 0}')["a"]
    result = reconcile(parsed, zeroed)
    assert verdicts(result)["energyratestructure[0][0].rate"] == CONFIRMS


def test_a_credit_is_not_matched_against_a_rate(parsed: dict[str, Any]) -> None:
    """The fixture prices a -0.0100 $/kWh vehicle credit. It is not a rate."""
    printed = [
        charge["price"]["amount"]["value"]
        for charge in parsed["charges"]
        if charge["kind"] == "credit"
    ]
    assert printed == ["-0.0100"], "this test needs the fixture's credit"

    record = read_record(
        json.dumps(
            {
                "startdate": 1769904000,
                "energyratestructure": [[{"rate": -0.01}]],
            }
        )
    )
    result = reconcile(parsed, record)
    assert verdicts(result)["energyratestructure[0][0].rate"] != CONFIRMS


def test_a_date_the_parse_cannot_read_is_not_a_contradiction(
    record: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "source": {"document_id": "unreadable-dates"},
        "identity": {
            "effective": {
                "value": "the first Tuesday after the Commission acts",
                "provenance": {"locator": "unreadable-dates p.1 sheet A front L1"},
            }
        },
        "charges": [],
    }
    result = reconcile(payload, record)
    assert verdicts(result)["startdate"] == NO_STATEMENT
    assert result.contradicted() == ()


def test_a_date_the_document_disagrees_with_is_a_contradiction(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    moved = copy.deepcopy(record)
    moved["startdate"] = read_record('{"d": 1500000000}')["d"]
    result = reconcile(parsed, moved)
    assert verdicts(result)["startdate"] == CONTRADICTS


def test_a_date_no_charge_carries_widens_rather_than_silencing(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    """Narrowing to an empty set would report silence where there is a value."""
    # Every date the fixture's charges carry: May 1 2026, January 1 2027 and
    # February 1 2026 (the vehicle credit). March 1 2026 is none of them.
    moved = copy.deepcopy(record)
    moved["startdate"] = read_record('{"d": 1772323200}')["d"]
    result = reconcile(parsed, moved)

    assert "compared against every charge" in result.date_note
    # 11.00 is only stated on May 1 2026, and it is still found.
    assert verdicts(result)["fixedchargefirstmeter"] == CONFIRMS


# --------------------------------------------------------------------------
# Completeness over the record
# --------------------------------------------------------------------------


def test_every_key_in_the_record_is_reported(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    """A field nobody mapped is visible, never silently dropped."""
    extended = copy.deepcopy(record)
    extended["somefieldinventedlater"] = 7
    result = reconcile(parsed, extended)
    reported = {finding.field.split("[")[0] for finding in result.findings}
    for key in extended:
        assert key in reported, f"{key} was dropped from the report"
    unmapped = next(f for f in result.findings if f.field == "somefieldinventedlater")
    assert unmapped.verdict == NOT_COMPARABLE
    assert unmapped.detail


def test_the_report_is_deterministic(parsed: dict[str, Any], record: dict[str, Any]) -> None:
    first = render_text(reconcile(parsed, record))
    second = render_text(reconcile(parsed, read_record(RECORD.read_text(encoding="utf-8"))))
    assert first == second
    assert render_json(reconcile(parsed, record)) == render_json(reconcile(parsed, record))


def test_json_output_carries_the_schema_and_the_summary(
    parsed: dict[str, Any], record: dict[str, Any]
) -> None:
    payload = json.loads(render_json(reconcile(parsed, record)))
    assert payload["schema"] == "ca-tariff-parse/reconcile/v1"
    assert payload["summary"][CONFIRMS] == len(MAPPED)
    assert payload["document_id"] == "synthetic"
    assert payload["record_label"] == "SYNTHETICurdbrecord0000000"


# --------------------------------------------------------------------------
# Reading the record
# --------------------------------------------------------------------------


def test_an_items_envelope_holding_one_record_is_read() -> None:
    wrapped = json.dumps({"items": [{"label": "x", "startdate": 1777593600}]})
    assert read_record(wrapped)["label"] == "x"


@pytest.mark.parametrize(
    "text",
    [
        "not json at all",
        "[1, 2, 3]",
        '{"items": [{"a": 1}, {"b": 2}]}',
        '{"items": "not a list"}',
    ],
)
def test_a_record_that_cannot_be_read_is_refused(text: str) -> None:
    with pytest.raises(ReconcileError):
        read_record(text)


def test_numbers_are_read_exactly_not_as_floats() -> None:
    """0.1 + 0.2 problems have no place in a tariff audit."""
    read = read_record('{"rate": 0.30000000000000004, "other": 0.3}')
    assert str(read["rate"]) == "0.30000000000000004"
    assert str(read["other"]) == "0.3"
    assert read["rate"] != read["other"]


# --------------------------------------------------------------------------
# Units and dates
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("$/kWh", ENERGY),
        ("per kWh", ENERGY),
        ("$ per kWh", ENERGY),
        # kWh is tested before kW; reading this as a demand charge would
        # compare an energy price against the wrong set of amounts.
        ("$/kWh per month", ENERGY),
        ("$ per monthly max kW", DEMAND),
        ("$/kW of Contract Capacity per month", DEMAND),
        ("per metered kW/month assessed from 2:00 p.m. to 11:00 p.m. only", DEMAND),
        ("per month per meter", MONTHLY),
        ("$/month", MONTHLY),
        ("$ per customer per day", "per day"),
        ("per excess KVAR", None),
        ("", None),
        (None, None),
    ],
)
def test_unit_families(unit: str | None, expected: str | None) -> None:
    assert family(unit) == expected


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("May 1, 2026", "2026-05-01"),
        ("January 1, 2027", "2027-01-01"),
        ("Jan 1, 2027", "2027-01-01"),
        ("2026-05-01", "2026-05-01"),
        ("5/1/2026", "2026-05-01"),
    ],
)
def test_dates_the_publishers_print(text: str, iso: str) -> None:
    read = as_date(text)
    assert read is not None
    assert read.isoformat() == iso


def test_a_date_that_is_not_a_date_reads_as_none() -> None:
    assert as_date("upon Commission approval") is None
    assert as_date(None) is None


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def _write_parse(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "parsed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_exits_zero_when_nothing_contradicts(tmp_path: Path, parsed: dict[str, Any]) -> None:
    path = _write_parse(tmp_path, parsed)
    out = tmp_path / "report.txt"
    assert main(["reconcile", str(path), str(RECORD), "-o", str(out)]) == 0
    assert "CONFIRMS  fixedchargefirstmeter" in out.read_text(encoding="utf-8")


def test_cli_exits_three_when_something_contradicts(tmp_path: Path, parsed: dict[str, Any]) -> None:
    altered_path = tmp_path / "record.json"
    altered_path.write_text(
        RECORD.read_text(encoding="utf-8").replace('"rate": 1.1,', '"rate": 9.9,'),
        encoding="utf-8",
    )
    assert '"rate": 9.9' in altered_path.read_text(encoding="utf-8")
    path = _write_parse(tmp_path, parsed)
    report = tmp_path / "r.json"
    assert main(["reconcile", str(path), str(altered_path), "--json", "-o", str(report)]) == 3
    assert json.loads(report.read_text(encoding="utf-8"))["summary"][CONTRADICTS] == 1


def test_cli_exits_two_when_the_record_cannot_be_read(
    tmp_path: Path, parsed: dict[str, Any]
) -> None:
    path = _write_parse(tmp_path, parsed)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert main(["reconcile", str(path), str(broken)]) == 2
    assert main(["reconcile", str(path), str(tmp_path / "absent.json")]) == 2


# --------------------------------------------------------------------------
# Shapes the record can arrive in, and what the report says about each
# --------------------------------------------------------------------------


def test_a_malformed_rate_structure_is_refused_with_a_reason(parsed: dict[str, Any]) -> None:
    record = read_record(
        json.dumps(
            {
                "energyratestructure": "not a list",
                "demandratestructure": ["not a list of tiers", [{"rate": 1.234}], ["not a tier"]],
            }
        )
    )
    result = reconcile(parsed, record)
    found = verdicts(result)
    assert found["energyratestructure"] == NOT_COMPARABLE
    assert found["demandratestructure[0]"] == NOT_COMPARABLE
    assert found["demandratestructure[2][0]"] == NOT_COMPARABLE
    # The one well-formed tier in that mess is still compared.
    assert found["demandratestructure[1][0].rate"] == CONFIRMS


def test_a_tier_with_no_numeric_rate_is_refused(parsed: dict[str, Any]) -> None:
    record = read_record(json.dumps({"energyratestructure": [[{"unit": "kWh"}]]}))
    finding = next(
        f for f in reconcile(parsed, record).findings if f.field == "energyratestructure[0][0].rate"
    )
    assert finding.verdict == NOT_COMPARABLE
    assert finding.stated is None


def test_a_fixed_charge_with_no_placeable_unit_is_refused(parsed: dict[str, Any]) -> None:
    record = read_record(
        json.dumps({"fixedchargefirstmeter": 11.0, "fixedchargeunits": "$/furlong"})
    )
    finding = next(
        f for f in reconcile(parsed, record).findings if f.field == "fixedchargefirstmeter"
    )
    assert finding.verdict == NOT_COMPARABLE
    assert "furlong" in finding.detail


def test_a_record_with_no_start_date_says_so(parsed: dict[str, Any]) -> None:
    record = read_record(json.dumps({"fixedchargefirstmeter": 11.0, "fixedchargeunits": "$/month"}))
    result = reconcile(parsed, record)
    assert verdicts(result)["startdate"] == NO_STATEMENT
    assert "no readable start date" in result.date_note


def test_a_start_date_that_is_not_a_date_is_refused(parsed: dict[str, Any]) -> None:
    record = read_record(json.dumps({"startdate": "whenever the Commission says"}))
    finding = next(f for f in reconcile(parsed, record).findings if f.field == "startdate")
    assert finding.verdict == NOT_COMPARABLE


def test_the_report_names_prices_the_record_does_not_carry(parsed: dict[str, Any]) -> None:
    """A note, not a verdict: a URDB entry need not carry every printed price."""
    record = read_record(json.dumps({"energyratestructure": [[{"rate": 1.1}]]}))
    result = reconcile(parsed, record)
    joined = " ".join(result.notes)
    assert "the record does not carry" in joined
    # 1.2000 and 0.5000 are printed on other effective dates and are not in the record.
    assert "1.2000" in joined
    assert all("does not carry" not in finding.detail for finding in result.findings)


def test_a_charges_key_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(ReconcileError):
        reconcile({"charges": {"not": "a list"}}, {})


def test_a_parse_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ReconcileError):
        reconcile("not a parse", {})  # type: ignore[arg-type]
