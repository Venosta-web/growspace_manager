"""Tests for the Bayesian Event Logbook feature."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.logbook import async_describe_events
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceEvent,
)
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

# --- Fixtures ---


def create_test_sensor(
    coordinator: MagicMock,
    growspace_id: str,
    sensor_type: str,
    strategy_class: type,
    env_config: EnvironmentConfig | None = None,
) -> BayesianEnvironmentSensor:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    return BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        # Inject dependencies
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
    )


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    coord = MagicMock()
    coord.hass = hass
    coord.growspaces = {"gs1": Growspace(id="gs1", name="Test Growspace")}
    coord._notification_manager = MagicMock()
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

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.STRESS,
        MoldRiskEvaluatorStrategy,
        env_config,
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

        # Rising edge fires one event, falling edge fires another — 2 total
        assert mock_coordinator.add_event.call_count == 2
        # Falling edge event (second call) has the full duration and peak severity
        falling_args = mock_coordinator.add_event.call_args_list[1][0]
        assert falling_args[0] == "gs1"
        event = falling_args[1]
        assert event.duration_sec == 600  # 10 mins
        assert event.severity == 0.95
        assert event.category == "alert"


# --- 4. Test Logbook Event Description ---


@pytest.mark.parametrize(
    ("category", "data", "expected_name", "expected_message"),
    [
        # CATEGORY_NOTE ("note") cases
        (
            "note",
            {"notes": "Test note", "tags": ["tag1", "tag2"], "images": ["img1.jpg"]},
            "Plant Note",
            "Test note [Tags: tag1, tag2 | 1 Image]",
        ),
        (
            "note",
            {
                "notes": "Test note 2",
                "tags": ["tag1"],
                "images": ["img1.jpg", "img2.jpg"],
            },
            "Plant Note",
            "Test note 2 [Tags: tag1 | 2 Images]",
        ),
        (
            "note",
            {"notes": ""},
            "Plant Note",
            "",
        ),
        # Watering cases ("water", "watering", "irrigation")
        (
            "watering",
            {"amount_ml": 500, "recipe": "Recipe A"},
            "Watering",
            "Watered 500ml with Recipe A",
        ),
        (
            "water",
            {"amount_ml": None},
            "Watering",
            "Watered",
        ),
        # Training cases ("training")
        (
            "training",
            {"sensor_type": "low_stress_training", "notes": "Bent stems"},
            "Low Stress Training",
            "Bent stems",
        ),
        (
            "training",
            {},
            "Training",
            "Training performed",
        ),
        # IPM cases ("ipm")
        (
            "ipm",
            {"sensor_type": "ipm_neem_oil", "notes": "Sprayed leaves"},
            "IPM Treatment",
            "Neem Oil: Sprayed leaves",
        ),
        (
            "ipm",
            {"sensor_type": "ipm_treatment"},
            "IPM Treatment",
            "Treatment: Applied",
        ),
        # Dehumidifier cases ("dehumidifier")
        (
            "dehumidifier",
            {"reasons": ["Turned ON", "VPD too low"]},
            "Dehumidifier Control",
            "Turned ON • VPD too low",
        ),
        (
            "dehumidifier",
            {"reasons": ["Turned OFF"]},
            "Dehumidifier Control",
            "Turned OFF",
        ),
        (
            "dehumidifier",
            {},
            "Dehumidifier Control",
            "Controlled",
        ),
        # Humidifier cases ("humidifier")
        (
            "humidifier",
            {"reasons": ["Turned ON", "Humidity too low"]},
            "Humidifier Control",
            "Turned ON • Humidity too low",
        ),
        (
            "humidifier",
            {"reasons": ["Turned OFF"]},
            "Humidifier Control",
            "Turned OFF",
        ),
        (
            "humidifier",
            {},
            "Humidifier Control",
            "Controlled",
        ),
        # Growth Milestone cases ("milestone")
        (
            "milestone",
            {"reasons": ["Stage changed to Veg"]},
            "Growth Milestone",
            "Stage changed to Veg",
        ),
        (
            "milestone",
            {"sensor_type": "veg_stage"},
            "Growth Milestone",
            "veg_stage",
        ),
        (
            "milestone",
            {},
            "Growth Milestone",
            "Milestone reached",
        ),
        # Alert cases ("alert")
        (
            "alert",
            {
                "sensor_type": "mold_risk",
                "reasons": ["High mold probability"],
                "duration_sec": 120,
            },
            "Mold Risk Alert",
            "Mold Risk detected — lasted 2 minutes • High mold probability",
        ),
        (
            "alert",
            {"sensor_type": "heat_stress", "duration_sec": 45},
            "Heat Stress Alert",
            "Heat Stress detected — lasted 45 seconds",
        ),
        (
            "alert",
            {"sensor_type": "mold_risk"},
            "Mold Risk Alert",
            "Mold Risk detected",
        ),
        # Environment cases ("environment")
        (
            "environment",
            {"reasons": ["High VPD"], "duration_sec": 180},
            "Environment Alert",
            "Conditions left optimal range for 3 minutes • High VPD",
        ),
        (
            "environment",
            {"duration_sec": 30},
            "Environment Alert",
            "Conditions left optimal range for 30 seconds",
        ),
        (
            "environment",
            {},
            "Environment Alert",
            "Conditions left optimal range",
        ),
        # Default cases
        (
            "custom_cat",
            {"notes": "Custom notes"},
            "Growspace Custom_Cat",
            "Custom notes",
        ),
        (
            None,
            {"sensor_type": "custom_sensor"},
            "Growspace Event",
            "custom_sensor",
        ),
        (
            None,
            {},
            "Growspace Event",
            "Event recorded",
        ),
    ],
)
def test_async_describe_events(
    hass: HomeAssistant,
    category: str | None,
    data: dict[str, Any],
    expected_name: str,
    expected_message: str,
) -> None:
    """Test that async_describe_events correctly formats all events."""
    mock_async_describe_event = MagicMock()

    # Register the events
    async_describe_events(hass, mock_async_describe_event)

    # Assert registration arguments
    mock_async_describe_event.assert_called_once()
    args = mock_async_describe_event.call_args[0]
    assert args[0] == DOMAIN
    assert args[1] == EVENT_GROWSPACE_LOG_ENTRY
    describe_callback = args[2]
    assert callable(describe_callback)

    # Prepare the event and verify the returned logbook entry
    event_data = dict(data)
    if category is not None:
        event_data["category"] = category

    mock_event = MagicMock()
    mock_event.data = event_data

    result = describe_callback(mock_event)
    assert result[LOGBOOK_ENTRY_NAME] == expected_name
    assert result[LOGBOOK_ENTRY_MESSAGE] == expected_message
