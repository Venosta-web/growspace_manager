"""Tests for Growspace Manager plant metrics services."""
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_CBD_PERCENTAGE,
    ATTR_DRY_WEIGHT,
    ATTR_PLANT_ID,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRIM_WEIGHT,
    ATTR_WET_WEIGHT,
)
from custom_components.growspace_manager.models import (
    HarvestMetrics,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.services.plant_scoring import (
    handle_update_harvest_metrics,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant."""
    return AsyncMock()


@pytest.fixture
def mock_strain_library():
    """Mock Strain Library."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_handle_update_harvest_metrics_success(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating harvest metrics for a plant."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        ATTR_WET_WEIGHT: 45.5,
        ATTR_DRY_WEIGHT: 12.2,
        ATTR_TRIM_WEIGHT: 3.1,
        ATTR_THC_PERCENTAGE: 22.5,
        ATTR_CBD_PERCENTAGE: 1.0,
        ATTR_TERPENE_PROFILE: "Myrcene, Limonene",
    }

    # Seed plant
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    mock_coordinator.plants["test_plant_1"] = plant

    # Run the handler
    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_update_harvest_metrics(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    # Check that update_plant was called with the correct harvest metrics
    mock_coordinator.plant_manager.update_plant.assert_called_once()

    # Extract the harvest_metrics kwarg passed to update_plant
    call_args = mock_coordinator.plant_manager.update_plant.call_args[1]
    assert "harvest_metrics" in call_args
    metrics: HarvestMetrics = call_args["harvest_metrics"]

    assert metrics.wet_weight == 45.5
    assert metrics.dry_weight == 12.2
    assert metrics.trim_weight == 3.1
    assert metrics.thc_percentage == 22.5
    assert metrics.cbd_percentage == 1.0
    assert metrics.terpene_profile == "Myrcene, Limonene"


@pytest.mark.asyncio
async def test_handle_update_harvest_metrics_partial(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating only some harvest metrics."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "test_plant_1",
        ATTR_WET_WEIGHT: 50.0,
    }

    # Seed plant
    plant = Plant(
        plant_id="test_plant_1",
        growspace_id="test_gs",
        genetics=PlantGenetics(strain_name="Test Strain"),
        stage="dry",
    )
    mock_coordinator.plants["test_plant_1"] = plant
    plant.harvest_metrics.dry_weight = 10.0  # Pretend this was set previously

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        await handle_update_harvest_metrics(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

    # Check that update_plant was called with the correct harvest metrics
    mock_coordinator.plant_manager.update_plant.assert_called_once()

    call_args = mock_coordinator.plant_manager.update_plant.call_args[1]
    assert "harvest_metrics" in call_args
    metrics: HarvestMetrics = call_args["harvest_metrics"]

    assert metrics.wet_weight == 50.0
    assert metrics.dry_weight == 10.0  # Unchanged
    assert metrics.trim_weight is None


@pytest.mark.asyncio
async def test_handle_update_harvest_metrics_not_found(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating harvest metrics for a plant that does not exist."""
    call = AsyncMock()
    call.data = {
        ATTR_PLANT_ID: "missing_plant",
    }

    from homeassistant.exceptions import ServiceValidationError

    with patch(
        "custom_components.growspace_manager.services.plant_scoring._ensure_plant_loaded",
        new_callable=AsyncMock,
    ) as mock_ensure:
        mock_ensure.return_value = True
        with pytest.raises(ServiceValidationError):
            await handle_update_harvest_metrics(
                mock_hass, mock_coordinator, mock_strain_library, call
            )
