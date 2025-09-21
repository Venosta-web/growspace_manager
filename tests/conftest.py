"""Fixtures for growspace_manager integration tests."""

import pytest
from unittest.mock import Mock
from datetime import datetime
from custom_components.growspace_manager.coordinator import (
    TestGrowspaceCoordinator,
    MockStore,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return Mock()


@pytest.fixture
def mock_store():
    """Create a mock store."""
    return MockStore()


@pytest.fixture
def sample_data():
    """Sample data for testing."""
    return {
        "growspaces": {
            "growspace_123": {
                "id": "growspace_123",
                "name": "Tent 1",
                "rows": 3,
                "plants_per_row": 3,
                "notification_target": None,
                "created_at": "2024-01-01T00:00:00",
            }
        },
        "plants": {
            "plant_abc": {
                "plant_id": "plant_abc",
                "growspace_id": "growspace_123",
                "strain": "Blue Dream",
                "row": 1,
                "col": 1,
                "stage": "veg",
                "veg_start": "2024-01-15",
                "flower_start": None,
                "dry_start": None,
                "cure_start": None,
                "created_at": "2024-01-15T00:00:00",
            }
        },
        "notifications_sent": {},
    }


@pytest.fixture
def coordinator(mock_hass, mock_store, sample_data):
    """Create a coordinator instance for testing."""
    return TestGrowspaceCoordinator(mock_hass, mock_store, sample_data, "test_entry")
