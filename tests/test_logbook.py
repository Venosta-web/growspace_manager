"""Tests for the Bayesian Event Logbook feature."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager.binary_sensor import BayesianEnvironmentSensor
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, GrowspaceEvent


# --- Fixtures ---
@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    coord = MagicMock(spec=GrowspaceCoordinator)
    coord.hass = hass
    coord.growspaces = {"gs1": Growspace(id="gs1", name="Test Growspace")}
    coord.events = {}
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


# --- 2. Test Coordinator Rolling Buffer ---
async def test_coordinator_rolling_buffer(hass: HomeAssistant) -> None:
    # Setup real coordinator partially or mock add_event if complex,
    # but we want to test the add_event logic so lets use a real-ish coordinator
    # However instantiating full coordinator is heavy.
    # Let's mock the class but use the real add_event method unbound?
    # Or proper instantiation with mocks.

    coordinator = GrowspaceCoordinator(hass)
    coordinator.storage_manager = MagicMock()
    coordinator.async_save = MagicMock()  # Mock save to avoid internal logic

    # Test adding 55 events
    gid = "gs1"
    for i in range(55):
        event = GrowspaceEvent(
            sensor_type="stress",
            growspace_id=gid,
            start_time=f"2023-01-01T{i:02}:00:00",
            end_time="2023-01-01T00:00:00",
            duration_sec=10,
            severity=0.8,
            category="alert",
            reasons=[],
        )
        coordinator.add_event(gid, event)

    assert len(coordinator.events[gid]) == 50
    # The first 5 should be gone (0-4), so the first one should be index 5
    assert coordinator.events[gid][0].start_time == "2023-01-01T05:00:00"


# --- 3. Test Sensor Event Capture ---
async def test_sensor_event_capture(hass: HomeAssistant, mock_coordinator) -> None:
    env_config = {
        "prior_mold": 0.5,
        "mold_threshold": 0.8,
        # ... other config needed for base class?
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
    }

    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        "gs1",
        env_config,
        "mold_risk",
        "Mold Risk",
        "prior_mold",
        "mold_threshold",
    )

    # Mock update probability logic to control is_on
    sensor._async_update_probability = MagicMock()
    sensor._async_update_probability.side_effect = (
        None  # ensure it's not raising if previously set
    )

    sensor._async_update_probability = AsyncMock()

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
