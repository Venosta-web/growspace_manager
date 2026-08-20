from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_update_strain_lineage_tree_stores_parents_and_derives_flat_lineage():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()
    lib.load = AsyncMock()

    parents = [
        {"name": "OG Kush", "source": "library"},
        {"name": "Durban Poison", "source": "manual"},
    ]
    result = await lib.update_strain_lineage_tree("Gelato #41", parents)

    assert result == "OG Kush × Durban Poison"
    assert lib._db.execute.called
    call_args = lib._db.execute.call_args_list
    sql_calls = [str(c) for c in call_args]
    assert any("lineage_tree" in s for s in sql_calls)

@pytest.mark.asyncio
async def test_update_strain_lineage_tree_single_parent():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()
    lib.load = AsyncMock()

    parents = [{"name": "OG Kush", "source": "library"}]
    result = await lib.update_strain_lineage_tree("Mystery", parents)
    assert result == "OG Kush"

@pytest.mark.asyncio
async def test_update_strain_lineage_tree_empty_parents():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()
    lib.load = AsyncMock()

    result = await lib.update_strain_lineage_tree("Unknown", [])
    assert result == ""


@pytest.mark.asyncio
async def test_update_strain_lineage_tree_no_db_returns_empty():
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = None

    result = await lib.update_strain_lineage_tree("X", [{"name": "Y", "source": "manual"}])
    assert result == ""


def test_get_strain_lineage_tree_no_lineage_tree():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test.db"
    lib = StrainLibrary(hass)
    lib.strains = {"OG Kush": {"meta": {}, "phenotypes": {}}}

    result = lib.get_strain_lineage_tree("OG Kush")
    assert result == {"name": "OG Kush", "source": "library", "parents": [], "generation": ""}

def test_get_strain_lineage_tree_resolves_library_parents():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test.db"
    lib = StrainLibrary(hass)
    lib.strains = {
        "Gelato #41": {
            "meta": {
                "lineage_tree": [
                    {"name": "Sunset Sherbet", "source": "library"},
                    {"name": "Thin Mint GSC", "source": "library"},
                ]
            },
            "phenotypes": {},
        },
        "Sunset Sherbet": {"meta": {}, "phenotypes": {}},
        "Thin Mint GSC": {"meta": {}, "phenotypes": {}},
    }

    result = lib.get_strain_lineage_tree("Gelato #41")
    assert result["name"] == "Gelato #41"
    assert len(result["parents"]) == 2
    assert result["parents"][0]["name"] == "Sunset Sherbet"
    assert result["parents"][0]["parents"] == []

def test_get_strain_lineage_tree_cycle_protection():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test.db"
    lib = StrainLibrary(hass)
    # A references B, B references A
    lib.strains = {
        "A": {"meta": {"lineage_tree": [{"name": "B", "source": "library"}]}, "phenotypes": {}},
        "B": {"meta": {"lineage_tree": [{"name": "A", "source": "library"}]}, "phenotypes": {}},
    }
    result = lib.get_strain_lineage_tree("A")
    # Should terminate without infinite recursion
    assert result["name"] == "A"
    assert result["parents"][0]["name"] == "B"
    # A appears as a leaf inside B (cycle caught by _seen at depth guard)
    assert result["parents"][0]["parents"] == [{"name": "A", "source": "library", "parents": [], "generation": ""}]

def test_get_strain_lineage_tree_manual_parent_is_leaf():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test.db"
    lib = StrainLibrary(hass)
    lib.strains = {
        "Hybrid X": {
            "meta": {
                "lineage_tree": [
                    {"name": "OG Kush", "source": "manual"},
                ]
            },
            "phenotypes": {},
        },
    }
    result = lib.get_strain_lineage_tree("Hybrid X")
    assert result["parents"][0] == {"name": "OG Kush", "source": "manual", "parents": []}

def test_get_strain_names_returns_sorted_list():
    from custom_components.growspace_manager.strain_library import StrainLibrary
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test.db"
    lib = StrainLibrary(hass)
    lib.strains = {
        "Gelato #41": {"meta": {}, "phenotypes": {}},
        "OG Kush": {"meta": {}, "phenotypes": {}},
        "Blue Dream": {"meta": {}, "phenotypes": {}},
    }
    result = lib.get_strain_names()
    assert result == ["Blue Dream", "Gelato #41", "OG Kush"]


@pytest.mark.asyncio
async def test_async_update_strain_generation_executes_sql():
    """async_update_strain_generation writes generation tag to DB."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()

    await lib.async_update_strain_generation("OG Kush F1", "F1")

    lib._db.execute.assert_called_once()
    call_args = lib._db.execute.call_args
    assert "generation" in call_args[0][0]
    assert "OG Kush F1" in call_args[0][1]
    assert "F1" in call_args[0][1]
    lib._db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_strain_generation_noop_when_db_none():
    """Gracefully does nothing when DB is not connected."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = None

    # Must not raise
    await lib.async_update_strain_generation("Some Strain", "BX")


@pytest.mark.asyncio
async def test_async_update_strain_generation_updates_in_memory_cache():
    """async_update_strain_generation also updates the in-memory strains cache."""
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()

    # Pre-populate in-memory strains cache
    lib.strains = {"OG Kush": {"meta": {}}}

    await lib.async_update_strain_generation("OG Kush", "BX")

    assert lib.strains["OG Kush"]["meta"]["generation"] == "BX"


@pytest.mark.asyncio
async def test_async_import_seedfinder_lineage_tree_creates_stubs_and_stores_lineage():
    """Full multi-level seedfinder tree creates ancestor stubs and wires each node's parents."""

    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = AsyncMock()
    lib._db.execute = AsyncMock()
    lib._db.commit = AsyncMock()
    lib.load = AsyncMock()
    lib._lineage_cache = {}

    # Root already in library; ancestors are not
    lib.strains = {"Chem Cake": {"meta": {}, "phenotypes": {}}}

    tree = {
        "name": "Chem Cake",
        "parents": [
            {
                "name": "Chemdog",
                "parents": [],
            },
            {
                "name": "Wedding Cake",
                "parents": [
                    {"name": "Triangle Mints", "parents": []},
                    {"name": "Animal Mints", "parents": []},
                ],
            },
        ],
    }

    await lib.async_import_seedfinder_lineage_tree("Chem Cake", tree)

    all_sqls = [str(c) for c in lib._db.execute.call_args_list]

    # Stubs created for all non-root ancestors not in library
    stub_names = ["Chemdog", "Wedding Cake", "Triangle Mints", "Animal Mints"]
    for name in stub_names:
        assert any(name in s for s in all_sqls), f"No stub INSERT found for {name}"

    # lineage_tree stored for nodes with parents: Chem Cake and Wedding Cake
    update_calls = [c for c in all_sqls if "lineage_tree" in c]
    assert len(update_calls) >= 2

    assert lib._db.commit.call_count >= 1
    lib.load.assert_called_once()


@pytest.mark.asyncio
async def test_async_import_seedfinder_lineage_tree_noop_when_db_none():
    """Silently does nothing when DB is not connected."""
    from custom_components.growspace_manager.strain_library import StrainLibrary

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = None
    lib.strains = {}

    # Must not raise
    await lib.async_import_seedfinder_lineage_tree("X", {"name": "X", "parents": [{"name": "Y", "parents": []}]})
