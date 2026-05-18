from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.common import MockConfigEntry, mock_component


@pytest.fixture
def mock_setup_entry():
    with patch(
        "custom_components.growspace_manager.async_setup_entry", return_value=True
    ) as mock_setup:
        yield mock_setup


async def test_configure_dehumidifier_thresholds(
    hass: HomeAssistant, mock_setup_entry, enable_custom_integrations
) -> None:
    """Test configuring detailed dehumidifier thresholds via options flow."""
    # Mock recorder dependency
    mock_component(hass, "recorder")

    # Setup - existing entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        data={"name": "Test"},
        entry_id="test_entry",
    )

    # Mock Coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.services = MagicMock()
    
    mock_growspace = Growspace(
        id="gs1",
        name="Test GS",
        environment_config=EnvironmentConfig(dehumidifier_entities=["switch.dehum"]),
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.get_sorted_growspace_options.return_value = [
        ("gs1", "Test GS")
    ]
    mock_coordinator.services.get_growspace.return_value = mock_growspace
    mock_coordinator.services.save = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock()


    entry.runtime_data = mock_coordinator
    entry.add_to_hass(hass)

    # Convert to options flow
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # 1. Select Configure Environment
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "configure_environment"}
    )

    # 2. Select Growspace
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"growspace_id": "gs1"}
    )

    # 3. Enable Dehumidifier Control AND Configure Thresholds
    # Note: We must provide valid entity selector data implicitly by just sending the string
    user_input = {
        "control_dehumidifier": True,
        "configure_dehumidifier": True,
        "dehumidifier_entities": ["switch.dehum"],
        # Pass other required or optional fields to pass validation if needed,
        # but pure optional fields can be omitted.
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=user_input
    )

    # Expect transition to 'configure_dehumidifier' step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_dehumidifier"

    # 4. Fill in Thresholds
    # Just setting one specific one to verify it sticks, others can use defaults if schema allows (but schema is Required with default)
    # The form will require all of them because vol.Required is used in the handler loop.
    # However, create_entry allows passing sparse if the underlying schema defaults handle it?
    # No, vol.Required means input MUST be present.
    # We'll generate the full payload.

    thresholds_input = {}
    stages = [
        "seedling",
        "veg",
        "flower_early",
        "flower_mid",
        "flower_late",
        "dry",
        "cure",
    ]
    cycles = ["day", "night"]

    for stage in stages:
        for cycle in cycles:
            thresholds_input[f"{stage}_{cycle}_on"] = 1.5
            thresholds_input[f"{stage}_{cycle}_off"] = 1.6

    # Set a specific one to verify
    thresholds_input["veg_day_on"] = 2.0

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=thresholds_input
    )

    # Expect transition to 'configure_sensor_placement' step
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_sensor_placement"

    # 5. Fill in Sensor Placement
    placement_input = {
        "coord_switch.dehum_x": 10.0,
        "coord_switch.dehum_y": 20.0,
        "coord_switch.dehum_z": 30.0,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=placement_input
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY

    # 6. Verify data saved to Growspace object
    saved_thresholds = mock_growspace.environment_config.dehumidifier_thresholds
    assert saved_thresholds["veg"]["day"]["on"] == 2.0
    assert saved_thresholds["veg"]["night"]["on"] == 1.5  # default form our loop
    assert saved_thresholds["flower_early"]["day"]["on"] == 1.5

    # Verify sensor coordinates saved
    saved_coords = mock_growspace.environment_config.sensor_coordinates
    assert saved_coords["switch.dehum"] == {"x": 10.0, "y": 20.0, "z": 30.0}

    # Verify save called
    assert mock_coordinator.services.save.called

    # 6. Verify Persistence: Re-open flow, checkbox should be True
    # We simulate this by checking what the schema default would be
    handler = EnvironmentConfigHandler(hass, entry)
    # Growspace object has the thresholds now
    options = mock_growspace.environment_config.to_dict()
    handler.get_environment_schema_step1(options)

    # Check default value of configure_dehumidifier
    # It's a bit tricky to inspect voluptuous schema defaults directly without internal knowledge
    # relying on the fact that we fixed the logic in handler.py

    # Instead, let's simulate a second pass in the options flow
    # mock_growspace already updated in step 5 logic (conceptually)

    result_2 = await hass.config_entries.options.async_init(entry.entry_id)
    result_2 = await hass.config_entries.options.async_configure(
        result_2["flow_id"], user_input={"action": "configure_environment"}
    )
    result_2 = await hass.config_entries.options.async_configure(
        result_2["flow_id"], user_input={"growspace_id": "gs1"}
    )

    # In step 1 form, the default for 'configure_dehumidifier' should be True
    # We can inspect the schema from the result
    schema_2 = result_2["data_schema"]
    # Provide the key to get the Marker object (Optional('configure_dehumidifier'))
    # Iterate to find the key
    target_key = next(
        (k for k in schema_2.schema if str(k) == "configure_dehumidifier"), None
    )
    assert target_key is not None
    assert target_key.default() is True  # Should be True because thresholds exist

    # 7. Uncheck and Verify Clearing
    user_input_clear = {
        "control_dehumidifier": True,
        "configure_dehumidifier": False,  # UNCHECK
        "dehumidifier_entities": ["switch.dehum"],
    }
    result_3 = await hass.config_entries.options.async_configure(
        result_2["flow_id"], user_input=user_input_clear
    )

    # Should go to sensor placement
    assert result_3["type"] == FlowResultType.FORM
    assert result_3["step_id"] == "configure_sensor_placement"

    # Finish flow
    result_4 = await hass.config_entries.options.async_configure(
        result_3["flow_id"],
        user_input={
            "coord_switch.dehum_x": 0.0,
            "coord_switch.dehum_y": 0.0,
            "coord_switch.dehum_z": 0.0,
        },
    )

    assert result_4["type"] == FlowResultType.CREATE_ENTRY

    # Verify thresholds cleared in growspace object
    assert mock_growspace.environment_config.dehumidifier_thresholds == {}
