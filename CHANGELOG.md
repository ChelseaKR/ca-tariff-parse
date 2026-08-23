# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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

### Fixed

- A stray change-bar glyph extracted as a line of its own no longer gets
  swept into a numbered condition item as spurious trailing text; it is
  furniture (see `change_markers` above) and no longer part of any
  recognizer's input.

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

[Unreleased]: https://github.com/ChelseaKR/ca-tariff-parse/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ChelseaKR/ca-tariff-parse/releases/tag/v0.1.0
