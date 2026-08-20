"""Tests for notification batching logic in Growspace Manager."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.notification_manager import NotificationManager
from custom_components.growspace_manager.notification_rewriter import (
    AINotificationRewriter,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_gs_1"


def make_snapshot(
    sensor_type: str = "stress",
    *,
    sensor_name: str = "Test Sensor",
    is_on: bool = True,
    reasons: list[tuple[float, str]] | None = None,
    sensor_states: dict | None = None,
    probability: float = 0.95,
    notification_title: str | None = None,
    notification_message: str | None = None,
) -> EvaluationSnapshot:
    """Build an EvaluationSnapshot for batching tests."""
    return EvaluationSnapshot(
        growspace_id=GROWSPACE_ID,
        sensor_type=sensor_type,
        sensor_name=sensor_name,
        probability=probability,
        threshold=0.8,
        is_on=is_on,
        reasons=reasons if reasons is not None else [(0.9, "Reason A"), (0.8, "Reason B")],
        sensor_states=sensor_states if sensor_states is not None else {"temp": 25.0},
        lights_on=None,
        notification_title=notification_title,
        notification_message=notification_message,
    )


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
    mgr = NotificationManager(hass, mock_coordinator, AINotificationRewriter(hass))
    yield mgr
    mgr.shutdown()


def _store(manager: NotificationManager, snapshot: EvaluationSnapshot) -> None:
    """Place a snapshot directly into the latest-snapshot store for batching."""
    manager._latest_snapshots[(snapshot.growspace_id, snapshot.sensor_type)] = snapshot


async def test_snapshot_stored_and_cleared(manager) -> None:
    """A triggered snapshot is stored; a resolved one is removed."""
    manager.report_evaluation(make_snapshot("optimal", is_on=True))
    assert (GROWSPACE_ID, "optimal") in manager._latest_snapshots

    manager.report_evaluation(make_snapshot("optimal", is_on=False))
    assert (GROWSPACE_ID, "optimal") not in manager._latest_snapshots


async def test_batching_trigger(manager, hass: HomeAssistant) -> None:
    """Test that a batched notification reflects the stored snapshot."""
    _store(manager, make_snapshot())

    with patch.object(manager, "async_send_notification") as mock_send:
        manager.async_schedule_notification(GROWSPACE_ID)
        await manager._async_send_batched_notification(GROWSPACE_ID)

        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        assert args[0] == GROWSPACE_ID
        assert "Test Sensor" in args[1]
        assert "Reason A" in args[2]


async def test_multiple_sensors_aggregation(manager, hass: HomeAssistant) -> None:
    """Test aggregation across multiple sensors."""
    _store(
        manager,
        make_snapshot(
            "stress", sensor_name="Sensor 1", reasons=[(0.9, "Hot")], sensor_states={"temp": 30}
        ),
    )
    _store(
        manager,
        make_snapshot(
            "mold", sensor_name="Sensor 2", reasons=[(0.8, "Dry")], sensor_states={"hum": 20}
        ),
    )

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_awaited_once()
        args, _ = mock_send.call_args
        _, title, msg = args[0], args[1], args[2]
        s_states = mock_send.call_args[1].get("sensor_states")

        assert "Multiple Critical" in title
        assert "Hot" in msg
        assert "Dry" in msg
        assert s_states["temp"] == 30
        assert s_states["hum"] == 20


async def test_cooldown_respected_globally(manager) -> None:
    """Test that critical cooldown prevents batching."""
    from custom_components.growspace_manager.const import NotificationTier

    manager._set_cooldown(GROWSPACE_ID, NotificationTier.CRITICAL)

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_not_awaited()


async def test_empty_active_sensors(manager) -> None:
    """Test that no notification is sent when no snapshot is triggered."""
    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_not_awaited()


async def test_batched_critical_title_format(manager, hass: HomeAssistant) -> None:
    """Test that critical batched notifications use red circle title format."""
    _store(
        manager,
        make_snapshot(
            "stress",
            sensor_name="Stress Sensor",
            reasons=[(0.95, "Extreme heat")],
            sensor_states={"temp": 40.0},
        ),
    )

    with patch.object(manager, "async_send_notification") as mock_send:
        await manager._async_send_batched_notification(GROWSPACE_ID)
        mock_send.assert_awaited_once()
        title = mock_send.call_args[0][1]
        assert "\U0001f534" in title
