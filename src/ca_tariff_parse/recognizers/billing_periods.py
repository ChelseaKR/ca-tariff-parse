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
from dataclasses import dataclass
from itertools import pairwise

from ..extract import Line, Word
from ..model import Cited, Holiday, TouWindow
from ..segment import Section
from .base import MONEY_RE, PERIOD_ALTERNATION, Citer, Emission

#: Clear space, in points, left either side of a derived column boundary.
COLUMN_MARGIN = 10.0
#: Two x positions within this many points are the same column.
ALIGN_TOLERANCE = 1.5

PERIOD_RE = re.compile(rf"\A(?:{PERIOD_ALTERNATION})\Z", re.IGNORECASE)
PARENTHETICAL_RE = re.compile(r"\A\(.+\)\Z")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
#: A season's date range, written either parenthesised ("(Jun 1 - Sept 30)") or
#: bare ("October 1 -May 31"). Both forms are a continuation of the season name
#: set above them, not a season of their own.
DATE_RANGE_RE = re.compile(
    rf"\A\(?\s*{_MONTH}\s*\d{{1,2}}\s*[-–—]\s*{_MONTH}\s*\d{{1,2}}\s*\)?\Z",
    re.IGNORECASE,
)
HOLIDAY_INTRO_RE = re.compile(r"\bholidays?\b.*:\s*\Z", re.IGNORECASE)
HOLIDAY_HEADER_SQUASHED = "holidaymonthdate"
#: A clock time as tariffs write them: "5:00 p.m.", "6 a.m.", "noon", "midnight".
_TIME = r"(?:\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?|noon|midnight)"
#: A window definition states when the period runs. Requiring one of these
#: words keeps a priced table row out of the window table: a transition
#: schedule prints "Non-Summer Off-Peak per kWh $0.1237", which lines up in the
#: same three columns and would otherwise be read as a period whose definition
#: is a price.
DEFINITION_RE = re.compile(r"\bhours\b|\bbetween\b", re.IGNORECASE)

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


#: Horizontal gap, in points, that separates two headings of a table.
HEADER_GAP = 8.0


@dataclass(frozen=True, slots=True)
class WindowColumns:
    """Where the window table's three columns divide, in points."""

    season_max: float
    period_max: float


def _period_runs(line: Line) -> list[tuple[Word, ...]]:
    """Maximal word runs on this line that spell exactly a period name.

    Longest first, so "Off-Peak Saver" is read as one period rather than as
    "Off-Peak" followed by a stray word.
    """
    runs: list[tuple[Word, ...]] = []
    index = 0
    while index < len(line.words):
        for size in (3, 2, 1):
            run = line.words[index : index + size]
            if len(run) == size and PERIOD_RE.match(" ".join(word.text for word in run)):
                runs.append(tuple(run))
                index += size
                break
        else:
            index += 1
    return runs


def _window_columns(lines: list[Line]) -> WindowColumns | None:
    """Recover the period column from the alignment the table itself uses.

    The period names of a window table are set flush in a single column, and
    that column is what divides the season label on its left from the
    definition on its right. Reading the division off the document keeps the
    table from depending on x coordinates that only happened to be right for
    one publisher's residential sheet: the same table on a commercial sheet
    sits about fifteen points further right.
    """
    aligned: dict[float, list[tuple[Word, ...]]] = {}
    for line in lines:
        for run in _period_runs(line):
            key = next(
                (known for known in aligned if abs(known - run[0].x0) <= ALIGN_TOLERANCE),
                run[0].x0,
            )
            aligned.setdefault(key, []).append(run)
    if not aligned:
        return None
    # The period column is the alignment most of the period names share. A
    # lone "Peak" inside a wrapped definition also spells a period name, and
    # must not be mistaken for the column.
    left, runs = max(aligned.items(), key=lambda item: (len(item[1]), -item[0]))
    return WindowColumns(
        season_max=left - COLUMN_MARGIN,
        period_max=max(word.x1 for run in runs for word in run) + COLUMN_MARGIN,
    )


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


def _holiday_header(lines: list[Line]) -> Line | None:
    for line in lines:
        if HOLIDAY_HEADER_SQUASHED in line.squashed:
            return line
    return None


def _holiday_columns(header: Line) -> tuple[float, float] | None:
    """Read the Month and Date boundaries off the holiday table's own header.

    The three headings name the three cells, so where they sit is where the
    cells divide. Fixed coordinates read the residential sheet correctly and
    read every holiday on the commercial sheet, whose table sits about thirty
    points further right, as a row with two cells missing.
    """
    groups: list[list[Word]] = []
    for word in header.words:
        if groups and word.x0 - groups[-1][-1].x1 <= HEADER_GAP:
            groups[-1].append(word)
        else:
            groups.append([word])
    if len(groups) != 3:
        return None
    month_x = groups[1][0].x0 - COLUMN_MARGIN
    date_x = groups[2][0].x0 - COLUMN_MARGIN
    if not groups[0][-1].x1 < month_x < date_x:
        return None
    return (month_x, date_x)


def _split_tables(section: Section) -> tuple[list[Line], list[Line], Line | None]:
    """Split the section into the window table, the holiday table and its intro.

    The split is made at the holiday table's own header row rather than at the
    sentence introducing it, because publishers word that sentence differently:
    one sheet ends it "during the following holidays:" and another "are as
    follows:".
    """
    lines = section.content_lines
    header = _holiday_header(lines)
    if header is None:
        return lines, [], None
    at = lines.index(header)
    intro = lines[at - 1] if at and HOLIDAY_INTRO_RE.search(lines[at - 1].text) else None
    return (lines[: at - 1] if intro is not None else lines[:at]), lines[at:], intro


#: A season label: the rows it occupies, the lines carrying it, and its text.
SeasonLabel = tuple[int, list[Line], str]


def _continues_a_season(text: str) -> bool:
    """True when this season-column fragment belongs to the label above it.

    A season is written as a name followed by its date range, and the two
    halves are often set on separate rows of a vertically centred cell. One
    sheet parenthesises the range, "(Jun 1 - Sept 30)", and another does not,
    "October 1 -May 31". Reading the bare form as a season of its own split
    "Summer" from its own dates and left half the windows unattributed.
    """
    return bool(PARENTHETICAL_RE.match(text) or DATE_RANGE_RE.match(text))


def _season_labels(rows: list[list[Line]], columns: WindowColumns) -> list[SeasonLabel]:
    """Collect season labels, joining a date range onto the name above it."""
    labels: list[SeasonLabel] = []
    for position, row in enumerate(rows):
        text = _bucket(row, 0.0, columns.season_max)
        if not text:
            continue
        carriers = [
            line for line in row if any(word.x0 < columns.season_max for word in line.words)
        ]
        if labels and _continues_a_season(text):
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


def _states_when_a_period_runs(definition: str) -> bool:
    """True when the right-hand cell defines a time window.

    A cell carrying a currency amount is not a window definition: it is a price
    that happens to fall in the same column. A transition schedule prints
    "Non-Summer Off-Peak per kWh $0.1237" in exactly this shape, and reading it
    as a window would state a time-of-use rule the document never wrote.
    """
    if not definition or any(MONEY_RE.match(token) for token in definition.split()):
        return False
    return bool(DEFINITION_RE.search(definition))


def _is_window_row(row: list[Line], columns: WindowColumns) -> bool:
    return bool(PERIOD_RE.match(_bucket(row, columns.season_max, columns.period_max))) and (
        _states_when_a_period_runs(_bucket(row, columns.period_max, float("inf")))
    )


def _parse_windows(lines: list[Line], section: Section, citer: Citer, emission: Emission) -> None:
    columns = _window_columns(lines)
    if columns is None:
        return
    rows = logical_rows(lines)
    labels = _season_labels(rows, columns)

    for position, row in enumerate(rows):
        period = _bucket(row, columns.season_max, columns.period_max)
        definition = _bucket(row, columns.period_max, float("inf"))
        season = _season_for(labels, position)
        if not _is_window_row(row, columns) or season is None:
            continue

        season_group, season_text = season
        definition_lines = [
            line for line in row if any(word.x0 >= columns.period_max for word in line.words)
        ]
        line = next(
            candidate
            for candidate in row
            if any(columns.season_max <= word.x0 < columns.period_max for word in candidate.words)
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
    header = _holiday_header(lines)
    if header is None:
        return
    columns = _holiday_columns(header)
    if columns is None:
        # The header does not divide into three headings, so which cell holds
        # the month and which the day rule cannot be read off the document. No
        # holiday is emitted rather than one assembled from guessed columns.
        return
    month_x, date_x = columns
    emission.take(header)
    for line in lines[lines.index(header) + 1 :]:
        name = _bucket([line], 0.0, month_x)
        month = _bucket([line], month_x, date_x)
        day_rule = _bucket([line], date_x, float("inf"))
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


def _body(section: Section, windows: list[Line]) -> list[Line]:
    """The window table without the heading line that opens its section."""
    return windows[1:] if section.level > 0 and windows else windows


def claims(section: Section) -> bool:
    """True only for a section that really holds a window or holiday table.

    Claiming on geometry alone was enough for the residential sheets and was
    wrong on a commercial one, where a transition schedule of future prices
    lines up in the same three columns as a window table.
    """
    windows, holidays, _ = _split_tables(section)
    body = _body(section, windows)
    columns = _window_columns(body)
    if columns is not None and any(_is_window_row(row, columns) for row in logical_rows(body)):
        return True
    return _holiday_header(holidays) is not None


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    windows, holidays, intro = _split_tables(section)

    body = _body(section, windows)
    if section.level > 0 and windows:
        emission.take(windows[0])

    _parse_windows(body, section, citer, emission)

    if intro is not None:
        emission.notes.append(citer.text(intro, section.section_id, intro.text))
        emission.take(intro)
    _parse_holidays(holidays, section, citer, emission)
    return emission
