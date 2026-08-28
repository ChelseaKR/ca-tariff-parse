# 0015. A schedule names itself, in its own words

- Status: Accepted
- Date: 2026-08-27

## Context

Parsing any of the second publisher's three schedules produced an identity
block that was almost entirely null:

```json
"identity": {
  "schedule_code": null, "title": null,
  "resolution": null, "adopted": null, "effective": null,
  "sheets": [ ... ]
}
```

Only `sheets` was populated, from the `Cal. P.U.C. Sheet No.` line in each
page's furniture. The README listed the identity fields among the things still
refused on the second publisher, with the reason:

> Each is a statement about how one publisher writes, not a thing a document
> cannot state about itself, so none of them belongs in a profile. Closing them
> means finding the shape, not adding a field.

That is the constraint this decision works inside. The question is not whether
the schedule code could be filled in -- `sources.toml` already records
`schedule = "B-1"` for that document, and copying it across would have produced
output that looked right. It is what on the page is allowed to say what the
schedule is called.

Reading the three documents settles it. Every sheet of every one of them prints
two lines directly under the sheet-number header:

```
Revised Cal. P.U.C. Sheet No. 61067-E
Cancelling Revised Cal. P.U.C. Sheet No. 60644-E
U 39 Oakland, California
ELECTRIC SCHEDULE B-1 Sheet 4
SMALL GENERAL SERVICE
```

The schedule names itself and the sheet it is printed on, and the line under
that is the schedule's title. Both repeat, unchanged, on all eleven sheets of
`pge-b-1`, all seven of `pge-e-1` and all ten of `pge-e-tou-c`.

## Decision

**A schedule's code and title are read from a line the document prints, in one
of the published forms of that sentence, matched whole. A document printing
none of those forms keeps a null code and a null title.**

The first publisher's form was already read:

```
Residential Time-of-Day Service          <- the title, on the line above
Rate Schedule R-TOD                      <- the code
```

The second publisher's is now read beside it:

```
ELECTRIC SCHEDULE B-1 Sheet 4            <- the code
SMALL GENERAL SERVICE                    <- the title, on the line below
```

`SHEET_SCHEDULE_RE` is anchored to a whole line and requires the trailing sheet
number. That is what makes the line a running head rather than a sentence that
happens to mention a schedule: `See Electric Schedule B-19` does not match, and
neither does any other line in the seven documents in the manifest.

Only the code is read from that line. The sheet count on it is the publisher's
own pagination of the schedule, which is a different thing from the
`Cal. P.U.C. Sheet No.` the furniture asserts, and putting the two in one field
would make `sheets` mean two things at once.

### Why not a profile field

Because the wording is on the page. A profile carries what a document *cannot*
state about itself ([ADR 0006](0006-the-document-profile-holds-three-things.md))
-- that a bracketed amount is a negative, that `Cancelling` announces a
supersession -- and a schedule's own name is not that. It is printed, in words,
on every sheet. Reading it from a pattern in this module is reading the page;
putting `schedule_line_form = "electric-schedule"` in a profile would be
recording a fact about the publisher that the publisher already prints.

The cost is that the set of published forms is a closed list that grows when a
document is read and found to write the sentence a third way. That is the
correct cost. The alternative -- a positional rule, "the schedule code is on
the fourth line of every page" -- would attach a code to any document at all,
including one that names no schedule.

### Why the title needs the running head to run

The title is the line under the schedule line, and on one sheet there is
nothing to tell that line from the first line of the body. What makes it a
title is that it repeats: the same text, under the same line, on every sheet
that carries one. So the title is read only when the schedule line appears on
at least two sheets and the line under it is identical on all of them.

Without that fence, a one-page document whose first body sentence followed the
schedule line would have been published with that sentence as its name.

### Which sheets have to agree

All of them, about the code. A document whose own sheets name two different
schedules is described correctly by neither, so it gets no code at all rather
than the first one found.

## What stays null, and why

The point of this phase was to separate a field the document does not state
from a field this parser had not read. Having read the furniture of all three
sheets:

- **`resolution` and `adopted` stay null.** These sheets print `Decision` and
  `Resolution` as footer labels with nothing beside them. The publisher files
  by advice letter, and the advice number is printed (`Advice 7846-E`), but an
  advice letter is not a resolution and filing it in the `resolution` field
  would put one kind of instrument under another kind's name.
- **`effective` stays null.** Not because the date is missing, but because
  there is no schedule-wide one to state: this publisher files sheet by sheet,
  and on `pge-e-1` sheet 1 takes effect on a different day from sheets 2 to 7.
  Each price already carries its own sheet's date, read from that sheet's own
  footer. A document-level `effective` here would be a date three quarters of
  the document does not take effect on.

Each of those is now a statement about the document rather than an unread gap,
which is what this ADR was for.

## Consequences

The three second-publisher documents now report their own code and title, each
cited to the line it was read from. Coverage moves by exactly two lines per
sheet, because two lines per sheet that were previously reported as
unrecognised content are now accounted for:

| Document | Before | After |
| --- | --- | --- |
| `pge-e-1` | 42/247 (17.0%) | 56/247 (22.7%) |
| `pge-e-tou-c` | 18/346 (5.2%) | 38/346 (11.0%) |
| `pge-b-1` | 104/477 (21.8%) | 126/477 (26.4%) |

No charge, window, condition or citation changes anywhere, and the four SMUD
schedules are byte for byte identical: no line in any of them matches the added
form, so nothing about their reading can have moved. That is the same test
[ADR 0006](0006-the-document-profile-holds-three-things.md) used when the
second publisher arrived.
