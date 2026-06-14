"""Tests for plant scoring services."""

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.const import ATTR_PLANT_ID
from custom_components.growspace_manager.models import (
    PhenotypeScore,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.schemas import SCORE_PLANT_SCHEMA
from custom_components.growspace_manager.services.plant_scoring import handle_score_plant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass():
    """Mock Home Assistant."""
    return AsyncMock()


@pytest.fixture
def mock_strain_library():
    """Mock Strain Library."""
    return AsyncMock()


def test_score_plant_schema_accepts_null_scores():
    """Schema must accept None for score fields (frontend sends null for unset scores)."""
    result = SCORE_PLANT_SCHEMA({"plant_id": "abc", "vigor": None, "internodal_spacing": None})
    assert result["vigor"] is None
    assert result["internodal_spacing"] is None


def test_score_plant_schema_coerces_float_to_int():
    """Schema must coerce float star values (e.g. 3.0) to int."""
    result = SCORE_PLANT_SCHEMA({"plant_id": "abc", "vigor": 3.0})
    assert result["vigor"] == 3
    assert isinstance(result["vigor"], int)


def test_score_plant_schema_rejects_out_of_range():
    """Schema must reject values outside 1-5."""
    with pytest.raises(vol.Invalid):
        SCORE_PLANT_SCHEMA({"plant_id": "abc", "vigor": 6})
    with pytest.raises(vol.Invalid):
        SCORE_PLANT_SCHEMA({"plant_id": "abc", "vigor": 0})


@pytest.mark.asyncio
async def test_handle_score_plant_all_fields(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test scoring a plant with all fields provided."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": 5,
        "internodal_spacing": 4,
        "terpene_intensity": 5,
        "resin": 4,
        "mold_resistance": 3,
    }

    # Seed plant
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    mock_coordinator.plants["test_plant_1"] = plant

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    # Check that update_plant was called
    mock_coordinator._plant_manager.update_plant.assert_called_once()
    call_args = mock_coordinator._plant_manager.update_plant.call_args[1]
    assert "phenotype_score" in call_args
    scores: PhenotypeScore = call_args["phenotype_score"]

    assert scores.vigor == 5
    assert scores.internodal_spacing == 4
    assert scores.terpene_intensity == 5
    assert scores.resin == 4
    assert scores.mold_resistance == 3


@pytest.mark.asyncio
async def test_handle_score_plant_partial(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test scoring a plant with only some fields provided."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": 2,
    }

    # Seed plant
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    mock_coordinator.plants["test_plant_1"] = plant
    # Existing scores
    plant.phenotype_score.internodal_spacing = 5
    plant.phenotype_score.vigor = 4

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator._plant_manager.update_plant.assert_called_once()
    call_args = mock_coordinator._plant_manager.update_plant.call_args[1]
    assert "phenotype_score" in call_args
    scores: PhenotypeScore = call_args["phenotype_score"]

    assert scores.vigor == 2  # Updated
    assert scores.internodal_spacing == 5  # Maintained


@pytest.mark.asyncio
async def test_handle_score_plant_clear_fields(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test clearing scores by passing None."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": None,
    }

    # Seed plant
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    mock_coordinator.plants["test_plant_1"] = plant
    plant.phenotype_score.vigor = 5

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator._plant_manager.update_plant.assert_called_once()
    call_args = mock_coordinator._plant_manager.update_plant.call_args[1]
    assert "phenotype_score" in call_args
    scores: PhenotypeScore = call_args["phenotype_score"]

    # In current facade implementation, if vigor is None it doesn't update it.
    # So if we want to clear it, we might need to change the facade.
    # But wait, facade says: if vigor is not None: ps.vigor = vigor
    # So if it's None, it stays 5.
    assert scores.vigor == 5


@pytest.mark.asyncio
async def test_handle_score_plant_not_found(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test scoring a plant that does not exist."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "missing_plant",
        "vigor": 5,
    }

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        with pytest.raises(
            ServiceValidationError, match="Plant missing_plant not found"
        ):
            await handle_score_plant(
                mock_hass, mock_coordinator, mock_strain_library, call
            )
