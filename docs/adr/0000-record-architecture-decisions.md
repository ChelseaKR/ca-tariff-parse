# 0000. Record architecture decisions

- Status: Accepted
- Date: 2026-08-17

## Context

This project makes claims about published prices. When a decision here is
wrong, the failure mode is a plausible looking number that nobody published,
which somebody might then rely on. Reconstructing why a parser chose to emit or
refuse a value, months later and from the code alone, is exactly the kind of
archaeology that leads to a reviewer quietly relaxing a check they do not
understand.

## Decision

Architecturally significant decisions are recorded as numbered files in
`docs/adr/`, in the style described by Michael Nygard.

A decision is significant here if it affects what the parser will or will not
emit, how a value is justified, or what the project redistributes. Formatting
preferences and library choices with no bearing on output correctness do not
need a record.

Each ADR states its status (Proposed, Accepted, Superseded), the context, the
decision, and the consequences including the ones we dislike. Records are
immutable once accepted: a change of mind is a new ADR that supersedes the old
one, never an edit to it.

## Consequences

- The reasoning behind a refusal is available to a future reviewer who is
  tempted to remove it.
- Superseded records stay in the log, so the history of a reversal is visible.
- Every substantive pull request carries the small cost of asking whether it
  needs a record.
