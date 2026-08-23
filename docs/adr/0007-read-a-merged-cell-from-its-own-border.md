# 0007. Read a merged cell from its own ruled border, not from line spacing

- Status: Accepted
- Date: 2026-08-22

## Context

Three of the four SMUD schedules carry a small table pairing a billing
circumstance ("Bill period is shorter than 27 days") with the basis on which
a charge is prorated under it. It was refused entirely: see the "Planned"
list this ADR removes an item from.

The refusal was earned. Read in line order, the table's second column looks
like this (SMUD's residential schedule, `V`):

```
Billing Circumstance                 Basis for Proration
Bill period is shorter than 27 days  Relationship between the length of the
(SIFC and kWh)                        billing period and 30 days.
Bill period is longer than 34 days
(kWh)
Seasons overlap and price changes    Relationship between the length of the
within bill period                    billing period and the number of days
                                       that fall within the respective season
                                       or pricing periods.
```

Pairing circumstance and basis by raw line position attaches "and kWh)" to
the first basis sentence and "Bill period is longer than 34 days (kWh)" to
nothing, which is wrong in a way that would have been reported as a fabricated
value under this project's own rule. Pairing by *paragraph* spacing, the way
`_paragraphs_by_spacing` already does for prose sections, does no better: the
gap between "(kWh)" and "Seasons overlap" and the gap inside the second basis
sentence's own wrap are not reliably distinguishable from the gap that marks a
genuine new row, because there is no such gap. Rendering the actual page
shows why:

```
+--------------------------------------+---------------------------------------------+
| Bill period is shorter than 27 days   | Relationship between the length of the       |
| (SIFC and kWh)                        | billing period and 30 days.                  |
+----------------------------------------                                              |
| Bill period is longer than 34 days    |                                               |
| (kWh)                                 |                                               |
+--------------------------------------+---------------------------------------------+
| Seasons overlap and price changes     | Relationship between the length of the       |
| within bill period                    | billing period and the number of days that   |
|                                        | fall within the respective season or pricing |
|                                        | periods.                                     |
+--------------------------------------+---------------------------------------------+
```

The first basis cell is a real merge, drawn by the publisher to span two rows
of the circumstance column. No amount of tuning a spacing threshold recovers
that, because there is genuinely no second basis paragraph for the second
circumstance to have been separated from: the ruled border, not the text, is
the only place this table states its own row structure.

## Decision

Where a table has a ruled border, read the border.

`pdfplumber` already detects the lines a PDF draws and can resolve them into
a grid of cell bounding boxes, including which cells a row's border omits
because a cell above them already spans that height. `extract.py` reads that
grid in a second pass over each page, using the words and lines the first
pass already built to give each cell a citation: a cell's text and line span
come from whichever already-extracted words fall inside its bounding box, not
from `pdfplumber`'s own cell-text extraction, so a cell's provenance is
always a real line of the document.

Two cells are told apart from one merged cell by their *bounding boxes*
overlapping, not by any positional heuristic: `TableCell.top`/`.bottom` come
directly from the border `pdfplumber` found. A circumstance cell whose box
overlaps exactly one basis cell's box is paired with it — and a basis cell's
box can overlap more than one circumstance, which is exactly what "the
publisher merged this cell across two rows" means. A circumstance overlapping
zero or more than one basis cell is left unpaired, on the same fail-closed
principle as every other refusal here: attaching a basis to the wrong
circumstance is worse than reporting one line as unparsed.

`recognizers/proration.py` claims a table by its own header cells reading
"Billing Circumstance" / "Basis for Proration", not by the heading of the
section around it. The same table sits under a subsection called "Proration
of Charges" on two of the three schedules and under a section simply called
"Billing" on the third: the table names itself, so nothing needs to guess
which section wording the next document will use.

## Consequences

- Coverage of all three affected schedules moved: `smud-r-tod` 117→119,
  `smud-r` 79→88, `smud-ci-tod1` 121→128 recognized lines. `smud-ssr`, which
  has no such table, is unchanged.
- `ExtractedTable`/`TableCell` in `extract.py`, and `Page.tables`, are new but
  general: any future recognizer that needs a ruled table's real cell
  structure can read it the same way, rather than each writing its own
  spacing heuristic.
- This only fires for a table that actually has a ruled border. The
  commercial transition table on `smud-ci-tod1` (Section VIII) has none, so
  it is untouched by this and is still refused; closing it needs the column
  geometry approach ADR 0004 already established, not this one.
- `layout_from_monospace`, used by every synthetic test fixture, does not
  produce ruled tables, because a plain-text fixture cannot express a drawn
  border. This recognizer is exercised by hand-built `ExtractedTable`/
  `TableCell` fixtures directly (`tests/test_proration.py`) instead of
  through a monospace document, and by the golden output of the three real
  schedules it now reads a table on.
