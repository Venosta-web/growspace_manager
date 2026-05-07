"""Tests for websocket_get_lineage_tree with strain library fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.managers.genetics import GeneticsManager
from custom_components.growspace_manager.models import (
    Plant,
    PlantGenetics,
    PollinationEvent,
)
from custom_components.growspace_manager.websocket import websocket_get_lineage_tree


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def save_callback() -> AsyncMock:
    """A mock async save callback."""
    return AsyncMock()


@pytest.fixture
def manager_empty(save_callback: AsyncMock) -> GeneticsManager:
    """GeneticsManager with a plant but no pollination events."""
    repo = MagicMock()
    repo.plants = {
        "plant-1": Plant(
            plant_id="plant-1",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="OG Kush"),
            stage="flower",
        ),
    }
    return GeneticsManager(repository=repo, save_callback=save_callback)


@pytest.fixture
def manager_with_pollination(save_callback: AsyncMock) -> GeneticsManager:
    """GeneticsManager with a plant that has a pollination event."""
    repo = MagicMock()
    repo.plants = {
        "plant-donor": Plant(
            plant_id="plant-donor",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="Durban Poison"),
            stage="flower",
        ),
        "plant-receiver": Plant(
            plant_id="plant-receiver",
            growspace_id="gs-1",
            genetics=PlantGenetics(strain_name="OG Kush"),
            stage="flower",
        ),
    }
    mgr = GeneticsManager(repository=repo, save_callback=save_callback)
    event = PollinationEvent(
        event_id="evt-1",
        date="2025-01-01",
        donor_plant_id="plant-donor",
        receiver_plant_id="plant-receiver",
        notes="",
    )
    mgr.pollination_events = {"evt-1": event}
    return mgr


# ---------------------------------------------------------------------------
# GeneticsManager.get_lineage_tree unit tests
# ---------------------------------------------------------------------------


class TestGetLineageTree:
    """Unit tests for GeneticsManager.get_lineage_tree."""

    def test_no_pollination_returns_empty_parents(
        self, manager_empty: GeneticsManager
    ) -> None:
        """Plant with no pollination events returns a node with empty parents."""
        tree = manager_empty.get_lineage_tree("plant-1")
        assert tree["name"] == "OG Kush"
        assert tree["parents"] == []

    def test_with_pollination_returns_two_parents(
        self, manager_with_pollination: GeneticsManager
    ) -> None:
        """Plant that is a pollination receiver gets donor + receiver as parents."""
        tree = manager_with_pollination.get_lineage_tree("plant-receiver")
        assert tree["name"] == "OG Kush"
        assert len(tree["parents"]) == 2
        parent_names = {p["name"] for p in tree["parents"]}
        assert "OG Kush" in parent_names
        assert "Durban Poison" in parent_names

    def test_unknown_plant_uses_id_as_name(
        self, manager_empty: GeneticsManager
    ) -> None:
        """Plant ID not in repository falls back to using plant_id as name."""
        tree = manager_empty.get_lineage_tree("unknown-plant")
        assert tree["name"] == "unknown-plant"
        assert tree["parents"] == []


# ---------------------------------------------------------------------------
# websocket_get_lineage_tree handler tests
# ---------------------------------------------------------------------------


def _make_hass(domain: str, strain_library: object | None = None) -> MagicMock:
    """Return a minimal mock hass with optional strain library."""
    hass = MagicMock()
    if strain_library is not None:
        hass.data = {domain: {"strain_library": strain_library}}
    else:
        hass.data = {}
    return hass


def _make_coordinator(plants: dict, genetics_tree: dict) -> MagicMock:
    """Return a mock coordinator with controlled plants and get_lineage_tree."""
    coordinator = MagicMock()
    coordinator.plants = plants
    coordinator.genetics_manager.get_lineage_tree.return_value = genetics_tree
    return coordinator


@pytest.mark.asyncio
async def test_fallback_uses_strain_library_when_no_pollination_parents() -> None:
    """When pollination tree has no parents, strain library parents are grafted in."""
    from custom_components.growspace_manager.const import DOMAIN

    strain_library = MagicMock()
    strain_library.get_strain_lineage_tree.return_value = {
        "name": "OG Kush",
        "source": "library",
        "parents": [
            {"name": "Chemdawg", "source": "manual", "parents": []},
            {"name": "Hindu Kush", "source": "manual", "parents": []},
        ],
    }

    plant = MagicMock()
    plant.genetics.strain_name = "OG Kush"

    pollination_tree = {"name": "OG Kush", "parents": []}
    coordinator = _make_coordinator({"plant-1": plant}, pollination_tree)

    hass = _make_hass(DOMAIN, strain_library)
    connection = MagicMock()
    msg = {"id": 1, "plant_id": "plant-1"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        await websocket_get_lineage_tree(hass, connection, msg)

    connection.send_result.assert_called_once()
    result_tree = connection.send_result.call_args[0][1]
    assert len(result_tree["parents"]) == 2
    parent_names = [p["name"] for p in result_tree["parents"]]
    assert "Chemdawg" in parent_names
    assert "Hindu Kush" in parent_names
    strain_library.get_strain_lineage_tree.assert_called_once_with("OG Kush")


@pytest.mark.asyncio
async def test_no_fallback_when_pollination_tree_has_parents() -> None:
    """When pollination tree already has parents, strain library is NOT consulted."""
    from custom_components.growspace_manager.const import DOMAIN

    strain_library = MagicMock()

    plant = MagicMock()
    plant.genetics.strain_name = "OG Kush"

    pollination_tree = {
        "name": "OG Kush",
        "parents": [
            {"name": "Receiver", "parents": []},
            {"name": "Donor", "parents": []},
        ],
    }
    coordinator = _make_coordinator({"plant-1": plant}, pollination_tree)

    hass = _make_hass(DOMAIN, strain_library)
    connection = MagicMock()
    msg = {"id": 2, "plant_id": "plant-1"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        await websocket_get_lineage_tree(hass, connection, msg)

    connection.send_result.assert_called_once()
    result_tree = connection.send_result.call_args[0][1]
    # Parents come from pollination, not strain library
    assert result_tree["parents"] == pollination_tree["parents"]
    strain_library.get_strain_lineage_tree.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_skipped_when_strain_library_not_loaded() -> None:
    """When strain library is absent from hass.data, no fallback occurs."""
    from custom_components.growspace_manager.const import DOMAIN

    plant = MagicMock()
    plant.genetics.strain_name = "OG Kush"

    pollination_tree = {"name": "OG Kush", "parents": []}
    coordinator = _make_coordinator({"plant-1": plant}, pollination_tree)

    # No strain library in hass.data
    hass = _make_hass(DOMAIN, strain_library=None)
    connection = MagicMock()
    msg = {"id": 3, "plant_id": "plant-1"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        await websocket_get_lineage_tree(hass, connection, msg)

    connection.send_result.assert_called_once()
    result_tree = connection.send_result.call_args[0][1]
    assert result_tree["parents"] == []


@pytest.mark.asyncio
async def test_fallback_skipped_when_strain_library_tree_also_empty() -> None:
    """When strain library tree has no parents either, nothing is grafted."""
    from custom_components.growspace_manager.const import DOMAIN

    strain_library = MagicMock()
    strain_library.get_strain_lineage_tree.return_value = {
        "name": "OG Kush",
        "source": "library",
        "parents": [],
    }

    plant = MagicMock()
    plant.genetics.strain_name = "OG Kush"

    pollination_tree = {"name": "OG Kush", "parents": []}
    coordinator = _make_coordinator({"plant-1": plant}, pollination_tree)

    hass = _make_hass(DOMAIN, strain_library)
    connection = MagicMock()
    msg = {"id": 4, "plant_id": "plant-1"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        await websocket_get_lineage_tree(hass, connection, msg)

    connection.send_result.assert_called_once()
    result_tree = connection.send_result.call_args[0][1]
    assert result_tree["parents"] == []


@pytest.mark.asyncio
async def test_plant_not_found_sends_error() -> None:
    """When plant_id is not in coordinator.plants, an error is returned."""
    coordinator = MagicMock()
    coordinator.plants = {}

    hass = MagicMock()
    hass.data = {}
    connection = MagicMock()
    msg = {"id": 5, "plant_id": "missing-plant"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        await websocket_get_lineage_tree(hass, connection, msg)

    connection.send_error.assert_called_once()
    call_args = connection.send_error.call_args[0]
    assert call_args[1] == "invalid_args"
    assert "missing-plant" in call_args[2]
