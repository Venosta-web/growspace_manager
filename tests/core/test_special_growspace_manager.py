"""Tests for SpecialGrowspaceManager."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import Growspace, GrowspaceType
from custom_components.growspace_manager.services.special_growspace_manager import (
    SpecialGrowspaceManager,
)


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    return coordinator


@pytest.fixture
def manager(mock_coordinator) -> SpecialGrowspaceManager:
    """SpecialGrowspaceManager fixture."""
    return SpecialGrowspaceManager(mock_coordinator)


def test_create_special_growspace(manager, mock_coordinator) -> None:
    """Test creating a special growspace."""
    manager.create_special_growspace(
        "mother", "Mother Plants", 1, 1, GrowspaceType.MOTHER
    )

    assert "mother" in mock_coordinator.growspaces
    gs = mock_coordinator.growspaces["mother"]
    assert gs.name == "Mother Plants"
    assert gs.growspace_type == GrowspaceType.MOTHER


def test_update_special_growspace_name(manager, mock_coordinator) -> None:
    """Test updating special growspace name."""
    gs = MagicMock(spec=Growspace)
    gs.name = "Old Name"
    mock_coordinator.growspaces = {"mother": gs}

    manager.update_special_growspace_name("mother", "New Name")
    assert gs.name == "New Name"

    # Test no update if name is same
    manager.update_special_growspace_name("mother", "New Name")
    assert gs.name == "New Name"


def test_get_canonical_special(manager, mock_coordinator) -> None:
    """Test getting canonical special growspace info."""
    gs = MagicMock(spec=Growspace)
    gs.name = "Mother Plants"
    mock_coordinator.growspaces = {"mother": gs}

    # Registered
    assert manager.get_canonical_special("mother") == ("mother", "Mother Plants")

    # Not registered
    assert manager.get_canonical_special("unknown") == ("unknown", "unknown")
