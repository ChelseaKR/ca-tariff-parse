"""Reading a committed parse back in, without loosening anything on the way.

`parse` writes JSON and nothing read it back. The loader closes that, and the
whole risk of a loader is that it is lenient where the writer was strict: a
citation half filled in, a verdict trusted instead of recomputed, an omission
read back as an empty answer. Every test here is about one of those.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from ca_tariff_parse import (
    BASELINE_SCHEMA_ID,
    SCHEMA_ID,
    ParsedSchedule,
    ProvenanceError,
    SchemaError,
    WithheldError,
    load,
    loads,
)
from ca_tariff_parse.extract import layout_from_path
from ca_tariff_parse.parser import parse_document
from ca_tariff_parse.watch import dump

from .conftest import COMPLETE, GOLDEN, REPO_ROOT

BASELINES = REPO_ROOT / "data" / "parsed"


def committed_payloads() -> list[Path]:
    files = sorted(GOLDEN.glob("*.json")) + sorted(BASELINES.glob("*.json"))
    assert files, "expected committed golden files and watch baselines to load"
    return files


@pytest.fixture(scope="module")
def parsed_complete() -> ParsedSchedule:
    return parse_document(layout_from_path(COMPLETE))


@pytest.fixture(scope="module")
def golden_payload() -> dict[str, Any]:
    return json.loads((GOLDEN / "smud-r-tod.json").read_text(encoding="utf-8"))


def mutate(payload: dict[str, Any], mutation: Any) -> dict[str, Any]:
    copied = copy.deepcopy(payload)
    mutation(copied)
    return copied


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", committed_payloads(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_committed_payload_reloads_byte_for_byte(path: Path) -> None:
    """Loading and re-emitting a committed file reproduces it exactly.

    Byte equality rather than object equality on purpose: it is the only form
    that catches a field the loader silently dropped, since a dropped field
    reconstructs into an object that compares equal to itself.
    """
    text = path.read_text(encoding="utf-8")
    assert dump(load(path).to_json()) == text


def test_a_fresh_parse_round_trips_to_an_equal_schedule(parsed_complete: ParsedSchedule) -> None:
    assert load(parsed_complete.to_json()) == parsed_complete


def test_loads_reads_the_same_thing_as_load(golden_payload: dict[str, Any]) -> None:
    assert loads(json.dumps(golden_payload)) == load(golden_payload)


def test_invalid_json_is_a_schema_error() -> None:
    with pytest.raises(SchemaError, match="not valid JSON"):
        loads("{ not json")


def test_a_missing_file_is_a_schema_error(tmp_path: Path) -> None:
    with pytest.raises(SchemaError, match="cannot read"):
        load(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# A citation that is not good enough is refused, with the path named
# ---------------------------------------------------------------------------


def test_a_deleted_provenance_block_fails_to_load_naming_the_path(
    golden_payload: dict[str, Any],
) -> None:
    broken = mutate(golden_payload, lambda p: p["charges"][3]["label"].pop("provenance"))
    with pytest.raises(SchemaError) as excinfo:
        load(broken)
    assert "charges[3].label" in str(excinfo.value)


def test_an_emptied_provenance_field_fails_to_load(golden_payload: dict[str, Any]) -> None:
    broken = mutate(
        golden_payload,
        lambda p: p["charges"][0]["price"]["amount"]["provenance"].update({"snippet": "  "}),
    )
    with pytest.raises(ProvenanceError, match="snippet"):
        load(broken)


def test_a_malformed_digest_in_a_citation_fails_to_load(golden_payload: dict[str, Any]) -> None:
    broken = mutate(
        golden_payload,
        lambda p: p["charges"][0]["label"]["provenance"].update({"document_sha256": "abc"}),
    )
    with pytest.raises(ProvenanceError, match="document_sha256"):
        load(broken)


def test_a_locator_that_disagrees_with_its_own_citation_is_refused(
    golden_payload: dict[str, Any],
) -> None:
    """The locator is derived. A payload that states a different one is wrong
    somewhere, and there is no way to tell which half to believe."""
    broken = mutate(
        golden_payload,
        lambda p: p["charges"][0]["label"]["provenance"].update({"locator": "elsewhere p.9 X L1"}),
    )
    with pytest.raises(ProvenanceError, match="locator"):
        load(broken)


# ---------------------------------------------------------------------------
# A verdict is recomputed, never read
# ---------------------------------------------------------------------------


def test_a_coverage_verdict_the_counters_do_not_support_is_refused(
    golden_payload: dict[str, Any],
) -> None:
    """`fully_recognized` is derived from the counters. Reading it as data
    would let a payload assert a clean sweep over lines it did not recognize,
    which is the failure ADR 0002 exists to prevent."""
    broken = mutate(golden_payload, lambda p: p["coverage"].update({"fully_recognized": True}))
    assert golden_payload["coverage"]["unrecognized_lines"] > 0
    with pytest.raises(SchemaError, match="fully_recognized"):
        load(broken)


def test_a_coverage_ratio_that_disagrees_with_its_counters_is_refused(
    golden_payload: dict[str, Any],
) -> None:
    broken = mutate(golden_payload, lambda p: p["coverage"].update({"line_ratio": 1.0}))
    with pytest.raises(SchemaError, match="line_ratio"):
        load(broken)


def test_an_unparsed_span_that_disagrees_with_its_pages_is_refused(
    golden_payload: dict[str, Any],
) -> None:
    broken = mutate(golden_payload, lambda p: p["unparsed"][0].update({"span": "p.99 lines 1-2"}))
    with pytest.raises(SchemaError, match="span"):
        load(broken)


# ---------------------------------------------------------------------------
# The key set is exact in both directions
# ---------------------------------------------------------------------------


def test_an_unknown_key_is_refused_rather_than_dropped(golden_payload: dict[str, Any]) -> None:
    broken = mutate(golden_payload, lambda p: p["charges"][0].update({"annualised": 123.0}))
    with pytest.raises(SchemaError, match="annualised"):
        load(broken)


def test_a_missing_required_key_is_refused(golden_payload: dict[str, Any]) -> None:
    broken = mutate(golden_payload, lambda p: p["charges"][0].pop("effective_from"))
    with pytest.raises(SchemaError, match="effective_from"):
        load(broken)


def test_a_price_amount_must_stay_a_string(golden_payload: dict[str, Any]) -> None:
    broken = mutate(
        golden_payload, lambda p: p["charges"][0]["price"]["amount"].update({"value": 0.1724})
    )
    with pytest.raises(SchemaError, match="exact decimal"):
        load(broken)


def test_an_unknown_schema_is_refused_rather_than_guessed_at(
    golden_payload: dict[str, Any],
) -> None:
    broken = mutate(golden_payload, lambda p: p.update({"schema": "something/else/v3"}))
    with pytest.raises(SchemaError) as excinfo:
        load(broken)
    assert SCHEMA_ID in str(excinfo.value)
    assert BASELINE_SCHEMA_ID in str(excinfo.value)


# ---------------------------------------------------------------------------
# An omission is not an empty answer
# ---------------------------------------------------------------------------


def test_a_watch_baseline_declares_what_it_left_out() -> None:
    schedule = load(BASELINES / "pge-e-1.json")
    assert schedule.withheld == ("notes", "unparsed[].sample")


def test_a_full_parse_declares_nothing_withheld() -> None:
    assert load(GOLDEN / "smud-r-tod.json").withheld == ()


def test_querying_a_withheld_collection_raises_rather_than_answering_none() -> None:
    schedule = load(BASELINES / "pge-e-1.json")
    assert len(schedule.notes) == 0
    with pytest.raises(WithheldError, match="unreported"):
        schedule.notes.where()


def test_a_baseline_re_emits_as_a_baseline_not_as_a_parse_with_no_notes() -> None:
    """The dangerous direction. Re-emitting a projection under
    `parsed-schedule/v1` would write `"notes": []`, which states that the
    document has no prose. It has prose; the projection dropped it."""
    payload = load(BASELINES / "pge-e-1.json").to_json()
    assert payload["schema"] == BASELINE_SCHEMA_ID
    assert "notes" not in payload
    assert all("sample" not in item for item in payload["unparsed"])  # type: ignore[union-attr]


def test_a_projection_that_does_not_describe_itself_is_refused() -> None:
    payload = json.loads((BASELINES / "pge-e-1.json").read_text(encoding="utf-8"))
    payload["omitted"]["fields"] = ["unparsed[].sample"]
    with pytest.raises(SchemaError, match="does not describe itself"):
        load(payload)


def test_a_projection_carrying_a_sample_it_says_it_omitted_is_refused() -> None:
    payload = json.loads((BASELINES / "pge-e-1.json").read_text(encoding="utf-8"))
    payload["unparsed"][0]["sample"] = ["a line"]
    with pytest.raises(SchemaError, match="one of the two is wrong"):
        load(payload)


# ---------------------------------------------------------------------------
# The query surface
# ---------------------------------------------------------------------------


def test_where_selects_on_a_cited_field_by_its_value(parsed_complete: ParsedSchedule) -> None:
    seasons = {c.season.value for c in parsed_complete.charges if c.season is not None}
    assert seasons, "the complete fixture is expected to state at least one season"
    wanted = sorted(seasons)[0]
    selected = parsed_complete.charges.where(season=wanted)
    assert selected
    assert all(c.season is not None and c.season.value == wanted for c in selected)


def test_where_selects_on_a_structural_field(parsed_complete: ParsedSchedule) -> None:
    selected = parsed_complete.charges.where(kind="fixed_charge")
    assert selected
    assert all(c.kind == "fixed_charge" for c in selected)


def test_where_none_means_the_document_did_not_state_it(
    parsed_complete: ParsedSchedule,
) -> None:
    stated = parsed_complete.charges.where(season=None)
    assert all(c.season is None for c in stated)
    assert len(stated) + len([c for c in parsed_complete.charges if c.season is not None]) == len(
        parsed_complete.charges
    )


def test_where_combines_criteria_conjunctively(parsed_complete: ParsedSchedule) -> None:
    both = parsed_complete.charges.where(kind="energy_usage", season=None)
    assert all(c.kind == "energy_usage" and c.season is None for c in both)


def test_an_unknown_field_name_is_an_error_not_an_empty_result(
    parsed_complete: ParsedSchedule,
) -> None:
    """An empty result reads as "the schedule states nothing of the kind".
    A typo is not that."""
    with pytest.raises(AttributeError, match="seson"):
        parsed_complete.charges.where(seson="Summer")


def test_where_returns_something_that_can_be_filtered_again(
    parsed_complete: ParsedSchedule,
) -> None:
    once = parsed_complete.charges.where(kind="energy_usage")
    assert once.where(kind="energy_usage") == once


# ---------------------------------------------------------------------------
# cite()
# ---------------------------------------------------------------------------


def test_cite_returns_the_provenance_behind_a_field(parsed_complete: ParsedSchedule) -> None:
    charge = parsed_complete.charges[0]
    assert parsed_complete.cite(charge, "label") is charge.label.provenance


def test_cite_refuses_a_field_the_document_did_not_state(
    parsed_complete: ParsedSchedule,
) -> None:
    absent = [c for c in parsed_complete.charges if c.applies_to is None]
    assert absent, "expected at least one charge with no applies_to"
    with pytest.raises(ProvenanceError, match="nothing to cite"):
        parsed_complete.cite(absent[0], "applies_to")


def test_cite_refuses_structural_metadata(parsed_complete: ParsedSchedule) -> None:
    with pytest.raises(ProvenanceError, match="structural metadata"):
        parsed_complete.cite(parsed_complete.charges[0], "kind")


def test_cite_refuses_a_field_that_does_not_exist(parsed_complete: ParsedSchedule) -> None:
    with pytest.raises(AttributeError, match="lable"):
        parsed_complete.cite(parsed_complete.charges[0], "lable")


# ---------------------------------------------------------------------------
# The load path needs no PDF stack
# ---------------------------------------------------------------------------


def test_load_works_with_pdfplumber_uninstalled() -> None:
    """Run in a subprocess with `pdfplumber` made unimportable.

    Asserting that `sys.modules` merely lacks it would prove nothing: the
    import is deferred, so it would be absent either way. This makes the
    import genuinely fail, which is what an install without the PDF extra
    looks like.
    """
    program = textwrap.dedent(
        """
        import sys

        class Blocker:
            def find_module(self, name, path=None):
                return self.find_spec(name, path)

            def find_spec(self, name, path=None, target=None):
                if name == "pdfplumber" or name.startswith("pdfplumber."):
                    raise ImportError("pdfplumber is not installed")
                return None

        sys.meta_path.insert(0, Blocker())
        try:
            import pdfplumber  # noqa: F401
        except ImportError:
            pass
        else:
            raise SystemExit("the blocker did not work; this test proves nothing")

        import ca_tariff_parse

        schedule = ca_tariff_parse.load(sys.argv[1])
        assert schedule.charges, "expected charges"
        assert "pdfplumber" not in sys.modules
        print(len(schedule.charges))
        """
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", program, str(GOLDEN / "smud-r-tod.json")],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) > 0
