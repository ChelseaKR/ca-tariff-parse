"""`explain` names the recognizer that read a line, or the fence that refused it.

Three properties are load-bearing and each is checked here rather than argued
for in a docstring:

1. **Recording cannot change what `parse` emits.** Asserted as bytes, over
   every committed fixture, with a trace open and closed.
2. **Every registered fence fires somewhere.** A fence is a name `explain`
   prints. A name nothing can reach is a declaration, not a refusal, and the
   census below fails naming it. This caught one on the first run:
   `rate_table.row-prices-nothing` was registered on a branch unreachable from
   its only caller, and was removed rather than left in the table.
3. **A line nothing reached says so.** The one thing this feature must never
   do is offer a nearest fence chosen by proximity, which would be a value
   invented from an absence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_tariff_parse.explain import (
    SelectorError,
    explain,
    fence_table,
    parse_selectors,
    to_text,
)
from ca_tariff_parse.parser import parse_path
from ca_tariff_parse.profiles import resolve
from ca_tariff_parse.trace import FENCES, active, recording, refuse

FIXTURES = Path(__file__).parent / "fixtures"

#: Every committed fixture, with the profile it is read under. The fence
#: census below is over exactly this set, so a fixture added later is in scope
#: without anybody remembering to add it to a second list.
CORPUS: tuple[tuple[Path, str | None], ...] = (
    (FIXTURES / "SYNTHETIC-example-schedule-complete.txt", None),
    (FIXTURES / "SYNTHETIC-example-schedule-unknown-section.txt", None),
    (FIXTURES / "SYNTHETIC-example-refused-rows.txt", None),
    (FIXTURES / "SYNTHETIC-example-keyword-schedule.txt", "pge-tariff-book"),
    (FIXTURES / "SYNTHETIC-example-unclosed-bracket.txt", "pge-tariff-book"),
)


def _parse(path: Path, profile: str | None):
    return parse_path(path, profile=resolve(profile)) if profile else parse_path(path)


def _traced(path: Path, profile: str | None):
    with recording() as trace:
        parsed = _parse(path, profile)
    return parsed, trace


# ---------------------------------------------------------------------------
# Recording changes nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,profile", CORPUS, ids=lambda v: getattr(v, "name", str(v)))
def test_a_traced_parse_emits_the_same_bytes_as_an_untraced_one(
    path: Path, profile: str | None
) -> None:
    """The whole reason `explain` and `parse` cannot disagree.

    Compared as serialized bytes rather than as objects: the promise is about
    what a caller receives, and two objects can be equal while their JSON is
    not.
    """
    plain = json.dumps(_parse(path, profile).to_json(), sort_keys=False)
    traced = json.dumps(_traced(path, profile)[0].to_json(), sort_keys=False)
    assert plain == traced


def test_a_refusal_recorded_with_nothing_watching_is_a_no_op() -> None:
    """Recognizers call `refuse` unconditionally, so this is the ordinary path.

    An `if tracing:` branch at every fence would be a second code path that
    could come to disagree with the first; this is what makes one path safe.
    """
    assert active() is None
    refuse(
        "rate_table",
        FENCES["rate_table.unit-not-in-label"],
        page=1,
        line=1,
        detail="nothing is listening",
    )
    assert active() is None


def test_a_nested_recording_restores_the_outer_one() -> None:
    with recording() as outer:
        with recording() as inner:
            assert active() is inner
        assert active() is outer
    assert active() is None


# ---------------------------------------------------------------------------
# The fence census
# ---------------------------------------------------------------------------


def _fences_reached_over_the_corpus() -> set[str]:
    reached: set[str] = set()
    for path, profile in CORPUS:
        reached |= _traced(path, profile)[1].fences_reached
    return reached


def test_the_registry_is_not_empty_and_the_corpus_is_not_empty() -> None:
    """The floor. Both assertions below compare sets, and two empty sets agree."""
    assert len(FENCES) >= 5, f"the fence registry holds {len(FENCES)} entries"
    assert len(CORPUS) >= 4
    for path, _ in CORPUS:
        assert path.exists(), f"{path.name} is named in CORPUS and is not in the tree"


def test_every_registered_fence_fires_on_a_committed_fixture() -> None:
    """A fence nothing reaches is a name, not a refusal.

    `explain --fences` prints this registry as though every entry were
    something the parser can report. An entry no input can produce would make
    that table a claim about the parser that is not true of it, and a reader
    filing an unread-shape report would look for a refusal that cannot happen.

    Run on the first draft this named `rate_table.row-prices-nothing`, which
    sat on a branch its only caller cannot reach. It was deleted rather than
    exempted.
    """
    unreached = sorted(set(FENCES) - _fences_reached_over_the_corpus())
    assert unreached == [], (
        "registered fences that no committed fixture reaches. Either add a "
        "fixture that trips it, or delete the fence -- an entry that cannot "
        f"fire is a table row `explain --fences` prints and never reports: {unreached}"
    )


def test_the_census_is_measured_over_the_corpus_and_not_asserted() -> None:
    """The count `explain` prints per document is the reached set of that run."""
    parsed, trace = _traced(*CORPUS[2])
    report = explain(parsed, trace)
    assert set(report.fences_reached) == trace.fences_reached
    assert set(report.fences_registered) == set(FENCES)
    assert set(report.fences_reached) <= set(report.fences_registered)


# ---------------------------------------------------------------------------
# Each fence, by name, on the input written for it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fence_id,line",
    [
        ("rate_table.unit-not-in-label", 9),
        ("rate_table.cell-not-an-amount", 10),
        ("rate_table.value-not-under-one-column", 11),
    ],
)
def test_a_refused_row_names_its_fence(fence_id: str, line: int) -> None:
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-refused-rows.txt", None)
    report = explain(parsed, trace, selectors=[(1, line)])
    assert len(report.lines) == 1
    item = report.lines[0]
    assert item.state == "refused"
    assert [r.fence.id for r in item.refusals] == [fence_id]


def test_a_line_can_be_consumed_by_one_recognizer_and_refused_by_another() -> None:
    """`state` is a summary, and `refused_by` is the record.

    Line 12 is a section heading, so segmentation credits it as understood --
    it is what produced the section id every citation in that section points
    at. `rate_table` separately claimed the section, found no readable row of
    effective-date headings under it, and refused at its own fence. Both are
    true of the same line, `state` reports the stronger fact that the line was
    read, and the fence is still named rather than being dropped because the
    summary went the other way.
    """
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-refused-rows.txt", None)
    item = explain(parsed, trace, selectors=[(1, 12)]).lines[0]
    assert item.state == "consumed"
    assert "segment" in item.consumed_by
    assert [r.fence.id for r in item.refusals] == ["rate_table.no-effective-date-header"]
    assert "rate_table.no-effective-date-header" in to_text(
        explain(parsed, trace, selectors=[(1, 12)])
    )


def test_an_unclosed_bracket_explains_the_adr_0014_fence_by_name() -> None:
    """The issue's own acceptance criterion, and the fence it names.

    ADR 0014 joins a heading across one line ending when the publisher's
    brackets say it continues, and refuses a bracket that never closes. The
    refusal is what a reader meets; until now it was legible only in the
    source.
    """
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-unclosed-bracket.txt", "pge-tariff-book")
    report = explain(parsed, trace, selectors=[(1, 18)])
    assert len(report.lines) == 1
    item = report.lines[0]
    assert item.state == "refused"
    assert [r.fence.id for r in item.refusals] == ["sheet_rates.bracket-unclosed"]
    assert item.refusals[0].fence.adr == "ADR 0014"
    assert item.refusals[0].recognizer == "sheet_rates"
    # The detail quotes the page rather than describing it.
    assert item.refusals[0].detail in item.text


def test_one_fence_firing_twice_on_a_line_is_reported_once() -> None:
    """`sheet_rates` reads a section under two shapes and both refuse the row."""
    _, trace = _traced(FIXTURES / "SYNTHETIC-example-unclosed-bracket.txt", "pge-tariff-book")
    raw = trace.refusals[(1, 18)]
    assert len(raw) > 1, "this line no longer exercises the duplicate path"
    parsed, trace2 = _traced(FIXTURES / "SYNTHETIC-example-unclosed-bracket.txt", "pge-tariff-book")
    item = explain(parsed, trace2, selectors=[(1, 18)]).lines[0]
    assert len(item.refusals) == 1


# ---------------------------------------------------------------------------
# The four states, and the one that must not be guessed
# ---------------------------------------------------------------------------


def test_a_line_no_recognizer_claimed_says_so_rather_than_naming_a_nearest_fence() -> None:
    """The guard this feature exists around.

    A line in a section every recognizer declined has no fence, because no
    rule reached it. Reporting the closest one would be a value derived from
    an absence, which is the defect this parser is built against.
    """
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-schedule-unknown-section.txt", None)
    report = explain(parsed, trace)
    unclaimed = [item for item in report.lines if item.state == "unclaimed"]
    assert unclaimed, "this fixture no longer carries a section nothing claims"
    for item in unclaimed:
        assert item.refusals == ()
        assert item.claimed_section == ()
        assert item.declined_section, "a line nothing claimed was examined by nobody either"
    rendered = to_text(report)
    assert "no rule in this parser reaches this line" in rendered
    assert "nearest" not in rendered


def test_every_state_is_produced_by_the_committed_corpus() -> None:
    """All four, or the vocabulary has an entry nothing exercises."""
    seen: set[str] = set()
    for path, profile in CORPUS:
        parsed, trace = _traced(path, profile)
        seen |= {item.state for item in explain(parsed, trace).lines}
    assert seen == {"consumed", "refused", "examined", "unclaimed"}, sorted(seen)


def test_a_consumed_line_names_the_recognizer_that_took_it() -> None:
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-schedule-complete.txt", None)
    report = explain(parsed, trace)
    consumed = [item for item in report.lines if item.state == "consumed"]
    assert consumed
    assert all(item.consumed_by for item in consumed)
    assert any("rate_table" in item.consumed_by for item in consumed)


def test_every_content_line_of_every_fixture_gets_one_of_the_four_states() -> None:
    """No line reports 'unknown'.

    The issue asks for exactly one consuming recognizer or at least one
    examining recognizer with a fence on every line. The second half of that
    is not achievable honestly and this is the measured reason: a line in a
    section every recognizer declined has no fence to name, and inventing one
    is the thing the feature is written to avoid. What is achievable, and what
    is asserted here, is that every line lands in a **named** state.
    """
    for path, profile in CORPUS:
        parsed, trace = _traced(path, profile)
        report = explain(parsed, trace)
        assert report.lines, f"{path.name} produced no explained lines"
        for item in report.lines:
            assert item.state in {"consumed", "refused", "examined", "unclaimed"}
            assert item.section, f"{path.name} p.{item.page} L{item.line} has no section"


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tokens,expected",
    [
        (["p.3", "L11"], [(3, 11)]),
        (["P.3", "l11"], [(3, 11)]),
        (["page.3", "Line.11"], [(3, 11)]),
        (["3:11"], [(3, 11)]),
        (["p.1", "L2", "3:4"], [(1, 2), (3, 4)]),
        ([], []),
    ],
)
def test_selectors_are_read_in_both_spellings(
    tokens: list[str], expected: list[tuple[int, int]]
) -> None:
    assert parse_selectors(tokens) == expected


@pytest.mark.parametrize("tokens", [["L11"], ["p.3"], ["p.3", "p.4"], ["nonsense"]])
def test_an_unreadable_selector_is_refused_rather_than_skipped(tokens: list[str]) -> None:
    """A dropped selector explains fewer lines than were asked about, silently."""
    with pytest.raises(SelectorError):
        parse_selectors(tokens)


def test_a_selector_naming_a_line_the_document_does_not_have_is_reported() -> None:
    """Not found and nothing to say are different answers."""
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-schedule-complete.txt", None)
    report = explain(parsed, trace, selectors=[(1, 4), (99, 99)])
    assert report.not_found == ((99, 99),)
    assert [(item.page, item.line) for item in report.lines] == [(1, 4)]
    assert "NOT FOUND" in to_text(report)


def test_a_section_selector_explains_that_section_only() -> None:
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-schedule-complete.txt", None)
    report = explain(parsed, trace, section="II.A")
    assert report.lines
    assert {item.section for item in report.lines} == {"II.A"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_the_text_report_states_both_fence_numbers() -> None:
    """A count of refusals says nothing about how much of the vocabulary ran."""
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-refused-rows.txt", None)
    rendered = to_text(explain(parsed, trace))
    assert f"of {len(FENCES)} reached on this document" in rendered


def test_the_fence_table_lists_every_registered_fence_with_its_adr() -> None:
    rendered = fence_table()
    for identifier, entry in FENCES.items():
        assert identifier in rendered
        assert entry.adr in rendered


def test_the_json_report_carries_the_same_states_as_the_text_one() -> None:
    parsed, trace = _traced(FIXTURES / "SYNTHETIC-example-refused-rows.txt", None)
    report = explain(parsed, trace)
    payload = json.loads(json.dumps(report.to_json()))
    assert [item["state"] for item in payload["lines"]] == [item.state for item in report.lines]
    assert payload["fences"]["registered"] == sorted(FENCES)
