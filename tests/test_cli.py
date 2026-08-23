"""Command line behaviour, including the coverage gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ca_tariff_parse.cli import EXIT_COVERAGE, EXIT_ERROR, EXIT_OK, main


def test_parse_writes_json_to_stdout(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["parse", str(complete_fixture)]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "ca-tariff-parse/parsed-schedule/v1"
    assert payload["charges"]
    assert "not a calculation of what any customer owes" in payload["disclaimer"]


def test_parse_writes_json_to_a_file(complete_fixture: Path, tmp_path: Path) -> None:
    out = tmp_path / "parsed.json"
    assert main(["parse", str(complete_fixture), "-o", str(out)]) == EXIT_OK
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["coverage"]["fully_recognized"] is True


def test_parse_still_emits_when_coverage_is_short(
    unknown_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate must not hide the output that explains why it failed."""
    code = main(["parse", str(unknown_fixture), "--min-coverage", "0.99"])
    captured = capsys.readouterr()
    assert code == EXIT_COVERAGE
    assert json.loads(captured.out)["unparsed"]
    assert "below the required" in captured.err


def test_parse_passes_a_satisfiable_coverage_gate(unknown_fixture: Path) -> None:
    assert main(["parse", str(unknown_fixture), "--min-coverage", "0.5"]) == EXIT_OK


def test_coverage_report_lists_unparsed_sections(
    unknown_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["coverage", str(unknown_fixture)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "unparsed:" in out
    assert "SYNTHETIC" in out
    assert "not rate advice" in out


def test_coverage_gate_returns_its_own_exit_code(unknown_fixture: Path) -> None:
    assert main(["coverage", str(unknown_fixture), "--min-coverage", "1.0"]) == EXIT_COVERAGE


def test_sources_lists_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sources"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "smud-r-tod" in out
    assert "Sacramento Municipal Utility District" in out


def test_sources_reports_an_empty_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = tmp_path / "sources.toml"
    manifest.write_text("", encoding="utf-8")
    assert main(["sources", "--manifest", str(manifest)]) == EXIT_OK
    assert "no documents registered" in capsys.readouterr().out


def test_sources_distinguishes_missing_present_and_mismatched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file at the manifest's filename is only `present` if it matches the
    pinned SHA-256; a corrupted or revised download must read `mismatched`."""
    good_bytes = b"rate schedule bytes"
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        "[[document]]\n"
        'id = "doc"\n'
        'schedule = "R"\n'
        'title = "Residential"\n'
        'publisher = "Test Utility"\n'
        'url = "https://example.com/doc.pdf"\n'
        'filename = "doc.pdf"\n'
        f'sha256 = "{hashlib.sha256(good_bytes).hexdigest()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 1\n"
        "bytes = 19\n",
        encoding="utf-8",
    )
    directory = tmp_path / "sources"
    directory.mkdir()

    # Not fetched: no file at all.
    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    assert "not fetched" in capsys.readouterr().out

    # Present and matching.
    target = directory / "doc.pdf"
    target.write_bytes(good_bytes)
    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "present" in out and "mismatched" not in out

    # Present but mismatched (truncated / revised / hand-edited bytes).
    target.write_bytes(b"some other bytes")
    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "mismatched" in out and "not fetched" not in out


def test_a_missing_manifest_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sources", "--manifest", str(tmp_path / "nope.toml")]) == EXIT_ERROR
    assert "not found" in capsys.readouterr().err


def test_verify_source_reports_a_missing_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["verify-source", "--id", "smud-r-tod", "--dir", str(tmp_path)])
    assert code == EXIT_ERROR
    assert "ca-tariff-parse fetch" in capsys.readouterr().err


def test_an_unknown_document_id_is_an_error(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["parse", str(complete_fixture), "--id", "not-a-real-id"])
    assert code == EXIT_ERROR
    assert "unknown document id" in capsys.readouterr().err


def test_parsing_with_an_id_rejects_a_document_whose_bytes_do_not_match(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A manifest id is a claim about which bytes were read."""
    code = main(["parse", str(complete_fixture), "--id", "smud-r-tod"])
    assert code == EXIT_ERROR
    assert "does not match the manifest" in capsys.readouterr().err


def test_parse_reads_an_unregistered_document_with_a_named_profile(
    keyword_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A profile can be named on the command line for a file not in the manifest."""
    assert main(["parse", str(keyword_fixture), "--profile", "pge-tariff-book"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    sections = {charge["price"]["amount"]["provenance"]["section"] for charge in payload["charges"]}
    assert sections == {"RATES", "SPECIALCONDITIONS"}
    assert any(charge["price"]["amount"]["value"].startswith("-") for charge in payload["charges"])


def test_parse_without_a_profile_refuses_what_that_profile_would_have_read(
    keyword_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["parse", str(keyword_fixture)]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert not any(
        charge["price"]["amount"]["value"].startswith("-") for charge in payload["charges"]
    )
    assert {
        charge["price"]["amount"]["provenance"]["section"] for charge in payload["charges"]
    } == {"preamble"}


def test_an_unknown_profile_is_rejected_by_the_command_line(keyword_fixture: Path) -> None:
    """A misspelled profile is an error, never a silent fall back to the default."""
    with pytest.raises(SystemExit):
        main(["parse", str(keyword_fixture), "--profile", "no-such-publisher"])
