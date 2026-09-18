# The tariff watch's observation log

This branch holds one file, `watch-log.jsonl`, and this README. It has no code
and nothing merges it into `main`.

`.github/workflows/tariff-watch.yml` on `main` appends one line per run and
pushes it here, whether or not anything moved. Each line opens with a sentence
of the form

    looked at 2026-09-14T14:32:30Z, found 0 changes across 7 documents

and then names every document the run examined, with the state it was found
in: `unchanged`, `changed` or `error`. `error` means what the publisher serves
now is unknown. It is never counted as unchanged.

**A quiet week is a line that says `found 0 changes`. A missed week is a week
with no line.** Each run is one commit whose message is that sentence, so
`git log --format='%cs %s' origin/watch-log` reads as the watch's diary.

The workflow only fast-forwards this branch. It never force-pushes, it refuses
to commit anything but one added line, and if the branch goes missing it fails
the run rather than starting an empty log. An empty log would read as a watch
that never looked.

The first three lines are backfilled from runs that predate the log. Each
carries a `backfilled_from` block naming its run.

From a checkout of `main`, `make watch-log` copies the log to the ignored
`data/watch-log.jsonl`, where `ca-tariff-parse history --id <id>` reads it.
See ADR 0019 on `main`:
`docs/adr/0019-a-look-is-recorded-even-when-nothing-moved.md`.
