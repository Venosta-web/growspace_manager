"""Service registration helper for Growspace Manager."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from functools import partial
from typing import Any, cast

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import (
    ATTR_GROWSPACE_ID,
    ATTR_MOTHER_PLANT_ID,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
    DOMAIN,
    GrowspaceService,
)
from .coordinator import GrowspaceCoordinator
from .exceptions import GrowspaceError
from .services import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_GROWSPACE_SCHEMA,
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
    UPDATE_GROWSPACE_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
    WATER_GROWSPACE_SCHEMA,
    WATER_PLANT_SCHEMA,
    ai_assistant,
    debug,
    environment,
    growspace,
    irrigation,
    irrigation_watering,
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
    entries = hass.config_entries.async_entries(DOMAIN)

    coordinators = [
        entry.runtime_data
        for entry in entries
        if entry.state == ConfigEntryState.LOADED and hasattr(entry, "runtime_data")
    ]

    # Prioritize specific ID keys
    # Map key name to the coordinator attribute to check against
    # Map key name to the coordinator attribute to check against
    id_lookups = [
        (ATTR_GROWSPACE_ID, "growspaces"),
        (ATTR_TARGET_GROWSPACE_ID, "growspaces"),
        (ATTR_PLANT_ID, "plants"),
        (ATTR_MOTHER_PLANT_ID, "plants"),
    ]

    for key, attr in id_lookups:
        if val := data.get(key):
            for coordinator in coordinators:
                if val in getattr(coordinator, attr):
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
        handler: Callable[..., Coroutine[Any, Any, Any]],
        needs_strain_lib: bool,
        call: ServiceCall,
    ) -> Any:
        try:
            coordinator = get_coordinator_for_call(hass, call)
            if needs_strain_lib:
                return await handler(hass, coordinator, strain_lib, call)
            return await handler(hass, coordinator, call)
        except GrowspaceError as err:
            raise ServiceValidationError(str(err)) from err

    # Helper to create the wrapper
    def wrap(
        handler: Callable[..., Coroutine[Any, Any, Any]], needs_strain_lib: bool = True
    ) -> Any:
        return partial(_wrap_dynamic, handler, needs_strain_lib)

    services = [
        (
            GrowspaceService.ADD_GROWSPACE,
            wrap(growspace.handle_add_growspace, True),
            ADD_GROWSPACE_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_GROWSPACE,
            wrap(growspace.handle_remove_growspace, False),
            REMOVE_GROWSPACE_SCHEMA,
        ),
        (
            GrowspaceService.UPDATE_GROWSPACE,
            wrap(growspace.handle_update_growspace, True),
            UPDATE_GROWSPACE_SCHEMA,
        ),
        (
            GrowspaceService.ADD_PLANT,
            wrap(plant.handle_add_plant, True),
            ADD_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_PLANT,
            wrap(plant.handle_remove_plant, True),
            REMOVE_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.UPDATE_PLANT,
            wrap(plant.handle_update_plant, True),
            UPDATE_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.MOVE_PLANT,
            wrap(plant.handle_move_plant, True),
            MOVE_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.SWITCH_PLANTS,
            wrap(plant.handle_switch_plants, True),
            SWITCH_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.TAKE_CLONE,
            wrap(plant.handle_take_clone, True),
            TAKE_CLONE_SCHEMA,
        ),
        (
            GrowspaceService.MOVE_CLONE,
            wrap(plant.handle_move_clone, True),
            MOVE_CLONE_SCHEMA,
        ),
        (
            GrowspaceService.TRANSITION_PLANT_STAGE,
            wrap(plant.handle_transition_plant_stage, True),
            TRANSITION_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.HARVEST_PLANT,
            wrap(plant.handle_harvest_plant, True),
            HARVEST_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.ADD_STRAIN,
            wrap(strain_library.handle_add_strain, True),
            ADD_STRAIN_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_STRAIN,
            wrap(strain_library.handle_remove_strain, True),
            REMOVE_STRAIN_SCHEMA,
        ),
        (
            GrowspaceService.UPDATE_STRAIN_META,
            wrap(strain_library.handle_update_strain_meta, True),
            UPDATE_STRAIN_META_SCHEMA,
        ),
        (
            GrowspaceService.IMPORT_STRAIN_LIBRARY,
            wrap(strain_library.handle_import_strain_library, True),
            IMPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            GrowspaceService.EXPORT_STRAIN_LIBRARY,
            wrap(strain_library.handle_export_strain_library, True),
            EXPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            GrowspaceService.CLEAR_STRAIN_LIBRARY,
            wrap(strain_library.handle_clear_strain_library, True),
            CLEAR_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            GrowspaceService.STRAIN_RECOMMENDATION,
            wrap(ai_assistant.handle_strain_recommendation, True),
            STRAIN_RECOMMENDATION_SCHEMA,
        ),
        (
            GrowspaceService.ASK_GROW_ADVICE,
            wrap(ai_assistant.handle_ask_grow_advice, True),
            ASK_GROW_ADVICE_SCHEMA,
        ),
        (
            GrowspaceService.ANALYZE_ALL_GROWSPACES,
            wrap(ai_assistant.handle_analyze_all_growspaces, True),
            ANALYZE_ALL_GROWSPACES_SCHEMA,
        ),
        (
            GrowspaceService.CONFIGURE_ENVIRONMENT,
            wrap(environment.handle_configure_environment, False),
            CONFIGURE_ENVIRONMENT_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_ENVIRONMENT,
            wrap(environment.handle_remove_environment, False),
            REMOVE_ENVIRONMENT_SCHEMA,
        ),
        (
            GrowspaceService.SET_DEHUMIDIFIER_CONTROL,
            wrap(environment.handle_set_dehumidifier_control, False),
            SET_DEHUMIDIFIER_CONTROL_SCHEMA,
        ),
        (
            GrowspaceService.SET_IRRIGATION_SETTINGS,
            wrap(irrigation.handle_set_irrigation_settings, False),
            SET_IRRIGATION_SETTINGS_SCHEMA,
        ),
        (
            GrowspaceService.ADD_IRRIGATION_TIME,
            wrap(irrigation.handle_add_irrigation_time, False),
            ADD_IRRIGATION_TIME_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_IRRIGATION_TIME,
            wrap(irrigation.handle_remove_irrigation_time, False),
            REMOVE_IRRIGATION_TIME_SCHEMA,
        ),
        (
            GrowspaceService.ADD_DRAIN_TIME,
            wrap(irrigation.handle_add_drain_time, False),
            ADD_DRAIN_TIME_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_DRAIN_TIME,
            wrap(irrigation.handle_remove_drain_time, False),
            REMOVE_DRAIN_TIME_SCHEMA,
        ),
        (
            GrowspaceService.DEBUG_LIST_GROWSPACES,
            wrap(debug.handle_debug_list_growspaces, False),
            DEBUG_LIST_GROWSPACES_SCHEMA,
        ),
        (
            GrowspaceService.DEBUG_RESET_SPECIAL_GROWSPACES,
            wrap(debug.handle_debug_reset_special_growspaces, False),
            DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        ),
        (
            GrowspaceService.DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL,
            wrap(debug.handle_debug_consolidate_duplicate_special, False),
            DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        ),
        (
            GrowspaceService.DEBUG_CLEANUP_LEGACY,
            wrap(debug.handle_debug_cleanup_legacy, False),
            DEBUG_CLEANUP_LEGACY_SCHEMA,
        ),
        (
            GrowspaceService.TEST_NOTIFICATION,
            wrap(debug.handle_test_notification, True),
            None,
        ),
        (
            GrowspaceService.GET_STRAIN_LIBRARY,
            wrap(strain_library.handle_get_strain_library, True),
            None,
        ),
        (
            GrowspaceService.WATER_PLANT,
            wrap(irrigation_watering.handle_water_plant, False),
            WATER_PLANT_SCHEMA,
        ),
        (
            GrowspaceService.WATER_GROWSPACE,
            wrap(irrigation_watering.handle_water_growspace, False),
            WATER_GROWSPACE_SCHEMA,
        ),
    ]

    for service_name, handler, schema in services:
        if service_name in [
            GrowspaceService.GET_STRAIN_LIBRARY,
            GrowspaceService.STRAIN_RECOMMENDATION,
            GrowspaceService.ASK_GROW_ADVICE,
            GrowspaceService.ANALYZE_ALL_GROWSPACES,
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
