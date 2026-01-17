"""Tests for the refactored Bayesian Mold Risk Sensor."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.models import EnvironmentConfig, GrowspaceType
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)

MOCK_CONFIG_ENTRY_ID = "test_entry"


@pytest.fixture
def mock_growspace():
    """Fixture for a mock growspace with environment config."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.growspace_type = GrowspaceType.FLOWER
    growspace.notification_target = "notify.test"
    growspace.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        vpd_sensor="sensor.vpd",
        co2_sensor="sensor.co2",
        circulation_fan_entities=["switch.fan"],
        light_sensors=["light.grow_light"],
        soil_moisture_sensor="sensor.soil_moisture",
        bayesian_options={
            "threshold_mold": 0.75,
            "prior_mold_risk": 0.10,
        },
    )
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}

    # Mock plants for stage calculation
    coordinator.plants = {}

    def _calculate_days_side_effect(start_date_str):
        if not start_date_str:
            return 0
        dt = date.fromisoformat(start_date_str.split("T")[0])
        return (date.today() - dt).days

    coordinator.get_growspace_plants.return_value = []
    coordinator.is_notifications_enabled.return_value = True
    coordinator.async_add_listener = Mock()
    coordinator.calculate_days.side_effect = _calculate_days_side_effect
    return coordinator


@pytest.fixture
def env_config(mock_growspace):
    """Fixture for a sample environment configuration."""
    return mock_growspace.environment_config


def set_sensor_state(hass: HomeAssistant, entity_id, state, attributes=None):
    """Helper to set a sensor's state in hass."""
    if state is None:
        hass.states.async_set(entity_id, STATE_UNKNOWN, attributes)
        return

    attrs = attributes or {}
    hass.states.async_set(entity_id, state, attrs)


@pytest.mark.asyncio
async def test_mold_sensor_stage_aware_thresholds(
    hass: HomeAssistant, mock_coordinator, env_config
) -> None:
    """Test new stage-aware humidity thresholds."""

    description = next(
        d for d in SENSOR_TYPES if d.sensor_type == GrowspaceSensorType.MOLD
    )
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold"
    sensor.platform = MagicMock()

    # Common mocks
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    # Mocks for trend analysis to ensure they don't interfere
    with patch(
        "custom_components.growspace_manager.strategies.mold.async_evaluate_mold_risk_trend",
        new_callable=AsyncMock,
    ) as mock_evaluate:
        # Return empty observations for trend analysis
        mock_evaluate.return_value = ([], [], {})

        # Case 1: Veg Stage (0 flower days)
        # Threshold > 85%

        # Sub-case 1.1: Veg Safe
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ):
            set_sensor_state(hass, "sensor.humidity", 84)
            set_sensor_state(hass, "sensor.temp", 25)
            set_sensor_state(hass, "switch.fan", "on")  # Circulation on
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            assert not sensor.is_on
            assert sensor._probability < 0.2

        # Sub-case 1.2: Veg Danger
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ):
            set_sensor_state(hass, "sensor.humidity", 86)
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            # 86% RH -> High Humidity -> Prob increases to ~0.3
            assert sensor._probability > 0.25
            assert any("High Humidity" in r[1] for r in sensor._reasons)

        # Case 2: Early Flower (10 flower days)
        # Threshold > 70%

        # Sub-case 2.1: Early Flower Safe
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 30, "flower_days": 10},
        ):
            set_sensor_state(hass, "sensor.humidity", 70)
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            assert not sensor.is_on
            assert sensor._probability < 0.2

        # Sub-case 2.2: Early Flower Danger
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 30, "flower_days": 10},
        ):
            set_sensor_state(hass, "sensor.humidity", 71)
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            assert sensor._probability > 0.25
            assert any("High Humidity" in r[1] for r in sensor._reasons)

        # Case 3: Late Flower (45 flower days)
        # Threshold > 60%

        # Sub-case 3.1: Late Flower Safe
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 60, "flower_days": 45},
        ):
            set_sensor_state(hass, "sensor.humidity", 60)
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            assert not sensor.is_on
            assert sensor._probability < 0.2

        # Sub-case 3.2: Late Flower Danger
        with patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 60, "flower_days": 45},
        ):
            set_sensor_state(hass, "sensor.humidity", 61)
            await hass.async_block_till_done()

            await sensor.async_update_and_notify()
            assert sensor._probability > 0.25
            assert any("High Humidity" in r[1] for r in sensor._reasons)


@pytest.mark.asyncio
async def test_veg_stage_scenario_false_positive_prevention(
    hass: HomeAssistant, mock_coordinator, env_config
) -> None:
    """
    Verify that in a Veg Stage scenario (e.g., 22.7°C, 56.8% RH, 0.87 kPa VPD),
    the sensor probability remains low even if trends are "rising" or "falling".
    """
    description = next(
        d for d in SENSOR_TYPES if d.sensor_type == GrowspaceSensorType.MOLD
    )
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold_false_positive"
    sensor.platform = MagicMock()
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    # Set up conditions
    # Veg Stage
    # Temp: 22.7°C
    # RH: 56.8%
    # VPD: 0.87 kPa

    set_sensor_state(hass, "sensor.temp", 22.7)
    set_sensor_state(hass, "sensor.humidity", 56.8)
    set_sensor_state(hass, "sensor.vpd", 0.87)
    set_sensor_state(hass, "switch.fan", "on")  # Circulation on
    set_sensor_state(hass, "sensor.co2", 600)
    await hass.async_block_till_done()

    # Mock trends: rising Humidity, falling VPD
    # We expect rising humidity to be IGNORED in the new logic
    # We expect falling VPD to be ignored because 0.87 > 0.5 (Veg danger zone)

    # We need to mock 'async_analyze_sensor_trend' if it's called
    # BUT the refactor uses the real implementation of 'async_evaluate_mold_risk_trend'
    # which calls 'sensor_instance.async_analyze_sensor_trend'.

    async def mock_analyze(sensor_id, duration, threshold):
        if "humidity" in sensor_id:
            return {"trend": "rising", "crossed_threshold": True}
        if "vpd" in sensor_id:
            return {"trend": "falling", "crossed_threshold": True}
        return {"trend": "stable", "crossed_threshold": False}

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ),
        patch.object(sensor, "async_analyze_sensor_trend", side_effect=mock_analyze),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()

        # Check reasons
        reasons_text = [r[1] for r in sensor._reasons]

        # Assertions
        assert not sensor.is_on, (
            f"Sensor turned ON unexpectedly. Prob: {sensor._probability}"
        )

        # Ensure Humidity Trend is NOT in reasons (it should be ignored)
        assert not any("Humidity trend" in r for r in reasons_text)

        # Ensure VPD Trend is NOT in reasons (it should be ignored because 0.87 > 0.5)
        # Note: Logic is "falling" trend check.
        # In `_async_evaluate_fallback_mold_trend_analysis`:
        # if stage.vpd < danger_zone:
        # danger_zone for Veg is 0.5. Current VPD is 0.87. So check fails. No observation added.
        assert not any("VPD trend" in r for r in reasons_text)

        # Ensure probability is close to prior (0.10)
        assert sensor._probability < 0.15


@pytest.mark.asyncio
async def test_user_reported_veg_scenario(
    hass: HomeAssistant, mock_coordinator, env_config
) -> None:
    """
    Verify the user reported scenario: 24.2°C, 64% RH, 0.75 kPa VPD, Veg day 34.
    The sensor should NOT have a high probability.
    """
    description = next(
        d for d in SENSOR_TYPES if d.sensor_type == GrowspaceSensorType.MOLD
    )
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold_user_scenario"
    sensor.platform = MagicMock()
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    # User scenario: 24.2°C, 64% RH, 0.75 kPa VPD, Veg day 34.
    set_sensor_state(hass, "sensor.temp", 24.2)
    set_sensor_state(hass, "sensor.humidity", 64.0)
    set_sensor_state(hass, "sensor.vpd", 0.75)
    set_sensor_state(
        hass, "switch.fan", "off"
    )  # Let's assume fan is off to see if it triggers
    set_sensor_state(
        hass, "humidifier.humidifier", "on"
    )  # Let's assume humidifier is on
    # Add a mock humidifier value sensor if needed
    set_sensor_state(hass, "sensor.humidifier_value", 50.0)
    env_config.humidifier_entities = ["sensor.humidifier_value"]

    await hass.async_block_till_done()

    async def mock_analyze(sensor_id, duration, threshold):
        if "vpd" in sensor_id:
            return {"trend": "falling", "crossed_threshold": True}
        return {"trend": "stable", "crossed_threshold": False}

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 34, "flower_days": 0},
        ),
        patch.object(sensor, "async_analyze_sensor_trend", side_effect=mock_analyze),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()

        [r[1] for r in sensor._reasons]

        # If it's > 0.75 (default threshold), it's ON.
        # User says it's 90%.
        assert sensor._probability < 0.75


@pytest.mark.asyncio
async def test_veg_fan_off_safe(
    hass: HomeAssistant, mock_coordinator, env_config
) -> None:
    """Test that Fan Off in Veg with low humidity does NOT trigger risk."""
    description = next(
        d for d in SENSOR_TYPES if d.sensor_type == GrowspaceSensorType.MOLD
    )
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_veg_fan_safe"
    sensor.platform = MagicMock()
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 50)  # Low/Safe
    set_sensor_state(hass, "switch.fan", "off")
    set_sensor_state(hass, "sensor.vpd", 1.0)
    await hass.async_block_till_done()

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()

    assert not sensor.is_on
    # Check reasons
    reasons = [r[1] for r in sensor._reasons]
    assert not any("Circulation Fan Off" in r for r in reasons)


@pytest.mark.asyncio
async def test_veg_fan_off_risk(
    hass: HomeAssistant, mock_coordinator, env_config
) -> None:
    """Test that Fan Off in Veg with HIGH humidity DOES trigger risk."""
    description = next(
        d for d in SENSOR_TYPES if d.sensor_type == GrowspaceSensorType.MOLD
    )
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_veg_fan_risk"
    sensor.platform = MagicMock()
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification = AsyncMock()

    set_sensor_state(hass, "sensor.temp", 25)
    set_sensor_state(hass, "sensor.humidity", 85)  # High
    set_sensor_state(hass, "switch.fan", "off")
    set_sensor_state(hass, "sensor.vpd", 1.0)
    await hass.async_block_till_done()

    with (
        patch.object(
            sensor,
            "_get_growth_stage_info",
            return_value={"veg_days": 20, "flower_days": 0},
        ),
        patch.object(sensor, "async_write_ha_state", new_callable=MagicMock),
    ):
        await sensor.async_update_and_notify()

    # Probability might be high enough?
    # Fan Off (0.85/0.15) -> Odds ~ 5.6
    # Prior 0.1 -> Odds 0.11
    # Posterior Odds ~ 0.6 -> Prob ~ 0.37 (Not ON if thresh 0.75)
    # But "Circulation Fan Off" should be in reasons.

    reasons = [r[1] for r in sensor._reasons]
    assert any("Circulation Fan Off" in r for r in reasons)
