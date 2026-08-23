"""The source manifest pins exact bytes."""

from __future__ import annotations

import dataclasses
import hashlib
import os
import urllib.error
from pathlib import Path

import pytest

from ca_tariff_parse.sources import (
    SourceError,
    digest,
    fetch,
    find,
    load_manifest,
    require_https,
    safe_digest,
    verify,
)

from .conftest import REPO_ROOT


class _FakeResponse:
    """A stand-in for the object ``urllib.request.urlopen`` hands a ``with``."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


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


def test_fetch_refuses_a_path_robots_txt_disallows(entries, tmp_path: Path, monkeypatch) -> None:
    """The README promises retrieval honours robots.txt; ``fetch`` must too.

    A host whose robots.txt disallows every path must never reach the second
    request that would download the document itself.
    """
    entry = find(entries, "smud-r-tod")
    requested: list[str] = []

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        requested.append(request.full_url)
        if request.full_url.endswith("/robots.txt"):
            return _FakeResponse(b"User-agent: *\nDisallow: /\n")
        raise AssertionError("the document itself must not be requested")

    monkeypatch.setattr("ca_tariff_parse.sources.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(SourceError, match=r"robots\.txt"):
        fetch(entry, tmp_path, timeout=5.0)
    assert requested == ["https://www.smud.org/robots.txt"]
    assert not (tmp_path / entry.filename).exists()


def test_fetch_proceeds_when_robots_txt_allows_the_path(
    entries, tmp_path: Path, monkeypatch
) -> None:
    entry = find(entries, "smud-r-tod")
    payload = b"a stand-in for the published document, not the real bytes"
    matching = dataclasses.replace(entry, sha256=hashlib.sha256(payload).hexdigest())

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        if request.full_url.endswith("/robots.txt"):
            return _FakeResponse(b"User-agent: *\nDisallow: /mobile/\n")
        assert request.full_url == matching.url
        return _FakeResponse(payload)

    monkeypatch.setattr("ca_tariff_parse.sources.urllib.request.urlopen", fake_urlopen)

    path = fetch(matching, tmp_path, timeout=5.0)
    assert path.read_bytes() == payload


def test_fetch_proceeds_when_robots_txt_is_unreachable(
    entries, tmp_path: Path, monkeypatch
) -> None:
    """A host with no robots.txt (or one that cannot be reached) allows everything.

    robots.txt is an opt-out the publisher has to publish; a network hiccup
    fetching it must not be read as a disallow.
    """
    entry = find(entries, "smud-r-tod")
    payload = b"a stand-in for the published document, not the real bytes"
    matching = dataclasses.replace(entry, sha256=hashlib.sha256(payload).hexdigest())

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        if request.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)
        assert request.full_url == matching.url
        return _FakeResponse(payload)

    monkeypatch.setattr("ca_tariff_parse.sources.urllib.request.urlopen", fake_urlopen)

    path = fetch(matching, tmp_path, timeout=5.0)
    assert path.read_bytes() == payload
