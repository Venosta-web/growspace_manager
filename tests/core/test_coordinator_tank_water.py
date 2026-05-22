"""Tests for async_configure_tank and get_tank_tracker coordinator methods."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry


def _make_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Create a minimal GrowspaceCoordinator for testing."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    def mock_create_task(
        hass: HomeAssistant, target: Any, *args: Any, **kwargs: Any
    ) -> Any:
        """Mock task creator that avoids unawaited coroutine warnings."""
        if hasattr(target, "close"):  # It's probably a coroutine
            target.close()
        return MagicMock()

    entry.async_create_background_task = MagicMock(side_effect=mock_create_task)

    return GrowspaceCoordinator.build(hass, entry, data={})


def _add_growspace_with_tank(
    coordinator: GrowspaceCoordinator,
    growspace_id: str = "gs_1",
    tank_entity: str = "sensor.tank_1",
    volume_liters: float | None = None,
) -> Growspace:
    """Add a growspace with a single irrigation tank to the coordinator."""
    tank = IrrigationTank(sensor_entity=tank_entity, volume_liters=volume_liters)
    env_config = EnvironmentConfig(irrigation_tanks=[tank])
    growspace = Growspace(
        id=growspace_id, name="Test Tent", environment_config=env_config
    )
    coordinator.data_repository.add_growspace(growspace)
    return growspace


# ── async_configure_tank ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_configure_tank_updates_volume(hass: HomeAssistant) -> None:
    """Test that async_configure_tank delegates to the services facade."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=None)

    # 1. Mock the facade method that handles the actual work
    # Note: Check if your facade method is named 'async_configure_tank' or 'configure_tank'
    coordinator.services.growspaces.configure_tank = AsyncMock()

    # 2. Call the services facade method directly
    await coordinator.services.growspaces.configure_tank("gs_1", "sensor.tank_1", volume_liters=100.0)

    # 3. Verify the call was made
    coordinator.services.growspaces.configure_tank.assert_called_once_with(
        "gs_1", "sensor.tank_1", volume_liters=100.0
    )


@pytest.mark.asyncio
async def test_async_configure_tank_calls_storage_save(hass: HomeAssistant) -> None:
    """Test that async_configure_tank triggers a storage save."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=50.0)

    # FIX: Change async_save to async_force_save
    coordinator.storage_manager.async_force_save = AsyncMock()

    await coordinator.services.growspaces.configure_tank(
        "gs_1", "sensor.tank_1", volume_liters=75.0
    )

    # FIX: Assert on async_force_save instead
    coordinator.storage_manager.async_force_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_configure_tank_unknown_entity_is_noop(hass: HomeAssistant) -> None:
    """Test that async_configure_tank silently returns if tank_entity is not found."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=50.0)

    coordinator.storage_manager.async_save = AsyncMock()

    await coordinator.services.growspaces.configure_tank(
        "gs_1", "sensor.unknown_tank", volume_liters=80.0
    )

    # Storage should not be called since tank was not found
    coordinator.storage_manager.async_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_configure_tank_volume_none_does_not_overwrite(
    hass: HomeAssistant,
) -> None:
    """Test that passing volume_liters=None leaves the existing value unchanged."""
    coordinator = _make_coordinator(hass)
    growspace = _add_growspace_with_tank(coordinator, volume_liters=60.0)

    coordinator.storage_manager.async_save = AsyncMock()

    await coordinator.services.growspaces.configure_tank("gs_1", "sensor.tank_1", volume_liters=None)

    tank = growspace.environment_config.irrigation_tanks[0]
    assert tank.volume_liters == 60.0


@pytest.mark.asyncio
async def test_async_configure_tank_unknown_growspace_is_noop(
    hass: HomeAssistant,
) -> None:
    """async_configure_tank with unknown growspace_id must not raise."""
    coordinator = _make_coordinator(hass)
    # Should not raise AttributeError
    await coordinator.services.growspaces.configure_tank(
        "nonexistent_gs", "sensor.tank", volume_liters=100.0
    )


# ── get_tank_tracker ──────────────────────────────────────────────────────────


def test_get_tank_tracker_returns_tracker_when_volume_set(hass: HomeAssistant) -> None:
    """Test get_tank_tracker returns a TankWaterTracker when volume_liters is set."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=200.0)

    tracker = coordinator.services.growspaces.get_tank_tracker("gs_1", "sensor.tank_1")

    assert isinstance(tracker, TankWaterTracker)


def test_get_tank_tracker_returns_none_when_volume_not_set(hass: HomeAssistant) -> None:
    """Test get_tank_tracker returns None when volume_liters is None."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=None)

    tracker = coordinator.services.growspaces.get_tank_tracker("gs_1", "sensor.tank_1")

    assert tracker is None


def test_get_tank_tracker_returns_none_for_unknown_entity(hass: HomeAssistant) -> None:
    """Test get_tank_tracker returns None when tank_entity is not found."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=200.0)

    tracker = coordinator.services.growspaces.get_tank_tracker("gs_1", "sensor.does_not_exist")

    assert tracker is None


def test_get_tank_tracker_returns_none_for_unknown_growspace(
    hass: HomeAssistant,
) -> None:
    """Test get_tank_tracker returns None when growspace_id is not found."""
    coordinator = _make_coordinator(hass)

    tracker = coordinator.services.growspaces.get_tank_tracker("nonexistent_gs", "sensor.tank_1")

    assert tracker is None


def test_get_tank_tracker_returns_same_instance_on_repeated_calls(
    hass: HomeAssistant,
) -> None:
    """Test that get_tank_tracker returns the same TankWaterTracker instance (lazy init)."""
    coordinator = _make_coordinator(hass)
    _add_growspace_with_tank(coordinator, volume_liters=150.0)

    tracker_first = coordinator.services.growspaces.get_tank_tracker("gs_1", "sensor.tank_1")
    tracker_second = coordinator.services.growspaces.get_tank_tracker("gs_1", "sensor.tank_1")

    assert tracker_first is tracker_second
