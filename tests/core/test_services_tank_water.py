"""Tests for configure_tank service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_TANK_ENTITY,
    ATTR_VOLUME_LITERS,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.services.tank_config import (
    handle_configure_tank,
)
from homeassistant.exceptions import ServiceValidationError


def _make_growspace(tank_entity: str = "sensor.tank_1") -> Growspace:
    """Build a minimal Growspace with one irrigation tank."""
    tank = IrrigationTank(sensor_entity=tank_entity, volume_liters=None)
    env = EnvironmentConfig(irrigation_tanks=[tank])
    return Growspace(id="gs_1", name="Test", environment_config=env)


@pytest.fixture
def coordinator():
    """Mock coordinator with tank-related async methods."""
    mock = MagicMock()
    mock._data_repository = MagicMock()
    mock._data_repository.get_growspace = MagicMock(return_value=_make_growspace())
    mock._growspace_manager = MagicMock()
    mock._growspace_manager.async_configure_tank = AsyncMock()
    mock.services.growspaces.configure_tank = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_handle_configure_tank_calls_coordinator(coordinator) -> None:
    """Test that handle_configure_tank calls coordinator with the correct args."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "gs_1",
        ATTR_TANK_ENTITY: "sensor.tank_1",
        ATTR_VOLUME_LITERS: 20.0,
    }

    await handle_configure_tank(MagicMock(), coordinator, call)

    coordinator.services.growspaces.configure_tank.assert_awaited_once_with(
        "gs_1",
        "sensor.tank_1",
        volume_liters=20.0,
    )


@pytest.mark.asyncio
async def test_handle_configure_tank_without_volume(coordinator) -> None:
    """Test that handle_configure_tank works when volume_liters is omitted."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "gs_1",
        ATTR_TANK_ENTITY: "sensor.tank_1",
    }

    await handle_configure_tank(MagicMock(), coordinator, call)

    coordinator.services.growspaces.configure_tank.assert_awaited_once_with(
        "gs_1",
        "sensor.tank_1",
        volume_liters=None,
    )


@pytest.mark.asyncio
async def test_handle_configure_tank_unknown_entity_raises(coordinator) -> None:
    """Test that ServiceValidationError is raised when tank entity is not found."""
    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "gs_1",
        ATTR_TANK_ENTITY: "sensor.unknown_tank",
        ATTR_VOLUME_LITERS: 10.0,
    }

    with pytest.raises(ServiceValidationError):
        await handle_configure_tank(MagicMock(), coordinator, call)

    coordinator.services.growspaces.configure_tank.assert_not_awaited()
