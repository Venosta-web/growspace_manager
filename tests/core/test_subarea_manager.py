"""Tests for subarea CRUD in GrowspaceManager."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def manager() -> GrowspaceManager:
    repo = GrowspaceRepository({}, {})
    gs = Growspace(id="gs1", name="Tent 1")
    repo.growspaces["gs1"] = gs
    save_cb = AsyncMock()
    mgr = GrowspaceManager(
        hass=MagicMock(),
        repository=repo,
        validator=GrowspaceValidator(repo),
        view_model_builder=MagicMock(spec=ViewModelBuilder),
        save_callback=save_cb,
        lock=asyncio.Lock(),
    )
    mgr.save_callback = save_cb  # keep ref for assertions
    return mgr


@pytest.mark.asyncio
async def test_add_subarea(manager: GrowspaceManager) -> None:
    sub = await manager.async_add_subarea("gs1", "Undercanopy")
    assert sub.name == "Undercanopy"
    assert sub.id
    assert len(manager.repository.growspaces["gs1"].subareas) == 1
    manager.save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_subarea_unknown_growspace(manager: GrowspaceManager) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        await manager.async_add_subarea("no_such_id", "X")


@pytest.mark.asyncio
async def test_update_subarea(manager: GrowspaceManager) -> None:
    sub = await manager.async_add_subarea("gs1", "Undercanopy")
    updated = await manager.async_update_subarea(
        "gs1", sub.id, {"temperature_sensors": ["sensor.t1"]}
    )
    assert updated.environment_config.temperature_sensors == ["sensor.t1"]


@pytest.mark.asyncio
async def test_update_subarea_not_found(manager: GrowspaceManager) -> None:
    with pytest.raises(ServiceValidationError):
        await manager.async_update_subarea("gs1", "bad_id", {})


@pytest.mark.asyncio
async def test_remove_subarea(manager: GrowspaceManager) -> None:
    sub = await manager.async_add_subarea("gs1", "Undercanopy")
    await manager.async_remove_subarea("gs1", sub.id)
    assert manager.repository.growspaces["gs1"].subareas == []


@pytest.mark.asyncio
async def test_remove_subarea_not_found(manager: GrowspaceManager) -> None:
    with pytest.raises(ServiceValidationError):
        await manager.async_remove_subarea("gs1", "bad_id")


@pytest.mark.asyncio
async def test_get_subareas(manager: GrowspaceManager) -> None:
    await manager.async_add_subarea("gs1", "Undercanopy")
    await manager.async_add_subarea("gs1", "Top Canopy")
    subareas = manager.get_subareas("gs1")
    assert len(subareas) == 2


@pytest.mark.asyncio
async def test_get_subareas_unknown_growspace(manager: GrowspaceManager) -> None:
    with pytest.raises(GrowspaceNotFoundError):
        manager.get_subareas("no_such_id")
