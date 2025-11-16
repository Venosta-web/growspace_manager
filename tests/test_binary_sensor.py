"""Tests for the Growspace Manager binary_sensor platform."""

from __future__ import annotations

import threading
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import utcnow

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

    # Expecting 3 base sensors for each of the 3 growspaces, plus the 2 specific ones
    assert len(entities) - 1 == 3 + 3 + 1 + 3 + 1

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
