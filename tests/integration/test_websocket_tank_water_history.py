"""Tests for get_tank_water_history WebSocket command."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket.irrigation import (
    websocket_get_tank_water_history,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_buckets(count: int, liters: float = 0.0) -> list[dict]:
    return [{"bucket_start": f"2024-01-01T00:{i:02d}:00+00:00", "liters_consumed": liters, "liters_refilled": 0.0} for i in range(count)]


def _make_coordinator(
    growspace_id: str = "tent1",
    flow_sensors: list | None = None,
    drain_sensors: list | None = None,
    trackers: dict | None = None,
) -> MagicMock:
    coord = MagicMock()
    env = MagicMock()
    env.irrigation_flow_sensors = flow_sensors or []
    env.drain_volume_sensors = drain_sensors or []

    growspace = MagicMock()
    growspace.environment_config = env
    coord.growspaces = {growspace_id: growspace}
    coord.services.growspaces.get_all_trackers_for_growspace.return_value = trackers or {}
    return coord


async def test_24h_returns_96_buckets(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """24h range returns 96 15-min buckets."""
    tracker = MagicMock()
    tracker.get_history_24h.return_value = _make_buckets(96)
    coord = _make_coordinator(trackers={"tank1": tracker})

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == "tent1"
    assert result["range"] == "24h"
    assert len(result["buckets"]) == 96


async def test_7d_returns_168_buckets(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """7d range returns 168 hourly buckets."""
    tracker = MagicMock()
    tracker.get_history_7d.return_value = _make_buckets(168)
    coord = _make_coordinator(trackers={"tank1": tracker})

    msg = {"id": 1, "growspace_id": "tent1", "range": "7d"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert len(result["buckets"]) == 168


async def test_6h_returns_24_buckets(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """6h range returns last 24 buckets from get_history_24h."""
    tracker = MagicMock()
    tracker.get_history_24h.return_value = _make_buckets(96)
    coord = _make_coordinator(trackers={"tank1": tracker})

    msg = {"id": 1, "growspace_id": "tent1", "range": "6h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert len(result["buckets"]) == 24


async def test_1h_returns_4_buckets(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """1h range returns last 4 buckets from get_history_24h."""
    tracker = MagicMock()
    tracker.get_history_24h.return_value = _make_buckets(96)
    coord = _make_coordinator(trackers={"tank1": tracker})

    msg = {"id": 1, "growspace_id": "tent1", "range": "1h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert len(result["buckets"]) == 4


async def test_aggregates_liters_across_tanks(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Liters are summed across all qualifying tanks per bucket index."""
    tracker_a = MagicMock()
    tracker_a.get_history_24h.return_value = _make_buckets(96, liters=1.0)
    tracker_b = MagicMock()
    tracker_b.get_history_24h.return_value = _make_buckets(96, liters=0.5)
    coord = _make_coordinator(trackers={"tank_a": tracker_a, "tank_b": tracker_b})

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert all(b["liters"] == pytest.approx(1.5) for b in result["buckets"])


async def test_returns_empty_buckets_when_flow_sensors_configured(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Returns empty buckets list when growspace uses flow sensors."""
    coord = _make_coordinator(flow_sensors=["sensor.flow1"])

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["buckets"] == []


async def test_returns_empty_buckets_when_drain_sensors_configured(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Returns empty buckets list when growspace uses drain sensors."""
    coord = _make_coordinator(drain_sensors=["sensor.drain1"])

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["buckets"] == []


async def test_all_zero_buckets_when_no_consumption(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Qualifying tanks with no events return all-zero liters buckets."""
    tracker = MagicMock()
    tracker.get_history_24h.return_value = _make_buckets(96, liters=0.0)
    coord = _make_coordinator(trackers={"tank1": tracker})

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert len(result["buckets"]) == 96
    assert all(b["liters"] == 0.0 for b in result["buckets"])


async def test_returns_empty_buckets_when_growspace_not_found(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Returns empty buckets list when growspace ID is not found in coordinator."""
    coord = MagicMock()
    coord.growspaces.get.return_value = None

    msg = {"id": 1, "growspace_id": "unknown", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == "unknown"
    assert result["range"] == "24h"
    assert result["buckets"] == []


async def test_returns_empty_buckets_when_no_qualifying_trackers(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Returns empty buckets list when growspace has no water trackers."""
    coord = _make_coordinator(trackers={})

    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == "tent1"
    assert result["range"] == "24h"
    assert result["buckets"] == []


async def test_error_sends_error_response(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Exceptions are caught and sent as error responses."""
    msg = {"id": 1, "growspace_id": "tent1", "range": "24h"}

    with patch(
        "custom_components.growspace_manager.websocket.irrigation.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("boom"),
    ):
        await websocket_get_tank_water_history(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(1, "unknown_error", "boom")
