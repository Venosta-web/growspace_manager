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
    coord.lifecycle_manager = MagicMock()
    coord.lifecycle_manager.async_add_plant = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_cache_invalidation_add_plant(hass: HomeAssistant) -> None:
    """Test that adding a plant invalidates the growspace cache."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS")

    # 1. Get initial data
    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["total_plants"] == 0

    # Setup mock return for add_plant

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

    async def side_effect_add_plant(**kwargs: Any) -> Plant:
        coordinator.plants[mock_plant.plant_id] = mock_plant
        return mock_plant

    # cast to Mock to set side_effect because mypy thinks it is the real method
    cast(
        MagicMock, coordinator.lifecycle_manager.async_add_plant
    ).side_effect = side_effect_add_plant

    # 2. Add plant
    await coordinator.async_add_plant(gs.id, "Strain A")

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
    gs = await coordinator.async_add_growspace("Test GS")

    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["name"] == "Test GS"

    await coordinator.async_update_growspace(gs.id, name="Renamed GS")

    data2 = coordinator.get_growspace_data(gs.id)
    assert data2["name"] == "Renamed GS"


@pytest.mark.asyncio
async def test_cache_invalidation_update_plant(hass: HomeAssistant) -> None:
    """Test that updating a plant invalidates cache."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS")

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
    coordinator._invalidate_cache(gs.id)

    async def side_effect_update(plant_id: str, **updates: Any) -> Plant:
        for k, v in updates.items():
            setattr(mock_plant, k, v)
        return mock_plant

    coordinator.lifecycle_manager.async_update_plant = AsyncMock(  # type: ignore[method-assign]
        side_effect=side_effect_update
    )

    data1 = coordinator.get_growspace_data(gs.id)
    assert data1["grid"]["position_1_1"]["plant_id"] == "p1"

    await coordinator.async_update_plant(mock_plant.plant_id, stage="flower")

    data2 = coordinator.get_growspace_data(gs.id)
    assert data2["grid"]["position_1_1"]["stage"] == "flower"
