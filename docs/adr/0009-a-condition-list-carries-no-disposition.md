# 0009. A numbered condition list carries no disposition

- Status: Accepted
- Date: 2026-08-22

## Context

Three SMUD schedules gate their Standby Service option on an enumerated
list, outside any Applicability or Eligibility part:

```
D. Standby Service Option
Standby Service applies when all of the following conditions are met:
1. The customer has generation, sited on the customer's premises, that
serves all or part of the customer's load; and
2. The generator(s) have a combined nameplate rating less than 100 kW; and
3. The generator(s) are connected to SMUD's electrical system; and
4. SMUD is required to have resources available to provide supplemental
service, backup electricity and/or to supply electricity during
generator(s) maintenance service.
```

`recognizers/applicability.py`'s `claims` fires only on the Applicability
part itself and on a section headed Eligibility (see its own docstring for
why that widening was needed at all). This list sits under "D. Standby
Service Option", a rate option heading exactly like "E. Customer Energy
Generation Options" beside it, so it was never seen.

Reading it as an `Applicability` was tried first, and did not fit. An
`Applicability` carries a `disposition` -- included, excluded or required --
summarising what the text says about who the schedule applies to. One item
of this list says nothing of the kind on its own: item 2 states a fact about
the generator, not a fact about who is eligible for anything, and the only
sentence that actually gates something is the intro line the four items
share. Forcing a disposition onto item 2 would either invent one that does not fit
("included", as a default, would be simply wrong) or require reading four
items as four separate coarse judgements about a schedule when they are one
judgement, stated once, about a rate option.

## Decision

A new record, `Condition`, holds `subject` (the intro sentence, carried
verbatim and shared by every item read from the same list) and `text` (one
item, verbatim). It carries no disposition field at all, because nothing
in the shape this parser has met so far justifies inventing one.

A new recognizer, `condition_list.py`, looks for the intro sentence
directly: a line ending in "the following condition(s) (is/are) met:". This
is deliberately not anchored to any section heading, unlike
`applicability.py`'s widened `claims`, because the two schedules that carry
this text put it under two different headings ("D. Standby Service Option"
on the residential and time-of-day schedules, the same wording under a
commercial schedule's own "D."), and a third schedule might use a third
heading. The trigger is narrow enough on its own: a rate schedule stating
"the following conditions are met" immediately before a numbered list is
making exactly this shape of claim, in every document seen so far.

Everything after the intro line must resolve to a strictly numbered,
unbroken sequence -- 1, 2, 3, ... with no gap -- before anything is
emitted, the same discipline `segment.py` already applies to a roman
numeral heading running out of order. A wrapped item is recognised by its
own indent and by whether the text read so far has reached a sentence's
end, not by a fixed line count: item 4 above wraps onto a second line
because it has not yet reached a period, and the line straight after it
(the priced block's own heading, "Standby Service Charge - January 1
through December 31") shares its indent with the wrap by coincidence of
this document's typesetting but is correctly left alone, because it opens
with none of the digits this recognizer is looking for. See the module for
the details of that boundary.

## Consequences

- `smud-r-tod` and `smud-r` each gain the four Standby Service conditions;
  `smud-ci-tod1` gains its three (its list omits the nameplate rating
  condition the other two state). Recognized lines: `smud-r-tod` 119 → 125,
  `smud-r` 88 → 94, `smud-ci-tod1` 128 → 142 (combined with
  [ADR 0008](0008-a-column-headed-unit-dates-a-whole-column-at-once.md)'s
  change to the same document). `smud-ssr`, which carries no such list, is
  byte for byte unchanged.
- `ParsedSchedule` gains a `conditions` array, published in
  `parsed-schedule/v1` and validated against the schema like every other
  field.
- The priced block that almost always follows this list (`Standby Service
  Charge - January 1 through December 31 ... Effective May 1, 2025
  $8.597`) was already read by `dated_charge.py` before this change and is
  unaffected: the two recognizers claim disjoint lines, and nothing here
  changes how that block is read.
- This is a narrow shape, found from one repeated sentence across three
  documents. A schedule that gates a different rate option the same way but
  phrases its intro sentence differently is not read by this and stays
  unparsed, which is the correct outcome for a phrase this parser has not
  actually seen printed.
