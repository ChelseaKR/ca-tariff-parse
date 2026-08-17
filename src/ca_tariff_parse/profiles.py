"""What a document cannot state about itself.

Everything this parser can read off a page it does read off the page: where a
table's columns divide, where the body of a page ends, which part of the year a
season names. That rule is [ADR
0004](../../docs/adr/0004-read-table-geometry-from-the-document.md) and it
survives here untouched.

A small residue is left over. It is not geometry and it is not wording; it is
the meaning a publisher attaches to a convention, which the document uses
everywhere and states nowhere. Three such things were found by parsing two
publishers:

* **How the outline is written.** A numbered outline announces itself: ``I.``
  followed by ``A.`` is a part and a subsection whatever the document is about.
  A keyword outline does not. A word set in a column of its own with the text
  beside it is a heading in one publisher's house style and a table's first
  column in another's, and the page looks identical either way.
* **How an amount is written.** ``($0.08140)`` is a negative amount to a
  publisher who uses accounting brackets and something else to one who does
  not. Reading it as positive would publish a charge where the document
  publishes a credit, and refusing it loses a real published price, so the
  parser must be told which publisher it is reading before it can do either.
* **Which word announces a supersession.** A page that prints two sheet numbers
  is telling the reader that one of them is withdrawn, but which one is carried
  by a filing word rather than by anything structural on the page.

A profile supplies those three and nothing else, and it is selected per
manifest entry. A document with no profile gets :data:`DEFAULT`, which claims a
numbered outline, refuses a bracketed amount and treats no word as announcing a
supersession. That is the fail-closed position: an unprofiled document is
refused rather than guessed at.

A profile deliberately holds no coordinate. The first draft of this seam gave
it the width of the keyword column, and the three schedules of one publisher
set that column at eight different left edges and their body text at nine. A
position in a profile is the mistake [ADR
0004](../../docs/adr/0004-read-table-geometry-from-the-document.md) removed
from the recognizers, reintroduced one layer up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "DEFAULT",
    "KEYWORD_COLUMN",
    "NUMBERED",
    "OUTLINE_STYLES",
    "DocumentProfile",
    "UnknownProfileError",
    "names",
    "resolve",
]

#: The outline is statute-style numbering: roman parts over lettered
#: subsections, each announcing itself at the head of its own line.
NUMBERED = "numbered"
#: The outline is a keyword set in a column of its own with the body of the
#: part beside it, so a line reads ``APPLICABILITY: This schedule is ...``.
KEYWORD_COLUMN = "keyword-column"

OUTLINE_STYLES = frozenset({NUMBERED, KEYWORD_COLUMN})


class UnknownProfileError(ValueError):
    """Raised when a manifest entry names a profile this build does not have."""


@dataclass(frozen=True, slots=True)
class DocumentProfile:
    """One publisher's conventions, as far as they are not on the page."""

    name: str
    outline: str = NUMBERED
    bracket_negative_amounts: bool = False
    """True when this publisher writes a negative amount in accounting
    brackets, so ``($0.08140)`` is minus eight and a bit cents. False means a
    bracketed amount is not an amount this parser can read, and a row carrying
    one is refused whole rather than published without it."""
    supersession_word: str | None = None
    """The word with which this publisher's page furniture announces the sheet
    it replaces, as in ``Cancelling Revised Cal. P.U.C. Sheet No. 61247-E``.
    ``None`` means no word is treated as announcing one, and a page asserting
    two sheet numbers records neither."""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("a profile must be named")
        if self.outline not in OUTLINE_STYLES:
            raise ValueError(
                f"unknown outline style {self.outline!r}; known: {sorted(OUTLINE_STYLES)}"
            )
        if self.supersession_word is not None and not self.supersession_word.strip():
            raise ValueError("supersession_word must be None or a non-empty word")

    def cancels(self, text: str) -> bool:
        """True when this line announces a sheet the publisher has withdrawn."""
        if self.supersession_word is None:
            return False
        return bool(re.search(rf"\b{re.escape(self.supersession_word)}\b", text, re.IGNORECASE))


#: Used for any document that names no profile. Everything is refused rather
#: than assumed: a numbered outline, no bracket notation, no supersession word.
DEFAULT = DocumentProfile(name="default")

#: A profile is named for the document family it was written from. The three
#: schedules behind ``pge-tariff-book`` are filed with the California Public
#: Utilities Commission and other Californian investor-owned utilities file in
#: the same form, so this profile is expected to fit theirs. It has not been
#: tested against one, and saying so is the point of naming it this way.
_REGISTRY: dict[str, DocumentProfile] = {
    DEFAULT.name: DEFAULT,
    "pge-tariff-book": DocumentProfile(
        name="pge-tariff-book",
        outline=KEYWORD_COLUMN,
        bracket_negative_amounts=True,
        supersession_word="Cancelling",
    ),
}


def resolve(name: str | None) -> DocumentProfile:
    """Look up a profile by name; ``None`` selects :data:`DEFAULT`."""
    if name is None:
        return DEFAULT
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownProfileError(
            f"unknown document profile {name!r}; known: {', '.join(names())}"
        ) from None


def names() -> list[str]:
    """Every profile this build knows about."""
    return sorted(_REGISTRY)
