# 0014. A unit the publisher broke across a line ending

- Status: Accepted
- Date: 2026-08-28

## Context

`TRAILING_UNIT_RE` reads a unit from the bracket a heading ends with. Two of
the second publisher's sheets set a heading whose bracket does not fit on one
line:

```
Base Services Charge Rates by Component ($ per
customer per day)
    Distribution
        Income Tier 1                            ($0.10751)
```

and, on the commercial schedule:

```
Total Demand Rate (per metered kW/month
assessed from 2:00 p.m. to 11:00 p.m. only)
    Summer                                    ---     $7.86
```

Neither line states a unit. The first opens a bracket it never closes; the
second closes one it never opened. Every block under both was refused, and the
refusal read as though the publisher had printed no unit, when the publisher
had printed one and the line ending fell inside it.

Joining lines is where a parser stops reading and starts reconstructing, so the
question is not whether these are units. It is what on the page says where the
unit ends.

## Decision

**A heading is joined across one line ending when the publisher's own brackets
say it continues: the line leaves exactly one bracket open, and the very next
line closes exactly one it did not open.**

Nothing else is joined:

- **A bracket that never closes** states nothing that can be read. There is no
  end to read to, and the block is refused. This is not hypothetical typography
  to guard against; it is what an extraction failure looks like.
- **A bracket that takes more than one line ending to close** is refused too.
  The rule reaches exactly as far as the publisher's punctuation reaches on the
  next line, and no shape in the corpus needs more. Reaching further would be a
  rule about how many lines to look at, which is a number this project would
  have to invent.
- **A line that closes a bracket opened by something other than the line
  immediately above it** is not a heading tail, and is read as it always was.

### The citation

The joined unit is cited to the span of both lines, not to either one. Half of
`$ per customer per day` appears on each line and the whole of it on neither,
so a citation naming one line would have a snippet that does not contain what
it cites. `cite_span` already existed for exactly this.

That is not a stylistic preference. `tests/test_realdoc.py::
test_every_cited_value_appears_on_the_line_it_cites`, added with ADR 0013,
asserts across all seven documents that every cited value appears on the line
its citation names. A wrapped unit cited to one line fails it, which is how
this decision was made rather than argued.

## Consequences

| Document | Before | After |
| --- | --- | --- |
| `pge-e-1` | 42 of 247 lines, 26 charges | 60 of 247, 38 charges |
| `pge-e-tou-c` | 25 of 346 lines, 11 charges | 43 of 346, 23 charges |
| `pge-b-1` | 131 of 477 lines, 57 charges | 135 of 477, 59 charges |

The four SMUD schedules are byte for byte unchanged.

One existing test changed, and the direction matters. The spot check quoting
`Income Tier 3` from `pge-e-1` found its charge by label alone, and the
unbundling sheets state `Income Tier 3` once per component, at four different
prices. The parser is not wrong to emit four; the lookup was wrong to assume
one. It now finds a charge by the pair the sheet itself prints, its component
and its label, and the four new prices were each read against the page before
the change was committed.
