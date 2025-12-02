"""Tests for the NotificationManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
)
from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.notification_manager import NotificationManager

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
    coordinator.is_notifications_enabled.return_value = True
    coordinator._notifications_sent = {}
    coordinator.async_save = AsyncMock()
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def manager(mock_hass: MagicMock, mock_coordinator: MagicMock) -> NotificationManager:
    """Fixture for NotificationManager."""
    return NotificationManager(mock_hass, mock_coordinator)


def test_initialization(
    manager: NotificationManager, mock_hass: MagicMock, mock_coordinator: MagicMock
):
    """Test initialization."""
    assert manager.hass == mock_hass
    assert manager.coordinator == mock_coordinator
    assert manager._last_notification_sent == {}


def test_generate_notification_message(manager: NotificationManager):
    """Test generating notification message."""
    base_message = "Base message"
    reasons = [(0.9, "Reason 1"), (0.8, "Reason 2")]

    message = manager.generate_notification_message(base_message, reasons)
    assert "Reason 1" in message
    assert "Reason 2" in message


async def test_async_send_notification_success(
    manager: NotificationManager, mock_hass: MagicMock
):
    """Test sending a notification successfully."""
    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_awaited_once_with(
        "notify",
        "mobile_app_test",
        {"message": "Test Message", "title": "Test Title"},
        blocking=False,
    )


async def test_async_send_notification_cooldown(
    manager: NotificationManager, mock_hass: MagicMock
):
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
):
    """Test sending notification with no target configured."""
    mock_coordinator.growspaces[GROWSPACE_ID].notification_target = None

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_disabled(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
):
    """Test sending notification when disabled."""
    mock_coordinator.is_notifications_enabled.return_value = False

    await manager.async_send_notification(GROWSPACE_ID, "Test Title", "Test Message")

    mock_hass.services.async_call.assert_not_awaited()


async def test_async_send_notification_ai_rewrite(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
):
    """Test sending notification with AI rewrite."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
            CONF_NOTIFICATION_PERSONALITY: "Pirate",
        }
    }

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
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
            {"message": "Ahoy! Test Message Rewrite", "title": "Test Title"},
            blocking=False,
        )


async def test_async_check_timed_notifications(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
):
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

    plant = Plant(
        plant_id="plant_1",
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
    )
    mock_coordinator.get_growspace_plants.return_value = [plant]
    mock_coordinator.calculate_days_in_stage.return_value = 10

    await manager.async_check_timed_notifications()

    mock_hass.services.async_call.assert_awaited()
    assert mock_coordinator._notifications_sent["plant_1"]["timed_notify_1"] is True
    mock_coordinator.async_save.assert_awaited()


def test_generate_notification_message_truncation(manager: NotificationManager):
    """Test message truncation in generate_notification_message."""
    base_message = "Base"
    # Create reasons that will exceed the 65 char limit
    # "Base" is 4 chars.
    # "Reason 1" is 8 chars.
    # "Reason 2" is 8 chars.
    # "Reason 3" is 8 chars.
    # "Reason 4" is 8 chars.
    # "Reason 5" is 8 chars.
    # "Reason 6" is 8 chars.
    # "Reason 7" is 8 chars.
    # "Reason 8" is 8 chars.
    reasons = [(0.9, "A" * 20), (0.8, "B" * 20), (0.7, "C" * 20)]

    # "Base" (4) + ", " (2) + "A"*20 (20) = 26 chars.
    # 26 + 2 + 20 = 48 chars.
    # 48 + 2 + 20 = 70 chars > 65. So C should be skipped.

    message = manager.generate_notification_message(base_message, reasons)
    assert "A" * 20 in message
    assert "B" * 20 in message
    assert "C" * 20 not in message


async def test_async_send_notification_exception(
    manager: NotificationManager, mock_hass: MagicMock
):
    """Test exception handling in async_send_notification."""
    mock_hass.services.async_call.side_effect = ValueError("Service Error")

    # Should not raise exception
    await manager.async_send_notification(GROWSPACE_ID, "Title", "Message")


async def test_rewrite_with_ai_personalities(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
):
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
            "homeassistant.components.conversation.async_converse"
        ) as mock_converse:
            mock_result = MagicMock()
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
):
    """Test AI rewrite with sensor data formatting."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    sensor_states = {"temp": 25, "humidity": 60, "fan": True, "light": None}

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
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
):
    """Test AI response truncation."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
            "max_response_length": 10,
        }
    }

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        # Case 1: Truncate
        result1 = MagicMock()
        long_response = "This is a long response"  # 23 chars. 10 < 23 < 60.
        result1.response.speech = {"plain": {"speech": long_response}}

        # Case 2: Too long, use default
        result2 = MagicMock()
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
):
    """Test AI returning empty response."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    with patch("homeassistant.components.conversation.async_converse") as mock_converse:
        mock_result = MagicMock()
        mock_result.response.speech = {}  # Empty speech
        mock_converse.return_value = mock_result

        await manager.async_send_notification(GROWSPACE_ID, "Title", "Original Message")

        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"] == "Original Message"


async def test_rewrite_with_ai_exception(
    manager: NotificationManager, mock_coordinator: MagicMock, mock_hass: MagicMock
):
    """Test exception during AI rewrite."""
    mock_coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent",
        }
    }

    with patch(
        "homeassistant.components.conversation.async_converse",
        side_effect=Exception("AI Error"),
    ):
        await manager.async_send_notification(GROWSPACE_ID, "Title", "Original Message")

        args = mock_hass.services.async_call.call_args[0]
        assert args[2]["message"] == "Original Message"


async def test_async_check_timed_notifications_empty_config(
    manager: NotificationManager, mock_coordinator: MagicMock
):
    """Test checking timed notifications with empty config."""
    mock_coordinator.options = {}
    await manager.async_check_timed_notifications()
    # Should just return without error


async def test_async_check_timed_notifications_missing_growspace(
    manager: NotificationManager, mock_coordinator: MagicMock
):
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
