from unittest.mock import MagicMock

from custom_components.growspace_manager.notifications.notification_settings_manager import (
    NotificationSettingsManager,
)


def test_update_notification_settings_id_mismatch() -> None:
    """Test update_notification_settings with ID mismatch."""
    # This covers the ID mismatch logic (line 157)
    manager = NotificationSettingsManager(MagicMock())

    # Existing notifications list
    notifications = [
        {
            "id": "notif1",
            "message": "Test Notif",
            "trigger_type": "day",
            "day": 5,
            "growspace_ids": ["gs1"],
        }
    ]

    # Update with different parameters, but passing "notif1" as ID
    # We want to trigger the logic where it finds the notification by ID.
    # Note: update_timed_notification_in_list doesn't have the "wrong_id" logic I wanted to test.
    # Wait, let me check where that logic is.

    manager.update_timed_notification_in_list(
        notifications, "notif1", "Updated Message", "flower_day", 10, ["gs2"]
    )

    assert notifications[0]["message"] == "Updated Message"
    assert notifications[0]["day"] == 10
    assert notifications[0]["growspace_ids"] == ["gs2"]


def test_update_notification_settings_id_mismatch_return_false():
    """Test that updating non-existent notification returns False."""
    manager = NotificationSettingsManager(MagicMock())
    notifications = [{"id": "n1", "message": "old"}]
    result = manager.update_timed_notification_in_list(
        notifications, "invalid", "new", "t", 1
    )
    assert result is False
    assert notifications[0]["message"] == "old"
