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
    local_state,
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
    uppercased = dataclasses.replace(
        entry,
        sha256=hashlib.sha256(content).hexdigest().upper(),
        # This entry describes the synthetic body above, so it pins that
        # body's length too. What is under test here is the digest comparison.
        bytes=len(content),
    )
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


def _entry(entries, document_id: str, **changes):
    return dataclasses.replace(find(entries, document_id), **changes)


@pytest.mark.parametrize(
    "filename",
    ["../outside.pdf", "nested/../../outside.pdf", "/etc/hosts"],
)
def test_a_filename_that_leaves_the_sources_root_is_refused(
    entries, tmp_path: Path, filename: str
) -> None:
    """A manifest entry names a document inside the sources directory.

    Nothing else is a document this project knows about, and a listing that
    read one would read a file the manifest has no business naming.
    """
    with pytest.raises(SourceError, match="stay inside"):
        _entry(entries, "smud-r-tod", filename=filename).path(tmp_path)


def test_an_ordinary_filename_still_resolves_under_the_root(entries, tmp_path: Path) -> None:
    """Control case: the refusal above is about leaving the root, not about joining."""
    assert _entry(entries, "smud-r-tod").path(tmp_path) == tmp_path / "1-R-TOD.pdf"


def test_a_size_mismatch_is_reported_without_reading_the_file(
    entries, tmp_path: Path, monkeypatch
) -> None:
    """The manifest already pins the size, and a wrong size settles it.

    Hashing a document that cannot match is work done to learn nothing, and it
    is done on every listing of every present document.
    """
    entry = _entry(entries, "smud-r-tod")
    (tmp_path / entry.filename).write_bytes(b"%PDF-1.4 truncated")

    def refuse(path: Path) -> str | None:
        raise AssertionError(f"hashed {path} despite the size already disagreeing")

    monkeypatch.setattr("ca_tariff_parse.sources.safe_digest", refuse)
    assert local_state(entry, tmp_path) == "mismatched"


def test_a_document_of_the_right_size_is_still_hashed(entries, tmp_path: Path) -> None:
    """Control case: the size check screens, it does not decide.

    A file of exactly the pinned length whose bytes differ is still a
    mismatch, so the digest has to run whenever the size agrees.
    """
    entry = _entry(entries, "smud-r-tod")
    (tmp_path / entry.filename).write_bytes(b"x" * entry.bytes)
    assert local_state(entry, tmp_path) == "mismatched"


def test_the_pinned_document_reports_present(entries, tmp_path: Path) -> None:
    """Control case: a real match still reads as present."""
    body = b"example bytes"
    entry = _entry(
        entries,
        "smud-r-tod",
        sha256=hashlib.sha256(body).hexdigest(),
        bytes=len(body),
    )
    (tmp_path / entry.filename).write_bytes(body)
    assert local_state(entry, tmp_path) == "present"


def test_an_absent_document_reports_not_fetched(entries, tmp_path: Path) -> None:
    assert local_state(_entry(entries, "smud-r-tod"), tmp_path) == "not fetched"


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
    matching = dataclasses.replace(
        entry, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)
    )

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
    matching = dataclasses.replace(
        entry, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)
    )

    def fake_urlopen(request, timeout=None):  # noqa: ARG001
        if request.full_url.endswith("/robots.txt"):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)
        assert request.full_url == matching.url
        return _FakeResponse(payload)

    monkeypatch.setattr("ca_tariff_parse.sources.urllib.request.urlopen", fake_urlopen)

    path = fetch(matching, tmp_path, timeout=5.0)
    assert path.read_bytes() == payload


def test_the_listing_and_the_check_never_disagree(entries, tmp_path: Path) -> None:
    """One document, one verdict, whichever command is asked for it.

    ``sources`` reports a state and ``verify-source`` raises or does not, and
    they read the same manifest entry against the same file. If one can call a
    document present while the other calls it a mismatch, the tool contradicts
    itself and a reader has no way to tell which answer to believe.
    """
    body = b"example bytes"
    good = _entry(
        entries,
        "smud-r-tod",
        sha256=hashlib.sha256(body).hexdigest(),
        bytes=len(body),
    )
    cases = {
        "pinned": good,
        # The digest is right and the pinned length is not. Nothing verifies
        # `bytes` on the way in, so a manifest can be hand edited into this
        # state and stay in it.
        "length disagrees": dataclasses.replace(good, bytes=len(body) + 1),
        "digest disagrees": dataclasses.replace(good, sha256="0" * 64),
    }
    for name, entry in cases.items():
        (tmp_path / entry.filename).write_bytes(body)
        state = local_state(entry, tmp_path)
        try:
            verify(entry, entry.path(tmp_path))
        except SourceError:
            checked = "mismatched"
        else:
            checked = "present"
        assert state == checked, (
            f"{name}: sources reports {state!r} and verify-source reports {checked!r} "
            "for the same file"
        )


def test_a_document_of_the_wrong_pinned_length_fails_the_check(entries, tmp_path: Path) -> None:
    """The manifest pins a length as well as a digest, and both are checked.

    ``fetch`` verifies through this function, so a length the manifest states
    and the download does not have is caught when the document arrives rather
    than becoming a disagreement between two commands later.
    """
    body = b"example bytes"
    entry = _entry(
        entries,
        "smud-r-tod",
        sha256=hashlib.sha256(body).hexdigest(),
        bytes=len(body) + 1,
    )
    (tmp_path / entry.filename).write_bytes(body)
    with pytest.raises(SourceError, match="pinned length"):
        verify(entry, entry.path(tmp_path))
