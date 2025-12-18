"""Tests for the EnvironmentAnalyzer."""

from unittest.mock import MagicMock

import pytest
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.const import (
    DEFAULT_FLOWER_EARLY_DAYS,
)
from custom_components.growspace_manager.environment_analyzer import EnvironmentAnalyzer
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace


@pytest.fixture
def mock_coordinator():
    """Mock the GrowspaceCoordinator."""
    coord = MagicMock()
    coord.growspaces = {}
    coord.options = {}
    coord.data = {}
    return coord


@pytest.fixture
def analyzer(hass: HomeAssistant, mock_coordinator):
    """Return an EnvironmentAnalyzer instance."""
    return EnvironmentAnalyzer(hass, mock_coordinator)


@pytest.fixture
def mock_growspace():
    """Return a mock Growspace."""
    gs = MagicMock(spec=Growspace)
    gs.id = "test_growspace"
    gs.environment_config = MagicMock(spec=EnvironmentConfig)
    gs.environment_config.light_sensor = "sensor.light"
    gs.environment_config.vpd_sensor = "sensor.vpd"
    return gs


def test_determine_granular_stage(analyzer: EnvironmentAnalyzer):
    """Test determining the granular growth stage."""
    # Cure
    assert analyzer.determine_granular_stage(0, 0, 0, 5) == "cure"
    # Dry
    assert analyzer.determine_granular_stage(0, 0, 5, 0) == "dry"
    # Flower Early
    assert (
        analyzer.determine_granular_stage(0, DEFAULT_FLOWER_EARLY_DAYS, 0, 0)
        == "flower_early"
    )
    # Flower Mid
    assert (
        analyzer.determine_granular_stage(0, DEFAULT_FLOWER_EARLY_DAYS + 5, 0, 0)
        == "flower_mid"
    )
    # Flower Late
    assert (
        analyzer.determine_granular_stage(0, DEFAULT_FLOWER_EARLY_DAYS + 30, 0, 0)
        == "flower_late"
    )
    # Veg Early
    assert analyzer.determine_granular_stage(10, 0, 0, 0) == "veg"
    # Veg Late
    assert analyzer.determine_granular_stage(30, 0, 0, 0) == "veg"
    # Default Veg Early (all 0)
    assert analyzer.determine_granular_stage(0, 0, 0, 0) == "veg"


def test_determine_is_day(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_growspace
):
    """Test determining if it is day or night."""
    # Setup light sensor state
    hass.states.async_set("sensor.light", STATE_ON)
    assert analyzer.determine_is_day(mock_growspace) is True

    hass.states.async_set("sensor.light", "off")
    assert analyzer.determine_is_day(mock_growspace) is False

    hass.states.async_set("sensor.light", "100.0")
    assert analyzer.determine_is_day(mock_growspace) is True

    hass.states.async_set("sensor.light", "0.0")
    assert analyzer.determine_is_day(mock_growspace) is False  # 0.0 is False

    # No sensor config
    mock_growspace.environment_config.light_sensor = None
    assert analyzer.determine_is_day(mock_growspace) is True


def test_calculate_biological_metrics(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_growspace
):
    """Test calculating biological metrics."""
    # Mock sensor values
    hass.states.async_set("sensor.vpd", "1.0")
    hass.states.async_set("sensor.light", "on")  # Day

    # Veg Early Day
    metrics = analyzer.calculate_biological_metrics(mock_growspace, 5, 0, 0, 0)
    assert metrics["granular_stage"] == "veg"
    assert metrics["is_day"] is True
    # veg_early day mild is (0.4, 0.8), stress is (0.3, 1.0).
    # 1.0 is > 0.8 (target max) but <= 1.0 (danger max). So warning.
    assert metrics["vpd_status"] == "warning"

    # Test Danger
    hass.states.async_set("sensor.vpd", "1.5")  # > 1.0
    metrics = analyzer.calculate_biological_metrics(mock_growspace, 5, 0, 0, 0)
    assert metrics["vpd_status"] == "danger"
