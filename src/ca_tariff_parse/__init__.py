"""Deterministic parser for published California electricity rate schedules.

Every value this package emits carries a citation to the document, page, sheet,
section and line it came from. Nothing is inferred, averaged or filled in.

The output represents a document. It is not a bill estimate, not rate advice,
and this project is not affiliated with any utility.
"""

from __future__ import annotations

from .audit import UncitedValueError, assert_fully_cited
from .model import (
    DISCLAIMER,
    Applicability,
    Charge,
    Cited,
    Coverage,
    CrossReference,
    Holiday,
    Money,
    ParsedSchedule,
    Provenance,
    ProvenanceError,
    ScheduleIdentity,
    SourceDocument,
    TouWindow,
    UnparsedSection,
)
from .parser import PARSER_VERSION, parse_document, parse_path

__version__ = PARSER_VERSION

__all__ = [
    "DISCLAIMER",
    "PARSER_VERSION",
    "Applicability",
    "Charge",
    "Cited",
    "Coverage",
    "CrossReference",
    "Holiday",
    "Money",
    "ParsedSchedule",
    "Provenance",
    "ProvenanceError",
    "ScheduleIdentity",
    "SourceDocument",
    "TouWindow",
    "UncitedValueError",
    "UnparsedSection",
    "__version__",
    "assert_fully_cited",
    "parse_document",
    "parse_path",
]
