#!/usr/bin/env bash
# Build the sdist and wheel, then install the wheel into an empty environment
# outside the checkout and run it. Nothing is uploaded.
#
# This is the check a release is owed before anyone presses publish: an index
# release is immutable, so a wheel that fails on import, or that lacks its
# Project-URL metadata, can only be corrected by spending a version number.
#
#   make dist-check
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

cd "${root}"
uv build --out-dir "${work}/dist"
wheel="$(ls "${work}"/dist/*.whl)"
sdist="$(ls "${work}"/dist/*.tar.gz)"
test "$(ls "${work}/dist" | grep -c -E '\.(whl|tar\.gz)$')" -eq 2

# Metadata the index renders: long description, classifiers, license, URLs.
uvx --from 'twine==7.0.0' twine check --strict "${work}"/dist/*

# The sdist has to build a wheel on its own, as a consumer of it would.
uv build --wheel --out-dir "${work}/from-sdist" "${sdist}"

# A clean interpreter, a clean directory, no checkout on the path.
uv venv --quiet --python 3.12 "${work}/venv"
uv pip install --quiet --python "${work}/venv/bin/python" "${wheel}"
mkdir "${work}/run"
cd "${work}/run"
cli="${work}/venv/bin/ca-tariff-parse"
py="${work}/venv/bin/python"

"${cli}" --version
"${cli}" --help > /dev/null
fixture="${root}/tests/fixtures/SYNTHETIC-example-schedule-complete.txt"
"${cli}" parse "${fixture}" --min-coverage 1.0 > "${work}/parsed.json"
"${cli}" export "${work}/parsed.json" --table charges > /dev/null

"${py}" -I - <<'PY'
from importlib.metadata import metadata

meta = metadata("ca-tariff-parse")
urls = {u.split(", ", 1)[0]: u.split(", ", 1)[1] for u in meta.get_all("Project-URL") or []}
required = {"Homepage", "Source", "Issues", "Changelog", "Documentation", "Security"}
missing = required - set(urls)
assert not missing, f"wheel metadata lacks Project-URL: {sorted(missing)}"
assert meta["License-Expression"] == "Apache-2.0", meta["License-Expression"]
print("Project-URL:", ", ".join(sorted(urls)))
PY
echo "dist-check: ok"
