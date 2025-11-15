"""Tests for the Growspace Manager switch platform."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


async def test_switch_creation(hass: HomeAssistant) -> None:
    """Test that all switches are created."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
        notification_target="notify.test",
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get("switch.test_growspace_notifications") is not None
    )


async def test_switch_on_off(hass: HomeAssistant) -> None:
    """Test the on/off state of the switch."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "My Growspace"},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.async_load",
        return_value=True,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
        notification_target="notify.test",
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("switch.test_growspace_notifications")
    assert state is not None
    assert state.state == "on"

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.test_growspace_notifications"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.test_growspace_notifications")
    assert state is not None
    assert state.state == "off"

    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": "switch.test_growspace_notifications"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("switch.test_growspace_notifications")
    assert state is not None
    assert state.state == "on"
