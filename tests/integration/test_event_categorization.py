"""Tests for Growspace Event Categorization."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.models import EnvironmentConfig, GrowspaceType
from custom_components.growspace_manager.strategies.optimal import (
    OptimalConditionsEvaluatorStrategy,
)
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)
from homeassistant.core import HomeAssistant

MOCK_CONFIG_ENTRY_ID = "test_entry"


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
    )


@pytest.fixture
def mock_growspace():
    """Fixture for a mock growspace with environment config."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.growspace_type = GrowspaceType.FLOWER
    growspace.notification_target = "notify.test"
    growspace.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        vpd_sensor="sensor.vpd",
        co2_sensor="sensor.co2",
        circulation_fan_entities=["switch.fan"],
        light_sensors=["light.grow_light"],
        soil_moisture_sensor="sensor.soil_moisture",
        bayesian_options={
            "threshold_stress": 0.8,
            "threshold_mold": 0.8,
            "threshold_optimal": 0.9,
            "threshold_drying": 0.8,
            "threshold_curing": 0.8,
            "prior_stress": 0.15,
            "prior_mold_risk": 0.10,
            "prior_optimal": 0.40,
            "prior_drying": 0.50,
            "prior_curing": 0.50,
        },
    )
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.is_notifications_enabled.return_value = True
    coordinator.add_event = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_event_categorization(hass: HomeAssistant, mock_coordinator) -> None:
    """Test that events are categorized correctly."""

    # 1. Test Optimal Conditions Sensor -> Should be "environment"
    optimal_sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.OPTIMAL,
        OptimalConditionsEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    optimal_sensor.hass = hass
    optimal_sensor.entity_id = "binary_sensor.test_optimal"

    # Mock platform for translation key
    mock_platform = MagicMock()
    mock_platform.platform_name = "test_platform"
    mock_platform.domain = "test_domain"
    optimal_sensor.platform = mock_platform

    # Mock internal state to simulate an event
    # Start: ON
    with patch.object(
        optimal_sensor,
        "_async_update_probability",
        side_effect=lambda: setattr(optimal_sensor, "_probability", 0.95),
    ):
        await optimal_sensor.async_update_and_notify()

    assert optimal_sensor.is_on
    assert optimal_sensor._event_start_time is not None

    # End: OFF (triggers event creation)
    with patch.object(
        optimal_sensor,
        "_async_update_probability",
        side_effect=lambda: setattr(optimal_sensor, "_probability", 0.5),
    ):
        await optimal_sensor.async_update_and_notify()

    assert not optimal_sensor.is_on

    # Verify event added to coordinator
    mock_coordinator.add_event.assert_called()
    call_args = mock_coordinator.add_event.call_args_list[-1]
    event = call_args[0][1]

    assert event.sensor_type == GrowspaceSensorType.OPTIMAL
    assert event.category == "environment"
    assert event.severity >= 0.9  # Should track max probability

    # 2. Test Stress Sensor -> Should be "alert"
    mock_coordinator.add_event.reset_mock()

    stress_sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    stress_sensor.hass = hass
    stress_sensor.entity_id = "binary_sensor.test_stress"

    # Mock platform for translation key
    mock_platform = MagicMock()
    mock_platform.platform_name = "test_platform"
    mock_platform.domain = "test_domain"
    stress_sensor.platform = mock_platform

    # Start: ON
    with patch.object(
        stress_sensor,
        "_async_update_probability",
        side_effect=lambda: setattr(stress_sensor, "_probability", 0.9),
    ):
        await stress_sensor.async_update_and_notify()

    # End: OFF
    with patch.object(
        stress_sensor,
        "_async_update_probability",
        side_effect=lambda: setattr(stress_sensor, "_probability", 0.1),
    ):
        await stress_sensor.async_update_and_notify()

    # Verify events — rising edge fires one, falling edge fires another
    assert mock_coordinator.add_event.call_count == 2
    # Both events share the same sensor_type and category
    for call in mock_coordinator.add_event.call_args_list:
        event = call[0][1]
        assert event.sensor_type == GrowspaceSensorType.STRESS
        assert event.category == "alert"
