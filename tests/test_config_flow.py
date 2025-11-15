"""Tests for the Growspace Manager config and options flow."""
from __future__ import annotations

from unittest.mock import patch

import voluptuous as vol
from homeassistant.components import dhcp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


async def test_full_user_flow(hass: HomeAssistant) -> None:
    """Test the full user flow from start to finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"

    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"name": "My Growspace"},
        )
        await hass.async_block_till_done()

    assert result2.get("type") == FlowResultType.CREATE_ENTRY
    assert result2.get("title") == "My Growspace"
    assert result2.get("data") == {"name": "My Growspace"}
    assert len(mock_setup_entry.mock_calls) == 1

async def test_options_flow(hass: HomeAssistant) -> None:
    """Test the options flow."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ), patch(
        "custom_components.growspace_manager.config_flow.OptionsFlowHandler._get_add_growspace_schema",
        return_value=vol.Schema(
            {
                vol.Required("name"): str,
                vol.Required("rows"): int,
                vol.Required("plants_per_row"): int,
                vol.Optional("notification_target"): str,
            }
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"action": "manage_growspaces"},
    )

    assert result2.get("type") == FlowResultType.FORM
    assert result2.get("step_id") == "manage_growspaces"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        user_input={"action": "add"},
    )
    assert result3.get("type") == FlowResultType.FORM
    assert result3.get("step_id") == "add_growspace"

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_add_growspace"
    ) as mock_add_growspace:
        result4 = await hass.config_entries.options.async_configure(
            result3["flow_id"],
            user_input={
                "name": "Test Growspace",
                "rows": 2,
                "plants_per_row": 2,
                "notification_target": "test",
            },
        )
        await hass.async_block_till_done()

    assert result4.get("type") == FlowResultType.CREATE_ENTRY
    assert result4.get("data") == {}
    assert len(mock_add_growspace.mock_calls) == 1


async def test_options_flow_manage_plants(hass: HomeAssistant) -> None:
    """Test the options flow for managing plants."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ), patch(
        "custom_components.growspace_manager.config_flow.OptionsFlowHandler._get_add_plant_schema",
        return_value=vol.Schema(
            {
                vol.Required("strain"): str,
                vol.Required("row"): int,
                vol.Required("col"): int,
            }
        ),
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"action": "manage_plants"},
    )
    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        user_input={"action": "add"},
    )
    result4 = await hass.config_entries.options.async_configure(
        result3["flow_id"],
        user_input={"growspace_id": "test"},
    )

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_add_plant"
    ) as mock_add_plant:
        result5 = await hass.config_entries.options.async_configure(
            result4["flow_id"],
            user_input={"strain": "Test Plant", "row": 1, "col": 1},
        )
        await hass.async_block_till_done()

    assert result5.get("type") == FlowResultType.CREATE_ENTRY
    assert result5.get("data") == {}
    assert len(mock_add_plant.mock_calls) == 1


async def test_options_flow_configure_environment(hass: HomeAssistant) -> None:
    """Test the options flow for configuring the environment."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"action": "configure_environment"},
    )
    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        user_input={"growspace_id": "test"},
    )

    assert result3.get("type") == FlowResultType.FORM
    assert result3.get("step_id") == "configure_environment"

    with patch("custom_components.growspace_manager.GrowspaceCoordinator.async_save"), patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_refresh"
    ):
        result4 = await hass.config_entries.options.async_configure(
            result3["flow_id"],
            user_input={
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                "vpd_sensor": "sensor.vpd",
            },
        )
        await hass.async_block_till_done()

    assert result4.get("type") == FlowResultType.CREATE_ENTRY


async def test_options_flow_configure_global(hass: HomeAssistant) -> None:
    """Test the options flow for configuring global settings."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"action": "configure_global"},
    )

    assert result2.get("type") == FlowResultType.FORM
    assert result2.get("step_id") == "configure_global"

    result3 = await hass.config_entries.options.async_configure(
        result2["flow_id"],
        user_input={"weather_entity": "weather.home"},
    )
    await hass.async_block_till_done()

    assert result3.get("type") == FlowResultType.CREATE_ENTRY
    assert config_entry.options["global_settings"] == {"weather_entity": "weather.home"}
