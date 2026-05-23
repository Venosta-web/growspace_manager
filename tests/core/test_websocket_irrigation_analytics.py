"""Tests for irrigation analytics WebSocket handler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket.irrigation import (
    WS_TYPE_GET_IRRIGATION_ANALYTICS,
    websocket_get_irrigation_analytics,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.mark.asyncio
async def test_get_irrigation_analytics_returns_stage_aggregates(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Handler aggregates consumption across all trackers and returns by stage."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_IRRIGATION_ANALYTICS,
        "growspace_id": "gs1",
    }
    tracker_a = MagicMock()
    tracker_a.get_stage_aggregates.return_value = {"veg": 12.0, "flower_early": 5.0}
    tracker_b = MagicMock()
    tracker_b.get_stage_aggregates.return_value = {"veg": 8.0}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {
            "sensor.tank_a": tracker_a,
            "sensor.tank_b": tracker_b,
        }
        await websocket_get_irrigation_analytics(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == "gs1"
    assert result["stage_aggregates"]["veg"] == pytest.approx(20.0)
    assert result["stage_aggregates"]["flower_early"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_get_irrigation_analytics_no_trackers_returns_empty(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Handler returns empty aggregates when no trackers exist for the growspace."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_IRRIGATION_ANALYTICS,
        "growspace_id": "gs1",
    }
    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {}
        await websocket_get_irrigation_analytics(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["stage_aggregates"] == {}


@pytest.mark.asyncio
async def test_get_irrigation_analytics_unknown_growspace_returns_empty(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Handler returns empty aggregates when growspace has no trackers."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_IRRIGATION_ANALYTICS,
        "growspace_id": "unknown",
    }
    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {}
        await websocket_get_irrigation_analytics(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["stage_aggregates"] == {}


@pytest.mark.asyncio
async def test_get_irrigation_analytics_handles_coordinator_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Handler sends error when coordinator lookup fails."""
    msg = {
        "id": 1,
        "type": WS_TYPE_GET_IRRIGATION_ANALYTICS,
        "growspace_id": "gs1",
    }
    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("no coordinator"),
    ):
        await websocket_get_irrigation_analytics(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once()
