"""Command line behaviour, including the coverage gate."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ca_tariff_parse.cli import EMITTED_KEYS, EXIT_COVERAGE, EXIT_ERROR, EXIT_OK, main


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


def test_sources_reports_mismatched_case_insensitively(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """digest()/hexdigest() always return lowercase hex; a hand-edited
    manifest entry with an uppercase sha256 must not be reported as
    `mismatched` for an otherwise byte-identical file."""
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
        f'sha256 = "{hashlib.sha256(good_bytes).hexdigest().upper()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 1\n"
        "bytes = 19\n",
        encoding="utf-8",
    )
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "doc.pdf").write_bytes(good_bytes)

    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "present" in out and "mismatched" not in out


def test_sources_reports_a_directory_as_mismatched_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A directory sitting at the manifest's filename is not the document
    the parser was audited against, and is not safe to open as a file — it
    must read as `mismatched`, not raise IsADirectoryError."""
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        "[[document]]\n"
        'id = "doc"\n'
        'schedule = "R"\n'
        'title = "Residential"\n'
        'publisher = "Test Utility"\n'
        'url = "https://example.com/doc.pdf"\n'
        'filename = "doc.pdf"\n'
        f'sha256 = "{hashlib.sha256(b"anything").hexdigest()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 1\n"
        "bytes = 19\n",
        encoding="utf-8",
    )
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "doc.pdf").mkdir()  # a directory, not a document

    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "mismatched" in out


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this platform")
def test_sources_reports_a_fifo_as_mismatched_without_hanging(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A FIFO with nothing writing to it must never be read: read_bytes()
    on one blocks forever. It must read as `mismatched`, not hang."""
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        "[[document]]\n"
        'id = "doc"\n'
        'schedule = "R"\n'
        'title = "Residential"\n'
        'publisher = "Test Utility"\n'
        'url = "https://example.com/doc.pdf"\n'
        'filename = "doc.pdf"\n'
        f'sha256 = "{hashlib.sha256(b"anything").hexdigest()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 1\n"
        "bytes = 19\n",
        encoding="utf-8",
    )
    directory = tmp_path / "sources"
    directory.mkdir()
    os.mkfifo(directory / "doc.pdf")  # a FIFO, not a document; nothing writes to it

    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "mismatched" in out


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


def _never_hash(path: Path) -> str | None:
    raise AssertionError(f"hashed {path} although its size already disagreed")


def _refuse_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any digest of a local document fail loudly, wherever it is called from."""
    import ca_tariff_parse.cli
    import ca_tariff_parse.sources

    for module in (ca_tariff_parse.cli, ca_tariff_parse.sources):
        if hasattr(module, "safe_digest"):
            monkeypatch.setattr(module, "safe_digest", _never_hash)


def _one_document_manifest(tmp_path: Path, body: bytes) -> Path:
    manifest = tmp_path / "sources.toml"
    manifest.write_text(
        "[[document]]\n"
        'id = "doc"\n'
        'schedule = "R"\n'
        'title = "Residential"\n'
        'publisher = "Test Utility"\n'
        'url = "https://example.com/doc.pdf"\n'
        'filename = "doc.pdf"\n'
        f'sha256 = "{hashlib.sha256(body).hexdigest()}"\n'
        'retrieved_at = "2026-01-01"\n'
        "pages = 1\n"
        f"bytes = {len(body)}\n",
        encoding="utf-8",
    )
    return manifest


def test_sources_settles_a_size_mismatch_without_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The manifest pins the length, and a file of another length cannot match.

    Hashing it reads every byte of a document to learn what its size already
    said, on every listing, for every document present.
    """
    manifest = _one_document_manifest(tmp_path, b"rate schedule bytes")
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "doc.pdf").write_bytes(b"truncated")

    _refuse_hashing(monkeypatch)
    assert main(["sources", "--manifest", str(manifest), "--dir", str(directory)]) == EXIT_OK
    assert "mismatched" in capsys.readouterr().out


def test_sources_still_hashes_a_document_of_the_pinned_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control case: the size screens, it never decides.

    A file of exactly the pinned length still has to be read, because two
    different documents of one length are exactly what a digest is for.
    """
    body = b"rate schedule bytes"
    manifest = _one_document_manifest(tmp_path, body)
    directory = tmp_path / "sources"
    directory.mkdir()
    (directory / "doc.pdf").write_bytes(b"x" * len(body))

    _refuse_hashing(monkeypatch)
    with pytest.raises(AssertionError, match="hashed"):
        main(["sources", "--manifest", str(manifest), "--dir", str(directory)])


def test_coverage_json_reports_the_figures_the_text_report_prints(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["coverage", str(complete_fixture)]) == EXIT_OK
    text = capsys.readouterr().out
    assert main(["coverage", str(complete_fixture), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    coverage = payload["coverage"]
    assert (
        f"content lines   {coverage['recognized_lines']}/{coverage['content_lines']} "
        f"recognized ({coverage['line_ratio']:.1%})" in text
    )
    assert (
        f"sections        {coverage['sections_recognized']}/{coverage['sections_total']} "
        f"fully recognized ({coverage['section_ratio']:.1%})" in text
    )
    assert f"emitted         {payload['emitted']['charges']} charge(s)" in text


def test_the_reports_name_a_failed_read_rather_than_showing_a_clean_sweep(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing read must not read as everything recognized.

    ``parse`` publishes ``fully_recognized`` false, and the text report says
    plainly that no content lines came out, because every count above it is
    zero whether the document was unreadable or genuinely empty.
    """
    unreadable = tmp_path / "UNREADABLE-doc.txt"
    unreadable.write_text("", encoding="utf-8")

    assert main(["parse", str(unreadable)]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["coverage"]["content_lines"] == 0
    assert payload["coverage"]["fully_recognized"] is False
    assert payload["charges"] == []

    assert main(["coverage", str(unreadable)]) == EXIT_OK
    text = capsys.readouterr().out
    assert "fully recognized False" in text
    assert "FAILED READ" in text
    assert "no content lines were extracted from this document" in text


def test_a_readable_document_is_not_labelled_a_failed_read(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Control: the failed-read line must not appear on a document that parsed."""
    assert main(["coverage", str(complete_fixture)]) == EXIT_OK
    text = capsys.readouterr().out
    assert "fully recognized True" in text
    assert "FAILED READ" not in text


def test_coverage_json_is_selected_from_the_parse_report_rather_than_recomputed(
    complete_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second computation of the same figures is a second thing to be wrong."""
    assert main(["parse", str(complete_fixture)]) == EXIT_OK
    full = json.loads(capsys.readouterr().out)
    assert main(["coverage", str(complete_fixture), "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)

    for key in ("schema", "parser_version", "disclaimer", "source", "coverage", "unparsed"):
        assert payload[key] == full[key], key
    assert payload["emitted"] == {key: len(full[key]) for key in EMITTED_KEYS}


def test_coverage_json_gates_on_min_coverage_the_same_way(
    unknown_fixture: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate is about the document, not about how the report is written."""
    text_code = main(["coverage", str(unknown_fixture), "--min-coverage", "0.99"])
    capsys.readouterr()
    json_code = main(["coverage", str(unknown_fixture), "--min-coverage", "0.99", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert text_code == json_code == EXIT_COVERAGE
    assert payload["unparsed"]
