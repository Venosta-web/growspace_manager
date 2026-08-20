"""Integration tests for nutrient deduction during watering."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    NutrientInventory,
    NutrientStock,
)
from homeassistant.core import HomeAssistant

from .common import create_plant


@pytest.fixture
async def mock_coordinator(hass: HomeAssistant):
    coord = GrowspaceCoordinator.build(hass, MagicMock())
    # Prevent real storage writes
    coord.storage_manager.async_save = AsyncMock()
    coord.storage_manager.async_force_save = AsyncMock()
    coord.view_model_builder = MagicMock()
    coord.view_model_builder.build_data_property.return_value = {}

    # Initialize basic data
    coord._data_repository.add_growspace(
        Growspace(id="gs1", name="Growspace 1", rows=1, plants_per_row=3)
    )
    for plant in [
        create_plant(plant_id="p1", growspace_id="gs1", row=1, col=1, strain="Strain"),
        create_plant(plant_id="p2", growspace_id="gs1", row=1, col=2, strain="Strain"),
        create_plant(plant_id="p3", growspace_id="gs1", row=1, col=3, strain="Strain"),
    ]:
        coord._data_repository.add_plant(plant)

    # Mock nutrient manager and inventory
    inventory = NutrientInventory()
    inventory.stocks = {
        "n1": NutrientStock(
            nutrient_id="n1",
            name="Nutrient A",
            current_ml=100.0,
            initial_ml=1000.0,
        )
    }
    coord._nutrient_manager.load_data({}, {}, inventory)

    try:
        yield coord
    finally:
        await coord.async_shutdown()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.events.async_fire_plant_event")
async def test_water_growspace_total_amount_deduction(
    mock_fire_event, mock_coordinator
) -> None:
    """Test that watering a growspace with total amount deducts correctly."""
    # 5L total for 3 plants
    total_amount = 5.0
    nutrients = {"n1": 2.0}  # 2ml/L — keyed by nutrient_id

    # Expected total deduction: 5.0 * 2.0 = 10.0 ml

    await mock_coordinator.services.growspaces.water_growspace(
        growspace_id="gs1", amount=total_amount, nutrients=nutrients
    )

    stock = mock_coordinator._nutrient_manager.inventory.stocks["n1"]
    assert stock.current_ml == pytest.approx(90.0)

    mock_coordinator.storage_manager.async_force_save.assert_awaited()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.events.async_fire_plant_event")
async def test_water_growspace_per_plant_compatibility(
    mock_fire_event, mock_coordinator
) -> None:
    """Test that legacy amount_per_plant still works."""
    # 2L per plant for 3 plants = 6L total
    amount_per_plant = 2.0
    nutrients = {"n1": 1.0}  # 1ml/L — keyed by nutrient_id

    # Expected total deduction: 3 plants * 2.0L * 1.0ml/L = 6.0 ml

    await mock_coordinator.services.growspaces.water_growspace(
        growspace_id="gs1", amount_per_plant=amount_per_plant, nutrients=nutrients
    )

    stock = mock_coordinator._nutrient_manager.inventory.stocks["n1"]
    assert stock.current_ml == pytest.approx(94.0)  # 100 - 6
