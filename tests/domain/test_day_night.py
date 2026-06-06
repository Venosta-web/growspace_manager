"""Tests for DayNightTracker."""

import time
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.domain.day_night import DayNightTracker
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN


@pytest.fixture
def hass() -> MagicMock:
    """Return a minimal mock HomeAssistant instance."""
    return MagicMock()


@pytest.fixture
def tracker() -> DayNightTracker:
    """Return a fresh DayNightTracker for growspace gs1."""
    return DayNightTracker("gs1")


@pytest.mark.parametrize(
    "light_state,expected_day",
    [
        ("1.0", True),
        ("0.0", False),
        (STATE_ON, True),
        (STATE_UNAVAILABLE, True),   # no valid sensors → default True
        (STATE_UNKNOWN, True),       # no valid sensors → default True
    ],
)
def test_determine_reads_light_sensor_state(
    hass: MagicMock,
    tracker: DayNightTracker,
    light_state: str,
    expected_day: bool,
) -> None:
    """determine() reads light sensor state and returns correct bool."""
    hass.states.get.return_value = MagicMock(state=light_state)
    assert tracker.determine(hass, ["sensor.light"]) is expected_day


def test_determine_no_light_sensors_returns_true(
    hass: MagicMock,
    tracker: DayNightTracker,
) -> None:
    """determine() returns True when no light sensors are configured."""
    assert tracker.determine(hass, []) is True
    hass.states.get.assert_not_called()


def test_determine_uses_last_known_when_unavailable(
    hass: MagicMock,
    tracker: DayNightTracker,
) -> None:
    """determine() uses cached state when all sensors are unavailable."""
    tracker._last_known_is_day = False
    hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)
    assert tracker.determine(hass, ["sensor.light"]) is False


def test_determine_or_logic_any_on_returns_true(
    hass: MagicMock,
    tracker: DayNightTracker,
) -> None:
    """determine() returns True if any one sensor is on (OR logic)."""
    hass.states.get.side_effect = lambda eid: {
        "sensor.light1": MagicMock(state="0"),
        "sensor.light2": MagicMock(state="500"),
    }.get(eid)
    assert tracker.determine(hass, ["sensor.light1", "sensor.light2"]) is True


def test_determine_all_off_returns_false(
    hass: MagicMock,
    tracker: DayNightTracker,
) -> None:
    """determine() returns False when all sensors read zero."""
    hass.states.get.return_value = MagicMock(state="0")
    assert tracker.determine(hass, ["sensor.light1", "sensor.light2"]) is False


def test_determine_valid_read_updates_cache_and_clears_timer(
    hass: MagicMock,
    tracker: DayNightTracker,
) -> None:
    """A valid read updates _last_known_is_day and clears _sensors_unavailable_since."""
    tracker._sensors_unavailable_since = time.monotonic() - 100
    hass.states.get.return_value = MagicMock(state="500")
    result = tracker.determine(hass, ["sensor.light"])
    assert result is True
    assert tracker._last_known_is_day is True
    assert tracker._sensors_unavailable_since is None


def test_determine_prolonged_unavailability_logs_warning(
    hass: MagicMock,
    tracker: DayNightTracker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A warning is logged after sensors are unavailable for over 5 minutes."""
    import logging

    tracker._last_known_is_day = True
    tracker._sensors_unavailable_since = time.monotonic() - 400  # > 300 s
    hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)

    with caplog.at_level(logging.WARNING):
        tracker.determine(hass, ["sensor.light"])

    assert any("unavailable" in r.message.lower() for r in caplog.records)
