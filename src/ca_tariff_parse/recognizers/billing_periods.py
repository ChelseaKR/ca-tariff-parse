"""Parse the time-of-use window table and the holiday table.

The window table uses a vertically centred season cell that spans several
period rows::

                    Peak        Weekdays between 5:00 p.m. and 8:00 p.m.
    Summer                      Weekdays between noon and midnight except
                    Mid-Peak
    (Jun 1 - Sept 30)           during the Peak hours.
                    Off-Peak    All other hours, including weekends and holidays.

Because the season label is centred rather than top aligned, seasons are
recovered by treating the first fragment of each season label as the boundary
between groups.

Two kinds of window definition are deliberately not reduced to a start and end
time:

* a residual period ("All other hours"), which the document defines by
  exclusion and which has no clock times to read;
* a period carrying an exception ("between noon and midnight except during the
  Peak hours"), where a bare start and end would misstate the rule.

Both keep their verbatim definition instead. Emitting clock times the document
did not state would be an invention.
"""

from __future__ import annotations

import re
from itertools import pairwise

from ..extract import Line
from ..model import Cited, Holiday, TouWindow
from ..segment import Section
from .base import Citer, Emission

#: Column boundaries for the window table, in points.
SEASON_MAX_X = 200.0
PERIOD_MAX_X = 300.0
#: Column boundaries for the holiday table, in points.
HOLIDAY_MONTH_X = 295.0
HOLIDAY_DATE_X = 405.0

PERIOD_RE = re.compile(r"\A(Super\s+Off-Peak|Off-Peak|Mid-Peak|On-Peak|Peak)\Z", re.IGNORECASE)
PARENTHETICAL_RE = re.compile(r"\A\(.+\)\Z")
HOLIDAY_INTRO_RE = re.compile(r"holidays\s*:\s*\Z", re.IGNORECASE)
HOLIDAY_HEADER_SQUASHED = "holidaymonthdate"
#: A clock time as tariffs write them: "5:00 p.m.", "6 a.m.", "noon", "midnight".
_TIME = r"(?:\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?|noon|midnight)"

#: Matches only a definition that is exactly a day type and a plain time range,
#: with nothing after the closing time. A definition carrying an exception
#: ("... except during the Peak hours") deliberately fails this match, so no
#: start or end time is emitted for it and the verbatim definition stands alone.
PLAIN_RANGE_RE = re.compile(
    r"\A(?P<day_type>Weekdays|Weekends|All days|Every day)\s+between\s+"
    rf"(?P<start>{_TIME})\s+and\s+(?P<end>{_TIME})\s*\.?\s*\Z",
    re.IGNORECASE,
)
RESIDUAL_RE = re.compile(r"\AAll other hours\b", re.IGNORECASE)


def claims(section: Section) -> bool:
    squashed = {line.squashed for line in section.content_lines}
    has_periods = any(
        PERIOD_RE.match(
            " ".join(
                word.text for word in line.words if SEASON_MAX_X <= word.x0 < PERIOD_MAX_X
            ).strip()
        )
        for line in section.content_lines
    )
    has_holidays = any(HOLIDAY_HEADER_SQUASHED in text for text in squashed)
    return has_periods or has_holidays


#: Fraction of the median row gap below which two text lines are treated as
#: belonging to the same logical table row.
ROW_GAP_FRACTION = 0.75


def logical_rows(lines: list[Line]) -> list[list[Line]]:
    """Group wrapped text lines into the table rows a reader sees.

    A cell that wraps sets its lines close together, while separate rows are
    spaced further apart, and a vertically centred cell can sit between the two
    wrapped halves of its neighbour. Splitting on a threshold derived from the
    table's own median gap recovers the real rows instead of assuming one text
    line is one row.
    """
    if len(lines) < 2:
        return [[line] for line in lines]
    gaps = sorted(later.top - earlier.top for earlier, later in pairwise(lines))
    median = gaps[len(gaps) // 2]
    threshold = median * ROW_GAP_FRACTION
    rows: list[list[Line]] = [[lines[0]]]
    for earlier, later in pairwise(lines):
        if later.top - earlier.top <= threshold:
            rows[-1].append(later)
        else:
            rows.append([later])
    return rows


def _bucket(row: list[Line], low: float, high: float) -> str:
    parts = [
        " ".join(word.text for word in line.words if low <= word.x0 < high).strip() for line in row
    ]
    return re.sub(r"\s+", " ", " ".join(part for part in parts if part)).strip()


def _split_tables(section: Section) -> tuple[list[Line], list[Line], Line | None]:
    """Split the section into the window table, the holiday table and the intro."""
    windows: list[Line] = []
    holidays: list[Line] = []
    intro: Line | None = None
    target = windows
    for line in section.content_lines:
        if HOLIDAY_INTRO_RE.search(line.text):
            intro = line
            target = holidays
            continue
        target.append(line)
    return windows, holidays, intro


#: A season label: the rows it occupies, the lines carrying it, and its text.
SeasonLabel = tuple[int, list[Line], str]


def _season_labels(rows: list[list[Line]]) -> list[SeasonLabel]:
    """Collect season labels, joining a date range onto the name above it.

    A season is written as a name followed by its date range, and the two halves
    are often set on separate rows of a vertically centred cell.
    """
    labels: list[SeasonLabel] = []
    for position, row in enumerate(rows):
        text = _bucket(row, 0.0, SEASON_MAX_X)
        if not text:
            continue
        carriers = [line for line in row if any(word.x0 < SEASON_MAX_X for word in line.words)]
        if labels and PARENTHETICAL_RE.match(text):
            start, group, existing = labels[-1]
            labels[-1] = (start, [*group, *carriers], f"{existing} {text}")
        else:
            labels.append((position, carriers, text))
    return labels


def _season_for(labels: list[SeasonLabel], position: int) -> tuple[list[Line], str] | None:
    """Find the season group a row belongs to.

    The label is centred over its group rather than sitting at the top of it, so
    the group runs until the first row of the next label.
    """
    for index, (_start, group, text) in enumerate(labels):
        next_start = labels[index + 1][0] if index + 1 < len(labels) else None
        if next_start is None or position < next_start:
            return (group, text)
    return None


def _window_times(
    definition: str, residual: bool, line: Line, section: str, citer: Citer
) -> tuple[Cited[str] | None, Cited[str] | None, Cited[str] | None]:
    """Read clock times, but only from a definition that is purely a range."""
    if residual:
        return (None, None, None)
    match = PLAIN_RANGE_RE.match(definition)
    if not match:
        return (None, None, None)
    return (
        citer.text(line, section, match.group("day_type")),
        citer.text(line, section, match.group("start").strip()),
        citer.text(line, section, match.group("end").strip()),
    )


def _parse_windows(lines: list[Line], section: Section, citer: Citer, emission: Emission) -> None:
    rows = logical_rows(lines)
    labels = _season_labels(rows)

    for position, row in enumerate(rows):
        period = _bucket(row, SEASON_MAX_X, PERIOD_MAX_X)
        definition = _bucket(row, PERIOD_MAX_X, float("inf"))
        season = _season_for(labels, position)
        if not PERIOD_RE.match(period) or not definition or season is None:
            continue

        season_group, season_text = season
        definition_lines = [
            line for line in row if any(word.x0 >= PERIOD_MAX_X for word in line.words)
        ]
        line = next(
            candidate
            for candidate in row
            if any(SEASON_MAX_X <= word.x0 < PERIOD_MAX_X for word in candidate.words)
        )

        residual = bool(RESIDUAL_RE.match(definition))
        day_type, start, finish = _window_times(
            definition, residual, line, section.section_id, citer
        )

        emission.tou_windows.append(
            TouWindow(
                season=Cited(
                    value=season_text,
                    provenance=citer.cite_span(season_group, section.section_id),
                ),
                period=citer.text(line, section.section_id, period),
                definition=Cited(
                    value=definition,
                    provenance=citer.cite_span(definition_lines, section.section_id),
                ),
                residual=residual,
                day_type=day_type,
                start=start,
                end=finish,
            )
        )
        emission.take(*row, *definition_lines, *season_group)


def _parse_holidays(lines: list[Line], section: Section, citer: Citer, emission: Emission) -> None:
    started = False
    for line in lines:
        if not started:
            if HOLIDAY_HEADER_SQUASHED in line.squashed:
                started = True
                emission.take(line)
            continue
        name = _bucket([line], 0.0, HOLIDAY_MONTH_X)
        month = _bucket([line], HOLIDAY_MONTH_X, HOLIDAY_DATE_X)
        day_rule = _bucket([line], HOLIDAY_DATE_X, float("inf"))
        if not (name and month and day_rule):
            # A row missing a cell is not completed by guessing.
            continue
        emission.holidays.append(
            Holiday(
                name=citer.text(line, section.section_id, name),
                month=citer.text(line, section.section_id, month),
                day_rule=citer.text(line, section.section_id, day_rule),
            )
        )
        emission.take(line)


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    windows, holidays, intro = _split_tables(section)

    body = windows[1:] if section.level > 0 and windows else windows
    if section.level > 0 and windows:
        emission.take(windows[0])

    _parse_windows(body, section, citer, emission)

    if intro is not None:
        emission.notes.append(citer.text(intro, section.section_id, intro.text))
        emission.take(intro)
    _parse_holidays(holidays, section, citer, emission)
    return emission
