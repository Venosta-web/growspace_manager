"""Tests for new NotificationsFacade methods (get_alerts and resolve_alert)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.services.notifications_facade import (
    NotificationsFacade,
)


def _make_coordinator() -> MagicMock:
    coordinator = MagicMock()
    coordinator.alert_monitor = MagicMock()
    coordinator.alert_monitor.get_alerts = MagicMock(return_value=[])
    coordinator.alert_monitor.resolve_alert = AsyncMock(return_value=True)
    coordinator._notification_manager = MagicMock()
    coordinator.notification_settings = MagicMock()
    coordinator.notification_state = MagicMock()
    coordinator.config_entry = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.async_commit = AsyncMock()
    return coordinator


# ---------------------------------------------------------------------------
# get_alerts
# ---------------------------------------------------------------------------


def test_get_alerts_delegates_to_alert_monitor() -> None:
    """get_alerts without filters delegates to alert_monitor.get_alerts."""
    alerts = [{"alert_id": "a1", "alert_type": "stress"}]
    coordinator = _make_coordinator()
    coordinator.alert_monitor.get_alerts.return_value = alerts
    facade = NotificationsFacade(coordinator)

    result = facade.get_alerts()

    assert result is alerts
    coordinator.alert_monitor.get_alerts.assert_called_once_with()


def test_get_alerts_passes_growspace_id_filter() -> None:
    """get_alerts passes growspace_id kwarg to alert_monitor."""
    coordinator = _make_coordinator()
    facade = NotificationsFacade(coordinator)

    facade.get_alerts(growspace_id="tent1")

    coordinator.alert_monitor.get_alerts.assert_called_once_with(growspace_id="tent1")


def test_get_alerts_passes_alert_type_filter() -> None:
    """get_alerts passes alert_type kwarg to alert_monitor."""
    coordinator = _make_coordinator()
    facade = NotificationsFacade(coordinator)

    facade.get_alerts(alert_type="mold")

    coordinator.alert_monitor.get_alerts.assert_called_once_with(alert_type="mold")


def test_latest_evaluation_delegates_to_notification_manager() -> None:
    """Vision reads the manager's latest active or inactive evaluation."""
    coordinator = _make_coordinator()
    snapshot = object()
    coordinator._notification_manager.latest_evaluation.return_value = snapshot
    facade = NotificationsFacade(coordinator)

    result = facade.latest_evaluation("tent1", "stress")

    assert result is snapshot
    coordinator._notification_manager.latest_evaluation.assert_called_once_with(
        "tent1", "stress"
    )


# ---------------------------------------------------------------------------
# resolve_alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_alert_delegates_and_returns_result() -> None:
    """resolve_alert delegates to alert_monitor and returns its result."""
    coordinator = _make_coordinator()
    coordinator.alert_monitor.resolve_alert.return_value = True
    facade = NotificationsFacade(coordinator)

    result = await facade.resolve_alert("alert-1", notes="resolved manually")

    assert result is True
    coordinator.alert_monitor.resolve_alert.assert_awaited_once_with(
        "alert-1", notes="resolved manually"
    )


@pytest.mark.asyncio
async def test_resolve_alert_without_notes() -> None:
    """resolve_alert can be called without notes."""
    coordinator = _make_coordinator()
    coordinator.alert_monitor.resolve_alert.return_value = False
    facade = NotificationsFacade(coordinator)

    result = await facade.resolve_alert("alert-99")

    assert result is False
    coordinator.alert_monitor.resolve_alert.assert_awaited_once_with(
        "alert-99", notes=None
    )
