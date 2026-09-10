"""Why one line of a document was read, or was not.

`coverage` reports that a line went unread and gives a coarse reason -- "3 of
13 lines in a recognized section matched no rule". That sentence is true and it
does not say which recognizer got closest, or what stopped it. Reading the
source is the only way to find out today, which makes a refusal legible to
whoever wrote the parser and to nobody else. Refusals are this project's
deliverable, so that is the wrong reader.

This turns :mod:`ca_tariff_parse.trace`'s record into an answer per line, in
one of four states. **The fourth is the one that has to exist**, and it is why
this module does not offer a "nearest fence":

``consumed``
    a recognizer claimed the line and emitted from it. It names which.
``refused``
    a recognizer reached the line and a **named fence** stopped it. It names
    the fence, the ADR the fence comes from, the fence's own reason, and what
    the fence saw on the page.
``examined``
    a recognizer claimed the line's section, read it, and took nothing from
    this line -- with no fence firing. Nothing refused it; no rule in that
    recognizer reaches this shape.
``unclaimed``
    no recognizer claimed the line's section at all. There is no rule in this
    parser whose shape matches the section, so there is no fence that *could*
    have fired, and offering one would be a value invented from an absence.

The distinction between the last two and ``refused`` is the one ADR 0018 draws
by hand: **"unstated on the page" is not the same fact as "unread by this
parser"**, and a reader deciding whether to file an unread-shape report needs
to know which they are looking at.

Nothing here re-runs a recognizer or re-derives a value. It reports what the
parse already did, recorded as it happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import ParsedSchedule
from .trace import FENCES, Refusal, Trace

#: `p.3 L11`, the spelling a citation in this project already uses, split by
#: the shell into two tokens.
_PAGE_TOKEN = re.compile(r"\Ap(?:age)?\.?(?P<page>\d+)\Z", re.IGNORECASE)
_LINE_TOKEN = re.compile(r"\AL(?:ine)?\.?(?P<line>\d+)\Z", re.IGNORECASE)
#: The same selector as one token, for a caller writing a script rather than a
#: command by hand.
_COMPACT = re.compile(r"\A(?P<page>\d+):(?P<line>\d+)\Z")


class SelectorError(ValueError):
    """A line selector that could not be read as one."""


def parse_selectors(tokens: list[str]) -> list[tuple[int, int]]:
    """Read ``["p.3", "L11"]`` or ``["3:11"]`` into ``[(3, 11)]``.

    A token that is neither raises rather than being skipped. A selector
    silently dropped would produce an explanation of fewer lines than the
    caller asked about, and no output saying so.
    """
    selected: list[tuple[int, int]] = []
    pending: int | None = None
    for token in tokens:
        compact = _COMPACT.match(token)
        if compact:
            if pending is not None:
                raise SelectorError(f"page selector 'p.{pending}' has no line after it")
            selected.append((int(compact.group("page")), int(compact.group("line"))))
            continue
        page = _PAGE_TOKEN.match(token)
        if page:
            if pending is not None:
                raise SelectorError(f"page selector 'p.{pending}' has no line after it")
            pending = int(page.group("page"))
            continue
        line = _LINE_TOKEN.match(token)
        if line:
            if pending is None:
                raise SelectorError(f"line selector {token!r} has no page before it")
            selected.append((pending, int(line.group("line"))))
            pending = None
            continue
        raise SelectorError(f"{token!r} is not a line selector; write 'p.3 L11' or '3:11'")
    if pending is not None:
        raise SelectorError(f"page selector 'p.{pending}' has no line after it")
    return selected


@dataclass(frozen=True, slots=True)
class LineExplanation:
    """What every recognizer did to one line."""

    page: int
    line: int
    section: str
    text: str
    consumed_by: tuple[str, ...]
    refusals: tuple[Refusal, ...]
    claimed_section: tuple[str, ...]
    declined_section: tuple[str, ...]

    @property
    def state(self) -> str:
        """One word for the line, in precedence order.

        A line can be both consumed and refused: a section heading is credited
        to segmentation while a recognizer that claimed the same section
        refuses at its own fence. `consumed` wins, because the stronger fact
        about a line is that something read it -- and `refusals` still carries
        the fence, so the summary going one way never drops the other.
        """
        if self.consumed_by:
            return "consumed"
        if self.refusals:
            return "refused"
        if self.claimed_section:
            return "examined"
        return "unclaimed"

    def to_json(self) -> dict[str, object]:
        return {
            "page": self.page,
            "line": self.line,
            "section": self.section,
            "text": self.text,
            "state": self.state,
            "consumed_by": list(self.consumed_by),
            "refused_by": [refusal.to_json() for refusal in self.refusals],
            "claimed_the_section": list(self.claimed_section),
            "declined_the_section": list(self.declined_section),
        }


@dataclass(frozen=True, slots=True)
class Explanation:
    """Every line asked about, and the fence coverage of the run behind it."""

    document_id: str
    lines: tuple[LineExplanation, ...]
    fences_reached: tuple[str, ...]
    fences_registered: tuple[str, ...]
    #: Selectors that named a line the document does not contain. Reported
    #: rather than dropped: a selector that matched nothing and an explanation
    #: that says nothing look identical in the output otherwise.
    not_found: tuple[tuple[int, int], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "lines": [line.to_json() for line in self.lines],
            "fences": {
                "registered": list(self.fences_registered),
                "reached_on_this_document": list(self.fences_reached),
            },
            "selectors_not_found": [{"page": page, "line": line} for page, line in self.not_found],
        }


def _distinct(refusals: tuple[Refusal, ...]) -> tuple[Refusal, ...]:
    """Collapse a fence that fired more than once on one line, in file order.

    A recognizer can read the same line under two shapes -- `sheet_rates`
    offers a section to both its single-column and its named-column readers --
    and a label that is refused is refused by each. Both records are true and
    printing them twice says nothing the first did not, so the report keeps
    the first of each ``(recognizer, fence, detail)``. The count is deliberately
    not published: it is a fact about how many internal passes a recognizer
    makes, which is not something a reader of a refusal should have to model.
    """
    seen: set[tuple[str, str, str]] = set()
    kept: list[Refusal] = []
    for refusal in refusals:
        signature = (refusal.recognizer, refusal.fence.id, refusal.detail)
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(refusal)
    return tuple(kept)


def _explain_one(trace: Trace, key: tuple[int, int]) -> LineExplanation:
    offered = trace.offered.get(trace.section_of.get(key, ""), {})
    return LineExplanation(
        page=key[0],
        line=key[1],
        section=trace.section_of.get(key, ""),
        text=trace.text_of.get(key, ""),
        consumed_by=tuple(trace.consumed.get(key, ())),
        refusals=_distinct(tuple(trace.refusals.get(key, ()))),
        claimed_section=tuple(sorted(n for n, claimed in offered.items() if claimed)),
        declined_section=tuple(sorted(n for n, claimed in offered.items() if not claimed)),
    )


def explain(
    parsed: ParsedSchedule,
    trace: Trace,
    *,
    selectors: list[tuple[int, int]] | None = None,
    section: str | None = None,
) -> Explanation:
    """Build the explanation for the lines a caller asked about.

    With neither ``selectors`` nor ``section``, every content line the parse
    placed is explained.
    """
    if selectors:
        wanted = [key for key in selectors if key in trace.section_of]
        missing = tuple(key for key in selectors if key not in trace.section_of)
    elif section is not None:
        wanted = sorted(k for k, s in trace.section_of.items() if s == section)
        missing = ()
    else:
        wanted = sorted(trace.section_of)
        missing = ()
    return Explanation(
        document_id=parsed.source.document_id,
        lines=tuple(_explain_one(trace, key) for key in wanted),
        fences_reached=tuple(sorted(trace.fences_reached)),
        fences_registered=tuple(sorted(FENCES)),
        not_found=missing,
    )


def _wrap(text: str, width: int, indent: str) -> list[str]:
    words = text.split()
    out: list[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width and current.strip():
            out.append(current.rstrip())
            current = indent
        current += word + " "
    if current.strip():
        out.append(current.rstrip())
    return out


def to_text(explanation: Explanation) -> str:
    """The explanation as a report a person reads."""
    out: list[str] = [f"document        {explanation.document_id}"]
    registered = len(explanation.fences_registered)
    reached = len(explanation.fences_reached)
    # Two numbers, always. A count of refusals says nothing about how much of
    # the parser's refusal vocabulary this document exercised, and a fence
    # that never fires anywhere is a fence that proves nothing.
    out.append(f"fences          {reached} of {registered} reached on this document")
    out.append(f"lines explained {len(explanation.lines)}")
    if explanation.not_found:
        for page, line in explanation.not_found:
            out.append(f"NOT FOUND       p.{page} L{line} is not a content line of this document")
    out.append("")

    for item in explanation.lines:
        out.append(f"p.{item.page} L{item.line}  section {item.section or '(none)'}")
        if item.text:
            out.append(f"    | {item.text[:100]}")
        if item.consumed_by:
            out.append(f"    consumed by   {', '.join(item.consumed_by)}")
        for refusal in item.refusals:
            out.append(
                f"    refused by    {refusal.recognizer} at {refusal.fence.id} "
                f"({refusal.fence.adr})"
            )
            out.extend(_wrap(refusal.fence.reason, 96, " " * 18))
            out.append(f"                  saw: {refusal.detail[:80]}")
        if item.state == "examined":
            out.append(
                "    examined      "
                + ", ".join(item.claimed_section)
                + " claimed this section and read nothing from this line; no fence fired"
            )
        if item.state == "unclaimed":
            out.append(
                "    unclaimed     no recognizer claimed section "
                f"{item.section or '(none)'}, so no rule in this parser reaches this line"
            )
        if item.declined_section:
            out.append(f"    declined      {', '.join(item.declined_section)}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def fence_table() -> str:
    """Every fence this parser can report, for `explain --fences`."""
    out = [f"{len(FENCES)} registered fence(s)", ""]
    for identifier in sorted(FENCES):
        entry = FENCES[identifier]
        out.append(f"{entry.id}  ({entry.adr})")
        out.extend(_wrap(entry.reason, 96, "    "))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def document_label(path: Path) -> str:
    return path.name
