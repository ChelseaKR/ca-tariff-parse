"""What the calendar expresses, and — the point of it — what it refuses to.

A calendar of tariff hours is the first consumer-facing derivation this
project ships, so the fence matters more than the feature. Every test here
holds one of two lines: a rule may only re-express text the parser already
committed to, and a rule that is not written must appear in the refusal list
rather than simply not being there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ca_tariff_parse import Cited, Holiday, Provenance, TouWindow, load
from ca_tariff_parse.calendar import ANCHOR_YEAR, CalendarError, Rendered, render
from ca_tariff_parse.cli import main

from .conftest import GOLDEN, REPO_ROOT, provenance

BASELINES = REPO_ROOT / "data" / "parsed"


def cite(value: str, **overrides: object) -> Cited[str]:
    return Cited(value, Provenance(**provenance(**overrides)))


def holiday(name: str, month: str, day_rule: str) -> Holiday:
    return Holiday(name=cite(name), month=cite(month), day_rule=cite(day_rule))


def window(
    season: str,
    period: str,
    definition: str,
    *,
    residual: bool = False,
    day_type: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> TouWindow:
    return TouWindow(
        season=cite(season),
        period=cite(period),
        definition=cite(definition),
        residual=residual,
        day_type=cite(day_type) if day_type else None,
        start=cite(start) if start else None,
        end=cite(end) if end else None,
    )


def one_off(**fields: object) -> Rendered:
    """Render a real parse carrying only the windows or holidays given.

    Both collections are emptied first, so a case about one holiday is not
    read against the golden's own five windows.
    """
    from dataclasses import replace

    schedule = load(GOLDEN / "smud-r-tod.json")
    base = {"tou_windows": (), "holidays": ()}
    return render(replace(schedule, **{**base, **fields}))


def lines(rendered: Rendered) -> list[str]:
    return rendered.ics.replace("\r\n ", "").replace("\r\n", "\n").splitlines()


def events(rendered: Rendered) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines(rendered):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            assert current is not None
            found.append(current)
            current = None
        elif current is not None and ":" in line:
            name, value = line.split(":", 1)
            current[name.split(";")[0]] = value
    return found


@pytest.fixture(scope="module")
def rtod() -> Rendered:
    return render(load(GOLDEN / "smud-r-tod.json"))


# ---------------------------------------------------------------------------
# What is expressed comes from what was read
# ---------------------------------------------------------------------------


def test_the_peak_windows_carry_the_hours_their_citation_states(rtod: Rendered) -> None:
    schedule = load(GOLDEN / "smud-r-tod.json")
    peaks = [
        w
        for w in schedule.tou_windows
        if w.start is not None and w.end is not None and not w.residual
    ]
    assert peaks, "expected smud-r-tod to state at least one bare peak window"
    rendered = [event for event in events(rtod) if "FREQ=WEEKLY" in event.get("RRULE", "")]
    assert len(rendered) == len(peaks)
    for event, source in zip(rendered, peaks, strict=True):
        # 5:00 p.m. -> 170000, 8:00 p.m. -> 200000
        assert event["DTSTART"].endswith("T170000"), source.start.value
        assert event["DTEND"].endswith("T200000"), source.end.value
        assert "BYDAY=MO,TU,WE,TH,FR" in event["RRULE"]
        assert source.definition.provenance.locator in event["X-CA-CITATION"]


def test_a_weekly_rule_starts_on_a_day_its_own_rule_includes(rtod: Rendered) -> None:
    """A DTSTART outside its recurrence is an extra occurrence to some readers."""
    import datetime as dt

    for event in events(rtod):
        if "FREQ=WEEKLY" not in event.get("RRULE", ""):
            continue
        stamp = event["DTSTART"][:8]
        weekday = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])).weekday()
        codes = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
        allowed = event["RRULE"].split("BYDAY=")[1].split(";")[0].split(",")
        assert codes[weekday] in allowed, event


def test_a_yearly_rule_starts_on_a_date_its_own_rule_includes(rtod: Rendered) -> None:
    import datetime as dt

    for event in events(rtod):
        rule = event.get("RRULE", "")
        if "FREQ=YEARLY" not in rule:
            continue
        stamp = event["DTSTART"]
        date = dt.date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        assert date.month == int(rule.split("BYMONTH=")[1].split(";")[0])
        if "BYMONTHDAY=" in rule:
            assert date.day == int(rule.split("BYMONTHDAY=")[1].split(";")[0])


def test_season_bounds_are_added_only_where_the_season_states_whole_months(
    rtod: Rendered,
) -> None:
    weekly = [e for e in events(rtod) if "FREQ=WEEKLY" in e.get("RRULE", "")]
    assert weekly
    for event in weekly:
        if event["X-CA-SEASON-BOUNDS"] == "stated":
            assert "BYMONTH=" in event["RRULE"]
        else:
            assert "BYMONTH=" not in event["RRULE"]


def test_a_season_without_a_month_range_is_partial_and_unbounded() -> None:
    rendered = one_off(
        tou_windows=(
            window(
                "Peak Season",
                "Peak",
                "Weekdays between 5:00 p.m. and 8:00 p.m.",
                day_type="Weekdays",
                start="5:00 p.m.",
                end="8:00 p.m.",
            ),
        )
    )
    event = next(e for e in events(rendered) if "FREQ=WEEKLY" in e.get("RRULE", ""))
    assert event["X-CA-SEASON-BOUNDS"] == "partial"
    assert "BYMONTH=" not in event["RRULE"]
    assert "Peak Season" in event["SUMMARY"]


def test_a_partial_month_range_is_not_widened_to_whole_months() -> None:
    """June 15 to September 30 is not BYMONTH=6,7,8,9, and rounding it either
    way is a claim the document did not make."""
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 15 - Sept 30)",
                "Peak",
                "Weekdays between 5:00 p.m. and 8:00 p.m.",
                day_type="Weekdays",
                start="5:00 p.m.",
                end="8:00 p.m.",
            ),
        )
    )
    event = next(e for e in events(rendered) if "FREQ=WEEKLY" in e.get("RRULE", ""))
    assert event["X-CA-SEASON-BOUNDS"] == "partial"
    assert "BYMONTH=" not in event["RRULE"]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_the_residual_window_appears_only_in_the_refusal_list(rtod: Rendered) -> None:
    schedule = load(GOLDEN / "smud-r-tod.json")
    residual = [w for w in schedule.tou_windows if w.residual]
    assert residual, "expected smud-r-tod to state a residual window"
    body = rtod.ics
    for source in residual:
        assert source.definition.value not in body
    refused = {item.locator for item in rtod.refused}
    for source in residual:
        assert source.definition.provenance.locator in refused


def test_a_residual_window_is_refused_even_when_it_carries_hours() -> None:
    """The fence has to be the residual flag itself, not the absence of times.

    In the committed documents a residual window happens to carry no start or
    end, so a check that only looked for missing times would pass while the
    residual fence did nothing. A residual period with hours beside it is
    still defined by exclusion, and the hours do not say what it excludes.
    """
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 1 - Sept 30)",
                "Off-Peak",
                "All other hours, including weekends and holidays.",
                residual=True,
                day_type="Weekdays",
                start="5:00 p.m.",
                end="8:00 p.m.",
            ),
        )
    )
    assert rendered.rendered_windows == 0
    assert len(rendered.refused) == 1
    assert "by exclusion" in rendered.refused[0].reason
    assert "BEGIN:VEVENT" not in rendered.ics


def test_the_residual_refusal_names_exclusion_not_a_missing_time(
    rtod: Rendered,
) -> None:
    schedule = load(GOLDEN / "smud-r-tod.json")
    residual_locators = {
        w.definition.provenance.locator for w in schedule.tou_windows if w.residual
    }
    assert residual_locators
    for item in rtod.refused:
        if item.locator in residual_locators:
            assert "by exclusion" in item.reason


def test_every_window_and_holiday_is_either_rendered_or_refused(rtod: Rendered) -> None:
    """Nothing may simply not be there. A calendar missing a window with no
    refusal beside it reads as a complete calendar."""
    kinds = [item.kind for item in rtod.refused]
    assert kinds.count("tou_window") + rtod.rendered_windows == rtod.total_windows
    assert kinds.count("holiday") + rtod.rendered_holidays == rtod.total_holidays


def test_a_day_rule_of_1_renders_as_a_fixed_day_rule() -> None:
    rendered = one_off(holidays=(holiday("New Year's Day", "January", "1"),))
    assert not rendered.refused
    event = next(e for e in events(rendered) if "FREQ=YEARLY" in e.get("RRULE", ""))
    assert event["RRULE"] == "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1"


def test_day_after_thanksgiving_is_refused_not_approximated() -> None:
    """It is a real rule and a defensible date, and it is not in the grammar.
    Putting the fourth Friday there would be a guess with a calendar entry's
    authority."""
    rendered = one_off(
        holidays=(holiday("Day after Thanksgiving", "November", "Day after Thanksgiving"),)
    )
    assert rendered.rendered_holidays == 0
    assert len(rendered.refused) == 1
    refusal = rendered.refused[0]
    assert refusal.kind == "holiday"
    assert refusal.stated == "Day after Thanksgiving"
    assert "closed grammar" in refusal.reason
    assert "Day after Thanksgiving" not in rendered.ics


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("Third Monday", "FREQ=YEARLY;BYMONTH=1;BYDAY=3MO"),
        ("Last Monday", "FREQ=YEARLY;BYMONTH=1;BYDAY=-1MO"),
        ("First Sunday", "FREQ=YEARLY;BYMONTH=1;BYDAY=1SU"),
        ("15", "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=15"),
    ],
)
def test_each_accepted_day_rule_form(rule: str, expected: str) -> None:
    rendered = one_off(holidays=(holiday("A holiday", "January", rule),))
    assert not rendered.refused, rendered.refused
    event = next(e for e in events(rendered) if "FREQ=YEARLY" in e.get("RRULE", ""))
    assert event["RRULE"] == expected


@pytest.mark.parametrize(
    "rule",
    ["Day after Thanksgiving", "The Friday before Labor Day", "Sixth Monday", "0", "32", ""],
)
def test_each_day_rule_outside_the_grammar_is_refused(rule: str) -> None:
    if rule == "":
        pytest.skip("Cited refuses an empty value at construction, one layer earlier")
    rendered = one_off(holidays=(holiday("A holiday", "January", rule),))
    assert rendered.rendered_holidays == 0
    assert len(rendered.refused) == 1


def test_a_window_with_hours_but_no_day_type_is_refused_not_assumed_daily() -> None:
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 1 - Sept 30)",
                "Peak",
                "Between 5:00 p.m. and 8:00 p.m.",
                start="5:00 p.m.",
                end="8:00 p.m.",
            ),
        )
    )
    assert rendered.rendered_windows == 0
    assert "no day type" in rendered.refused[0].reason


def test_a_day_type_outside_the_grammar_is_refused() -> None:
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 1 - Sept 30)",
                "Peak",
                "Weekdays excluding holidays between 5:00 p.m. and 8:00 p.m.",
                day_type="Weekdays excluding holidays",
                start="5:00 p.m.",
                end="8:00 p.m.",
            ),
        )
    )
    assert rendered.rendered_windows == 0
    assert "closed grammar" in rendered.refused[0].reason


def test_a_window_that_crosses_midnight_is_refused_not_split() -> None:
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 1 - Sept 30)",
                "Peak",
                "Weekdays between 10:00 p.m. and 6:00 a.m.",
                day_type="Weekdays",
                start="10:00 p.m.",
                end="6:00 a.m.",
            ),
        )
    )
    assert rendered.rendered_windows == 0
    assert "crosses midnight" in rendered.refused[0].reason


def test_a_prose_time_phrase_is_refused_rather_than_read_as_a_clock() -> None:
    """`tou_period` and the window times sometimes hold a phrase the publisher
    wrote as prose. It is not a clock time and is not treated as one."""
    rendered = one_off(
        tou_windows=(
            window(
                "Summer (Jun 1 - Sept 30)",
                "Off-Peak",
                "Weekdays from midnight to 6:00 a.m. daily",
                day_type="Weekdays",
                start="midnight to 6:00 a.m. daily",
                end="6:00 a.m.",
            ),
        )
    )
    assert rendered.rendered_windows == 0
    assert "closed grammar" in rendered.refused[0].reason


def test_a_document_that_states_no_windows_refuses_nothing_and_renders_nothing() -> None:
    rendered = render(load(GOLDEN / "smud-ssr.json"))
    assert rendered.total_windows == 0
    assert rendered.refused == []
    assert "BEGIN:VEVENT" not in rendered.ics


def test_a_document_whose_every_window_is_refused_renders_no_events() -> None:
    rendered = render(load(GOLDEN / "smud-ci-tod1.json"))
    assert rendered.rendered_windows == 0
    assert rendered.total_windows == 5
    assert len([r for r in rendered.refused if r.kind == "tou_window"]) == 5


# ---------------------------------------------------------------------------
# The refusal file is part of the output
# ---------------------------------------------------------------------------


def test_the_refusal_file_states_how_much_was_and_was_not_rendered(
    tmp_path: Path,
) -> None:
    assert main(["calendar", str(GOLDEN / "smud-r-tod.json"), "--dir", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "smud-r-tod.refused.json").read_text(encoding="utf-8"))
    assert payload["stated"] == {"tou_windows": 5, "holidays": 11}
    assert payload["rendered"] == {"tou_windows": 2, "holidays": 11}
    assert len(payload["refused"]) == 3
    for item in payload["refused"]:
        assert item["locator"]
        assert item["reason"]
        assert item["stated"]


def test_the_refusal_file_is_written_even_when_nothing_was_refused(
    tmp_path: Path,
) -> None:
    """A missing file reads as "no refusal list", which is a different
    statement from "nothing was refused"."""
    assert main(["calendar", str(GOLDEN / "smud-ssr.json"), "--dir", str(tmp_path)]) == 0
    payload = json.loads((tmp_path / "smud-ssr.refused.json").read_text(encoding="utf-8"))
    assert payload["refused"] == []


def test_the_calendar_says_it_is_incomplete_where_it_is(tmp_path: Path) -> None:
    assert main(["calendar", str(GOLDEN / "smud-r-tod.json"), "--dir", str(tmp_path)]) == 0
    ics = (tmp_path / "smud-r-tod.ics").read_text(encoding="utf-8")
    assert "X-CA-REFUSALS:3 window" in ics.replace("\r\n ", "")


# ---------------------------------------------------------------------------
# Determinism and file shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["smud-r-tod", "smud-r", "smud-ci-tod1", "smud-ssr"])
def test_an_identical_parse_renders_identical_bytes(name: str) -> None:
    schedule = load(GOLDEN / f"{name}.json")
    first = render(schedule)
    second = render(load(GOLDEN / f"{name}.json"))
    assert first.ics == second.ics
    assert first.refused_json() == second.refused_json()


def test_nothing_in_the_output_reads_the_clock() -> None:
    """A generation time would make two renderings of one parse differ."""
    rendered = render(load(GOLDEN / "smud-r-tod.json"))
    stamps = {line for line in lines(rendered) if line.startswith("DTSTAMP:")}
    assert len(stamps) == 1
    # smud-r-tod's manifest entry states a retrieval date; the stamp is that,
    # not now.
    assert stamps == {"DTSTAMP:20260817T000000Z"}


def test_content_lines_are_folded_to_75_octets() -> None:
    rendered = render(load(GOLDEN / "smud-r-tod.json"))
    for line in rendered.ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75, line


def test_the_file_is_crlf_terminated_and_well_formed() -> None:
    rendered = render(load(GOLDEN / "smud-r-tod.json"))
    assert rendered.ics.startswith("BEGIN:VCALENDAR\r\n")
    assert rendered.ics.endswith("END:VCALENDAR\r\n")
    unfolded = lines(rendered)
    assert unfolded.count("BEGIN:VEVENT") == unfolded.count("END:VEVENT")
    assert unfolded.count("BEGIN:VEVENT") == rendered.rendered_windows + rendered.rendered_holidays


def test_the_calendar_says_it_infers_no_time_zone() -> None:
    rendered = render(load(GOLDEN / "smud-r-tod.json"))
    body = rendered.ics.replace("\r\n ", "")
    assert "X-CA-TIME-ZONE:none." in body
    assert "TZID" not in body
    assert f"X-CA-ANCHOR-YEAR:{ANCHOR_YEAR}" in body


def test_a_semicolon_or_comma_in_a_value_is_escaped() -> None:
    rendered = one_off(holidays=(holiday("Christmas; Boxing, Day", "December", "25"),))
    body = rendered.ics.replace("\r\n ", "")
    assert r"SUMMARY:Christmas\; Boxing\, Day" in body


# ---------------------------------------------------------------------------
# A baseline is not a full parse
# ---------------------------------------------------------------------------


def test_a_watch_baseline_is_refused_with_its_omissions_named() -> None:
    with pytest.raises(CalendarError, match="watch baseline"):
        render(load(BASELINES / "smud-r-tod.json"))


def test_the_command_reports_that_refusal_rather_than_writing_half_a_calendar(
    tmp_path: Path,
) -> None:
    assert main(["calendar", str(BASELINES / "smud-r-tod.json"), "--dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
