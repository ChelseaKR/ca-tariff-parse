"""Parse a priced table that dates itself from a bare year in its own header.

Every other priced table this parser reads dates a column either from the
words "Effective as of" printed over it (:mod:`rate_table`) or from the sheet
footer beneath it (:mod:`sheet_rates`). One table dates itself a third way,
heading its single price column with nothing but the year itself and a
footnote mark::

    Season and Charge Component                    Unit      2028*
    CITS-0: C&I Secondary 0-20 kW
        System Infrastructure Fixed Charge          per month  $44.45
        Maximum Demand Charge                       per kW     $4.101
        Non-Summer Peak                              per kWh   $0.1506
    *Subject to future rate increases.

Unlike either of those tables, the unit is not stated once for the whole
block: it is the tail of each row's own label, exactly the way
:func:`~ca_tariff_parse.recognizers.base.unit_tail` already reads it
elsewhere. And unlike the main rate table's own rows, a season and a
time-of-use period are not split onto a heading row above the block; they are
folded into the same label as the charge itself ("Non-Summer Peak"), so both
are read from that label rather than from context above it.

The footnote asterisk on the year is not carried into ``effective_from``: it
marks the footnote below the table, not the date itself, and the footnote's
own sentence is left for the ordinary unparsed accounting to carry verbatim
rather than attached to every price under it.
"""

from __future__ import annotations

import re

from ..extract import Line, normalize, squash
from ..model import Charge, Cited, Money
from ..segment import Section
from .base import (
    MONEY_RE,
    PERIOD_ALTERNATION,
    Citer,
    Emission,
    category_code,
    unit_tail,
)

#: The table's own header must both say "Unit" and end in a bare year, with an
#: optional footnote mark. Requiring both is what tells this header apart from
#: any other line that merely happens to end in four digits.
HEADER_UNIT_RE = re.compile(r"\bUnit\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\A(?P<year>(?:19|20)\d{2})\**\Z")

#: A row's label, once its unit is stripped, states its season and
#: time-of-use period together rather than inheriting them from a heading row
#: above the block, e.g. "Non-Summer Peak" or "Summer Off-Peak Saver".
SEASON_PERIOD_RE = re.compile(
    rf"\A(?P<season>Non-Summer|Summer)\s+(?P<period>{PERIOD_ALTERNATION})\Z", re.IGNORECASE
)
#: Squashed units that make a row an energy charge rather than a fixed one.
ENERGY_UNITS = frozenset({"$/kwh", "$perkwh", "perkwh"})


def _find_header(section: Section) -> int | None:
    for position, line in enumerate(section.content_lines):
        words = line.words
        if len(words) < 2 or not HEADER_UNIT_RE.search(line.text):
            continue
        if YEAR_RE.match(words[-1].text):
            return position
    return None


def claims(section: Section) -> bool:
    return _find_header(section) is not None


def _read_row(line: Line) -> tuple[str, str, str] | None:
    """Read one ``label ... $amount`` row: the full label, its unit, and the
    amount. ``None`` when the line is not one, or its unit cannot be read."""
    words = line.words
    if len(words) < 2:
        return None
    money = MONEY_RE.match(words[-1].text)
    if money is None:
        return None
    label = normalize(" ".join(w.text for w in words[:-1]))
    unit = unit_tail(label)
    if unit is None:
        return None
    return label, unit, f"{money.group('sign')}{money.group('num')}"


def _season_and_period(label: str, unit: str) -> tuple[str, str] | None:
    stem = label.removesuffix(unit).strip()
    match = SEASON_PERIOD_RE.match(stem)
    if match is None:
        return None
    return match.group("season"), match.group("period")


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    header_at = _find_header(section)
    if header_at is None:
        return emission

    header_line = lines[header_at]
    year_match = YEAR_RE.match(header_line.words[-1].text)
    if year_match is None:  # pragma: no cover - _find_header already required this
        return emission
    effective = citer.text(header_line, section.section_id, year_match.group("year"))

    category: Cited[str] | None = None
    found_row = False
    for line in lines[header_at + 1 :]:
        row = _read_row(line)
        if row is None:
            code = category_code(line.text)
            if code is not None:
                category = citer.text(line, section.section_id, code)
                emission.take(line)
            # Any other unrecognised line (the footnotes, in practice) is left
            # unconsumed so it is carried verbatim rather than swallowed.
            continue

        label, unit, amount = row
        seasonal = _season_and_period(label, unit)
        season = citer.text(line, section.section_id, seasonal[0]) if seasonal else None
        tou_period = citer.text(line, section.section_id, seasonal[1]) if seasonal else None
        kind = "energy_usage" if squash(unit) in ENERGY_UNITS else "fixed_charge"

        emission.charges.append(
            Charge(
                label=citer.text(line, section.section_id, label),
                kind=kind,
                price=Money(
                    amount=Cited(value=amount, provenance=citer.cite(line, section.section_id)),
                    currency="USD",
                    unit=citer.text(line, section.section_id, unit),
                ),
                effective_from=effective,
                rate_category=category,
                season=season,
                tou_period=tou_period,
            )
        )
        emission.take(line)
        found_row = True

    if found_row:
        emission.take(header_line)
    return emission
