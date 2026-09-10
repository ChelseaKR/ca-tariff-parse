# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `explain` names the recognizer that read a line, or the named fence that
  refused it, with the ADR the fence comes from and what it saw on the page.
  Every line lands in one of four states, and `unclaimed` -- no recognizer
  claimed the line's section, so no fence could have fired -- is a first-class
  answer rather than a gap. `explain` never offers a nearest fence: a closest
  rule chosen by proximity would be a value invented from an absence.
- `explain --fences` lists every fence the parser can report. The report also
  prints how many of them a document reached, out of how many exist, because a
  count of refusals says nothing about how much of the vocabulary ran.
- `ca_tariff_parse.trace`, the channel recognizers record into. Recording is
  off unless a caller opens it and nothing reads a trace back while parsing,
  so `parse` emits the same bytes either way -- asserted over every committed
  fixture rather than stated.
- Two fixtures written to trip fences: `SYNTHETIC-example-refused-rows.txt`
  and `SYNTHETIC-example-unclosed-bracket.txt`, the second carrying the ADR
  0014 case of a label that opens a bracket the publisher never closes.

### Changed

- Nothing in `parse`'s output. The engine now records which recognizer was
  offered each section, which claimed it, and which lines each consumed; none
  of it reaches the emitted document.

## [0.3.0] - 2026-09-07

Seventeen commits since `v0.2.0`, and six of them are verbs a reader can
run: `export`, `check`, `history`, `calendar`, `load` and `reconcile`.
The theme underneath them is the same one the project keeps finding --
a state for what the tool could not decide, kept separate from a clean
result. `check` has one, `diff` stopped reading equal parser stamps as
clean when they are indeterminate, and `history` stopped reading an
empty record as a failed match.

`PARSER_VERSION` moves with the release version -- `test_release_metadata`
holds the two equal -- so every committed parse was re-captured at 0.3.0.
The recapture is recorded here because a golden re-captured without a
stated reason stops being evidence. It was done from the seven source
documents already on disk, each first confirmed against its `sources.toml`
sha256 by `make verify-source`, so no document was re-fetched and none
could have moved underneath it. **The whole diff across all eleven files is
eleven lines: `parser_version` 0.2.0 -> 0.3.0, one per file. No price, no
date, no coverage figure and no line count changed.**

A consumer holding a 0.2.0 parse and comparing it against a 0.3.0 one gets
`PARSER_DIFFERENT` rather than a silent comparison, which is what that
field is for; `diff.py` already documents that equal stamps are
`PARSER_INDETERMINATE` rather than proof the same build read both.

### Changed

- **The one action that stands between this project and an installable package
  is now written down as the form it has to be typed into.** The publish
  workflow and `docs/ROADMAP.md` both said the project must be "registered on
  pypi.org with this repository, that workflow file and the `pypi` environment
  named as its publisher", which is accurate and is not the five labelled
  fields PyPI's *Add a pending publisher* form actually asks for. Both now
  carry the values verbatim, and both note that `Workflow name` is the
  filename rather than the workflow's `name:` field, because getting that one
  wrong produces a failure that reads like a permissions problem instead of a
  typo. The name was re-checked free on 2026-09-07, and the roadmap now says
  what free means here: nothing is reserved until the registration is made.
  No workflow behaviour changes and nothing is published.

### Fixed

- **`history --all` no longer reports an empty record as a failed match.** With
  a reviewed baseline committed and no change reports beside it — which is the
  state of this repository today, since `data/changes/` does not exist until
  the watch records a revision — `--all` exited 5 and printed
  `no record matched None`. Two things wrong with that: `--all` asks for
  nothing by name, so nothing coming back is a statement about what has been
  committed rather than a request that failed, and a script reading exit 5 was
  told the request was wrong. It now exits 0 and says which directory holds no
  reports. The report itself says that neither an empty match nor an empty
  report set means the document has not changed; it means the committed record
  does not cover it. `--match` selecting nothing still exits 5.

### Added

- **A `reconcile` verb audits a URDB record against the cited parse.**
  OpenEI's Utility Rate Database is the dataset most tools use for California
  tariffs, and its records carry no citation to a page.
  `ca-tariff-parse reconcile parsed.json urdb-record.json` reads a record the
  user downloaded themselves and reports, for each field, whether the parse
  **confirms** it with a citation, **contradicts** it with both values and the
  page, has **no statement** about it, or cannot express it at all. Offline;
  the record is a file the caller supplies and nothing is written back. Exits 0
  when nothing contradicts, 3 when something does, 2 when the record cannot be
  read.

  What it refuses to do is the substance. It does not align URDB's
  index-numbered rate periods with the names the document prints, because
  neither record states the correspondence; values are compared by membership
  in a unit family instead, and the report says so. It does not compare a tier
  that carries an adjustment beside its rate, because `rate + adj` is what a
  customer pays and the printed price is what this model records. It does not
  match a credit against a rate. It does not treat a parse with no charges as
  agreement: `smud-ssr` prices nothing (ADR 0011), so every priced field of a
  record reconciled against it comes back "no statement". And a record whose
  start date no charge carries widens the comparison to every charge rather
  than narrowing it to nothing, so an empty selection can never be printed as
  silence where there is a disagreement.

  Every key in the record is reported, including the ones the mapping does not
  cover, each with the reason it is not comparable — so the report is complete
  over the record rather than quietly partial.

- **A `history` verb rebuilds a value's timeline from the committed reports.**
  The watch writes a diff per revision and a reviewed baseline, and nothing read
  them back. `history --id <id> --match 'kind=... label=...'` walks the reports
  in the order they themselves state and prints every state a matching record
  has held, each with its retrieval date and the citation of the revision that
  set it, ending with the baseline. `--all` covers every record the reports
  mention; `--jsonl` writes one object per timeline.

  What it refuses to do is the substance. It does not smooth a gap: each report
  states the digest of the bytes on both sides, so a report comparing against
  bytes no committed report produced means a revision is missing, and the
  timeline says so at that point instead of joining the two ends — including
  against the reviewed baseline. It does not order by filename: a retrieval
  date is read from the report, and two reports whose dates run backwards are
  refused with both dates named. And no leg claims one parser read both sides:
  every leg carries `diff`'s three-state `parser_comparison`, which still has
  no state meaning "the same parser".

  A record no report mentions is listed with one state from the baseline rather
  than omitted, so "no result" cannot mean both "no such record" and "a record
  nobody has moved". A `--match` naming a field no record kind is identified by
  is an error rather than a term that quietly matches nothing, and a well-formed
  match that selects nothing exits 5 — a different code from a read failure.

### Changed

- **`diff --jsonl` now carries both sides' stamps on every change line**:
  retrieval date, document digest, parser version and `parser_comparison`, for
  the old side and the new. It is still one object per change. The stamps are
  repeated per line rather than written once in a header so that a line lifted
  out of the file still says which retrieval it came from, and so `history` can
  read a report's retrieval date rather than inferring it from the filename.

- **A `calendar` verb writes the time rules the document stated, and a refusal
  list for the rest.** `calendar <parsed.json> --dir DIR` writes
  `<id>.ics` and `<id>.refused.json`, both always, because a missing refusal
  file reads as "no refusals" and an empty list reads as "nothing was refused".

  This is the first consumer-facing derivation the project ships, so the fence
  is the feature. A `VEVENT` is written only where it re-expresses text the
  parser already committed to. A residual window is refused on the residual
  flag itself rather than on the absence of times, so it stays refused even if
  it carried hours. A window defined by exception, a window with hours but no
  stated day type, and a window whose end is at or before its start are each
  refused with the reason and the citation. A holiday `day_rule` outside a
  closed grammar — a fixed day, an ordinal weekday, a last weekday — is refused
  rather than approximated: `Day after Thanksgiving` is a real rule with a
  defensible date, and rendering it as the fourth Friday would give a guess a
  calendar entry's authority.

  Season bounds are added only where the season names whole months, because
  `BYMONTH` can express whole months and nothing else; a range like
  `Jun 15 - Sept 30` is left unbounded and marked partial rather than widened.
  No time zone is inferred and the file says so. Recurrences are anchored to
  1970 because a published rule states no year, and every `DTSTART` is a real
  instance of its own rule so a reader cannot read it as an extra occurrence.
  Nothing reads the clock: `DTSTAMP` is the document's retrieval date, or the
  epoch, so the same parse renders identical bytes.

  On `smud-r-tod` this renders 2 of 5 windows and 11 of 11 holidays, with three
  refusals. On `smud-ci-tod1`, which states no bare times, it renders none of
  its five and says so. A watch baseline is refused outright: it omits the
  verbatim prose, and a refusal that cannot quote what it refused is not one.

- **An `export` verb writes the parse as cited tables.** `parse` emits one
  nested document per schedule; the shape downstream tooling consumes is one
  row per charge. `export <parsed.json> --table charges` writes CSV,
  `--format jsonl` writes the same rows as objects, and `--all DIR` writes
  every table.

  The reshape is where the project's guarantee is easiest to lose, so: every
  cited field is followed by a `<field>.locator` column, and `document_id`,
  `document_sha256` and `parser_version` sit on every row, so a row lifted out
  of its file still names the bytes it came from. A null is an empty cell,
  never `0` or `n/a`. Each table's row count is checked against the record
  count and a mismatch raises rather than writing a short table. Nothing is
  computed — the export reshapes what was read, and a derived number beside
  cited ones would be indistinguishable from them. A schedule that prices
  nothing exports a header with no rows, because a missing file would read as
  "not exported".

  Columns are derived from `schemas/parsed-schedule-v1.schema.json` rather than
  listed in the export, so they cannot drift from the model. `notes` and
  `unparsed` are deliberately not tables, and the exclusion of `unparsed` is
  checked against the schema: if that record ever gains a cited field the
  export refuses to run rather than quietly hiding it.

  Rows sort by their first citation's own page, sheet, section and line rather
  than by the rendered locator text, so page 10 follows page 9, with the whole
  row as the final tiebreak; two exports of one parse are byte identical. CSV
  cells a spreadsheet would evaluate are prefixed with an apostrophe, except a
  leading minus on a number, because a credit is printed as `-0.05` and
  neutralising it would change what a reader sees. `--snippets` adds the
  cited text and is off by default (ADR 0003).

- **A parse can be read back into typed records, without a PDF stack.**
  `parse` wrote JSON and nothing read it back: every record had `to_json` and
  none had the inverse, so a downstream project wanting the committed
  baselines under `data/parsed/` re-implemented the model and, with it, every
  rule about what a value is allowed to be. `ca_tariff_parse.load` (and
  `loads`) now rebuilds a `ParsedSchedule` from a file, a mapping or JSON
  text, and every record carries `from_json`.

  Loading is not trusting. Each leaf goes back through the same constructors a
  fresh parse uses, so a citation missing a field, a digest that is not 64 hex
  characters or a page number that is not positive raises `ProvenanceError`
  and yields no object at all; `assert_fully_cited` then walks the
  reconstruction independently. Every derived key — a locator, an unparsed
  span, `line_ratio`, `section_ratio`, `fully_recognized` — is recomputed from
  the fields beside it and compared, so a payload cannot assert a clean sweep
  its own counters do not support. The key set is exact in both directions: a
  missing key and an unknown key are both refused, because either would leave
  a caller holding an object that looks complete and is not.

  A watch baseline omits the document's verbatim prose on purpose (ADR 0003,
  ADR 0016), and `load` reads that shape too without flattening the omission
  into an answer. Such a schedule reports `withheld == ("notes",
  "unparsed[].sample")`, its `notes` collection refuses to be queried rather
  than returning nothing, and re-serialising it writes a baseline again — not
  a `parsed-schedule/v1` payload with `"notes": []`, which would state that the
  document has no prose.

  The query surface is `schedule.charges.where(...)` over any record
  collection and `schedule.cite(record, field)`. `where` compares a cited
  field on its value and a structural field directly; `where(season=None)`
  selects the charges that state no season, a different question from
  `where(season="Summer")`; and an unknown field name raises rather than
  returning an empty result, because an empty result reads as "the schedule
  states none of these". `cite` raises for a field the document did not state
  and for structural metadata, rather than handing back a blank.

  Every committed golden file and watch baseline now loads and re-emits byte
  for byte, which is what the round-trip test asserts: byte equality catches a
  field the loader silently dropped, where object equality cannot. Reading
  needs only the standard library — importing the package does not import
  `pdfplumber`, and a subprocess test makes that import genuinely fail to
  prove it.

### Fixed

- **A diff whose two parses state the same parser version no longer reads as
  clean.** `parser_version` is the release constant in `parser.py`, so it moves
  only when a release is cut and every build between two releases stamps it
  identically. The report printed its "two different parser versions read these
  documents" warning only when the two strings differed, and printed nothing at
  all when they matched — which is the common case, and which reads as "one
  parser read both, so everything below is the publisher's". A baseline written
  by last month's parser and a revision read by today's would produce a report
  that mixed parser changes with publisher changes and said nothing about it.
  `ScheduleDiff.parser_comparison` now reports one of three states —
  `different`, `unstated`, `indeterminate` — with no fourth state meaning
  "same parser", because the payloads cannot establish one. Every report
  carries the note for its state, the watch summary carries
  `parser_comparison`, and the tariff-watch pull request template carries the
  matching review item in all three cases instead of only the first.
- **A `robots.txt` group naming this tool by name is now honoured.** Fetches
  sent a spoofed desktop Chrome `User-Agent`, which `urllib.robotparser`
  reduces to the token `mozilla` before matching a group. No plausible
  `User-agent:` line matches that, so no named group was ever selected and only
  a `User-agent: *` group could refuse a fetch. A publisher writing
  `User-agent: ca-tariff-parse` / `Disallow: /` was fetched anyway — and
  because the header claimed to be Chrome, that publisher had no server-side
  way to identify the request either, so the by-name opt-out the README
  promises existed at neither end. Requests now identify themselves as
  `ca-tariff-parse/<version>` with a link to this repository, and the robots
  check matches on that same token.
- **The diff report no longer claims every line cites both sides.** That
  sentence printed above every table, unconditionally, and was untrue of every
  added and removed row (which carry the one citation they have, by
  construction and by ADR 0016) and of some changed rows: a value that is not a
  cited envelope cites neither side, and an optional cited field absent on one
  side cites one. The note is now derived from the rows and counts them, so it
  cannot drift from what the table shows.
- **Occurrence ordinals past the second were wrong.** The suffix was the
  literal string `nd`, correct for exactly one value, so the third repeat of an
  identity rendered "3nd occurrence" and the eleventh would have rendered
  "11nd". The committed baselines already contain identities occurring four
  times, and this text is the `what` column of the tariff-watch report a
  reviewer reads. Ordinals are now correct for any number, teens included.

### Added

- **`check`: which properties of a parse hold, and which cannot be decided.**
  `parse` is honest about what it read and silent about whether what it read
  hangs together, so a consumer works that out downstream and lands one step
  from this project's defining defect: a missing thing read as a value. A
  charge whose period no window defines is not a charge that applies all day;
  a residual window is not a window with no hours.

  `ca-tariff-parse check parsed.json` answers five named properties —
  `period-window-closure`, `season-vocabulary`, `window-enumerability`,
  `unit-uniformity`, `cross-reference-pinned` — each as `holds`,
  `does not hold` (with every record involved listed by its citation), or
  `cannot be established`. There is deliberately no fourth state meaning "no
  problems found": a document with no charges satisfies "every charge has a
  window" vacuously, so `smud-ssr`, which prices nothing, reports all five as
  `cannot be established` rather than five passes. `--require <property>`
  exits 4 unless that property holds, and treats `cannot be established` as
  unmet. `--json` writes the same report as JSON. It infers nothing, fills
  nothing in, fetches nothing, and is byte-for-byte deterministic; the watch
  baseline's projection changes no result.

  Two answers over today's corpus are facts about the documents rather than
  about the tool, and are recorded in the README: `season-vocabulary` cannot
  be established on any real document, because each names its seasons twice in
  two vocabularies and matching them would be inference; and
  `period-window-closure` does not hold on `smud-r-tod` or on the complete
  synthetic fixture, where one credit line carries the period
  `midnight to 6:00 a.m. daily`, a phrase read from prose that no window
  defines.
- ADR 0018 records what the second publisher does not state, from the
  footer of all twenty-eight pinned sheets: `resolution` is a form label with
  nothing beside it, `adopted` is never printed, and `effective` is per sheet
  and differs within a document. The three schedule-level fields stay null as
  a statement rather than a gap, and two synthetic fixtures pin that a
  document printing neither publisher's shape, or this publisher's signature
  block with an empty `Resolution`, invents nothing. No parser change.
- A table's first line says how far its unit heading reaches. ADR 0013 read
  a unit over the components of its table only where the heading was set left
  of them, and called a heading level with them their sibling; the residential
  sheet sets a heading's own first-level lines level with the heading
  (`Energy Rates by Component ($ per kWh)` over `Generation: $0.12855`), so
  that inference was one publisher's typography, not a fact about pages. The
  reach is now read off the heading's first line: nothing set further left
  than it is in the table, and a heading whose first line is set left of it
  heads nothing. A component line level with the rows beneath a heading is
  their sibling and is passed over; a block with no component line of its
  own is priced under the heading's own name. See ADR 0017. `pge-e-1` goes
  from 67 of 247 content lines to 84 and from 38 charges to 53; the four SMUD
  schedules and the other two PG&E schedules are byte for byte unchanged.
- A row's label is joined across a line ending where the publisher's own
  brackets say it continues, the rule ADR 0014 reads a wrapped unit by, and
  cited to both lines with the label's own words as the quote. A row whose
  next line may be the rest of its label, and whose page does not say so, is
  refused rather than published with half a name; so is a label still opening
  a bracket. See ADR 0017.
- `diff`: what changed between two parses of one schedule, value by value.
  Records are matched by what they are (a charge by its kind, label, category,
  season, period, applicability, group, effective date and unit) rather than
  by where they sit, so a value that only moved on the page is not a change,
  and each occurrence of a repeated identity is its own record. Every line
  carries the citation the value was read from before and after; a diff
  across two parser versions says so at the top. Exits 3 when anything
  changed. See ADR 0016.
- `watch`: downloads each pinned document and, where the publisher serves
  bytes that are not the pinned bytes, parses the revision, diffs it against
  the document's baseline, writes the report under `data/changes/`, and
  proposes the manifest entry's new digest, retrieval date, page count and
  size in place, comments intact. A download that fails is an error, never
  "unchanged". `baseline` writes the reviewed parse of each pinned document
  under `data/parsed/`, from the pinned bytes only.
- `data/parsed/`: the reviewed parse of all seven pinned documents, as a
  projection of `parse`'s output without `notes` and the samples under
  `unparsed`, which is where most of an unread document's prose would
  otherwise travel (ADR 0003). The file says what it omits and why. A test
  fails when a committed baseline is not what the current parser writes.
- `.github/workflows/tariff-watch.yml`: the watch, weekly and on demand,
  opening one pull request per revised document for a person to review.
  It merges nothing and never commits a PDF.
- `download` in `sources.py`, split out of `fetch`: the half that touches
  the network, without the digest check. `fetch` is unchanged in behaviour.
  Only the watch calls `download` on its own, because looking at bytes that
  may not be the pinned bytes is its purpose.

## [0.2.0] - 2026-09-01

The first signed tag from `main`. Everything below was on `main` before the tag and described here as unreleased; this section is the same list with a version on it.

### Added

- The second publisher's schedule code and, where the page settles it, its
  title. The line naming a schedule is the one that runs across the sheets,
  wherever the publisher sets it, which is what tells it from a body sentence
  ending in the word "schedule" that matches the same shape on one sheet. The
  title is the neighbouring line that repeats, and only when exactly one of the
  two does; where both repeat, none is read. See ADR 0015. Content lines
  recognized go from 135 to 157 on `pge-b-1`, 43 to 53 on `pge-e-tou-c` and 60
  to 67 on `pge-e-1`.
- A unit the publisher broke across a line ending is now read. The bracket it
  is written in opens on one line and closes on the next, so neither line
  stated a unit and every block under two of the second publisher's sheet
  shapes was refused. Joined only where the publisher's own punctuation says
  it continues, and cited as the span of both lines, since half the unit
  appears on each. See ADR 0014. `pge-e-1` goes from 42 of 247 content lines
  to 60 and from 26 charges to 38; `pge-e-tou-c` from 25 of 346 to 43 and from
  11 charges to 23; `pge-b-1` from 131 of 477 to 135 and from 57 to 59.
- A unit stated over a table now reaches the components of that table. Both
  publishers' unbundling sheets state the unit once and then name each
  component on a line of its own, so the line above each block of rows states
  no unit and every block was refused. The reach is fenced by the indentation
  the page itself sets, and stops at prose, at a heading level with the
  component names, and at a row set further left than the rows above it. See
  ADR 0013. `pge-b-1` goes from 113 of 477 content lines to 131 and from 31
  charges to 57; `pge-e-tou-c` from 18 of 346 to 25 and from 3 charges to 11.
- A test asserting that every cited value appears on the line its citation
  names, across all seven pinned documents, with the one composition in the
  parser named rather than skipped.
- A page that names its columns is now read across them. `sheet_rates.py`
  refused any page setting amounts in more than one column, because a block
  with no column headings cannot say which column its amount belongs to. Where
  the page prints the names over the amounts, it can: the names are read off
  the page the way every other column reading here is, and each price carries
  the column's own name in `applies_to`, cited to the line that names it. See
  ADR 0012. `pge-b-1` goes from 104 of 477 content lines to 113, and from 18
  charges to 31; the four SMUD schedules are byte for byte unchanged.
- On such a page, a cell the publisher marked with a run of dashes is read as
  that column carrying no price for that row, rather than as a reason to refuse
  the row. It still emits nothing itself.
- `coverage --json`, writing the same figures as JSON instead of the text
  report, for a CI step gating one document or a script tracking coverage over
  time. Every value is selected out of `parse`'s own payload rather than
  computed a second time, and `--min-coverage` gates identically either way.
- A test binding the README's "Coverage today" table to the parser: with the
  pinned documents present, every published figure has to be the one the tool
  reports, and every pinned document has to appear in the table. Skips where
  the documents have not been fetched, like the other real-document tests.
- Issue forms and a pull request template, so that what `CONTRIBUTING.md` asks
  for is visible on the screen where someone files a report or opens a change.
  One form for a wrong or uncited value, asking for the four things
  `CONTRIBUTING.md` names; one for a shape the parser does not read, asking
  what on the page settles the reading; and a `config.yml` routing anything
  with a security dimension to `SECURITY.md`. A test asserts the forms are
  ones GitHub can render, that every contact link points at a file that still
  exists, and that no checklist box ships already ticked.
- The billing-proration table on three of the four SMUD schedules, read from
  the table's own ruled border rather than from line order, so a basis cell
  the publisher drew to span more than one circumstance is captured as the
  merge it is. See ADR 0007. Emitted as a new `proration` array in
  `parsed-schedule/v1`; `coverage` reports a `proration rule(s)` count
  alongside charges, windows and holidays.
- `ExtractedTable`/`TableCell` in the extraction layer, and `Page.tables`:
  general support for reading a ruled table's real cell structure, available
  to future recognizers.
- A stable JSON Schema for `parsed-schedule/v1`, published at
  `schemas/parsed-schedule-v1.schema.json`. Validated in the test suite
  against every committed golden file, every synthetic fixture and, when
  present locally, all seven real source documents.
- A new `Condition` record and `conditions` array in `parsed-schedule/v1`, for
  a numbered list of conditions gating a rate option outside any
  Applicability or Eligibility part, such as the Standby Service option's own
  "all of the following conditions are met" list on three SMUD schedules.
  Carries no disposition: see ADR 0009 for why `Applicability`'s scale does
  not fit one item of a conjunction. `coverage` reports a `condition(s)`
  count alongside the rest.
- A recognizer for the commercial transition table on `smud-ci-tod1`, which
  states its unit in a column of its own and dates its prices to a bare year
  carrying a footnote instead of a row or a sheet footer. Columns are read
  from the header's own x positions, the same way every other unruled table
  here is; see ADR 0008. Gains all seven of that document's post-2027 prices.
- `category_code` in `recognizers/base.py`: the rate-category caption reading
  `rate_table.py` already did, made public and shared with the transition
  table recognizer rather than duplicated.
- `change_markers` on the document profile: the single capital letters a
  publisher sets in brackets beside a revised line. A line carrying nothing
  but one such marker, or the literal change bar a whole changed paragraph is
  flagged with, is now read as furniture rather than unrecognised content. A
  marker attached to real text is untouched, since stripping it would edit a
  quotation. `pge-tariff-book` names the six letters observed across its
  three schedules (`R`, `N`, `I`, `D`, `L`, `T`); the default names none. See
  ADR 0010.

### Changed

- The multi-column refusal is now per row rather than per page. A row that does
  not fill every column its table names is refused, because its single price
  may be one column's or the whole row's and the page does not say which; a
  page that names no columns is refused whole, exactly as before. The rows this
  keeps unread are named in ADR 0012.

### Fixed

- A document the parser read nothing out of is no longer reported as fully
  recognized. Zero unrecognized lines out of zero content lines is
  arithmetically a clean sweep, so a scanned sheet with no text layer, a PDF
  whose pages yield no words, or an empty file produced `fully_recognized:
  true` alongside an empty `charges` array and exit 0 — a failed read
  published as a completely understood schedule, which is the one claim this
  parser exists not to make. `fully_recognized` now requires that at least one
  content line was read, and `coverage`'s text report names the failed read
  outright instead of printing a column of zeroes that looks the same as a
  document which is genuinely empty. No published payload key changed, so the
  v1 schema and the golden files are untouched. See ADR 0002.

- `verify-source` and `sources` no longer disagree about one file. The
  listing reads the manifest's pinned length to decide whether a present
  document is the pinned one, and nothing checked that length on the way in,
  so a manifest entry whose `bytes` was wrong and whose `sha256` was right
  made `sources` report `mismatched` while `verify-source` reported `matches
  manifest` for the same bytes. `verify` now checks both pinned facts, which
  also makes `fetch` catch the disagreement when a document arrives instead of
  leaving it to surface later as two commands contradicting each other.

- A credit now takes the applicability window of the sentence above it rather
  than the last such sentence in its section. Where one section stated two
  differently windowed credits, the first was published with the second one's
  hours: a real quote, with real provenance, attached to the wrong charge, so
  the provenance walk could not see it. A credit standing above every such
  sentence, or under one that states a scope with no hours in it, now carries
  no window rather than borrowing one.
- A manifest entry whose filename climbs out of the sources directory, or is
  absolute, is refused instead of resolved. Since `sources` began hashing what
  it finds, such an entry had its contents read to compute a digest that could
  never match.
- `sources` no longer hashes a document whose size already disagrees with the
  manifest. The manifest pins the length as well as the digest, so a file of
  another length is reported `mismatched` without being read. A file of
  exactly the pinned length is still hashed, because that is what a digest is
  for.
- A unit read from a line of its own is now cited to that line rather than to
  the label above it. Thirty nine charges across the three second-publisher
  documents carried a unit citation whose snippet did not contain the unit,
  which a reader had no way to check without finding the page by hand.
- A stray change-bar glyph extracted as a line of its own no longer gets
  swept into a numbered condition item as spurious trailing text; it is
  furniture (see `change_markers` above) and no longer part of any
  recognizer's input.
- `sources` and `verify-source` no longer hang forever on a FIFO, or crash
  with a raw traceback on a directory or a permission-denied file, at a
  manifest entry's filename. Either now reads as `mismatched` — it is not the
  document the parser was audited against, and it is never opened. Also:
  `sha256` is now compared case-insensitively, so a hand-edited manifest
  entry with an uppercase digest no longer reads a byte-identical file as
  `mismatched`.
- `fetch` now actually checks the host's `robots.txt` before downloading a
  document, refusing a path the publisher has disallowed. The README already
  documented this as retrieval's behaviour; the code did not do it — a
  manifest entry pointing at a newly disallowed path would have been fetched
  anyway. A host with no reachable `robots.txt` is still read as allowing
  everything, so this adds no new failure mode for the documents already in
  the manifest.

### Notes

- `v0.1.0` was tagged on 2026-09-01, retroactively, at commit `ba8c9aa`: the last commit on `main` before any of the changes above landed, and the commit at which the `[0.1.0]` section below was written. The section's date is the date its entry was written, not the date of the tag.

## [0.1.0] - 2026-08-18

First release. A command line parser that turns published California
electricity rate schedules into structured data, with provenance on every
emitted value and coverage published as an output rather than claimed. It is
not rate advice and not a bill estimate, and it is not affiliated with,
endorsed by, or approved by SMUD or any other utility.

### Added

- Deterministic parser for published California electricity rate schedules,
  emitting charges, units, applicability conditions, seasonal and time-of-use
  windows, and effective dates.
- Provenance on every emitted value: document id, SHA-256 of the exact bytes,
  page, sheet, section, line and the verbatim snippet. `Cited` cannot be
  constructed without a complete citation, and an independent audit walk fails
  the parse before anything is written if it can reach an uncited value.
- Fail-closed accounting: a line no recognizer understood is reported in
  `unparsed` with its location and reason, and is still carried verbatim in
  `notes`. Coverage is published as an output rather than claimed implicitly.
- Refusal cases, each covered by a test: a priced row whose unit cannot be read,
  an amount that does not sit clearly under one effective-date column, a
  time-of-use window defined by exclusion or carrying an exception, a cell the
  publisher marked `n/a`, and a holiday row with a missing cell.
- Command line interface with `parse`, `coverage`, `sources`, `fetch` and
  `verify-source`. Only `fetch` touches the network.
- Source manifest pinning publisher, URL, retrieval date and SHA-256 for each
  document, with digest verification before parsing.
- Recognizers for the effective-date rate tables, dated charge blocks, per-unit
  credits, time-of-use and holiday tables, cross references to sibling
  schedules, and applicability statements.
- Labelled synthetic fixtures so the suite runs offline without redistributing
  a publisher's document, plus committed golden output for the real schedules.
- Two further published schedules in the manifest, chosen to be unlike the two
  residential sheets the parser was written against: a commercial
  time-of-day schedule with demand charges, three service voltage levels and a
  transition table, and a prose-only solar and storage schedule with no rate
  table at all.
- `applies_to` on a charge, recording the column heading a price sat under
  when one charge is priced across several categories at once.
- `make coverage-real`, reporting parse coverage of every fetched document.
- Three schedules from a second publisher in the manifest, added to find out
  how much of this parser is general. The account of what is general and what
  was one publisher's house style is in ADR 0005. No golden file is committed
  for them: most of each document is still carried verbatim in `notes` and
  committing that would republish the document. Six prices quoted from those
  sheets, with their unit, effective date and block heading, are asserted
  instead, so a change that alters one of them fails rather than passing.
- A per-document **profile**, selected by a `profile` key on a manifest entry
  and carrying only what a document cannot state about itself: whether the
  outline is numbered or a keyword column, whether a negative amount is written
  in accounting brackets, and which word announces a superseded sheet. A
  document naming no profile gets a default in which all three are the refusing
  value, so an unprofiled document is refused rather than guessed at. The
  design and the justification for each field are in ADR 0006. This took the
  second publisher's three schedules from 0% to 15.6%, 4.2% and 20.9%, and left
  the first publisher's four byte for byte unchanged.
- A recognizer for a priced table that dates itself from its sheet rather than
  from its rows: a heading stating a unit in its own parenthesis over a run of
  rows of one label and one amount. It refuses a block with no stated unit, a
  page setting amounts in more than one column, a row that dates itself, a row
  carrying a cell marked with dashes, and a label that does not stop clear of
  the value column.
- Per-sheet effective dates. A publisher that files sheet by sheet gives the
  sheets of one schedule different effective days, so a price is dated from the
  footer of the sheet it is printed on rather than from the document.
- `group` on a charge, recording the heading of the block of rows a price was
  read from. Without it a row labelled "Income Tier 1" would not say which of a
  sheet's several tables it came from.
- `--profile` on `parse` and `coverage`, for a document that is not in the
  manifest. Registered documents take theirs from the manifest.
- A labelled synthetic fixture in a keyword outline with accounting-bracket
  negatives and a supersession header, so the profile is exercised offline in
  CI and the same fixture read with no profile has to refuse all three.

### Fixed

- A dated block pricing several categories on one row no longer folds every
  amount but the last into the effective date. Each amount is assigned to the
  heading above it, and a block whose amounts do not line up one to one with
  its headings is refused outright.
- A charge unit is read to the end of its own label rather than matched against
  a fixed list of unit strings. "per month" is a substring of "per monthly max
  kW", so a demand charge was being quoted as a flat monthly amount.
- A priced table row is no longer read as a time-of-use window. A transition
  schedule of future prices lines up in the same three columns as a window
  table, and one of its rows was emitted as a window whose definition was a
  price.
- "Off-Peak Saver" is no longer labelled "Off-Peak". They are separate periods
  with separate prices.
- The holiday table's columns are read from its own three headings instead of
  fixed coordinates, which found no holidays at all on a sheet whose table sits
  thirty points further right.
- A season's date range is joined to the season name above it whether or not
  the publisher brackets it.
- One section can hold more than one dated block, each with its own label. Every
  dated row in a section was previously filed under the first label above it.
- A resolution footer that names an amending resolution in brackets no longer
  carries the closing bracket into the adopted date.
- A time-of-use window is no longer given a season read off any text that
  happens to sit left of the period column. A second publisher heads that
  column "TIME PERIOD" and two windows were emitted under a season called
  "PERIOD". A season states a part of the year, and a window whose season
  cannot be read is not emitted.
- A sheet number a page announces as cancelled is never cited as that page's
  own. A publisher that prints "Revised Cal. P.U.C. Sheet No. X" above
  "Cancelling Revised Cal. P.U.C. Sheet No. Y" had every citation on the page
  pointing at the withdrawn sheet. Which word announces the supersession now
  comes from the document profile, and with no profile a page asserting two
  sheet numbers records neither.
- A sheet's own banner is no longer read as part of the part continued from the
  sheet before. Under a keyword outline that published a page banner as an
  eligibility statement. How deep the banner runs is read as the shallowest run
  any sheet sets above its first keyword.
- Under a keyword outline a paragraph break is read from the page's own line
  spacing, because the body column carries no hanging indent to mark one.
  Merging the paragraphs gave one coarse eligibility label to a run of text
  where half said who was included and half said who was not.
- A body line low on the page is no longer discarded as a footer. The band says
  where a footer may be and the page's own line spacing says where the body
  ends, so a line set at body spacing is accounted for instead of vanishing
  from both the coverage denominator and the unparsed report.
- A rate table row is refused whole when any cell in its value area is neither
  an amount nor an explicit `n/a`. The row was previously committed with the
  unreadable cell skipped, so a row of three prices could publish two.

### Notes

- The published PDFs are deliberately not redistributed from this repository.
  Only their digests and retrieval details are committed.

[Unreleased]: https://github.com/ChelseaKR/ca-tariff-parse/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ChelseaKR/ca-tariff-parse/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ChelseaKR/ca-tariff-parse/releases/tag/v0.1.0
