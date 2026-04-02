from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.models import EnvironmentConfig, GrowspaceType
from custom_components.growspace_manager.strategies.optimal import (
    OptimalConditionsEvaluatorStrategy,
)
from homeassistant.core import HomeAssistant


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
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.hass = MagicMock(spec=HomeAssistant)
    coordinator.growspaces = {}
    coordinator.data = {}
    return coordinator


@pytest.mark.asyncio
async def test_minimal_sensor_vpd_calculation(mock_coordinator) -> None:
    """Test that VPD is calculated when missing from config but temp/humidity exist."""

    # 1. Setup Environment with only Temp & Humidity
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        vpd_sensor=None,  # No VPD sensor configured
    )

    growspace_id = "gs1"
    mock_growspace = MagicMock()
    mock_growspace.environment_config = env_config
    mock_growspace.growspace_type = GrowspaceType.FLOWER
    mock_coordinator.growspaces = {growspace_id: mock_growspace}
    mock_coordinator.get_growspace_plants.return_value = []

    # Explicitly mock states before assigning to sensor
    mock_states = MagicMock()
    mock_coordinator.hass.states = mock_states

    sensor = create_test_sensor(
        mock_coordinator,
        growspace_id,
        GrowspaceSensorType.OPTIMAL,
        OptimalConditionsEvaluatorStrategy,
        env_config,
    )
    sensor.hass = mock_coordinator.hass

    # 3. Mock entity states
    def mock_get_state(entity_id):
        mock_state = MagicMock()
        if entity_id == "sensor.temp":
            mock_state.state = "25.0"
        elif entity_id == "sensor.humidity":
            mock_state.state = "60.0"
        else:
            return None
        return mock_state

    mock_states.get.side_effect = mock_get_state

    # 4. Trigger evaluation logic (private method that builds state)
    env_state = sensor._get_base_environment_state()

    # 5. Assertions
    # VPD is calculated using the LST (Leaf Surface Temperature) model with the
    # default lst_offset=-2.0 from EnvironmentConfig.
    # leaf_svp(23°C) - air_avp(25°C, 60%) ≈ 2.804 - 1.895 = 0.91 kPa

    assert env_state.temp == 25.0
    assert env_state.humidity == 60.0
    assert env_state.vpd is not None
    assert env_state.vpd == 0.91
