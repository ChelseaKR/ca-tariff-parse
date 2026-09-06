"""Flatten a parse into cited tables.

``parse`` emits one nested document per schedule. An analyst comparing thirty
schedules in a spreadsheet or a notebook wants one row per charge with the
citation beside it, not a tree.

The whole risk of a reshape is that the guarantee does not survive it. A table
of prices with the citations left behind is worse than the JSON, because it
looks like something a reader can act on. So every cited field travels with a
``<field>.locator`` column, and ``document_id``, ``document_sha256`` and
``parser_version`` sit on every row: a row lifted out of its file still says
which bytes of which document it came from.

Two rules keep the tables honest about what they do not contain.

*A null is an empty cell.* Never ``0``, never ``n/a``, never a blank that a
spreadsheet will helpfully total. A charge with no season states no season.

*Nothing is dropped in the reshape.* Each table's row count is checked against
the record count of the parse it came from, and a mismatch raises rather than
writing a short table.

Columns are derived from ``schemas/parsed-schedule-v1.schema.json`` rather than
listed here, so a field added to the model and the schema appears in the export
without anyone remembering to add it, and a field added to only one of them is
a loud failure instead of a silently missing column.

Nothing is computed. There is no annualised price and no hours-per-window
column: the export reshapes what was read, and a derived number in a table of
cited ones would be indistinguishable from them.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "TABLES",
    "ExportError",
    "columns",
    "render_csv",
    "render_jsonl",
    "rows",
    "table_names",
]

#: Columns carried on every row of every table, before the record's own.
#: A row lifted out of its file still names the bytes it was read from.
IDENTITY_COLUMNS = ("document_id", "document_sha256", "parser_version")

#: Where the schema lives relative to the installed package. Read at import
#: time from the repository checkout, and shipped beside the package when
#: installed.
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "parsed-schedule-v1.schema.json"

#: ``$defs`` names that hold a cited scalar rather than a record.
CITED_DEFS = frozenset({"citedString", "citedStringOrNull"})

#: Collections deliberately not exported as tables, and why.
NOT_TABLES = {
    "notes": (
        "notes carry the document's own prose verbatim, one cited string per "
        "line the parser did not consume; they are a reading aid, not records "
        "with fields to put in columns, and a watch baseline omits them "
        "entirely (ADR 0003, ADR 0016)"
    ),
    "unparsed": (
        "an unparsed section reports where the parser stopped, not a value it "
        "read; it carries no citation to flatten and `coverage` is where it is "
        "reported"
    ),
}


class ExportError(ValueError):
    """Raised when a parse cannot be reshaped into the table asked for."""


def _schema() -> Mapping[str, Any]:
    try:
        text = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - only if the package is broken
        raise ExportError(f"cannot read the published schema at {SCHEMA_PATH}: {exc}") from exc
    loaded: Mapping[str, Any] = json.loads(text)
    return loaded


def _ref_name(node: Mapping[str, Any]) -> str | None:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return ref.removeprefix("#/$defs/")
    return None


def _derive_tables(schema: Mapping[str, Any]) -> dict[str, str]:
    """Map each exportable collection to the ``$defs`` name of its record."""
    found: dict[str, str] = {}
    for name, spec in schema.get("properties", {}).items():
        if spec.get("type") != "array":
            continue
        item = _ref_name(spec.get("items", {}))
        if item is None or item in CITED_DEFS:
            continue
        found[name] = item
    for name, why in NOT_TABLES.items():
        if name not in schema.get("properties", {}):
            raise ExportError(
                f"{name} is excluded from the export because {why}, but the schema no longer "
                "declares it. The exclusion is stale and would hide a real table."
            )
        item = found.pop(name, None)
        if item is None:
            continue
        cited = [
            field
            for field, spec in schema["$defs"][item].get("properties", {}).items()
            if _ref_name(spec) in CITED_DEFS
        ]
        if cited:
            raise ExportError(
                f"{name} is excluded from the export as carrying no citations, but "
                f"{item} now cites {', '.join(cited)}. Excluding a table of cited values "
                "would hide them; reconsider the exclusion."
            )
    if not found:
        raise ExportError(
            f"{SCHEMA_PATH} declares no array of records; the export has nothing to derive "
            "its columns from"
        )
    return found


_SCHEMA = _schema()
#: Table name -> the ``$defs`` name of the record it holds, derived from the
#: published schema at import time.
TABLES: dict[str, str] = _derive_tables(_SCHEMA)


def table_names() -> tuple[str, ...]:
    return tuple(TABLES)


def _record_columns(def_name: str, prefix: str, *, snippets: bool) -> list[str]:
    """Columns for one record definition, in the schema's own declaration order."""
    definition = _SCHEMA["$defs"][def_name]
    out: list[str] = []
    for field, spec in definition.get("properties", {}).items():
        path = f"{prefix}{field}"
        ref = _ref_name(spec)
        if ref in CITED_DEFS:
            out.append(path)
            out.append(f"{path}.locator")
            if snippets:
                out.append(f"{path}.snippet")
        elif ref is not None:
            out.extend(_record_columns(ref, f"{path}.", snippets=snippets))
        else:
            out.append(path)
    return out


def columns(table: str, *, snippets: bool = False) -> tuple[str, ...]:
    """The fixed column order for one table.

    Derived from the schema, so it cannot drift from the model. Identity
    columns first, then the record's own fields in declaration order, each
    cited field followed immediately by its locator.
    """
    if table not in TABLES:
        raise ExportError(_unknown_table(table))
    return (*IDENTITY_COLUMNS, *_record_columns(TABLES[table], "", snippets=snippets))


def _unknown_table(table: str) -> str:
    known = ", ".join(TABLES)
    why = NOT_TABLES.get(table)
    if why is not None:
        return f"{table} is not exported as a table: {why}. Tables are: {known}"
    return f"unknown table {table!r}; tables are: {known}"


def _cited_cells(node: Mapping[str, Any], path: str, *, snippets: bool) -> dict[str, Any]:
    provenance = node["provenance"]
    cells: dict[str, Any] = {
        path: node["value"],
        f"{path}.locator": provenance["locator"],
    }
    if snippets:
        cells[f"{path}.snippet"] = provenance["snippet"]
    return cells


def _record_cells(
    record: Mapping[str, Any], def_name: str, prefix: str, *, snippets: bool
) -> dict[str, Any]:
    definition = _SCHEMA["$defs"][def_name]
    cells: dict[str, Any] = {}
    for field, spec in definition.get("properties", {}).items():
        path = f"{prefix}{field}"
        ref = _ref_name(spec)
        held = record.get(field)
        if ref in CITED_DEFS:
            if held is None:
                # Absent, and absent it stays. An empty cell reads as "the
                # document did not state this"; 0 or "n/a" would read as a
                # value someone chose.
                cells[path] = None
                cells[f"{path}.locator"] = None
                if snippets:
                    cells[f"{path}.snippet"] = None
            else:
                cells.update(_cited_cells(held, path, snippets=snippets))
        elif ref is not None:
            if held is None:
                for column in _record_columns(ref, f"{path}.", snippets=snippets):
                    cells[column] = None
            else:
                cells.update(_record_cells(held, ref, f"{path}.", snippets=snippets))
        else:
            cells[path] = held
    return cells


def _primary_provenance(record: Mapping[str, Any], def_name: str) -> Mapping[str, Any] | None:
    """The citation of the record's first cited field, in declaration order."""
    definition = _SCHEMA["$defs"][def_name]
    for field, spec in definition.get("properties", {}).items():
        held = record.get(field)
        if held is None:
            continue
        ref = _ref_name(spec)
        if ref in CITED_DEFS:
            provenance = held.get("provenance")
            return provenance if isinstance(provenance, Mapping) else None
        if ref is not None:
            found = _primary_provenance(held, ref)
            if found is not None:
                return found
    return None


def _sort_key(
    cells: Mapping[str, Any], provenance: Mapping[str, Any] | None, order: Sequence[str]
) -> tuple[Any, ...]:
    """A total order that two exports of one parse cannot disagree about.

    Sorted by the record's first citation, on the citation's own fields rather
    than its rendered text, so page 10 follows page 9 instead of page 1. A row
    with no citation at all sorts last rather than first, and the whole row is
    the final tiebreak, so two records citing the same line never leave the
    order to chance.
    """
    tail = tuple("" if cells.get(name) is None else str(cells[name]) for name in order)
    if provenance is None:
        return (True, "", 0, "", "", 0, tail)
    return (
        False,
        str(provenance.get("document_id") or ""),
        int(provenance.get("page") or 0),
        str(provenance.get("sheet") or ""),
        str(provenance.get("section") or ""),
        int(provenance.get("line") or 0),
        tail,
    )


def rows(payload: Mapping[str, Any], table: str, *, snippets: bool = False) -> list[dict[str, Any]]:
    """One row per record of ``table``, in a deterministic order.

    ``payload`` is ``parse``'s JSON or a watch baseline; both carry the same
    cited records, and the projection removes nothing this reshapes.
    """
    if table not in TABLES:
        raise ExportError(_unknown_table(table))
    records = payload.get(table)
    if not isinstance(records, list):
        raise ExportError(f"payload has no {table} array to export")
    source = payload.get("source")
    if not isinstance(source, Mapping):
        raise ExportError("payload has no source block, so no row could name its document")
    identity = {
        "document_id": source.get("document_id"),
        "document_sha256": source.get("sha256"),
        "parser_version": payload.get("parser_version"),
    }
    missing = [name for name, value in identity.items() if not value]
    if missing:
        raise ExportError(
            f"payload does not state {', '.join(missing)}; every exported row has to name "
            "the document and parser it came from"
        )
    order = columns(table, snippets=snippets)
    definition = TABLES[table]
    decorated = [
        (
            {**identity, **_record_cells(record, definition, "", snippets=snippets)},
            _primary_provenance(record, definition),
        )
        for record in records
    ]
    decorated.sort(key=lambda pair: _sort_key(pair[0], pair[1], order))
    built = [cells for cells, _ in decorated]
    if len(built) != len(records):
        # Unreachable by construction, and asserted anyway: a reshape that
        # loses a row is the one failure a reader of the table cannot see.
        raise ExportError(f"{table}: reshaped {len(built)} rows from {len(records)} records")
    return built


#: Characters that make a spreadsheet treat a cell as a formula.
FORMULA_PREFIXES = ("=", "+", "@", "\t", "\r")


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def neutralise(value: Any) -> str:
    """Render a cell so a spreadsheet cannot read it as a formula.

    A leading minus is left alone when the cell is a number, because a credit
    is printed as ``-0.05`` and prefixing it would change what a reader sees.
    A leading minus on anything else is neutralised.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    if text.startswith(FORMULA_PREFIXES) or (text.startswith("-") and not _is_number(text)):
        return "'" + text
    return text


def render_csv(rendered: Iterable[Mapping[str, Any]], order: Sequence[str]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(order)
    for row in rendered:
        writer.writerow([neutralise(row.get(name)) for name in order])
    return buffer.getvalue()


def render_jsonl(rendered: Iterable[Mapping[str, Any]], order: Sequence[str]) -> str:
    lines = []
    for row in rendered:
        ordered = {name: row.get(name) for name in order}
        lines.append(json.dumps(ordered, ensure_ascii=False, sort_keys=False))
    return "".join(f"{line}\n" for line in lines)
