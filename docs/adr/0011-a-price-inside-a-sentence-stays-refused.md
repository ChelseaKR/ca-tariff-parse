# 0011. A price stated inside a sentence stays refused

- Status: Accepted
- Date: 2026-08-22

## Context

`smud-ssr`, the solar and storage schedule, states its one price in prose
rather than in a table:

> The Export Compensation Rate effective June 1, 2026 will be $0.0960 per
> kWh (subject to updates as described in the paragraph below).

Every other charge this parser emits comes from a table shape: a label
column and a value column, a heading stating a unit, a row dated by its own
text or by the sheet's footer. This is none of those. Reading it would mean
finding the label ("Export Compensation Rate", the section title, not
anything printed on the priced line itself), the unit (`per kWh`, readable
by the existing `unit_tail`) and the effective date (`June 1, 2026`,
readable by the existing date patterns) entirely from sentence structure
rather than table geometry, for a shape seen exactly once.

`tests/test_realdoc.py::test_a_prose_only_schedule_emits_no_charge` already
asserts, and is named for, the current behaviour: `smud-ssr` emits zero
charges, on purpose, and that is treated as the honest outcome rather than a
gap to be closed by more code. This ADR is that decision written down,
because the roadmap listed the shape as merely unaddressed and a roadmap
entry reads as a standing intention to eventually close it.

## Decision

This stays refused, deliberately, not for lack of a rule that could read
this one sentence, but because of what closing it would generalise into.

A rule narrow enough to read only this exact sentence would be a rule
fitted to n=1: every part of it -- the label coming from the section title
rather than the priced line, the parenthetical caveat that the rate is
itself provisional pending a formula described three sentences later, the
particular verb tense ("will be") -- would be encoded from a single
example, with no second document to say which parts of that shape are the
general case and which are this document's own phrasing. Every other
prose-reading rule in this parser (`condition_list.py`'s intro sentence,
`cross_reference.py`'s "Refer to Rate Schedule", `applicability.py`'s
exclusion phrases) was written against a phrase repeated across at least
two schedules, which is what let the rule be a real generalisation rather
than a transcription of one sentence into code that happens to look like a
rule.

The parenthetical is a second, independent reason this one stays refused
even if a second example turned up tomorrow. "(subject to updates as
described in the paragraph below)" states that the number is not a fixed
price the way every other emitted charge is: it is a current value of a
formula, defined elsewhere, that recalculates on a cycle. Emitting it as an
ordinary `Charge` with a plain `effective_from` would publish it with the
same apparent certainty as a table row that is not provisional in that way,
which is the exact difference this parser's citations exist to preserve.

## Consequences

- `smud-ssr` continues to emit zero charges. The existing test that asserts
  this is not a placeholder for a future fix; it is the specification.
- The roadmap item this closes is removed from "Planned" without a
  recognizer landing, which is unusual for this log: every prior roadmap
  item closed by shipping code that reads more of a document.
  [ADR 0002](0002-fail-closed-on-anything-not-understood.md)'s standing
  rule is that refusing is preferred to guessing; this is that rule applied
  to a roadmap item itself rather than to a single row.
- A future document that repeats this same sentence, or one close to it,
  on a second schedule would be grounds to revisit this decision with an
  actual generalisation available -- not grounds to guess at one now.
