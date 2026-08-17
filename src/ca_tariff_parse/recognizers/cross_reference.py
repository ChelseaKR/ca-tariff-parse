"""Capture pointers from this schedule to other published schedules.

A rate schedule is rarely self contained. It defers surcharges, discounts and
generation options to sibling schedules, and a bill depends on all of them.
Recording those pointers is what stops a caller from mistaking one parsed
schedule for the whole tariff.
"""

from __future__ import annotations

import re

from ..extract import Line
from ..model import Cited, CrossReference
from ..segment import Section
from .base import Citer, Emission, paragraphs

REFER_RE = re.compile(
    r"Refer\s+to\s+Rate\s+Schedules?\s+(?P<targets>[A-Z][A-Za-z0-9\-]*"
    r"(?:\s*(?:,|and)\s*[A-Z][A-Za-z0-9\-]*)*)",
)
SPLIT_RE = re.compile(r"\s*(?:,|\band\b)\s*")


def _matches(section: Section) -> list[tuple[list[Line], str, list[str]]]:
    """Find cross references, allowing one to wrap across lines.

    A reference is often broken by the line wrap, as in "Refer to Rate Schedule"
    followed by "MED." on the next line, so paragraphs are searched rather than
    single lines.
    """
    found: list[tuple[list[Line], str, list[str]]] = []
    for group in paragraphs(section, skip_heading=False):
        text = re.sub(r"\s+", " ", " ".join(line.text for line in group)).strip()
        match = REFER_RE.search(text)
        if not match:
            continue
        targets = [part for part in SPLIT_RE.split(match.group("targets")) if part]
        if targets:
            found.append((group, text, targets))
    return found


def claims(section: Section) -> bool:
    return bool(_matches(section))


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    for group, text, targets in _matches(section):
        provenance = citer.cite_span(group, section.section_id)
        for target in targets:
            emission.cross_references.append(
                CrossReference(
                    target=Cited(value=target, provenance=provenance),
                    context=Cited(value=text, provenance=provenance),
                )
            )
        emission.take(*group)
    return emission
