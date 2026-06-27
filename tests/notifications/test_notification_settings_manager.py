"""Tests for the NotificationSettingsManager."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.notifications.notification_settings_manager import (
    NotificationSettingsManager,
)


def test_growspaces_property() -> None:
    """Test growspaces property retrieves from coordinator."""
    mock_coordinator = MagicMock()
    mock_growspaces = {"gs1": MagicMock()}
    mock_coordinator.growspaces = mock_growspaces

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.growspaces == mock_growspaces


def test_notifications_enabled_property() -> None:
    """Test notifications_enabled property retrieves from coordinator."""
    mock_coordinator = MagicMock()
    mock_enabled = {"gs1": True}
    mock_coordinator.notification_state.enabled = mock_enabled

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.notifications_enabled == mock_enabled


def test_config_entry_property() -> None:
    """Test config_entry property retrieves from coordinator."""
    mock_coordinator = MagicMock()
    mock_entry = MagicMock()
    mock_coordinator.config_entry = mock_entry

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.config_entry == mock_entry


@pytest.mark.parametrize(
    ("notifications_dict", "growspace_id", "expected"),
    [
        ({"gs1": True}, "gs1", True),
        ({"gs1": False}, "gs1", False),
        ({}, "gs2", True),  # Defaults to True
    ],
)
def test_is_notifications_enabled(
    notifications_dict: dict[str, bool], growspace_id: str, expected: bool
) -> None:
    """Test is_notifications_enabled returns correct status."""
    mock_coordinator = MagicMock()
    mock_coordinator.notification_state.enabled = notifications_dict

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.is_notifications_enabled(growspace_id) is expected


def test_set_notifications_state_nonexistent_growspace() -> None:
    """Test set_notifications_state logs warning for nonexistent growspace."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {}
    mock_coordinator.notification_state.enabled = {"gs1": True}

    manager = NotificationSettingsManager(mock_coordinator)
    result = manager.set_notifications_state("nonexistent", False)

    # Should not have modified the state
    assert result == {"gs1": True}


def test_set_notifications_state_existent_growspace() -> None:
    """Test set_notifications_state successfully updates state."""
    mock_coordinator = MagicMock()
    mock_growspace = MagicMock()
    mock_growspace.name = "My Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.notification_state.enabled = {"gs1": True}

    manager = NotificationSettingsManager(mock_coordinator)
    result = manager.set_notifications_state("gs1", False)

    assert result == {"gs1": False}
    assert mock_coordinator.notification_state.enabled["gs1"] is False


def test_get_timed_notifications_default() -> None:
    """Test get_timed_notifications returns empty list when none configured."""
    mock_coordinator = MagicMock()
    mock_coordinator.config_entry.options = {}

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.get_timed_notifications() == []


def test_get_timed_notifications_configured() -> None:
    """Test get_timed_notifications returns configured list."""
    mock_coordinator = MagicMock()
    notifications = [{"id": "1", "message": "water"}]
    mock_coordinator.config_entry.options = {"timed_notifications": notifications}

    manager = NotificationSettingsManager(mock_coordinator)
    assert manager.get_timed_notifications() == notifications


@pytest.mark.parametrize(
    ("growspace_ids", "expected_ids"),
    [
        (None, []),
        (["gs1", "gs2"], ["gs1", "gs2"]),
    ],
)
def test_create_timed_notification(
    growspace_ids: list[str] | None, expected_ids: list[str]
) -> None:
    """Test creating a timed notification generates UUID and correct dict structure."""
    mock_coordinator = MagicMock()
    manager = NotificationSettingsManager(mock_coordinator)

    result = manager.create_timed_notification(
        message="Alert!",
        trigger_type="vpd",
        day=5,
        growspace_ids=growspace_ids,
    )

    assert "id" in result
    assert isinstance(result["id"], str)
    assert len(result["id"]) > 0
    assert result["message"] == "Alert!"
    assert result["trigger_type"] == "vpd"
    assert result["day"] == 5
    assert result["growspace_ids"] == expected_ids


def test_update_timed_notification_in_list() -> None:
    """Test updating a timed notification in a list."""
    mock_coordinator = MagicMock()
    manager = NotificationSettingsManager(mock_coordinator)

    notifications = [
        {
            "id": "notif1",
            "message": "Test Notif",
            "trigger_type": "day",
            "day": 5,
            "growspace_ids": ["gs1"],
        }
    ]

    # Try updating existing
    result = manager.update_timed_notification_in_list(
        notifications, "notif1", "Updated Message", "flower_day", 10, ["gs2"]
    )
    assert result is True
    assert notifications[0]["message"] == "Updated Message"
    assert notifications[0]["trigger_type"] == "flower_day"
    assert notifications[0]["day"] == 10
    assert notifications[0]["growspace_ids"] == ["gs2"]


def test_update_timed_notification_in_list_not_found() -> None:
    """Test updating a non-existent timed notification returns False."""
    mock_coordinator = MagicMock()
    manager = NotificationSettingsManager(mock_coordinator)

    notifications = [
        {
            "id": "notif1",
            "message": "Test Notif",
            "trigger_type": "day",
            "day": 5,
            "growspace_ids": ["gs1"],
        }
    ]

    result = manager.update_timed_notification_in_list(
        notifications, "invalid_id", "Updated Message", "flower_day", 10, ["gs2"]
    )
    assert result is False
    assert notifications[0]["message"] == "Test Notif"


def test_remove_timed_notification_from_list() -> None:
    """Test removing a timed notification from a list."""
    mock_coordinator = MagicMock()
    manager = NotificationSettingsManager(mock_coordinator)

    notifications = [
        {"id": "notif1", "message": "Test 1"},
        {"id": "notif2", "message": "Test 2"},
    ]

    result = manager.remove_timed_notification_from_list(notifications, "notif1")
    assert result == [{"id": "notif2", "message": "Test 2"}]


def test_repr() -> None:
    """Test string representation of NotificationSettingsManager."""
    mock_coordinator = MagicMock()
    mock_coordinator.notification_state.enabled = {"gs1": True, "gs2": False, "gs3": True}
    mock_coordinator.config_entry.options = {
        "timed_notifications": [
            {"id": "1"},
            {"id": "2"},
        ]
    }

    manager = NotificationSettingsManager(mock_coordinator)
    assert repr(manager) == "NotificationManager(enabled=2/3, timed=2)"
