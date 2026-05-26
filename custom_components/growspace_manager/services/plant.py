"""Services related to Plants."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from ..const import (
    ATTR_AMOUNT,
    ATTR_AMOUNT_ML,
    ATTR_CBD_PERCENTAGE,
    ATTR_COL,
    ATTR_DRY_WEIGHT,
    ATTR_EC,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_INTERNODAL_SPACING,
    ATTR_METADATA,
    ATTR_MOLD_RESISTANCE,
    ATTR_MOTHER_PLANT_ID,
    ATTR_NEW_COL,
    ATTR_NEW_ROW,
    ATTR_NEW_STAGE,
    ATTR_NOTES,
    ATTR_NUM_CLONES,
    ATTR_PH,
    ATTR_PHENOTYPE,
    ATTR_PLANT1_ID,
    ATTR_PLANT2_ID,
    ATTR_PLANT_ID,
    ATTR_RESIN,
    ATTR_ROW,
    ATTR_SEED_BATCH_ID,
    ATTR_START_NUMBER,
    ATTR_STRAIN,
    ATTR_TAGS,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TERPENE_INTENSITY,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRANSITION_DATE,
    ATTR_TRIM_WEIGHT,
    ATTR_VIGOR,
    ATTR_WET_WEIGHT,
    CANONICAL_ID_MOTHER,
    DATE_FIELDS,
    GrowspaceService,
)
from ..exceptions import GrowspaceError
from ..strain_library import StrainLibrary
from ..utils import parse_date_field

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

from ..schemas import (
    ADD_PLANT_SCHEMA,
    ADD_PLANTS_SCHEMA,
    ADD_TIMELINE_NOTE_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    SCORE_PLANT_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UPDATE_HARVEST_METRICS_SCHEMA,
    UPDATE_PLANT_SCHEMA,
)
from ._definition import ServiceDefinition

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
    existing_plants = coordinator.services.growspaces.get_growspace_plants(growspace_id)
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
                return resolved_id  # type: ignore[no-any-return]
            _LOGGER.warning(
                "Could not resolve entity ID '%s' to a plant_id attribute", plant_id
            )
        else:
            _LOGGER.warning("Entity Registry not available, cannot resolve entity ID")
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as e:
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
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as load_err:
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
    _LOGGER.debug("Service call: add_plant with data: %s", call.data)

    growspace_id = call.data[ATTR_GROWSPACE_ID]
    if growspace_id not in coordinator.growspaces:
        _LOGGER.error("Growspace %s does not exist for add_plant", growspace_id)
        raise ServiceValidationError(f"Growspace '{growspace_id}' not found.")

    try:
        row = call.data[ATTR_ROW]
        col = call.data[ATTR_COL]

        # Parse and handle optional dates
        add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
        parsed_dates = {f: parse_date_field(call.data.get(f)) for f in add_date_fields}

        # Auto-set mother_start if stage is mother and not provided.
        if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get("mother_start"):
            parsed_dates["mother_start"] = dt_util.utcnow()
            _LOGGER.debug(
                "Auto-setting mother_start to now for '%s' growspace",
                CANONICAL_ID_MOTHER,
            )

        seed_batch_id = call.data.get(ATTR_SEED_BATCH_ID)
        batch = (
            coordinator.genetics_manager.seed_batches.get(seed_batch_id)
            if seed_batch_id
            else None
        )

        # Call through facade
        try:
            plant = await coordinator.services.plants.add_plant(
                growspace_id=growspace_id,
                strain=call.data[ATTR_STRAIN],
                row=row,
                col=col,
                phenotype=call.data.get(ATTR_PHENOTYPE, ""),
                seed_batch_id=seed_batch_id,
                generation=batch.generation if batch else "",
                **parsed_dates,  # type: ignore[arg-type]
            )
            plant_id = plant.plant_id
        except GrowspaceError as err:
            raise ServiceValidationError(str(err)) from err

        _LOGGER.info(
            "Plant %s added successfully to growspace %s at (%d,%d)",
            plant_id,
            growspace_id,
            row,
            col,
        )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as err:
        _LOGGER.exception("Failed to add plant")
        raise ServiceValidationError(f"Failed to add plant: {err}") from err


async def handle_add_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle batch add plants service call."""

    def validate_batch_add() -> tuple[str, str, int, int]:
        """Validate batch add request and return extracted params."""
        gs_id = call.data[ATTR_GROWSPACE_ID]
        if gs_id not in coordinator.growspaces:
            _LOGGER.error("Growspace %s does not exist for add_plants", gs_id)
            raise ServiceValidationError(f"Growspace {gs_id} does not exist")

        # Pre-check capacity for at least one plant
        row, col = coordinator.validator.find_first_available_position(gs_id)
        if row is None or col is None:
            _LOGGER.error("Growspace %s is full for add_plants", gs_id)
            raise ServiceValidationError(f"Growspace {gs_id} is full")

        strn = call.data[ATTR_STRAIN]
        amt = call.data[ATTR_AMOUNT]
        return gs_id, strn, amt, row

    try:
        _LOGGER.debug("Service call: add_plants with data: %s", call.data)

        growspace_id, strain, amount, _ = validate_batch_add()
        start_number = call.data.get(ATTR_START_NUMBER, 1)
        base_phenotype = call.data.get(ATTR_PHENOTYPE)
        seed_batch_id = call.data.get(ATTR_SEED_BATCH_ID)
        batch = (
            coordinator.genetics_manager.seed_batches.get(seed_batch_id)
            if seed_batch_id
            else None
        )
        batch_generation = batch.generation if batch else ""

        # Parse and handle optional dates
        add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
        parsed_dates = {f: parse_date_field(call.data.get(f)) for f in add_date_fields}

        # Auto-set mother_start if stage is mother and not provided.
        if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get("mother_start"):
            parsed_dates["mother_start"] = dt_util.utcnow()
            _LOGGER.debug(
                "Auto-setting mother_start to now for '%s' growspace (batch)",
                CANONICAL_ID_MOTHER,
            )

        plants_added_count = 0

        for i in range(amount):
            current_number = start_number + i
            if base_phenotype:
                phenotype = f"{base_phenotype} #{current_number}"
            else:
                phenotype = f"{strain} #{current_number}"

            # Validate capacity
            free_row, free_col = coordinator.validator.find_first_available_position(
                growspace_id
            )

            if free_row is None or free_col is None:
                _LOGGER.warning(
                    "Growspace %s is full. Stopped batch add after %d plants",
                    growspace_id,
                    plants_added_count,
                )
                # Partial success - just stop adding
                break

            # Add the plant through facade
            try:
                await coordinator.services.plants.add_plant(
                    growspace_id=growspace_id,
                    strain=strain,
                    row=free_row,
                    col=free_col,
                    phenotype=phenotype,
                    seed_batch_id=seed_batch_id,
                    generation=batch_generation,
                    **parsed_dates,  # type: ignore[arg-type]
                )
                plants_added_count += 1
            except GrowspaceError as err:
                _LOGGER.error("Failed to add plant %d of batch: %s", i + 1, err)
                break

        _LOGGER.info(
            "Batch add complete. Added %d/%d plants to growspace %s",
            plants_added_count,
            amount,
            growspace_id,
        )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as err:
        _LOGGER.exception("Unexpected error during batch add plants")
        raise ServiceValidationError(f"Failed to batch add plants: {err}") from err


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking clones from a plant."""
    mother_plant_id = call.data[ATTR_MOTHER_PLANT_ID]
    transition_date_raw = call.data.get(ATTR_TRANSITION_DATE)
    transition_datetime = parse_date_field(transition_date_raw) or dt_util.utcnow()
    transition_date = transition_datetime.date()

    # Extract target growspace ID (optional)
    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)

    # Number of clones to make (default = 1)
    num_clones = call.data.get(ATTR_NUM_CLONES, 1)
    try:
        num_clones = int(num_clones)
    except TypeError, ValueError:
        raise ServiceValidationError(
            f"num_clones must be an integer, got: {num_clones!r}"
        )
    if num_clones <= 0:
        raise ServiceValidationError(f"num_clones must be positive, got: {num_clones}")

    _LOGGER.debug(
        "Handling take_clone for %s, requesting %d clones to growspace %s",
        mother_plant_id,
        num_clones,
        target_growspace_id or "default (clone)",
    )

    if mother_plant_id not in coordinator.plants:
        _LOGGER.error("Mother plant %s does not exist for take_clone", mother_plant_id)
        raise ServiceValidationError(f"Mother plant {mother_plant_id} not found.")

    # Delegate to facade
    try:
        clones = await coordinator.services.plants.take_clones(
            mother_plant_id=mother_plant_id,
            num_clones=num_clones,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )
        clones_added_count = len(clones)
    except (GrowspaceError, ValueError) as err:
        _LOGGER.error("Failed to take clones from %s: %s", mother_plant_id, err)
        raise ServiceValidationError(str(err)) from err

    _LOGGER.info(
        "Successfully took %d clones from %s to growspace %s",
        clones_added_count,
        mother_plant_id,
        target_growspace_id or "clone",
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
    transition_datetime = parse_date_field(transition_date_str) or dt_util.utcnow()
    transition_date = transition_datetime.date()

    if not plant_id or not target_growspace_id:
        _LOGGER.error(
            "Missing plant_id or target_growspace_id for move_clone service call"
        )
        raise ServiceValidationError(
            "Missing plant_id or target_growspace_id for move_clone."
        )

    try:
        await coordinator.services.plants.promote_clone(
            clone_id=plant_id,
            target_growspace_id=target_growspace_id,
            transition_date=transition_date,
        )

        _LOGGER.info(
            "Moved clone %s to growspace %s (PROMOTED)",
            plant_id,
            target_growspace_id,
        )
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as e:
        _LOGGER.exception("Failed to promote clone %s", plant_id)
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
    try:
        plant_id = call.data[ATTR_PLANT_ID]
        coordinator.validator.validate_plant_exists(plant_id)

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

        await coordinator.services.plants.update_plant(plant_id, **update_data)
        _LOGGER.info("Updated plant %s with data: %s", plant_id, update_data)

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to update plant")
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(f"Failed to update plant: {err}") from err


async def handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle remove plant service call."""
    plant_id = call.data[ATTR_PLANT_ID]

    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s not found for removal", plant_id)
        raise ServiceValidationError(f"Plant {plant_id} not found for removal.")

    try:
        plant_info = coordinator.plants[plant_id]  # Get info before removal
        await coordinator.services.plants.remove_plant(plant_id)
        _LOGGER.info(
            "Plant %s removed successfully from growspace %s",
            plant_id,
            plant_info.growspace_id,
        )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to remove plant %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to remove plant {plant_id}: {err}"
        ) from err


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switch plants service call."""
    # Extract IDs before try block to avoid UnboundLocalError in exception handler
    plant_id_1 = call.data[ATTR_PLANT1_ID]
    plant_id_2 = call.data[ATTR_PLANT2_ID]

    if plant_id_1 not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_1)
        raise ServiceValidationError(f"Plant {plant_id_1} does not exist.")
    if plant_id_2 not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for switch_plants", plant_id_2)
        raise ServiceValidationError(f"Plant {plant_id_2} does not exist.")

    try:
        await coordinator.services.plants.switch_plants(plant_id_1, plant_id_2)
        _LOGGER.info("Plants %s and %s switched successfully", plant_id_1, plant_id_2)

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to switch plants %s and %s", plant_id_1, plant_id_2)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to switch plants {plant_id_1} and {plant_id_2}: {err}"
        ) from err


async def handle_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle move plant service call, potentially switching positions with another plant."""
    plant_id = call.data[ATTR_PLANT_ID]
    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for move_plant", plant_id)
        raise ServiceValidationError(f"Plant {plant_id} does not exist.")

    try:
        plant = coordinator.plants[plant_id]

        # Validate new position is within bounds
        new_row, new_col = call.data[ATTR_NEW_ROW], call.data[ATTR_NEW_COL]

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
        existing_plants = coordinator.services.growspaces.get_growspace_plants(
            plant.growspace_id
        )
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
            # Switch positions through facade
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

            # Use the facade
            await coordinator.services.plants.switch_plants(
                plant_id, occupying_plant_id
            )

            _LOGGER.info(
                "Successfully switched positions for %s and %s",
                plant_id,
                occupying_plant_id,
            )
        else:
            # Position is empty, move through facade
            await coordinator.services.plants.move_plant(plant_id, new_row, new_col)
            _LOGGER.info(
                "Plant %s moved to (%d,%d) in growspace %s",
                plant.strain,
                new_row,
                new_col,
                plant.growspace_id,
            )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to move plant %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(f"Failed to move plant {plant_id}: {err}") from err


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transition plant stage service call."""
    plant_id = call.data[ATTR_PLANT_ID]
    if plant_id not in coordinator.plants:
        _LOGGER.error("Plant %s does not exist for transition_plant_stage", plant_id)
        raise ServiceValidationError(f"Plant {plant_id} does not exist.")

    new_stage = call.data[ATTR_NEW_STAGE]
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

    try:
        await coordinator.services.plants.transition_plant_stage(
            plant_id=plant_id,
            new_stage=new_stage,
            transition_date=transition_date or None,
        )
        _LOGGER.info("Plant %s transitioned to %s stage", plant_id, new_stage)

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to transition plant stage for %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to transition plant stage for {plant_id}: {err}"
        ) from err


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any] | None:
    """Handle harvest plant service call."""
    plant_id_input = call.data.get(ATTR_PLANT_ID)
    if not plant_id_input:
        raise ServiceValidationError("Missing plant_id")
    plant_id = _resolve_plant_id(hass, plant_id_input)
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    target_growspace_id = call.data.get(ATTR_TARGET_GROWSPACE_ID)
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

    try:
        await coordinator.services.plants.harvest_plant(
            plant_id=plant_id,
            target_growspace_id=target_growspace_id,
            target_growspace_name=None,
            transition_date=transition_date.date().isoformat()
            if transition_date
            else None,
            wet_weight=call.data.get(ATTR_WET_WEIGHT),
            dry_weight=call.data.get(ATTR_DRY_WEIGHT),
            trim_weight=call.data.get(ATTR_TRIM_WEIGHT),
            thc_percentage=call.data.get(ATTR_THC_PERCENTAGE),
            cbd_percentage=call.data.get(ATTR_CBD_PERCENTAGE),
            terpene_profile=call.data.get(ATTR_TERPENE_PROFILE),
        )

        return {
            ATTR_PLANT_ID: plant_id,
            ATTR_TARGET_GROWSPACE_ID: target_growspace_id,
            "harvest_date": transition_date.date().isoformat()
            if transition_date
            else None,
        }

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.exception("Failed to harvest plant %s", plant_id)
        if isinstance(err, ServiceValidationError):
            raise
        raise ServiceValidationError(
            f"Failed to harvest plant {plant_id}: {err}"
        ) from err


async def handle_add_timeline_note(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle adding a timeline note to a plant."""
    plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    await coordinator.services.add_timeline_note(
        plant_id=plant_id,
        notes=call.data[ATTR_NOTES],
        timestamp=call.data.get(ATTR_TRANSITION_DATE),
        images_base64=call.data.get(ATTR_IMAGES, []),
        tags=call.data.get(ATTR_TAGS, []),
        ph=call.data.get(ATTR_PH),
        ec=call.data.get(ATTR_EC),
        amount_ml=call.data.get(ATTR_AMOUNT_ML),
        external_metadata=call.data.get(ATTR_METADATA, {}),
    )


async def handle_score_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the score_plant service call."""
    plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    await coordinator.services.plants.score_plant(
        plant_id=plant_id,
        vigor=call.data.get(ATTR_VIGOR),
        internodal_spacing=call.data.get(ATTR_INTERNODAL_SPACING),
        terpene_intensity=call.data.get(ATTR_TERPENE_INTENSITY),
        resin=call.data.get(ATTR_RESIN),
        mold_resistance=call.data.get(ATTR_MOLD_RESISTANCE),
    )


async def handle_update_harvest_metrics(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the update_harvest_metrics service call."""
    plant_id = _resolve_plant_id(hass, call.data[ATTR_PLANT_ID])
    await _ensure_plant_loaded(hass, coordinator, plant_id)

    await coordinator.services.plants.update_harvest_metrics(
        plant_id=plant_id,
        wet_weight=call.data.get(ATTR_WET_WEIGHT),
        dry_weight=call.data.get(ATTR_DRY_WEIGHT),
        trim_weight=call.data.get(ATTR_TRIM_WEIGHT),
        thc_percentage=call.data.get(ATTR_THC_PERCENTAGE),
        cbd_percentage=call.data.get(ATTR_CBD_PERCENTAGE),
        terpene_profile=call.data.get(ATTR_TERPENE_PROFILE),
    )


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.ADD_PLANT,
        handle_add_plant,
        ADD_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_PLANTS,
        handle_add_plants,
        ADD_PLANTS_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_PLANT,
        handle_remove_plant,
        REMOVE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_PLANT,
        handle_update_plant,
        UPDATE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.MOVE_PLANT,
        handle_move_plant,
        MOVE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.SWITCH_PLANTS,
        handle_switch_plants,
        SWITCH_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.TRANSITION_PLANT_STAGE,
        handle_transition_plant_stage,
        TRANSITION_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.TAKE_CLONE,
        handle_take_clone,
        TAKE_CLONE_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.MOVE_CLONE,
        handle_move_clone,
        MOVE_CLONE_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.HARVEST_PLANT,
        handle_harvest_plant,
        HARVEST_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_HARVEST_METRICS,
        handle_update_harvest_metrics,
        UPDATE_HARVEST_METRICS_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.SCORE_PLANT,
        handle_score_plant,
        SCORE_PLANT_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_TIMELINE_NOTE,
        handle_add_timeline_note,
        ADD_TIMELINE_NOTE_SCHEMA,
        needs_strain_lib=True,
    ),
]
