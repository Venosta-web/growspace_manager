"""Notification manager for Growspace Manager.

Handles notification switches and timed notification management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
import uuid

from .timed import normalize_timed_notification_trigger, normalize_timed_notifications

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator
    from ..models import Growspace

_LOGGER = logging.getLogger(__name__)


class NotificationSettingsManager:
    """Manages notification settings for growspaces.

    Handles:
    - Per-growspace notification enable/disable switches
    - Timed notification CRUD operations
    - Config entry options management
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the NotificationSettingsManager.

        Args:
            coordinator: The GrowspaceCoordinator instance
        """
        self.coordinator = coordinator

    @property
    def growspaces(self) -> dict[str, Growspace]:
        """Get growspaces from coordinator."""
        return self.coordinator.growspaces

    @property
    def notifications_enabled(self) -> dict[str, bool]:
        """Get notification enabled state from coordinator."""
        return self.coordinator.notification_state.enabled

    @property
    def config_entry(self) -> Any:
        """Get config entry from coordinator."""
        return self.coordinator.config_entry

    def is_notifications_enabled(self, growspace_id: str) -> bool:
        """Check if notifications are enabled for a specific growspace.

        Args:
            growspace_id: The ID of the growspace to check

        Returns:
            True if notifications are enabled, False otherwise (defaults to True)
        """
        return self.notifications_enabled.get(growspace_id, True)

    def set_notifications_state(
        self, growspace_id: str, enabled: bool
    ) -> dict[str, bool]:
        """Set notification state for a growspace.

        Args:
            growspace_id: The ID of the growspace
            enabled: New notification state

        Returns:
            Updated notifications_enabled dict for data property
        """
        if growspace_id not in self.growspaces:
            _LOGGER.warning(
                "Attempted to set notifications for non-existent growspace: %s",
                growspace_id,
            )
            return self.notifications_enabled

        old_state = self.notifications_enabled.get(growspace_id, True)
        self.notifications_enabled[growspace_id] = enabled

        _LOGGER.info(
            "Notifications for growspace %s (%s): %s → %s",
            growspace_id,
            self.growspaces[growspace_id].name,
            "enabled" if old_state else "disabled",
            "enabled" if enabled else "disabled",
        )

        return self.notifications_enabled

    def get_timed_notifications(self) -> list[dict[str, Any]]:
        """Get the list of configured timed notifications.

        Returns:
            List of timed notification configurations
        """
        return normalize_timed_notifications(
            self.config_entry.options.get("timed_notifications", [])
        )

    def create_timed_notification(
        self,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new timed notification.

        Args:
            message: Notification message
            trigger_type: Type of trigger
            day: Day number for trigger
            growspace_ids: List of growspace IDs to apply to

        Returns:
            New notification dict
        """
        return {
            "id": str(uuid.uuid4()),
            "message": message,
            "trigger_type": normalize_timed_notification_trigger(trigger_type),
            "day": int(day),
            "growspace_ids": growspace_ids or [],
        }

    def update_timed_notification_in_list(
        self,
        notifications: list[dict[str, Any]],
        notification_id: str,
        message: str,
        trigger_type: str,
        day: int,
        growspace_ids: list[str] | None = None,
    ) -> bool:
        """Update a timed notification in the list.

        Args:
            notifications: List of notifications to update
            notification_id: ID of notification to update
            message: New message
            trigger_type: New trigger type
            day: New day
            growspace_ids: New growspace IDs

        Returns:
            True if notification was found and updated
        """
        for notification in notifications:
            if notification["id"] == notification_id:
                notification["message"] = message
                notification["trigger_type"] = normalize_timed_notification_trigger(
                    trigger_type
                )
                notification["day"] = int(day)
                notification["growspace_ids"] = growspace_ids or []
                return True
        return False

    def remove_timed_notification_from_list(
        self, notifications: list[dict[str, Any]], notification_id: str
    ) -> list[dict[str, Any]]:
        """Remove a timed notification from the list.

        Args:
            notifications: List of notifications
            notification_id: ID of notification to remove

        Returns:
            New list without the removed notification
        """
        return [n for n in notifications if n["id"] != notification_id]

    def __repr__(self) -> str:
        """Return string representation."""
        enabled_count = sum(1 for v in self.notifications_enabled.values() if v)
        total_count = len(self.notifications_enabled)
        timed_count = len(self.get_timed_notifications())
        return (
            f"NotificationManager("
            f"enabled={enabled_count}/{total_count}, "
            f"timed={timed_count})"
        )
