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

- Recognizers for the prose sections currently reported as unparsed: standby
  eligibility conditions, proration rules, and critical peak pricing terms.
- Additional publishers beyond the two SMUD residential schedules.
- A stable JSON Schema published alongside the `parsed-schedule/v1` output.

Coverage figures move only when a recognizer genuinely understands more of a
document. Widening a rule to raise the number is a defect, not progress.
