"""Tests for lineage_classifier — pure functions, no HA dependencies."""
from __future__ import annotations

import pytest
from typing import Any

from custom_components.growspace_manager.managers.lineage_classifier import (
    classify_lineage,
    _is_ancestor,
)


def test_is_ancestor_direct_parent():
    tree = {"name": "Child", "parents": [{"name": "Parent A", "parents": []}]}
    assert _is_ancestor("Parent A", tree) is True


def test_is_ancestor_grandparent():
    tree = {
        "name": "Child",
        "parents": [
            {
                "name": "F1",
                "parents": [
                    {"name": "Grandparent", "parents": []},
                ],
            }
        ],
    }
    assert _is_ancestor("Grandparent", tree) is True


def test_is_ancestor_not_present():
    tree = {"name": "Child", "parents": [{"name": "Unrelated", "parents": []}]}
    assert _is_ancestor("Missing", tree) is False


def test_is_ancestor_cycle_safe():
    node_a: dict[str, Any] = {"name": "A", "parents": []}
    node_b: dict[str, Any] = {"name": "B", "parents": [node_a]}
    node_a["parents"] = [node_b]
    assert _is_ancestor("X", node_a) is False


def test_is_ancestor_empty_parents():
    tree = {"name": "Root", "parents": []}
    assert _is_ancestor("Anyone", tree) is False


def test_classify_s1_same_name():
    tree = {"name": "Strain A", "parents": []}
    assert classify_lineage("Strain A", "Strain A", tree, tree) == "S1"


def test_classify_bx_parent_is_direct_ancestor_of_child():
    mother_tree = {"name": "OG Kush", "parents": []}
    f1_tree = {
        "name": "OG x Diesel",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Sour Diesel", "parents": []},
        ],
    }
    assert classify_lineage("OG Kush", "OG x Diesel", mother_tree, f1_tree) == "BX"


def test_classify_bx_child_is_crossed_to_grandparent():
    grandparent_tree = {"name": "Skunk #1", "parents": []}
    f2_tree = {
        "name": "Deep Cross",
        "parents": [
            {
                "name": "Mid Gen",
                "parents": [{"name": "Skunk #1", "parents": []}],
            }
        ],
    }
    assert classify_lineage("Skunk #1", "Deep Cross", grandparent_tree, f2_tree) == "BX"


def test_classify_f2_siblings_share_identical_parents():
    sibling_a = {
        "name": "Sib A",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Gelato", "parents": []},
        ],
    }
    sibling_b = {
        "name": "Sib B",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Gelato", "parents": []},
        ],
    }
    assert classify_lineage("Sib A", "Sib B", sibling_a, sibling_b) == "F2"


def test_classify_f2_not_triggered_when_parents_differ():
    plant_a = {
        "name": "A",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Gelato", "parents": []},
        ],
    }
    plant_b = {
        "name": "B",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Sour Diesel", "parents": []},
        ],
    }
    assert classify_lineage("A", "B", plant_a, plant_b) == "F1"


def test_classify_f1_no_shared_ancestry():
    tree_a = {"name": "OG Kush", "parents": []}
    tree_b = {"name": "Durban Poison", "parents": []}
    assert classify_lineage("OG Kush", "Durban Poison", tree_a, tree_b) == "F1"


def test_classify_f1_fallback_empty_parents():
    tree_a = {"name": "Unknown A", "parents": []}
    tree_b = {"name": "Unknown B", "parents": []}
    assert classify_lineage("Unknown A", "Unknown B", tree_a, tree_b) == "F1"


def test_classify_s1_takes_priority_over_ancestor_check():
    tree = {
        "name": "Strain",
        "parents": [{"name": "Strain", "parents": []}],
    }
    assert classify_lineage("Strain", "Strain", tree, tree) == "S1"
