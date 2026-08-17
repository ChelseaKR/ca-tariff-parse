# 0001. Every emitted value carries provenance

- Status: Accepted
- Date: 2026-08-17

## Context

The purpose of this project is to make tariff documents computable. That is
only useful if a consumer can check any number against the document it came
from. A structured price with no traceable origin is worse than no price: it
looks authoritative, it is easy to copy, and it cannot be verified without
redoing the work by hand.

Rate schedules are also revised in place. A citation that names a document but
not its exact bytes can silently come to point at a different revision.

## Decision

No value reaches the output without a complete citation, enforced twice by two
unrelated mechanisms.

1. `Cited` is the only container a scalar travels in. Its `provenance` field
   has no default and no `None` path, and `Provenance` validates every field on
   construction: a non-empty document id, a 64 character lowercase SHA-256, a
   1-based page and line, a well formed section id, and a non-empty verbatim
   snippet. A value without a citation cannot be built.
2. `audit.assert_fully_cited` walks the serialised result and fails if it can
   reach any scalar that is not inside a `Cited` envelope. The small set of
   structural fields it tolerates (`kind`, `currency`, `disposition`,
   `residual`) is restricted to closed vocabularies that the walk also checks.

The audit runs inside `parse_document`, before anything is returned or written.

Provenance pins `document_sha256`, so a citation identifies exact bytes rather
than a URL whose contents may have changed.

## Consequences

- The output is verbose. A single price carries a citation block larger than
  itself. This is accepted: verifiability is the product.
- Belt and braces is deliberate. The audit is redundant with the type today,
  and that redundancy is the point: it still catches a future recognizer that
  bypasses the model, or a new dataclass field that nobody wrapped.
- Adding a field to the output means deciding whether it is evidence, which
  must be cited, or structure, which must join a closed vocabulary. There is no
  third option, and that friction is intentional.
- Amounts are carried as strings, not floats, so an exact printed decimal is
  not silently altered by binary floating point before anyone sees it.
