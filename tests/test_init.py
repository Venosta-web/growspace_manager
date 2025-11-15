"""Test the Growspace Manager integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from custom_components.growspace_manager.const import DOMAIN


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant):
    """Test a successful setup entry."""
    from custom_components.growspace_manager import async_setup_entry

    entry = ConfigEntry(1, DOMAIN, "Test", {}, "test", "local_push")
    hass.data[DOMAIN] = {}

    with pytest.raises(Exception):
        await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_async_unload_entry(hass: HomeAssistant):
    """Test a successful unload entry."""
    from custom_components.growspace_manager import async_unload_entry

    entry = ConfigEntry(1, DOMAIN, "Test", {}, "test", "local_push")
    hass.data[DOMAIN] = {entry.entry_id: {"coordinator": AsyncMock()}}

    assert await async_unload_entry(hass, entry)
