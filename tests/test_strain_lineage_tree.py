import pytest
from unittest.mock import AsyncMock, MagicMock
import json

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
