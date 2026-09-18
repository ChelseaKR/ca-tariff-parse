"""The watch: a revision is diffed and proposed, never absorbed; a failure is never "unchanged"."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from ca_tariff_parse.cli import EXIT_CHANGED, EXIT_ERROR, EXIT_OK, main
from ca_tariff_parse.parser import parse_manifest_document, parse_path
from ca_tariff_parse.sources import SourceEntry, SourceError, load_manifest
from ca_tariff_parse.watch import (
    BASELINE_SCHEMA,
    CHANGED,
    ERROR,
    NEVER_LOOKED,
    OBSERVATION_SCHEMA,
    UNCHANGED,
    ObservationError,
    Outcome,
    append_observation,
    looks_at,
    manifest_with,
    observation,
    observation_sentence,
    project,
    read_observations,
    watch_entry,
    write_baseline,
)

from .conftest import COMPLETE, REPO_ROOT, UNKNOWN

OLD = COMPLETE.read_bytes()
#: The same document with one price revised, in place, so nothing else moves.
NEW = OLD.replace(b"$1.1000", b"$1.1500")
assert OLD != NEW

Downloader = Callable[[SourceEntry, Path], Path]


def _manifest(tmp_path: Path, payload: bytes = OLD) -> tuple[Path, SourceEntry]:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        "# this comment must survive a manifest update\n"
        "[[document]]\n"
        'id = "syn"\n'
        'schedule = "SYN-1"\n'
        'title = "Synthetic"\n'
        'publisher = "Test Utility"\n'
        'url = "https://example.com/syn.txt"\n'
        'filename = "syn.txt"\n'
        f'sha256 = "{hashlib.sha256(payload).hexdigest()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 4\n"
        f"bytes = {len(payload)}\n",
        encoding="utf-8",
    )
    return manifest, load_manifest(manifest)[0]


def _serving(payload: bytes) -> Downloader:
    def downloader(entry: SourceEntry, root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        target = root / entry.filename
        target.write_bytes(payload)
        return target

    return downloader


def _seed(tmp_path: Path, entry: SourceEntry) -> Path:
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    (pinned / entry.filename).write_bytes(OLD)
    parsed = parse_manifest_document(entry, pinned / entry.filename)
    return write_baseline(tmp_path / "parsed", entry.id, parsed.to_json())


def _watch(tmp_path: Path, entry: SourceEntry, downloader: Downloader) -> Outcome:
    return watch_entry(
        entry,
        downloader=downloader,
        baseline_dir=tmp_path / "parsed",
        changes_dir=tmp_path / "changes",
        work_dir=tmp_path / "work",
        today="2026-09-01",
    )


# --- the projection ------------------------------------------------------------


def test_the_baseline_drops_the_verbatim_carriers_and_says_so() -> None:
    payload = parse_path(UNKNOWN).to_json()
    assert payload["notes"] and payload["unparsed"] and payload["unparsed"][0]["sample"]

    baseline = project(payload)

    assert baseline["schema"] == BASELINE_SCHEMA
    assert "notes" not in baseline
    assert all("sample" not in item for item in baseline["unparsed"])
    assert baseline["omitted"]["fields"] == ["notes", "unparsed[].sample"]
    assert "ADR 0016" in baseline["omitted"]["why"]
    # Everything cited is untouched, in order.
    for key in ("charges", "tou_windows", "holidays", "identity", "coverage", "source"):
        assert baseline[key] == payload[key]
    assert next(iter(baseline)) == "schema"


# --- the watch ------------------------------------------------------------------


def test_the_pinned_bytes_are_unchanged(tmp_path: Path) -> None:
    _, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    outcome = _watch(tmp_path, entry, _serving(OLD))
    assert outcome.state == UNCHANGED
    assert outcome.sha256 == entry.sha256
    assert not (tmp_path / "changes").exists()


def test_a_revision_is_diffed_written_and_proposed(tmp_path: Path) -> None:
    _, entry = _manifest(tmp_path)
    baseline = _seed(tmp_path, entry)
    before = baseline.read_text(encoding="utf-8")

    outcome = _watch(tmp_path, entry, _serving(NEW))

    assert outcome.state == CHANGED
    assert outcome.sha256 == hashlib.sha256(NEW).hexdigest()
    assert outcome.retrieved_at == "2026-09-01"
    assert outcome.changed == 1 and outcome.total == 1
    assert outcome.report is not None and outcome.report.name == "2026-09-01-syn.md"
    report = outcome.report.read_text(encoding="utf-8")
    assert "1.1000" in report and "1.1500" in report
    assert "syn p.2 sheet SYN-1-2 II.A L11" in report
    assert outcome.jsonl is not None
    assert len(outcome.jsonl.read_text(encoding="utf-8").splitlines()) == 1
    # The baseline now describes the revision, ready to be reviewed and merged.
    after = json.loads(baseline.read_text(encoding="utf-8"))
    assert after["source"]["sha256"] == outcome.sha256
    assert after["source"]["retrieved_at"] == "2026-09-01"
    assert baseline.read_text(encoding="utf-8") != before
    # The bytes themselves never land next to the baseline.
    assert sorted(p.name for p in (tmp_path / "parsed").iterdir()) == ["syn.json"]


def test_a_download_failure_is_an_error_never_unchanged(tmp_path: Path) -> None:
    _, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)

    def failing(entry: SourceEntry, root: Path) -> Path:  # noqa: ARG001
        raise OSError("connection reset")

    outcome = _watch(tmp_path, entry, failing)
    assert outcome.state == ERROR
    assert "download failed" in outcome.detail


def test_a_missing_baseline_is_an_error_not_a_fresh_start(tmp_path: Path) -> None:
    _, entry = _manifest(tmp_path)
    outcome = _watch(tmp_path, entry, _serving(NEW))
    assert outcome.state == ERROR
    assert "no baseline" in outcome.detail


# --- the manifest proposal -------------------------------------------------------


def test_manifest_with_replaces_the_four_pinned_facts_and_nothing_else() -> None:
    text = (REPO_ROOT / "sources" / "sources.toml").read_text(encoding="utf-8")
    before = {entry["id"]: entry for entry in tomllib.loads(text)["document"]}

    out = manifest_with(
        text, "pge-b-1", sha256="ab" * 32, size=1234, pages=12, retrieved_at="2026-09-01"
    )

    after = {entry["id"]: entry for entry in tomllib.loads(out)["document"]}
    assert after["pge-b-1"]["sha256"] == "ab" * 32
    assert after["pge-b-1"]["bytes"] == 1234
    assert after["pge-b-1"]["pages"] == 12
    assert after["pge-b-1"]["retrieved_at"] == "2026-09-01"
    for key in ("id", "profile", "schedule", "title", "publisher", "url", "filename"):
        assert after["pge-b-1"][key] == before["pge-b-1"][key]
    for entry_id in before:
        if entry_id != "pge-b-1":
            assert after[entry_id] == before[entry_id]
    # The comments the manifest carries survive, because nothing re-serialized it.
    assert "A second publisher, added to find out" in out
    assert out.count("[[document]]") == text.count("[[document]]")


def test_manifest_with_refuses_an_id_it_cannot_find_exactly_once(tmp_path: Path) -> None:
    manifest, _ = _manifest(tmp_path)
    text = manifest.read_text(encoding="utf-8")
    with pytest.raises(SourceError, match="0 time"):
        manifest_with(text, "nope", sha256="ab" * 32, size=1, pages=1, retrieved_at="2026-09-01")
    doubled = text + "\n" + text.split("\n", 1)[1]
    with pytest.raises(SourceError, match="2 time"):
        manifest_with(doubled, "syn", sha256="ab" * 32, size=1, pages=1, retrieved_at="2026-09-01")


# --- the commands --------------------------------------------------------------


def _cli_downloader(payload: bytes) -> Callable[..., Path]:
    def download(entry: SourceEntry, root: Path, *, timeout: float) -> Path:  # noqa: ARG001
        return _serving(payload)(entry, root)

    return download


def _watch_args(tmp_path: Path, manifest: Path) -> list[str]:
    return [
        "watch",
        "--manifest",
        str(manifest),
        "--baseline-dir",
        str(tmp_path / "parsed"),
        "--changes-dir",
        str(tmp_path / "changes"),
        "--work-dir",
        str(tmp_path / "work"),
        "--date",
        "2026-09-01",
        "--summary",
        str(tmp_path / "summary.json"),
        "--log",
        str(tmp_path / "watch-log.jsonl"),
    ]


def test_watch_command_proposes_the_manifest_update_and_writes_a_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    monkeypatch.setattr("ca_tariff_parse.cli.download", _cli_downloader(NEW))

    assert main(_watch_args(tmp_path, manifest)) == EXIT_OK

    revised = load_manifest(manifest)[0]
    assert revised.sha256 == hashlib.sha256(NEW).hexdigest()
    assert revised.bytes == len(NEW)
    assert revised.retrieved_at == "2026-09-01"
    assert "this comment must survive" in manifest.read_text(encoding="utf-8")
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["date"] == "2026-09-01"
    assert summary["outcomes"][0]["state"] == CHANGED
    assert summary["outcomes"][0]["changed"] == 1
    assert (tmp_path / "changes" / "2026-09-01-syn.md").is_file()


def test_watch_command_leaves_the_manifest_alone_when_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    before = manifest.read_text(encoding="utf-8")
    monkeypatch.setattr("ca_tariff_parse.cli.download", _cli_downloader(OLD))

    assert main(_watch_args(tmp_path, manifest)) == EXIT_OK

    assert manifest.read_text(encoding="utf-8") == before
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["outcomes"][0]["state"] == UNCHANGED


def test_watch_command_exits_non_zero_when_it_could_not_look(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)

    def failing(entry: SourceEntry, root: Path, *, timeout: float) -> Path:  # noqa: ARG001
        raise OSError("connection reset")

    monkeypatch.setattr("ca_tariff_parse.cli.download", failing)
    assert main(_watch_args(tmp_path, manifest)) == EXIT_ERROR
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["outcomes"][0]["state"] == ERROR


def test_baseline_command_writes_a_projection_from_the_pinned_bytes(tmp_path: Path) -> None:
    manifest, entry = _manifest(tmp_path)
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    (pinned / entry.filename).write_bytes(OLD)

    code = main(
        [
            "baseline",
            "--manifest",
            str(manifest),
            "--dir",
            str(pinned),
            "--baseline-dir",
            str(tmp_path / "parsed"),
        ]
    )

    assert code == EXIT_OK
    baseline = json.loads((tmp_path / "parsed" / "syn.json").read_text(encoding="utf-8"))
    assert baseline["schema"] == BASELINE_SCHEMA
    assert baseline["source"]["sha256"] == entry.sha256


def test_baseline_command_refuses_bytes_that_are_not_the_pinned_bytes(tmp_path: Path) -> None:
    manifest, entry = _manifest(tmp_path)
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    (pinned / entry.filename).write_bytes(NEW)
    code = main(
        [
            "baseline",
            "--manifest",
            str(manifest),
            "--dir",
            str(pinned),
            "--baseline-dir",
            str(tmp_path / "p"),
        ]
    )
    assert code == EXIT_ERROR
    assert not (tmp_path / "p").exists()


def test_diff_command_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    other = tmp_path / "other.json"
    old.write_text(json.dumps(parse_path(COMPLETE).to_json()), encoding="utf-8")
    revised = tmp_path / "revised.txt"
    revised.write_bytes(NEW)
    payload = parse_path(revised, document_id=COMPLETE.stem).to_json()
    new.write_text(json.dumps(payload), encoding="utf-8")
    other.write_text(json.dumps(parse_path(UNKNOWN).to_json()), encoding="utf-8")

    assert main(["diff", str(old), str(old)]) == EXIT_OK
    assert "0 added, 0 removed, 0 changed" in capsys.readouterr().err

    out = tmp_path / "changes.jsonl"
    assert main(["diff", str(old), str(new), "--jsonl", "-o", str(out)]) == EXIT_CHANGED
    line = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert (line["old"], line["new"]) == ("1.1000", "1.1500")

    assert main(["diff", str(old), str(other)]) == EXIT_ERROR
    assert "not parses of one document" in capsys.readouterr().err


# --- the observation log -------------------------------------------------------
#
# A run that finds nothing writes no change report. Without a record of the run
# itself, a repository whose publishers revised nothing is byte for byte a
# repository whose watch has never run, and the second is reported as the first.


def _log(tmp_path: Path) -> Path:
    return tmp_path / "watch-log.jsonl"


def _clock(monkeypatch: pytest.MonkeyPatch, *times: str) -> None:
    """Pin the moment each run looks, in order."""
    queue: Iterator[str] = iter(times)
    monkeypatch.setattr("ca_tariff_parse.cli._utc_now", lambda: next(queue))


def test_a_run_that_found_nothing_still_records_that_it_looked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    monkeypatch.setattr("ca_tariff_parse.cli.download", _cli_downloader(OLD))
    _clock(monkeypatch, "2026-09-01T14:23:41Z")

    assert main(_watch_args(tmp_path, manifest)) == EXIT_OK

    assert not (tmp_path / "changes").exists(), "nothing changed, so nothing is reported"
    records = read_observations(_log(tmp_path))
    assert len(records) == 1
    record = records[0]
    assert record["schema"] == OBSERVATION_SCHEMA
    assert record["looked_at"] == "2026-09-01T14:23:41Z"
    # A quiet week is a line that says so, with the time and a count of zero.
    assert record["summary"] == "looked at 2026-09-01T14:23:41Z, found 0 changes across 1 document"
    assert (record["examined"], record["changes"], record["errors"]) == (1, 0, 0)
    assert [(d["id"], d["state"]) for d in record["documents"]] == [("syn", UNCHANGED)]
    assert record["summary"] in capsys.readouterr().out
    look = looks_at(records, "syn")
    assert (look.ever, look.looks, look.last_state) == (True, 1, UNCHANGED)
    assert "found the bytes the manifest pins" in look.sentence()


def test_a_run_that_could_not_look_is_recorded_as_unknown_not_as_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)

    def failing(entry: SourceEntry, root: Path, *, timeout: float) -> Path:  # noqa: ARG001
        raise OSError("connection reset")

    monkeypatch.setattr("ca_tariff_parse.cli.download", failing)
    assert main(_watch_args(tmp_path, manifest)) == EXIT_ERROR

    look = looks_at(read_observations(_log(tmp_path)), "syn")
    assert look.last_state == ERROR
    assert "unknown rather than unchanged" in look.sentence()


def test_the_log_is_appended_so_an_earlier_look_is_never_restated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    monkeypatch.setattr("ca_tariff_parse.cli.download", _cli_downloader(OLD))
    _clock(monkeypatch, "2026-09-01T14:23:41Z", "2026-09-08T14:24:02Z")
    assert main(_watch_args(tmp_path, manifest)) == EXIT_OK
    first = _log(tmp_path).read_text(encoding="utf-8")

    args = _watch_args(tmp_path, manifest)
    args[args.index("--date") + 1] = "2026-09-08"
    assert main(args) == EXIT_OK

    text = _log(tmp_path).read_text(encoding="utf-8")
    assert text.startswith(first), "the earlier line is evidence and is not rewritten"
    look = looks_at(read_observations(_log(tmp_path)), "syn")
    assert (look.looks, look.first, look.last) == (
        2,
        "2026-09-01T14:23:41Z",
        "2026-09-08T14:24:02Z",
    )


def test_no_log_records_nothing_and_is_therefore_not_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, entry = _manifest(tmp_path)
    _seed(tmp_path, entry)
    monkeypatch.setattr("ca_tariff_parse.cli.download", _cli_downloader(OLD))

    assert main([*_watch_args(tmp_path, manifest), "--no-log"]) == EXIT_OK

    assert not _log(tmp_path).exists()
    assert looks_at(read_observations(_log(tmp_path)), "syn").ever is False


def test_never_looked_is_not_reported_as_a_count_of_zero() -> None:
    look = looks_at([], "syn")
    assert look.ever is False
    assert look.to_json()["last_state"] == NEVER_LOOKED
    sentence = look.sentence()
    assert "has ever been examined" in sentence
    # The sentence must not read as a statement about the document's stability.
    assert "unchanged" not in sentence


def test_a_damaged_log_is_an_error_rather_than_an_empty_record(tmp_path: Path) -> None:
    path = _log(tmp_path)
    assert read_observations(path) == [], "a log that does not exist is not damaged"

    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ObservationError, match="not JSON"):
        read_observations(path)

    path.write_text(json.dumps({"schema": "something/else", "documents": []}) + "\n", "utf-8")
    with pytest.raises(ObservationError, match="states schema"):
        read_observations(path)

    path.write_text(json.dumps({"schema": OBSERVATION_SCHEMA}) + "\n", "utf-8")
    with pytest.raises(ObservationError, match="names no documents"):
        read_observations(path)

    # A line that does not say when it looked cannot separate a quiet week from
    # a missed one, which is the only question the log exists to answer.
    path.write_text(json.dumps({"schema": OBSERVATION_SCHEMA, "documents": []}) + "\n", "utf-8")
    with pytest.raises(ObservationError, match="does not say when it looked"):
        read_observations(path)


def test_the_state_reported_is_the_one_the_latest_time_states(tmp_path: Path) -> None:
    """The time is read from the record, never inferred from the file's order."""
    path = _log(tmp_path)
    later, earlier = "2026-09-08T14:24:02Z", "2026-09-01T14:23:41Z"
    append_observation(
        path, observation(later, [Outcome("syn", UNCHANGED, "")], parser_version="0.0.0")
    )
    append_observation(
        path, observation(earlier, [Outcome("syn", ERROR, "")], parser_version="0.0.0")
    )

    look = looks_at(read_observations(path), "syn")
    assert (look.first, look.last, look.last_state) == (earlier, later, UNCHANGED)


def test_the_sentence_counts_changes_and_never_counts_an_unread_document_as_unchanged() -> None:
    at = "2026-09-21T14:23:41Z"
    quiet = [Outcome("a", UNCHANGED, ""), Outcome("b", UNCHANGED, "")]
    assert observation_sentence(at, quiet) == f"looked at {at}, found 0 changes across 2 documents"

    moved = [Outcome("a", CHANGED, ""), Outcome("b", UNCHANGED, "")]
    assert observation_sentence(at, moved) == f"looked at {at}, found 1 change across 2 documents"

    unread = [Outcome("a", UNCHANGED, ""), Outcome("b", ERROR, "connection reset")]
    sentence = observation_sentence(at, unread)
    assert sentence.startswith(f"looked at {at}, found 0 changes across 2 documents; ")
    assert "1 could not be read, so whether it has changed is unknown" in sentence

    record = observation(at, unread, parser_version="0.0.0")
    assert (record["examined"], record["changes"], record["errors"]) == (2, 0, 1)
    assert record["summary"] == sentence


def test_every_document_a_run_looked_at_is_named_in_its_own_right() -> None:
    """A run that examined two of three documents cannot read as one that examined three."""
    record = observation(
        "2026-09-01",
        [Outcome("a", UNCHANGED, "pinned"), Outcome("b", ERROR, "connection reset")],
        parser_version="0.3.0",
    )
    assert [d["id"] for d in record["documents"]] == ["a", "b"]
    assert looks_at([record], "c").ever is False


# --- the scheduled workflow ------------------------------------------------------
#
# The workflow runs only on a schedule and on dispatch, so no pull request
# exercises it. These tests are its lint: they read the file and fail on the
# shapes that would lose a look or push somewhere this project does not allow.

WATCH_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tariff-watch.yml"
LOG_BRANCH = "watch-log"


def _watch_steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WATCH_WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = workflow["jobs"]["watch"]["steps"]
    return steps


def _step(name: str) -> dict[str, Any]:
    matches = [step for step in _watch_steps() if step.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}, found {len(matches)}"
    return matches[0]


def _commands(script: str) -> list[str]:
    """Shell lines with continuations joined and comments dropped.

    A flag on the second line of a wrapped command is on the command, and a
    scanner reading raw lines would miss it; a comment that names a command
    is not a command.
    """
    joined = re.sub(r"\\\n\s*", " ", script)
    lines = (line.split("#", 1)[0].strip() for line in joined.splitlines())
    return [line for line in lines if line]


def _all_commands() -> list[str]:
    return [line for step in _watch_steps() for line in _commands(str(step.get("run", "")))]


def test_the_scheduled_watch_records_every_run_and_only_the_second_look_opts_out() -> None:
    """The overview run is the run. A per-document re-run inside it is not a
    second run, and recording it would inflate the count of looks."""
    invocations = [line for line in _all_commands() if "ca-tariff-parse watch" in line]
    assert len(invocations) == 2, invocations
    overview, second_look = invocations
    assert "--summary" in overview and "--no-log" not in overview
    assert '--log "${RUNNER_TEMP}/watch-log/watch-log.jsonl"' in overview
    assert "--id" in second_look and "--no-log" in second_look


def test_the_watch_never_pushes_to_main() -> None:
    """main is protected and the watch's token cannot push to it. Every push the
    workflow makes goes to the log branch or to a proposal branch."""
    pushes = [line for line in _all_commands() if re.search(r"\bgit\s+push\b", line)]
    assert pushes, "a workflow that never pushes cannot record anything"
    targets = []
    for push in pushes:
        assert not re.search(r"(:|\s)(refs/heads/)?main\b", push), push
        match = re.search(r"\bgit\s+push\s+(?:-\S+\s+)*origin\s+([^\s;]+)", push)
        assert match, f"a push whose remote and refspec cannot be read: {push}"
        targets.append(match.group(1))
    assert set(targets) == {"HEAD:refs/heads/watch-log", '"${branch}"'}, targets


def test_the_watch_never_rewrites_a_branch() -> None:
    """A look already recorded is evidence. Nothing may force a push over it."""
    for line in _all_commands():
        if not re.search(r"\bgit\s+push\b", line):
            continue
        assert "--force" not in line and not re.search(r"\s-f\b", line), line
        assert not re.search(r"\s\+\S*:", line), f"a + refspec forces: {line}"


def test_the_record_step_appends_exactly_one_line_and_says_what_it_found() -> None:
    record = _step("Record that it looked, whatever it found")
    commands = _commands(str(record["run"]))
    script = "\n".join(commands)
    assert "git add watch-log.jsonl" in commands
    # Exactly one line added and none removed, checked before anything is committed.
    assert "$(printf '1\\t0\\twatch-log.jsonl')" in script
    assert script.index("--numstat") < script.index("git commit")
    # The sentence -- "looked at <time>, found <n> changes" -- is the commit
    # message and goes on the run page before the push is attempted, so a push
    # that fails still leaves it readable.
    assert "jq -r '.summary'" in script
    assert 'git commit -q -m "tariff-watch: ${sentence}"' in commands
    assert script.index("GITHUB_STEP_SUMMARY") < script.index("git push")
    # A run that could not push fails; it does not report success.
    assert script.rstrip().endswith("exit 1")


def test_a_missing_log_branch_fails_the_run_instead_of_starting_a_fresh_log() -> None:
    """An empty log reads as a watch that never looked. Recreating the branch
    would publish that over the record it replaced."""
    checkout = _step("Check out the observation log")
    commands = _commands(str(checkout["run"]))
    assert any("refs/heads/watch-log" in line and "git fetch" in line for line in commands)
    assert not any("--orphan" in line for line in _all_commands())
    record = _step("Record that it looked, whatever it found")
    assert "steps.log.outputs.present" in str(record.get("env", {}))
    assert 'if [ "${LOG_PRESENT}" != "true" ]; then' in _commands(str(record["run"]))


def test_a_proposal_does_not_wait_on_the_record() -> None:
    """A revision is worth a pull request even in a run that could not log itself."""
    assert _step("Propose one pull request per revised document").get("if") == "${{ !cancelled() }}"
    verdict = _step("Fail if the watch could not look at every document")
    assert verdict.get("if") == "${{ !cancelled() }}"
    names = [step.get("name") for step in _watch_steps()]
    assert names.index("Record that it looked, whatever it found") < names.index(
        "Propose one pull request per revised document"
    )


def test_the_workflow_reads_no_step_output_through_template_interpolation_in_shell() -> None:
    """Step outputs reach a shell through env:, never through ${{ }} in run:."""
    for step in _watch_steps():
        assert "${{ steps." not in str(step.get("run", "")), step.get("name")


def test_main_does_not_carry_the_observation_log() -> None:
    """The log lives on its branch. A copy on main would drift from it, so a
    local copy, made by `make watch-log` or by a local run, is ignored."""
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "data/watch-log.jsonl" in ignored
