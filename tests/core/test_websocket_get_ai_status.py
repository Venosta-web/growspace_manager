"""Tests for the get_ai_status WebSocket handler."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_coordinator(ai_enabled: bool) -> MagicMock:
    coord = MagicMock()
    coord.options = {"ai_settings": {"ai_enabled": ai_enabled}}
    return coord


# ---------------------------------------------------------------------------
# get_ai_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ai_status_returns_true_when_ai_enabled(
    mock_connection: MagicMock,
) -> None:
    """get_ai_status returns { ai_enabled: true } when ai_settings.ai_enabled is True."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_status,
    )

    coordinator = _make_coordinator(ai_enabled=True)
    msg = {"id": 1, "type": f"{DOMAIN}/get_ai_status"}

    result = await websocket_get_ai_status(MagicMock(), coordinator, msg)

    assert result == {"ai_enabled": True}


@pytest.mark.asyncio
async def test_get_ai_status_returns_false_when_ai_disabled(
    mock_connection: MagicMock,
) -> None:
    """get_ai_status returns { ai_enabled: false } when ai_settings.ai_enabled is False."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_status,
    )

    coordinator = _make_coordinator(ai_enabled=False)
    msg = {"id": 2, "type": f"{DOMAIN}/get_ai_status"}

    result = await websocket_get_ai_status(MagicMock(), coordinator, msg)

    assert result == {"ai_enabled": False}


@pytest.mark.asyncio
async def test_get_ai_status_returns_false_when_no_ai_settings(
    mock_connection: MagicMock,
) -> None:
    """get_ai_status returns { ai_enabled: false } when ai_settings is absent."""
    from custom_components.growspace_manager.websocket.ai_assistant import (
        websocket_get_ai_status,
    )

    coordinator = MagicMock()
    coordinator.options = {}
    msg = {"id": 3, "type": f"{DOMAIN}/get_ai_status"}

    result = await websocket_get_ai_status(MagicMock(), coordinator, msg)

    assert result == {"ai_enabled": False}
