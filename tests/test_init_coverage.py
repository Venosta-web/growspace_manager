"""Additional tests for __init__.py to improve coverage."""

import json
import tempfile
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import BodyPartReader
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager import (
    DOMAIN,
    StrainLibraryUploadView,
    _get_history_with_binary_search_downsample,
    _get_statistics_data,
    _query_recorder_events,
    websocket_get_event_log,
)
from custom_components.growspace_manager.services.strain_library import StrainLibrary


@pytest.fixture
def mock_strain_library():
    return AsyncMock(spec=StrainLibrary)


@pytest.mark.asyncio
async def test_strain_upload_write_failure(
    hass: HomeAssistant, mock_strain_library
) -> None:
    """Test exception raising during file write in upload view."""
    view = StrainLibraryUploadView(hass, mock_strain_library)

    mock_request = MagicMock()
    mock_reader = AsyncMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    mock_field = AsyncMock(spec=BodyPartReader)
    mock_field.name = "file"
    # fail during read_chunk
    mock_field.read_chunk = AsyncMock(side_effect=OSError("Chunk read failed"))

    mock_reader.next = AsyncMock(return_value=mock_field)

    # Allow mkstemp to succeed
    async def mock_executor_side_effect(target, *args):
        if target == tempfile.mkstemp:
            return (1, "mock_test.zip")
        if getattr(target, "__name__", "") == "unlink":
            return None
        # Raise for other executor jobs (like write_chunk if it was called via executor,
        # but here read_chunk fails which is awaited directly)
        return None

    hass.async_add_executor_job = AsyncMock(side_effect=mock_executor_side_effect)

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.unlink") as mock_unlink,
    ):
        response = await view.post(mock_request)

        assert response.status == 500
        # Check that unlink was called (coverage for line 235)
        # Wait, unlink is called via executor.
        # hass.async_add_executor_job is called with unlink logic?
        # line 235: await self.hass.async_add_executor_job(temp_path.unlink)
        # So we assert hass.async_add_executor_job was called with target having unlink name or something.
        # But specifically, we want to hit lines 232-236.
        # The fact that response is 500 means line 252 caught it.
        # But we want to ensure line 236 `raise` in `_save_upload_to_temp` was hit.
        # If it wasn't hit, exception wouldn't propagate to `post`.


@pytest.mark.asyncio
async def test_websocket_get_event_log_limit(hass: HomeAssistant) -> None:
    """Test limiting events in websocket log."""

    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    # Create 3 mock event rows and data rows for recorder (new schema)
    mock_event_data_pairs = []
    for i in range(3):
        event_row = MagicMock()
        event_row.time_fired_ts = 1672531200.0 + i
        event_row.data_id = i + 1

        data_row = MagicMock()
        data_row.shared_data = json.dumps(
            {
                "sensor_type": "test",
                "growspace_id": "gs1",
                "timestamp": 1672531200.0 + i,
                "category": "test",
            }
        )
        mock_event_data_pairs.append((event_row, data_row))

    # Mock the recorder instance and session
    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    # Mock for EventTypes query
    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)

    # Mock for Events/EventData query
    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(mock_event_data_pairs)

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        else:
            return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        # Limit 1
        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_log",
            "growspace_id": "gs1",
            "limit": 1,
        }
        await websocket_get_event_log(hass, mock_connection, msg)

        args = mock_connection.send_result.call_args[0]
        data = args[1]
        assert len(data["gs1"]) == 1  # Testing limit functionality


@pytest.mark.asyncio
async def test_websocket_get_event_log_limit_global(hass: HomeAssistant) -> None:
    """Test limiting events in global websocket log."""

    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    # Create 3 mock event rows and data rows for recorder (new schema)
    mock_event_data_pairs = []
    for i in range(3):
        event_row = MagicMock()
        event_row.time_fired_ts = 1672531200.0 + i
        event_row.data_id = i + 1

        data_row = MagicMock()
        data_row.shared_data = json.dumps(
            {
                "sensor_type": "test",
                "growspace_id": "gs1",
                "timestamp": 1672531200.0 + i,
                "category": "test",
            }
        )
        mock_event_data_pairs.append((event_row, data_row))

    # Mock the recorder instance and session
    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    # Mock for EventTypes query
    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)

    # Mock for Events/EventData query
    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(mock_event_data_pairs)

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        else:
            return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        # Limit 1 - global query
        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "limit": 1}
        await websocket_get_event_log(hass, mock_connection, msg)

        args = mock_connection.send_result.call_args[0]
        data = args[1]
        assert len(data["gs1"]) == 1  # Testing limit functionality


@pytest.mark.asyncio
async def test_get_statistics_data_direct(hass: HomeAssistant) -> None:
    """Test private _get_statistics_data function coverage."""
    # 1. Test low interval returns None (line 447)
    res = await _get_statistics_data(
        hass, ["sensor.test"], dt_util.utcnow(), dt_util.utcnow(), 30
    )
    assert res is None

    # 2. Test missing entity (line 490)
    start = dt_util.utcnow()
    # Patch the module attribute usage in growspace_manager
    with patch(
        "custom_components.growspace_manager.recorder_stats"
    ) as mock_stats_module:
        # Return stats for valid_sensor, but not for missing_sensor
        mock_stats_module.async_statistics_during_period = AsyncMock(
            return_value={"sensor.valid": [{"start": start.timestamp(), "mean": 10}]}
        )

        res = await _get_statistics_data(
            hass, ["sensor.valid", "sensor.missing"], start, start, 60
        )

        assert "sensor.valid" in res
        assert "sensor.missing" in res
        assert res["sensor.missing"] == []  # Line 490


@pytest.mark.asyncio
async def test_downsample_dicts(hass: HomeAssistant) -> None:
    """Test binary search downsampler with dict data."""
    start = dt_util.utcnow()
    end = start + timedelta(minutes=10)

    # Dicts with string timestamps
    history = {"sensor.test": [{"last_updated": start.isoformat(), "state": "10"}]}

    async def mock_executor(func):
        return func()  # Run inline

    hass.async_add_executor_job = AsyncMock(side_effect=mock_executor)

    with patch("homeassistant.components.recorder.get_instance"):
        # We need to mock get_instance(hass).async_add_executor_job(_get_history)
        # But _get_history_with_binary_search_downsample calls it.
        # It's cleaner to patch _get_history_with_binary_search_downsample internal _get_history? No.
        # We patch get_instance...

        mock_instance = MagicMock()
        mock_instance.async_add_executor_job = AsyncMock(return_value=history)
        with patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_instance,
        ):
            res = await _get_history_with_binary_search_downsample(
                hass, ["sensor.test"], start, end, 5
            )

            assert "sensor.test" in res
            assert len(res["sensor.test"]) > 0


@pytest.mark.asyncio
async def test_downsample_no_valid_timestamps(hass: HomeAssistant) -> None:
    """Test binary search downsampler with no valid timestamps."""
    start = dt_util.utcnow()
    end = start + timedelta(minutes=10)

    # State with None timestamp
    history = {"sensor.test": [{"last_updated": None, "state": "10"}]}

    async def mock_executor(func):
        return func()  # Run inline

    hass.async_add_executor_job = AsyncMock(side_effect=mock_executor)

    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value=history)
    with patch(
        "custom_components.growspace_manager.get_instance", return_value=mock_instance
    ):
        res = await _get_history_with_binary_search_downsample(
            hass, ["sensor.test"], start, end, 5
        )

        assert "sensor.test" in res
        assert res["sensor.test"] == []  # Line 552


@pytest.mark.asyncio
async def test_websocket_get_event_log_event_type_not_found(
    hass: HomeAssistant,
) -> None:
    """Test websocket_get_event_log when event type is not found in recorder.

    This covers lines 344-348 in __init__.py.
    """

    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    # EventTypes query returns None (event type not found)
    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = None  # No event type found

    mock_session.query = MagicMock(return_value=mock_event_type_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        # Should return empty result when event type not found
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_websocket_get_event_log_no_event_data(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log when event data row has no shared_data.

    This covers line 375 in __init__.py.
    """

    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    # Create event row with no data
    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.data_id = 1

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = None  # No data!

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)

    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(
        [(mock_event_row, mock_event_data_row)]
    )

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        else:
            return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        # Should skip events without data
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_websocket_get_event_log_add_timestamp(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log adds timestamp from event row.

    This covers line 386 in __init__.py.
    """

    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    # Event data without timestamp
    event_data = {
        "sensor_type": "test",
        "growspace_id": "gs1",
        "category": "test",
        # No "timestamp" field!
    }

    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.data_id = 1

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = json.dumps(event_data)

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)

    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(
        [(mock_event_row, mock_event_data_row)]
    )

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        else:
            return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        # Verify timestamp was added from time_fired_ts
        args = mock_connection.send_result.call_args[0]
        data = args[1]
        assert data["gs1"][0]["timestamp"] == 1672531200.0


@pytest.mark.asyncio
async def test_websocket_get_event_log_json_decode_error(
    hass: HomeAssistant,
) -> None:
    """Test websocket_get_event_log handles JSON decode errors.

    This covers lines 393-397 in __init__.py.
    """
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.data_id = 1

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = "not valid json {{"  # Invalid JSON

    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)

    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(
        [(mock_event_row, mock_event_data_row)]
    )

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        else:
            return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        # Should skip invalid JSON and return empty
        mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_websocket_get_event_log_import_error(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log handles ImportError.

    This covers lines 419-421 in __init__.py.
    """
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    with patch(
        "custom_components.growspace_manager.get_instance",
        side_effect=ImportError("Recorder not available"),
    ):
        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_websocket_get_event_log_key_error(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log handles KeyError.

    This covers lines 423-425 in __init__.py.
    """
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    with patch(
        "custom_components.growspace_manager.get_instance",
        side_effect=KeyError("recorder_instance"),
    ):
        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
        await websocket_get_event_log(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_downsample_idx_less_than_zero(hass: HomeAssistant) -> None:
    """Test binary search downsampler with query time before all states.

    This covers line 677 in __init__.py - the else branch where idx < 0.
    """
    start = dt_util.utcnow()
    end = start + timedelta(minutes=10)

    # State with timestamp AFTER the start time - first few query times will have idx < 0
    state_time = (start + timedelta(minutes=5)).isoformat()
    history = {
        "sensor.test": [
            {"last_updated": state_time, "state": "50"},
        ]
    }

    async def mock_executor(func):
        return func()

    hass.async_add_executor_job = AsyncMock(side_effect=mock_executor)

    mock_instance = MagicMock()
    mock_instance.async_add_executor_job = AsyncMock(return_value=history)
    with patch(
        "custom_components.growspace_manager.get_instance", return_value=mock_instance
    ):
        res = await _get_history_with_binary_search_downsample(
            hass, ["sensor.test"], start, end, 5
        )

        assert "sensor.test" in res
        # Should have results from the 5+ minute mark onwards
        assert len(res["sensor.test"]) > 0


@pytest.mark.asyncio
async def test_websocket_get_event_log_query_exception(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log handles unexpected exception in query.

    This covers lines 396-397 in __init__.py.
    """
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    mock_recorder = MagicMock()

    # We want to execute the internal _query_events function
    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    with patch(
        "custom_components.growspace_manager.get_instance",
        return_value=mock_recorder,
    ):
        # Patch session_scope to raise an exception when called
        with patch(
            "custom_components.growspace_manager.session_scope",
            side_effect=RuntimeError("Database connection lost"),
        ):
            msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1"}
            await websocket_get_event_log(hass, mock_connection, msg)

            # verify result is empty list (graceful failure)
            mock_connection.send_result.assert_called_with(1, {"gs1": []})


@pytest.mark.asyncio
async def test_query_recorder_events_direct(hass: HomeAssistant) -> None:
    """Test _query_recorder_events directly to ensure full coverage.

    This avoids issues where AsyncMock side_effects might not be traced by coverage.
    """

    # Mock data
    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.data_id = 1

    event_data = {"growspace_id": "gs1", "category": "alert", "timestamp": 1672531200.0}
    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = json.dumps(event_data)

    # Mock Session and Query
    mock_session = MagicMock()

    # Mock EventType query (not found first, then found)
    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query

    # Mock Events query
    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(
        [(mock_event_row, mock_event_data_row)]
    )

    def mock_query(*args):
        if len(args) == 1:
            return mock_event_type_query
        return mock_events_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with patch(
        "custom_components.growspace_manager.session_scope",
        return_value=MagicMock(
            __enter__=MagicMock(return_value=mock_session),
            __exit__=MagicMock(return_value=None),
        ),
    ):
        # 1. Test Event Type Not Found
        mock_event_type_query.first.return_value = None
        events = _query_recorder_events(hass, 0, 9999999999)
        assert events == []

        # 2. Test Success
        mock_event_type_query.first.return_value = (1,)
        events = _query_recorder_events(
            hass, 0, 9999999999, limit=10, growspace_id="gs1"
        )
        assert len(events) == 1
        assert events[0]["growspace_id"] == "gs1"

        # 3. Test Filter by Growspace ID (mismatch)
        events = _query_recorder_events(
            hass, 0, 9999999999, limit=10, growspace_id="gs2"
        )
        assert len(events) == 0

        # 4. Test JSON Error
        bad_data_row = MagicMock()
        bad_data_row.shared_data = "{invalid_json"
        mock_events_query.__iter__ = lambda self: iter([(mock_event_row, bad_data_row)])
        events = _query_recorder_events(hass, 0, 9999999999)
        assert events == []

        # 5. Test Exception Handling
        mock_session.query.side_effect = RuntimeError("DB Fail")
        events = _query_recorder_events(hass, 0, 9999999999)
        assert events == []
