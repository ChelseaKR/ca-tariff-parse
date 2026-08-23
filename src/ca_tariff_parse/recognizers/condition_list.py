"""Capture a numbered list of conditions that must all be met, verbatim.

Some rate options are gated outside any Applicability or Eligibility part::

    D. Standby Service Option
    Standby Service applies when all of the following conditions are met:
    1. The customer has generation, sited on the customer's premises, that
    serves all or part of the customer's load; and
    2. The generator(s) have a combined nameplate rating less than 100 kW; and
    3. The generator(s) are connected to SMUD's electrical system; and
    4. SMUD is required to have resources available to provide supplemental
    service, backup electricity and/or to supply electricity during
    generator(s) maintenance service.

``applicability.py`` never sees this: its ``claims`` only fires on the
Applicability part itself and on a section headed Eligibility, and this list
sits under "D. Standby Service Option", a rate option heading like any other.
The intro sentence is the trigger this recognizer looks for instead, wherever
it appears: ending in "the following conditions are met", it is a narrow
enough phrase that a rate schedule is unlikely to use it for anything else,
and everything after it must still resolve to a strictly numbered, unbroken
list before anything is emitted.

Read as an :class:`~ca_tariff_parse.model.Applicability`, an item here would
need a ``disposition``, and none of "included", "excluded" or "required" fits
one condition of a conjunction the intro sentence already states in full. So
this is a distinct shape, :class:`~ca_tariff_parse.model.Condition`, that
carries no disposition at all.
"""

from __future__ import annotations

import re

from ..extract import Line, normalize
from ..model import Cited, Condition
from ..segment import Section
from .base import Citer, Emission, strip_item_number

#: The intro sentence that gates the list, e.g. "Standby Service applies when
#: all of the following conditions are met:" or, dropping "all of", "...when
#: the following conditions are met:". Anchored at the end of the line so a
#: sentence that merely mentions conditions in passing does not match.
INTRO_RE = re.compile(r"following conditions? (?:are|is) met\s*:\s*\Z", re.IGNORECASE)
#: One item's own numbering, e.g. "1. " or "12. ".
ITEM_RE = re.compile(r"\A(?P<num>\d+)\.\s+\S")
#: A line that closes the sentence it ends, allowing one trailing "and"/"or"
#: the way these lists join their last two items. A line without one of these
#: is still being written and its next, more deeply indented line is read as
#: its wrapped continuation; a line that already has one is not, even if a
#: later line happens to share its indent by coincidence of layout.
TERMINATED_RE = re.compile(r"[.;:]\s*(?:and|or)?\s*\Z", re.IGNORECASE)


def _intro_positions(section: Section) -> list[int]:
    return [i for i, line in enumerate(section.content_lines) if INTRO_RE.search(line.text)]


def claims(section: Section) -> bool:
    return bool(_intro_positions(section))


def _read_item(lines: list[Line], start: int) -> tuple[list[Line], int, int] | None:
    """The lines, next position and number of the item starting at ``start``.

    ``None`` when ``lines[start]`` does not open a numbered item at all. A
    short item is one line. A wrapped one keeps adding the lines after it for
    as long as each is indented past the item's own bullet and the text read
    so far has not yet reached a sentence's end, which is what tells a
    genuine wrap ("...to supply" / "electricity during... service.") apart
    from the next thing on the page merely sharing that indent, such as the
    priced block these options are so often followed by.
    """
    first = lines[start]
    match = ITEM_RE.match(first.text)
    if match is None:
        return None
    item = [first]
    text = first.text
    position = start + 1
    while (
        position < len(lines)
        and TERMINATED_RE.search(text) is None
        and lines[position].indent > first.indent
    ):
        item.append(lines[position])
        text = normalize(f"{text} {lines[position].text}")
        position += 1
    return item, position, int(match.group("num"))


def _read_list(lines: list[Line], start: int) -> list[list[Line]]:
    """Every item of a strictly numbered list beginning at ``lines[start]``.

    Numbers must run 1, 2, 3, ... with no gap and no repeat, the same
    discipline :mod:`ca_tariff_parse.segment` already applies to a roman
    numeral heading: a numbered item out of sequence is not part of this
    list, whatever else it looks like.
    """
    items: list[list[Line]] = []
    position = start
    expected = 1
    while position < len(lines):
        read = _read_item(lines, position)
        if read is None or read[2] != expected:
            break
        item_lines, position, _num = read
        items.append(item_lines)
        expected += 1
    return items


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    lines = section.content_lines
    for at in _intro_positions(section):
        intro = lines[at]
        items = _read_list(lines, at + 1)
        if not items:
            # The sentence promised a list and none followed with certainty;
            # nothing is emitted and the sentence itself is left unparsed
            # rather than reported as understood.
            continue
        subject = citer.text(intro, section.section_id, intro.text)
        for item_lines in items:
            text = strip_item_number(normalize(" ".join(line.text for line in item_lines)))
            if not text:  # pragma: no cover - ITEM_RE already requires a non-space token
                continue
            provenance = citer.cite_span(item_lines, section.section_id)
            emission.conditions.append(
                Condition(subject=subject, text=Cited(value=text, provenance=provenance))
            )
            emission.take(*item_lines)
        emission.take(intro)
    return emission
