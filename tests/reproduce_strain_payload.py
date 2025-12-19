import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_get_all_excludes_base64(hass: HomeAssistant):
    """Test that get_all does not return image_base64."""
    library = StrainLibrary(hass)

    # Mock database connection and execution
    library._db = MagicMock()
    library._db.execute = MagicMock()

    # Simulation of DB rows. Note: schema doesn't have image_base64,
    # but let's ensure code doesn't magically inject it from somewhere else.
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [
        {
            "strain_id": 1,
            "strain_name": "TestStrain",
            "breeder": "TestBreeder",
            "type": "Hybrid",
            "lineage": "A x B",
            "sex": "Feminized",
            "sativa_percentage": 50,
            "indica_percentage": 50,
            "phenotype_id": 101,
            "phenotype_name": "Pheno1",
            "description": "Tasty",
            "image_path": "/local/images/test.jpg",
            "image_crop_meta": None,
            "flower_days_min": 60,
            "flower_days_max": 70,
        }
    ]

    # We need to mock the context manager for execute
    execute_ctx = AsyncMock()
    execute_ctx.__aenter__.return_value = mock_cursor
    library._db.execute.return_value = execute_ctx

    # Mock harvests query (empty)
    harvests_cursor = AsyncMock()
    harvests_cursor.__aiter__.return_value = []

    # We need side_effect to handle different queries
    def execute_side_effect(query, params=None):
        if "harvests" in query:
            ctx = AsyncMock()
            ctx.__aenter__.return_value = harvests_cursor
            return ctx
        # Default to strains query
        return execute_ctx

    library._db.execute.side_effect = execute_side_effect

    await library.load()

    all_strains = library.get_all()
    assert "TestStrain" in all_strains
    pheno = all_strains["TestStrain"]["phenotypes"]["Pheno1"]

    # Assertions
    assert "image_base64" not in pheno
    assert "image_base64" not in all_strains["TestStrain"]
    assert pheno["image_path"] == "/local/images/test.jpg"
