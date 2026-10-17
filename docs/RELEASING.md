# Releasing to PyPI

Nothing in this repository publishes to PyPI on its own. This is the procedure
a maintainer follows, written so each step can be followed without reading the
workflows first, with what it should look like when it worked.

Last verified: 2026-10-17. `https://pypi.org/pypi/ca-tariff-parse/json` and the
TestPyPI equivalent both returned 404, so the name is free but not reserved.
Recheck before step 2: a 404 today says nothing about next week.

## What was checked, and what it found

Run `make dist-check` to repeat it. It builds the sdist and wheel, runs
`twine check --strict`, builds a wheel again from the sdist, installs the wheel
into an empty virtual environment outside the checkout, runs the command line
tool and asserts the `Project-URL` metadata the wheel carries.

| Item | State |
| --- | --- |
| Name, license, readme, classifiers, `requires-python`, console script | Present in `pyproject.toml` and in the built `METADATA`. |
| `Project-URL` metadata | `Homepage`, `Source`, `Issues`, `Changelog`, `Documentation`, `Security`. The last three were added; a published release's metadata cannot be edited afterwards. |
| Clean-environment install | **Failed before this change.** The `v0.3.0` wheel died on import with `ExportError`, because the published schema was read from the repository root and the wheel did not carry it. Fixed in `src/ca_tariff_parse/export.py` and `pyproject.toml`. |
| Release workflow | Already present: `release.yml` (signed tag to draft GitHub release) and `publish-pypi.yml` (dispatch-only, OIDC trusted publishing, no stored token). Neither was changed. |

### The v0.3.0 tag must not be published

`publish-pypi.yml` builds at the tagged commit. `v0.3.0` predates the schema fix,
so uploading it would put a wheel on PyPI that cannot start, and an uploaded
release is immutable: PyPI will not accept the same filename again, even after
deletion. The same defect makes the README's
`uv tool install "git+https://github.com/ChelseaKR/ca-tariff-parse@v0.3.0"`
fail today. Cut a new version first. `[Unreleased]` in `CHANGELOG.md` carries
new features as well as the fix, so a minor bump (`0.4.0`) matches its contents.

## Procedure

### 1. Merge the readiness pull request

It carries the fix above and `make dist-check`. Confirm the `dist` job in CI is
green on `main`.

### 2. Register the project on PyPI (once)

A maintainer signs in at pypi.org and opens *Your account*, then *Publishing*, then
*Add a new pending publisher*, GitHub tab. Enter exactly:

| Field | Value |
| --- | --- |
| PyPI Project Name | `ca-tariff-parse` |
| Owner | `ChelseaKR` |
| Repository name | `ca-tariff-parse` |
| Workflow name | `publish-pypi.yml` |
| Environment name | `pypi` |

`Workflow name` is the filename, not the workflow's `name:` field. A typo there
fails like a permissions problem. A pending publisher reserves nothing until the
first upload succeeds, so do step 5 soon after.

The account needs two-factor authentication, which PyPI requires for publishing.

### 3. Create the `pypi` environment on GitHub (once)

Repository *Settings*, then *Environments*, then *New environment*, named `pypi`.
Add a maintainer under *Required reviewers* so the upload waits for a
confirmation. Do not add secrets. There is no token and none is wanted.

### 4. Prepare and tag the release

Follow the shape of release PR #36 (commit `95bf997`). In one pull request:

1. `pyproject.toml`: `version`.
2. `src/ca_tariff_parse/parser.py`: `PARSER_VERSION`, same string.
3. `CITATION.cff`: `version` and `date-released`.
4. `CHANGELOG.md`: turn `[Unreleased]` into `[X.Y.Z] - YYYY-MM-DD` and open a
   new empty `[Unreleased]`.
5. `README.md`: the `@v0.3.0` pins in *Quick start*.
6. Regenerate what stamps the parser version: `data/parsed/*.json` and
   `tests/golden/*.json` change in that one field and no other. Review that the
   diff says only that. `uv lock` brings `uv.lock` along.
7. `make verify` and `make dist-check` both exit 0.

After it merges, tag the merge commit with a signing key whose public half is in
`.github/allowed_signers`:

```bash
git checkout main && git pull
git tag -s vX.Y.Z -m "vX.Y.Z"
git verify-tag vX.Y.Z      # needs gpg.format ssh and gpg.ssh.allowedSignersFile
git push origin vX.Y.Z
```

### 5. Release, then publish

1. *Actions*, then `release`, *Run workflow* from `main`, input `vX.Y.Z`. It
   re-verifies the signature, re-runs `make verify` at the tagged commit and
   creates a **draft** GitHub release.
2. Read the draft on the *Releases* page and press *Publish release*.
   `publish-pypi.yml` refuses a tag whose release is still a draft.
3. *Actions*, then `publish-pypi`, *Run workflow* from `main`, input `vX.Y.Z`.
   Approve the `pypi` environment prompt when it appears.

Expected: the `publish` job goes green and
`https://pypi.org/project/ca-tariff-parse/X.Y.Z/` exists, with attestations.

### 6. Check what the index serves

```bash
uvx --from ca-tariff-parse==X.Y.Z ca-tariff-parse --version
uvx --from ca-tariff-parse==X.Y.Z python -c \
  "from importlib.metadata import metadata as m; print(m('ca-tariff-parse').get_all('Project-URL'))"
```

Then change the README's *Quick start* to `uv tool install ca-tariff-parse`,
delete the sentence saying it is not on PyPI, and close Phase 8 in
`docs/ROADMAP.md`.

## If something fails

| Symptom | Cause |
| --- | --- |
| `publish` fails with a trusted-publisher error | Step 2 is missing or a field differs. Compare the error's claims with the table. |
| `verify` fails at `git verify-tag` | The tag is not signed by a key in `.github/allowed_signers`, or the tag is lightweight. |
| `verify` fails at `gh release view` | The release is still a draft (step 5.2). |
| PyPI rejects the upload as a duplicate file | That version exists already, or existed and was deleted. Use the next number. |
| `build` fails on `test "$(ls dist \| wc -l)" -eq 2` | Something else wrote into `dist/`. Look at the job's file listing. |

## Known limit of the PyPI page

The README links to repository files with relative paths such as
`docs/adr/...`. PyPI renders those as links that go nowhere. The project page's
*Documentation* link takes a reader to the repository. Rewriting the links as
absolute URLs at build time is possible with a hatch metadata hook and is not
done here.
