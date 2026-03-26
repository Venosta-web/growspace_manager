"""Tests for plant scoring services."""

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.const import ATTR_PLANT_ID
from custom_components.growspace_manager.models import Plant, PlantGenetics
from custom_components.growspace_manager.schemas import SCORE_PLANT_SCHEMA
from custom_components.growspace_manager.services.plant import handle_score_plant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass():
    """Mock Home Assistant."""
    return AsyncMock()


@pytest.fixture
def mock_coordinator():
    """Mock Growspace Coordinator."""
    coordinator = AsyncMock()

    # Create a mock plant to be updated
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    coordinator.plants = {"test_plant_1": plant}
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Mock Strain Library."""
    return AsyncMock()


def test_score_plant_schema_accepts_null_scores():
    """Schema must accept None for score fields (frontend sends null for unset scores)."""
    result = SCORE_PLANT_SCHEMA({"plant_id": "abc", "vigor": None, "structure": None})
    assert result["vigor"] is None
    assert result["structure"] is None


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
    """Test scoring a plant with all fields."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": 5,
        "structure": 4,
        "aroma": 3,
        "resin": 2,
        "pest_resistance": 1,
    }

    # Run the handler
    with patch(
        "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    # Check that update_plant was called
    mock_coordinator.plant_manager.update_plant.assert_called_once()

    # Verify the phenotype_score object passed to update_plant (new field names)
    call_args = mock_coordinator.plant_manager.update_plant.call_args[1]
    assert "phenotype_score" in call_args
    ps = call_args["phenotype_score"]

    assert ps.vigor == 5
    assert ps.internodal_spacing == 4   # legacy 'structure'
    assert ps.terpene_intensity == 3    # legacy 'aroma'
    assert ps.resin == 2
    assert ps.mold_resistance == 1      # legacy 'pest_resistance'


@pytest.mark.asyncio
async def test_handle_score_plant_partial(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating only some scores."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": 5,
    }

    plant = mock_coordinator.plants["test_plant_1"]
    plant.phenotype_score.internodal_spacing = 3  # Pretend previously set

    with patch(
        "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator.plant_manager.update_plant.assert_called_once()

    call_args = mock_coordinator.plant_manager.update_plant.call_args[1]
    ps = call_args["phenotype_score"]

    assert ps.vigor == 5
    assert ps.internodal_spacing == 3  # Retained
    assert ps.terpene_intensity is None


@pytest.mark.asyncio
async def test_handle_score_plant_clear_fields(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test clearing scores by sending None."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        "vigor": None,
        "aroma": None,
    }

    plant = mock_coordinator.plants["test_plant_1"]
    plant.phenotype_score.vigor = 5
    plant.phenotype_score.terpene_intensity = 4
    plant.phenotype_score.resin = 3

    with patch(
        "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_score_plant(mock_hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator.plant_manager.update_plant.assert_called_once()

    call_args = mock_coordinator.plant_manager.update_plant.call_args[1]
    ps = call_args["phenotype_score"]

    assert ps.vigor is None
    assert ps.terpene_intensity is None
    assert ps.resin == 3  # Unchanged


@pytest.mark.asyncio
async def test_handle_score_plant_not_found(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test scoring a plant that does not exist in the coordinator."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "missing_plant",
        "vigor": 5,
    }

    # The plant is missing
    assert "missing_plant" not in mock_coordinator.plants

    with patch(
        "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        with pytest.raises(
            ServiceValidationError, match="Plant missing_plant not found"
        ):
            await handle_score_plant(
                mock_hass, mock_coordinator, mock_strain_library, call
            )
