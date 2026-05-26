from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_async_commit_invalidates_cache(hass: HomeAssistant) -> None:
    """Test that async_commit invalidates the cache before updating data."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")

    # Mock storage manager (Ensure path is exactly this, without .services.)
    with patch(
        "custom_components.growspace_manager.coordinator.StorageManager"
    ) as mock_sm_cls:
        mock_sm_instance = mock_sm_cls.return_value
        mock_sm_instance.async_save = AsyncMock()
        mock_sm_instance.async_force_save = AsyncMock()

        coordinator = GrowspaceCoordinator.build(hass, entry, data={})

        # Manually populate cache to simulate existing state
        # Using a tuple to match expected internal CacheManager structure
        coordinator.cache._cache = {"gs1": ({"data": "stale_data"}, "dummy_hash")}

        # Mock the cache's invalidate method
        coordinator.cache.invalidate = MagicMock()

        # Check that async_commit invalidates the cache
        await coordinator.async_commit()

        # Verify invalidate was called
        coordinator.cache.invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_async_commit_rebuilds_cache(hass: HomeAssistant) -> None:
    """Test that cache is effectively refreshed."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")

    with patch(
        "custom_components.growspace_manager.coordinator.StorageManager"
    ) as mock_sm_cls:
        mock_sm_instance = mock_sm_cls.return_value
        mock_sm_instance.async_save = AsyncMock()
        mock_sm_instance.async_force_save = AsyncMock()

        coordinator = GrowspaceCoordinator.build(hass, entry, data={})
        coordinator.async_set_updated_data = MagicMock()
        coordinator.serializer = MagicMock()
        coordinator.serializer.serialize_growspace = MagicMock(
            side_effect=lambda gs, plants, *args, **kwargs: {"name": gs.name}
        )

        # Add a growspace manually to avoid triggering async_commit loop logic in setup
        gs = await coordinator.growspace_manager.add_growspace("Test GS")

        # Verify it's in cache (async_add calls commit)
        assert gs.id in coordinator.cache._cache

        # Backdoor modification logic simulation:
        # We manually inject a WRONG tuple value (timestamp, data) into cache
        coordinator.cache._cache[gs.id] = (123456789.0, {"name": "Old Cache"})

        # And we update the growspace name in reality
        coordinator.growspaces[gs.id].name = "Updated Name"

        # Now call commit. If it invalidates cache, it should rebuild using serializer
        await coordinator.async_commit()

        # Cache should be updated — name lives in the identity sub-object (ADR 0005)
        assert coordinator.cache._cache[gs.id][1]["identity"]["name"] == "Updated Name"
