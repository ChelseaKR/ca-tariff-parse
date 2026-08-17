# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  how much of this parser is general. They parse at 0%, that figure is
  published in the README beside the four that parse, and the account of what
  is general and what was one publisher's house style is in ADR 0005. No golden
  file is committed for them: nothing is recognized, so the whole document text
  would sit in `notes` and committing that would republish the document.

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
  pointing at the withdrawn sheet.
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

[Unreleased]: https://github.com/ChelseaKR/ca-tariff-parse/commits/main
