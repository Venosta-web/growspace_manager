"""Tests for the TrendAnalyzer helper."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import utcnow

from custom_components.growspace_manager.trend_analyzer import TrendAnalyzer


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    return hass


@pytest.fixture
def trend_analyzer(mock_hass):
    """Fixture for TrendAnalyzer."""
    return TrendAnalyzer(mock_hass)


def create_mock_history(
    states: list[tuple[datetime, float | str]],
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
):
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
):
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
):
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
):
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
):
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
):
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
):
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
):
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
