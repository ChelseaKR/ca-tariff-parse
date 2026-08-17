# 0003. Pin source documents by digest rather than redistribute them

- Status: Accepted
- Date: 2026-08-17

## Context

The parser needs real published PDFs. Committing them would make the test suite
self-contained. But those documents are the work of their publishers, this
repository has no permission to republish them, and vendoring a utility's
document alongside a tool that parses it invites the reading that the two are
connected. A stale committed copy also quietly becomes wrong when the publisher
issues a revision.

## Decision

Source PDFs are not committed. `sources/sources.toml` records, for each
document: publisher, URL, retrieval date, page count, byte size and SHA-256.

- `ca-tariff-parse fetch` downloads them. It is the only command that makes a
  network request.
- `ca-tariff-parse verify-source`, and `--id` on `parse`, check a local file
  against the pinned digest and refuse to proceed on a mismatch.
- Tests needing a real document are marked `realdoc` and skip when it is
  absent, so the suite passes offline.
- The structured output of parsing the real documents is committed under
  `tests/golden/`. Facts read out of a public tariff, each carrying its
  citation, are the deliverable of this project rather than a copy of the
  publisher's document.

## Consequences

- CI exercises the full parser through labelled synthetic fixtures. The
  real-document path is covered locally and by the committed golden files, and
  is skipped rather than silently passed when the PDFs are absent.
- A publisher revision breaks the digest check rather than being absorbed. That
  is the intended behaviour: a revision is reviewed deliberately, and the
  manifest and golden files are updated together.
- Contributors must run `make fetch` before `make golden`.
- The repository stays small and carries no third-party binaries.
