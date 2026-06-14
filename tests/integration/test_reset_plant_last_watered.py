"""Tests for the reset_plant_last_watered service.

This service is a test fixture helper that clears a plant's last_watered
timestamp so E2E tests can exercise watering flows from a clean state.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.irrigation_watering import (
    handle_reset_plant_last_watered,
)
from tests.common import MockConfigEntry

from .common import create_plant


def _make_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Return a coordinator with async_commit mocked for inspection."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock(
        side_effect=lambda _hass, coro, name: hass.async_create_task(coro)
    )
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator.async_commit = AsyncMock()  # type: ignore[method-assign]
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.fixture
def coordinator_with_plant(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Coordinator pre-loaded with one watered plant."""
    coordinator = _make_coordinator(hass)
    coordinator._data_repository.add_growspace(
        Growspace(id="gs1", name="Tent 1", rows=3, plants_per_row=3)
    )
    plant = create_plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="OG Kush",
        phenotype="A",
        row=1,
        col=1,
    )
    plant.last_watered = "2026-05-20T10:00:00+00:00"
    coordinator._data_repository.add_plant(plant)
    return coordinator


class TestResetLastWateredFacade:
    """Facade-level tests — exercise the public coordinator interface."""

    @pytest.mark.asyncio
    async def test_reset_clears_timestamp(
        self, coordinator_with_plant: GrowspaceCoordinator
    ) -> None:
        """reset_last_watered sets last_watered to None on a pre-watered plant."""
        assert coordinator_with_plant.plants["p1"].last_watered is not None

        await coordinator_with_plant.services.plants.reset_last_watered("p1")

        assert coordinator_with_plant.plants["p1"].last_watered is None

    @pytest.mark.asyncio
    async def test_reset_persists_change(
        self, coordinator_with_plant: GrowspaceCoordinator
    ) -> None:
        """reset_last_watered commits the change so it survives a restart."""
        await coordinator_with_plant.services.plants.reset_last_watered("p1")

        coordinator_with_plant.async_commit.assert_called_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_reset_unknown_plant_raises(
        self, coordinator_with_plant: GrowspaceCoordinator
    ) -> None:
        """Unknown plant ID raises ServiceValidationError, not a silent no-op."""
        with pytest.raises(ServiceValidationError):
            await coordinator_with_plant.services.plants.reset_last_watered("no-such-plant")


class TestResetLastWateredHandler:
    """Service-handler tests — verify the HA service call routes correctly."""

    @pytest.mark.asyncio
    async def test_handler_clears_timestamp(
        self,
        hass: HomeAssistant,
        coordinator_with_plant: GrowspaceCoordinator,
    ) -> None:
        """Service handler clears last_watered via the coordinator facade."""
        call = MagicMock()
        call.data = {"plant_id": "p1"}

        await handle_reset_plant_last_watered(hass, coordinator_with_plant, call)

        assert coordinator_with_plant.plants["p1"].last_watered is None

    @pytest.mark.asyncio
    async def test_handler_unknown_plant_raises(
        self,
        hass: HomeAssistant,
        coordinator_with_plant: GrowspaceCoordinator,
    ) -> None:
        """Service handler raises ServiceValidationError for an unknown plant ID."""
        call = MagicMock()
        call.data = {"plant_id": "ghost-plant"}

        with pytest.raises(ServiceValidationError):
            await handle_reset_plant_last_watered(hass, coordinator_with_plant, call)
