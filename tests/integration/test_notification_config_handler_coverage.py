"""Tests for the Notification Config Handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.notification_config_handler import (
    NotificationConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = "test_entry"
    entry.runtime_data = MagicMock()
    return entry


@pytest.fixture
def handler(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> NotificationConfigHandler:
    """Create a NotificationConfigHandler instance."""
    handler = NotificationConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_notification_id = "notif1"
    return handler


async def test_async_step_manage_timed_notifications_abort_no_entry(
    mock_hass: MagicMock,
) -> None:
    handler = NotificationConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_manage_timed_notifications()
    assert result == {"type": "abort"}


async def test_async_step_manage_timed_notifications_get(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.get_timed_notifications.return_value = []
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_manage_timed_notifications()
    assert result["type"] == "form"


async def test_async_step_manage_timed_notifications_post(
    handler: NotificationConfigHandler,
) -> None:
    handler.async_step_add_timed_notification = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_timed_notifications({"action": "add"})
    handler.async_step_add_timed_notification.assert_called_once()

    handler.async_step_edit_timed_notification = AsyncMock(
        return_value={"type": "form"}
    )
    await handler.async_step_manage_timed_notifications(
        {"action": "edit", "notification_id": "n1"}
    )
    assert handler.flow.selected_notification_id == "n1"

    handler.async_step_delete_timed_notification = AsyncMock(
        return_value={"type": "form"}
    )
    await handler.async_step_manage_timed_notifications(
        {"action": "delete", "notification_id": "n1"}
    )
    handler.async_step_delete_timed_notification.assert_called_once()

    handler.flow.async_step_init = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_timed_notifications({"action": "back"})
    handler.flow.async_step_init.assert_called_once()


async def test_async_step_add_timed_notification_success(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services = MagicMock()
    coordinator.services.notifications.async_add_timed_notification = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {
        "message": "MSG",
        "trigger_type": "type",
        "day": 1,
        "growspace_ids": ["gs1"],
    }
    result = await handler.async_step_add_timed_notification(user_input)
    assert result["type"] == "create_entry"
    coordinator.services.notifications.async_add_timed_notification.assert_called_once_with(
        "MSG", "type", 1, ["gs1"]
    )


async def test_async_step_add_timed_notification_get(
    handler: NotificationConfigHandler,
) -> None:
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_add_timed_notification()
    assert result["type"] == "form"


async def test_async_step_edit_timed_notification_success(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services = MagicMock()
    coordinator.services.notifications.get_timed_notifications = MagicMock(
        return_value=[{"id": "notif1", "message": "msg", "trigger_type": "t", "day": 1}]
    )
    coordinator.services.notifications.async_update_timed_notification = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {"message": "new", "trigger_type": "t", "day": 2, "growspace_ids": []}
    result = await handler.async_step_edit_timed_notification(user_input)
    assert result["type"] == "create_entry"
    coordinator.services.notifications.async_update_timed_notification.assert_called_once_with(
        "notif1", "new", "t", 2, []
    )


async def test_async_step_edit_timed_notification_not_found(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services = MagicMock()
    coordinator.services.notifications.get_timed_notifications = MagicMock(
        return_value=[]
    )
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_edit_timed_notification()
    assert result == {"type": "abort"}


async def test_async_step_delete_timed_notification_success(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services = MagicMock()
    coordinator.services.notifications.async_remove_timed_notification = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    result = await handler.async_step_delete_timed_notification({"confirm": True})
    assert result["type"] == "create_entry"
    coordinator.services.notifications.async_remove_timed_notification.assert_called_once_with(
        "notif1"
    )


async def test_get_add_edit_schema_with_growspaces(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MagicMock(name="gs1")}
    coordinator.growspaces["gs1"].name = "GS1"

    schema = handler.get_add_edit_schema(coordinator)
    assert "growspace_ids" in schema.schema


async def test_async_steps_no_coordinator(handler: NotificationConfigHandler) -> None:
    # Use a real handler with None entry
    handler_no_entry = NotificationConfigHandler(handler.hass, None)
    handler_no_entry.flow = handler.flow
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    assert await handler_no_entry.async_step_manage_timed_notifications() == {
        "type": "abort"
    }
    assert await handler_no_entry.async_step_add_timed_notification() == {
        "type": "abort"
    }
    assert await handler_no_entry.async_step_edit_timed_notification() == {
        "type": "abort"
    }
    assert await handler_no_entry.async_step_delete_timed_notification() == {
        "type": "abort"
    }

    # Test None coordinator
    handler.config_entry.runtime_data = None
    assert await handler.async_step_manage_timed_notifications() == {"type": "abort"}
    # The other steps check config_entry first, so they don't need coordinator check
    # if handler.config_entry is None.


async def test_async_step_edit_timed_notification_no_notif(
    handler: NotificationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.get_timed_notifications.return_value = [{"id": "other"}]
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_edit_timed_notification()
    assert result == {"type": "abort"}


async def test_get_add_edit_schema_empty(handler: NotificationConfigHandler) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {}
    schema = handler.get_add_edit_schema(coordinator)
    assert "growspace_ids" not in schema.schema


async def test_get_timed_notification_schema_empty(
    handler: NotificationConfigHandler,
) -> None:
    schema = handler.get_timed_notification_schema([])
    assert "notification_id" not in schema.schema
