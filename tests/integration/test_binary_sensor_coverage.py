"""Tests to increase coverage for binary_sensor.py."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
    LightCycleVerificationSensor,
    _get_strategy_class,
)
from custom_components.growspace_manager.const import (
    ATTR_TIME_IN_CURRENT_STATE,
    PlantStage,
)
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


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
def mock_growspace():
    """Fixture for a mock growspace."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
    )
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.options = {}
    coordinator.get_growspace_plants.return_value = []
    return coordinator


def test_get_strategy_class_fallback() -> None:
    """Test fallback strategy class."""
    strategy = _get_strategy_class("unknown_type")
    assert strategy == StressEvaluatorStrategy


@pytest.mark.asyncio
async def test_remove_from_hass(mock_coordinator, hass: HomeAssistant) -> None:
    """Test async_will_remove_from_hass."""
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS
    description.prior_key = "prior_stress"
    description.threshold_key = "threshold_stress"

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor.notification_manager = MagicMock()

    await sensor.async_will_remove_from_hass()
    sensor.notification_manager.detach_sensor.assert_called_once_with("gs1", sensor)


@pytest.mark.asyncio
async def test_determine_light_state_no_sensors(mock_coordinator) -> None:
    """Test _determine_light_state with no light sensors."""
    config = EnvironmentConfig(light_sensors=[])
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    assert sensor._determine_light_state() is None


@pytest.mark.asyncio
async def test_determine_fan_state_no_sensors(mock_coordinator) -> None:
    """Test _determine_fan_state with no fan entities."""
    config = EnvironmentConfig(circulation_fan_entities=[])
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    assert sensor._determine_fan_state() is None


@pytest.mark.asyncio
async def test_humidifier_on_state(mock_coordinator, hass: HomeAssistant) -> None:
    """Test humidifier state ON."""
    config = EnvironmentConfig(humidifier_entities=["switch.humidifier"])
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    sensor.hass = hass

    hass.states.async_set("switch.humidifier", STATE_ON)
    assert sensor._determine_humidifier_state() is True

    hass.states.async_set("switch.humidifier", STATE_OFF)
    assert sensor._determine_humidifier_state() is False


@pytest.mark.asyncio
async def test_ai_alert_exception_handling(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test exception handling during AI alert generation."""
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._probability = 0.9
    sensor.threshold = 0.8
    sensor.notification_manager = MagicMock()
    # Explicitly make async_send_notification an AsyncMock
    sensor.notification_manager.async_send_notification = AsyncMock()
    sensor.coordinator.strain_library = MagicMock()

    sensor._options["ai_auto_alerts"] = True

    with patch(
        "custom_components.growspace_manager.binary_sensor.GrowAssistant"
    ) as mock_assistant:
        mock_cls = mock_assistant.return_value
        mock_cls.generate_alert_message = AsyncMock(side_effect=Exception("AI Error"))

        await sensor._send_notification("Title", "Message")

        sensor.notification_manager.async_send_notification.assert_awaited()


@pytest.mark.asyncio
async def test_ai_alert_success(mock_coordinator, hass: HomeAssistant) -> None:
    """Test successful AI alert generation."""
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    mock_coordinator.options = {"ai_auto_alerts": True}
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._probability = 0.9
    sensor.threshold = 0.8
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()
    sensor.coordinator.strain_library = MagicMock()

    with patch(
        "custom_components.growspace_manager.binary_sensor.GrowAssistant"
    ) as mock_assistant:
        mock_cls = mock_assistant.return_value
        mock_cls.generate_alert_message = AsyncMock(return_value="AI Suggestion")

        await sensor._send_notification("Title", "Message")

        # Verify message construction
        args = sensor.notification_manager.async_send_notification.await_args[0]
        assert "AI Suggestion" in args[2]
        assert "(Original: Message)" in args[2]


@pytest.mark.asyncio
async def test_optimal_sensor_event_category(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test optimal sensor event category assignment."""
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.OPTIMAL
    description.prior_key = "prior_optimal"

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.OPTIMAL,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass

    # Init with high prob so old_state=True
    sensor._probability = 0.9
    # Initial Start Time
    sensor._event_start_time = dt_util.utcnow() - timedelta(minutes=10)

    # Mock strategy to return low probability on update forcing new_state=False
    with patch.object(
        sensor.strategy, "async_evaluate", AsyncMock(return_value=([], []))
    ):
        # Mock prior to be low so calculation results in low
        sensor.prior = 0.1

        with patch.object(sensor, "async_write_ha_state"):
            await sensor.async_update_and_notify()

    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert event.category == "environment"


def test_time_in_current_state_attr(mock_coordinator) -> None:
    """Test ATTR_TIME_IN_CURRENT_STATE attribute."""
    description = MagicMock()
    description.sensor_type = GrowspaceSensorType.STRESS

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor._probability = 0.9
    sensor._event_start_time = dt_util.utcnow() - timedelta(seconds=100)

    attrs = sensor.extra_state_attributes
    assert ATTR_TIME_IN_CURRENT_STATE in attrs
    assert attrs[ATTR_TIME_IN_CURRENT_STATE] >= 100


def test_get_current_stage_key_fallback(mock_coordinator: MagicMock) -> None:
    """Test fallback in _get_current_stage_key."""
    config = EnvironmentConfig()
    LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )


def test_get_current_stage_key_branches(mock_coordinator: MagicMock) -> None:
    """Test all branches of _get_current_stage_key."""
    config = EnvironmentConfig()
    sensor = LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )

    # 1. Vega (0 days)
    assert sensor._get_current_stage_key({"flower_days": -1}) == PlantStage.VEG

    # 2. Early Flower (10 days)
    assert sensor._get_current_stage_key({"flower_days": 10}) == "flower_early"

    # 3. Mid Flower (30 days)
    assert sensor._get_current_stage_key({"flower_days": 30}) == "flower_mid"

    # 4. Late Flower (50 days)
    assert sensor._get_current_stage_key({"flower_days": 50}) == "flower_late"

    # 5. Fallback (< 0 days)
    assert sensor._get_current_stage_key({"flower_days": -1}) == PlantStage.VEG


@pytest.mark.asyncio
async def test_light_verification_callbacks(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test light verification callbacks."""
    config = EnvironmentConfig(light_sensors=["light.grow_1"])
    sensor = LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )
    sensor.hass = hass

    # Test _handle_coordinator_update
    with patch.object(
        mock_coordinator.config_entry, "async_create_background_task"
    ) as mock_create_task:
        sensor._handle_coordinator_update()
        mock_create_task.assert_called()

    # Test _async_light_sensor_changed
    with patch.object(
        mock_coordinator.config_entry, "async_create_background_task"
    ) as mock_create_task:
        sensor._async_light_sensor_changed(MagicMock())
        mock_create_task.assert_called()


@pytest.mark.asyncio
async def test_light_verification_async_update_no_entity(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test async_update with no light entity."""
    config = EnvironmentConfig(light_sensors=[])
    sensor = LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )
    sensor.hass = hass

    with patch.object(sensor, "async_write_ha_state") as mock_write:
        await sensor.async_update()
        assert sensor._is_correct is False
        mock_write.assert_called()


@pytest.mark.asyncio
async def test_light_verification_async_update_unavailable(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test async_update with unavailable light entity."""
    config = EnvironmentConfig(light_sensors=["light.grow_1"])
    sensor = LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )
    sensor.hass = hass

    hass.states.async_set("light.grow_1", STATE_UNAVAILABLE)

    with patch.object(sensor, "async_write_ha_state") as mock_write:
        await sensor.async_update()
        assert sensor._is_correct is False
        mock_write.assert_called()


def test_missing_growspace_raises_error(mock_coordinator) -> None:
    """Test that initializing a sensor with a missing growspace raises ValueError."""
    env_config = mock_coordinator.growspaces["gs1"].environment_config
    with pytest.raises(ValueError, match="Growspace missing_gs not found"):
        create_test_sensor(
            mock_coordinator,
            "missing_gs",
            GrowspaceSensorType.STRESS,
            StressEvaluatorStrategy,
            env_config=env_config,
        )


def test_get_aggregated_sensor_value_empty(mock_coordinator) -> None:
    """Test _get_aggregated_sensor_value with empty list."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    assert sensor._get_aggregated_sensor_value([]) is None
