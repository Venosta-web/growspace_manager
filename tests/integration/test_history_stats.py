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
