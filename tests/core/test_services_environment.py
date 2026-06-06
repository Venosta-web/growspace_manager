"""Tests for the environment service handlers."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import (
    CONF_BULK_EC_SENSORS,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_HUMIDITY_SENSOR,
    CONF_PORE_EC_SENSORS,
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
    return MagicMock(spec=ServiceCall)


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
    mock_gs.environment_config = EnvironmentConfig(irrigation_tanks=[existing_tank])
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


@pytest.mark.asyncio
async def test_configure_environment_accepts_bulk_and_pore_ec_sensors(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """configure_environment service writes bulk_ec_sensors and pore_ec_sensors to EnvironmentConfig."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        CONF_BULK_EC_SENSORS: ["sensor.bulk_ec_1"],
        CONF_PORE_EC_SENSORS: ["sensor.pore_ec_1"],
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    env: EnvironmentConfig = mock_gs.environment_config
    assert env.bulk_ec_sensors == ["sensor.bulk_ec_1"]
    assert env.pore_ec_sensors == ["sensor.pore_ec_1"]


@pytest.mark.asyncio
async def test_configure_environment_stores_vpd_optimal_overrides(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """configure_environment service writes vpd_optimal_overrides to EnvironmentConfig."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    overrides = {
        "veg": {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4, "high": 1.0}},
    }
    mock_call.data = {
        "growspace_id": growspace_id,
        "vpd_optimal_overrides": overrides,
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    env: EnvironmentConfig = mock_gs.environment_config
    assert env.vpd_optimal_overrides == overrides


@pytest.mark.asyncio
async def test_configure_environment_rejects_invalid_vpd_optimal_overrides(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """configure_environment raises ServiceValidationError for invalid vpd_optimal_overrides."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "vpd_optimal_overrides": {
            "unknown_stage": {
                "day": {"low": 0.5, "high": 1.2},
                "night": {"low": 0.4, "high": 1.0},
            }
        },
    }

    with pytest.raises(ServiceValidationError, match="Unknown stage key"):
        await handle_configure_environment(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_validate_stage_vpd_overrides_none_and_invalid_types(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test stage_vpd_overrides validation edge cases."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "stage_vpd_overrides": None,
    }
    await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)
    assert mock_gs.environment_config.circulation_fan_config.stage_vpd_overrides == {}

    mock_call.data = {
        "growspace_id": growspace_id,
        "stage_vpd_overrides": ["invalid", "list"],
    }
    with pytest.raises(
        ServiceValidationError, match="stage_vpd_overrides must be a dictionary"
    ):
        await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)

    mock_call.data = {
        "growspace_id": growspace_id,
        "stage_vpd_overrides": {"veg": {"day": "not_a_number", "night": 1.0}},
    }
    with pytest.raises(ServiceValidationError, match="VPD override must be a number"):
        await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_validate_vpd_optimal_overrides_invalid_type(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test vpd_optimal_overrides validation with non-dictionary type."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "vpd_optimal_overrides": ["not", "a", "dict"],
    }
    with pytest.raises(
        ServiceValidationError, match="vpd_optimal_overrides must be a dictionary"
    ):
        await handle_configure_environment(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_handle_configure_environment_with_circulation_fan_config(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test configure_environment service parses circulation_fan_config raw dictionary."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.environment_config = None
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    raw_fan_config = {
        "enabled": True,
        "regulation_mode": "vpd",
        "min_speed": 15,
        "max_speed": 85,
        "vpd_target": 1.1,
        "vpd_tolerance": 0.1,
        "wind_enabled": True,
        "wind_period_seconds": 90,
        "wind_amplitude_pct": 8,
        "stage_vpd_enabled": True,
        "stage_vpd_overrides": {"veg": {"day": 1.0, "night": 0.8}},
    }
    mock_call.data = {
        "growspace_id": growspace_id,
        "circulation_fan_config": raw_fan_config,
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    env: EnvironmentConfig = mock_gs.environment_config
    assert env.circulation_fan_config.enabled is True
    assert env.circulation_fan_config.regulation_mode == "vpd"
    assert env.circulation_fan_config.min_speed == 15
    assert env.circulation_fan_config.max_speed == 85
    assert env.circulation_fan_config.vpd_target == 1.1
    assert env.circulation_fan_config.vpd_tolerance == 0.1
    assert env.circulation_fan_config.wind_enabled is True
    assert env.circulation_fan_config.wind_period_seconds == 90
    assert env.circulation_fan_config.wind_amplitude_pct == 8
    assert env.circulation_fan_config.stage_vpd_enabled is True
    assert env.circulation_fan_config.stage_vpd_overrides == {
        "veg": {"day": 1.0, "night": 0.8}
    }


@pytest.mark.asyncio
async def test_parse_fan_config_fallback_none(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test _parse_fan_config returns default CirculationFanConfig when raw and existing config are None."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.environment_config = None
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "circulation_fan_config": None,
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)

    env: EnvironmentConfig = mock_gs.environment_config
    assert isinstance(env.circulation_fan_config, CirculationFanConfig)
    assert env.circulation_fan_config.enabled is False
    assert env.circulation_fan_config.min_speed == 0


@pytest.mark.asyncio
async def test_handle_configure_circulation_fan_config_none(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test configure_circulation_fan initializes environment config when it is None."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = None
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "enabled": True,
    }

    await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)

    assert isinstance(mock_gs.environment_config, EnvironmentConfig)
    assert mock_gs.environment_config.circulation_fan_config.enabled is True


@pytest.mark.parametrize(
    ("overrides", "match_msg"),
    [
        (
            {"unknown_stage": {"day": 1.0, "night": 1.0}},
            "Unknown stage key",
        ),
        (
            {"veg": ["not", "a", "dict"]},
            "must contain both 'day' and 'night' keys",
        ),
        (
            {"veg": {"day": 1.0}},
            "must contain both 'day' and 'night' keys",
        ),
        (
            {"veg": {"night": 1.0}},
            "must contain both 'day' and 'night' keys",
        ),
        (
            {"veg": {"day": 0.05, "night": 1.0}},
            "out of range",
        ),
        (
            {"veg": {"day": 3.05, "night": 1.0}},
            "out of range",
        ),
    ],
)
@pytest.mark.asyncio
async def test_validate_stage_vpd_overrides_errors(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
    overrides: dict,
    match_msg: str,
) -> None:
    """Test various validation errors in stage_vpd_overrides."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "stage_vpd_overrides": overrides,
    }
    with pytest.raises(ServiceValidationError, match=match_msg):
        await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)


@pytest.mark.parametrize(
    ("overrides", "match_msg"),
    [
        (
            {"veg": ["not", "a", "dict"]},
            "must contain both 'day' and 'night' keys",
        ),
        (
            {"veg": {"day": {"low": 0.5, "high": 1.2}}},
            "must contain both 'day' and 'night' keys",
        ),
        (
            {"veg": {"day": ["not", "a", "dict"], "night": {"low": 0.5, "high": 1.2}}},
            "must contain both 'low' and 'high' keys",
        ),
        (
            {"veg": {"day": {"low": 0.5}, "night": {"low": 0.5, "high": 1.2}}},
            "must contain both 'low' and 'high' keys",
        ),
        (
            {
                "veg": {
                    "day": {"low": 0.05, "high": 1.2},
                    "night": {"low": 0.5, "high": 1.2},
                }
            },
            "VPD values out of range",
        ),
        (
            {
                "veg": {
                    "day": {"low": 0.5, "high": 3.05},
                    "night": {"low": 0.5, "high": 1.2},
                }
            },
            "VPD values out of range",
        ),
        (
            {
                "veg": {
                    "day": {"low": 1.5, "high": 1.2},
                    "night": {"low": 0.5, "high": 1.2},
                }
            },
            "low .* must be < high",
        ),
    ],
)
@pytest.mark.asyncio
async def test_validate_vpd_optimal_overrides_errors(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
    overrides: dict,
    match_msg: str,
) -> None:
    """Test various validation errors in vpd_optimal_overrides."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_coordinator.growspaces = {growspace_id: mock_gs}

    mock_call.data = {
        "growspace_id": growspace_id,
        "vpd_optimal_overrides": overrides,
    }
    with pytest.raises(ServiceValidationError, match=match_msg):
        await handle_configure_environment(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
async def test_handle_configure_environment_no_fan_controller(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test configure_environment when circulation fan controller is not present."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = None
    mock_coordinator.growspaces = {growspace_id: mock_gs}
    mock_coordinator.subsystem_manager.get_circulation_fan_controller.return_value = (
        None
    )

    mock_call.data = {
        "growspace_id": growspace_id,
        "temp_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
    }

    await handle_configure_environment(mock_hass, mock_coordinator, mock_call)
    assert mock_gs.environment_config is not None


@pytest.mark.asyncio
async def test_handle_configure_circulation_fan_no_fan_controller(
    mock_hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_call: MagicMock,
) -> None:
    """Test configure_circulation_fan when circulation fan controller is not present."""
    growspace_id = "gs1"
    mock_gs = MagicMock()
    mock_gs.name = "Test GS"
    mock_gs.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {growspace_id: mock_gs}
    mock_coordinator.subsystem_manager.get_circulation_fan_controller.return_value = (
        None
    )

    mock_call.data = {
        "growspace_id": growspace_id,
        "enabled": True,
    }

    await handle_configure_circulation_fan(mock_hass, mock_coordinator, mock_call)
    assert mock_gs.environment_config.circulation_fan_config.enabled is True
