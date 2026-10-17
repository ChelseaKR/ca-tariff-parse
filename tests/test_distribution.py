"""What `pip install ca-tariff-parse` would hand a reader.

An index release is immutable, so a defect in the wheel cannot be fixed in
place: the next version number has to carry the fix. Two have already cost
another project in this family a release: a wheel with no `Project-URL`
metadata, and a wheel that could not find a file it read from the repository
root. These tests check the configuration that decides both. The built wheel
itself is installed into a clean environment and run by the `dist` job in
`.github/workflows/ci.yml`.
"""

from __future__ import annotations

import tomllib
from typing import Any
from urllib.parse import urlparse

from ca_tariff_parse import export

from .conftest import REPO_ROOT

REPOSITORY = "https://github.com/ChelseaKR/ca-tariff-parse"
#: Labels a reader looks for on the project page. `Source` and `Issues` are
#: the ones a reviewer of the index listing checks first.
REQUIRED_URLS = ("Homepage", "Source", "Issues", "Changelog", "Documentation", "Security")


def _pyproject() -> dict[str, Any]:
    data: dict[str, Any] = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data


def test_the_project_urls_are_declared_and_point_at_the_repository() -> None:
    urls = _pyproject()["project"]["urls"]
    for label in REQUIRED_URLS:
        assert label in urls, f"[project.urls] has no {label}"
    for label, url in urls.items():
        parsed = urlparse(url)
        assert parsed.scheme == "https", label
        assert (
            url == REPOSITORY
            or url.startswith(f"{REPOSITORY}/")
            or url.startswith(f"{REPOSITORY}#")
        ), label


def test_the_project_urls_that_name_a_file_name_one_that_exists() -> None:
    urls = _pyproject()["project"]["urls"]
    for label in ("Changelog", "Security"):
        path = urls[label].removeprefix(f"{REPOSITORY}/blob/main/")
        assert (REPO_ROOT / path).is_file(), f"{label} points at {path}, which does not exist"


def test_the_index_listing_has_what_it_needs() -> None:
    project = _pyproject()["project"]
    assert project["readme"] == "README.md"
    assert project["license"]
    assert project["requires-python"]
    assert project["classifiers"]
    assert project["scripts"]["ca-tariff-parse"] == "ca_tariff_parse.cli:main"


def test_the_wheel_carries_the_schema_the_export_command_reads() -> None:
    include = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert include, "the wheel force-includes nothing"
    (source, target), *rest = include.items()
    assert not rest
    assert (REPO_ROOT / source).is_file()
    # Beside the package, where export.py looks first when installed.
    assert target == "ca_tariff_parse/_schemas/" + source.rsplit("/", 1)[-1]
    assert export._PACKAGE_SCHEMA.relative_to(export._PACKAGE_SCHEMA.parents[2]).as_posix() == (
        target
    )


def test_a_checkout_reads_the_one_published_schema() -> None:
    # No second copy lives in the source tree: a copy could drift from the
    # schema that docs and consumers link to.
    assert not export._PACKAGE_SCHEMA.exists()
    assert export.SCHEMA_PATH == export._CHECKOUT_SCHEMA
    assert export.SCHEMA_PATH.is_file()
