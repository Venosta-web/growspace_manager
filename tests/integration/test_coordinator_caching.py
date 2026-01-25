from unittest.mock import patch

import pytest


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
