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
from custom_components.growspace_manager.const import ATTR_TIME_IN_CURRENT_STATE
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.notifications.formatting import (
    generate_notification_message,
)
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)
from homeassistant.const import STATE_UNAVAILABLE
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
    )

    if hass is not None:
        sensor.hass = hass
        sensor.trend_analyzer = TrendAnalyzer(hass)
        sensor.strategy = strategy_class(
            env_config=sensor.env_config,
            analyze_trend=lambda *args, **kwargs: sensor.async_analyze_sensor_trend(
                *args, **kwargs
            ),
            get_state=hass.states.get,
            get_growspace=lambda: coordinator.growspaces.get(growspace_id),
            get_notification_message=generate_notification_message,
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


# NOTE: the attach/detach batch-registration handshake was removed; sensors now
# push EvaluationSnapshots and a resolved (is_on=False) snapshot supersedes detach.


# NOTE: device-state helpers (light/fan/humidifier ON/OFF/None aggregation) moved
# to the EnvironmentStateAssembler; see tests/domain/test_environment_state_assembler.py.


# NOTE: the sensor's AI-auto-alert path (_send_notification) was removed; AI
# enrichment of alerts now lives in AlertMonitor._async_enrich_with_ai, gated by
# CONF_AI_AUTO_ALERTS, and is covered by the alert-monitor tests.


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
        sensor.strategy,
        "async_evaluate",
        AsyncMock(return_value=([(0.9, 0.1)], [("reason", "high")])),
    ):
        sensor.prior = 0.9
        with patch.object(sensor, "async_write_ha_state"):
            await sensor.async_update_and_notify()

    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert event.category == "environment"


# NOTE: light-flip cooldown detection moved off the sensor to the notification
# manager (driven by the snapshot's lights_on field).


@pytest.mark.asyncio
async def test_async_added_to_hass_schedules_initial_update(
    mock_coordinator, hass: HomeAssistant
) -> None:
    """Test async_added_to_hass schedules the initial update."""
    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
    )
    sensor.hass = hass

    with patch.object(
        mock_coordinator.config_entry, "async_create_background_task"
    ) as mock_create_task:
        await sensor.async_added_to_hass()
        mock_create_task.assert_called()
        coro = mock_create_task.call_args[0][1]
        coro.close()


# NOTE: fan/dehumidifier/exhaust-max scenarios moved to the assembler suite
# (tests/domain/test_environment_state_assembler.py).


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


# NOTE: humidifier ON/OFF/None aggregation moved to the assembler suite
# (tests/domain/test_environment_state_assembler.py).
