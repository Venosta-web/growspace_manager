"""The options form carries placements and refuses bad HA metadata in place."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.config_handlers.environment_sensors_handler import (
    EnvironmentSensorsHandler,
)
from custom_components.growspace_manager.models import Growspace


@pytest.mark.parametrize(
    "handler_class", [EnvironmentConfigHandler, EnvironmentSensorsHandler]
)
@pytest.mark.parametrize(
    "declaration",
    [
        [{"entity_id": "sensor.flow", "placement": "supply"}],
        [{"entity_id": "sensor.flow", "placement": "gone"}],
        [{"entity_id": "sensor.flow", "placement": "supply", "unit": "L"}],
    ],
)
async def test_invalid_form_keeps_input_and_explains_fix(
    hass, handler_class, declaration
):
    flow = MagicMock()
    flow.hass = hass
    flow.selected_growspace_id = "tent"
    growspace = Growspace(id="tent", name="Tent")
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        growspace
    )
    flow.async_show_form.side_effect = lambda **kwargs: kwargs
    handler = handler_class(flow)
    result = await handler.async_step_configure_environment(
        {"flow_meters": declaration}
    )
    assert result["errors"] == {"flow_meters": "invalid_flow_meter"}
    assert result["step_id"] == "configure_environment"
    assert result["description_placeholders"]["flow_meter_error"]
    assert any(field.schema == "flow_meters" for field in result["data_schema"].schema)
    assert not any(
        field.schema == "irrigation_flow_sensors"
        for field in result["data_schema"].schema
    )
    flow.config_entry.runtime_data.services.save.assert_not_called()


@pytest.mark.parametrize(
    "handler_class", [EnvironmentConfigHandler, EnvironmentSensorsHandler]
)
@pytest.mark.parametrize(
    "meters", [[], [{"entity_id": "sensor.flow", "placement": "default"}]]
)
async def test_form_accepts_valid_meter_or_explicit_clear(hass, handler_class, meters):
    hass.states.async_set(
        "sensor.flow",
        "0",
        {"device_class": "volume_flow_rate", "unit_of_measurement": "L/s"},
    )
    flow = MagicMock()
    flow.hass = hass
    flow.selected_growspace_id = "tent"
    growspace = Growspace(id="tent", name="Tent")
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        growspace
    )
    handler = handler_class(flow)
    handler._determine_next_step = AsyncMock(return_value={"type": "form"})
    await handler.async_step_configure_environment({"flow_meters": meters})
    assert flow.env_config_step1["flow_meters"] == meters
    handler._determine_next_step.assert_awaited_once()
