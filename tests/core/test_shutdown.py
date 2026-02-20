from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager import DOMAIN, async_unload_entry
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_async_unload_entry_calls_shutdown(hass: HomeAssistant) -> None:
    """Test that unloading the entry calls async_shutdown on the coordinator."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")
    entry.add_to_hass(hass)

    # Mock the coordinator attached to runtime_data
    mock_coordinator = AsyncMock()
    entry.runtime_data = mock_coordinator

    # Mock unload_platforms to return True
    entry.mock_state = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    await async_unload_entry(hass, entry)

    # Verify shutdown was called
    mock_coordinator.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_async_unload_entry_shutdown_exception(hass: HomeAssistant) -> None:
    """Test that unload proceeds even if shutdown raises an exception."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")
    entry.add_to_hass(hass)

    mock_coordinator = AsyncMock()
    mock_coordinator.async_shutdown.side_effect = Exception("Save failed")
    entry.runtime_data = mock_coordinator

    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    # Should not raise
    result = await async_unload_entry(hass, entry)
    assert result is True
    # Verify it was still attempted
    mock_coordinator.async_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_coordinator_async_shutdown_logic(hass: HomeAssistant) -> None:
    """Test that GrowspaceCoordinator.async_shutdown calls storage_manager.async_force_save."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")

    # Init coordinator
    # We mock storage_manager inside
    with patch(
        "custom_components.growspace_manager.coordinator.StorageManager"
    ) as mock_sm_cls:
        mock_sm_instance = mock_sm_cls.return_value
        mock_sm_instance.async_force_save = AsyncMock()

        coordinator = GrowspaceCoordinator(hass, entry, data={})

        await coordinator.async_shutdown()

        mock_sm_instance.async_force_save.assert_called_once()
