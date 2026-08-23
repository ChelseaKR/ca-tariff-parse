"""The source manifest: which documents this project knows about.

The published PDFs are not redistributed from this repository. What is
committed is the manifest: the publisher, the URL, the retrieval date and the
SHA-256 of the exact bytes that were read. Anyone can fetch the document and
confirm they are holding the same file the parser was run against.

Fetching is the only part of this project that touches the network, and it is a
separate command. Parsing never does.
"""

from __future__ import annotations

import hashlib
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

DEFAULT_MANIFEST = Path("sources/sources.toml")

#: Sent when fetching. Some publishers reject a default client, and a request
#: that identifies itself is the polite way to ask.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class SourceError(RuntimeError):
    """Raised when a source document is missing, or is not the expected bytes."""


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One published document this project can parse."""

    id: str
    schedule: str
    title: str
    publisher: str
    url: str
    filename: str
    sha256: str
    retrieved_at: str
    pages: int
    bytes: int
    profile: str | None = None
    """Name of the document profile this publisher's sheets need, or ``None``
    for the default. A profile carries only what a document cannot state about
    itself; see :mod:`ca_tariff_parse.profiles`."""

    def path(self, root: Path) -> Path:
        validate_source_filename(self.filename)
        return root / self.filename


def validate_source_filename(filename: str) -> None:
    """Reject manifest filenames with path traversal or platform-dependent semantics."""
    requested = Path(filename)
    windows_requested = PureWindowsPath(filename)
    segments = filename.split("/")
    if (
        not filename
        or "\\" in filename
        or ":" in filename
        or requested.is_absolute()
        or windows_requested.is_absolute()
        or bool(windows_requested.drive)
        or any(segment in {"", "."} for segment in segments)
        or ".." in segments
    ):
        raise SourceError(
            f"manifest filename must be a portable relative path under root, got {filename!r}"
        )


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[SourceEntry]:
    """Read the manifest from disk."""
    if not path.exists():
        raise SourceError(f"source manifest not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [SourceEntry(**entry) for entry in data.get("document", [])]


def find(entries: list[SourceEntry], document_id: str) -> SourceEntry:
    for entry in entries:
        if entry.id == document_id:
            return entry
    known = ", ".join(entry.id for entry in entries) or "(none)"
    raise SourceError(f"unknown document id {document_id!r}; manifest lists: {known}")


def digest(path: Path) -> str:
    """Hash a file's bytes. Only call this once ``path.is_file()`` is known to
    be true: on a FIFO with nothing writing to it, ``read_bytes()`` blocks
    forever rather than raising, and on a directory it raises. Prefer
    :func:`safe_digest`, which checks first.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_digest(path: Path) -> str | None:
    """Like :func:`digest`, but never blocks or raises: returns ``None`` if
    ``path`` is not a readable regular file — a directory, a FIFO or other
    special file, a permission-denied file, or a path that stopped existing
    between an earlier check and this call — instead of assuming the caller
    already validated it.
    """
    if not path.is_file():
        return None
    try:
        return digest(path)
    except OSError:
        return None


def verify(entry: SourceEntry, path: Path) -> str:
    """Confirm a local file is byte for byte the document the manifest pins."""
    if not path.exists():
        raise SourceError(
            f"{path} is not present. Fetch it with: ca-tariff-parse fetch --id {entry.id}"
        )
    actual = safe_digest(path)
    # Compared case-insensitively: digest()/hexdigest() always returns
    # lowercase hex, but a hand-edited manifest entry might not.
    if actual is None or actual.lower() != entry.sha256.lower():
        raise SourceError(
            f"{path} does not match the manifest.\n"
            f"  expected sha256 {entry.sha256}\n"
            f"  actual   sha256 "
            f"{actual if actual is not None else '(not a readable regular file)'}\n"
            "The publisher may have revised the document. Do not parse it as though "
            "it were the pinned revision; update the manifest deliberately instead."
        )
    return actual


def require_https(url: str) -> None:
    """Reject any manifest URL that is not plain HTTPS.

    Without this, a manifest entry carrying ``file://`` would make the fetcher
    read a local path, and one carrying a custom scheme could reach a handler
    nobody intended. A published tariff is served over HTTPS, so anything else
    is a manifest defect rather than a case to support.
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme != "https":
        raise SourceError(f"source URLs must use https, got {scheme or 'no'} scheme in {url!r}")


def fetch(entry: SourceEntry, root: Path, *, timeout: float = 60.0) -> Path:
    """Download one document and verify it against the manifest."""
    require_https(entry.url)
    root.mkdir(parents=True, exist_ok=True)
    target = entry.path(root)
    # The scheme is pinned to https by require_https above, so the audited
    # "permitted schemes" concern behind S310 and B310 is handled.
    request = urllib.request.Request(entry.url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  # nosec B310
        payload = response.read()
    target.write_bytes(payload)
    verify(entry, target)
    return target
