# 0019. A look is recorded even when nothing moved

- Status: Accepted
- Date: 2026-09-13; storage revised 2026-09-18

## Context

`tariff-watch.yml` has run twice: a `workflow_dispatch` on 2026-09-02 and one
scheduled run on 2026-09-07 (runs `33597504100` and `34133314317`). Both
succeeded. Both looked at all seven pinned documents and found every one of
them serving the pinned bytes. Neither opened a pull request, because there was
nothing to propose, and `data/changes/` has never existed in this tree or in
its history. A third run, scheduled on 2026-09-14 (`34856244471`), found the
same.

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

**Every run of the watch appends one line to `watch-log.jsonl` on the
`watch-log` branch, and the workflow pushes it there, whether or not anything
moved.**

The record is a JSON line per run
(`ca-tariff-parse/watch-observation/v1`) naming the UTC time the run looked, a
sentence of the form `looked at <time>, found <n> changes across <k> documents`,
the counts behind it, the parser version, and every document the run examined
with the state it was found in (`unchanged`, `changed` or `error`) and the
detail the run printed. A document the run could not read is never counted as
unchanged: the sentence names it as unknown. It is appended, never rewritten:
an earlier line is evidence that a look happened and nothing here is entitled
to restate it.

**A quiet week and a missed week are different on the branch.** A quiet week
is a line that says `found 0 changes`, with the time. A missed week is a week
with no line. The branch's own history carries one commit per run, whose
message is that sentence.

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

The three runs that predate the log are backfilled from their own workflow run
output, and each backfilled line carries a `backfilled_from` block naming the
run id and its URL. Their `looked_at` is the time the run's look step finished,
read from the run's step timings. Their `sha256` and `bytes` are `null` because
the runs printed neither; the digest could be derived from the manifest at that
commit plus the code's definition of `unchanged`, and a derivation is not an
observation.

### Where the record lives, and why not on `main`

The first version of this decision committed the line to `main`. `main` is
protected by the `protect-main` ruleset. It refuses a commit that has not
passed the required checks, and the workflow's `GITHUB_TOKEN` is not a bypass
actor. A scheduled push to `main` would have failed every week, and the
failure would have looked exactly like the missed look this record exists to
expose. Weakening the ruleset for a data file is the wrong trade. So the record
lives somewhere that needs no push to `main`. Three places were weighed:

- **A dedicated `watch-log` branch (chosen).** It is plain git, so it does not
  expire, it is readable offline (`make watch-log`, or
  `git show origin/watch-log:watch-log.jsonl`), and every run is one commit
  with a one-line diff that GitHub renders like any other history. That makes
  it the most reviewable of the three. The weakness is that the branch is
  unprotected. The workflow narrows it: it only fast-forwards and never
  force-pushes, it refuses to commit anything but exactly one added line, and a
  missing branch fails the run rather than being recreated empty. An empty log
  would read as a watch that never looked. A ruleset that blocks deletion and
  non-fast-forward pushes on `refs/heads/watch-log`, and requires no checks,
  would close the rest without touching `protect-main`.
- **A single GitHub release with the log as an asset (rejected).** A release
  needs a tag, and this repository's tags are signed release versions that
  `release.yml` and `publish-pypi.yml` act on. A standing non-version tag would
  sit among them and could be mistaken for one. Replacing an asset keeps no
  history, so each week would overwrite the last with nothing to diff.
- **The run summary plus an issue comment (rejected as the record, kept as a
  view).** A run summary expires with the run's logs. An issue comment
  persists, but it is not machine-readable without the API, it notifies
  subscribers every week, and it can be edited or deleted without a trace in
  the repository. The workflow still writes the sentence and a per-document
  table to the run summary, before it pushes, so a failed push still leaves
  the look readable on the run page.

`main` carries no copy. `data/watch-log.jsonl` is the local default path for
`watch --log` and `history --watch-log`, and it is ignored. `make watch-log`
fills it from the branch.

## Consequences

The watch now writes to the `watch-log` branch on a schedule. It never writes
to `main`, and `tests/test_watch.py` fails if any push in the workflow names
`main`, forces, or uses a `+` refspec. The record step stages exactly
`watch-log.jsonl`, refuses to push unless the diff is one line added and none
removed, and fails the run if it cannot push. A run that could not record
itself is exactly the state this ADR exists to make visible. Proposals for
revised documents do not wait on the record, so a revision still reaches a pull
request in a week whose push failed. A commit pushed with `GITHUB_TOKEN` starts
no workflow, and `ci.yml` runs on pushes to `main` only, so the branch carries
no CI verdicts. It holds one append-only data file, a README and no code.

What this does **not** do is make a quiet publisher into evidence. Three
observations over twelve days are three observations. The log makes the count
readable; it does not make it large.

Also rejected: keeping the record only in the job summary (off-repository,
expires, and invisible to `history`); writing an "all clear" pull request each week
(weekly noise for a human to close, and the review gate this project cares
about is the digest, not the silence); and inferring looks from the workflow
run history through the API (a reader of the repository does not have it, and
it ages out).
