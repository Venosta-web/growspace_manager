from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.models import EnvironmentConfig, GrowspaceType
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)


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
def mock_growspace():
    """Fixture for a mock growspace with environment config."""
    growspace = MagicMock()
    growspace.name = "Test Growspace"
    growspace.growspace_type = GrowspaceType.FLOWER

    # Create env_config as MagicMock with proper attribute access
    env_config = MagicMock()
    env_config.temperature_sensor = "sensor.temp"
    env_config.humidity_sensor = "sensor.humidity"
    env_config.vpd_sensor = "sensor.vpd"
    env_config.co2_sensor = "sensor.co2"
    env_config.circulation_fan_entity = None
    env_config.light_sensor = None
    env_config.soil_moisture_sensor = None
    env_config.dehumidifier_entity = None
    env_config.exhaust_fan_entity = None
    env_config.humidifier_entity = None
    env_config.bayesian_options = MagicMock()
    env_config.bayesian_options.stress_threshold = 0.7
    env_config.bayesian_options.mold_threshold = 0.75
    env_config.bayesian_options.optimal_threshold = 0.8
    env_config.bayesian_options.prior_stress = 0.15
    env_config.bayesian_options.prior_mold_risk = 0.10
    env_config.bayesian_options.prior_optimal = 0.40
    env_config.to_dict.return_value = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
    }
    growspace.environment_config = env_config
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
    dry_growspace.growspace_type = GrowspaceType.DRY
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
    sensor = create_test_sensor(
        mock_coordinator,
        "dry",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["dry"].environment_config,
    )

    # This calls _get_growth_stage_info internally relies on coordinator.get_growspace_plants
    # We expect it to currently return the actual days (50), effectively failing the desired behavior
    # After the fix, it should return 0.
    info = sensor.assembler._growth_stage_info(
        mock_coordinator.growspaces["dry"]
    )


    assert info["flower_days"] == -1
    assert info["veg_days"] == -1


def test_get_growth_stage_info_cure_growspace(mock_coordinator) -> None:
    """Test _get_growth_stage_info for 'cure' growspace."""
    # Setup cure growspace
    cure_growspace = MagicMock()
    cure_growspace.name = "Curing Jars"
    cure_growspace.growspace_type = GrowspaceType.CURE
    cure_growspace.environment_config = mock_coordinator.growspaces[
        "gs1"
    ].environment_config.copy()
    mock_coordinator.growspaces["cure"] = cure_growspace

    sensor = create_test_sensor(
        mock_coordinator,
        "cure",
        GrowspaceSensorType.STRESS,
        StressEvaluatorStrategy,
        mock_coordinator.growspaces["cure"].environment_config,
    )

    info = sensor.assembler._growth_stage_info(
        mock_coordinator.growspaces["cure"]
    )
    assert info["flower_days"] == -1
    assert info["veg_days"] == -1
