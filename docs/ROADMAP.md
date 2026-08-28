# Roadmap

## Observability

Tier: C (library and CLI).

This is a local command line tool with no hosted route, no background service
and no user session. Distributed tracing is documented out of scope for this
tier. The tool emits no telemetry of any kind and makes no network request
except in the explicit `fetch` command.

The operator-facing signal is the `coverage` command, which reports what the
parser accounted for and what it did not.

## The plan, 2026 to 2028

This section is the forward half of the roadmap. Everything below it is the
record of what has already been settled, and nothing here overrules that
record: an item listed under *Decided against* is a decision, not a gap, and
reopening one means overturning its reasoning rather than restating the idea.

Every phase below is bounded by the rule `CONTRIBUTING.md` puts above
everything else: **never invent a rate, a rate structure, a time window, or a
citation.** Three consequences shape the whole plan.

- **A refusal is a deliverable.** A phase that reads its shape and a phase
  that proves the shape cannot be read without guessing both close honestly.
  The second closes with an ADR and a test asserting the refusal, the way
  ADR 0011 closed the price stated inside a sentence.
- **Coverage is a measurement, not a target.** Each phase states the figure it
  expects to move, because a phase that moves no figure and adds no refusal
  did nothing. It never states a figure it intends to reach, because a rule
  widened to hit a number is the defect this project exists to avoid.
- **The four SMUD schedules are the regression.** `tests/golden/` holds their
  full parsed output. A phase that leaves those four files byte for byte
  unchanged has demonstrated it added a seam rather than a second branch,
  which is the test ADR 0006 used when the second publisher arrived. A phase
  that does change them changes them deliberately, price by price.

The coverage figures each phase is measured against are the ones in the
README's "Coverage today" table, reproducible with `make coverage-real`
against the documents `sources/sources.toml` pins.

### Phase 1: The values already published

**Delivers.** Two defects in what the parser emits today, both filed:

- A credit's `tou_period` is resolved once per section and attached to every
  credit row in it, so the first of two differently windowed credits is
  published with the second one's applicability sentence (issue #13). The
  citation is real and the provenance walk cannot catch it, because the quote
  is genuine and attached to the wrong charge. `dated_charge.py` and
  `condition_list.py` each already carry a test proving two same-shape items
  in one section keep their own local context; `credit.py` has neither the
  test nor the discipline.
- `SourceEntry.path()` joins a manifest filename onto the sources root with
  nothing keeping the result under that root, and `sources` now reads and
  hashes every present document's full bytes on every invocation even though
  the manifest already records the size that would settle a mismatch without
  reading anything (issue #16).

**Depends on.** Nothing.

**Done when.** Each fix has a test that fails against the tree as it stands
and passes after, `tests/golden/` is byte for byte unchanged, and the
`coverage` figures for all seven documents are unmoved. This phase is about
values already published being right, not about publishing more of them.

### Phase 2: Coverage as a checked output, not a written claim

**Delivers.** The README says coverage is "a published output, not an implicit
claim", and it is: the parser computes it. But the table in the README is
typed by hand, so the claim and the measurement can drift apart silently, and
the only thing standing between them is whoever remembers to rerun
`make coverage-real`.

- `coverage --json`, emitting the figures already sitting on `parsed.coverage`
  and `parsed.unparsed` rather than the prose report, so a script, a CI step
  or a coverage-over-time record can read them (issue #10). `--min-coverage`
  gates identically either way. This is a formatting change, not a new
  computation.
- A `realdoc`-marked test that reads the README's own table and asserts every
  figure in it equals what the parser reports for that document. It skips
  where the pinned documents are absent, exactly as the existing realdoc spot
  checks do, and fails where a figure in the README does not match the tool.

**Depends on.** Nothing. It comes second because every later phase claims a
coverage movement, and a claim is worth more when a test binds it to the
measurement.

**Done when.** `coverage --json` parses as JSON carrying the same numbers the
text report prints, editing any figure in the README's table fails the suite
where the documents are present, and the table's figures are unchanged,
because this phase reads no new content.

### Phase 3: The contribution surface

**Delivers.** `CONTRIBUTING.md` states precisely what a good report of a wrong
value contains and precisely what a pull request has to have done. Neither is
visible from the screen where someone actually files one.

- `.github/ISSUE_TEMPLATE/`: a wrong-or-uncited-value report prompting for the
  manifest id, page and section, the emitted JSON and the document's actual
  text; an unread-shape report pointing at the rule that a recognizer refuses
  rather than guesses; and a `config.yml` routing anything with a security
  dimension to `SECURITY.md` (issue #11).
- `.github/PULL_REQUEST_TEMPLATE.md`: the checklist `CONTRIBUTING.md` already
  states, including that a golden diff was read price by price and that a new
  refusal has a test proving the refusal (issue #12).

**Depends on.** Nothing.

**Done when.** The templates parse as the GitHub form schemas they claim to
be, every prompt in them traces to a sentence already in `CONTRIBUTING.md`,
and no source file changed.

### Phase 4: A column that names itself

This is the largest single piece of unread content in the project, and the
first of the three shape refusals the README lists under "What is still
refused on the second publisher".

**Delivers.** Today a page that sets amounts in more than one column is
refused whole: `_page_has_one_amount_column` in `sheet_rates.py` reads nothing
from such a page, because "a block that has no column headings of its own
cannot" say which column an amount sits under. That reasoning is right, and it
is about a block that has no column headings. Some blocks have them. The
second publisher's unbundling sheets head their table with the columns' own
names on the heading line:

```
Energy Rates by Component ($ per kWh)          PEAK      OFF-PEAK
Generation:
   Summer (all usage)                       $0.20782    $0.10482
   Winter (all usage)                       $0.13710    $0.11042
```

Where the document names its columns, which column an amount sits under is
read off the page the way ADR 0004 requires, from the heading words set over
it. The machinery exists: `Column`, `columns_from` and `assign` in
`recognizers/base.py`, and `dated_charge.py` already carries exactly this
reading for a commercial sheet that prices one charge across three service
voltage levels, putting the column's own heading in the charge's `applies_to`
field. Phase 4 gives `sheet_rates.py` the same reading, on the same field, for
a block whose heading line names its columns.

The refusals narrow rather than disappear, and the narrowing is the design:

- A block whose heading names no columns is refused on a multi-column page,
  exactly as now.
- A row is committed whole or not at all. It carries one cell per named
  column, each aligned with exactly one of them, or it is refused. A row
  carrying fewer amounts than the table has columns is refused, because a
  single price on a two column row may be either column's or the whole row's
  and the page does not say which. That refusal is load-bearing: it is what
  keeps `Transmission* (all usage) $0.04638` from being published as a peak
  rate.
- A cell the publisher marked with dashes stays unread, but stops refusing the
  row that carries it. Under a named column a dash says which column has no
  price for that row, which is the fact the second README refusal says the
  page could not state.

**Depends on.** Phase 2, for the test that binds the coverage claim to the
measurement.

**Done when.** ADR 0012 records the decision and its fences; the rows of a
table whose columns the page names are read across them, with `applies_to`
naming the column each was read from; a synthetic fixture proves a row that
does not line up one to one with the named columns is refused, and proves a
page that names no columns is still refused whole; `tests/golden/` is byte for
byte unchanged; and the README's table and its refusal list say what became
true.

**Shipped**, in the pull request that carries this correction's sibling. It
moved `pge-b-1` from 104 of 477 content lines to 113 and from 18 charges to 31,
and left the other six documents where they were. The names turned out to sit
in two different places on the page, on a header line over the table and on the
block's own heading line, and one mechanism reads both, which is why the phase
below no longer says what it first said.

### Phase 5: A sub-heading between a unit and its rows

**Corrected after Phase 4.** This phase and Phase 6 were first written as two
places a table's column names can sit: on the block's own heading line, or on a
header line over several blocks. Reading the three documents line by line
showed those are one mechanism, a line that sets words over the amounts, and
Phase 4 shipped both. What actually separates the remaining tables from the one
Phase 4 reads is different, and it is what these two phases are now about.

**Delivers.** Both publishers' component tables put a sub-heading between the
heading that states the unit and the rows it prices:

```
Energy Rates by Component ($ per kWh)          PEAK      OFF-PEAK
Generation:
   Summer (all usage)                       $0.20782    $0.10482
Distribution**:
   Summer (all usage)                       $0.20388    $0.18388
```

`_read_heading` looks at the line immediately above the first row, finds
`Generation:`, finds no unit on it, and refuses the block. The unit is stated,
two lines up, over a sub-heading that names a component rather than a unit.

The question is how far a stated unit reaches, and whether the page settles it.
A sub-heading that names a component is not a heading that restates a unit, and
treating every unitless line above a block as transparent would let a unit
reach across a table it has nothing to do with. Whatever rule lands has to be
readable off the page, and a reach that cannot be established refuses the block
as now.

**Depends on.** Phase 4, whose column reading these tables also need: both are
on pages that name two columns.

**Done when.** Either the shape is read, `pge-b-1` and `pge-e-tou-c` gain their
component tables, and a fixture proves a unit does not reach a block it is
separated from by more than the rule allows; or an ADR records why the reach
cannot be established from the page, with a test asserting the refusal. Both
outcomes close this phase. `tests/golden/` byte for byte unchanged either way.

### Phase 6: A unit broken across a line ending

**Delivers.** The other thing standing between the second publisher's tables
and their units is a parenthesis the publisher opened on one line and closed on
the next:

```
Base Services Charge Rates by Component ($ per
customer per day)
   Distribution
      Income Tier 1                            ($0.10751)
```

`TRAILING_UNIT_RE` requires the unit's own brackets to open and close on one
line, so it sees no unit on either. The page states one: the publisher's own
brackets delimit it, and the line ending falls inside them rather than between
them. Sheet 3 of `pge-b-1` has the same shape on its demand rate, whose unit
runs `(per metered kW/month assessed from 2:00 p.m. to 11:00 p.m. only)` across
two lines.

Whether joining a heading across a line ending is reading or reconstructing is
the phase's question. A bracket that opens and never closes settles nothing and
refuses.

**Depends on.** Phase 5, since the tables that need this mostly need that too.

**Done when.** Either the shape is read and those blocks gain their units, with
a fixture proving an unclosed bracket refuses rather than joining to the end of
the page; or an ADR records why a heading cannot be joined across a line ending
without inventing what the publisher meant, with a test asserting the refusal.

### Phase 7: The second publisher's identity

**Delivers.** The last item in the README's refusal list is "the identity
fields, the cross-reference wording and the credit form", each "a statement
about how one publisher writes, not a thing a document cannot state about
itself, so none of them belongs in a profile. Closing them means finding the
shape, not adding a field."

The identity half is measurable today: parse any of the three PG&E schedules
and `identity` comes back with `schedule_code`, `title`, `resolution`,
`adopted` and `effective` all null, and only `sheets` populated. The document
states some of those plainly in its own furniture, and prints beside every
sheet number the number that sheet cancels.

This phase reads what the furniture states and stops there. A field the second
publisher does not print stays null, because a null is a true statement about
a document that does not carry the field, and a borrowed value is not.

**Depends on.** Nothing in Phases 4 to 6, though it comes after them because
they move more.

**Done when.** The identity fields the PG&E furniture states are read and
cited, the ones it does not are still null, a fixture proves a document that
prints neither publisher's shape still parses with a null identity rather than
a guessed one, `tests/golden/` is byte for byte unchanged, and an ADR records
which fields were found to be unstated rather than merely unread.

### Phase 8: Release and distribution

**Delivers.** The README's Standards Conformance table says Release and
Versioning applies, "SemVer with a signed-tag release workflow that separates
verification from publication". `.github/workflows/release.yml` implements it
and has never run: there is no tag and no release. Installation is
clone-and-`make install`.

The work is a signed annotated tag verified against
`.github/allowed_signers`, the release workflow's first real end-to-end run,
and a decision about whether this belongs on a package index at all.

**Blocked, and on whom.** Signing a tag needs the owner's key, and publishing
under a name on an index is the owner's decision about a name only the owner
can hold. Neither is delegable to a contributor, and neither should be worked
around. This phase stays open, and stays honestly described as blocked, until
the owner does the two things only the owner can do.

**Depends on.** Phases 1 to 3 at minimum, since a release should carry the
correctness fixes.

**Done when.** `v0.1.0` exists as a signed annotated tag, the release workflow
has run green from it, and the README's install section describes whatever
distribution the owner chose, including "clone it" if that is the answer.

### Sequencing

| Order | Phase | Depends on | Moves |
| --- | --- | --- | --- |
| 1 | The values already published | nothing | no figure; two wrong outputs |
| 2 | Coverage as a checked output | nothing | no figure; binds the claim |
| 3 | The contribution surface | nothing | no figure |
| 4 | A column that names itself | 2 | `pge-e-tou-c`, `pge-b-1` |
| 5 | A sub-heading between a unit and its rows | 4 | `pge-b-1`, `pge-e-tou-c` |
| 6 | A unit broken across a line ending | 5 | `pge-b-1`, `pge-e-tou-c`, or a refusal |
| 7 | The second publisher's identity | nothing | identity fields, no coverage figure |
| 8 | Release and distribution | 1 to 3 | nothing in the parser; blocked on the owner |

Phases 1 to 3 are independent of each other and of everything after them.
Phases 4 to 6 are one line of work cut into three, and each one's refusals are
what make the next one safe. Phase 7 could be done at any point and is placed
last among the reading phases because it moves the least.

### Not in this plan

Stated so that the plan's silence is not read as an omission.

- **A third publisher.** ADR 0005 designed the document profile so that a
  second publisher would not become a second special case, and a third would
  test that. It is not planned here because the second publisher is not
  finished: three of its schedules are pinned and most of two of them is still
  unread. Adding a third document before then would widen the surface rather
  than the understanding.
- **Anything reached by fetching.** The manifest pins seven documents by
  digest. Adding to it is a deliberate act with a retrieval date and a
  publisher's `robots.txt` behind it, not something a phase assumes.
- **The refusals under *Decided against*.** They are decisions. See ADR 0011.

## Done

These were the largest items on this roadmap. Each is described where it
landed rather than repeated here.

- **A document profile, so a second publisher can be read at all.**
  [ADR 0005](adr/0005-a-second-publisher-needs-a-document-profile.md) and
  [ADR 0006](adr/0006-the-document-profile-holds-three-things.md); see "The
  document profile" in the README. Three PG&E schedules went from 0% coverage
  to what the coverage table now reports.
- **An amount written in accounting brackets**, as `($0.08140)` for a
  negative. Shipped as the profile's `bracket_negative_amounts` field; see
  ADR 0006.
- **The proration table**, on three of the four SMUD documents. Its basis
  column is sometimes a cell genuinely drawn to span more than one
  circumstance, which line-by-line reading cannot tell apart from an
  unrelated cell. Shipped by reading the table's own ruled border directly
  (`ExtractedTable` in `extract.py`) rather than inferring row breaks from
  spacing; see "The proration table" in the README and ADR 0007.
- **A stable JSON Schema for `parsed-schedule/v1`**, published at
  `schemas/parsed-schedule-v1.schema.json` and validated in the test suite
  against every golden file and every synthetic fixture's output, and, when
  the real source documents are present locally, all seven of those too, so
  the schema cannot drift from what `parse` actually emits.
- **Enumerated condition lists** outside an Applicability or Eligibility
  heading, such as the standby service conditions ("Standby Service applies
  when all of the following conditions are met: 1. ... 2. ... 3. ..."). Read
  as a new record, `Condition`, that carries no disposition at all rather than
  forcing one from `Applicability`'s scale: see ADR 0009 for why that scale
  does not fit a connection requirement.
- **The commercial transition table**, which puts the unit in a column of its
  own rather than in the label, and dates its prices to a bare year carrying a
  footnote. It has no ruled border the way the proration table does, so this
  needed its own shape read from column geometry, the way `sheet_rates.py`
  reads its tables. Shipped as `transition_table.py`; see ADR 0008.
- **Filing change markers**, the `(R)`, `(N)`, `(I)`, `(D)`, `(L)`, `(T)` and
  similar a regulated publisher sets beside a revised line, and the change bar
  in its right margin. A marker attached to real text is still carried
  verbatim inside whatever citation quotes that line, unchanged; a line that
  is *nothing but* the marker is now read as furniture, the same category as a
  running header, under a new profile field naming which letters a publisher
  uses this way. See ADR 0010.

## Decided against

- **A price stated inside a sentence**, as the solar and storage schedule
  states its export compensation rate. This stays refused: not for lack of a
  rule that could read this one sentence, but because a rule fitted to a
  single example is not a generalisation, and this price is additionally
  stated as provisional on a formula defined elsewhere, which an ordinary
  `Charge` has no way to say. See ADR 0011 for the full reasoning; the
  existing test asserting `smud-ssr` emits zero charges is the specification,
  not a placeholder.

Coverage figures move only when a recognizer genuinely understands more of a
document. Widening a rule to raise the number is a defect, not progress.
