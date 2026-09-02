"""What changed between two parses of one schedule, value by value.

A publisher revises a schedule at the same URL, the pinned digest stops
matching, and the question is what actually changed. Comparing two parse
outputs line by line answers it badly: a price that moved from line 11 to line
12 because a row was inserted above it is not a change, and a price that kept
its line but lost a digit is. So the comparison is by *identity*, not by
position. Each record is identified by the fields that say which value it is
(a charge by its kind, label, category, season, period, applicability, group,
effective date and unit), and what is compared is the field that says what the
value is (the amount). Where a document states the same identity twice, each
occurrence is its own record, in document order, so a second occurrence
appearing later is an addition rather than a collision.

Every reported change carries both citations: where the old value was read
from, in the old bytes, and where the new one was read from, in the new. A
change that cannot point at both is not reported as a change at all, because
the reader could not check it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

Json = dict[str, Any]

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"


class DiffError(ValueError):
    """Raised when the two payloads are not two parses of one document."""


@dataclass(frozen=True, slots=True)
class Spec:
    """How records of one kind are identified, and which of their fields is the value."""

    kind: str
    key: tuple[str, ...]
    value: tuple[str, ...]


#: One spec per array in ``parse``'s payload. ``identity`` is an object, not an
#: array, and is read by :func:`_identity_records` instead.
SPECS: tuple[Spec, ...] = (
    Spec(
        "charges",
        (
            "kind",
            "label",
            "rate_category",
            "season",
            "tou_period",
            "applies_to",
            "group",
            "effective_from",
            "price.unit",
        ),
        ("price.amount", "price.currency"),
    ),
    Spec(
        "tou_windows", ("season", "period", "day_type"), ("definition", "start", "end", "residual")
    ),
    Spec("holidays", ("name",), ("month", "day_rule")),
    Spec("proration", ("circumstance",), ("basis",)),
    Spec("conditions", ("subject",), ("text",)),
    Spec("cross_references", ("target",), ("context",)),
    Spec("applicability", ("text",), ("disposition",)),
)

IDENTITY_FIELDS = ("schedule_code", "title", "resolution", "adopted", "effective")


@dataclass(frozen=True, slots=True)
class Cell:
    """One field's value and, where the field is cited, its provenance."""

    value: object
    cite: Json | None


@dataclass(frozen=True, slots=True)
class Record:
    kind: str
    key: tuple[str, ...]
    values: Mapping[str, Cell]
    anchors: Mapping[str, Cell]

    def anchor(self) -> Json | None:
        """The first citation this record carries, for an addition or removal."""
        for cell in (*self.anchors.values(), *self.values.values()):
            if cell.cite is not None:
                return cell.cite
        return None


@dataclass(frozen=True, slots=True)
class Change:
    kind: str
    key: tuple[str, ...]
    change: str
    field: str | None
    old: object
    new: object
    old_cite: Json | None
    new_cite: Json | None

    def to_json(self) -> Json:
        return {
            "kind": self.kind,
            "key": list(self.key),
            "change": self.change,
            "field": self.field,
            "old": self.old,
            "new": self.new,
            "old_cite": self.old_cite,
            "new_cite": self.new_cite,
        }


@dataclass(frozen=True, slots=True)
class Stamp:
    """What one parse says about the bytes it read and how much it read."""

    sha256: str | None
    parser_version: str | None
    retrieved_at: str | None
    page_count: int | None
    byte_size: int | None
    recognized_lines: int | None
    content_lines: int | None

    @classmethod
    def of(cls, payload: Mapping[str, Any]) -> Stamp:
        source = payload.get("source") or {}
        coverage = payload.get("coverage") or {}
        return cls(
            sha256=source.get("sha256"),
            parser_version=payload.get("parser_version"),
            retrieved_at=source.get("retrieved_at"),
            page_count=source.get("page_count"),
            byte_size=source.get("byte_size"),
            recognized_lines=coverage.get("recognized_lines"),
            content_lines=coverage.get("content_lines"),
        )

    def to_json(self) -> Json:
        return {
            "sha256": self.sha256,
            "parser_version": self.parser_version,
            "retrieved_at": self.retrieved_at,
            "page_count": self.page_count,
            "byte_size": self.byte_size,
            "recognized_lines": self.recognized_lines,
            "content_lines": self.content_lines,
        }


@dataclass(frozen=True, slots=True)
class ScheduleDiff:
    document_id: str
    old: Stamp
    new: Stamp
    changes: tuple[Change, ...]

    @property
    def across_parser_versions(self) -> bool:
        """True when the two parses were not made by the same parser.

        A diff across parser versions can contain parser changes as well as
        publisher changes, and nothing in the payloads can tell them apart.
        """
        return self.old.parser_version != self.new.parser_version

    def summary(self) -> dict[str, int]:
        counts = {ADDED: 0, REMOVED: 0, CHANGED: 0}
        for change in self.changes:
            counts[change.change] += 1
        return counts

    def to_jsonl(self) -> str:
        lines = [
            json.dumps(
                {"document_id": self.document_id, **change.to_json()},
                ensure_ascii=False,
                sort_keys=False,
            )
            for change in self.changes
        ]
        return "".join(line + "\n" for line in lines)

    def to_markdown(self) -> str:
        return "".join(_markdown(self))


def _leaf(record: Mapping[str, Any], path: str) -> Cell:
    """Read a dotted path; a cited field yields its value and provenance."""
    node: Any = record
    for part in path.split("."):
        if not isinstance(node, Mapping):
            return Cell(None, None)
        node = node.get(part)
    if isinstance(node, Mapping) and "value" in node and "provenance" in node:
        provenance = node["provenance"]
        return Cell(node["value"], dict(provenance) if isinstance(provenance, Mapping) else None)
    return Cell(node, None)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _records(payload: Mapping[str, Any], spec: Spec) -> dict[tuple[str, ...], Record]:
    """Every record of one kind, keyed by identity plus occurrence."""
    seen: dict[tuple[str, ...], int] = {}
    out: dict[tuple[str, ...], Record] = {}
    for item in payload.get(spec.kind) or ():
        anchors = {path: _leaf(item, path) for path in spec.key}
        base = tuple(_text(cell.value) for cell in anchors.values())
        occurrence = seen.get(base, 0) + 1
        seen[base] = occurrence
        key = (*base, f"#{occurrence}")
        values = {path: _leaf(item, path) for path in spec.value}
        out[key] = Record(spec.kind, key, values, anchors)
    return out


def _identity_records(payload: Mapping[str, Any]) -> dict[tuple[str, ...], Record]:
    """The identity fields as records: a null field is absent, which is a statement."""
    identity = payload.get("identity") or {}
    out: dict[tuple[str, ...], Record] = {}
    for name in IDENTITY_FIELDS:
        cell = _leaf(identity, name)
        if cell.value is None:
            continue
        key = (name, "#1")
        out[key] = Record("identity", key, {"value": cell}, {})
    for index, sheet in enumerate(identity.get("sheets") or (), start=1):
        key = ("sheets", f"#{index}")
        out[key] = Record("identity", key, {"value": _leaf({"s": sheet}, "s")}, {})
    return out


def _compare(
    old: Mapping[tuple[str, ...], Record], new: Mapping[tuple[str, ...], Record], kind: str
) -> Iterator[Change]:
    """New document order first, then what only the old document had."""
    for key, record in new.items():
        before = old.get(key)
        if before is None:
            yield Change(kind, key, ADDED, None, None, _values(record), None, record.anchor())
            continue
        for field, cell in record.values.items():
            was = before.values[field]
            if was.value != cell.value:
                yield Change(kind, key, CHANGED, field, was.value, cell.value, was.cite, cell.cite)
    for key, record in old.items():
        if key not in new:
            yield Change(kind, key, REMOVED, None, _values(record), None, record.anchor(), None)


def _values(record: Record) -> Json:
    return {field: cell.value for field, cell in record.values.items()}


def schedule_diff(old: Mapping[str, Any], new: Mapping[str, Any]) -> ScheduleDiff:
    """Compare two parses of one document."""
    old_id = (old.get("source") or {}).get("document_id")
    new_id = (new.get("source") or {}).get("document_id")
    if not old_id or old_id != new_id:
        raise DiffError(
            f"the two payloads are not parses of one document: {old_id!r} and {new_id!r}"
        )
    changes: list[Change] = list(
        _compare(_identity_records(old), _identity_records(new), "identity")
    )
    for spec in SPECS:
        changes.extend(_compare(_records(old, spec), _records(new, spec), spec.kind))
    return ScheduleDiff(str(old_id), Stamp.of(old), Stamp.of(new), tuple(changes))


# --- rendering ---------------------------------------------------------------

_TITLES = {
    "identity": "Identity",
    "charges": "Charges",
    "tou_windows": "Time-of-use windows",
    "holidays": "Holidays",
    "proration": "Proration rules",
    "conditions": "Conditions",
    "cross_references": "Cross references",
    "applicability": "Applicability",
}


def _escape(text: object) -> str:
    return _text(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _key_text(key: tuple[str, ...]) -> str:
    parts = [part for part in key[:-1] if part]
    label = " · ".join(_escape(part) for part in parts) or "(unlabelled)"
    occurrence = key[-1]
    return label if occurrence == "#1" else f"{label} ({occurrence[1:]}nd occurrence)"


def _cite_text(cite: Json | None) -> str:
    if cite is None:
        return "—"
    locator = _escape(cite.get("locator"))
    snippet = _escape(cite.get("snippet"))
    return f"`{locator}` — “{snippet}”" if snippet else f"`{locator}`"


def _value_text(value: object) -> str:
    if isinstance(value, Mapping):
        return "; ".join(f"{name}: {_escape(item)}" for name, item in value.items())
    return _escape(value)


def _ratio(stamp: Stamp) -> str:
    if stamp.recognized_lines is None or stamp.content_lines is None:
        return "not stated"
    return f"{stamp.recognized_lines}/{stamp.content_lines}"


def _markdown(delta: ScheduleDiff) -> Iterator[str]:
    counts = delta.summary()
    yield f"# {delta.document_id}: what changed\n\n"
    yield "| | before | after |\n| --- | --- | --- |\n"
    yield f"| document sha256 | `{_text(delta.old.sha256)}` | `{_text(delta.new.sha256)}` |\n"
    yield f"| retrieved | {_text(delta.old.retrieved_at)} | {_text(delta.new.retrieved_at)} |\n"
    yield f"| pages / bytes | {_text(delta.old.page_count)} / {_text(delta.old.byte_size)}"
    yield f" | {_text(delta.new.page_count)} / {_text(delta.new.byte_size)} |\n"
    yield f"| parser | {_text(delta.old.parser_version)} | {_text(delta.new.parser_version)} |\n"
    yield f"| content lines recognized | {_ratio(delta.old)} | {_ratio(delta.new)} |\n\n"
    if delta.across_parser_versions:
        yield (
            "> **Two different parser versions read these documents.** Some of what is "
            "listed below may be a change in the parser rather than in the schedule; "
            "re-parse the old bytes with the current parser before relying on any line.\n\n"
        )
    yield (
        f"**{counts[ADDED]} added, {counts[REMOVED]} removed, {counts[CHANGED]} changed.** "
        "A value that only moved on the page is not listed. Every line cites where the "
        "value was read before and after; check the citation, not this table.\n\n"
    )
    for kind, title in _TITLES.items():
        rows = [change for change in delta.changes if change.kind == kind]
        if rows:
            yield from _section(title, rows)
    yield (
        "\n_This report is a comparison of two parses of a published document. It is not "
        "rate advice and not a bill estimate, and the project is not affiliated with any "
        "utility._\n"
    )


def _section(title: str, rows: list[Change]) -> Iterator[str]:
    yield f"## {title}\n\n"
    yield "| what | change | before | after | cited before | cited after |\n"
    yield "| --- | --- | --- | --- | --- | --- |\n"
    for change in rows:
        what = _key_text(change.key)
        label = change.change if change.field is None else f"{change.change} `{change.field}`"
        yield (
            f"| {what} | {label} | {_value_text(change.old)} | {_value_text(change.new)}"
            f" | {_cite_text(change.old_cite)} | {_cite_text(change.new_cite)} |\n"
        )
    yield "\n"
