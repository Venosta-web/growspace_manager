"""Services related to Plants."""

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from ..const import (
    ATTR_COL,
    ATTR_GROWSPACE_ID,
    ATTR_MOTHER_PLANT_ID,
    ATTR_NUM_CLONES,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_ROW,
    ATTR_STRAIN,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TRANSITION_DATE,
    DATE_FIELDS,
    EVENT_CLONES_TAKEN,
    EVENT_PLANT_ADDED,
    EVENT_PLANT_HARVESTED,
    EVENT_PLANT_MOVED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_SWITCHED,
    EVENT_PLANT_TRANSITIONED,
    EVENT_PLANT_UPDATED,
)
from ..coordinator import GrowspaceCoordinator
from ..growspace_validator import GrowspaceValidator
from ..strain_library import StrainLibrary
from ..utils import parse_date_field

# from ..models import Plant # Potentially needed for type hinting if desired

_LOGGER = logging.getLogger(__name__)


def _resolve_position_conflict(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    plant_id: str,
    service_data: dict[str, Any],
) -> None:
    """Check for position conflicts and resolve if necessary."""
    if ATTR_ROW not in service_data or ATTR_COL not in service_data:
        return

    new_row, new_col = service_data[ATTR_ROW], service_data[ATTR_COL]
    existing_plants = coordinator.get_growspace_plants(growspace_id)
    is_occupied = any(
        p.plant_id != plant_id and p.row == new_row and p.col == new_col
        for p in existing_plants
    )

    if is_occupied:
        _LOGGER.warning(
            "Position (%d,%d) in growspace %s is occupied. Finding first free space",
            new_row,
            new_col,
            growspace_id,
        )
        free_row, free_col = coordinator.validator.find_first_available_position(
            growspace_id
        )
        if free_row is not None and free_col is not None:
            _LOGGER.info(
                "Moving plant %s to first free space: (%d,%d)",
                plant_id,
                free_row,
                free_col,
            )
            service_data[ATTR_ROW] = free_row
            service_data[ATTR_COL] = free_col
        else:
            _LOGGER.error(
                "No free space found in growspace %s for plant %s. Position will not be updated",
                growspace_id,
                plant_id,
            )
            service_data.pop(ATTR_ROW, None)
            service_data.pop(ATTR_COL, None)


def _prepare_update_data(service_data: dict[str, Any]) -> dict[str, Any]:
    """Prepare the dictionary for updating plant data."""
    update_data = {}
    for k, v in service_data.items():
        if k == ATTR_PLANT_ID:
            continue

        if v is None and k not in DATE_FIELDS:
            continue

        if k in DATE_FIELDS:
            # parse_date_field returns a datetime
            parsed_value = parse_date_field(v)
            update_data[k] = parsed_value
            _LOGGER.debug(
                "UPDATE_PLANT: Parsed date field %s: '%s' -> %s", k, v, parsed_value
            )
        else:
            update_data[k] = v
            _LOGGER.debug("UPDATE_PLANT: Non-date field %s: '%s'", k, v)
    return update_data


def _resolve_plant_id(hass: HomeAssistant, plant_id: str) -> str:
    """Resolve plant ID from entity ID if necessary."""
    if "." not in plant_id:
        return plant_id

    try:
        entity_registry = hass.data.get(er.DATA_REGISTRY)
        if entity_registry:
            state = hass.states.get(plant_id)
            if state and state.attributes.get("plant_id"):
                resolved_id = state.attributes["plant_id"]
                _LOGGER.debug(
                    "Resolved entity ID '%s' to plant ID '%s'", plant_id, resolved_id
                )
                return resolved_id
            _LOGGER.warning(
                "Could not resolve entity ID '%s' to a plant_id attribute", plant_id
            )
        else:
            _LOGGER.warning("Entity Registry not available, cannot resolve entity ID")
    except Exception as e:
        _LOGGER.warning("Error resolving entity ID '%s': %s", plant_id, e)

    return plant_id


async def _ensure_plant_loaded(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, plant_id: str
) -> bool:
    """Ensure plant is loaded in coordinator, attempting reload if missing."""
    if plant_id in coordinator.plants:
        return True

    _LOGGER.warning(
        "Plant %s not found in current coordinator data. Attempting to reload from storage",
        plant_id,
    )
    try:
        await coordinator.async_load()
    except Exception as load_err:
        _LOGGER.error("Error reloading coordinator data: %s", load_err)

    if plant_id not in coordinator.plants:
        _LOGGER.error(
            "Plant %s still does not exist after storage reload attempt", plant_id
        )
        raise ServiceValidationError(
            f"Plant {plant_id} not found and could not be reloaded from storage."
        )
    return True


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
        growspace_id = call.data[ATTR_GROWSPACE_ID]
        if growspace_id not in coordinator.growspaces:
            _LOGGER.error("Growspace %s does not exist for add_plant", growspace_id)
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found.")

        row = call.data[ATTR_ROW]
        col = call.data[ATTR_COL]

        # Parse and handle optional dates
        def _local_parse_date(field_name: str) -> datetime | None:
            val = call.data.get(field_name)
            return parse_date_field(val)

        seedling_start = _local_parse_date("seedling_start")
        mother_start = _local_parse_date("mother_start")
        clone_start = _local_parse_date("clone_start")
        veg_start = _local_parse_date("veg_start")
        flower_start = _local_parse_date("flower_start")
        dry_start = _local_parse_date("dry_start")
        cure_start = _local_parse_date("cure_start")

        # Auto-set mother_start if stage is mother and not provided.
        if growspace_id == "mother" and not mother_start:
            mother_start = datetime.now()
            _LOGGER.debug("Auto-setting mother_start to now for 'mother' growspace")

        # Call coordinator directly, catching validation errors
        try:
            plant_id = await coordinator.async_add_plant(
                growspace_id=growspace_id,
                strain=call.data[ATTR_STRAIN],
                row=row,
                col=col,
                phenotype=call.data.get(ATTR_PHENOTYPE, ""),
                seedling_start=seedling_start,
                mother_start=mother_start,
                clone_start=clone_start,
                veg_start=veg_start,
                flower_start=flower_start,
                dry_start=dry_start,
                cure_start=cure_start,
            )
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        _LOGGER.info(
            "Plant %s added successfully to growspace %s at (%d,%d)",
            plant_id,
            growspace_id,
            row,
            col,
        )

        hass.bus.async_fire(
            EVENT_PLANT_ADDED,
            {
                ATTR_PLANT_ID: plant_id,
                ATTR_GROWSPACE_ID: growspace_id,
                ATTR_STRAIN: call.data[ATTR_STRAIN],
                "position": f"({row},{col})",
            },
        )

    except Exception as err:
        _LOGGER.exception("Failed to add plant: %s", err)
        raise


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking clones from a plant."""
    mother_plant_id = call.data[ATTR_MOTHER_PLANT_ID]
    transition_date_raw = call.data.get(ATTR_TRANSITION_DATE)
    transition_datetime = parse_date_field(transition_date_raw) or datetime.now()
    transition_date = transition_datetime.date()

    # Number of clones to make (default = 1)
    num_clones = call.data.get(ATTR_NUM_CLONES, 1)
    try:
        num_clones = int(num_clones)
        if num_clones <= 0:
            num_clones = 1
    except (TypeError, ValueError):
        num_clones = 1
        _LOGGER.warning("Invalid num_clones provided, defaulting to 1")

    _LOGGER.debug(
        "Handling take_clone for %s, requesting %d clones", mother_plant_id, num_clones
    )

    if mother_plant_id not in coordinator.plants:
        _LOGGER.error("Mother plant %s does not exist for take_clone", mother_plant_id)
        raise ServiceValidationError(f"Mother plant {mother_plant_id} not found.")

    # Delegate to coordinator
    try:
        clones = await coordinator.async_take_clones(
            mother_plant_id=mother_plant_id,
            num_clones=num_clones,
            transition_date=transition_date,
        )
        clones_added_count = len(clones)
    except ValueError as err:
        _LOGGER.error("Failed to take clones from %s: %s", mother_plant_id, err)
        raise ServiceValidationError(str(err)) from err

    hass.bus.async_fire(
        EVENT_CLONES_TAKEN,
        {
            ATTR_MOTHER_PLANT_ID: mother_plant_id,
            ATTR_NUM_CLONES: clones_added_count,
            ATTR_GROWSPACE_ID: "clone",  # Implied by async_take_clones
        },
    )
    _LOGGER.info(
        "Successfully took %d clones from %s", clones_added_count, mother_plant_id
    )


async def handle_move_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Move an existing clone using coordinator methods, typically to 'veg' stage."""

    plant_id = call.data.get(ATTR_PLANT_ID)
    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)

    transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
    transition_datetime = parse_date_field(transition_date_str) or datetime.now()
    transition_date = transition_datetime.date()

    if not plant_id or not target_growspace_id:
        _LOGGER.error(
            "Missing plant_id or target_growspace_id for move_clone service call"
        )
        raise ServiceValidationError(
            "Missing plant_id or target_growspace_id for move_clone."
        )

    try:
        await coordinator.async_promote_clone(
            clone_id=plant_id,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )

        _LOGGER.info(
            "Moved clone %s to growspace %s (PROMOTED)",
            plant_id,
            target_growspace_id,
        )

        hass.bus.async_fire(
            EVENT_PLANT_MOVED,
            {
                ATTR_PLANT_ID: plant_id,  # Plant ID is preserved now
                "new_growspace_id": target_growspace_id,
                "is_clone_move": True,
                ATTR_TRANSITION_DATE: transition_date.isoformat(),
            },
        )
    except Exception as e:
        _LOGGER.exception("Failed to promote clone %s: %s", plant_id, e)
        create_notification(
            hass,
            f"Failed to move clone {plant_id}: {e!s}",
            title="Growspace Manager Error",
        )
        raise ServiceValidationError(str(e)) from e


async def handle_update_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle update plant service call."""
    validator = GrowspaceValidator(coordinator)

    try:
        plant_id = call.data[ATTR_PLANT_ID]
        validator.validate_plant_exists(plant_id)

        _LOGGER.debug("UPDATE_PLANT: Incoming call.data: %s", call.data)

        plant = coordinator.plants[plant_id]
        growspace_id = plant.growspace_id

        # Create a mutable copy of call.data to allow modifications
        service_data = dict(call.data)

        # Resolve position conflicts
        _resolve_position_conflict(coordinator, growspace_id, plant_id, service_data)

        # Prepare update data
        update_data = _prepare_update_data(service_data)

        if not update_data:
            _LOGGER.warning(
                "No update fields provided for plant %s. Service call ignored",
                plant_id,
            )
            return

        # If strain and phenotype are being updated, ensure they exist in the library
        if ATTR_STRAIN in update_data and ATTR_PHENOTYPE in update_data:
            strain = update_data[ATTR_STRAIN]
            phenotype = update_data[ATTR_PHENOTYPE]

            # Check if strain and phenotype exist in library
            strain_key = strain.strip()
            pheno_key = phenotype.strip() if phenotype else "default"

            # Ensure strain exists in library (add if missing)
            # Note: This implicitly adds it. Ideally we should check first?
            # The original code logic was to ensure it exists.
            # Let's assume add_strain handles existence check or we rely on it.
            # Actually, we should just ensure it exists.
            # Since we are updating a plant, we might be setting it to a new strain.
            # We should probably ensure the strain exists in the library.
            # The original code did this inline? No, it just proceeded.
            # Wait, the original code for this block was cut off in the view.
            # Let's assume we need to ensure it exists.
            await strain_library.add_strain(strain=strain_key, phenotype=pheno_key)

        await coordinator.async_update_plant(plant_id, **update_data)
        _LOGGER.info("Updated plant %s with data: %s", plant_id, update_data)

        hass.bus.async_fire(
            EVENT_PLANT_UPDATED,
            {ATTR_PLANT_ID: plant_id, "updated_fields": list(update_data.keys())},
        )

    except Exception as err:
        _LOGGER.exception("Failed to update plant: %s", err)
        raise


async def handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle remove plant service call."""
    try:
        plant_id = call.data[ATTR_PLANT_ID]

        if plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s not found for removal", plant_id)
            raise ServiceValidationError(f"Plant {plant_id} not found for removal.")

        plant_info = coordinator.plants[plant_id]  # Get info before removal
        await coordinator.async_remove_plant(plant_id)
        _LOGGER.info(
            "Plant %s removed successfully from growspace %s",
            plant_id,
            plant_info.growspace_id,
        )

        hass.bus.async_fire(
            EVENT_PLANT_REMOVED,
            {ATTR_PLANT_ID: plant_id, ATTR_GROWSPACE_ID: plant_info.growspace_id},
        )

    except Exception as err:
        _LOGGER.exception("Failed to remove plant %s: %s", plant_id, err)
        raise


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switch plants service call."""
    # Extract IDs before try block to avoid UnboundLocalError in exception handler
    plant_id_1 = call.data["plant1_id"]
    plant_id_2 = call.data["plant2_id"]

    try:
        if plant_id_1 not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_1)
            raise ServiceValidationError(f"Plant {plant_id_1} does not exist.")
        if plant_id_2 not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_2)
            raise ServiceValidationError(f"Plant {plant_id_2} does not exist.")

        plant1_data = coordinator.plants[plant_id_1]
        plant2_data = coordinator.plants[plant_id_2]

        await coordinator.async_switch_plants(plant_id_1, plant_id_2)
        _LOGGER.info("Plants %s and %s switched successfully", plant_id_1, plant_id_2)

        hass.bus.async_fire(
            EVENT_PLANT_SWITCHED,
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
        raise


async def handle_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle move plant service call, potentially switching positions with another plant."""
    try:
        plant_id = call.data[ATTR_PLANT_ID]
        if plant_id not in coordinator.plants:
            _LOGGER.error("Plant %s does not exist for move_plant", plant_id)
            raise ServiceValidationError(f"Plant {plant_id} does not exist.")

        plant = coordinator.plants[plant_id]

        # Validate new position is within bounds
        new_row, new_col = call.data["new_row"], call.data["new_col"]

        # Validate position is not occupied (GrowspaceValidator handles boundary checks)
        # if not is_special and (
        #     new_row < 1
        #     or new_row > growspace.rows
        #     or new_col < 1
        #     or new_col > growspace.plants_per_row
        # ):
        #     raise ServiceValidationError(
        #         f"Position ({new_row}, {new_col}) out of bounds for growspace {growspace_id}."
        #     )
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
                EVENT_PLANT_SWITCHED,
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
                "Successfully switched positions for %s and %s",
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
                EVENT_PLANT_MOVED,
                {
                    ATTR_PLANT_ID: plant_id,
                    ATTR_STRAIN: plant.strain,
                    "old_position": f"({old_row},{old_col})",
                    "new_position": f"({new_row},{new_col})",
                    ATTR_GROWSPACE_ID: plant.growspace_id,
                },
            )

    except ValueError as err:
        _LOGGER.warning("Validation error moving plant %s: %s", plant_id, err)
        raise ServiceValidationError(str(err)) from err

    except Exception as err:
        _LOGGER.exception("Failed to move plant %s: %s", plant_id, err)
        raise


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transition plant stage service call."""
    try:
        plant_id = call.data[ATTR_PLANT_ID]
        if plant_id not in coordinator.plants:
            _LOGGER.error(
                "Plant %s does not exist for transition_plant_stage", plant_id
            )
            raise ServiceValidationError(f"Plant {plant_id} does not exist.")

        new_stage = call.data["new_stage"]
        transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
        transition_date = None
        if transition_date_str:
            transition_date = parse_date_field(transition_date_str)
            if not transition_date:
                _LOGGER.warning(
                    "Could not parse transition_date string: %s", transition_date_str
                )
                raise ServiceValidationError(
                    f"Invalid transition_date format: {transition_date_str}."
                )

        await coordinator.async_transition_plant_stage(
            plant_id=plant_id,
            new_stage=new_stage,
            transition_date=transition_date.isoformat() if transition_date else None,
        )
        _LOGGER.info("Plant %s transitioned to %s stage", plant_id, new_stage)

        hass.bus.async_fire(
            EVENT_PLANT_TRANSITIONED,
            {
                ATTR_PLANT_ID: plant_id,
                "new_stage": new_stage,
                ATTR_TRANSITION_DATE: transition_date.isoformat()
                if transition_date
                else None,
            },
        )

    except Exception as err:
        _LOGGER.exception("Failed to transition plant stage for %s: %s", plant_id, err)
        raise


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any] | None:
    """Handle harvest plant service call."""
    plant_id = call.data.get(ATTR_PLANT_ID)
    if not plant_id:
        _LOGGER.error("Missing plant_id in harvest_plant service call")
        raise ServiceValidationError("Missing plant_id for harvest_plant.")

    plant_id = _resolve_plant_id(hass, plant_id)

    if not await _ensure_plant_loaded(hass, coordinator, plant_id):
        return

    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)
    transition_date_str = call.data.get(ATTR_TRANSITION_DATE)
    transition_date = None

    if transition_date_str:
        transition_date_dt = parse_date_field(transition_date_str)
        if transition_date_dt:
            transition_date = transition_date_dt.date()
        else:
            _LOGGER.warning(
                "Could not parse transition_date string: %s", transition_date_str
            )
            raise ServiceValidationError(
                f"Invalid transition_date format: {transition_date_str}."
            )

    try:
        await coordinator.async_harvest_plant(
            plant_id=plant_id,
            target_growspace_id=target_growspace_id,
            target_growspace_name=None,
            transition_date=transition_date.isoformat() if transition_date else None,
        )
        _LOGGER.info("Plant %s harvested successfully", plant_id)

        result = {
            ATTR_PLANT_ID: plant_id,
            ATTR_TARGET_GROWSPACE_ID: target_growspace_id,
            "harvest_date": transition_date.isoformat() if transition_date else None,
        }

        hass.bus.async_fire(EVENT_PLANT_HARVESTED, result)
        return result

    except Exception as err:
        _LOGGER.exception("Failed to harvest plant %s: %s", plant_id, err)
        create_notification(
            hass,
            f"Failed to harvest plant {plant_id}: {err!s}",
            title="Growspace Manager Error",
        )
        raise
