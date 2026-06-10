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
    hass: HomeAssistant | None = None,
) -> BayesianEnvironmentSensor:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    from custom_components.growspace_manager.trend_analyzer import TrendAnalyzer

    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    sensor = BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )

    if hass is not None:
        sensor.hass = hass
        sensor.trend_analyzer = TrendAnalyzer(hass)
        notification_manager = coordinator.notification_manager
        sensor.strategy = strategy_class(
            env_config=sensor.env_config,
            analyze_trend=lambda *args, **kwargs: sensor.async_analyze_sensor_trend(*args, **kwargs),
            get_state=hass.states.get,
            get_growspace=lambda: coordinator.growspaces.get(growspace_id),
            get_notification_message=lambda msg, r: (
                notification_manager.generate_notification_message(msg, r)
                if notification_manager
                else msg
            ),
        )

    return sensor


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
        hass,
    )

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

    # 1. Empty (no plants) — returns EMPTY, not VEG
    assert sensor._get_current_stage_key({"flower_days": -1}) == "empty"

    # 2. Early Flower (10 days)
    assert sensor._get_current_stage_key({"flower_days": 10}) == "flower_early"

    # 3. Mid Flower (30 days)
    assert sensor._get_current_stage_key({"flower_days": 30}) == "flower_mid"

    # 4. Late Flower (50 days)
    assert sensor._get_current_stage_key({"flower_days": 50}) == "flower_late"

    # 5. No-plants fallback also returns EMPTY
    assert sensor._get_current_stage_key({"flower_days": -1}) == "empty"


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
        coro = mock_create_task.call_args[0][1]
        coro.close()

    # Test _async_light_sensor_changed
    with patch.object(
        mock_coordinator.config_entry, "async_create_background_task"
    ) as mock_create_task:
        sensor._async_light_sensor_changed(MagicMock())
        mock_create_task.assert_called()
        coro = mock_create_task.call_args[0][1]
        coro.close()


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


@pytest.mark.asyncio
async def test_trend_analyzer_not_initialized(mock_coordinator) -> None:
    """Test async_analyze_sensor_trend when trend_analyzer is not initialized."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.trend_analyzer = None
    res = await sensor.async_analyze_sensor_trend("sensor.temp", 10, 0.5)
    assert res == {"trend": "unknown", "crossed_threshold": False}


@pytest.mark.asyncio
async def test_trend_analyzer_exception_handling(mock_coordinator) -> None:
    """Test exception handling in async_analyze_sensor_trend."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.trend_analyzer = MagicMock()
    sensor.trend_analyzer.async_analyze_sensor_trend = AsyncMock(
        side_effect=ValueError("Trend error")
    )
    res = await sensor.async_analyze_sensor_trend("sensor.temp", 10, 0.5)
    assert res == {"trend": "unknown", "crossed_threshold": False}


def test_generate_notification_message_no_manager(mock_coordinator) -> None:
    """Test generate_notification_message when notification_manager is None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = None
    assert sensor.generate_notification_message("Hello") == "Hello"


@pytest.mark.asyncio
async def test_optimal_sensor_event_category_rising_edge(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test optimal sensor event category on rising edge."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.OPTIMAL,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["gs1"].environment_config,
        hass,
    )
    # Init with low prob so old_state=False
    sensor._probability = 0.1
    
    # Mock strategy to return high probability on update forcing new_state=True
    with patch.object(
        sensor.strategy, "async_evaluate", AsyncMock(return_value=([(0.9, 0.1)], [("reason", "high")]))
    ):
        sensor.prior = 0.9
        with patch.object(sensor, "async_write_ha_state"):
            await sensor.async_update_and_notify()
            
    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert event.category == "environment"


def test_get_base_environment_state_no_growspace(mock_coordinator, hass: HomeAssistant) -> None:
    """Test _get_base_environment_state when _get_growspace returns None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        hass=hass,
    )
    with patch.object(sensor, "_get_growspace", return_value=None):
        env_state = sensor._get_base_environment_state()
        assert env_state.temp is None



def test_check_light_state_change_no_notification_manager(mock_coordinator) -> None:
    """Test _check_light_state_change when notification_manager is None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = None
    sensor._last_light_state = True
    sensor._check_light_state_change(False)
    # Verify no exception is raised and it completes cleanly


@pytest.mark.asyncio
async def test_async_added_to_hass_no_notification_manager(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test async_added_to_hass when notification_manager is None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.notification_manager = None
    
    with patch.object(
        mock_coordinator.config_entry, "async_create_background_task"
    ) as mock_create_task:
        await sensor.async_added_to_hass()
        mock_create_task.assert_called()
        coro = mock_create_task.call_args[0][1]
        coro.close()


@pytest.mark.asyncio
async def test_remove_from_hass_no_notification_manager(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test async_will_remove_from_hass when notification_manager is None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.notification_manager = None

    await sensor.async_will_remove_from_hass()
    # Verify it completes without raising error


@pytest.mark.asyncio
async def test_send_notification_no_notification_manager(mock_coordinator) -> None:
    """Test _send_notification when notification_manager is None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = None
    await sensor._send_notification("Title", "Message")
    # Verify it exits cleanly


def test_determine_fan_state_scenarios(mock_coordinator, hass: HomeAssistant) -> None:
    """Test _determine_fan_state scenarios."""
    config = EnvironmentConfig(circulation_fan_entities=["switch.fan1", "switch.fan2"])
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    sensor.hass = hass

    # Scenario 1: One fan ON, one fan OFF -> should return False (not all are off)
    hass.states.async_set("switch.fan1", STATE_ON)
    hass.states.async_set("switch.fan2", STATE_OFF)
    assert sensor._determine_fan_state() is False

    # Scenario 2: All fans OFF -> should return True (all are off)
    hass.states.async_set("switch.fan1", STATE_OFF)
    hass.states.async_set("switch.fan2", STATE_OFF)
    assert sensor._determine_fan_state() is True

    # Scenario 3: All fans unavailable/unknown -> should return None
    hass.states.async_set("switch.fan1", STATE_UNAVAILABLE)
    hass.states.async_set("switch.fan2", STATE_UNAVAILABLE)
    assert sensor._determine_fan_state() is None


def test_determine_dehumidifier_state_scenarios(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test _determine_dehumidifier_state scenarios."""
    config = EnvironmentConfig(dehumidifier_entities=["switch.dehum1", "switch.dehum2"])
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    sensor.hass = hass

    # Scenario 1: One ON, one OFF -> should return True (any on)
    hass.states.async_set("switch.dehum1", STATE_ON)
    hass.states.async_set("switch.dehum2", STATE_OFF)
    assert sensor._determine_dehumidifier_state() is True

    # Scenario 2: All OFF -> should return False (none on)
    hass.states.async_set("switch.dehum1", STATE_OFF)
    hass.states.async_set("switch.dehum2", STATE_OFF)
    assert sensor._determine_dehumidifier_state() is False

    # Scenario 3: Unavailable/unknown -> should return None
    hass.states.async_set("switch.dehum1", STATE_UNAVAILABLE)
    hass.states.async_set("switch.dehum2", STATE_UNAVAILABLE)
    assert sensor._determine_dehumidifier_state() is None


def test_get_max_sensor_value_scenarios(mock_coordinator, hass: HomeAssistant) -> None:
    """Test _get_max_sensor_value scenarios."""
    config = EnvironmentConfig(exhaust_fan_entities=["sensor.ex1", "sensor.ex2"])
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    sensor.hass = hass

    # Scenario 1: Both have values -> should return max
    hass.states.async_set("sensor.ex1", "25.0")
    hass.states.async_set("sensor.ex2", "45.0")
    assert sensor._determine_exhaust_value() == pytest.approx(45.0)

    # Scenario 2: One is None, one has value -> should return the non-None one
    hass.states.async_set("sensor.ex1", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.ex2", "15.0")
    assert sensor._determine_exhaust_value() == pytest.approx(15.0)

    # Scenario 3: All None -> should return None
    hass.states.async_set("sensor.ex1", STATE_UNAVAILABLE)
    hass.states.async_set("sensor.ex2", STATE_UNAVAILABLE)
    assert sensor._determine_exhaust_value() is None

    # Scenario 4: No entities configured -> should return None
    empty_sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        EnvironmentConfig(exhaust_fan_entities=[]),
    )
    empty_sensor.hass = hass
    assert empty_sensor._determine_exhaust_value() is None


def test_light_verification_update_state_no_sensors(mock_coordinator) -> None:
    """Test _update_state when light_sensors is empty."""
    config = EnvironmentConfig(light_sensors=[])
    sensor = LightCycleVerificationSensor(
        mock_coordinator,
        "gs1",
        config,
        get_plants=mock_coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )
    sensor._update_state()
    assert sensor._is_schedule_matched is True


def test_generate_notification_message_with_manager(mock_coordinator) -> None:
    """Test generate_notification_message when notification_manager is not None."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.generate_notification_message.return_value = "Detailed: Hello"
    assert sensor.generate_notification_message("Hello") == "Detailed: Hello"
    sensor.notification_manager.generate_notification_message.assert_called_once_with(
        "Hello", sensor._reasons
    )


def test_determine_humidifier_state_scenarios(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test _determine_humidifier_state scenarios."""
    config = EnvironmentConfig(humidifier_entities=["switch.hum1", "switch.hum2"])
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        config,
    )
    sensor.hass = hass

    # Scenario 1: One ON, one OFF -> should return True (any on)
    hass.states.async_set("switch.hum1", STATE_ON)
    hass.states.async_set("switch.hum2", STATE_OFF)
    assert sensor._determine_humidifier_state() is True

    # Scenario 2: All OFF -> should return False (none on)
    hass.states.async_set("switch.hum1", STATE_OFF)
    hass.states.async_set("switch.hum2", STATE_OFF)
    assert sensor._determine_humidifier_state() is False

    # Scenario 3: Unavailable/unknown -> should return None (covers line 978->976)
    hass.states.async_set("switch.hum1", STATE_UNAVAILABLE)
    hass.states.async_set("switch.hum2", STATE_UNAVAILABLE)
    assert sensor._determine_humidifier_state() is None

    # Scenario 4: No humidifier entities configured -> should return None
    empty_sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        EnvironmentConfig(humidifier_entities=[]),
    )
    empty_sensor.hass = hass
    assert empty_sensor._determine_humidifier_state() is None

