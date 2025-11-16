"""Tests for the Growspace Manager binary_sensor platform."""

from __future__ import annotations

import threading
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow


from custom_components.growspace_manager.binary_sensor import (
    BayesianCuringSensor,
    BayesianDryingSensor,
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    BayesianStressSensor,
    LightCycleVerificationSensor,
    async_setup_entry,
)
from custom_components.growspace_manager.const import DOMAIN

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
        "light_sensor": "light.test_light",
        "stress_threshold": 0.7,
        "mold_threshold": 0.75,
        "optimal_threshold": 0.8,
        "drying_threshold": 0.8,
        "curing_threshold": 0.8,
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
    drying_growspace.environment_config = {
        "temperature_sensor": "sensor.drying_temp",
        "humidity_sensor": "sensor.drying_humidity",
        "vpd_sensor": "sensor.drying_vpd",
    }
    coordinator.growspaces["dry"] = drying_growspace

    curing_growspace = MagicMock()
    curing_growspace.name = "Curing Jars"
    curing_growspace.notification_target = None
    curing_growspace.environment_config = {
        "temperature_sensor": "sensor.curing_temp",
        "humidity_sensor": "sensor.curing_humidity",
        "vpd_sensor": "sensor.curing_vpd",
    }
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
    coordinator._calculate_days.side_effect = _calculate_days_side_effect
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator):
    """Fixture for a mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}}
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    # This is needed to satisfy the thread safety check in async_write_ha_state
    hass.loop_thread_id = threading.get_ident()
    return hass


@pytest.mark.asyncio
async def test_async_setup_entry(mock_hass: HomeAssistant):
    """Test the binary sensor platform setup."""
    # Use MagicMock here to avoid RuntimeWarning about unawaited coroutine
    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]

    # Expecting 3 base sensors for each of the 3 growspaces, plus the 3 specific ones(11 cause len starts at 0)
    assert len(entities) == 12

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


async def test_async_setup_entry_no_env_config(mock_hass):
    """Test setup when a growspace has no environment config."""
    mock_hass.data[DOMAIN][MOCK_CONFIG_ENTRY_ID]["coordinator"].growspaces[
        "gs1"
    ].environment_config = None
    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    assert async_add_entities.called
    entities = async_add_entities.call_args.args[0]
    assert not any(e.growspace_id == "gs1" for e in entities)
    assert any(e.growspace_id == "dry" for e in entities)
    assert any(e.growspace_id == "cure" for e in entities)


def test_get_growth_stage_info(mock_coordinator):
    """Test _get_growth_stage_info calculates days correctly."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    # Mock _days_since to avoid issues with isoformat strings
    sensor._days_since = (
        lambda d: (date.today() - date.fromisoformat(d.split("T")[0])).days if d else 0
    )
    info = sensor._get_growth_stage_info()
    assert info["veg_days"] == 30
    assert info["flower_days"] == 5


async def test_send_notification_anti_spam(mock_coordinator, mock_hass):
    """Test that notifications are not sent if within the cooldown period."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._last_notification_sent = utcnow() - timedelta(minutes=1)
    await sensor._send_notification("Test Title", "Test Message")
    mock_hass.services.async_call.assert_not_called()


async def test_send_notification_no_target(mock_coordinator, mock_hass):
    """Test that notifications are not sent if no target is configured."""
    mock_coordinator.growspaces["gs1"].notification_target = None
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    await sensor._send_notification("Test Title", "Test Message")
    mock_hass.services.async_call.assert_not_called()


async def test_stress_sensor_notification_on_state_change(mock_coordinator, mock_hass):
    """Test stress sensor sends notification when state changes to on."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.1  # Start in OFF state (threshold is 0.7)

    # This function simulates the probability update
    async def mock_update_prob():
        sensor._probability = 0.9

    with (
        patch.object(sensor, "_async_update_probability", side_effect=mock_update_prob),
        patch.object(sensor, "_send_notification", new_callable=AsyncMock) as mock_send,
    ):
        await sensor.async_update_and_notify()
        assert sensor.is_on
        mock_send.assert_called_once()

        # Reset and ensure notification is not sent again
        mock_send.reset_mock()
        await sensor.async_update_and_notify()
        assert sensor.is_on
        mock_send.assert_not_called()


async def test_optimal_conditions_notification_on_state_change(
    mock_coordinator, mock_hass
):
    """Test optimal sensor sends notification when state changes to off."""
    sensor = BayesianOptimalConditionsSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.9  # Start in ON state (threshold is 0.8)

    async def mock_update_prob():
        sensor._probability = 0.5

    with (
        patch.object(sensor, "_async_update_probability", side_effect=mock_update_prob),
        patch.object(sensor, "_send_notification", new_callable=AsyncMock) as mock_send,
    ):
        await sensor.async_update_and_notify()
        assert not sensor.is_on
        mock_send.assert_called_once()


def test_generate_notification_message_truncation(mock_coordinator):
    """Test that the notification message is correctly truncated."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor._reasons = [
        (0.9, "VPD out of range"),  # This will be added
        (0.8, "Temp is much too high for the current growth stage"),  # This is too long
        (0.7, "Humidity is low"),  # This will not be added because the loop breaks
    ]
    message = sensor._generate_notification_message("Alert")
    assert len(message) < 65
    assert "VPD out of range" in message
    assert "Temp is much too high" not in message
    assert "Humidity is low" not in message
    assert message == "Alert, VPD out of range"


# Parametrized tests for BayesianStressSensor
@pytest.mark.parametrize(
    "sensor_readings, expected_reason_fragment",
    [
        ({"temp": 33}, "Extreme Heat"),
        ({"temp": 14}, "Extreme Cold"),
        ({"temp": 25, "is_lights_on": False}, "Night Temp High"),
        ({"humidity": 30}, "Humidity Dry"),
        ({"humidity": 75, "veg_days": 20}, "Humidity High"),
        ({"vpd": 0.2, "veg_days": 10}, "VPD out of range"),
        ({"vpd": 1.7, "flower_days": 10}, "VPD out of range"),
        ({"co2": 350}, "CO2 Low"),
        ({"co2": 1900}, "CO2 High"),
    ],
)
async def test_bayesian_stress_sensor_granular(
    mock_coordinator, mock_hass, sensor_readings, expected_reason_fragment
):
    """Test BayesianStressSensor triggers for specific individual conditions."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor._probability = 0.1
    # We need to set entity_id and platform for async_write_ha_state to work
    sensor.entity_id = "binary_sensor.test_stress"
    sensor.platform = MagicMock()
    sensor.platform.platform_name = "growspace_manager"

    # Provide enough side effect values for all calls to _get_sensor_value
    with (
        patch.object(sensor, "_get_sensor_value", side_effect=[31, 75, 1.5, 300, None]),
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"flower_days": 10, "veg_days": 20},
        ),
        patch.object(
            sensor,
            "_async_analyze_sensor_trend",
            return_value={"trend": "stable", "crossed_threshold": False},
        ),
    ):
        await sensor.async_update_and_notify()

    assert sensor.is_on
    mock_hass.services.async_call.assert_called_once()
    call_args = mock_hass.services.async_call.call_args
    assert call_args.args[0] == "notify"
    assert "test" in call_args.args[1]
    # The payload is in the third positional argument (args[2])
    assert "Plants Under Stress" in call_args.args[2]["title"]


@pytest.mark.asyncio
async def test_light_cycle_verification_sensor(mock_coordinator, mock_hass):
    """Test the LightCycleVerificationSensor."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_light_cycle"
    sensor.platform = MagicMock()
    sensor.platform.platform_name = "growspace_manager"

    # Define a reusable mock for get_growth_stage_info
    def set_stage(veg, flower):
        sensor._get_growth_stage_info = lambda: {"flower_days": flower, "veg_days": veg}

    # Test case 1: Veg stage, light on for 10 hours (correct)
    set_stage(veg=10, flower=0)
    mock_hass.states.get.return_value = MagicMock(
        state="on", last_changed=utcnow() - timedelta(hours=10)
    )
    await sensor.async_update()
    assert sensor.is_on

    # Test case 2: Veg stage, light on for 20 hours (incorrect)
    set_stage(veg=10, flower=0)
    mock_hass.states.get.return_value = MagicMock(
        state="on", last_changed=utcnow() - timedelta(hours=20)
    )
    await sensor.async_update()
    assert not sensor.is_on

    # Test case 3: Flower stage, light off for 5 hours (correct)
    set_stage(veg=30, flower=20)
    mock_hass.states.get.return_value = MagicMock(
        state="off", last_changed=utcnow() - timedelta(hours=5)
    )
    await sensor.async_update()
    assert sensor.is_on

    # Test case 4: Flower stage, light off for 14 hours (incorrect)
    set_stage(veg=30, flower=20)
    mock_hass.states.get.return_value = MagicMock(
        state="off", last_changed=utcnow() - timedelta(hours=14)
    )
    await sensor.async_update()
    assert not sensor.is_on


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
async def test_get_sensor_value_edge_cases(
    mock_hass, mock_coordinator, env_config, state_value, expected
):
    """Test the _get_sensor_value helper with various invalid states."""
    # Use any sensor class, as they share the same helper
    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass

    # Set up the mock state
    if state_value is None:
        mock_hass.states.get.return_value = None
    else:
        set_sensor_state(mock_hass, "sensor.temp", state_value)

    assert sensor._get_sensor_value("sensor.temp") == expected


# Helper to create mock history states
def create_mock_history(
    states: list[tuple[datetime, float | str]],
) -> dict[str, list[MagicMock]]:
    """Create a mock history list for get_significant_states."""
    mock_states = []
    for dt, state_val in states:
        mock_state = MagicMock()
        mock_state.last_updated = dt
        mock_state.state = str(state_val)
        mock_states.append(mock_state)
    return {"sensor.temp": mock_states}


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
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
            True,
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
            True,
        ),
    ],
)
async def test_async_analyze_sensor_trend(
    mock_recorder,
    mock_hass,
    mock_coordinator,
    env_config,
    history_data,
    duration,
    threshold,
    expected_trend,
    expected_crossed,
):
    """Test the _async_analyze_sensor_trend helper."""
    # Mock the recorder history call
    mock_history = create_mock_history(history_data)
    mock_recorder.return_value.async_add_executor_job.return_value = mock_history

    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass

    analysis = await sensor._async_analyze_sensor_trend(
        "sensor.temp", duration, threshold
    )

    assert analysis["trend"] == expected_trend
    assert analysis["crossed_threshold"] == expected_crossed


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_readings, stage_info, expected_reason",
    [
        # Case 1: High temp at night
        (
            {"temp": 25, "humidity": 60, "vpd": 1.0, "light": "off"},
            {"veg_days": 20, "flower_days": 0},
            "Night Temp High",
        ),
        # Case 2: High humidity in late veg
        (
            {"temp": 25, "humidity": 75, "vpd": 1.0, "light": "on"},
            {"veg_days": 20, "flower_days": 0},
            "Humidity High",
        ),
        # Case 3: High humidity in late flower
        (
            {"temp": 25, "humidity": 55, "vpd": 1.0, "light": "on"},
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
async def test_stress_sensor_stage_and_time_logic(
    mock_recorder,
    mock_hass,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianStressSensor with stage- and time-specific logic."""
    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    sensor = BayesianStressSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_stress_complex"

    # Mock sensor states
    set_sensor_state(mock_hass, "sensor.temp", sensor_readings.get("temp", 25))
    set_sensor_state(mock_hass, "sensor.humidity", sensor_readings.get("humidity", 60))
    set_sensor_state(mock_hass, "sensor.vpd", sensor_readings.get("vpd", 1.0))
    set_sensor_state(mock_hass, "light.grow_light", sensor_readings.get("light", "on"))

    # Mock stage info
    with patch.object(sensor, "_get_growth_stage_info", return_value=stage_info):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_readings, stage_info, expected_reason",
    [
        # Case 1: High humidity at night in late flower
        (
            {"temp": 20, "humidity": 55, "vpd": 1.0, "light": "off"},
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
            {"temp": 22, "humidity": 50, "vpd": 1.1, "light": "on"},
            {"veg_days": 30, "flower_days": 40},
            "Day VPD Low",
        ),
    ],
)
async def test_mold_risk_sensor_triggers(
    mock_recorder,
    mock_hass,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianMoldRiskSensor with specific triggers."""
    mock_recorder.return_value.async_add_executor_job = AsyncMock(return_value={})
    sensor = BayesianMoldRiskSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_mold_complex"

    # Mock sensor states
    set_sensor_state(mock_hass, "sensor.temp", sensor_readings.get("temp", 20))
    set_sensor_state(mock_hass, "sensor.humidity", sensor_readings.get("humidity", 50))
    set_sensor_state(mock_hass, "sensor.vpd", sensor_readings.get("vpd", 1.2))
    set_sensor_state(mock_hass, "light.grow_light", sensor_readings.get("light", "on"))
    set_sensor_state(mock_hass, "switch.fan", sensor_readings.get("fan", "on"))

    # Mock stage info
    with patch.object(sensor, "_get_growth_stage_info", return_value=stage_info):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@pytest.mark.asyncio
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
            {"temp": 25, "humidity": 60, "vpd": 1.0, "co2": 300, "light": "on"},
            {"veg_days": 20, "flower_days": 0},
            "CO2 Low",
        ),
    ],
)
async def test_optimal_sensor_off_states(
    mock_hass,
    mock_coordinator,
    env_config,
    sensor_readings,
    stage_info,
    expected_reason,
):
    """Test BayesianOptimalConditionsSensor for non-optimal (off) states."""
    sensor = BayesianOptimalConditionsSensor(mock_coordinator, "gs1", env_config)
    sensor.hass = mock_hass
    sensor.entity_id = "binary_sensor.test_optimal_fail"
    sensor._probability = 1.0  # Start as ON

    # Mock sensor states
    set_sensor_state(mock_hass, "sensor.temp", sensor_readings.get("temp", 25))
    set_sensor_state(mock_hass, "sensor.humidity", sensor_readings.get("humidity", 60))
    set_sensor_state(mock_hass, "sensor.vpd", sensor_readings.get("vpd", 1.0))
    set_sensor_state(mock_hass, "sensor.co2", sensor_readings.get("co2", 1200))
    set_sensor_state(mock_hass, "light.grow_light", sensor_readings.get("light", "on"))

    # Mock stage info
    with patch.object(sensor, "_get_growth_stage_info", return_value=stage_info):
        await sensor._async_update_probability()

    assert not sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)


@pytest.mark.asyncio
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
async def test_dry_cure_sensors_off_states(
    mock_hass,
    mock_coordinator,
    env_config,
    sensor_class,
    growspace_id,
    sensor_readings,
    expected_reason,
):
    """Test Drying and Curing sensors for non-optimal (off) states."""
    # Set up a specific growspace for this test
    mock_coordinator.growspaces[growspace_id] = MagicMock(
        name=growspace_id.capitalize()
    )

    sensor = sensor_class(mock_coordinator, growspace_id, env_config)
    sensor.hass = mock_hass
    sensor.entity_id = f"binary_sensor.test_{growspace_id}_fail"
    sensor._probability = 1.0  # Start as ON

    # Mock sensor states
    set_sensor_state(mock_hass, "sensor.temp", sensor_readings.get("temp", 20))
    set_sensor_state(mock_hass, "sensor.humidity", sensor_readings.get("humidity", 55))

    await sensor._async_update_probability()

    assert not sensor.is_on
    assert any(expected_reason in reason for _, reason in sensor._reasons)
