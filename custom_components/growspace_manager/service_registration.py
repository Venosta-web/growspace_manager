"""Service registration helper for Growspace Manager."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, cast

from homeassistant.core import HomeAssistant, SupportsResponse

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator
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


async def register_services(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_lib: StrainLibrary,
) -> None:
    """Register services for the Growspace Manager integration."""
    services = [
        (
            "add_growspace",
            partial(
                growspace.handle_add_growspace,
                hass,
                coordinator,
                strain_lib,
            ),
            ADD_GROWSPACE_SCHEMA,
        ),
        (
            "remove_growspace",
            partial(growspace.handle_remove_growspace, hass, coordinator),
            REMOVE_GROWSPACE_SCHEMA,
        ),
        (
            "add_plant",
            partial(plant.handle_add_plant, hass, coordinator, strain_lib),
            ADD_PLANT_SCHEMA,
        ),
        (
            "remove_plant",
            partial(plant.handle_remove_plant, hass, coordinator, strain_lib),
            REMOVE_PLANT_SCHEMA,
        ),
        (
            "update_plant",
            partial(plant.handle_update_plant, hass, coordinator, strain_lib),
            UPDATE_PLANT_SCHEMA,
        ),
        (
            "move_plant",
            partial(plant.handle_move_plant, hass, coordinator, strain_lib),
            MOVE_PLANT_SCHEMA,
        ),
        (
            "switch_plants",
            partial(plant.handle_switch_plants, hass, coordinator, strain_lib),
            SWITCH_PLANT_SCHEMA,
        ),
        (
            "take_clone",
            partial(plant.handle_take_clone, hass, coordinator, strain_lib),
            TAKE_CLONE_SCHEMA,
        ),
        (
            "move_clone",
            partial(plant.handle_move_clone, hass, coordinator, strain_lib),
            MOVE_CLONE_SCHEMA,
        ),
        (
            "transition_plant_stage",
            partial(plant.handle_transition_plant_stage, hass, coordinator, strain_lib),
            TRANSITION_PLANT_SCHEMA,
        ),
        (
            "harvest_plant",
            partial(plant.handle_harvest_plant, hass, coordinator, strain_lib),
            HARVEST_PLANT_SCHEMA,
        ),
        (
            "add_strain",
            partial(strain_library.handle_add_strain, hass, coordinator, strain_lib),
            ADD_STRAIN_SCHEMA,
        ),
        (
            "remove_strain",
            partial(strain_library.handle_remove_strain, hass, coordinator, strain_lib),
            REMOVE_STRAIN_SCHEMA,
        ),
        (
            "update_strain_meta",
            partial(
                strain_library.handle_update_strain_meta, hass, coordinator, strain_lib
            ),
            UPDATE_STRAIN_META_SCHEMA,
        ),
        (
            "import_strain_library",
            partial(
                strain_library.handle_import_strain_library,
                hass,
                coordinator,
                strain_lib,
            ),
            IMPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "export_strain_library",
            partial(
                strain_library.handle_export_strain_library,
                hass,
                coordinator,
                strain_lib,
            ),
            EXPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "clear_strain_library",
            partial(
                strain_library.handle_clear_strain_library,
                hass,
                coordinator,
                strain_lib,
            ),
            CLEAR_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "strain_recommendation",
            partial(
                ai_assistant.handle_strain_recommendation,
                hass,
                coordinator,
                strain_lib,
            ),
            STRAIN_RECOMMENDATION_SCHEMA,
        ),
        (
            "ask_grow_advice",
            partial(ai_assistant.handle_ask_grow_advice, hass, coordinator, strain_lib),
            ASK_GROW_ADVICE_SCHEMA,
        ),
        (
            "analyze_all_growspaces",
            partial(
                ai_assistant.handle_analyze_all_growspaces,
                hass,
                coordinator,
                strain_lib,
            ),
            ANALYZE_ALL_GROWSPACES_SCHEMA,
        ),
        (
            "configure_environment",
            partial(environment.handle_configure_environment, hass, coordinator),
            CONFIGURE_ENVIRONMENT_SCHEMA,
        ),
        (
            "remove_environment",
            partial(environment.handle_remove_environment, hass, coordinator),
            REMOVE_ENVIRONMENT_SCHEMA,
        ),
        (
            "set_dehumidifier_control",
            partial(environment.handle_set_dehumidifier_control, hass, coordinator),
            SET_DEHUMIDIFIER_CONTROL_SCHEMA,
        ),
        (
            "set_irrigation_settings",
            partial(irrigation.handle_set_irrigation_settings, hass, coordinator),
            SET_IRRIGATION_SETTINGS_SCHEMA,
        ),
        (
            "add_irrigation_time",
            partial(irrigation.handle_add_irrigation_time, hass, coordinator),
            ADD_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "remove_irrigation_time",
            partial(irrigation.handle_remove_irrigation_time, hass, coordinator),
            REMOVE_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "add_drain_time",
            partial(irrigation.handle_add_drain_time, hass, coordinator),
            ADD_DRAIN_TIME_SCHEMA,
        ),
        (
            "remove_drain_time",
            partial(irrigation.handle_remove_drain_time, hass, coordinator),
            REMOVE_DRAIN_TIME_SCHEMA,
        ),
        (
            "debug_list_growspaces",
            partial(debug.handle_debug_list_growspaces, hass, coordinator),
            DEBUG_LIST_GROWSPACES_SCHEMA,
        ),
        (
            "debug_reset_special_growspaces",
            partial(debug.handle_debug_reset_special_growspaces, hass, coordinator),
            DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        ),
        (
            "debug_consolidate_duplicate_special",
            partial(
                debug.handle_debug_consolidate_duplicate_special, hass, coordinator
            ),
            DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        ),
        (
            "debug_cleanup_legacy",
            partial(debug.handle_debug_cleanup_legacy, hass, coordinator),
            DEBUG_CLEANUP_LEGACY_SCHEMA,
        ),
        (
            "test_notification",
            partial(debug.handle_test_notification, hass, coordinator, strain_lib),
            None,
        ),
        (
            "get_strain_library",
            partial(
                strain_library.handle_get_strain_library,
                hass,
                coordinator,
                strain_lib,
            ),
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


def remove_services(hass: HomeAssistant) -> None:
    """Remove services for the Growspace Manager integration."""
    services = [
        "add_growspace",
        "remove_growspace",
        "add_plant",
        "remove_plant",
        "update_plant",
        "move_plant",
        "switch_plants",
        "take_clone",
        "move_clone",
        "transition_plant_stage",
        "harvest_plant",
        "add_strain",
        "remove_strain",
        "update_strain_meta",
        "export_strain_library",
        "import_strain_library",
        "clear_strain_library",
        "get_strain_library",
        "ask_grow_advice",
        "analyze_all_growspaces",
        "strain_recommendation",
        "debug_cleanup_legacy",
        "debug_list_growspaces",
        "debug_reset_special_growspaces",
        "debug_consolidate_growspaces",
        "configure_environment",
        "remove_environment",
        "set_dehumidifier_control",
        "set_irrigation_settings",
        "add_irrigation_time",
        "remove_irrigation_time",
        "add_drain_time",
        "remove_drain_time",
    ]
    for service in services:
        hass.services.async_remove(DOMAIN, service)
