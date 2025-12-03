"""Tests for the Growspace Manager binary_sensor platform."""

from __future__ import annotations

import logging  # Added this import
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import utcnow

from custom_components.growspace_manager.binary_sensor import (
    BayesianCuringSensor,
    BayesianDryingSensor,
    BayesianEnvironmentSensor,  # Added this import
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    BayesianStressSensor,
    LightCycleVerificationSensor,
    async_setup_entry,
)
from custom_components.growspace_manager.notification_manager import NotificationManager

MOCK_CONFIG_ENTRY_ID = "test_entry"


@pytest.fixture
def mock_growspace():
    """Fixture for a mock growspace with environment config."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.notification_target = "notify.test"
    growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
        "light_sensor": "light.grow_light",
        "stress_threshold": 0.7,
        "mold_threshold": 0.75,
        "optimal_threshold": 0.8,
        "drying_threshold": 0.8,
        "curing_threshold": 0.8,
        "prior_stress": 0.15,
        "prior_mold_risk": 0.10,
        "prior_optimal": 0.40,
        "prior_drying": 0.50,
        "prior_curing": 0.50,
    }
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator, building on the base fixture."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}

    drying_growspace = MagicMock()
    drying_growspace.name = "Drying Tent"
    drying_growspace.notification_target = None
    drying_growspace.environment_config = mock_growspace.environment_config.copy()
    drying_growspace.environment_config.update(
        {
            "temperature_sensor": "sensor.drying_temp",
            "humidity_sensor": "sensor.drying_humidity",
            "vpd_sensor": "sensor.drying_vpd",
        }
    )
    coordinator.growspaces["dry"] = drying_growspace

    curing_growspace = MagicMock()
    curing_growspace.name = "Curing Jars"
    curing_growspace.notification_target = None
    curing_growspace.environment_config = mock_growspace.environment_config.copy()
    curing_growspace.environment_config.update(
        {
            "temperature_sensor": "sensor.curing_temp",
            "humidity_sensor": "sensor.curing_humidity",
            "vpd_sensor": "sensor.curing_vpd",
        }
    )
    coordinator.growspaces["cure"] = curing_growspace

    coordinator.plants = {
        "p1": MagicMock(
            veg_start=(date.today() - timedelta(days=10)).isoformat(), flower_start=None
        ),
        "p2": MagicMock(
            veg_start=(date.today() - timedelta(days=30)).isoformat(),
            flower_start=(date.today() - timedelta(days=5)).isoformat(),
        ),
    }

    def _calculate_days_side_effect(start_date_str):
        if not start_date_str:
            return 0
        dt = date.fromisoformat(start_date_str.split("T")[0])
        return (date.today() - dt).days

    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.is_notifications_enabled.return_value = True
    coordinator.async_add_listener = Mock()
    coordinator.calculate_days.side_effect = _calculate_days_side_effect
    coordinator.options = {}  # Disable AI by default
    return coordinator


@pytest.fixture
def env_config(mock_growspace):
    """Fixture for a sample environment configuration."""
    return mock_growspace.environment_config


def set_sensor_state(hass: HomeAssistant, entity_id, state, attributes=None):
    """Helper to set a sensor's state in hass."""
    if state is None:
        hass.states.async_set(entity_id, STATE_UNKNOWN, attributes)
        return

    attrs = attributes or {}
    attrs.pop("last_changed", None)  # Remove last_changed, it's not a valid arg
    hass.states.async_set(entity_id, state, attrs)


def create_mock_history(
    states: list[tuple[datetime, float | str]],
) -> dict[str, list[State]]:
    """Create a mock history list for get_significant_states."""
    mock_states = []
    for dt, state_val in states:
        # Create a real State object
        state = State("sensor.temp", str(state_val), last_updated=dt)
        mock_states.append(state)
    return {"sensor.temp": mock_states}


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant, mock_coordinator: MagicMock):
    """Test the binary sensor platform setup."""

    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID
    config_entry.runtime_data = Mock(coordinator=mock_coordinator)

    await async_setup_entry(hass, config_entry, async_add_entities)
    await hass.async_block_till_done()

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]

    assert len(entities) == 10
    assert any(
        isinstance(e, BayesianStressSensor) and e.growspace_id == "gs1"
        for e in entities
    )
    assert any(
        isinstance(e, BayesianDryingSensor) and e.growspace_id == "dry"
        for e in entities
    )
    assert any(
        isinstance(e, BayesianCuringSensor) and e.growspace_id == "cure"
        for e in entities
    )


@pytest.mark.asyncio
async def test_async_setup_entry_no_env_config(hass: HomeAssistant, mock_coordinator):
    """Test setup when a growspace has no environment config."""
    mock_coordinator.growspaces["gs1"].environment_config = None

    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID
    config_entry.runtime_data = Mock(coordinator=mock_coordinator)

    await async_setup_entry(hass, config_entry, async_add_entities)
    await hass.async_block_till_done()

    assert async_add_entities.called
    entities = async_add_entities.call_args.args[0]
    assert not any(e.growspace_id == "gs1" for e in entities)
    assert any(e.growspace_id == "dry" for e in entities)
    assert any(e.growspace_id == "cure" for e in entities)


def test_get_growth_stage_info(mock_coordinator):
    """Test _get_growth_stage_info calculates days correctly."""
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    # _days_since is a static method, not an attribute - no need to mock it
    info = sensor._get_growth_stage_info()
    assert info["veg_days"] == 30
    assert info["flower_days"] == 5


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_notification_sending(
    mock_recorder, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test that notifications are sent on state change."""

    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_notification"
    sensor.platform = MagicMock()

    # Mock growspace object for notification target
    mock_coordinator.growspaces["gs1"].notification_target = "notify.test"
    mock_coordinator.is_notifications_enabled.return_value = True

    # Set initial state to "off" (no stress)
    set_sensor_state(hass, "sensor.temp", 25)  # Optimal temp
    set_sensor_state(hass, "sensor.humidity", 70)
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "light.grow_light", "on")
    await hass.async_block_till_done()
    # Mock notification manager to verify notification flow
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    with (
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
    ):
        await sensor.async_update_and_notify()
    assert not sensor.is_on

    # Second update - trigger notification by state change
    with (
        patch.object(
            sensor, "get_notification_title_message", return_value=("Title", "Message")
        ) as mock_get_notification,
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        # Change state to trigger notification
        set_sensor_state(hass, "sensor.temp", 31)  # High heat stress
        await hass.async_block_till_done()
        await sensor.async_update_and_notify()

        mock_get_notification.assert_called_with(True)
        # Verify notification was called
        sensor.notification_manager.async_send_notification.assert_awaited_once()
        call_args = sensor.notification_manager.async_send_notification.call_args
        assert call_args[0][0] == "gs1"  # growspace_id
        assert call_args[0][1] == "Title"
        assert call_args[0][2] == "Message"


@pytest.mark.asyncio
async def test_send_notification_anti_spam(mock_coordinator, hass: HomeAssistant):
    """Test that notifications are not sent if within the cooldown period."""

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    # Notification cooldown is handled by notification_manager, not the sensor
    # Mock the notification manager to simulate cooldown
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()
    sensor.notification_manager.should_send_notification = Mock(return_value=False)

    # Patch at the class level
    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as mock_async_call:
        await sensor._send_notification("Test Title", "Test Message")
        mock_async_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_notification_no_target(mock_coordinator, hass: HomeAssistant):
    """Test that notifications are not sent if no target is configured."""

    mock_coordinator.growspaces["gs1"].notification_target = None
    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass

    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as mock_async_call:
        await sensor._send_notification("Test Title", "Test Message")
        mock_async_call.assert_not_called()


@pytest.mark.asyncio
async def test_stress_sensor_notification_on_state_change(
    mock_coordinator, hass: HomeAssistant
):
    """Test stress sensor sends notification when state changes to on."""

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._probability = 0.1  # Start in OFF state (threshold is 0.7)
    sensor.platform = MagicMock()
    sensor.entity_id = "binary_sensor.test_stress"

    async def mock_update_prob():
        sensor._probability = 0.9

    with (
        patch.object(sensor, "_async_update_probability", side_effect=mock_update_prob),
        patch.object(sensor, "_send_notification", new_callable=AsyncMock) as mock_send,
        # FIX: Add patch
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()
        assert sensor.is_on
        mock_send.assert_called_once()

        mock_send.reset_mock()
        await sensor.async_update_and_notify()
        assert sensor.is_on
        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_optimal_conditions_notification_on_state_change(
    mock_coordinator, hass: HomeAssistant
):
    """Test optimal sensor sends notification when state changes to off."""

    # Corrected instantiation
    sensor = BayesianOptimalConditionsSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._probability = 0.9  # Start in ON state (threshold is 0.8)
    sensor.platform = MagicMock()
    sensor.entity_id = "binary_sensor.test_optimal"

    async def mock_update_prob():
        sensor._probability = 0.5

    with (
        patch.object(sensor, "_async_update_probability", side_effect=mock_update_prob),
        patch.object(sensor, "_send_notification", new_callable=AsyncMock) as mock_send,
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()
        assert not sensor.is_on
        mock_send.assert_called_once()


def test_generate_notification_message_truncation(mock_coordinator):
    """Test that the notification message is correctly truncated."""
    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor._reasons = [
        (0.9, "VPD out of range"),
        (0.8, "Temp is much too high for the current growth stage"),
        (0.7, "Humidity is low"),
    ]
    message = sensor._generate_notification_message("Alert")
    assert len(message) < 65
    assert "VPD out of range" in message
    assert "Temp is much too high" not in message
    assert "Humidity is low" not in message
    assert message == "Alert, VPD out of range"


def test_stress_sensor_notification_returns_none_when_off(mock_coordinator, env_config):
    """Test that the stress sensor does not generate a notification when turning off."""
    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    notification = sensor.get_notification_title_message(new_state_on=False)
    assert notification is None


def test_mold_risk_sensor_notification_returns_none_when_off(
    mock_coordinator, env_config
):
    """Test that the mold risk sensor does not generate a notification when turning off."""
    sensor = BayesianMoldRiskSensor(mock_coordinator, "gs1", env_config)
    notification = sensor.get_notification_title_message(new_state_on=False)
    assert notification is None


def test_optimal_conditions_notification_returns_none_when_on(
    mock_coordinator, env_config
):
    """Test that the optimal conditions sensor does not generate a notification when turning on."""
    sensor = BayesianOptimalConditionsSensor(mock_coordinator, "gs1", env_config)
    notification = sensor.get_notification_title_message(new_state_on=True)
    assert notification is None


def test_mold_risk_sensor_notification_returns_tuple_when_on_and_growspace_exists(
    mock_coordinator, env_config
):
    """Test that the mold risk sensor generates a notification when turning on and growspace exists."""
    sensor = BayesianMoldRiskSensor(mock_coordinator, "gs1", env_config)
    with (
        patch.object(
            mock_coordinator, "growspaces", new=MagicMock()
        ) as mock_growspaces_dict,
        patch.object(
            sensor, "_generate_notification_message", return_value="Mocked message"
        ) as mock_generate_message,
    ):
        mock_growspace_obj = MagicMock()
        mock_growspace_obj.name = "Test Growspace"
        mock_growspaces_dict.get.return_value = mock_growspace_obj
        notification = sensor.get_notification_title_message(new_state_on=True)
        assert notification == ("High Mold Risk in Test Growspace", "Mocked message")
        mock_growspaces_dict.get.assert_called_once_with("gs1")
        mock_generate_message.assert_called_once_with("High mold risk detected")


def test_mold_risk_sensor_notification_returns_none_when_on_and_growspace_does_not_exist(
    mock_coordinator, env_config
):
    """Test that the mold risk sensor does not generate a notification when turning on and growspace does not exist."""
    sensor = BayesianMoldRiskSensor(mock_coordinator, "gs1", env_config)
    with (
        patch.object(
            mock_coordinator, "growspaces", new=MagicMock()
        ) as mock_growspaces_dict,
        patch.object(sensor, "_generate_notification_message") as mock_generate_message,
    ):
        mock_growspaces_dict.get.return_value = None
        notification = sensor.get_notification_title_message(new_state_on=True)
        assert notification is None
        mock_growspaces_dict.get.assert_called_once_with("gs1")
        mock_generate_message.assert_not_called()


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.parametrize(
    "sensor_readings, expected_reason_fragment",
    [
        ({"temp": 33}, "Extreme Heat"),
        ({"temp": 14}, "Extreme Cold"),
        ({"temp": 25, "is_lights_on": False}, "Night Temp High"),
        ({"humidity": 30}, "Humidity Dry"),
        ({"humidity": 75, "veg_days": 20, "flower_days": 0}, "Humidity High"),
        ({"vpd": 0.2, "veg_days": 10, "flower_days": 0}, "VPD out of range"),
        ({"vpd": 1.7, "flower_days": 10}, "VPD out of range"),
        ({"co2": 350}, "CO2 Low"),
        ({"co2": 1900, "humidity": 50}, "CO2 High"),
    ],
)
@pytest.mark.asyncio
async def test_bayesian_stress_sensor_granular(
    mock_analyze_trend,
    mock_coordinator,
    hass: HomeAssistant,
    sensor_readings,
    expected_reason_fragment,
):
    """Test BayesianStressSensor triggers for specific individual conditions."""

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_stress_granular"
    sensor._probability = 0.1  # Start as OFF
    sensor.platform = MagicMock()
    sensor.threshold = 0.49  # Lower threshold for single observation
    sensor.prior = 0.5  # Set neutral prior to allow single observations to trigger

    # Fix mocking for notification manager
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()
    sensor.notification_manager.async_process_ai_notification = AsyncMock()
    sensor.notification_manager.hass = hass

    # Mock sensor states
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp", 25))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity", 60))
    set_sensor_state(hass, "sensor.vpd", sensor_readings.get("vpd", 1.0))
    set_sensor_state(hass, "sensor.co2", sensor_readings.get("co2", 800))
    light_state = "on" if sensor_readings.get("is_lights_on", True) else "off"
    set_sensor_state(hass, "light.grow_light", light_state)
    await hass.async_block_till_done()

    # Avoid light hysteresis
    sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
    sensor._last_light_state = True if light_state == "on" else False

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={
                "flower_days": sensor_readings.get("flower_days", 10),
                "veg_days": sensor_readings.get("veg_days", 20),
            },
        ),
        patch("homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        # Mock generate_notification_message to return string representation of reasons
        sensor.notification_manager.generate_notification_message.side_effect = (
            lambda *args: str(args)
        )

        await sensor.async_update_and_notify()

        # 1. Assert the sensor turned ON
        assert sensor.is_on, (
            f"Sensor did not turn ON for stress condition: {expected_reason_fragment}. "
            f"Probability: {sensor._probability}. Reasons: {sensor._reasons}"
        )

        # 2. Assert the notification was called
        sensor.notification_manager.async_send_notification.assert_called_once()

        # 3. Check that the expected reason fragment is in the notification message
        call_args = sensor.notification_manager.async_send_notification.call_args
        # args: (growspace_id, title, message, sensor_states)
        # Note: Depending on how it's called, message might be in args[2] or kwargs["message"]
        if call_args.kwargs and "message" in call_args.kwargs:
            message = call_args.kwargs["message"]
        else:
            message = call_args.args[2]

        assert expected_reason_fragment in message, (
            f"Expected '{expected_reason_fragment}' not in notification: '{message}'"
        )


@pytest.mark.parametrize(
    "state_value, expected",
    [
        ("25.5", 25.5),
        (STATE_UNAVAILABLE, None),
        (STATE_UNKNOWN, None),
        ("on", None),
        (None, None),
    ],
)
@pytest.mark.asyncio
async def test_get_sensor_value_edge_cases(
    hass: HomeAssistant, mock_coordinator, env_config, state_value, expected
):
    """Test the _get_sensor_value helper with various invalid states."""

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass

    if state_value is not None:
        set_sensor_state(hass, "sensor.temp", state_value)
        await hass.async_block_till_done()

    assert sensor._get_sensor_value("sensor.temp") == expected


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "history_data, duration, threshold, expected_trend, expected_crossed",
    [
        # Case 1: Rising trend
        (
            [
                (utcnow() - timedelta(minutes=10), 20.0),
                (utcnow(), 22.0),
            ],
            15,
            21.0,
            "rising",
            False,
        ),
        # Case 2: Falling trend
        (
            [
                (utcnow() - timedelta(minutes=10), 22.0),
                (utcnow(), 20.0),
            ],
            15,
            21.0,
            "falling",
            False,
        ),
        # Case 3: Stable trend
        (
            [
                (utcnow() - timedelta(minutes=10), 20.0),
                (utcnow(), 20.0),
            ],
            15,
            21.0,
            "stable",
            False,
        ),
        # Case 4: Not enough data
        (
            [
                (utcnow(), 20.0),
            ],
            15,
            21.0,
            "stable",
            False,
        ),
        # Case 5: Contains invalid states
        (
            [
                (utcnow() - timedelta(minutes=10), 20.0),
                (utcnow() - timedelta(minutes=5), STATE_UNAVAILABLE),
                (utcnow(), 22.0),
            ],
            15,
            21.0,
            "rising",
            False,
        ),
    ],
)
async def test_async_analyze_sensor_trend(
    mock_recorder,
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    history_data,
    duration,
    threshold,
    expected_trend,
    expected_crossed,
):
    """Test the _async_analyze_sensor_trend helper."""

    mock_history = create_mock_history(history_data)
    mock_recorder.return_value.async_add_executor_job = AsyncMock(
        return_value=mock_history
    )

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.platform = MagicMock()
    sensor.entity_id = "binary_sensor.test_trend"

    analysis = await sensor._async_analyze_sensor_trend(
        "sensor.temp", duration, threshold
    )

    assert analysis["trend"] == expected_trend
    assert analysis["crossed_threshold"] == expected_crossed


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.parametrize(
    "sensor_readings, stage_info, expected_reason",
    [
        # Case 1: High temp at night
        (
            {"temp": 30, "humidity": 60, "vpd": 0.8, "light": "off"},
            {"veg_days": 20, "flower_days": 0},
            "Night Temp High",
        ),
        # Case 2: High humidity in late veg
        (
            {"temp": 25, "humidity": 90, "vpd": 1.0, "light": "on"},
            {"veg_days": 20, "flower_days": 0},
            "Humidity High",
        ),
        # Case 3: High humidity in late flower
        (
            {"temp": 25, "humidity": 65, "vpd": 1.0, "light": "on"},
            {"veg_days": 30, "flower_days": 50},
            "Humidity out of range",
        ),
        # Case 4: VPD stress in early flower (day)
        (
            {"temp": 25, "humidity": 60, "vpd": 0.5, "light": "on"},
            {"veg_days": 30, "flower_days": 10},
            "VPD out of range",
        ),
        # Case 5: VPD stress in late flower (night)
        (
            {"temp": 20, "humidity": 60, "vpd": 0.5, "light": "off"},
            {"veg_days": 30, "flower_days": 50},
            "VPD out of range",
        ),
    ],
)
@pytest.mark.asyncio
async def test_stress_sensor_stage_and_time_logic(
    mock_analyze_trend,
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianStressSensor with stage- and time-specific logic."""

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_stress_complex"
    sensor.platform = MagicMock()
    sensor.threshold = 0.49  # Lower threshold for single observation

    # Mock sensor states
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp", 25))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity", 60))
    set_sensor_state(hass, "sensor.vpd", sensor_readings.get("vpd", 1.0))
    light_state = sensor_readings.get("light", "on")
    set_sensor_state(hass, "light.grow_light", light_state)
    await hass.async_block_till_done()

    # Avoid light hysteresis
    sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
    sensor._last_light_state = True if light_state == "on" else False

    # Mock stage info
    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.parametrize(
    "sensor_readings, stage_info, expected_reason",
    [
        # Case 1: High humidity at night in late flower
        (
            {"temp": 20, "humidity": 61, "vpd": 1.0, "light": "off"},
            {"veg_days": 30, "flower_days": 40},
            "Night Humidity High",
        ),
        # Case 2: Circulation fan is off in late flower
        (
            {"temp": 20, "humidity": 50, "vpd": 1.2, "light": "on", "fan": "off"},
            {"veg_days": 30, "flower_days": 40},
            "Circulation Fan Off",
        ),
        # Case 3: Low VPD (day) in late flower
        (
            {"temp": 22, "humidity": 50, "vpd": 0.8, "light": "on"},
            {"veg_days": 30, "flower_days": 40},
            "Day VPD Low",
        ),
        # Case 4: Low VPD at night in late flower
        (
            {"temp": 20, "humidity": 50, "vpd": 0.7, "light": "off"},
            {"veg_days": 30, "flower_days": 40},
            "Night VPD Low",
        ),
        # Case 5: High humidity during day in late flower
        (
            {"temp": 22, "humidity": 65, "vpd": 1.0, "light": "on"},
            {"veg_days": 30, "flower_days": 40},
            "Day Humidity High",
        ),
    ],
)
@pytest.mark.asyncio
async def test_mold_risk_sensor_triggers(
    mock_analyze_trend,
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianMoldRiskSensor with specific triggers."""

    # Corrected instantiation
    sensor = BayesianMoldRiskSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold_complex"
    sensor.platform = MagicMock()
    sensor.threshold = 0.49

    # Mock sensor states
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp", 20))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity", 50))
    set_sensor_state(hass, "sensor.vpd", sensor_readings.get("vpd", 1.2))
    set_sensor_state(hass, "sensor.co2", sensor_readings.get("co2", 800))
    light_state = sensor_readings.get("light", "on")
    set_sensor_state(hass, "light.grow_light", light_state)
    set_sensor_state(hass, "switch.fan", sensor_readings.get("fan", "on"))
    await hass.async_block_till_done()

    # Avoid light hysteresis
    sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
    sensor._last_light_state = True if light_state == "on" else False

    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.parametrize(
    "sensor_readings, stage_info, expected_reason",
    [
        # Case 1: Temp too high in late flower (day)
        (
            {"temp": 28, "humidity": 45, "vpd": 1.5, "light": "on"},
            {"veg_days": 30, "flower_days": 50},
            "Temp out of range",
        ),
        # Case 2: VPD too low in veg (day)
        (
            {"temp": 25, "humidity": 80, "vpd": 0.3, "light": "on"},
            {"veg_days": 10, "flower_days": 0},
            "VPD out of range",
        ),
        # Case 3: CO2 too low
        (
            {"temp": 28, "humidity": 60, "vpd": 1.0, "co2": 10, "light": "on"},
            {"veg_days": 20, "flower_days": 0},
            "CO2 Low",
        ),
    ],
)
@pytest.mark.asyncio
async def test_optimal_sensor_off_states(
    mock_analyze_trend,
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianOptimalConditionsSensor for non-optimal (off) states."""

    # Corrected instantiation
    sensor = BayesianOptimalConditionsSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_optimal_fail"
    sensor._probability = 1.0  # Start as ON
    sensor.platform = MagicMock()

    # Mock sensor states
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp"))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity"))
    set_sensor_state(hass, "sensor.vpd", sensor_readings.get("vpd"))
    set_sensor_state(hass, "sensor.co2", sensor_readings.get("co2"))
    light_state = sensor_readings.get("light", "on")
    set_sensor_state(hass, "light.grow_light", light_state)
    await hass.async_block_till_done()

    # Avoid light hysteresis
    sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
    sensor._last_light_state = True if light_state == "on" else False

    # Mock stage info
    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor._async_update_probability()

    assert not sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.parametrize(
    "sensor_class, growspace_id, sensor_readings, expected_reason",
    [
        # Case 1: Drying sensor, temp too high
        (
            BayesianDryingSensor,
            "dry",
            {"temp": 25, "humidity": 50},
            "Temp out of range",
        ),
        # Case 2: Drying sensor, humidity too low
        (
            BayesianDryingSensor,
            "dry",
            {"temp": 18, "humidity": 40},
            "Humidity out of range",
        ),
        # Case 3: Curing sensor, temp too low
        (
            BayesianCuringSensor,
            "cure",
            {"temp": 15, "humidity": 58},
            "Temp out of range",
        ),
        # Case 4: Curing sensor, humidity too high
        (
            BayesianCuringSensor,
            "cure",
            {"temp": 20, "humidity": 65},
            "Humidity out of range",
        ),
    ],
)
@pytest.mark.asyncio
async def test_dry_cure_sensors_off_states(
    mock_analyze_trend,
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    sensor_class,
    growspace_id,
    sensor_readings,
    expected_reason,
):
    """Test Drying and Curing sensors for non-optimal (off) states."""

    # Set up a specific growspace for this test
    mock_coordinator.growspaces[growspace_id].name = growspace_id.capitalize()

    # Corrected instantiation
    sensor = sensor_class(
        mock_coordinator,
        growspace_id,
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = f"binary_sensor.test_{growspace_id}_fail"
    sensor._probability = 1.0  # Start as ON
    sensor.platform = MagicMock()  # Mock platform

    # Mock sensor states
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp", 20))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity", 55))
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock):
        await sensor._async_update_probability()

    assert not sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@pytest.mark.asyncio
async def test_curing_sensor_skips_if_not_cure_growspace(mock_coordinator, env_config):
    """Test that the Curing sensor skips probability calculation if growspace_id is not 'cure'."""
    # Create a Curing sensor for a non-cure growspace
    sensor = BayesianCuringSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = MagicMock()
    sensor.entity_id = "binary_sensor.test_curing_non_cure"
    sensor._probability = 0.5  # Set an initial probability
    sensor.platform = MagicMock()

    with patch.object(
        sensor, "async_write_ha_state", new_callable=AsyncMock
    ) as mock_write_ha_state:
        await sensor._async_update_probability()

    assert sensor._probability == 0
    mock_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_drying_sensor_skips_if_not_dry_growspace(mock_coordinator, env_config):
    """Test that the Drying sensor skips probability calculation if growspace_id is not 'dry'."""
    # Create a Drying sensor for a non-dry growspace
    sensor = BayesianDryingSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = MagicMock()
    sensor.entity_id = "binary_sensor.test_drying_non_dry"
    sensor._probability = 0.5  # Set an initial probability
    sensor.platform = MagicMock()

    with patch.object(
        sensor, "async_write_ha_state", new_callable=AsyncMock
    ) as mock_write_ha_state:
        await sensor._async_update_probability()

    assert sensor._probability == 0
    mock_write_ha_state.assert_called_once()


def test_light_cycle_verification_sensor_is_on_property(mock_coordinator, env_config):
    """Test the is_on property of LightCycleVerificationSensor."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor._is_correct = True
    assert sensor.is_on is True
    sensor._is_correct = False
    assert sensor.is_on is False


def test_light_cycle_verification_sensor_extra_state_attributes_veg_stage(
    mock_coordinator, env_config
):
    """Test extra_state_attributes for LightCycleVerificationSensor in veg stage."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.light_entity_id = "light.test_light"
    sensor._time_in_current_state = timedelta(hours=10)

    with patch.object(
        sensor,
        "_get_growth_stage_info",
        return_value={"veg_days": 20, "flower_days": 0},
    ):
        attrs = sensor.extra_state_attributes
        assert attrs["expected_schedule"] == "18/6"
        assert attrs["light_entity_id"] == "light.test_light"
        assert attrs["time_in_current_state"] == str(timedelta(hours=10))


def test_light_cycle_verification_sensor_extra_state_attributes_flower_stage(
    mock_coordinator, env_config
):
    """Test extra_state_attributes for LightCycleVerificationSensor in flower stage."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.light_entity_id = "light.test_light"
    sensor._time_in_current_state = timedelta(hours=8)

    with patch.object(
        sensor,
        "_get_growth_stage_info",
        return_value={"veg_days": 30, "flower_days": 40},
    ):
        attrs = sensor.extra_state_attributes
        assert attrs["expected_schedule"] == "12/12"
        assert attrs["light_entity_id"] == "light.test_light"
        assert attrs["time_in_current_state"] == str(timedelta(hours=8))


@pytest.mark.asyncio
async def test_light_cycle_verification_sensor_async_update_no_light_entity(
    hass: HomeAssistant, mock_coordinator, env_config
):
    """Test async_update when no light entity is configured."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = hass
    sensor.light_entity_id = None
    with patch.object(
        sensor, "async_write_ha_state", new_callable=AsyncMock
    ) as mock_write_ha_state:
        await sensor.async_update()
        assert not sensor._is_correct
        mock_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_light_cycle_verification_sensor_async_update_light_state_unavailable(
    hass: HomeAssistant, mock_coordinator, env_config
):
    """Test async_update when the light sensor state is unavailable."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = hass
    sensor.light_entity_id = "light.test_light"
    hass.states.async_set("light.test_light", STATE_UNAVAILABLE)
    with patch.object(
        sensor, "async_write_ha_state", new_callable=AsyncMock
    ) as mock_write_ha_state:
        await sensor.async_update()
        assert not sensor._is_correct
        mock_write_ha_state.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage_info, light_state, time_since_last_changed, expected_is_correct",
    [
        # Veg Stage
        ({"veg_days": 20, "flower_days": 0}, "on", timedelta(hours=17), True),
        ({"veg_days": 20, "flower_days": 0}, "on", timedelta(hours=19), False),
        ({"veg_days": 20, "flower_days": 0}, "off", timedelta(hours=5), True),
        ({"veg_days": 20, "flower_days": 0}, "off", timedelta(hours=7), False),
        # Flower Stage
        ({"veg_days": 30, "flower_days": 40}, "on", timedelta(hours=11), True),
        ({"veg_days": 30, "flower_days": 40}, "on", timedelta(hours=13), False),
        ({"veg_days": 30, "flower_days": 40}, "off", timedelta(hours=11), True),
        ({"veg_days": 30, "flower_days": 40}, "off", timedelta(hours=13), False),
    ],
)
async def test_light_cycle_verification_sensor_async_update(
    hass: HomeAssistant,
    mock_coordinator,
    env_config,
    stage_info,
    light_state,
    time_since_last_changed,
    expected_is_correct,
):
    """Test the async_update method of LightCycleVerificationSensor."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = hass
    sensor.light_entity_id = "light.test_light"

    now = utcnow()
    last_changed = now - time_since_last_changed
    mock_state = State("light.test_light", light_state, last_changed=last_changed)

    with (
        patch("homeassistant.core.StateMachine.get", return_value=mock_state),
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(
            sensor, "async_write_ha_state", new_callable=AsyncMock
        ) as mock_write_ha_state,
        patch(
            "custom_components.growspace_manager.binary_sensor.utcnow", return_value=now
        ),
    ):
        await sensor.async_update()
        assert sensor._is_correct == expected_is_correct
        assert sensor._time_in_current_state == time_since_last_changed
        mock_write_ha_state.assert_called_once()


@pytest.mark.parametrize(
    "plants, expected_veg, expected_flower",
    [
        ([], 0, 0),
        (
            [MagicMock(veg_start="2023-01-01", flower_start=None)],
            (date.today() - date(2023, 1, 1)).days,
            0,
        ),
        (
            [
                MagicMock(veg_start="2023-01-01", flower_start="2023-01-20"),
                MagicMock(veg_start="2022-12-01", flower_start="2023-01-10"),
            ],
            (date.today() - date(2022, 12, 1)).days,
            (date.today() - date(2023, 1, 10)).days,
        ),
        ([MagicMock(veg_start=None, flower_start=None)], 0, 0),
    ],
)
def test_light_cycle_get_growth_stage_info_scenarios(
    mock_coordinator, env_config, plants, expected_veg, expected_flower
):
    """Test _get_growth_stage_info with different plant scenarios."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    mock_coordinator.get_growspace_plants.return_value = plants
    mock_coordinator.calculate_days.side_effect = (
        lambda date_str: (date.today() - date.fromisoformat(date_str)).days
        if date_str
        else 0
    )

    result = sensor._get_growth_stage_info()

    assert result["veg_days"] == expected_veg
    assert result["flower_days"] == expected_flower


@patch(
    "custom_components.growspace_manager.binary_sensor.async_track_state_change_event"
)
@pytest.mark.asyncio
async def test_light_cycle_async_added_to_hass_with_light_entity(
    mock_track_state_change, mock_coordinator, env_config
):
    """Test async_added_to_hass with a light entity."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = MagicMock()
    # async_on_remove and async_update are methods, use Mock() not assignment
    with (
        patch.object(sensor, "async_on_remove", MagicMock()) as mock_on_remove,
        patch.object(sensor, "async_update", AsyncMock()) as mock_update,
    ):
        await sensor.async_added_to_hass()

        mock_coordinator.async_add_listener.assert_called_once_with(
            sensor._handle_coordinator_update
        )
        mock_track_state_change.assert_called_once_with(
            sensor.hass,
            [sensor.light_entity_id],
            sensor._async_light_sensor_changed,
        )
        mock_on_remove.assert_called_once()
        mock_update.assert_awaited_once()


@patch(
    "custom_components.growspace_manager.binary_sensor.async_track_state_change_event"
)
@pytest.mark.asyncio
async def test_light_cycle_async_added_to_hass_without_light_entity(
    mock_track_state_change, mock_coordinator, env_config
):
    """Test async_added_to_hass without a light entity."""
    env_config["light_sensor"] = None
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = MagicMock()
    # async_on_remove and async_update are methods, use Mock() not assignment
    with (
        patch.object(sensor, "async_on_remove", MagicMock()) as mock_on_remove,
        patch.object(sensor, "async_update", AsyncMock()) as mock_update,
    ):
        await sensor.async_added_to_hass()

        mock_coordinator.async_add_listener.assert_called_once_with(
            sensor._handle_coordinator_update
        )
        mock_track_state_change.assert_not_called()
        mock_on_remove.assert_not_called()
        mock_update.assert_awaited_once()


def test_light_cycle_callbacks(mock_coordinator, env_config):
    """Test the callbacks for coordinator and light sensor changes."""
    sensor = LightCycleVerificationSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = MagicMock()
    # async_update is a method, use patch.object
    with patch.object(sensor, "async_update", MagicMock()) as mock_update:
        # Test coordinator update
        sensor._handle_coordinator_update()
        sensor.hass.async_create_task.assert_called_once_with(mock_update())

        # Test light sensor change
        sensor.hass.async_create_task.reset_mock()
        sensor._async_light_sensor_changed(None)
        sensor.hass.async_create_task.assert_called_once_with(mock_update())


class TestBayesianEnvironmentSensor:
    """Tests for the BayesianEnvironmentSensor base class."""

    @pytest.fixture
    def base_sensor(self, mock_coordinator, env_config):
        """Fixture for a base BayesianEnvironmentSensor instance."""
        # BayesianEnvironmentSensor is abstract, so we need to mock its __init__
        # or use a concrete subclass for instantiation.
        # For testing base class properties, we can mock the __init__
        with patch(
            "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor.__init__",
            return_value=None,
        ):
            sensor = BayesianEnvironmentSensor(  # Corrected instantiation
                mock_coordinator,
                "gs1",
                env_config,
                "test_type",
                "Test Sensor",
                "prior_test",
                "threshold_test",
            )
            sensor.coordinator = mock_coordinator
            sensor.coordinator.options = {}  # Disable AI by default
            sensor.growspace_id = "gs1"
            sensor.env_config = env_config
            sensor.hass = MagicMock()
            sensor.hass.services.async_call = AsyncMock()
            sensor._reasons = []
            sensor._sensor_states = {}
            sensor.notification_manager = MagicMock()
            sensor.notification_manager.async_send_notification = AsyncMock()
            sensor.notification_manager.hass = sensor.hass
            sensor.trend_analyzer = MagicMock()
            sensor.trend_analyzer.hass = sensor.hass

            # Initialize light state tracking
            sensor._last_light_state = None
            sensor._last_light_change_time = None

            sensor._probability = 0.679
            sensor.threshold = 0.5
            sensor._sensor_states = {"temp": 25, "humidity": 60}
            sensor._reasons = [
                (0.9, "Reason A"),
                (0.8, "Reason B"),
                (0.7, "Reason C"),
            ]
            # Notification state is handled by notification_manager, not sensor attributes
            # Set a notification target for the growspace in the coordinator
            sensor.coordinator.growspaces["gs1"].notification_target = "notify.test"
            return sensor

    def test_extra_state_attributes(self, base_sensor):
        """Test the extra_state_attributes property."""
        attrs = base_sensor.extra_state_attributes
        assert attrs["probability"] == 0.679
        assert attrs["threshold"] == 0.5
        assert attrs["observations"] == {"temp": 25, "humidity": 60}
        assert attrs["reasons"] == ["Reason A", "Reason B", "Reason C"]

    @pytest.mark.parametrize(
        "prior, observations, expected_probability",
        [
            (0.5, [], 0.5),  # No observations, should return prior
            (0.5, [(0.9, 0.1)], 0.9),  # Single observation
            (0.5, [(0.9, 0.1), (0.8, 0.2)], 0.972972972972973),  # Multiple observations
            (0.1, [(0.1, 0.9), (0.2, 0.8)], 0.003076923076923077),
            (0.5, [(0, 0)], 0.5),  # total = 0, should return prior
            (0.5, [(0.0, 1.0), (0.0, 1.0)], 0.0),  # prob_true becomes 0
            (0.5, [(1.0, 0.0), (1.0, 0.0)], 1.0),  # prob_false becomes 0
        ],
    )
    def test_calculate_bayesian_probability(
        self,
        base_sensor,
        prior,
        observations,
        expected_probability,  # Added base_sensor here
    ):
        """Test the _calculate_bayesian_probability static method."""
        result = base_sensor._calculate_bayesian_probability(prior, observations)
        assert result == pytest.approx(expected_probability)

    @pytest.mark.asyncio  # Added this decorator
    async def test_async_update_probability_not_implemented(
        self, base_sensor
    ):  # Added async
        """Test that _async_update_probability raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            await base_sensor._async_update_probability()  # Added await

    def test_get_notification_title_message_base_class(self, base_sensor):
        """Test that get_notification_title_message returns None for the base class."""
        assert base_sensor.get_notification_title_message(True) is None
        assert base_sensor.get_notification_title_message(False) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_type", [AttributeError, TypeError, ValueError])
    async def test_send_notification_error_logging(
        self, base_sensor, exception_type, caplog
    ):
        """Test error logging when _send_notification fails."""
        # Mock the notification manager's async_send_notification to raise the exception
        base_sensor.notification_manager.async_send_notification.side_effect = (
            exception_type("Test Error")
        )

        with caplog.at_level(logging.ERROR):
            await base_sensor._send_notification("Title", "Message")
            assert "Failed to send notification to gs1: Test Error" in caplog.text

    @pytest.mark.asyncio
    async def test_send_notification_disabled_in_coordinator(self, base_sensor, caplog):
        """Test that no notification is sent if disabled in the coordinator."""
        # Use a real NotificationManager for this test to verify logic
        base_sensor.notification_manager = NotificationManager(
            base_sensor.hass, base_sensor.coordinator
        )

        base_sensor.coordinator.growspaces["gs1"].notification_target = "notify.test"
        base_sensor.coordinator.is_notifications_enabled.return_value = False

        # Mock hass.services.async_call
        base_sensor.hass.services.async_call = AsyncMock()

        with caplog.at_level(logging.DEBUG):
            await base_sensor._send_notification("Title", "Message")
            base_sensor.hass.services.async_call.assert_not_awaited()
            assert "Notifications disabled in coordinator for gs1" in caplog.text

    @pytest.mark.asyncio
    @patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
    async def test_async_analyze_sensor_trend_error_logging(
        self, mock_recorder, base_sensor, caplog
    ):
        """Test error logging in _async_analyze_sensor_trend."""
        # Mock async_analyze_sensor_trend to raise an exception
        base_sensor.trend_analyzer.async_analyze_sensor_trend = AsyncMock(
            side_effect=AttributeError("Test Error")
        )
        base_sensor.hass = MagicMock()  # Ensure hass is mocked
        base_sensor.trend_analyzer.hass = (
            base_sensor.hass
        )  # Ensure trend analyzer uses mocked hass

        with caplog.at_level(logging.ERROR):
            result = await base_sensor._async_analyze_sensor_trend(
                "sensor.temp", 15, 21.0
            )
            assert result == {"trend": "unknown", "crossed_threshold": False}
            assert (
                "Error analyzing sensor history for sensor.temp: Test Error"
                in caplog.text
            )

    @pytest.mark.parametrize(
        "date_str, expected_days",
        [
            ("2023-01-01", (date.today() - date(2023, 1, 1)).days),
            ("invalid-date", 0),
            (None, 0),
        ],
    )
    def test_days_since_scenarios(self, date_str, expected_days):
        """Test _days_since with various date strings."""
        if date_str == "invalid-date":
            with patch(
                "custom_components.growspace_manager.binary_sensor.datetime"
            ) as mock_datetime:
                mock_datetime.strptime.side_effect = ValueError
                mock_datetime.strptime.return_value.date.return_value = date(2023, 1, 1)
                mock_datetime.today.return_value = date.today()
                result = BayesianEnvironmentSensor._days_since(date_str)
                assert result == expected_days
        else:
            result = BayesianEnvironmentSensor._days_since(date_str)
            assert result == expected_days

    def test_get_growth_stage_info_no_plants(self, base_sensor):
        """Test _get_growth_stage_info when no plants are found."""
        base_sensor.coordinator.get_growspace_plants.return_value = []
        result = base_sensor._get_growth_stage_info()
        assert result == {"veg_days": 0, "flower_days": 0}

    @pytest.mark.asyncio
    @patch(
        "custom_components.growspace_manager.binary_sensor.async_track_state_change_event"
    )
    async def test_async_added_to_hass_scenarios(
        self, mock_track_state_change, base_sensor
    ):
        """Test async_added_to_hass with different sensor configurations."""
        base_sensor.hass = MagicMock()
        base_sensor.async_on_remove = MagicMock()
        base_sensor.async_update_and_notify = AsyncMock()
        base_sensor.coordinator.async_add_listener = MagicMock()

        # Scenario 1: All sensors configured
        base_sensor.env_config = {
            "temperature_sensor": "sensor.temp",
            "humidity_sensor": "sensor.humidity",
            "vpd_sensor": "sensor.vpd",
            "co2_sensor": "sensor.co2",
            "circulation_fan": "switch.fan",
        }
        await base_sensor.async_added_to_hass()
        base_sensor.coordinator.async_add_listener.assert_called_once_with(
            base_sensor._handle_coordinator_update
        )
        mock_track_state_change.assert_called_once_with(
            base_sensor.hass,
            [
                "sensor.temp",
                "sensor.humidity",
                "sensor.vpd",
                "sensor.co2",
                "switch.fan",
            ],
            base_sensor._async_sensor_changed,
        )
        base_sensor.async_on_remove.assert_called_once()
        base_sensor.async_update_and_notify.assert_awaited_once()

        # Reset mocks for next scenario
        base_sensor.coordinator.async_add_listener.reset_mock()
        mock_track_state_change.reset_mock()
        base_sensor.async_on_remove.reset_mock()
        base_sensor.async_update_and_notify.reset_mock()

        # Scenario 2: Some sensors are None
        base_sensor.env_config = {
            "temperature_sensor": "sensor.temp",
            "humidity_sensor": None,
            "vpd_sensor": "sensor.vpd",
            "co2_sensor": None,
            "circulation_fan": "switch.fan",
        }
        await base_sensor.async_added_to_hass()
        mock_track_state_change.assert_called_once_with(
            base_sensor.hass,
            ["sensor.temp", "sensor.vpd", "switch.fan"],
            base_sensor._async_sensor_changed,
        )

        # Reset mocks for next scenario
        base_sensor.coordinator.async_add_listener.reset_mock()
        mock_track_state_change.reset_mock()
        base_sensor.async_on_remove.reset_mock()
        base_sensor.async_update_and_notify.reset_mock()

        # Scenario 3: No sensors configured
        base_sensor.env_config = {
            "temperature_sensor": None,
            "humidity_sensor": None,
            "vpd_sensor": None,
            "co2_sensor": None,
            "circulation_fan": None,
        }
        await base_sensor.async_added_to_hass()
        mock_track_state_change.assert_called_once_with(
            base_sensor.hass, [], base_sensor._async_sensor_changed
        )

    def test_handle_coordinator_update_calls_async_update_and_notify(self, base_sensor):
        """Test that _handle_coordinator_update calls async_update_and_notify."""
        base_sensor.hass = MagicMock()
        base_sensor.async_update_and_notify = MagicMock()
        base_sensor._handle_coordinator_update()
        base_sensor.hass.async_create_task.assert_called_once_with(
            base_sensor.async_update_and_notify()
        )

    def test_async_sensor_changed_calls_async_update_and_notify(self, base_sensor):
        """Test that _async_sensor_changed calls async_update_and_notify."""
        base_sensor.hass = MagicMock()
        base_sensor.async_update_and_notify = MagicMock()
        base_sensor._async_sensor_changed(None)
        base_sensor.hass.async_create_task.assert_called_once_with(
            base_sensor.async_update_and_notify()
        )

    def test_get_sensor_value_no_sensor_id(self, base_sensor):
        """Test _get_sensor_value returns None if no sensor_id is provided."""
        result = base_sensor._get_sensor_value(None)
        assert result is None
        result = base_sensor._get_sensor_value("")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_base_environment_state_light_sensor_domain_sensor(
        self, base_sensor
    ):
        """Test _get_base_environment_state when light sensor is a sensor domain."""
        base_sensor.hass = MagicMock()
        base_sensor.env_config["light_sensor"] = "sensor.light_level"
        base_sensor._get_sensor_value = MagicMock(
            side_effect=[25.0, 60.0, 1.0, 800.0, 100.0, 0.0, 0.0]
        )  # Mock sensor values: temp, hum, vpd, co2, light, exhaust, humidifier

        # Mock light_state to have domain "sensor"
        mock_light_state = MagicMock(spec=State)
        mock_light_state.domain = "sensor"
        mock_light_state.state = (
            "100"  # This state won't be used if _get_sensor_value is mocked
        )
        base_sensor.hass.states.get.return_value = mock_light_state

        # Mock _get_growth_stage_info
        base_sensor._get_growth_stage_info = MagicMock(
            return_value={"veg_days": 20, "flower_days": 0}
        )

        # Test with sensor_value > 0
        # Avoid hysteresis
        base_sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
        base_sensor._last_light_state = True

        env_state = base_sensor._get_base_environment_state()
        assert env_state.is_lights_on is True

        base_sensor._get_sensor_value.side_effect = [
            25.0,
            60.0,
            1.0,
            800.0,
            0.0,
            0.0,
            0.0,
        ]  # Light sensor value is 0
        # Reset hysteresis avoidance for new state
        base_sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
        base_sensor._last_light_state = False

        env_state = base_sensor._get_base_environment_state()
        assert env_state.is_lights_on is False

        # Test with sensor_value is None
        base_sensor._get_sensor_value.side_effect = [
            25.0,
            60.0,
            1.0,
            800.0,
            None,
            0.0,
            0.0,
        ]  # Light sensor value is None
        base_sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
        base_sensor._last_light_state = False
        env_state = base_sensor._get_base_environment_state()
        assert env_state.is_lights_on is None  # None when sensor_value is None


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.binary_sensor.utcnow")
async def test_light_state_gradient_logic(
    mock_utcnow, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test the 5-minute gradient logic for light state transitions."""

    # Setup sensor
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_gradient"

    # Mock time
    initial_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)
    mock_utcnow.return_value = initial_time

    # 1. Initial State: Lights ON
    # Initialize light tracking to bypass hysteresis
    sensor._last_light_state = True  # Start with lights on
    sensor._last_light_change_time = initial_time - timedelta(
        minutes=10
    )  # Long enough ago
    set_sensor_state(hass, "light.grow_light", "on")
    set_sensor_state(hass, "sensor.temp", 25)  # Optimal day temp
    await hass.async_block_till_done()

    state = sensor._get_base_environment_state()
    assert state.is_lights_on is True
    assert sensor._last_light_state is True
    # No state change, so _last_light_change_time remains the same
    assert sensor._last_light_change_time == initial_time - timedelta(minutes=10)

    # 2. Lights turn OFF (Transition Start)
    set_sensor_state(hass, "light.grow_light", "off")
    await hass.async_block_till_done()

    # Time advances 2 minutes (within 5 min gradient)
    current_time = initial_time + timedelta(minutes=2)

    mock_utcnow.return_value = current_time

    state = sensor._get_base_environment_state()
    # Should still report as ON (previous state) because we are in the gradient
    assert state.is_lights_on is True
    # Internal state should be updated though
    assert sensor._last_light_state is False
    assert sensor._last_light_change_time == current_time

    # 3. Time advances to 6 minutes (Gradient Over)
    final_time = initial_time + timedelta(minutes=8)

    mock_utcnow.return_value = final_time

    state = sensor._get_base_environment_state()
    assert state.is_lights_on is False
    assert sensor._last_light_state is False
    # Change time should NOT have updated since the last change
    assert sensor._last_light_change_time == current_time


@pytest.mark.asyncio
async def test_dehumidifier_state_detection(
    hass: HomeAssistant, mock_coordinator, env_config
):
    """Test that dehumidifier state is correctly detected in environment state."""
    # Add dehumidifier entity to env_config
    env_config["dehumidifier_entity"] = "switch.dehumidifier"

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass

    # Test with dehumidifier ON
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 60)
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "switch.dehumidifier", "on")
    await hass.async_block_till_done()

    state = sensor._get_base_environment_state()
    assert state.dehumidifier_on is True

    # Test with dehumidifier OFF
    set_sensor_state(hass, "switch.dehumidifier", "off")
    await hass.async_block_till_done()

    state = sensor._get_base_environment_state()
    assert state.dehumidifier_on is False

    # Test with dehumidifier unavailable
    set_sensor_state(hass, "switch.dehumidifier", STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    state = sensor._get_base_environment_state()
    assert state.dehumidifier_on is False


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.asyncio
async def test_active_desiccation_low_humidity(
    mock_analyze_trend, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test Active Desiccation detection when dehumidifier is on with low humidity."""
    env_config["dehumidifier_entity"] = "switch.dehumidifier"

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_desiccation"
    sensor.platform = MagicMock()
    sensor.threshold = 0.7
    sensor.prior = 0.15

    # Set up dehumidifier ON with low humidity (< 40%)
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 35)  # Low humidity
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "switch.dehumidifier", "on")
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor._async_update_probability()

    # Should detect active desiccation
    assert sensor.is_on
    assert any("Active Desiccation" in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.asyncio
async def test_active_desiccation_high_vpd(
    mock_analyze_trend, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test Active Desiccation detection when dehumidifier is on with high VPD."""
    env_config["dehumidifier_entity"] = "switch.dehumidifier"

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_desiccation_vpd"
    sensor.platform = MagicMock()
    sensor.threshold = 0.7
    sensor.prior = 0.15

    # Set up dehumidifier ON with high VPD (> 1.5)
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 45)  # Normal humidity
    set_sensor_state(hass, "sensor.vpd", 1.8)  # High VPD
    set_sensor_state(hass, "switch.dehumidifier", "on")
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor._async_update_probability()

    # Should detect active desiccation
    assert sensor.is_on
    assert any("Active Desiccation" in reason for _, reason in sensor._reasons)
    assert any("High VPD 1.8kPa" in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.asyncio
async def test_active_saturation_veg_stage(
    mock_analyze_trend, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test Active Saturation detection in veg stage with humidifier on."""
    env_config["humidifier_sensor"] = "sensor.humidifier"

    # Set up plants in veg stage (flower_days = 0)
    mock_coordinator.plants = {
        "p1": MagicMock(
            veg_start=(date.today() - timedelta(days=20)).isoformat(), flower_start=None
        )
    }

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_saturation_veg"
    sensor.platform = MagicMock()
    sensor.threshold = 0.7
    sensor.prior = 0.15

    # Set up humidifier ON with high humidity in veg (> 75%)
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 80)  # High humidity for veg
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "sensor.humidifier", 50)  # Humidifier running
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor._async_update_probability()

    # Should detect active saturation
    assert sensor.is_on
    assert any("Active Saturation" in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.asyncio
async def test_active_saturation_flower_stage(
    mock_analyze_trend, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test Active Saturation detection in flower stage with humidifier on."""
    env_config["humidifier_sensor"] = "sensor.humidifier"

    # Set up plants in flower stage
    mock_coordinator.plants = {
        "p1": MagicMock(
            veg_start=(date.today() - timedelta(days=30)).isoformat(),
            flower_start=(date.today() - timedelta(days=10)).isoformat(),
        )
    }

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_saturation_flower"
    sensor.platform = MagicMock()
    sensor.threshold = 0.7
    sensor.prior = 0.15

    # Set up humidifier ON with high humidity in flower (> 60%)
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 65)  # High humidity for flower
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "sensor.humidifier", 50)  # Humidifier running
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor._async_update_probability()

    # Should detect active saturation
    assert sensor.is_on
    assert any("Active Saturation" in reason for _, reason in sensor._reasons)


@patch(
    "custom_components.growspace_manager.binary_sensor.BayesianEnvironmentSensor._async_analyze_sensor_trend",
    new_callable=AsyncMock,
    return_value={"trend": "stable", "crossed_threshold": False},
)
@pytest.mark.asyncio
async def test_no_desiccation_when_conditions_normal(
    mock_analyze_trend, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test that Active Desiccation is NOT triggered when conditions are normal."""
    env_config["dehumidifier_entity"] = "switch.dehumidifier"

    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        env_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_no_desiccation"
    sensor.platform = MagicMock()
    sensor.threshold = 0.7
    sensor.prior = 0.15

    # Set up dehumidifier ON but with normal humidity and VPD
    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 55)  # Normal humidity
    set_sensor_state(hass, "sensor.vpd", 1.0)  # Normal VPD
    set_sensor_state(hass, "switch.dehumidifier", "on")
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor._async_update_probability()

    # Should NOT detect active desiccation
    assert not any("Active Desiccation" in reason for _, reason in sensor._reasons)
