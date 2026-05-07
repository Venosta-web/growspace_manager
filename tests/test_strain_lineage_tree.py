import pytest
from unittest.mock import AsyncMock, MagicMock

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
    assert result == {"name": "OG Kush", "source": "library", "parents": []}

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
    assert result["parents"][0]["parents"] == [{"name": "A", "source": "library", "parents": []}]

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
    from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_async_update_strain_generation_noop_when_db_none():
    """Gracefully does nothing when DB is not connected."""
    from custom_components.growspace_manager.strain_library import StrainLibrary
    from unittest.mock import MagicMock

    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_strain_lib.db"
    lib = StrainLibrary(hass)
    lib._db = None

    # Must not raise
    await lib.async_update_strain_generation("Some Strain", "BX")
