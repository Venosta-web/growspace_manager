"""Tests for the NotificationManager."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    MIN_STRESS_DURATION_SECONDS,
    NOTIFICATION_CHANNEL,
    NOTIFICATION_GROUP,
    NOTIFICATION_ICON,
    NotificationTier,
)
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.notification_manager import (
    NotificationManager,
    PendingAlert,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)
from custom_components.growspace_manager.services.facade import ServiceFacade
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .common import create_plant

GROWSPACE_ID = "test_growspace"
GROWSPACE_NAME = "Test Growspace"
NOTIFICATION_TARGET = "notify.mobile_app_test"


def make_snapshot(
    sensor_type: str = "stress",
    *,
    is_on: bool = True,
    probability: float = 0.75,
    sensor_name: str = "Stress Sensor",
    reasons: list[tuple[float, str]] | None = None,
    sensor_states: dict | None = None,
    notification_title: str | None = None,
    notification_message: str | None = None,
    growspace_id: str = GROWSPACE_ID,
) -> EvaluationSnapshot:
    """Build an EvaluationSnapshot for notification-manager tests."""
    return EvaluationSnapshot(
        growspace_id=growspace_id,
        sensor_type=sensor_type,
        sensor_name=sensor_name,
        probability=probability,
        threshold=0.7,
        is_on=is_on,
        reasons=reasons if reasons is not None else [],
        sensor_states=sensor_states if sensor_states is not None else {},
        lights_on=None,
        notification_title=notification_title,
        notification_message=notification_message,
    )


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
    coordinator.async_commit = AsyncMock()

    # Initialize query methods
    coordinator.get_growspace_plants = MagicMock(
        name="get_growspace_plants",
        side_effect=lambda gid: [
            p for p in coordinator.plants.values() if p.growspace_id == gid
        ],
    )
    coordinator.get_plant = MagicMock(
        name="get_plant", side_effect=lambda pid: coordinator.plants.get(pid)
    )
    coordinator.get_growspace = MagicMock(
        name="get_growspace", side_effect=lambda gid: coordinator.growspaces.get(gid)
    )

    # Initialize ServiceFacade and wrap it in a MagicMock
    facade = ServiceFacade(coordinator)
    coordinator.services = MagicMock(wraps=facade)

    # Add config_entry with background task support
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.async_create_background_task = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.data = {}
    hass.config = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def mock_ai_rewriter() -> MagicMock:
    """Mock AINotificationRewriter that returns messages unchanged by default."""
    rewriter = MagicMock()
    rewriter.async_rewrite = AsyncMock(side_effect=lambda msg, *_a, **_kw: msg)
    return rewriter


@pytest.fixture
def manager(
    mock_hass: MagicMock, mock_coordinator: MagicMock, mock_ai_rewriter: MagicMock
) -> NotificationManager:
    """Fixture for NotificationManager."""
    return NotificationManager(mock_hass, mock_coordinator, mock_ai_rewriter)


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
    mock_coordinator.services.notifications.is_notifications_enabled.return_value = (
        False
    )

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_ai_rewrite(
    manager: NotificationManager,
    mock_coordinator: MagicMock,
    mock_hass: MagicMock,
    mock_ai_rewriter: MagicMock,
) -> None:
    """Test that NotificationManager uses the rewritten message from AINotificationRewriter."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }
    mock_ai_rewriter.async_rewrite.side_effect = None
    mock_ai_rewriter.async_rewrite.return_value = "Ahoy! Test Message Rewrite"

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

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
    mock_coordinator.notification_state.sent = {"plant_1": {}}

    with patch(
        "custom_components.growspace_manager.notification_manager.current_stage_age_in",
        return_value=10,
    ):
        await manager.async_check_timed_notifications()

    mock_hass.services.async_call.assert_awaited()
    assert mock_coordinator.notification_state.sent["plant_1"]["timed_notify_1"]
    mock_coordinator.async_commit.assert_awaited()


async def test_async_check_timed_notifications_normalizes_legacy_trigger(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test a legacy stored trigger fires against its normalized stage."""
    mock_coordinator.options = {
        "timed_notifications": [
            {
                "id": "legacy_notify",
                "trigger_type": "days_since_flip",
                "day": 10,
                "message": "Flower Day 10",
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
    mock_coordinator.notification_state.sent = {"plant_1": {}}

    with patch(
        "custom_components.growspace_manager.notification_manager.current_stage_age_in",
        return_value=10,
    ) as stage_age:
        await manager.async_check_timed_notifications()

    stage_age.assert_called_once_with(plant, "flower")
    mock_hass.services.async_call.assert_awaited()
    assert mock_coordinator.notification_state.sent["plant_1"]["timed_legacy_notify"]


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
    """Test that the snapshot's sensor name appears in the single-sensor title."""
    manager._latest_snapshots[(GROWSPACE_ID, "stress")] = make_snapshot(
        sensor_name="sensor.no_name"
    )

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Verify it used sensor.no_name in title (single sensor path)
        args = mock_send.call_args[0]
        assert "sensor.no_name" in args[1]


async def test_async_send_batched_notification_multiple_sensors(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test batched notification with multiple active sensors."""
    manager._latest_snapshots[(GROWSPACE_ID, "stress")] = make_snapshot(
        "stress", sensor_name="Sensor 1"
    )
    manager._latest_snapshots[(GROWSPACE_ID, "mold")] = make_snapshot(
        "mold", sensor_name="Sensor 2"
    )

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Multiple-sensor path
        args = mock_send.call_args[0]
        assert "Multiple Critical" in args[1]
        assert "Sensor 1" in args[2]
        assert "Sensor 2" in args[2]


async def test_async_send_batched_notification_specialized_title(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test batched notification with the snapshot's precomputed title/message."""
    manager._latest_snapshots[(GROWSPACE_ID, "stress")] = make_snapshot(
        notification_title="Special Title",
        notification_message="Special Base",
    )

    with patch.object(
        manager, "async_send_notification", new_callable=AsyncMock
    ) as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        # Single-sensor path uses the snapshot's precomputed title/message
        args = mock_send.call_args[0]
        assert args[1] == "Special Title"
        assert "Special Base" in args[2]


async def test_async_send_batched_notification_unique_reasons(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test aggregation of unique reasons in batched notification."""
    manager._latest_snapshots[(GROWSPACE_ID, "stress")] = make_snapshot(
        "stress", sensor_name="S1", reasons=[(0.9, "Reason 1"), (0.8, "Reason 2")]
    )
    manager._latest_snapshots[(GROWSPACE_ID, "mold")] = make_snapshot(
        "mold",
        sensor_name="S2",
        reasons=[(0.7, "Reason 1")],  # Duplicate reason
    )

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
    mock_coordinator.services.notifications.is_notifications_enabled.return_value = (
        False
    )
    await manager.async_send_notification(GROWSPACE_ID, "T", "M")
    mock_hass.services.async_call.assert_not_called()

    # CASE: No target
    mock_coordinator.services.notifications.is_notifications_enabled.return_value = True
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
    """Test that report_evaluation creates a new entry when sensor turns on."""
    manager.report_evaluation(make_snapshot(probability=0.75))

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

    manager.report_evaluation(make_snapshot(probability=0.85))

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

    manager.report_evaluation(make_snapshot(is_on=False, probability=0.3))

    assert alert_key not in manager._pending_alerts


async def test_update_pending_alert_critical_schedules_delayed_timer(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that critical probability schedules a delayed timer, not an immediate notification."""
    snapshot = make_snapshot(
        probability=0.95,
        reasons=[(0.95, "Extreme heat")],
        sensor_states={"temp": 40.0},
    )

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
        manager.report_evaluation(snapshot)
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
    cancel_mock = MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        return_value=cancel_mock,
    ):
        manager.report_evaluation(make_snapshot(probability=0.95))

    alert_key = f"{GROWSPACE_ID}_stress"
    assert alert_key in manager._pending_alerts
    assert manager._pending_alerts[alert_key].notification_timer is cancel_mock

    # Now sensor turns off before 180s
    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.report_evaluation(make_snapshot(is_on=False))
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

    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.report_evaluation(make_snapshot(is_on=False, probability=0.3))
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

    with patch.object(manager, "_schedule_recovery") as mock_recovery:
        manager.report_evaluation(make_snapshot(is_on=False, probability=0.3))
        mock_recovery.assert_not_called()


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
        manager.coordinator.config_entry.async_create_background_task.assert_called_once()
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


async def test_timer_not_rescheduled_while_active(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that a second critical update does not schedule a second timer."""
    cancel_mock = MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        return_value=cancel_mock,
    ) as mock_later:
        manager.report_evaluation(make_snapshot(probability=0.95))
        # Second update at same probability
        manager.report_evaluation(make_snapshot(probability=0.95))
        # Timer should only be scheduled once
        assert mock_later.call_count == 1


async def test_timer_cancelled_when_probability_drops_below_threshold(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test that the pending timer is cancelled if probability drops below critical."""
    cancel_mock = MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        return_value=cancel_mock,
    ):
        manager.report_evaluation(make_snapshot(probability=0.95))

    alert_key = f"{GROWSPACE_ID}_stress"
    assert manager._pending_alerts[alert_key].notification_timer is cancel_mock

    # Probability drops below threshold — timer should be cancelled
    manager.report_evaluation(make_snapshot(probability=0.70))
    cancel_mock.assert_called_once()
    assert manager._pending_alerts[alert_key].notification_timer is None


def test_report_evaluation_clears_snapshot_on_resolve(
    manager: NotificationManager,
) -> None:
    """A resolved snapshot is removed from the latest-snapshot store."""
    manager.report_evaluation(make_snapshot("optimal", is_on=True))
    assert (GROWSPACE_ID, "optimal") in manager._latest_snapshots

    manager.report_evaluation(make_snapshot("optimal", is_on=False))
    assert (GROWSPACE_ID, "optimal") not in manager._latest_snapshots


def test_optimal_high_probability_creates_no_pending_alert(
    manager: NotificationManager,
) -> None:
    """A triggered optimal snapshot is stored but never creates a pending alert."""
    manager.report_evaluation(make_snapshot("optimal", is_on=True, probability=0.99))

    assert (GROWSPACE_ID, "optimal") in manager._latest_snapshots
    assert manager._pending_alerts == {}


# --- Step 4: light-flip cooldown migration ---


def _snapshot_with_lights(
    sensor_type: str, lights_on: bool | None
) -> EvaluationSnapshot:
    """Build a resolved snapshot carrying the given light state."""
    return EvaluationSnapshot(
        growspace_id=GROWSPACE_ID,
        sensor_type=sensor_type,
        sensor_name=sensor_type,
        probability=0.0,
        threshold=0.7,
        is_on=False,
        reasons=[],
        sensor_states={},
        lights_on=lights_on,
        notification_title=None,
        notification_message=None,
    )


def test_light_flip_on_off_on_triggers_two_cooldowns(
    manager: NotificationManager,
) -> None:
    """An on->off->on light sequence triggers the cooldown exactly twice."""
    with patch.object(manager, "trigger_cooldown") as mock_cooldown:
        manager.report_evaluation(_snapshot_with_lights("stress", True))
        manager.report_evaluation(_snapshot_with_lights("stress", False))
        manager.report_evaluation(_snapshot_with_lights("stress", True))

    assert mock_cooldown.call_count == 2
    mock_cooldown.assert_called_with(GROWSPACE_ID)


def test_light_flip_deduped_across_sensor_types(
    manager: NotificationManager,
) -> None:
    """Three same-wave snapshots (one physical flip) trigger one cooldown."""
    # Establish the prior state (lights on) without a flip.
    manager.report_evaluation(_snapshot_with_lights("stress", True))

    with patch.object(manager, "trigger_cooldown") as mock_cooldown:
        # All three sensor types observe the same off-transition.
        manager.report_evaluation(_snapshot_with_lights("stress", False))
        manager.report_evaluation(_snapshot_with_lights("mold", False))
        manager.report_evaluation(_snapshot_with_lights("optimal", False))

    mock_cooldown.assert_called_once_with(GROWSPACE_ID)


def test_light_flip_none_reading_ignored(manager: NotificationManager) -> None:
    """A None light reading neither triggers a cooldown nor clears prior state."""
    manager.report_evaluation(_snapshot_with_lights("stress", True))

    with patch.object(manager, "trigger_cooldown") as mock_cooldown:
        manager.report_evaluation(_snapshot_with_lights("stress", None))
        # Still considered "on"; a subsequent off then triggers exactly one.
        manager.report_evaluation(_snapshot_with_lights("stress", False))

    mock_cooldown.assert_called_once_with(GROWSPACE_ID)


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
        manager.coordinator.config_entry.async_create_background_task.assert_called_once()


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
    mock_coordinator.notification_state.sent = {}

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.current_stage_age_in",
            return_value=10,
        ),
        patch.object(manager, "async_send_notification", new_callable=AsyncMock),
    ):
        await manager._check_and_trigger_plant_notification(
            plant, growspace, "notify_1", "veg", 10, "Message"
        )

    assert "new_plant" in mock_coordinator.notification_state.sent
    assert (
        mock_coordinator.notification_state.sent["new_plant"]["timed_notify_1"] is True
    )

    # Test fallback to growspace.growspace_id if id not present
    del growspace.id
    growspace.growspace_id = GROWSPACE_ID + "_alt"

    mock_coordinator.notification_state.sent = {}  # Reset

    with (
        patch(
            "custom_components.growspace_manager.notification_manager.current_stage_age_in",
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


# --- Missing coverage tests ---


def test_shutdown_cancels_batch_timers_and_pending_alerts(
    manager: NotificationManager,
) -> None:
    """Test shutdown cancels batch timers and pending alert timers (lines 79-87)."""
    batch_timer = MagicMock()
    manager._batch_timers[GROWSPACE_ID] = batch_timer

    alert_timer = MagicMock()
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now,
        last_probability=0.9,
        peak_probability=0.9,
        sensor_name="Sensor",
        notification_timer=alert_timer,
    )
    manager._pending_alerts[f"{GROWSPACE_ID}_stress"] = alert

    manager.shutdown()

    batch_timer.assert_called_once()
    assert manager._batch_timers == {}
    alert_timer.assert_called_once()
    assert alert.notification_timer is None
    assert manager._pending_alerts == {}


def test_shutdown_with_alert_timer_none(manager: NotificationManager) -> None:
    """Test shutdown handles pending alerts without a timer (lines 83-87)."""
    now = dt_util.utcnow()
    alert = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now,
        last_probability=0.9,
        peak_probability=0.9,
        sensor_name="Sensor",
        notification_timer=None,
    )
    manager._pending_alerts[f"{GROWSPACE_ID}_stress"] = alert

    manager.shutdown()

    assert manager._pending_alerts == {}


def test_update_pending_alert_no_plants_cancels_timer(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test update_pending_alert early-exits when growspace has no plants (lines 121-127)."""
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = []

    cancel_mock = MagicMock()
    alert_key = f"{GROWSPACE_ID}_stress"
    now = dt_util.utcnow()
    manager._pending_alerts[alert_key] = PendingAlert(
        growspace_id=GROWSPACE_ID,
        first_triggered=now,
        last_probability=0.8,
        peak_probability=0.8,
        sensor_name="Stress Sensor",
        notification_timer=cancel_mock,
    )

    manager.report_evaluation(make_snapshot(probability=0.8))

    cancel_mock.assert_called_once()
    assert alert_key not in manager._pending_alerts


def test_update_pending_alert_no_plants_no_existing_alert(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test update_pending_alert when no plants and no pending alert (line 121)."""
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = []

    # Should not raise
    manager.report_evaluation(make_snapshot(probability=0.5))
    assert f"{GROWSPACE_ID}_stress" not in manager._pending_alerts


async def test_fire_critical_timer_alert_removed_before_firing(
    manager: NotificationManager, mock_hass: MagicMock
) -> None:
    """Test _fire_critical returns early if alert is removed before timer fires (line 168)."""
    callback_fn = None

    def capture_call_later(hass, delay, fn):
        nonlocal callback_fn
        callback_fn = fn
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.notification_manager.async_call_later",
        side_effect=capture_call_later,
    ):
        manager.report_evaluation(make_snapshot(probability=0.95))

    # Remove the alert before the timer fires
    manager._pending_alerts.clear()

    with patch.object(manager, "async_schedule_notification") as mock_schedule:
        callback_fn(dt_util.utcnow())
        mock_schedule.assert_not_called()


async def test_async_send_batched_notification_pops_existing_timer(
    manager: NotificationManager, mock_coordinator: MagicMock
) -> None:
    """Test _async_send_batched_notification cancels lingering batch timer (line 264)."""
    batch_timer = MagicMock()
    manager._batch_timers[GROWSPACE_ID] = batch_timer

    # No active sensors so it returns early after popping the timer
    await manager._async_send_batched_notification(GROWSPACE_ID)

    batch_timer.assert_called_once()
    assert GROWSPACE_ID not in manager._batch_timers


async def test_async_send_notification_no_plants_skips(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test notification is skipped when growspace has no plants (lines 367-371)."""
    mock_coordinator.services.growspaces.get_growspace_plants.return_value = []
    mock_coordinator.services.notifications.is_notifications_enabled.return_value = True

    await manager.async_send_notification(GROWSPACE_ID, "Title", "Message")

    mock_hass.services.async_call.assert_not_awaited()
