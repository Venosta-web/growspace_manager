"""Tests for EntityRegistry queries and sensor lookups."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.presentation.entity_queries import (
    EntityQueries,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant


@pytest.fixture
def entity_queries(hass: HomeAssistant) -> EntityQueries:
    """Fixture for EntityQueries."""
    return EntityQueries(hass)


def test_lookup_plant_entity_id(hass: HomeAssistant) -> None:
    """Test looking up plant entity ID."""
    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get:
        mock_er = MagicMock()
        mock_er_get.return_value = mock_er
        mock_er.async_get_entity_id.return_value = "sensor.plant_1"

        eq = EntityQueries(hass)
        assert eq.lookup_plant_entity_id("p1") == "sensor.plant_1"
        mock_er.async_get_entity_id.assert_called_once_with(
            "sensor", DOMAIN, f"{DOMAIN}_p1"
        )


def test_lookup_overview_entity_id(hass: HomeAssistant) -> None:
    """Test looking up overview entity ID."""
    with patch("homeassistant.helpers.entity_registry.async_get") as mock_er_get:
        mock_er = MagicMock()
        mock_er_get.return_value = mock_er
        eq = EntityQueries(hass)

        # Registry match
        mock_er.async_get_entity_id.return_value = "sensor.overview_1"
        assert eq.lookup_overview_entity_id("gs1") == "sensor.overview_1"

        # Fallback for special growspaces
        mock_er.async_get_entity_id.return_value = None
        assert eq.lookup_overview_entity_id("mother") == "sensor.mother"
        assert eq.lookup_overview_entity_id("clone") == "sensor.clone"
        assert eq.lookup_overview_entity_id("dry") == "sensor.dry"
        assert eq.lookup_overview_entity_id("cure") == "sensor.cure"

        # Not found
        assert eq.lookup_overview_entity_id("unknown") is None


def test_get_sensor_value(hass: HomeAssistant, entity_queries: EntityQueries) -> None:
    """Test getting numeric sensor value."""
    # Valid value
    hass.states.async_set("sensor.test", "12.3")
    assert entity_queries.get_sensor_value("sensor.test") == 12.3

    # Unknown state
    hass.states.async_set("sensor.test", STATE_UNKNOWN)
    assert entity_queries.get_sensor_value("sensor.test") is None

    # Unavailable state
    hass.states.async_set("sensor.test", STATE_UNAVAILABLE)
    assert entity_queries.get_sensor_value("sensor.test") is None

    # Invalid value
    hass.states.async_set("sensor.test", "abc")
    assert entity_queries.get_sensor_value("sensor.test") is None

    # No sensor ID
    assert entity_queries.get_sensor_value(None) is None


def test_get_sensor_state(hass: HomeAssistant, entity_queries: EntityQueries) -> None:
    """Test getting raw sensor state."""
    # Valid state
    hass.states.async_set("sensor.test", "on")
    assert entity_queries.get_sensor_state("sensor.test") == "on"

    # Invalid states
    hass.states.async_set("sensor.test", STATE_UNKNOWN)
    assert entity_queries.get_sensor_state("sensor.test") is None

    # No sensor ID
    assert entity_queries.get_sensor_state(None) is None


def test_parse_tank_level(entity_queries: EntityQueries) -> None:
    """Test parsing tank level strings."""
    assert entity_queries.parse_tank_level("50.5 %") == 50.5
    assert entity_queries.parse_tank_level("50,2 %") == 50.2
    assert entity_queries.parse_tank_level("75") == 75.0
    assert entity_queries.parse_tank_level("") is None
    assert entity_queries.parse_tank_level(None) is None
    assert entity_queries.parse_tank_level("abc") is None
    # Test numeric input
    assert entity_queries.parse_tank_level(45.5) == 45.5
