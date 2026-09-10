"""What every recognizer did to every line, recorded while a document is read.

A refusal is this project's deliverable. Until now a refusal was legible only
by reading the source: ``coverage`` reports that a line went unread and gives a
coarse reason -- "3 of 13 lines in a recognized section matched no rule" -- and
nothing says which recognizer got closest to the line or what stopped it. This
module is the channel that records both, and :mod:`ca_tariff_parse.explain` is
the surface that prints it.

Three things about the design, each of which is load-bearing.

**Recording cannot change what the parser emits.** Recording is off unless a
caller opens it with :func:`recording`, and even when it is open the recorders
are write-only: nothing in this package reads a trace back while parsing, so no
decision the parser makes can depend on whether it was being watched. That is
why ``explain`` and ``parse`` cannot disagree, and it is asserted rather than
asserted-about: ``tests/test_explain.py`` parses each committed fixture with
and without a trace open and compares the emitted JSON as bytes.

**A fence is named, not described.** :class:`Fence` carries a stable
identifier, the ADR that decided it, and the reason in the fence's own words.
An identifier is what lets a census group refusals across documents (#69) and
what lets a contributor filing an unread-shape report say which rule stopped
short. Prose in a docstring cannot do either.

**A line no recognizer reached says so.** The one thing this module must never
do is offer a nearest fence chosen by proximity: "the closest rule to this line
was X" is a value invented from an absence, which is the defect this whole
project is built against. :class:`LineTrace` therefore distinguishes four
states, and the fourth is a first-class answer rather than a gap:

``consumed``
    a recognizer claimed the line and emitted from it;
``refused``
    a recognizer reached the line and a named fence stopped it;
``claimed_but_not_reached``
    a recognizer claimed the line's section and read nothing from this line --
    it examined the section, not the line, and no fence fired;
``unclaimed``
    no recognizer claimed the line's section at all. There is no rule in this
    parser whose shape matches the section, so no fence can exist for it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

#: ``(page, line)``, the coordinate every citation in this project already uses.
LineKey = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Fence:
    """A named place where a recognizer stops reading, and why.

    ``id`` is stable across releases and is what a census groups on. ``adr`` is
    the decision that put the fence there, so a reader who disagrees with a
    refusal has one document to argue with rather than a call site to reverse
    engineer. ``reason`` is the fence's own sentence, in the present tense and
    about the page rather than about the code.
    """

    id: str
    adr: str
    reason: str


#: Every fence this parser can report, by identifier. Populated at import time
#: by :func:`fence`, so the registry is exactly the set of fences that exist in
#: the code -- there is no second, hand-maintained list to drift from it.
FENCES: dict[str, Fence] = {}


def fence(identifier: str, *, adr: str, reason: str) -> Fence:
    """Register a fence and return it.

    Called at module scope so that importing a recognizer is what puts its
    fences in :data:`FENCES`. A duplicate identifier is refused rather than
    silently overwritten: two fences sharing a name would make a census count
    two different refusals as one.
    """
    if identifier in FENCES:
        raise ValueError(f"fence {identifier!r} is already registered")
    registered = Fence(id=identifier, adr=adr, reason=reason)
    FENCES[identifier] = registered
    return registered


@dataclass(frozen=True, slots=True)
class Refusal:
    """One recognizer stopping at one line, at one named fence.

    ``detail`` quotes what the fence actually saw on the page -- the label that
    left a bracket open, the token that is not an amount. It is a reading, not
    a diagnosis: everything in it appears in the document.
    """

    recognizer: str
    fence: Fence
    page: int
    line: int
    detail: str

    def to_json(self) -> dict[str, object]:
        return {
            "recognizer": self.recognizer,
            "fence": self.fence.id,
            "adr": self.fence.adr,
            "reason": self.fence.reason,
            "detail": self.detail,
        }


@dataclass(slots=True)
class Trace:
    """Everything one parse of one document did, by line.

    Written to by the engine and by the recognizers; never read by either.
    """

    #: ``section_id`` -> ``recognizer`` -> whether its ``claims`` predicate
    #: accepted the section. Both outcomes are recorded: a recognizer that
    #: declined a section examined it, and saying so is the difference between
    #: "no rule looked" and "every rule looked and none matched".
    offered: dict[str, dict[str, bool]] = field(default_factory=dict)
    #: ``(page, line)`` -> the recognizers that marked the line consumed.
    consumed: dict[LineKey, list[str]] = field(default_factory=dict)
    #: ``(page, line)`` -> the fences that stopped a recognizer at that line.
    refusals: dict[LineKey, list[Refusal]] = field(default_factory=dict)
    #: ``(page, line)`` -> the section the line was read under.
    section_of: dict[LineKey, str] = field(default_factory=dict)
    #: ``(page, line)`` -> the line's own text, so an explanation can quote the
    #: page without extracting the document a second time.
    text_of: dict[LineKey, str] = field(default_factory=dict)

    def offer(self, section_id: str, recognizer: str, *, claimed: bool) -> None:
        self.offered.setdefault(section_id, {})[recognizer] = claimed

    def took(self, key: LineKey, recognizer: str) -> None:
        taken = self.consumed.setdefault(key, [])
        if recognizer not in taken:
            taken.append(recognizer)

    def refused(self, refusal: Refusal) -> None:
        self.refusals.setdefault((refusal.page, refusal.line), []).append(refusal)

    def place(self, key: LineKey, section_id: str, text: str) -> None:
        self.section_of[key] = section_id
        self.text_of[key] = text

    @property
    def fences_reached(self) -> set[str]:
        """The identifiers of every fence that actually fired in this trace.

        A fence that exists and never fires proves nothing, so this is the
        numerator of the coverage figure ``explain --fences`` prints and the
        one ``tests/test_explain.py`` holds the registry to.
        """
        return {refusal.fence.id for refusals in self.refusals.values() for refusal in refusals}


_ACTIVE: ContextVar[Trace | None] = ContextVar("ca_tariff_parse_trace", default=None)


@contextmanager
def recording() -> Iterator[Trace]:
    """Open a trace for the duration of the block, and yield it.

    Reset on the way out rather than set back to ``None``, so a nested
    recording restores the outer one instead of closing it.
    """
    trace = Trace()
    token = _ACTIVE.set(trace)
    try:
        yield trace
    finally:
        _ACTIVE.reset(token)


def active() -> Trace | None:
    """The trace being recorded into, or ``None`` when nothing is watching."""
    return _ACTIVE.get()


def refuse(recognizer: str, at: Fence, *, page: int, line: int, detail: str) -> None:
    """Record that ``recognizer`` stopped at ``at`` on one line.

    A no-op when nothing is recording, which is the ordinary case: ``parse``
    runs with no trace open, so the call costs one context lookup and changes
    nothing. Recognizers therefore call this unconditionally -- an
    ``if tracing:`` branch at every fence would be a second code path that
    could come to disagree with the first.
    """
    trace = _ACTIVE.get()
    if trace is None:
        return
    trace.refused(Refusal(recognizer=recognizer, fence=at, page=page, line=line, detail=detail))


def took(recognizer: str, keys: set[LineKey]) -> None:
    """Record that ``recognizer`` consumed every line in ``keys``."""
    trace = _ACTIVE.get()
    if trace is None:
        return
    for key in keys:
        trace.took(key, recognizer)


def offer(section_id: str, recognizer: str, *, claimed: bool) -> None:
    """Record that ``recognizer``'s claim predicate was asked about a section."""
    trace = _ACTIVE.get()
    if trace is None:
        return
    trace.offer(section_id, recognizer, claimed=claimed)


def place(entries: list[tuple[LineKey, str]], section_id: str) -> None:
    """Record which section each line was read under, and what it says."""
    trace = _ACTIVE.get()
    if trace is None:
        return
    for key, text in entries:
        trace.place(key, section_id, text)
