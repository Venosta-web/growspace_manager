"""Tests for the TrendAnalyzer helper."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.trend_analyzer import TrendAnalyzer
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import utcnow


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def trend_analyzer(mock_hass):
    """Fixture for TrendAnalyzer."""
    return TrendAnalyzer(mock_hass)


def create_mock_history(
    states: Sequence[tuple[datetime, float | str]],
) -> dict[str, list[State]]:
    """Create a mock history list for get_significant_states."""
    mock_states = []
    for dt, state_val in states:
        state = State("sensor.test", str(state_val), last_updated=dt)
        mock_states.append(state)
    return {"sensor.test": mock_states}


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_rising(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test detecting a rising trend."""
    now = utcnow()
    history_data = [
        (now - timedelta(minutes=15), 20.0),
        (now - timedelta(minutes=10), 21.0),
        (now - timedelta(minutes=5), 22.0),
        (now, 23.0),
    ]
    mock_history = create_mock_history(history_data)

    # Mock the recorder instance and executor job
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=25.0
    )

    assert result["trend"] == "rising"
    assert result["crossed_threshold"] is False


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_falling(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test detecting a falling trend."""
    now = utcnow()
    history_data = [
        (now - timedelta(minutes=15), 25.0),
        (now, 20.0),
    ]
    mock_history = create_mock_history(history_data)

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=15.0
    )

    assert result["trend"] == "falling"
    assert (
        result["crossed_threshold"] is True
    )  # All values > 15.0 is False? Wait, 25 > 15, 20 > 15. So True.


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_stable(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test detecting a stable trend."""
    now = utcnow()
    history_data = [
        (now - timedelta(minutes=15), 20.0),
        (now, 20.0),
    ]
    mock_history = create_mock_history(history_data)

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=25.0
    )

    assert result["trend"] == "stable"


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_insufficient_data(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test handling insufficient data."""
    now = utcnow()
    history_data = [
        (now, 20.0),
    ]
    mock_history = create_mock_history(history_data)

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=25.0
    )

    assert result["trend"] == "stable"
    assert result["crossed_threshold"] is False


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_invalid_states(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test handling invalid states (unavailable/unknown)."""
    now = utcnow()
    history_data = [
        (now - timedelta(minutes=15), 20.0),
        (now - timedelta(minutes=10), STATE_UNAVAILABLE),
        (now, 22.0),
    ]
    # create_mock_history handles string values too
    mock_history = create_mock_history(history_data)

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=25.0
    )

    # Should ignore the unavailable state and compare 20.0 and 22.0 -> rising
    assert result["trend"] == "rising"


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_error_handling(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test error handling during history retrieval."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    # Simulate an error
    mock_recorder_instance.async_add_executor_job = AsyncMock(
        side_effect=ValueError("DB Error")
    )

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=25.0
    )

    assert result["trend"] == "unknown"
    assert result["crossed_threshold"] is False


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensor_trend_crossed_threshold(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test crossed_threshold logic."""
    now = utcnow()
    # All values above 20.0
    history_data = [
        (now - timedelta(minutes=15), 21.0),
        (now, 22.0),
    ]
    mock_history = create_mock_history(history_data)

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=20.0
    )

    assert result["crossed_threshold"] is True

    # One value below 20.0
    history_data_mixed = [
        (now - timedelta(minutes=15), 19.0),
        (now, 22.0),
    ]
    mock_history_mixed = create_mock_history(history_data_mixed)
    mock_recorder_instance.async_add_executor_job = AsyncMock(
        return_value=mock_history_mixed
    )

    result_mixed = await trend_analyzer.async_analyze_sensor_trend(
        "sensor.test", duration_minutes=15, threshold=20.0
    )

    assert result_mixed["crossed_threshold"] is False


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensors_trends_bulk(
    mock_get_recorder, trend_analyzer, mock_hass
) -> None:
    """Test bulk trend analysis."""
    now = utcnow()

    # History for sensor 1 (Rising)
    h1 = [
        (now - timedelta(minutes=15), 20.0),
        (now, 23.0),
    ]
    # History for sensor 2 (Falling)
    h2 = [
        (now - timedelta(minutes=15), 25.0),
        (now, 20.0),
    ]

    mock_states_1 = []
    for dt, val in h1:
        mock_states_1.append(State("sensor.one", str(val), last_updated=dt))

    mock_states_2 = []
    for dt, val in h2:
        mock_states_2.append(State("sensor.two", str(val), last_updated=dt))

    mock_history_dict = {
        "sensor.one": mock_states_1,
        "sensor.two": mock_states_2,
    }

    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance
    mock_recorder_instance.async_add_executor_job = AsyncMock(
        return_value=mock_history_dict
    )

    result = await trend_analyzer.async_analyze_sensors_trends(
        ["sensor.one", "sensor.two"], duration_minutes=15, threshold=22.0
    )

    assert result["sensor.one"]["trend"] == "rising"
    assert result["sensor.one"]["crossed_threshold"] is False  # 20 < 22

    assert result["sensor.two"]["trend"] == "falling"
    assert result["sensor.two"]["crossed_threshold"] is False  # 20 < 22


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensors_trends_empty_ids(
    mock_get_recorder, trend_analyzer: TrendAnalyzer
) -> None:
    """Test analyzing with empty sensor IDs list (line 31)."""
    result = await trend_analyzer.async_analyze_sensors_trends(
        [], duration_minutes=15, threshold=25.0
    )
    assert result == {}
    # Ensure no DB call was made
    mock_get_recorder.assert_not_called()


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensors_trends_invalid_objects(
    mock_get_recorder, trend_analyzer: TrendAnalyzer
) -> None:
    """Test handling non-State objects in history (line 58)."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    # Return a mix of valid State and invalid object (e.g. dict or string)
    # The code expects a dict of {sensor_id: [states]}
    # We inject a non-State object into the list
    mock_history = {
        "sensor.test": [
            State("sensor.test", "20.0"),
            "not a state object",  # This should be skipped
            State("sensor.test", "22.0"),
        ]
    }

    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensors_trends(
        ["sensor.test"], duration_minutes=15, threshold=25.0
    )

    # Should calculate trend based on 20.0 and 22.0 (rising)
    # If "not a state object" caused a crash, test would fail.
    assert result["sensor.test"]["trend"] == "rising"


@patch("custom_components.growspace_manager.trend_analyzer.get_recorder_instance")
@pytest.mark.asyncio
async def test_async_analyze_sensors_trends_value_error(
    mock_get_recorder, trend_analyzer: TrendAnalyzer
) -> None:
    """Test handling ValueError during float conversion (lines 63-64)."""
    mock_recorder_instance = MagicMock()
    mock_get_recorder.return_value = mock_recorder_instance

    # "unknown state" strings are likely skipped by explicit check,
    # but "some_random_text" that is NOT in [STATE_UNKNOWN, STATE_UNAVAILABLE, None, ""]
    # will proceed to float() conversion and raise ValueError.
    mock_history = {
        "sensor.test": [
            State("sensor.test", "20.0"),
            State(
                "sensor.test", "not_a_number"
            ),  # Should raise ValueError and continue
            State("sensor.test", "22.0"),
        ]
    }

    mock_recorder_instance.async_add_executor_job = AsyncMock(return_value=mock_history)

    result = await trend_analyzer.async_analyze_sensors_trends(
        ["sensor.test"], duration_minutes=15, threshold=25.0
    )

    # Should skip the middle invalid value and see 20->22 (rising)
    assert result["sensor.test"]["trend"] == "rising"
