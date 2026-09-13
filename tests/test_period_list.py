"""Time-of-use periods set as a list, and the four cases where none is emitted.

Built from hand positioned lines rather than a monospace fixture, the way
``test_condition_list.py`` and ``test_proration.py`` are: what decides three of
these cases is indent, and a character grid cannot place a hanging indent the
way a filed sheet does.

The real document that motivated this reader (``E-TOU-C``, issue #75) exercises
the happy path and none of the refusals -- its own introductory line is not
followed by a period line, so the season test never has to reject anything
there. A refusal no fixture reaches is a refusal nothing checks, so each one is
reached here directly.
"""

from __future__ import annotations

from ca_tariff_parse.extract import LayoutDoc, Line, Page, Word
from ca_tariff_parse.profiles import resolve
from ca_tariff_parse.recognizers import period_list
from ca_tariff_parse.recognizers.base import Citer
from ca_tariff_parse.segment import Section

PROFILE = resolve("pge-tariff-book")
ROWS = 190.0
#: Where this publisher sets the wrapped half of a definition, well right of
#: the rows: measured at 400.5 points on the sheet this refusal comes from.
FAR_RIGHT = 400.0

SEASON = "Summer (service from June 1 through September 30):"
INTRO = "Times of the year and times of the day are defined as follows:"
PEAK = "Peak: 4:00 p.m. to 9:00 p.m. All days"
OFF_PEAK = "Off-Peak: All other times"


def _line(index: int, indent: float, text: str) -> Line:
    words = tuple(
        Word(text=word, x0=indent + i * 30.0, x1=indent + i * 30.0 + 25.0)
        for i, word in enumerate(text.split(" "))
    )
    return Line(page=1, index=index, top=float(index) * 14.0, words=words, furniture=False)


def _doc(lines: tuple[Line, ...]) -> LayoutDoc:
    page = Page(number=1, height=792.0, lines=lines, sheet="SYN-5")
    return LayoutDoc(
        document_id="syn-periods",
        sha256="b" * 64,
        filename="<inline>",
        byte_size=0,
        pages=(page,),
        synthetic=True,
    )


def _section(lines: tuple[Line, ...]) -> Section:
    return Section(
        section_id="SPECIALCONDITIONS",
        level=1,
        heading="SPECIAL CONDITIONS",
        lines=list(lines),
        heading_inline=True,
    )


def _read(lines: tuple[Line, ...]):
    section = _section(lines)
    claimed = period_list.claims(section, PROFILE)
    emission = period_list.parse(section, Citer(_doc(lines)), PROFILE)
    assert claimed is bool(emission.tou_windows)
    return emission


def test_a_season_heading_heads_the_period_lines_under_it() -> None:
    lines = (
        _line(1, ROWS, SEASON),
        _line(2, ROWS, PEAK),
        _line(3, ROWS, OFF_PEAK),
    )
    emission = _read(lines)

    assert [window.period.value for window in emission.tou_windows] == ["Peak", "Off-Peak"]
    assert all(
        window.season.value == "Summer (service from June 1 through September 30)"
        for window in emission.tou_windows
    )
    peak, off_peak = emission.tou_windows
    assert (peak.residual, peak.start.value, peak.end.value, peak.day_type.value) == (
        False,
        "4:00 p.m.",
        "9:00 p.m.",
        "All days",
    )
    # Defined by exclusion, so no clock is invented for it.
    assert off_peak.residual is True
    assert (off_peak.start, off_peak.end, off_peak.day_type) == (None, None, None)
    assert off_peak.definition.value == "All other times"
    for index in (1, 2, 3):
        assert (1, index) in emission.consumed


def test_a_heading_that_names_no_part_of_the_year_is_not_a_season() -> None:
    """The list's own introduction ends in a colon too.

    Reading it as a season would publish two windows under a season the
    document never wrote, which is the failure ADR 0005 records from the first
    pass over this publisher.
    """
    lines = (_line(1, ROWS, INTRO), _line(2, ROWS, PEAK), _line(3, ROWS, OFF_PEAK))
    emission = _read(lines)

    assert emission.tou_windows == []
    assert emission.consumed == set()


def test_a_period_line_with_no_season_in_force_emits_nothing() -> None:
    lines = (_line(1, ROWS, PEAK), _line(2, ROWS, OFF_PEAK))
    emission = _read(lines)

    assert emission.tou_windows == []


def test_a_definition_that_states_no_time_is_not_a_window_definition() -> None:
    """A cross reference sitting in the definition's place is not a rule."""
    lines = (
        _line(1, ROWS, SEASON),
        _line(2, ROWS, "Peak: See Section 5 of this schedule."),
    )
    emission = _read(lines)

    assert emission.tou_windows == []


def test_a_row_followed_by_text_set_further_right_is_refused_whole() -> None:
    """The wrapped-definition shape, in miniature.

    Read as a list this publishes "Every day, including weekends" as the whole
    rule -- a holiday rule saying the opposite of the page.
    """
    lines = (
        _line(1, ROWS, SEASON),
        _line(2, ROWS, "Peak: 4:00 p.m. to 9:00 p.m. Every day, including weekends"),
        _line(3, FAR_RIGHT, "and holidays"),
    )
    emission = _read(lines)

    assert emission.tou_windows == []
    assert emission.consumed == set()


def test_the_next_season_heading_ends_a_group_without_refusing_it() -> None:
    """A second season is not a continuation, so it does not refuse the first."""
    lines = (
        _line(1, ROWS, SEASON),
        _line(2, ROWS, PEAK),
        _line(3, ROWS, "Winter (service from October 1 through May 31):"),
        _line(4, ROWS, PEAK),
    )
    emission = _read(lines)

    assert [window.season.value for window in emission.tou_windows] == [
        "Summer (service from June 1 through September 30)",
        "Winter (service from October 1 through May 31)",
    ]


def test_a_change_bar_in_the_right_margin_is_not_part_of_the_rule() -> None:
    """The value drops the filing glyph; the citation still quotes the line as printed."""
    lines = (
        _line(1, ROWS, SEASON + " |"),
        _line(2, ROWS, PEAK + " (R)"),
    )
    emission = _read(lines)

    window = emission.tou_windows[0]
    assert window.definition.value == "4:00 p.m. to 9:00 p.m. All days"
    assert window.end.value == "9:00 p.m."
    assert window.season.value == "Summer (service from June 1 through September 30)"
    assert window.definition.provenance.snippet.endswith("(R)")
    assert window.season.provenance.snippet.endswith("|")
