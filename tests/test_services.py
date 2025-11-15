"""Tests for the Growspace Manager services."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


async def test_add_growspace_service(hass: HomeAssistant) -> None:
    """Test the add_growspace service."""
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

    await hass.services.async_call(
        DOMAIN,
        "add_growspace",
        {"name": "Test Growspace", "rows": 2, "plants_per_row": 2},
        blocking=True,
    )
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    assert len(coordinator.growspaces) == 1
    assert list(coordinator.growspaces.values())[0].name == "Test Growspace"


async def test_remove_growspace_service(hass: HomeAssistant) -> None:
    """Test the remove_growspace service."""
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
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "remove_growspace",
        {"growspace_id": growspace.id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(coordinator.growspaces) == 0


async def test_add_plant_service(hass: HomeAssistant) -> None:
    """Test the add_plant service."""
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
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "add_plant",
        {
            "growspace_id": growspace.id,
            "strain": "Test Plant",
            "row": 1,
            "col": 1,
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(coordinator.plants) == 1
    assert list(coordinator.plants.values())[0].strain == "Test Plant"


async def test_remove_plant_service(hass: HomeAssistant) -> None:
    """Test the remove_plant service."""
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
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    plant = await coordinator.async_add_plant(
        growspace_id=growspace.id,
        strain="Test Plant",
        row=1,
        col=1,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "remove_plant",
        {"plant_id": plant.id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(coordinator.plants) == 0


async def test_update_plant_service(hass: HomeAssistant) -> None:
    """Test the update_plant service."""
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
    growspace = await coordinator.async_add_growspace(
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    plant = await coordinator.async_add_plant(
        growspace_id=growspace.id,
        strain="Test Plant",
        row=1,
        col=1,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "update_plant",
        {"plant_id": plant.id, "strain": "New Strain"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert coordinator.plants[plant.id].strain == "New Strain"
