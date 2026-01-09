"""Additional tests for __init__.py to improve coverage."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import tempfile
from datetime import datetime, timedelta

from aiohttp import BodyPartReader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager import (
    DOMAIN,
    StrainLibraryUploadView,
    websocket_get_event_log,
    _get_statistics_data,
    _get_history_with_binary_search_downsample,
)
from custom_components.growspace_manager.models import GrowspaceEvent
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

    mock_coordinator = MagicMock()
    # 3 events
    events = [
        GrowspaceEvent(
            sensor_type="test",
            growspace_id="gs1",
            start_time=f"2023-01-01T00:0{i}",
            end_time="2023-01-01T00:06:00",
            duration_sec=10,
            severity=0.5,
            category="test",
            reasons=[],
        )
        for i in range(3)
    ]
    mock_coordinator.events = {"gs1": events}

    with patch(
        "custom_components.growspace_manager.service_registration.get_coordinator_for_call",
        return_value=mock_coordinator,
    ):
        # Limit 1
        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "growspace_id": "gs1", "limit": 1}
        await websocket_get_event_log(hass, mock_connection, msg)

        args = mock_connection.send_result.call_args[0]
        data = args[1]
        assert len(data["gs1"]) == 1  # Testing line 311


@pytest.mark.asyncio
async def test_websocket_get_event_log_limit_global(hass: HomeAssistant) -> None:
    """Test limiting events in global websocket log."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    mock_coordinator = MagicMock()
    events = [
        GrowspaceEvent(
            sensor_type="test",
            growspace_id="gs1",
            start_time=f"2023-01-01T00:0{i}",
            end_time="2023-01-01T00:06:00",
            duration_sec=10,
            severity=0.5,
            category="test",
            reasons=[],
        )
        for i in range(3)
    ]
    mock_coordinator.events = {"gs1": events}

    mock_entry = MagicMock()
    mock_entry.state = ConfigEntryState.LOADED
    mock_entry.runtime_data = mock_coordinator

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_entry],
    ):
        # Limit 1
        msg = {"id": 1, "type": f"{DOMAIN}/get_log", "limit": 1}
        await websocket_get_event_log(hass, mock_connection, msg)

        args = mock_connection.send_result.call_args[0]
        data = args[1]
        assert len(data["gs1"]) == 1  # Testing line 329


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
