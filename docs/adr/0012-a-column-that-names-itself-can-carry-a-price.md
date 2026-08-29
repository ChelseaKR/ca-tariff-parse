# 0012. A column that names itself can carry a price

- Status: Accepted
- Date: 2026-08-28

## Context

`sheet_rates.py` refused any page that set amounts in more than one column. The
refusal is in `_page_has_one_amount_column`, and its reason was written down
next to it:

> A page that sets them in two is a table with columns. A block on such a page
> that states no column headings of its own cannot say which column its single
> amount belongs to, so nothing is read from that page at all.

That reasoning is right, and it is about a block that has no column headings.
The second publisher's rate sheets do have them. Sheet 3 of `pge-b-1` sets its
two rate options over its amounts, on a line of its own:

```
Total Bundled Time-of-Use Rates              B-1 Rates    B1-ST Rates
Total TOU Energy Rates ($ per kWh)
    Peak Summer                               $0.47087       $0.49377
    Partial-Peak Winter (for B1-ST only)           ---       $0.36632
```

Fourteen prices sat there unread, and the README recorded the cost plainly:
"This is why the commercial schedule's own rate sheets contribute nothing at
all: they price two rate options side by side."

The question this ADR settles is not whether to read them. It is what on the
page is allowed to say which column a price belongs to.

## Decision

**A page that names its columns is read across them. A page that does not is
refused exactly as before.**

The names come from the page, never from a profile, a constant or a list of
publishers. This is [ADR 0004](0004-read-table-geometry-from-the-document.md)
applied one step further out: the geometry that says which column a price sits
in is the same geometry that says which name is set over it.

The mechanism already existed. `Column`, `columns_from` and `assign` in
`recognizers/base.py` were built for
[ADR 0004](0004-read-table-geometry-from-the-document.md)'s standby charge, and
`dated_charge.py` already reads a commercial sheet that prices one charge
across three service voltage levels, carrying each column's own heading in the
charge's `applies_to`. This decision gives `sheet_rates.py` the same reading,
on the same field.

### Which line names the columns

The first line on the page whose words sit over the amounts below them. A group
of that line names a column when an amount on the page sits closer to that
group than to any other, and within `COLUMN_TOLERANCE`, which is the tolerance
every other column reading here already uses. A line carrying an amount itself
is never a naming line: it is a row of some table rather than a heading over
one. Fewer than two named groups is not a naming line either, because one
column of amounts under one heading is the shape this module already read
without needing anything named.

"The first such line" is a decision, and the alternative was "the nearest one
above each block". They agree on every page in the corpus, and the first is
what a rate sheet actually does: the header is printed once, at the top, over
a table whose blocks then each state their own unit. The narrower rule would
also let a stray line between two blocks rename the columns for the second one,
which is a way to be wrong that the page gives no warning of.

### What a row has to do to be read

A row carries one cell per named column, each sitting under exactly the column
its position in the row gives it, or the row is refused whole. In particular:

- **A row with fewer cells than the table has columns is refused.** Its single
  price may be that column's or the whole row's, and the page does not say
  which. This is the fence that matters most. On sheet 3 of `pge-e-tou-c` the
  rows reading `Transmission* (all usage) $0.04638` set one amount between the
  two columns, and on sheet 3 of `pge-b-1` the PDP tables set one amount under
  the first of two. Both stay unread, and both would otherwise have been
  published as a peak rate or as one rate option's price.
- **A cell that sits under no named column refuses its row**, because
  `assign` returns nothing for it and attribution by counting is not
  attribution.
- **A row of nothing but unpriced cells prices nothing**, and is left for the
  unparsed report.

### What an unpriced cell now means

A cell the publisher marked with a run of dashes used to refuse the row that
carried it. Under a named column it says something exact: this column has no
price for this row. `Partial-Peak Winter (for B1-ST only)` is priced for one
rate option and not the other, and the sheet says so by marking the other cell.
The cell itself still emits nothing. What changes is that it no longer takes
the priced cell beside it down with it.

### Filing markers inside the value area

The bracketed capitals of [ADR 0010](0010-a-change-marker-standing-alone-is-furniture.md)
are set beside a changed cell, so on a two column row they fall between the
cells as well as after them. They are skipped inside the value area for the
same reason they were already skipped at the end of it, and under the same
rule: they are a filing convention, not a cell. Nothing about the citation
changes, because the citation quotes the whole line as printed.

## Consequences

`pge-b-1` goes from 104 of 477 content lines recognized to 113, and from 18
charges to 31. The thirteen new prices are the seven rows of sheet 3's
time-of-use energy table, across two columns, less the one cell the publisher
marked as carrying no price. Each carries the column's own name in
`applies_to`, cited to the line that names it.

Nothing else moves. The four SMUD schedules are byte for byte identical, which
is the test [ADR 0006](0006-the-document-profile-holds-three-things.md) used
when the second publisher arrived: this is a seam, not a second branch. The
other two PG&E documents are unchanged, because what still stands between them
and their tables is a sub-heading between a unit and its rows, and a unit
broken across a line ending. Those are separate questions and get their own
decisions.

The refusal that was lifted was never load-bearing on its own. What was
load-bearing is the sentence underneath it, that a price has to say which
column it belongs to, and that is now enforced per row rather than per page.
