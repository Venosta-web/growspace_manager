"""Tests for the apply_steering_mode WebSocket command (ADR-0012)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import SteeringMode
from custom_components.growspace_manager.websocket.irrigation import (
    websocket_apply_steering_mode,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_connection() -> MagicMock:
    """Mock websocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


async def test_apply_steering_mode_delegates_and_echoes_intent(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """The command stamps via the facade and returns the declared intent."""
    coord = MagicMock()
    coord.services.growspaces.apply_steering_mode = AsyncMock()
    msg = {"id": 1, "growspace_id": "tent1", "steering_mode": "generative"}

    result = await websocket_apply_steering_mode(hass, coord, msg)

    coord.services.growspaces.apply_steering_mode.assert_awaited_once_with(
        "tent1", SteeringMode.GENERATIVE
    )
    assert result == {"growspace_id": "tent1", "declared_steering_mode": "generative"}
