"""The watch: a revision is diffed and proposed, never absorbed; a failure is never "unchanged"."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest

from ca_tariff_parse.cli import EXIT_CHANGED, EXIT_ERROR, EXIT_OK, main
from ca_tariff_parse.parser import parse_manifest_document, parse_path
from ca_tariff_parse.sources import SourceEntry, SourceError, load_manifest
from ca_tariff_parse.watch import (
    BASELINE_SCHEMA,
    CHANGED,
    ERROR,
    UNCHANGED,
    Outcome,
    manifest_with,
    project,
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
    # The comments the manifest carries survive, because nothing re-serialised it.
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
