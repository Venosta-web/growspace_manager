"""Exercise overview attribute exclusions through entity registration and Recorder."""

import json
import logging
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.sensor.overview import GrowspaceOverviewSensor
from homeassistant.components.recorder.db_schema import (
    MAX_STATE_ATTRS_BYTES,
    StateAttributes,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


@pytest.mark.parametrize("section", ["environment", "irrigation", "future_section"])
async def test_large_overview_attributes_stay_live_but_are_not_recorded(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture, section: str
) -> None:
    """Keep state history without Recorder rejecting a growing live payload."""
    logger = logging.getLogger(__name__)
    growspace = Growspace(id="test", name="Test growspace")
    coordinator = DataUpdateCoordinator(
        hass, logger, name="overview test", config_entry=None
    )
    coordinator.growspaces = {growspace.id: growspace}
    coordinator.services = MagicMock()
    coordinator.services.growspaces.get_growspace_plants.return_value = [object()]
    payload = {
        "identity": {"name": growspace.name},
        section: {"data": "x" * MAX_STATE_ATTRS_BYTES},
        "grid": [],
        "plants": [],
    }
    coordinator.async_set_updated_data({"serialized_growspaces": {"test": payload}})
    sensor = GrowspaceOverviewSensor(coordinator, growspace.id, growspace)
    sensor.entity_id = "sensor.test_overview"
    sensor._attr_name = "Overview"
    # This standalone platform has no config entry to own a device.
    sensor._attr_device_info = None
    component = EntityComponent(logger, "sensor", hass)
    await component.async_add_entities([sensor])

    state = hass.states.get(sensor.entity_id)
    assert state is not None
    assert state.state == "1"
    assert state.attributes[section] == payload[section]
    assert "grid" not in state.attributes
    assert "plants" not in state.attributes
    assert len(json_bytes(dict(state.attributes))) > MAX_STATE_ATTRS_BYTES

    event = Event("state_changed", {"new_state": state})
    recorded = StateAttributes.shared_attrs_bytes_from_event(event, None)
    assert json.loads(recorded) == {"friendly_name": state.attributes["friendly_name"]}
    assert "exceed maximum size" not in caplog.text
    assert state.attributes[section] == payload[section]
    assert coordinator.data["serialized_growspaces"]["test"] == payload
    await component.async_remove_entity(sensor.entity_id)
