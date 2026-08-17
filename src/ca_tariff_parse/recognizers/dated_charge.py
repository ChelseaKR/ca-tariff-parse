"""Parse standalone charge blocks stated as one price per effective date.

These appear as an option inside a schedule rather than in the main table::

    Standby Service Charge - January 1 through December 31
    ($/kW of Contract Capacity per month)
        Effective May 1, 2025          $8.597
        Effective January 1, 2026      $8.855

The unit is whatever the parenthetical says, carried verbatim. A block with no
parenthetical unit is not emitted, because the number alone would not say what
it is a price for.
"""

from __future__ import annotations

import re

from ..model import Charge, Cited, Money
from ..segment import Section
from .base import Citer, Emission

DATED_RE = re.compile(r"\AEffective\s+(?P<when>.+?)\s+(?P<sign>-?)\$(?P<num>[\d,]+(?:\.\d+)?)\s*\Z")
UNIT_RE = re.compile(r"\A\((?P<unit>[^)]+)\)\s*\Z")


def _dated_rows(section: Section) -> list[int]:
    return [
        position for position, line in enumerate(section.content_lines) if DATED_RE.match(line.text)
    ]


def claims(section: Section) -> bool:
    return len(_dated_rows(section)) >= 2


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    rows = _dated_rows(section)
    if not rows:
        return emission

    first_row = rows[0]

    unit: Cited[str] | None = None
    label: Cited[str] | None = None
    for position in range(first_row - 1, -1, -1):
        line = lines[position]
        match = UNIT_RE.match(line.text)
        if match and unit is None:
            unit = citer.text(line, section.section_id, match.group("unit").strip())
            emission.take(line)
            continue
        if unit is not None:
            label = citer.text(line, section.section_id, line.text)
            emission.take(line)
            break

    if unit is None or label is None:
        # Without a stated unit and a stated label the numbers mean nothing on
        # their own, so nothing is emitted and the block reports as unparsed.
        return emission

    for position in rows:
        line = lines[position]
        match = DATED_RE.match(line.text)
        if not match:
            continue
        emission.charges.append(
            Charge(
                label=label,
                kind="fixed_charge",
                price=Money(
                    amount=Cited(
                        value=f"{match.group('sign')}{match.group('num')}",
                        provenance=citer.cite(line, section.section_id),
                    ),
                    currency="USD",
                    unit=unit,
                ),
                effective_from=citer.text(line, section.section_id, match.group("when").strip()),
            )
        )
        emission.take(line)

    if section.level > 0 and lines:
        emission.take(lines[0])
    return emission
