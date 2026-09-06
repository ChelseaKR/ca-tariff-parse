"""Read a committed parse back into typed records.

``parse`` writes JSON. Until now nothing read it back: every record had
``to_json`` and none had the inverse, so a consumer who wanted the baselines
under ``data/parsed/`` re-implemented the model, and with it every rule about
what a value is allowed to be.

This module closes that. :func:`load` reconstructs a :class:`ParsedSchedule`
through the ordinary constructors, which means the payload passes the same
guards a fresh parse does:

* :class:`~ca_tariff_parse.model.Provenance` refuses a citation that is
  missing a field, has a malformed digest, or names a page or line that is not
  a positive integer;
* :class:`~ca_tariff_parse.model.Cited` refuses a value with no citation
  behind it at all;
* every derived key in the payload --- a locator, a span, a coverage ratio,
  ``fully_recognized`` --- is recomputed from the fields it is derived from and
  compared, so a payload cannot assert a verdict its own counters do not
  support;
* :func:`~ca_tariff_parse.audit.assert_fully_cited` then walks the
  reconstructed result independently, exactly as it does before ``parse``
  writes anything.

The result is that a partially cited object cannot be produced. Either the
whole payload reconstructs or the load raises.

Nothing here imports ``pdfplumber``. Reading a committed parse is a
standard-library operation, so a consumer of the baselines needs none of the
PDF stack.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .audit import UncitedValueError, assert_fully_cited
from .model import ParsedSchedule, SchemaError

__all__ = ["load", "loads"]


def loads(text: str) -> ParsedSchedule:
    """Load a parse from JSON text."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"not valid JSON: {exc}") from exc
    return _build(payload, "<text>")


def load(source: str | Path | Mapping[str, Any]) -> ParsedSchedule:
    """Load a parse from a file path or an already-decoded mapping.

    A string or :class:`~pathlib.Path` is read as a file. Use :func:`loads`
    for JSON held in memory as text.
    """
    if isinstance(source, Mapping):
        return _build(source, "<mapping>")
    path = Path(source)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"{path} is not valid JSON: {exc}") from exc
    return _build(payload, str(path))


def _build(payload: object, where: str) -> ParsedSchedule:
    schedule = ParsedSchedule.from_json(payload, "")
    # Independent of the reconstruction above, and deliberately so: if a future
    # field is added to the model and its `from_json` forgets to demand a
    # citation, this walk still refuses the result.
    try:
        assert_fully_cited(schedule.to_json())
    except UncitedValueError as exc:
        raise UncitedValueError(f"{where}: {exc}") from exc
    return schedule
