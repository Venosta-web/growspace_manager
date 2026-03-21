"""Service registration helper for Growspace Manager."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN, GrowspaceService
from .coordinator import GrowspaceCoordinator
from .exceptions import GrowspaceError
from .schemas import (
    APPLY_IPM_SCHEMA,
    CONFIGURE_DRAIN_MONITORING_SCHEMA,
    LOG_DRAIN_READING_SCHEMA,
    LOG_TRAINING_EVENT_SCHEMA,
    REMOVE_EC_RAMP_CURVE_SCHEMA,
    REMOVE_IPM_PRESET_SCHEMA,
    RESET_WATER_TRACKING_SCHEMA,
    SAVE_EC_RAMP_CURVE_SCHEMA,
    SAVE_IPM_PRESET_SCHEMA,
    SCORE_PLANT_SCHEMA,
    SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
    UPDATE_HARVEST_METRICS_SCHEMA,
)
from .services import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_GROWSPACE_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    ADD_PLANT_SCHEMA,
    ADD_PLANTS_SCHEMA,
    ADD_STRAIN_SCHEMA,
    ADD_TIMELINE_NOTE_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    BATCH_ACTION_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    EXPORT_GROW_REPORT_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    PRINT_LABEL_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    REMOVE_NUTRIENT_PRESET_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    SAVE_NUTRIENT_PRESET_SCHEMA,
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
    batch,
    debug,
    drain_ec,
    ec_ramp,
    environment,
    growspace,
    ipm,
    irrigation,
    irrigation_watering,
    nutrient_presets,
    plant,
    report,
    strain_library,
    training,
    vision_checkup,
    water_analytics,
)
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


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
            coordinator = GrowspaceCoordinator.get_for_service_call(hass, call)
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
            GrowspaceService.ADD_PLANTS,
            wrap(plant.handle_add_plants, True),
            ADD_PLANTS_SCHEMA,
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
            GrowspaceService.UPDATE_HARVEST_METRICS,
            wrap(plant.handle_update_harvest_metrics, True),
            UPDATE_HARVEST_METRICS_SCHEMA,
        ),
        (
            GrowspaceService.SCORE_PLANT,
            wrap(plant.handle_score_plant, True),
            SCORE_PLANT_SCHEMA,
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
            GrowspaceService.EXPORT_GROW_REPORT,
            wrap(report.handle_export_grow_report, False),
            EXPORT_GROW_REPORT_SCHEMA,
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
        (
            GrowspaceService.SAVE_NUTRIENT_PRESET,
            wrap(nutrient_presets.handle_save_nutrient_preset, False),
            SAVE_NUTRIENT_PRESET_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_NUTRIENT_PRESET,
            wrap(nutrient_presets.handle_remove_nutrient_preset, False),
            REMOVE_NUTRIENT_PRESET_SCHEMA,
        ),
        (
            GrowspaceService.LOG_TRAINING_EVENT,
            wrap(training.handle_log_training_event, False),
            LOG_TRAINING_EVENT_SCHEMA,
        ),
        (
            GrowspaceService.SAVE_IPM_PRESET,
            wrap(ipm.handle_save_ipm_preset, False),
            SAVE_IPM_PRESET_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_IPM_PRESET,
            wrap(ipm.handle_remove_ipm_preset, False),
            REMOVE_IPM_PRESET_SCHEMA,
        ),
        (
            GrowspaceService.APPLY_IPM,
            wrap(ipm.handle_apply_ipm, False),
            APPLY_IPM_SCHEMA,
        ),
        (
            GrowspaceService.BATCH_ACTION,
            wrap(batch.handle_batch_action, False),
            BATCH_ACTION_SCHEMA,
        ),
        (
            GrowspaceService.ADD_TIMELINE_NOTE,
            wrap(plant.handle_add_timeline_note, True),
            ADD_TIMELINE_NOTE_SCHEMA,
        ),
        (
            GrowspaceService.PRINT_LABEL,
            wrap(strain_library.handle_print_label, True),
            PRINT_LABEL_SCHEMA,
        ),
        (
            GrowspaceService.LOG_DRAIN_READING,
            wrap(drain_ec.handle_log_drain_reading, False),
            LOG_DRAIN_READING_SCHEMA,
        ),
        (
            GrowspaceService.CONFIGURE_DRAIN_MONITORING,
            wrap(drain_ec.handle_configure_drain_monitoring, False),
            CONFIGURE_DRAIN_MONITORING_SCHEMA,
        ),
        (
            GrowspaceService.RESET_WATER_TRACKING,
            wrap(water_analytics.handle_reset_water_tracking, False),
            RESET_WATER_TRACKING_SCHEMA,
        ),
        (
            GrowspaceService.SAVE_EC_RAMP_CURVE,
            wrap(ec_ramp.handle_save_ec_ramp_curve, False),
            SAVE_EC_RAMP_CURVE_SCHEMA,
        ),
        (
            GrowspaceService.REMOVE_EC_RAMP_CURVE,
            wrap(ec_ramp.handle_remove_ec_ramp_curve, False),
            REMOVE_EC_RAMP_CURVE_SCHEMA,
        ),
        (
            GrowspaceService.TRIGGER_VISION_CHECKUP,
            wrap(vision_checkup.handle_trigger_vision_checkup, False),
            SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
        ),
    ]

    for service_name, handler, schema in services:
        if service_name in [
            GrowspaceService.GET_STRAIN_LIBRARY,
            GrowspaceService.STRAIN_RECOMMENDATION,
            GrowspaceService.ASK_GROW_ADVICE,
            GrowspaceService.ANALYZE_ALL_GROWSPACES,
            GrowspaceService.TRIGGER_VISION_CHECKUP,
        ]:
            hass.services.async_register(
                DOMAIN,
                service_name,
                cast(Any, handler),
                schema=schema,
                supports_response=SupportsResponse.ONLY,
            )
        elif service_name == GrowspaceService.PRINT_LABEL:
            hass.services.async_register(
                DOMAIN,
                service_name,
                cast(Any, handler),
                schema=schema,
                supports_response=SupportsResponse.OPTIONAL,
            )
        else:
            hass.services.async_register(
                DOMAIN, service_name, cast(Any, handler), schema=schema
            )
