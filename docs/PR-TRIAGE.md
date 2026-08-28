# Pull request triage

Eight open pull requests, four open issues, assessed against `main` at
`af6d911` ("feat: coverage --json, and a test that the published table is the
measurement (#25)").

This document is a decision aid, not a record of anything merged. Nothing in
this triage wrote to the repository, to any pull request, or to any issue.

## Method, and what that means for trust

Every claim below is marked as verified or as taken on trust.

**Verified by re-derivation.** PR head SHAs against the API (all eight match
the local tracking refs exactly, so the local repository is a sound basis for
diff reading). The tip of `main`. Merge state, by `git merge-tree` rather than
by `mergeStateStatus`. Commit ancestry and the resulting stack. Patch
identity between `4283faa` and the merged `af6d911`. Changelog landing
positions against the current file. ADR numbering across all open PRs and the
closed one. CI conclusions, run timestamps, step counts and workflow triggers.
The manifest's pinned lengths and digests against the seven documents on disk.
The published tariff text behind the values PRs #27, #28 and #29 quote, read
out of the pinned PDFs.

**Taken on trust.** The coverage counts each chain PR reports in its commit
message and README table ("pge-b-1 135 to 157" and so on). These are produced
by tests that skip in CI, see "The green that is not a gate" below. Their
internal arithmetic is verified and consistent; whether the parser emits those
figures was not re-executed. The `mypy`, `ruff` and coverage-floor results
inside each green run were not re-run.

**Not done.** No test suite was executed. No branch was checked out.

## Two structures, not one stack

Every one of the eight targets `main` directly. No PR is based on another
PR's branch, so **no PR would be auto-closed by merging and deleting its
base**, and `delete_branch_on_merge` is `false` in any case.

What exists instead is a *content* stack: four PRs whose branches contain each
other's commits.

```
main af6d911 ("coverage --json", merged as #25)
 │
 │   ── chain A: sheet_rates, one branch stacked on the next ──
 │   4283faa  (identical patch to af6d911, ALREADY ON MAIN)
 │     └── 19934ee  #27  Phase 4  ADR 0012
 │           └── 8b50193  #28  Phase 5  ADR 0013
 │                 └── 747e991  #29  Phase 6  ADR 0014
 │                       └── 8d1e5aa  #32  Phase 7  ADR 0015
 │
 │   ── chain B: sources and credit ──
 │   a54568a
 │     ├── #24  (+ merge of main + a formatting commit)  MERGEABLE
 │     └── c5a2055  #31  Phase 1 follow-up
 │
 │   ── independent ──
 │   16fdf98  #26  Phase 3   issue and PR templates
 │   93231fa  #21  dependabot, ruff 0.16.4
```

`#32` contains `#29` contains `#28` contains `#27`. Merging `#32` alone would
deliver all four. Because this repository squash merges (every recent commit
on `main` has a single parent and a `(#N)` title suffix), GitHub will **not**
auto-close `#27`, `#28` and `#29` when `#32` lands; they would have to be
closed by hand.

Every chain-A branch also carries `4283faa`, which is patch-identical to
`af6d911`, already on `main` as #25. That single duplicated commit is the
entire reason all four report `DIRTY`. Rebasing drops it by patch id.

## Per-PR recommendations

| PR | Title | Base | Real merge state | Correct? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| #24 | Phase 1: a credit's own window, and a manifest filename that stays put | `main` | CLEAN, green, only run that postdates current `main` | Yes | **merge** (merge first) |
| #26 | Phase 3: issue forms and a pull request template | `main` | DIRTY: changelog only, keep-both | Yes | **merge after rebase** |
| #21 | deps: bump ruff from 0.16.3 to 0.16.4 | `main` | Reported UNKNOWN; `merge-tree` says CLEAN | Yes, lock-only | **merge** (last) |
| #27 | Phase 4: a column that names itself can carry a price | `main` | DIRTY only from the duplicated `4283faa` | Yes, values verified against the PDF | **merge after rebase** |
| #28 | Phase 5: a unit reaches over the table it heads | `main` | Same | Yes, groups verified against the PDF | **merge after rebase**, after #27 |
| #29 | Phase 6: a unit the publisher broke across a line ending | `main` | Same | Yes, broken bracket verified against the PDF | **merge after rebase**, after #28 |
| #32 | Phase 7: a running head runs | `main` | Same | Yes | **merge after rebase**, after #29 |
| #31 | Phase 1 follow-up: one verdict per document | `main` | DIRTY: two test files, keep-both | Yes, and its premise re-derived | **merge after rebase**, after #24 |

Nothing here is actively wrong. There is no PR I would refuse to merge, and no
invented tariff value anywhere in the eight.

## Per-PR detail

### #24, Phase 1: a credit's own window, and a manifest filename that stays put

Two fixes. A credit now takes the applicability window of the nearest
"Credit applies to" sentence *above* it rather than the last one in the
section; and a manifest `filename` that climbs out of the sources directory is
refused rather than resolved, with a size screen so `sources` stops hashing a
file whose length already disagrees with the manifest.

**Correct.** The credit tests genuinely fail without the change: the old code
assigned `window` in a loop that ran to completion before any charge was
emitted, so every credit in a section received the *last* sentence's window.
`test_two_credits_in_one_section_keep_their_own_windows` would have both
credits reading "noon to 6:00 p.m." under the old code and asserts they differ.
`test_a_credit_above_every_applicability_sentence_takes_no_window` asserts
`None` where the old code produced a borrowed window. Both are real
regressions caught. A third test is an explicit control case for the
single-credit path, and the size-screen pair likewise has a control asserting
that a file of exactly the pinned length is still hashed. This is the
`implemented and fenced` pattern the repository uses elsewhere.

Closes issues #13 and #16. It is the redone version of closed-unmerged #18 and
#17.

The only PR whose green run (03:52:21Z) postdates the current tip of `main`
(03:47:51Z), because its branch already merged `main` in. Merge it first.

### #26, Phase 3: issue forms and a pull request template

Two GitHub issue forms, a `config.yml` routing security reports to
`SECURITY.md`, and a pull request template. Adds `pyyaml` to the dev group
(already present in the lock at the same version) and a test that the forms are
ones GitHub can actually render.

**Correct**, and the test is the good kind: a malformed issue form fails
silently, GitHub simply drops it from the chooser, so a test that parses the
YAML and checks required field ids, contact-link targets and unticked
checkboxes is testing the exact failure mode that would otherwise be invisible.
The tests fail without the change trivially, since the files do not exist.

Closes issues #11 and #12. Redone version of closed-unmerged #20.

Its only conflict is the changelog, and it is the benign shape: `#25` inserted
two entries at the top of `### Added` after `#26` branched, and `#26` inserts
one at the same anchor. Keep both, in either order.

### #21, deps: bump ruff 0.16.3 to 0.16.4

`uv.lock` only, version line plus hashes. Nothing else changed. `merge-tree`
reports it clean against the current `main` even though GitHub still reports
`UNKNOWN` (it simply has not recomputed since Aug 24).

**One caveat.** Its green run is from Aug 24 against base `0a232ce`, four
commits behind. A new ruff minor can add lint rules, and `main` plus the whole
chain has gained a great deal of code since. Merge it **last**, after the
parser work, so that its check runs against the code it will actually lint.

### #27, #28, #29, #32: the sheet_rates chain

This is the substantial work, and it is the part where the domain caution
matters most. I read the pinned PDFs directly and checked the values these PRs
quote.

**#27** stops refusing a page that sets amounts in more than one column *when
the page names those columns*, reading the names off the page and attributing
each amount to the column it sits under. The refusal moves from the page to the
row and gets stricter there: a row that does not fill every named column is
still refused, because its single amount may be one column's or the whole
row's.

Verified against `sources/ELEC_SCHEDS_B-1.pdf` (digest confirmed against the
manifest), page 3:

```
Total Bundled Time-of-Use Rates B-1 Rates B1-ST Rates
Total TOU Energy Rates ($ per kWh)
Peak Summer $0.47087 (R) $0.49377 (R)
Partial-Peak Winter (for B1-ST only) --- $0.36632 (R)
```

The column names, the group name, the unit, the two peak-summer prices and the
dashed cell in the docstring and tests are all exactly what the publisher
printed, on the page the test asserts (`provenance.page == 3`). The PDP tables
lower on the same sheet do set one amount under two columns
(`Peak Summer ($0.06014)`), which is what the row-level refusal keeps unread,
as the PR claims.

**#28** lets a unit stated over a table reach the components of that table,
fenced by the page's own indentation, and separately fixes a citation defect
where a unit read from its own line was cited to the label above it, whose
snippet does not contain the unit. Verified on B-1 page 4: `Energy Rates by
Components ($ per kWh)` over `Generation:` and `Distribution**:`, which are the
group names the test asserts. The citation fix ships with a new cross-document
test that every cited value appears on the line its citation names, with the
single known composition named rather than skipped. That test is a genuine
strengthening of the provenance contract.

**#29** reads a unit whose bracket the publisher broke across a line ending,
joining only where the punctuation says the heading continues, and refusing a
bracket that takes more than one line ending to close rather than inventing a
lookahead limit. Verified on `sources/ELEC_SCHEDS_E-1.pdf` page 3:

```
Base Services Charge Rates by Component ($ per customer
per day)
```

That is exactly the shape described. This PR also changes an existing spot
check from keying on label alone to keying on (component, label). That is the
kind of edit that deserves suspicion, so I checked it: `Income Tier 3` really
does appear four times on E-1 page 3, at `$0.36945`, `$0.31065`, `$0.00000` and
`$0.11333`. The old lookup assumed one match and was wrong to; the parser is
not wrong to emit four. The test change is a correction, not a weakening.

**#32** reads the second publisher's schedule code and, where the page settles
it, its title, by finding the line that repeats across sheets rather than by
adding a profile field. It leaves `resolution`, `adopted` and `effective` null
and records that as a finding about what the sheets do not print. That
restraint is consistent with the project's stated rule.

**Correctness of the chain as a whole.** No value is invented: prices come from
`read_amount` over document words, column names from the naming line, and
everything carries provenance. Every quoted figure I could check against the
published PDFs matched exactly. The README coverage table in the rebased result
is internally consistent and its arithmetic is right (67/247 = 27.1%,
53/346 = 15.3%, 157/477 = 32.9%).

**What I could not check without executing:** whether the parser actually
produces those coverage counts, and whether the four SMUD golden files really
are byte for byte unchanged. See the next section for why that is not idle.

### #31, Phase 1 follow-up: one verdict per document

`sources` and `verify-source` could disagree about one file: with a manifest
entry whose `sha256` is right and whose `bytes` is wrong, the listing said
`mismatched` (because #24 gave it a size screen) while `verify-source` said it
matched. `verify` now checks both pinned facts.

**Correct, and the premise is real** rather than hypothetical: #24 introduces
the size screen, and nothing on `main` or in #24 validates `entry.bytes` on the
way in, so the two commands genuinely could contradict each other. The new test
asserts the property directly across a pinned entry, a length-disagreeing entry
and a digest-disagreeing entry.

I re-derived the claim the PR leans on, that this breaks nothing real: all
seven manifest entries pin their true lengths and true digests, checked against
the seven PDFs on disk. `verify-source` will still exit 0.

**Depends on #24** for `local_state`. Its conflict with `main` is two test
files and is purely additive on both sides (main's robots.txt tests from #22
versus #31's two new tests), so the resolution is keep-both.

Not a duplicate of #24 and should not be closed as one: it shares #24's commit
`a54568a` because it was branched from it, but `c5a2055` is separate work.

## Non-diff hazards checked

**Changelog landing positions, checked against the current file rather than
the diff.** This was the specific hazard raised, and it does not bite here, but
it was close enough to be worth spelling out. `CHANGELOG.md` on `main` has a
released section, `## [0.1.0] - 2026-08-18` at line 78, with `[Unreleased]`
occupying lines 8 to 77. Several hunks carry `### Added` or `### Fixed` as
context, and both of those strings appear twice in the file, once in
`[Unreleased]` and once in `[0.1.0]`. What disambiguates them is the adjacent
bullet text, and I confirmed the three anchor phrases actually used
(`A stray change-bar glyph`, `ADR 0010.`, `coverage --json`) each appear
**exactly once** in the whole file, all inside `[Unreleased]`. I then computed
the merged trees and read the section markers out of the result: in every case
`## [0.1.0]` survives intact and every added entry lands above it. No hunk
lands in a released section.

Worth noting for the future: `[0.1.0]` is documented as released on
2026-08-18, but there are no git tags and no GitHub releases, so nothing has
actually shipped under that number yet.

**ADR numbering.** `main` holds 0000 through 0011. Across the eight open PRs
the new ADRs are 0012 (#27), 0013 (#28), 0014 (#29) and 0015 (#32), and because
those four are a strict linear chain the numbers are contiguous and **collide
with nothing**. No renumbering is required by any recommendation in this
document, provided the chain is merged in order.

The collision described in the repository's history is real but already
resolved: closed PR #30 shipped `docs/adr/0015-a-schedule-names-itself-in-its-own-words.md`
while its own body still described the decision as "recorded in ADR 0014",
the residue of a renumber. #30 covered the same ground as #32 and was closed at
03:45:57Z, twelve minutes before the last merge to `main`. #32 is the survivor.
No live duplicate pair remains among the eight.

**Other monotonic identifiers.** No database migrations, no numbered fixtures,
no sequence files in this repository. `sources/sources.toml` is keyed by
document id, not by an incrementing number. Nothing else to collide.

**Duplicate and superseded work.** Four closed-unmerged PRs (#17, #18, #19,
#20) addressed issues #16, #13, #10 and #11/#12. The open #24 and #26 are the
redone versions of that work, and #19's subject shipped as #25. That history is
settled; none of the eight open PRs duplicates another.

## Real merge state: no starvation, no absence, but a green that is not a gate

**Billing starvation: not present.** All eight PRs have three checks each, all
`pass`, with durations of 12 to 28 seconds and real job ids. No run has zero
steps, no run is in the 3 to 5 second band, and no run carries a budget
annotation. This is the prior that failed to transfer, and I checked it rather
than assuming.

**Dependabot: correctly configured.** `.github/dependabot.yml` declares
`package-ecosystem: "uv"` against a `uv.lock` project, plus `github-actions`.
That is right, and #21 is consequently a normal green PR rather than one born
red.

**Absent scanning: not applicable.** `ci.yml` triggers on `pull_request` with
no branch filter, so every PR is scanned whatever its base. There is no
`codeql.yml` in this repository at all; static analysis is bandit inside the
"Secret, static and dependency scanning" job. Nothing is silently unscanned.

**Stale green: present on seven of eight.** Only #24's run postdates the
current tip of `main`. The other seven were green against an older base. This
matters least for #26 and most for #21.

**The green that is not a gate.** This is the finding that most changes how the
eight should be read. `ci.yml` never runs `make fetch`, and the real PDFs are
deliberately not committed, so every test marked `realdoc` **skips in CI**. The
workflow says so itself in a comment. That means the green checks on #27, #28,
#29 and #32 do not execute a single assertion about a real tariff document:
not the quoted prices, not the coverage counts, not the "four SMUD schedules
byte for byte unchanged" claim that the golden files exist to protect. The
synthetic fixtures do run, and the refusal tests do run, but the evidence that
these four PRs do what they say is local only.

Two consequences. First, reviewing the chain means running the real-document
tests by hand; the seven documents are already present in `sources/` on this
machine and verified against the manifest, so this needs no network:

```sh
uv run pytest -m realdoc
make golden   # review every changed price before accepting
```

Second, `main` is **not protected**: no branch protection and no rulesets, so
no check is required to merge and the green marks are advisory in the literal
sense.

## Safe order of operations

The ordering constraints are: #31 after #24; the chain strictly in order; #21
last so it lints the final tree.

1. **Merge #24 as is.** Clean, green against the current `main`, and the only
   PR needing nothing. Closes issues #13 and #16.
2. **Rebase and merge #26.** One changelog conflict, keep both entries at the
   top of `### Added` in `[Unreleased]`. Closes issues #11 and #12. At this
   point all four open issues are closed.
3. **Rebase and merge #31.** Because #24 squash merges, `a54568a` will not be
   dropped by patch id, so expect to resolve `tests/test_sources.py` and
   `tests/test_cli.py`, keeping both sides. No semantic conflict, both sides
   are additions at the end of the file.
4. **Rebase and merge the chain in order: #27, then #28, then #29, then #32.**
   Each rebase onto `main` drops the duplicated `4283faa` automatically, since
   it is patch-identical to the merged `af6d911`. I simulated all four rebases:
   every one is **clean**, ADRs land contiguously as 0012 through 0015, and no
   changelog entry is duplicated in the result.

   Before each merge, run `uv run pytest -m realdoc` and `make golden`, because
   CI will not. The `make golden` step is the regeneration this sequence
   needs: the four SMUD golden files must come back byte for byte unchanged,
   which is each PR's own stated claim and the thing CI cannot check.

   After each squash merge, the next PR in the chain needs a fresh rebase, and
   the one just merged will *not* auto-close. Close it by hand.

   The shortcut, if per-phase review is not wanted: rebase and merge **#32
   alone**, which carries all four commits, then close #27, #28 and #29 as
   contained in it. Use a rebase merge rather than a squash if the four
   separate commits and their four ADRs should stay distinct in the history.

5. **Merge #21 last**, so ruff 0.16.4 runs against the finished tree rather
   than against a four-commit-old base. If it turns the build red, that is new
   lint on new code and is worth seeing then rather than earlier.

Nothing in this sequence requires an ADR renumber or a changelog renumber.

## Corrections to the priors

- **Billing starvation** did not transfer to this repository. Checked
  annotations, step counts and durations; all 24 jobs are real and green.
- **Dependabot** is correctly configured here (`uv`, not `pip`).
- **"Absent is not green"** does not apply as stated, since `ci.yml` has no
  branch filter, but a **variant of it does and is worse**: the checks are
  present and green while skipping every real-document test. Absent scanning
  would at least have looked absent. This looks like a full pass.
- **The ADR 0014 collision** is real history but already resolved, by the
  closure of #30. Among the eight open PRs, ADR numbering is contiguous and
  clean.

## Defects on `main` not addressed by any open PR

I found none worth a code change. Checked: no build artefacts tracked
(`.coverage`, caches, `htmlcov` are all untracked), every `ADR NNNN` reference
in the README resolves to a file that exists, the coverage table matches the
committed figures, and `docs/`, `schemas/` and `sources/` are internally
consistent. The four open issues are all addressed by #24 and #26.

Two observations that are not defects and need no patch, recorded so they are
not rediscovered:

- `CITATION.cff` carries `cff-version` but no `version` field for the software
  itself, so it will not track releases automatically. Cosmetic until something
  is actually tagged.
- `CHANGELOG.md` documents `[0.1.0]` as released on 2026-08-18 while no tag and
  no GitHub release exist. Harmless now; it is the condition under which the
  changelog-landing hazard checked above would become live, because a real
  release cutting a new section would move `[Unreleased]` and every open PR's
  anchor with it.
