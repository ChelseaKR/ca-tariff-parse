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


#: The sentence that says how much of California this covers. The denominator
#: is measured elsewhere and cited in the README; the numerator is a fact about
#: this repository, so it is checked against the manifest rather than trusted.
FRACTION_RE = re.compile(r"pins documents from \*{0,2}(\d+)\*{0,2} of them")
FRAME_RE = re.compile(r"California has \*{0,2}(\d+)\*{0,2} retail electric service territories")


def test_the_stated_fraction_is_the_manifest_the_repository_actually_pins() -> None:
    """A coverage table with no frame invites the reading that the table is the
    state. The frame is written down; this keeps its numerator true."""
    text = README.read_text(encoding="utf-8")
    stated = FRACTION_RE.search(text)
    assert stated, "the README no longer says what fraction of the frame it covers"
    publishers = {entry.publisher for entry in load_manifest(MANIFEST)}
    assert int(stated.group(1)) == len(publishers), (
        f"the README says {stated.group(1)} publisher(s) are pinned; the manifest "
        f"pins {len(publishers)}: {sorted(publishers)}"
    )


def test_the_frame_names_where_its_own_number_came_from() -> None:
    """The denominator is not this project's measurement, so it cites one."""
    text = README.read_text(encoding="utf-8")
    frame = FRAME_RE.search(text)
    assert frame, "the README no longer states the frame the fraction is out of"
    frame_paragraph = text[frame.start() : frame.start() + 900]
    assert "California Energy Commission" in frame_paragraph
    assert "Electric Load Serving Entities" in frame_paragraph
    assert "2026-08-23" in frame_paragraph, "a retrieved count states when it was retrieved"
