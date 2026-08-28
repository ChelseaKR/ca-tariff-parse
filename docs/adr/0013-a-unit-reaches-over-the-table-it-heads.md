# 0013. A unit reaches over the table it heads, and no further

- Status: Accepted
- Date: 2026-08-28

## Context

`sheet_rates.py` read a block's unit from the line immediately above its first
row. Both publishers' unbundling sheets state the unit once, over a table, and
then name each component of that table on a line of its own:

```
Energy Rates by Component ($ per kWh)          PEAK      OFF-PEAK
Generation:
    Summer (all usage)                      $0.20782    $0.10482
Distribution**:
    Summer (all usage)                      $0.20388    $0.18388
```

The line above the rows is `Generation:`, which states no unit, so every block
on those sheets was refused. The README recorded the refusal as "a block whose
heading states no unit, because a number with no unit says nothing about what
it prices". That reason is right about a block with no unit anywhere over it.
It was wrong about these, where the unit is stated two lines up.

Reading them raises a question the previous rule never had to answer: how far
down does a stated unit reach? Reaching too far prices a block in a unit stated
over something else, which is the same class of defect as a price under the
wrong date.

## Decision

**A unit reaches over the table it heads, and the table is what sits under it:
its own rows, and the lines that name the components grouping them. Anything
else ends the reach.**

Scanning up from a block, the reach passes over lines that are rows this same
table's reader accepts, and over lines that name a component. It stops at the
first line that states a unit, which becomes the block's unit; the nearest
component line is the block's own label. Four fences, each read off the page:

1. **A component line is set left of the rows it groups.** That indentation is
   how the page says the rows are under it. A line level with its rows, or
   right of them, groups nothing.
2. **The unit heading is set left of every component line it reaches over.** A
   heading level with them is another heading like them rather than one over
   them. This is what keeps the synthetic keyword fixture's
   `Example Unpriced Heading:`, which sits level with the unit heading above
   it, refused: the existing test asserting that refusal is unchanged and still
   passes.
3. **Two lines running that are neither rows nor a unit heading end the
   reach.** One line above a block is its heading. Two are prose or another
   table's furniture, and the reach stops rather than being guessed past.
4. **A row set further left than the rows above it starts something else.**
   Below the components, both sheets set further component rows at the table's
   own indentation. Collected into the block above them, all of them would be
   published under a component name the publisher gave to something else.

### What the block is called

The component's name, carried exactly as printed: `Generation:` and
`Distribution**:`, colon and footnote markers included. Trimming either would
be editing a quotation, and the `**` is the publisher's own pointer to the
footnote saying what that component is combined with on a bill.

The table's own heading is not lost by this. The unit is cited to the line that
states it, so the citation carries `Energy Rates by Component ($ per kWh)`
verbatim in its snippet, which is where a reader looks to see which table a
component belonged to.

### A citation that did not contain what it cited

Fixing that citation was not cosmetic. `_read_heading` already had a shape
where the label and the unit sit on different lines, and it cited the unit to
the label's line, whose snippet does not contain the unit. Thirty nine charges
across the three second-publisher documents carried a unit citation a reader
could not check against the line it named. The unit is now cited to the line
that prints it, and `tests/test_realdoc.py` asserts across all seven documents
that every cited value appears on the line its citation names.

One value in the corpus does not, and is named rather than skipped: a credit's
unit, which is written `$/kWh` from a row printing `-$0.0150/kWh`. That is a
composition, not a quotation, and the test asserts it is the only one, so a
second composition cannot appear quietly.

## Consequences

`pge-b-1` goes from 113 of 477 content lines to 131, and from 31 charges to 57.
`pge-e-tou-c` goes from 18 of 346 to 25, and from 3 charges to 11. The four
SMUD schedules are byte for byte identical.

What stays unread is stated rather than left to be discovered: the component
rows set level with their table's heading, and, on the sheets Phase 6 is about,
every block whose unit is broken across a line ending. Both are reported in
`notes`, verbatim, as everything unrecognized is.
