"""The coverage table in the README is what the tool actually reports.

The README calls coverage "a published output, not an implicit claim", and it
is: the parser computes every figure in that table. The table itself is typed
by hand, so the claim and the measurement can drift apart, and nothing but
memory stands between them.

This binds them. It skips where the pinned documents have not been fetched,
the way the other real-document tests do, and it fails wherever a figure in
the README is not the figure the parser reports for that document.
"""

from __future__ import annotations

import re

import pytest

from ca_tariff_parse.parser import parse_manifest_document
from ca_tariff_parse.sources import SourceEntry, load_manifest, verify

from .conftest import REPO_ROOT, SOURCES

pytestmark = pytest.mark.realdoc

MANIFEST = REPO_ROOT / "sources" / "sources.toml"
README = REPO_ROOT / "README.md"
HEADING = "## Coverage today"
#: The columns the table publishes, in the order it publishes them.
COLUMNS = (
    "schedule",
    "publisher",
    "lines",
    "charges",
    "windows",
    "holidays",
    "proration",
    "conditions",
)


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def published_rows() -> dict[str, dict[str, str]]:
    """The README's coverage table, keyed by the schedule code each row names.

    The first cell reads "R-TOD, residential time-of-day"; the code is the part
    before the comma, which is what the manifest calls the schedule.
    """
    text = README.read_text(encoding="utf-8")
    body = text[text.index(HEADING) :]
    rows: dict[str, dict[str, str]] = {}
    for line in body.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = _cells(line)
        if len(cells) != len(COLUMNS) or cells[0] in {"Schedule"} or set(cells[0]) <= {"-", " "}:
            continue
        row = dict(zip(COLUMNS, cells, strict=True))
        rows[row["schedule"].split(",")[0].strip()] = row
    return rows


def _entries() -> dict[str, SourceEntry]:
    return {entry.schedule: entry for entry in load_manifest(MANIFEST)}


def test_the_table_lists_every_document_the_manifest_pins() -> None:
    """A document added to the manifest cannot quietly skip the published table."""
    assert set(published_rows()) == set(_entries())


@pytest.mark.parametrize("schedule", sorted(_entries()))
def test_the_published_figures_are_the_ones_the_parser_reports(schedule: str) -> None:
    entry = _entries()[schedule]
    path = SOURCES / entry.filename
    if not path.exists():
        pytest.skip(f"{entry.id} ({entry.filename}) not fetched; run `make fetch`")
    verify(entry, path)
    parsed = parse_manifest_document(entry, path)
    coverage = parsed.coverage

    row = published_rows()[schedule]
    assert row["publisher"], f"{schedule} publishes no publisher"
    measured = {
        "lines": (
            f"{coverage.recognized_lines}/{coverage.content_lines} ({coverage.line_ratio:.1%})"
        ),
        "charges": str(len(parsed.charges)),
        "windows": str(len(parsed.tou_windows)),
        "holidays": str(len(parsed.holidays)),
        "proration": str(len(parsed.proration)),
        "conditions": str(len(parsed.conditions)),
    }
    assert {key: row[key] for key in measured} == measured


def test_the_table_states_the_reproducing_command() -> None:
    """A reader can check the table without reading this test."""
    text = README.read_text(encoding="utf-8")
    assert re.search(r"`make coverage-real` reproduces the table", text)
