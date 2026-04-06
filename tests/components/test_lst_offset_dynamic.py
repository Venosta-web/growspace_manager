"""Tests for dynamic LST offset logic in VPD calculations."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
)
from custom_components.growspace_manager.sensor import CalculatedVpdSensor
from custom_components.growspace_manager.utils import VPDCalculator
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass():
    """Mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


def test_calculated_vpd_sensor_dynamic_offset(mock_coordinator, mock_hass) -> None:
    """Test CalculatedVpdSensor applies 0.0 offset for dry/cure stages."""

    # Setup mock states for temp/humidity
    temp_state = MagicMock()
    temp_state.state = "25.0"
    humidity_state = MagicMock()
    humidity_state.state = "60.0"

    def side_effect(entity_id):
        if entity_id == "sensor.temp":
            return temp_state
        if entity_id == "sensor.humidity":
            return humidity_state
        return None

    mock_hass.states.get.side_effect = side_effect
    mock_coordinator.hass = mock_hass

    # 1. Test with FLOWER stage (should use configured offset -2.0)
    gs_flower = Growspace(
        id="gs1",
        name="Flower Room",
        growspace_type=GrowspaceType.FLOWER,
        environment_config=EnvironmentConfig(lst_offset=-2.0),
    )
    # Ensure coordinator has the growspace
    mock_coordinator.growspaces = {"gs1": gs_flower}

    sensor = CalculatedVpdSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace_name="Flower Room",
        temp_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        lst_offset=-2.0,
    )
    sensor.hass = mock_hass

    # Calculate expected VPD for 25C, 60% RH, -2.0 offset
    expected_flower_vpd = VPDCalculator.calculate_vpd_with_lst_offset(25.0, 60.0, -2.0)

    assert sensor.native_value == pytest.approx(expected_flower_vpd)
    assert sensor.extra_state_attributes["lst_offset"] == -2.0

    # 2. Test with DRY stage (should override to 0.0 offset)
    gs_dry = Growspace(
        id="gs1",
        name="Dry Room",
        growspace_type=GrowspaceType.DRY,
        environment_config=EnvironmentConfig(lst_offset=-2.0),
    )
    mock_coordinator.growspaces = {"gs1": gs_dry}

    # Calculate expected VPD for 25C, 60% RH, 0.0 offset (DRY override)
    expected_dry_vpd = VPDCalculator.calculate_vpd_with_lst_offset(25.0, 60.0, 0.0)

    assert sensor.native_value == pytest.approx(expected_dry_vpd)
    assert sensor.extra_state_attributes["lst_offset"] == 0.0
    assert sensor.extra_state_attributes["configured_lst_offset"] == -2.0

    # 3. Test with CURE stage (should override to 0.0 offset)
    gs_cure = Growspace(
        id="gs1",
        name="Cure Room",
        growspace_type=GrowspaceType.CURE,
        environment_config=EnvironmentConfig(lst_offset=-2.0),
    )
    mock_coordinator.growspaces = {"gs1": gs_cure}

    assert sensor.native_value == pytest.approx(
        expected_dry_vpd
    )  # Same as dry (0.0 offset)
    assert sensor.extra_state_attributes["lst_offset"] == 0.0


def test_bayesian_sensor_fallback_vpd_dynamic_offset(
    mock_coordinator, mock_hass
) -> None:
    """Test BayesianEnvironmentSensor fallback VPD uses 0.0 offset for dry/cure."""

    # Setup mock states
    temp_state = MagicMock()
    temp_state.state = "20.0"
    humidity_state = MagicMock()
    humidity_state.state = "60.0"

    mock_hass.states.get.side_effect = lambda eid: {
        "sensor.temp": temp_state,
        "sensor.humidity": humidity_state,
    }.get(eid)
    mock_coordinator.hass = mock_hass

    # 1. Setup Flower Growspace
    env_config_flower = EnvironmentConfig(
        temperature_sensors=["sensor.temp"],
        humidity_sensors=["sensor.humidity"],
        lst_offset=-2.0,
    )
    gs_flower = Growspace(
        id="gs1",
        name="Flower Room",
        growspace_type=GrowspaceType.FLOWER,
        environment_config=env_config_flower,
    )
    mock_coordinator.growspaces = {"gs1": gs_flower}

    description = SENSOR_TYPES[0]  # Stress sensor
    sensor = BayesianEnvironmentSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        env_config=env_config_flower,
        description=description,
        strategy_class=MagicMock(),
        get_growspace=lambda eid: mock_coordinator.growspaces.get(eid),
        get_plants=lambda eid: [],
        add_event=MagicMock(),
        notification_manager=None,
        strain_library=None,
        options={},
    )
    sensor.hass = mock_hass

    # Patch _get_growth_stage_info and others to avoid complex logic
    sensor._get_growth_stage_info = MagicMock(return_value={})
    sensor._determine_light_state = MagicMock(return_value=True)
    sensor._determine_fan_state = MagicMock(return_value=False)
    sensor._determine_dehumidifier_state = MagicMock(return_value=False)
    sensor._determine_exhaust_value = MagicMock(return_value=0.0)
    sensor._determine_humidifier_value = MagicMock(return_value=0.0)
    sensor._determine_humidifier_state = MagicMock(return_value=False)
    sensor._get_sensor_value = MagicMock(return_value=None)
    sensor._get_aggregated_sensor_value = MagicMock(return_value=None)

    # Force using aggregated value helper to return our mock states
    def mock_agg(sensors):
        if "sensor.temp" in sensors:
            return 20.0
        if "sensor.humidity" in sensors:
            return 60.0
        return None

    sensor._get_aggregated_sensor_value.side_effect = mock_agg

    state = sensor._get_base_environment_state()
    expected_flower_vpd = VPDCalculator.calculate_vpd_with_lst_offset(20.0, 60.0, -2.0)
    assert state.vpd == pytest.approx(expected_flower_vpd)
    assert sensor._sensor_states["lst_offset"] == -2.0

    # 2. Setup Dry Growspace
    gs_dry = Growspace(
        id="gs1",
        name="Dry Room",
        growspace_type=GrowspaceType.DRY,
        environment_config=EnvironmentConfig(
            temperature_sensors=["sensor.temp"],
            humidity_sensors=["sensor.humidity"],
            lst_offset=-2.0,
        ),
    )
    mock_coordinator.growspaces = {"gs1": gs_dry}

    state = sensor._get_base_environment_state()
    expected_dry_vpd = VPDCalculator.calculate_vpd_with_lst_offset(20.0, 60.0, 0.0)
    assert state.vpd == pytest.approx(expected_dry_vpd)
    assert sensor._sensor_states["lst_offset"] == 0.0
