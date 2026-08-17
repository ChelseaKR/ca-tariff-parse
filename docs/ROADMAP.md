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
- **Publishers other than SMUD.** Four schedules from one publisher have
  already shown that the same publisher sets the same table in different
  places; a second publisher will find more.
- A stable JSON Schema published alongside the `parsed-schedule/v1` output.

Coverage figures move only when a recognizer genuinely understands more of a
document. Widening a rule to raise the number is a defect, not progress.
