"""Tests for the Growspace Manager binary_sensor platform."""

from __future__ import annotations

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
    coordinator._calculate_days.side_effect = _calculate_days_side_effect
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
) -> dict[str, list[MagicMock]]:
    """Create a mock history list for get_significant_states."""
    mock_states = []
    for dt, state_val in states:
        mock_state = MagicMock()
        mock_state.last_updated = dt
        mock_state.state = str(state_val)
        mock_states.append(mock_state)
    return {"sensor.temp": mock_states}


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant, mock_coordinator: MagicMock):
    """Test the binary sensor platform setup."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(hass, config_entry, async_add_entities)
    await hass.async_block_till_done()

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]

    assert len(entities) == 14  # 10 sensors for gs1 + 2 drying + 2 curing
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}
    hass.data[DOMAIN][MOCK_CONFIG_ENTRY_ID]["coordinator"].growspaces[
        "gs1"
    ].environment_config = None

    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(hass, config_entry, async_add_entities)
    await hass.async_block_till_done()

    assert async_add_entities.called
    entities = async_add_entities.call_args.args[0]
    assert not any(e.growspace_id == "gs1" for e in entities)
    assert any(e.growspace_id == "dry" for e in entities)
    assert any(e.growspace_id == "cure" for e in entities)


def test_get_growth_stage_info(mock_coordinator):
    """Test _get_growth_stage_info calculates days correctly."""
    # Instantiation now only passes the three required arguments
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor._days_since = (
        lambda date_str: (
            date.today() - date.fromisoformat(date_str.split("T")[0])
        ).days
        if date_str
        else 0
    )
    info = sensor._get_growth_stage_info()
    assert info["veg_days"] == 30
    assert info["flower_days"] == 5


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
@pytest.mark.asyncio
async def test_notification_sending(
    mock_recorder, hass: HomeAssistant, mock_coordinator, env_config
):
    """Test that notifications are sent on state change."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    set_sensor_state(hass, "sensor.humidity", 60)
    set_sensor_state(hass, "sensor.vpd", 1.0)
    set_sensor_state(hass, "light.grow_light", "on")
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock):
        await sensor.async_update_and_notify()
    assert not sensor.is_on

    # Use patch.object on hass.services to mock async_call
    with (
        patch(
            "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
        ) as mock_service_call,
        patch.object(
            sensor, "get_notification_title_message", return_value=("Title", "Message")
        ) as mock_get_notification,
        patch.object(
            sensor,
            "_send_notification",
            new_callable=AsyncMock,
            wraps=sensor._send_notification,
        ) as mock_send,
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
    ):
        # First update, no state change, so no notification
        await sensor.async_update_and_notify()
        mock_get_notification.assert_not_called()
        mock_send.assert_not_called()

        # Second update, state changes to ON, triggering notification
        set_sensor_state(hass, "sensor.temp", 31)  # High heat stress
        await hass.async_block_till_done()
        await sensor.async_update_and_notify()

        mock_get_notification.assert_called_with(True)
        mock_send.assert_awaited_once_with("Title", "Message")
        # Check that hass.services.async_call was actually called by _send_notification
        mock_service_call.assert_called_once()


@pytest.mark.asyncio
async def test_send_notification_anti_spam(mock_coordinator, hass: HomeAssistant):
    """Test that notifications are not sent if within the cooldown period."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._last_notification_sent = utcnow() - timedelta(minutes=1)

    # Patch at the class level
    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as mock_async_call:
        await sensor._send_notification("Test Title", "Test Message")
        mock_async_call.assert_not_called()


@pytest.mark.asyncio
async def test_send_notification_no_target(mock_coordinator, hass: HomeAssistant):
    """Test that notifications are not sent if no target is configured."""
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

    # Corrected instantiation
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor._probability = 0.1
    sensor.threshold = 0.49  # Corrected: Set threshold below 0.5
    sensor.entity_id = "binary_sensor.test_stress"
    sensor.platform = MagicMock()
    sensor.platform.platform_name = "growspace_manager"

    # Set up mock sensor values
    set_sensor_state(hass, "sensor.temp", sensor_readings.get("temp", 25))
    set_sensor_state(hass, "sensor.humidity", sensor_readings.get("humidity", 60))
    set_sensor_state(hass, "sensor.vpd", sensor_readings.get("vpd", 1.0))
    set_sensor_state(hass, "sensor.co2", sensor_readings.get("co2", 800))
    set_sensor_state(
        hass,
        "light.grow_light",
        "on" if sensor_readings.get("is_lights_on", True) else "off",
    )
    await hass.async_block_till_done()

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={
                "flower_days": sensor_readings.get("flower_days", 10),
                "veg_days": sensor_readings.get("veg_days", 20),
            },
        ),
        patch(
            "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
        ) as mock_service_call,
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
    ):
        await sensor.async_update_and_notify()

        # 1. Assert the sensor turned ON
        assert sensor.is_on, (
            f"Sensor did not turn ON for stress condition: {expected_reason_fragment}. Reasons: {sensor._reasons}"
        )

        # 2. Assert the notification was called
        mock_service_call.assert_called_once()

        # 3. Check that the expected reason fragment is in the notification message
        service_data = {}
        if "service_data" in mock_service_call.call_args.kwargs:
            service_data = mock_service_call.call_args.kwargs["service_data"]
        elif len(mock_service_call.call_args.args) >= 3:
            service_data = mock_service_call.call_args.args[2]

        message = service_data.get("message", "")
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    set_sensor_state(hass, "light.grow_light", sensor_readings.get("light", "on"))
    await hass.async_block_till_done()

    # Mock stage info
    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
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
            {"temp": 22, "humidity": 50, "vpd": 0.8, "light": "on"},
            {"veg_days": 30, "flower_days": 40},
            "Day VPD Low",
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    set_sensor_state(hass, "light.grow_light", sensor_readings.get("light", "on"))
    set_sensor_state(hass, "switch.fan", sensor_readings.get("fan", "on"))
    await hass.async_block_till_done()

    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
    set_sensor_state(hass, "light.grow_light", sensor_readings.get("light", "on"))
    await hass.async_block_till_done()

    # Mock stage info
    with (
        patch.object(sensor, "_get_growth_stage_info", return_value=stage_info),
        patch.object(sensor, "async_write_ha_state", new_callable=AsyncMock),
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
    hass.data[DOMAIN] = {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}

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
