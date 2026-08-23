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

The full shape is published as a JSON Schema at
[`schemas/parsed-schedule-v1.schema.json`](schemas/parsed-schedule-v1.schema.json),
so a downstream consumer can validate against the shape rather than against
this document's prose description of it. `tests/test_schema.py` validates
every committed golden file and every synthetic fixture's output against it,
and, when the real source documents are present locally, all seven of those
too, so the schema and the code that emits `parse`'s output cannot drift
apart unnoticed.

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
parses completely, and the figure for each is an output of the tool rather than
a claim made here.

| Schedule | Publisher | Lines recognized | Charges | Windows | Holidays | Proration rules |
| --- | --- | --- | --- | --- | --- | --- |
| R-TOD, residential time-of-day | SMUD | 119/151 (78.8%) | 42 | 5 | 11 | 1 |
| R, residential | SMUD | 88/115 (76.5%) | 30 | 0 | 0 | 3 |
| CI-TOD1, commercial and industrial time-of-day | SMUD | 137/201 (68.2%) | 85 | 5 | 11 | 3 |
| SSR, solar and storage | SMUD | 49/76 (64.5%) | 0 | 0 | 0 | 0 |
| E-1, residential | PG&E | 42/269 (15.6%) | 26 | 0 | 0 | 0 |
| E-TOU-C, residential time-of-use | PG&E | 18/425 (4.2%) | 3 | 0 | 0 | 0 |
| B-1, small general service | PG&E | 106/507 (20.9%) | 18 | 0 | 0 | 0 |

`make coverage-real` reproduces the table from the fetched documents.

### The document profile

The three PG&E figures were 0% until a **document profile** was added. A
profile is selected per manifest entry and carries only what a document cannot
state about itself. There are three fields, and a document naming no profile
gets a default in which all three are the refusing value.

| Field | Why the document cannot say it |
| --- | --- |
| `outline` | A numbered outline announces itself: `I.` over `A.` is a part and a subsection whatever the document is about. A keyword outline announces nothing. A word set in a column of its own with text beside it is a heading in one house style, a table's first column in another, and a wide margin with a hanging indent in a third, and the page looks the same in all three. This parser meets the other two inside the first publisher's own tables. |
| `bracket_negative_amounts` | `($0.08140)` is a negative to a publisher who uses accounting brackets. Reading it as positive publishes a charge where a credit was published; refusing it withholds a real price. The page offers no third reading, so the parser has to be told before it can do either. |
| `supersession_word` | A sheet prints its own number over the number it replaces, and which one is withdrawn is carried by a filing word rather than by anything structural on the page. |

Nothing else is in it, and in particular no coordinate. ADR 0005 expected the
profile to state the width of the keyword column; across three schedules that
column starts anywhere from 72 to 101 points and the body beside it anywhere
from 133 to 172, so a single number cannot separate them and the column is read
from the page instead.

What that bought, and what it did not, is in
[ADR 0006](docs/adr/0006-the-document-profile-holds-three-things.md). The short
version is that the outline is worth most of the coverage, the bracket notation
is worth the prices that would otherwise have been refused or reversed, and the
new prices are dated sheet by sheet, because these sheets are filed one at a
time and the sheets of one schedule take effect on different days.

Coverage of the four SMUD schedules did not move and their golden output is
byte for byte unchanged. That is the test that this is a seam rather than a
second branch: the first publisher takes the default for all three fields.

### The proration table

Three of the four SMUD schedules carry a small table pairing a billing
circumstance ("Bill period is shorter than 27 days") with the basis on which
a charge is prorated under it. Reading it in line order does not work: the
"Basis for Proration" cell is sometimes one row tall and sometimes drawn to
span two or three circumstances at once, and text extracted in reading order
cannot tell those apart. Two circumstances that share one basis print as one
paragraph starting a line late, which looks exactly like an unrelated basis
misattributed to the wrong circumstance.

The two cases are told apart by going around the text entirely: `pdfplumber`
reports the ruled lines a table's own cells are drawn with, and a cell whose
border spans two rows *is* a merge, not a guess about one. Reading that
border directly, rather than inferring row breaks from spacing, is what lets
`Bill period is shorter than 27 days` and `Bill period is longer than 34
days` share one basis while a third circumstance keeps its own — exactly what
the published page shows, and unrelated to how any of the three sentences
happens to wrap. A circumstance whose cell does not sit inside exactly one
basis cell's border is left unparsed rather than paired at a guess.

Only a table with a real ruled border is read this way. A schedule with no
such table, or one under a different header, is untouched by this and keeps
being read line by line as before. The full account, including the case that
originally looked like it needed a spacing threshold and did not, is in
[ADR 0007](docs/adr/0007-read-a-merged-cell-from-its-own-border.md).

### The commercial transition table

CI-TOD1 prices commercial rates through 2027 in its main tables, each of
those dated by an "Effective as of" column the way every other SMUD table
here is. Rates for 2028 and beyond are filed separately, in a small table
that dates its one price column with nothing but the year itself and a
footnote mark:

```
Season and Charge Component                  Unit       2028*
CITS-0: C&I Secondary 0-20 kW
    System Infrastructure Fixed Charge        per month  $44.45
    Maximum Demand Charge                     per kW     $4.101
    Non-Summer Peak                           per kWh    $0.1506
*Subject to future rate increases.
```

Two things distinguish it from the main tables. The unit is not stated once
for the block, the way `sheet_rates.py` reads it, nor in its own aligned
column despite the "Unit" heading, the way the table's own layout might
suggest: it is read the same way `rate_table.py` already reads every other
priced row here, as the tail of the row's own label. And the season and
time-of-use period are not split onto a heading row above the block; a row
reads "Non-Summer Peak", so both are read out of that one label instead.

The header is claimed by requiring both a literal "Unit" and a bare year
(with an optional footnote mark) at the end of the same line, which is
specific enough that nothing else in any of the seven schedules here matches
it. The footnote's asterisk does not reach `effective_from`: the date is
`"2028"`, and the footnote's own sentence is left where it was, to be carried
verbatim like any other unrecognised line.

### What is still refused on the second publisher

Most of it, and each refusal is a case where a value could otherwise be wrong.

- **A page that sets amounts in more than one column.** A row carrying one
  amount in a two column table has to say which column it sits in, and a block
  that states no columns cannot. This is why the commercial schedule's own rate
  sheets contribute nothing at all: they price two rate options side by side.
- **A block whose heading states no unit**, because a number with no unit says
  nothing about what it prices.
- **A row carrying a cell the publisher marked with dashes**, which prices a
  column the block does not name.
- **The identity fields, the cross-reference wording and the credit form.**
  Each is a statement about how one publisher writes, not a thing a document
  cannot state about itself, so none of them belongs in a profile. Closing them
  means finding the shape, not adding a field.

### What a second publisher cost

Two of the three PG&E schedules once emitted no value at all, and the third
emitted two time-of-use windows under a season the publisher never wrote. The
full account of that first pass is in
[ADR 0005](docs/adr/0005-a-second-publisher-needs-a-document-profile.md). What
turned out to be general was the machinery that made the failure legible rather
than dangerous: the positional layout model, the citation and audit rules, the
coverage accounting, and above all the refusals. A rate table whose shape is
not recognised produces nothing rather than something plausible.

What is left unaccounted for on the four SMUD schedules is largely genuine
narrative: critical peak pricing terms, service voltage definitions, metering
conditions. One specific thing is structured and still refused, on purpose:

- **A price stated inside a sentence.** SSR gives its export compensation rate
  as "The Export Compensation Rate effective June 1, 2026 will be $0.0960 per
  kWh". Reading a price out of prose means deciding by guesswork what the price
  is for, so SSR emits no charges at all rather than one.

```
$ uv run ca-tariff-parse coverage sources/CI-TOD1.pdf --id smud-ci-tod1
content lines   137/201 recognized (68.2%)
sections        15/29 fully recognized (51.7%)
fully recognized False
emitted         85 charge(s), 5 time-of-use window(s), 11 holiday(s), 5 cross reference(s), 3 proration rule(s)

unparsed:
  II.A       p.2 lines 36-36 (1) 1 of 33 lines in a recognized section matched no rule
      | Commercial rates beyond 2027 are effective as shown in Section VIII. Transition Schedule.
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
against the pinned digest before parsing, records the publisher and retrieval
date in the output, and reads the document with the profile its manifest entry
names. They also accept `--min-coverage`, which exits non-zero when too little
of the document was understood, and `--profile`, which names a document profile
for a file that is not in the manifest.

## How it works

1. **Extract.** `pdfplumber` gives the position of every word. Positions are
   kept, because which price belongs to which effective date is carried
   entirely by horizontal alignment. Where a table has a ruled border,
   `pdfplumber`'s own line-drawing detection is read too, so a cell a
   publisher drew to span several rows is captured as the single merged cell
   it is rather than guessed at from spacing.
2. **Segment.** Lines are grouped into the document's own outline, so every
   value can cite a part and an unrecognised part can be named rather than
   lost. Two outlines are known: statute-style numbering (roman parts, lettered
   subsections) and a keyword set in a column with the body beside it. Which
   one a document uses comes from its profile, because the page does not say.
3. **Recognize.** Small independent recognizers each claim a section shape and
   report exactly which lines they consumed.
4. **Account.** Any line no recognizer consumed becomes an `unparsed` entry and
   a verbatim note.
5. **Audit.** The provenance walk runs before anything is written.

Tests run against clearly labelled synthetic fixtures, so the suite works
offline and without redistributing a publisher's document. One fixture is
written in a keyword outline with accounting-bracket negatives and a
supersession header, so the profile is exercised in CI too, and parsing it
without a profile has to refuse all three.

The golden output of the four SMUD schedules is committed under
`tests/golden/`, so a parser change that would alter a published price shows up
as a reviewable diff. No golden file is committed for the three PG&E schedules:
most of each document is still carried verbatim in `notes`, and committing that
would republish it. Those three are covered instead by a spot check of six
prices quoted from the sheets with their unit, effective date and heading.

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
