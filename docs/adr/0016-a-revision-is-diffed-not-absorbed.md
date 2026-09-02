# 0016. A revision is diffed, not absorbed

- Status: Accepted
- Date: 2026-09-01

## Context

ADR 0003 pins each source document by digest and says what a mismatch means:
"a revision is reviewed deliberately, and the manifest and golden files are
updated together." That is the right rule and it has a cost. The review begins
with a person noticing that `verify-source` fails, fetching the new bytes,
parsing them, and working out by eye what the publisher changed. Nothing did
the noticing, and nothing did the working out. A publisher who revises a
schedule in a month nobody ran `make fetch` revised it silently.

Two things made a mechanical first half of that review possible and one thing
stood in its way.

Possible, because `parse` already emits every value with the page, sheet,
section and line it was read from, so two parses of one document can be
compared value by value and each difference can point at both readings. And
because the manifest already pins the digest, so "the publisher serves
different bytes" is a fact the tool can establish without judgement.

In the way: what to compare a revision *against*. The obvious answer is the
last parse of the pinned bytes. For the four SMUD schedules that already sits
under `tests/golden/`. For the three PG&E schedules no golden file is
committed, and the reason is recorded in the Makefile: most of each of those
documents is still carried verbatim in `notes`, and committing that would
republish a document this repository deliberately does not redistribute.

## Decision

**The watch compares against a baseline, and a baseline is a projection.**
`data/parsed/<id>.json` is `parse`'s payload with two things removed: `notes`,
and the `sample` lines under each `unparsed` section. Those are the two places
a document's own prose travels verbatim in bulk; everything else in the payload
is a cited value, which ADR 0003 already names as this project's deliverable
rather than the publisher's. The projection names itself
(`ca-tariff-parse/watch-baseline/v1`) so it cannot be mistaken for a full
parse, and carries an `omitted` field saying what is missing and why, so the
absence is a statement rather than a gap. The `baseline` command writes one
only from bytes that match the manifest.

**The diff matches values by identity, not position.** A charge is the same
charge across two parses when its kind, label, rate category, season,
time-of-use period, applicability, group, effective date and unit agree; what
is compared is its amount. A window is identified by its season, period and
day type; a holiday by its name; a proration rule by its circumstance; a
condition by its subject; a cross reference by its target; an applicability
paragraph by its text; an identity field by its name. Where a document states
one identity more than once, each occurrence is its own record in document
order, so a second statement appearing later is an addition and not a
collision. A value whose citation moved and whose value did not is not a
change, because a row inserted above it moves every line below and changes
nothing the reader cares about.

**Every reported change cites both sides.** A changed value carries the
provenance it was read from in the old bytes and in the new. An added or
removed record carries the one citation it has. The report is a table of
citations with values beside them, and its own footer says to check the
citation rather than the table.

**A diff across parser versions says so first.** The baseline records the
parser that wrote it. When the current parser is not that one, the report
opens by saying that some of its lines may be parser changes rather than
publisher changes, and the pull request's checklist repeats it. The tool
cannot tell the two apart from the payloads and does not pretend to.

**The manifest is proposed, never rewritten.** The watch substitutes the four
pinned facts of one entry — digest, retrieval date, page count, byte size —
in place, inside the one `[[document]]` block that names the entry, each
exactly once, and refuses if it cannot. The comments explaining each publisher
survive because nothing re-serialises the file. The result travels in a pull
request with the report and the new baseline; merging it is the review ADR
0003 asks for, and a person does it.

**`download` is split out of `fetch`.** The watch's purpose is to look at
bytes that may not be the pinned bytes, which is exactly what `fetch` refuses.
Rather than give `fetch` a flag that relaxes its check, the network half is
its own function and `fetch` composes it with `verify`. Nothing else calls
`download`.

**A failure to look is an error.** A download that fails, a baseline that is
missing, or a revision that cannot be parsed is reported as an error and fails
the run. "Unchanged" is reserved for the case where the tool downloaded the
bytes and they were the pinned bytes.

## What this does not do

- It does not accept a revision. The pinned digest changes only when a person
  merges the proposal.
- It does not commit a PDF, in the pull request or anywhere else.
- It does not widen any recognizer. A revision the parser reads less of than
  the pinned bytes shows up as removals, with coverage before and after in the
  report's header, and that is the honest description of what happened.
- It does not decide whether a maintained feed of these reports belongs
  anywhere but in this repository. That is a separate decision with its own
  gates, and the roadmap lists it under what is not in the plan.

## Consequences

- `data/parsed/` is about a megabyte of committed JSON and grows with the
  manifest. A `realdoc` test fails when a committed baseline is not byte for
  byte what the current parser writes, so a parser change that alters a
  published value has to regenerate the baselines in the same change, the way
  it already has to regenerate `tests/golden/`.
- A pull request from the watch is a review obligation. The checklist on it
  says what to check: every line against the publisher's document, the
  README's coverage table, and the parser-version caveat when it applies.
- `tests/golden/` and `data/parsed/` now both describe the SMUD documents,
  one in full and one projected. They serve different purposes and are
  regenerated by different targets; neither replaces the other.
