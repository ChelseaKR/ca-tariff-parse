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
- a time-of-use window whose definition holds a currency amount, because that
  is a price sitting in the same column, not a statement of when a period runs;
- a price for a cell the publisher marked `n/a`;
- a holiday row with a missing cell, or a whole holiday table whose header does
  not divide into three headings;
- a dated block pricing several categories at once whose amounts do not line up
  one for one with the headings above them.

**Coverage is a published output, not an implicit claim.** Every parse reports
how many content lines it accounted for, and everything it did not understand
appears in `unparsed` with its location and reason. Nothing is ever silently
dropped: unrecognised text is still carried verbatim in `notes`. A document
containing a section the parser does not understand cannot produce the same
output as one it fully understands, and there is a test that proves it.

## Coverage today

Seven published schedules from two publishers are in the manifest. None of them
parses completely, three of them do not parse at all, and the figure for each
is an output of the tool rather than a claim made here.

| Schedule | Publisher | Lines recognized | Charges | Windows | Holidays |
| --- | --- | --- | --- | --- | --- |
| R-TOD, residential time-of-day | SMUD | 117/151 (77.5%) | 42 | 5 | 11 |
| R, residential | SMUD | 79/115 (68.7%) | 30 | 0 | 0 |
| CI-TOD1, commercial and industrial time-of-day | SMUD | 121/201 (60.2%) | 78 | 5 | 11 |
| SSR, solar and storage | SMUD | 49/76 (64.5%) | 0 | 0 | 0 |
| E-1, residential | PG&E | 0/269 (0.0%) | 0 | 0 | 0 |
| E-TOU-C, residential time-of-use | PG&E | 0/425 (0.0%) | 0 | 0 | 0 |
| B-1, small general service | PG&E | 0/507 (0.0%) | 0 | 0 | 0 |

`make coverage-real` reproduces the table from the fetched documents.

### What a second publisher cost

The three zeroes are the honest result of asking whether this parser
generalises. It does not. The full account is in
[ADR 0005](docs/adr/0005-a-second-publisher-needs-a-document-profile.md); the
short version is that three quarters of the collapse is one assumption. This
parser recovers a document's outline from statute-style numbering, roman
numerals over capital letters, and cites every value to the part it came from.
The second publisher has no numbered outline: it sets a keyword in a narrow
left-hand column with the text beside it, so a line reads `APPLICABILITY: This
schedule is applicable to ...`. With no outline the whole document lands in one
section and no recognizer has anything to key on.

What turned out to be general is the machinery that made the failure legible
rather than dangerous: the positional layout model, the citation and audit
rules, the coverage accounting, and above all the refusals. Even before the
fixes below, two of the three documents emitted not one value: a rate table
whose shape is not recognised produces nothing rather than something plausible.
What turned out to be specific to the first
publisher is every recognizer's claim: the rate table keys on the literal words
`Effective as of`, the identity reader on `Rate Schedule <code>` and a
resolution number, cross references on `Refer to Rate Schedule X`. A second
publisher writes all of those differently and gets nothing.

One thing did produce output, and it was wrong: two time-of-use windows under a
season called `PERIOD`, which is the window table's own column heading and not
a season at all. That, a citation naming a sheet the publisher had cancelled,
and a body line silently swallowed by a fixed footer band are fixed here,
because each is wrong for any publisher. The publisher-specific gaps are left
open on purpose. Closing them with a second branch beside the first is how a
parser becomes a pile of special cases, so ADR 0005 designs a per-document
profile instead and does not implement it against a single second example.

Coverage of the four SMUD schedules did not move and their golden output is
byte for byte unchanged.

What is left unaccounted for on those four is largely genuine narrative:
proration wording, critical peak pricing terms, service voltage definitions,
metering conditions. Three specific things are structured and still refused, on
purpose:

- **A price stated inside a sentence.** SSR gives its export compensation rate
  as "The Export Compensation Rate effective June 1, 2026 will be $0.0960 per
  kWh". Reading a price out of prose means deciding by guesswork what the price
  is for, so SSR emits no charges at all rather than one.
- **The proration table**, on three of the four documents. Its second column is
  a merged cell whose text interleaves with the rows beside it, so pairing a
  circumstance with a basis line by line attaches the wrong rule to the wrong
  circumstance.
- **The commercial transition table**, which states its unit in a column of its
  own and dates its prices to a bare year with a footnote. Both are unlike
  every other priced table here, and neither is read yet.

```
$ uv run ca-tariff-parse coverage sources/CI-TOD1.pdf --id smud-ci-tod1
content lines   121/201 recognized (60.2%)
sections        15/29 fully recognized (51.7%)
fully recognized False
emitted         78 charge(s), 5 time-of-use window(s), 11 holiday(s), 5 cross reference(s)

unparsed:
  VIII       p.7 L4 to p.8 L1 (12) 12 of 13 lines in a recognized section matched no rule
      | Season and Charge Component Unit 2028*
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
`robots.txt` for a host is read before anything is fetched from it, and a
publisher that disallows the path is not fetched from at all.

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
the four schedules that parse is committed under `tests/golden/`, so a parser
change that would alter a published price shows up as a reviewable diff. No
golden file is committed for the three that parse at 0%: nothing is recognized,
so the whole document text would sit in `notes` and committing that would
republish the document. Those three are covered by tests asserting the refusal
instead.

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
make verify        # install, lint, typecheck, test with the coverage floor
make fmt           # apply formatting and safe fixes
make golden        # regenerate golden output (review every changed price)
make coverage-real # report parse coverage of every fetched document
```

## Licence

Apache-2.0. See `LICENSE`.

Licensing the code says nothing about the source documents. Rate schedules
remain the work of their publishers, which is one reason they are fetched
rather than vendored.
