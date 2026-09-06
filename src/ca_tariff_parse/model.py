"""Core data model.

The central rule of this project is that no emitted value may exist without a
citation back to a specific published document, page, sheet, section and line.

That rule is enforced in two independent places:

1. :class:`Cited` refuses to construct without a fully populated
   :class:`Provenance`. There is no default and no ``None`` path, so a value
   without provenance cannot be built in the first place.
2. :func:`ca_tariff_parse.audit.assert_fully_cited` walks a finished result and
   fails if it can reach a scalar that is not wrapped in a :class:`Cited` and
   not on the small allowlist of structural metadata keys.

Belt and braces is deliberate here. A tariff parser that emits a plausible
looking price nobody published would be actively harmful.

The same rule governs reading a parse back in. Every record carries a
``from_json`` that reconstructs it through the ordinary constructors, so a
committed payload with a citation missing, malformed, or disagreeing with
itself raises :class:`ProvenanceError` instead of yielding a partially cited
object. Reconstruction is not a courtesy re-read of a trusted file: it is the
schema's constraints expressed in code, applied to bytes this process did not
write.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Self

SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

#: Section identifiers look like "II.A" or "V.A.1" or "header".
SECTION_ID_RE = re.compile(r"\A[A-Za-z0-9]+(\.[A-Za-z0-9]+)*\Z")


class ProvenanceError(ValueError):
    """Raised when a citation is missing, malformed or incomplete."""


class SchemaError(ValueError):
    """Raised when a payload is not the shape this version of the model reads.

    Distinct from :class:`ProvenanceError`, which means the payload was the
    right shape and the citation in it was not good enough.
    """


#: Keys ``to_json`` writes that are derived from other keys rather than stored.
#: They are re-derived on read and cross-checked, never trusted.
DERIVED_KEYS: dict[str, frozenset[str]] = {
    "provenance": frozenset({"locator"}),
    "coverage": frozenset({"line_ratio", "section_ratio", "fully_recognized"}),
    "unparsed": frozenset({"span"}),
}


def _mapping(node: object, path: str) -> Mapping[str, Any]:
    if not isinstance(node, Mapping):
        raise SchemaError(f"{path} must be an object, got {type(node).__name__}")
    return node


def _sequence(node: object, path: str) -> list[Any]:
    if not isinstance(node, list):
        raise SchemaError(f"{path} must be an array, got {type(node).__name__}")
    return node


def _keys(
    node: Mapping[str, Any],
    path: str,
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    derived: Iterable[str] = (),
) -> None:
    """Reject a payload whose key set is not the one this model knows.

    Strict in both directions on purpose. A missing key is a value the writer
    had and this reader would silently drop; an unknown key is a value this
    reader does not understand and would silently discard. Either way a caller
    would receive an object that looks complete and is not, which is the
    failure this package exists to make impossible.
    """
    present = set(node)
    missing = sorted(set(required) - present)
    if missing:
        raise SchemaError(f"{path} is missing required key(s): {', '.join(missing)}")
    unknown = sorted(present - set(required) - set(optional) - set(derived))
    if unknown:
        raise SchemaError(
            f"{path} carries key(s) this model does not read: {', '.join(unknown)}. "
            "Reading it would drop them silently."
        )


def _str(node: Mapping[str, Any], key: str, path: str) -> str:
    value = node[key]
    if not isinstance(value, str):
        raise SchemaError(f"{path}.{key} must be a string, got {type(value).__name__}")
    return value


def _opt_str(node: Mapping[str, Any], key: str, path: str) -> str | None:
    if node.get(key) is None:
        return None
    return _str(node, key, path)


def _int(node: Mapping[str, Any], key: str, path: str) -> int:
    value = node[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise SchemaError(f"{path}.{key} must be an integer, got {type(value).__name__}")
    return value


def _opt_int(node: Mapping[str, Any], key: str, path: str) -> int | None:
    if node.get(key) is None:
        return None
    return _int(node, key, path)


def _bool(node: Mapping[str, Any], key: str, path: str) -> bool:
    value = node[key]
    if not isinstance(value, bool):
        raise SchemaError(f"{path}.{key} must be a boolean, got {type(value).__name__}")
    return value


class WithheldError(LookupError):
    """Raised when a caller queries records a payload deliberately omitted.

    A watch baseline drops the document's verbatim prose on purpose (ADR 0003,
    ADR 0016). The result is an empty collection that does not mean "the
    document states none of these", and answering a query against it with
    "none" would publish an omission as a measurement.
    """


class Records[R](tuple[R, ...]):
    """A tuple of records with one filter on it.

    ``where`` exists so a caller can select without re-implementing the
    difference between a cited field and a structural one. It never
    synthesises a record and never widens a match: an unknown field name is an
    error rather than an empty result, because an empty result reads as "this
    schedule states nothing of the kind" and a typo is not that.

    A collection can also be *withheld*, meaning the payload it came from
    omitted it rather than reporting it empty. A withheld collection is still
    an empty tuple --- there is nothing to iterate --- but it refuses to be
    queried, and says why.
    """

    _withheld: str | None

    def __new__(cls, iterable: Iterable[R] = (), withheld: str | None = None) -> Records[R]:
        made = super().__new__(cls, iterable)
        made._withheld = withheld
        if withheld is not None and made:
            raise ValueError("a withheld collection cannot also hold records")
        return made

    @property
    def withheld(self) -> str | None:
        """Why this collection was omitted, or ``None`` if it was reported."""
        return self._withheld

    def __repr__(self) -> str:
        if self._withheld is not None:
            return f"Records(withheld: {self._withheld})"
        return f"Records({list(self)!r})"

    def where(self, **criteria: object) -> Records[R]:
        """Records for which every named field equals the given value.

        A field holding a :class:`Cited` is compared on its ``value``. A field
        that is absent on the record matches only the criterion ``None``, so
        ``where(season=None)`` selects the charges that state no season and is
        a different question from ``where(season="Summer")``.
        """
        if self._withheld is not None:
            raise WithheldError(
                f"this collection was omitted from the payload it was loaded from "
                f"({self._withheld}); it is not empty, it is unreported, and a "
                "query against it has no answer"
            )
        if not criteria:
            return Records(self)
        selected = []
        for record in self:
            if all(_matches(record, name, wanted) for name, wanted in criteria.items()):
                selected.append(record)
        return Records(selected)


def _matches(record: object, name: str, wanted: object) -> bool:
    if not hasattr(record, name):
        raise AttributeError(
            f"{type(record).__name__} has no field {name!r}; "
            f"it states {', '.join(sorted(_field_names(record)))}"
        )
    held = getattr(record, name)
    if held is None:
        return wanted is None
    if isinstance(held, Cited):
        return bool(held.value == wanted)
    return bool(held == wanted)


def _field_names(record: object) -> tuple[str, ...]:
    fields = getattr(type(record), "__dataclass_fields__", {})
    return tuple(fields)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where in a published document a single value came from.

    Every field is required. ``document_sha256`` pins the exact bytes that were
    read, so a citation cannot silently drift onto a different revision of the
    same document.
    """

    document_id: str
    document_sha256: str
    page: int
    sheet: str | None
    section: str
    line: int
    snippet: str
    end_line: int | None = None
    """Last line of the cited unit when it spans several lines.

    A table cell cites a single line. A prose item cites the whole paragraph,
    which the publisher wrapped across several lines; ``line`` is the first and
    ``end_line`` the last, and ``snippet`` carries the reflowed text.
    """

    def __post_init__(self) -> None:
        if not self.document_id or not self.document_id.strip():
            raise ProvenanceError("provenance.document_id must be a non-empty string")
        if not SHA256_RE.match(self.document_sha256 or ""):
            raise ProvenanceError(
                "provenance.document_sha256 must be 64 lowercase hex characters, "
                f"got {self.document_sha256!r}"
            )
        if not isinstance(self.page, int) or isinstance(self.page, bool) or self.page < 1:
            raise ProvenanceError(f"provenance.page must be a 1-based integer, got {self.page!r}")
        if self.sheet is not None and not self.sheet.strip():
            raise ProvenanceError("provenance.sheet must be None or a non-empty string")
        if not self.section or not SECTION_ID_RE.match(self.section):
            raise ProvenanceError(
                f"provenance.section must be a dotted section id, got {self.section!r}"
            )
        if not isinstance(self.line, int) or isinstance(self.line, bool) or self.line < 1:
            raise ProvenanceError(f"provenance.line must be a 1-based integer, got {self.line!r}")
        if not self.snippet or not self.snippet.strip():
            raise ProvenanceError(
                "provenance.snippet must quote the source line verbatim and cannot be empty"
            )
        if self.end_line is not None and (
            not isinstance(self.end_line, int)
            or isinstance(self.end_line, bool)
            or self.end_line < self.line
        ):
            raise ProvenanceError(
                f"provenance.end_line must be >= line ({self.line}), got {self.end_line!r}"
            )

    @property
    def locator(self) -> str:
        """A short human readable citation, e.g. ``smud-r-tod p.2 sheet R-TOD-2 II.A L14``."""
        sheet = f" sheet {self.sheet}" if self.sheet else ""
        span = (
            f"L{self.line}"
            if self.end_line in (None, self.line)
            else (f"L{self.line}-{self.end_line}")
        )
        return f"{self.document_id} p.{self.page}{sheet} {self.section} {span}"

    def to_json(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "document_sha256": self.document_sha256,
            "page": self.page,
            "sheet": self.sheet,
            "section": self.section,
            "line": self.line,
            "end_line": self.end_line,
            "snippet": self.snippet,
            "locator": self.locator,
        }

    @classmethod
    def from_json(cls, node: object, path: str = "provenance") -> Self:
        """Rebuild a citation from its serialised form.

        ``locator`` is derived, so it is not read as data. It is compared
        against the locator this citation actually produces, and a payload
        whose locator disagrees with its own page, sheet, section and line is
        refused: one of the two is wrong and there is no way to tell which.
        """
        node = _mapping(node, path)
        _keys(
            node,
            path,
            required=(
                "document_id",
                "document_sha256",
                "page",
                "sheet",
                "section",
                "line",
                "snippet",
            ),
            optional=("end_line",),
            derived=DERIVED_KEYS["provenance"],
        )
        built = cls(
            document_id=_str(node, "document_id", path),
            document_sha256=_str(node, "document_sha256", path),
            page=_int(node, "page", path),
            sheet=_opt_str(node, "sheet", path),
            section=_str(node, "section", path),
            line=_int(node, "line", path),
            snippet=_str(node, "snippet", path),
            end_line=_opt_int(node, "end_line", path),
        )
        stated = node.get("locator")
        if stated is not None and stated != built.locator:
            raise ProvenanceError(
                f"{path}.locator says {stated!r} but the citation's own page, "
                f"sheet, section and line read {built.locator!r}"
            )
        return built


@dataclass(frozen=True, slots=True)
class Cited[T: (str, int, float, bool)]:
    """A single scalar together with the citation that justifies it.

    ``Cited`` is the only way a value reaches the output. Constructing one
    without a valid :class:`Provenance` raises :class:`ProvenanceError`.
    """

    value: T
    provenance: Provenance

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            raise ProvenanceError(
                "Cited requires a Provenance instance; a value with no citation "
                f"cannot be emitted (got {type(self.provenance).__name__})"
            )
        if self.value is None:
            raise ProvenanceError("Cited.value cannot be None; omit the field instead")

    def to_json(self) -> dict[str, object]:
        return {"value": self.value, "provenance": self.provenance.to_json()}

    @classmethod
    def from_json(cls, node: object, path: str) -> Cited[Any]:
        node = _mapping(node, path)
        _keys(node, path, required=("value", "provenance"))
        value = node["value"]
        if not isinstance(value, str | int | float | bool):
            raise SchemaError(
                f"{path}.value must be a scalar the model can carry, got {type(value).__name__}"
            )
        return Cited(value, Provenance.from_json(node["provenance"], f"{path}.provenance"))


def _cited(node: Mapping[str, Any], key: str, path: str) -> Cited[Any]:
    if key not in node:
        raise SchemaError(f"{path} is missing required key: {key}")
    return Cited.from_json(node[key], f"{path}.{key}")


def _opt_cited(node: Mapping[str, Any], key: str, path: str) -> Cited[Any] | None:
    if node.get(key) is None:
        return None
    return Cited.from_json(node[key], f"{path}.{key}")


# ---------------------------------------------------------------------------
# Tariff structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Money:
    """A price or credit read from a rate table cell.

    ``amount`` is a string, not a float. Tariff prices are exact decimal
    quantities printed to a fixed number of places and turning ``$0.1724`` into
    a binary float loses that exactness. Callers that want arithmetic should
    build a :class:`decimal.Decimal` from ``amount``.
    """

    amount: Cited[str]
    currency: str
    unit: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {
            "amount": self.amount.to_json(),
            "currency": self.currency,
            "unit": self.unit.to_json(),
        }

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("amount", "currency", "unit"))
        amount = _cited(node, "amount", path)
        if not isinstance(amount.value, str):
            raise SchemaError(
                f"{path}.amount.value must stay a string; a tariff price is an exact "
                f"decimal and {type(amount.value).__name__} would lose that"
            )
        return cls(
            amount=amount,
            currency=_str(node, "currency", path),
            unit=_cited(node, "unit", path),
        )


@dataclass(frozen=True, slots=True)
class Charge:
    """One priced line item within a rate schedule."""

    label: Cited[str]
    kind: str
    price: Money
    effective_from: Cited[str]
    rate_category: Cited[str] | None = None
    season: Cited[str] | None = None
    tou_period: Cited[str] | None = None
    applies_to: Cited[str] | None = None
    """The column heading this price sat under, when one charge is priced
    across several categories at once, for example a service voltage level.
    Carried verbatim from the heading, and absent when the block prices a
    single amount per effective date."""
    group: Cited[str] | None = None
    """The heading of the block of rows this price was read from, when the
    document prices a run of rows under one heading that also states their
    unit. Carried verbatim. Without it a row labelled "Income Tier 1" would not
    say which of a sheet's several tables it came from."""

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "label": self.label.to_json(),
            "kind": self.kind,
            "price": self.price.to_json(),
            "effective_from": self.effective_from.to_json(),
        }
        for name in ("rate_category", "season", "tou_period", "applies_to", "group"):
            value: Cited[str] | None = getattr(self, name)
            if value is not None:
                out[name] = value.to_json()
        return out

    #: Fields a charge states only when the document does. Absent means the
    #: document did not say, never a default.
    OPTIONAL = ("rate_category", "season", "tou_period", "applies_to", "group")

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(
            node,
            path,
            required=("label", "kind", "price", "effective_from"),
            optional=cls.OPTIONAL,
        )
        return cls(
            label=_cited(node, "label", path),
            kind=_str(node, "kind", path),
            price=Money.from_json(node["price"], f"{path}.price"),
            effective_from=_cited(node, "effective_from", path),
            **{name: _opt_cited(node, name, path) for name in cls.OPTIONAL},
        )


@dataclass(frozen=True, slots=True)
class TouWindow:
    """One time-of-use period as the document defines it.

    ``residual`` marks a period the document defines by exclusion, for example
    "All other hours, including weekends and holidays". No start or end time is
    invented for a residual period; the verbatim definition is carried instead.
    """

    season: Cited[str]
    period: Cited[str]
    definition: Cited[str]
    residual: bool
    day_type: Cited[str] | None = None
    start: Cited[str] | None = None
    end: Cited[str] | None = None

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {
            "season": self.season.to_json(),
            "period": self.period.to_json(),
            "definition": self.definition.to_json(),
            "residual": self.residual,
        }
        for name in ("day_type", "start", "end"):
            value: Cited[str] | None = getattr(self, name)
            if value is not None:
                out[name] = value.to_json()
        return out

    OPTIONAL = ("day_type", "start", "end")

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(
            node,
            path,
            required=("season", "period", "definition", "residual"),
            optional=cls.OPTIONAL,
        )
        return cls(
            season=_cited(node, "season", path),
            period=_cited(node, "period", path),
            definition=_cited(node, "definition", path),
            residual=_bool(node, "residual", path),
            **{name: _opt_cited(node, name, path) for name in cls.OPTIONAL},
        )


@dataclass(frozen=True, slots=True)
class Holiday:
    """A named holiday on which the document says off-peak pricing applies."""

    name: Cited[str]
    month: Cited[str]
    day_rule: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name.to_json(),
            "month": self.month.to_json(),
            "day_rule": self.day_rule.to_json(),
        }

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("name", "month", "day_rule"))
        return cls(
            name=_cited(node, "name", path),
            month=_cited(node, "month", path),
            day_rule=_cited(node, "day_rule", path),
        )


@dataclass(frozen=True, slots=True)
class Applicability:
    """One eligibility or exclusion statement, carried verbatim."""

    text: Cited[str]
    disposition: str

    def to_json(self) -> dict[str, object]:
        return {"text": self.text.to_json(), "disposition": self.disposition}

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("text", "disposition"))
        return cls(text=_cited(node, "text", path), disposition=_str(node, "disposition", path))


@dataclass(frozen=True, slots=True)
class Condition:
    """One item of a numbered list of conditions that must all be met.

    A schedule sometimes gates a rate option on an enumerated list outside
    any Applicability or Eligibility part, as in "Standby Service applies
    when all of the following conditions are met: 1. ... 2. ... 3. ...".
    ``Applicability.disposition`` sorts a statement into included, excluded
    or required, and none of those fits one item of a conjunction: the item
    is not itself a condition of eligibility for the schedule, it is one of
    several conditions an option's own intro sentence already states are
    jointly required, so no disposition is attached rather than forcing one.
    """

    subject: Cited[str]
    """The intro sentence naming what the list gates, carried verbatim and
    shared by every item read from the same list, e.g. "Standby Service
    applies when all of the following conditions are met:"."""
    text: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {"subject": self.subject.to_json(), "text": self.text.to_json()}

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("subject", "text"))
        return cls(subject=_cited(node, "subject", path), text=_cited(node, "text", path))


@dataclass(frozen=True, slots=True)
class ProrationRule:
    """One row of a billing-proration table: a circumstance and its basis.

    Read from a ruled table's own cells rather than from line order, because a
    basis cell that spans more than one circumstance is a genuine merge the
    publisher drew, not an artefact of how the words happen to wrap. Each
    ``ProrationRule`` still carries its own citation, so a basis shared by two
    circumstances appears as two rules, each citing the same basis cell and
    its own circumstance cell.
    """

    circumstance: Cited[str]
    basis: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {"circumstance": self.circumstance.to_json(), "basis": self.basis.to_json()}

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("circumstance", "basis"))
        return cls(
            circumstance=_cited(node, "circumstance", path),
            basis=_cited(node, "basis", path),
        )


@dataclass(frozen=True, slots=True)
class CrossReference:
    """A pointer from this schedule to another published schedule."""

    target: Cited[str]
    context: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {"target": self.target.to_json(), "context": self.context.to_json()}

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=("target", "context"))
        return cls(target=_cited(node, "target", path), context=_cited(node, "context", path))


@dataclass(frozen=True, slots=True)
class UnparsedSection:
    """A stretch of the source document the parser did not understand.

    Unparsed content is a first class output. It is never dropped, and it is
    never quietly folded into a neighbouring section.

    Line numbers are per page, and a section can run across a page break, so
    the span is reported as a page and line at each end rather than as a single
    page with two line numbers. Without both pages a span like "lines 35 to 5"
    is unreadable, and a reader cannot find the text being reported.
    """

    section: str
    heading: str
    page: int
    sheet: str | None
    first_line: int
    last_line: int
    line_count: int
    reason: str
    last_page: int | None = None
    last_sheet: str | None = None
    sample: list[str] = field(default_factory=list)

    @property
    def end_page(self) -> int:
        return self.last_page if self.last_page is not None else self.page

    @property
    def span(self) -> str:
        """Human readable location, e.g. ``p.2 L35 to p.3 L5``."""
        if self.end_page == self.page:
            return f"p.{self.page} lines {self.first_line}-{self.last_line}"
        return f"p.{self.page} L{self.first_line} to p.{self.end_page} L{self.last_line}"

    def to_json(self) -> dict[str, object]:
        return {
            "section": self.section,
            "heading": self.heading,
            "page": self.page,
            "sheet": self.sheet,
            "first_line": self.first_line,
            "last_page": self.end_page,
            "last_sheet": self.last_sheet if self.last_sheet is not None else self.sheet,
            "last_line": self.last_line,
            "line_count": self.line_count,
            "reason": self.reason,
            "span": self.span,
            "sample": list(self.sample),
        }

    @classmethod
    def from_json(cls, node: object, path: str, *, sample_withheld: bool = False) -> Self:
        """Rebuild an unparsed span.

        ``to_json`` resolves ``last_page`` and ``last_sheet`` before writing
        them, so what comes back is always explicit; nothing is inferred here.
        ``span`` is derived and is compared rather than read.
        """
        node = _mapping(node, path)
        required = [
            "section",
            "heading",
            "page",
            "sheet",
            "first_line",
            "last_page",
            "last_sheet",
            "last_line",
            "line_count",
            "reason",
        ]
        if not sample_withheld:
            required.append("sample")
        _keys(
            node,
            path,
            required=required,
            optional=("sample",) if sample_withheld else (),
            derived=DERIVED_KEYS["unparsed"],
        )
        if sample_withheld and "sample" in node:
            raise SchemaError(
                f"{path}.sample is present in a payload whose schema says the "
                "samples were omitted; one of the two is wrong"
            )
        sample = [] if sample_withheld else _sequence(node["sample"], f"{path}.sample")
        for index, line in enumerate(sample):
            if not isinstance(line, str):
                raise SchemaError(
                    f"{path}.sample[{index}] must be a string, got {type(line).__name__}"
                )
        built = cls(
            section=_str(node, "section", path),
            heading=_str(node, "heading", path),
            page=_int(node, "page", path),
            sheet=_opt_str(node, "sheet", path),
            first_line=_int(node, "first_line", path),
            last_line=_int(node, "last_line", path),
            line_count=_int(node, "line_count", path),
            reason=_str(node, "reason", path),
            last_page=_opt_int(node, "last_page", path),
            last_sheet=_opt_str(node, "last_sheet", path),
            sample=list(sample),
        )
        stated = node.get("span")
        if stated is not None and stated != built.span:
            raise SchemaError(
                f"{path}.span says {stated!r} but the pages and lines beside it read {built.span!r}"
            )
        return built


@dataclass(frozen=True, slots=True)
class Coverage:
    """How much of the source document the parser actually accounted for.

    This is a published output, not an implicit claim. ``fully_recognized`` is
    true only when the parser read at least one content line and every content
    line it read was consumed by a recognizer.

    The first half of that is not pedantry. A document the extractor got no
    text out of at all -- a scanned sheet with no text layer, a PDF whose
    pages fail to open, an empty file -- arrives here with every counter at
    zero, and zero unrecognized lines out of zero content lines is
    arithmetically a clean sweep. Reporting that as ``fully_recognized`` would
    publish a failed read as a completely understood schedule, which is the
    one thing this parser exists not to do. Nothing read is not everything
    recognized. See docs/adr/0002.
    """

    content_lines: int
    recognized_lines: int
    unrecognized_lines: int
    boilerplate_lines: int
    sections_total: int
    sections_recognized: int
    sections_unrecognized: int

    @property
    def line_ratio(self) -> float:
        if self.content_lines == 0:
            return 0.0
        return round(self.recognized_lines / self.content_lines, 6)

    @property
    def section_ratio(self) -> float:
        if self.sections_total == 0:
            return 0.0
        return round(self.sections_recognized / self.sections_total, 6)

    @property
    def read_anything(self) -> bool:
        """Whether the parser got any content line at all out of the document.

        False is a failed read, not an empty schedule. Not a new field in the
        payload: ``content_lines`` already carries it, and adding a key would
        churn the v1 schema and every golden file for something the reader can
        already see. This exists so the distinction has a name in the code.
        """
        return self.content_lines > 0

    @property
    def fully_recognized(self) -> bool:
        if not self.read_anything:
            return False
        return self.unrecognized_lines == 0 and self.sections_unrecognized == 0

    def to_json(self) -> dict[str, object]:
        return {
            "content_lines": self.content_lines,
            "recognized_lines": self.recognized_lines,
            "unrecognized_lines": self.unrecognized_lines,
            "boilerplate_lines": self.boilerplate_lines,
            "sections_total": self.sections_total,
            "sections_recognized": self.sections_recognized,
            "sections_unrecognized": self.sections_unrecognized,
            "line_ratio": self.line_ratio,
            "section_ratio": self.section_ratio,
            "fully_recognized": self.fully_recognized,
        }

    #: The seven counters coverage is actually made of.
    COUNTERS = (
        "content_lines",
        "recognized_lines",
        "unrecognized_lines",
        "boilerplate_lines",
        "sections_total",
        "sections_recognized",
        "sections_unrecognized",
    )

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        """Rebuild coverage from its counters, never from its verdict.

        ``line_ratio``, ``section_ratio`` and ``fully_recognized`` are derived
        from the seven counters. Reading them as data would let a payload
        assert a clean sweep the counters do not support --- exactly the
        failure ADR 0002 records. They are recomputed and compared, and a
        disagreement is refused rather than resolved in either direction.
        """
        node = _mapping(node, path)
        _keys(node, path, required=cls.COUNTERS, derived=DERIVED_KEYS["coverage"])
        built = cls(**{name: _int(node, name, path) for name in cls.COUNTERS})
        for name, derived in (
            ("line_ratio", built.line_ratio),
            ("section_ratio", built.section_ratio),
            ("fully_recognized", built.fully_recognized),
        ):
            stated = node.get(name)
            if stated is not None and stated != derived:
                raise SchemaError(
                    f"{path}.{name} says {stated!r} but the counters beside it give {derived!r}"
                )
        return built


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Identity of the bytes that were parsed."""

    document_id: str
    sha256: str
    page_count: int
    byte_size: int
    filename: str
    publisher: str | None = None
    retrieved_from: str | None = None
    retrieved_at: str | None = None
    synthetic: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "sha256": self.sha256,
            "page_count": self.page_count,
            "byte_size": self.byte_size,
            "filename": self.filename,
            "publisher": self.publisher,
            "retrieved_from": self.retrieved_from,
            "retrieved_at": self.retrieved_at,
            "synthetic": self.synthetic,
        }

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(
            node,
            path,
            required=(
                "document_id",
                "sha256",
                "page_count",
                "byte_size",
                "filename",
                "publisher",
                "retrieved_from",
                "retrieved_at",
                "synthetic",
            ),
        )
        if not SHA256_RE.match(_str(node, "sha256", path)):
            raise SchemaError(
                f"{path}.sha256 must be 64 lowercase hex characters, got {node['sha256']!r}"
            )
        return cls(
            document_id=_str(node, "document_id", path),
            sha256=_str(node, "sha256", path),
            page_count=_int(node, "page_count", path),
            byte_size=_int(node, "byte_size", path),
            filename=_str(node, "filename", path),
            publisher=_opt_str(node, "publisher", path),
            retrieved_from=_opt_str(node, "retrieved_from", path),
            retrieved_at=_opt_str(node, "retrieved_at", path),
            synthetic=_bool(node, "synthetic", path),
        )


@dataclass(frozen=True, slots=True)
class ScheduleIdentity:
    """The schedule's own self description, read off the document."""

    schedule_code: Cited[str] | None = None
    title: Cited[str] | None = None
    resolution: Cited[str] | None = None
    adopted: Cited[str] | None = None
    effective: Cited[str] | None = None
    sheets: tuple[Cited[str], ...] = ()

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for name in ("schedule_code", "title", "resolution", "adopted", "effective"):
            value: Cited[str] | None = getattr(self, name)
            out[name] = value.to_json() if value is not None else None
        out["sheets"] = [s.to_json() for s in self.sheets]
        return out

    SINGLE = ("schedule_code", "title", "resolution", "adopted", "effective")

    @classmethod
    def from_json(cls, node: object, path: str) -> Self:
        node = _mapping(node, path)
        _keys(node, path, required=(*cls.SINGLE, "sheets"))
        sheets = _sequence(node["sheets"], f"{path}.sheets")
        return cls(
            sheets=tuple(
                Cited.from_json(sheet, f"{path}.sheets[{index}]")
                for index, sheet in enumerate(sheets)
            ),
            **{name: _opt_cited(node, name, path) for name in cls.SINGLE},
        )


#: The schema identifier ``parse`` writes and :func:`ca_tariff_parse.load`
#: reads. A payload announcing anything else is refused rather than read on
#: the assumption that the shapes are close enough.
SCHEMA_ID = "ca-tariff-parse/parsed-schedule/v1"

#: The projection the watch commits under ``data/parsed/``: the same payload
#: with the document's verbatim prose removed. Defined here rather than
#: imported from :mod:`ca_tariff_parse.watch` so that reading a baseline needs
#: nothing from the parsing side of the package.
BASELINE_SCHEMA_ID = "ca-tariff-parse/watch-baseline/v1"

#: The record collections on a :class:`ParsedSchedule`, in payload order,
#: each mapped to the reader that rebuilds one of its items.
RECORD_FIELDS: dict[str, Callable[[object, str], Any]] = {}


@dataclass(frozen=True, slots=True)
class ParsedSchedule:
    """The full structured representation of one published rate schedule."""

    source: SourceDocument
    identity: ScheduleIdentity
    applicability: tuple[Applicability, ...]
    charges: tuple[Charge, ...]
    tou_windows: tuple[TouWindow, ...]
    holidays: tuple[Holiday, ...]
    cross_references: tuple[CrossReference, ...]
    proration: tuple[ProrationRule, ...]
    conditions: tuple[Condition, ...]
    notes: tuple[Cited[str], ...]
    unparsed: tuple[UnparsedSection, ...]
    coverage: Coverage
    parser_version: str
    withheld: tuple[str, ...] = ()
    """What the payload this schedule came from deliberately left out.

    Empty for a fresh parse and for a full ``parsed-schedule/v1`` payload. A
    watch baseline omits the document's verbatim prose (ADR 0003, ADR 0016),
    and this names those fields so a reader is never left inferring "the
    document has none" from a collection that is empty because it was never
    written. Not serialised: ``to_json`` emits ``parsed-schedule/v1``, and a
    payload that carries the fields has nothing to declare.
    """

    def __post_init__(self) -> None:
        # Present every collection as Records so `where` is available whether
        # the schedule was parsed from a PDF or loaded from a committed
        # payload. Records is a tuple subclass, so equality, ordering and
        # serialisation are unchanged.
        for name in (*RECORD_FIELDS, "notes", "unparsed"):
            held = getattr(self, name)
            if not isinstance(held, Records):
                object.__setattr__(self, name, Records(held))

    def cite(self, record: object, field_name: str) -> Provenance:
        """The citation behind one field of one record.

        Raises rather than returning ``None`` when the field states nothing.
        A caller asking where a value came from has to be told that there is
        no value, not handed an empty citation it might render as a blank.
        """
        if not hasattr(record, field_name):
            raise AttributeError(
                f"{type(record).__name__} has no field {field_name!r}; "
                f"it states {', '.join(sorted(_field_names(record)))}"
            )
        held = getattr(record, field_name)
        if held is None:
            raise ProvenanceError(
                f"{type(record).__name__}.{field_name} is absent in this parse: the "
                "document did not state it, so there is nothing to cite"
            )
        if isinstance(held, Cited):
            return held.provenance
        raise ProvenanceError(
            f"{type(record).__name__}.{field_name} is structural metadata "
            f"({held!r}), not a value read off the page, so it carries no citation"
        )

    @classmethod
    def from_json(cls, node: object, path: str = "") -> Self:
        """Rebuild a whole parse from its serialised form.

        Reads either shape this project writes: a full
        ``parsed-schedule/v1`` payload, or the ``watch-baseline/v1``
        projection of one, which drops the document's verbatim prose. The
        projection's omissions are carried on :attr:`withheld` and its
        ``notes`` collection refuses to be queried, so an omission is never
        read back as an empty answer.

        Every leaf goes back through the ordinary constructors, so a payload
        whose citation is missing, malformed, or inconsistent with itself is
        refused here rather than becoming a half-cited object in a caller's
        hands.
        """
        node = _mapping(node, path or "<payload>")
        where = path or "<payload>"
        stated_schema = node.get("schema")
        if stated_schema == SCHEMA_ID:
            projected = False
        elif stated_schema == BASELINE_SCHEMA_ID:
            projected = True
        else:
            raise SchemaError(
                f"{where}.schema is {stated_schema!r}; this model reads "
                f"{SCHEMA_ID!r} and {BASELINE_SCHEMA_ID!r}, and will not guess "
                "at another shape"
            )
        _keys(
            node,
            where,
            required=(
                "schema",
                "parser_version",
                "disclaimer",
                "source",
                "identity",
                *RECORD_FIELDS,
                *(() if projected else ("notes",)),
                "unparsed",
                "coverage",
                *(("omitted",) if projected else ()),
            ),
        )
        _str(node, "disclaimer", where)
        prefix = f"{path}." if path else ""
        if projected:
            omitted = _mapping(node["omitted"], f"{prefix}omitted")
            _keys(omitted, f"{prefix}omitted", required=("fields", "why"))
            fields = _sequence(omitted["fields"], f"{prefix}omitted.fields")
            withheld = tuple(str(item) for item in fields)
            why = _str(omitted, "why", f"{prefix}omitted")
            if "notes" not in withheld:
                raise SchemaError(
                    f"{prefix}omitted.fields does not name notes, but the payload "
                    "carries no notes key; the projection does not describe itself"
                )
        else:
            withheld = ()
            why = ""
        collections: dict[str, object] = {}
        for name, read in RECORD_FIELDS.items():
            items = _sequence(node[name], f"{prefix}{name}")
            collections[name] = Records(
                read(item, f"{prefix}{name}[{index}]") for index, item in enumerate(items)
            )
        if projected:
            notes_records: Records[Any] = Records((), withheld=why)
        else:
            notes_records = Records(
                Cited.from_json(note, f"{prefix}notes[{index}]")
                for index, note in enumerate(_sequence(node["notes"], f"{prefix}notes"))
            )
        return cls(
            source=SourceDocument.from_json(node["source"], f"{prefix}source"),
            identity=ScheduleIdentity.from_json(node["identity"], f"{prefix}identity"),
            notes=notes_records,
            unparsed=Records(
                UnparsedSection.from_json(
                    item, f"{prefix}unparsed[{index}]", sample_withheld=projected
                )
                for index, item in enumerate(_sequence(node["unparsed"], f"{prefix}unparsed"))
            ),
            coverage=Coverage.from_json(node["coverage"], f"{prefix}coverage"),
            parser_version=_str(node, "parser_version", where),
            withheld=withheld,
            **collections,  # type: ignore[arg-type]
        )

    def to_json(self) -> dict[str, object]:
        """Serialise back to the shape this schedule was read from.

        A schedule loaded from a watch baseline re-emits as a watch baseline,
        not as a full parse. Emitting it as ``parsed-schedule/v1`` would write
        ``"notes": []`` and an ``unparsed`` entry with no ``sample``, which
        states that the document has no prose --- publishing an omission as a
        measurement. See :attr:`withheld`.
        """
        payload: dict[str, object] = {
            "schema": SCHEMA_ID,
            "parser_version": self.parser_version,
            "disclaimer": DISCLAIMER,
            "source": self.source.to_json(),
            "identity": self.identity.to_json(),
            "applicability": [a.to_json() for a in self.applicability],
            "charges": [c.to_json() for c in self.charges],
            "tou_windows": [w.to_json() for w in self.tou_windows],
            "holidays": [h.to_json() for h in self.holidays],
            "cross_references": [x.to_json() for x in self.cross_references],
            "proration": [p.to_json() for p in self.proration],
            "conditions": [c.to_json() for c in self.conditions],
            "notes": [n.to_json() for n in self.notes],
            "unparsed": [u.to_json() for u in self.unparsed],
            "coverage": self.coverage.to_json(),
        }
        if not self.withheld:
            return payload
        payload["schema"] = BASELINE_SCHEMA_ID
        del payload["notes"]
        payload["unparsed"] = [
            {key: value for key, value in item.items() if key != "sample"}
            for item in (u.to_json() for u in self.unparsed)
        ]
        # __post_init__ guarantees Records here; the annotation stays a plain
        # tuple so that constructing a schedule from tuples keeps type-checking.
        notes = self.notes if isinstance(self.notes, Records) else Records(self.notes)
        payload["omitted"] = {
            "fields": list(self.withheld),
            "why": notes.withheld or "",
        }
        return payload


RECORD_FIELDS.update(
    {
        "applicability": Applicability.from_json,
        "charges": Charge.from_json,
        "tou_windows": TouWindow.from_json,
        "holidays": Holiday.from_json,
        "cross_references": CrossReference.from_json,
        "proration": ProrationRule.from_json,
        "conditions": Condition.from_json,
    }
)


DISCLAIMER = (
    "This output is a representation of a published document, not a calculation of "
    "what any customer owes. It is not rate advice and not a bill estimate. Values are "
    "reproduced from the cited source and may be superseded, prorated, surcharged or "
    "adjusted by other schedules and rules. Verify against the publisher before relying "
    "on anything here. This project is not affiliated with, endorsed by, or approved by "
    "any utility."
)
