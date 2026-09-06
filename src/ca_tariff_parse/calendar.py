"""Re-express the time rules a document already stated, and refuse the rest.

Downstream tools that compute over a time-of-use schedule need machine-checkable
rules. This writes them as iCalendar, and the fence matters more than the
feature: the rule set is a lossless re-expression of text the parser already
committed to, never an interpretation of text it did not.

So a window becomes a ``VEVENT`` only when the parser read a bare start and end
time for it and the document named the days it applies to. Everything else is
listed, with its citation and the reason, in a refusal file written beside the
calendar:

* a residual window ("All other hours, including weekends and holidays") is
  refused because the parser has already refused to give it hours, and
  inventing them here would undo that;
* a window defined by exception ("Weekdays between noon and midnight except
  during the Peak hours") is refused because the exception is prose this
  module cannot subtract;
* a window with hours but no stated day type is refused rather than assumed
  daily;
* a holiday whose ``day_rule`` is outside a small closed grammar is refused
  rather than approximated.

The refusal file is part of the output, not a log. A consumer that reads the
``.ics`` alone would see a partial calendar with nothing saying it was
partial, which is this project's defining defect wearing a different hat.

Season bounds are added only when the season text states a whole-month range,
because ``BYMONTH`` can express whole months and nothing else. A season stated
any other way leaves the event unbounded and marked partial: the season string
travels in the summary, and no month is guessed.

Everything is floating local time. No time zone is inferred, and the file says
so, because a published schedule states clock times and not offsets.

Deterministic: the same parse renders the same bytes. Nothing here reads the
clock.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .model import Holiday, ParsedSchedule, TouWindow

__all__ = [
    "ANCHOR_YEAR",
    "CalendarError",
    "Refusal",
    "Rendered",
    "render",
]

PRODID = "-//ca-tariff-parse//tariff calendar//EN"

#: The year the recurrences are anchored to. A published schedule states a
#: recurring rule with no year in it, so ``DTSTART`` needs a date the document
#: never gave. The year carries no information and the file says so; only the
#: month, day and time in a ``DTSTART`` mean anything.
ANCHOR_YEAR = 1970

#: The stamp written when the source document states no retrieval date. A
#: generation time would make two renderings of one parse differ, which the
#: determinism requirement forbids, so no clock is read.
EPOCH_STAMP = "19700101T000000Z"

WEEKDAYS = {
    "monday": "MO",
    "tuesday": "TU",
    "wednesday": "WE",
    "thursday": "TH",
    "friday": "FR",
    "saturday": "SA",
    "sunday": "SU",
}

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
#: Abbreviations a publisher actually prints, mapped to the same numbers.
MONTH_ABBREVIATIONS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sept": 9,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

#: Days in each month, ignoring leap years. Only used to check that a stated
#: month range ends on the last day of its month and that a fixed day exists,
#: so February 29 is out of the grammar rather than silently accepted.
DAYS_IN_MONTH = {
    1: 31,
    2: 28,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}

#: Day types this module will translate. Anything else is refused rather than
#: guessed: "Weekdays including holidays" and "Weekdays excluding holidays" are
#: different rules and neither is the other.
DAY_TYPES = {
    "weekdays": ("MO", "TU", "WE", "TH", "FR"),
    "weekends": ("SA", "SU"),
    "every day": ("MO", "TU", "WE", "TH", "FR", "SA", "SU"),
    "daily": ("MO", "TU", "WE", "TH", "FR", "SA", "SU"),
    "all days": ("MO", "TU", "WE", "TH", "FR", "SA", "SU"),
}

TIME_RE = re.compile(r"\A(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\Z", re.IGNORECASE)

#: "Jun 1 - Sept 30", "October 1 -May 31", "June 1 to September 30".
MONTH_RANGE_RE = re.compile(
    r"([A-Za-z]+)\.?\s*(\d{1,2})\s*(?:-|–|—|to)\s*([A-Za-z]+)\.?\s*(\d{1,2})"
)

ORDINAL_DAY_RE = re.compile(
    r"\A(first|second|third|fourth|fifth)\s+"
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\Z",
    re.IGNORECASE,
)
LAST_DAY_RE = re.compile(
    r"\Alast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\Z",
    re.IGNORECASE,
)
FIXED_DAY_RE = re.compile(r"\A(\d{1,2})\Z")


class CalendarError(ValueError):
    """Raised when a parse cannot be rendered at all."""


@dataclass(frozen=True, slots=True)
class Refusal:
    """One thing the document states that this module will not express."""

    kind: str
    subject: str
    reason: str
    locator: str
    stated: str

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "subject": self.subject,
            "reason": self.reason,
            "locator": self.locator,
            "stated": self.stated,
        }


@dataclass(frozen=True, slots=True)
class Rendered:
    """The calendar and the list of what is not in it."""

    ics: str
    refused: list[Refusal]
    document_id: str
    rendered_windows: int
    rendered_holidays: int
    total_windows: int
    total_holidays: int

    def refused_json(self) -> str:
        payload = {
            "schema": "ca-tariff-parse/calendar-refusals/v1",
            "document_id": self.document_id,
            "why": (
                "Every rule in the .ics is a re-expression of text the parser "
                "already read. These are the windows and holidays it will not "
                "express, each with the citation of what the document actually "
                "says. A calendar read without this list would look complete."
            ),
            "rendered": {
                "tou_windows": self.rendered_windows,
                "holidays": self.rendered_holidays,
            },
            "stated": {
                "tou_windows": self.total_windows,
                "holidays": self.total_holidays,
            },
            "refused": [item.to_json() for item in self.refused],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _escape(text: str) -> str:
    """RFC 5545 text escaping. Order matters: backslash first."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Fold a content line to 75 octets, continuing with a leading space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return [line]
    out = []
    chunk = bytearray()
    limit = 75
    for character in line:
        raw = character.encode("utf-8")
        if len(chunk) + len(raw) > limit:
            out.append(chunk.decode("utf-8"))
            chunk = bytearray()
            limit = 74  # the continuation space counts toward the octet limit
        chunk.extend(raw)
    out.append(chunk.decode("utf-8"))
    return [out[0], *(" " + part for part in out[1:])]


def _time(value: str) -> tuple[int, int] | None:
    """``5:00 p.m.`` -> (17, 0). ``noon``/``midnight`` are named, not clock."""
    text = value.strip().lower().rstrip(".")
    if text == "noon":
        return (12, 0)
    if text == "midnight":
        return (0, 0)
    match = TIME_RE.match(value.strip())
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not 1 <= hour <= 12 or minute > 59:
        return None
    morning = match.group(3).lower() == "a"
    if hour == 12:
        # 12 a.m. is midnight and 12 p.m. is noon; neither is 12 nor 24.
        hour = 0 if morning else 12
    elif not morning:
        hour += 12
    return (hour, minute)


#: Weekday codes in the order :mod:`datetime` numbers them (Monday is 0).
WEEKDAY_ORDER = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _first_matching_day(month: int, days: Sequence[str]) -> int:
    """The first day of ``month`` in the anchor year falling on one of ``days``.

    ``DTSTART`` has to be an instance of its own rule, or a reader is entitled
    to treat it as an extra occurrence outside the recurrence. Only the day of
    the month moves; the year is still the anchor and still means nothing.
    """
    wanted = {WEEKDAY_ORDER.index(code) for code in days}
    for day in range(1, DAYS_IN_MONTH[month] + 1):
        if dt.date(ANCHOR_YEAR, month, day).weekday() in wanted:
            return day
    raise CalendarError(f"no day of month {month} matches {days}")  # pragma: no cover


def _nth_weekday(month: int, weekday: str, ordinal: int) -> int:
    """The date of the nth (or last, ordinal -1) given weekday in the month."""
    index = WEEKDAY_ORDER.index(weekday)
    matching = [
        day
        for day in range(1, DAYS_IN_MONTH[month] + 1)
        if dt.date(ANCHOR_YEAR, month, day).weekday() == index
    ]
    return matching[-1] if ordinal == -1 else matching[ordinal - 1]


def _month(word: str) -> int | None:
    key = word.strip().lower().rstrip(".")
    return MONTHS.get(key) or MONTH_ABBREVIATIONS.get(key)


def _season_months(season: str) -> tuple[int, ...] | None:
    """The whole months a season names, or None when it names none.

    Only a range that starts on the 1st and ends on the last day of a month is
    accepted, because ``BYMONTH`` selects whole months. A range like
    "June 15 - September 30" would have to be widened or narrowed to fit, and
    either is a claim the document did not make.
    """
    match = MONTH_RANGE_RE.search(season)
    if match is None:
        return None
    start_month = _month(match.group(1))
    end_month = _month(match.group(3))
    if start_month is None or end_month is None:
        return None
    if int(match.group(2)) != 1:
        return None
    if int(match.group(4)) != DAYS_IN_MONTH[end_month]:
        return None
    months = []
    current = start_month
    for _ in range(12):
        months.append(current)
        if current == end_month:
            return tuple(months)
        current = current % 12 + 1
    return None


def _day_type(window: TouWindow) -> tuple[str, ...] | None:
    if window.day_type is None:
        return None
    return DAY_TYPES.get(window.day_type.value.strip().lower())


def _stamp(schedule: ParsedSchedule) -> str:
    retrieved = schedule.source.retrieved_at
    if retrieved and re.fullmatch(r"\d{4}-\d{2}-\d{2}", retrieved):
        return retrieved.replace("-", "") + "T000000Z"
    return EPOCH_STAMP


def _window_event(
    schedule: ParsedSchedule, index: int, window: TouWindow
) -> tuple[list[str], Refusal | None]:
    subject = f"{window.season.value} / {window.period.value}"
    locator = window.definition.provenance.locator
    stated = window.definition.value

    if window.residual:
        return [], Refusal(
            "tou_window",
            subject,
            "the document defines this period by exclusion, and the parser "
            "already refused to give it hours; deriving them here would undo "
            "that refusal",
            locator,
            stated,
        )
    if window.start is None or window.end is None:
        return [], Refusal(
            "tou_window",
            subject,
            "the parser read no bare start and end time for this period, so "
            "there are no hours to re-express",
            locator,
            stated,
        )
    days = _day_type(window)
    if days is None:
        return [], Refusal(
            "tou_window",
            subject,
            (
                f"the day type {window.day_type.value!r} is outside the closed "
                "grammar this module translates"
                if window.day_type is not None
                else "the document states no day type for this period, and "
                "assuming every day would be an invention"
            ),
            locator,
            stated,
        )
    start = _time(window.start.value)
    end = _time(window.end.value)
    if start is None or end is None:
        unreadable = window.start.value if start is None else window.end.value
        return [], Refusal(
            "tou_window",
            subject,
            f"the time {unreadable!r} is outside the closed grammar this module translates",
            locator,
            stated,
        )
    if end <= start:
        return [], Refusal(
            "tou_window",
            subject,
            "the stated end is at or before the stated start, so the window "
            "crosses midnight; splitting it is a decision the document did "
            "not make",
            locator,
            stated,
        )

    months = _season_months(window.season.value)
    anchor_month = months[0] if months else 1
    rule = f"FREQ=WEEKLY;BYDAY={','.join(days)}"
    if months:
        rule += f";BYMONTH={','.join(str(month) for month in months)}"

    anchor_day = _first_matching_day(anchor_month, days)
    stamp = f"{ANCHOR_YEAR}{anchor_month:02d}{anchor_day:02d}"
    lines = [
        "BEGIN:VEVENT",
        f"UID:{schedule.source.document_id}-window-{index}@ca-tariff-parse",
        f"DTSTAMP:{_stamp(schedule)}",
        f"SUMMARY:{_escape(subject)}",
        f"DTSTART:{stamp}T{start[0]:02d}{start[1]:02d}00",
        f"DTEND:{stamp}T{end[0]:02d}{end[1]:02d}00",
        f"RRULE:{rule}",
        f"DESCRIPTION:{_escape(locator + ' — ' + stated)}",
        f"X-CA-CITATION:{_escape(locator)}",
        "X-CA-SEASON-BOUNDS:" + ("stated" if months else "partial"),
        "END:VEVENT",
    ]
    return lines, None


def _holiday_event(
    schedule: ParsedSchedule, index: int, holiday: Holiday
) -> tuple[list[str], Refusal | None]:
    name = holiday.name.value
    locator = holiday.day_rule.provenance.locator
    stated = holiday.day_rule.value
    month = _month(holiday.month.value)
    if month is None:
        return [], Refusal(
            "holiday",
            name,
            f"the month {holiday.month.value!r} is not one this module reads",
            holiday.month.provenance.locator,
            holiday.month.value,
        )

    rule = None
    day = 1
    fixed = FIXED_DAY_RE.match(stated.strip())
    ordinal = ORDINAL_DAY_RE.match(stated.strip())
    last = LAST_DAY_RE.match(stated.strip())
    if fixed:
        number = int(fixed.group(1))
        if not 1 <= number <= DAYS_IN_MONTH[month]:
            return [], Refusal(
                "holiday",
                name,
                f"day {number} is not a day of {holiday.month.value}",
                locator,
                stated,
            )
        rule = f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={number}"
        day = number
    elif ordinal:
        weekday = WEEKDAYS[ordinal.group(2).lower()]
        position = ORDINALS[ordinal.group(1).lower()]
        rule = f"FREQ=YEARLY;BYMONTH={month};BYDAY={position}{weekday}"
        day = _nth_weekday(month, weekday, position)
    elif last:
        weekday = WEEKDAYS[last.group(1).lower()]
        rule = f"FREQ=YEARLY;BYMONTH={month};BYDAY=-1{weekday}"
        day = _nth_weekday(month, weekday, -1)
    else:
        return [], Refusal(
            "holiday",
            name,
            "the day rule is outside the closed grammar this module "
            "translates (a fixed day, an ordinal weekday, or a last weekday); "
            "approximating it would put the wrong date in a calendar",
            locator,
            stated,
        )

    lines = [
        "BEGIN:VEVENT",
        f"UID:{schedule.source.document_id}-holiday-{index}@ca-tariff-parse",
        f"DTSTAMP:{_stamp(schedule)}",
        f"SUMMARY:{_escape(name)}",
        f"DTSTART;VALUE=DATE:{ANCHOR_YEAR}{month:02d}{day:02d}",
        f"RRULE:{rule}",
        f"DESCRIPTION:{_escape(locator + ' — ' + holiday.month.value + ' ' + stated)}",
        f"X-CA-CITATION:{_escape(locator)}",
        "END:VEVENT",
    ]
    return lines, None


def _emit(lines: Iterable[str]) -> str:
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"


def render(schedule: ParsedSchedule) -> Rendered:
    """The calendar for one parse, and everything it refuses to express."""
    if schedule.withheld:
        raise CalendarError(
            "this parse came from a watch baseline, which omits "
            f"{', '.join(schedule.withheld)}; render a calendar from a full parse "
            "so that a refusal names the text it refused"
        )
    body: list[str] = []
    refused: list[Refusal] = []
    rendered_windows = 0
    rendered_holidays = 0

    for index, window in enumerate(schedule.tou_windows):
        lines, refusal = _window_event(schedule, index, window)
        if refusal is not None:
            refused.append(refusal)
        else:
            body.extend(lines)
            rendered_windows += 1
    for index, holiday in enumerate(schedule.holidays):
        lines, refusal = _holiday_event(schedule, index, holiday)
        if refusal is not None:
            refused.append(refusal)
        else:
            body.extend(lines)
            rendered_holidays += 1

    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(schedule.source.document_id)}",
        "X-CA-TIME-ZONE:none. Times are floating local times, as the document "
        "states them. No offset is inferred.",
        f"X-CA-ANCHOR-YEAR:{ANCHOR_YEAR}. The document states recurring rules "
        "with no year. Only the month, day and time of a DTSTART mean anything.",
        f"X-CA-PARSER-VERSION:{schedule.parser_version}",
        f"X-CA-DOCUMENT-SHA256:{schedule.source.sha256}",
        f"X-CA-REFUSALS:{len(refused)} window(s) and holiday(s) this calendar "
        "does not express are listed in the accompanying refusal file.",
    ]
    lines = [*header, *body, "END:VCALENDAR"]
    return Rendered(
        ics=_emit(lines),
        refused=refused,
        document_id=schedule.source.document_id,
        rendered_windows=rendered_windows,
        rendered_holidays=rendered_holidays,
        total_windows=len(schedule.tou_windows),
        total_holidays=len(schedule.holidays),
    )


def summary(rendered: Rendered) -> Sequence[str]:
    """Lines for a human reading the command's own output."""
    return [
        f"{rendered.document_id}: "
        f"{rendered.rendered_windows} of {rendered.total_windows} TOU window(s) "
        f"and {rendered.rendered_holidays} of {rendered.total_holidays} holiday(s) "
        "rendered as rules",
        f"{len(rendered.refused)} refused; see the refusal file for each reason",
    ]
