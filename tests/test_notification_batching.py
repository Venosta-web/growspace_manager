"""Tests for notification batching logic in Growspace Manager."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.notification_manager import NotificationManager
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_gs_1"


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: MagicMock(
            name="Test Growspace", notification_target="notify.mobile_app_test"
        )
    }
    coordinator.is_notifications_enabled.return_value = True
    coordinator.options = {}
    return coordinator


@pytest.fixture
def manager(hass: HomeAssistant, mock_coordinator):
    """Notification manager fixture."""
    return NotificationManager(hass, mock_coordinator)


@pytest.fixture
def mock_sensor():
    """Mock sensor fixture."""
    sensor = MagicMock()
    sensor.growspace_id = GROWSPACE_ID
    sensor.name = "Test Sensor"
    sensor.is_on = True
    sensor.reasons = [(0.9, "Reason A"), (0.8, "Reason B")]
    sensor.sensor_states = {"temp": 25.0}
    sensor.get_notification_title_message.return_value = None
    return sensor


async def test_sensor_registration(manager, mock_sensor) -> None:
    """Test attaching and detaching sensors."""
    manager.attach_sensor(GROWSPACE_ID, mock_sensor)
    assert mock_sensor in manager._registered_sensors[GROWSPACE_ID]

    manager.detach_sensor(GROWSPACE_ID, mock_sensor)
    assert mock_sensor not in manager._registered_sensors[GROWSPACE_ID]


async def test_batching_trigger(manager, mock_sensor, hass: HomeAssistant) -> None:
    """Test that multiple triggers result in a single batched call."""
    manager.attach_sensor(GROWSPACE_ID, mock_sensor)

    with patch.object(manager, "async_send_notification") as mock_send:
        # Schedule notification
        manager.async_schedule_notification(GROWSPACE_ID)

        # Manually trigger batch to avoid waiting for timer in test
        await manager._async_send_batched_notification(GROWSPACE_ID)

        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        # args might be positional or keyword
        assert args[0] == GROWSPACE_ID
        assert "Test Sensor" in args[1]
        assert "Reason A" in args[2]


async def test_multiple_sensors_aggregation(manager, hass: HomeAssistant) -> None:
    """Test aggregation across multiple sensors."""
    s1 = MagicMock()
    s1.name = "Sensor 1"
    s1.is_on = True
    s1.reasons = [(0.9, "Hot")]
    s1.sensor_states = {"temp": 30}
    s1.get_notification_title_message.return_value = None

    s2 = MagicMock()
    s2.name = "Sensor 2"
    s2.is_on = True
    s2.reasons = [(0.8, "Dry")]
    s2.sensor_states = {"hum": 20}
    s2.get_notification_title_message.return_value = None

    manager.attach_sensor(GROWSPACE_ID, s1)
    manager.attach_sensor(GROWSPACE_ID, s2)

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        # growspace_id, title, message, sensor_states
        _, title, msg = args[0], args[1], args[2]
        s_states = mock_send.call_args[1].get("sensor_states")

        # Check title
        assert "Multiple Issues" in title
        # Check message contains both reasons
        assert "Hot" in msg
        assert "Dry" in msg
        # Check sensor states aggregated
        assert s_states["temp"] == 30
        assert s_states["hum"] == 20


async def test_cooldown_respected_globally(manager) -> None:
    """Test that global cooldown prevents batching."""
    manager.trigger_cooldown(GROWSPACE_ID)

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_not_awaited()


async def test_empty_active_sensors(manager) -> None:
    """Test that no notification is sent if no registered sensors are ON."""
    s1 = MagicMock(is_on=False)
    manager.attach_sensor(GROWSPACE_ID, s1)

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_not_awaited()
