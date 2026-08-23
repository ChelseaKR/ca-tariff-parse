"""A numbered condition list, read outside any Applicability or Eligibility part.

Built from hand positioned lines rather than a monospace fixture, the same
way ``test_proration.py`` builds its table: what matters here is indent, and
a monospace fixture's fixed character grid cannot easily place two different
hanging indents the way a real sheet does.
"""

from __future__ import annotations

from ca_tariff_parse.extract import LayoutDoc, Line, Page, Word
from ca_tariff_parse.recognizers import condition_list
from ca_tariff_parse.recognizers.base import Citer
from ca_tariff_parse.segment import Section


def _line(index: int, indent: float, text: str) -> Line:
    words = tuple(
        Word(text=word, x0=indent + i * 60.0, x1=indent + i * 60.0 + 50.0)
        for i, word in enumerate(text.split(" "))
    )
    return Line(page=1, index=index, top=float(index) * 14.0, words=words, furniture=False)


INTRO = "Standby Service applies when all of the following conditions are met:"


def _doc(lines: tuple[Line, ...]) -> LayoutDoc:
    page = Page(number=1, height=792.0, lines=lines, sheet="SYN-1")
    return LayoutDoc(
        document_id="syn-conditions",
        sha256="a" * 64,
        filename="<inline>",
        byte_size=0,
        pages=(page,),
        synthetic=True,
    )


def _section(lines: tuple[Line, ...], section_id: str = "IV.D") -> Section:
    return Section(
        section_id=section_id, level=2, heading="Standby Service Option", lines=list(lines)
    )


def test_a_wrapped_item_is_joined_and_a_following_heading_is_left_alone() -> None:
    lines = (
        _line(1, 90.0, INTRO),
        _line(2, 108.0, "1. First condition; and"),
        _line(3, 108.0, "2. Second condition wraps across"),
        _line(4, 126.0, "a second line and ends here."),
        # Same indent as the intro, immediately after the list -- e.g. the
        # priced block's own heading -- and must not be swept in.
        _line(5, 90.0, "Standby Service Charge - January 1 through December 31"),
    )
    section = _section(lines)
    citer = Citer(_doc(lines))

    assert condition_list.claims(section)
    emission = condition_list.parse(section, citer)

    texts = [c.text.value for c in emission.conditions]
    assert texts == [
        "First condition; and",
        "Second condition wraps across a second line and ends here.",
    ]
    assert all(c.subject.value == INTRO for c in emission.conditions)
    # The wrapped item's citation spans both of its lines.
    wrapped = emission.conditions[1]
    assert wrapped.text.provenance.line == 3
    assert wrapped.text.provenance.end_line == 4
    for index in (1, 2, 3, 4):
        assert (1, index) in emission.consumed
    # The unrelated heading below the list is untouched.
    assert (1, 5) not in emission.consumed


def test_an_intro_with_nothing_numbered_after_it_emits_nothing() -> None:
    """The sentence promised a list; none followed with certainty."""
    lines = (_line(1, 90.0, INTRO), _line(2, 90.0, "Not a numbered item at all."))
    section = _section(lines)
    citer = Citer(_doc(lines))

    assert condition_list.claims(section)
    emission = condition_list.parse(section, citer)

    assert emission.conditions == []
    assert emission.consumed == set()


def test_an_out_of_order_item_number_ends_the_list_there() -> None:
    """Numbers must run 1, 2, 3 -- a gap is not part of this list."""
    lines = (
        _line(1, 90.0, INTRO),
        _line(2, 108.0, "1. First condition; and"),
        _line(3, 108.0, "3. Skips a number; and"),
    )
    section = _section(lines)
    emission = condition_list.parse(section, Citer(_doc(lines)))

    assert [c.text.value for c in emission.conditions] == ["First condition; and"]
    assert (1, 3) not in emission.consumed


def test_a_sentence_that_only_mentions_conditions_in_passing_is_not_claimed() -> None:
    lines = (
        _line(1, 90.0, "Please review the following considerations before enrolling."),
        _line(2, 108.0, "1. First consideration."),
    )
    section = _section(lines)
    assert not condition_list.claims(section)


def test_two_lists_in_one_section_keep_their_own_subject() -> None:
    other_intro = "Three-Phase Service applies when all of the following conditions are met:"
    lines = (
        _line(1, 90.0, INTRO),
        _line(2, 108.0, "1. First list's only item."),
        _line(3, 90.0, other_intro),
        _line(4, 108.0, "1. Second list's only item."),
    )
    section = _section(lines)
    emission = condition_list.parse(section, Citer(_doc(lines)))

    by_subject = {c.subject.value: c.text.value for c in emission.conditions}
    assert by_subject == {INTRO: "First list's only item.", other_intro: "Second list's only item."}
