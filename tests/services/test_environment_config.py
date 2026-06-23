"""Tests for environment configuration service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.services.environment import (
    handle_configure_environment,
)
from homeassistant.core import Context, HomeAssistant, ServiceCall


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.services = MagicMock()
    coordinator.services.save = AsyncMock()
    coordinator.services.request_refresh = AsyncMock()
    _fan_coord_mock = MagicMock()
    _fan_coord_mock.async_restart = AsyncMock()
    coordinator._subsystem_manager = MagicMock()
    coordinator._subsystem_manager.get_circulation_fan_controller = MagicMock(
        return_value=_fan_coord_mock
    )
    return coordinator


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    call.context = Context()
    return call


@pytest.fixture(autouse=True)
def mock_exhaust_migration():
    """Patch the migration repair helper (it needs a real issue registry)."""
    with patch(
        "custom_components.growspace_manager.services.environment"
        ".evaluate_exhaust_migration_issues"
    ) as mock_eval:
        yield mock_eval


@pytest.mark.asyncio
async def test_handle_configure_environment_with_coordinates_and_tanks(
    mock_hass,
    mock_coordinator,
    mock_call,
) -> None:
    """Test handle_configure_environment with sensor_coordinates and irrigation_tanks."""
    growspace_id = "gs1"

    # Mock growspace
    mock_gs = MagicMock()
    mock_gs.name = "Test Growspace"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    # Prepare service call data
    mock_call.data = {
        "growspace_id": growspace_id,
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "sensor_coordinates": {
            "sensor.temp": {"x": 10, "y": 20, "z": 30},
            "sensor.hum": {"x": 15, "y": 25, "z": 35},
        },
        "irrigation_tanks": [
            {"name": "Tank A", "sensor_entity": "sensor.tank_a_level"},
            {"name": "Tank B", "sensor_entity": "sensor.tank_b_level"},
        ],
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    # Verify coordinator save and refresh were called
    mock_coordinator.services.save.assert_awaited_once()
    mock_coordinator.services.request_refresh.assert_awaited_once()

    # Verify environment config was updated correctly
    updated_config = mock_gs.environment_config

    assert updated_config.temperature_sensor == "sensor.temp"
    assert updated_config.humidity_sensor == "sensor.hum"
    assert updated_config.vpd_sensor == "sensor.vpd"

    # Verify sensor coordinates
    assert updated_config.sensor_coordinates == {
        "sensor.temp": {"x": 10, "y": 20, "z": 30},
        "sensor.hum": {"x": 15, "y": 25, "z": 35},
    }

    # Verify irrigation tanks
    assert len(updated_config.irrigation_tanks) == 2
    assert updated_config.irrigation_tanks[0].name == "Tank A"
    assert updated_config.irrigation_tanks[0].sensor_entity == "sensor.tank_a_level"
    assert updated_config.irrigation_tanks[1].name == "Tank B"
    assert updated_config.irrigation_tanks[1].sensor_entity == "sensor.tank_b_level"


@pytest.mark.asyncio
async def test_handle_configure_environment_persists_lst_offset(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test that configure_environment stores the lst_offset from the service call."""
    growspace_id = "gs1"

    mock_gs = MagicMock()
    mock_gs.name = "Test Growspace"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "lst_offset": -3.5,
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    assert mock_gs.environment_config.lst_offset == -3.5


@pytest.mark.asyncio
async def test_handle_configure_environment_defaults_lst_offset(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test that configure_environment defaults lst_offset to -2.0 when not provided."""
    growspace_id = "gs1"

    mock_gs = MagicMock()
    mock_gs.name = "Test Growspace"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    assert mock_gs.environment_config.lst_offset == -2.0
