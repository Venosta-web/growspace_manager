from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant


def create_test_sensor(
    coordinator: MagicMock,
    growspace_id: str,
    sensor_type: str,
    strategy_class: type,
    env_config: EnvironmentConfig | None = None,
) -> BayesianEnvironmentSensor:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    return BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        # Inject dependencies
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )


@pytest.fixture
def mock_growspace_multi():
    """Fixture for a mock growspace with multi-device config."""
    growspace = MagicMock()
    growspace.name = "Multi Device Growspace"
    growspace.growspace_id = "gs_multi"

    config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        vpd_sensor="sensor.vpd",
        co2_sensor="sensor.co2",
        # Config initialized with defaults, lists are empty by default in original model?
        # But we updated models.py.
        # Check backward compat migration
        light_sensors=["light.1"],
        circulation_fan_entities=["fan.1"],
    )
    # Manually populate lists to simulate multi-device config
    config.light_sensors = ["light.1", "light.2"]
    config.circulation_fan_entities = ["fan.1", "fan.2"]

    growspace.environment_config = config
    return growspace


@pytest.fixture
def mock_coordinator_multi(mock_growspace_multi):
    """Fixture for coordinator with multi-device growspace."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs_multi": mock_growspace_multi}
    coordinator.options = {}
    # Add missing dependencies
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.add_event = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.strain_library = None
    return coordinator


@pytest.fixture
def sensor_multi(
    mock_coordinator_multi, hass: HomeAssistant
) -> BayesianEnvironmentSensor:
    """Fixture for the sensor instance."""
    sensor = create_test_sensor(
        mock_coordinator_multi,
        "gs_multi",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator_multi.growspaces["gs_multi"].environment_config,
    )
    sensor.hass = hass
    return sensor


def set_state(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)


@pytest.mark.asyncio
async def test_lights_or_logic(sensor_multi, hass: HomeAssistant) -> None:
    """Test that is_lights_on is True if ANY light is on."""
    # Both off
    set_state(hass, "light.1", STATE_OFF)
    set_state(hass, "light.2", STATE_OFF)
    state = sensor_multi._get_base_environment_state()
    assert state.is_lights_on is False

    # Light 1 On
    set_state(hass, "light.1", STATE_ON)
    set_state(hass, "light.2", STATE_OFF)
    state = sensor_multi._get_base_environment_state()
    assert state.is_lights_on is True

    # Light 2 On
    set_state(hass, "light.1", STATE_OFF)
    set_state(hass, "light.2", STATE_ON)
    state = sensor_multi._get_base_environment_state()
    assert state.is_lights_on is True

    # Both On
    set_state(hass, "light.1", STATE_ON)
    set_state(hass, "light.2", STATE_ON)
    state = sensor_multi._get_base_environment_state()
    assert state.is_lights_on is True


@pytest.mark.asyncio
async def test_fans_and_logic_for_off(sensor_multi, hass: HomeAssistant) -> None:
    """Test that fan_off is True only if ALL fan are off."""
    # Both off -> fan_off = True
    set_state(hass, "fan.1", STATE_OFF)
    set_state(hass, "fan.2", STATE_OFF)
    state = sensor_multi._get_base_environment_state()
    assert state.fan_off is True

    # Fan 1 On -> fan_off = False (system is active)
    set_state(hass, "fan.1", STATE_ON)
    set_state(hass, "fan.2", STATE_OFF)
    state = sensor_multi._get_base_environment_state()
    assert state.fan_off is False

    # Fan 2 On
    set_state(hass, "fan.1", STATE_OFF)
    set_state(hass, "fan.2", STATE_ON)
    state = sensor_multi._get_base_environment_state()
    assert state.fan_off is False

    # Both On
    set_state(hass, "fan.1", STATE_ON)
    set_state(hass, "fan.2", STATE_ON)
    state = sensor_multi._get_base_environment_state()
    assert state.fan_off is False
