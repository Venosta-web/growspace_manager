"""Tests for the initialization and unloading of the Growspace Manager integration.

This file contains tests to ensure that the integration can be successfully set up
and unloaded within Home Assistant.
"""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.growspace_manager import async_unload_entry
from custom_components.growspace_manager.const import DOMAIN


@pytest.mark.asyncio
async def test_async_setup_entry(recorder_mock, enable_custom_integrations):
    """Test a successful setup of the integration entry.

    This test simulates the process of Home Assistant setting up the integration
    from a config entry and asserts that the setup is successful.

    Args:
        recorder_mock: A mock of the Home Assistant recorder component.
        enable_custom_integrations: A fixture to enable custom integrations.
    """
    # Get the hass object from the recorder_mock fixture
    hass: HomeAssistant = recorder_mock.hass

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_async_unload_entry(recorder_mock, enable_custom_integrations):
    """Test a successful unload of the integration entry.

    This test ensures that the integration can be gracefully unloaded, cleaning
    up its components and resources from Home Assistant.

    Args:
        recorder_mock: A mock of the Home Assistant recorder component.
        enable_custom_integrations: A fixture to enable custom integrations.
    """
    # Get the hass object from the recorder_mock fixture
    hass: HomeAssistant = recorder_mock.hass

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert await async_unload_entry(hass, entry)
