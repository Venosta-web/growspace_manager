"""Plant CRUD and timeline note service handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_AMOUNT_ML,
    ATTR_COL,
    ATTR_EC,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_ROW,
    ATTR_SEED_BATCH_ID,
    ATTR_START_NUMBER,
    ATTR_STRAIN,
    ATTR_TAGS,
    ATTR_TRANSITION_DATE,
    CANONICAL_ID_MOTHER,
    DATE_FIELDS,
    GrowspaceService,
    ATTR_PH,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.plant_utils import (
    _ensure_plant_loaded,
    _resolve_plant_id,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.utils import parse_date_field
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

from custom_components.growspace_manager.schemas import (
    ADD_PLANT_SCHEMA,
    ADD_PLANTS_SCHEMA,
    ADD_TIMELINE_NOTE_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
)

from ._definition import ServiceDefinition

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
            parsed_value = parse_date_field(v)
            update_data[k] = parsed_value
            _LOGGER.debug(
                "UPDATE_PLANT: Parsed date field %s: '%s' -> %s", k, v, parsed_value
            )
        else:
            update_data[k] = v
            _LOGGER.debug("UPDATE_PLANT: Non-date field %s: '%s'", k, v)
    return update_data


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

        add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
        parsed_dates = {f: parse_date_field(call.data.get(f)) for f in add_date_fields}

        if growspace_id == CANONICAL_ID_MOTHER and not parsed_dates.get("mother_start"):
            parsed_dates["mother_start"] = dt_util.utcnow()
            _LOGGER.debug(
                "Auto-setting mother_start to now for '%s' growspace",
                CANONICAL_ID_MOTHER,
            )

        seed_batch_id = call.data.get(ATTR_SEED_BATCH_ID)
        batch = (
            coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
            if seed_batch_id
            else None
        )

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
        gs_id = call.data[ATTR_GROWSPACE_ID]
        if gs_id not in coordinator.growspaces:
            _LOGGER.error("Growspace %s does not exist for add_plants", gs_id)
            raise ServiceValidationError(f"Growspace {gs_id} does not exist")

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
            coordinator.services.genetics.seed_batch_by_id(seed_batch_id)
            if seed_batch_id
            else None
        )
        batch_generation = batch.generation if batch else ""

        add_date_fields = [f for f in DATE_FIELDS if f != "transition_date"]
        parsed_dates = {f: parse_date_field(call.data.get(f)) for f in add_date_fields}

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

            free_row, free_col = coordinator.validator.find_first_available_position(
                growspace_id
            )

            if free_row is None or free_col is None:
                _LOGGER.warning(
                    "Growspace %s is full. Stopped batch add after %d plants",
                    growspace_id,
                    plants_added_count,
                )
                break

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

        service_data = dict(call.data)

        _resolve_position_conflict(coordinator, growspace_id, plant_id, service_data)

        update_data = _prepare_update_data(service_data)

        if not update_data:
            _LOGGER.warning(
                "No update fields provided for plant %s. Service call ignored",
                plant_id,
            )
            return

        if ATTR_STRAIN in update_data and ATTR_PHENOTYPE in update_data:
            strain = update_data[ATTR_STRAIN]
            phenotype = update_data[ATTR_PHENOTYPE]

            strain_key = strain.strip()
            pheno_key = phenotype.strip() if phenotype else "default"

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
        plant_info = coordinator.plants[plant_id]
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
        GrowspaceService.ADD_TIMELINE_NOTE,
        handle_add_timeline_note,
        ADD_TIMELINE_NOTE_SCHEMA,
        needs_strain_lib=True,
    ),
]
