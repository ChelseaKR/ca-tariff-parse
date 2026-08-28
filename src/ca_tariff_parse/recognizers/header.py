"""Read the schedule's own identity off the page furniture."""

from __future__ import annotations

import re

from ..extract import LayoutDoc, Line, sheet_numbers
from ..model import Cited, ScheduleIdentity
from ..profiles import DEFAULT, DocumentProfile
from .base import Citer, LineKey

FRONT = "front"

#: The line a schedule names itself on. One publisher prints "Rate Schedule
#: R-TOD" in the header band; another prints "ELECTRIC SCHEDULE B-1 Sheet 3" in
#: the body, over the title. What they have in common is the shape: some words,
#: the word Schedule, the code, and optionally the sheet number printed after
#: it. Which publisher writes which way is not something a profile should hold,
#: because the page states it.
SCHEDULE_RE = re.compile(
    r"\A(?:[A-Za-z.&\' ]+\s)?Schedule\s+(?P<code>[A-Za-z0-9][A-Za-z0-9\-]*)"
    r"(?:\s+Sheet\s+[0-9]+)?\Z",
    re.IGNORECASE,
)
#: Fewest sheets a schedule line has to appear on before it is read as one.
#: A running head runs: this is what tells the line naming the schedule from a
#: sentence that happens to end "... for which a residential or agricultural
#: schedule is", which is a real line of one of these documents and matches the
#: shape exactly once.
MINIMUM_RUNNING_SHEETS = 2
#: The footer line that dates the schedule. A schedule amended since it was
#: first adopted prints the amending resolution inside brackets, as in
#: "(as amended by Resolution No. 26-04-04 adopted April 16, 2026) Effective:
#: June 1, 2026", so the closing bracket is allowed to fall outside the adopted
#: date rather than being carried into it.
RESOLUTION_RE = re.compile(
    r"Resolution\s+No\.?\s*(?P<res>\S+)\s+adopted\s+(?P<adopted>.+?)\)?\s+"
    r"Effective:\s*(?P<effective>.+?)\s*\Z",
    re.IGNORECASE,
)
SHEET_RE = re.compile(r"Sheet\s*No\.?\s*(?P<sheet>[A-Za-z0-9][A-Za-z0-9\-]*)", re.IGNORECASE)

_MONTH_NAME = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
)
#: The date a sheet says it takes effect, as its own footer prints it. One
#: publisher files sheet by sheet, so the sheets of a single schedule take
#: effect on different days: on one schedule here, sheet 1 is effective June 1
#: and sheets 2 to 7 are effective March 1. Dating a price to the document
#: rather than to its sheet would file three quarters of that schedule under a
#: day it did not take effect.
#:
#: The match is anchored at the end of the line so that a footer also carrying
#: "Submitted June 1, 2026" cannot be read as the effective date.
SHEET_EFFECTIVE_RE = re.compile(
    rf"\bEffective:?\s+(?P<when>{_MONTH_NAME}\s+\d{{1,2}},\s+\d{{4}})\s*\Z",
)


def sheet_effective_dates(doc: LayoutDoc, citer: Citer) -> dict[int, Cited[str]]:
    """The effective date each page's own furniture states, by page number.

    A page whose furniture states no date, or states two that disagree, is
    absent from the result, and a recognizer that needs a date for that page
    emits nothing rather than borrowing a neighbouring sheet's.
    """
    found: dict[int, list[Cited[str]]] = {}
    for page in doc.pages:
        for line in page.lines:
            if not line.furniture:
                continue
            match = SHEET_EFFECTIVE_RE.search(line.text)
            if match:
                found.setdefault(page.number, []).append(
                    citer.text(line, FRONT, match.group("when").strip())
                )
    return {
        number: dates[0]
        for number, dates in found.items()
        if len({date.value for date in dates}) == 1
    }


def _schedule_lines(doc: LayoutDoc) -> list[tuple[Line, str, Line | None, Line | None]]:
    """Every line naming a schedule, with the lines above and below it."""
    found: list[tuple[Line, str, Line | None, Line | None]] = []
    for page in doc.pages:
        lines = page.lines
        for position, line in enumerate(lines):
            match = SCHEDULE_RE.match(line.text)
            if match is None:
                continue
            above = lines[position - 1] if position else None
            below = lines[position + 1] if position + 1 < len(lines) else None
            found.append((line, match.group("code"), above, below))
    return found


def _running_schedule(
    doc: LayoutDoc, citer: Citer
) -> tuple[Cited[str] | None, Cited[str] | None, set[LineKey]]:
    """The schedule code and title the document prints on every one of its sheets.

    **The code** is read from the line that names it, wherever the publisher
    sets that line: in the header band, or in the body over the title. What
    settles which line that is, rather than a sentence ending in the word
    schedule, is that a running head runs. The code has to be named on more
    sheets than any other candidate and on at least two, or nothing is read.

    **The title** is the neighbouring line that repeats on every one of those
    sheets, and only when exactly one of the two does. One publisher sets the
    title above the schedule line and the line below it is body text, which
    changes sheet to sheet; that is what says which is the title. Another sets
    the title below and a regulatory identifier above, and both repeat, so the
    page does not say which of them names the schedule and neither is read.
    """
    hits = _schedule_lines(doc)
    if not hits:
        return None, None, set()

    pages: dict[str, set[int]] = {}
    for line, candidate, _, _ in hits:
        pages.setdefault(candidate, set()).add(line.page)
    ranked = sorted(pages.items(), key=lambda item: len(item[1]), reverse=True)
    code_text, on_pages = ranked[0]
    if len(on_pages) < MINIMUM_RUNNING_SHEETS:
        return None, None, set()
    if len(ranked) > 1 and len(ranked[1][1]) == len(on_pages):
        # Two candidates run equally: the document names two schedules and is
        # described correctly by neither.
        return None, None, set()

    running = [hit for hit in hits if hit[1] == code_text]
    consumed = {(line.page, line.index) for line, _, _, _ in running}
    code = citer.text(running[0][0], FRONT, code_text)

    sides: dict[str, list[Line | None]] = {
        "above": [above for _, _, above, _ in running],
        "below": [below for _, _, _, below in running],
    }
    repeating: dict[str, list[Line]] = {}
    for name, neighbours in sides.items():
        if any(neighbour is None for neighbour in neighbours):
            continue
        present = [neighbour for neighbour in neighbours if neighbour is not None]
        if not present[0].text.strip():
            continue
        if len({neighbour.text for neighbour in present}) != 1:
            continue
        repeating[name] = present
    if len(repeating) != 1:
        # Neither neighbour runs, or both do. A publisher that sets a
        # regulatory identifier above the schedule line and the title below it
        # repeats both, and nothing on the page says which one names it.
        return code, None, consumed
    title_lines = next(iter(repeating.values()))
    title = citer.text(title_lines[0], FRONT, title_lines[0].text)
    consumed |= {(line.page, line.index) for line in title_lines}
    return code, title, consumed


def parse_identity(
    doc: LayoutDoc, citer: Citer, profile: DocumentProfile = DEFAULT
) -> tuple[ScheduleIdentity, set[LineKey]]:
    """Extract title, schedule code, resolution and effective date.

    Nothing here is inferred. If the document does not print a field, the field
    stays ``None`` rather than being guessed from the filename or the date.
    """
    schedule_code, title, consumed = _running_schedule(doc, citer)
    resolution: Cited[str] | None = None
    adopted: Cited[str] | None = None
    effective: Cited[str] | None = None
    sheets: list[Cited[str]] = []

    for page in doc.pages:
        for line in page.lines:
            if not line.furniture:
                continue
            text = line.text

            match = RESOLUTION_RE.search(text)
            if match:
                consumed.add((line.page, line.index))
                if resolution is None:
                    resolution = citer.text(line, FRONT, match.group("res"))
                    adopted = citer.text(line, FRONT, match.group("adopted").strip())
                    effective = citer.text(line, FRONT, match.group("effective").strip())
                continue

            # A supersession header prints the cancelled sheet number as well
            # as this page's own. Only the numbers the page asserts as its own
            # are recorded, so the schedule is never described by a sheet it
            # replaced. The cancelling line is still consumed, because it is
            # accounted for even though nothing is read from it.
            if SHEET_RE.search(text):
                consumed.add((line.page, line.index))
                sheets.extend(
                    citer.text(line, FRONT, number) for number in sheet_numbers(line, profile)
                )

    identity = ScheduleIdentity(
        schedule_code=schedule_code,
        title=title,
        resolution=resolution,
        adopted=adopted,
        effective=effective,
        sheets=tuple(sheets),
    )
    return identity, consumed
