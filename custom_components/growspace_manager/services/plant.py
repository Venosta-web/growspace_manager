"""Plant services."""
import logging
from datetime import date

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

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
        create_notification(hass, f"Growspace '{growspace_id}' not found.", title="Growspace Manager")
        return

    row = call.data.get("row")
    col = call.data.get("col")

    if not (1 <= row <= growspace.rows and 1 <= col <= growspace.plants_per_row):
        create_notification(hass, "Position is out of bounds for the selected growspace.", title="Growspace Manager")
        return

    for plant in coordinator.get_growspace_plants(growspace_id):
        if plant.row == row and plant.col == col:
            create_notification(hass, "Position is already occupied.", title="Growspace Manager")
            return

    try:
        plant_id = await coordinator.async_add_plant(
            growspace_id=growspace_id,
            strain=call.data.get("strain"),
            row=row,
            col=col,
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
    except Exception as e:
        create_notification(hass, f"Failed to add plant: {e}", title="Growspace Manager")
        raise


async def handle_take_clone(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle taking a clone from a mother plant."""
    mother_plant_id = call.data.get("mother_plant_id")
    mother_plant = coordinator.plants.get(mother_plant_id)

    if not mother_plant:
        create_notification(hass, f"Mother plant '{mother_plant_id}' not found.", title="Growspace Manager")
        return

    num_clones = call.data.get("num_clones", 1)
    if not isinstance(num_clones, int) or num_clones < 1:
        num_clones = 1

    clone_growspace = coordinator.growspaces.get("clone")
    if not clone_growspace:
        create_notification(hass, "Clone growspace not found.", title="Growspace Manager")
        return

    clones_taken = 0
    for _ in range(num_clones):
        row, col = coordinator.find_first_available_position("clone")
        if row is None:
            create_notification(hass, "No available space in clone growspace.", title="Growspace Manager")
            break

        await coordinator.async_add_plant(
            growspace_id="clone",
            strain=mother_plant.strain,
            phenotype=mother_plant.phenotype,
            row=row,
            col=col,
            clone_start=parse_date_field(call.data.get("transition_date")) or date.today(),
            source_mother=mother_plant_id,
        )
        clones_taken += 1

    if clones_taken > 0:
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_clones_taken", {"mother_plant_id": mother_plant_id, "num_clones": clones_taken})


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
        create_notification(hass, "Missing required parameters.", title="Growspace Manager")
        return

    plant = coordinator.plants.get(plant_id)
    if not plant:
        create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
        return

    try:
        row, col = coordinator.find_first_available_position(target_growspace_id)
        if row is None:
            create_notification(hass, f"No available space in '{target_growspace_id}'.", title="Growspace Manager")
            return

        new_plant_id = await coordinator.async_add_plant(
            growspace_id=target_growspace_id,
            strain=plant.strain,
            phenotype=plant.phenotype,
            row=row,
            col=col,
            veg_start=parse_date_field(call.data.get("transition_date")) or date.today(),
        )
        await coordinator.async_remove_plant(plant_id)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_moved", {"plant_id": new_plant_id, "growspace_id": target_growspace_id})
    except Exception as e:
        create_notification(hass, f"Failed to move clone: {e}", title="Growspace Manager")
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
        create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
        return

    update_data = {
        key: value
        for key, value in call.data.items()
        if key != "plant_id" and value is not None
    }

    for key in ["clone_start", "veg_start", "flower_start", "mother_start"]:
        if key in update_data:
            update_data[key] = parse_date_field(update_data[key])

    if not update_data:
        return

    try:
        await coordinator.async_update_plant(plant_id, **update_data)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_updated", {"plant_id": plant_id})
    except Exception as e:
        create_notification(hass, f"Failed to update plant: {e}", title="Growspace Manager")
        raise


async def handle_remove_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle removing a plant."""
    plant_id = call.data.get("plant_id")
    if not coordinator.plants.get(plant_id):
        create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
        return

    try:
        await coordinator.async_remove_plant(plant_id)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_removed", {"plant_id": plant_id})
    except Exception as e:
        create_notification(hass, f"Failed to remove plant: {e}", title="Growspace Manager")
        raise


async def handle_switch_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle switching the positions of two plants."""
    plant_id_1 = call.data.get("plant_id_1")
    plant_id_2 = call.data.get("plant_id_2")

    if not all([coordinator.plants.get(plant_id_1), coordinator.plants.get(plant_id_2)]):
        create_notification(hass, "One or both plants not found.", title="Growspace Manager")
        return

    try:
        await coordinator.async_switch_plants(plant_id_1, plant_id_2)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plants_switched", {"plant_ids": [plant_id_1, plant_id_2]})
    except Exception as e:
        create_notification(hass, f"Failed to switch plants: {e}", title="Growspace Manager")
        raise


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
        create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
        return

    growspace = coordinator.growspaces.get(plant.growspace_id)
    if not (1 <= new_row <= growspace.rows and 1 <= new_col <= growspace.plants_per_row):
        create_notification(hass, "Position is out of bounds.", title="Growspace Manager")
        return

    occupant = next(
        (p for p in coordinator.get_growspace_plants(plant.growspace_id) if p.row == new_row and p.col == new_col),
        None,
    )

    try:
        if occupant:
            await coordinator.async_switch_plants(plant_id, occupant.plant_id)
            hass.bus.async_fire(f"{DOMAIN}_plants_switched", {"plant_ids": [plant_id, occupant.plant_id]})
        else:
            await coordinator.async_move_plant(plant_id, new_row, new_col)
            hass.bus.async_fire(f"{DOMAIN}_plant_moved", {"plant_id": plant_id})

        await coordinator.async_save()
        await coordinator.async_request_refresh()
    except Exception as e:
        create_notification(hass, f"Failed to move plant: {e}", title="Growspace Manager")
        raise


async def handle_transition_plant_stage(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle transitioning a plant to a new stage."""
    plant_id = call.data.get("plant_id")
    new_stage = call.data.get("new_stage")
    transition_date = parse_date_field(call.data.get("transition_date"))

    if not coordinator.plants.get(plant_id):
        create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
        return

    if transition_date is None and call.data.get("transition_date") is not None:
        create_notification(hass, "Invalid date format for transition.", title="Growspace Manager")
        return

    try:
        await coordinator.async_transition_plant_stage(plant_id, new_stage, transition_date)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_transitioned", {"plant_id": plant_id, "new_stage": new_stage})
    except Exception as e:
        create_notification(hass, f"Failed to transition plant: {e}", title="Growspace Manager")
        raise


async def handle_harvest_plant(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle harvesting a plant."""
    plant_id = call.data.get("plant_id")
    target_growspace_id = call.data.get("target_growspace_id", "dry")
    transition_date = parse_date_field(call.data.get("transition_date"))

    if not plant_id:
        create_notification(hass, "Plant ID is required.", title="Growspace Manager")
        return

    # Resolve plant_id from entity_id if needed
    if "." in plant_id:
        try:
            entity_registry = async_get_entity_registry(hass)
            entity = entity_registry.async_get(plant_id)
            if entity:
                state = hass.states.get(plant_id)
                plant_id = state.attributes.get("plant_id")
        except Exception:
            pass  # Ignore if resolution fails

    plant = coordinator.plants.get(plant_id)
    if not plant:
        await coordinator.async_load()
        plant = coordinator.plants.get(plant_id)
        if not plant:
            create_notification(hass, f"Plant '{plant_id}' not found.", title="Growspace Manager")
            return

    if transition_date is None and call.data.get("transition_date") is not None:
        create_notification(hass, "Invalid date format for transition.", title="Growspace Manager")
        return

    try:
        await coordinator.async_harvest_plant(plant_id, target_growspace_id, transition_date)
        await coordinator.async_save()
        await coordinator.async_request_refresh()
        hass.bus.async_fire(f"{DOMAIN}_plant_harvested", {"plant_id": plant_id})
    except Exception as e:
        create_notification(hass, f"Failed to harvest plant: {e}", title="Growspace Manager")
        raise