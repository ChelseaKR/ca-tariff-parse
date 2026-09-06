"""The reshape does not lose the citation, the absence, or a row.

A flat table of tariff prices is the shape downstream tooling actually
consumes, and it is also the shape in which this project's guarantee is
easiest to lose: a spreadsheet of prices with the citations left behind looks
more actionable than the JSON and is worth less. Every test here holds one
part of the reshape to the thing it replaced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ca_tariff_parse import export
from ca_tariff_parse.cli import main
from ca_tariff_parse.export import (
    ExportError,
    columns,
    neutralise,
    render_csv,
    render_jsonl,
    rows,
    table_names,
)

from .conftest import GOLDEN, REPO_ROOT

BASELINES = REPO_ROOT / "data" / "parsed"


def payloads() -> list[Path]:
    files = sorted(GOLDEN.glob("*.json")) + sorted(BASELINES.glob("*.json"))
    assert files, "expected committed payloads to export"
    return files


def read(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return read(GOLDEN / "smud-r-tod.json")


# ---------------------------------------------------------------------------
# The columns come from the schema, not from a list somebody maintains
# ---------------------------------------------------------------------------


def test_the_charges_columns_are_the_documented_order() -> None:
    assert columns("charges") == (
        "document_id",
        "document_sha256",
        "parser_version",
        "label",
        "label.locator",
        "kind",
        "price.amount",
        "price.amount.locator",
        "price.currency",
        "price.unit",
        "price.unit.locator",
        "effective_from",
        "effective_from.locator",
        "rate_category",
        "rate_category.locator",
        "season",
        "season.locator",
        "tou_period",
        "tou_period.locator",
        "applies_to",
        "applies_to.locator",
        "group",
        "group.locator",
    )


@pytest.mark.parametrize("table", table_names())
def test_every_cited_field_is_followed_by_its_locator(table: str) -> None:
    order = columns(table)
    for index, name in enumerate(order):
        if not name.endswith(".locator"):
            continue
        assert order[index - 1] == name.removesuffix(".locator"), (
            f"{table}: {name} does not sit beside the value it cites"
        )


@pytest.mark.parametrize("table", table_names())
def test_no_column_is_derived(table: str) -> None:
    """The export reshapes; it does not compute. Every column is either an
    identity column or a field the schema declares."""
    schema = json.loads(
        (REPO_ROOT / "schemas" / "parsed-schedule-v1.schema.json").read_text(encoding="utf-8")
    )
    declared = set()

    def walk(def_name: str, prefix: str) -> None:
        for field, spec in schema["$defs"][def_name].get("properties", {}).items():
            path = f"{prefix}{field}"
            ref = spec.get("$ref", "").removeprefix("#/$defs/")
            declared.add(path)
            if ref and ref not in {"citedString", "citedStringOrNull"}:
                walk(ref, f"{path}.")

    walk(export.TABLES[table], "")
    for name in columns(table, snippets=True):
        base = name.removesuffix(".locator").removesuffix(".snippet")
        assert base in declared or name in export.IDENTITY_COLUMNS, name


def test_unparsed_is_not_a_table_and_says_why() -> None:
    assert "unparsed" not in table_names()
    with pytest.raises(ExportError, match="no citation to flatten"):
        rows({}, "unparsed")


def test_notes_is_not_a_table_and_says_why() -> None:
    assert "notes" not in table_names()
    with pytest.raises(ExportError, match="verbatim"):
        columns("notes")


def test_an_unknown_table_names_the_ones_that_exist() -> None:
    with pytest.raises(ExportError, match="charges"):
        columns("prices")


def test_excluding_a_table_that_gained_citations_is_refused() -> None:
    """The exclusion of `unparsed` rests on it carrying no citations. If that
    stops being true the exclusion would hide cited values, so it fails."""
    schema = {
        "properties": {
            "charges": {"type": "array", "items": {"$ref": "#/$defs/charge"}},
            "unparsed": {"type": "array", "items": {"$ref": "#/$defs/unparsedSection"}},
            "notes": {"type": "array", "items": {"$ref": "#/$defs/citedString"}},
        },
        "$defs": {
            "charge": {"properties": {"label": {"$ref": "#/$defs/citedString"}}},
            "unparsedSection": {"properties": {"reason": {"$ref": "#/$defs/citedString"}}},
        },
    }
    with pytest.raises(ExportError, match="now cites reason"):
        export._derive_tables(schema)


def test_a_stale_exclusion_is_refused() -> None:
    schema = {
        "properties": {"charges": {"type": "array", "items": {"$ref": "#/$defs/charge"}}},
        "$defs": {"charge": {"properties": {"label": {"$ref": "#/$defs/citedString"}}}},
    }
    with pytest.raises(ExportError, match="exclusion is stale"):
        export._derive_tables(schema)


# ---------------------------------------------------------------------------
# Nothing is dropped, nothing is invented
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", payloads(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_table_has_one_row_per_record(path: Path) -> None:
    payload = read(path)
    for table in table_names():
        assert len(rows(payload, table)) == len(payload[table]), table


def test_regrouping_the_rows_reproduces_every_cited_value_and_locator(
    golden: dict[str, Any],
) -> None:
    exported = rows(golden, "charges")
    for charge in golden["charges"]:
        matching = [
            row
            for row in exported
            if row["label.locator"] == charge["label"]["provenance"]["locator"]
            and row["price.amount"] == charge["price"]["amount"]["value"]
            and row["label"] == charge["label"]["value"]
        ]
        assert matching, charge["label"]["value"]
        row = matching[0]
        assert row["price.amount.locator"] == charge["price"]["amount"]["provenance"]["locator"]
        assert row["price.unit"] == charge["price"]["unit"]["value"]
        assert row["kind"] == charge["kind"]
        for field in ("season", "tou_period", "rate_category", "applies_to", "group"):
            held = charge.get(field)
            if held is None:
                assert row[field] is None
                assert row[f"{field}.locator"] is None
            else:
                assert row[field] == held["value"]
                assert row[f"{field}.locator"] == held["provenance"]["locator"]


def test_a_null_is_an_empty_cell_not_a_zero(golden: dict[str, Any]) -> None:
    exported = rows(golden, "charges")
    without = [row for row in exported if row["applies_to"] is None]
    assert without, "expected at least one charge stating no applies_to"
    rendered = render_csv(without[:1], columns("charges"))
    cells = rendered.splitlines()[1].split(",")
    index = columns("charges").index("applies_to")
    assert cells[index] == ""
    assert "n/a" not in rendered.lower()


def test_a_parse_with_no_holidays_exports_a_header_and_no_rows() -> None:
    payload = read(GOLDEN / "smud-ssr.json")
    assert payload["charges"] == []
    rendered = render_csv(rows(payload, "charges"), columns("charges"))
    assert rendered.splitlines() == [",".join(columns("charges"))]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", payloads(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_exporting_the_same_parse_twice_yields_identical_bytes(path: Path) -> None:
    payload = read(path)
    for table in table_names():
        order = columns(table)
        first = render_csv(rows(payload, table), order)
        second = render_csv(rows(payload, table), order)
        assert first == second, table
        assert render_jsonl(rows(payload, table), order) == render_jsonl(
            rows(payload, table), order
        )


@pytest.mark.parametrize("name", ["smud-r-tod", "smud-r", "smud-ci-tod1", "smud-ssr"])
def test_a_baseline_exports_the_same_tables_as_the_full_parse(name: str) -> None:
    """The watch projection removes only the verbatim prose. Nothing the
    export reshapes is in it, so the tables must be identical."""
    full = read(GOLDEN / f"{name}.json")
    projected = read(BASELINES / f"{name}.json")
    for table in table_names():
        order = columns(table)
        assert render_csv(rows(full, table), order) == render_csv(rows(projected, table), order)


@pytest.mark.parametrize("path", payloads(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_rows_on_a_real_parse_come_out_in_page_order(path: Path) -> None:
    exported = rows(read(path), "charges")
    pages = [int(row["label.locator"].split()[1].removeprefix("p.")) for row in exported]
    assert pages == sorted(pages)


def test_page_ten_sorts_after_page_two_not_before_it() -> None:
    """Sorting the rendered locator as text puts p.10 before p.2. No committed
    document is long enough to show that, so this is the fixture that is."""

    def charge(page: int, line: int, label: str) -> dict[str, Any]:
        provenance = {
            "document_id": "synthetic",
            "document_sha256": "a" * 64,
            "page": page,
            "sheet": None,
            "section": "II.A",
            "line": line,
            "end_line": None,
            "snippet": f"{label} $1.00",
            "locator": f"synthetic p.{page} II.A L{line}",
        }
        cited = {"value": label, "provenance": provenance}
        return {
            "label": cited,
            "kind": "fixed_charge",
            "price": {
                "amount": {"value": "1.00", "provenance": provenance},
                "currency": "USD",
                "unit": {"value": "per month", "provenance": provenance},
            },
            "effective_from": {"value": "May 1, 2025", "provenance": provenance},
        }

    payload = {
        "parser_version": "0.2.0",
        "source": {"document_id": "synthetic", "sha256": "a" * 64},
        "charges": [charge(10, 1, "ten"), charge(2, 9, "two"), charge(2, 1, "two-first")],
    }
    assert [row["label"] for row in rows(payload, "charges")] == ["two-first", "two", "ten"]


# ---------------------------------------------------------------------------
# Snippets are off by default
# ---------------------------------------------------------------------------


def test_snippets_are_absent_by_default(golden: dict[str, Any]) -> None:
    assert not any(name.endswith(".snippet") for name in columns("charges"))
    assert all(not key.endswith(".snippet") for row in rows(golden, "charges") for key in row)


def test_snippets_appear_only_when_asked_for(golden: dict[str, Any]) -> None:
    order = columns("charges", snippets=True)
    assert "label.snippet" in order
    exported = rows(golden, "charges", snippets=True)
    assert exported[0]["label.snippet"] == golden["charges"][0]["label"]["provenance"]["snippet"]


# ---------------------------------------------------------------------------
# CSV cells cannot be read as formulas, and a price is not corrupted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cell", ["=1+1", "+A1", "@SUM(A1)", "\tfoo", "\rfoo", "-- twice"])
def test_a_cell_a_spreadsheet_would_evaluate_is_neutralised(cell: str) -> None:
    assert neutralise(cell).startswith("'")


@pytest.mark.parametrize("cell", ["-0.05", "-1", "0.32561", "Peak", ""])
def test_a_value_a_spreadsheet_would_not_evaluate_is_left_alone(cell: str) -> None:
    """A credit is printed as -0.05. Prefixing it would change what a reader
    sees, so a leading minus is neutralised only when the cell is not a
    number."""
    assert neutralise(cell) == cell


def test_a_none_renders_as_an_empty_cell() -> None:
    assert neutralise(None) == ""


def test_a_negative_price_survives_the_export_unchanged() -> None:
    payload = read(GOLDEN / "smud-r-tod.json")
    negative = [row for row in rows(payload, "charges") if str(row["price.amount"]).startswith("-")]
    assert negative, "expected at least one credit priced as a negative amount"
    order = columns("charges")
    rendered = render_csv(negative[:1], order)
    cells = next(iter(__import__("csv").reader(rendered.splitlines()[1:])))
    assert cells[order.index("price.amount")] == negative[0]["price.amount"]


# ---------------------------------------------------------------------------
# Payload guards
# ---------------------------------------------------------------------------


def test_a_payload_with_no_source_block_is_refused(golden: dict[str, Any]) -> None:
    broken = {key: value for key, value in golden.items() if key != "source"}
    with pytest.raises(ExportError, match="no source block"):
        rows(broken, "charges")


def test_a_payload_that_does_not_state_its_parser_is_refused(golden: dict[str, Any]) -> None:
    broken = dict(golden)
    broken.pop("parser_version")
    with pytest.raises(ExportError, match="parser_version"):
        rows(broken, "charges")


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_export_writes_one_table_to_a_file(tmp_path: Path) -> None:
    out = tmp_path / "charges.csv"
    code = main(["export", str(GOLDEN / "smud-r-tod.json"), "--table", "charges", "-o", str(out)])
    assert code == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(columns("charges"))
    assert len(lines) == 1 + len(read(GOLDEN / "smud-r-tod.json")["charges"])


def test_export_all_writes_every_table_including_the_empty_ones(tmp_path: Path) -> None:
    code = main(["export", str(GOLDEN / "smud-ssr.json"), "--all", str(tmp_path)])
    assert code == 0
    written = {path.stem for path in tmp_path.glob("*.csv")}
    assert written == set(table_names())
    # smud-ssr prices nothing. An empty file would read as "not exported".
    charges = (tmp_path / "charges.csv").read_text(encoding="utf-8")
    assert charges.splitlines() == [",".join(columns("charges"))]


def test_export_all_in_jsonl(tmp_path: Path) -> None:
    code = main(
        ["export", str(GOLDEN / "smud-r-tod.json"), "--all", str(tmp_path), "--format", "jsonl"]
    )
    assert code == 0
    holidays = (tmp_path / "holidays.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(holidays) == len(read(GOLDEN / "smud-r-tod.json")["holidays"])
    assert json.loads(holidays[0])["document_id"] == "smud-r-tod"


def test_export_needs_exactly_one_of_table_and_all(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["export", str(GOLDEN / "smud-r-tod.json")])
    with pytest.raises(SystemExit):
        main(
            [
                "export",
                str(GOLDEN / "smud-r-tod.json"),
                "--table",
                "charges",
                "--all",
                str(tmp_path),
            ]
        )
