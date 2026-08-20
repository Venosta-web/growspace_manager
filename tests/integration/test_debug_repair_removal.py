"""Removal behaviour of the special-growspace repair services.

Every assertion here runs against a live coordinator: `coordinator.growspaces`
is a snapshot rebuilt on each access, so a repair that mutates it removes
nothing from the store and only a real coordinator exposes that.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import (
    DEFAULT_PLANTS_PER_ROW,
    DEFAULT_ROWS,
    DOMAIN,
)
from custom_components.growspace_manager.services.debug import (
    handle_debug_consolidate_duplicate_special,
    handle_debug_reset_special_growspaces,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from tests.common import MockConfigEntry

CANONICAL_DRY = "dry"


@pytest.fixture
def strain_library() -> MagicMock:
    """Return the strain library argument every debug handler ignores."""
    return MagicMock(spec=StrainLibrary)


def _service_call(**data: object) -> ServiceCall:
    """Return a service call carrying the given data."""
    call = MagicMock(spec=ServiceCall)
    call.data = data
    return call


def _reset_call(*, preserve_plants: bool = True) -> ServiceCall:
    """Return a reset call that touches only the dry growspace."""
    return _service_call(
        reset_dry=True, reset_cure=False, preserve_plants=preserve_plants
    )


async def test_consolidation_removes_every_duplicate(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Every emptied duplicate is gone from the store, not just from a snapshot."""
    coordinator = init_integration.runtime_data
    first = await coordinator.services.growspaces.add_growspace(name="dry")
    second = await coordinator.services.growspaces.add_growspace(name="dry")
    plant = await coordinator.services.plants.add_plant(
        growspace_id=first.id, strain="OG Kush"
    )

    await handle_debug_consolidate_duplicate_special(
        hass, coordinator, strain_library, _service_call()
    )

    assert first.id not in coordinator.growspaces
    assert second.id not in coordinator.growspaces
    assert CANONICAL_DRY in coordinator.growspaces
    assert coordinator.plants[plant.plant_id].growspace_id == CANONICAL_DRY


async def test_consolidation_keeps_a_duplicate_it_could_not_empty(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """A plant with nowhere to go keeps its duplicate alive instead of dying with it."""
    coordinator = init_integration.runtime_data
    await coordinator.services.growspaces.update_growspace(
        CANONICAL_DRY, rows=1, plants_per_row=1
    )
    await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )
    duplicate = await coordinator.services.growspaces.add_growspace(name="dry")
    stranded = await coordinator.services.plants.add_plant(
        growspace_id=duplicate.id, strain="Blue Dream"
    )

    await handle_debug_consolidate_duplicate_special(
        hass, coordinator, strain_library, _service_call()
    )

    assert duplicate.id in coordinator.growspaces
    assert coordinator.plants[stranded.plant_id].growspace_id == duplicate.id


async def test_reset_restores_default_dimensions(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """The reset recreates the canonical growspace, so its defaults come back."""
    coordinator = init_integration.runtime_data
    await coordinator.services.growspaces.update_growspace(
        CANONICAL_DRY, rows=DEFAULT_ROWS + 2, plants_per_row=DEFAULT_PLANTS_PER_ROW + 2
    )

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call()
    )

    canonical = coordinator.growspaces[CANONICAL_DRY]
    assert canonical.rows == DEFAULT_ROWS
    assert canonical.plants_per_row == DEFAULT_PLANTS_PER_ROW


async def test_reset_re_places_a_plant_the_default_grid_no_longer_fits(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Shrinking back to the default grid moves a stranded plant, not deletes it."""
    coordinator = init_integration.runtime_data
    await coordinator.services.growspaces.update_growspace(
        CANONICAL_DRY, rows=DEFAULT_ROWS + 2, plants_per_row=DEFAULT_PLANTS_PER_ROW + 2
    )
    plant = await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY,
        strain="OG Kush",
        row=DEFAULT_ROWS + 2,
        col=DEFAULT_PLANTS_PER_ROW + 2,
    )

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call()
    )

    relocated = coordinator.plants[plant.plant_id]
    assert relocated.growspace_id == CANONICAL_DRY
    assert 1 <= relocated.row <= DEFAULT_ROWS
    assert 1 <= relocated.col <= DEFAULT_PLANTS_PER_ROW


async def test_reset_removes_the_duplicates_it_folded_in(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Overview duplicates are removed and their plants land on the canonical."""
    coordinator = init_integration.runtime_data
    # `<canonical>_overview_*` is the legacy id shape the reset folds in; ids
    # minted by `add_growspace` are UUIDs and never match it.
    duplicate_id = coordinator.services.growspaces.ensure_special_growspace(
        f"{CANONICAL_DRY}_overview_1", "dry overview 1"
    )
    plant = await coordinator.services.plants.add_plant(
        growspace_id=duplicate_id, strain="OG Kush"
    )

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call()
    )

    assert duplicate_id not in coordinator.growspaces
    assert coordinator.plants[plant.plant_id].growspace_id == CANONICAL_DRY


async def test_reset_preserving_plants_deletes_none_of_them(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """`preserve_plants: true` keeps every plant, on the recreated canonical."""
    coordinator = init_integration.runtime_data
    plant = await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call()
    )

    assert plant.plant_id in coordinator.plants
    assert coordinator.plants[plant.plant_id].growspace_id == CANONICAL_DRY


async def test_reset_without_preserving_plants_deletes_them(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """`preserve_plants: false` now removes the plants along with the growspace."""
    coordinator = init_integration.runtime_data
    plant = await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call(preserve_plants=False)
    )

    assert plant.plant_id not in coordinator.plants


async def test_reset_leaves_the_canonical_growspace_a_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Removing the canonical takes its device; the reset registers it again."""
    coordinator = init_integration.runtime_data

    await handle_debug_reset_special_growspaces(
        hass, coordinator, strain_library, _reset_call()
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get_device(identifiers={(DOMAIN, CANONICAL_DRY)})
