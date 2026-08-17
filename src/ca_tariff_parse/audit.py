"""Independent check that nothing reached the output without a citation.

:class:`~ca_tariff_parse.model.Cited` already makes an uncited value impossible
to construct. This module is the second, independent guard: it walks the
serialised result and fails if it can reach a value-bearing leaf that is not
inside a ``Cited`` envelope.

The two mechanisms are deliberately unrelated. If a future recognizer bypasses
the model, or a new field is added to a dataclass and forgotten, this walk still
catches it before the JSON is written.
"""

from __future__ import annotations

from typing import Any

__all__ = ["UncitedValueError", "assert_fully_cited"]


class UncitedValueError(AssertionError):
    """Raised when the output contains a value with no citation behind it."""


#: Keys whose values are structural metadata about the parse rather than facts
#: read out of the source document. Each is restricted to a closed vocabulary
#: or a self describing block, checked below.
STRUCTURAL_KEYS = frozenset(
    {"schema", "parser_version", "disclaimer", "source", "coverage", "unparsed"}
)

#: Controlled vocabularies. A structural field may only hold one of these.
VOCABULARIES: dict[str, frozenset[str]] = {
    "kind": frozenset({"energy_usage", "fixed_charge", "credit"}),
    "currency": frozenset({"USD"}),
    "disposition": frozenset({"included", "excluded", "required"}),
}

#: Keys inside a serialised Cited envelope.
CITED_KEYS = frozenset({"value", "provenance"})


def _is_cited(node: Any) -> bool:
    return (
        isinstance(node, dict)
        and set(node) >= CITED_KEYS
        and isinstance(node.get("provenance"), dict)
    )


def _check_provenance(node: dict[str, Any], path: str) -> None:
    required = ("document_id", "document_sha256", "page", "section", "line", "snippet")
    for field in required:
        if not node.get(field):
            raise UncitedValueError(f"{path}.provenance.{field} is empty or missing")


def _check_structural(key: str, value: Any, path: str) -> None:
    """Validate a field that describes the parse rather than quoting the source."""
    if key in VOCABULARIES:
        if value not in VOCABULARIES[key]:
            raise UncitedValueError(
                f"{path} holds {value!r}, which is outside the controlled "
                f"vocabulary {sorted(VOCABULARIES[key])}"
            )
        return
    if not isinstance(value, bool):
        raise UncitedValueError(f"{path} must be a bool, got {type(value).__name__}")


def _walk_mapping(node: dict[str, Any], path: str) -> None:
    if _is_cited(node):
        _check_provenance(node["provenance"], path)
        return
    for key, value in node.items():
        child = f"{path}.{key}" if path else key
        if key in STRUCTURAL_KEYS:
            continue
        if key in VOCABULARIES or key == "residual":
            _check_structural(key, value, child)
            continue
        _walk(value, child)


def _walk(node: Any, path: str) -> None:
    if isinstance(node, dict):
        _walk_mapping(node, path)
        return

    if isinstance(node, list):
        for index, item in enumerate(node):
            _walk(item, f"{path}[{index}]")
        return

    if node is None:
        return

    raise UncitedValueError(
        f"{path} is a bare {type(node).__name__} ({node!r}) with no citation. "
        "Every emitted value must be wrapped in a Cited envelope."
    )


def assert_fully_cited(payload: dict[str, Any]) -> None:
    """Raise :class:`UncitedValueError` unless every value carries provenance."""
    _walk(payload, "")
