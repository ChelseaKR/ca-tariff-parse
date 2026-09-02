"""The diff reports values that changed, with both citations, and nothing that only moved."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

import pytest

from ca_tariff_parse.diff import ADDED, CHANGED, REMOVED, DiffError, schedule_diff
from ca_tariff_parse.parser import parse_path

from .conftest import COMPLETE

Json = dict[str, Any]


@pytest.fixture(scope="module")
def parsed() -> Json:
    return parse_path(COMPLETE).to_json()


def _charge(payload: Json, where: Callable[[Json], bool]) -> Json:
    matches = [charge for charge in payload["charges"] if where(charge)]
    assert len(matches) == 1, "the fixture should state this charge exactly once"
    return matches[0]


def _peak_may(charge: Json) -> bool:
    return (
        charge["label"]["value"] == "Peak $/kWh"
        and charge["effective_from"]["value"] == "May 1, 2026"
    )


def test_two_parses_of_the_same_bytes_have_no_changes(parsed: Json) -> None:
    delta = schedule_diff(parsed, copy.deepcopy(parsed))
    assert delta.changes == ()
    assert delta.summary() == {ADDED: 0, REMOVED: 0, CHANGED: 0}
    assert not delta.across_parser_versions


def test_a_changed_amount_is_reported_with_both_citations(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    amount = _charge(new, _peak_may)["price"]["amount"]
    amount["value"] = "1.1500"
    amount["provenance"]["snippet"] = "Peak $/kWh $1.1500 $1.2000"

    delta = schedule_diff(parsed, new)

    assert len(delta.changes) == 1
    change = delta.changes[0]
    assert change.kind == "charges"
    assert change.change == CHANGED
    assert change.field == "price.amount"
    assert (change.old, change.new) == ("1.1000", "1.1500")
    assert change.old_cite is not None and "$1.1000" in change.old_cite["snippet"]
    assert change.new_cite is not None and "$1.1500" in change.new_cite["snippet"]
    assert change.old_cite["locator"] == change.new_cite["locator"]


def test_a_value_that_only_moved_on_the_page_is_not_a_change(parsed: Json) -> None:
    """A row inserted above shifts every citation below it; no value changed."""
    new = copy.deepcopy(parsed)
    for charge in new["charges"]:
        for field in ("label", "effective_from"):
            provenance = charge[field]["provenance"]
            provenance["line"] += 1
            provenance["locator"] = provenance["locator"] + " (moved)"
        charge["price"]["amount"]["provenance"]["line"] += 1
    assert schedule_diff(parsed, new).changes == ()


def test_a_removed_charge_is_reported_as_removed_not_left_silent(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    gone = _charge(new, _peak_may)
    new["charges"].remove(gone)

    delta = schedule_diff(parsed, new)

    assert [change.change for change in delta.changes] == [REMOVED]
    change = delta.changes[0]
    assert change.kind == "charges"
    assert change.new is None
    assert isinstance(change.old, dict) and change.old["price.amount"] == "1.1000"
    assert change.old_cite is not None and change.new_cite is None
    assert "Peak $/kWh" in change.key


def test_an_added_charge_is_reported_as_added(parsed: Json) -> None:
    old = copy.deepcopy(parsed)
    old["charges"].remove(_charge(old, _peak_may))

    delta = schedule_diff(old, parsed)

    assert [change.change for change in delta.changes] == [ADDED]
    assert delta.changes[0].new_cite is not None
    assert delta.changes[0].old_cite is None


def test_a_second_occurrence_of_one_identity_is_its_own_record(parsed: Json) -> None:
    """Stating the same charge twice is an addition, not a collision with the first."""
    new = copy.deepcopy(parsed)
    new["charges"].append(copy.deepcopy(_charge(new, _peak_may)))

    delta = schedule_diff(parsed, new)

    assert len(delta.changes) == 1
    assert delta.changes[0].change == ADDED
    assert delta.changes[0].key[-1] == "#2"
    assert "2nd occurrence" in delta.to_markdown()


def test_windows_holidays_and_identity_are_compared_too(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    new["tou_windows"][0]["definition"]["value"] = "Weekdays between 4:00 p.m. and 9:00 p.m."
    new["holidays"][0]["day_rule"]["value"] = "2"
    new["identity"]["title"]["value"] = "A Renamed Schedule"

    kinds = sorted((change.kind, change.field) for change in schedule_diff(parsed, new).changes)

    assert kinds == [
        ("holidays", "day_rule"),
        ("identity", "value"),
        ("tou_windows", "definition"),
    ]


def test_an_identity_field_that_becomes_null_is_a_removal(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    new["identity"]["title"] = None
    delta = schedule_diff(parsed, new)
    assert [(change.kind, change.change) for change in delta.changes] == [("identity", REMOVED)]


def test_different_parser_versions_are_flagged_loudly(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    new["parser_version"] = "9.9.9"
    delta = schedule_diff(parsed, new)
    assert delta.across_parser_versions
    assert "Two different parser versions" in delta.to_markdown()


def test_two_different_documents_cannot_be_diffed(parsed: Json) -> None:
    other = copy.deepcopy(parsed)
    other["source"]["document_id"] = "something-else"
    with pytest.raises(DiffError, match="not parses of one document"):
        schedule_diff(parsed, other)


def test_jsonl_carries_one_object_per_change_with_the_document_id(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    _charge(new, _peak_may)["price"]["amount"]["value"] = "1.1500"
    new["holidays"][0]["day_rule"]["value"] = "2"

    delta = schedule_diff(parsed, new)
    lines = [json.loads(line) for line in delta.to_jsonl().splitlines()]

    assert len(lines) == len(delta.changes) == 2
    for line in lines:
        assert line["document_id"] == parsed["source"]["document_id"]
        assert {"kind", "key", "change", "field", "old", "new", "old_cite", "new_cite"} <= set(line)
        assert line["old_cite"]["locator"] and line["new_cite"]["locator"]


def test_the_markdown_report_escapes_table_pipes_in_quotes(parsed: Json) -> None:
    new = copy.deepcopy(parsed)
    amount = _charge(new, _peak_may)["price"]["amount"]
    amount["value"] = "1.1500"
    amount["provenance"]["snippet"] = "Peak | $/kWh $1.1500"

    report = schedule_diff(parsed, new).to_markdown()

    assert "Peak \\| $/kWh $1.1500" in report
    assert "| document sha256 |" in report
    assert "not rate advice" in report
