"""Pure functions for classifying cannabis cross types from lineage trees."""

from __future__ import annotations

import re
from typing import Any


def _parse_generation(gen_str: str) -> tuple[str, int]:
    """Extract the generation prefix and number from a generation string.

    Examples: "F2" -> ("F", 2), "S1" -> ("S", 1), "BX" -> ("BX", 1)
    """
    if not gen_str:
        return "F", 1
    match = re.match(r"([A-Za-z]+)(\d*)", str(gen_str).upper())
    if match:
        g_type = match.group(1)
        g_num = int(match.group(2)) if match.group(2) else 1
        return g_type, g_num
    return "F", 1


def classify_lineage(
    parent_a: str,
    parent_b: str,
    tree_a: dict[str, Any],
    tree_b: dict[str, Any],
) -> str:
    """Return the cumulative genetic cross classification for two parents.

    Args:
        parent_a: Name/ID of the first parent.
        parent_b: Name/ID of the second parent.
        tree_a: Pre-resolved lineage tree — {name, parents: [...], generation: "F2"}.
        tree_b: Pre-resolved lineage tree — same format.

    Returns:
        Progressive generation string: "S1"/"S2"/..., "BX1"/"BX2"/...,
        "F2"/"F3"/..., or "F1".
    """
    # Selfing (Sx): crossing a plant with itself
    if parent_a == parent_b:
        g_type, g_num = _parse_generation(tree_a.get("generation", ""))
        if g_type == "S":
            return f"S{g_num + 1}"
        return "S1"

    # Backcrossing (BXx): crossing offspring back to an ancestor
    is_a_ancestor = _is_ancestor(parent_a, tree_b)
    is_b_ancestor = _is_ancestor(parent_b, tree_a)
    if is_a_ancestor or is_b_ancestor:
        progeny_tree = tree_b if is_a_ancestor else tree_a
        g_type, g_num = _parse_generation(progeny_tree.get("generation", ""))
        if g_type == "BX":
            return f"BX{g_num + 1}"
        return "BX1"

    # Filial generations (Fx): crossing siblings from the same parents
    parents_a = {p["name"] for p in tree_a.get("parents", [])}
    parents_b = {p["name"] for p in tree_b.get("parents", [])}
    if parents_a and parents_b and parents_a == parents_b:
        g_type_a, g_num_a = _parse_generation(tree_a.get("generation", ""))
        g_type_b, g_num_b = _parse_generation(tree_b.get("generation", ""))
        if g_type_a == "F" and g_type_b == "F":
            return f"F{max(g_num_a, g_num_b) + 1}"
        return "F2"

    # Outcross: two entirely different lines
    return "F1"


def _is_ancestor(
    name: str,
    tree: dict[str, Any],
    visited: frozenset[str] | None = None,
) -> bool:
    """Return True if name appears in the parent nodes of *tree*, or their ancestors.

    Does not match the root node itself — callers handle identity via S1 check.
    Cycle-safe via immutable visited set.
    """
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
