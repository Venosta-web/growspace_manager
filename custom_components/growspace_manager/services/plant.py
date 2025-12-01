"""Services related to Plants."""

import logging
from datetime import date, datetime
from dataclasses import replace

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.helpers.entity_registry import (
    EntityRegistry,
)  # Added for potential entity ID lookup

from ..const import DATE_FIELDS, DOMAIN  # Ensure DATE_FIELDS is imported
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary
# from ..models import Plant # Potentially needed for type hinting if desired

_LOGGER = logging.getLogger(__name__)


async def handle_add_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle add plant service call."""
    _LOGGER.debug(
        "Service call: add_plant with data: %s", call.data
    )  # Changed warning to debug for less noisy logs
    try:
        growspace_id = call.data["growspace_id"]
        if growspace_id not in coordinator.growspaces:
            _LOGGER.error("Growspace %s does not exist for add_plant", growspace_id)
            create_notification(
                hass,
                f"Growspace '{growspace_id}' not found.",
                title="Growspace Manager Error",
            )
            return

        growspace = coordinator.growspaces[growspace_id]

        # Check position bounds
        row, col = call.data["row"], call.data["col"]
        
        # Skip boundary check for special growspaces
        is_special = growspace_id in ["mother", "clone", "dry", "cure"]
        
        if not is_special and (row < 1 or row > growspace.rows or col < 1 or col > growspace.plants_per_row):
            _LOGGER.error(
                "Position (%s,%s) is outside growspace bounds (%dx%d) for %s",
                row,
                col,
                growspace.rows,
                growspace.plants_per_row,
                growspace_id,
            )
            create_notification(
                hass,
                f"Position ({row},{col}) is outside growspace '{growspace_id}' bounds.",
                title="Growspace Manager Error",
            )
            return

        # Check if position is occupied
        existing_plants = coordinator.get_growspace_plants(growspace_id)
        for plant in existing_plants:
            if plant.row == row and plant.col == col:
                _LOGGER.error(
                    "Position (%s,%s) is already occupied in growspace %s",
                    row,
                    col,
                    growspace_id,
                )
                create_notification(
                    hass,
                    f"Position ({row},{col}) in growspace '{growspace_id}' is already occupied.",
                    title="Growspace Manager Error",
                )
                return

        # Parse and handle optional dates
        # Parse and handle optional dates
        def parse_date_field(field_name: str) -> datetime | None:
            val = call.data.get(field_name)
            if isinstance(val, datetime):
                return val
            if isinstance(val, date):
                return datetime.combine(val, datetime.min.time())
            return None  # Leave None if not provided or invalid

        seedling_start = parse_date_field("seedling_start")
        mother_start = parse_date_field("mother_start")
        clone_start = parse_date_field("clone_start")
        veg_start = parse_date_field("veg_start")
        flower_start = parse_date_field("flower_start")
        dry_start = parse_date_field("dry_start")
        cure_start = parse_date_field("cure_start")

        # Auto-set mother_start if stage is mother and not provided.
        # This logic is specific to a 'mother' growspace ID. Ensure 'mother' is a known special ID.
        if growspace_id == "mother" and not mother_start:
            mother_start = datetime.now()
            _LOGGER.debug("Auto-setting mother_start to now for 'mother' growspace.")

        plant_id = await coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=call.data["strain"],
            row=row,
            col=col,
            phenotype=call.data.get("phenotype", ""),
            seedling_start=seedling_start,
            mother_start=mother_start,
            clone_start=clone_start,
            veg_start=veg_start,
            flower_start=flower_start,
            dry_start=dry_start,
            cure_start=cure_start,
        )
        _LOGGER.info(
            "Plant %s added successfully to growspace %s at (%d,%d)",
            plant_id,
            growspace_id,
            row,
            col,
        )

        hass.bus.async_fire(
            f"{DOMAIN}_plant_added",  # Using DOMAIN constant
            {
                "plant_id": plant_id,
                "growspace_id": growspace_id,
                "strain": call.data["strain"],
                "position": f"({row},{col})",
            },
        )

    except Exception as err:
        _LOGGER.exception("Failed to add plant: %s", err)
        create_notification(
            hass,
            f"Failed to add plant: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking clones from a plant."""
    mother_plant_id = call.data["mother_plant_id"]
    transition_date = call.data.get("transition_date")  # Optional transition date
    if transition_date is None:
        transition_date = datetime.now()  # Default to now if not provided

    # Number of clones to make (default = 1)
    num_clones = call.data.get("num_clones", 1)
    try:
        num_clones = int(num_clones)
        if num_clones <= 0:
            num_clones = 1
    except (TypeError, ValueError):
        num_clones = 1
        _LOGGER.warning("Invalid num_clones provided, defaulting to 1.")

    _LOGGER.debug(
        "Handling take_clone for %s, requesting %d clones", mother_plant_id, num_clones
    )

    if mother_plant_id not in coordinator.plants:
        _LOGGER.error("Mother plant %s does not exist for take_clone", mother_plant_id)
        create_notification(
            hass,
            f"Mother plant {mother_plant_id} not found.",
            title="Growspace Manager Error",
        )
        return

    mother = coordinator.plants[mother_plant_id]

    # Use a fixed ID for the clone growspace, e.g., 'clone'. Ensure this ID is handled by your system.
    growspace_id = "clone"
    if (
        growspace_id is None
    ):  # This check is redundant if growspace_id is hardcoded, but good practice if it were dynamic.
        _LOGGER.error("No target growspace ID defined for clones.")
        create_notification(
            hass,
            "Clone growspace ID is not configured.",
            title="Growspace Manager Error",
        )
        return

    clones_added_count = 0
    for i in range(num_clones):
        try:
            row, col = validator.find_first_available_position(growspace_id)
            if row is None or col is None:  # Defensive check
                _LOGGER.warning(
                    "No free slot found for clone %s/%s in growspace %s",
                    i + 1,
                    num_clones,
                    growspace_id,
                )
                break  # Stop trying to add more clones if no space

            await coordinator.async_add_plant(
                growspace_id=growspace_id,
                phenotype=mother.phenotype or "",
                strain=mother.strain or "",
                row=row,
                col=col,
                stage="clone",  # Set stage to clone
                source_mother=mother_plant_id,  # Track lineage
                clone_start=transition_date,  # Use provided transition date if any
            )
            clones_added_count += 1
            _LOGGER.debug(
                "Added clone %d/%d to %s at (%d,%d)",
                i + 1,
                num_clones,
                growspace_id,
                row,
                col,
            )
        except Exception as e:
            _LOGGER.error(
                "Failed to add clone %d/%d to growspace %s: %s",
                i + 1,
                num_clones,
                growspace_id,
                e,
            )
            # Continue trying to add other clones if one fails

    if clones_added_count > 0:
        hass.bus.async_fire(
            f"{DOMAIN}_clones_taken",
            {
                "mother_plant_id": mother_plant_id,
                "target_growspace_id": growspace_id,
                "num_clones_requested": num_clones,
                "num_clones_added": clones_added_count,
            },
        )
        _LOGGER.info(
            "Successfully took %d clones from %s", clones_added_count, mother_plant_id
        )
    else:
        _LOGGER.error("Failed to add any clones for mother plant %s", mother_plant_id)
        create_notification(
            hass,
            f"Failed to add any clones for mother plant {mother_plant_id}.",
            title="Growspace Manager Error",
        )


async def handle_move_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Move an existing clone using coordinator methods, typically to 'veg' stage."""
    from ..growspace_validator import GrowspaceValidator
    validator = GrowspaceValidator(coordinator)

    plant_id = call.data.get("plant_id")
    target_growspace_id = call.data.get("target_growspace_id")
    transition_date_str = call.data.get(
        "transition_date", datetime.now().isoformat()
    )  # Default to now

    if not plant_id or not target_growspace_id:
        _LOGGER.error(
            "Missing plant_id or target_growspace_id for move_clone service call."
        )
        create_notification(
            hass,
            "Missing plant_id or target_growspace_id for move_clone.",
            title="Growspace Manager Error",
        )
        return

    try:
        validator.validate_plant_exists(plant_id)
    except ValueError as err:
        _LOGGER.error("Validation error moving clone: %s", err)
        create_notification(
            hass,
            f"Validation error: {str(err)}",
            title="Growspace Manager Error",
        )
        return

    try:
        transition_date = datetime.fromisoformat(
            transition_date_str.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Invalid transition_date format '%s' for move_clone, using current time.",
            transition_date_str,
        )
        transition_date = datetime.now()

    plant = coordinator.plants[plant_id]

    # Find first available position in target growspace
    try:
        row, col = validator.find_first_available_position(target_growspace_id)
        if row is None or col is None:
            _LOGGER.warning(
                "No free slot in growspace %s for clone %s",
                target_growspace_id,
                plant_id,
            )
            create_notification(
                hass,
                f"No free slot in growspace '{target_growspace_id}' for clone {plant_id}.",
                title="Growspace Manager Error",
            )
            return
    except Exception as e:
        _LOGGER.error(
            "Could not find position in target growspace %s for clone %s: %s",
            target_growspace_id,
            plant_id,
            e,
        )
        create_notification(
            hass,
            f"Could not find position in growspace '{target_growspace_id}' for clone {plant_id}.",
            title="Growspace Manager Error",
        )
        return

    # Add the plant to the new growspace, transitioning stage to 'veg'
    try:
        new_plant_id = await coordinator.async_add_plant(
            growspace_id=target_growspace_id,
            strain=plant.strain,
            phenotype=plant.phenotype,
            row=row,
            col=col,
            stage="veg",  # Transitioning clone to veg
            clone_start=plant.clone_start,  # Keep original clone start date if it exists
            source_mother=plant.source_mother,
            veg_start=transition_date,  # Set veg start date to transition date
        )

        # Remove the old plant (the clone)
        await coordinator.async_remove_plant(plant_id)

        _LOGGER.info(
            "Moved clone %s (now %s) to growspace %s at (%s,%s)",
            plant_id,
            new_plant_id,
            target_growspace_id,
            row,
            col,
        )

        hass.bus.async_fire(
            f"{DOMAIN}_plant_moved",
            {
                "plant_id": new_plant_id,  # New plant ID
                "old_plant_id": plant_id,  # Original plant ID
                "strain": plant.strain,
                "old_growspace_id": plant.growspace_id,
                "new_growspace_id": target_growspace_id,
                "new_position": f"({row},{col})",
                "is_clone_move": True,
                "transition_date": transition_date.isoformat(),
            },
        )
    except Exception as e:
        _LOGGER.exception("Failed to move clone %s: %s", plant_id, e)
        create_notification(
            hass,
            f"Failed to move clone {plant_id}: {str(e)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_update_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle update plant service call."""
    from ..growspace_validator import GrowspaceValidator
    validator = GrowspaceValidator(coordinator)

    try:
        plant_id = call.data["plant_id"]
        validator.validate_plant_exists(plant_id)

        def parse_date_field(val) -> datetime | None:
            """Helper to parse date strings or return None."""
            if not val or val in ("None", ""):
                return None
            if isinstance(val, datetime):
                return val
            if isinstance(val, date):
                return datetime.combine(val, datetime.min.time())
            if isinstance(val, str):
                try:
                    # Attempt to parse ISO format, handling potential timezone 'Z'
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    _LOGGER.warning("Could not parse date string: %s", val)
                    return None
            return None  # Return None for any other type

        _LOGGER.debug("UPDATE_PLANT: Incoming call.data: %s", call.data)

        plant = coordinator.plants[plant_id]
        growspace_id = plant.growspace_id

        # Create a mutable copy of call.data to allow modifications
        service_data = dict(call.data)

        # If position is being updated, check for conflicts
        if "row" in service_data and "col" in service_data:
            new_row, new_col = service_data["row"], service_data["col"]
            existing_plants = coordinator.get_growspace_plants(growspace_id)
            is_occupied = any(
                p.plant_id != plant_id and p.row == new_row and p.col == new_col
                for p in existing_plants
            )

            if is_occupied:
                _LOGGER.warning(
                    "Position (%d,%d) in growspace %s is occupied. Finding first free space.",
                    new_row,
                    new_col,
                    growspace_id,
                )
                free_row, free_col = coordinator.find_first_free_position(growspace_id)
                if free_row is not None and free_col is not None:
                    _LOGGER.info(
                        "Moving plant %s to first free space: (%d,%d)",
                        plant_id,
                        free_row,
                        free_col,
                    )
                    service_data["row"] = free_row
                    service_data["col"] = free_col
                else:
                    _LOGGER.error(
                        "No free space found in growspace %s for plant %s. Position will not be updated.",
                        growspace_id,
                        plant_id,
                    )
                    # Remove row/col from service_data to prevent update
                    service_data.pop("row")
                    service_data.pop("col")

        update_data = {}
        for k, v in service_data.items():
            if k == "plant_id":
                continue

            # Preserve None values if explicitly passed for non-date fields, if intended to clear.
            # Original logic skipped None values for non-date fields. Let's refine this:
            # If `v` is None, and it's a date field, `parse_date_field` handles it.
            # If `v` is None, and it's NOT a date field, should we clear it?
            # For now, let's assume None means 'no change' for non-date fields, as per original code.
            # If you want to allow clearing fields (setting to None), this logic needs adjustment.
            if v is None and k not in DATE_FIELDS:
                continue  # Skip if value is None for non-date fields (original behavior)

            if k in DATE_FIELDS:
                parsed_value = parse_date_field(v)
                update_data[k] = parsed_value
                _LOGGER.debug(
                    "UPDATE_PLANT: Parsed date field %s: '%s' -> %s",
                    k,
                    v,
                    parsed_value,
                )
            else:
                update_data[k] = v
                _LOGGER.debug("UPDATE_PLANT: Non-date field %s: '%s'", k, v)

        if not update_data:  # No fields to update found
            _LOGGER.warning(
                "No update fields provided for plant %s. Service call ignored.",
                plant_id,
            )
            return

        # If strain and phenotype are being updated, ensure they exist in the library
        if "strain" in update_data and "phenotype" in update_data:
            strain = update_data["strain"]
            phenotype = update_data["phenotype"]

            # Check if strain and phenotype exist in library, using keys consistent with StrainLibrary
            strain_key = strain.strip()
            pheno_key = phenotype.strip() if phenotype else "default"

            strain_exists = strain_key in strain_library.strains
            phenotype_exists = False
            if strain_exists:
                phenotype_exists = pheno_key in strain_library.strains[strain_key]["phenotypes"]

            if not strain_exists or not phenotype_exists:
                _LOGGER.info(
                    "Strain '%s' with phenotype '%s' not in library, adding it.",
                    strain,
                    phenotype,
                )
                await strain_library.add_strain(
                    strain,
                    phenotype,
                )

        await coordinator.async_update_plant(plant_id, **update_data)
        _LOGGER.info(
            "Plant %s updated successfully with fields: %s",
            plant_id,
            list(update_data.keys()),
        )

        hass.bus.async_fire(
            f"{DOMAIN}_plant_updated",
            {"plant_id": plant_id, "updated_fields": list(update_data.keys())},
        )

    except Exception as err:
        _LOGGER.exception("Failed to update plant %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to update plant {plant_id}: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle remove plant service call."""
    try:
        plant_id = call.data["plant_id"]

        if plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for remove_plant", plant_id)
            create_notification(
                hass,
                f"Plant {plant_id} does not exist",
                title="Growspace Manager Error",
            )
            return

        plant_info = coordinator.plants[plant_id]  # Get info before removal
        await coordinator.async_remove_plant(plant_id)
        _LOGGER.info(
            "Plant %s removed successfully from growspace %s",
            plant_id,
            plant_info.growspace_id,
        )

        hass.bus.async_fire(
            f"{DOMAIN}_plant_removed",
            {"plant_id": plant_id, "growspace_id": plant_info.growspace_id},
        )

    except Exception as err:
        _LOGGER.exception("Failed to remove plant %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to remove plant {plant_id}: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switch plants service call."""
    try:
        plant_id_1 = call.data["plant1_id"]
        plant_id_2 = call.data["plant2_id"]

        if plant_id_1 not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_1)
            create_notification(
                hass,
                f"Plant {plant_id_1} does not exist.",
                title="Growspace Manager Error",
            )
            return
        if plant_id_2 not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_2)
            create_notification(
                hass,
                f"Plant {plant_id_2} does not exist.",
                title="Growspace Manager Error",
            )
            return

        plant1_data = coordinator.plants[plant_id_1]
        plant2_data = coordinator.plants[plant_id_2]

        await coordinator.async_switch_plants(plant_id_1, plant_id_2)
        _LOGGER.info("Plants %s and %s switched successfully", plant_id_1, plant_id_2)

        hass.bus.async_fire(
            f"{DOMAIN}_plants_switched",
            {
                "plant1_id": plant_id_1,
                "plant1_strain": plant1_data.strain,
                "plant1_old_position": f"({plant1_data.row},{plant1_data.col})",
                "plant2_id": plant_id_2,
                "plant2_strain": plant2_data.strain,
                "plant2_old_position": f"({plant2_data.row},{plant2_data.col})",
            },
        )

    except Exception as err:
        _LOGGER.exception(
            "Failed to switch plants %s and %s: %s", plant_id_1, plant_id_2, err
        )
        create_notification(
            hass,
            f"Failed to switch plants: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle move plant service call, potentially switching positions with another plant."""
    try:
        plant_id = call.data["plant_id"]
        if plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for move_plant", plant_id)
            create_notification(
                hass,
                f"Plant {plant_id} does not exist.",
                title="Growspace Manager Error",
            )
            return

        plant = coordinator.plants[plant_id]
        growspace = coordinator.growspaces[plant.growspace_id]

        # Validate new position is within bounds
        new_row, new_col = call.data["new_row"], call.data["new_col"]
        
        # Skip boundary check for special growspaces
        is_special = plant.growspace_id in ["mother", "clone", "dry", "cure"]
        
        if not is_special and (
            new_row < 1
            or new_row > growspace.rows
            or new_col < 1
            or new_col > growspace.plants_per_row
        ):
            _LOGGER.error(
                "Position (%d,%d) is outside growspace bounds (%dx%d) for plant %s",
                new_row,
                new_col,
                growspace.rows,
                growspace.plants_per_row,
                plant.plant_id,
            )
            create_notification(
                hass,
                f"New position ({new_row},{new_col}) is outside growspace '{plant.growspace_id}' bounds.",
                title="Growspace Manager Error",
            )
            return

        old_row, old_col = plant.row, plant.col

        # Check if new position is occupied by another plant
        existing_plants = coordinator.get_growspace_plants(plant.growspace_id)
        occupying_plant = None
        for other_plant in existing_plants:
            if (
                other_plant.plant_id != plant_id
                and other_plant.row == new_row
                and other_plant.col == new_col
            ):
                occupying_plant = other_plant
                break

        if occupying_plant:
            # Switch positions: move the occupying plant to the original position
            occupying_plant_id = occupying_plant.plant_id

            _LOGGER.info(
                "Switching positions: %s (%d,%d) ↔ %s (%d,%d) in growspace %s",
                plant.strain,
                old_row,
                old_col,
                occupying_plant.strain,
                new_row,
                new_col,
                plant.growspace_id,
            )

            # Use the dedicated switch method
            await coordinator.async_switch_plants(plant_id, occupying_plant_id)

            # Fire event for both plants
            hass.bus.async_fire(
                f"{DOMAIN}_plants_switched",
                {
                    "plant1_id": plant_id,
                    "plant1_strain": plant.strain,
                    "plant1_old_position": f"({old_row},{old_col})",
                    "plant1_new_position": f"({new_row},{new_col})",
                    "plant2_id": occupying_plant_id,
                    "plant2_strain": occupying_plant.strain,
                    "plant2_old_position": f"({new_row},{new_col})",
                    "plant2_new_position": f"({old_row},{old_col})",
                },
            )
            _LOGGER.info(
                "Successfully switched positions for %s and %s.",
                plant_id,
                occupying_plant_id,
            )
        else:
            # Position is empty, just move normally
            await coordinator.async_move_plant(plant_id, new_row, new_col)
            _LOGGER.info(
                "Plant %s moved to (%d,%d) in growspace %s",
                plant.strain,
                new_row,
                new_col,
                plant.growspace_id,
            )
            hass.bus.async_fire(
                f"{DOMAIN}_plant_moved",
                {
                    "plant_id": plant_id,
                    "strain": plant.strain,
                    "old_position": f"({old_row},{old_col})",
                    "new_position": f"({new_row},{new_col})",
                    "growspace_id": plant.growspace_id,
                },
            )

    except Exception as err:
        _LOGGER.exception("Failed to move plant %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to move plant: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transition plant stage service call."""
    try:
        plant_id = call.data["plant_id"]
        if plant_id not in coordinator.plants:
            _LOGGER.error(
                "Plant %s does not exist for transition_plant_stage", plant_id
            )
            create_notification(
                hass,
                f"Plant {plant_id} does not exist.",
                title="Growspace Manager Error",
            )
            return

        new_stage = call.data["new_stage"]
        transition_date_str = call.data.get("transition_date")
        transition_date = None
        if transition_date_str:
            try:
                # Attempt to parse date, ensure it's a date object
                transition_date = datetime.fromisoformat(
                    transition_date_str.replace("Z", "+00:00")
                )
            except ValueError:
                _LOGGER.warning(
                    "Could not parse transition_date string: %s", transition_date_str
                )
                create_notification(
                    hass,
                    f"Invalid transition_date format: {transition_date_str}.",
                    title="Growspace Manager Error",
                )
                return  # Abort if date is invalid and required

        await coordinator.async_transition_plant_stage(
            plant_id=plant_id,
            new_stage=new_stage,
            transition_date=transition_date,
        )
        _LOGGER.info("Plant %s transitioned to %s stage", plant_id, new_stage)

        hass.bus.async_fire(
            f"{DOMAIN}_plant_transitioned",
            {
                "plant_id": plant_id,
                "new_stage": new_stage,
                "transition_date": transition_date.isoformat()
                if transition_date
                else None,
            },
        )

    except Exception as err:
        _LOGGER.exception("Failed to transition plant stage for %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to transition plant stage: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle harvest plant service call."""
    plant_id = call.data.get("plant_id")
    if not plant_id:
        _LOGGER.error("Missing plant_id in harvest_plant service call.")
        create_notification(
            hass, "Missing plant_id for harvest_plant.", title="Growspace Manager Error"
        )
        return

    # Normalize plant_id if entity ID is provided
    if "." in plant_id:
        try:
            # Attempt to resolve entity ID to plant_id attribute
            # This requires accessing the entity registry.
            entity_registry = hass.data.get(er.ENTITY_REGISTRY_DOMAIN)
            if entity_registry:
                # Assuming the entity domain is 'plant' and the integration is the source
                # You might need to adjust the domain and entity_id extraction based on your setup.
                # For example, if your plant entity is `plant.my_plant`, the first part might be 'plant'.
                # It's safer to use `async_get_by_entity_id` if you know the exact entity ID format.
                # A more direct approach is to rely on custom attributes set by the component.
                # Let's assume plant_id is stored in the state attributes.
                state = hass.states.get(plant_id)
                if state and state.attributes.get("plant_id"):
                    plant_id = state.attributes["plant_id"]
                    _LOGGER.debug(
                        "Resolved entity ID '%s' to plant ID '%s'",
                        call.data["plant_id"],
                        plant_id,
                    )
                else:
                    _LOGGER.warning(
                        "Could not resolve entity ID '%s' to a plant_id attribute.",
                        call.data["plant_id"],
                    )
            else:
                _LOGGER.warning(
                    "Entity Registry not available, cannot resolve entity ID."
                )
        except Exception as e:
            _LOGGER.warning(
                "Error resolving entity ID '%s': %s", call.data["plant_id"], e
            )

    # If plant_id not found, try to reload data (generally not recommended as a primary strategy)
    if plant_id not in coordinator.plants:
        _LOGGER.warning(
            "Plant %s not found in current coordinator data. Attempting to reload from storage.",
            plant_id,
        )
        try:
            await coordinator.store.async_load()  # Reloads data into coordinator.data
            await (
                coordinator.async_load()
            )  # Re-initializes coordinator state from loaded data
        except Exception as load_err:
            _LOGGER.error("Error reloading coordinator data: %s", load_err)

        if plant_id not in coordinator.plants:
            _LOGGER.error(
                "Plant %s still does not exist after storage reload attempt.", plant_id
            )
            create_notification(
                hass,
                f"Plant {plant_id} not found and could not be reloaded from storage.",
                title="Growspace Manager Error",
            )
            return

    # Ensure plant exists after potential reload
    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for harvest_plant", plant_id)
        create_notification(
            hass, f"Plant {plant_id} does not exist.", title="Growspace Manager Error"
        )
        return

    target_growspace_id = call.data.get("target_growspace_id")
    transition_date_str = call.data.get("transition_date")
    transition_date = None
    if transition_date_str:
        try:
            transition_date = datetime.fromisoformat(
                transition_date_str.replace("Z", "+00:00")
            ).date()
        except ValueError:
            _LOGGER.warning(
                "Could not parse transition_date string: %s", transition_date_str
            )
            create_notification(
                hass,
                f"Invalid transition_date format: {transition_date_str}.",
                title="Growspace Manager Error",
            )
            return  # Abort if date is invalid

    try:
        await coordinator.async_harvest_plant(
            plant_id=plant_id,
            target_growspace_id=target_growspace_id,
            # target_growspace_name not used by coordinator.async_harvest_plant
            transition_date=transition_date,
        )
        _LOGGER.info("Plant %s harvested successfully", plant_id)

        hass.bus.async_fire(
            f"{DOMAIN}_plant_harvested",
            {
                "plant_id": plant_id,
                "target_growspace_id": target_growspace_id,
                "harvest_date": transition_date.isoformat()
                if transition_date
                else None,
            },
        )

    except Exception as err:
        _LOGGER.exception("Failed to harvest plant %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to harvest plant {plant_id}: {str(err)}",
            title="Growspace Manager Error",
        )
        raise
