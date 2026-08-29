# 0015. A running head runs

- Status: Accepted
- Date: 2026-08-28

## Context

Parse any of the three second-publisher documents and `identity` came back with
`schedule_code`, `title`, `resolution`, `adopted` and `effective` all null, and
only `sheets` populated. The README listed the identity fields among the things
still refused on that publisher, with the reason:

> Each is a statement about how one publisher writes, not a thing a document
> cannot state about itself, so none of them belongs in a profile. Closing them
> means finding the shape, not adding a field.

The two publishers do write it differently. One prints, in the header band:

```
Residential Time-of-Day Service
Rate Schedule R-TOD
```

The other prints, in the body of every sheet:

```
U 39 Oakland, California
ELECTRIC SCHEDULE B-1 Sheet 3
SMALL GENERAL SERVICE
```

Title above in one, title below in the other, and a regulatory identifier where
the first publisher puts its title.

## Decision

**The line that names the schedule is the one that runs.** A line is a
candidate when its whole text is some words, the word Schedule, a code, and
optionally the sheet number printed after it. Among the candidates, the code
that appears on more sheets than any other, and on at least two, is the
schedule's. If two codes run equally, the document names two schedules and is
described correctly by neither, so nothing is read.

Requiring it to run is not a tidy-up. `pge-b-1` contains this line:

```
to residential or agricultural service for which a residential or agricultural schedule is
```

That is a wrapped sentence, and it matches the shape exactly. It appears on one
sheet. `B-1` appears on eleven.

**The title is the neighbouring line that repeats on every one of those sheets,
and only when exactly one of the two does.** Where the first publisher sets its
title above, the line below is body text and changes sheet to sheet, and that
is what says which is the title. Where the second sets its title below, the
line above is a regulatory identifier that also repeats, and then nothing on
the page says which of the two names the schedule.

That produces different answers for documents of the same publisher, and the
reason is worth stating rather than smoothing over: on `pge-b-1` the line above
reads "U 39 Oakland, California" on some sheets and "U 39 San Francisco,
California" on others, so only one neighbour runs and the title is read. On
`pge-e-1` and `pge-e-tou-c` both neighbours run and no title is read. The rule
is not claiming to recognise a title. It is reporting whether the page
distinguishes one, and on two of these documents it does not.

## What stays null, and why that is a finding

- **`resolution` and `adopted`.** The second publisher's footer prints the word
  `Resolution` with nothing after it. There is no number to read. This is the
  document stating no resolution, not the parser failing to find one.
- **`effective`.** The sheets of one of these schedules take effect on
  different days: sheet 1 of `pge-e-1` on June 1, 2026 and the rest on March 1,
  2026. A single document-level effective date would have to pick one. The
  per-sheet dates are read and every price carries its own, which is the whole
  reason `sheet_effective_dates` exists.

A null here is a true statement about a document that does not carry the field.
Filling one in from a neighbouring sheet, or from the manifest, would make the
output say something the page does not.

## Consequences

The schedule line is content on the second publisher's sheets rather than
furniture, so reading it also accounts for it. Content lines recognized:
`pge-b-1` 135 to 157, `pge-e-tou-c` 43 to 53, `pge-e-1` 60 to 67. No charge
count moves, because identity emits no prices.

The four SMUD schedules are byte for byte unchanged, including their identity
blocks, which the golden files pin.
