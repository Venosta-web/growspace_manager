"""Tests for the Growspace Manager binary_sensor platform."""
from __future__ import annotations

import threading
from datetime import date, timedelta, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import utcnow

from custom_components.growspace_manager.binary_sensor import (
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
    """Fixture for a mock growspace."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
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
    }
    growspace.notification_target = "notify.test"
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.plants = {
        "p1": MagicMock(
            veg_start=(date.today() - timedelta(days=10)).isoformat(),
            flower_start=None,
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
    hass.data = {
        DOMAIN: {
            MOCK_CONFIG_ENTRY_ID: {
                "coordinator": mock_coordinator,
            }
        }
    }
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
    assert len(entities) == 4
    assert any(isinstance(e, BayesianStressSensor) for e in entities)
    assert any(isinstance(e, BayesianMoldRiskSensor) for e in entities)
    assert any(isinstance(e, BayesianOptimalConditionsSensor) for e in entities)
    assert any(isinstance(e, LightCycleVerificationSensor) for e in entities)


@pytest.mark.asyncio
async def test_async_setup_entry_no_env_config(mock_hass: HomeAssistant):
    """Test setup when growspace has no environment config."""
    mock_hass.data[DOMAIN][MOCK_CONFIG_ENTRY_ID]["coordinator"].growspaces[
        "gs1"
    ].environment_config = None
    async_add_entities = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = MOCK_CONFIG_ENTRY_ID

    await async_setup_entry(mock_hass, config_entry, async_add_entities)

    async_add_entities.assert_not_called()


def test_get_growth_stage_info(mock_coordinator):
    """Test _get_growth_stage_info calculates days correctly."""
    sensor = BayesianStressSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"].environment_config
    )
    # Mock _days_since to avoid issues with isoformat strings
    sensor._days_since = lambda d: (date.today() - date.fromisoformat(d.split("T")[0])).days if d else 0
    info = sensor._get_growth_stage_info()

    assert info["veg_days"] == 30
    assert info["flower_days"] == 5


@pytest.mark.asyncio
async def test_stress_sensor_notification(mock_coordinator, mock_hass):
    """Test that stress sensor sends notification only when state changes to on."""
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
    with patch.object(
        sensor, "_get_sensor_value", side_effect=[31, 75, 1.5, 300, None]
    ), patch.object(
        sensor, "_get_growth_stage_info", return_value={"flower_days": 10, "veg_days": 20}
    ), patch.object(sensor, "_async_analyze_sensor_trend", return_value={"trend": "stable", "crossed_threshold": False}):
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
