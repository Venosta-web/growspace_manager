"""Debug services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ..const import (
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    GrowspaceService,
)
from ..schemas import (
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
)
from ..strain_library import StrainLibrary

from ._definition import ServiceDefinition

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

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
        plant_count = len(coordinator.services.get_growspace_plants(gs_id))
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
        plants = coordinator.services.get_growspace_plants(gs_id)
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
    restored_count = 0
    for plant_data in plants_data_to_restore:
        plant_id = plant_data["plant_id"]
        if plant_id in coordinator.plants:
            try:
                new_row, new_col = coordinator.validator.find_first_available_position(
                    canonical_id
                )
                if new_row is None or new_col is None:
                    _LOGGER.warning(
                        "Cannot restore %s: no space in %s", plant_id, canonical_id
                    )
                    continue

                coordinator.plants[plant_id].growspace_id = canonical_id
                coordinator.plants[plant_id].row = new_row
                coordinator.plants[plant_id].col = new_col
                restored_count += 1
                _LOGGER.debug(
                    "Restored %s to %s at (%d,%d) from %s",
                    plant_id,
                    canonical_id,
                    new_row,
                    new_col,
                    plant_data["old_pos"],
                )
            except ValueError as e:
                _LOGGER.warning(
                    "Failed to assign position to preserved plant %s: %s",
                    plant_id,
                    e,
                )
        else:
            _LOGGER.warning(
                "Plant %s to restore not found in coordinator.plants",
                plant_id,
            )
    _LOGGER.debug("Restored %d plants to canonical %s", restored_count, log_prefix)


async def _handle_reset_dry_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    preserve_plants: bool,
) -> None:
    dry_ids_to_remove = [
        gs_id
        for gs_id in list(coordinator.growspaces.keys())
        if gs_id == CANONICAL_ID_DRY or gs_id.startswith("dry_overview")
    ]

    dry_plants_data_to_restore: list[dict[str, Any]] = []
    if preserve_plants:
        for dry_id in dry_ids_to_remove:
            dry_plants_data_to_restore.extend(
                {
                    "plant_id": plant.plant_id,
                    "strain": plant.strain,
                    "old_pos": f"({plant.row},{plant.col})",
                }
                for plant in coordinator.services.get_growspace_plants(dry_id)
                if plant.plant_id in coordinator.plants
            )

    for dry_id in dry_ids_to_remove:
        coordinator.growspaces.pop(dry_id, None)
        _LOGGER.debug("Removed dry growspace %s", dry_id)

    canonical_dry = coordinator.growspace_manager.ensure_special_growspace(
        CANONICAL_ID_DRY, "dry"
    )

    if preserve_plants and dry_plants_data_to_restore:
        await _restore_plants_to_canonical_growspace(
            coordinator, canonical_dry, dry_plants_data_to_restore, CANONICAL_ID_DRY
        )


async def _handle_reset_cure_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    preserve_plants: bool,
) -> None:
    cure_ids_to_remove = [
        gs_id
        for gs_id in list(coordinator.growspaces.keys())
        if gs_id == CANONICAL_ID_CURE or gs_id.startswith("cure_overview")
    ]

    cure_plants_data_to_restore: list[dict[str, Any]] = []
    if preserve_plants:
        for cure_id in cure_ids_to_remove:
            cure_plants_data_to_restore.extend(
                {
                    "plant_id": plant.plant_id,
                    "strain": plant.strain,
                    "old_pos": f"({plant.row},{plant.col})",
                }
                for plant in coordinator.services.get_growspace_plants(cure_id)
                if plant.plant_id in coordinator.plants
            )

    for cure_id in cure_ids_to_remove:
        coordinator.growspaces.pop(cure_id, None)
        _LOGGER.debug("Removed cure growspace %s", cure_id)

    canonical_cure = coordinator.growspace_manager.ensure_special_growspace(
        CANONICAL_ID_CURE, "cure"
    )

    if preserve_plants and cure_plants_data_to_restore:
        await _restore_plants_to_canonical_growspace(
            coordinator, canonical_cure, cure_plants_data_to_restore, CANONICAL_ID_CURE
        )


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
                coordinator.growspace_manager.ensure_special_growspace(
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
                coordinator.growspace_manager.ensure_special_growspace(
                    CANONICAL_ID_CURE, "cure"
                )

            await _consolidate_plants_to_canonical_growspace(
                coordinator, duplicate_ids, canonical_cure, CANONICAL_ID_CURE
            )

        coordinator.data["growspaces"] = coordinator.growspaces
        coordinator.data["plants"] = coordinator.plants
        await coordinator.async_commit()

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
        await coordinator.async_commit()

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
    for dup_id in duplicate_ids:
        plants_to_move = coordinator.services.get_growspace_plants(dup_id)
        for plant in plants_to_move:
            plant_id = plant.plant_id
            if plant_id in coordinator.plants:
                try:
                    new_row, new_col = (
                        coordinator.validator.find_first_available_position(
                            canonical_id
                        )
                    )
                    if new_row is None or new_col is None:
                        _LOGGER.warning(
                            "Cannot move plant %s to %s: No space available",
                            plant_id,
                            canonical_id,
                        )
                        continue

                    plant.growspace_id = canonical_id
                    plant.row = new_row
                    plant.col = new_col
                    _LOGGER.debug(
                        "Moved plant %s from duplicate %s %s to %s at (%d,%d)",
                        plant_id,
                        log_prefix,
                        dup_id,
                        canonical_id,
                        new_row,
                        new_col,
                    )
                except ValueError as e:
                    _LOGGER.warning(
                        "Failed to find position for plant %s from duplicate %s: %s",
                        plant_id,
                        dup_id,
                        e,
                    )
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
