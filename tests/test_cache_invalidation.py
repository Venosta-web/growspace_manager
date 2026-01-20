from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_async_commit_invalidates_cache(hass: HomeAssistant) -> None:
    """Test that async_commit invalidates the cache before updating data."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")

    # Mock storage manager
    with patch(
        "custom_components.growspace_manager.coordinator.StorageManager"
    ) as mock_sm_cls:
        mock_sm_instance = mock_sm_cls.return_value
        mock_sm_instance.async_save = AsyncMock()

        coordinator = GrowspaceCoordinator(hass, entry, data={})

        # Manually populate cache to simulate existing state
        coordinator._serialized_cache = {"gs1": {"data": "stale_data"}}

        # Spy on _invalidate_cache
        with patch.object(
            coordinator, "_invalidate_cache", wraps=coordinator._invalidate_cache
        ) as spy_invalidate:
            await coordinator.async_commit()

            spy_invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_async_commit_rebuilds_cache(hass: HomeAssistant) -> None:
    """Test that cache is effectively refreshed."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")

    with patch(
        "custom_components.growspace_manager.coordinator.StorageManager"
    ) as mock_sm_cls:
        mock_sm_instance = mock_sm_cls.return_value
        mock_sm_instance.async_save = AsyncMock()

        coordinator = GrowspaceCoordinator(hass, entry, data={})
        coordinator.async_set_updated_data = MagicMock()
        coordinator.serializer = MagicMock()
        coordinator.serializer.serialize_growspace = MagicMock(
            side_effect=lambda gs, plants, *args, **kwargs: {"name": gs.name}
        )

        # Add a growspace manually to avoid triggering async_commit loop logic in setup
        gs = await coordinator.async_add_growspace("Test GS")

        # Verify it's in cache (async_add calls commit)
        assert gs.id in coordinator._serialized_cache

        # Backdoor modification logic simulation:
        # We manually inject a WRONG value into cache
        coordinator._serialized_cache[gs.id] = {"name": "Old Cache"}

        # And we update the growspace name in reality
        coordinator.growspaces[gs.id].name = "Updated Name"

        # Now call commit. If it invalidates cache, it should rebuild using serializer
        await coordinator.async_commit()

        # Cache should be updated
        assert coordinator._serialized_cache[gs.id]["name"] == "Updated Name"
