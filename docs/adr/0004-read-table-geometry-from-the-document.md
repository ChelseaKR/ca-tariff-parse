# 0004. Read table geometry from the document, not from constants

- Status: Accepted
- Date: 2026-08-17

## Context

The first version of this parser was written against two SMUD residential
schedules and read their tables using fixed x coordinates: the season column
ended at 200 points, the period column at 300, the holiday month column began
at 295. Those numbers were correct, and they were correct only for those two
sheets.

Adding a commercial schedule and a solar and storage schedule from the same
publisher showed what that cost. The same publisher sets the same tables in
different places: the commercial time-of-day table sits about fifteen points
right of the residential one, and its holiday table about thirty. On that
sheet the parser found none of the eleven holidays, because every row looked
like a row with two cells missing.

Two failures were worse than a gap, because they produced output rather than
withholding it.

- A transition schedule of future prices happens to lay out as three columns
  in the same bands as a time-of-use window table. A row reading "Non-Summer
  Off-Peak per kWh $0.1237" was emitted as a period named Off-Peak whose
  definition was a price. Nothing in the output marked it as suspect.
- A standby charge priced across three service voltage levels put three
  amounts on one row. The rule that matched a single trailing amount matched
  the last one and swallowed the other two into the effective date, so the
  parser emitted a charge dated "May 1, 2025 $8.597 $6.832". The subtransmission
  price was published as though it were the whole charge.

Both are the failure this project exists to prevent: a value nobody published,
carrying a citation that makes it look checked.

## Decision

Where a table states its own structure, that statement is what the parser
reads.

- The holiday table's cell boundaries come from the positions of its own three
  headings. If the header does not divide into three headings, no holiday is
  emitted rather than one assembled from guessed columns.
- The window table's columns come from the alignment its period names share,
  taken as the alignment most of them agree on so that a stray "Peak" inside a
  wrapped definition cannot be mistaken for the column.
- A dated block pricing several categories at once takes its columns from the
  headings on its own label line, and every amount must fall under exactly one
  of them. A block whose amount count and heading count disagree is refused
  whole.
- A charge's unit is the tail of its own label, running to the end of it,
  rather than the first entry of a list of known unit strings found anywhere
  inside it.

Alongside that, a shape is only claimed when it is that shape and not merely
laid out like it. A time-of-use window definition must say when the period
runs and must not contain a currency amount.

Remaining fixed values are tolerances, not positions: how much clear space
separates two headings, how far a value may sit from a column centre before
the assignment is ambiguous. Those describe typesetting in general rather than
one publisher's sheet.

## Consequences

- Coverage of the two residential schedules did not move, and their golden
  output is byte for byte unchanged. That is the point: the change is about
  what happens on documents the parser was not written against.
- Reported coverage on the two new documents is well short of complete, at
  roughly 60% and 65%. Those figures are published in the README next to the
  residential ones.
- Refusing a shape is now more common, and each refusal is visible in
  `unparsed`. A block of nine real prices is reported as unparsed rather than
  emitted when its headings cannot be matched to its amounts one for one.
- Adding a publisher is still expected to find geometry the parser reads by
  convention rather than by reading. When it does, the fix is to find the
  document's own statement of the structure, not to widen a tolerance.
