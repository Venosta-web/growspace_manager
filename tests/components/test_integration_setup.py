"""Tests for full integration setup via the HA config entry lifecycle.

These tests exercise the real async_setup_entry / async_unload_entry path
using a live HomeAssistant instance instead of mocked coordinators.
Use `init_integration` (from tests/conftest.py) whenever you want to test
behaviour that requires the coordinator, services, or entities to be wired up
for real.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN  # noqa: E402
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator  # noqa: E402


@pytest.mark.usefixtures("init_integration")
async def test_entry_loads_successfully(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Entry reaches LOADED state and coordinator is stored in runtime_data."""
    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert isinstance(coordinator, GrowspaceCoordinator)


@pytest.mark.usefixtures("init_integration")
async def test_default_special_growspaces_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Special growspaces (dry, cure, veg, clone, mother) exist after setup."""
    coordinator: GrowspaceCoordinator = mock_config_entry.runtime_data
    special_ids = {"dry", "cure", "veg", "clone", "mother"}
    assert special_ids.issubset(coordinator.growspaces.keys()), (
        f"Missing special growspaces: {special_ids - set(coordinator.growspaces)}"
    )


@pytest.mark.usefixtures("init_integration")
async def test_domain_services_registered(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Core services are registered on the domain after setup."""
    expected = {"add_growspace", "add_plant", "water_plant", "remove_plant"}
    registered = set(hass.services.async_services_for_domain(DOMAIN))
    assert expected.issubset(registered), (
        f"Missing services: {expected - registered}"
    )


@pytest.mark.usefixtures("init_integration")
async def test_entry_unloads_cleanly(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Entry unloads without errors and reaches NOT_LOADED state."""
    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
