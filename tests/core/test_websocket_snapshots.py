"""Snapshot tests for Growspace Manager WebSocket API."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.websocket import (
    websocket_add_growspace_note,
    websocket_add_timeline_note,
    websocket_delete_breeder,
    websocket_get_alerts,
    websocket_get_event_log,
    websocket_get_growspace_data,
    websocket_get_history_stats,
    websocket_get_ipm_presets,
    websocket_get_nutrient_inventory,
    websocket_get_nutrient_presets,
    websocket_get_strain_library,
    websocket_get_vision_history,
    websocket_update_breeder,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_connection():
    """Mock a WebSocket connection."""
    connection = MagicMock()
    connection.send_result = MagicMock()
    connection.send_error = MagicMock()
    return connection


@pytest.mark.asyncio
async def test_websocket_get_growspace_data_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_growspace_data output matches snapshot."""
    coordinator = MagicMock()
    coordinator.get_growspace_data.return_value = {
        "id": "gs1",
        "name": "Test Growspace",
        "plants": [
            {"id": "p1", "strain": "Northern Lights"},
            {"id": "p2", "strain": "Blueberry"},
        ],
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": f"{DOMAIN}/get_data", "growspace_id": "gs1"}
        await websocket_get_growspace_data(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_strain_library_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_strain_library output matches snapshot."""
    strain_library = MagicMock()
    strain_library.get_all.return_value = {
        "Northern Lights": {"type": "Indica", "flowering_weeks": 8},
        "Blueberry": {"type": "Indica/Sativa", "flowering_weeks": 9},
    }
    hass.data[DOMAIN] = {"strain_library": strain_library}

    msg = {"id": 2, "type": f"{DOMAIN}/get_strain_library"}
    websocket_get_strain_library(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_nutrient_inventory_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_nutrient_inventory output matches snapshot."""
    coordinator = MagicMock()
    inventory = MagicMock()
    inventory_data = {
        "stocks": {
            "n1": {"name": "Nutri-Plus A", "current_ml": 500, "initial_ml": 1000},
            "n2": {"name": "Nutri-Plus B", "current_ml": 450, "initial_ml": 1000},
        }
    }
    # coordinator.nutrient_inventory_service.get_inventory() returns it
    coordinator.nutrient_inventory_service.get_inventory.return_value = inventory

    with (
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
            return_value=coordinator,
        ),
        patch(
            "custom_components.growspace_manager.websocket.asdict",
            return_value=inventory_data,
        ),
    ):
        msg = {"id": 3, "type": f"{DOMAIN}/get_nutrient_inventory"}
        websocket_get_nutrient_inventory(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_nutrient_presets_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_nutrient_presets output matches snapshot."""
    coordinator = MagicMock()
    coordinator.nutrient_manager.get_serialization_data.return_value = {
        "nutrient_presets": [
            {"name": "Early Veg", "nutrients": {"n1": 2.0, "n2": 2.0}},
            {"name": "Late Veg", "nutrients": {"n1": 4.0, "n2": 4.0}},
        ],
        "ipm_presets": [],
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 4, "type": f"{DOMAIN}/get_nutrient_presets"}
        websocket_get_nutrient_presets(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_ipm_presets_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_ipm_presets output matches snapshot."""
    coordinator = MagicMock()
    coordinator.nutrient_manager.get_serialization_data.return_value = {
        "nutrient_presets": [],
        "ipm_presets": [
            {"name": "Neem Oil Spray", "application_type": "foliar"},
        ],
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 5, "type": f"{DOMAIN}/get_ipm_presets"}
        websocket_get_ipm_presets(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_add_timeline_note_snapshot(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test websocket_add_timeline_note success."""
    coordinator = MagicMock()
    hass.data[DOMAIN] = {"strain_library": MagicMock()}

    with (
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
            return_value=coordinator,
        ),
        patch(
            "custom_components.growspace_manager.websocket.async_add_timeline_note",
            new_callable=AsyncMock,
        ) as mock_add_note,
    ):
        msg = {
            "id": 6,
            "type": f"{DOMAIN}/add_timeline_note",
            "plant_id": "p1",
            "notes": "Looking healthy!",
            "transition_date": None,
            "images": ["base64data"],
            "tags": ["healthy"],
            "ph": 6.2,
            "ec": 1.4,
            "amount_ml": 500,
            "metadata": {"source": "manual"},
        }
        await websocket_add_timeline_note(hass, mock_connection, msg)

        mock_add_note.assert_called_once()
        mock_connection.send_result.assert_called_once_with(6)


@pytest.mark.asyncio
async def test_websocket_add_growspace_note_snapshot(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test websocket_add_growspace_note success."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock()}
    hass.data[DOMAIN] = {"strain_library": MagicMock()}

    with (
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
            return_value=coordinator,
        ),
        patch(
            "custom_components.growspace_manager.websocket.async_add_growspace_note",
            new_callable=AsyncMock,
        ) as mock_add_note,
    ):
        msg = {
            "id": 7,
            "type": f"{DOMAIN}/add_growspace_note",
            "growspace_id": "gs1",
            "notes": "Tent looking healthy today.",
            "images": [],
        }
        await websocket_add_growspace_note(hass, mock_connection, msg)

        mock_add_note.assert_called_once()
        mock_connection.send_result.assert_called_once_with(7)


@pytest.mark.asyncio
async def test_websocket_get_event_log_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_event_log output matches snapshot."""
    mock_event_data = {
        "category": "manual",
        "growspace_id": "gs1",
        "notes": "Manual log entry",
        "timestamp": 1672531200000,
    }

    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.event_id = 123

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = json.dumps(mock_event_data)

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    # Mock EventTypes row
    mock_event_type_row = (1,)

    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = mock_event_type_row
    mock_query.join.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.__iter__.return_value = iter([(mock_event_row, mock_event_data_row)])

    mock_session.query.return_value = mock_query

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session

        msg = {"id": 7, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_alerts_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_alerts output matches snapshot."""
    mock_event_data = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 0.9,
        "start_time": "2023-01-01T00:00:00",
        "end_time": "2023-01-01T00:05:00",
        "duration_sec": 300,
        "timestamp": 1672531200000,
    }

    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.event_id = 456

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = json.dumps(mock_event_data)

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = (1,)
    mock_query.join.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.__iter__.return_value = iter([(mock_event_row, mock_event_data_row)])

    mock_session.query.return_value = mock_query

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session

        msg = {"id": 8, "type": f"{DOMAIN}/get_alerts", "growspace_id": "gs1"}
        await websocket_get_alerts(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_get_history_stats_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_history_stats output matches snapshot."""
    # Use frozen time for consistent ISO formats
    with patch(
        "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
        new_callable=AsyncMock,
    ) as mock_downsample:
        mock_downsample.return_value = {
            "sensor.temp": [
                {"s": "22.5", "lu": "2026-01-12T12:00:00+00:00"},
                {"s": "23.0", "lu": "2026-01-12T12:05:00+00:00"},
            ]
        }

        msg = {
            "id": 9,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.temp"],
            "start_time": "2026-01-12T11:00:00+00:00",
            "interval_minutes": 5,
        }
        await websocket_get_history_stats(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result == snapshot


@pytest.mark.asyncio
async def test_websocket_update_breeder_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_update_breeder output matches snapshot."""
    strain_library = AsyncMock()
    strain_library.update_breeder.return_value = 5
    hass.data[DOMAIN] = {"strain_library": strain_library}

    msg = {
        "id": 10,
        "type": f"{DOMAIN}/update_breeder",
        "original_name": "Old Breeder",
        "new_name": "New Breeder",
        "logo": "new_logo.png",
    }
    await websocket_update_breeder(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(10, {"updated": 5})
    assert snapshot == {"updated": 5}


@pytest.mark.asyncio
async def test_websocket_delete_breeder_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_delete_breeder output matches snapshot."""
    strain_library = AsyncMock()
    strain_library.delete_breeder.return_value = 3
    hass.data[DOMAIN] = {"strain_library": strain_library}

    msg = {
        "id": 11,
        "type": f"{DOMAIN}/delete_breeder",
        "breeder_name": "Breeder to Delete",
    }
    await websocket_delete_breeder(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(11, {"deleted": 3})
    assert snapshot == {"deleted": 3}


@pytest.mark.asyncio
async def test_websocket_get_vision_history_empty(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_vision_history returns empty list when growspace has no history."""
    coordinator = MagicMock()
    growspace = MagicMock()
    growspace.vision_checkup_history = []
    coordinator.growspaces = {"tent1": growspace}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {
            "id": 12,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
        }
        await websocket_get_vision_history(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(
        12, {"history": [], "total": 0}
    )


@pytest.mark.asyncio
async def test_websocket_get_vision_history_with_results(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_vision_history returns paginated history with correct fields."""
    coordinator = MagicMock()
    growspace = MagicMock()

    result1 = MagicMock()
    result1.timestamp = "2026-03-21T10:00:00"
    result1.check_type = "early"
    result1.analysis = "Plants look healthy."
    result1.issues_detected = []
    result1.severity = "none"
    result1.recommendations = ["Keep it up"]
    result1.snapshot_paths = ["/local/snap1.jpg"]

    result2 = MagicMock()
    result2.timestamp = "2026-03-21T14:00:00"
    result2.check_type = "mid"
    result2.analysis = "Minor yellowing detected."
    result2.issues_detected = ["yellowing"]
    result2.severity = "low"
    result2.recommendations = ["Check pH", "Adjust nutrients"]
    result2.snapshot_paths = ["/local/snap2.jpg"]

    growspace.vision_checkup_history = [result1, result2]
    coordinator.growspaces = {"tent1": growspace}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {
            "id": 13,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
            "limit": 10,
        }
        await websocket_get_vision_history(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    call_id, result = mock_connection.send_result.call_args[0]
    assert call_id == 13
    assert result["total"] == 2
    assert len(result["history"]) == 2

    first = result["history"][0]
    assert first["timestamp"] == "2026-03-21T10:00:00"
    assert first["check_type"] == "early"
    assert first["analysis"] == "Plants look healthy."
    assert first["issues_detected"] == []
    assert first["severity"] == "none"
    assert first["recommendations"] == ["Keep it up"]
    assert first["snapshot_paths"] == ["/local/snap1.jpg"]


@pytest.mark.asyncio
async def test_websocket_get_vision_history_growspace_not_found(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_vision_history returns error when growspace does not exist."""
    coordinator = MagicMock()
    coordinator.growspaces = {}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {
            "id": 14,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "nonexistent",
        }
        await websocket_get_vision_history(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(
        14, "not_found", "Growspace nonexistent not found"
    )


@pytest.mark.asyncio
async def test_websocket_get_vision_history_limit(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_vision_history respects the limit parameter."""
    coordinator = MagicMock()
    growspace = MagicMock()

    results = []
    for i in range(5):
        r = MagicMock()
        r.timestamp = f"2026-03-21T{10 + i:02d}:00:00"
        r.check_type = "mid"
        r.analysis = f"Analysis {i}"
        r.issues_detected = []
        r.severity = "none"
        r.recommendations = []
        r.snapshot_paths = []
        results.append(r)

    growspace.vision_checkup_history = results
    coordinator.growspaces = {"tent1": growspace}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {
            "id": 15,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
            "limit": 2,
        }
        await websocket_get_vision_history(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    call_id, result = mock_connection.send_result.call_args[0]
    assert call_id == 15
    assert result["total"] == 5
    assert len(result["history"]) == 2
