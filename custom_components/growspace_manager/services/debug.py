"""Debug services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    GrowspaceService,
)
from custom_components.growspace_manager.schemas import (
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def handle_test_notification(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle test notification service call."""
    message = call.data.get("message", "Test notification from Growspace Manager")
    create_notification(hass, message, title="Growspace Manager Test")


async def handle_debug_list_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Debug service to list all growspaces."""
    _LOGGER.debug("=== Current Growspaces ===")
    if not coordinator.growspaces:
        _LOGGER.debug("No growspaces found")
        return

    for gs_id, gs_data in coordinator.growspaces.items():
        plant_count = len(coordinator.services.growspaces.get_growspace_plants(gs_id))
        _LOGGER.debug(
            "%s -> name='%s', plants=%d, rows=%s, plants_per_row=%s",
            gs_id,
            gs_data.name,
            plant_count,
            gs_data.rows,
            gs_data.plants_per_row,
        )

    _LOGGER.debug("=== Plants by Growspace ===")
    for gs_id in coordinator.growspaces:
        plants = coordinator.services.growspaces.get_growspace_plants(gs_id)
        if plants:
            _LOGGER.debug("%s has %d plants:", gs_id, len(plants))
            for plant in plants:
                _LOGGER.debug(
                    "  - %s (%s) at (%s,%s)",
                    plant.strain,
                    plant.plant_id,
                    plant.row,
                    plant.col,
                )
        else:
            _LOGGER.debug("%s has 0 plants", gs_id)


async def _restore_plants_to_canonical_growspace(
    coordinator: GrowspaceCoordinator,
    canonical_id: str,
    plants_data_to_restore: list[dict[str, Any]],
    log_prefix: str,
) -> None:
    restored = await coordinator.services.plants.relocate_to_growspace(
        canonical_id, [plant_data["plant_id"] for plant_data in plants_data_to_restore]
    )
    _LOGGER.debug("Restored %d plants to canonical %s", len(restored), log_prefix)


async def _reset_special_growspace(
    coordinator: GrowspaceCoordinator,
    canonical_id: str,
    preserve_plants: bool,
) -> None:
    """Reset one family of special growspaces onto its canonical growspace."""
    ids_to_remove = [
        gs_id
        for gs_id in list(coordinator.growspaces.keys())
        if gs_id == canonical_id or gs_id.startswith(f"{canonical_id}_overview")
    ]

    plants_data_to_restore: list[dict[str, Any]] = []
    if preserve_plants:
        for gs_id in ids_to_remove:
            plants_data_to_restore.extend(
                {
                    "plant_id": plant.plant_id,
                    "strain": plant.strain,
                    "old_pos": f"({plant.row},{plant.col})",
                }
                for plant in coordinator.services.growspaces.get_growspace_plants(gs_id)
                if plant.plant_id in coordinator.plants
            )

    # The canonical growspace is recreated below, so its revision would restart
    # at 0 and let a draft captured before the reset apply afterwards.
    previous_revision = max(
        (
            coordinator.growspaces[gs_id].layout_revision
            for gs_id in ids_to_remove
            if gs_id in coordinator.growspaces
        ),
        default=0,
    )

    for gs_id in ids_to_remove:
        coordinator.growspaces.pop(gs_id, None)
        _LOGGER.debug("Removed %s growspace %s", canonical_id, gs_id)

    canonical = coordinator.services.growspaces.ensure_special_growspace(
        canonical_id, canonical_id
    )
    await coordinator.services.growspaces.carry_forward_layout_revision(
        canonical, previous_revision
    )

    if preserve_plants and plants_data_to_restore:
        await _restore_plants_to_canonical_growspace(
            coordinator, canonical, plants_data_to_restore, canonical_id
        )


async def _handle_reset_dry_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    preserve_plants: bool,
) -> None:
    await _reset_special_growspace(coordinator, CANONICAL_ID_DRY, preserve_plants)


async def _handle_reset_cure_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    preserve_plants: bool,
) -> None:
    await _reset_special_growspace(coordinator, CANONICAL_ID_CURE, preserve_plants)


async def handle_debug_consolidate_duplicate_special(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Debug service to consolidate duplicate dry/cure growspaces."""
    _LOGGER.debug("Starting duplicate special growspace consolidation")

    try:
        dry_growspaces = {}
        cure_growspaces = {}

        for gs_id, gs_data in coordinator.growspaces.items():
            # Using .lower() for case-insensitive comparison of names
            if gs_data.name.lower() == CANONICAL_ID_DRY:
                dry_growspaces[gs_id] = gs_data
            elif gs_data.name.lower() == CANONICAL_ID_CURE:
                cure_growspaces[gs_id] = gs_data

        _LOGGER.debug("Found dry growspaces: %s", list(dry_growspaces.keys()))
        _LOGGER.debug("Found cure growspaces: %s", list(cure_growspaces.keys()))

        # Consolidate dry growspaces
        if len(dry_growspaces) > 1:
            canonical_dry = CANONICAL_ID_DRY  # Assuming 'dry' is the canonical ID
            duplicate_ids = [
                gs_id for gs_id in dry_growspaces if gs_id != canonical_dry
            ]
            _LOGGER.debug(
                "Consolidating dry duplicates %s -> %s",
                duplicate_ids,
                canonical_dry,
            )

            if canonical_dry not in coordinator.growspaces:
                coordinator.services.growspaces.ensure_special_growspace(
                    CANONICAL_ID_DRY, "dry"
                )

            await _consolidate_plants_to_canonical_growspace(
                coordinator, duplicate_ids, canonical_dry, CANONICAL_ID_DRY
            )

        # Consolidate cure growspaces
        if len(cure_growspaces) > 1:
            canonical_cure = CANONICAL_ID_CURE  # Assuming 'cure' is the canonical ID
            duplicate_ids = [
                gs_id for gs_id in cure_growspaces if gs_id != canonical_cure
            ]
            _LOGGER.debug(
                "Consolidating cure duplicates %s -> %s",
                duplicate_ids,
                canonical_cure,
            )

            if canonical_cure not in coordinator.growspaces:
                coordinator.services.growspaces.ensure_special_growspace(
                    CANONICAL_ID_CURE, "cure"
                )

            await _consolidate_plants_to_canonical_growspace(
                coordinator, duplicate_ids, canonical_cure, CANONICAL_ID_CURE
            )

        coordinator.data["growspaces"] = coordinator.growspaces
        coordinator.data["plants"] = coordinator.plants
        await coordinator.services.save()

        _LOGGER.debug("Duplicate consolidation complete")

    except Exception:
        _LOGGER.exception("Duplicate consolidation failed")
        raise


async def handle_debug_reset_special_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Debug service to reset special growspaces (dry/cure)."""
    reset_dry = call.data.get("reset_dry", True)
    reset_cure = call.data.get("reset_cure", True)
    preserve_plants = call.data.get("preserve_plants", True)

    _LOGGER.debug(
        "Starting reset of special growspaces - reset_dry=%s, reset_cure=%s, preserve_plants=%s",
        reset_dry,
        reset_cure,
        preserve_plants,
    )

    try:
        if reset_dry:
            await _handle_reset_dry_growspace(hass, coordinator, preserve_plants)
        if reset_cure:
            await _handle_reset_cure_growspace(hass, coordinator, preserve_plants)

        # Save changes after all resets are done
        coordinator.data["growspaces"] = coordinator.growspaces
        coordinator.data["plants"] = coordinator.plants
        await coordinator.services.save()

        _LOGGER.debug("Special growspace reset complete")

    except Exception:
        _LOGGER.exception("Failed to update strain")
        raise


async def _consolidate_plants_to_canonical_growspace(
    coordinator: GrowspaceCoordinator,
    duplicate_ids: list[str],
    canonical_id: str,
    log_prefix: str,
) -> None:
    """Move plants from duplicate growspaces to the canonical one."""
    plant_ids_to_move = [
        plant.plant_id
        for dup_id in duplicate_ids
        for plant in coordinator.services.growspaces.get_growspace_plants(dup_id)
        if plant.plant_id in coordinator.plants
    ]

    # Relocate before the duplicates are removed, so every source growspace is
    # still present to have its Layout Revision advanced.
    if plant_ids_to_move:
        moved = await coordinator.services.plants.relocate_to_growspace(
            canonical_id, plant_ids_to_move
        )
        _LOGGER.debug(
            "Moved %d plants from duplicate %s growspaces to %s",
            len(moved),
            log_prefix,
            canonical_id,
        )

    for dup_id in duplicate_ids:
        coordinator.growspaces.pop(dup_id, None)
        _LOGGER.debug("Removed duplicate %s growspace %s", log_prefix, dup_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.TEST_NOTIFICATION,
        handle_test_notification,
        None,
    ),
    ServiceDefinition(
        GrowspaceService.DEBUG_LIST_GROWSPACES,
        handle_debug_list_growspaces,
        DEBUG_LIST_GROWSPACES_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL,
        handle_debug_consolidate_duplicate_special,
        DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.DEBUG_RESET_SPECIAL_GROWSPACES,
        handle_debug_reset_special_growspaces,
        DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    ),
]
