"""Tests for the EnvironmentAnalyzer."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DEFAULT_FLOWER_EARLY_DAYS
from custom_components.growspace_manager.domain.stage import (
    BayesianStage,
    StageDays,
    classify_stages,
)
from custom_components.growspace_manager.environment_analyzer import EnvironmentAnalyzer
from custom_components.growspace_manager.models import EnvironmentConfig
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant


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
    gs = MagicMock()
    gs.id = "test_growspace"
    gs.environment_config = MagicMock(spec=EnvironmentConfig)
    gs.environment_config.light_sensors = ["sensor.light"]
    gs.environment_config.vpd_sensor = "sensor.vpd"
    gs.environment_config.vpd_sensors = []
    gs.environment_config.temperature_sensors = []
    gs.environment_config.humidity_sensors = []
    gs.environment_config.minimum_source_air_temperature = 18.0
    return gs


def test_classify_stages_display_stage_via_domain() -> None:
    """Test that classify_stages produces the correct display_stage for all branches."""
    assert classify_stages(StageDays(cure=5)).display_stage == BayesianStage.CURE
    assert classify_stages(StageDays(dry=5)).display_stage == BayesianStage.DRY
    assert (
        classify_stages(StageDays(flower=10)).display_stage
        == BayesianStage.FLOWER_EARLY
    )
    assert (
        classify_stages(StageDays(flower=DEFAULT_FLOWER_EARLY_DAYS + 5)).display_stage
        == BayesianStage.FLOWER_MID
    )
    assert (
        classify_stages(StageDays(flower=DEFAULT_FLOWER_EARLY_DAYS + 30)).display_stage
        == BayesianStage.FLOWER_LATE
    )
    assert classify_stages(StageDays(veg=10)).display_stage == BayesianStage.VEG
    assert (
        classify_stages(StageDays(seedling=5)).display_stage == BayesianStage.SEEDLING
    )
    assert classify_stages(StageDays(clone=5)).display_stage == BayesianStage.CLONE
    assert classify_stages(StageDays()).display_stage == BayesianStage.EMPTY


def test_determine_is_day(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_growspace
) -> None:
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
    mock_growspace.environment_config.light_sensors = []
    assert analyzer.determine_is_day(mock_growspace) is True


def test_calculate_biological_metrics(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_growspace
) -> None:
    """Test calculating biological metrics."""
    # Mock sensor values
    hass.states.async_set("sensor.vpd", "1.3")
    hass.states.async_set("sensor.light", "on")  # Day

    veg_days = StageDays(veg=5)

    # Veg Day
    metrics = analyzer.calculate_biological_metrics(mock_growspace, veg_days)
    assert metrics["granular_stage"] == BayesianStage.VEG
    assert metrics["is_day"] is True
    # veg day mild is (0.6, 1.2), stress is (0.4, 1.4).
    # 1.3 is > 1.2 (mild max) but <= 1.4 (stress max). So warning.
    assert metrics["vpd_status"] == "warning"

    # Verify Day/Night targets are exposed
    assert "day_vpd_target_min" in metrics
    assert "day_vpd_target_max" in metrics
    assert "night_vpd_target_min" in metrics
    assert "night_vpd_target_max" in metrics
    assert metrics["day_vpd_target_min"] == 0.6  # veg mild min
    assert metrics["day_vpd_target_max"] == 1.2  # veg mild max

    # Test Danger
    hass.states.async_set("sensor.vpd", "1.5")
    metrics = analyzer.calculate_biological_metrics(mock_growspace, veg_days)
    assert metrics["vpd_status"] == "danger"

    # Test Optimal
    hass.states.async_set("sensor.vpd", "0.6")
    metrics = analyzer.calculate_biological_metrics(mock_growspace, veg_days)
    assert metrics["vpd_status"] == "optimal"

    # Empty growspace: VPD monitoring off regardless of sensor value
    hass.states.async_set("sensor.vpd", "9.9")
    metrics = analyzer.calculate_biological_metrics(mock_growspace, StageDays())
    assert metrics["granular_stage"] == BayesianStage.EMPTY
    assert metrics["vpd_status"] == "unknown"
    assert metrics["vpd_target_min"] is None


def test_determine_is_day_invalid_state(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_growspace
) -> None:
    """Test determine_is_day with invalid state."""
    # Invalid float
    hass.states.async_set("sensor.light", "invalid_float")
    # Should catch ValueError and return True (default)
    assert analyzer.determine_is_day(mock_growspace) is True


def test_get_sensor_value_exceptions(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer
) -> None:
    """Test _get_sensor_value exception handling."""
    hass.states.async_set("sensor.test", "invalid_numeric")
    assert analyzer._get_sensor_value("sensor.test") is None
    assert analyzer._get_sensor_value(None) is None
    assert analyzer._get_sensor_value("") is None
    # Test unknown state (Line 252)
    hass.states.async_set("sensor.unknown", "unknown")
    assert analyzer._get_sensor_value("sensor.unknown") is None
    # Test missing entity (Line 252)
    assert analyzer._get_sensor_value("sensor.missing") is None


def test_get_aggregated_sensor_value_edge_cases(analyzer: EnvironmentAnalyzer) -> None:
    """Test edge cases for _get_aggregated_sensor_value."""
    # No sensor IDs (Line 257)
    assert analyzer._get_aggregated_sensor_value([]) is None

    # Sensor IDs provided but no values returned (Line 266)
    with patch.object(analyzer, "_get_sensor_value", return_value=None):
        assert analyzer._get_aggregated_sensor_value(["sensor.v1", "sensor.v2"]) is None


def test_calculate_recommendation_missing_growspace(
    analyzer: EnvironmentAnalyzer, mock_coordinator
) -> None:
    """Test recommendation when growspace not found."""
    # mock_coordinator.growspaces empty by default fixture
    res = analyzer._calculate_recommendation(
        "invalid_id", 1.0, 1.0, 25.0, 1.0, 25.0, 1.0
    )
    assert res == "Idle"

    res = analyzer._calculate_recommendation("gs1", None, 1.0, 25.0, 1.0, 25.0, 1.0)
    assert res == "Idle"


@pytest.mark.asyncio
async def test_async_update_air_exchange_recommendations_branches(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_coordinator, mock_growspace
) -> None:
    """Test branches in async_update_air_exchange_recommendations."""
    mock_coordinator.growspaces["gs1"] = mock_growspace
    mock_coordinator.options = {"global_settings": {}}  # No sensors

    # Mock stress sensor missing
    # entity_registry.async_get will fail or return None if not mocked?
    # Actually entity_registry relies on helper.
    # We can mock async_get_entity_id on the registry if we mock the helper call.
    # But simpler: ensure hass.states.get returns None or off.

    # 1. Stress sensor entity ID not found (default real behavior if not registered)
    # But loop uses async_get_entity_id. If not exists, it returns None.
    # We need to mock er.async_get(hass).

    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.return_value = None

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        await analyzer.async_update_air_exchange_recommendations()
        assert (
            analyzer.coordinator.data["air_exchange_recommendations"]["gs1"] == "Idle"
        )

    # 2. Stress sensor found but state not "on"
    mock_registry.async_get_entity_id.return_value = "binary_sensor.stress"
    hass.states.async_set("binary_sensor.stress", "off")

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        await analyzer.async_update_air_exchange_recommendations()
        assert (
            analyzer.coordinator.data["air_exchange_recommendations"]["gs1"] == "Idle"
        )


def test_calculate_recommendation_logic(
    analyzer: EnvironmentAnalyzer, mock_coordinator, mock_growspace
) -> None:
    """Test detailed recommendation logic."""
    mock_coordinator.growspaces["gs1"] = mock_growspace
    mock_growspace.environment_config.minimum_source_air_temperature = (
        20.0  # Min temp constraint
    )

    # Target VPD = 1.0. Current = 0.5 (Need to increase/decrease? 0.5 diff).

    # 1. Idle because outside/lung unset or too cold
    res = analyzer._calculate_recommendation("gs1", 0.5, 1.0, None, None, None, None)
    assert res == "Idle"

    # 2. Open Window (Outside VPD = 0.9 (diff 0.1), Temp = 25 (>20))
    res = analyzer._calculate_recommendation("gs1", 0.5, 1.0, 25.0, 0.9, None, None)
    assert res == "Open Window"

    # 3. Ventilate Lung Room (Lung VPD = 0.95 (diff 0.05), Temp = 25) - Lung is better than Outside (0.9)
    res = analyzer._calculate_recommendation("gs1", 0.5, 1.0, 25.0, 0.9, 25.0, 0.95)
    assert res == "Ventilate Lung Room"

    # 4. Outside too cold (Temp 10 < 20), even if VPD matches perfectly (1.0)
    res = analyzer._calculate_recommendation("gs1", 0.5, 1.0, 10.0, 1.0, None, None)
    assert res == "Idle"


@pytest.mark.asyncio
async def test_async_update_air_exchange_full_flow(
    hass: HomeAssistant, analyzer: EnvironmentAnalyzer, mock_coordinator, mock_growspace
) -> None:
    """Test full flow of async_update_air_exchange_recommendations."""
    mock_coordinator.growspaces["gs1"] = mock_growspace
    mock_growspace.environment_config.vpd_sensor = "sensor.vpd"

    # Global settings
    mock_coordinator.options = {
        "global_settings": {
            "weather_entity": "weather.home",
            "lung_room_temp_sensor": "sensor.lung_temp",
            "lung_room_humidity_sensor": "sensor.lung_hum",
        }
    }
    mock_coordinator.data = {
        "serialized_growspaces": {
            "gs1": {"metrics": {"vpd_target_min": 0.9, "vpd_target_max": 1.1}}
        }
    }

    # Mock sensors
    hass.states.async_set("sensor.vpd", "0.5")  # Current VPD
    hass.states.async_set("sensor.lung_temp", "25.0")
    hass.states.async_set("sensor.lung_hum", "60.0")  # Calc VPD ~?

    # Mock weather
    hass.states.async_set(
        "weather.home", "sunny", {"temperature": 25.0, "humidity": 60.0}
    )

    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.return_value = "binary_sensor.stress"
    hass.states.async_set("binary_sensor.stress", "on")

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        await analyzer.async_update_air_exchange_recommendations()

        # Should have run calculation and stored result
        assert "gs1" in analyzer.coordinator.data["air_exchange_recommendations"]
        assert analyzer.coordinator.data["air_exchange_recommendations"]["gs1"] in [
            "Idle",
            "Open Window",
            "Ventilate Lung Room",
        ]
