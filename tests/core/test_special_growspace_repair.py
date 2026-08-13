"""Tests for the batch relocation seam used by special-growspace repairs."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.events import EVENT_PLANT_LAYOUT_CHANGED
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.services.context import ServiceContext
from homeassistant.core import HomeAssistant
from tests.common import async_capture_events


@pytest.fixture
def repository() -> GrowspaceRepository:
    """Return a canonical growspace and two duplicates holding plants."""
    repository = GrowspaceRepository()
    repository.add_growspace(Growspace(id="dry", name="dry", rows=2, plants_per_row=2))
    repository.add_growspace(
        Growspace(id="dry_overview_1", name="dry", rows=2, plants_per_row=2)
    )
    repository.add_growspace(
        Growspace(id="dry_overview_2", name="dry", rows=2, plants_per_row=2)
    )
    repository.add_plant(
        Plant(plant_id="p1", growspace_id="dry_overview_1", row=1, col=1)
    )
    repository.add_plant(
        Plant(plant_id="p2", growspace_id="dry_overview_1", row=1, col=2)
    )
    repository.add_plant(
        Plant(plant_id="p3", growspace_id="dry_overview_2", row=1, col=1)
    )
    return repository


@pytest.fixture
def save_callback() -> AsyncMock:
    """Return the persistence seam used by managers."""
    return AsyncMock()


@pytest.fixture
def service_context(save_callback: AsyncMock) -> ServiceContext:
    """Return the shared mutation context."""
    return ServiceContext(
        save_callback=save_callback,
        lock=asyncio.Lock(),
        add_event=MagicMock(),
        invalidate_cache=MagicMock(),
    )


@pytest.fixture
def manager(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    service_context: ServiceContext,
) -> PlantManager:
    """Return a PlantManager wired to the real repository and validator."""
    return PlantManager(
        ctx=service_context,
        hass=hass,
        repository=repository,
        notification_state=NotificationState(),
        validator=GrowspaceValidator(repository),
        growspace_manager=MagicMock(),
        strain_library=MagicMock(),
        plant_view_builder=MagicMock(),
    )


async def test_relocation_advances_each_growspace_once(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A batch relocation is one revision and one event per growspace."""
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)

    relocated = await manager.relocate_plants_to_growspace("dry", ["p1", "p2", "p3"])

    assert relocated == ["p1", "p2", "p3"]
    assert repository.require_growspace("dry").layout_revision == 1
    assert repository.require_growspace("dry_overview_1").layout_revision == 1
    assert repository.require_growspace("dry_overview_2").layout_revision == 1
    save_callback.assert_awaited_once_with()
    assert sorted(event.data["growspace_id"] for event in events) == [
        "dry",
        "dry_overview_1",
        "dry_overview_2",
    ]
    assert all(event.data["layout_revision"] == 1 for event in events)


async def test_relocation_gives_every_plant_its_own_cell(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """Positions are searched per plant, so relocated plants never collide."""
    await manager.relocate_plants_to_growspace("dry", ["p1", "p2", "p3"])

    plants = repository.get_growspace_plants("dry")
    assert len(plants) == 3
    assert len({(plant.row, plant.col) for plant in plants}) == 3


async def test_relocation_skips_plants_that_do_not_fit(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """A full destination skips the surplus plants instead of failing."""
    repository.require_growspace("dry").rows = 1
    repository.require_growspace("dry").plants_per_row = 1

    relocated = await manager.relocate_plants_to_growspace("dry", ["p1", "p2", "p3"])

    assert relocated == ["p1"]
    assert repository.require_plant("p2").growspace_id == "dry_overview_1"


async def test_relocation_skips_unknown_plants(
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A plant that no longer exists does not abort the repair."""
    relocated = await manager.relocate_plants_to_growspace("dry", ["gone", "p1"])

    assert relocated == ["p1"]
    save_callback.assert_awaited_once_with()


async def test_relocation_requires_the_destination_growspace(
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """Relocating into a missing growspace fails before anything is written."""
    with pytest.raises(GrowspaceNotFoundError):
        await manager.relocate_plants_to_growspace("missing", ["p1"])

    save_callback.assert_not_awaited()


async def test_relocation_waits_for_the_shared_plant_lock(
    manager: PlantManager,
    repository: GrowspaceRepository,
) -> None:
    """A repair cannot interleave with another plant-manager mutation."""
    async with manager._lock:
        task = asyncio.create_task(manager.relocate_plants_to_growspace("dry", ["p1"]))
        await asyncio.sleep(0)
        assert not task.done()
        assert repository.require_plant("p1").growspace_id == "dry_overview_1"

    assert await task == ["p1"]
