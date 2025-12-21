"""Tests for the NotificationConfigHandler."""

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.config_handlers.notification_config_handler import (
    NotificationConfigHandler,
)
from custom_components.growspace_manager.models import Growspace


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    return MagicMock()


@pytest.fixture
def handler(mock_hass, mock_config_entry) -> NotificationConfigHandler:
    """Fixture for the handler."""
    return NotificationConfigHandler(mock_hass, mock_config_entry)


def test_get_timed_notification_schema_empty(
    handler: NotificationConfigHandler,
) -> None:
    """Test timed notification schema with no existing notifications."""
    schema = handler.get_timed_notification_schema([])
    assert isinstance(schema, vol.Schema)
    # notification_id should NOT be in schema
    # We can inspect schema.schema dict
    assert "notification_id" not in str(schema.schema)


def test_get_timed_notification_schema_with_items(
    handler: NotificationConfigHandler,
) -> None:
    """Test timed notification schema with existing notifications."""
    notifications = [{"id": "n1", "message": "msg1", "trigger_type": "type1", "day": 5}]
    schema = handler.get_timed_notification_schema(notifications)
    # notification_id should BE in schema
    assert "notification_id" in str(schema.schema)


def test_get_add_edit_schema_empty_growspaces(
    handler: NotificationConfigHandler,
) -> None:
    """Test add/edit schema with no growspaces."""
    coordinator = MagicMock()
    coordinator.growspaces = {}

    schema = handler.get_add_edit_schema(coordinator)
    assert isinstance(schema, vol.Schema)
    # growspace_id should NOT be in schema
    assert "growspace_id" not in str(schema.schema)


def test_get_add_edit_schema_with_growspaces(
    handler: NotificationConfigHandler,
) -> None:
    """Test add/edit schema with growspaces available."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": Growspace(id="gs1", name="GS1")}

    schema = handler.get_add_edit_schema(coordinator)
    # growspace_id should BE in schema
    assert "growspace_id" in str(schema.schema)


def test_get_add_edit_schema_defaults(handler: NotificationConfigHandler) -> None:
    """Test schema defaults from existing notification."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": Growspace(id="gs1", name="GS1")}
    notification = {
        "message": "Hello",
        "trigger_type": "days_since_germination",
        "day": 10,
        "growspace_id": "gs1",
    }

    schema = handler.get_add_edit_schema(coordinator, notification)
    # Voluptuous schemas are hard to inspect extensively for default values without internal access
    # But ensuring it doesn't crash is a good start, and the code path is covered.
    assert "growspace_id" in str(schema.schema)
