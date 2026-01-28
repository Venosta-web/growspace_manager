from unittest.mock import MagicMock

import pytest

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
async def test_optimal_conditions_notification(mock_sensor) -> None:
    """Test notification title generation for falling edge."""
    strategy = OptimalConditionsEvaluatorStrategy(mock_sensor)

    # Mock coordinator and growspace
    mock_sensor.coordinator.growspaces = {"gs1": MagicMock(name="GTent")}
    mock_sensor.growspace_id = "gs1"
    mock_sensor.generate_notification_message.return_value = "msg"

    # Rising edge (True) -> Should return None (handled by bayesian_evaluator base or not needed here)
    # The method only handles falling edge (new_state_on=False)
    assert strategy.get_notification_title_message(True) is None

    # Falling edge (False) -> Should return notification
    title_msg = strategy.get_notification_title_message(False)
    assert title_msg is not None
    assert "Optimal Conditions Lost" in title_msg[0]
    assert "GTent" in title_msg[0]

    # Test fallback name
    mock_sensor.coordinator.growspaces = {}
    title_msg_fallback = strategy.get_notification_title_message(False)
    assert title_msg_fallback is not None
    assert "Optimal Conditions Lost: gs1" in title_msg_fallback[0]
