"""Deterministic parser for published California electricity rate schedules.

Every value this package emits carries a citation to the document, page, sheet,
section and line it came from. Nothing is inferred, averaged or filled in.

The output represents a document. It is not a bill estimate, not rate advice,
and this project is not affiliated with any utility.

The names exported here are the supported public API. :func:`load` and
:func:`loads` read a committed parse or watch baseline back into typed
records without touching a PDF; :func:`parse_path` and :func:`parse_document`
read a document, and need the ``pdfplumber`` stack. Importing this package
does not import ``pdfplumber``, so a consumer of the committed baselines needs
only the standard library at import time.
"""

from __future__ import annotations

from .audit import UncitedValueError, assert_fully_cited
from .loader import load, loads
from .model import (
    BASELINE_SCHEMA_ID,
    DISCLAIMER,
    SCHEMA_ID,
    Applicability,
    Charge,
    Cited,
    Condition,
    Coverage,
    CrossReference,
    Holiday,
    Money,
    ParsedSchedule,
    ProrationRule,
    Provenance,
    ProvenanceError,
    Records,
    ScheduleIdentity,
    SchemaError,
    SourceDocument,
    TouWindow,
    UnparsedSection,
    WithheldError,
)
from .parser import PARSER_VERSION, parse_document, parse_path

__version__ = PARSER_VERSION

__all__ = [
    "BASELINE_SCHEMA_ID",
    "DISCLAIMER",
    "PARSER_VERSION",
    "SCHEMA_ID",
    "Applicability",
    "Charge",
    "Cited",
    "Condition",
    "Coverage",
    "CrossReference",
    "Holiday",
    "Money",
    "ParsedSchedule",
    "ProrationRule",
    "Provenance",
    "ProvenanceError",
    "Records",
    "ScheduleIdentity",
    "SchemaError",
    "SourceDocument",
    "TouWindow",
    "UncitedValueError",
    "UnparsedSection",
    "WithheldError",
    "__version__",
    "assert_fully_cited",
    "load",
    "loads",
    "parse_document",
    "parse_path",
]
