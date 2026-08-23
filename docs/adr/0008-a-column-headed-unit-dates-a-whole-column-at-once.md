# 0008. A column headed "Unit" dates a whole column at once

- Status: Accepted
- Date: 2026-08-22

## Context

`smud-ci-tod1` prices its rates for 2028 and beyond in a table none of the
existing recognizers claims, on Section VIII, "Transition Schedule":

```
Season and Charge Component               Unit      2028*
CITS-0: C&I Secondary 0-20 kW
System Infrastructure Fixed Charge        per month  $44.45
Maximum Demand Charge                     per kW     $4.101
Non-Summer Peak                           per kWh    $0.1506
...
*Subject to future rate increases.
```

Every other priced table this parser reads states a row's unit inside the
row's own label (`unit_tail`, read to the end of the label) or once, in a
heading over a whole block (`sheet_rates.py`, `dated_charge.py`'s
parenthetical heading). Here the unit sits in a column of its own, headed
literally "Unit". And every other table dates a price from a row of its own
("Effective May 1, 2025 $8.597") or from the sheet's own footer. Here the
date is a bare year printed once, in the header, over the whole column: the
table prices rates *after* this sheet's own effective date, so the sheet's
footer cannot date it and no row states a date of its own either.

[ADR 0007](0007-read-a-merged-cell-from-its-own-border.md) already found
this table has no ruled border, so reading its cells off `pdfplumber`'s grid
detection the way the proration table's cells are read was not available.
[ADR 0004](0004-read-table-geometry-from-the-document.md) is what applies
instead: an unruled table's columns are read from the x positions of the
header's own words, the same way the holiday table's and the standby
charge's columns already are.

## Decision

A new recognizer, `transition_table.py`, claims a section whose header line
divides into a label column, a column literally headed "Unit", and one or
more columns each headed with a bare year (optionally carrying a footnote
asterisk, read and kept exactly as printed: `"2028*"`, not `"2028"`). Both
conditions are required together. Requiring the word "Unit" specifically,
rather than any column past the label, is what keeps this from firing on an
ordinary table that happens to end a row in a number; requiring a year
header on top of that is what keeps it from firing on "Unit" appearing for
some unrelated reason.

Every row's label is whatever sits left of the "Unit" column, read as one
run of text the way a table row's label always is here. Everything to its
right is assigned to the "Unit" column or a year column by nearest centre,
[`assign`](../../src/ca_tariff_parse/recognizers/base.py), the same
attribution rule every other unruled table in this parser uses. A word that
fits no column refuses the row whole: this is the same discipline ADR 0004
already established for the standby charge, applied to a third column
shape rather than a second.

A rate category caption above a run of rows, "CITS-0: C&I Secondary 0-20
kW", is the same shape `rate_table.py` already reads off a caption row.
Reading it required only calling the same function; `_category_code` moved
out of `rate_table.py` into `recognizers/base.py` as `category_code`, public
now that two recognizers use it, rather than being copied.

The header row is credited only once a row was actually dated from it, the
same rule [ADR 0007](0007-read-a-merged-cell-from-its-own-border.md) applies
to the proration table's header: a table this recognizer found the shape of
but could not read a single price from is not "understood", and its header
should not look otherwise.

## Consequences

- `smud-ci-tod1` gains all seven prices Section VIII states for its first
  rate category (`CITS-0`): recognized lines 128 → 142. The other three
  SMUD schedules and the golden output of every schedule that carries no
  such table are unaffected, because the shape this claims does not appear
  on them.
- Every emitted charge's `effective_from` is the bare year exactly as
  printed, footnote asterisk included. What the asterisk means -- the
  footnote text two lines below it -- is not connected to the charge it
  marks; doing that would need a general mechanism this parser does not yet
  have for tying a footnote marker to what it marks, and inventing one
  narrowly for this table risked getting the general case wrong later. The
  footnote's own two lines are left for `notes`, same as before.
- `smud-ci-tod1`'s rate categories past `CITS-0` are not addressed by this
  change; nothing about the recognizer is specific to `CITS-0`; it happened
  to be the only category priced on the page this table currently occupies.
