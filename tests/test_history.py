"""A timeline built only from what is committed, with the gaps left in it.

The watch writes a diff per revision and a reviewed baseline. `history` reads
them back. The risk in a timeline is that it looks continuous: a missing
revision joined to its neighbours, a retrieval order guessed from filenames, a
run of reports presented as though one parser read them all. Each of those is
a test here.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest

from ca_tariff_parse.cli import EXIT_NO_MATCH, EXIT_OK, main
from ca_tariff_parse.diff import PARSER_DIFFERENT, PARSER_INDETERMINATE, schedule_diff
from ca_tariff_parse.history import (
    ABSENT,
    HistoryError,
    parse_match,
    read_legs,
    timelines,
)
from ca_tariff_parse.watch import dump, project

from .conftest import GOLDEN

DOC = "smud-r-tod"
MOVING = 'label="System Infrastructure Fixed Charge per month per meter"'


def stamped(payload: dict[str, Any], sha: str, retrieved: str) -> dict[str, Any]:
    """A copy of a parse that states it was read from `sha` on `retrieved`."""
    out = copy.deepcopy(payload)
    out["source"]["sha256"] = sha
    out["source"]["retrieved_at"] = retrieved

    def restamp(node: Any) -> None:
        if isinstance(node, dict):
            if "provenance" in node and isinstance(node["provenance"], dict):
                node["provenance"]["document_sha256"] = sha
            for value in node.values():
                restamp(value)
        elif isinstance(node, list):
            for item in node:
                restamp(item)

    restamp(out)
    return out


@pytest.fixture
def scenario(tmp_path: Path) -> Path:
    """A baseline and two change reports, moving one price twice."""
    changes = tmp_path / "changes"
    parsed = tmp_path / "parsed"
    changes.mkdir()
    parsed.mkdir()

    first = stamped(
        json.loads((GOLDEN / f"{DOC}.json").read_text(encoding="utf-8")), "a" * 64, "2026-01-05"
    )
    second = stamped(first, "b" * 64, "2026-03-02")
    second["charges"][0]["price"]["amount"]["value"] = "27.10"
    third = stamped(second, "c" * 64, "2026-06-01")
    third["charges"][0]["price"]["amount"]["value"] = "28.40"

    for old, new, date in ((first, second, "2026-03-02"), (second, third, "2026-06-01")):
        (changes / f"{date}-{DOC}.jsonl").write_text(
            schedule_diff(old, new).to_jsonl(), encoding="utf-8"
        )
    (parsed / f"{DOC}.json").write_text(dump(project(third)), encoding="utf-8")
    return tmp_path


def built(root: Path, match: str | None = MOVING):
    legs = read_legs(root / "changes", DOC)
    baseline = json.loads((root / "parsed" / f"{DOC}.json").read_text(encoding="utf-8"))
    return timelines(legs, baseline, parse_match(match) if match else None)


def moving(root: Path):
    """The one record the scenario actually moves."""
    found = [line for line in built(root) if line.events]
    assert len(found) == 1, [line.identity for line in found]
    return found[0]


# ---------------------------------------------------------------------------
# The timeline itself
# ---------------------------------------------------------------------------


def test_a_changed_price_lists_three_states(scenario: Path) -> None:
    line = moving(scenario)
    states = [line.events[0].before, *(event.after for event in line.events)]
    assert states == ["26.20", "27.10", "28.40"]
    assert line.current is not None
    assert line.current["price.amount"] == "28.40"


def test_each_state_carries_the_citation_of_the_revision_that_set_it(
    scenario: Path,
) -> None:
    line = moving(scenario)
    for event in line.events:
        assert event.cite_before is not None
        assert event.cite_after is not None
        assert event.cite_before["locator"]
        assert event.cite_after["locator"]


def test_each_event_carries_its_retrieval_date(scenario: Path) -> None:
    line = moving(scenario)
    assert [event.retrieved_at for event in line.events] == ["2026-03-02", "2026-06-01"]


def test_a_record_that_never_changed_has_one_state(scenario: Path) -> None:
    unchanged = [line for line in built(scenario) if not line.events]
    assert unchanged, "expected records the scenario does not move"
    for line in unchanged:
        assert line.events == ()
        assert line.current is not None


def test_an_unchanged_record_is_listed_rather_than_omitted(scenario: Path) -> None:
    """Leaving it out would make "no result" mean both "no such record" and
    "a record the publisher has not moved"."""
    text = _run(scenario, MOVING)
    assert "No committed report records a change to this record" in text


def test_records_are_matched_by_identity_not_by_position() -> None:
    """A value that only moved on the page has no event."""
    first = stamped(
        json.loads((GOLDEN / f"{DOC}.json").read_text(encoding="utf-8")), "a" * 64, "2026-01-05"
    )
    moved = stamped(first, "d" * 64, "2026-09-01")
    moved["charges"] = [moved["charges"][-1], *moved["charges"][:-1]]
    assert schedule_diff(first, moved).changes == (), "reordering the array is not a change"


# ---------------------------------------------------------------------------
# Gaps are reported, not joined
# ---------------------------------------------------------------------------


def test_a_missing_revision_is_reported_as_a_gap(scenario: Path) -> None:
    """The second report compares against bytes no committed report produced."""
    changes = scenario / "changes"
    report = changes / f"2026-06-01-{DOC}.jsonl"
    lines = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line["sha256_before"] = "9" * 64
    report.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )
    gaps = built(scenario)[0].gaps
    assert any("a revision is missing between 2026-03-02 and 2026-06-01" in gap for gap in gaps)


def test_a_gap_is_not_smoothed_into_the_timeline(scenario: Path) -> None:
    report = (scenario / "changes") / f"2026-06-01-{DOC}.jsonl"
    lines = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line["sha256_before"] = "9" * 64
    report.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )
    text = _run(scenario, MOVING)
    assert "## Gaps in the committed record" in text
    assert "the line between them is not" in text


def test_a_baseline_from_bytes_no_report_produced_is_a_gap(scenario: Path) -> None:
    path = scenario / "parsed" / f"{DOC}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source"]["sha256"] = "e" * 64
    path.write_text(dump(payload), encoding="utf-8")
    gaps = built(scenario)[0].gaps
    assert any("the reviewed baseline was written from bytes" in gap for gap in gaps)


def test_no_gap_is_reported_when_the_chain_is_whole(scenario: Path) -> None:
    assert built(scenario)[0].gaps == ()


# ---------------------------------------------------------------------------
# Order comes from the reports, not the filenames
# ---------------------------------------------------------------------------


def test_reports_whose_dates_run_backwards_are_refused_with_both_named(
    scenario: Path,
) -> None:
    report = (scenario / "changes") / f"2026-06-01-{DOC}.jsonl"
    lines = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line["retrieved_at"] = "2026-02-01"
    report.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )
    with pytest.raises(HistoryError) as excinfo:
        read_legs(scenario / "changes", DOC)
    message = str(excinfo.value)
    assert "2026-03-02" in message
    assert "2026-02-01" in message


def test_a_report_with_no_retrieval_date_is_refused(scenario: Path) -> None:
    report = (scenario / "changes") / f"2026-06-01-{DOC}.jsonl"
    lines = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    for line in lines:
        line.pop("retrieved_at")
    report.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines), encoding="utf-8"
    )
    with pytest.raises(HistoryError, match="does not state retrieved_at"):
        read_legs(scenario / "changes", DOC)


def test_a_report_describing_two_comparisons_is_refused(scenario: Path) -> None:
    """A report is one comparison. Two retrieval dates in one file would let a
    timeline place half of it in one revision and half in another."""
    report = (scenario / "changes") / f"2026-06-01-{DOC}.jsonl"
    line = json.loads(report.read_text(encoding="utf-8").splitlines()[0])
    other = copy.deepcopy(line)
    other["retrieved_at"] = "2027-01-01"
    other["key"] = [*line["key"][:-1], "#2"]
    report.write_text(
        json.dumps(line, ensure_ascii=False) + "\n" + json.dumps(other, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(HistoryError, match="one report describes one comparison"):
        read_legs(scenario / "changes", DOC)


def test_an_empty_report_is_refused_rather_than_skipped(scenario: Path) -> None:
    (scenario / "changes" / f"2026-07-01-{DOC}.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(HistoryError, match="holds no change lines"):
        read_legs(scenario / "changes", DOC)


# ---------------------------------------------------------------------------
# No leg claims one parser read both sides
# ---------------------------------------------------------------------------


def test_every_leg_reports_a_three_state_parser_comparison(scenario: Path) -> None:
    line = moving(scenario)
    for event in line.events:
        assert event.parser_comparison in {
            PARSER_INDETERMINATE,
            PARSER_DIFFERENT,
            "unstated",
        }


def test_equal_parser_stamps_are_indeterminate_not_clean(scenario: Path) -> None:
    """Both sides of the scenario were read by this parser, so the stamps are
    equal. That establishes nothing, and the note says so."""
    line = moving(scenario)
    assert {event.parser_comparison for event in line.events} == {PARSER_INDETERMINATE}
    text = _run(scenario, MOVING)
    assert "proves nothing" in text
    assert "same parser read both" not in text


def test_no_note_says_one_parser_read_the_timeline(scenario: Path) -> None:
    text = _run(scenario, MOVING)
    for phrase in ("one parser", "the same parser read", "unchanged parser"):
        assert phrase not in text


# ---------------------------------------------------------------------------
# --match
# ---------------------------------------------------------------------------


def test_a_match_term_that_is_not_field_equals_value_is_refused() -> None:
    with pytest.raises(HistoryError, match="is not field=value"):
        parse_match("label")


def test_a_match_naming_a_field_no_record_has_is_refused() -> None:
    """A typo that matched nothing would look exactly like a value the
    document does not state."""
    with pytest.raises(HistoryError, match="no record is identified by"):
        parse_match("lable=Generation")


def test_a_match_naming_a_real_field_of_another_kind_selects_nothing_quietly(
    scenario: Path,
) -> None:
    selected = built(scenario, "period=Peak")
    assert all(line.kind == "tou_windows" for line in selected)


def test_a_match_that_selects_nothing_exits_non_zero(scenario: Path, capsys) -> None:
    code = main(
        [
            "history",
            "--id",
            DOC,
            "--changes-dir",
            str(scenario / "changes"),
            "--baseline-dir",
            str(scenario / "parsed"),
            "--match",
            "label=nothing-is-called-this",
        ]
    )
    assert code == EXIT_NO_MATCH
    assert "no record matched" in capsys.readouterr().err


def _committed_baseline_only(root: Path) -> None:
    """A reviewed baseline with no change reports beside it.

    This is the state of the repository itself: `data/parsed/` is committed and
    `data/changes/` does not exist yet, because the watch has not recorded a
    revision. It is the case the command has to get right.
    """
    (root / "changes").mkdir()
    (root / "parsed").mkdir()
    first = stamped(
        json.loads((GOLDEN / f"{DOC}.json").read_text(encoding="utf-8")), "a" * 64, "2026-01-05"
    )
    (root / "parsed" / f"{DOC}.json").write_text(dump(project(first)), encoding="utf-8")


def test_all_with_no_committed_reports_is_not_a_failed_match(tmp_path: Path, capsys) -> None:
    """`--all` asks for nothing by name, so nothing coming back is a statement
    about what has been committed, not a match that failed. Exiting 5 here
    would tell a script the request was wrong when the record is simply empty."""
    _committed_baseline_only(tmp_path)
    code = main(
        [
            "history",
            "--id",
            DOC,
            "--changes-dir",
            str(tmp_path / "changes"),
            "--baseline-dir",
            str(tmp_path / "parsed"),
            "--all",
        ]
    )
    captured = capsys.readouterr()
    assert code == EXIT_OK
    assert "no committed report" in captured.err
    assert "None" not in captured.err
    assert "not about whether the document has changed" in captured.err


def test_an_empty_report_says_what_it_does_and_does_not_establish(
    tmp_path: Path,
) -> None:
    _committed_baseline_only(tmp_path)
    text = _run_at(tmp_path, None)
    assert "Nothing to show" in text
    assert "Neither says the document has not changed" in text


def test_the_no_match_code_is_not_the_read_failure_code() -> None:
    assert EXIT_NO_MATCH != EXIT_OK
    assert EXIT_NO_MATCH == 5


def test_all_lists_every_record_the_reports_mention(scenario: Path) -> None:
    legs = read_legs(scenario / "changes", DOC)
    baseline = json.loads((scenario / "parsed" / f"{DOC}.json").read_text(encoding="utf-8"))
    every = timelines(legs, baseline, None)
    mentioned = {(line["kind"], tuple(line["key"])) for leg in legs for line in leg.changes}
    assert {(line.kind, line.key) for line in every} == mentioned


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _run_at(root: Path, match: str | None, *extra: str) -> str:
    return _run(root, match, *extra)


def _run(root: Path, match: str | None, *extra: str) -> str:
    buffer = io.StringIO()
    argv = [
        "history",
        "--id",
        DOC,
        "--changes-dir",
        str(root / "changes"),
        "--baseline-dir",
        str(root / "parsed"),
        *(["--match", match] if match else ["--all"]),
        *extra,
    ]
    with contextlib.redirect_stdout(buffer):
        main(argv)
    return buffer.getvalue()


def test_the_command_needs_exactly_one_of_match_and_all(scenario: Path) -> None:
    base = [
        "history",
        "--id",
        DOC,
        "--changes-dir",
        str(scenario / "changes"),
        "--baseline-dir",
        str(scenario / "parsed"),
    ]
    assert main(base) == 1
    assert main([*base, "--all", "--match", "label=x"]) == 1


def test_jsonl_carries_one_object_per_timeline(scenario: Path) -> None:
    text = _run(scenario, MOVING, "--jsonl")
    lines = [json.loads(line) for line in text.splitlines()]
    assert lines
    for line in lines:
        assert line["document_id"] == DOC
        assert {"kind", "key", "identity", "events", "current", "gaps"} <= set(line)


def test_an_absent_value_is_named_rather_than_left_blank(scenario: Path) -> None:
    """A record added by a revision has no value before it, and "" would read
    as a value the document stated."""
    changes = scenario / "changes"
    first = stamped(
        json.loads((GOLDEN / f"{DOC}.json").read_text(encoding="utf-8")), "c" * 64, "2026-06-01"
    )
    later = stamped(first, "f" * 64, "2026-09-01")
    later["holidays"] = later["holidays"][:-1]
    (changes / f"2026-09-01-{DOC}.jsonl").write_text(
        schedule_diff(first, later).to_jsonl(), encoding="utf-8"
    )
    path = scenario / "parsed" / f"{DOC}.json"
    path.write_text(dump(project(later)), encoding="utf-8")
    removed = [
        line
        for line in built(scenario, None)
        if any(event.after is ABSENT or event.after == ABSENT for event in line.events)
    ]
    assert removed, "expected the last revision to remove a holiday"

    text = _run(scenario, None)
    # On an *event* line, not the "now" line: the two are different statements
    # and the "now" branch has its own wording, so asserting the phrase alone
    # would pass even if a removal rendered as blank.
    event_lines = [
        line
        for line in text.splitlines()
        if line.startswith("- **2026-09-01**") and "removed" in line
    ]
    assert event_lines, text
    for line in event_lines:
        assert line.rstrip().endswith("→ (not in the document)"), line
