"""Read the schedule's own identity off the lines the document prints.

A schedule states which schedule it is, in a sentence of its own, at a fixed
place on its sheets. Two publishers write that sentence differently::

    Rate Schedule R-TOD                      (with the title on the line above)
    ELECTRIC SCHEDULE B-1 Sheet 4            (with the title on the line below)

Both are read here, and neither is inferred. Each pattern is anchored to a
whole line, so a sentence mentioning a schedule in passing is not one, and a
document printing neither form comes back with a null code and a null title
rather than one taken from its filename or its manifest entry. See
[ADR 0015](../../../docs/adr/0015-a-schedule-names-itself-in-its-own-words.md).
"""

from __future__ import annotations

import re

from ..extract import LayoutDoc, Line, sheet_numbers
from ..model import Cited, ScheduleIdentity
from ..profiles import DEFAULT, DocumentProfile
from .base import Citer, LineKey

FRONT = "front"

SCHEDULE_RE = re.compile(r"\ARate Schedule\s+(?P<code>[A-Za-z0-9][A-Za-z0-9\-]*)\Z")
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
#: The other published form of the same sentence: a schedule naming itself and
#: the sheet it is printed on, in the running head of every sheet. The trailing
#: sheet number is required because it is what makes the line a running head
#: rather than a sentence that mentions a schedule. Only the code is read from
#: it: the sheet numbers this parser records are the ones the page furniture
#: asserts as its own, and this line's count is the publisher's own pagination
#: of the schedule, which is a different thing.
SHEET_SCHEDULE_RE = re.compile(
    r"\AELECTRIC SCHEDULE\s+(?P<code>[A-Za-z0-9][A-Za-z0-9\-]*)\s+Sheet\s+[0-9]+\Z"
)
#: Fewest sheets a line has to repeat on before the line under it is read as a
#: running title. On one sheet there is nothing to tell a running head from the
#: first line of the body, and reading it would name the schedule after a
#: sentence.
MINIMUM_RUNNING_SHEETS = 2

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


def _running_heads(doc: LayoutDoc) -> list[tuple[Line, str, Line | None]]:
    """Every line that names the schedule and its sheet, with the line under it.

    The line under it is carried but not yet read: whether it is the running
    title or the first line of the body is settled by
    :func:`_read_running_head`, from whether it repeats.
    """
    found: list[tuple[Line, str, Line | None]] = []
    for page in doc.pages:
        lines = page.lines
        for position, line in enumerate(lines):
            match = SHEET_SCHEDULE_RE.match(line.text)
            if match is None:
                continue
            below = lines[position + 1] if position + 1 < len(lines) else None
            found.append((line, match.group("code"), below))
    return found


def _read_running_head(
    doc: LayoutDoc, citer: Citer
) -> tuple[Cited[str] | None, Cited[str] | None, set[LineKey]]:
    """The schedule code and title a document prints in the head of its sheets.

    The code is refused outright when the sheets disagree about it, because a
    document whose own sheets name two schedules is described correctly by
    neither. The title is refused when the line under the schedule line is not
    the same line on every sheet, because what makes that line a title rather
    than the first sentence of the body is that it runs.
    """
    heads = _running_heads(doc)
    if not heads:
        return None, None, set()
    if len({code for _, code, _ in heads}) != 1:
        return None, None, set()

    consumed = {(line.page, line.index) for line, _, _ in heads}
    first_line, first_code, _ = heads[0]
    code = citer.text(first_line, FRONT, first_code)

    titles = [below for _, _, below in heads]
    if len(titles) < MINIMUM_RUNNING_SHEETS or any(below is None for below in titles):
        return code, None, consumed
    running = [below for below in titles if below is not None]
    if len({below.text for below in running}) != 1:
        return code, None, consumed
    title = citer.text(running[0], FRONT, running[0].text)
    consumed |= {(below.page, below.index) for below in running}
    return code, title, consumed


def parse_identity(
    doc: LayoutDoc, citer: Citer, profile: DocumentProfile = DEFAULT
) -> tuple[ScheduleIdentity, set[LineKey]]:
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

    if schedule_code is None:
        # The other published form of the same sentence. It is looked at only
        # when the first found nothing, so a document printing both is
        # described by the one its own furniture states.
        schedule_code, title, head_consumed = _read_running_head(doc, citer)
        consumed |= head_consumed

    identity = ScheduleIdentity(
        schedule_code=schedule_code,
        title=title,
        resolution=resolution,
        adopted=adopted,
        effective=effective,
        sheets=tuple(sheets),
    )
    return identity, consumed
