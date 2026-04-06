"""Tests for GrowspaceCoordinator service call retrieval logic."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_growspace_coordinator(hass: HomeAssistant):
    """Create a mock coordinator attached to a config entry."""

    def _create_coordinator(
        entry_id: str = "test_entry",
        growspace_ids: list[str] | None = None,
        plant_ids: list[str] | None = None,
    ):
        entry = MockConfigEntry(domain=DOMAIN, entry_id=entry_id)
        entry.add_to_hass(hass)

        # Manually set state to LOADED as the mock helper might not do it automatically for logic checks
        entry.mock_state(hass, ConfigEntryState.LOADED)

        coordinator = MagicMock()
        coordinator.config_entry = entry

        # Setup searchable collections
        coordinator.growspaces = {gid: MagicMock() for gid in (growspace_ids or [])}
        coordinator.plants = {pid: MagicMock() for pid in (plant_ids or [])}

        entry.runtime_data = coordinator
        return coordinator

    return _create_coordinator


async def test_get_for_service_call_single_entry(
    hass: HomeAssistant, mock_growspace_coordinator
) -> None:
    """Test retrieval when only one entry exists (fallback)."""
    coord1 = mock_growspace_coordinator(entry_id="entry1")

    # Empty call data
    # Empty call data
    call: dict[str, Any] = {}

    result = GrowspaceCoordinator.get_for_service_call(hass, call)
    assert result == coord1


async def test_get_for_service_call_multiple_entries_exact_match(
    hass: HomeAssistant, mock_growspace_coordinator
) -> None:
    """Test retrieval with multiple entries using specific IDs."""
    coord1 = mock_growspace_coordinator(
        entry_id="entry1", growspace_ids=["gs1"], plant_ids=["p1"]
    )
    coord2 = mock_growspace_coordinator(
        entry_id="entry2", growspace_ids=["gs2"], plant_ids=["p2"]
    )

    # 1. Match by growspace_id (entry 1)
    call1 = {"growspace_id": "gs1"}
    assert GrowspaceCoordinator.get_for_service_call(hass, call1) == coord1

    # 2. Match by growspace_id (entry 2)
    call2 = {"growspace_id": "gs2"}
    assert GrowspaceCoordinator.get_for_service_call(hass, call2) == coord2

    # 3. Match by plant_id (entry 2)
    call3 = {"plant_id": "p2"}
    assert GrowspaceCoordinator.get_for_service_call(hass, call3) == coord2

    # 4. Match by target_growspace_id (entry 1)
    call4 = {"target_growspace_id": "gs1"}
    assert GrowspaceCoordinator.get_for_service_call(hass, call4) == coord1


async def test_get_for_service_call_multiple_entries_list_match(
    hass: HomeAssistant, mock_growspace_coordinator
) -> None:
    """Test retrieval when ID is a list."""
    coord1 = mock_growspace_coordinator(entry_id="entry1", plant_ids=["p1a", "p1b"])
    mock_growspace_coordinator(entry_id="entry2", plant_ids=["p2a"])

    # Match list containing items from coord1
    call = {"plant_id": ["p1a", "p1b"]}
    assert GrowspaceCoordinator.get_for_service_call(hass, call) == coord1

    # Match mixed list (should match first valid found? logic says "any")
    # If p1a is found in coord1, it returns coord1.
    call_mixed = {"plant_id": ["p1a", "p2a"]}
    assert GrowspaceCoordinator.get_for_service_call(hass, call_mixed) == coord1


async def test_get_for_service_call_ambiguous_failure(
    hass: HomeAssistant, mock_growspace_coordinator
) -> None:
    """Test failure when multiple entries exist but no ID matches."""
    mock_growspace_coordinator(entry_id="entry1")
    mock_growspace_coordinator(entry_id="entry2")

    call: dict[str, Any] = {}

    with pytest.raises(ServiceValidationError, match="Could not determine"):
        GrowspaceCoordinator.get_for_service_call(hass, call)


async def test_get_for_service_call_invalid_id_failure(
    hass: HomeAssistant, mock_growspace_coordinator
) -> None:
    """Test failure when ID does not exist in any coordinator."""
    mock_growspace_coordinator(entry_id="entry1", growspace_ids=["gs1"])
    mock_growspace_coordinator(entry_id="entry2", growspace_ids=["gs2"])

    call: dict[str, Any] = {"growspace_id": "gs3"}

    # Should fall through to the ambiguous error since no match found
    # and multiple coords exist
    with pytest.raises(ServiceValidationError, match="Could not determine"):
        GrowspaceCoordinator.get_for_service_call(hass, call)
