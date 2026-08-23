# Roadmap

## Observability

Tier: C (library and CLI).

This is a local command line tool with no hosted route, no background service
and no user session. Distributed tracing is documented out of scope for this
tier. The tool emits no telemetry of any kind and makes no network request
except in the explicit `fetch` command.

The operator-facing signal is the `coverage` command, which reports what the
parser accounted for and what it did not.

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
