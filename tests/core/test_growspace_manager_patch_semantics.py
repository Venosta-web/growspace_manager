"""Patch semantics for GrowspaceManager.update_growspace.

Every growspace_manager service is a patch: an omitted field is left alone. The
manager already reads its updates with `in kwargs`, so absence works — but an
explicit ``None``, which a service adapter can hand it for a field the caller
never sent, used to be read as a value. Blanking a growspace's name that way
loses data silently, and a ``None`` grid crashes on ``int(None)``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.context import ServiceContext
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder


@pytest.fixture
def manager() -> GrowspaceManager:
    """Return a manager over one named growspace with a notification target."""
    repo = GrowspaceRepository()
    repo.add_growspace(
        Growspace(
            id="gs1",
            name="Tent 1",
            rows=2,
            plants_per_row=2,
            notification_target="mobile_app_phone",
        )
    )
    return GrowspaceManager(
        ctx=ServiceContext(
            save_callback=AsyncMock(),
            lock=asyncio.Lock(),
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=MagicMock(),
        repository=repo,
        notification_state=MagicMock(),
        validator=GrowspaceValidator(repo),
        view_model_builder=MagicMock(spec=ViewModelBuilder),
    )


@pytest.mark.asyncio
async def test_grid_update_leaves_the_omitted_name(manager: GrowspaceManager) -> None:
    """Resizing the grid keeps the name and the notification target."""
    await manager.update_growspace("gs1", rows=4, plants_per_row=5)

    growspace = manager.repository.require_growspace("gs1")
    assert (growspace.rows, growspace.plants_per_row) == (4, 5)
    assert growspace.name == "Tent 1"
    assert growspace.notification_target == "mobile_app_phone"


@pytest.mark.asyncio
async def test_explicit_none_name_is_not_a_value(manager: GrowspaceManager) -> None:
    """A None name means "not given", never "blank the name"."""
    await manager.update_growspace("gs1", name=None, rows=4, plants_per_row=5)

    growspace = manager.repository.require_growspace("gs1")
    assert growspace.name == "Tent 1"
    assert (growspace.rows, growspace.plants_per_row) == (4, 5)


@pytest.mark.asyncio
async def test_explicit_none_grid_is_not_a_value(manager: GrowspaceManager) -> None:
    """A None grid leaves the dimensions alone instead of raising on int(None)."""
    await manager.update_growspace("gs1", name="Renamed", rows=None)

    growspace = manager.repository.require_growspace("gs1")
    assert growspace.name == "Renamed"
    assert (growspace.rows, growspace.plants_per_row) == (2, 2)


@pytest.mark.asyncio
async def test_notification_target_is_still_clearable(
    manager: GrowspaceManager,
) -> None:
    """Clearing the target is a real intent, so an empty value still lands."""
    await manager.update_growspace("gs1", notification_target="")

    assert manager.repository.require_growspace("gs1").notification_target is None
