"""`check` never answers "holds" for a property it did not test.

The three states are the point. A document with no charges satisfies "every
charge has a window" vacuously, and reporting that as a pass is the same
error as printing a suppressed cell as zero --- the defect this parser exists
to refuse, committed one step downstream by whoever computes over the parse.

So most of what is asserted here is not that a healthy parse is green. It is
that each *empty* shape reports `cannot be established`, that each *broken*
shape reports `does not hold` and names the records with citations, and that
`--require` treats "we could not tell" as unmet.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ca_tariff_parse.check import (
    CANNOT_BE_ESTABLISHED,
    DOES_NOT_HOLD,
    HOLDS,
    PROPERTY_IDS,
    check,
    to_json,
    to_text,
    unmet,
)
from ca_tariff_parse.parser import parse_path
from ca_tariff_parse.sources import load_manifest
from ca_tariff_parse.watch import project

from .conftest import COMPLETE, GOLDEN, REPO_ROOT

Json = dict[str, Any]

PINNED = [entry.schedule for entry in load_manifest(REPO_ROOT / "sources" / "sources.toml")]


@pytest.fixture(scope="module")
def parsed() -> Json:
    return parse_path(COMPLETE).to_json()


def golden(name: str) -> Json:
    return json.loads((GOLDEN / f"{name}.json").read_text(encoding="utf-8"))


def state(payload: Json, property_id: str, *, pinned: list[str] | None = None) -> str:
    return one(payload, property_id, pinned=pinned).state


def one(payload: Json, property_id: str, *, pinned: list[str] | None = None):
    found = [p for p in check(payload, pinned=pinned) if p.id == property_id]
    assert len(found) == 1, f"{property_id} is reported {len(found)} times, not once"
    return found[0]


# --------------------------------------------------------------------------
# Nothing to test is never a pass
# --------------------------------------------------------------------------


def test_a_document_with_no_charges_establishes_nothing() -> None:
    """`smud-ssr` prices nothing; every property must say so."""
    properties = check(golden("smud-ssr"), pinned=PINNED)
    assert [p.state for p in properties] == [CANNOT_BE_ESTABLISHED] * len(PROPERTY_IDS)
    closure = one(golden("smud-ssr"), "period-window-closure", pinned=PINNED)
    assert closure.state == CANNOT_BE_ESTABLISHED
    assert "states no charges" in closure.detail


def test_no_property_reports_holds_on_an_empty_payload() -> None:
    empty: Json = {
        "charges": [],
        "tou_windows": [],
        "cross_references": [],
        "source": {"document_id": "empty"},
    }
    for prop in check(empty, pinned=PINNED):
        assert prop.state == CANNOT_BE_ESTABLISHED, (
            f"{prop.id} answered {prop.state!r} over a payload with nothing in "
            "it; a vacuous truth is not a measurement"
        )


def test_charges_with_no_period_do_not_close_period_window_vacuously() -> None:
    """`smud-r` prices 30 charges and names no period on any of them."""
    closure = one(golden("smud-r"), "period-window-closure", pinned=PINNED)
    assert closure.state == CANNOT_BE_ESTABLISHED
    assert "none of the 30 charges" in closure.detail


def test_a_manifest_that_was_not_given_is_not_a_pass(parsed: Json) -> None:
    prop = one(parsed, "cross-reference-pinned", pinned=None)
    assert prop.state == CANNOT_BE_ESTABLISHED
    assert "no manifest was given" in prop.detail


# --------------------------------------------------------------------------
# period-window closure
# --------------------------------------------------------------------------


def test_removing_a_window_flips_closure_and_names_the_orphaned_charge() -> None:
    """The acceptance case from issue #54, run against a real document."""
    before = golden("smud-ci-tod1")
    assert state(before, "period-window-closure", pinned=PINNED) == HOLDS

    after = copy.deepcopy(before)
    period = after["tou_windows"][0]["period"]["value"]
    # Every window naming that period, not just the first: the document
    # defines the same period once per season, and dropping one leaves the
    # period still defined. A sabotage that does not land reads as a pass.
    after["tou_windows"] = [w for w in after["tou_windows"] if w["period"]["value"] != period]
    assert len(after["tou_windows"]) < len(before["tou_windows"]), "the edit removed nothing"
    assert all(w["period"]["value"] != period for w in after["tou_windows"]), (
        "the dropped period is still defined by another window, so this edit "
        "does not test what it claims to"
    )
    assert any((c.get("tou_period") or {}).get("value") == period for c in after["charges"]), (
        "no charge is priced for the dropped period, so nothing would be orphaned"
    )

    prop = one(after, "period-window-closure", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert repr(period) in prop.detail
    assert prop.involved, "the orphaned charges were not named"
    for item in prop.involved:
        assert item.cite is not None and item.cite["locator"], (
            "an orphaned charge was named without the citation it was read from"
        )


def test_priced_periods_with_no_windows_at_all_do_not_hold() -> None:
    payload = copy.deepcopy(golden("smud-ci-tod1"))
    payload["tou_windows"] = []
    prop = one(payload, "period-window-closure", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert "states no time-of-use windows at all" in prop.detail
    assert prop.involved


def test_a_real_document_that_closes_reports_holds() -> None:
    assert state(golden("smud-ci-tod1"), "period-window-closure", pinned=PINNED) == HOLDS


# --------------------------------------------------------------------------
# season vocabulary
# --------------------------------------------------------------------------


def test_two_vocabularies_are_undecidable_rather_than_a_finding() -> None:
    """Charges and windows name seasons differently in every real document."""
    prop = one(golden("smud-r-tod"), "season-vocabulary", pinned=PINNED)
    assert prop.state == CANNOT_BE_ESTABLISHED
    assert "share no season name at all" in prop.detail
    assert "Summer Season (June - September)" in prop.detail
    assert "Summer (Jun 1 - Sept 30)" in prop.detail


def test_one_shared_vocabulary_with_a_gap_does_not_hold() -> None:
    payload = copy.deepcopy(golden("smud-r-tod"))
    # Give one window the charges' own name for a season. The vocabularies now
    # overlap, so a season with no window is a real gap rather than a second
    # naming system.
    payload["tou_windows"][0]["season"]["value"] = "Summer Season (June - September)"
    prop = one(payload, "season-vocabulary", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert "Non-Summer Season (October - May)" in prop.detail


def test_one_vocabulary_with_no_gap_holds() -> None:
    payload = copy.deepcopy(golden("smud-r-tod"))
    charge_seasons = sorted({c["season"]["value"] for c in payload["charges"] if c.get("season")})
    for index, window in enumerate(payload["tou_windows"]):
        window["season"]["value"] = charge_seasons[index % len(charge_seasons)]
    assert state(payload, "season-vocabulary", pinned=PINNED) == HOLDS


# --------------------------------------------------------------------------
# window enumerability
# --------------------------------------------------------------------------


def test_a_residual_window_is_undecidable_not_a_failure(parsed: Json) -> None:
    payload = copy.deepcopy(parsed)
    # Give every non-residual window a clock, leaving only the residual ones
    # to decide the answer.
    for window in payload["tou_windows"]:
        if not window["residual"]:
            window.setdefault("start", {"value": "12:00 p.m.", "provenance": {}})
            window.setdefault("end", {"value": "6:00 p.m.", "provenance": {}})
    prop = one(payload, "window-enumerability", pinned=PINNED)
    assert prop.state == CANNOT_BE_ESTABLISHED
    assert "by exclusion" in prop.detail
    assert prop.involved


def test_a_clockless_non_residual_window_does_not_hold(parsed: Json) -> None:
    prop = one(parsed, "window-enumerability", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert "state no start and end time" in prop.detail
    assert prop.involved
    assert all(item.cite for item in prop.involved)


def test_windows_that_all_state_a_clock_and_none_residual_hold(parsed: Json) -> None:
    payload = copy.deepcopy(parsed)
    for window in payload["tou_windows"]:
        window["residual"] = False
        window["start"] = {"value": "8:00 a.m.", "provenance": {}}
        window["end"] = {"value": "10:00 p.m.", "provenance": {}}
    assert state(payload, "window-enumerability", pinned=PINNED) == HOLDS


# --------------------------------------------------------------------------
# unit uniformity
# --------------------------------------------------------------------------


def test_a_line_priced_once_cannot_establish_uniformity() -> None:
    payload = copy.deepcopy(golden("smud-r-tod"))
    seen: set[tuple[str, ...]] = set()
    unique = []
    for charge in payload["charges"]:
        key = tuple(
            (charge.get(name) or {}).get("value") or ""
            for name in ("label", "rate_category", "season", "tou_period", "applies_to", "group")
        )
        if key not in seen:
            seen.add(key)
            unique.append(charge)
    payload["charges"] = unique
    prop = one(payload, "unit-uniformity", pinned=PINNED)
    assert prop.state == CANNOT_BE_ESTABLISHED
    assert "is priced once" in prop.detail


def test_a_unit_that_moves_between_effective_dates_does_not_hold(parsed: Json) -> None:
    payload = copy.deepcopy(parsed)
    repriced = [charge for charge in payload["charges"] if charge["label"]["value"] == "Peak $/kWh"]
    assert len(repriced) > 1, "the fixture no longer prices this line twice"
    repriced[-1]["price"]["unit"]["value"] = "$/kW"
    assert repriced[-1]["price"]["unit"]["value"] == "$/kW", "the edit did not land"

    prop = one(payload, "unit-uniformity", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert "not in the same terms" in prop.detail
    assert len(prop.involved) == len(repriced)


def test_the_fixture_keeps_one_unit_per_line(parsed: Json) -> None:
    assert state(parsed, "unit-uniformity", pinned=PINNED) == HOLDS


# --------------------------------------------------------------------------
# cross references
# --------------------------------------------------------------------------


def test_a_reference_to_an_unpinned_schedule_does_not_hold(parsed: Json) -> None:
    prop = one(parsed, "cross-reference-pinned", pinned=PINNED)
    assert prop.state == DOES_NOT_HOLD
    assert "SYN-HGA" in prop.detail
    assert prop.involved and all(item.cite for item in prop.involved)


def test_every_reference_pinned_holds(parsed: Json) -> None:
    targets = [ref["target"]["value"] for ref in parsed["cross_references"]]
    assert state(parsed, "cross-reference-pinned", pinned=PINNED + targets) == HOLDS


def test_an_empty_manifest_establishes_nothing(parsed: Json) -> None:
    prop = one(parsed, "cross-reference-pinned", pinned=[])
    assert prop.state == CANNOT_BE_ESTABLISHED
    assert "pins no schedule codes" in prop.detail


# --------------------------------------------------------------------------
# --require, determinism, and the baseline projection
# --------------------------------------------------------------------------


def test_require_treats_undecidable_as_unmet() -> None:
    properties = check(golden("smud-ssr"), pinned=PINNED)
    assert all(p.state == CANNOT_BE_ESTABLISHED for p in properties)
    failed = unmet(properties, ["period-window-closure"])
    assert [p.id for p in failed] == ["period-window-closure"]


def test_require_is_satisfied_only_by_holds() -> None:
    properties = check(golden("smud-ci-tod1"), pinned=PINNED)
    assert unmet(properties, ["period-window-closure"]) == []
    assert [p.id for p in unmet(properties, ["window-enumerability"])] == ["window-enumerability"]


def test_the_same_payload_reports_byte_identical_output(parsed: Json) -> None:
    first = to_json("doc", check(parsed, pinned=PINNED))
    second = to_json("doc", check(copy.deepcopy(parsed), pinned=PINNED))
    assert first == second
    assert to_text("doc", check(parsed, pinned=PINNED)) == to_text(
        "doc", check(copy.deepcopy(parsed), pinned=PINNED)
    )


def test_the_baseline_projection_changes_no_result(parsed: Json) -> None:
    """A baseline drops `notes` and the unparsed samples; no property reads them."""
    full = check(parsed, pinned=PINNED)
    projected = check(project(copy.deepcopy(parsed)), pinned=PINNED)
    assert [(p.id, p.state, p.detail) for p in full] == [
        (p.id, p.state, p.detail) for p in projected
    ]


def test_every_property_id_is_reported_exactly_once(parsed: Json) -> None:
    reported = [p.id for p in check(parsed, pinned=PINNED)]
    assert reported == list(PROPERTY_IDS)


def test_the_json_report_carries_the_states_and_the_citations(parsed: Json) -> None:
    payload = json.loads(to_json("doc", check(parsed, pinned=PINNED)))
    assert payload["schema"] == "ca-tariff-parse/check/v1"
    assert payload["document_id"] == "doc"
    assert sum(payload["summary"].values()) == len(PROPERTY_IDS)
    involved = [
        item
        for prop in payload["properties"]
        for item in prop["involved"]
        if prop["state"] == DOES_NOT_HOLD
    ]
    assert involved, "no failing property named a record"
    assert all(item["cite"] and item["cite"]["locator"] for item in involved)


def test_the_text_report_says_what_undecidable_means(parsed: Json) -> None:
    text = to_text("doc", check(parsed, pinned=PINNED))
    assert "It is not a pass, and it is not a finding." in text
    for property_id in PROPERTY_IDS:
        assert property_id in text


def test_every_golden_document_reports_every_property() -> None:
    for name in ("smud-r", "smud-r-tod", "smud-ci-tod1", "smud-ssr"):
        properties = check(golden(name), pinned=PINNED)
        assert [p.id for p in properties] == list(PROPERTY_IDS), name
        assert all(p.detail for p in properties), f"{name} left a property unexplained"


def test_a_payload_whose_arrays_are_not_arrays_is_refused() -> None:
    from ca_tariff_parse.check import CheckError

    with pytest.raises(CheckError, match="not a list of records"):
        check({"charges": {"label": "not a list"}}, pinned=PINNED)


def test_the_golden_files_are_read_from_where_the_suite_keeps_them() -> None:
    assert (GOLDEN / "smud-ssr.json").is_file()
    assert isinstance(REPO_ROOT, Path)
