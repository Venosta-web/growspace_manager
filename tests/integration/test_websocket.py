"""Test the Growspace Manager WebSocket API."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.websocket import (
    _EPOCH_SENTINEL,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    WS_TYPE_ADD_TIMELINE_NOTE,
    WS_TYPE_GET_ALERTS,
    WS_TYPE_GET_DATA,
    WS_TYPE_GET_HISTORY_STATS,
    WS_TYPE_GET_IPM_PRESETS,
    WS_TYPE_GET_LOG,
    WS_TYPE_GET_NUTRIENT_INVENTORY,
    WS_TYPE_GET_NUTRIENT_PRESETS,
    WS_TYPE_GET_STRAIN_LIBRARY,
    WS_TYPE_REMOVE_NUTRIENT_STOCK,
    WS_TYPE_REMOVE_TIMELINE_EVENT,
    WS_TYPE_UPDATE_NUTRIENT_STOCK,
    _extract_ts,
    _merge_logbook_event,
    async_register_websocket_api,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from tests.common import MockConfigEntry

WebSocketGenerator = Any


@pytest.fixture
def mock_strain_library():
    """Mock strain library."""
    lib = MagicMock(spec=StrainLibrary)
    lib.get_all.return_value = {
        "Strain A": {"meta": {"type": "Sativa", "breeder": "Breeder A"}},
        "Strain B": {"meta": {"type": "Indica"}},
    }
    return lib


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coord = MagicMock()
    # Correctly mock services.get_growspace_data to return serializable data
    coord.services = MagicMock()
    coord.services.get_growspace_data.return_value = {"id": "gs1", "name": "Growspace 1"}

    # WebSocket handlers await these service calls
    coord.services.add_timeline_note = AsyncMock()
    coord.services.add_subarea = AsyncMock()
    coord.services.update_subarea = AsyncMock()
    coord.services.remove_subarea = AsyncMock()

    # Coordinator level awaitables
    coord.async_commit = AsyncMock()
    coord.async_request_refresh = AsyncMock()

    return coord


async def test_websocket_get_strain_library(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_strain_library
) -> None:
    """Test getting strain library via WebSocket."""
    # Setup mock entry and coordinator to replace legacy direct hass.data access
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, options={}, state=ConfigEntryState.LOADED
    )
    entry.add_to_hass(hass)

    mock_coord = MagicMock()
    mock_coord.strain_library = mock_strain_library
    entry.runtime_data = mock_coord

    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_GET_STRAIN_LIBRARY,
        }
    )

    response = await client.receive_json()
    assert response["success"]
    assert len(response["result"]["strains"]) == 2
    assert "Strain A" in response["result"]["strain_list"]


async def test_websocket_get_strain_library_not_loaded(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting strain library when not loaded."""
    # Ensure no config entries exist for DOMAIN
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_remove(entry.entry_id)

    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_GET_STRAIN_LIBRARY,
        }
    )

    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "not_loaded"


async def test_websocket_get_growspace_data(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
) -> None:
    """Test getting growspace data."""
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_DATA, "growspace_id": "gs1"}
        )

        response = await client.receive_json()
        assert response["success"]
        assert response["result"]["id"] == "gs1"


async def test_websocket_get_growspace_data_error(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting growspace data with error."""
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("Coordinator Error"),
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_GET_DATA,
            }
        )

        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "unknown_error"


async def test_websocket_get_event_log(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting event log."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    # Mock recorder query
    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        mock_instance = MagicMock()
        mock_recorder.return_value = mock_instance

        # Test empty result first
        # async_add_executor_job must return an awaitable
        async def mock_executor(*args, **kwargs):
            return []

        mock_instance.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )

        response = await client.receive_json()
        assert response["success"]
        assert response["result"] == {"gs1": []}


async def test_websocket_get_alerts(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting alerts."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock DB results
        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        mock_event = MagicMock()
        mock_event.time_fired_ts = 1672574400.0
        mock_event.event_id = 100

        # An alert event
        mock_data = MagicMock()
        mock_data.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "stress",
                "sensor_type": "vpd",
                "severity": 10.0,
                "start_time": "2023-01-01T12:00:00+00:00",
                "end_time": "2023-01-01T12:05:00+00:00",
            }
        )

        q_mock = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value
        q_mock.limit.return_value = [(mock_event, mock_data)]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_ALERTS, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        assert len(response["result"]["gs1"]) == 1
        assert response["result"]["gs1"][0]["category"] == "stress"


async def test_websocket_get_log_filters_spam(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test get_log filters out spam categories."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock DB results with a SPAM event
        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        mock_event = MagicMock()
        mock_event.time_fired_ts = 1672574400.0
        mock_event.event_id = 100

        mock_data = MagicMock()
        mock_data.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "optimal",  # This is a SPAM category
                "sensor_type": "vpd",
                "severity": 10.0,
                "start_time": "2023-01-01T12:00:00+00:00",
                "end_time": "2023-01-01T12:05:00+00:00",
            }
        )

        q_mock = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value
        q_mock.limit.return_value = [(mock_event, mock_data)]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        # Should be filtered out
        assert len(response["result"]["gs1"]) == 0


async def test_websocket_get_history_stats(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting history stats."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    start_time = datetime.now() - timedelta(hours=2)

    # Test fallback to binary search (short interval)
    with patch(
        "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
        return_value={"sensor.test": [{"s": "10", "lu": "time"}]},
    ):
        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": start_time.isoformat(),
                "interval_minutes": 5,
            }
        )

        response = await client.receive_json()
        assert response["success"]
        assert "sensor.test" in response["result"]

    # Test statistics API (long interval)
    with patch(
        "custom_components.growspace_manager.websocket._get_statistics_data",
        return_value={"sensor.test": [{"s": "10", "lu": "time"}]},
    ):
        await client.send_json(
            {
                "id": 2,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": start_time.isoformat(),
                "interval_minutes": 60,
            }
        )

        response = await client.receive_json()
        assert response["success"]
        assert "sensor.test" in response["result"]


# Add more specific tests for _merge_logbook_event logic if needed


def test_extract_ts() -> None:
    """Test timestamp extraction."""
    # Test valid datetime object
    dt = datetime.now()
    state_obj = MagicMock()
    state_obj.last_updated = dt
    assert _extract_ts(state_obj) == dt

    # Test dict with last_updated
    data = {"last_updated": "2023-01-01T12:00:00+00:00"}
    expected = datetime.fromisoformat(data["last_updated"])
    assert _extract_ts(data) == expected

    # Test dict with last_changed fallback
    data = {"last_changed": "2023-01-01T12:00:00+00:00"}
    expected = datetime.fromisoformat(data["last_changed"])
    assert _extract_ts(data) == expected

    # Test None
    state_obj.last_updated = None
    assert _extract_ts(state_obj) == _EPOCH_SENTINEL

    # Test empty dict
    assert _extract_ts({}) == _EPOCH_SENTINEL


def test_merge_logbook_event() -> None:
    """Test logbook event merging."""
    events = []

    # To match code logic (DESC order), formatted list has NEWER events.
    # We try to merge an OLDER event into the latest (newest) formatted event.

    # Setup: Add NEWER event first
    newer_evt = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 10.0,
        "start_time": "2023-01-01T12:06:00+00:00",
        "end_time": "2023-01-01T12:10:00+00:00",
        "duration_sec": 240,
        "reasons": ["high temp"],
    }
    events.append(newer_evt)

    # Try to merge OLDER event
    older_evt = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 10.0,
        "start_time": "2023-01-01T12:00:00+00:00",
        "end_time": "2023-01-01T12:05:00+00:00",
        "duration_sec": 300,
        "reasons": ["high temp"],
    }

    # Should merge
    assert _merge_logbook_event(events, older_evt, None)
    assert len(events) == 1
    # start_time should be updated to older event's start time (earliest time)
    # The code: last_evt["start_time"] = data_dict["start_time"]
    assert events[0]["start_time"] == older_evt["start_time"]
    assert events[0]["duration_sec"] == 540

    # Dissimilar event (different severity)
    evt3 = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 5.0,
        "start_time": "2023-01-01T12:15:00+00:00",
        "end_time": "2023-01-01T12:20:00+00:00",
    }
    assert not _merge_logbook_event(events, evt3, None)


@dataclass
class MockPreset:
    name: str


async def test_websocket_get_presets(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
) -> None:
    """Test getting nutrient and IPM presets."""
    hass.data[DOMAIN] = {"coordinator": mock_coordinator}
    nutrient_presets_data = {"p1": {"name": "Nutrient Preset"}}
    ipm_presets_data = {"i1": {"name": "IPM Preset"}}

    mock_coordinator.nutrient_manager.get_serialization_data.return_value = {
        "nutrient_presets": nutrient_presets_data,
        "ipm_presets": ipm_presets_data,
    }

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        # Nutrient presets
        await client.send_json({"id": 1, "type": WS_TYPE_GET_NUTRIENT_PRESETS})
        response = await client.receive_json()
        assert response["success"]
        assert "p1" in response["result"]

        # IPM presets
        await client.send_json({"id": 2, "type": WS_TYPE_GET_IPM_PRESETS})
        response = await client.receive_json()
        assert response["success"]
        assert "i1" in response["result"]


async def test_websocket_timeline_notes(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
) -> None:
    """Test adding/removing timeline notes."""
    hass.data[DOMAIN] = {"coordinator": mock_coordinator, "strain_library": MagicMock()}

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            return_value=mock_coordinator,
        ),
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_ADD_TIMELINE_NOTE,
                ATTR_PLANT_ID: "plant1",
                ATTR_NOTES: "test note",
            }
        )
        response = await client.receive_json()
        assert response["success"]
        mock_coordinator.services.add_timeline_note.assert_called_once()


async def test_websocket_remove_timeline_event(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test removing timeline event."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        # Make session_scope be a context manager that yields mock_session
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock async_add_executor_job to return a coroutine
        async def mock_executor(*args, **kwargs):
            if args and callable(args[0]):
                args[0]()  # Execute the callback

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_REMOVE_TIMELINE_EVENT, "event_id": 123}
        )
        response = await client.receive_json()
        assert response["success"]
        mock_session.query.assert_called_once()


async def test_websocket_get_event_log_internals(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting event log internals (query logic)."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock DB results
        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        # Create mock rows: (Events, EventData)
        mock_event = MagicMock()
        mock_event.time_fired_ts = 1672574400.0  # 2023-01-01 12:00:00 UTC
        mock_event.event_id = 100

        mock_data = MagicMock()
        mock_data.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "normal",
                "sensor_type": "temp",
                "severity": 5.0,
                "start_time": "2023-01-01T12:00:00+00:00",
                "end_time": "2023-01-01T12:05:00+00:00",
            }
        )

        # Mock query chain - now includes additional .filter() calls for spam exclusion
        q_base = mock_session.query.return_value.join.return_value.filter.return_value
        # The new code adds .filter() calls in a loop for spam categories
        # We need to make filter() return itself to allow chaining
        q_base.filter.return_value = q_base
        q_mock = q_base.order_by.return_value
        q_mock.limit.return_value = [(mock_event, mock_data)]

        # Execute the inner function synchronously via side_effect
        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        assert len(response["result"]["gs1"]) == 1
        assert response["result"]["gs1"][0]["event_id"] == 100


async def test_websocket_get_history_stats_long_interval(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats with long interval (>= 60 mins)."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats_module:

        async def mock_async_stats(*args, **kwargs):
            return {
                "sensor.test": [
                    {"start": 1672574400.0, "mean": 20.5, "state": 20.0},
                    {
                        "start": 1672578000.0,
                        "mean": 0.0,
                        "state": 0.0,
                    },  # Test mean=0 case
                ]
            }

        mock_stats_module.statistics_during_period.side_effect = mock_async_stats
        mock_stats_module.async_statistics_during_period.side_effect = mock_async_stats

        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": "2023-01-01T00:00:00+00:00",
                "end_time": "2023-01-02T00:00:00+00:00",
                "interval_minutes": 60,
            }
        )
        response = await client.receive_json()
        assert response["success"]
        result = response["result"]
        assert "sensor.test" in result
        assert len(result["sensor.test"]) == 2
        assert result["sensor.test"][0]["s"] == "20.5"
        assert result["sensor.test"][1]["s"] == "0.0"


async def test_websocket_get_history_stats_day_interval(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats with day interval (>= 1440 mins)."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats_module:

        async def mock_async_stats(*args, **kwargs):
            return {"sensor.test": [{"start": 1672574400.0, "mean": 10.0}]}

        mock_stats_module.statistics_during_period.side_effect = mock_async_stats
        mock_stats_module.async_statistics_during_period.side_effect = mock_async_stats

        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": "2023-01-01T00:00:00+00:00",
                "end_time": "2023-01-02T00:00:00+00:00",
                "interval_minutes": 1440,
            }
        )
        response = await client.receive_json()
        assert response["success"]
        # Verify call to statistics_during_period used "day" period
        assert mock_stats_module.async_statistics_during_period.call_args[0][4] == "day"


async def test_websocket_get_history_stats_fallback(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats falling back to binary search when stats API fails."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.recorder_stats"
        ) as mock_stats_module,
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
    ):
        # Stats API raises exception
        async def mock_fail(*args, **kwargs):
            raise ValueError("Stats API broken")

        mock_stats_module.statistics_during_period.side_effect = mock_fail
        mock_stats_module.async_statistics_during_period.side_effect = mock_fail

        # History Mock
        async def mock_history_executor(func, *args, **kwargs):
            if func.__name__ == "_get_history":
                state = MagicMock()
                state.state = "50"
                state.last_updated = datetime.fromisoformat("2023-01-01T12:00:00+00:00")
                return {"sensor.test": [state]}
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = (
            mock_history_executor
        )

        with patch("homeassistant.components.recorder.history.get_significant_states"):
            await client.send_json(
                {
                    "id": 1,
                    "type": WS_TYPE_GET_HISTORY_STATS,
                    "entity_ids": ["sensor.test"],
                    "start_time": "2023-01-01T00:00:00+00:00",
                    "interval_minutes": 60,
                }
            )
            response = await client.receive_json()
            assert response["success"]
            # Should have fallen back and got history result
            assert len(response["result"]["sensor.test"]) > 0
            assert response["result"]["sensor.test"][0]["s"] == "50"


async def test_websocket_get_event_log_no_growspace_id(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting event log without specifying growspace_id."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:

        async def mock_executor(func, *args, **kwargs):
            # Mock the return of _query_events directly as a list of dicts
            return [
                {"growspace_id": "gs1", "event_id": 1},
                {"growspace_id": "gs2", "event_id": 2},
            ]

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {
                "id": 1,
                "type": WS_TYPE_GET_LOG,
                # No growspace_id
            }
        )
        response = await client.receive_json()
        assert response["success"]
        res = response["result"]
        # Expected format: { "gs1": [...], "gs2": [...] }
        assert "gs1" in res
        assert "gs2" in res
        assert len(res["gs1"]) == 1
        assert len(res["gs2"]) == 1


async def test_websocket_get_history_stats_short_interval(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats with short interval (< 60 mins) and downsampling."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        # Mock history data extraction
        state1 = MagicMock()
        state1.last_updated = datetime.fromisoformat("2023-01-01T12:00:00+00:00")
        state1.state = "10"

        state2 = MagicMock()
        state2.last_updated = datetime.fromisoformat("2023-01-01T12:04:00+00:00")
        state2.state = "11"

        # Binary search executor replacement
        async def mock_executor(func, *args, **kwargs):
            if func.__name__ == "_get_history":
                return {"sensor.test": [state1, state2]}
            return func()  # Run downsampler

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        with patch("homeassistant.components.recorder.history.get_significant_states"):
            await client.send_json(
                {
                    "id": 1,
                    "type": WS_TYPE_GET_HISTORY_STATS,
                    "entity_ids": ["sensor.test"],
                    "start_time": "2023-01-01T12:00:00+00:00",
                    "end_time": "2023-01-01T13:00:00+00:00",
                    "interval_minutes": 5,
                }
            )
            response = await client.receive_json()
            assert response["success"]
            result = response["result"]
            assert "sensor.test" in result
            # Downsampling logic:
            # 12:00 -> state1 (10)
            # 12:05 -> state2 (11) (closest previous state at 12:04)
            # ...
            assert len(result["sensor.test"]) > 0
            assert result["sensor.test"][0]["s"] == "10"


async def test_websocket_get_growspace_data_validation_error(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting growspace data with validation error."""

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("Invalid ID"),
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_DATA, "growspace_id": "invalid"}
        )

        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "not_loaded"


async def test_websocket_get_vision_history_validation_error(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test getting vision history with validation error (not loaded)."""

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("Integration not loaded"),
    ):
        async_register_websocket_api(hass)
        client = await hass_ws_client(hass)

        await client.send_json(
            {
                "id": 1,
                "type": "growspace_manager/get_vision_history",
                "growspace_id": "tent1",
            }
        )

        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "not_loaded"


async def test_websocket_get_event_log_internals_no_type(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test event log query when event type is missing."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock DB results: No event type found
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Execute synchronously
        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json({"id": 1, "type": WS_TYPE_GET_LOG})
        response = await client.receive_json()
        assert response["success"]
        assert response["result"] == {}  # Empty result


async def test_websocket_get_event_log_bad_date_merge(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test event log merge with bad date data (triggers exception in merge)."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        # Create 2 events that look consecutive but have bad dates
        evt1 = MagicMock(time_fired_ts=1000, event_id=1)
        data1 = MagicMock(
            shared_data=json.dumps(
                {
                    "growspace_id": "gs1",
                    "category": "user_action",  # Changed from "alert" to avoid SQL filtering
                    "sensor_type": "temp",
                    "severity": 5,
                    "start_time": "BAD-DATE",
                    "end_time": "BAD-DATE",
                }
            )
        )

        evt2 = MagicMock(time_fired_ts=900, event_id=2)
        data2 = MagicMock(
            shared_data=json.dumps(
                {
                    "growspace_id": "gs1",
                    "category": "user_action",  # Changed from "alert" to avoid SQL filtering
                    "sensor_type": "temp",
                    "severity": 5,
                    "start_time": "BAD-DATE",
                    "end_time": "BAD-DATE",
                }
            )
        )

        # Mock query chain - account for SQL filtering
        q_base = mock_session.query.return_value.join.return_value.filter.return_value
        q_base.filter.return_value = q_base
        q_mock = q_base.order_by.return_value
        q_mock.limit.return_value = [(evt1, data1), (evt2, data2)]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        # Should return both events because merge failed silently
        assert len(response["result"]["gs1"]) == 2


async def test_websocket_get_history_stats_fallback_empty(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats fallback with empty history."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        # History Mock returns empty list for entity
        async def mock_history_executor(func, *args, **kwargs):
            if func.__name__ == "_get_history":
                return {"sensor.test": []}
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = (
            mock_history_executor
        )

        with patch("homeassistant.components.recorder.history.get_significant_states"):
            await client.send_json(
                {
                    "id": 1,
                    "type": WS_TYPE_GET_HISTORY_STATS,
                    "entity_ids": ["sensor.test"],
                    "start_time": "2023-01-01T00:00:00+00:00",
                    "interval_minutes": 5,
                }
            )
            response = await client.receive_json()
            assert response["success"]
            assert response["result"] == {"sensor.test": []}


async def test_websocket_get_event_log_filtering(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test event log filtering (triggers continue statements)."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        # 1. Row with missing shared_data
        evt1 = MagicMock(time_fired_ts=1000, event_id=1)
        data1 = MagicMock(shared_data=None)

        # 2. Row with different growspace_id
        evt2 = MagicMock(time_fired_ts=900, event_id=2)
        data2 = MagicMock(
            shared_data=json.dumps({"growspace_id": "other_gs", "category": "normal"})
        )

        # 3. Valid Row
        evt3 = MagicMock(time_fired_ts=800, event_id=3)
        data3 = MagicMock(
            shared_data=json.dumps({"growspace_id": "gs1", "category": "normal"})
        )

        # Mock query chain - account for SQL filtering
        q_base = mock_session.query.return_value.join.return_value.filter.return_value
        q_base.filter.return_value = q_base
        q_mock = q_base.order_by.return_value
        q_mock.limit.return_value = [(evt1, data1), (evt2, data2), (evt3, data3)]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        # Only evt3 should remain
        assert len(response["result"]["gs1"]) == 1
        assert response["result"]["gs1"][0]["event_id"] == 3


async def test_websocket_get_history_stats_sentinel(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats sentinel filtering."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        # State with None last_updated (triggers sentinel)
        state1 = MagicMock()
        state1.last_updated = None
        state1.state = "10"

        # Valid state
        state2 = MagicMock()
        state2.last_updated = datetime.fromisoformat("2023-01-01T12:04:00+00:00")
        state2.state = "11"

        async def mock_executor(func, *args, **kwargs):
            if func.__name__ == "_get_history":
                return {"sensor.test": [state1, state2]}
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        with patch("homeassistant.components.recorder.history.get_significant_states"):
            await client.send_json(
                {
                    "id": 1,
                    "type": WS_TYPE_GET_HISTORY_STATS,
                    "entity_ids": ["sensor.test"],
                    "start_time": "2023-01-01T12:00:00+00:00",
                    "end_time": "2023-01-01T13:00:00+00:00",
                    "interval_minutes": 5,
                }
            )
            response = await client.receive_json()
        assert response["success"]
        # state1 should be skipped (at 12:00)
        # 12:00 skipped. 12:05 to 13:00 (inclusive) = 12 points
        assert len(response["result"]["sensor.test"]) == 12
        assert response["result"]["sensor.test"][0]["lu"] == "2023-01-01T12:05:00+00:00"
        assert response["result"]["sensor.test"][0]["s"] == "11"


async def test_websocket_get_event_log_limits(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test event log limits and json errors."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        # With SQL-level filtering, spam events don't reach Python
        # Test that we correctly return limited results and handle bad JSON
        events = []

        # 50 Normal events
        events.extend(
            [
                (
                    MagicMock(time_fired_ts=3000 + i, event_id=i),
                    MagicMock(
                        shared_data=json.dumps(
                            {"growspace_id": "gs1", "category": "normal"}
                        )
                    ),
                )
                for i in range(55)
            ]
        )

        # 210 Spammy events
        # SQL filtering excludes spam events at DB level

        # Add a bad JSON one
        events.append(
            (
                MagicMock(time_fired_ts=5000, event_id=9999),
                MagicMock(shared_data="{bad_json"),
            )
        )

        # Sort desc by timestamp
        events.sort(key=lambda x: x[0].time_fired_ts, reverse=True)

        async def mock_executor(func, *args, **kwargs):
            # Mock the internal query manually
            with patch(
                "custom_components.growspace_manager.websocket.session_scope"
            ) as mock_scope:
                mock_session = MagicMock()
                mock_scope.return_value.__enter__.return_value = mock_session

                # Chain: query.join.filter.order_by -> then .limit()
                # If limit IS provided:
                q_base = mock_session.query.return_value.join.return_value.filter.return_value
                q_base.filter.return_value = q_base
                q_mock = q_base.order_by.return_value
                q_mock.limit.return_value = events
                q_mock.__iter__.return_value = events

                return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1", "limit": 50}
        )
        response = await client.receive_json()
        assert response["success"]
        # Limit (50). Spam events are now filtered out entirely by get_log.
        # We provided >50 normal and >200 spammy.
        # It should return 50 normal events.
        assert len(response["result"]["gs1"]) == 50


async def test_websocket_nutrient_inventory_service_not_ready(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, mock_coordinator
) -> None:
    """Test nutrient inventory when service is not initialized."""
    # Remove service from coordinator to simulate not initialized
    # Use explicit deletion if the property is set, or set to None
    mock_coordinator.nutrient_inventory_service = None

    hass.data[DOMAIN] = {"coordinator": mock_coordinator}
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    # We must patch get_any to return our modified mock_coordinator
    # otherwise it tries to run real logic and fails validation
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coordinator,
    ):
        # 1. Get Inventory - returns empty
        await client.send_json({"id": 1, "type": WS_TYPE_GET_NUTRIENT_INVENTORY})
        response = await client.receive_json()
        assert response["success"]
        assert response["result"]["stocks"] == {}

        # 2. Update Stock - returns error
        await client.send_json(
            {
                "id": 2,
                "type": WS_TYPE_UPDATE_NUTRIENT_STOCK,
                "nutrient_id": "n1",
                "name": "N1",
                "current_ml": 10,
                "initial_ml": 20,
            }
        )
        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "not_initialized"

        # 3. Remove Stock - returns error
        await client.send_json(
            {"id": 3, "type": WS_TYPE_REMOVE_NUTRIENT_STOCK, "nutrient_id": "n1"}
        )
        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "not_initialized"


async def test_websocket_exceptions(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test generic exception handling for all commands."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    # Mock coordinator raising exception
    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            side_effect=Exception("Boom"),
        ),
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
            side_effect=Exception("Boom"),
        ),
    ):
        commands = [
            {"id": 1, "type": WS_TYPE_GET_NUTRIENT_INVENTORY},
            {
                "id": 2,
                "type": WS_TYPE_UPDATE_NUTRIENT_STOCK,
                "nutrient_id": "x",
                "name": "x",
                "current_ml": 1,
                "initial_ml": 1,
            },
            {"id": 3, "type": WS_TYPE_REMOVE_NUTRIENT_STOCK, "nutrient_id": "x"},
            {"id": 4, "type": WS_TYPE_GET_NUTRIENT_PRESETS},
            {"id": 5, "type": WS_TYPE_GET_IPM_PRESETS},
            {
                "id": 6,
                "type": WS_TYPE_ADD_TIMELINE_NOTE,
                ATTR_PLANT_ID: "p1",
                ATTR_NOTES: "n",
            },
            {"id": 7, "type": WS_TYPE_GET_DATA, "growspace_id": "g1"},
        ]

        for cmd in commands:
            await client.send_json(cmd)
            resp = await client.receive_json()
            assert not resp["success"]
            assert resp["error"]["code"] == "unknown_error"

    # Strain library exception
    # Create a mock library instance that raises on get_all
    mock_lib = MagicMock()
    mock_lib.get_all.side_effect = Exception("Lib Boom")

    # Inject it via a mock coordinator
    mock_coord = MagicMock()
    mock_coord.strain_library = mock_lib
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        return_value=mock_coord,
    ):
        await client.send_json({"id": 8, "type": WS_TYPE_GET_STRAIN_LIBRARY})
        resp = await client.receive_json()
        assert not resp["success"]
        assert resp["error"]["code"] == "unknown_error"

    # History Stats exception
    with patch(
        "custom_components.growspace_manager.websocket._get_statistics_data",
        side_effect=Exception("Stats Boom"),
    ):
        await client.send_json(
            {
                "id": 9,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["s1"],
                "start_time": "2023-01-01T00:00:00+00:00",
                "interval_minutes": 60,
            }
        )
        resp = await client.receive_json()
        assert not resp["success"]
        assert resp["error"]["code"] == "unknown_error"


async def test_websocket_history_stats_missing_start(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test history stats with invalid/missing start time."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    # Send strict violation (empty string checks)
    await client.send_json(
        {
            "id": 1,
            "type": WS_TYPE_GET_HISTORY_STATS,
            "entity_ids": ["s1"],
            "start_time": "",  # Empty string is handled by vol.Required normally, but dt_util.parse_datetime("") -> None
            "interval_minutes": 5,
        }
    )
    resp = await client.receive_json()
    assert not resp["success"]
    assert resp["error"]["code"] == "invalid_args"


async def test_websocket_statistics_edge_cases(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test _get_statistics_data edge cases."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats_module:
        # 1. Interval too small (<60) - returns None (which triggers fallback in caller, but we want to cover the line)
        # We can call the internal function directly or rely on the fallback logic triggering binary search
        # Let's verify the fallback happens by ensuring binary search is called

        # 2. No stats data returned
        async def mock_empty(*args, **kwargs):
            return {}  # Empty dict

        mock_stats_module.statistics_during_period.side_effect = mock_empty
        mock_stats_module.async_statistics_during_period.side_effect = mock_empty

        # 3. Stats data missing entity
        async def mock_missing_entity(*args, **kwargs):
            return {"other.entity": []}

        # 4. Value fallback from mean to state
        async def mock_val_fallback(*args, **kwargs):
            return {"sensor.test": [{"start": 100, "mean": None, "state": 50}]}

        # Test Case: Missing Entity in stats
        mock_stats_module.statistics_during_period.side_effect = mock_missing_entity
        mock_stats_module.async_statistics_during_period.side_effect = (
            mock_missing_entity
        )
        await client.send_json(
            {
                "id": 2,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": "2023-01-01T00:00:00+00:00",
                "interval_minutes": 60,
            }
        )
        resp = await client.receive_json()
        assert resp["success"]
        assert resp["result"]["sensor.test"] == []

        # Test Case: Value Fallback
        mock_stats_module.statistics_during_period.side_effect = mock_val_fallback
        mock_stats_module.async_statistics_during_period.side_effect = mock_val_fallback
        await client.send_json(
            {
                "id": 3,
                "type": WS_TYPE_GET_HISTORY_STATS,
                "entity_ids": ["sensor.test"],
                "start_time": "2023-01-01T00:00:00+00:00",
                "interval_minutes": 60,
            }
        )
        resp = await client.receive_json()
        assert resp["success"]
        assert resp["result"]["sensor.test"][0]["s"] == "50"


async def test_websocket_downsample_dict_state(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test binary search downsampler with dictionary states."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_recorder:
        state_dict = {"last_updated": "2023-01-01T12:00:00+00:00", "state": "25"}

        async def mock_executor(func, *args, **kwargs):
            if func.__name__ == "_get_history":
                return {"sensor.test": [state_dict]}
            return func()

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        with patch("homeassistant.components.recorder.history.get_significant_states"):
            await client.send_json(
                {
                    "id": 1,
                    "type": WS_TYPE_GET_HISTORY_STATS,
                    "entity_ids": ["sensor.test"],
                    "start_time": "2023-01-01T12:00:00+00:00",
                    "end_time": "2023-01-01T12:05:00+00:00",
                    "interval_minutes": 5,
                }
            )
            resp = await client.receive_json()
            assert resp["success"]
            assert resp["result"]["sensor.test"][0]["s"] == "25"
