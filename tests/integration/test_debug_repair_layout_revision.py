"""Layout Revision behaviour of the special-growspace repair services."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.exceptions import LayoutConflictError
from custom_components.growspace_manager.services.debug import (
    handle_debug_consolidate_duplicate_special,
    handle_debug_reset_special_growspaces,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall
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


def _draft_from_current(coordinator, growspace_id: str) -> list[dict[str, object]]:
    """Capture the complete layout a client would hold as a draft."""
    return [
        {"plant_id": plant.plant_id, "row": plant.row, "col": plant.col}
        for plant in coordinator.services.growspaces.get_growspace_plants(growspace_id)
    ]


async def test_consolidation_advances_revisions_of_both_growspaces(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Consolidating a duplicate advances the source and the destination."""
    coordinator = init_integration.runtime_data
    duplicate = await coordinator.services.growspaces.add_growspace(name="dry")
    plant = await coordinator.services.plants.add_plant(
        growspace_id=duplicate.id, strain="OG Kush"
    )
    canonical_revision = coordinator.growspaces[CANONICAL_DRY].layout_revision
    duplicate_revision = duplicate.layout_revision

    await handle_debug_consolidate_duplicate_special(
        hass, coordinator, strain_library, _service_call()
    )

    assert duplicate.layout_revision > duplicate_revision
    assert coordinator.growspaces[CANONICAL_DRY].layout_revision > canonical_revision
    assert coordinator.plants[plant.plant_id].growspace_id == CANONICAL_DRY
    assert coordinator.services.growspaces.get_growspace_plants(duplicate.id) == []


async def test_draft_captured_before_consolidation_conflicts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """A pre-consolidation draft is rejected instead of overwriting the repair."""
    coordinator = init_integration.runtime_data
    duplicate = await coordinator.services.growspaces.add_growspace(name="dry")
    await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )
    await coordinator.services.plants.add_plant(
        growspace_id=duplicate.id, strain="Blue Dream"
    )
    stale_revision = coordinator.growspaces[CANONICAL_DRY].layout_revision
    stale_draft = _draft_from_current(coordinator, CANONICAL_DRY)

    await handle_debug_consolidate_duplicate_special(
        hass, coordinator, strain_library, _service_call()
    )
    repaired = _draft_from_current(coordinator, CANONICAL_DRY)

    with pytest.raises(LayoutConflictError):
        await coordinator.services.plants.set_plant_layout(
            CANONICAL_DRY, stale_revision, stale_draft
        )

    assert _draft_from_current(coordinator, CANONICAL_DRY) == repaired


async def test_reset_advances_revision_of_the_canonical_growspace(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """Resetting a special growspace advances its revision past the old one."""
    coordinator = init_integration.runtime_data
    plant = await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )
    previous_revision = coordinator.growspaces[CANONICAL_DRY].layout_revision

    await handle_debug_reset_special_growspaces(
        hass,
        coordinator,
        strain_library,
        _service_call(reset_dry=True, reset_cure=False, preserve_plants=True),
    )

    assert coordinator.growspaces[CANONICAL_DRY].layout_revision > previous_revision
    assert coordinator.plants[plant.plant_id].growspace_id == CANONICAL_DRY


async def test_draft_captured_before_reset_conflicts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    strain_library: MagicMock,
) -> None:
    """A pre-reset draft is rejected even though the growspace was recreated."""
    coordinator = init_integration.runtime_data
    await coordinator.services.plants.add_plant(
        growspace_id=CANONICAL_DRY, strain="OG Kush"
    )
    stale_revision = coordinator.growspaces[CANONICAL_DRY].layout_revision
    stale_draft = _draft_from_current(coordinator, CANONICAL_DRY)

    await handle_debug_reset_special_growspaces(
        hass,
        coordinator,
        strain_library,
        _service_call(reset_dry=True, reset_cure=False, preserve_plants=True),
    )

    with pytest.raises(LayoutConflictError):
        await coordinator.services.plants.set_plant_layout(
            CANONICAL_DRY, stale_revision, stale_draft
        )
