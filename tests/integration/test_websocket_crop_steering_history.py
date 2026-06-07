"""Tests for get_crop_steering_history WebSocket command."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket.irrigation import (
    websocket_get_crop_steering_history,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_connection() -> MagicMock:
    """Mock websocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_coordinator(growspace_id: str | None = "tent1") -> MagicMock:
    coord = MagicMock()
    if growspace_id is None:
        coord.growspaces = {}
    else:
        coord.growspaces = {growspace_id: MagicMock()}
    return coord


async def test_returns_history_for_known_growspace(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """A known growspace delegates to the analyzer and sends the result."""
    coord = _make_coordinator()
    msg = {"id": 1, "growspace_id": "tent1"}
    analyzer_result = {
        "lights_on": "2026-06-07T06:00:00+00:00",
        "soil_moisture": [],
        "pore_ec": [],
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
            return_value=coord,
        ),
        patch(
            "custom_components.growspace_manager.websocket.irrigation.CropSteeringHistoryAnalyzer"
        ) as mock_analyzer_cls,
    ):
        mock_analyzer = mock_analyzer_cls.return_value
        mock_analyzer.async_get_history = AsyncMock(return_value=analyzer_result)

        await websocket_get_crop_steering_history(hass, mock_connection, msg)

    mock_connection.send_error.assert_not_called()
    result = mock_connection.send_result.call_args[0][1]
    assert result == {"growspace_id": "tent1", **analyzer_result}


async def test_unknown_growspace_sends_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """An unknown growspace_id is a contract violation surfaced via send_error."""
    coord = _make_coordinator(growspace_id=None)
    msg = {"id": 1, "growspace_id": "missing"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_crop_steering_history(hass, mock_connection, msg)

    mock_connection.send_result.assert_not_called()
    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "not_found"


async def test_exception_sends_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Unexpected errors are surfaced via send_error rather than raised."""
    coord = _make_coordinator()
    msg = {"id": 1, "growspace_id": "tent1"}

    with (
        patch(
            "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
            return_value=coord,
        ),
        patch(
            "custom_components.growspace_manager.websocket.irrigation.CropSteeringHistoryAnalyzer"
        ) as mock_analyzer_cls,
    ):
        mock_analyzer = mock_analyzer_cls.return_value
        mock_analyzer.async_get_history = AsyncMock(side_effect=RuntimeError("boom"))

        await websocket_get_crop_steering_history(hass, mock_connection, msg)

    mock_connection.send_result.assert_not_called()
    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "unknown_error"
