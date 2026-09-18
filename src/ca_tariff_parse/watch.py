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

A run that finds nothing writes no report, and for a while that was the whole
record: an unrevised corpus and a watch that had never run produced byte
identical repositories. "No change" and "nobody looked" are different
statements and this project's defining defect is publishing the second as the
first, so every run now appends one line to an **observation log**
(:data:`OBSERVATION_SCHEMA`) naming when it looked, what it looked at and what
it found --- including, and especially, a run in which nothing moved. The
scheduled workflow keeps that log on the ``watch-log`` branch rather than on
``main``. See ADR 0019.
"""

from __future__ import annotations

import dataclasses
import json
import re
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diff import PARSER_INDETERMINATE, DiffError, schedule_diff
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

#: The observation log's payload version. One line per run of the watch.
OBSERVATION_SCHEMA = "ca-tariff-parse/watch-observation/v1"
#: What :func:`looks_at` reports for a document the log has never named. A
#: distinct string rather than a count of zero, because "looked, nothing
#: changed" and "never looked" are the two things this log exists to separate
#: and a bare ``0`` reads as the first.
NEVER_LOOKED = "never looked"

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
    """The one serialization every baseline and report uses, so diffs are byte-stable."""
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
    #: One of :data:`~ca_tariff_parse.diff.PARSER_DIFFERENT`,
    #: ``PARSER_INDETERMINATE`` or ``PARSER_UNSTATED``. There is no value
    #: meaning "one parser read both": equal ``parser_version`` strings are
    #: indeterminate, because the constant only moves at a release.
    parser_comparison: str = PARSER_INDETERMINATE
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
            "parser_comparison": self.parser_comparison,
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
        delta.parser_comparison,
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
    publisher; rewriting it through a TOML serializer would lose them. So the
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


class ObservationError(ValueError):
    """Raised when the observation log cannot be read as one."""


@dataclass(frozen=True, slots=True)
class Look:
    """What an observation log says about one document.

    ``looks`` is a count of runs that named this document, not of revisions.
    A document with ``looks == 0`` has never been examined by any run the log
    records, and that is a different statement from a document
    looked at eleven times that never moved. Keeping them apart is the whole
    reason this record exists.
    """

    document_id: str
    looks: int
    first: str | None
    last: str | None
    last_state: str | None

    @property
    def ever(self) -> bool:
        return self.looks > 0

    def to_json(self) -> Json:
        return {
            "document_id": self.document_id,
            "looks": self.looks,
            "first_looked_at": self.first,
            "last_looked_at": self.last,
            "last_state": self.last_state if self.ever else NEVER_LOOKED,
        }

    def sentence(self) -> str:
        """One sentence a reader can act on, never a bare zero."""
        if not self.ever:
            return (
                f"The observation log read here records no look at {self.document_id}. "
                "Nothing here says this document has ever been examined, so the "
                "absence of a change report is not evidence that it has not changed. "
                "The scheduled watch keeps its log on the watch-log branch; "
                "`make watch-log` fetches it."
            )
        span = (
            f"on {self.first}"
            if self.first == self.last
            else f"between {self.first} and {self.last}"
        )
        found = {
            UNCHANGED: "found the bytes the manifest pins",
            CHANGED: (
                "found the publisher serving different bytes; the change report "
                "for it is under the changes directory"
            ),
            ERROR: (
                "could not be completed, so what the publisher serves now is "
                "unknown rather than unchanged"
            ),
        }.get(self.last_state or "", f"recorded the state {self.last_state!r}")
        return (
            f"The observation log read here records {self.looks} look(s) at "
            f"{self.document_id}, {span}. The most recent, on {self.last}, {found}."
        )


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def observation_sentence(looked_at: str, outcomes: Sequence[Outcome]) -> str:
    """``looked at <time>, found <n> changes``, with what could not be read.

    Written for every run, so that a quiet week is a line that says so and a
    missed week is a line that is not there. A document the run could not
    read is never counted as unchanged: it is named as unknown.
    """
    changes = sum(outcome.state == CHANGED for outcome in outcomes)
    errors = sum(outcome.state == ERROR for outcome in outcomes)
    sentence = (
        f"looked at {looked_at}, found {_count(changes, 'change')} "
        f"across {_count(len(outcomes), 'document')}"
    )
    if errors:
        sentence += (
            f"; {errors} could not be read, so whether "
            f"{'it has' if errors == 1 else 'they have'} changed is unknown"
        )
    return sentence


def observation(looked_at: str, outcomes: Iterable[Outcome], *, parser_version: str) -> Json:
    """One run of the watch, as the line the log keeps.

    ``looked_at`` is the UTC time the run looked, to the second. The counts
    and the sentence are a convenience for a reader scanning the log. The
    per-document list is the record: every document the run looked at is
    named with what was found for it, so a run that examined six of seven
    documents cannot read as a run that examined all seven.
    """
    looked = list(outcomes)
    return {
        "schema": OBSERVATION_SCHEMA,
        "looked_at": looked_at,
        "summary": observation_sentence(looked_at, looked),
        "examined": len(looked),
        "changes": sum(outcome.state == CHANGED for outcome in looked),
        "errors": sum(outcome.state == ERROR for outcome in looked),
        "parser_version": parser_version,
        "documents": [
            {
                "id": outcome.id,
                "state": outcome.state,
                "detail": outcome.detail,
                "sha256": outcome.sha256,
                "bytes": outcome.bytes,
            }
            for outcome in looked
        ],
    }


def append_observation(path: Path, record: Json) -> Path:
    """Append one run to the log, creating it if this is the first run.

    Append rather than rewrite: an earlier run's record is evidence of a look
    that happened, and nothing here is entitled to restate it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    return path


def read_observations(path: Path) -> list[Json]:
    """Every run the log records, in the order the file states.

    A log that does not exist is an empty record and not an error: a repository
    whose watch has never run has nothing to read. A log that exists and cannot
    be read *is* an error, because the alternative is reporting a damaged
    record as an empty one, which is the confusion this file exists to end.
    """
    if not path.is_file():
        return []
    records: list[Json] = []
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not text.strip():
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as error:
            raise ObservationError(f"{path.name} line {number} is not JSON: {error}") from None
        if not isinstance(record, dict):
            raise ObservationError(f"{path.name} line {number} is not an observation record")
        if record.get("schema") != OBSERVATION_SCHEMA:
            raise ObservationError(
                f"{path.name} line {number} states schema {record.get('schema')!r}, "
                f"not {OBSERVATION_SCHEMA!r}"
            )
        if not isinstance(record.get("documents"), list):
            raise ObservationError(f"{path.name} line {number} names no documents")
        if not isinstance(record.get("looked_at"), str) or not record["looked_at"]:
            raise ObservationError(f"{path.name} line {number} does not say when it looked")
        records.append(record)
    return records


def looks_at(observations: Iterable[Json], document_id: str) -> Look:
    """What the log records for one document.

    ``last_state`` is taken from the latest ``looked_at`` the log states for
    this document, and where two lines share it, from the later of them in
    file order. The time is read from the record rather than inferred from the
    file's order, for the reason ``history`` reads a retrieval date out of a
    report rather than out of its filename. ``looked_at`` is an ISO 8601 UTC
    time, so comparing the strings compares the times.
    """
    seen: list[tuple[str, str]] = []
    for record in observations:
        date = record.get("looked_at")
        for document in record.get("documents") or ():
            if isinstance(document, dict) and document.get("id") == document_id:
                seen.append((str(date), str(document.get("state"))))
    if not seen:
        return Look(document_id, 0, None, None, None)
    dates = [date for date, _ in seen]
    last = max(dates)
    last_state = next(state for date, state in reversed(seen) if date == last)
    return Look(document_id, len(seen), min(dates), last, last_state)


__all__ = [
    "BASELINE_SCHEMA",
    "CHANGED",
    "ERROR",
    "NEVER_LOOKED",
    "OBSERVATION_SCHEMA",
    "OMITTED",
    "UNCHANGED",
    "DiffError",
    "Downloader",
    "Look",
    "ObservationError",
    "Outcome",
    "append_observation",
    "baseline_path",
    "dump",
    "looks_at",
    "manifest_with",
    "observation",
    "observation_sentence",
    "project",
    "read_observations",
    "watch",
    "watch_entry",
    "write_baseline",
]
