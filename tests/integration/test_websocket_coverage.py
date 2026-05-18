"""Tests for Websocket coverage (exceptions and edge cases)."""

from dataclasses import dataclass
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.websocket import (
    ATTR_NOTES,
    ATTR_PLANT_ID,
    websocket_add_timeline_note,
    websocket_delete_breeder,
    websocket_get_alerts,
    websocket_get_event_log,
    websocket_get_genetics_data,
    websocket_get_history_stats,
    websocket_get_nutrient_inventory,
    websocket_remove_nutrient_stock,
    websocket_remove_timeline_event,
    websocket_update_breeder,
    websocket_update_nutrient_stock,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_connection():
    """Mock websocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def mock_msg():
    """Mock websocket message."""
    return {"id": 1, "growspace_id": "gs1", "limit": 50}


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    return hass


async def test_websocket_get_event_log_recorder_error(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_event_log handles recorder import/key errors."""
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=ImportError("Recorder not found"),
    ):
        await websocket_get_event_log(hass, mock_connection, mock_msg)

        # Sould return empty result, not error
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


async def test_websocket_get_event_log_generic_error(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_event_log handles generic exceptions."""
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=Exception("Boom"),
    ):
        await websocket_get_event_log(hass, mock_connection, mock_msg)

        mock_connection.send_error.assert_called_with(1, "unknown_error", "Boom")


async def test_websocket_get_alerts_no_event_type(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts handles missing event type in DB."""
    mock_msg["limit"] = 10

    # Mock recorder instance
    mock_recorder = AsyncMock()

    # Mock session scope and query chain
    mock_session = MagicMock()
    # Mock first query for event type to return None
    mock_session.query.return_value.filter.return_value.first.return_value = None

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_session)),
        ),
    ):
        # We need to test the inner query function
        # But since async_add_executor_job runs it in thread, we can use side_effect
        # to just run it immediately if we mock async_add_executor_job,
        # OR we can let it run if we mock the session correctly.

        # Let's mock async_add_executor_job to run the function
        async def run_job(func, *args):
            return func(*args)

        mock_recorder.async_add_executor_job.side_effect = run_job

        await websocket_get_alerts(hass, mock_connection, mock_msg)

        # Should return empty dict/list structure
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


async def test_websocket_get_alerts_recorder_error(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts handles recorder errors."""
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=ImportError("Recorder fail"),
    ):
        await websocket_get_alerts(hass, mock_connection, mock_msg)
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


async def test_websocket_get_alerts_generic_error(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts handles generic errors."""
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=Exception("Boom Alerts"),
    ):
        await websocket_get_alerts(hass, mock_connection, mock_msg)
        mock_connection.send_error.assert_called_with(1, "unknown_error", "Boom Alerts")


async def test_websocket_nutrient_inventory_service_missing(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test nutrient inventory commands when service is missing."""
    # Mock coordinator get via service call
    mock_coord = MagicMock()
    # Ensure it does NOT have nutrient_inventory_service
    mock_coord.nutrient_inventory_service = None

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_any",
        return_value=mock_coord,
    ):
        # 1. get_nutrient_inventory
        websocket_get_nutrient_inventory(hass, mock_connection, mock_msg)
        mock_connection.send_result.assert_called_with(1, {"stocks": {}})

        # Reset mocks
        mock_connection.reset_mock()

        # 2. update_nutrient_stock
        websocket_update_nutrient_stock(hass, mock_connection, mock_msg)
        mock_connection.send_error.assert_called_with(
            1, "not_initialized", "Service not ready"
        )

        # Reset mocks
        mock_connection.reset_mock()

        # 3. remove_nutrient_stock
        websocket_remove_nutrient_stock(hass, mock_connection, mock_msg)
        mock_connection.send_error.assert_called_with(
            1, "not_initialized", "Service not ready"
        )


async def test_websocket_nutrient_inventory_success(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test successful nutrient inventory commands."""
    # Mock coordinator with service
    mock_coord = MagicMock()
    mock_config_entry = MagicMock()
    mock_config_entry.async_create_background_task.side_effect = (
        lambda hass, coro, name: asyncio.create_task(coro)
    )
    mock_coord.config_entry = mock_config_entry
    mock_service = MagicMock()
    mock_coord.nutrient_inventory_service = mock_service
    mock_coord.async_commit = AsyncMock()

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_any",
        return_value=mock_coord,
    ):
        # Update Stock Success
        msg_update = {
            "id": 1,
            "nutrient_id": "n1",
            "name": "N1",
            "current_ml": 500,
            "initial_ml": 1000,
        }
        websocket_update_nutrient_stock(hass, mock_connection, msg_update)
        await asyncio.sleep(0)  # Yield to background tasks

        mock_service.update_stock.assert_called_with(
            nutrient_id="n1", name="N1", current_ml=500.0, initial_ml=1000.0
        )
        mock_connection.send_result.assert_called_with(1)
        mock_coord.async_commit.assert_awaited()

        # Reset
        mock_connection.reset_mock()
        mock_coord.async_commit.reset_mock()
        mock_config_entry.async_create_background_task.reset_mock()


        # Remove Stock Success
        msg_remove = {"id": 2, "nutrient_id": "n1"}
        websocket_remove_nutrient_stock(hass, mock_connection, msg_remove)
        await asyncio.sleep(0)  # Yield to background tasks

        mock_service.remove_stock.assert_called_with("n1")
        mock_connection.send_result.assert_called_with(2)
        mock_coord.async_commit.assert_awaited()


async def test_websocket_add_timeline_note_validation_error(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test add_timeline_note handles validation errors."""
    msg = {"id": 1, ATTR_PLANT_ID: "plant1", ATTR_NOTES: "notes"}

    mock_coord = MagicMock()
    mock_coord.services.add_timeline_note = AsyncMock(
        side_effect=ServiceValidationError("Invalid Plant")
    )

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            return_value=mock_coord,
        ),
    ):
        # We need mock strain library in hass.data
        hass.data[DOMAIN] = {"strain_library": MagicMock()}

        await websocket_add_timeline_note(hass, mock_connection, msg)

        mock_connection.send_error.assert_called_with(
            1, "invalid_args", "Invalid Plant"
        )


async def test_websocket_remove_timeline_event_error(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test remove_timeline_event handles errors."""
    msg = {"id": 1, "event_id": 123}

    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=Exception("DB Error"),
    ):
        await websocket_remove_timeline_event(hass, mock_connection, msg)

        mock_connection.send_error.assert_called_with(1, "unknown_error", "DB Error")


async def test_websocket_get_alerts_filtering(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts filtering logic."""
    mock_msg["limit"] = 2
    mock_msg["growspace_id"] = "gs1"

    # Mock data rows
    # 1. Invalid row (None) -> Line 297
    # 2. Row with different growspace_id -> Line 301
    # 3. Row with non-alert category -> Line 305
    # 4. Valid alert -> Success
    # 5. Valid alert -> Success
    # 6. Valid alert -> Should be skipped due to limit (Line 308)

    row_none = (MagicMock(), None)

    row_diff_gs = (
        MagicMock(),
        MagicMock(shared_data=json.dumps({"growspace_id": "gs2", "category": "mold"})),
    )

    row_bad_cat = (
        MagicMock(),
        MagicMock(shared_data=json.dumps({"growspace_id": "gs1", "category": "info"})),
    )

    row_valid_1 = (
        MagicMock(time_fired_ts=100),
        MagicMock(
            shared_data=json.dumps({"growspace_id": "gs1", "category": "optimal"})
        ),
    )

    row_valid_2 = (
        MagicMock(time_fired_ts=101),
        MagicMock(
            shared_data=json.dumps({"growspace_id": "gs1", "category": "stress"})
        ),
    )

    row_valid_3 = (
        MagicMock(time_fired_ts=102),
        MagicMock(shared_data=json.dumps({"growspace_id": "gs1", "category": "mold"})),
    )

    mock_recorder = AsyncMock()
    mock_session = MagicMock()
    # Chain of query mocks...
    # session.query().join().filter().order_by().limit().__iter__
    mock_query = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value
    mock_query.__iter__.return_value = [
        row_none,
        row_diff_gs,
        row_bad_cat,
        row_valid_1,
        row_valid_2,
        row_valid_3,
    ]

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_session)),
        ),
    ):
        # Execute plain function immediately
        mock_recorder.async_add_executor_job.side_effect = lambda f, *a: f(*a)

        await websocket_get_alerts(hass, mock_connection, mock_msg)

        # Verify result contains only the 2 valid alerts allowed by limit
        args, _ = mock_connection.send_result.call_args
        res = args[1]["gs1"]
        assert len(res) == 2
        assert res[0]["category"] == "optimal"
        assert res[1]["category"] == "stress"


async def test_websocket_get_alerts_invalid_json(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts with invalid JSON."""
    row_bad_json = (MagicMock(), MagicMock(shared_data="{invalid"))

    mock_recorder = AsyncMock()
    mock_session = MagicMock()
    mock_query = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value
    mock_query.__iter__.return_value = [row_bad_json]

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_session)),
        ),
    ):
        mock_recorder.async_add_executor_job.side_effect = lambda f, *a: f(*a)
        await websocket_get_alerts(hass, mock_connection, mock_msg)
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


async def test_websocket_get_alerts_no_growspace_id(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test get_alerts without growspace_id (Global view)."""
    del mock_msg["growspace_id"]

    row_valid = (
        MagicMock(time_fired_ts=100),
        MagicMock(shared_data=json.dumps({"growspace_id": "gs1", "category": "mold"})),
    )

    mock_recorder = AsyncMock()
    mock_session = MagicMock()
    mock_query = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value.limit.return_value
    mock_query.__iter__.return_value = [row_valid]

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=MagicMock(__enter__=MagicMock(return_value=mock_session)),
        ),
    ):
        mock_recorder.async_add_executor_job.side_effect = lambda f, *a: f(*a)
        await websocket_get_alerts(hass, mock_connection, mock_msg)

        args, _ = mock_connection.send_result.call_args
        res = args[1]
        assert "gs1" in res
        assert len(res["gs1"]) == 1


async def test_websocket_get_nutrient_inventory_success_get(
    hass: HomeAssistant, mock_connection, mock_msg
) -> None:
    """Test successful get_nutrient_inventory."""

    @dataclass
    class MockInventory:
        stocks: dict

    mock_coord = MagicMock()
    mock_service = MagicMock()
    mock_coord.nutrient_inventory_service = mock_service
    mock_service.get_inventory.return_value = MockInventory(stocks={})

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_any",
        return_value=mock_coord,
    ):
        websocket_get_nutrient_inventory(hass, mock_connection, mock_msg)
        mock_connection.send_result.assert_called()


async def test_websocket_get_history_stats_sub_hourly(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_history_stats with sub-hourly interval (fallback path)."""
    msg = {
        "id": 1,
        "entity_ids": ["sensor.test"],
        "start_time": "2023-01-01T00:00:00Z",
        "interval_minutes": 5,  # < 60
    }

    with patch(
        "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
        return_value={"sensor.test": []},
    ) as mock_downsample:
        await websocket_get_history_stats(hass, mock_connection, msg)
        mock_downsample.assert_awaited()


async def test_websocket_get_history_stats_empty(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_history_stats returns None from stats API."""
    msg = {
        "id": 1,
        "entity_ids": ["s.t"],
        "start_time": "2023-01-01T00:00:00Z",
        "interval_minutes": 60,
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket._get_statistics_data",
            return_value=None,
        ),
        patch(
            "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
            return_value={"s.t": []},
        ) as mock_fallback,
    ):
        await websocket_get_history_stats(hass, mock_connection, msg)
        mock_fallback.assert_awaited()


async def test_websocket_breeder_commands_strain_library_missing(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test breeder commands when strain library is not loaded."""
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop("strain_library", None)
    else:
        hass.data[DOMAIN] = {}

    msg_update = {
        "id": 12,
        "type": f"{DOMAIN}/update_breeder",
        "original_name": "O",
        "new_name": "N",
    }
    await websocket_update_breeder(hass, mock_connection, msg_update)
    mock_connection.send_error.assert_called_with(
        12, "not_loaded", "Growspace Manager strain library not loaded"
    )

    mock_connection.reset_mock()

    msg_delete = {
        "id": 13,
        "type": f"{DOMAIN}/delete_breeder",
        "breeder_name": "B",
    }
    await websocket_delete_breeder(hass, mock_connection, msg_delete)
    mock_connection.send_error.assert_called_with(
        13, "not_loaded", "Growspace Manager strain library not loaded"
    )


async def test_websocket_breeder_commands_generic_error(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test breeder commands generic exceptions."""
    strain_library = AsyncMock()
    strain_library.update_breeder.side_effect = Exception("Breeder Update Fail")
    strain_library.delete_breeder.side_effect = Exception("Breeder Delete Fail")

    mock_coordinator = MagicMock()
    mock_coordinator.strain_library = strain_library

    msg_update = {
        "id": 14,
        "type": f"{DOMAIN}/update_breeder",
        "original_name": "O",
        "new_name": "N",
    }
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coordinator,
    ):
        await websocket_update_breeder(hass, mock_connection, msg_update)
    mock_connection.send_error.assert_called_with(
        14, "unknown_error", "Breeder Update Fail"
    )

    mock_connection.reset_mock()

    msg_delete = {
        "id": 15,
        "type": f"{DOMAIN}/delete_breeder",
        "breeder_name": "B",
    }
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coordinator,
    ):
        await websocket_delete_breeder(hass, mock_connection, msg_delete)
    mock_connection.send_error.assert_called_with(
        15, "unknown_error", "Breeder Delete Fail"
    )


def test_websocket_get_genetics_data_success(
    mock_connection: MagicMock, mock_msg: dict
) -> None:
    """Test websocket_get_genetics_data sends result on success (websocket.py:596-603)."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.genetics_manager.get_serialization_data.return_value = {"seed_batches": {}}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        websocket_get_genetics_data(hass, mock_connection, mock_msg)

    mock_connection.send_result.assert_called_once_with(1, {"seed_batches": {}})
    mock_connection.send_error.assert_not_called()


def test_websocket_get_genetics_data_error(
    mock_connection: MagicMock, mock_msg: dict
) -> None:
    """Test websocket_get_genetics_data sends error on exception (websocket.py:604-606)."""
    hass = MagicMock()

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("Something went wrong"),
    ):
        websocket_get_genetics_data(hass, mock_connection, mock_msg)

    mock_connection.send_error.assert_called_once_with(
        1, "unknown_error", "Something went wrong"
    )
    mock_connection.send_result.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_get_strain_lineage_tree_success(mock_hass: MagicMock) -> None:
    """Test get_strain_lineage_tree returns resolved tree."""
    from custom_components.growspace_manager.websocket import websocket_get_strain_lineage_tree

    strain_library = MagicMock()
    strain_library.get_strain_lineage_tree.return_value = {
        "name": "Gelato #41",
        "source": "library",
        "parents": [],
    }
    mock_coordinator = MagicMock()
    mock_coordinator.strain_library = strain_library
    connection = MagicMock()

    msg = {"id": 1, "type": f"{DOMAIN}/get_strain_lineage_tree", "strain_name": "Gelato #41"}
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coordinator,
    ):
        await websocket_get_strain_lineage_tree(mock_hass, connection, msg)

    connection.send_result.assert_called_once_with(
        1, {"name": "Gelato #41", "source": "library", "parents": []}
    )


@pytest.mark.asyncio
async def test_websocket_get_strain_lineage_tree_not_loaded(mock_hass: MagicMock) -> None:
    """Test get_strain_lineage_tree when strain library not loaded."""
    from custom_components.growspace_manager.websocket import websocket_get_strain_lineage_tree

    mock_hass.data = {}
    connection = MagicMock()
    msg = {"id": 1, "type": f"{DOMAIN}/get_strain_lineage_tree", "strain_name": "X"}
    await websocket_get_strain_lineage_tree(mock_hass, connection, msg)
    connection.send_error.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_update_strain_lineage_tree_success(mock_hass: MagicMock) -> None:
    """Test update_strain_lineage_tree saves and returns flat lineage."""
    from custom_components.growspace_manager.websocket import (
        websocket_update_strain_lineage_tree,
    )

    strain_library = AsyncMock()
    strain_library.update_strain_lineage_tree.return_value = "OG Kush × Durban Poison"
    mock_coordinator = MagicMock()
    mock_coordinator.strain_library = strain_library
    connection = MagicMock()

    parents = [
        {"name": "OG Kush", "source": "library"},
        {"name": "Durban Poison", "source": "manual"},
    ]
    msg = {
        "id": 2,
        "type": f"{DOMAIN}/update_strain_lineage_tree",
        "strain_name": "Hybrid",
        "parents": parents,
    }
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coordinator,
    ):
        await websocket_update_strain_lineage_tree(mock_hass, connection, msg)
    connection.send_result.assert_called_once_with(
        2, {"lineage": "OG Kush × Durban Poison"}
    )


@pytest.mark.asyncio
async def test_websocket_update_strain_lineage_tree_not_loaded(
    mock_hass: MagicMock,
) -> None:
    """Test update_strain_lineage_tree when strain library not loaded."""
    from custom_components.growspace_manager.websocket import (
        websocket_update_strain_lineage_tree,
    )

    mock_hass.data = {}
    connection = MagicMock()
    msg = {
        "id": 3,
        "type": f"{DOMAIN}/update_strain_lineage_tree",
        "strain_name": "X",
        "parents": [],
    }
    await websocket_update_strain_lineage_tree(mock_hass, connection, msg)
    connection.send_error.assert_called_once()
