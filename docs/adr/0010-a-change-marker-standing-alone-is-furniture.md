# 0010. A change marker standing alone on a line is furniture

- Status: Accepted
- Date: 2026-08-22

## Context

The three PG&E schedules print a bracketed capital beside a filing change,
`(R)` revised, `(N)` new, `(I)` increase, `(D)` decrease, `(L)` line change
only, `(T)` transferred -- the letters California's General Order 96-B
defines -- and a change bar in the right margin beside a whole changed
paragraph, which `pdfplumber` extracts as the literal character `|`. Both
are visible today, inside `notes`, wherever the line they sit beside is not
otherwise understood, e.g. `"BASELINE RATES: PG&E may require the customer
to complete and file with it a (L)"`.

Where a marker sits at the end of an otherwise real line, `sheet_rates.py`
already reads through it (`MARGIN_TOKEN_RE`, unconditionally, for any single
bracketed capital): the row's own amount is what is emitted, and the marker
is stripped from the row's own value area without altering the citation's
snippet, which still quotes the line as printed. That was already correct
and untouched by this decision.

What was not handled is a line carrying *nothing else at all*: `pdfplumber`
extracts a change bar spanning several rows as its own line, at its own
vertical position, and a marker beside a heading with no priced row of its
own the same way. Such a line is not content in any sense the rest of this
parser tries to structure -- it names no fact, prices nothing, states no
eligibility -- and today it is reported as an unrecognised content line and
carried into `notes` as the bare string `"(D)"` or `"|"`, which is not
useful to a reader and drags down a coverage figure over content that was
never there.

Stripping the marker from a real line's quotation, so that `notes` reads
"...file with it a" instead, was rejected: that edits a quotation, which
this parser does not do anywhere else, and the roadmap said so before this
ADR existed. The question this ADR answers is only about a line that
*is* the marker, nothing else.

## Decision

Reading a bare marker line as furniture, the same category as a running
header or footer (`Line.furniture`, already excluded from the coverage
denominator and from every recognizer's input), is the fix. It fits the
category exactly: `Page furniture is not content`, per `extract.py`'s own
docstring for that flag.

Which letters a publisher uses this way is a filing convention the page
does not state, the same shape of fact `supersession_word` already
supplies. A new profile field, `change_markers: frozenset[str]`, names
them; the default is empty, so an unprofiled document treats no line this
way. `pge-tariff-book` names the six letters actually observed across the
three schedules it was written from: `{"R", "N", "I", "D", "L", "T"}`. The
change bar, `|`, is not itself letter-specific -- it is the same right
margin glyph as the bracketed letters, just for a whole paragraph rather
than one line -- so it counts as soon as a profile names any letter at all,
rather than needing a field of its own.

A line only qualifies when it carries exactly one word and that word is one
of these two forms. A marker sharing a line with anything else, however
short, is left exactly as it is today: still inside whatever citation
quotes that line, verbatim.

## Consequences

- `pge-e-1`'s coverage moves from 42/269 (15.6%) to 42/247 (17.0%); 22
  lines were entirely a bare marker or a change bar. `pge-e-tou-c` moves
  from 18/425 (4.2%) to 18/346 (5.2%), 79 such lines. `pge-b-1` moves from
  106/507 (20.9%) to 104/477 (21.8%); 2 of the lines reclassified as
  furniture here had previously been swept in as spurious trailing
  "continuation" text of a numbered item by an unrelated recognizer (a bug
  this change also incidentally closed, since the swept line no longer
  exists in `content_lines` for that recognizer to reach). No emitted price
  changes anywhere: this only ever removes a line that priced nothing.
- The four SMUD schedules take the empty default for `change_markers`, the
  same as every other profile field, and their golden output is byte for
  byte unchanged.
- What each letter *means* -- revised versus new versus a wording change
  with no rate change -- is still not read. A reader who needs to know
  whether a given price changed, rather than merely that a line beside it
  once carried a flag now excluded as furniture, still has to consult the
  publisher's own filing.
