"""Shared scaffolding for the manager suites.

The Plant Manager is built here over **real** in-memory models and a real
`GrowspaceRepository`, because most of what these suites assert is about what
the repository holds after a mutation — and a doubled repository would prove
none of it. What is faked is everything outside the manager's own decisions:
persistence, so a suite can make a save fail and watch the rollback; the
validator, so placement is a decision a test makes rather than a second
implementation to satisfy; and Home Assistant itself.

`manager_factory` takes the save callback, which is the seam that matters. A
manager built with a failing one is how "the repository is exactly as it was"
becomes something a test can see rather than something a reviewer has to
believe.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.context import ServiceContext


@pytest.fixture
def repository() -> GrowspaceRepository:
    """Repository with a normal cultivation growspace."""
    result = GrowspaceRepository()
    result.add_growspace(Growspace(id="main", name="Main", rows=5, plants_per_row=5))
    return result


@pytest.fixture
def manager_factory(repository: GrowspaceRepository):
    """Build a manager around real in-memory models and controllable persistence."""

    def build(save_callback: AsyncMock | None = None) -> PlantManager:
        growspace_manager = Mock()

        def ensure_special(
            growspace_id: str | PlantStage,
            name: str,
            rows: int = 5,
            plants_per_row: int = 5,
            **_: object,
        ) -> str:
            canonical = str(growspace_id)
            if not repository.has_growspace(canonical):
                repository.add_growspace(
                    Growspace(
                        id=canonical,
                        name=name,
                        rows=rows,
                        plants_per_row=plants_per_row,
                    )
                )
            return canonical

        growspace_manager.ensure_special_growspace.side_effect = ensure_special
        growspace_manager.ensure_mother_growspace.side_effect = lambda: ensure_special(
            PlantStage.MOTHER, "mother"
        )

        validator = Mock()
        validator.validate_position_not_occupied.return_value = None
        validator.validate_plant_exists.return_value = None
        validator.find_first_available_position.return_value = (1, 1)

        hass = Mock()
        hass.bus.async_fire = Mock()
        return PlantManager(
            ctx=ServiceContext(
                save_callback=save_callback or AsyncMock(),
                lock=asyncio.Lock(),
                add_event=Mock(),
                invalidate_cache=Mock(),
            ),
            hass=hass,
            repository=repository,
            notification_state=NotificationState(),
            validator=validator,
            growspace_manager=growspace_manager,
            strain_library=Mock(record_harvest=AsyncMock()),
            plant_view_builder=Mock(build=Mock(return_value={})),
        )

    return build
