"""Tests for serializers coverage gaps."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.serializers import GrowspaceSerializer


@pytest.fixture
def serializer(hass: HomeAssistant):
    """Return a serializer instance."""
    return GrowspaceSerializer(hass)


def test_deserialize_irrigation_config_veg_hours(
    serializer: GrowspaceSerializer,
) -> None:
    """Test sanitization of veg_day_hours in irrigation config."""
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "irrigation_config": {
                "veg_day_hours": "18",  # String to be converted to int
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)
    gs = growspaces["gs1"]

    # Line 153 coverage
    assert gs.irrigation_config.veg_day_hours == 18


def test_deserialize_irrigation_strategy_dict_sanitization(
    serializer: GrowspaceSerializer,
) -> None:
    """Test sanitization of irrigation strategy when provided as a dict."""
    # This covers lines 185-194 in _sanitize_irrigation_strategy
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "irrigation_strategy": {
                "p0_duration_minutes": "5",
                "p2_stop_before_lights_off_minutes": "120.0",
                "shot_duration_seconds": "15",
                "shot_interval_minutes": 30,
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)
    gs = growspaces["gs1"]

    strat = gs.irrigation_strategy
    # Verify values were sanitized/converted and loaded into the object
    assert strat.p0_duration_minutes == 5
    assert strat.p2_stop_before_lights_off_minutes == 120
    assert strat.shot_duration_seconds == 15
    assert strat.shot_interval_minutes == 30
