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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

#: Section identifiers look like "II.A" or "V.A.1" or "header".
SECTION_ID_RE = re.compile(r"\A[A-Za-z0-9]+(\.[A-Za-z0-9]+)*\Z")


class ProvenanceError(ValueError):
    """Raised when a citation is missing, malformed or incomplete."""


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


@dataclass(frozen=True, slots=True)
class Applicability:
    """One eligibility or exclusion statement, carried verbatim."""

    text: Cited[str]
    disposition: str

    def to_json(self) -> dict[str, object]:
        return {"text": self.text.to_json(), "disposition": self.disposition}


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


@dataclass(frozen=True, slots=True)
class CrossReference:
    """A pointer from this schedule to another published schedule."""

    target: Cited[str]
    context: Cited[str]

    def to_json(self) -> dict[str, object]:
        return {"target": self.target.to_json(), "context": self.context.to_json()}


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


@dataclass(frozen=True, slots=True)
class Coverage:
    """How much of the source document the parser actually accounted for.

    This is a published output, not an implicit claim. ``fully_recognized`` is
    true only when every content line in the document was consumed by a
    recognizer.
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
    def fully_recognized(self) -> bool:
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
    notes: tuple[Cited[str], ...]
    unparsed: tuple[UnparsedSection, ...]
    coverage: Coverage
    parser_version: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema": "ca-tariff-parse/parsed-schedule/v1",
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
            "notes": [n.to_json() for n in self.notes],
            "unparsed": [u.to_json() for u in self.unparsed],
            "coverage": self.coverage.to_json(),
        }


DISCLAIMER = (
    "This output is a representation of a published document, not a calculation of "
    "what any customer owes. It is not rate advice and not a bill estimate. Values are "
    "reproduced from the cited source and may be superseded, prorated, surcharged or "
    "adjusted by other schedules and rules. Verify against the publisher before relying "
    "on anything here. This project is not affiliated with, endorsed by, or approved by "
    "any utility."
)
