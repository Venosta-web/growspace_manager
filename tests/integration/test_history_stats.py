"""Tests for the history stats websocket command."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.websocket import websocket_get_history_stats
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    return hass


@pytest.fixture
def mock_connection():
    """Mock WebSocket connection."""
    connection = MagicMock()
    connection.send_result = MagicMock()
    connection.send_error = MagicMock()
    return connection


@pytest.mark.asyncio
async def test_websocket_get_history_stats_binary_search(
    mock_hass, mock_connection
) -> None:
    """Test get_history_stats uses binary search downsampling correctly."""

    # Mock data: 1000 states over 1000 minutes
    start_time = dt_util.utcnow() - timedelta(minutes=1000)
    end_time = dt_util.utcnow()

    states = []
    for i in range(1001):
        t = start_time + timedelta(minutes=i)
        state = MagicMock()
        state.state = str(i)
        state.last_updated = t
        states.append(state)

    # Mock history.get_significant_states return value
    # Format: {entity_id: [State, State, ...]}
    history_data = {"sensor.test": states}

    def mock_get_history(*args, **kwargs):
        return history_data

    # Mock get_instance to return a mock recorder instance
    mock_recorder = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.history.get_significant_states",
            side_effect=mock_get_history,
            create=True,
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance",
            return_value=mock_recorder,
        ),
    ):
        # We need to simulate the nested async_add_executor_job call in the implementation
        # The implementation calls: await get_instance(hass).async_add_executor_job(_get_history)
        mock_recorder.async_add_executor_job = AsyncMock(
            side_effect=lambda f, *args: f(*args)
        )

        # Mock statistics to return None to force fallback to binary search history
        with (
            patch(
                "custom_components.growspace_manager.websocket.environment.recorder_stats.statistics_during_period",
                new_callable=AsyncMock,
                create=True,
                return_value=None,
            ),
            patch(
                "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
                new_callable=AsyncMock,
                create=True,
                return_value=None,
            ),
        ):
            msg = {
                "id": 1,
                "type": f"{DOMAIN}/get_history_stats",
                "entity_ids": ["sensor.test"],
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "interval_minutes": 100,  # Should downsample to ~10 points
            }

            await websocket_get_history_stats(mock_hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]

        assert "sensor.test" in result
        points = result["sensor.test"]

        # With interval=100 min over 1000 min, we expect approx 11 points (0, 100, 200..1000)
        # Verify checking a few
        assert len(points) >= 10 and len(points) <= 12

        # Check first point
        assert points[0]["s"] == "0"
        # Check last point
        # Depending on binary search check (last state <= current_time)
        # At start_time, it should be state 0.
        # At start_time + 100m, it should be state 100.

        assert points[1]["s"] == "100"


@pytest.mark.asyncio
async def test_websocket_get_history_stats_statistics_api(
    mock_hass, mock_connection
) -> None:
    """Test get_history_stats uses Recorder Statistics API for large intervals."""

    start_time = dt_util.utcnow() - timedelta(days=7)

    with patch(
        "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
        new_callable=AsyncMock,
        create=True,
    ) as mock_stats:
        mock_stats.return_value = {
            "sensor.test": [
                {"start": start_time.timestamp(), "mean": 20.5},
                {"start": (start_time + timedelta(hours=1)).timestamp(), "mean": 21.0},
            ]
        }

        msg = {
            "id": 2,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start_time.isoformat(),
            "interval_minutes": 60,  # >= 60 triggers statistics API
        }

        await websocket_get_history_stats(mock_hass, mock_connection, msg)

        mock_stats.assert_called_once()
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]

        assert "sensor.test" in result
        assert len(result["sensor.test"]) == 2

        assert result["sensor.test"][0]["s"] == "20.5"


@pytest.mark.asyncio
async def test_websocket_get_history_stats_statistics_daily_and_missing_and_exception(
    mock_hass, mock_connection
) -> None:
    """Test statistics daily interval, missing entity stats, and statistics exception."""
    start_time = dt_util.utcnow() - timedelta(days=2)
    end_time = dt_util.utcnow()

    # Mock statistics call for daily interval
    with patch(
        "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
        new_callable=AsyncMock,
        create=True,
    ) as mock_stats:
        # Scenario 1: Daily interval, one entity missing from stats data
        mock_stats.return_value = {
            "sensor.test": [
                {"start": start_time.timestamp(), "mean": 20.5},
            ]
            # "sensor.missing" is not in stats_data
        }

        msg = {
            "id": 3,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test", "sensor.missing"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "interval_minutes": 1440,  # >= 1440 triggers period = "day"
        }

        await websocket_get_history_stats(mock_hass, mock_connection, msg)

        mock_stats.assert_called_once()
        # Verify period="day" is passed
        args, kwargs = mock_stats.call_args
        assert args[4] == "day"

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "sensor.test" in result
        assert "sensor.missing" in result
        assert result["sensor.missing"] == []

        # Reset mocks
        mock_connection.reset_mock()
        mock_stats.reset_mock()

        # Scenario 2: Statistics API raises an exception (should fall back to raw history)
        mock_stats.side_effect = Exception("Stats API failure")
        history_data = {"sensor.test": []}
        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))

        with (
            patch(
                "custom_components.growspace_manager.websocket.environment.history.get_significant_states",
                return_value=history_data,
                create=True,
            ),
            patch(
                "custom_components.growspace_manager.websocket.environment.get_instance",
                return_value=mock_recorder,
            ),
        ):
            await websocket_get_history_stats(mock_hass, mock_connection, msg)
            mock_connection.send_result.assert_called_once()
            result = mock_connection.send_result.call_args[0][1]
            assert "sensor.test" in result
            assert result["sensor.test"] == []


@pytest.mark.asyncio
async def test_websocket_get_history_stats_binary_search_edge_cases(
    mock_hass, mock_connection
) -> None:
    """Test binary search downsampling edge cases like dict states, sentinel TS, and idx < 0."""
    start_time = dt_util.utcnow() - timedelta(minutes=1000)
    end_time = dt_util.utcnow()

    # Create states:
    # 1. State before start_time (to get idx >= 0 initially)
    # 2. State with epoch sentinel (None last_updated)
    # 3. State as a dict
    # 4. State as an object
    state_before = MagicMock()
    state_before.state = "10.0"
    state_before.last_updated = start_time - timedelta(minutes=10)

    state_sentinel = {"state": "20.0", "last_updated": None}

    state_dict = {"state": "30.0", "last_updated": start_time + timedelta(minutes=100)}

    state_obj = MagicMock()
    state_obj.state = "40.0"
    state_obj.last_updated = start_time + timedelta(minutes=200)

    # Put them in states list
    # Because of bisect_right, they must be sorted by timestamp
    states = [state_before, state_sentinel, state_dict, state_obj]

    # We need len(states) > 200 to bypass sparse threshold and enter binary search
    # Let's pad it with many states at the end to make it > 200
    for i in range(250):
        s = MagicMock()
        s.state = "50.0"
        s.last_updated = end_time + timedelta(minutes=i)
        states.append(s)

    history_data = {"sensor.test": states}
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.history.get_significant_states",
            return_value=history_data,
            create=True,
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance",
            return_value=mock_recorder,
        ),
    ):
        msg = {
            "id": 4,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "interval_minutes": 50,
        }

        await websocket_get_history_stats(mock_hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert "sensor.test" in result
    points = result["sensor.test"]
    assert len(points) > 0

    # Let's also test the idx < 0 case.
    # To trigger idx < 0, all states must have timestamp after end_time.
    states_future = []
    for i in range(210):
        s = MagicMock()
        s.state = "60.0"
        s.last_updated = end_time + timedelta(minutes=10 + i)
        states_future.append(s)

    history_data_future = {"sensor.test": states_future}
    mock_connection.reset_mock()

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.history.get_significant_states",
            return_value=history_data_future,
            create=True,
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance",
            return_value=mock_recorder,
        ),
    ):
        await websocket_get_history_stats(mock_hass, mock_connection, msg)
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result["sensor.test"] == []


@pytest.mark.asyncio
async def test_websocket_get_history_stats_sparse_and_fan_data(
    mock_hass, mock_connection
) -> None:
    """Test history stats with fan entity IDs, empty states, and sparse data logic."""
    start_time = dt_util.utcnow() - timedelta(minutes=100)
    end_time = dt_util.utcnow()

    # Create sparse states (fewer than 200):
    # For a fan state as dict (with percentage)
    fan_state_dict = {
        "state": "on",
        "last_updated": start_time + timedelta(minutes=10),
        "attributes": {"percentage": 50},
    }
    # For a fan state as object (with percentage)
    fan_state_obj = MagicMock()
    fan_state_obj.state = "on"
    fan_state_obj.last_updated = start_time + timedelta(minutes=20)
    fan_state_obj.attributes = {"percentage": 100}

    # For a fan state as dict (without percentage)
    fan_state_dict_no_pct = {
        "state": "on",
        "last_updated": start_time + timedelta(minutes=30),
        "attributes": {},
    }

    # A state with epoch sentinel (should be skipped)
    sentinel_state = {"state": "on", "last_updated": None}

    # A non-fan state as dict
    sensor_state_dict = {
        "state": "23.5",
        "last_updated": start_time + timedelta(minutes=40),
    }

    # Non-fan state as object
    sensor_state_obj = MagicMock()
    sensor_state_obj.state = "24.0"
    sensor_state_obj.last_updated = start_time + timedelta(minutes=50)

    history_data = {
        "fan.test_fan": [fan_state_dict, fan_state_obj, fan_state_dict_no_pct, sentinel_state],
        "sensor.test_sensor": [sensor_state_dict, sensor_state_obj],
        "sensor.empty_sensor": [],
    }

    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.history.get_significant_states",
            return_value=history_data,
            create=True,
        ) as mock_get_states,
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance",
            return_value=mock_recorder,
        ),
    ):
        msg = {
            "id": 5,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["fan.test_fan", "sensor.test_sensor", "sensor.empty_sensor"],
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "interval_minutes": 5,
        }

        await websocket_get_history_stats(mock_hass, mock_connection, msg)

        # Verify that get_significant_states was called twice (once for non-fan, once for fan)
        assert mock_get_states.call_count == 2

        # Check call arguments
        # One call should have minimal_response=True (for sensor.test_sensor, sensor.empty_sensor)
        # Another call should have minimal_response=False (for fan.test_fan)
        calls = mock_get_states.call_args_list
        fan_call = None
        sensor_call = None
        for call in calls:
            kwargs = call[1]
            if kwargs.get("minimal_response") is False:
                fan_call = call
            elif kwargs.get("minimal_response") is True:
                sensor_call = call

        assert fan_call is not None
        assert sensor_call is not None
        assert "fan.test_fan" in fan_call[0][3]
        assert "sensor.test_sensor" in sensor_call[0][3]

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]

    # Verify results
    assert "fan.test_fan" in result
    assert "sensor.test_sensor" in result
    assert "sensor.empty_sensor" in result

    assert result["sensor.empty_sensor"] == []

    fan_points = result["fan.test_fan"]
    # fan_state_dict, fan_state_obj, fan_state_dict_no_pct should be processed (sentinel skipped)
    assert len(fan_points) == 3
    # fan_state_dict attributes percentage: 50 -> "a": {"percentage": 50}
    assert fan_points[0]["s"] == "on"
    assert fan_points[0]["a"] == {"percentage": 50}

    # fan_state_obj attributes percentage: 100 -> "a": {"percentage": 100}
    assert fan_points[1]["s"] == "on"
    assert fan_points[1]["a"] == {"percentage": 100}

    # fan_state_dict_no_pct should not have "a" key since percentage is None
    assert fan_points[2]["s"] == "on"
    assert "a" not in fan_points[2]

    sensor_points = result["sensor.test_sensor"]
    assert len(sensor_points) == 2
    assert sensor_points[0]["s"] == "23.5"
    assert sensor_points[1]["s"] == "24.0"


@pytest.mark.asyncio
async def test_websocket_get_history_stats_general_exception(
    mock_hass, mock_connection
) -> None:
    """Test general exception handling in get_history_stats websocket handler."""
    msg = {
        "id": 6,
        "type": f"{DOMAIN}/get_history_stats",
        "entity_ids": ["sensor.test"],
        "start_time": "2026-06-01T00:00:00Z",
        "interval_minutes": 5,
    }

    # Mock parse_datetime to raise a generic Exception
    with patch(
        "custom_components.growspace_manager.websocket.environment.dt_util.parse_datetime",
        side_effect=RuntimeError("Unexpected parsing failure"),
    ):
        await websocket_get_history_stats(mock_hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(
        6, "unknown_error", "Unexpected parsing failure"
    )
