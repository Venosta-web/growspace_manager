"""Test the Growspace Manager integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.growspace_manager.const import DOMAIN


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant, enable_custom_integrations):
    """Test a successful setup entry."""
    from homeassistant.setup import async_setup_component

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_async_unload_entry(hass: HomeAssistant, enable_custom_integrations):
    """Test a successful unload entry."""
    from custom_components.growspace_manager import async_unload_entry
    from homeassistant.setup import async_setup_component

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test")
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert await async_unload_entry(hass, entry)
