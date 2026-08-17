# 0002. Fail closed on anything the parser does not understand

- Status: Accepted
- Date: 2026-08-17

## Context

A parser over hand-set documents will always meet shapes it does not know. The
tempting behaviours are both dangerous: guess at the value, or skip the line.
Guessing fabricates a price. Skipping quietly produces output that looks
complete, and gives a consumer no way to distinguish a document that was fully
understood from one where half the table was dropped.

## Decision

Anything not understood with certainty is refused and reported.

- A recognizer that cannot read a value emits nothing for it. Concretely: a
  priced row whose unit is not a recognisable substring of its label; an amount
  that does not sit within tolerance of exactly one effective-date column; a
  time-of-use window that is defined by exclusion or carries an exception; a
  cell the publisher marked `n/a`; a holiday row missing a cell.
- A row is committed whole or not at all, so amounts can never be emitted with
  some cells attributed to the wrong effective date.
- Every content line a recognizer did not consume becomes an `UnparsedSection`
  entry with its section, page, line span and reason, and is additionally
  carried verbatim in `notes`. Fail closed means surfaced, never discarded.
- `Coverage` is part of the output. It reports recognized and unrecognized line
  counts and a `fully_recognized` flag that is true only when nothing was left
  over.

A test asserts that a document containing an unrecognised section cannot
produce output identical to one that is fully understood.

## Consequences

- Reported coverage on real documents is well short of 100% (roughly 77% and
  69% on the two SMUD residential schedules). This is the honest number and it
  is published in the README rather than hidden.
- Coverage must never be treated as a target. Widening a tolerance or a regex
  to raise it converts a visible gap into an invisible fabrication, which is
  the exact failure this decision exists to prevent. `CONTRIBUTING.md` says so
  explicitly.
- The output carries prose the parser made no attempt to structure. That is
  preferred to dropping it.
