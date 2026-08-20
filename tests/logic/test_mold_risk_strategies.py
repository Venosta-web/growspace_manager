from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)


@pytest.fixture
def mock_sensor():
    """Mock the Bayesian sensor."""
    measure_type = MagicMock()
    measure_type.env_config = MagicMock()
    measure_type.env_config.humidity_sensor = "sensor.humidity"
    return measure_type


def _make_mold_strategy(mock_sensor: MagicMock) -> MoldRiskEvaluatorStrategy:
    """Create a MoldRiskEvaluatorStrategy with injected test dependencies."""
    from unittest.mock import AsyncMock

    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    return MoldRiskEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=MagicMock(return_value=mock_growspace),
        get_notification_message=MagicMock(return_value="msg"),
    )


@pytest.mark.asyncio
async def test_mold_risk_humidity_none(mock_sensor) -> None:
    """Test early return when humidity is None."""
    strategy = _make_mold_strategy(mock_sensor)
    state = MagicMock(spec=EnvironmentState)
    state.humidity = None

    obs, reasons = await strategy.async_evaluate(state)
    assert len(obs) == 0
    assert len(reasons) == 0


@pytest.mark.asyncio
async def test_evaluate_humidity_risk_branches(mock_sensor) -> None:
    """Test specific branches in _evaluate_humidity_risk."""
    strategy = _make_mold_strategy(mock_sensor)
    state = MagicMock(spec=EnvironmentState)
    state.humidity = 87.0
    state.seedling_days = -1
    state.clone_days = -1
    state.veg_days = -1
    state.flower_days = 43  # Late flower
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1

    # Late flower critical humidity is 65.0, high is 60.0
    # 87.0 is way above critical
    await strategy.async_evaluate(state)
    # Just ensuring no errors, logic is covered by existing tests mostly,
    # but we need to hit specific stage branches.

    # Test explicit "Veg" branch with high humidity but not extreme
    state.flower_days = -1
    state.veg_days = 10  # must be non-empty to evaluate veg thresholds
    state.humidity = 82.0  # High > 80, Critical > 85
    # Should hit "High humidity" branch
    obs_list = []
    reasons = []
    strategy._evaluate_humidity_risk(state, obs_list, reasons)
    assert len(obs_list) == 1
    assert "High humidity" in reasons[0][1]


@pytest.mark.asyncio
async def test_evaluate_circulation_risk_branches(mock_sensor) -> None:
    """Test circulation risk thresholds."""
    strategy = _make_mold_strategy(mock_sensor)
    state = MagicMock(spec=EnvironmentState)
    state.fan_off = True
    # Initialize all stage attributes to integers to avoid MagicMock comparison errors
    state.seedling_days = -1
    state.clone_days = -1
    state.veg_days = -1
    state.flower_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1

    # 1. Early stage threshold (Acclimation: 100.0)
    state.seedling_days = 1
    state.flower_days = -1
    state.humidity = 95.0  # Below 100
    obs = []
    reasons = []
    strategy._evaluate_circulation_risk(state, obs, reasons)
    assert len(obs) == 0  # Should return early

    state.humidity = 101.0
    strategy._evaluate_circulation_risk(state, obs, reasons)
    assert len(obs) == 1

    # 2. Veg threshold (80.0)
    state.seedling_days = -1
    state.flower_days = -1
    state.veg_days = 10  # must be non-empty to evaluate veg thresholds
    state.humidity = 79.0
    obs = []
    strategy._evaluate_circulation_risk(state, obs, [])
    assert len(obs) == 0

    state.humidity = 81.0
    strategy._evaluate_circulation_risk(state, obs, [])
    assert len(obs) == 1


@pytest.mark.asyncio
async def test_evaluate_humidifier_risk_branches(mock_sensor) -> None:
    """Test humidifier risk logic branches."""
    strategy = _make_mold_strategy(mock_sensor)
    state = MagicMock(spec=EnvironmentState)
    state.humidifier_on = True
    # Initialize all stage attributes to integers
    state.seedling_days = -1
    state.clone_days = -1
    state.veg_days = -1
    state.flower_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1

    # 1. Early stage safe zone (< 90)
    state.seedling_days = 1
    state.flower_days = -1
    state.humidity = 89.0
    obs = []
    strategy._evaluate_humidifier_risk(state, obs, [])
    assert len(obs) == 0

    # 2. Veg safe zone (< 85)
    state.seedling_days = -1
    state.flower_days = -1
    state.humidity = 84.0
    obs = []
    strategy._evaluate_humidifier_risk(state, obs, [])
    assert len(obs) == 0

    # 3. Late flower safe zone (< 60)
    state.flower_days = 45
    state.humidity = 59.0
    obs = []
    strategy._evaluate_humidifier_risk(state, obs, [])
    assert len(obs) == 0

    # 4. Mid flower safe zone (< 70) (implicit else branch)
    state.flower_days = 20
    state.humidity = 69.0
    obs = []
    strategy._evaluate_humidifier_risk(state, obs, [])
    assert len(obs) == 0


@pytest.mark.asyncio
async def test_notification_title_generation(mock_sensor) -> None:
    """Test notification title generation."""
    mock_growspace = MagicMock()
    mock_growspace.name = "GTent"
    from unittest.mock import AsyncMock

    strategy = MoldRiskEvaluatorStrategy(
        env_config=mock_sensor.env_config,
        analyze_trend=AsyncMock(return_value={"trend": "stable", "crossed_threshold": False}),
        get_state=MagicMock(return_value=None),
        get_growspace=lambda: mock_growspace,
        get_notification_message=MagicMock(return_value="msg"),
    )

    # Rising edge
    title_msg = strategy.get_notification_title_message(True, [])
    assert title_msg is not None
    assert "High Mold Risk" in title_msg[0]

    # Falling edge (None)
    title_msg = strategy.get_notification_title_message(False, [])
    assert title_msg is None
