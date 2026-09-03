# 0017. A table's first line says how far its heading reaches

- Status: Accepted
- Date: 2026-09-02

## Context

ADR 0013 read a unit heading over the components of its own table and drew
four fences from the two sheets that showed the shape, both of them from the
commercial and time-of-use schedules, where the page is set like this:

```
Energy Rates by Component ($ per kWh)          PEAK      OFF-PEAK
Generation:
    Summer (all usage)                      $0.20782    $0.10482
```

The second of those fences said that a heading level with the component lines
below it is their sibling rather than their parent, and the fourth that a row
set further left than the rows above it starts something else. Both were read
off those two sheets, and both were true of them.

The residential schedule sets the same table differently:

```
Energy Rates by Component ($ per kWh)
Generation:                                   $0.12855
Distribution**:                               $0.18042 (R)
Conservation Incentive Adjustment:
    Tier 1 Usage (0% - 100% of Baseline)     ($0.04052) (I)
    Tier 2 Usage (101% - 400% of Baseline)    $0.04089 (R)
    Tier 2 Usage Continued (Over 400% of      $0.04089 (R)
    Baseline)
Transmission* (all usage)                     $0.04638
...
Bundled Power Charge Indifference            ($0.01011)
Adjustment (all usage)****
```

Here the heading's own first-level lines sit level with the heading. The
parser already read `Generation:` and `Distribution**:` as the heading's rows,
because a row directly beneath a heading is that heading's row whatever its
indent. It then refused everything after them: `Conservation Incentive
Adjustment:` sits level with the heading, so the second fence called it a
sibling and its three rows went unpriced, and the twelve `(all usage)` rows
below were set further left than the tier rows above them, so the fourth fence
cut them off from any heading at all. Fifteen prices stated in `$ per kWh`
under a heading that says `$ per kWh` were reported as unrecognized, because a
rule inferred from one typesetting was applied to another.

The question ADR 0013 answered, how far down a stated unit reaches, was right.
What it read the answer from was too narrow.

## Decision

**How far a unit heading reaches is read off its own first line. That line is
the table's first line; nothing set further left than it is in the table, and
a heading whose first line is set left of it heads nothing.**

Scanning up from a block to the unit heading over it, everything passed over,
rows and component lines alike, and the block's own rows, has to sit at the
first line's level or deeper. One line set left of it ends the reach, and the
block is refused rather than priced in a unit stated over something else.

This keeps what ADR 0013 got right and replaces what it inferred:

- On the two-column sheets the heading's first line is `Generation:`,
  indented under the heading, and the reach is exactly what it was.
- On the residential sheet the heading's first line is `Generation:
  $0.12855`, level with the heading. `Conservation Incentive Adjustment:` is
  level with that line, so it is in the table, and it is set left of the tier
  rows under it, so it is their label. The `(all usage)` rows are level with
  the first line too, so they are in the table; no component line is set left
  of them, so they are priced under the heading's own name, exactly as the
  heading's first two rows are.
- On the commercial sheet the `(all usage)` rows are set level with the
  heading and left of `Generation:`, the table's first line. They are outside
  the table. A reader can see they are energy rates; the page does not say
  what they are priced per, and this parser does not say it for the page.

**A component line level with the rows it follows is their sibling, not their
heading**, and is passed over on the way up without becoming a block's label.
ADR 0013's first fence already said a component groups only the rows set right
of it; this is the same fence read from the other side.

**A row's label is joined across a line ending where its brackets say so.**
`Tier 2 Usage Continued (Over 400% of` leaves one bracket open and `Baseline)`
on the next line closes one it did not open, which is the rule ADR 0014 reads
a wrapped unit by. The joined label is cited to both lines. Its quote is the
label's own words in order, not both lines whole: the amount sits between the
two halves on the page, and a snippet of both lines would not contain the
label as one phrase. `cite_span` takes the quote for that reason.

**A row whose next line may be the rest of its label is refused.** `Bundled
Power Charge Indifference` is followed by `Adjustment (all usage)****`, an
unpriced line set as a row, stating no unit, carrying no amount in any
notation, and heading nothing. Nothing on the page ties the second line to the
first, and nothing separates them either. Published, the row would carry the
first half of its name; refused, it is reported verbatim with the rest. A label
still opening a bracket is refused for the same reason: the page broke it
somewhere this parser could not follow.

**Level is judged within two points.** The residential sheet's first-level
lines start anywhere from 177.3 to 177.7, the time-of-use sheet's from 95.4 to
97.9, and the smallest deliberate indent in the corpus is 7.2. Two points sits
inside the first and well clear of the second, the way `COLUMN_TOLERANCE`
already sits between a column's jitter and the gap to the next one. In the
monospace fixtures one character column is six.

## What this overturns, and what it does not

ADR 0013's second fence, as worded, is withdrawn: a heading level with its own
first line still heads it. The test that pinned the old wording now asserts
the new one, and its docstring says why. The synthetic keyword fixture's
`Example Unpriced Heading:` block, which that fence was written to keep
refused, stays refused under this rule for a reason the page states: the
heading's first line is the indented tier row, and the unpriced heading is set
left of it. The two-column fixture whose heading sits right of its components
stays refused for the same reason.

The fourth fence stands as an outdent rule: a row set left of the rows above
it leaves their component. What changes is where such a row lands. Level with
the table's first line, it is one of the heading's own rows; left of it, it is
outside the table.

Nothing here reads a row that fills fewer columns than its table names. The
time-of-use sheet's `(all usage)` rows set one amount under two named columns
and are refused by ADR 0012 as before.

## Consequences

| Document | Before | After |
| --- | --- | --- |
| `pge-e-1` | 67 of 247 lines, 38 charges | 84 of 247, 53 charges |
| `pge-e-tou-c` | 53 of 346 lines, 23 charges | unchanged |
| `pge-b-1` | 157 of 477 lines, 59 charges | unchanged |

The four SMUD schedules are byte for byte unchanged. `data/parsed/pge-e-1.json`
gains the fifteen charges, each reviewed against the sheet before this was
committed; the watch's own `diff` lists them with their citations.

Single-column runs are now cut at an outdent the way two-column runs already
were. Without that, the tier rows and the `(all usage)` rows on the residential
sheet became one run once the joined label no longer ended it, and every
`(all usage)` row was filed under `Conservation Incentive Adjustment:`. The
grouping in `tests/golden/` and `data/parsed/` is what catches that, and did.
