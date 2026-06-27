"""Tests for stress strategies."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)


@pytest.fixture
def mock_sensor() -> MagicMock:
    """Mock the Bayesian sensor."""
    measure_type = MagicMock()
    measure_type.env_config = MagicMock()
    measure_type.env_config.to_dict.return_value = {}
    measure_type.env_config.temperature_sensor = None
    return measure_type


def test_stress_notification(mock_sensor: MagicMock) -> None:
    """Test get_notification_title_message in StressEvaluatorStrategy."""
    mock_growspace = MagicMock()
    mock_growspace.name = "FloweringTent"

    strategy = StressEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # new_state_on is False -> should return None (exercises line 76)
    assert strategy.get_notification_title_message(False, []) is None

    # new_state_on is True -> should return notification
    title_msg = strategy.get_notification_title_message(True, [])
    assert title_msg is not None
    assert title_msg[0] == "Plant Stress Alert: FloweringTent"

    # Test when growspace is None
    strategy_no_growspace = StressEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: None,
        get_notification_message=MagicMock(return_value="msg"),
    )
    title_msg_fallback = strategy_no_growspace.get_notification_title_message(True, [])
    assert title_msg_fallback is not None
    assert title_msg_fallback[0] == "Plant Stress Alert: Unknown"


@pytest.mark.asyncio
async def test_stress_evaluate(mock_sensor: MagicMock) -> None:
    """Test async_evaluate in StressEvaluatorStrategy."""
    # Test with temperature_sensor = None (exercises False branch at line 56)
    strategy = StressEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=MagicMock(return_value=None),
        get_notification_message=MagicMock(return_value="msg"),
    )

    state = EnvironmentState(temp=25.0, humidity=50.0, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state)
    assert isinstance(obs, list)
    assert isinstance(reasons, list)

    # Test with temperature_sensor = "sensor.temp" (exercises True branch at line 56)
    mock_sensor.env_config.temperature_sensor = "sensor.temp"

    with patch("custom_components.growspace_manager.strategies.stress.async_evaluate_stress_trend", new_callable=AsyncMock) as mock_trend_eval:
        mock_trend_eval.return_value = ([("stress_trend", 0.7)], ["Temp trend high"], None)
        obs, reasons = await strategy.async_evaluate(state)
        assert ("stress_trend", 0.7) in obs
        assert "Temp trend high" in reasons
