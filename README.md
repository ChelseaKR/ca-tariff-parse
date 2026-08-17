# ca-tariff-parse

Turn a published California electricity rate schedule into machine-readable
structured data, with a citation for every single value.

Utility rate schedules are unstructured PDFs. They describe tiered prices,
time-of-use windows, seasonal changes and eligibility conditions in prose and
hand-set tables. Nothing public turns them into data you can compute with. This
does, and it shows its work: every number it emits carries the document, page,
sheet, section and line it was read from.

> **This is not rate advice and it is not a bill estimate.** A parsed schedule
> is a representation of a document, not a calculation of what anyone owes.
> Real bills depend on surcharges, prorations, discounts and other schedules
> this tool does not combine.
>
> **Not affiliated with, endorsed by, or approved by SMUD or any other
> utility.** The publishers listed here have no involvement in this project.

## Quick start

```bash
git clone https://github.com/ChelseaKR/ca-tariff-parse
cd ca-tariff-parse
make install

# Download the published schedules named in sources/sources.toml.
# This is the only command that touches the network.
make fetch

# Parse one, with every value cited.
uv run ca-tariff-parse parse sources/1-R-TOD.pdf --id smud-r-tod -o parsed.json

# See exactly how much of the document was accounted for.
uv run ca-tariff-parse coverage sources/1-R-TOD.pdf --id smud-r-tod
```

No account, no key, no telemetry. Once the source document is on disk,
everything runs offline.

## What comes out

```json
{
  "label":  { "value": "Peak $/kWh" },
  "kind":   "energy_usage",
  "price":  {
    "amount":   { "value": "0.1724" },
    "currency": "USD",
    "unit":     { "value": "$/kWh" }
  },
  "effective_from": { "value": "May 1, 2025" },
  "season":         { "value": "Non-Summer Season (October - May)" },
  "tou_period":     { "value": "Peak" }
}
```

Each of those objects is abbreviated above. In the real output every one of
them also carries a `provenance` block:

```json
"provenance": {
  "document_id":     "smud-r-tod",
  "document_sha256": "9be2f188d4bb39b4bb6436a9a37035457d0e0ab51f769fe995f58ca35422accd",
  "page": 2, "sheet": "R-TOD-2", "section": "II.A", "line": 11,
  "snippet": "Peak $/kWh $0.1724 $0.1776 $0.1829",
  "locator": "smud-r-tod p.2 sheet R-TOD-2 II.A L11"
}
```

## The rule that outranks everything else

**Never invent a rate, a rate structure, a time window, or a citation.**

A tariff parser that emits a plausible looking price nobody published would be
actively harmful, because someone might rely on it. So the design is built
around refusing rather than guessing.

**A value with no citation cannot exist.** `Cited` refuses to construct without
a fully populated `Provenance`, and a separate audit walks the finished result
and fails if it can reach any value not wrapped in one. The two mechanisms are
independent on purpose: the audit still catches a recognizer that bypasses the
model. Nothing is written to disk until the audit passes.

**Where the parser is unsure, it emits nothing.** Concretely, it refuses to
emit:

- a priced row whose unit it cannot read from the label, rather than assuming
  one;
- any row where an amount does not sit clearly under exactly one
  effective-date column, because a price under the wrong date is worse than no
  price;
- a start and end time for a window defined by exclusion ("All other hours"),
  or one carrying an exception ("between noon and midnight except during the
  Peak hours"), because a bare range would misstate the rule. The verbatim
  definition is carried instead;
- a price for a cell the publisher marked `n/a`;
- a holiday row with a missing cell.

**Coverage is a published output, not an implicit claim.** Every parse reports
how many content lines it accounted for, and everything it did not understand
appears in `unparsed` with its location and reason. Nothing is ever silently
dropped: unrecognised text is still carried verbatim in `notes`. A document
containing a section the parser does not understand cannot produce the same
output as one it fully understands, and there is a test that proves it.

## Coverage today

Parsing the two SMUD residential schedules currently accounts for roughly 77%
and 69% of their content lines. The remainder is prose the parser makes no
attempt to structure (standby eligibility conditions, proration rules, critical
peak pricing narrative). It is reported, not hidden.

```
$ uv run ca-tariff-parse coverage sources/1-R-TOD.pdf --id smud-r-tod
content lines   117/151 recognized (77.5%)
sections        16/24 fully recognized (66.7%)
fully recognized False
emitted         42 charge(s), 5 time-of-use window(s), 11 holiday(s), 6 cross reference(s)

unparsed:
  II.C       p.2 L35 to p.3 L5 (7) 7 of 8 lines in a recognized section matched no rule
      | 1. The CPP Rate base prices per time-of-day period are the same ...
```

## Source documents

The published PDFs are **not redistributed from this repository**. What is
committed is `sources/sources.toml`: the publisher, URL, retrieval date and
SHA-256 of the exact bytes that were read. `make fetch` downloads them and
`make verify-source` confirms you hold the same bytes the parser was run
against. If a publisher revises a schedule at the same URL the digest stops
matching, which is a signal to review the change deliberately rather than to
relax the check.

`sources/sources.toml` records where a document came from. It is not a claim of
permission, endorsement, or any relationship with the publisher.

Retrieval honours `robots.txt` and is a handful of requests, never a crawl.

## Commands

| Command | What it does |
| --- | --- |
| `parse <doc>` | Emit the structured schedule as JSON |
| `coverage <doc>` | Report what was accounted for and what was not |
| `sources` | List the documents in the manifest |
| `fetch` | Download source documents (the only networked command) |
| `verify-source` | Check local documents against the manifest digests |

`parse` and `coverage` accept `--id <manifest-id>`, which verifies the file
against the pinned digest before parsing and records the publisher and
retrieval date in the output. They also accept `--min-coverage`, which exits
non-zero when too little of the document was understood.

## How it works

1. **Extract.** `pdfplumber` gives the position of every word. Positions are
   kept, because which price belongs to which effective date is carried
   entirely by horizontal alignment.
2. **Segment.** Lines are grouped into the document's own numbered outline
   (roman parts, lettered subsections), so every value can cite a section and
   an unrecognised part can be named rather than lost.
3. **Recognize.** Small independent recognizers each claim a section shape and
   report exactly which lines they consumed.
4. **Account.** Any line no recognizer consumed becomes an `unparsed` entry and
   a verbatim note.
5. **Audit.** The provenance walk runs before anything is written.

Tests run against a clearly labelled synthetic fixture, so the suite works
offline and without redistributing a publisher's document. The golden output of
the real schedules is committed under `tests/golden/`, so a parser change that
would alter a published price shows up as a reviewable diff.

## Standards Conformance

| Standard | State |
| --- | --- |
| Responsible-Tech Framework | Applies: the no-fabrication rule, the refusal cases and the published coverage figure are the core design. |
| Code Quality | Applies: ruff, strict mypy, complexity ceiling, 85% coverage floor. |
| Security & Supply-Chain | Applies: SHA-pinned actions, least-privilege tokens, secret scanning, SAST, dependency scanning, lockfile. |
| CI/CD | Applies: `make verify` is the gate and CI runs the same target. |
| Release & Versioning | Applies: SemVer with a signed-tag release workflow that separates verification from publication. |
| Observability | Applies: Tier C (library and CLI). No hosted route, so tracing is out of scope for that tier; the tool emits no telemetry by design. |
| Performance | N/A: no hosted route and no shipped HTML. Parsing one local document has no latency budget to gate on. |
| Accessibility | N/A: no user interface. The surfaces are a JSON document and plain terminal text. |
| Internationalization | N/A: parses English-language tariff documents and ships no user-facing message catalog. See `docs/I18N.md`. |
| AI Evaluation | N/A: no model and no inference. Parsing is deterministic rule matching over document geometry. |
| Documentation | Applies: this README, the ADR log, and module docstrings that state why a refusal exists. |
| Quality & Metrics | Applies: coverage floor and complexity ceiling enforced in CI. |
| AI Development Measurement | Applies: built with agentic assistance; no repository-local metrics ledger yet. |
| Incident Response | Applies: `SECURITY.md` carries the reporting path. A data-exposure or secret-leak defect is in scope even though nothing is deployed. |
| Data Governance | Applies: L1 public non-sensitive. Ingests published tariff documents only, records lineage in `sources/sources.toml`, and handles no personal data. |

## Development

```bash
make verify   # install, lint, typecheck, test with the coverage floor
make fmt      # apply formatting and safe fixes
make golden   # regenerate golden output (review every changed price)
```

## Licence

Apache-2.0. See `LICENSE`.

Licensing the code says nothing about the source documents. Rate schedules
remain the work of their publishers, which is one reason they are fetched
rather than vendored.
