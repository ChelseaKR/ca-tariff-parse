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

### Notes

- The published PDFs are deliberately not redistributed from this repository.
  Only their digests and retrieval details are committed.

[Unreleased]: https://github.com/ChelseaKR/ca-tariff-parse/commits/main
