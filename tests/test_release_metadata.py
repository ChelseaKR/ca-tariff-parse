"""The version is stated in three places, and a release ties them together.

`pyproject.toml` names what is installed, `PARSER_VERSION` names what every
emitted document says parsed it, and `CITATION.cff` names what a citation
points at. The release workflow checks the first against the tag; the other
two would drift silently. A changelog section that does not exist for the
version is the same defect from the reader's side.
"""

from __future__ import annotations

import datetime
import re
import tomllib

import yaml

from ca_tariff_parse.parser import PARSER_VERSION

from .conftest import REPO_ROOT

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _project_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def test_the_project_version_is_semver() -> None:
    assert SEMVER.match(_project_version())


def test_the_parser_reports_the_project_version() -> None:
    assert _project_version() == PARSER_VERSION


def test_the_citation_names_the_project_version_and_a_real_date() -> None:
    citation = yaml.safe_load((REPO_ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["version"] == _project_version()
    released = citation["date-released"]
    # cff wants an ISO date; pyyaml may hand back either a date or its string.
    if isinstance(released, str):
        released = datetime.date.fromisoformat(released)
    assert isinstance(released, datetime.date)


def test_the_changelog_has_a_dated_section_for_the_project_version() -> None:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = re.escape(_project_version())
    heading = re.compile(rf"^## \[{version}\] - \d{{4}}-\d{{2}}-\d{{2}}$", re.M)
    assert heading.search(text)
