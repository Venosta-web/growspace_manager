"""Tests for irrigation analytics WebSocket handler."""

from __future__ import annotations

from unittest.mock import MagicMock

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

    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {
            "sensor.tank_a": tracker_a,
            "sensor.tank_b": tracker_b,
        }
        result = await websocket_get_irrigation_analytics(
            hass, mock_get.return_value, msg
        )

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
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {}
        result = await websocket_get_irrigation_analytics(
            hass, mock_get.return_value, msg
        )

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
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.get_all_trackers_for_growspace.return_value = {}
        result = await websocket_get_irrigation_analytics(
            hass, mock_get.return_value, msg
        )

    assert result["stage_aggregates"] == {}
