from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import BayesianStressSensor


@pytest.fixture
def mock_growspace():
    """Fixture for a mock growspace with environment config."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
    }
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    # Setup regular growspace
    coordinator.growspaces = {"gs1": mock_growspace}

    # Setup dry growspace
    dry_growspace = MagicMock()
    dry_growspace.name = "Drying Tent"
    dry_growspace.environment_config = mock_growspace.environment_config.copy()
    coordinator.growspaces["dry"] = dry_growspace

    # Setup plants with flowering history
    # Plant that has been flowering for 50 days (Late Flower)
    plant_p1 = MagicMock()
    plant_p1.veg_start = (date.today() - timedelta(days=80)).isoformat()
    plant_p1.flower_start = (date.today() - timedelta(days=50)).isoformat()

    coordinator.plants = {"p1": plant_p1}

    # Mock get_growspace_plants to return this plant for any growspace requested
    coordinator.get_growspace_plants.return_value = [plant_p1]

    def _calculate_days_side_effect(start_date_str):
        if not start_date_str:
            return 0
        dt = date.fromisoformat(start_date_str.split("T")[0])
        return (date.today() - dt).days

    coordinator.calculate_days.side_effect = _calculate_days_side_effect

    return coordinator


def test_get_growth_stage_info_dry_growspace(mock_coordinator) -> None:
    """Test _get_growth_stage_info for 'dry' growspace."""
    # Create sensor for 'dry' growspace
    sensor = BayesianStressSensor(
        mock_coordinator,
        "dry",
        mock_coordinator.growspaces["dry"].environment_config,
    )

    # This calls _get_growth_stage_info internally relies on coordinator.get_growspace_plants
    # We expect it to currently return the actual days (50), effectively failing the desired behavior
    # After the fix, it should return 0.
    info = sensor._get_growth_stage_info()

    # NOTE: This assertion is designed to PASS AFTER the fix.
    # Before the fix, it would be 50.
    assert info["flower_days"] == 0
    assert info["veg_days"] == 0


def test_get_growth_stage_info_cure_growspace(mock_coordinator) -> None:
    """Test _get_growth_stage_info for 'cure' growspace."""
    # Setup cure growspace
    cure_growspace = MagicMock()
    cure_growspace.name = "Curing Jars"
    cure_growspace.environment_config = mock_coordinator.growspaces[
        "gs1"
    ].environment_config.copy()
    mock_coordinator.growspaces["cure"] = cure_growspace

    sensor = BayesianStressSensor(
        mock_coordinator,
        "cure",
        mock_coordinator.growspaces["cure"].environment_config,
    )

    info = sensor._get_growth_stage_info()
    assert info["flower_days"] == 0
    assert info["veg_days"] == 0
