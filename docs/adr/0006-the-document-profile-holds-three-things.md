# 0006. The document profile holds three things and no coordinates

- Status: Accepted
- Date: 2026-08-17

## Context

[ADR 0005](0005-a-second-publisher-needs-a-document-profile.md) designed a
per-document profile and deliberately did not build it, on the grounds that
fitting a seam against one further publisher is how it becomes a second special
case. That was the right call at the time. There are now two publishers with
genuinely different conventions and seven schedules between them, which is the
minimum needed to tell a seam from a branch.

The test of the design is not how much of the second publisher parses. It is
whether each field in the profile is something a document genuinely cannot
state about itself, and whether the first publisher's output moves at all.

## Decision

A profile holds three fields. A document that names none gets a default in
which all three are the refusing value.

**`outline`: `numbered` or `keyword-column`.** A numbered outline announces
itself. `I.` followed by `A.` is a part and a subsection whatever the document
is about, and the parser can and does read it without being told. A keyword
outline announces nothing: a word set in a column of its own with text beside
it is a heading in one publisher's house style, a table's first column in
another's, and a wide left margin with a hanging indent in a third. The page
looks identical in all three cases, and this parser meets the other two inside
the first publisher's own tables, where the same geometry carries a season
label beside a period column. So the fact that the left column is the outline
has to be supplied. Once supplied, everything about the column is read from the
page.

**`bracket_negative_amounts`.** `($0.08140)` is minus eight and a bit cents to a
publisher who uses accounting brackets. Nothing in the document says so, and
the two possible mistakes are both bad in a way this project exists to avoid:
reading it as positive publishes a charge where the publisher published a
credit, and refusing it withholds a real published price. There is no third
reading available from the page, so the parser has to be told which publisher
it is looking at before it can do either. The default refuses, and a row
carrying a bracketed amount under the default is left unparsed and reported.

**`supersession_word`.** Every sheet of the second publisher prints its own
number over the number it replaces, and which of the two is withdrawn is
carried by a filing word rather than by anything structural. The word is
`Cancelling` here; another regulator's book would use another. The default
names no word, which means a page asserting two sheet numbers records neither
and its citations carry no sheet at all. That is the fail-closed reading, and
it is what the first publisher's documents already get, because they print one
number per page and the question never arises.

Nothing else is in the profile, and in particular no coordinate is.

## What the design got wrong the first time

ADR 0005 said the profile should state the width of the keyword column. It was
written that way against a reading of one sheet. Across the second publisher's
three schedules the keyword column starts anywhere from 72 to 101 points and
the body beside it anywhere from 133 to 172, and on one schedule the body
begins three points left of where another schedule's keyword ends. A single
number cannot separate them. Two of the three documents would have had a table
row read as a heading.

So the column is read from the page, the same way [ADR
0004](0004-read-table-geometry-from-the-document.md) reads a table's columns
from its own headings. A keyword is the first run of words on a line, cut at
the first clear space wide enough to be a column boundary, set entirely in
capitals, starting no further right than the leftmost content on its own page,
and closed by a colon within three lines. What stays fixed are tolerances: how
wide a gap has to be to be a column, how far right of the page's own left edge
a keyword may sit. A position in a profile is the mistake ADR 0004 removed from
the recognizers, put back one layer up.

## What the profile made readable, and what it did not

Three things fell out of the seam that are not in it, because the document
states them and the parser now reads them.

- **A part continued onto the next sheet.** The publisher reprints the keyword
  with `(Cont'd.)` beneath it. That is the same part, so it is not opened
  again.
- **The sheet's own banner.** Each sheet reprints its identity above the first
  part it carries. It belongs to no part, and attributing it to the part
  continued from the sheet before published a page banner as an eligibility
  statement. How deep the banner runs is read as the shallowest run any sheet
  sets above its first keyword, so the rule can only ever divert lines that
  some sheet has proved are banner.
- **The date a price takes effect.** These sheets are filed one at a time, and
  the sheets of one schedule take effect on different days: sheet 1 of the
  residential schedule is effective 1 June and sheets 2 to 7 are effective 1
  March. Each price is dated from the footer of the sheet it is printed on.
  Dating them from the document would have filed three quarters of that
  schedule under a day it did not take effect.

A new recognizer reads the shape these sheets price in: a heading stating a
unit in its own parenthesis, then a run of rows of one label and one amount,
dated by the sheet. It refuses far more than it reads, and every refusal is a
case where a value could otherwise be wrong:

- a block whose heading states no unit, because a number with no unit says
  nothing about what it prices;
- **a page that sets amounts in more than one column**, because a row carrying
  one amount in a two column table has to say which column it sits in and a
  block stating no columns cannot. This costs most of the commercial schedule's
  prices and is the same refusal as the standby charge in ADR 0004;
- a row that dates itself, which belongs to the dated-charge shape and would
  otherwise be labelled with its own date and then dated again from the footer;
- a row carrying a cell the publisher marked with dashes, which prices a column
  this block does not name;
- a row where anything but a right-margin change flag follows the amount, or
  where the label does not stop clear of the value column, which is what
  separates a table row from a sentence ending in a price.

Left open, and still open: the identity fields, the cross-reference wording and
the credit form. Each is a statement about how one publisher writes, and none
of them is a thing a document cannot state about itself, so none of them
belongs in a profile. Closing them means finding the shape, not adding a field.

## Consequences

- The four schedules of the first publisher are byte for byte unchanged. Their
  golden files did not move. That is the test that this is a seam and not a
  branch: everything the profile supplies has a refusing default, and the first
  publisher takes the default for all three fields.
- The second publisher's three schedules go from 0% to 15.6%, 4.2% and 20.9%,
  and emit 26, 3 and 18 prices. Those figures are low and they are published
  next to the others. The commercial schedule's own rate sheets contribute
  nothing at all, because they price two rate options side by side.
- No golden file is committed for the second publisher. Most of each document
  is still carried verbatim in `notes`, and committing that would republish a
  document [ADR 0003](0003-do-not-redistribute-source-documents.md) says this
  repository does not redistribute. What is committed instead is a spot check:
  six prices quoted from the sheets with their unit, effective date and
  heading, checked against the PDFs by hand, so that a parser change altering
  one of them fails rather than passing quietly.
- A profile is named for the document family it was written from. The three
  schedules behind `pge-tariff-book` are filed with the California Public
  Utilities Commission and other Californian investor-owned utilities file in
  the same form, so the profile is expected to fit theirs. It has not been
  tested against one, and the name is meant to keep that honest.
- The `Charge` record gains an optional `group`, the heading of the block a
  price was read from. Without it a row labelled "Income Tier 1" would not say
  which of a sheet's several tables it came from. It is absent from every
  charge the first publisher's schedules produce, which is why their output did
  not change.
