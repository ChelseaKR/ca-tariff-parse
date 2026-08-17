"""Read the schedule's own identity off the page furniture."""

from __future__ import annotations

import re

from ..extract import LayoutDoc
from ..model import Cited, ScheduleIdentity
from .base import Citer, LineKey

FRONT = "front"

SCHEDULE_RE = re.compile(r"\ARate Schedule\s+(?P<code>[A-Za-z0-9][A-Za-z0-9\-]*)\Z")
RESOLUTION_RE = re.compile(
    r"Resolution\s+No\.?\s*(?P<res>\S+)\s+adopted\s+(?P<adopted>.+?)\s+"
    r"Effective:\s*(?P<effective>.+?)\s*\Z",
    re.IGNORECASE,
)
SHEET_RE = re.compile(r"Sheet\s*No\.?\s*(?P<sheet>[A-Za-z0-9][A-Za-z0-9\-]*)", re.IGNORECASE)


def parse_identity(doc: LayoutDoc, citer: Citer) -> tuple[ScheduleIdentity, set[LineKey]]:
    """Extract title, schedule code, resolution and effective date.

    Nothing here is inferred. If the document does not print a field, the field
    stays ``None`` rather than being guessed from the filename or the date.
    """
    consumed: set[LineKey] = set()
    schedule_code: Cited[str] | None = None
    title: Cited[str] | None = None
    resolution: Cited[str] | None = None
    adopted: Cited[str] | None = None
    effective: Cited[str] | None = None
    sheets: list[Cited[str]] = []

    for page in doc.pages:
        furniture = [line for line in page.lines if line.furniture]
        for position, line in enumerate(furniture):
            text = line.text

            match = SCHEDULE_RE.match(text)
            if match:
                consumed.add((line.page, line.index))
                if schedule_code is None:
                    schedule_code = citer.text(line, FRONT, match.group("code"))
                    # The running title is the line directly above the schedule
                    # line in the header band.
                    if position > 0 and furniture[position - 1].top < line.top:
                        above = furniture[position - 1]
                        title = citer.text(above, FRONT, above.text)
                        consumed.add((above.page, above.index))
                continue

            match = RESOLUTION_RE.search(text)
            if match:
                consumed.add((line.page, line.index))
                if resolution is None:
                    resolution = citer.text(line, FRONT, match.group("res"))
                    adopted = citer.text(line, FRONT, match.group("adopted").strip())
                    effective = citer.text(line, FRONT, match.group("effective").strip())
                continue

            match = SHEET_RE.search(text)
            if match:
                consumed.add((line.page, line.index))
                sheets.append(citer.text(line, FRONT, match.group("sheet")))

    identity = ScheduleIdentity(
        schedule_code=schedule_code,
        title=title,
        resolution=resolution,
        adopted=adopted,
        effective=effective,
        sheets=tuple(sheets),
    )
    return identity, consumed
