"""Tests for lineage_classifier — pure functions, no HA dependencies."""

from __future__ import annotations

from typing import Any

from custom_components.growspace_manager.managers.lineage_classifier import (
    _is_ancestor,
    _parse_generation,
    classify_lineage,
)

# ---------------------------------------------------------------------------
# _parse_generation
# ---------------------------------------------------------------------------


def test_parse_generation_f2():
    assert _parse_generation("F2") == ("F", 2)


def test_parse_generation_s1():
    assert _parse_generation("S1") == ("S", 1)


def test_parse_generation_bx_no_number():
    assert _parse_generation("BX") == ("BX", 1)


def test_parse_generation_bx2():
    assert _parse_generation("BX2") == ("BX", 2)


def test_parse_generation_empty():
    assert _parse_generation("") == ("F", 1)


def test_parse_generation_lowercase():
    assert _parse_generation("f3") == ("F", 3)


# ---------------------------------------------------------------------------
# _is_ancestor
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# classify_lineage — selfing (Sx)
# ---------------------------------------------------------------------------


def test_classify_s1_same_name():
    tree = {"name": "Strain A", "parents": [], "generation": ""}
    assert classify_lineage("Strain A", "Strain A", tree, tree) == "S1"


def test_classify_s1_from_f1_parent():
    tree = {"name": "F1 Plant", "parents": [], "generation": "F1"}
    assert classify_lineage("F1 Plant", "F1 Plant", tree, tree) == "S1"


def test_classify_s2_from_s1_parent():
    tree = {"name": "S1 Plant", "parents": [], "generation": "S1"}
    assert classify_lineage("S1 Plant", "S1 Plant", tree, tree) == "S2"


def test_classify_s3_from_s2_parent():
    tree = {"name": "S2 Plant", "parents": [], "generation": "S2"}
    assert classify_lineage("S2 Plant", "S2 Plant", tree, tree) == "S3"


def test_classify_s1_takes_priority_over_ancestor_check():
    tree = {
        "name": "Strain",
        "parents": [{"name": "Strain", "parents": []}],
        "generation": "",
    }
    assert classify_lineage("Strain", "Strain", tree, tree) == "S1"


# ---------------------------------------------------------------------------
# classify_lineage — backcrossing (BXx)
# ---------------------------------------------------------------------------


def test_classify_bx1_parent_is_direct_ancestor_of_child():
    mother_tree = {"name": "OG Kush", "parents": [], "generation": ""}
    f1_tree = {
        "name": "OG x Diesel",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Sour Diesel", "parents": []},
        ],
        "generation": "F1",
    }
    assert classify_lineage("OG Kush", "OG x Diesel", mother_tree, f1_tree) == "BX1"


def test_classify_bx1_child_is_crossed_to_grandparent():
    grandparent_tree = {"name": "Skunk #1", "parents": [], "generation": ""}
    f2_tree = {
        "name": "Deep Cross",
        "parents": [
            {
                "name": "Mid Gen",
                "parents": [{"name": "Skunk #1", "parents": []}],
            }
        ],
        "generation": "F2",
    }
    assert (
        classify_lineage("Skunk #1", "Deep Cross", grandparent_tree, f2_tree) == "BX1"
    )


def test_classify_bx2_from_bx1_progeny():
    recurrent_parent = {"name": "OG Kush", "parents": [], "generation": ""}
    bx1_tree = {
        "name": "BX1 Plant",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "F1 Plant", "parents": []},
        ],
        "generation": "BX1",
    }
    assert classify_lineage("OG Kush", "BX1 Plant", recurrent_parent, bx1_tree) == "BX2"


def test_classify_bx3_from_bx2_progeny():
    recurrent_parent = {"name": "OG Kush", "parents": [], "generation": ""}
    bx2_tree = {
        "name": "BX2 Plant",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "BX1 Plant", "parents": []},
        ],
        "generation": "BX2",
    }
    assert classify_lineage("OG Kush", "BX2 Plant", recurrent_parent, bx2_tree) == "BX3"


def test_classify_bx1_legacy_bx_string_treated_as_bx1():
    """Existing stored 'BX' data should increment to BX2."""
    recurrent_parent = {"name": "OG Kush", "parents": [], "generation": ""}
    bx_tree = {
        "name": "BX Plant",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "F1 Plant", "parents": []},
        ],
        "generation": "BX",
    }
    assert classify_lineage("OG Kush", "BX Plant", recurrent_parent, bx_tree) == "BX2"


# ---------------------------------------------------------------------------
# classify_lineage — filial generations (Fx)
# ---------------------------------------------------------------------------


def test_classify_f2_siblings_share_identical_parents():
    sibling_a = {
        "name": "Sib A",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Gelato", "parents": []},
        ],
        "generation": "F1",
    }
    sibling_b = {
        "name": "Sib B",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Gelato", "parents": []},
        ],
        "generation": "F1",
    }
    assert classify_lineage("Sib A", "Sib B", sibling_a, sibling_b) == "F2"


def test_classify_f3_from_f2_siblings():
    sibling_a = {
        "name": "F2 Sib A",
        "parents": [
            {"name": "F1 Parent 1", "parents": []},
            {"name": "F1 Parent 2", "parents": []},
        ],
        "generation": "F2",
    }
    sibling_b = {
        "name": "F2 Sib B",
        "parents": [
            {"name": "F1 Parent 1", "parents": []},
            {"name": "F1 Parent 2", "parents": []},
        ],
        "generation": "F2",
    }
    assert classify_lineage("F2 Sib A", "F2 Sib B", sibling_a, sibling_b) == "F3"


def test_classify_f4_from_f3_siblings():
    sibling_a = {
        "name": "F3 Sib A",
        "parents": [
            {"name": "F2 Parent 1", "parents": []},
            {"name": "F2 Parent 2", "parents": []},
        ],
        "generation": "F3",
    }
    sibling_b = {
        "name": "F3 Sib B",
        "parents": [
            {"name": "F2 Parent 1", "parents": []},
            {"name": "F2 Parent 2", "parents": []},
        ],
        "generation": "F3",
    }
    assert classify_lineage("F3 Sib A", "F3 Sib B", sibling_a, sibling_b) == "F4"


def test_classify_f2_no_generation_field_falls_back():
    """Missing generation field falls back to F2 for sibling crosses."""
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
        "generation": "F1",
    }
    plant_b = {
        "name": "B",
        "parents": [
            {"name": "OG Kush", "parents": []},
            {"name": "Sour Diesel", "parents": []},
        ],
        "generation": "F1",
    }
    assert classify_lineage("A", "B", plant_a, plant_b) == "F1"


# ---------------------------------------------------------------------------
# classify_lineage — outcross (F1)
# ---------------------------------------------------------------------------


def test_classify_f1_no_shared_ancestry():
    tree_a = {"name": "OG Kush", "parents": [], "generation": ""}
    tree_b = {"name": "Durban Poison", "parents": [], "generation": ""}
    assert classify_lineage("OG Kush", "Durban Poison", tree_a, tree_b) == "F1"


def test_classify_f1_fallback_empty_parents():
    tree_a = {"name": "Unknown A", "parents": [], "generation": ""}
    tree_b = {"name": "Unknown B", "parents": [], "generation": ""}
    assert classify_lineage("Unknown A", "Unknown B", tree_a, tree_b) == "F1"
