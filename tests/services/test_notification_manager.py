"""Tests for the NotificationManager."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from common import create_plant
import pytest

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    MIN_STRESS_DURATION_SECONDS,
    NOTIFICATION_CHANNEL,
    NOTIFICATION_GROUP,
    NOTIFICATION_ICON,
    NotificationTier,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
)
from custom_components.growspace_manager.notification_manager import (
    NotificationManager,
    PendingAlert,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

GROWSPACE_ID = "test_growspace"
GROWSPACE_NAME = "Test Growspace"
NOTIFICATION_TARGET = "notify.mobile_app_test"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name=GROWSPACE_NAME,
            notification_target=NOTIFICATION_TARGET,
        )
    }
    coordinator.options = {}
    coordinator.async_save = AsyncMock()
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock()
    hass.data = {}
    hass.config = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def manager(mock_hass: MagicMock, mock_coordinator: MagicMock) -> NotificationManager:
    """Fixture for NotificationManager."""
    return NotificationManager(mock_hass, mock_coordinator)


def test_initialization(
    manager: NotificationManager, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test initialization."""
    assert manager.hass == mock_hass
    assert manager.coordinator == mock_coordinator
    assert manager._last_notification_sent == {}


def testgenerate_notification_message(manager: NotificationManager) -> None:
    """Test generating notification message."""
    base_message = "Base message"
    reasons = [(0.9, "Reason 1"), (0.8, "Reason 2")]

    message = manager.generate_notification_message(base_message, reasons)
    assert "Reason 1" in message
    assert "Reason 2" in message


async def test_async_send_notification_success(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test sending a notification successfully."""
    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_awaited_once_with(
        "notify",
        "mobile_app_test",
        {
            "message": "Test Message",
            "title": "Test Title",
            "data": {
                "group": NOTIFICATION_GROUP,
                "channel": NOTIFICATION_CHANNEL,
                "notification_icon": NOTIFICATION_ICON,
                "push": {"thread-id": NOTIFICATION_GROUP},
            },
        },
        blocking=False,
    )


async def test_async_send_notification_cooldown(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test notification cooldown."""
    now = dt_util.utcnow()
    with patch(
        "custom_components.growspace_manager.notification_manager.utcnow",
        return_value=now,
    ):
        # First notification
        await manager.async_send_notification(
            GROWSPACE_ID, "Test Title", "Test Message"
        )
        mock_hass.services.async_call.assert_awaited()
        mock_hass.services.async_call.reset_mock()

        # Second notification immediately (should be skipped)
        await manager.async_send_notification(
            GROWSPACE_ID, "Test Title", "Test Message"
        )
        mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_no_target(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test sending notification with no target configured."""
    mock_coordinator.growspaces[GROWSPACE_ID].notification_target = None

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_disabled(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test sending notification when disabled."""
    mock_coordinator.is_notifications_enabled.return_value = False

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_ai_rewrite(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test sending notification with AI rewrite."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
            CONF_NOTIFICATION_PERSONALITY: "Pirate",
        }
    }

    with patch(
        "custom_components.growspace_manager.notification_manager.conversation.async_converse",
        new_callable=AsyncMock,
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.error_code = None
        mock_result.response.response_type = None
        mock_result.response.speech = {
            "plain": {"speech": "Ahoy! Test Message Rewrite"}
        }
        mock_converse.return_value = mock_result

        await manager.async_send_notification(
            GROWSPACE_ID, "Test Title", "Test Message"
        )

        mock_hass.services.async_call.assert_awaited_once_with(
            "notify",
            "mobile_app_test",
            {
                "message": "Ahoy! Test Message Rewrite",
                "title": "Test Title",
                "data": {
                    "group": NOTIFICATION_GROUP,
                    "channel": NOTIFICATION_CHANNEL,
                    "notification_icon": NOTIFICATION_ICON,
                    "push": {"thread-id": NOTIFICATION_GROUP},
                },
            },
            blocking=False,
        )


async def test_async_check_timed_notifications(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test checking timed notifications."""
    mock_coordinator.options = {
        "timed_notifications": [
            {
                "id": "notify_1",
                "trigger_type": "veg",
                "day": 10,
                "message": "Veg Day 10",
                "growspace_ids": [GROWSPACE_ID],
            }
        ]
    }

    plant = create_plant(
        plant_id="plant_1",
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
    )
    mock_coordinator.plants = {"plant_1": plant}
    mock_coordinator.get_growspace_plants.return_value = [plant]
    mock_coordinator.notifications_sent = {"plant_1": {}}

    with patch(
        "custom_components.growspace_manager.notification_manager.calculate_days_in_stage",
        return_value=10,
    ):
        await manager.async_check_timed_notifications()

    mock_hass.services.async_call.assert_awaited()
    assert mock_coordinator.notifications_sent["plant_1"]["timed_notify_1"]
    mock_coordinator.async_save.assert_awaited()


def test_generate_notification_message_truncation(manager: NotificationManager) -> None:
    """Test message truncation in generate_notification_message."""
    base_message = "Base"
    # Create reasons that will exceed the 240 char limit
    # "Base" (4) + ", " (2) + "A"*100 (100) = 106 chars.
    # 106 + 2 + 100 = 208 chars.
    # 208 + 2 + 100 = 310 chars > 240. So C should be skipped.
    reasons = [(0.9, "A" * 100), (0.8, "B" * 100), (0.7, "C" * 100)]

    message = manager.generate_notification_message(base_message, reasons)
    assert "A" * 100 in message
    assert "B" * 100 in message
    assert "C" * 100 not in message


async def test_async_send_notification_exception(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test exception handling in async_send_notification."""
    mock_hass.services.async_call.side_effect = ValueError("Service Error")

    # Should not raise exception
    await manager.async_send_notification(GROWSPACE_ID, "Title", "Message")


async def test_rewrite_with_ai_personalities(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test AI rewrite with different personalities."""
    personalities = ["Scientific", "Chill Stoner", "Strict Coach", "Pirate", "Standard"]

    for personality in personalities:
        mock_coordinator.options = {
            "ai_settings": {
                CONF_AI_ENABLED: True,
                CONF_ASSISTANT_ID: "test_agent",
                CONF_NOTIFICATION_PERSONALITY: personality,
            }
        }

        # Reset notification cooldown for each test
        manager._last_notification_sent.clear()

        with patch(
            "custom_components.growspace_manager.notification_manager.conversation.async_converse",
            new_callable=AsyncMock,
        ) as mock_converse:
            mock_result = MagicMock()
            mock_result.response.error_code = None
            mock_result.response.response_type = None
            mock_result.response.speech = {
                "plain": {"speech": f"Rewritten as {personality}"}
            }
            mock_converse.return_value = mock_result

            await manager.async_send_notification(GROWSPACE_ID, "Title", "Message")

            # Verify prompt contains personality context
            # We need to check the call args of the mock
            assert mock_converse.call_count == 1
            call_args = mock_converse.call_args
            prompt = call_args[1]["text"]

            if personality == "Scientific":
                assert "precise technical terminology" in prompt
            elif personality == "Chill Stoner":
                assert "laid-back and friendly" in prompt
            elif personality == "Strict Coach":
                assert "direct and authoritative" in prompt
            elif personality == "Pirate":
                assert "Write like a pirate" in prompt
            else:  # Standard
                assert "clear, professional, and helpful" in prompt

            # Reset for next iteration
            mock_hass.services.async_call.reset_mock()


async def test_rewrite_with_ai_sensor_formatting(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test AI rewrite with sensor data formatting."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    sensor_states = {"temp": 25, "humidity": 60, "fan": True, "light": None}

    with patch(
        "custom_components.growspace_manager.notification_manager.conversation.async_converse",
        new_callable=AsyncMock,
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.error_code = None
        mock_result.response.response_type = None
        mock_result.response.speech = {"plain": {"speech": "Rewritten"}}
        mock_converse.return_value = mock_result

        await manager.async_send_notification(
            GROWSPACE_ID, "Title", "Message", sensor_states=sensor_states
        )

        # Verify prompt contains formatted sensor data
        call_args = mock_converse.call_args
        prompt = call_args[1]["text"]
        assert "temp: 25" in prompt
        assert "humidity: 60" in prompt
        assert "fan: True" not in prompt  # bools are excluded
        assert "light: None" not in prompt  # None is excluded


async def test_rewrite_with_ai_truncation(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test AI response truncation."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
            "max_response_length": 10,
        }
    }

    with patch(
        "custom_components.growspace_manager.notification_manager.conversation.async_converse",
        new_callable=AsyncMock,
    ) as mock_converse:
        # Case 1: Truncate
        result1 = MagicMock()
        result1.response.error_code = None
        result1.response.response_type = None
        long_response = "This is a long response"  # 23 chars. 10 < 23 < 60.
        result1.response.speech = {"plain": {"speech": long_response}}

        # Case 2: Too long, use default
        result2 = MagicMock()
        result2.response.error_code = None
        result2.response.response_type = None
        very_long_response = "A" * 70  # 70 chars >= 10 + 50
        result2.response.speech = {"plain": {"speech": very_long_response}}

        mock_converse.side_effect = [result1, result2]

        # Test Case 1
        await manager.async_send_notification(GROWSPACE_ID, "Title", "Message")
        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"].endswith("...")

        # Reset cooldown for second test
        manager._last_notification_sent.clear()

        # Test Case 2
        await manager.async_send_notification(GROWSPACE_ID, "Title", "Original Message")
        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"] == "Original Message"


async def test_rewrite_with_ai_empty_response(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test AI returning empty response."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    with patch(
        "custom_components.growspace_manager.notification_manager.conversation.async_converse",
        new_callable=AsyncMock,
    ) as mock_converse:
        mock_result = MagicMock()
        mock_result.response.error_code = None
        mock_result.response.response_type = None
        mock_result.response.speech = {}  # Empty speech
        mock_converse.return_value = mock_result

        await manager.async_send_notification(GROWSPACE_ID, "Title", "Original Message")

        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"] == "Original Message"


async def test_rewrite_with_ai_exception(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test exception during AI rewrite."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    with patch(
        "custom_components.growspace_manager.notification_manager.conversation.async_converse",
        new_callable=AsyncMock,
        side_effect=Exception("AI Error"),
    ):
        await manager.async_send_notification(GROWSPACE_ID, "Title", "Original Message")

        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"] == "Original Message"


async def test_async_check_timed_notifications_empty_config(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test checking timed notifications with empty config."""
    mock_coordinator.options = {}
    await manager.async_check_timed_notifications()
    # Should just return without error


async def test_async_check_timed_notifications_missing_growspace(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test checking timed notifications for missing growspace."""
    mock_coordinator.options = {
        "timed_notifications": [
            {
                "id": "notify_1",
                "trigger_type": "veg",
                "day": 10,
                "message": "Veg Day 10",
                "growspace_ids": ["missing_gs"],
            }
        ]
    }

    await manager.async_check_timed_notifications()
    # Should continue without error


async def test_async_schedule_notification_cancel(manager: NotificationManager) -> None:
    """Test scheduling notification cancels existing timer."""
    mock_timer = MagicMock()
    manager._batch_timers[GROWSPACE_ID] = mock_timer

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later"
    ) as mock_call:
        manager.async_schedule_notification(GROWSPACE_ID)
        # Verify old timer was cancelled (called)
        mock_timer.assert_called_once()
        mock_call.assert_called_once()


async def test_async_send_batched_notification_sensor_name_fallback(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test sensor name fallback to entity_id when name attribute is missing."""
    sensor = MagicMock()
    del sensor.name
    sensor.entity_id = "sensor.no_name"
    sensor.is_on = True
    sensor.sensor_states = {}
    sensor.reasons = []

    manager.attach_sensor(GROWSPACE_ID, sensor)

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Verify it used sensor.no_name in title (single sensor path)
        args = mock_send.call_args[0]
        assert "sensor.no_name" in args[1]


async def test_async_check_tank_levels(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test checking tank levels."""

    # CASE 1: Low level triggers notification
    tank = IrrigationTank(
        sensor_entity="sensor.tank1", name="Water Tank", warning_level=30.0
    )
    gs = mock_coordinator.growspaces[GROWSPACE_ID]
    gs.environment_config = EnvironmentConfig(irrigation_tanks=[tank])

    mock_state = MagicMock()
    mock_state.state = "10.0 %"
    mock_hass.states = MagicMock()
    mock_hass.states.get.return_value = mock_state

    with patch(
        "custom_components.growspace_manager.presentation.entity_queries.EntityQueries"
    ) as mock_queries:
        mock_instance = mock_queries.return_value
        mock_instance.parse_tank_level.return_value = 10.0
        with patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send:
            await manager.async_check_tank_levels()
            mock_send.assert_awaited_once()
            # It uses keyword arguments
            assert "Low Irrigation Tank Level" in mock_send.call_args[1]["title"]

    # CASE 2: No environment config (skip)
    gs.environment_config = None
    mock_send.reset_mock()
    await manager.async_check_tank_levels()
    mock_send.assert_not_awaited()


async def test_async_send_batched_notification_multiple_sensors(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test batched notification with multiple active sensors."""
    s1 = MagicMock(entity_id="sensor.s1")
    s1.name = "Sensor 1"
    s1.is_on = True
    s1.sensor_states = {}
    s1.reasons = []

    s2 = MagicMock(entity_id="sensor.s2")
    s2.name = "Sensor 2"
    s2.is_on = True
    s2.sensor_states = {}
    s2.reasons = []

    manager.attach_sensor(GROWSPACE_ID, s1)
    manager.attach_sensor(GROWSPACE_ID, s2)

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Line 139-140 path
        args = mock_send.call_args[0]
        assert "Multiple Critical" in args[1]
        assert "Sensor 1" in args[2]
        assert "Sensor 2" in args[2]


async def test_async_send_batched_notification_specialized_title(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test batched notification with specialized title from sensor."""
    sensor = MagicMock()
    sensor.name = "S1"
    sensor.is_on = True
    sensor.sensor_states = {}
    sensor.reasons = []
    sensor.get_notification_title_message.return_value = (
        "Special Title",
        "Special Base",
    )

    manager.attach_sensor(GROWSPACE_ID, sensor)

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Line 134 path
        args = mock_send.call_args[0]
        assert args[1] == "Special Title"
        assert "Special Base" in args[2]


async def test_async_send_batched_notification_unique_reasons(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test aggregation of unique reasons in batched notification."""
    s1 = MagicMock(entity_id="sensor.s1", is_on=True)
    s1.name = "S1"
    s1.sensor_states = {}
    s1.reasons = [(0.9, "Reason 1"), (0.8, "Reason 2")]

    s2 = MagicMock(entity_id="sensor.s2", is_on=True)
    s2.name = "S2"
    s2.sensor_states = {}
    s2.reasons = [(0.7, "Reason 1")]  # Duplicate reason

    manager.attach_sensor(GROWSPACE_ID, s1)
    manager.attach_sensor(GROWSPACE_ID, s2)

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Verify Reason 1 is only included once
        msg = mock_send.call_args[0][2]
        assert msg.count("Reason 1") == 1


async def test_async_send_batched_notification_cooldown(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test critical tier cooldown in _async_send_batched_notification."""

    manager._set_cooldown(GROWSPACE_ID, NotificationTier.CRITICAL)

    # Cooldown is 30 min, so immediate call should still be active
    await manager._async_send_batched_notification(GROWSPACE_ID)
    # Should return early due to critical cooldown


async def test_async_send_batched_notification_empty_active(
    manager: NotificationManager,
) -> None:
    """Test batched notification with no active sensors (line 110)."""
    # no sensors registered
    await manager._async_send_batched_notification(GROWSPACE_ID)
    # should return early


async def test_generate_notification_message_sorting(
    manager: NotificationManager,
) -> None:
    """Test reasons sorting in generate_notification_message (lines 121-123)."""
    reasons = [(0.5, "Low"), (0.9, "High"), (0.7, "Medium")]
    message = manager.generate_notification_message("Base", reasons)
    # Should be sorted High, Medium, Low
    assert message.index("High") < message.index("Medium")
    assert message.index("Medium") < message.index("Low")


async def test_async_send_notification_disabled_cases(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test notification disabled cases (lines 44-45, 49-50)."""
    # CASE: Notifications disabled for growspace
    mock_coordinator.is_notifications_enabled.return_value = False
    await manager.async_send_notification(GROWSPACE_ID, "T", "M")
    mock_hass.services.async_call.assert_not_called()

    # CASE: No target
    mock_coordinator.is_notifications_enabled.return_value = True
    mock_coordinator.growspaces[GROWSPACE_ID].notification_target = None
    await manager.async_send_notification(GROWSPACE_ID, "T", "M")
    mock_hass.services.async_call.assert_not_called()


def test_pending_alert_creation() -> None:
    """Test PendingAlert dataclass creation and defaults."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id="gs1",
        first_triggered=now,
        last_probability=0.72,
        peak_probability=0.78,
        sensor_name="Stress Sensor",
    )
    assert alert.growspace_id == "gs1"
    assert alert.first_triggered == now
    assert alert.last_probability == 0.72
    assert alert.peak_probability == 0.78
    assert alert.sensor_name == "Stress Sensor"
    assert alert.notified is False
    assert alert.escalated is False
    assert alert.notified_as_critical is False
    assert alert.notification_timer is None


def test_pending_alert_duration() -> None:
    """Test PendingAlert duration calculation."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id="gs1",
        first_triggered=now - timedelta(minutes=25),
        last_probability=0.72,
        peak_probability=0.78,
        sensor_name="Stress Sensor",
    )
    duration = (now - alert.first_triggered).total_seconds() / 60
    assert duration == pytest.approx(25.0, abs=0.1)


def test_initialization_has_new_state(manager: NotificationManager) -> None:
    """Test initialization includes pending alerts and cooldowns."""
    assert manager._pending_alerts == {}
    assert manager._cooldowns == {}


async def test_tier_cooldown_critical(manager: NotificationManager) -> None:
    """Test that critical cooldown blocks critical but not warning."""
    now = dt_util.utcnow()
    with patch(
        "custom_components.growspace_manager.notification_manager.utcnow",
        return_value=now,
    ):
        manager._set_cooldown(GROWSPACE_ID, NotificationTier.CRITICAL)

    # Critical should be blocked
    assert manager._is_on_cooldown(
        GROWSPACE_ID, NotificationTier.CRITICAL, now + timedelta(minutes=5)
    )
    # Warning should NOT be blocked by critical cooldown
    assert not manager._is_on_cooldown(
        GROWSPACE_ID, NotificationTier.WARNING, now + timedelta(minutes=5)
    )
    # Critical should expire after 30 min
    assert not manager._is_on_cooldown(
        GROWSPACE_ID, NotificationTier.CRITICAL, now + timedelta(minutes=31)
    )


async def test_tier_cooldown_warning(manager: NotificationManager) -> None:
    """Test that warning cooldown is 2 hours."""
    now = dt_util.utcnow()
    with patch(
        "custom_components.growspace_manager.notification_manager.utcnow",
        return_value=now,
    ):
        manager._set_cooldown(GROWSPACE_ID, NotificationTier.WARNING)

    # Warning blocked at 1 hour
    assert manager._is_on_cooldown(
        GROWSPACE_ID, NotificationTier.WARNING, now + timedelta(hours=1)
    )
    # Warning expires after 2 hours
    assert not manager._is_on_cooldown(
        GROWSPACE_ID, NotificationTier.WARNING, now + timedelta(hours=2, minutes=1)
    )


# --- Task 4: update_pending_alert tests ---


async def test_update_pending_alert_creates_entry(manager: NotificationManager) -> None:
    """Test that update_pending_alert creates a new entry when sensor turns on."""
    sensor = MagicMock()
    sensor.is_on = True
    sensor.name = "Stress Sensor"
    sensor._probability = 0.75
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"

    manager.update_pending_alert(GROWSPACE_ID, sensor)

    alert_key = f"{GROWSPACE_ID}_stress"
    assert alert_key in manager._pending_alerts
    alert = manager._pending_alerts[alert_key]
    assert alert.last_probability == 0.75
    assert alert.peak_probability == 0.75
    assert alert.sensor_name == "Stress Sensor"
    assert alert.notified is False


async def test_update_pending_alert_updates_existing(
    manager: NotificationManager,
) -> None:
    """Test that update_pending_alert updates peak probability on existing entry."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=5),
        last_probability=0.72,
        peak_probability=0.72,
        sensor_name="Stress Sensor",
    )

    sensor = MagicMock()
    sensor.is_on = True
    sensor.name = "Stress Sensor"
    sensor._probability = 0.85
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"

    manager.update_pending_alert(GROWSPACE_ID, sensor)

    alert = manager._pending_alerts[alert_key]
    assert alert.last_probability == 0.85
    assert alert.peak_probability == 0.85


async def test_update_pending_alert_removes_on_off(
    manager: NotificationManager,
) -> None:
    """Test that update_pending_alert removes entry when sensor turns off."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=5),
        last_probability=0.72,
        peak_probability=0.72,
        sensor_name="Stress Sensor",
    )

    sensor = MagicMock()
    sensor.is_on = False
    sensor.name = "Stress Sensor"
    sensor._probability = 0.3
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"

    manager.update_pending_alert(GROWSPACE_ID, sensor)

    assert alert_key not in manager._pending_alerts


async def test_update_pending_alert_critical_schedules_delayed_timer(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that critical probability schedules a delayed timer, not an immediate notification."""
    sensor = MagicMock()
    sensor.is_on = True
    sensor.name = "Stress Sensor"
    sensor._probability = 0.95
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"
    sensor.reasons = [(0.95, "Extreme heat")]
    sensor.sensor_states = {"temp": 40.0}
    sensor.get_notification_title_message.return_value = None

    manager.attach_sensor(GROWSPACE_ID, sensor)

    callback_fn = None

    def capture_call_later(hass, delay, fn):
        nonlocal callback_fn
        assert delay == MIN_STRESS_DURATION_SECONDS
        callback_fn = fn
        return MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.async_call_later",
            side_effect=capture_call_later,
        ),
        patch.object(manager, "async_schedule_notification") as mock_schedule,
    ):
        manager.update_pending_alert(GROWSPACE_ID, sensor)
        # Not scheduled immediately
        mock_schedule.assert_not_called()

    alert_key = f"{GROWSPACE_ID}_stress"
    alert = manager._pending_alerts[alert_key]
    # Not yet marked as critical — timer is pending
    assert alert.notified_as_critical is False
    assert alert.notification_timer is not None

    # Simulate the timer firing
    with patch.object(manager, "async_schedule_notification") as mock_schedule:
        callback_fn(dt_util.utcnow())
        mock_schedule.assert_called_once_with(GROWSPACE_ID)

    assert alert.notified_as_critical is True
    assert alert.notification_timer is None


async def test_update_pending_alert_timer_cancelled_on_resolve(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that resolving stress before the min-duration timer cancels it without notifying."""
    sensor_on = MagicMock()
    sensor_on.is_on = True
    sensor_on.name = "Stress Sensor"
    sensor_on._probability = 0.95
    sensor_on.entity_description = MagicMock()
    sensor_on.entity_description.sensor_type = "stress"

    cancel_mock = MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        return_value=cancel_mock,
    ):
        manager.update_pending_alert(GROWSPACE_ID, sensor_on)

    alert_key = f"{GROWSPACE_ID}_stress"
    assert alert_key in manager._pending_alerts
    assert manager._pending_alerts[alert_key].notification_timer is cancel_mock

    # Now sensor turns off before 180s
    sensor_off = MagicMock()
    sensor_off.is_on = False
    sensor_off.entity_description = MagicMock()
    sensor_off.entity_description.sensor_type = "stress"

    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.update_pending_alert(GROWSPACE_ID, sensor_off)
        # Timer should be cancelled
        cancel_mock.assert_called_once()
        # No recovery because notified_as_critical was never set
        mock_recovery.assert_not_called()

    assert alert_key not in manager._pending_alerts


# --- Task 5: async_check_pending_alerts tests ---


async def test_check_pending_alerts_warning_persistence_not_met(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that warning alert is not sent before persistence period."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=10),
        last_probability=0.75,
        peak_probability=0.75,
        sensor_name="Stress Sensor",
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_not_awaited()


async def test_check_pending_alerts_warning_persistence_met(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that warning alert is sent after persistence period."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=25),
        last_probability=0.75,
        peak_probability=0.80,
        sensor_name="Stress Sensor",
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args
        assert "\u26a0\ufe0f" in call_kwargs[0][1]
        assert "25 minutes" in call_kwargs[0][2]

    assert manager._pending_alerts[alert_key].notified is True


async def test_check_pending_alerts_skip_already_notified(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that already-notified warning alerts are not resent."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=30),
        last_probability=0.75,
        peak_probability=0.80,
        sensor_name="Stress Sensor",
        notified=True,
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_not_awaited()


async def test_check_pending_alerts_escalation(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test escalation reminder for critical alerts after 30 minutes."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=35),
        last_probability=0.95,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=True,
        escalated=False,
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_awaited_once()
        title = mock_send.call_args[0][1]
        assert "Still active" in title

    assert manager._pending_alerts[alert_key].escalated is True


async def test_check_pending_alerts_no_escalation_if_dropped_to_warning(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test no escalation if probability dropped below critical."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=35),
        last_probability=0.75,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=True,
        escalated=False,
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_not_awaited()


async def test_check_pending_alerts_no_double_escalation(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test escalation only fires once."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=65),
        last_probability=0.95,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=True,
        escalated=True,
    )

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.utcnow",
            return_value=now,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager.async_check_pending_alerts()
        mock_send.assert_not_awaited()


# --- Task 6: Recovery notification tests ---


async def test_recovery_notification_on_critical_resolve(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that recovery notification is sent when a critical alert resolves."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=45),
        last_probability=0.92,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=True,
    )

    sensor = MagicMock()
    sensor.is_on = False
    sensor.name = "Stress Sensor"
    sensor._probability = 0.3
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"

    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.update_pending_alert(GROWSPACE_ID, sensor)
        mock_recovery.assert_called_once()

    assert alert_key not in manager._pending_alerts


async def test_no_recovery_for_warning_resolve(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that no recovery notification for warning-only alerts."""
    now = dt_util.utcnow()
    alert_key = f"{GROWSPACE_ID}_stress"
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=25),
        last_probability=0.75,
        peak_probability=0.80,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=False,
    )

    sensor = MagicMock()
    sensor.is_on = False
    sensor.name = "Stress Sensor"
    sensor._probability = 0.3
    sensor.entity_description = MagicMock()
    sensor.entity_description.sensor_type = "stress"

    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.update_pending_alert(GROWSPACE_ID, sensor)
        mock_recovery.assert_not_called()


async def test_tank_level_uses_critical_tier(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test that tank level alerts use critical tier."""
    tank = IrrigationTank(
        sensor_entity="sensor.tank1", name="Water Tank", warning_level=30.0
    )
    gs = mock_coordinator.growspaces[GROWSPACE_ID]
    gs.environment_config = EnvironmentConfig(irrigation_tanks=[tank])

    mock_state = MagicMock()
    mock_state.state = "10.0 %"
    mock_hass.states = MagicMock()
    mock_hass.states.get.return_value = mock_state

    with (
        patch(
            "custom_components.growspace_manager.presentation.entity_queries.EntityQueries"
        ) as mock_queries,
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        mock_instance = mock_queries.return_value
        mock_instance.parse_tank_level.return_value = 10.0
        await manager.async_check_tank_levels()
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs.get("tier") == "critical"


async def test_send_recovery_notification(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test the actual recovery notification send."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=45),
        last_probability=0.3,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified=True,
        notified_as_critical=True,
    )

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_recovery(GROWSPACE_ID, alert)
        mock_send.assert_awaited_once()
        title = mock_send.call_args[0][1]
        message = mock_send.call_args[0][2]
        assert "\u2705" in title
        assert "resolved" in message.lower()
        assert "45 minutes" in message


async def test_schedule_recovery(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test scheduling recovery notification."""
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=dt_util.utcnow(),
        last_probability=0.9,
        peak_probability=0.95,
        sensor_name="Test Sensor",
    )

    with patch.object(manager, "_async_send_recovery", new_callable=AsyncMock):
        manager._schedule_recovery(GROWSPACE_ID, alert)
        mock_hass.async_create_task.assert_called_once()
        # Verify call arguments if needed
        # args = mock_hass.async_create_task.call_args[0]
        # assert args[0] == mock_send_recovery.return_value


async def test_async_send_recovery_cooldown(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test recovery notification cooldown."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(minutes=10),
        last_probability=0.9,
        peak_probability=0.95,
        sensor_name="Test Sensor",
    )

    # Set recovery cooldown
    manager._set_cooldown(GROWSPACE_ID, "recovery")

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_recovery(GROWSPACE_ID, alert)
        mock_send.assert_not_awaited()


async def test_async_send_recovery_suppressed_below_min_duration(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that recovery is suppressed when stress lasted less than min duration."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now - timedelta(seconds=30),
        last_probability=0.3,
        peak_probability=0.95,
        sensor_name="Stress Sensor",
        notified_as_critical=True,
    )

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_recovery(GROWSPACE_ID, alert)
        mock_send.assert_not_awaited()


def test_detach_sensor(manager: NotificationManager) -> None:
    """Test detaching a sensor."""
    sensor = MagicMock()
    manager.attach_sensor(GROWSPACE_ID, sensor)
    assert sensor in manager._registered_sensors[GROWSPACE_ID]

    manager.detach_sensor(GROWSPACE_ID, sensor)
    assert sensor not in manager._registered_sensors[GROWSPACE_ID]


def test_trigger_cooldown(manager: NotificationManager) -> None:
    """Test manually triggering cooldown."""
    now = dt_util.utcnow()
    with patch(
        "custom_components.growspace_manager.notification_manager.utcnow",
        return_value=now,
    ):
        manager.trigger_cooldown(GROWSPACE_ID)

    assert manager._is_on_cooldown(GROWSPACE_ID, NotificationTier.CRITICAL, now)
    assert manager._is_on_cooldown(GROWSPACE_ID, NotificationTier.WARNING, now)
    assert manager._last_notification_sent[GROWSPACE_ID] == now


async def test_async_schedule_notification_execution(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that scheduled notification callback executes."""
    # We need to simulate the callback execution
    callback_func = None

    def mock_call_later(hass, delay, action):
        nonlocal callback_func
        callback_func = action
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        side_effect=mock_call_later,
    ):
        manager.async_schedule_notification(GROWSPACE_ID)

    assert callback_func is not None

    with patch.object(
        manager, "_async_send_batched_notification", new_callable=AsyncMock
    ):
        # Execute the callback
        callback_func(dt_util.utcnow())
        mock_hass.async_create_task.assert_called_once()


async def test_async_send_notification_tier_cooldown_debug(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test debug logging when tier cooldown is active."""
    manager._set_cooldown(GROWSPACE_ID, NotificationTier.CRITICAL)

    with patch(
        "custom_components.growspace_manager.notification_manager._LOGGER.debug"
    ) as mock_debug:
        await manager.async_send_notification(
            GROWSPACE_ID, "Title", "Message", tier=NotificationTier.CRITICAL
        )
        mock_debug.assert_called_with(
            "Tier %s cooldown active for %s, skipping notification",
            NotificationTier.CRITICAL,
            GROWSPACE_ID,
        )


async def test_async_send_notification_with_tier_sets_cooldown(
    manager: NotificationManager, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test sending notification with tier sets the cooldown."""
    with patch.object(manager, "_set_cooldown") as mock_set_cooldown:
        await manager.async_send_notification(
            GROWSPACE_ID, "Title", "Message", tier=NotificationTier.WARNING
        )
        mock_set_cooldown.assert_called_with(GROWSPACE_ID, NotificationTier.WARNING)


async def test_check_and_trigger_plant_notification_init(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test initialization of notifications_sent dict for new plant."""
    plant = MagicMock()
    plant.plant_id = "new_plant"
    growspace = MagicMock()
    growspace.id = GROWSPACE_ID
    growspace.name = GROWSPACE_NAME

    # Ensure plant not in notifications_sent
    mock_coordinator.notifications_sent = {}

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.calculate_days_in_stage",
            return_value=10,
        ),
        patch.object(manager, "async_send_notification", new_callable=AsyncMock),
    ):
        await manager._check_and_trigger_plant_notification(
            plant, growspace, "notify_1", "veg", 10, "Message"
        )

    assert "new_plant" in mock_coordinator.notifications_sent
    assert mock_coordinator.notifications_sent["new_plant"]["timed_notify_1"] is True

    # Test fallback to growspace.growspace_id if id not present
    del growspace.id
    growspace.growspace_id = GROWSPACE_ID + "_alt"

    mock_coordinator.notifications_sent = {}  # Reset

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.calculate_days_in_stage",
            return_value=10,
        ),
        patch.object(
            manager, "async_send_notification", new_callable=AsyncMock
        ) as mock_send,
    ):
        await manager._check_and_trigger_plant_notification(
            plant, growspace, "notify_1", "veg", 10, "Message"
        )
        mock_send.assert_awaited()
        assert mock_send.call_args[0][0] == GROWSPACE_ID + "_alt"
