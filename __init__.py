"""Growspace Manager integration."""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.device_registry as dr
from homeassistant.helpers.storage import Store
from datetime import date
from homeassistant.helpers import entity_registry as er


from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .services import (
    ADD_GROWSPACE_SCHEMA,
    ADD_PLANT_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    TAKE_CLONE_SCHEMA,
    MOVE_CLONE_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    MOVE_PLANT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the integration via YAML (optional)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growspace Manager from a config entry."""
    _LOGGER.debug("Setting up Growspace Manager integration")

    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}

    coordinator = GrowspaceCoordinator(
        hass,
        store,
        data,
        entry_id=entry.entry_id,
    )
    # Load data into the coordinator
    await coordinator.async_load()

    # Ensure DOMAIN exists in hass.data
    hass.data.setdefault(DOMAIN, {})  # <--- Important
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug("Set up platforms: %s", PLATFORMS)
    # Handle pending growspace
    if "pending_growspace" in hass.data.get(DOMAIN, {}):
        pending = hass.data[DOMAIN].pop("pending_growspace")
        try:
            await coordinator.async_add_growspace(
                name=pending["name"],
                rows=pending["rows"],
                plants_per_row=pending["plants_per_row"],
                notification_target=pending.get("notification_target"),
            )
            _LOGGER.info("Created pending growspace: %s", pending["name"])
        except Exception:
            _LOGGER.exception("Failed to create pending growspace: %s", Exception)

    await _register_services(hass, coordinator)

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )

    return True


async def _register_services(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Register all Growspace Manager services."""

    async def handle_add_growspace(call: ServiceCall) -> None:
        """Handle add growspace service call."""
        try:
            device_registry = dr.async_get(hass)
            mobile_devices = [
                d.name
                for d in device_registry.devices.values()
                if any("mobile_app" in entry_id for entry_id in d.config_entries)
            ]
            notification_target = call.data.get("notification_target")
            if notification_target and notification_target not in mobile_devices:
                notification_target = None

            growspace_id = await coordinator.async_add_growspace(
                name=call.data["name"],
                rows=call.data["rows"],
                plants_per_row=call.data["plants_per_row"],
                notification_target=notification_target,
            )

            _LOGGER.info(
                "Growspace %s added successfully via service call", growspace_id
            )
            hass.bus.async_fire(
                f"{DOMAIN}_growspace_added",
                {"growspace_id": growspace_id, "name": call.data["name"]},
            )

        except Exception as err:
            _LOGGER.error("Failed to add growspace: %s", err)
            create_notification(
                hass,
                f"Failed to add growspace: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_remove_growspace(call: ServiceCall) -> None:
        """Handle remove growspace service call."""
        try:
            await coordinator.async_remove_growspace(call.data["growspace_id"])
            _LOGGER.info("Growspace %s removed successfully", call.data["growspace_id"])
            hass.bus.async_fire(
                f"{DOMAIN}_growspace_removed",
                {"growspace_id": call.data["growspace_id"]},
            )
        except Exception as err:
            _LOGGER.error("Failed to remove growspace: %s", err)
            create_notification(
                hass,
                f"Failed to remove growspace: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_add_plant(call: ServiceCall) -> None:
        """Handle add plant service call."""
        try:
            growspace_id = call.data["growspace_id"]
            if growspace_id not in coordinator.growspaces:
                _LOGGER.exception("Growspace %s does not exist", growspace_id)
                return

            # Check position availability
            growspace = coordinator.growspaces[call.data["growspace_id"]]
            if (
                call.data["row"] > growspace["rows"]
                or call.data["col"] > growspace["plants_per_row"]
            ):
                _LOGGER.exception(
                    "Position %s is outside growspace bounds",
                    ({call.data["row"]}, {call.data["col"]}),
                )

            # Check if position is occupied
            existing_plants = coordinator.get_growspace_plants(
                call.data["growspace_id"]
            )
            for plant in existing_plants:
                if (
                    plant["row"] == call.data["row"]
                    and plant["col"] == call.data["col"]
                ):
                    _LOGGER.exception(
                        "Position %s is already occupied",
                        ({call.data["row"]}, {call.data["col"]}),
                    )
            # Auto-set mother_start if stage is mother and not provided
            mother_start = call.data.get("mother_start")
            if growspace_id == "mother" and not mother_start:
                mother_start = date.today().isoformat()
            plant_id = await coordinator.async_add_plant(
                growspace_id=call.data["growspace_id"],
                strain=call.data["strain"],
                row=call.data["row"],
                col=call.data["col"],
                phenotype=call.data.get("phenotype", ""),
                seedling_start=call.data.get("seedling_start"),
                mother_start=call.data.get("mother_start"),
                clone_start=call.data.get("clone_start"),
                veg_start=call.data.get("veg_start"),
                flower_start=call.data.get("flower_start"),
                dry_start=call.data.get("dry_start"),
                cure_start=call.data.get("cure_start"),
            )

            _LOGGER.info("Plant %s added successfully via service call", plant_id)
            hass.bus.async_fire(
                f"{DOMAIN}_plant_added",
                {
                    "plant_id": plant_id,
                    "growspace_id": call.data["growspace_id"],
                    "strain": call.data["strain"],
                    "position": f"({call.data['row']},{call.data['col']})",
                },
            )

        except Exception as err:
            _LOGGER.error("Failed to add plant: %s", err)
            create_notification(
                hass,
                f"Failed to add plant: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_take_clone(call: ServiceCall) -> None:
        """Handle taking clones from a plant."""
        mother_plant_id = call.data["mother_plant_id"]
        target_growspace_id = call.data.get("target_growspace_id")
        target_growspace_name = call.data.get("target_growspace_name")
        transition_date = call.data.get("transition_date")

        # how many clones to make (default = 3)
        num_clones = call.data.get("num_clones")
        if num_clones is None:
            num_clones = 1
        else:
            try:
                num_clones = int(num_clones)
            except (TypeError, ValueError):
                num_clones = 1
        _LOGGER.info("num clones is %s", num_clones)
        if mother_plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist", mother_plant_id)
            return

        mother = coordinator.plants[mother_plant_id]

        # If no target growspace was provided, use the mother’s growspace
        growspace_id = "clone"
        if growspace_id is None:
            _LOGGER.error("No target growspace available for clones")
            return

        # Place clones in free slots
        for i in range(num_clones):
            row, col = coordinator._find_first_available_position(growspace_id)
            if row is None:
                _LOGGER.warning("No free slot for clone %s/%s", i + 1, num_clones)
                break

            # Add the clone with stage set to "clone"
            await coordinator.async_add_plant(
                growspace_id=growspace_id,
                phenotype=mother.get("phenotype") or "",
                strain=mother.get("strain", "Unknown"),
                row=row,
                col=col,
                stage="clone",
                mother_plant_id=mother_plant_id,  # optional, track lineage
                clone_start=transition_date,  # optional
            )

        await coordinator.async_save()
        await coordinator.async_request_refresh()

    async def handle_move_clone(call: ServiceCall) -> None:
        """Move an existing clone using coordinator methods."""
        plant_id = call.data.get("plant_id")
        target_growspace_id = call.data.get("target_growspace_id")
        transition_date = date.today().isoformat()

        if not plant_id or not target_growspace_id:
            _LOGGER.error("Missing plant_id or target_growspace_id")
            return

        coordinator = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]][
            "coordinator"
        ]

        if plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist", plant_id)
            return

        plant = coordinator.plants[plant_id]
        # Get all the original plant data
        original_data = plant.copy()
        # Find first available position in target growspace
        row, col = coordinator._find_first_available_position(target_growspace_id)
        if row is None or col is None:
            _LOGGER.warning("No free slot in growspace %s", target_growspace_id)
            return

        # Add the plant to the new growspace
        new_plant_id = await coordinator.async_add_plant(
            growspace_id=target_growspace_id,
            strain=original_data.get("strain", "Unknown"),
            phenotype=original_data.get("phenotype"),
            row=row,
            col=col,
            stage="veg",
            clone_start=original_data.get("clone_start"),
            mother_plant_id=original_data.get("mother_plant_id"),
            veg_start=transition_date,
        )

        # Remove the old plant
        await coordinator.async_remove_plant(plant_id)

        _LOGGER.info(
            "Moved clone %s -> %s to growspace %s at (%s,%s)",
            plant_id,
            new_plant_id,
            target_growspace_id,
            row,
            col,
        )

        await coordinator.async_save()
        await coordinator.async_request_refresh()

    async def handle_update_plant(call: ServiceCall) -> None:
        """Handle update plant service call."""
        try:
            plant_id = call.data["plant_id"]
            if plant_id not in coordinator.plants:
                _LOGGER.error("Plant %s does not exist", plant_id)

            # Extract update data, excluding plant_id
            update_data = {
                k: v for k, v in call.data.items() if k != "plant_id" and v is not None
            }

            await coordinator.async_update_plant(plant_id, **update_data)
            _LOGGER.info("Plant %s updated successfully", plant_id)
            hass.bus.async_fire(
                f"{DOMAIN}_plant_updated",
                {"plant_id": plant_id, "updated_fields": list(update_data.keys())},
            )

        except Exception as err:
            _LOGGER.error("Failed to update plant: %s", err)
            create_notification(
                hass,
                f"Failed to update plant: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_remove_plant(call: ServiceCall) -> None:
        """Handle remove plant service call."""
        try:
            plant_id = call.data["plant_id"]
            if plant_id not in coordinator.plants:
                _LOGGER.exception("Plant %s does not exist", {plant_id})

            plant = coordinator.plants[plant_id]
            await coordinator.async_remove_plant(plant_id)
            _LOGGER.info("Plant %s removed successfully", plant_id)
            hass.bus.async_fire(
                f"{DOMAIN}_plant_removed",
                {"plant_id": plant_id, "growspace_id": plant["growspace_id"]},
            )

        except Exception as err:
            _LOGGER.error("Failed to remove plant: %s", err)
            create_notification(
                hass,
                f"Failed to remove plant: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_switch_plants(call: ServiceCall) -> None:
        """Handle switch plants service call."""
        try:
            plant_id_1 = call.data["plant_id_1"]
            plant_id_2 = call.data["plant_id_2"]
            if plant_id_1 not in coordinator.plants:
                _LOGGER.exception("Plant %s does not exist", {plant_id_1})
            if plant_id_2 not in coordinator.plants:
                _LOGGER.exception("Plant %s does not exist", {plant_id_2})

            await coordinator.async_switch_plants(plant_id_1, plant_id_2)
            _LOGGER.info(
                "Plants %s and %s switched successfully", plant_id_1, plant_id_2
            )
            hass.bus.async_fire(
                f"{DOMAIN}_plants_switched",
                {"plant1_id": plant_id_1, "plant2_id": plant_id_2},
            )

        except Exception as err:
            _LOGGER.error("Failed to switch plants: %s", err)
            create_notification(
                hass,
                f"Failed to switch plants: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_move_plant(call: ServiceCall) -> None:
        """Handle move plant service call with position switching."""
        try:
            plant_id = call.data["plant_id"]
            if plant_id not in coordinator.plants:
                _LOGGER.exception("Plant %s does not exist", {plant_id})

            plant = coordinator.plants[plant_id]
            growspace = coordinator.growspaces[plant["growspace_id"]]

            # Validate new position is within bounds
            new_row, new_col = call.data["new_row"], call.data["new_col"]
            if (
                new_row < 1
                or new_row > growspace["rows"]
                or new_col < 1
                or new_col > growspace["plants_per_row"]
            ):
                _LOGGER.exception(
                    "Position %s is outside growspace bounds",
                    ({new_row}, {new_col}),
                )

            # Store original position
            old_row, old_col = plant["row"], plant["col"]

            # Check if new position is occupied by another plant
            existing_plants = coordinator.get_growspace_plants(plant["growspace_id"])
            occupying_plant = None
            for other_plant in existing_plants:
                if (
                    other_plant["plant_id"] != plant_id
                    and other_plant["row"] == new_row
                    and other_plant["col"] == new_col
                ):
                    occupying_plant = other_plant
                    break

            if occupying_plant:
                # Switch positions: move the occupying plant to the original position
                occupying_plant_id = occupying_plant["plant_id"]

                _LOGGER.info(
                    "Switching positions: %s (%d,%d) ↔ %s (%d,%d)",
                    plant["strain"],
                    old_row,
                    old_col,
                    occupying_plant["strain"],
                    new_row,
                    new_col,
                )

                # Use the dedicated switch method
                await coordinator.async_switch_plants(plant_id, occupying_plant_id)

                # Fire event for both plants
                hass.bus.async_fire(
                    f"{DOMAIN}_plants_switched",
                    {
                        "plant1_id": plant_id,
                        "plant1_strain": plant["strain"],
                        "plant1_old_position": f"({old_row},{old_col})",
                        "plant1_new_position": f"({new_row},{new_col})",
                        "plant2_id": occupying_plant_id,
                        "plant2_strain": occupying_plant["strain"],
                        "plant2_old_position": f"({new_row},{new_col})",
                        "plant2_new_position": f"({old_row},{old_col})",
                    },
                )

                _LOGGER.info(
                    "Successfully switched positions: %s moved to (%d,%d), %s moved to (%d,%d)",
                    plant["strain"],
                    new_row,
                    new_col,
                    occupying_plant["strain"],
                    old_row,
                    old_col,
                )
            else:
                # Position is empty, just move normally
                await coordinator.async_move_plant(plant_id, new_row, new_col)

                _LOGGER.info(
                    "Plant %s moved to (%d,%d)", plant["strain"], new_row, new_col
                )
                hass.bus.async_fire(
                    f"{DOMAIN}_plant_moved",
                    {
                        "plant_id": plant_id,
                        "strain": plant["strain"],
                        "old_position": f"({old_row},{old_col})",
                        "new_position": f"({new_row},{new_col})",
                    },
                )

        except Exception as err:
            _LOGGER.error("Failed to move plant: %s", err)
            create_notification(
                hass,
                f"Failed to move plant: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_transition_plant_stage(call: ServiceCall) -> None:
        """Handle transition plant stage service call."""
        try:
            plant_id = call.data["plant_id"]
            if plant_id not in coordinator.plants:
                _LOGGER.exception("Plant %s does not exist", {plant_id})

            await coordinator.async_transition_plant_stage(
                plant_id=plant_id,
                new_stage=call.data["new_stage"],
                transition_date=call.data.get("transition_date"),
            )
            _LOGGER.info(
                "Plant %s transitioned to %s stage", plant_id, call.data["new_stage"]
            )
            hass.bus.async_fire(
                f"{DOMAIN}_plant_transitioned",
                {"plant_id": plant_id, "new_stage": call.data["new_stage"]},
            )

        except Exception as err:
            _LOGGER.error("Failed to transition plant stage: %s", err)
            create_notification(
                hass,
                f"Failed to transition plant stage: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_harvest_plant(call: ServiceCall) -> None:
        """Handle harvest plant service call."""
        try:
            plant_id = call.data["plant_id"]

            # Accept either raw plant_id or an entity_id; normalize if needed
            if "." in plant_id:
                entity = hass.states.get(plant_id)
                if entity and entity.attributes.get("plant_id"):
                    plant_id = entity.attributes["plant_id"]

            # If not found, try a quick storage reload to avoid stale memory edge cases
            if plant_id not in coordinator.plants:
                store_data = await coordinator.store.async_load() or {}
                coordinator.growspaces = store_data.get(
                    "growspaces", coordinator.growspaces
                )
                coordinator.plants = store_data.get("plants", coordinator.plants)
                coordinator.mark_notification_sent = store_data.get(
                    "notifications_sent", coordinator.mark_notification_sent
                )
                coordinator.data = {
                    "growspaces": coordinator.growspaces,
                    "plants": coordinator.plants,
                    "notifications_sent": coordinator.mark_notification_sent,
                }

            if plant_id not in coordinator.plants:
                _LOGGER.error("Plant %s does not exist", plant_id)

            await coordinator.async_harvest_plant(
                plant_id=plant_id,
                target_growspace_id=call.data.get("target_growspace_id"),
                target_growspace_name=call.data.get("target_growspace_name"),
                transition_date=call.data.get("transition_date"),
            )
            _LOGGER.info("Plant %s harvested successfully", plant_id)
            hass.bus.async_fire(
                f"{DOMAIN}_plant_harvested",
                {
                    "plant_id": plant_id,
                    "target_growspace_id": call.data.get("target_growspace_id"),
                },
            )

        except Exception as err:
            _LOGGER.error("Failed to harvest plant: %s", err)
            create_notification(
                hass,
                f"Failed to harvest plant: {str(err)}",
                title="Growspace Manager Error",
            )
            raise

    async def handle_export_strain_library(call: ServiceCall) -> None:
        """Handle export strain library service call."""
        try:
            strains = coordinator.get_strain_options()
            _LOGGER.info("Exported strain library: %s strains", len(strains))
            hass.bus.async_fire(
                f"{DOMAIN}_strain_library_exported", {"strains": strains}
            )
        except Exception as err:
            _LOGGER.error("Failed to export strain library: %s", err)
            raise

    async def handle_import_strain_library(call: ServiceCall) -> None:
        """Handle import strain library service call."""
        try:
            added_count = await coordinator.import_strain_library(
                strains=call.data["strains"],
                replace=call.data.get("replace", False),
            )
            _LOGGER.info("Imported %s strains to library", added_count)
            hass.bus.async_fire(
                f"{DOMAIN}_strain_library_imported", {"added_count": added_count}
            )
        except Exception as err:
            _LOGGER.error("Failed to import strain library: %s", err)
            raise

    async def handle_clear_strain_library(call: ServiceCall) -> None:
        """Handle clear strain library service call."""
        try:
            count = await coordinator.clear_strain_library()
            _LOGGER.info("Cleared %s strains from library", count)
            hass.bus.async_fire(
                f"{DOMAIN}_strain_library_cleared", {"cleared_count": count}
            )
        except Exception as err:
            _LOGGER.error("Failed to clear strain library: %s", err)
            raise

    async def handle_test_notification(call: ServiceCall) -> None:
        """Handle test notification service call."""
        message = call.data.get("message", "Test notification from Growspace Manager")
        create_notification(hass, message, title="Growspace Manager Test")

    async def debug_cleanup_legacy(call):
        """Debug service to cleanup legacy growspaces."""
        coordinator = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]][
            "coordinator"
        ]

        dry_only = call.data.get("dry_only", False)
        cure_only = call.data.get("cure_only", False)
        force = call.data.get("force", False)

        removed_growspaces = []
        migrated_plants = []

        try:
            _LOGGER.info(
                "DEBUG: Starting legacy cleanup - dry_only=%s, cure_only=%s, force=%s",
                dry_only,
                cure_only,
                force,
            )

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

            _LOGGER.info(
                "DEBUG: Found legacy growspaces - dry: %s, cure: %s",
                legacy_dry,
                legacy_cure,
            )

            # Cleanup dry legacy growspaces
            if not cure_only:
                for legacy_id in legacy_dry:
                    # Ensure canonical dry exists
                    canonical_dry = coordinator.ensure_special_growspace("dry", "dry")

                    # Migrate plants
                    plants_to_migrate = coordinator.get_growspace_plants(legacy_id)
                    for plant in plants_to_migrate:
                        plant_id = plant["plant_id"]
                        coordinator.plants[plant_id]["growspace_id"] = canonical_dry
                        # Find available position
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(canonical_dry)
                            )
                            coordinator.plants[plant_id]["row"] = new_row
                            coordinator.plants[plant_id]["col"] = new_col
                            migrated_plants.append(f"{plant['strain']} ({plant_id})")
                        except Exception as e:
                            _LOGGER.warning(
                                "Failed to find position for migrated plant %s: %s",
                                plant_id,
                                e,
                            )

                    # Remove legacy growspace
                    coordinator.growspaces.pop(legacy_id, None)
                    removed_growspaces.append(legacy_id)
                    _LOGGER.info(
                        "DEBUG: Removed legacy dry growspace %s, migrated %d plants",
                        legacy_id,
                        len(plants_to_migrate),
                    )

            # Cleanup cure legacy growspaces
            if not dry_only:
                for legacy_id in legacy_cure:
                    # Ensure canonical cure exists
                    canonical_cure = coordinator.ensure_special_growspace(
                        "cure", "cure"
                    )

                    # Migrate plants
                    plants_to_migrate = coordinator.get_growspace_plants(legacy_id)
                    for plant in plants_to_migrate:
                        plant_id = plant["plant_id"]
                        coordinator.plants[plant_id]["growspace_id"] = canonical_cure
                        # Find available position
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(
                                    canonical_cure
                                )
                            )
                            coordinator.plants[plant_id]["row"] = new_row
                            coordinator.plants[plant_id]["col"] = new_col
                            migrated_plants.append(f"{plant['strain']} ({plant_id})")
                        except Exception:
                            _LOGGER.exception(
                                "Failed to find position for migrated plant %s",
                                plant_id,
                            )

                    # Remove legacy growspace
                    coordinator.growspaces.pop(legacy_id, None)
                    removed_growspaces.append(legacy_id)
                    _LOGGER.info(
                        "DEBUG: Removed legacy cure growspace %s, migrated %d plants",
                        legacy_id,
                        len(plants_to_migrate),
                    )

            # Update coordinator data
            coordinator.data["growspaces"] = coordinator.growspaces
            coordinator.data["plants"] = coordinator.plants

            # Save and notify
            await coordinator.async_save()
            coordinator.async_set_updated_data(coordinator.data)

            _LOGGER.info(
                "DEBUG: Cleanup complete - removed %d growspaces, migrated %d plants",
                len(removed_growspaces),
                len(migrated_plants),
            )

        except Exception:
            _LOGGER.error("DEBUG: Legacy cleanup failed: %s")
            raise

    async def debug_list_growspaces(call):
        """Debug service to list all growspaces."""
        coordinator = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]][
            "coordinator"
        ]

        _LOGGER.info("DEBUG: === Current Growspaces ===")
        for gs_id, gs_data in coordinator.growspaces.items():
            plant_count = len(coordinator.get_growspace_plants(gs_id))
            _LOGGER.info(
                "DEBUG: %s -> name='%s', plants=%d, rows=%s, cols=%s",
                gs_id,
                gs_data.get("name"),
                plant_count,
                gs_data.get("rows"),
                gs_data.get("plants_per_row"),
            )

        _LOGGER.info("DEBUG: === Plants by Growspace ===")
        for gs_id in coordinator.growspaces:
            plants = coordinator.get_growspace_plants(gs_id)
            if plants:
                _LOGGER.info("DEBUG: %s has %d plants:", gs_id, len(plants))
                for plant in plants:
                    _LOGGER.info(
                        "DEBUG:   - %s (%s) at (%s,%s)",
                        plant["strain"],
                        plant["plant_id"],
                        plant["row"],
                        plant["col"],
                    )

    async def debug_reset_special_growspaces(call):
        """Debug service to reset special growspaces to canonical state."""
        coordinator = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]][
            "coordinator"
        ]

        reset_dry = call.data.get("reset_dry", True)
        reset_cure = call.data.get("reset_cure", True)
        preserve_plants = call.data.get("preserve_plants", True)

        _LOGGER.info(
            "DEBUG: Resetting special growspaces - dry=%s, cure=%s, preserve=%s",
            reset_dry,
            reset_cure,
            preserve_plants,
        )

        try:
            if reset_dry:
                # Remove all dry-related growspaces
                dry_ids = [
                    gs_id
                    for gs_id in list(coordinator.growspaces.keys())
                    if gs_id == "dry" or gs_id.startswith("dry_overview")
                ]

                dry_plants = []
                if preserve_plants:
                    # Collect all plants from dry growspaces
                    for dry_id in dry_ids:
                        dry_plants.extend(coordinator.get_growspace_plants(dry_id))

                # Remove all dry growspaces
                for dry_id in dry_ids:
                    coordinator.growspaces.pop(dry_id, None)
                    _LOGGER.info("DEBUG: Removed dry growspace %s", dry_id)

                # Create canonical dry
                canonical_dry = coordinator.ensure_special_growspace("dry", "dry")

                # Restore plants if preserving
                if preserve_plants and dry_plants:
                    for plant in dry_plants:
                        coordinator.plants[plant["plant_id"]]["growspace_id"] = (
                            canonical_dry
                        )
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(canonical_dry)
                            )
                            coordinator.plants[plant["plant_id"]]["row"] = new_row
                            coordinator.plants[plant["plant_id"]]["col"] = new_col
                        except Exception as e:
                            _LOGGER.warning(
                                "Failed to assign position to preserved plant %s: %s",
                                plant["plant_id"],
                                e,
                            )
                    _LOGGER.info(
                        "DEBUG: Restored %d plants to canonical dry", len(dry_plants)
                    )

            if reset_cure:
                # Remove all cure-related growspaces
                cure_ids = [
                    gs_id
                    for gs_id in list(coordinator.growspaces.keys())
                    if gs_id == "cure" or gs_id.startswith("cure_overview")
                ]

                cure_plants = []
                if preserve_plants:
                    # Collect all plants from cure growspaces
                    for cure_id in cure_ids:
                        cure_plants.extend(coordinator.get_growspace_plants(cure_id))

                # Remove all cure growspaces
                for cure_id in cure_ids:
                    coordinator.growspaces.pop(cure_id, None)
                    _LOGGER.info("DEBUG: Removed cure growspace %s", cure_id)

                # Create canonical cure
                canonical_cure = coordinator.ensure_special_growspace("cure", "cure")

                # Restore plants if preserving
                if preserve_plants and cure_plants:
                    for plant in cure_plants:
                        coordinator.plants[plant["plant_id"]]["growspace_id"] = (
                            canonical_cure
                        )
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(
                                    canonical_cure
                                )
                            )
                            coordinator.plants[plant["plant_id"]]["row"] = new_row
                            coordinator.plants[plant["plant_id"]]["col"] = new_col
                        except Exception as e:
                            _LOGGER.warning(
                                "Failed to assign position to preserved plant %s: %s",
                                plant["plant_id"],
                                e,
                            )
                    _LOGGER.info(
                        "DEBUG: Restored %d plants to canonical cure", len(cure_plants)
                    )

            # Update coordinator data
            coordinator.data["growspaces"] = coordinator.growspaces
            coordinator.data["plants"] = coordinator.plants

            # Save and notify
            await coordinator.async_save()
            coordinator.async_set_updated_data(coordinator.data)

            _LOGGER.info("DEBUG: Special growspace reset complete")

        except Exception as e:
            _LOGGER.exception("DEBUG: Special growspace reset failed: %s")
            raise

    async def debug_consolidate_duplicate_special(call):
        """Debug service to consolidate duplicate dry/cure growspaces."""
        coordinator = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]][
            "coordinator"
        ]

        try:
            _LOGGER.info("DEBUG: Starting duplicate special growspace consolidation")

            # Find all dry-related growspaces
            dry_growspaces = {}
            cure_growspaces = {}

            for gs_id, gs_data in coordinator.growspaces.items():
                if gs_data.get("name", "").lower() == "dry":
                    dry_growspaces[gs_id] = gs_data
                elif gs_data.get("name", "").lower() == "cure":
                    cure_growspaces[gs_id] = gs_data

            _LOGGER.info("DEBUG: Found dry growspaces: %s", list(dry_growspaces.keys()))
            _LOGGER.info(
                "DEBUG: Found cure growspaces: %s", list(cure_growspaces.keys())
            )

            # Consolidate dry growspaces
            if len(dry_growspaces) > 1:
                canonical_dry = "dry"
                duplicate_ids = [
                    gs_id for gs_id in dry_growspaces if gs_id != canonical_dry
                ]

                _LOGGER.info(
                    "DEBUG: Consolidating dry duplicates %s -> %s",
                    duplicate_ids,
                    canonical_dry,
                )

                # Ensure canonical exists
                if canonical_dry not in coordinator.growspaces:
                    coordinator.ensure_special_growspace("dry", "dry")

                # Migrate all plants from duplicates to canonical
                total_migrated = 0
                for duplicate_id in duplicate_ids:
                    plants = coordinator.get_growspace_plants(duplicate_id)
                    _LOGGER.info(
                        "DEBUG: Migrating %d plants from %s to %s",
                        len(plants),
                        duplicate_id,
                        canonical_dry,
                    )

                    for plant in plants:
                        plant_id = plant["plant_id"]
                        coordinator.plants[plant_id]["growspace_id"] = canonical_dry
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(canonical_dry)
                            )
                            coordinator.plants[plant_id]["row"] = new_row
                            coordinator.plants[plant_id]["col"] = new_col
                            total_migrated += 1
                            _LOGGER.info(
                                "DEBUG: Migrated plant %s (%s) to position (%d,%d)",
                                plant["strain"],
                                plant_id,
                                new_row,
                                new_col,
                            )
                        except Exception as e:
                            _LOGGER.warning(
                                "Failed to find position for plant %s: %s", plant_id, e
                            )

                    # Remove duplicate growspace
                    coordinator.growspaces.pop(duplicate_id, None)
                    _LOGGER.info(
                        "DEBUG: Removed duplicate dry growspace %s", duplicate_id
                    )

                _LOGGER.info(
                    "DEBUG: Dry consolidation complete - migrated %d plants",
                    total_migrated,
                )

            # Consolidate cure growspaces
            if len(cure_growspaces) > 1:
                canonical_cure = "cure"
                duplicate_ids = [
                    gs_id for gs_id in cure_growspaces if gs_id != canonical_cure
                ]

                _LOGGER.info(
                    "DEBUG: Consolidating cure duplicates %s -> %s",
                    duplicate_ids,
                    canonical_cure,
                )

                # Ensure canonical exists
                if canonical_cure not in coordinator.growspaces:
                    coordinator.ensure_special_growspace("cure", "cure")

                # Migrate all plants from duplicates to canonical
                total_migrated = 0
                for duplicate_id in duplicate_ids:
                    plants = coordinator.get_growspace_plants(duplicate_id)
                    _LOGGER.info(
                        "DEBUG: Migrating %d plants from %s to %s",
                        len(plants),
                        duplicate_id,
                        canonical_cure,
                    )

                    for plant in plants:
                        plant_id = plant["plant_id"]
                        coordinator.plants[plant_id]["growspace_id"] = canonical_cure
                        try:
                            new_row, new_col = (
                                coordinator.find_first_available_position(
                                    canonical_cure
                                )
                            )
                            coordinator.plants[plant_id]["row"] = new_row
                            coordinator.plants[plant_id]["col"] = new_col
                            total_migrated += 1
                            _LOGGER.info(
                                "DEBUG: Migrated plant %s (%s) to position (%d,%d)",
                                plant["strain"],
                                plant_id,
                                new_row,
                                new_col,
                            )
                        except Exception as e:
                            _LOGGER.warning(
                                "Failed to find position for plant %s: %s", plant_id, e
                            )

                    # Remove duplicate growspace
                    coordinator.growspaces.pop(duplicate_id, None)
                    _LOGGER.info(
                        "DEBUG: Removed duplicate cure growspace %s", duplicate_id
                    )

                _LOGGER.info(
                    "DEBUG: Cure consolidation complete - migrated %d plants",
                    total_migrated,
                )

            # Update coordinator data
            coordinator.data["growspaces"] = coordinator.growspaces
            coordinator.data["plants"] = coordinator.plants

            # Save and notify
            await coordinator.async_save()
            coordinator.async_set_updated_data(coordinator.data)

            _LOGGER.info("DEBUG: Duplicate consolidation complete")

        except Exception:
            _LOGGER.error("DEBUG: Duplicate consolidation failed: %s")
            raise

    # Register all services
    services = [
        ("add_growspace", handle_add_growspace, ADD_GROWSPACE_SCHEMA),
        ("remove_growspace", handle_remove_growspace, REMOVE_GROWSPACE_SCHEMA),
        ("add_plant", handle_add_plant, ADD_PLANT_SCHEMA),
        ("update_plant", handle_update_plant, UPDATE_PLANT_SCHEMA),
        ("remove_plant", handle_remove_plant, REMOVE_PLANT_SCHEMA),
        ("move_plant", handle_move_plant, MOVE_PLANT_SCHEMA),
        ("switch_plants", handle_switch_plants, SWITCH_PLANT_SCHEMA),
        (
            "transition_plant_stage",
            handle_transition_plant_stage,
            TRANSITION_PLANT_SCHEMA,
        ),
        ("take_clone", handle_take_clone, TAKE_CLONE_SCHEMA),
        ("move_clone", handle_move_clone, MOVE_CLONE_SCHEMA),
        ("harvest_plant", handle_harvest_plant, HARVEST_PLANT_SCHEMA),
        (
            "export_strain_library",
            handle_export_strain_library,
            EXPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "import_strain_library",
            handle_import_strain_library,
            IMPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "clear_strain_library",
            handle_clear_strain_library,
            CLEAR_STRAIN_LIBRARY_SCHEMA,
        ),
        ("test_notification", handle_test_notification, None),
        ("debug_cleanup_legacy", debug_cleanup_legacy, DEBUG_CLEANUP_LEGACY_SCHEMA),
        ("debug_list_growspaces", debug_list_growspaces, DEBUG_LIST_GROWSPACES_SCHEMA),
        (
            "debug_reset_special_growspaces",
            debug_reset_special_growspaces,
            DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        ),
        (
            "debug_consolidate_growspaces",
            debug_consolidate_duplicate_special,
            DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        ),
    ]

    for service_name, handler, schema in services:
        hass.services.async_register(DOMAIN, service_name, handler, schema=schema)
        _LOGGER.debug("Registered service: %s", service_name)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove all services
        service_names = [
            "add_growspace",
            "remove_growspace",
            "add_plant",
            "update_plant",
            "remove_plant",
            "switch_plant",
            "transition_plant_stage",
            "harvest_plant",
            "export_strain_library",
            "import_strain_library",
            "clear_strain_library",
            "test_notification",
            "debug_cleanup_legacy",
            "debug_list_growspaces",
            "debug_reset_special_growspaces",
            "debug_consolidate_growspaces",
            "move_plant",
        ]

        for service_name in service_names:
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)
                _LOGGER.debug("Removed service: %s", service_name)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry."""
    _LOGGER.debug("Reloading Growspace Manager integration")
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading entry."""
    await hass.config_entries.async_reload(entry.entry_id)
