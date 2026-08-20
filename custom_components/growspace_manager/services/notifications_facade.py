"""Notifications sub-facade for the Growspace Manager integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.notification_manager import (
        NotificationManager,
    )
    from custom_components.growspace_manager.notifications.evaluation_snapshot import (
        EvaluationSnapshot,
    )

_LOGGER = logging.getLogger(__name__)


class NotificationsFacade:
    """Facade for all notification-related operations."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialise the facade with the coordinator."""
        self._coordinator = coordinator

    @property
    def manager(self) -> NotificationManager:
        """Expose the raw NotificationManager for callers that need direct access."""
        return self._coordinator._notification_manager

    async def _update_options(self, options: dict[str, Any]) -> None:
        if hasattr(self._coordinator, "options"):
            self._coordinator.options.update(options)
        new_options = self._coordinator.config_entry.options.copy()
        new_options.update(options)
        self._coordinator.hass.config_entries.async_update_entry(
            self._coordinator.config_entry, options=new_options
        )
        await self._coordinator.async_commit()

    async def set_notifications_enabled(self, growspace_id: str, enabled: bool) -> None:
        """Enable or disable notifications for a growspace."""
        if growspace_id not in self._coordinator.growspaces:
            self._coordinator.notification_settings.set_notifications_state(
                growspace_id, enabled
            )
            return
        self._coordinator.notification_settings.set_notifications_state(
            growspace_id, enabled
        )
        await self._coordinator.async_commit()

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are enabled for a growspace."""
        return self._coordinator.notification_settings.is_notifications_enabled(
            growspace_id
        )

    def report_evaluation(self, snapshot: EvaluationSnapshot) -> None:
        """Report a Bayesian sensor evaluation to notification consumers."""
        self.manager.report_evaluation(snapshot)
        self._coordinator.alert_monitor.report_evaluation(snapshot)

    def get_timed_notifications(self) -> list[dict[str, Any]]:
        """Return the list of configured timed notifications."""
        return self._coordinator.notification_settings.get_timed_notifications()

    async def add_timed_notification(
        self,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Add a new timed notification."""
        notifications = self.get_timed_notifications().copy()
        new_notification = (
            self._coordinator.notification_settings.create_timed_notification(
                message, trigger_type, day, growspace_ids
            )
        )
        notifications.append(new_notification)
        await self._update_options({"timed_notifications": notifications})

    async def update_timed_notification(
        self,
        notification_id: str,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Update an existing timed notification."""
        notifications = self.get_timed_notifications().copy()
        if self._coordinator.notification_settings.update_timed_notification_in_list(
            notifications, notification_id, message, trigger_type, day, growspace_ids
        ):
            await self._update_options({"timed_notifications": notifications})

    async def remove_timed_notification(self, notification_id: str) -> None:
        """Remove a timed notification."""
        notifications = (
            self._coordinator.notification_settings.remove_timed_notification_from_list(
                self.get_timed_notifications(), notification_id
            )
        )
        await self._update_options({"timed_notifications": notifications})

    async def async_add_timed_notification(
        self,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Alias for add_timed_notification."""
        await self.add_timed_notification(message, trigger_type, day, growspace_ids)

    async def async_update_timed_notification(
        self,
        notification_id: str,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> None:
        """Alias for update_timed_notification."""
        await self.update_timed_notification(
            notification_id, message, trigger_type, day, growspace_ids
        )

    async def async_remove_timed_notification(self, notification_id: str) -> None:
        """Alias for remove_timed_notification."""
        await self.remove_timed_notification(notification_id)

    def should_send_notification(self, plant_id: str, stage: str, days: int) -> bool:
        """Return True if the notification has not been sent yet."""
        return not self._coordinator.notification_state.is_sent(plant_id, stage, days)

    async def mark_notification_sent(
        self, plant_id: str, stage: str, days: int
    ) -> None:
        """Mark a notification as sent to prevent duplicates."""
        self._coordinator.notification_state.mark_sent(plant_id, stage, days)
        await self._coordinator.async_commit()

    # -------------------------------------------------------------------------
    # Alert monitor operations
    # -------------------------------------------------------------------------

    def get_alerts(
        self,
        growspace_id: str | None = None,
        alert_type: str | None = None,
    ) -> list[dict]:
        """Return alerts from the alert monitor, optionally filtered."""
        kwargs: dict = {}
        if growspace_id is not None:
            kwargs["growspace_id"] = growspace_id
        if alert_type is not None:
            kwargs["alert_type"] = alert_type
        return self._coordinator.alert_monitor.get_alerts(**kwargs)

    async def resolve_alert(self, alert_id: str, notes: str | None = None) -> bool:
        """Mark an alert as resolved."""
        return await self._coordinator.alert_monitor.resolve_alert(
            alert_id, notes=notes
        )
