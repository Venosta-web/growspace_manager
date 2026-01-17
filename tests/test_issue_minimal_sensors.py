from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.binary_sensor import (
    BayesianEnvironmentSensor,
    GrowspaceBinarySensorDescription,
    GrowspaceSensorType,
)
from .conftest import create_plant

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
)
from .conftest import create_plant

from custom_components.growspace_manager.strategies.optimal import (
    OptimalConditionsEvaluatorStrategy,
)
from .conftest import create_plant



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
    mock_growspace = MagicMock(spec=Growspace)
    mock_growspace.environment_config = env_config
    mock_growspace.growspace_type = GrowspaceType.FLOWER
    mock_coordinator.growspaces = {growspace_id: mock_growspace}
    mock_coordinator.get_growspace_plants.return_value = []

    # 2. Setup Sensor
    description = GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.OPTIMAL,
        sensor_type=GrowspaceSensorType.OPTIMAL,
        prior_key="prior_optimal",
    )

    # Explicitly mock states before assigning to sensor
    mock_states = MagicMock()
    mock_coordinator.hass.states = mock_states

    sensor = BayesianEnvironmentSensor(
        mock_coordinator,
        growspace_id,
        env_config,
        description,
        OptimalConditionsEvaluatorStrategy,
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
    # With the fix, VPD should be calculated from 25.0 C and 60.0% RH
    # Expected VPD approx 1.27 kPa

    assert env_state.temp == 25.0
    assert env_state.humidity == 60.0
    assert env_state.vpd is not None
    assert env_state.vpd == 1.26
    print(f"SUCCESS: VPD calculated as {env_state.vpd}")
