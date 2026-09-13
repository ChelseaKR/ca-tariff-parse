# 0019. A look is recorded even when nothing moved

- Status: Accepted
- Date: 2026-09-13

## Context

`tariff-watch.yml` has run twice: a `workflow_dispatch` on 2026-09-02 and one
scheduled run on 2026-09-07 (runs `33597504100` and `34133314317`). Both
succeeded. Both looked at all seven pinned documents and found every one of
them serving the pinned bytes. Neither opened a pull request, because there was
nothing to propose, and `data/changes/` has never existed in this tree or in
its history.

That is the schedule working exactly as designed, and it was nevertheless
reported outside this repository as "weekly tariff-watch PRs running". The
report was wrong and the repository gave it no way to be right, because **a
repository whose publishers revised nothing is byte for byte a repository whose
watch has never run.** Both carry seven baselines, no change reports, and no
other trace at all.

Three faults would produce that same silence and they are not equally bad:

1. the schedule is not firing;
2. it is firing and genuinely finding nothing;
3. it is finding changes and failing to open a pull request.

The third is the serious one — it would mean tariff revisions were being
detected and silently dropped — and the repository could not tell a reader
which of the three it was in. Only the workflow run log could, and a run log is
off-repository, expires, and says nothing at all once it has aged out.

This is the project's own defining defect wearing the opposite coat. Everywhere
else the parser refuses to publish an absence as a value: a suppressed cell is
not zero, a residual window is not a window with no hours, `smud-ssr` reports
five properties as `cannot be established` rather than five passes. Here the
tool was publishing **an absence of evidence as evidence of absence** — silence
read as "nothing has changed" when it equally meant "nothing has looked".

## Decision

**Every run of the watch appends one line to `data/watch-log.jsonl`, and the
workflow commits it to `main`, whether or not anything moved.**

The record is a JSON line per run
(`ca-tariff-parse/watch-observation/v1`) naming the date, the parser version,
and every document the run examined with the state it was found in —
`unchanged`, `changed` or `error` — and the detail the run printed. It is
appended, never rewritten: an earlier line is evidence that a look happened and
nothing here is entitled to restate it.

Four consequences follow from that being a *record of looks* rather than a
summary:

- **Every document is named in its own right.** A run that examined six of
  seven documents cannot read as a run that examined all seven.
- **"Never looked" is not a count of zero.** `looks_at` returns a `Look` whose
  `last_state` is the string `never looked` where the log names no such
  document, and whose sentence says in terms that the absence of a change
  report is not evidence the document has not changed.
- **A failure to look is recorded as one.** An `error` line says what the
  publisher serves now is *unknown*, which is neither `unchanged` nor
  `changed`. This is the same three states the rest of the project uses.
- **A damaged log is an error, not an empty record.** A log that does not exist
  is empty and that is a true statement about a repository whose watch has
  never run. A log that exists and does not parse raises, because reporting a
  damaged record as an empty one is the confusion this file exists to end.

`history --id <id>` now opens with the observation record, so the question
"has this been looked at, and when" is answered in the same place as "what has
this value been". `--jsonl` writes that record as its first line, under its own
schema id so a consumer can tell it from a timeline; it is written even when no
timeline follows, because an empty file would state "no record moved" and
"nothing ever looked" with the same zero bytes.

The two runs that predate the log are backfilled from their own workflow run
output, and each backfilled line carries a `backfilled_from` block naming the
run id and its URL. Their `sha256` and `bytes` are `null` because the runs
printed neither; the digest could be derived from the manifest at that commit
plus the code's definition of `unchanged`, and a derivation is not an
observation.

## Consequences

The watch now writes to `main` on a schedule. That is a new capability for a
workflow that previously only opened pull requests, and it is deliberately
narrow: the step stages exactly `data/watch-log.jsonl`, refuses to push if
anything else is staged or if the diff deletes a line, and fails the run if it
cannot push — because a run that could not record itself is exactly the state
this ADR exists to make visible. A commit pushed with `GITHUB_TOKEN` starts no
workflow, so these commits carry no CI verdict of their own; they change one
append-only data file and no code.

What this does **not** do is make a quiet publisher into evidence. Two
observations over eleven days are two observations. The log makes the count
readable; it does not make it large.

Rejected: keeping the record only in the job summary (off-repository, expires,
and invisible to `history`); writing an "all clear" pull request each week
(weekly noise for a human to close, and the review gate this project cares
about is the digest, not the silence); and inferring looks from the workflow
run history through the API (a reader of the repository does not have it, and
it ages out).
