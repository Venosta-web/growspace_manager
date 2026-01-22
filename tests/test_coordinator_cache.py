from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Plant
from homeassistant.core import HomeAssistant

from .common import create_plant


def create_test_coordinator(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    strain_library: Any | None = None,
) -> GrowspaceCoordinator:
    """Helper to create a coordinator with a mock config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass, coro, name: coro.close()
    )

    coord = GrowspaceCoordinator(
        hass,
        entry,
        data=data or {},
        options=options,
        strain_library=strain_library,
    )
    coord.storage_manager = MagicMock()
    coord.storage_manager.async_save = AsyncMock()
    # Don't mock _plant_service - let real service logic run for cache invalidation tests
    return coord


@pytest.mark.asyncio
async def test_cache_invalidation_add_plant(hass: HomeAssistant) -> None:
    """Test that adding a plant invalidates the growspace cache."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator._growspace_service.add_growspace("Test GS")

    # 1. Get initial data
    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["total_plants"] == 0

    # 2. Add plant using real coordinator/service (no mocks - real cache invalidation)
    await coordinator.async_add_plant(
        growspace_id=gs.id,
        strain="Strain A",
        row=1,
        col=1,
    )

    # 3. Get data again (should be fresh)
    data2 = coordinator.get_growspace_data(gs.id)
    assert data2["total_plants"] == 1
    plant_in_grid = data2["grid"].get("position_1_1")
    assert plant_in_grid is not None
    assert plant_in_grid["strain"] == "Strain A"


@pytest.mark.asyncio
async def test_cache_invalidation_update_growspace(hass: HomeAssistant) -> None:
    """Test that updating growspace invalidates cache."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator._growspace_service.add_growspace("Test GS")

    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["name"] == "Test GS"

    await coordinator._growspace_service.update_growspace(gs.id, name="Renamed GS")

    data2 = coordinator.get_growspace_data(gs.id)
    assert data2["name"] == "Renamed GS"


@pytest.mark.asyncio
async def test_cache_invalidation_update_plant(hass: HomeAssistant) -> None:
    """Test that updating a plant invalidates cache."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator._growspace_service.add_growspace("Test GS")

    mock_plant = create_plant(
        plant_id="p1",
        growspace_id=gs.id,
        strain="Strain A",
        phenotype="",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    coordinator.plants[mock_plant.plant_id] = mock_plant
    # Direct manual update requires manual cache invalidation or update call
    coordinator.growspaces[gs.id].plants_per_row = 5
    coordinator.growspaces[gs.id].rows = 5

    # Manually invalidate because we bypassed standard add methods that would invalidate
    coordinator.cache.invalidate(gs.id)

    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["grid"]["position_1_1"]["plant_id"] == "p1"

    await coordinator.async_update_plant(mock_plant.plant_id, stage="flower")

    data2 = coordinator.get_growspace_data(gs.id)
    assert data2["grid"]["position_1_1"]["stage"] == "flower"
