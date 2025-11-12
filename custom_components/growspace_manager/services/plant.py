"""Plant services."""

import logging
from datetime import date

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.entity_registry as er

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary
from ..utils import parse_date_field

_LOGGER = logging.getLogger(__name__)


async def handle_add_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the service call to add a new plant."""
    growspace_id = call.data.get("growspace_id")
    growspace = coordinator.growspaces.get(growspace_id)

    if not growspace:
        raise ServiceValidationError(f"Growspace '{growspace_id}' not found.")

    row = call.data.get("row")
    col = call.data.get("col")

    if not (1 <= row <= growspace.rows and 1 <= col <= growspace.plants_per_row):
        raise ServiceValidationError(
            "Position is out of bounds for the selected growspace.",
        )

    # Check for occupant
    occupant = None
    for plant in coordinator.get_growspace_plants(growspace_id):
        if plant.row == row and plant.col == col:
            occupant = plant
            break

    final_row, final_col = row, col

    if occupant:
        _LOGGER.info(
            "Position (%d, %d) in %s is occupied by %s. Finding next available",
            row,
            col,
            growspace_id,
            occupant.strain,
        )
        # Find the next available slot
        new_row, new_col = coordinator.find_first_available_position(growspace_id)

        if new_row is None:
            # Growspace is full
            raise ServiceValidationError(
                f"Growspace '{growspace.name}' is already full occupied.",
            )
        final_row, final_col = new_row, new_col

    try:
        plant_id = await coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=call.data.get("strain"),
            row=final_row,
            col=final_col,
            phenotype=call.data.get("phenotype"),
            clone_start=parse_date_field(call.data.get("clone_start")),
            veg_start=parse_date_field(call.data.get("veg_start")),
            flower_start=parse_date_field(call.data.get("flower_start")),
            mother_start=parse_date_field(call.data.get("mother_start"))
            if growspace_id == "mother"
            else None,
        )
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_added", {"plant_id": plant_id})
    except (ValueError, TypeError, HomeAssistantError) as e:
        _LOGGER.error("Failed to add plant: %s", e)
        raise HomeAssistantError(f"Failed to add plant: {e}") from e


def _validate_plant_exists(
    coordinator: GrowspaceCoordinator,
    plant_id: str,
    plant_type: str = "Plant",
) -> None:
    """Raise ServiceValidationError if a plant does not exist."""
    if not coordinator.plants.get(plant_id):
        raise ServiceValidationError(f"{plant_type} '{plant_id}' not found.")


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking a clone from a mother plant."""
    mother_plant_id = call.data.get("mother_plant_id")
    _validate_plant_exists(coordinator, mother_plant_id, "Mother plant")
    mother_plant = coordinator.plants.get(mother_plant_id)

    num_clones = call.data.get("num_clones", 1)
    if not isinstance(num_clones, int) or num_clones < 1:
        num_clones = 1

    clone_growspace = coordinator.growspaces.get("clone")
    if not clone_growspace:
        raise ServiceValidationError("Clone growspace not found.")

    clones_taken = 0
    try:
        for _ in range(num_clones):
            row, col = coordinator.find_first_available_position("clone")
            if row is None:
                raise ServiceValidationError("No available space in clone growspace.")

            await coordinator.async_add_plant(
                growspace_id="clone",
                strain=mother_plant.strain,
                phenotype=mother_plant.phenotype,
                row=row,
                col=col,
                clone_start=parse_date_field(call.data.get("transition_date"))
                or date.today(),
                source_mother=mother_plant_id,
            )
            clones_taken += 1

        if clones_taken > 0:
            await coordinator.async_save()
            await coordinator.async_request_refresh()
            hass.bus.async_fire(
                f"{DOMAIN}_clones_taken",
                {"mother_plant_id": mother_plant_id, "num_clones": clones_taken},
            )
    except (ServiceValidationError, HomeAssistantError) as e:
        _LOGGER.error("Failed to take clone(s): %s", e)
        raise


async def handle_move_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Move a clone to a new growspace."""
    plant_id = call.data.get("plant_id")
    target_growspace_id = call.data.get("target_growspace_id")

    if not all([plant_id, target_growspace_id]):
        raise ServiceValidationError(
            "Missing required parameters (plant_id, target_growspace_id)."
        )

    _validate_plant_exists(coordinator, plant_id)
    plant = coordinator.plants.get(plant_id)

    try:
        row, col = coordinator.find_first_available_position(target_growspace_id)
        if row is None:
            raise ServiceValidationError(
                f"No available space in '{target_growspace_id}'."
            )

        new_plant_id = await coordinator.async_add_plant(
            growspace_id=target_growspace_id,
            strain=plant.strain,
            phenotype=plant.phenotype,
            row=row,
            col=col,
            veg_start=parse_date_field(call.data.get("transition_date"))
            or date.today(),
        )
        await coordinator.async_remove_plant(plant_id)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(
            f"{DOMAIN}_plant_moved",
            {"plant_id": new_plant_id, "growspace_id": target_growspace_id},
        )
    except (ServiceValidationError, HomeAssistantError) as e:
        _LOGGER.error("Failed to move clone: %s", e)
        raise


async def handle_update_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle updating a plant's details."""
    plant_id = call.data.get("plant_id")
    if not coordinator.plants.get(plant_id):
        raise ServiceValidationError(f"Plant '{plant_id}' not found.")

    update_data = {
        key: value
        for key, value in call.data.items()
        if key != "plant_id" and value is not None
    }

    for key in ("clone_start", "veg_start", "flower_start", "mother_start"):
        if key in update_data:
            update_data[key] = parse_date_field(update_data[key])

    if not update_data:
        _LOGGER.warning(
            "Update plant service called for %s with no data to update", plant_id
        )
        return

    try:
        await coordinator.async_update_plant(plant_id, **update_data)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_updated", {"plant_id": plant_id})
    except (ValueError, HomeAssistantError) as e:
        _LOGGER.error("Failed to update plant: %s", e)
        raise HomeAssistantError(f"Failed to update plant: {e}") from e


async def handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle removing a plant."""
    plant_id = call.data.get("plant_id")
    if not coordinator.plants.get(plant_id):
        raise ServiceValidationError(f"Plant '{plant_id}' not found.")

    try:
        await coordinator.async_remove_plant(plant_id)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_removed", {"plant_id": plant_id})
    except HomeAssistantError as e:
        _LOGGER.error("Failed to remove plant: %s", e)
        raise HomeAssistantError(f"Failed to remove plant: {e}") from e


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switching the positions of two plants."""
    plant_id_1 = call.data.get("plant_id_1")
    plant_id_2 = call.data.get("plant_id_2")

    if not all(
        [coordinator.plants.get(plant_id_1), coordinator.plants.get(plant_id_2)]
    ):
        raise ServiceValidationError("One or both plants not found.")

    try:
        await coordinator.async_switch_plants(plant_id_1, plant_id_2)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(
            f"{DOMAIN}_plants_switched",
            {"plant_ids": [plant_id_1, plant_id_2]},
        )
    except HomeAssistantError as e:
        _LOGGER.error("Failed to switch plants: %s", e)
        raise HomeAssistantError(f"Failed to switch plants: {e}") from e


async def handle_move_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle moving a plant to a new position."""
    plant_id = call.data.get("plant_id")
    new_row = call.data.get("new_row")
    new_col = call.data.get("new_col")
    plant = coordinator.plants.get(plant_id)

    if not plant:
        raise ServiceValidationError(f"Plant '{plant_id}' not found.")

    growspace = coordinator.growspaces.get(plant.growspace_id)
    if not (
        1 <= new_row <= growspace.rows and 1 <= new_col <= growspace.plants_per_row
    ):
        raise ServiceValidationError("Position is out of bounds.")

    occupant = next(
        (
            p
            for p in coordinator.get_growspace_plants(plant.growspace_id)
            if p.row == new_row and p.col == new_col
        ),
        None,
    )

    try:
        if occupant:
            await coordinator.async_switch_plants(plant_id, occupant.plant_id)
            hass.bus.async_fire(
                f"{DOMAIN}_plants_switched",
                {"plant_ids": [plant_id, occupant.plant_id]},
            )
        else:
            await coordinator.async_move_plant(plant_id, new_row, new_col)
            hass.bus.async_fire(f"{DOMAIN}_plant_moved", {"plant_id": plant_id})

        await coordinator.async_save()
        await coordinator.async_request_refresh()
    except HomeAssistantError as e:
        _LOGGER.error("Failed to move plant: %s", e)
        raise HomeAssistantError(f"Failed to move plant: {e}") from e


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transitioning a plant to a new stage."""
    plant_id = call.data.get("plant_id")
    new_stage = call.data.get("new_stage")
    transition_date_str = call.data.get("transition_date")
    transition_date = parse_date_field(transition_date_str)

    if not coordinator.plants.get(plant_id):
        raise ServiceValidationError(f"Plant '{plant_id}' not found.")

    if transition_date is None and transition_date_str is not None:
        raise ServiceValidationError("Invalid date format for transition.")

    try:
        await coordinator.async_transition_plant_stage(
            plant_id,
            new_stage,
            transition_date,
        )
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(
            f"{DOMAIN}_plant_transitioned",
            {"plant_id": plant_id, "new_stage": new_stage},
        )
    except (ValueError, HomeAssistantError) as e:
        _LOGGER.error("Failed to transition plant: %s", e)
        raise HomeAssistantError(f"Failed to transition plant: {e}") from e


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle harvesting a plant."""
    plant_id = call.data.get("plant_id")
    target_growspace_id = call.data.get("target_growspace_id", "dry")
    transition_date_str = call.data.get("transition_date")
    transition_date = parse_date_field(transition_date_str)

    if not plant_id:
        raise ServiceValidationError("Plant ID is required.")

    # Resolve plant_id from entity_id if needed
    if "." in plant_id:
        try:
            entity_registry = er.async_get(hass)
            entity = entity_registry.async_get(plant_id)
            if entity:
                state = hass.states.get(plant_id)
                if state:
                    plant_id = state.attributes.get("plant_id")
        except (AttributeError, TypeError):
            _LOGGER.warning("Could not resolve entity_id %s to plant_id", plant_id)

    plant = coordinator.plants.get(plant_id)
    if not plant:
        await coordinator.async_load()
        plant = coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant '{plant_id}' not found after reload.")

    if transition_date is None and transition_date_str is not None:
        raise ServiceValidationError("Invalid date format for transition.")

    try:
        await coordinator.async_harvest_plant(
            plant_id,
            target_growspace_id,
            transition_date,
        )
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_harvested", {"plant_id": plant_id})
    except HomeAssistantError as e:
        _LOGGER.error("Failed to harvest plant: %s", e)
        raise HomeAssistantError(f"Failed to harvest plant: {e}") from e
