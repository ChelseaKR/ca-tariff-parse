"""Parse a per-unit credit stated on its own line.

For example::

    Credit applies to all electricity usage charges from midnight to 6:00 a.m. daily.
        Electric Vehicle Credit.................................. -$0.0150/kWh

The credit carries no effective date of its own, so it inherits the schedule's
own effective date, cited to the footer that prints it rather than assumed.
"""

from __future__ import annotations

import re

from ..model import Charge, Cited, Money
from ..segment import Section
from .base import Citer, Emission

CREDIT_RE = re.compile(
    r"\A(?P<label>.+?)\s+(?P<sign>-)\$(?P<num>\d+(?:\.\d+)?)\s*/\s*(?P<unit>[A-Za-z]+)\s*\Z"
)
APPLIES_RE = re.compile(r"\ACredit applies to\s+(?P<scope>.+?)\s*\Z", re.IGNORECASE)
WINDOW_RE = re.compile(r"\bfrom\s+(?P<window>.+?)\s*\.?\s*\Z", re.IGNORECASE)


def _credit_rows(section: Section) -> list[int]:
    return [
        position
        for position, line in enumerate(section.content_lines)
        if CREDIT_RE.match(line.text)
    ]


def claims(section: Section) -> bool:
    return bool(_credit_rows(section))


def parse(section: Section, citer: Citer, effective: Cited[str] | None) -> Emission:
    emission = Emission()
    if effective is None:
        # No document effective date was printed, so there is nothing to date
        # the credit from and it is not emitted.
        return emission

    lines = section.content_lines
    windows: list[tuple[int, Cited[str]]] = []

    for pos, line in enumerate(lines):
        match = APPLIES_RE.match(line.text)
        if not match:
            continue
        scope = match.group("scope")
        window_match = WINDOW_RE.search(scope)
        if window_match:
            window = citer.text(line, section.section_id, window_match.group("window").strip())
            windows.append((pos, window))
        emission.notes.append(citer.text(line, section.section_id, line.text))
        emission.take(line)

    for position in _credit_rows(section):
        line = lines[position]
        match = CREDIT_RE.match(line.text)
        if not match:
            continue

        # Pair each credit row with the nearest preceding applicability window
        row_window: Cited[str] | None = None
        for w_pos, w_cited in windows:
            if w_pos < position:
                row_window = w_cited
            else:
                break

        emission.charges.append(
            Charge(
                label=citer.text(line, section.section_id, match.group("label").strip()),
                kind="credit",
                price=Money(
                    amount=Cited(
                        value=f"-{match.group('num')}",
                        provenance=citer.cite(line, section.section_id),
                    ),
                    currency="USD",
                    unit=citer.text(line, section.section_id, f"$/{match.group('unit')}"),
                ),
                effective_from=effective,
                tou_period=row_window,
            )
        )
        emission.take(line)

    if section.level > 0 and lines and not section.heading_inline:
        emission.take(lines[0])
    return emission
