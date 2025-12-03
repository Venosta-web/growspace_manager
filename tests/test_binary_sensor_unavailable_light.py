"""Test binary sensor behavior when light sensor is unavailable."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

from custom_components.growspace_manager.binary_sensor import BayesianStressSensor


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
        "light_sensor": "light.grow_light",
        "stress_threshold": 0.7,
        "prior_stress": 0.15,
    }
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}

    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []
    coordinator.is_notifications_enabled.return_value = True
    coordinator.async_add_listener = Mock()
    coordinator.options = {}
    return coordinator


def set_sensor_state(hass, entity_id, state, attributes=None):
    """Helper to set a sensor's state in hass."""
    if state is None:
        hass.states.async_set(entity_id, STATE_UNKNOWN, attributes)
        return
    attrs = attributes or {}
    hass.states.async_set(entity_id, state, attrs)


@pytest.mark.asyncio
async def test_unavailable_light_sensor_no_night_stress(
    hass: HomeAssistant, mock_coordinator
):
    """Test that unavailable light sensor does not trigger Night Temp High stress."""

    # Setup sensor
    sensor = BayesianStressSensor(
        mock_coordinator,
        "gs1",
        mock_coordinator.growspaces["gs1"].environment_config,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_stress_unavailable_light"
    sensor.platform = MagicMock()

    # Mock notification manager
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()
    sensor.notification_manager.generate_notification_message.side_effect = (
        lambda *args: str(args)
    )

    # Mock trend analyzer
    sensor._async_analyze_sensor_trend = AsyncMock(
        return_value={"trend": "stable", "crossed_threshold": False}
    )

    # Scenario:
    # Light sensor is UNAVAILABLE
    # Temp is 30°C (High for night, but normal/warm for day)
    # If light was OFF (night), this would trigger "Night Temp High" (prob 0.8) -> Stress ON
    # If light is UNKNOWN, it should NOT trigger "Night Temp High" -> Stress OFF (or low prob)

    set_sensor_state(hass, "sensor.temp", 30)
    set_sensor_state(hass, "sensor.humidity", 60)
    set_sensor_state(hass, "sensor.vpd", 1.2)
    set_sensor_state(hass, "light.grow_light", STATE_UNAVAILABLE)
    await hass.async_block_till_done()

    # Avoid light hysteresis logic interfering (force update)
    sensor._last_light_change_time = utcnow() - timedelta(minutes=10)
    sensor._last_light_state = None

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor.async_update_and_notify()

    # Verify results
    # 1. Light state should be None
    assert sensor._sensor_states["is_lights_on"] is None

    # 2. Should NOT have "Night Temp High" in reasons
    reasons = [r[1] for r in sensor._reasons]
    assert not any("Night Temp High" in r for r in reasons), (
        f"Found Night Temp High in reasons: {reasons}"
    )

    # 3. Probability should be low (only "High Heat" or "Temp Warm" might trigger if configured, but 30 is borderline)
    # With 30C, it might hit "Temp Warm" (prob 0.65) or "High Heat" (>30).
    # Let's check if it triggered stress.
    # If it hit "High Heat" (>30), it might be ON. But we specifically want to avoid "Night Temp High".

    # Let's try 26C.
    # 26C is > 24C (Night Threshold). So if Night logic applies, it triggers Night Temp High.
    # 26C is NOT > 28C (Warm Threshold). So no other stress should trigger.

    set_sensor_state(hass, "sensor.temp", 26)
    await hass.async_block_till_done()

    with patch.object(sensor, "async_write_ha_state", new_callable=MagicMock):
        await sensor.async_update_and_notify()

    reasons = [r[1] for r in sensor._reasons]
    assert not any("Night Temp High" in r for r in reasons), (
        f"Found Night Temp High with 26C: {reasons}"
    )
    assert not sensor.is_on, f"Sensor triggered stress unexpectedly: {reasons}"
