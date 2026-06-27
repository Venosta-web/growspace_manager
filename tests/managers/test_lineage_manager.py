
from custom_components.growspace_manager.managers.lineage import StrainLineageManager

STRAINS = {
    "Gelato": {
        "meta": {
            "lineage_tree": [
                {"name": "Sunset Sherbet", "source": "library"},
                {"name": "Thin Mint GSC", "source": "manual"},
            ],
            "generation": "F1",
        },
        "phenotypes": {},
    },
    "Sunset Sherbet": {
        "meta": {"lineage_tree": [], "generation": ""},
        "phenotypes": {},
    },
}


CYCLIC_STRAINS = {
    "A": {"meta": {"lineage_tree": [{"name": "B", "source": "library"}]}, "phenotypes": {}},
    "B": {"meta": {"lineage_tree": [{"name": "A", "source": "library"}]}, "phenotypes": {}},
}


def test_get_strain_lineage_tree_cycle_does_not_infinite_loop() -> None:
    manager = StrainLineageManager(CYCLIC_STRAINS, db=None)
    tree = manager.get_strain_lineage_tree("A")
    assert tree["name"] == "A"
    b_node = tree["parents"][0]
    assert b_node["name"] == "B"
    # A appears as B's parent but is returned as a leaf — cycle cut here
    a_back = b_node["parents"][0]
    assert a_back["name"] == "A"
    assert a_back["parents"] == []


def test_get_strain_lineage_tree_resolves_library_parent() -> None:
    manager = StrainLineageManager(STRAINS, db=None)
    tree = manager.get_strain_lineage_tree("Gelato")

    assert tree["name"] == "Gelato"
    assert len(tree["parents"]) == 2
    library_parent = tree["parents"][0]
    assert library_parent["name"] == "Sunset Sherbet"
    assert library_parent["source"] == "library"
    manual_parent = tree["parents"][1]
    assert manual_parent["name"] == "Thin Mint GSC"
    assert manual_parent["source"] == "manual"
    assert manual_parent["parents"] == []
