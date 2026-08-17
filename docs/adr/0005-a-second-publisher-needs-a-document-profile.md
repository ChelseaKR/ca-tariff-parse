# 0005. A second publisher needs a document profile, not a second special case

- Status: Accepted
- Date: 2026-08-17

## Context

Four schedules from one publisher had already shown that the same publisher
sets the same table in different places, and [ADR
0004](0004-read-table-geometry-from-the-document.md) closed that by reading
table geometry from the document. It ended by saying that adding a publisher
was still expected to find geometry the parser reads by convention rather than
by reading. That was the untested claim, so three schedules from a second
publisher were fetched and parsed: a residential one, a residential
time-of-use one and a small commercial one.

`robots.txt` for the host was read first. It disallows two mobile paths to a
general client and publishes a sitemap of the tariff book, so the three
documents were in scope. Retrieval was three requests.

Coverage collapsed to nothing.

| Schedule | Lines recognized |
| --- | --- |
| E-1, residential | 0/269 |
| E-TOU-C, residential time-of-use | 0/425 |
| B-1, small general service | 0/507 |

Three quarters of that collapse has a single cause. This parser recovers the
document's outline from statute-style numbering, roman numerals over capital
letters, and cites every value to the part it was read from. The second
publisher has no numbered outline. It sets a keyword in a narrow left-hand
column and the text beside it, so the line reads `APPLICABILITY: This schedule
is applicable to ...`. With no outline the segmenter produces one section
holding the whole document, and every recognizer is handed 500 lines of mixed
prose and tables as though they were one block.

The rest of the collapse is recognizers keyed to phrasing rather than to shape.
The rate table recognizer claims a section by finding the literal words
`Effective as of`, because that is how the first publisher heads its price
columns. The second publisher does not date columns at all: one amount per row,
and the sheet as a whole carries the effective date in its footer. The identity
reader looks for `Rate Schedule <code>` and `Resolution No. <n> adopted <date>
Effective: <date>`; this publisher writes `ELECTRIC SCHEDULE E-1 Sheet 1` and
dates by advice letter. Cross references look for `Refer to Rate Schedule X`;
this publisher writes `see Special Condition 8` and `in accordance with Rule
1`. Applicability claims a section whose *heading* is Applicability, and here
that word is a label in a column, not a heading.

Nearly all of that produced nothing, which is the designed behaviour and the
reason two of the three documents emitted not one value. One thing did produce
output, and it was wrong.

On the commercial sheet the parser emitted two time-of-use windows whose season
was `PERIOD`. The window table is nested inside the right-hand column of the
keyword layout, and `TIME PERIOD` is its own column heading, set in the
left-hand keyword column. The window recognizer takes the season from whatever
text sits left of the period column, so it took the heading. Both windows came
out under a season the publisher never wrote, with the real seasons, which this
sheet sets as full-width banner rows, lost. A fabricated season attached to a
real window, carrying a citation, is the same class of failure as the standby
charge in ADR 0004.

Two smaller defects were general rather than particular to either publisher.

- Every page of these documents prints its own sheet number over the number of
  the sheet it replaces: `Revised Cal. P.U.C. Sheet No. 61362-E` above
  `Cancelling Revised Cal. P.U.C. Sheet No. 61247-E`. Sheet detection took the
  last match on the page, which was correct only because the first publisher
  prints exactly one. Every citation on such a page named the withdrawn sheet,
  and the schedule's own list of sheets was half cancelled numbers.
- Page furniture was decided by a fixed fraction of page height. This publisher
  runs body text a little further down the page, and three body lines fell past
  the band. A line marked as furniture is in no section, so it is neither
  counted nor reported as unparsed: it disappears. One of the three carried a
  published amount.

## Decision

The general defects are fixed. The publisher-specific ones are not worked
around, and no second special case is added.

Fixed, because each is wrong for any publisher:

- A sheet number a page announces as cancelled is never recorded as that page's
  own, and a page asserting two numbers that disagree records none.
- The footer band says where a footer may be; the page's own line spacing says
  where the body ends. A line in the band set at ordinary body spacing under
  the line above it is body, and is accounted for.
- A time-of-use window is emitted only when its season states a part of the
  year, which is what a season is. Any other text left of the period column is
  not a season, and a window whose season cannot be read is not emitted at all.
- A rate table row is refused whole when any cell in its value area is neither
  an amount nor an explicit `n/a`. The rule that a row is committed whole or
  not at all was stated in ADR 0002 and not enforced: an unreadable cell was
  skipped and the rest of the row published. The second publisher writes a
  negative in accounting brackets, `($0.08140)`, which is a real price in a
  form this parser does not read, so a row mixing the two forms would have
  published part of itself as the whole.

Not fixed, and deliberately left as a gap: the outline, the table claim
phrasing, the identity fields, the cross-reference wording, the credit form and
the accounting-bracket negative. Each of those is a statement about how one
publisher writes, and answering them with a second branch beside the first is
how a parser becomes a pile of special cases that nobody can review.

The shape the second branch should take instead is a **document profile**,
selected per manifest entry and supplying only what is genuinely a publisher's
house style:

- how the outline is written: numbered parts, or a keyword column whose width
  the profile states, or neither;
- how an amount is written, so that an accounting bracket can be read as a
  negative where a publisher uses it and refused where one does not;
- which page furniture announces a supersession, and which line dates the
  sheet.

Recognizers keep reading geometry from the document. The profile answers only
the questions the document does not answer about itself. A document with no
profile parses as today, which is to say it is refused rather than guessed at.

No profile is implemented here. Implementing it against one further publisher
would fit it to that publisher, which is the mistake this record exists to
avoid making twice.

## Consequences

- Reported coverage on the second publisher's three schedules is 0%, published
  in the README beside the four that do parse. The output of those parses is
  the unparsed report and the verbatim text, which is the honest result.
- No golden file is committed for them. Nothing is recognized, so the whole
  document text would sit in `notes`, and committing that would republish a
  document [ADR 0003](0003-do-not-redistribute-source-documents.md) says this
  repository does not redistribute. What is committed is the manifest entry and
  a test asserting the refusal.
- Coverage of the four original schedules did not move and their golden output
  is byte for byte unchanged. As in ADR 0004, that is the point: the change is
  about documents the parser was not written against.
- The window recognizer now refuses more. A window table whose season column
  the parser cannot read produces nothing rather than a season it inferred from
  position.
- The claim in ADR 0004 that a fixed value is acceptable when it is a tolerance
  rather than a position survives, but the footer band was a position wearing a
  tolerance's clothes, and so was the sheet-detection scan order. Both are now
  read from the document.
