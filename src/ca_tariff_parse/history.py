"""Rebuild a value's timeline from the reports the watch already committed.

The watch writes one diff per revision under ``data/changes/`` and the
reviewed parse under ``data/parsed/``. Nothing read them back. The project's
thesis is a cited change feed, and a feed is only useful if a reader can ask
"what has this price been, and when did it move" without re-reading every pull
request.

Everything here is built from what is committed. Nothing is fetched, nothing is
parsed from a PDF, and nothing is interpolated.

Three things this refuses to do, because each would turn the record into a
story it cannot support:

*It does not smooth a gap.* Each report states the digest of the bytes on both
sides. If one report's "before" digest is not the previous report's "after"
digest, a revision is missing between them --- the watch failed to download it,
or the reports were not all committed --- and the timeline says so at that
point rather than joining the two ends.

*It does not order by filename.* A retrieval date is a fact the report states,
so it is read from the report. Two reports whose dates run backwards are
refused with both dates named, because the order they should be read in is
exactly what is in doubt.

*It does not claim one parser read the whole timeline.* Consecutive reports
carry the three-state ``parser_comparison`` that ``diff`` computes: there is no
state meaning "the same parser", because two equal release stamps cannot
establish one. A leg whose state is not ``different`` is reported as
``unstated`` or ``indeterminate``, and the conservative reading is the
fallthrough.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from .diff import (
    ADDED,
    CHANGED,
    PARSER_DIFFERENT,
    PARSER_INDETERMINATE,
    PARSER_UNSTATED,
    REMOVED,
    SPECS,
    Spec,
)

__all__ = [
    "ABSENT",
    "Event",
    "HistoryError",
    "Leg",
    "Timeline",
    "parse_match",
    "timelines",
    "to_jsonl",
    "to_text",
]

#: What a record's value is before it first appears, and after it is removed.
#: A distinct object rather than ``None`` so that "the document did not carry
#: this record" cannot be printed as an empty value.
ABSENT = "absent"

KEY_FIELDS: dict[str, tuple[str, ...]] = {spec.kind: spec.key for spec in SPECS}
#: ``identity`` is not in ``SPECS``: ``diff`` reads the identity block into
#: records of its own, keyed by the field name.
KEY_FIELDS["identity"] = ("field",)
VALUE_FIELDS: dict[str, tuple[str, ...]] = {spec.kind: spec.value for spec in SPECS}

#: ``diff`` appends an occurrence marker to every record key, so two rows a
#: document prints identically are still two records. It is part of the key and
#: not one of the identity fields.
OCCURRENCE = "occurrence"

#: Every field name any record kind can be matched on. A ``--match`` term
#: outside this set is a typo, and a typo that silently matched nothing would
#: be indistinguishable from a value the document does not state.
MATCHABLE: frozenset[str] = frozenset(
    {OCCURRENCE, "kind", *(name for fields in KEY_FIELDS.values() for name in fields)}
)

PARSER_NOTES = {
    PARSER_DIFFERENT: (
        "the two parses state different parser versions, so a change on this "
        "leg may be the parser's and not the publisher's"
    ),
    PARSER_UNSTATED: (
        "one of the two parses does not state a parser version, so whether one "
        "parser read both cannot be established"
    ),
    PARSER_INDETERMINATE: (
        "both parses state the same parser version, which proves nothing: the "
        "stamp is a release constant and every build between two releases "
        "stamps it identically"
    ),
}


class HistoryError(ValueError):
    """Raised when the committed record cannot be read as a timeline."""


@dataclass(frozen=True, slots=True)
class Event:
    """One value a record held, and the revision that put it there."""

    retrieved_at: str | None
    change: str
    field: str | None
    before: object
    after: object
    cite_before: Mapping[str, Any] | None
    cite_after: Mapping[str, Any] | None
    parser_version: str | None
    parser_version_before: str | None
    parser_comparison: str

    def to_json(self) -> dict[str, object]:
        return {
            "retrieved_at": self.retrieved_at,
            "change": self.change,
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "cite_before": self.cite_before,
            "cite_after": self.cite_after,
            "parser_version_before": self.parser_version_before,
            "parser_version": self.parser_version,
            "parser_comparison": self.parser_comparison,
        }


@dataclass(frozen=True, slots=True)
class Leg:
    """One report: the step from one committed revision to the next."""

    path: Path
    retrieved_at_before: str | None
    retrieved_at: str | None
    sha256_before: str | None
    sha256: str | None
    parser_version_before: str | None
    parser_version: str | None
    parser_comparison: str
    changes: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class Timeline:
    """Every state one record held, in order, and what is missing."""

    kind: str
    key: tuple[str, ...]
    identity: dict[str, str]
    events: tuple[Event, ...]
    current: Mapping[str, object] | None
    gaps: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "key": list(self.key),
            "identity": self.identity,
            "events": [event.to_json() for event in self.events],
            "current": self.current,
            "gaps": list(self.gaps),
        }


def parse_match(text: str) -> dict[str, str]:
    """``kind=energy_usage label=Generation`` -> a mapping.

    A value containing a space has to be quoted, and an unparseable term is an
    error rather than a term that silently matches everything.
    """
    import shlex

    criteria: dict[str, str] = {}
    for term in shlex.split(text):
        if "=" not in term:
            raise HistoryError(
                f"--match term {term!r} is not field=value; a term that cannot be "
                "read would otherwise select every record"
            )
        name, value = term.split("=", 1)
        if not name:
            raise HistoryError(f"--match term {term!r} names no field")
        criteria[name] = value
    if not criteria:
        raise HistoryError("--match selected nothing to match on")
    unknown = sorted(set(criteria) - MATCHABLE)
    if unknown:
        raise HistoryError(
            f"--match names field(s) no record is identified by: {', '.join(unknown)}. "
            f"Matchable fields are: {', '.join(sorted(MATCHABLE))}. A term that "
            "matched nothing would look exactly like a value the document does "
            "not state"
        )
    return criteria


def _identity(kind: str, key: Sequence[str]) -> dict[str, str]:
    """Name the parts of a record key, so a caller can match on them.

    The last element is ``diff``'s occurrence marker, which is part of the key
    but is not a field the document states; it is carried under its own name
    rather than folded into the last real field.
    """
    fields = KEY_FIELDS.get(kind)
    if fields is None:
        raise HistoryError(f"the reports name a record kind this model does not read: {kind!r}")
    if len(key) != len(fields) + 1:
        raise HistoryError(
            f"a {kind} record states {len(key)} key part(s) but this model "
            f"identifies one by {len(fields)} field(s) plus an occurrence marker: "
            f"{', '.join(fields)}. The report was written by a different version "
            "of the identity spec"
        )
    named = dict(zip(fields, (str(part) for part in key[:-1]), strict=True))
    named[OCCURRENCE] = str(key[-1])
    return named


def read_leg(path: Path) -> Leg:
    """One committed change report."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    changes: list[Mapping[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HistoryError(f"{path.name} line {number}: not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise HistoryError(f"{path.name} line {number}: each line must be an object")
        changes.append(loaded)
    if not changes:
        raise HistoryError(
            f"{path.name} holds no change lines. An empty report cannot say which "
            "revision it compared, so it cannot take its place in a timeline"
        )
    head = changes[0]
    required = ("retrieved_at", "sha256", "parser_comparison")
    missing = [name for name in required if name not in head]
    if missing:
        raise HistoryError(
            f"{path.name} does not state {', '.join(missing)}. Reports written "
            "before those fields existed cannot be placed in a timeline without "
            "guessing the retrieval date from the filename"
        )
    for number, change in enumerate(changes, start=1):
        for name in ("retrieved_at", "retrieved_at_before", "sha256", "sha256_before"):
            if change.get(name) != head.get(name):
                raise HistoryError(
                    f"{path.name} line {number} states a different {name} from line 1; "
                    "one report describes one comparison"
                )
    return Leg(
        path=path,
        retrieved_at_before=head.get("retrieved_at_before"),
        retrieved_at=head.get("retrieved_at"),
        sha256_before=head.get("sha256_before"),
        sha256=head.get("sha256"),
        parser_version_before=head.get("parser_version_before"),
        parser_version=head.get("parser_version"),
        parser_comparison=head.get("parser_comparison", PARSER_UNSTATED),
        changes=tuple(changes),
    )


def read_legs(changes_dir: Path, document_id: str) -> list[Leg]:
    """Every report for one document, in the order the reports themselves state."""
    paths = sorted(Path(changes_dir).glob(f"*-{document_id}.jsonl"))
    legs = [read_leg(path) for path in paths]
    for earlier, later in pairwise(legs):
        if earlier.retrieved_at is None or later.retrieved_at is None:
            raise HistoryError(
                f"{earlier.path.name} or {later.path.name} states no retrieval date, "
                "so the order to read them in cannot be established"
            )
        if later.retrieved_at < earlier.retrieved_at:
            raise HistoryError(
                f"retrieval dates run backwards: {earlier.path.name} states "
                f"{earlier.retrieved_at} and {later.path.name} states "
                f"{later.retrieved_at}. The order these should be read in is "
                "exactly what is in doubt, so nothing is assumed"
            )
    return legs


def _chain_gaps(legs: Sequence[Leg]) -> list[str]:
    """Where the committed record skips a revision."""
    gaps = []
    for earlier, later in pairwise(legs):
        if earlier.sha256 is None or later.sha256_before is None:
            gaps.append(
                f"between {earlier.retrieved_at} and {later.retrieved_at} the "
                "reports do not both state a document digest, so whether a "
                "revision is missing cannot be established"
            )
        elif earlier.sha256 != later.sha256_before:
            gaps.append(
                f"a revision is missing between {earlier.retrieved_at} and "
                f"{later.retrieved_at}: {later.path.name} compares against bytes "
                f"({later.sha256_before[:12]}…) that no committed report produced "
                f"({earlier.path.name} ends at {earlier.sha256[:12]}…)"
            )
    return gaps


def _current_values(
    baseline: Mapping[str, Any], kind: str, key: tuple[str, ...]
) -> Mapping[str, object] | None:
    """The record's value in the reviewed baseline, or None when it is not there."""
    from .diff import _records

    spec = next((item for item in SPECS if item.kind == kind), None)
    if spec is None:
        return None
    records = _records(baseline, spec)
    record = records.get(key)
    if record is None:
        return None
    return {name: cell.value for name, cell in record.values.items()}


def _matches(identity: Mapping[str, str], criteria: Mapping[str, str], kind: str) -> bool:
    for name, wanted in criteria.items():
        if name == "kind" and "kind" not in identity:
            # `kind` names the collection for every spec but `charges`, whose
            # own records also carry a `kind` field. The field wins where there
            # is one.
            if kind != wanted:
                return False
            continue
        if name not in identity:
            # This kind of record is not identified by that field, so it is not
            # what the caller asked for. Not an error: `parse_match` has already
            # refused a field no kind has at all, so this is a real field asked
            # of the wrong kind.
            return False
        if identity[name] != wanted:
            return False
    return True


def timelines(
    legs: Sequence[Leg],
    baseline: Mapping[str, Any] | None,
    criteria: Mapping[str, str] | None = None,
    *,
    kinds: Iterable[str] | None = None,
) -> list[Timeline]:
    """One timeline per record the reports or the baseline mention."""
    gaps = _chain_gaps(legs)
    if legs and baseline is not None:
        last = legs[-1]
        current_sha = (baseline.get("source") or {}).get("sha256")
        if last.sha256 and current_sha and last.sha256 != current_sha:
            gaps.append(
                f"the reviewed baseline was written from bytes ({current_sha[:12]}…) "
                f"that no committed report produced; the last report ends at "
                f"{last.sha256[:12]}… on {last.retrieved_at}"
            )

    collected: dict[tuple[str, tuple[str, ...]], list[Event]] = {}
    order: list[tuple[str, tuple[str, ...]]] = []
    for leg in legs:
        for change in leg.changes:
            kind = str(change.get("kind", ""))
            key = tuple(str(part) for part in change.get("key", ()))
            slot = (kind, key)
            if slot not in collected:
                collected[slot] = []
                order.append(slot)
            collected[slot].append(
                Event(
                    retrieved_at=leg.retrieved_at,
                    change=str(change.get("change", "")),
                    field=change.get("field"),
                    before=change.get("old", ABSENT) if change.get("change") != ADDED else ABSENT,
                    after=change.get("new", ABSENT) if change.get("change") != REMOVED else ABSENT,
                    cite_before=change.get("old_cite"),
                    cite_after=change.get("new_cite"),
                    parser_version=leg.parser_version,
                    parser_version_before=leg.parser_version_before,
                    parser_comparison=leg.parser_comparison,
                )
            )

    wanted_kinds = set(kinds) if kinds is not None else None
    built: list[Timeline] = []
    for kind, key in order:
        if wanted_kinds is not None and kind not in wanted_kinds:
            continue
        identity = _identity(kind, key)
        if criteria and not _matches(identity, criteria, kind):
            continue
        current = _current_values(baseline, kind, key) if baseline is not None else None
        built.append(
            Timeline(
                kind=kind,
                key=key,
                identity=identity,
                events=tuple(collected[(kind, key)]),
                current=current,
                gaps=tuple(gaps),
            )
        )

    if criteria and baseline is not None:
        built.extend(_unchanged_from_baseline(baseline, criteria, built, gaps, wanted_kinds))
    return built


def _unchanged_from_baseline(
    baseline: Mapping[str, Any],
    criteria: Mapping[str, str],
    already: Sequence[Timeline],
    gaps: Sequence[str],
    wanted_kinds: set[str] | None,
) -> Iterator[Timeline]:
    """Records that match but never changed: one state, from the baseline.

    A record with no events is not absent from the history; it is a record the
    publisher has not moved. Leaving it out would make "no result" mean two
    different things.
    """
    from .diff import _records

    seen = {(line.kind, line.key) for line in already}
    for spec in SPECS:
        if wanted_kinds is not None and spec.kind not in wanted_kinds:
            continue
        for key, record in _records(baseline, spec).items():
            if (spec.kind, key) in seen:
                continue
            identity = _identity(spec.kind, key)
            if not _matches(identity, criteria, spec.kind):
                continue
            yield Timeline(
                kind=spec.kind,
                key=key,
                identity=identity,
                events=(),
                current={name: cell.value for name, cell in record.values.items()},
                gaps=tuple(gaps),
            )


def _state_text(value: object) -> str:
    if value is ABSENT or value == ABSENT:
        return "(not in the document)"
    if value is None:
        return "(the document stated no value)"
    return str(value)


def _cite_text(cite: Mapping[str, Any] | None) -> str:
    if not cite:
        return "no citation"
    return str(cite.get("locator") or "no citation")


def to_text(document_id: str, built: Sequence[Timeline]) -> str:
    lines = [f"# History of {document_id}", ""]
    if not built:
        lines.append(
            "Nothing to show. Either no record matched, or no committed change "
            "report mentions a record for this document. Neither says the "
            "document has not changed: it says the record here does not cover it."
        )
        return "".join(line + "\n" for line in lines)
    gaps = built[0].gaps
    if gaps:
        lines.append("## Gaps in the committed record")
        lines.append("")
        for gap in gaps:
            lines.append(f"- {gap}")
        lines.append("")
        lines.append(
            "A gap is reported rather than joined: the values on either side of "
            "it are real, and the line between them is not."
        )
        lines.append("")
    for line in built:
        identity = ", ".join(
            f"{name}={value}"
            for name, value in line.identity.items()
            if value and name != OCCURRENCE
        )
        lines.append(f"## {line.kind}: {identity}")
        lines.append("")
        if not line.events:
            lines.append(
                "No committed report records a change to this record, so it has "
                "held one value for as long as the reports cover."
            )
        for event in line.events:
            field = f" ({event.field})" if event.field else ""
            lines.append(
                f"- **{event.retrieved_at}** {event.change}{field}: "
                f"{_state_text(event.before)} → {_state_text(event.after)}"
            )
            lines.append(f"  - before: {_cite_text(event.cite_before)}")
            lines.append(f"  - after: {_cite_text(event.cite_after)}")
            lines.append(f"  - parser: {PARSER_NOTES[event.parser_comparison]}")
        if line.current is not None:
            rendered = ", ".join(
                f"{name}={_state_text(value)}" for name, value in line.current.items()
            )
            lines.append(f"- **now** (reviewed baseline): {rendered}")
        else:
            lines.append(
                "- **now** (reviewed baseline): (not in the reviewed baseline). "
                "This is what the baseline states, not an inference from the reports."
            )
        lines.append("")
    return "".join(line + "\n" for line in lines)


def to_jsonl(document_id: str, built: Sequence[Timeline]) -> str:
    rendered = []
    for line in built:
        payload = {"document_id": document_id, **line.to_json()}
        rendered.append(json.dumps(payload, ensure_ascii=False, sort_keys=False))
    return "".join(item + "\n" for item in rendered)


def spec_for(kind: str) -> Spec:
    spec = next((item for item in SPECS if item.kind == kind), None)
    if spec is None:
        raise HistoryError(f"unknown record kind {kind!r}")
    return spec


def value_fields(kind: str) -> tuple[str, ...]:
    return VALUE_FIELDS[kind]


def changed_count(built: Sequence[Timeline]) -> int:
    return sum(1 for line in built if line.events)


CHANGE_KINDS = (ADDED, REMOVED, CHANGED)
