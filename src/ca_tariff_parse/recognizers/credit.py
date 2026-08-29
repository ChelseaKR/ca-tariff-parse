"""Parse a per-unit credit stated on its own line.

For example::

    Credit applies to all electricity usage charges from midnight to 6:00 a.m. daily.
        Electric Vehicle Credit.................................. -$0.0150/kWh

The credit carries no effective date of its own, so it inherits the schedule's
own effective date, cited to the footer that prints it rather than assumed.

One section can state more than one credit, each under its own applicability
sentence. A credit takes the window of the nearest sentence above it and no
other: reading past that sentence to a later one would publish a real quote,
with real provenance, saying a price applies during hours the publisher gave
to a different credit. A credit standing above every such sentence takes no
window, and so does one whose nearest sentence states a scope without hours,
because in both cases the document states no window for that credit and the
next one down belongs to something else.
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


def _window_above(windows: list[tuple[int, Cited[str] | None]], position: int) -> Cited[str] | None:
    """The window stated by the nearest applicability sentence above ``position``.

    ``None`` when no sentence precedes the credit, or when the nearest one
    states no window. Nothing below the credit is consulted, because a sentence
    under it introduces the next credit rather than this one.
    """
    above = [window for at, window in windows if at < position]
    return above[-1] if above else None


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
    #: Every applicability sentence in the section, by the position it sits at
    #: and the window it states, which is ``None`` when it states a scope with
    #: no hours in it.
    windows: list[tuple[int, Cited[str] | None]] = []

    for position, line in enumerate(lines):
        match = APPLIES_RE.match(line.text)
        if not match:
            continue
        scope = match.group("scope")
        window_match = WINDOW_RE.search(scope)
        stated = (
            citer.text(line, section.section_id, window_match.group("window").strip())
            if window_match
            else None
        )
        windows.append((position, stated))
        emission.notes.append(citer.text(line, section.section_id, line.text))
        emission.take(line)

    for position in _credit_rows(section):
        line = lines[position]
        match = CREDIT_RE.match(line.text)
        if not match:
            continue
        window = _window_above(windows, position)
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
                tou_period=window,
            )
        )
        emission.take(line)

    if section.level > 0 and lines and not section.heading_inline:
        emission.take(lines[0])
    return emission
