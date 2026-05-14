"""Tests for the environment service handlers."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import (
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    IrrigationTank,
    SensorGroup,
)
from custom_components.growspace_manager.services.environment import (
    handle_configure_environment,
    handle_remove_environment,
    handle_set_dehumidifier_control,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    return call


@pytest.mark.asyncio
async def test_handle_configure_environment_success(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test successful environment configuration."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.hum",
        "sensor_groups": [
            {
                "id": "group1",
                "name": "Group 1",
                "x": 1.0,
                "y": 2.0,
                "z": 3.0,
                "temperature_sensors": ["sensor.s1"],
            }
        ],
        "irrigation_tanks": [
            {"sensor_entity": "sensor.tank", "name": "Tank 1", "warning_level": 20.0}
        ],
        CONF_DEHUMIDIFIER_THRESHOLDS: {"day": 50.0},
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    assert isinstance(mock_gs.environment_config, EnvironmentConfig)
    assert mock_gs.environment_config.temperature_sensor == "sensor.temp"
    assert len(mock_gs.environment_config.sensor_groups) == 1
    assert isinstance(mock_gs.environment_config.sensor_groups[0], SensorGroup)
    assert mock_gs.environment_config.sensor_groups[0].id == "group1"
    assert len(mock_gs.environment_config.irrigation_tanks) == 1
    assert isinstance(mock_gs.environment_config.irrigation_tanks[0], IrrigationTank)
    assert mock_gs.environment_config.dehumidifier_thresholds == {"day": 50.0}
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_configure_environment_singular_plural_lists(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test environment configuration with singular and plural entity lists."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    # Test singular as string
    mock_call.data = {
        "growspace_id": growspace_id,
        "circulation_fan_entity": "fan.1",
        "exhaust_entity": ["fan.2"],  # plural list
    }
    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)
    assert mock_gs.environment_config.circulation_fan_entities == ["fan.1"]
    assert mock_gs.environment_config.exhaust_fan_entities == ["fan.2"]
    mock_coordinator.async_commit.assert_awaited()
    mock_coordinator.async_request_refresh.assert_awaited()

    # Test plural taking precedence
    mock_coordinator.async_commit.reset_mock()
    mock_coordinator.async_request_refresh.reset_mock()
    mock_call.data = {
        "growspace_id": growspace_id,
        "circulation_fan_entities": ["fan.3", "fan.4"],
        "circulation_fan_entity": "fan.1",
    }
    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)
    assert mock_gs.environment_config.circulation_fan_entities == ["fan.3", "fan.4"]


@pytest.mark.asyncio
async def test_handle_configure_environment_gs_not_found(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test environment configuration with invalid growspace ID."""
    mock_coordinator.growspaces = {}
    mock_call.data = {"growspace_id": "non_existent"}

    with pytest.raises(
        ServiceValidationError, match="Growspace 'non_existent' not found"
    ):
        await handle_configure_environment(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_handle_configure_environment_invalid_groups_and_tanks(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test environment configuration with invalid group/tank data."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "sensor_groups": [{"invalid_key": "value"}],
        "irrigation_tanks": [{"invalid_key": "value"}],
    }

    # Should log warning but not fail
    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    # SensorGroup.from_dict will fail because 'id' is missing, so it won't be appended
    assert len(mock_gs.environment_config.sensor_groups) == 0
    assert len(mock_gs.environment_config.irrigation_tanks) == 0
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_remove_environment_success(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test successful environment removal."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {"growspace_id": growspace_id}

    await handle_remove_environment(mock_hass, mock_coordinator, mock_call)

    assert isinstance(mock_gs.environment_config, EnvironmentConfig)
    # Default values should be present
    assert mock_gs.environment_config.temperature_sensor is None
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_remove_environment_gs_not_found(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test environment removal with invalid growspace ID."""
    mock_coordinator.growspaces = {}
    mock_call.data = {"growspace_id": "non_existent"}

    with pytest.raises(
        ServiceValidationError, match="Growspace 'non_existent' not found"
    ):
        await handle_remove_environment(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_success(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test successful dehumidifier control update."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {"growspace_id": growspace_id, "enabled": True}

    await handle_set_dehumidifier_control(mock_hass, mock_coordinator, mock_call)

    assert mock_gs.environment_config.control_dehumidifier is True
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_gs_not_found(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test dehumidifier control update with invalid growspace ID."""
    mock_coordinator.growspaces = {}
    mock_call.data = {"growspace_id": "non_existent", "enabled": True}

    with pytest.raises(
        ServiceValidationError, match="Growspace 'non_existent' not found"
    ):
        await handle_set_dehumidifier_control(mock_hass, mock_coordinator, mock_call)
