"""Debug services."""

import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

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


async def _migrate_plants_from_legacy_growspace(
    coordinator: GrowspaceCoordinator,
    legacy_id: str,
    canonical_id: str,
    migrated_plants_info: list[str],
) -> None:
    plants_to_migrate = coordinator.get_growspace_plants(legacy_id)
    _LOGGER.debug(
        "Migrating %d plants from legacy growspace %s to %s",
        len(plants_to_migrate),
        legacy_id,
        canonical_id,
    )

    for plant in plants_to_migrate:
        plant_id = plant.plant_id
        if plant_id in coordinator.plants:
            coordinator.plants[plant_id]["growspace_id"] = canonical_id
            try:
                new_row, new_col = coordinator.find_first_available_position(
                    canonical_id
                )
                coordinator.plants[plant_id]["row"] = new_row
                coordinator.plants[plant_id]["col"] = new_col
                migrated_plants_info.append(
                    f"{plant.strain} ({plant_id}) to {canonical_id} at ({new_row},{new_col})"
                )
            except Exception as e:
                _LOGGER.warning(
                    "Failed to find position for migrated plant %s: %s",
                    plant_id,
                    e,
                )
        else:
            _LOGGER.warning(
                "Plant %s found in growspace %s but not in coordinator.plants",
                plant_id,
                legacy_id,
            )
    coordinator.growspaces.pop(legacy_id, None)
    _LOGGER.debug("Removed legacy growspace %s.", legacy_id)

async def _cleanup_dry_legacy_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    migrated_plants_info: list[str],
    removed_growspaces: list[str],
    legacy_dry: list[str],
) -> None:
    for legacy_id in legacy_dry:
        canonical_dry = coordinator.ensure_special_growspace("dry", "dry")
        await _migrate_plants_from_legacy_growspace(
            coordinator, legacy_id, canonical_dry, migrated_plants_info
        )
        removed_growspaces.append(legacy_id)

async def _cleanup_cure_legacy_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    migrated_plants_info: list[str],
    removed_growspaces: list[str],
    legacy_cure: list[str],
) -> None:
    for legacy_id in legacy_cure:
        canonical_cure = coordinator.ensure_special_growspace("cure", "cure")
        await _migrate_plants_from_legacy_growspace(
            coordinator, legacy_id, canonical_cure, migrated_plants_info
        )
        removed_growspaces.append(legacy_id)


async def debug_cleanup_legacy(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Debug service to cleanup legacy growspaces."""
    dry_only = call.data.get("dry_only", False)
    cure_only = call.data.get("cure_only", False)
    # 'force' parameter was present but not used in original logic, removed for clarity.

    removed_growspaces = []
    migrated_plants_info = []  # Store info about migrated plants for logging

    _LOGGER.debug(
        "Starting legacy cleanup - dry_only=%s, cure_only=%s",
        dry_only,
        cure_only,
    )

    try:
        # Find legacy growspaces
        legacy_dry = [
            gs_id
            for gs_id in coordinator.growspaces
            if gs_id.startswith("dry_overview")
        ]
        legacy_cure = [
            gs_id
            for gs_id in coordinator.growspaces
            if gs_id.startswith("cure_overview")
        ]

        _LOGGER.debug(
            "Found legacy growspaces - dry: %s, cure: %s",
            legacy_dry,
            legacy_cure,
        )

        # Cleanup dry legacy growspaces
        if not cure_only:
            for legacy_id in legacy_dry:
                # Ensure canonical dry exists
                canonical_dry = coordinator.ensure_special_growspace("dry", "dry")
                await _migrate_plants_from_legacy_growspace(
                    coordinator, legacy_id, canonical_dry, migrated_plants_info
                )
                removed_growspaces.append(legacy_id)

        # Cleanup cure legacy growspaces
        if not dry_only:
            for legacy_id in legacy_cure:
                canonical_cure = coordinator.ensure_special_growspace("cure", "cure")
                await _migrate_plants_from_legacy_growspace(
                    coordinator, legacy_id, canonical_cure, migrated_plants_info
                )
                removed_growspaces.append(legacy_id)

        # Update coordinator data and save
        coordinator.data["growspaces"] = coordinator.growspaces
        coordinator.data["plants"] = coordinator.plants

        await coordinator.async_save()

        _LOGGER.debug(
            "Cleanup complete - removed %d growspaces. Migrated plants: %s",
            len(removed_growspaces),
            migrated_plants_info if migrated_plants_info else "None",
        )

    except Exception as e:
        _LOGGER.exception("Legacy cleanup failed: %s", e)
        raise


async def debug_list_growspaces(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Debug service to list all growspaces."""
    _LOGGER.debug("=== Current Growspaces ===")
    if not coordinator.growspaces:
        _LOGGER.debug("No growspaces found.")
        return

    for gs_id, gs_data in coordinator.growspaces.items():
        plant_count = len(coordinator.get_growspace_plants(gs_id))
        _LOGGER.debug(
            "%s -> name='%s', plants=%d, rows=%s, cols=%s",
            gs_id,
            gs_data.get("name"),
            plant_count,
            gs_data.get("rows"),
            gs_data.get("plants_per_row"),
        )

    _LOGGER.debug("=== Plants by Growspace ===")
    for gs_id in coordinator.growspaces:
        plants = coordinator.get_growspace_plants(gs_id)
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
            _LOGGER.debug("%s has 0 plants.", gs_id)


async def _restore_plants_to_canonical_growspace(
    coordinator: GrowspaceCoordinator,
    canonical_id: str,
    plants_data_to_restore: list[dict],
    log_prefix: str,
) -> None:
    restored_count = 0
    for plant_data in plants_data_to_restore:
        plant_id = plant_data["plant_id"]
        if plant_id in coordinator.plants:
            try:
                new_row, new_col = coordinator.find_first_available_position(
                    canonical_id
                )
                coordinator.plants[plant_id]["growspace_id"] = canonical_id
                coordinator.plants[plant_id]["row"] = new_row
                coordinator.plants[plant_id]["col"] = new_col
                restored_count += 1
                _LOGGER.debug(
                    "Restored %s to %s at (%d,%d) from %s",
                    plant_id,
                    canonical_id,
                    new_row,
                    new_col,
                    plant_data["old_pos"],
                )
            except Exception as e:
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
        if gs_id == "dry" or gs_id.startswith("dry_overview")
    ]

    dry_plants_data_to_restore = []
    if preserve_plants:
        for dry_id in dry_ids_to_remove:
            plants = coordinator.get_growspace_plants(dry_id)
            for plant in plants:
                if plant.plant_id in coordinator.plants:
                    dry_plants_data_to_restore.append(
                        {
                            "plant_id": plant.plant_id,
                            "strain": plant.strain,
                            "old_pos": f"({plant.row},{plant.col})",
                        }
                    )

    for dry_id in dry_ids_to_remove:
        coordinator.growspaces.pop(dry_id, None)
        _LOGGER.debug("Removed dry growspace %s", dry_id)

    canonical_dry = coordinator.ensure_special_growspace("dry", "dry")

    if preserve_plants and dry_plants_data_to_restore:
        await _restore_plants_to_canonical_growspace(
            coordinator, canonical_dry, dry_plants_data_to_restore, "dry"
        )

async def _handle_reset_cure_growspace(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    preserve_plants: bool,
) -> None:
    cure_ids_to_remove = [
        gs_id
        for gs_id in list(coordinator.growspaces.keys())
        if gs_id == "cure" or gs_id.startswith("cure_overview")
    ]

    cure_plants_data_to_restore = []
    if preserve_plants:
        for plant in plants:
            cure_plants_data_to_restore.append(
                {
                    "plant_id": plant.plant_id,
                    "strain": plant.strain,
                    "old_pos": f"({plant.row},{plant.col})",
                }
            )

    for cure_id in cure_ids_to_remove:
        coordinator.growspaces.pop(cure_id, None)
        _LOGGER.debug("Removed cure growspace %s", cure_id)

    canonical_cure = coordinator.ensure_special_growspace("cure", "cure")

    if preserve_plants and cure_plants_data_to_restore:
        await _restore_plants_to_canonical_growspace(
            coordinator, canonical_cure, cure_plants_data_to_restore, "cure"
        )


async def debug_reset_special_growspaces(
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
        await coordinator.async_save()

        _LOGGER.debug("Special growspace reset complete.")

    except Exception as e:
        _LOGGER.exception("Special growspace reset failed: %s", e)
        raise


async def debug_consolidate_duplicate_special(
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
            if gs_data.get("name", "").lower() == "dry":
                dry_growspaces[gs_id] = gs_data
            elif gs_data.get("name", "").lower() == "cure":
                cure_growspaces[gs_id] = gs_data

        _LOGGER.debug("Found dry growspaces: %s", list(dry_growspaces.keys()))
        _LOGGER.debug("Found cure growspaces: %s", list(cure_growspaces.keys()))

        # Consolidate dry growspaces
        if len(dry_growspaces) > 1:
            canonical_dry = "dry"  # Assuming 'dry' is the canonical ID
            duplicate_ids = [
                gs_id for gs_id in dry_growspaces if gs_id != canonical_dry
            ]
            _LOGGER.debug(
                "Consolidating dry duplicates %s -> %s",
                duplicate_ids,
                canonical_dry,
            )

            if canonical_dry not in coordinator.growspaces:
                coordinator.ensure_special_growspace("dry", "dry")

            await _consolidate_plants_to_canonical_growspace(
                coordinator, duplicate_ids, canonical_dry, "dry"
            )

        # Consolidate cure growspaces
        if len(cure_growspaces) > 1:
            canonical_cure = "cure"  # Assuming 'cure' is the canonical ID
            duplicate_ids = [
                gs_id for gs_id in cure_growspaces if gs_id != canonical_cure
            ]
            _LOGGER.debug(
                "Consolidating cure duplicates %s -> %s",
                duplicate_ids,
                canonical_cure,
            )

            if canonical_cure not in coordinator.growspaces:
                coordinator.ensure_special_growspace("cure", "cure")

            await _consolidate_plants_to_canonical_growspace(
                coordinator, duplicate_ids, canonical_cure, "cure"
            )

        coordinator.data["growspaces"] = coordinator.growspaces
        coordinator.data["plants"] = coordinator.plants
        await coordinator.async_save()

        _LOGGER.debug("Duplicate consolidation complete")

    except Exception as e:
        _LOGGER.exception("Duplicate consolidation failed: %s", e)
        raise
