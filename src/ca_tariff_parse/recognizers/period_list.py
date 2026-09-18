"""Read time-of-use periods a publisher sets as a list rather than as a table.

``billing_periods`` reads a three-column window table: a season cell on the
left, a period name in the middle, a definition on the right. The second
publisher's residential time-of-use schedule does not print one. It prints a
list, under a heading, in the special conditions part::

    2. TIME PERIODS FOR E-TOU-C: Times of the year and times of the day are
    defined as follows:

    Summer (service from June 1 through September 30):

    Peak: 4:00 p.m. to 9:00 p.m. All days

    Off-Peak: All other times

    Winter (service from October 1 through May 31):

    Peak: 4:00 p.m. to 9:00 p.m. All days

    Off-Peak: All other times

There is no column to divide, so the geometry the table reader works from is
absent and its ``claims`` correctly declined the section. The result was that
``E-TOU-C`` -- the schedule named after its time-of-use periods, whose title is
*Residential Time-of-Use (Peak Pricing 4 - 9 p.m. Every Day)* -- parsed **zero**
time-of-use windows while the page stated four. That is issue #75, and it was
the parser, not the sheet.

The shape this reads is a **season heading that heads period lines**, and both
halves have to be true:

* a season heading is a line ending in a colon that states a part of the year
  ("Summer (service from June 1 through September 30):"). Requiring it to state
  a part of the year is what keeps the list's own introduction --- "... are
  defined as follows:" --- from being read as a season, the same refusal
  ``billing_periods`` makes for a column heading that is not a season;
* a period line is ``<period name>: <definition>``, and the definition has to
  say *when* the period runs: either a clock time, or an exclusion ("All other
  times"). A definition that states neither is not a window definition, and a
  line is not made into one by sitting under a season.

A period line with no season heading in force emits nothing. A season the
parser cannot read would be a season nobody published, which is the failure
ADR 0005 records from the first pass over this publisher: two windows emitted
under a season the document never wrote.

Nothing here reads a coordinate. The list is flat --- season and periods sit at
one indent --- so the order of the lines is the whole structure, and the order
is on the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import Line, normalize
from ..model import TouWindow
from ..profiles import DocumentProfile
from ..segment import Section
from .base import CLOCK_TIME, PERIOD_ALTERNATION, Citer, Emission
from .billing_periods import RESIDUAL_RE, SEASON_SPAN_RE

#: A line naming one period and defining it: ``Off-Peak: All other times``.
PERIOD_LINE_RE = re.compile(
    rf"\A(?P<period>{PERIOD_ALTERNATION}):\s*(?P<definition>\S.*)\Z",
    re.IGNORECASE,
)
#: A heading that opens a group of period lines. It has to end in a colon *and*
#: name a part of the year; "defined as follows:" does neither test's work
#: alone.
SEASON_HEADING_RE = re.compile(r"\A(?P<season>\S.*?)\s*:\Z")
#: A definition written as a plain range with the day type after it, which is
#: how this publisher writes one: "4:00 p.m. to 9:00 p.m. All days". A
#: definition carrying anything else --- an exception, a cross reference, a
#: condition --- deliberately fails this and keeps its verbatim text with no
#: start, end or day type read out of it.
LIST_RANGE_RE = re.compile(
    rf"\A(?P<start>{CLOCK_TIME})\s+to\s+(?P<end>{CLOCK_TIME})\s+"
    r"(?P<day_type>Weekdays|Weekends|All days|Every day|Daily)\s*\.?\s*\Z",
    re.IGNORECASE,
)
_CLOCK_RE = re.compile(CLOCK_TIME, re.IGNORECASE)

#: Clear space, in points, a line may sit right of the period rows and still be
#: treated as level with them rather than as text continuing one of them.
CONTINUATION_MARGIN = 1.0


def text_of(line: Line, profile: DocumentProfile) -> str:
    """The line's words, less the filing change markers in the right margin.

    A marker is furniture wherever it sits (ADR 0010); a line ending in the
    change bar this publisher's filings carry states "4:00 p.m. to 9:00 p.m.
    All days", not "... All days |". The citation still quotes the line exactly
    as printed, because stripping a glyph out of a quotation would edit it --
    only the *value* read from the line drops the marker.
    """
    words = list(line.words)
    while words and profile.is_change_marker(words[-1].text):
        words.pop()
    return normalize(" ".join(word.text for word in words))


def _states_when_a_period_runs(definition: str) -> bool:
    """True when the definition says when the period runs, rather than what it costs."""
    return bool(RESIDUAL_RE.match(definition) or _CLOCK_RE.search(definition))


@dataclass(frozen=True, slots=True)
class _Period:
    line: Line
    name: str
    definition: str


def _season_at(line: Line, profile: DocumentProfile) -> str | None:
    match = SEASON_HEADING_RE.match(text_of(line, profile))
    if match is None:
        return None
    season = match.group("season")
    if PERIOD_LINE_RE.match(text_of(line, profile)):
        # "Peak: 4:00 p.m. to 9:00 p.m." also ends in a colon on a page that
        # wraps it; a period is never its own season.
        return None
    return season if SEASON_SPAN_RE.search(season) else None


def _period_at(line: Line, profile: DocumentProfile) -> _Period | None:
    match = PERIOD_LINE_RE.match(text_of(line, profile))
    if match is None:
        return None
    definition = match.group("definition").strip()
    if not _states_when_a_period_runs(definition):
        return None
    return _Period(line, match.group("period"), definition)


def _groups(section: Section, profile: DocumentProfile) -> list[tuple[Line, str, list[_Period]]]:
    """Each season heading in this section with the period lines it heads.

    A group runs from its heading until the first line that is neither a period
    line nor the next season heading, so the list ends where the page stops
    printing it rather than at a line count.
    """
    found: list[tuple[Line, str, list[_Period]]] = []
    lines = section.content_lines
    index = 0
    while index < len(lines):
        season = _season_at(lines[index], profile)
        if season is None:
            index += 1
            continue
        heading = lines[index]
        periods: list[_Period] = []
        index += 1
        while index < len(lines):
            period = _period_at(lines[index], profile)
            if period is None:
                break
            periods.append(period)
            index += 1
        if periods and _is_flat(periods, lines[index] if index < len(lines) else None, profile):
            found.append((heading, season, periods))
    return found


def _is_flat(periods: list[_Period], terminator: Line | None, profile: DocumentProfile) -> bool:
    """True when the list ends rather than continuing off the row it stopped on.

    A flat list is one where each definition is finished on its own line. The
    other publisher's small-general-service sheet prints what looks like the
    same list and is not one: its definitions wrap, and the wrapped half is set
    far to the right of the rows --

        Peak: 4:00 p.m. to 9:00 p.m. Every day, including weekends
                                     and holidays

    -- so the row above is not a definition, it is the first line of one. Read
    as a list it publishes "Every day, including weekends" as the whole rule,
    which is a published time-of-use rule missing its last two words.

    The page says which case it is, and it says it with position: a line set to
    the right of the rows belongs to the block the rows are in; a line set left
    of them, or level with them, does not. Where a group's last row is followed
    by a line further right, the group is refused whole rather than published
    with a truncated definition.
    """
    if terminator is None or _season_at(terminator, profile) is not None:
        return True
    rows = min(period.line.indent for period in periods)
    return terminator.indent <= rows + CONTINUATION_MARGIN


def claims(section: Section, profile: DocumentProfile) -> bool:
    """True only for a section that prints periods as a list under a season."""
    return bool(_groups(section, profile))


def parse(section: Section, citer: Citer, profile: DocumentProfile) -> Emission:
    emission = Emission()
    for heading, season, periods in _groups(section, profile):
        season_cited = citer.text(heading, section.section_id, season)
        for period in periods:
            residual = bool(RESIDUAL_RE.match(period.definition))
            match = None if residual else LIST_RANGE_RE.match(period.definition)
            emission.tou_windows.append(
                TouWindow(
                    season=season_cited,
                    period=citer.text(period.line, section.section_id, period.name),
                    definition=citer.text(period.line, section.section_id, period.definition),
                    residual=residual,
                    day_type=(
                        None
                        if match is None
                        else citer.text(period.line, section.section_id, match.group("day_type"))
                    ),
                    start=(
                        None
                        if match is None
                        else citer.text(
                            period.line, section.section_id, match.group("start").strip()
                        )
                    ),
                    end=(
                        None
                        if match is None
                        else citer.text(period.line, section.section_id, match.group("end").strip())
                    ),
                )
            )
            emission.take(period.line)
        emission.take(heading)
    return emission
