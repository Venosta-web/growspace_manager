"""Snapshot tests for Growspace Manager WebSocket API."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models.vision_evidence import (
    CaptureTrigger,
    CheckupStatus,
    LightWindow,
    VisionCheckup,
)
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnectionSource,
    VisionModelSummary,
    VisionStatus,
)
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
    websocket_get_vision_history_v2,
    websocket_get_vision_status,
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


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_get_growspace_data_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_growspace_data output matches snapshot."""
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.growspaces.get_growspace_data.return_value = {
        "id": "gs1",
        "name": "Test Growspace",
        "plants": [
            {"id": "p1", "strain": "Northern Lights"},
            {"id": "p2", "strain": "Blueberry"},
        ],
    }

    if True:
        msg = {"id": 1, "type": f"{DOMAIN}/get_data", "growspace_id": "gs1"}
        result = await websocket_get_growspace_data(hass, coordinator, msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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

    coordinator = MagicMock()
    coordinator._strain_library = strain_library
    coordinator.services.config.strain_library = strain_library

    if True:
        msg = {"id": 2, "type": f"{DOMAIN}/get_strain_library"}
        result = websocket_get_strain_library(hass, coordinator, msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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
    # coordinator._nutrient_manager.inventory_service.get_inventory() returns it
    coordinator._nutrient_manager.inventory_service.get_inventory.return_value = (
        inventory
    )

    with (
        patch(
            "custom_components.growspace_manager.websocket.nutrients.asdict",
            return_value=inventory_data,
        ),
    ):
        msg = {"id": 3, "type": f"{DOMAIN}/get_nutrient_inventory"}
        result = websocket_get_nutrient_inventory(hass, coordinator, msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_get_nutrient_presets_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_nutrient_presets output matches snapshot."""
    coordinator = MagicMock()
    coordinator.services.config.get_nutrient_serialization_data.return_value = {
        "nutrient_presets": [
            {"name": "Early Veg", "nutrients": {"n1": 2.0, "n2": 2.0}},
            {"name": "Late Veg", "nutrients": {"n1": 4.0, "n2": 4.0}},
        ],
        "ipm_presets": [],
    }

    if True:
        msg = {"id": 4, "type": f"{DOMAIN}/get_nutrient_presets"}
        result = websocket_get_nutrient_presets(hass, coordinator, msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_get_ipm_presets_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_ipm_presets output matches snapshot."""
    coordinator = MagicMock()
    coordinator.services.config.get_nutrient_serialization_data.return_value = {
        "nutrient_presets": [],
        "ipm_presets": [
            {"name": "Neem Oil Spray", "application_type": "foliar"},
        ],
    }

    if True:
        msg = {"id": 5, "type": f"{DOMAIN}/get_ipm_presets"}
        result = websocket_get_ipm_presets(hass, coordinator, msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_add_timeline_note_snapshot(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test websocket_add_timeline_note success."""
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.add_timeline_note = AsyncMock()
    coordinator._strain_library = MagicMock()

    if True:
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
        await websocket_add_timeline_note(hass, coordinator, msg)

        coordinator.services.add_timeline_note.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_add_growspace_note_snapshot(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test websocket_add_growspace_note success."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock()}
    coordinator._strain_library = MagicMock()

    coordinator.services = MagicMock()
    coordinator.services.growspaces.add_growspace_note = AsyncMock()

    if True:
        msg = {
            "id": 7,
            "type": f"{DOMAIN}/add_growspace_note",
            "growspace_id": "gs1",
            "notes": "Tent looking healthy today.",
            "images": [],
        }
        await websocket_add_growspace_note(hass, coordinator, msg)

        coordinator.services.growspaces.add_growspace_note.assert_called_once()


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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
            "custom_components.growspace_manager.websocket.logbook.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.logbook.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session

        msg = {"id": 7, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        result = await websocket_get_event_log(hass, MagicMock(), msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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
            "custom_components.growspace_manager.websocket.logbook.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.logbook.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session

        msg = {"id": 8, "type": f"{DOMAIN}/get_alerts", "growspace_id": "gs1"}
        result = await websocket_get_alerts(hass, MagicMock(), msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_get_history_stats_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_get_history_stats output matches snapshot."""
    # Use frozen time for consistent ISO formats
    with patch(
        "custom_components.growspace_manager.websocket.environment._get_history_with_binary_search_downsample",
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
        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        assert result == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_update_breeder_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_update_breeder output matches snapshot."""
    strain_library = AsyncMock()
    strain_library.update_breeder = AsyncMock(return_value=5)

    coordinator = MagicMock()
    coordinator._strain_library = strain_library
    coordinator.services.config.strain_library = strain_library

    if True:
        msg = {
            "id": 10,
            "type": f"{DOMAIN}/update_breeder",
            "original_name": "Old Breeder",
            "new_name": "New Breeder",
            "logo": "new_logo.png",
        }
        result = await websocket_update_breeder(hass, coordinator, msg)

        assert result == {"updated": 5}
        assert snapshot == {"updated": 5}


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_websocket_delete_breeder_snapshot(
    hass: HomeAssistant, mock_connection, snapshot: SnapshotAssertion
) -> None:
    """Test websocket_delete_breeder output matches snapshot."""
    strain_library = AsyncMock()
    strain_library.delete_breeder = AsyncMock(return_value=3)

    coordinator = MagicMock()
    coordinator._strain_library = strain_library
    coordinator.services.config.strain_library = strain_library

    if True:
        msg = {
            "id": 11,
            "type": f"{DOMAIN}/delete_breeder",
            "breeder_name": "Breeder to Delete",
        }
        result = await websocket_delete_breeder(hass, coordinator, msg)

        assert result == {"deleted": 3}
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

    if True:
        msg = {
            "id": 12,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
        }
        result = await websocket_get_vision_history(hass, coordinator, msg)

        assert result == {"history": [], "total": 0}


@pytest.mark.asyncio
async def test_websocket_get_vision_status_returns_cached_negotiated_model(
    hass: HomeAssistant,
) -> None:
    """The public status command projects the cache without refreshing it."""
    coordinator = MagicMock()
    coordinator.vision_connection.status = VisionStatus(
        availability=VisionAvailability.READY,
        connection_source=VisionConnectionSource.SUPERVISOR,
        service_version="1.4.0",
        vision_schema_version=1,
        model=VisionModelSummary(id="dinov2-small", version="1.0.0", dimension=384),
    )

    result = await websocket_get_vision_status(
        hass,
        coordinator,
        {"id": 16, "type": f"{DOMAIN}/get_vision_status"},
    )

    assert result == {
        "availability": "ready",
        "connection_source": "supervisor",
        "service_version": "1.4.0",
        "vision_schema_version": 1,
        "model": {"id": "dinov2-small", "version": "1.0.0", "dimension": 384},
    }
    coordinator.vision_connection.async_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_get_vision_history_v2_merges_frozen_legacy_tail(
    hass: HomeAssistant,
) -> None:
    """V1 checkups and attributed cloud rows share only the public timeline."""
    checkup = VisionCheckup(
        checkup_id="01991f1d-5c00-7000-8000-000000000001",
        growspace_id="tent1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at="2026-09-01T06:00:00+00:00",
        completed_at="2026-09-01T06:00:04+00:00",
        status=CheckupStatus.COMPLETED,
    )
    legacy = SimpleNamespace(
        timestamp="2026-08-31T06:00:00+00:00",
        check_type="early",
        snapshot_paths=["/local/legacy.jpg"],
        analysis="Historical cloud description.",
        issues_detected=["yellowing"],
        severity="high",
        recommendations=["Historical recommendation."],
    )
    growspace = MagicMock(vision_checkup_history=[legacy])
    coordinator = MagicMock(growspaces={"tent1": growspace})
    store = AsyncMock()
    store.async_get_checkups.return_value = [checkup]
    store.async_count_checkups.return_value = 1
    store.async_count_captures.return_value = 0
    store.async_get_checkup_captures.return_value = []
    hass.data.setdefault(DOMAIN, {})["vision_evidence_store"] = store

    result = await websocket_get_vision_history_v2(
        hass,
        coordinator,
        {
            "id": 17,
            "type": f"{DOMAIN}/get_vision_history_v2",
            "growspace_id": "tent1",
            "limit": 10,
        },
    )

    assert result == {
        "history": [
            {
                "result_schema": "evidence_v1",
                "checkup_id": checkup.checkup_id,
                "growspace_id": "tent1",
                "trigger_source": "scheduled",
                "light_window": "early",
                "started_at": "2026-09-01T06:00:00+00:00",
                "completed_at": "2026-09-01T06:00:04+00:00",
                "status": "completed",
                "captures": [],
            },
            {
                "result_schema": "legacy_cloud_v1",
                "timestamp": "2026-08-31T06:00:00+00:00",
                "check_type": "early",
                "snapshot_paths": ["/local/legacy.jpg"],
                "analysis": "Historical cloud description.",
                "issues_detected": ["yellowing"],
                "severity": "high",
                "recommendations": ["Historical recommendation."],
            },
        ],
        "total": 2,
        "capture_total": 0,
    }
    assert growspace.vision_checkup_history == [legacy]


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

    if True:
        msg = {
            "id": 13,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
            "limit": 10,
        }
        result = await websocket_get_vision_history(hass, coordinator, msg)

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

    msg = {
        "id": 14,
        "type": f"{DOMAIN}/get_vision_history",
        "growspace_id": "nonexistent",
    }
    with pytest.raises(GrowspaceNotFoundError, match="'nonexistent' not found"):
        await websocket_get_vision_history(hass, coordinator, msg)


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

    if True:
        msg = {
            "id": 15,
            "type": f"{DOMAIN}/get_vision_history",
            "growspace_id": "tent1",
            "limit": 2,
        }
        result = await websocket_get_vision_history(hass, coordinator, msg)

    assert result["total"] == 5
    assert len(result["history"]) == 2
