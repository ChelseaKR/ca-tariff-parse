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
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path

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
        """Where this document sits under ``root``.

        A manifest entry names a document inside the sources directory, and
        the manifest is hand maintained, so this is a statement about what an
        entry is allowed to mean rather than a defence against an attacker. An
        entry whose filename climbs out of the root, or is absolute, names
        something that is not one of this project's documents, and the listing
        would go on to read its bytes to compute a digest that could never
        match. Refusing here is the same kind of refusal as
        :func:`require_https`: a manifest defect, reported rather than
        followed.
        """
        target = root / self.filename
        if not target.resolve().is_relative_to(root.resolve()):
            raise SourceError(
                f"source filenames must stay inside {root}, but {self.id!r} names {self.filename!r}"
            )
        return target


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
    """Confirm a local file is byte for byte the document the manifest pins.

    Both pinned facts are checked, the digest and the length. The digest is
    what settles whether the bytes are the right ones; the length is checked
    because :func:`local_state` reads it to decide the same question, and two
    commands reading one manifest entry against one file have to reach the
    same verdict. A length the manifest states and the file does not have is
    a manifest defect, and ``fetch`` verifies through here, so it is caught
    when the document arrives rather than becoming a disagreement between two
    commands later.
    """
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
    # Readable, because safe_digest has just read it.
    size = path.stat().st_size
    if size != entry.bytes:
        raise SourceError(
            f"{path} matches the manifest digest but not its pinned length.\n"
            f"  expected {entry.bytes} bytes\n"
            f"  actual   {size} bytes\n"
            "The manifest entry disagrees with itself about one file. Correct the "
            "entry deliberately rather than relaxing either check."
        )
    return actual


def local_state(entry: SourceEntry, root: Path) -> str:
    """Whether the document is absent, the pinned bytes, or something else.

    Returns ``"not fetched"``, ``"present"`` or ``"mismatched"``. A file under
    the manifest's name is not necessarily the document the parser was audited
    against: it may be truncated, replaced by a publisher revision, hand
    edited, or not a regular file at all.

    The manifest pins the length as well as the digest, and a file of another
    length cannot be the pinned document, so the size settles those cases
    without reading the file. It only ever screens: a file of exactly the
    right length is still hashed, because two different documents of one
    length are what a digest is for.
    """
    local = entry.path(root)
    if not local.exists():
        return "not fetched"
    try:
        size = local.stat().st_size
    except OSError:
        # A path that stopped existing, or one this process may not stat.
        return "mismatched"
    if size != entry.bytes:
        return "mismatched"
    actual = safe_digest(local)
    if actual is None or actual.lower() != entry.sha256.lower():
        return "mismatched"
    return "present"


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


def _robots_allowed(url: str, *, timeout: float) -> bool:
    """True unless this host's own ``robots.txt`` disallows fetching ``url``.

    ``robots.txt`` is an opt-out a publisher has to publish: a host that has
    none, or one that cannot be reached at all, is read as allowing
    everything rather than blocking a fetch on a network hiccup that has
    nothing to do with the publisher's actual policy. Only a ``robots.txt``
    that is reached and that names the path as disallowed refuses the fetch.
    """
    # Same host and scheme as url, which the caller has already required to be
    # https before calling this, so the "permitted schemes" concern behind
    # S310 and B310 is handled exactly as it is for the document fetch below.
    parsed = urllib.parse.urlparse(url)
    robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  # nosec B310
            body = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return True
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.decode("utf-8", errors="replace").splitlines())
    return parser.can_fetch(USER_AGENT, url)


def fetch(entry: SourceEntry, root: Path, *, timeout: float = 60.0) -> Path:
    """Download one document and verify it against the manifest.

    Honours the host's own ``robots.txt`` first, as documented in the
    project README: a path the publisher has disallowed is never fetched,
    whatever the manifest says.
    """
    require_https(entry.url)
    if not _robots_allowed(entry.url, timeout=timeout):
        raise SourceError(
            f"{entry.url} is disallowed by robots.txt for this host; refusing to "
            "fetch it. Update the manifest deliberately if this document has moved."
        )
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
