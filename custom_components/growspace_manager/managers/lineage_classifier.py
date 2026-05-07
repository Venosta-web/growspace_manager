"""Pure functions for classifying cannabis cross types from lineage trees."""
from __future__ import annotations

from typing import Any


def classify_lineage(
    parent_a: str,
    parent_b: str,
    tree_a: dict[str, Any],
    tree_b: dict[str, Any],
) -> str:
    """Return the genetic cross classification for two parents.

    Args:
        parent_a: Name/ID of the first parent.
        parent_b: Name/ID of the second parent.
        tree_a: Pre-resolved lineage tree for parent_a — {name, parents: [...]}.
        tree_b: Pre-resolved lineage tree for parent_b — same format.

    Returns:
        "S1", "BX", "F2", or "F1" in that priority order.
    """
    if parent_a == parent_b:
        return "S1"
    if _is_ancestor(parent_a, tree_b) or _is_ancestor(parent_b, tree_a):
        return "BX"
    parents_a = {p["name"] for p in tree_a.get("parents", [])}
    parents_b = {p["name"] for p in tree_b.get("parents", [])}
    if parents_a and parents_b and parents_a == parents_b:
        return "F2"
    return "F1"


def _is_ancestor(
    name: str,
    tree: dict[str, Any],
    visited: frozenset[str] | None = None,
) -> bool:
    """Return True if name appears anywhere in tree's ancestry (cycle-safe)."""
    if visited is None:
        visited = frozenset()
    node_name = tree.get("name", "")
    if node_name in visited:
        return False
    visited = visited | {node_name}
    for parent in tree.get("parents", []):
        if parent.get("name") == name:
            return True
        if _is_ancestor(name, parent, visited):
            return True
    return False
