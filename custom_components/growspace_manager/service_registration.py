"""Service registration helper for Growspace Manager."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, cast

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator
from .services import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_GROWSPACE_SCHEMA,
    UPDATE_GROWSPACE_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    ADD_PLANT_SCHEMA,
    ADD_STRAIN_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
    ai_assistant,
    debug,
    environment,
    growspace,
    irrigation,
    plant,
    strain_library,
)
from .services.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


def get_coordinator_for_call(
    hass: HomeAssistant, call: ServiceCall | dict
) -> GrowspaceCoordinator:
    """Retrieve the correct coordinator based on service call data."""
    data = call.data if isinstance(call, ServiceCall) else call

    # Get all potential coordinators from loaded entries
    coordinators = [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state == ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
    ]

    # 1. Try growspace_id
    if growspace_id := (data.get("growspace_id") or data.get("target_growspace_id")):
        for coordinator in coordinators:
            if growspace_id in coordinator.growspaces:
                return coordinator

    # 2. Try plant_id
    if plant_id := (data.get("plant_id") or data.get("mother_plant_id")):
        for coordinator in coordinators:
            if plant_id in coordinator.plants:
                return coordinator

    # 3. Fallback: If only one config entry exists, use it.
    if len(coordinators) == 1:
        return coordinators[0]

    raise ServiceValidationError(
        "Could not determine which Growspace Manager instance to use. "
        "Please specify a valid growspace_id or plant_id."
    )


async def register_services(
    hass: HomeAssistant,
    strain_lib: StrainLibrary,
) -> None:
    """Register services for the Growspace Manager integration."""

    async def _wrap_dynamic(
        handler: Any,
        needs_strain_lib: bool,
        call: ServiceCall,
    ) -> Any:
        coordinator = get_coordinator_for_call(hass, call)
        if needs_strain_lib:
            return await handler(hass, coordinator, strain_lib, call)
        return await handler(hass, coordinator, call)

    # Helper to create the wrapper
    def wrap(handler: Any, needs_strain_lib: bool = True) -> Any:
        return partial(_wrap_dynamic, handler, needs_strain_lib)

    services = [
        (
            "add_growspace",
            wrap(growspace.handle_add_growspace, True),
            ADD_GROWSPACE_SCHEMA,
        ),
        (
            "remove_growspace",
            wrap(growspace.handle_remove_growspace, False),
            REMOVE_GROWSPACE_SCHEMA,
        ),
        (
            "update_growspace",
            wrap(growspace.handle_update_growspace, True),
            UPDATE_GROWSPACE_SCHEMA,
        ),
        (
            "add_plant",
            wrap(plant.handle_add_plant, True),
            ADD_PLANT_SCHEMA,
        ),
        (
            "remove_plant",
            wrap(plant.handle_remove_plant, True),
            REMOVE_PLANT_SCHEMA,
        ),
        (
            "update_plant",
            wrap(plant.handle_update_plant, True),
            UPDATE_PLANT_SCHEMA,
        ),
        (
            "move_plant",
            wrap(plant.handle_move_plant, True),
            MOVE_PLANT_SCHEMA,
        ),
        (
            "switch_plants",
            wrap(plant.handle_switch_plants, True),
            SWITCH_PLANT_SCHEMA,
        ),
        (
            "take_clone",
            wrap(plant.handle_take_clone, True),
            TAKE_CLONE_SCHEMA,
        ),
        (
            "move_clone",
            wrap(plant.handle_move_clone, True),
            MOVE_CLONE_SCHEMA,
        ),
        (
            "transition_plant_stage",
            wrap(plant.handle_transition_plant_stage, True),
            TRANSITION_PLANT_SCHEMA,
        ),
        (
            "harvest_plant",
            wrap(plant.handle_harvest_plant, True),
            HARVEST_PLANT_SCHEMA,
        ),
        (
            "add_strain",
            wrap(strain_library.handle_add_strain, True),
            ADD_STRAIN_SCHEMA,
        ),
        (
            "remove_strain",
            wrap(strain_library.handle_remove_strain, True),
            REMOVE_STRAIN_SCHEMA,
        ),
        (
            "update_strain_meta",
            wrap(strain_library.handle_update_strain_meta, True),
            UPDATE_STRAIN_META_SCHEMA,
        ),
        (
            "import_strain_library",
            wrap(strain_library.handle_import_strain_library, True),
            IMPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "export_strain_library",
            wrap(strain_library.handle_export_strain_library, True),
            EXPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "clear_strain_library",
            wrap(strain_library.handle_clear_strain_library, True),
            CLEAR_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "strain_recommendation",
            wrap(ai_assistant.handle_strain_recommendation, True),
            STRAIN_RECOMMENDATION_SCHEMA,
        ),
        (
            "ask_grow_advice",
            wrap(ai_assistant.handle_ask_grow_advice, True),
            ASK_GROW_ADVICE_SCHEMA,
        ),
        (
            "analyze_all_growspaces",
            wrap(ai_assistant.handle_analyze_all_growspaces, True),
            ANALYZE_ALL_GROWSPACES_SCHEMA,
        ),
        (
            "configure_environment",
            wrap(environment.handle_configure_environment, False),
            CONFIGURE_ENVIRONMENT_SCHEMA,
        ),
        (
            "remove_environment",
            wrap(environment.handle_remove_environment, False),
            REMOVE_ENVIRONMENT_SCHEMA,
        ),
        (
            "set_dehumidifier_control",
            wrap(environment.handle_set_dehumidifier_control, False),
            SET_DEHUMIDIFIER_CONTROL_SCHEMA,
        ),
        (
            "set_irrigation_settings",
            wrap(irrigation.handle_set_irrigation_settings, False),
            SET_IRRIGATION_SETTINGS_SCHEMA,
        ),
        (
            "add_irrigation_time",
            wrap(irrigation.handle_add_irrigation_time, False),
            ADD_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "remove_irrigation_time",
            wrap(irrigation.handle_remove_irrigation_time, False),
            REMOVE_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "add_drain_time",
            wrap(irrigation.handle_add_drain_time, False),
            ADD_DRAIN_TIME_SCHEMA,
        ),
        (
            "remove_drain_time",
            wrap(irrigation.handle_remove_drain_time, False),
            REMOVE_DRAIN_TIME_SCHEMA,
        ),
        (
            "debug_list_growspaces",
            wrap(debug.handle_debug_list_growspaces, False),
            DEBUG_LIST_GROWSPACES_SCHEMA,
        ),
        (
            "debug_reset_special_growspaces",
            wrap(debug.handle_debug_reset_special_growspaces, False),
            DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        ),
        (
            "debug_consolidate_duplicate_special",
            wrap(debug.handle_debug_consolidate_duplicate_special, False),
            DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        ),
        (
            "debug_cleanup_legacy",
            wrap(debug.handle_debug_cleanup_legacy, False),
            DEBUG_CLEANUP_LEGACY_SCHEMA,
        ),
        (
            "test_notification",
            wrap(debug.handle_test_notification, True),
            None,
        ),
        (
            "get_strain_library",
            wrap(strain_library.handle_get_strain_library, True),
            None,
        ),
    ]

    for service_name, handler, schema in services:
        if service_name in [
            "get_strain_library",
            "strain_recommendation",
            "ask_grow_advice",
            "analyze_all_growspaces",
        ]:
            hass.services.async_register(
                DOMAIN,
                service_name,
                cast(Any, handler),
                schema=schema,
                supports_response=SupportsResponse.ONLY,
            )
        else:
            hass.services.async_register(
                DOMAIN, service_name, cast(Any, handler), schema=schema
            )
