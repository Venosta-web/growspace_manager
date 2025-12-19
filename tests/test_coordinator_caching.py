import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import timedelta
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_serializer():
    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceSerializer"
    ) as mock:
        instance = mock.return_value
        instance.serialize_growspace.side_effect = lambda g, p, e: {
            "id": g.id,
            "name": g.name,
            "serialized": True,
        }
        yield instance


@pytest.mark.asyncio
async def test_coordinator_caching(hass: HomeAssistant, mock_serializer):
    """Test that coordinator caches serialization and invalidates on change."""
    coordinator = GrowspaceCoordinator(hass, MagicMock(), options={})
    coordinator.serializer = mock_serializer

    # Setup initial data
    gs_id = "gs_1"
    coordinator.growspaces[gs_id] = Growspace(
        id=gs_id, name="Test GS", rows=3, plants_per_row=3
    )

    # 1. First update: Should call serializer
    coordinator.update_data_property()
    assert coordinator.data["serialized_growspaces"][gs_id]["serialized"] is True
    assert mock_serializer.serialize_growspace.call_count == 1

    # 2. Second update (no changes): Should NOT call serializer (use cache)
    coordinator.update_data_property()
    assert mock_serializer.serialize_growspace.call_count == 1  # Count remains 1

    # 3. Simulate invalidation via _invalidate_cache
    coordinator._invalidate_cache(gs_id)
    coordinator.update_data_property()
    assert mock_serializer.serialize_growspace.call_count == 2  # Called again

    # 4. Simulate modifying method (async_update_growspace logic)
    # We'll just call the invalidation logic logic directly or simulate a modifying method
    # Let's use async_update_growspace but we need to mock async_commit to avoid storage/event issues
    coordinator.async_commit = MagicMock()
    # But async update calls wait on lock.
    # easier to check invalidation directly or mock the lock

    # Let's test specific method invalidation mapping
    # async_add_plant
    coordinator._invalidate_cache = MagicMock()

    # Mock lifecycle manager to avoid real logic
    coordinator.lifecycle_manager = MagicMock()
    coordinator.lifecycle_manager.async_add_plant = AsyncMock(
        return_value=Plant(plant_id="p1", growspace_id=gs_id, strain="strain")
    )

    await coordinator.async_add_plant(growspace_id=gs_id, strain="Test")
    coordinator._invalidate_cache.assert_called_with(gs_id)
