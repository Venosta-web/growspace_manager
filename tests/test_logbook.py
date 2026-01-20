"""Tests for the Bayesian Event Logbook feature."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, GrowspaceEvent
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


# --- Fixtures ---
@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    coord = MagicMock(spec=GrowspaceCoordinator)
    coord.hass = hass
    coord.growspaces = {"gs1": Growspace(id="gs1", name="Test Growspace")}
    coord.notification_manager = MagicMock()
    return coord


# --- 1. Test Data Model ---
def test_growspace_event_model() -> None:
    data = {
        "sensor_type": "mold_risk",
        "growspace_id": "gs1",
        "start_time": "2023-10-27T10:00:00+00:00",
        "end_time": "2023-10-27T10:05:00+00:00",
        "duration_sec": 300,
        "severity": 0.95,
        "category": "alert",
        "reasons": ["High Humidity"],
    }
    event = GrowspaceEvent.from_dict(data)
    assert event.sensor_type == "mold_risk"
    assert event.duration_sec == 300
    assert event.severity == 0.95
    assert event.category == "alert"
    assert event.to_dict() == data


# --- 3. Test Sensor Event Capture ---
async def test_sensor_event_capture(hass: HomeAssistant, mock_coordinator) -> None:
    # Create env_config as MagicMock with proper attribute access
    env_config = MagicMock()
    env_config.temperature_sensor = "sensor.temp"
    env_config.humidity_sensor = "sensor.hum"
    env_config.vpd_sensor = None
    env_config.co2_sensor = None
    env_config.circulation_fan_entity = None
    env_config.light_sensor = None
    env_config.soil_moisture_sensor = None
    env_config.dehumidifier_entity = None
    env_config.exhaust_fan_entity = None
    env_config.humidifier_entity = None
    env_config.bayesian_options = MagicMock()
    env_config.bayesian_options.mold_threshold = 0.8
    env_config.bayesian_options.prior_mold_risk = 0.5
    env_config.bayesian_options.stress_threshold = 0.7
    env_config.bayesian_options.prior_stress = 0.15
    env_config.bayesian_options.optimal_threshold = 0.8
    env_config.bayesian_options.prior_optimal = 0.40
    env_config.to_dict.return_value = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
    }

    description = next(d for d in SENSOR_TYPES if d.sensor_type == "mold")
    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        description,
        MoldRiskEvaluatorStrategy,
    )
    sensor.hass = hass
    sensor.entity_id = "binary_sensor.test_mold_logbook"
    sensor.platform = MagicMock()

    # Mock update probability logic to control is_on
    sensor._async_update_probability = MagicMock()  # type: ignore[method-assign]
    sensor._async_update_probability.side_effect = (
        None  # ensure it's not raising if previously set
    )

    sensor._async_update_probability = AsyncMock()  # type: ignore[method-assign]

    # 1. Initial State (Off)
    sensor._probability = 0.5  # Threshold is 0.8
    with patch("custom_components.growspace_manager.binary_sensor.utcnow") as mock_time:
        mock_time.return_value = datetime(2023, 10, 27, 10, 0, 0, tzinfo=dt_util.UTC)
        await sensor.async_update_and_notify()
        assert sensor._event_start_time is None

        # 2. Rising Edge (Off -> On)
        # We need the update method to CHANGE the probability so old_state_on is False and new is True
        async def set_prob_rising():
            sensor._probability = 0.85

        sensor._async_update_probability.side_effect = set_prob_rising
        await sensor.async_update_and_notify()

        assert sensor._event_start_time == datetime(
            2023, 10, 27, 10, 0, 0, tzinfo=dt_util.UTC
        )
        assert sensor._event_max_prob == 0.85

        # 3. Sustained On (Update Max Prob)
        mock_time.return_value = datetime(2023, 10, 27, 10, 5, 0, tzinfo=dt_util.UTC)

        async def set_prob_high():
            sensor._probability = 0.95

        sensor._async_update_probability.side_effect = set_prob_high
        await sensor.async_update_and_notify()
        assert sensor._event_max_prob == 0.95

        # 4. Falling Edge (On -> Off)
        mock_time.return_value = datetime(
            2023, 10, 27, 10, 10, 0, tzinfo=dt_util.UTC
        )  # 10 mins duration

        async def set_prob_low():
            sensor._probability = 0.4

        sensor._async_update_probability.side_effect = set_prob_low
        await sensor.async_update_and_notify()

        # Verify event created and added
        assert sensor._event_start_time is None
        assert sensor._event_max_prob == 0.0

        mock_coordinator.add_event.assert_called_once()
        args = mock_coordinator.add_event.call_args[0]
        assert args[0] == "gs1"
        event = args[1]
        assert event.duration_sec == 600  # 10 mins
        assert event.severity == 0.95
        assert event.category == "alert"
