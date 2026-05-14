"""Tests for additional websocket coverage."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket import (
    _EPOCH_SENTINEL,
    WS_TYPE_GET_HISTORY_STATS,
    WS_TYPE_UPDATE_SENSOR_COORDINATES,
    _extract_ts,
    _get_history_with_binary_search_downsample,
    _get_statistics_data,
    _merge_logbook_event,
    websocket_get_history_stats,
    websocket_update_sensor_coordinates,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import homeassistant.util.dt as dt_util


@pytest.fixture
def mock_connection():
    """Mock websocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def test_extract_ts_unsupported_type() -> None:
    """Test _extract_ts with an unsupported type."""
    # Line 63 coverage
    # To reach line 63, it must NOT be a dict, and must have last_updated = None or something that isn't str/datetime
    mock_obj = MagicMock()
    mock_obj.last_updated = 123  # Not str, not datetime, not None
    assert _extract_ts(mock_obj) == _EPOCH_SENTINEL

    mock_obj.last_updated = None
    assert _extract_ts(mock_obj) == _EPOCH_SENTINEL


async def test_websocket_get_history_stats_invalid_times(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test get_history_stats with invalid timestamps."""
    # Line 613-614 coverage (already covered probably, but let's be sure)
    msg_bad_start = {
        "id": 1,
        "type": WS_TYPE_GET_HISTORY_STATS,
        "entity_ids": ["sensor.test"],
        "start_time": "invalid",
        "interval_minutes": 60,
    }
    await websocket_get_history_stats(hass, mock_connection, msg_bad_start)
    mock_connection.send_error.assert_called_with(
        1, "invalid_args", "Invalid start_time"
    )

    # Line 617-618 coverage
    msg_bad_end = {
        "id": 2,
        "type": WS_TYPE_GET_HISTORY_STATS,
        "entity_ids": ["sensor.test"],
        "start_time": "2023-01-01T00:00:00Z",
        "end_time": "invalid",
        "interval_minutes": 60,
    }
    with patch(
        "homeassistant.util.dt.parse_datetime",
        side_effect=[datetime(2023, 1, 1, tzinfo=dt_util.UTC), None],
    ):
        await websocket_get_history_stats(hass, mock_connection, msg_bad_end)
        mock_connection.send_error.assert_called_with(
            2, "invalid_args", "Invalid end_time"
        )


async def test_websocket_update_sensor_coordinates_success(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test successful sensor coordinate update."""
    msg = {
        "id": 1,
        "type": WS_TYPE_UPDATE_SENSOR_COORDINATES,
        "growspace_id": "gs1",
        "entity_id": "sensor.test",
        "x": 10,
        "y": 20,
        "z": 30,
        "rotation": 90,
    }

    mock_coord = MagicMock()
    mock_growspace = MagicMock()
    mock_coord.growspaces = {"gs1": mock_growspace}
    mock_growspace.environment_config.sensor_coordinates = {}
    mock_coord.async_commit = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coord,
    ):
        await websocket_update_sensor_coordinates(hass, mock_connection, msg)

        assert mock_growspace.environment_config.sensor_coordinates["sensor.test"] == {
            "x": 10,
            "y": 20,
            "z": 30,
            "rotation": 90,
        }
        mock_coord.async_commit.assert_awaited()
        mock_coord.async_request_refresh.assert_awaited()
        mock_connection.send_result.assert_called_with(1)


async def test_websocket_update_sensor_coordinates_no_rotation(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test sensor coordinate update without rotation."""
    msg = {
        "id": 1,
        "type": WS_TYPE_UPDATE_SENSOR_COORDINATES,
        "growspace_id": "gs1",
        "entity_id": "sensor.test",
        "x": 10,
        "y": 20,
        "z": 30,
    }

    mock_coord = MagicMock()
    mock_growspace = MagicMock()
    mock_coord.growspaces = {"gs1": mock_growspace}
    mock_growspace.environment_config.sensor_coordinates = (
        None  # Test initialization too
    )
    mock_coord.async_commit = AsyncMock()
    mock_coord.async_request_refresh = AsyncMock()

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coord,
    ):
        await websocket_update_sensor_coordinates(hass, mock_connection, msg)

        assert mock_growspace.environment_config.sensor_coordinates["sensor.test"] == {
            "x": 10,
            "y": 20,
            "z": 30,
        }
        mock_connection.send_result.assert_called_with(1)


async def test_websocket_update_sensor_coordinates_errors(
    hass: HomeAssistant, mock_connection
) -> None:
    """Test sensor coordinate update error cases."""
    msg = {
        "id": 1,
        "growspace_id": "gs1",
        "entity_id": "sensor.test",
        "x": 1,
        "y": 1,
        "z": 1,
    }

    mock_coord = MagicMock()

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coord,
    ):
        # 1. Growspace not found (Line 673-676)
        mock_coord.growspaces = {}
        await websocket_update_sensor_coordinates(hass, mock_connection, msg)
        mock_connection.send_error.assert_called_with(
            1, "not_found", "Growspace gs1 not found"
        )

        # 2. No environment config (Line 683-688)
        mock_growspace = MagicMock()
        mock_growspace.environment_config = None
        mock_coord.growspaces = {"gs1": mock_growspace}
        await websocket_update_sensor_coordinates(hass, mock_connection, msg)
        mock_connection.send_error.assert_called_with(
            1, "invalid_state", "Grow space has no environment configuration"
        )

        # 3. ServiceValidationError (Line 711)
        mock_growspace.environment_config = MagicMock()
        with patch.object(
            mock_coord,
            "async_commit",
            side_effect=ServiceValidationError("Validation Fail"),
        ):
            await websocket_update_sensor_coordinates(hass, mock_connection, msg)
            mock_connection.send_error.assert_called_with(
                1, "invalid_args", "Validation Fail"
            )

        # 4. Generic Exception (Line 713-714)
        with patch.object(
            mock_coord, "async_commit", side_effect=Exception("Unexpected")
        ):
            await websocket_update_sensor_coordinates(hass, mock_connection, msg)
        mock_connection.send_error.assert_called_with(1, "unknown_error", "Unexpected")


def test_merge_logbook_event_error() -> None:
    """Test error handling in _merge_logbook_event."""
    # Line 152-153 coverage
    # We need matching severity etc to reach the try block
    formatted_events = [
        {
            "category": "alert",
            "growspace_id": "gs1",
            "sensor_type": "temp",
            "severity": 10.0,
            "start_time": "2023-01-01T12:06:00+00:00",
        }
    ]
    # Trigger TypeError by passing something fromisoformat fails on
    data_dict = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 10.0,
        "start_time": "bad-date",
        "end_time": "bad-date",
    }
    # Should just return False (no merge) and catch the exception inside
    assert _merge_logbook_event(formatted_events, data_dict, None) is False


async def test_get_statistics_data_fallbacks(hass: HomeAssistant) -> None:
    """Test fallback paths in _get_statistics_data."""
    # Line 731: interval < 60
    assert (
        await _get_statistics_data(hass, ["s1"], datetime.now(), datetime.now(), 5)
        is None
    )

    # Line 749: mock missing async_statistics_during_period
    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats:
        if hasattr(mock_stats, "async_statistics_during_period"):
            del mock_stats.async_statistics_during_period
        mock_stats.statistics_during_period.return_value = {
            "s1": [{"start": 1672574400.0, "state": 10}]
        }

        with patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_get_inst:

            async def mock_exec(func, *args):
                return func(*args)

            mock_get_inst.return_value.async_add_executor_job.side_effect = mock_exec

            res = await _get_statistics_data(
                hass, ["s1"], datetime.now(), datetime.now(), 60
            )
            assert res["s1"][0]["s"] == "10"

    # Line 761: empty stats_data
    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats:
        mock_stats.async_statistics_during_period = AsyncMock(return_value={})
        res = await _get_statistics_data(
            hass, ["s1"], datetime.now(), datetime.now(), 60
        )
        assert res is None


async def test_get_history_with_binary_search_downsample_generic_error(
    hass: HomeAssistant,
) -> None:
    """Test generic error in history fetching (Line 863)."""
    # Line 863 is inside _get_history which calls history.get_significant_states
    with (
        patch(
            "custom_components.growspace_manager.websocket.history.get_significant_states",
            side_effect=Exception("Boom history"),
        ),
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_get_inst,
    ):

        async def mock_exec(func, *args):
            return func(*args)

        mock_get_inst.return_value.async_add_executor_job.side_effect = mock_exec

        with pytest.raises(Exception, match="Boom history"):
            await _get_history_with_binary_search_downsample(
                hass, ["s1"], datetime.now(), datetime.now(), 5
            )
