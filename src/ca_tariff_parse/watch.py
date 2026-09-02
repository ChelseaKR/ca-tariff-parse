"""The watch: fetch what a publisher serves now and diff it against what was pinned.

The manifest pins each document by digest, and a mismatch is a signal to review
the revision deliberately rather than to relax the check (ADR 0003). This module
is the review's first half done in advance: it downloads the current bytes,
notices when they are not the pinned bytes, parses the revision, and writes a
value-level diff against the last parse that was reviewed. It never touches the
manifest's pinned digest on its own; the manifest change it proposes travels in
a pull request alongside the diff, for a person to merge or refuse.

What it compares against is a *baseline*: the last reviewed parse of each
pinned document, committed under ``data/parsed/`` as a projection of ``parse``'s
output with the verbatim carriers removed (``notes`` and the samples under
``unparsed``). Facts read out of a public tariff, each with its citation, are
this project's deliverable; a carrier of most of the document's prose is not
(ADR 0003, ADR 0016).
"""

from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diff import DiffError, schedule_diff
from .parser import parse_manifest_document
from .sources import SourceEntry, SourceError, digest

Json = dict[str, Any]

BASELINE_SCHEMA = "ca-tariff-parse/watch-baseline/v1"
#: What :func:`project` removes from ``parse``'s payload, and nothing else.
OMITTED = ("notes", "unparsed[].sample")
OMITTED_WHY = (
    "notes and the samples under unparsed carry the document's own prose verbatim, "
    "and most of a document the parser does not yet read would travel in them; the "
    "cited values are the deliverable, the prose is the publisher's (ADR 0003, ADR 0016)"
)

UNCHANGED = "unchanged"
CHANGED = "changed"
ERROR = "error"

#: Puts a document at ``root`` and returns its path. The real one is
#: :func:`ca_tariff_parse.sources.download`; tests pass something offline.
Downloader = Callable[[SourceEntry, Path], Path]


def project(payload: Json) -> Json:
    """The baseline shape: ``parse``'s payload without its verbatim carriers.

    Everything cited survives untouched, in the same order. ``schema`` names
    the projection so a reader cannot mistake it for a full parse, and
    ``omitted`` says what is missing and why, so its absence is a statement
    rather than a gap.
    """
    out = {key: value for key, value in payload.items() if key != "notes"}
    out["schema"] = BASELINE_SCHEMA
    out["unparsed"] = [
        {key: value for key, value in item.items() if key != "sample"}
        for item in payload.get("unparsed") or ()
    ]
    out["omitted"] = {"fields": list(OMITTED), "why": OMITTED_WHY}
    return out


def dump(payload: Json) -> str:
    """The one serialisation every baseline and report uses, so diffs are byte-stable."""
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def baseline_path(baseline_dir: Path, entry_id: str) -> Path:
    return baseline_dir / f"{entry_id}.json"


def write_baseline(baseline_dir: Path, entry_id: str, payload: Json) -> Path:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_path(baseline_dir, entry_id)
    path.write_text(dump(project(payload)), encoding="utf-8")
    return path


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the watch found for one document."""

    id: str
    state: str
    detail: str
    sha256: str | None = None
    bytes: int | None = None
    pages: int | None = None
    retrieved_at: str | None = None
    added: int = 0
    removed: int = 0
    changed: int = 0
    across_parser_versions: bool = False
    report: Path | None = None
    jsonl: Path | None = None
    baseline: Path | None = None

    @property
    def total(self) -> int:
        return self.added + self.removed + self.changed

    def to_json(self) -> Json:
        return {
            "id": self.id,
            "state": self.state,
            "detail": self.detail,
            "sha256": self.sha256,
            "bytes": self.bytes,
            "pages": self.pages,
            "retrieved_at": self.retrieved_at,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "across_parser_versions": self.across_parser_versions,
            "report": None if self.report is None else str(self.report),
            "jsonl": None if self.jsonl is None else str(self.jsonl),
            "baseline": None if self.baseline is None else str(self.baseline),
        }


def watch_entry(
    entry: SourceEntry,
    *,
    downloader: Downloader,
    baseline_dir: Path,
    changes_dir: Path,
    work_dir: Path,
    today: str,
) -> Outcome:
    """Download one document and, if the publisher revised it, diff the revision.

    A failure to download, to read, or to find the baseline is reported as an
    error, never as "unchanged": the watch has to be able to say it looked.
    """
    baseline = baseline_path(baseline_dir, entry.id)
    if not baseline.is_file():
        return Outcome(
            entry.id, ERROR, f"no baseline at {baseline}; run the baseline command first"
        )
    try:
        path = downloader(entry, work_dir)
    except (SourceError, OSError) as error:
        return Outcome(entry.id, ERROR, f"download failed: {error}")
    sha256 = digest(path)
    size = path.stat().st_size
    if sha256.lower() == entry.sha256.lower() and size == entry.bytes:
        return Outcome(entry.id, UNCHANGED, "the publisher serves the pinned bytes", sha256, size)
    revised = dataclasses.replace(entry, sha256=sha256, bytes=size, retrieved_at=today)
    try:
        parsed = parse_manifest_document(revised, path)
        new = project(parsed.to_json())
        old: Json = json.loads(baseline.read_text(encoding="utf-8"))
        delta = schedule_diff(old, new)
    except (ValueError, OSError, RuntimeError) as error:
        return Outcome(
            entry.id, ERROR, f"the revision could not be compared: {error}", sha256, size
        )
    changes_dir.mkdir(parents=True, exist_ok=True)
    report = changes_dir / f"{today}-{entry.id}.md"
    jsonl = changes_dir / f"{today}-{entry.id}.jsonl"
    report.write_text(delta.to_markdown(), encoding="utf-8")
    jsonl.write_text(delta.to_jsonl(), encoding="utf-8")
    baseline.write_text(dump(new), encoding="utf-8")
    counts = delta.summary()
    return Outcome(
        entry.id,
        CHANGED,
        f"{len(delta.changes)} value-level change(s); see {report}",
        sha256,
        size,
        parsed.source.page_count,
        today,
        counts["added"],
        counts["removed"],
        counts["changed"],
        delta.across_parser_versions,
        report,
        jsonl,
        baseline,
    )


def watch(
    entries: Iterable[SourceEntry],
    *,
    downloader: Downloader,
    baseline_dir: Path,
    changes_dir: Path,
    work_dir: Path,
    today: str,
) -> list[Outcome]:
    """Every entry, in manifest order; one entry's failure never stops the next."""
    return [
        watch_entry(
            entry,
            downloader=downloader,
            baseline_dir=baseline_dir,
            changes_dir=changes_dir,
            work_dir=work_dir,
            today=today,
        )
        for entry in entries
    ]


_PINNED = (
    ("sha256", r'^sha256 = "[^"]*"$', 'sha256 = "{}"'),
    ("retrieved_at", r'^retrieved_at = "[^"]*"$', 'retrieved_at = "{}"'),
    ("pages", r"^pages = \d+$", "pages = {}"),
    ("bytes", r"^bytes = \d+$", "bytes = {}"),
)


def manifest_with(
    text: str, entry_id: str, *, sha256: str, size: int, pages: int, retrieved_at: str
) -> str:
    """The manifest text with one entry's four pinned facts replaced, and nothing else.

    The manifest is hand maintained and carries comments that explain each
    publisher; rewriting it through a TOML serialiser would lose them. So the
    four lines are substituted in place, inside the one ``[[document]]`` block
    that names ``entry_id``, each exactly once, and the result has to load as
    TOML before it is returned.
    """
    segments = re.split(r"(?m)^(?=\[\[document\]\]$)", text)
    id_line = re.compile(rf'(?m)^id = "{re.escape(entry_id)}"$')
    hits = [index for index, segment in enumerate(segments) if id_line.search(segment)]
    if len(hits) != 1:
        raise SourceError(f"manifest names {entry_id!r} {len(hits)} time(s), not once")
    block = segments[hits[0]]
    values = {"sha256": sha256, "retrieved_at": retrieved_at, "pages": pages, "bytes": size}
    for name, pattern, template in _PINNED:
        block, count = re.subn(pattern, template.format(values[name]), block, flags=re.M)
        if count != 1:
            raise SourceError(f"manifest entry {entry_id!r} does not state {name} exactly once")
    segments[hits[0]] = block
    out = "".join(segments)
    tomllib.loads(out)
    return out


__all__ = [
    "BASELINE_SCHEMA",
    "CHANGED",
    "ERROR",
    "OMITTED",
    "UNCHANGED",
    "DiffError",
    "Downloader",
    "Outcome",
    "baseline_path",
    "dump",
    "manifest_with",
    "project",
    "watch",
    "watch_entry",
    "write_baseline",
]
