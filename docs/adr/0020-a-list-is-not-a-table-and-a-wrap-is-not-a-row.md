# 0020. A list is not a table, and a wrap is not a row

- Status: Accepted
- Date: 2026-09-13

## Context

`E-TOU-C` is titled *Residential Time-of-Use (Peak Pricing 4 - 9 p.m. Every
Day)*. The parse carried **zero** time-of-use windows. Issue #75 asked the right
first question — is the parser wrong, or does the sheet not state them — and
did not answer it.

**The sheet states them.** Sheet 5, inside the special conditions part:

```
2. TIME PERIODS FOR E-TOU-C: Times of the year and times of the day are
defined as follows:

Summer (service from June 1 through September 30):

Peak: 4:00 p.m. to 9:00 p.m. All days

Off-Peak: All other times

Winter (service from October 1 through May 31):

Peak: 4:00 p.m. to 9:00 p.m. All days

Off-Peak: All other times
```

Four windows, each with its season, and the parser read none of them. The
reason is not a refusal and it is not a missing profile field: `billing_periods`
reads a **table** — a season cell on the left, a period name in the middle, a
definition on the right, with the column boundaries recovered from the
alignment of the period names themselves (ADR 0004). There is no such alignment
here because there are no columns. Its `claims` correctly declined a section
that holds no window table, and nothing else looked.

So this was not the second publisher being harder than the first. It was one
shape the parser had never met.

`tests/test_realdoc.py` asserted `parsed.tou_windows == ()` for all three of
this publisher's schedules. That reads as an accounting rule — "no window is
claimed from a shape the parser cannot follow" — and it was in fact **asserting
the defect as intended behavior** for the one schedule where windows are the
substance.

## Decision

**Read the list, as a list.** A new recognizer, `period_list`, claims a section
that prints a season heading over period lines. Both halves have to be true:

- a **season heading** is a line ending in a colon that states a part of the
  year. Requiring it to state a part of the year is what keeps the list's own
  introduction — "…are defined as follows:" — from being read as a season, and
  it is the same refusal `billing_periods` already makes for a column heading
  that names no season. ADR 0005 records what the alternative costs: two
  windows emitted under a season the document never wrote.
- a **period line** is `<period name>: <definition>`, and the definition has to
  say *when* the period runs — a clock time, or an exclusion. A definition
  stating neither is not a window definition, and a line is not made into one
  by sitting under a season.

A period line with no season heading in force emits nothing.

**And the harder half: a wrap is not a row.** `B-1` prints what looks like the
same list on its own sheet 5 and is not one. Its definitions wrap, and the
wrapped half is set far to the right of the rows:

```
Peak: 4:00 p.m. to 9:00 p.m. Every day, including weekends
                             and holidays
Partial-Peak: 2:00 p.m. to 4:00 p.m. AND      Every day, including weekends
              9:00 p.m. to 11:00 p.m.         and holidays
```

The first draft of this recognizer read that block and published **one** window
whose definition was `4:00 p.m. to 9:00 p.m. Every day, including weekends` —
a time-of-use rule missing its last two words, and therefore a rule about
holidays that says the opposite of the page. That is precisely the class of
value this project exists not to emit, and it was caught by re-measuring every
document rather than only the one in the issue.

The page says which case it is, and it says it with position. A line set to the
**right** of the rows belongs to the text block the rows are in; a line set
level with them or to their left does not. So: **where the line that ends a
group is set further right than the group's own rows, the group is refused
whole.** `B-1` reads zero windows again, and reads them as a refusal with a
stated reason rather than as silence.

This is ADR 0004 applied one layer up — the structure is read off the page, not
supplied by a profile — and it is the same rule ADR 0017 reads a table's reach
by. Nothing was added to the document profile. A profile holds what a document
cannot state about itself, and a document states its own indentation.

## Consequences

`E-TOU-C` goes from **53/346 lines (15.3%) and 0 windows** to **59/346 (17.1%)
and 4 windows**. The six new lines are the two season headings and the four
period lines. The list's two-line introduction is **not** claimed: no value is
read out of it, so it stays in `unparsed` rather than being credited to a
recognizer that only understood its title.

The other six pinned documents are untouched: every one of their committed
baselines and golden files is byte for byte unchanged, and the whole diff under
`data/parsed/` is the four windows plus `E-TOU-C`'s own three coverage
counters. No price moved.

`check` now has something to say about this document that it could not say
before: `window-enumerability` reports `cannot be established` and names the
two residual Off-Peak windows, because the page defines them by exclusion and
this parser does not invent a clock for them.

**Zero holidays on this schedule is the sheet, not the parser.** The word
"holiday" does not appear anywhere in the document, and both Peak periods run
"All days". `tests/test_realdoc.py` pins that as a statement about the document
rather than leaving a bare zero: the day the publisher adds a holiday list, the
test fails rather than the count staying quietly at zero.

Rejected: widening `billing_periods` to cover both shapes. Its whole method is
recovering column boundaries from the page, and a list has none — the two
readers share their vocabulary (the period names, the clock-time pattern, what
makes a definition residual) and nothing else. Also rejected: putting the
list's introductory wording in the document profile. "TIME PERIODS FOR E-TOU-C"
is text on the page, and a recognizer that keyed on it would read one document
rather than one shape.
