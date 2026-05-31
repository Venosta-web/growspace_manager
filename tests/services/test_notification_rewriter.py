"""Tests for AINotificationRewriter."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
)
from custom_components.growspace_manager.notification_rewriter import (
    AINotificationRewriter,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

AI_SETTINGS_BASE = {
    CONF_AI_ENABLED: True,
    CONF_ASSISTANT_ID: "test_agent",
}


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    return hass


@pytest.fixture
def rewriter(mock_hass: MagicMock) -> AINotificationRewriter:
    """Fixture for AINotificationRewriter."""
    return AINotificationRewriter(mock_hass)


def _make_converse_result(speech: str | None, error_code: str | None = None) -> MagicMock:
    result = MagicMock()
    result.response.error_code = error_code
    result.response.response_type = None
    if speech is not None:
        result.response.speech = {"plain": {"speech": speech}}
    else:
        result.response.speech = {}
    return result


async def test_async_rewrite_success(rewriter: AINotificationRewriter) -> None:
    """Test successful AI rewrite returns rewritten message."""
    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=_make_converse_result("Ahoy! Test Message Rewrite"),
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)

    assert result == "Ahoy! Test Message Rewrite"


async def test_async_rewrite_on_cooldown(rewriter: AINotificationRewriter) -> None:
    """Test returns original message when on AI rate-limit cooldown."""
    rewriter._ai_cooldown_until = dt_util.utcnow() + timedelta(minutes=10)

    result = await rewriter.async_rewrite(
        "Original", "Tent", None, AI_SETTINGS_BASE
    )

    assert result == "Original"


async def test_async_rewrite_rate_limit_sets_cooldown(
    rewriter: AINotificationRewriter,
) -> None:
    """Test 429 rate limit response sets cooldown and returns original."""
    mock_result = _make_converse_result("Too Many Requests", error_code="rate_limit")

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)

    assert result == "Original"
    assert rewriter._ai_cooldown_until is not None


async def test_async_rewrite_non_rate_limit_error_no_cooldown(
    rewriter: AINotificationRewriter,
) -> None:
    """Test non-rate-limit error logs warning but does not set cooldown."""
    mock_result = _make_converse_result("Some error occurred", error_code="some_other_error")

    with (
        patch(
            "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
            new_callable=AsyncMock,
            return_value=mock_result,
        ),
        patch(
            "custom_components.growspace_manager.notification_rewriter._LOGGER.warning"
        ) as mock_warn,
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)
        mock_warn.assert_called()

    assert result == "Original"
    assert rewriter._ai_cooldown_until is None


async def test_async_rewrite_empty_speech_returns_original(
    rewriter: AINotificationRewriter,
) -> None:
    """Test empty speech in response returns original message."""
    mock_result = MagicMock()
    mock_result.response.error_code = None
    mock_result.response.response_type = None
    mock_result.response.speech = {}

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)

    assert result == "Original"


async def test_async_rewrite_none_result_returns_original(
    rewriter: AINotificationRewriter,
) -> None:
    """Test None response returns original message."""
    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)

    assert result == "Original"


async def test_async_rewrite_exception_returns_original(
    rewriter: AINotificationRewriter,
) -> None:
    """Test exception during rewrite returns original message."""
    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        side_effect=ValueError("AI Error"),
    ):
        result = await rewriter.async_rewrite("Original", "Tent", None, AI_SETTINGS_BASE)

    assert result == "Original"


@pytest.mark.parametrize(
    ("personality", "expected_phrase"),
    [
        ("Scientific", "precise technical terminology"),
        ("Chill Stoner", "laid-back and friendly"),
        ("Strict Coach", "direct and authoritative"),
        ("Pirate", "Write like a pirate"),
        ("Standard", "clear, professional, and helpful"),
    ],
)
async def test_async_rewrite_personalities(
    rewriter: AINotificationRewriter, personality: str, expected_phrase: str
) -> None:
    """Test prompt contains correct personality guidance for each personality."""
    ai_settings = {**AI_SETTINGS_BASE, CONF_NOTIFICATION_PERSONALITY: personality}

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=_make_converse_result(f"Rewritten as {personality}"),
    ) as mock_converse:
        await rewriter.async_rewrite("Message", "Tent", None, ai_settings)

    prompt = mock_converse.call_args[1]["text"]
    assert expected_phrase in prompt


async def test_async_rewrite_sensor_formatting(
    rewriter: AINotificationRewriter,
) -> None:
    """Test sensor data formatting: bools and None values are excluded from prompt."""
    sensor_states = {"temp": 25, "humidity": 60, "fan": True, "light": None}

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=_make_converse_result("Rewritten"),
    ) as mock_converse:
        await rewriter.async_rewrite("Message", "Tent", sensor_states, AI_SETTINGS_BASE)

    prompt = mock_converse.call_args[1]["text"]
    assert "temp: 25" in prompt
    assert "humidity: 60" in prompt
    assert "fan: True" not in prompt
    assert "light: None" not in prompt


async def test_async_rewrite_truncation_close(
    rewriter: AINotificationRewriter,
) -> None:
    """Test response slightly over limit is intelligently truncated."""
    ai_settings = {**AI_SETTINGS_BASE, "max_response_length": 10}
    long_response = "This is a long response"  # 23 chars; 10 < 23 < 60

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=_make_converse_result(long_response),
    ):
        result = await rewriter.async_rewrite("Message", "Tent", None, ai_settings)

    assert result.endswith("...")


async def test_async_rewrite_truncation_too_long(
    rewriter: AINotificationRewriter,
) -> None:
    """Test response far over limit falls back to original."""
    ai_settings = {**AI_SETTINGS_BASE, "max_response_length": 10}
    very_long_response = "A" * 70  # 70 >= 10 + 50

    with patch(
        "custom_components.growspace_manager.notification_rewriter.conversation.async_converse",
        new_callable=AsyncMock,
        return_value=_make_converse_result(very_long_response),
    ):
        result = await rewriter.async_rewrite("Original Message", "Tent", None, ai_settings)

    assert result == "Original Message"
