"""Tests for the environment service handlers."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import (
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
)
from custom_components.growspace_manager.models import (
    CirculationFanConfig,
    EnvironmentConfig,
    IrrigationTank,
    SensorGroup,
)
from custom_components.growspace_manager.services.environment import (
    handle_configure_circulation_fan,
    handle_configure_environment,
    handle_remove_environment,
    handle_set_dehumidifier_control,
    handle_set_humidifier_control,
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


@pytest.mark.asyncio
async def test_handle_set_humidifier_control_success(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test successful humidifier control update."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {"growspace_id": growspace_id, "enabled": True}

    await handle_set_humidifier_control(mock_hass, mock_coordinator, mock_call)

    assert mock_gs.environment_config.control_humidifier is True
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_humidifier_control_gs_not_found(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test humidifier control update with invalid growspace ID."""
    mock_coordinator.growspaces = {}
    mock_call.data = {"growspace_id": "non_existent", "enabled": True}

    with pytest.raises(
        ServiceValidationError, match="Growspace 'non_existent' not found"
    ):
        await handle_set_humidifier_control(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_handle_configure_environment_preserves_tank_runtime_data(
    mock_hass, mock_coordinator, mock_call
) -> None:
    """Test that configuring an environment preserves runtime data of existing irrigation tanks."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"

    # Setup existing tank with runtime data
    existing_tank = IrrigationTank(
        sensor_entity="sensor.tank",
        name="Old Tank Name",
        water_history=[10.0, 20.0],
        last_recorded_level=20.0,
        peak_level=30.0,
    )
    mock_gs.environment_config = EnvironmentConfig(
        irrigation_tanks=[existing_tank]
    )
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    # Call with new tank configuration having same sensor_entity
    mock_call.data = {
        "growspace_id": growspace_id,
        "irrigation_tanks": [
            {
                "sensor_entity": "sensor.tank",
                "name": "New Tank Name",
                "warning_level": 15.0,
            }
        ],
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    # Verify updated config preserves the runtime data
    updated_tanks = mock_gs.environment_config.irrigation_tanks
    assert len(updated_tanks) == 1
    new_tank = updated_tanks[0]
    assert new_tank.sensor_entity == "sensor.tank"
    assert new_tank.name == "New Tank Name"
    assert new_tank.warning_level == 15.0
    # Preserved fields
    assert new_tank.water_history == [10.0, 20.0]
    assert new_tank.last_recorded_level == 20.0
    assert new_tank.peak_level == 30.0

    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_configure_circulation_fan_success(
    mock_hass: MagicMock, mock_coordinator: MagicMock, mock_call: MagicMock
) -> None:
    """Test successful circulation fan configuration."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "enabled": True,
        "regulation_mode": "vpd",
        "min_speed": 20,
        "max_speed": 80,
        "vpd_target": 1.2,
        "vpd_tolerance": 0.15,
        "humidity_target": 60.0,
        "humidity_tolerance": 5.0,
        "temperature_target": 25.0,
        "temperature_tolerance": 2.0,
        "critical_temp_low": None,
        "critical_temp_high": 32.0,
        "critical_temp_hysteresis": 1.0,
        "wind_enabled": True,
        "wind_period_seconds": 120,
        "wind_amplitude_pct": 15,
    }

    await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)

    fan_cfg = mock_gs.environment_config.circulation_fan_config
    assert isinstance(fan_cfg, CirculationFanConfig)
    assert fan_cfg.enabled is True
    assert fan_cfg.min_speed == 20
    assert fan_cfg.max_speed == 80
    assert fan_cfg.vpd_target == 1.2
    assert fan_cfg.wind_enabled is True
    assert fan_cfg.wind_period_seconds == 120
    assert fan_cfg.critical_temp_high == 32.0
    assert fan_cfg.critical_temp_low is None
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_configure_circulation_fan_gs_not_found(
    mock_hass: MagicMock, mock_coordinator: MagicMock, mock_call: MagicMock
) -> None:
    """Test circulation fan configuration with invalid growspace ID."""
    mock_coordinator.growspaces = {}
    mock_call.data = {"growspace_id": "non_existent"}

    with pytest.raises(
        ServiceValidationError, match="Growspace 'non_existent' not found"
    ):
        await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)

