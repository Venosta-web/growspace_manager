"""Tests for post-harvest strategies."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from custom_components.growspace_manager.models import EnvironmentState, GrowspaceType
from custom_components.growspace_manager.strategies.drying import DryingEvaluatorStrategy
from custom_components.growspace_manager.strategies.curing import CuringEvaluatorStrategy


@pytest.fixture
def mock_sensor() -> MagicMock:
    """Mock the Bayesian sensor."""
    measure_type = MagicMock()
    measure_type.env_config = MagicMock()
    measure_type.env_config.to_dict.return_value = {}
    return measure_type


@pytest.mark.asyncio
async def test_post_harvest_missing_state_fields(mock_sensor: MagicMock) -> None:
    """Test async_evaluate early return when state fields are None."""
    mock_growspace = MagicMock()
    mock_growspace.growspace_type = GrowspaceType.DRY

    strategy = DryingEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # Missing temp
    state_temp_none = EnvironmentState(temp=None, humidity=50.0, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state_temp_none)
    assert obs == []
    assert reasons == []

    # Missing humidity
    state_humidity_none = EnvironmentState(temp=20.0, humidity=None, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state_humidity_none)
    assert obs == []
    assert reasons == []

    # Both missing
    state_both_none = EnvironmentState(temp=None, humidity=None, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state_both_none)
    assert obs == []
    assert reasons == []


@pytest.mark.asyncio
async def test_post_harvest_wrong_growspace_type(mock_sensor: MagicMock) -> None:
    """Test async_evaluate when growspace type does not match."""
    mock_growspace = MagicMock()
    mock_growspace.growspace_type = GrowspaceType.VEG  # Wrong type for Drying which expects DRY

    strategy = DryingEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace,
        get_notification_message=MagicMock(return_value="msg"),
    )

    state = EnvironmentState(temp=20.0, humidity=50.0, vpd=1.0)
    obs, reasons = await strategy.async_evaluate(state)
    assert obs == []
    assert reasons == []


@pytest.mark.asyncio
async def test_post_harvest_success(mock_sensor: MagicMock) -> None:
    """Test async_evaluate success path for drying and curing."""
    mock_growspace_dry = MagicMock()
    mock_growspace_dry.growspace_type = GrowspaceType.DRY

    strategy_dry = DryingEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace_dry,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # In range
    state = EnvironmentState(temp=18.0, humidity=60.0, vpd=1.0)
    obs, reasons = await strategy_dry.async_evaluate(state)
    assert len(obs) > 0
    assert len(reasons) > 0
    assert any("Optimal" in r[1] for r in reasons)

    # Out of range
    state_out = EnvironmentState(temp=25.0, humidity=75.0, vpd=1.0)
    obs_out, reasons_out = await strategy_dry.async_evaluate(state_out)
    assert len(obs_out) > 0
    assert len(reasons_out) > 0
    assert any("out of range" in r[1] for r in reasons_out)

    mock_growspace_cure = MagicMock()
    mock_growspace_cure.growspace_type = GrowspaceType.CURE

    strategy_cure = CuringEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace_cure,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # In range
    state_cure = EnvironmentState(temp=18.0, humidity=60.0, vpd=1.0)
    obs_cure, reasons_cure = await strategy_cure.async_evaluate(state_cure)
    assert len(obs_cure) > 0
    assert len(reasons_cure) > 0

    # Out of range
    state_cure_out = EnvironmentState(temp=5.0, humidity=40.0, vpd=1.0)
    obs_cure_out, reasons_cure_out = await strategy_cure.async_evaluate(state_cure_out)
    assert len(obs_cure_out) > 0
    assert len(reasons_cure_out) > 0
