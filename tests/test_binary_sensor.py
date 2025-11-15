"""Tests for the Growspace Manager binary_sensor platform."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import utcnow

from custom_components.growspace_manager.binary_sensor import (
    BayesianCuringSensor,
    BayesianDryingSensor,
    BayesianMoldRiskSensor,
    BayesianOptimalConditionsSensor,
    BayesianStressSensor,
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
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.async_add_listener = Mock()
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator):
    """Fixture for a mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {MOCK_CONFIG_ENTRY_ID: {"coordinator": mock_coordinator}}}
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    hass.states.get = Mock(return_value=None)
    return hass


async def test_async_setup_entry(mock_hass):
    """Test the binary sensor platform setup creates all expected sensors."""
    async_add_entities = AsyncMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args.args[0]

    # Expecting 3 base sensors for each of the 3 growspaces, plus the 2 specific ones
    assert len(entities) == 3 + 3 + 1 + 3 + 1

    assert any(
        isinstance(e, BayesianStressSensor) and e.growspace_id == "gs1" for e in entities
    )
    assert any(
        isinstance(e, BayesianDryingSensor) and e.growspace_id == "dry" for e in entities
    )
    assert any(
        isinstance(e, BayesianCuringSensor) and e.growspace_id == "cure" for e in entities
    )


async def test_async_setup_entry_no_env_config(mock_hass):
    """Test setup when a growspace has no environment config."""
    mock_hass.data[DOMAIN][MOCK_CONFIG_ENTRY_ID]["coordinator"].growspaces[
        "gs1"
    ].environment_config = None
    async_add_entities = AsyncMock()
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

    with patch.object(
        sensor, "_async_update_probability", side_effect=mock_update_prob
    ), patch.object(
        sensor, "_send_notification", new_callable=AsyncMock
    ) as mock_send:
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

    with patch.object(
        sensor, "_async_update_probability", side_effect=mock_update_prob
    ), patch.object(
        sensor, "_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await sensor.async_update_and_notify()
        assert not sensor.is_on
        mock_send.assert_called_once()


def test_generate_notification_message_truncation(mock_coordinator):
    """Test that the notification message is correctly truncated."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor._reasons = [
        (0.9, "VPD out of range"), # This will be added
        (0.8, "Temp is much too high for the current growth stage"), # This is too long
        (0.7, "Humidity is low"), # This will not be added because the loop breaks
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
    sensor.prior = 0.5  # Use a higher prior to test individual triggers

    # Set up the mock environment state from parameters
    env_state = {
        "temp": 25,
        "humidity": 50,
        "vpd": 1.2,
        "co2": 800,
        "veg_days": 15,
        "flower_days": 0,
        "is_lights_on": True,
        "fan_off": False,
    }
    env_state.update(sensor_readings)

    # Use a dataclass or a simple mock object for the state
    class MockEnvironmentState:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    mock_state_obj = MockEnvironmentState(**env_state)

    with patch.object(
        sensor, "_get_base_environment_state", return_value=mock_state_obj
    ), patch.object(
        sensor, "_async_analyze_sensor_trend", return_value={"trend": "stable"}
    ), patch.object(sensor, "async_write_ha_state", Mock()):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason_fragment in reason for _, reason in sensor._reasons)


# Tests for new sensors
@pytest.mark.parametrize(
    "sensor_readings, expected_on_state",
    [
        ({"temp": 18, "humidity": 50}, True),  # Optimal conditions
        ({"temp": 22, "humidity": 50}, False),  # Temp too high
        ({"temp": 18, "humidity": 60}, False),  # Humidity too high
        ({"temp": 14, "humidity": 50}, False),  # Temp too low
        ({"temp": 18, "humidity": 40}, False),  # Humidity too low
    ],
)
async def test_bayesian_drying_sensor(
    mock_coordinator, mock_hass, sensor_readings, expected_on_state
):
    """Test the BayesianDryingSensor logic."""
    sensor = BayesianDryingSensor(
        mock_coordinator, "dry", mock_coordinator.growspaces["dry"].environment_config
    )
    sensor.hass = mock_hass

    # Mock the base environment state
    class MockEnvironmentState:
        def __init__(self, **kwargs):
            self.temp = kwargs.get("temp")
            self.humidity = kwargs.get("humidity")
            self.vpd = None
            self.co2 = None
            self.veg_days = 0
            self.flower_days = 0
            self.is_lights_on = False
            self.fan_off = False

    with patch.object(
        sensor,
        "_get_base_environment_state",
        return_value=MockEnvironmentState(**sensor_readings),
    ), patch.object(sensor, "async_write_ha_state", Mock()):
        await sensor._async_update_probability()

    assert sensor.is_on == expected_on_state


# Trend Analysis Tests
@pytest.mark.parametrize(
    "history_data, expected_trend",
    [
        (
            [Mock(state="20"), Mock(state="22"), Mock(state="25")],
            "rising",
        ),
        (
            [Mock(state="25"), Mock(state="22"), Mock(state="20")],
            "falling",
        ),
        (
            [Mock(state="22"), Mock(state="22.05"), Mock(state="22")],
            "stable",
        ),
        ([], "stable"),  # No data
        ([Mock(state="25")], "stable"),  # Single data point
    ],
)
@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
async def test_async_analyze_sensor_trend(
    mock_get_recorder, mock_coordinator, mock_hass, history_data, expected_trend
):
    """Test the _async_analyze_sensor_trend method."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass

    # Configure the mock recorder to execute the lambda
    async def call_lambda(func):
        return func()

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job.side_effect = call_lambda
    mock_get_recorder.return_value = mock_recorder

    with patch(
        "custom_components.growspace_manager.binary_sensor.history.get_significant_states",
        return_value={"sensor.temp": history_data},
    ):
        result = await sensor._async_analyze_sensor_trend("sensor.temp", 30, 24)
        assert result["trend"] == expected_trend


@patch("custom_components.growspace_manager.binary_sensor.get_recorder_instance")
async def test_async_analyze_sensor_trend_crossing_threshold(
    mock_get_recorder, mock_coordinator, mock_hass
):
    """Test crossed_threshold logic in _async_analyze_sensor_trend."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass

    async def call_lambda(func):
        return func()

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job.side_effect = call_lambda
    mock_get_recorder.return_value = mock_recorder

    # All values are above the threshold
    history_data_above = [Mock(state="25"), Mock(state="26"), Mock(state="27")]
    with patch(
        "custom_components.growspace_manager.binary_sensor.history.get_significant_states",
        return_value={"sensor.temp": history_data_above},
    ):
        result = await sensor._async_analyze_sensor_trend("sensor.temp", 30, 24)
        assert result["crossed_threshold"]

    # One value is below the threshold
    history_data_mixed = [Mock(state="23"), Mock(state="26"), Mock(state="27")]
    with patch(
        "custom_components.growspace_manager.binary_sensor.history.get_significant_states",
        return_value={"sensor.temp": history_data_mixed},
    ):
        result = await sensor._async_analyze_sensor_trend("sensor.temp", 30, 24)
        assert not result["crossed_threshold"]


@pytest.mark.parametrize(
    "sensor_readings, expected_on_state",
    [
        ({"temp": 20, "humidity": 58}, True),  # Optimal conditions
        ({"temp": 22, "humidity": 58}, False),  # Temp too high
        ({"temp": 20, "humidity": 62}, False),  # Humidity too high
        ({"temp": 17, "humidity": 58}, False),  # Temp too low
        ({"temp": 20, "humidity": 54}, False),  # Humidity too low
    ],
)
async def test_bayesian_curing_sensor(
    mock_coordinator, mock_hass, sensor_readings, expected_on_state
):
    """Test the BayesianCuringSensor logic."""
    sensor = BayesianCuringSensor(
        mock_coordinator, "cure", mock_coordinator.growspaces["cure"].environment_config
    )
    sensor.hass = mock_hass

    class MockEnvironmentState:
        def __init__(self, **kwargs):
            self.temp = kwargs.get("temp")
            self.humidity = kwargs.get("humidity")
            self.vpd = None
            self.co2 = None
            self.veg_days = 0
            self.flower_days = 0
            self.is_lights_on = False
            self.fan_off = False

    with patch.object(
        sensor,
        "_get_base_environment_state",
        return_value=MockEnvironmentState(**sensor_readings),
    ), patch.object(sensor, "async_write_ha_state", Mock()):
        await sensor._async_update_probability()

    assert sensor.is_on == expected_on_state


# Edge Case Tests
@pytest.mark.parametrize(
    "bad_state",
    [
        None,  # Simulates a non-existent sensor
        Mock(state="unavailable"),
        Mock(state="unknown"),
        Mock(state="error"),  # Simulates a non-numeric state
    ],
)
async def test_sensor_handles_bad_data_gracefully(
    mock_coordinator, mock_hass, bad_state
):
    """Test that sensors handle bad underlying data gracefully."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass
    initial_prior = sensor.prior

    # Mock the state of the temperature sensor to be bad
    mock_hass.states.get = Mock(return_value=bad_state)

    with patch.object(
        sensor, "_async_analyze_sensor_trend", return_value={"trend": "stable"}
    ), patch.object(sensor, "async_write_ha_state", Mock()):
        await sensor._async_update_probability()

    # The probability should not have changed from the prior
    assert sensor._probability == initial_prior
    assert not sensor.is_on

# Parametrized tests for BayesianMoldRiskSensor
@pytest.mark.parametrize(
    "sensor_readings, expected_reason_fragment",
    [
        ({"humidity": 52, "is_lights_on": False}, "Night Humidity High"),
        ({"vpd": 1.2, "is_lights_on": False}, "Night VPD Low"),
        ({"humidity": 58, "is_lights_on": True}, "Day Humidity High"),
        ({"vpd": 1.1, "is_lights_on": True}, "Day VPD Low"),
        ({"fan_off": True}, "Circulation Fan Off"),
        ({"temp": 20}, "Temp in danger zone"),
    ],
)
async def test_bayesian_mold_risk_sensor_granular(
    mock_coordinator, mock_hass, sensor_readings, expected_reason_fragment
):
    """Test BayesianMoldRiskSensor triggers for specific individual conditions."""
    sensor = BayesianMoldRiskSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    sensor.hass = mock_hass

    # Mold risk is only high in late flower, so we set that as a baseline
    env_state = {
        "temp": 25,
        "humidity": 50,
        "vpd": 1.4,
        "co2": 800,
        "veg_days": 30,
        "flower_days": 40,
        "is_lights_on": True,
        "fan_off": False,
    }
    env_state.update(sensor_readings)

    class MockEnvironmentState:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    mock_state_obj = MockEnvironmentState(**env_state)

    with patch.object(
        sensor, "_get_base_environment_state", return_value=mock_state_obj
    ), patch.object(
        sensor, "_async_analyze_sensor_trend", return_value={"trend": "stable"}
    ), patch.object(sensor, "async_write_ha_state", Mock()):
        await sensor._async_update_probability()

    assert sensor.is_on
    assert any(expected_reason_fragment in reason for _, reason in sensor._reasons)
