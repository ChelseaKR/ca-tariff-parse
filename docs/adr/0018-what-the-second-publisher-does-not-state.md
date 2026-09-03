# 0018. What the second publisher does not state

- Status: Accepted
- Date: 2026-09-02

## Context

`ScheduleIdentity` carries five fields beside the sheet list: `schedule_code`,
`title`, `resolution`, `adopted` and `effective`. The first publisher prints
all five on its front sheet, on one line:

```
Resolution No. 25-06-15 adopted June 19, 2025 Effective: June 20, 2025
```

ADR 0015 read the second publisher's `schedule_code`, and its `title` where
the page settles which neighbouring line it is. The roadmap's Phase 7 asked
what the other three fields are for this publisher, and said the answer had to
be one of two things: a value read and cited from the furniture, or a null
recorded as unstated rather than merely unread.

This is that record. It was made by reading the footer of every sheet of the
three pinned documents, twenty-eight sheets in all.

## What the furniture prints

Every sheet carries the same four-line signature block:

```
Advice 7846-E              Issued by              Submitted February 27, 2026
Decision                   Shilpa Ramaiya         Effective March 1, 2026
                           Vice President         Resolution
                           Regulatory and Rates
```

- **`Advice <number>`** on every sheet: the advice letter that filed the
  sheet. Numbers differ sheet by sheet within one document (`B-1` carries
  seven different ones, filed between 2020 and 2026).
- **`Decision`** on every sheet, followed by a decision number on some (`D.26-04-036`,
  `D.21-03-056`, `18-08-013`) and by nothing on most.
- **`Submitted <date>`** on every sheet: the date the advice letter was filed.
- **`Effective <date>`** on every sheet: the date that sheet took effect. Within
  one document the dates differ: `E-1` sheet 1 is effective June 1, 2026 and
  sheets 2 to 7 March 1, 2026; `B-1` spans August 1, 2020 to March 1, 2026.
- **`Resolution`** on every sheet, followed by nothing on all twenty-eight.

## Decision

**`resolution` is null.** The word is printed as a form label, and on every
sheet of every document the space beside it is empty. A label with nothing
beside it is the publisher stating that there is no value, which is a
different fact from the parser not finding one, and the null records it.
The decision numbers some sheets print beside `Decision` are not resolutions,
and they are per sheet.

**`adopted` is null.** No sheet prints an adoption. `Submitted` is the date an
advice letter was filed and `Decision` the authority it was filed under;
reading either as the schedule's adoption would be a translation this parser
has no warrant for.

**`effective` is null at the schedule level, and stated at the sheet level.**
Each sheet states when it took effect, and the sheets of one schedule took
effect on different days. A single date for the schedule would be one sheet's
date borrowed for the rest, which is the kind of value ADR 0015 refuses. The
per-sheet dates are read from each sheet's own footer and carried on every
charge as `effective_from` (`header.sheet_effective_dates`); nothing about
them is lost by leaving the schedule-level field empty.

**What is read stays read**: `schedule_code` on all three documents, `title`
on the one where the page settles it (ADR 0015), and `sheets` on all three.

## What this does not do

- It adds no field. The advice letter number, the decision number and the
  submission date are real facts about each sheet that the model has no place
  for. Carrying them means a new per-sheet record and a schema revision, and
  that is a decision about the schema rather than about this publisher. It is
  listed in the roadmap under what is not in this plan, so that its absence is
  a choice and not an oversight.
- It reads nothing from the furniture that ADR 0015 did not already read.

## Consequences

`tests/test_realdoc.py` already asserts the three nulls on `pge-e-1` and the
two distinct per-sheet dates its charges carry; `tests/test_header_identity.py`
gains a synthetic document printing neither publisher's shape, whose identity
comes back entirely null, and one printing the second publisher's signature
block with an empty `Resolution`, whose `resolution`, `adopted` and
`effective` come back null while its sheets' effective dates are read.
`tests/golden/` and `data/parsed/` are byte for byte unchanged, because
nothing the parser emits changed.
