"""Audit a URDB rate record against a cited parse, field by field.

OpenEI's Utility Rate Database is the dataset most tools reach for when they
need a California tariff, and its records carry no citation to a page. A
consumer who wants to know whether a URDB number is what the utility actually
published has to open the PDF.

``reconcile`` answers that question for a record the user already holds. For
each URDB field this model has a counterpart for, it reports one of:

    confirms         the parse states this value, and here is the citation
    contradicts      the parse states values of this kind and none is this one
    no statement     the parse read no value of this kind at all

and for the rest:

    not comparable   this model cannot express the field, and why

There is deliberately no state meaning "checked out fine". A schedule whose
parse emitted no charges --- ``smud-ssr`` is one, see ADR 0011 --- reports
every price field as :data:`NO_STATEMENT`, never as confirmed and never as
contradicted. Reporting "nothing to disagree with" as agreement is the same
error as printing a suppressed cell as zero.

Two things about the comparison are worth stating plainly, because they are
the difference between an audit and a guess.

**Values are compared by membership, not by position.** A URDB record
identifies its rate periods by anonymous index, and the document identifies
them by the name it prints --- "Peak", "Off-Peak", a season's own words.
Nothing in either record states the correspondence between the two. So this
module does not pretend to align them. It asks the only question both records
can answer: does the document state this amount, in a comparable unit, on the
effective date the record names? A contradiction therefore means the two
records disagree about what the schedule prices, which is either a URDB entry
error or a gap in this parser. Both are worth knowing; neither is diagnosed
here.

**An adjustment is not a rate.** A URDB tier may carry ``adj`` beside
``rate``, and the amount a customer pays is their sum. This model records the
price the page prints. Comparing a bare ``rate`` against a printed price when
an adjustment exists would confirm a number nobody is billed, so a tier
carrying a non-zero ``adj`` is reported :data:`NOT_COMPARABLE` rather than
compared.

``reconcile`` writes nothing, fetches nothing and fills no field it did not
read. It is offline and deterministic: the same two files give byte-identical
output.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

Json = dict[str, Any]

#: The parse states this value, in a comparable unit, on the selected date.
CONFIRMS = "confirms"
#: The parse states values of this kind, and this is not one of them.
CONTRADICTS = "contradicts"
#: The parse read no value of this kind. Not agreement, and not disagreement.
NO_STATEMENT = "no statement"
#: The field has no counterpart in this model, and the reason is named.
NOT_COMPARABLE = "not comparable"

#: Worst first, so a summary line and an exit code agree on what matters.
VERDICTS = (CONTRADICTS, NO_STATEMENT, CONFIRMS, NOT_COMPARABLE)

SCHEMA_ID = "ca-tariff-parse/reconcile/v1"


class ReconcileError(ValueError):
    """The URDB record, or the parse, is not something ``reconcile`` can read."""


# --------------------------------------------------------------------------
# Units
#
# A unit family is the coarsest statement that two amounts are the same kind
# of quantity. It is deliberately coarse: the document prints its unit in its
# own words ("per metered kW/month assessed from 2:00 p.m. to 11:00 p.m.
# only"), and URDB prints a code ("$/kW"). Anything finer would be this
# project reading meaning into a publisher's phrasing.
# --------------------------------------------------------------------------

ENERGY = "per kWh"
DEMAND = "per kW"
MONTHLY = "per month"
DAILY = "per day"

FAMILIES = (ENERGY, DEMAND, MONTHLY, DAILY)


def family(unit: str | None) -> str | None:
    """Which family of quantity a unit string names, or None when unmappable.

    Order matters: "kWh" is tested before "kW" because the second is a
    substring of the first, and a per-kWh energy price read as a per-kW demand
    price would be compared against the wrong set of amounts.
    """
    if not unit:
        return None
    text = unit.casefold()
    if "kwh" in text or "kw-h" in text or "kilowatt-hour" in text:
        return ENERGY
    if "kvar" in text or "kva" in text:
        # Reactive power. Real, priced by some schedules, and not a quantity
        # any URDB field in the mapping below expresses.
        return None
    if "kw" in text or "kilowatt" in text:
        return DEMAND
    if "day" in text or "daily" in text:
        return DAILY
    if "month" in text:
        return MONTHLY
    return None


# --------------------------------------------------------------------------
# Reading the record
# --------------------------------------------------------------------------


def read_record(text: str) -> Json:
    """Read a URDB rate record from JSON text.

    Numbers are read as :class:`~decimal.Decimal` rather than float, so a rate
    printed ``0.1724`` is compared as ``0.1724`` and not as the nearest binary
    approximation of it.

    Accepts a bare rate object or the API's ``{"items": [...]}`` envelope
    holding exactly one. An envelope holding several is refused: picking one
    would be this tool deciding which record the user meant.
    """
    try:
        payload = json.loads(text, parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as exc:
        raise ReconcileError(f"the URDB record is not valid JSON: {exc}") from exc
    if isinstance(payload, Mapping) and "items" in payload:
        items = payload["items"]
        if not isinstance(items, Sequence) or isinstance(items, str):
            raise ReconcileError('"items" is present but is not a list of records')
        if len(items) != 1:
            raise ReconcileError(
                f'"items" holds {len(items)} records; reconcile compares one record '
                "against one parse. Extract the record you mean and pass that."
            )
        payload = items[0]
    if not isinstance(payload, Mapping):
        raise ReconcileError("a URDB rate record is a JSON object")
    return dict(payload)


def _decimal(node: object) -> Decimal | None:
    """A URDB scalar as an exact decimal, or None when it is not a number."""
    if isinstance(node, Decimal):
        return node
    if isinstance(node, bool):
        return None
    if isinstance(node, int):
        return Decimal(node)
    if isinstance(node, str):
        try:
            return Decimal(node.strip())
        except InvalidOperation:
            return None
    return None


# --------------------------------------------------------------------------
# Reading the parse
# --------------------------------------------------------------------------


def _value(cell: object) -> str | None:
    if isinstance(cell, Mapping):
        found = cell.get("value")
        return found if isinstance(found, str) else None
    return None


def _cite(cell: object) -> Json | None:
    if isinstance(cell, Mapping):
        found = cell.get("provenance")
        return dict(found) if isinstance(found, Mapping) else None
    return None


def _locator(cite: Json | None) -> str:
    if not cite:
        return "no citation"
    locator = cite.get("locator")
    return locator if isinstance(locator, str) else "no citation"


def _rows(payload: Mapping[str, Any], key: str) -> list[Json]:
    found = payload.get(key)
    if found is None:
        return []
    if not isinstance(found, list):
        raise ReconcileError(f"{key!r} is {type(found).__name__}, not a list of records")
    return [dict(row) for row in found if isinstance(row, Mapping)]


MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def as_date(text: str | None) -> datetime.date | None:
    """A date the document printed, read as a date, or None if it is not one.

    Returning None is a real answer: a document may state an effective date
    in words this function does not know, and treating that as a mismatch
    would manufacture a contradiction out of a reading failure.
    """
    if not text:
        return None
    cleaned = text.strip().rstrip(".").replace(",", " ")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(" ".join(cleaned.split()), fmt).date()
        except ValueError:
            continue
    return None


def urdb_date(node: object) -> datetime.date | None:
    """A URDB ``startdate``, which is either epoch seconds or a date string."""
    number = _decimal(node)
    if number is not None:
        try:
            return datetime.datetime.fromtimestamp(int(number), tz=datetime.UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(node, str):
        return as_date(node)
    return None


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """One record the parse states, and the citation it was read from."""

    what: str
    cite: Json | None

    def to_json(self) -> Json:
        return {"what": self.what, "cite": self.cite}


@dataclass(frozen=True, slots=True)
class Finding:
    """What comparing one URDB field against the parse established."""

    field: str
    stated: str | None
    verdict: str
    detail: str
    evidence: tuple[Evidence, ...] = ()

    def to_json(self) -> Json:
        return {
            "field": self.field,
            "stated": self.stated,
            "verdict": self.verdict,
            "detail": self.detail,
            "evidence": [item.to_json() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """The whole audit of one record against one parse."""

    document_id: str
    record_label: str | None
    date_note: str
    findings: tuple[Finding, ...]
    notes: tuple[str, ...]

    def summary(self) -> dict[str, int]:
        counts = dict.fromkeys(VERDICTS, 0)
        for finding in self.findings:
            counts[finding.verdict] += 1
        return counts

    def contradicted(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.verdict == CONTRADICTS)


# --------------------------------------------------------------------------
# The comparable side of the parse
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Amount:
    """One priced amount the parse states, with where it was read from."""

    value: Decimal
    printed: str
    label: str
    cite: Json | None


def _charge_label(row: Mapping[str, Any]) -> str:
    parts = [_value(row.get("label")) or "(unlabelled)"]
    for name in ("season", "tou_period", "applies_to", "group"):
        found = _value(row.get(name))
        if found:
            parts.append(found)
    effective = _value(row.get("effective_from"))
    if effective:
        parts.append(f"effective {effective}")
    return " — ".join(parts)


def _amount(row: Mapping[str, Any]) -> Amount | None:
    price = row.get("price")
    if not isinstance(price, Mapping):
        return None
    printed = _value(price.get("amount"))
    if printed is None:
        return None
    try:
        value = Decimal(printed)
    except InvalidOperation:
        return None
    unit = _value(price.get("unit")) or ""
    label = f"{_charge_label(row)} — {printed} {unit}".strip()
    return Amount(value=value, printed=printed, label=label, cite=_cite(price.get("amount")))


def amounts(charges: Iterable[Json], want: str, on: datetime.date | None) -> list[Amount]:
    """Every amount the parse states in one unit family, on one date.

    Credits are excluded from every family. A credit is a reduction the
    document prints as a negative amount; URDB carries the same idea in
    ``sell``, and matching a credit against a rate would confirm a price
    nobody is billed.
    """
    found: list[Amount] = []
    for row in charges:
        if row.get("kind") == "credit":
            continue
        price = row.get("price")
        unit = _value(price.get("unit")) if isinstance(price, Mapping) else None
        if family(unit) != want:
            continue
        if on is not None and as_date(_value(row.get("effective_from"))) != on:
            continue
        amount = _amount(row)
        if amount is not None:
            found.append(amount)
    return found


def _distinct(found: Iterable[Amount]) -> list[str]:
    seen: list[str] = []
    for amount in found:
        if amount.printed not in seen:
            seen.append(amount.printed)
    return seen


def compare(field: str, stated: Decimal, want: str, pool: list[Amount]) -> Finding:
    """One URDB amount against every comparable amount the parse states."""
    rendered = str(stated)
    if not pool:
        return Finding(
            field=field,
            stated=rendered,
            verdict=NO_STATEMENT,
            detail=(
                f"this parse states no {want} amount that could be compared. That is "
                "not agreement and not disagreement: the document may not price this, "
                "or the parser may have refused the row that does."
            ),
        )
    matching = [a for a in pool if a.value == stated]
    if matching:
        return Finding(
            field=field,
            stated=rendered,
            verdict=CONFIRMS,
            detail=f"the parse states {rendered} {want}, cited below.",
            evidence=tuple(Evidence(a.label, a.cite) for a in matching),
        )
    return Finding(
        field=field,
        stated=rendered,
        verdict=CONTRADICTS,
        detail=(
            f"the parse states {len(_distinct(pool))} distinct {want} "
            f"amount(s) — {', '.join(_distinct(pool))} — and none of them is "
            f"{rendered}. One of the two records is wrong: either the record carries "
            "a price this document does not print, or this parser did not read the "
            "row that prints it."
        ),
        evidence=tuple(Evidence(a.label, a.cite) for a in pool),
    )


# --------------------------------------------------------------------------
# The mapping, and the fields deliberately outside it
# --------------------------------------------------------------------------

#: URDB keys with no counterpart in this model, each with the reason. A key
#: absent from this table and absent from the comparisons below is still
#: reported, under a generic reason: the report is complete over the record,
#: so a field nobody mapped is visible rather than silently dropped.
UNMAPPED: dict[str, str] = {
    "energyweekdayschedule": (
        "URDB names its rate periods by index; the document names them in its own "
        "words. Neither record states the correspondence, so aligning them would "
        "be a guess, not a reading."
    ),
    "energyweekendschedule": (
        "URDB names its rate periods by index; the document names them in its own "
        "words. Neither record states the correspondence, so aligning them would "
        "be a guess, not a reading."
    ),
    "demandweekdayschedule": (
        "URDB names its demand periods by index; the document names them in its "
        "own words, and neither record states the correspondence."
    ),
    "demandweekendschedule": (
        "URDB names its demand periods by index; the document names them in its "
        "own words, and neither record states the correspondence."
    ),
    "flatdemandmonths": (
        "a month-to-period index vector; the same anonymous-index problem as the schedule matrices."
    ),
    "mincharge": (
        "this model records the priced line items a page prints. Nothing in a "
        "charge states the role 'the minimum a bill must reach', and selecting one "
        "by reading its label text would be a guess."
    ),
    "minchargeunits": "the unit of a field this model does not express.",
    "fixedchargeunits": "read as the unit of `fixedchargefirstmeter`, not compared on its own.",
    "demandrateunit": "read as the unit of the demand structures, not compared on its own.",
    "flatdemandunit": "read as the unit of `flatdemandstructure`, not compared on its own.",
    "enddate": (
        "this model reads the date a schedule or a price becomes effective. A "
        "document states when a price starts; an end date in URDB is usually the "
        "start of the record that superseded it, which is a fact about the "
        "database, not about the page."
    ),
    "startdate": "compared below.",
    "label": "the record's own identifier in URDB; the document does not carry it.",
    "utility": "the publisher's name as URDB spells it; not a value read off a page.",
    "eiaid": "an EIA utility identifier; not a value read off a page.",
    "name": "URDB's own title for the record.",
    "sector": "a URDB classification, not a statement the document makes.",
    "description": "URDB's prose summary of the record.",
    "source": "a URL URDB cites; this project cites a page, sheet, section and line.",
    "sourceparent": "a URL URDB cites.",
    "uri": "the record's address in URDB.",
    "revisions": "URDB's own edit history.",
    "approved": "a URDB moderation flag.",
    "is_default": "a URDB flag.",
    "country": "a URDB classification.",
    "voltagecategory": "a URDB classification with no cited counterpart in this model.",
    "phasewiring": "a URDB classification with no cited counterpart in this model.",
}

#: A tier's keys beside ``rate``. Named so that a reader can see they were
#: considered and why each is not folded into the comparison.
TIER_EXTRAS: dict[str, str] = {
    "max": "a tier's upper bound; this model records a price, not a tier boundary.",
    "sell": "a sell-back rate; this model records what the page prices, not export terms.",
    "unit": "read as the unit of the tier's rate, not compared on its own.",
}


def _tier_findings(
    field: str, tier: Mapping[str, Any], want: str, pool: list[Amount]
) -> list[Finding]:
    """One tier of a URDB rate structure, compared or refused with a reason."""
    rate = _decimal(tier.get("rate"))
    adj = _decimal(tier.get("adj"))
    if rate is None:
        return [
            Finding(
                field=f"{field}.rate",
                stated=None,
                verdict=NOT_COMPARABLE,
                detail="the tier states no numeric rate.",
            )
        ]
    if adj is not None and adj != 0:
        return [
            Finding(
                field=f"{field}.rate",
                stated=str(rate),
                verdict=NOT_COMPARABLE,
                detail=(
                    f"the tier states an adjustment of {adj} beside its rate. What a "
                    f"customer pays is {rate} + {adj}; what this model records is the "
                    "price the page prints. Those are not the same quantity, so the "
                    "bare rate is not compared."
                ),
            )
        ]
    return [compare(f"{field}.rate", rate, want, pool)]


def _structure_findings(
    record: Mapping[str, Any], key: str, want: str, pool: list[Amount]
) -> list[Finding]:
    """Every tier of one URDB rate structure."""
    structure = record.get(key)
    if structure is None:
        return []
    if not isinstance(structure, Sequence) or isinstance(structure, str):
        return [
            Finding(
                field=key,
                stated=None,
                verdict=NOT_COMPARABLE,
                detail=f"{key} is {type(structure).__name__}, not a list of periods.",
            )
        ]
    findings: list[Finding] = []
    for p, period in enumerate(structure):
        if not isinstance(period, Sequence) or isinstance(period, str):
            findings.append(
                Finding(
                    field=f"{key}[{p}]",
                    stated=None,
                    verdict=NOT_COMPARABLE,
                    detail="a URDB rate period is a list of tiers.",
                )
            )
            continue
        for t, tier in enumerate(period):
            if not isinstance(tier, Mapping):
                findings.append(
                    Finding(
                        field=f"{key}[{p}][{t}]",
                        stated=None,
                        verdict=NOT_COMPARABLE,
                        detail="a URDB tier is an object.",
                    )
                )
                continue
            findings.extend(_tier_findings(f"{key}[{p}][{t}]", tier, want, pool))
    return findings


# --------------------------------------------------------------------------
# The audit
# --------------------------------------------------------------------------


def _date_selection(
    record: Mapping[str, Any], charges: list[Json]
) -> tuple[datetime.date | None, str]:
    """Which effective date the priced comparisons are restricted to, and why.

    A record naming a date no charge in this parse carries does **not** narrow
    the comparison to nothing. Silently comparing against an empty set would
    turn every priced field into "no statement" and hide the disagreement that
    is actually there.
    """
    stated = urdb_date(record.get("startdate"))
    if stated is None:
        return None, (
            "The record states no readable start date, so priced fields are compared "
            "against every charge in the parse, whatever its effective date."
        )
    dates = {as_date(_value(row.get("effective_from"))) for row in charges}
    if stated in dates:
        return stated, (
            f"The record states {stated.isoformat()}. Priced fields are compared only "
            "against charges the document makes effective on that date."
        )
    return None, (
        f"The record states {stated.isoformat()}, and no charge in this parse carries "
        "that effective date. Priced fields are therefore compared against every "
        "charge, whatever its effective date — narrowing to nothing would have "
        "reported silence where there is a disagreement."
    )


def _stated_dates(payload: Mapping[str, Any]) -> list[tuple[Evidence, datetime.date | None]]:
    """Every date this parse states, with its citation and its reading."""
    found: list[tuple[Evidence, datetime.date | None]] = []
    identity = payload.get("identity")
    if isinstance(identity, Mapping):
        printed = _value(identity.get("effective"))
        if printed:
            found.append(
                (
                    Evidence(f"schedule effective {printed}", _cite(identity.get("effective"))),
                    as_date(printed),
                )
            )
    seen: set[str] = set()
    for row in _rows(payload, "charges"):
        printed = _value(row.get("effective_from"))
        if printed and printed not in seen:
            seen.add(printed)
            found.append(
                (
                    Evidence(f"a charge effective {printed}", _cite(row.get("effective_from"))),
                    as_date(printed),
                )
            )
    return found


def _startdate_finding(record: Mapping[str, Any], payload: Mapping[str, Any]) -> Finding:
    """The record's start date against every date this parse states."""
    if record.get("startdate") is None:
        return Finding("startdate", None, NO_STATEMENT, "the record states no start date.")
    stated = urdb_date(record.get("startdate"))
    if stated is None:
        return Finding(
            field="startdate",
            stated=str(record.get("startdate")),
            verdict=NOT_COMPARABLE,
            detail="the record's start date could not be read as a date.",
        )
    rendered = stated.isoformat()
    dated = _stated_dates(payload)
    if not dated:
        return Finding("startdate", rendered, NO_STATEMENT, "this parse states no date at all.")
    readable = [pair for pair in dated if pair[1] is not None]
    if not readable:
        return Finding(
            field="startdate",
            stated=rendered,
            verdict=NO_STATEMENT,
            detail=(
                "this parse states dates, but none of them could be read as a date, so "
                "none could be compared. They are listed below verbatim."
            ),
            evidence=tuple(item for item, _ in dated),
        )
    matching = [item for item, when in readable if when == stated]
    if matching:
        return Finding(
            field="startdate",
            stated=rendered,
            verdict=CONFIRMS,
            detail="the document states this date.",
            evidence=tuple(matching),
        )
    return Finding(
        field="startdate",
        stated=rendered,
        verdict=CONTRADICTS,
        detail=f"the document states {len(readable)} readable date(s) and none is {rendered}.",
        evidence=tuple(item for item, _ in readable),
    )


def _unmapped_findings(record: Mapping[str, Any], compared: set[str]) -> list[Finding]:
    """Every remaining key in the record, named rather than dropped."""
    findings: list[Finding] = []
    for key in sorted(record):
        if key in compared:
            continue
        reason = UNMAPPED.get(key, "no counterpart in this model.")
        findings.append(Finding(key, None, NOT_COMPARABLE, reason))
    return findings


def _tier_extra_notes(record: Mapping[str, Any]) -> list[str]:
    present: set[str] = set()
    for key in ("energyratestructure", "demandratestructure", "flatdemandstructure"):
        structure = record.get(key)
        if not isinstance(structure, Sequence) or isinstance(structure, str):
            continue
        for period in structure:
            if not isinstance(period, Sequence) or isinstance(period, str):
                continue
            for tier in period:
                if isinstance(tier, Mapping):
                    present.update(k for k in tier if k in TIER_EXTRAS)
    return [f"tier field {key!r}: {TIER_EXTRAS[key]}" for key in sorted(present)]


def _unstated_note(want: str, pool: list[Amount], record_values: set[Decimal]) -> list[str]:
    extra = [a.printed for a in pool if a.value not in record_values]
    if not extra:
        return []
    unique: list[str] = []
    for printed in extra:
        if printed not in unique:
            unique.append(printed)
    return [
        f"the parse states {len(unique)} {want} amount(s) the record does not carry: "
        + ", ".join(unique)
        + ". That is not a finding about the record; a URDB entry need not carry "
        "every price a schedule prints."
    ]


def reconcile(payload: Mapping[str, Any], record: Mapping[str, Any]) -> Reconciliation:
    """Audit one URDB record against one parse."""
    if not isinstance(payload, Mapping):
        raise ReconcileError("a parse payload is an object")
    charges = _rows(payload, "charges")
    on, date_note = _date_selection(record, charges)

    pools = {want: amounts(charges, want, on) for want in FAMILIES}
    findings: list[Finding] = [_startdate_finding(record, payload)]
    compared: set[str] = {"startdate"}
    seen_values: dict[str, set[Decimal]] = {want: set() for want in FAMILIES}

    fixed = _decimal(record.get("fixedchargefirstmeter"))
    if fixed is not None:
        compared.add("fixedchargefirstmeter")
        units = record.get("fixedchargeunits")
        want = family(units if isinstance(units, str) else None)
        if want is None:
            findings.append(
                Finding(
                    field="fixedchargefirstmeter",
                    stated=str(fixed),
                    verdict=NOT_COMPARABLE,
                    detail=(
                        "the record states a fixed charge but no unit this tool can "
                        f"place ({units!r}). An amount whose "
                        "quantity is unknown cannot be compared against a priced line."
                    ),
                )
            )
        else:
            findings.append(compare("fixedchargefirstmeter", fixed, want, pools[want]))
            seen_values[want].add(fixed)

    for key, want in (
        ("energyratestructure", ENERGY),
        ("demandratestructure", DEMAND),
        ("flatdemandstructure", DEMAND),
    ):
        if key in record:
            compared.add(key)
            produced = _structure_findings(record, key, want, pools[want])
            findings.extend(produced)
            for finding in produced:
                value = _decimal(finding.stated)
                if value is not None:
                    seen_values[want].add(value)

    findings.extend(_unmapped_findings(record, compared))

    notes: list[str] = list(_tier_extra_notes(record))
    for want in FAMILIES:
        if pools[want] and seen_values[want]:
            notes.extend(_unstated_note(want, pools[want], seen_values[want]))

    source = payload.get("source")
    stated_id = source.get("document_id") if isinstance(source, Mapping) else None
    label = record.get("label")
    return Reconciliation(
        document_id=stated_id if isinstance(stated_id, str) and stated_id else "(unnamed parse)",
        record_label=label if isinstance(label, str) else None,
        date_note=date_note,
        findings=tuple(findings),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

PREAMBLE = (
    "Values are compared by membership, not by position: URDB names its rate "
    "periods by index and the document names them in its own words, and neither "
    "record states the correspondence. A contradiction means the two records "
    "disagree about what this schedule prices — either a URDB entry error or a "
    "gap in this parser. This report diagnoses neither."
)

CLOSING = (
    "This is a report about one parse of a published document and one record a "
    "user supplied. It states no rate, computes nothing, and writes nothing back."
)


def render_text(result: Reconciliation) -> str:
    counts = result.summary()
    head = result.document_id
    if result.record_label:
        head = f"{head} against URDB record {result.record_label}"
    lines = [
        f"{head}: {counts[CONFIRMS]} confirmed, {counts[CONTRADICTS]} contradicted, "
        f"{counts[NO_STATEMENT]} with no statement, {counts[NOT_COMPARABLE]} not comparable",
        "",
        PREAMBLE,
        "",
        result.date_note,
        "",
    ]
    for finding in result.findings:
        stated = "" if finding.stated is None else f"  (record states {finding.stated})"
        lines.append(f"{finding.verdict.upper()}  {finding.field}{stated}")
        lines.append(f"    {finding.detail}")
        for item in finding.evidence:
            lines.append(f"      - {item.what}")
            lines.append(f"        {_locator(item.cite)}")
        lines.append("")
    for note in result.notes:
        lines.append(f"note: {note}")
    if result.notes:
        lines.append("")
    lines.append(CLOSING)
    return "\n".join(lines) + "\n"


def render_json(result: Reconciliation) -> str:
    payload = {
        "schema": SCHEMA_ID,
        "document_id": result.document_id,
        "record_label": result.record_label,
        "date_selection": result.date_note,
        "summary": result.summary(),
        "findings": [finding.to_json() for finding in result.findings],
        "notes": list(result.notes),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


__all__ = [
    "CONFIRMS",
    "CONTRADICTS",
    "DAILY",
    "DEMAND",
    "ENERGY",
    "MONTHLY",
    "NOT_COMPARABLE",
    "NO_STATEMENT",
    "SCHEMA_ID",
    "VERDICTS",
    "Amount",
    "Evidence",
    "Finding",
    "ReconcileError",
    "Reconciliation",
    "amounts",
    "as_date",
    "compare",
    "family",
    "read_record",
    "reconcile",
    "render_json",
    "render_text",
    "urdb_date",
]
