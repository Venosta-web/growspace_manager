"""Tests for the Growspace Manager binary sensor platform."""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt

from custom_components.growspace_manager.binary_sensor import (
    async_setup_entry,
    BayesianStressSensor,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant


@pytest.fixture
def mock_coordinator() -> GrowspaceCoordinator:
    """Fixture for a mock coordinator."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    growspace = Growspace(
        id="test_growspace", name="Test Growspace", rows=2, plants_per_row=2
    )
    growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
    }
    coordinator.growspaces = {"test_growspace": growspace}
    coordinator.plants = {}
    return coordinator


async def test_async_setup_entry(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
) -> None:
    """Test the binary_sensor platform setup."""
    hass.data = {"growspace_manager": {"test_entry_id": {"coordinator": mock_coordinator}}}
    async_add_entities = MagicMock()
    await async_setup_entry(hass, MagicMock(), async_add_entities)
    async_add_entities.assert_called_once()


@patch("homeassistant.helpers.event.async_track_state_change_event")
async def test_bayesian_stress_sensor(
    mock_track_state_change: MagicMock,
    hass: HomeAssistant,
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test the BayesianStressSensor."""
    growspace = mock_coordinator.growspaces["test_growspace"]
    sensor = BayesianStressSensor(
        mock_coordinator, "test_growspace", growspace.environment_config
    )
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()
    sensor._get_sensor_value = MagicMock(return_value=25)
    sensor._get_growth_stage_info = MagicMock(return_value={"veg_days": 10, "flower_days": 0})
    sensor._async_analyze_sensor_trend = AsyncMock(return_value={"trend": "stable", "crossed_threshold": False})


    await sensor._async_update_probability()

    assert not sensor.is_on
    assert sensor._probability < sensor.threshold

    # Simulate high temperature
    sensor._get_sensor_value = MagicMock(return_value=35)
    await sensor._async_update_probability()
    assert sensor.is_on
    assert sensor._probability > sensor.threshold
