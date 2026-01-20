from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)


@pytest.fixture
def mock_sensor():
    sensor = MagicMock()
    sensor.env_config.humidity_sensor = None
    sensor._reasons = []
    return sensor


@pytest.mark.asyncio
async def test_mold_risk_seedling_high_humidity(mock_sensor) -> None:
    """Test that 88% humidity in seedling stage triggers a High humidity warning but with early stage thresholds."""
    strategy = MoldRiskEvaluatorStrategy(mock_sensor)

    # Seedling stage (10 days old)
    state = EnvironmentState(
        temp=25.0,
        humidity=88.0,
        vpd=0.8,
        co2=400,
        veg_days=0,
        flower_days=0,
        seedling_days=10,
        clone_days=0,
        is_lights_on=True,
        fan_off=False,
        dehumidifier_on=False,
        exhaust_value=0.0,
        humidifier_value=0.0,
        soil_moisture=50.0,
        humidifier_on=False,
    )

    _obs, rsn = await strategy.async_evaluate(state)

    # Probability calculation: 88% is >= high_humidity (88.0)
    # So it should have a high humidity reason but NOT critical (92.0)
    has_high_hum_reason = any("High humidity: 88.0%" in r[1] for r in rsn)
    assert has_high_hum_reason
    assert not any("Critical" in r[1] for r in rsn)


@pytest.mark.asyncio
async def test_mold_risk_veg_high_humidity(mock_sensor) -> None:
    """Test that 86% humidity triggers a Critical humidity warning in veg stage."""
    strategy = MoldRiskEvaluatorStrategy(mock_sensor)

    # Veg stage (20 days old)
    state = EnvironmentState(
        temp=25.0,
        humidity=86.0,
        vpd=0.8,
        co2=400,
        veg_days=20,
        flower_days=0,
        seedling_days=0,
        clone_days=0,
        is_lights_on=True,
        fan_off=False,
        dehumidifier_on=False,
        exhaust_value=0.0,
        humidifier_value=0.0,
        soil_moisture=50.0,
        humidifier_on=False,
    )

    _obs, rsn = await strategy.async_evaluate(state)

    # In Veg, 86% is >= critical_humidity (85.0)
    has_critical_hum_reason = any("Critical humidity: 86.0%" in r[1] for r in rsn)
    assert has_critical_hum_reason


@pytest.mark.asyncio
async def test_mold_risk_extreme_humidity_penalty(mock_sensor) -> None:
    """Test extra penalty for extreme humidity in non-early stages."""
    strategy = MoldRiskEvaluatorStrategy(mock_sensor)

    # Veg stage, 91% humidity
    state = EnvironmentState(
        temp=25.0,
        humidity=91.0,
        vpd=0.8,
        co2=400,
        veg_days=20,
        flower_days=0,
        seedling_days=0,
        clone_days=0,
        is_lights_on=True,
        fan_off=False,
        dehumidifier_on=False,
        exhaust_value=0.0,
        humidifier_value=0.0,
        soil_moisture=50.0,
        humidifier_on=False,
    )

    _obs, rsn = await strategy.async_evaluate(state)
    has_extreme_reason = any("Extreme humidity risk: 91.0%" in r[1] for r in rsn)
    assert has_extreme_reason

    # Seedling stage, 91% humidity -> No extreme penalty (91 < 92)
    state.seedling_days = 10
    state.veg_days = 0
    _obs, rsn = await strategy.async_evaluate(state)
    has_extreme_reason = any("Extreme humidity risk" in r[1] for r in rsn)
    assert not has_extreme_reason
    # But it should have High humidity reason
    assert any("High humidity" in r[1] for r in rsn)
