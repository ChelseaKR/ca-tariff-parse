"""Capture eligibility and exclusion statements verbatim.

Applicability language decides who a rate applies to, so it is carried across
word for word. The only interpretation is a coarse ``disposition`` label, and
that label never replaces the text it summarises.
"""

from __future__ import annotations

import re

from ..extract import squash
from ..segment import Section
from .base import Citer, Emission, paragraphs, strip_item_number

EXCLUDES = (
    "are not eligible",
    "is not eligible",
    "not be eligible",
    "are not available",
    "shall not apply",
    "does not apply",
    "closed to new customers",
)
REQUIRES = (
    "must ",
    "is required for",
    "are required to",
    "is required to",
)

#: A section whose own heading is this states eligibility under another name.
#: A schedule that puts its conditions under "Conditions of Service" rather
#: than "Applicability" is saying the same kind of thing, and skipping it left
#: the parser answering "who is eligible" from half the document.
ELIGIBILITY_HEADINGS = frozenset({"eligibility", "eligibilityrequirements"})


def _disposition(text: str) -> str:
    low = text.lower()
    if any(token in low for token in EXCLUDES):
        return "excluded"
    if any(token in low for token in REQUIRES):
        return "required"
    return "included"


def claims(section: Section, headings: dict[str, str]) -> bool:
    """True for the Applicability part, its subsections, and any Eligibility part."""
    root = section.section_id.split(".")[0]
    if squash(headings.get(root, "")) == "applicability":
        return True
    return squash(section.heading) in ELIGIBILITY_HEADINGS


def parse(section: Section, citer: Citer) -> Emission:
    emission = Emission()
    for group in paragraphs(section):
        text = strip_item_number(" ".join(line.text for line in group))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        provenance = citer.cite_span(group, section.section_id)
        from ..model import Applicability, Cited

        emission.applicability.append(
            Applicability(
                text=Cited(value=text, provenance=provenance),
                disposition=_disposition(text),
            )
        )
        emission.take(*group)

    # The heading itself is part of the section and is accounted for here.
    if section.content_lines and section.level > 0:
        emission.take(section.content_lines[0])
    return emission
