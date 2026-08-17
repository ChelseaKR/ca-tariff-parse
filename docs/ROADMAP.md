# Roadmap

## Observability

Tier: C (library and CLI).

This is a local command line tool with no hosted route, no background service
and no user session. Distributed tracing is documented out of scope for this
tier. The tool emits no telemetry of any kind and makes no network request
except in the explicit `fetch` command.

The operator-facing signal is the `coverage` command, which reports what the
parser accounted for and what it did not.

## Planned

Named in rough order of how much of the remaining unparsed content each would
account for, and why each is still refused today.

- **The proration table**, on three of the four documents. Its second column is
  a merged cell whose lines interleave with the rows beside it, so a line by
  line pairing attaches the wrong basis to the wrong circumstance. Needs the
  merged cell recovered before anything is emitted.
- **The commercial transition table**, which puts the unit in a column of its
  own rather than in the label, and dates its prices to a bare year carrying a
  footnote. Both differ from every priced table the parser reads today.
- **Enumerated condition lists** outside an Applicability or Eligibility
  heading, such as the standby service conditions. Carried verbatim in `notes`
  today but not structured.
- **A price stated inside a sentence**, as the solar and storage schedule
  states its export compensation rate. Refused because deciding what such a
  price is for is guesswork, and a wrong answer here is a fabricated tariff
  value. Any attempt needs a rule narrow enough to refuse far more often than
  it accepts.
- **A document profile, so a second publisher can be read at all.** Three
  schedules from a second publisher are in the manifest and parse at 0%. The
  reason and the shape of the fix are in
  [ADR 0005](adr/0005-a-second-publisher-needs-a-document-profile.md): a
  profile selected per manifest entry, stating only what a document cannot
  state about itself, namely how its outline is written, how an amount is
  written, and which page furniture announces a supersession. Recognizers keep
  reading geometry from the document. This is the largest single item here and
  it should not be attempted against one further publisher, because fitting it
  to one example is the mistake it exists to avoid.
- **An amount written in accounting brackets**, as `($0.08140)` for a negative.
  Read as not a number today, so a row carrying one is refused whole. Whether
  brackets mean a negative is a publisher's convention, so it belongs in the
  profile rather than in the amount pattern.
- **Filing change markers**, the `(R)`, `(N)`, `(I)` and `(D)` a regulated
  publisher sets beside a revised line, and the change bars in its right
  margin. They are carried verbatim inside cited text today, because stripping
  them would edit a quotation. Recognising them as furniture rather than
  content is a profile question too.
- A stable JSON Schema published alongside the `parsed-schedule/v1` output.

Coverage figures move only when a recognizer genuinely understands more of a
document. Widening a rule to raise the number is a defect, not progress.
