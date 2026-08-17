"""End to end parse of the labelled synthetic fixture.

Every expected value below is a value written into the fixture by hand. None of
it comes from a real tariff, and the fixture says so in its own text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ca_tariff_parse.parser import parse_path


@pytest.fixture
def parsed(complete_fixture: Path):
    return parse_path(complete_fixture)


def test_the_fixture_is_flagged_synthetic(parsed) -> None:
    assert parsed.source.synthetic is True


def test_identity_is_read_off_the_document(parsed) -> None:
    identity = parsed.identity
    assert identity.schedule_code is not None
    assert identity.schedule_code.value == "SYN-1"
    assert identity.title is not None
    assert identity.title.value == "Example Service (SYNTHETIC)"
    assert identity.resolution is not None
    assert identity.resolution.value == "SYN-00-00"
    assert identity.adopted is not None
    assert identity.adopted.value == "January 1, 2026"
    assert identity.effective is not None
    assert identity.effective.value == "February 1, 2026"
    assert [sheet.value for sheet in identity.sheets] == [
        "SYN-1-1",
        "SYN-1-2",
        "SYN-1-3",
        "SYN-1-4",
    ]


def test_rate_table_values_and_columns(parsed) -> None:
    rows = {
        (c.label.value, c.effective_from.value): c
        for c in parsed.charges
        if c.kind in {"energy_usage", "fixed_charge"}
    }
    fixed = rows[("Fixed Charge per month per meter", "May 1, 2026")]
    assert fixed.price.amount.value == "11.00"
    assert fixed.price.unit.value == "per month per meter"
    assert fixed.price.currency == "USD"
    assert fixed.rate_category is not None
    assert fixed.rate_category.value == "SYN01"
    assert fixed.season is not None
    assert fixed.season.value == "Example Season (March - April)"

    peak = rows[("Peak $/kWh", "January 1, 2027")]
    assert peak.price.amount.value == "1.2000"
    assert peak.price.unit.value == "$/kWh"
    assert peak.tou_period is not None
    assert peak.tou_period.value == "Peak"


def test_a_cell_marked_not_applicable_emits_no_charge(parsed) -> None:
    """The publisher printed n/a, so there is no price to emit."""
    off_peak = [c for c in parsed.charges if c.label.value == "Off-Peak $/kWh"]
    assert [c.effective_from.value for c in off_peak] == ["January 1, 2027"]


def test_dated_charge_block(parsed) -> None:
    standby = [c for c in parsed.charges if "Standby" in c.label.value]
    assert [c.price.amount.value for c in standby] == ["1.234", "2.345"]
    assert [c.effective_from.value for c in standby] == ["May 1, 2026", "January 1, 2027"]
    assert standby[0].price.unit.value == "$/kW of Example Capacity per month"


def test_credit_inherits_the_document_effective_date(parsed) -> None:
    credit = next(c for c in parsed.charges if c.kind == "credit")
    assert credit.price.amount.value == "-0.0100"
    assert credit.price.unit.value == "$/kWh"
    assert credit.effective_from.value == "February 1, 2026"
    assert credit.tou_period is not None
    assert credit.tou_period.value == "midnight to 6:00 a.m. daily"


def test_time_of_use_windows(parsed) -> None:
    windows = {(w.season.value, w.period.value): w for w in parsed.tou_windows}
    summer_peak = windows[("Example Summer (Mar 1 - Apr 30)", "Peak")]
    assert summer_peak.residual is False
    assert summer_peak.start is not None
    assert summer_peak.start.value == "5:00 p.m."
    assert summer_peak.end is not None
    assert summer_peak.end.value == "8:00 p.m."
    assert summer_peak.day_type is not None
    assert summer_peak.day_type.value == "Weekdays"


def test_a_residual_window_carries_no_invented_clock_times(parsed) -> None:
    residual = next(w for w in parsed.tou_windows if w.residual)
    assert residual.start is None
    assert residual.end is None
    assert "All other hours" in residual.definition.value


def test_a_window_with_an_exception_carries_no_clock_times(parsed) -> None:
    """ "between noon and midnight except during the Peak hours" is not a range."""
    mid = next(w for w in parsed.tou_windows if w.period.value == "Mid-Peak")
    assert mid.residual is False
    assert mid.start is None
    assert mid.end is None
    assert "except during the Peak hours" in mid.definition.value


def test_holidays(parsed) -> None:
    holidays = {h.name.value: (h.month.value, h.day_rule.value) for h in parsed.holidays}
    assert holidays["Example New Year Day"] == ("January", "1")
    assert holidays["Example Spring Day"] == ("March", "Third Monday")


def test_cross_references(parsed) -> None:
    assert [x.target.value for x in parsed.cross_references] == ["SYN-HGA"]


def test_applicability_dispositions(parsed) -> None:
    dispositions = {a.disposition for a in parsed.applicability}
    assert "included" in dispositions
    assert "excluded" in dispositions
    excluded = next(a for a in parsed.applicability if a.disposition == "excluded")
    assert "not eligible" in excluded.text.value


def test_every_charge_carries_a_resolvable_citation(parsed) -> None:
    for charge in parsed.charges:
        prov = charge.price.amount.provenance
        assert prov.document_id
        assert len(prov.document_sha256) == 64
        assert prov.page >= 1
        assert prov.line >= 1
        assert prov.snippet
        # The cited snippet must actually contain the amount that was emitted.
        assert charge.price.amount.value.lstrip("-") in prov.snippet


def test_citation_sheets_track_the_page(parsed) -> None:
    for charge in parsed.charges:
        prov = charge.price.amount.provenance
        assert prov.sheet == f"SYN-1-{prov.page}"
