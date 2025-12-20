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
