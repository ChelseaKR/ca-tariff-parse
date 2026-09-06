"""Does a parse hang together, and where can that not be decided?

`parse` is honest about what it read. It is silent about whether what it read
is *self-complete*: whether every charge priced for a "Peak" period has a
window that says when Peak is, whether a window's hours can be enumerated at
all, whether one line's unit stayed the same across its effective dates,
whether a schedule it points at is pinned anywhere.

A consumer works those out downstream, and the moment they do, they are one
step away from this project's defining defect: a missing thing read as a
value. A charge whose period has no window is not a charge that applies all
day; a residual window is not a window with no hours. `check` moves that
discovery back to the tool that still holds the citations.

Every property answers in one of three states, and the third is the one that
makes this worth writing:

    holds                    the property was tested and is true
    does not hold            the property was tested and is false; the
                             records involved are listed with citations
    cannot be established    the property was not tested, because the parse
                             does not carry what deciding it would need

There is deliberately no state meaning "no problems found". A property with
nothing to test reports :data:`CANNOT_BE_ESTABLISHED`, never
:data:`HOLDS`: a document with no charges satisfies "every charge has a
window" vacuously, and reporting that as a pass is the same error as
printing a suppressed cell as zero.

`check` adds nothing to a parse, infers nothing, and fetches nothing. It is
offline and deterministic: the same payload gives byte-identical output.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

Json = dict[str, Any]

HOLDS = "holds"
DOES_NOT_HOLD = "does not hold"
CANNOT_BE_ESTABLISHED = "cannot be established"

#: Worst first, so a summary line and an exit code agree on what matters.
STATES = (DOES_NOT_HOLD, CANNOT_BE_ESTABLISHED, HOLDS)


class CheckError(ValueError):
    """The payload is not something `check` can read."""


@dataclass(frozen=True, slots=True)
class Involved:
    """One record a property names, and the citation it was read from."""

    what: str
    cite: Json | None

    def to_json(self) -> Json:
        return {"what": self.what, "cite": self.cite}


@dataclass(frozen=True, slots=True)
class Property:
    """One named property of a parse, and what testing it established."""

    id: str
    title: str
    state: str
    detail: str
    involved: tuple[Involved, ...] = ()

    def to_json(self) -> Json:
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state,
            "detail": self.detail,
            "involved": [item.to_json() for item in self.involved],
        }


# --------------------------------------------------------------------------
# Reading the payload
# --------------------------------------------------------------------------


def _value(cell: object) -> str | None:
    """The value inside a cited envelope, or None when the field is absent."""
    if isinstance(cell, Mapping):
        found = cell.get("value")
        return found if isinstance(found, str) else None
    return None


def _cite(cell: object) -> Json | None:
    if isinstance(cell, Mapping):
        found = cell.get("provenance")
        return dict(found) if isinstance(found, Mapping) else None
    return None


def _rows(payload: Mapping[str, Any], key: str) -> list[Json]:
    found = payload.get(key)
    if found is None:
        return []
    if not isinstance(found, list):
        raise CheckError(f"{key!r} is {type(found).__name__}, not a list of records")
    return [dict(row) for row in found if isinstance(row, Mapping)]


def _locator(cite: Json | None) -> str:
    if not cite:
        return "no citation"
    locator = cite.get("locator")
    return locator if isinstance(locator, str) else "no citation"


# --------------------------------------------------------------------------
# The properties
# --------------------------------------------------------------------------


def period_window_closure(payload: Mapping[str, Any]) -> Property:
    """Every charge priced for a time-of-use period has a window naming it."""
    charges = _rows(payload, "charges")
    windows = _rows(payload, "tou_windows")
    priced = [row for row in charges if _value(row.get("tou_period"))]

    if not priced:
        why = (
            "this parse states no charges"
            if not charges
            else (f"none of the {len(charges)} charges states a time-of-use period")
        )
        return Property(
            "period-window-closure",
            "every charge priced for a period has a window defining it",
            CANNOT_BE_ESTABLISHED,
            f"{why}, so there is nothing to close. A document that prices no "
            "period does not thereby define every period it prices.",
        )
    if not windows:
        return Property(
            "period-window-closure",
            "every charge priced for a period has a window defining it",
            DOES_NOT_HOLD,
            f"{len(priced)} charge(s) are priced by period and this parse "
            "states no time-of-use windows at all",
            tuple(_charge_involved(row) for row in priced),
        )

    defined = {_value(row.get("period")) for row in windows}
    orphans = [row for row in priced if _value(row.get("tou_period")) not in defined]
    if orphans:
        names = sorted({_value(row.get("tou_period")) or "" for row in orphans})
        return Property(
            "period-window-closure",
            "every charge priced for a period has a window defining it",
            DOES_NOT_HOLD,
            f"{len(orphans)} of {len(priced)} priced charge(s) name a period no "
            f"window defines: {', '.join(repr(name) for name in names)}. The "
            "hours those prices apply to are not in this parse.",
            tuple(_charge_involved(row) for row in orphans),
        )
    return Property(
        "period-window-closure",
        "every charge priced for a period has a window defining it",
        HOLDS,
        f"all {len(priced)} priced charge(s) name one of the "
        f"{len(defined)} period(s) the windows define",
    )


def season_vocabulary(payload: Mapping[str, Any]) -> Property:
    """Do the charge tables and the window table name seasons the same way?"""
    charges = _rows(payload, "charges")
    windows = _rows(payload, "tou_windows")
    charge_seasons = {s for s in (_value(row.get("season")) for row in charges) if s}
    window_seasons = {s for s in (_value(row.get("season")) for row in windows) if s}

    title = "the seasons named on charges are the seasons the windows define"
    if not charge_seasons or not window_seasons:
        return Property(
            "season-vocabulary",
            title,
            CANNOT_BE_ESTABLISHED,
            f"{len(charge_seasons)} season(s) are named on charges and "
            f"{len(window_seasons)} on windows; with one side empty there is "
            "nothing to compare.",
        )
    shared = charge_seasons & window_seasons
    if shared == charge_seasons:
        return Property(
            "season-vocabulary",
            title,
            HOLDS,
            f"all {len(charge_seasons)} season(s) named on charges appear "
            "verbatim as window seasons",
        )
    if not shared:
        return Property(
            "season-vocabulary",
            title,
            CANNOT_BE_ESTABLISHED,
            "the two tables share no season name at all — charges say "
            f"{_listed(charge_seasons)} and windows say {_listed(window_seasons)}. "
            "The document names its seasons twice, in two vocabularies, and "
            "nothing in this parse says whether they denote the same seasons. "
            "That is a fact about the document, not a gap in it, and matching "
            "them would be inference.",
            tuple(_involved_seasons(charges, windows, charge_seasons | window_seasons)),
        )
    missing = sorted(charge_seasons - shared)
    return Property(
        "season-vocabulary",
        title,
        DOES_NOT_HOLD,
        f"the two tables share {len(shared)} season name(s), so they use one "
        f"vocabulary, but {len(missing)} season(s) named on charges are "
        f"defined by no window: {_listed(missing)}",
        tuple(_involved_seasons(charges, windows, set(missing))),
    )


def window_enumerability(payload: Mapping[str, Any]) -> Property:
    """Can the hours of every window be read off this parse?"""
    windows = _rows(payload, "tou_windows")
    title = "every window states hours that can be enumerated"
    if not windows:
        return Property(
            "window-enumerability",
            title,
            CANNOT_BE_ESTABLISHED,
            "this parse states no time-of-use windows, so there are no hours "
            "to enumerate and nothing that says there are none.",
        )

    residual = [row for row in windows if row.get("residual") is True]
    clockless = [
        row
        for row in windows
        if row.get("residual") is not True
        and not (_value(row.get("start")) and _value(row.get("end")))
    ]
    if clockless:
        return Property(
            "window-enumerability",
            title,
            DOES_NOT_HOLD,
            f"{len(clockless)} of {len(windows)} window(s) are not defined by "
            "exclusion yet state no start and end time, so their hours are "
            "neither enumerable nor declared unenumerable",
            tuple(_window_involved(row) for row in clockless),
        )
    if residual:
        return Property(
            "window-enumerability",
            title,
            CANNOT_BE_ESTABLISHED,
            f"{len(residual)} of {len(windows)} window(s) are residual: the "
            "document defines them by exclusion ('all other hours') and this "
            "parser does not invent a clock for them (ADR 0002). The day "
            "cannot be enumerated from these windows alone, by the document's "
            "own choice.",
            tuple(_window_involved(row) for row in residual),
        )
    return Property(
        "window-enumerability",
        title,
        HOLDS,
        f"all {len(windows)} window(s) state a start and an end time and none "
        "is defined by exclusion",
    )


#: The fields that say *which* priced line a charge is, as `diff.py` reads
#: them. Two charges agreeing on all of these are the same line at two
#: effective dates, and a unit that moves between them is a real signal.
_IDENTITY = ("label", "rate_category", "season", "tou_period", "applies_to", "group")


def unit_uniformity(payload: Mapping[str, Any]) -> Property:
    """One priced line keeps one unit across its effective dates."""
    charges = _rows(payload, "charges")
    title = "one priced line states one unit across its effective dates"
    if not charges:
        return Property(
            "unit-uniformity",
            title,
            CANNOT_BE_ESTABLISHED,
            "this parse states no charges, so no line has a unit to keep.",
        )

    by_identity: dict[tuple[str, ...], list[Json]] = {}
    for row in charges:
        key = tuple(_value(row.get(name)) or "" for name in _IDENTITY)
        by_identity.setdefault(key, []).append(row)

    repeated = {key: rows for key, rows in by_identity.items() if len(rows) > 1}
    if not repeated:
        return Property(
            "unit-uniformity",
            title,
            CANNOT_BE_ESTABLISHED,
            f"each of the {len(charges)} charge(s) is priced once, so no line "
            "is stated twice and no unit could have moved between statements.",
        )

    split = {key: rows for key, rows in repeated.items() if len({_unit(row) for row in rows}) > 1}
    if split:
        involved = [_charge_involved(row) for rows in split.values() for row in rows]
        return Property(
            "unit-uniformity",
            title,
            DOES_NOT_HOLD,
            f"{len(split)} priced line(s) are stated more than once with more "
            "than one unit, so two of their prices are not in the same terms",
            tuple(involved),
        )
    return Property(
        "unit-uniformity",
        title,
        HOLDS,
        f"{len(repeated)} priced line(s) are stated more than once, and each "
        "keeps one unit throughout",
    )


def cross_reference_pinned(payload: Mapping[str, Any], *, pinned: Iterable[str] | None) -> Property:
    """Is every schedule this document points at pinned in the manifest?"""
    references = _rows(payload, "cross_references")
    title = "every schedule this one points at is pinned in the manifest"
    if pinned is None:
        return Property(
            "cross-reference-pinned",
            title,
            CANNOT_BE_ESTABLISHED,
            "no manifest was given, so there is no list of pinned schedules to "
            "check against. Pass --manifest.",
        )
    codes = {code for code in pinned if code}
    if not references:
        return Property(
            "cross-reference-pinned",
            title,
            CANNOT_BE_ESTABLISHED,
            "this parse states no cross references, so nothing points anywhere "
            "and nothing says the document points nowhere.",
        )
    if not codes:
        return Property(
            "cross-reference-pinned",
            title,
            CANNOT_BE_ESTABLISHED,
            "the manifest pins no schedule codes, so a reference could not be "
            "matched against anything.",
        )

    targets = {_value(row.get("target")) for row in references} - {None}
    unpinned = sorted(str(name) for name in targets - codes)
    if unpinned:
        return Property(
            "cross-reference-pinned",
            title,
            DOES_NOT_HOLD,
            f"{len(unpinned)} of {len(targets)} referenced schedule(s) are "
            f"pinned nowhere in this manifest: {_listed(unpinned)}. A reader "
            "following one of them leaves what this repository has read.",
            tuple(
                _reference_involved(row)
                for row in references
                if _value(row.get("target")) in set(unpinned)
            ),
        )
    return Property(
        "cross-reference-pinned",
        title,
        HOLDS,
        f"all {len(targets)} referenced schedule(s) are pinned in the manifest",
    )


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def check(payload: Mapping[str, Any], *, pinned: Iterable[str] | None = None) -> list[Property]:
    """Every property, in a fixed order, over one parse payload."""
    if not isinstance(payload, Mapping):  # pragma: no cover - guarded by the CLI
        raise CheckError("a parse payload is an object")
    return [
        period_window_closure(payload),
        season_vocabulary(payload),
        window_enumerability(payload),
        unit_uniformity(payload),
        cross_reference_pinned(payload, pinned=pinned),
    ]


#: Every property `check` can report, for `--require` to be validated against.
PROPERTY_IDS = (
    "period-window-closure",
    "season-vocabulary",
    "window-enumerability",
    "unit-uniformity",
    "cross-reference-pinned",
)


def unmet(properties: Iterable[Property], required: Iterable[str]) -> list[Property]:
    """The required properties that did not come back :data:`HOLDS`.

    `cannot be established` counts as unmet, deliberately. A caller who says
    a property is required is saying a value depends on it, and "we could not
    tell" is not permission to proceed.
    """
    wanted = set(required)
    return [p for p in properties if p.id in wanted and p.state != HOLDS]


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _unit(row: Mapping[str, Any]) -> str:
    price = row.get("price")
    if isinstance(price, Mapping):
        return _value(price.get("unit")) or ""
    return ""


def _charge_label(row: Mapping[str, Any]) -> str:
    parts = [_value(row.get("label")) or "(unlabelled)"]
    for name in ("season", "tou_period", "applies_to", "group"):
        found = _value(row.get(name))
        if found:
            parts.append(found)
    effective = _value(row.get("effective_from"))
    if effective:
        parts.append(f"effective {effective}")
    unit = _unit(row)
    if unit:
        parts.append(unit)
    return " — ".join(parts)


def _charge_involved(row: Mapping[str, Any]) -> Involved:
    return Involved(_charge_label(row), _cite(row.get("label")))


def _window_involved(row: Mapping[str, Any]) -> Involved:
    season = _value(row.get("season")) or "(no season)"
    period = _value(row.get("period")) or "(no period)"
    definition = _value(row.get("definition")) or ""
    what = f"{season} — {period}"
    if definition:
        what = f"{what} — {definition}"
    return Involved(what, _cite(row.get("period")))


def _reference_involved(row: Mapping[str, Any]) -> Involved:
    target = _value(row.get("target")) or "(no target)"
    context = _value(row.get("context")) or ""
    what = f"{target} — {context}" if context else target
    return Involved(what, _cite(row.get("target")))


def _involved_seasons(
    charges: list[Json], windows: list[Json], names: set[str]
) -> Iterator[Involved]:
    seen: set[tuple[str, str]] = set()
    for row in charges:
        name = _value(row.get("season"))
        if name in names and ("charge", name) not in seen:
            seen.add(("charge", str(name)))
            yield Involved(f"named on a charge: {name}", _cite(row.get("season")))
    for row in windows:
        name = _value(row.get("season"))
        if name in names and ("window", name) not in seen:
            seen.add(("window", str(name)))
            yield Involved(f"named on a window: {name}", _cite(row.get("season")))


def _listed(names: Iterable[str]) -> str:
    return ", ".join(repr(name) for name in sorted(names))


def summary(properties: Iterable[Property]) -> dict[str, int]:
    counts = dict.fromkeys(STATES, 0)
    for prop in properties:
        counts[prop.state] += 1
    return counts


def to_text(document_id: str, properties: list[Property]) -> str:
    counts = summary(properties)
    lines = [
        f"{document_id}: {counts[HOLDS]} hold, "
        f"{counts[DOES_NOT_HOLD]} do not hold, "
        f"{counts[CANNOT_BE_ESTABLISHED]} cannot be established",
        "",
        "A property that cannot be established was not tested. It is not a "
        "pass, and it is not a finding.",
        "",
    ]
    for prop in properties:
        lines.append(f"{prop.state.upper()}  {prop.id}")
        lines.append(f"    {prop.title}")
        lines.append(f"    {prop.detail}")
        for item in prop.involved:
            lines.append(f"      - {item.what}")
            lines.append(f"        {_locator(item.cite)}")
        lines.append("")
    lines.append(
        "This is a report about one parse of a published document. It states "
        "no rate and computes nothing."
    )
    return "\n".join(lines) + "\n"


def to_json(document_id: str, properties: list[Property]) -> str:
    payload = {
        "schema": "ca-tariff-parse/check/v1",
        "document_id": document_id,
        "summary": summary(properties),
        "properties": [prop.to_json() for prop in properties],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "CANNOT_BE_ESTABLISHED",
    "DOES_NOT_HOLD",
    "HOLDS",
    "PROPERTY_IDS",
    "STATES",
    "CheckError",
    "Involved",
    "Property",
    "check",
    "cross_reference_pinned",
    "period_window_closure",
    "season_vocabulary",
    "summary",
    "to_json",
    "to_text",
    "unit_uniformity",
    "unmet",
    "window_enumerability",
]
