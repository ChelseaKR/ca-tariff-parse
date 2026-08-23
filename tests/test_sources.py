"""The source manifest pins exact bytes."""

from __future__ import annotations

import dataclasses
import hashlib
import os
from pathlib import Path

import pytest

from ca_tariff_parse.sources import (
    SourceError,
    digest,
    find,
    load_manifest,
    require_https,
    safe_digest,
    verify,
)

from .conftest import REPO_ROOT


@pytest.fixture
def entries():
    return load_manifest(REPO_ROOT / "sources" / "sources.toml")


def test_the_manifest_describes_every_document(entries) -> None:
    assert entries
    for entry in entries:
        assert entry.url.startswith("https://")
        assert len(entry.sha256) == 64
        assert entry.publisher
        assert entry.pages > 0
        assert entry.bytes > 0


def test_find_locates_a_document(entries) -> None:
    assert find(entries, "smud-r-tod").schedule == "R-TOD"


def test_find_rejects_an_unknown_id(entries) -> None:
    with pytest.raises(SourceError, match="unknown document id"):
        find(entries, "nope")


def test_a_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="manifest not found"):
        load_manifest(tmp_path / "absent.toml")


def test_verify_rejects_a_missing_file(entries, tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="not present"):
        verify(find(entries, "smud-r-tod"), tmp_path / "1-R-TOD.pdf")


def test_verify_rejects_the_wrong_bytes(entries, tmp_path: Path) -> None:
    impostor = tmp_path / "1-R-TOD.pdf"
    impostor.write_bytes(b"not the published document")
    with pytest.raises(SourceError, match="does not match the manifest"):
        verify(find(entries, "smud-r-tod"), impostor)


def test_digest_is_sha256(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"")
    assert digest(path) == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


def test_verify_rejects_a_directory_instead_of_crashing(entries, tmp_path: Path) -> None:
    impostor = tmp_path / "1-R-TOD.pdf"
    impostor.mkdir()  # a directory, not a document
    with pytest.raises(SourceError, match="does not match the manifest"):
        verify(find(entries, "smud-r-tod"), impostor)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are not available on this platform")
def test_verify_rejects_a_fifo_without_hanging(entries, tmp_path: Path) -> None:
    impostor = tmp_path / "1-R-TOD.pdf"
    os.mkfifo(impostor)  # nothing writes to it; read_bytes() on this blocks forever
    with pytest.raises(SourceError, match="does not match the manifest"):
        verify(find(entries, "smud-r-tod"), impostor)


def test_verify_matches_an_uppercase_manifest_sha256(entries, tmp_path: Path) -> None:
    # digest()/hexdigest() always return lowercase hex; a hand-edited manifest
    # entry with an uppercase sha256 must still match byte-identical content.
    entry = find(entries, "smud-r-tod")
    target = tmp_path / "1-R-TOD.pdf"
    content = b"synthetic document bytes, not the real published PDF"
    target.write_bytes(content)
    uppercased = dataclasses.replace(entry, sha256=hashlib.sha256(content).hexdigest().upper())
    assert verify(uppercased, target) == hashlib.sha256(content).hexdigest()


def test_safe_digest_returns_none_for_a_directory(tmp_path: Path) -> None:
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    assert safe_digest(directory) is None


def test_safe_digest_returns_none_for_a_missing_path(tmp_path: Path) -> None:
    assert safe_digest(tmp_path / "absent.bin") is None


def test_manifest_urls_are_https(entries) -> None:
    for entry in entries:
        require_https(entry.url)


@pytest.mark.parametrize(
    "filename",
    [
        "../escape.pdf",
        "../../etc/passwd",
        "/etc/passwd",
        "nested/../../escape.pdf",
        "C:\\Windows\\system32",
        "C:file.pdf",
        "",
        ".",
    ],
)
def test_path_rejects_path_traversal_filenames(entries, filename: str) -> None:
    """A manifest entry must not be able to traverse outside the declared root."""
    entry = dataclasses.replace(find(entries, "smud-r-tod"), filename=filename)
    with pytest.raises(SourceError, match="must be a portable relative path"):
        entry.path(Path("sources"))


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://www.example.org/schedule.pdf",
        "ftp://example.org/schedule.pdf",
        "./local.pdf",
    ],
)
def test_fetch_refuses_a_non_https_url(url: str) -> None:
    """A manifest entry must not be able to make the fetcher read a local path."""
    with pytest.raises(SourceError, match="must use https"):
        require_https(url)
