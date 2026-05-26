"""Tests for optimal strategies and base evaluator strategy."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.strategies.evaluator_strategy import (
    BayesianEvaluatorStrategy,
)
from custom_components.growspace_manager.strategies.optimal import (
    OptimalConditionsEvaluatorStrategy,
)


@pytest.fixture
def mock_sensor() -> MagicMock:
    """Mock the Bayesian sensor."""
    measure_type = MagicMock()
    measure_type.env_config = MagicMock()
    measure_type.env_config.to_dict.return_value = {}
    return measure_type


@pytest.mark.asyncio
async def test_optimal_conditions_notification(mock_sensor: MagicMock) -> None:
    """Test notification title generation for falling edge."""
    mock_growspace = MagicMock()
    mock_growspace.name = "GTent"

    strategy = OptimalConditionsEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # Rising edge -> should return None
    assert strategy.get_notification_title_message(True, []) is None

    # Falling edge -> should return notification
    title_msg = strategy.get_notification_title_message(False, [])
    assert title_msg is not None
    assert "Optimal Conditions Lost" in title_msg[0]
    assert "GTent" in title_msg[0]

    # Test fallback name when get_growspace returns None
    strategy_no_growspace = OptimalConditionsEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: None,
        get_notification_message=MagicMock(return_value="msg"),
    )
    title_msg_fallback = strategy_no_growspace.get_notification_title_message(False, [])
    assert title_msg_fallback is not None
    assert "Optimal Conditions Lost: Unknown" in title_msg_fallback[0]


class DummyEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Dummy strategy to test the base class methods."""

    async def async_evaluate(
        self, state: Any
    ) -> tuple[Any, Any]:
        """Implement abstract method."""
        return [], []


def test_base_evaluator_strategy_notification_default(mock_sensor: MagicMock) -> None:
    """Test that the default base class implementation of get_notification_title_message returns None."""
    strategy = DummyEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=MagicMock(return_value=None),
        get_notification_message=MagicMock(return_value="msg"),
    )

    assert strategy.get_notification_title_message(True, []) is None


@pytest.mark.asyncio
async def test_optimal_conditions_evaluate_missing_state_fields(mock_sensor: MagicMock) -> None:
    """Test async_evaluate early return when state fields are None."""
    strategy = OptimalConditionsEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=MagicMock(return_value=None),
        get_notification_message=MagicMock(return_value="msg"),
    )

    # All fields None
    state_all_none = EnvironmentState(temp=None, humidity=None, vpd=None)
    obs, reasons = await strategy.async_evaluate(state_all_none)
    assert obs == []
    assert reasons == []

    # Only temp is None
    state_temp_none = EnvironmentState(temp=None, humidity=50.0, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state_temp_none)
    assert obs == []
    assert reasons == []

    # Only humidity is None
    state_humidity_none = EnvironmentState(temp=25.0, humidity=None, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state_humidity_none)
    assert obs == []
    assert reasons == []

    # Only vpd is None
    state_vpd_none = EnvironmentState(temp=25.0, humidity=50.0, vpd=None)
    obs, reasons = await strategy.async_evaluate(state_vpd_none)
    assert obs == []
    assert reasons == []


@pytest.mark.asyncio
async def test_optimal_conditions_evaluate_success(mock_sensor: MagicMock) -> None:
    """Test async_evaluate when all required fields are present."""
    strategy = OptimalConditionsEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=MagicMock(return_value=None),
        get_notification_message=MagicMock(return_value="msg"),
    )

    state = EnvironmentState(temp=24.0, humidity=55.0, vpd=1.0, co2=600.0)
    obs, reasons = await strategy.async_evaluate(state)

    assert isinstance(obs, list)
    assert isinstance(reasons, list)


