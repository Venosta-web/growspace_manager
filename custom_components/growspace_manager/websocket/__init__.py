"""WebSocket API package for the Growspace Manager integration."""

from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import (
    ATTR_AMOUNT_ML,
    ATTR_EC,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_PH,
    ATTR_PLANT_ID,
    ATTR_TAGS,
    ATTR_TRANSITION_DATE,
)
from ..coordinator import GrowspaceCoordinator
from . import (
    data,
    environment,
    genetics,
    irrigation,
    lineage,
    logbook,
    nutrients,
    strain,
    subareas,
    timeline,
    vision,
)
from ._common import _EPOCH_SENTINEL, _extract_ts, _merge_logbook_event

# Re-export all handler functions so existing imports from `.websocket` still resolve
from .data import (
    SCHEMA_WS_GET_DATA,
    SCHEMA_WS_GET_GROW_REPORT,
    WS_TYPE_GET_DATA,
    WS_TYPE_GET_GROW_REPORT,
    websocket_get_growspace_data,
)
from .environment import (
    SCHEMA_WS_GET_HISTORY_STATS,
    SCHEMA_WS_UPDATE_SENSOR_COORDINATES,
    WS_TYPE_GET_HISTORY_STATS,
    WS_TYPE_UPDATE_SENSOR_COORDINATES,
    _downsample_entity_binary_search,
    _get_history_with_binary_search_downsample,
    _get_statistics_data,
    websocket_get_history_stats,
    websocket_update_sensor_coordinates,
)
from .genetics import (
    SCHEMA_WS_DELETE_BREEDER,
    SCHEMA_WS_GET_GENETICS_DATA,
    SCHEMA_WS_UPDATE_BREEDER,
    WS_TYPE_DELETE_BREEDER,
    WS_TYPE_GET_GENETICS_DATA,
    WS_TYPE_UPDATE_BREEDER,
    websocket_delete_breeder,
    websocket_get_genetics_data,
    websocket_update_breeder,
)
from .lineage import (
    SCHEMA_WS_GET_LINEAGE_TREE,
    SCHEMA_WS_GET_STRAIN_LINEAGE_TREE,
    SCHEMA_WS_IMPORT_STRAIN_LINEAGE_TREE,
    SCHEMA_WS_UPDATE_STRAIN_LINEAGE_TREE,
    WS_TYPE_GET_LINEAGE_TREE,
    WS_TYPE_GET_STRAIN_LINEAGE_TREE,
    WS_TYPE_IMPORT_STRAIN_LINEAGE_TREE,
    WS_TYPE_UPDATE_STRAIN_LINEAGE_TREE,
    websocket_get_lineage_tree,
    websocket_get_strain_lineage_tree,
    websocket_import_strain_lineage_tree,
    websocket_update_strain_lineage_tree,
)
from .logbook import (
    SCHEMA_WS_GET_ALERTS,
    SCHEMA_WS_GET_LOG,
    WS_TYPE_GET_ALERTS,
    WS_TYPE_GET_LOG,
    _query_logbook_events_impl,
    websocket_get_alerts,
    websocket_get_event_log,
)
from .nutrients import (
    SCHEMA_WS_GET_EC_RAMP_CURVES,
    SCHEMA_WS_GET_IPM_PRESETS,
    SCHEMA_WS_GET_NUTRIENT_INVENTORY,
    SCHEMA_WS_GET_NUTRIENT_PRESETS,
    SCHEMA_WS_REMOVE_NUTRIENT_STOCK,
    SCHEMA_WS_UPDATE_NUTRIENT_STOCK,
    WS_TYPE_GET_EC_RAMP_CURVES,
    WS_TYPE_GET_IPM_PRESETS,
    WS_TYPE_GET_NUTRIENT_INVENTORY,
    WS_TYPE_GET_NUTRIENT_PRESETS,
    WS_TYPE_REMOVE_NUTRIENT_STOCK,
    WS_TYPE_UPDATE_NUTRIENT_STOCK,
    websocket_get_ec_ramp_curves,
    websocket_get_ipm_presets,
    websocket_get_nutrient_inventory,
    websocket_get_nutrient_presets,
    websocket_remove_nutrient_stock,
    websocket_update_nutrient_stock,
)
from .strain import (
    SCHEMA_WS_DOWNLOAD_STRAIN_IMAGE,
    SCHEMA_WS_GET_EXTERNAL_STRAIN_DETAILS,
    SCHEMA_WS_GET_STRAIN_LIBRARY,
    SCHEMA_WS_QUERY_EXTERNAL_STRAIN,
    SCHEMA_WS_UPLOAD_STRAIN_IMAGE,
    WS_TYPE_DOWNLOAD_STRAIN_IMAGE,
    WS_TYPE_GET_EXTERNAL_STRAIN_DETAILS,
    WS_TYPE_GET_STRAIN_LIBRARY,
    WS_TYPE_QUERY_EXTERNAL_STRAIN,
    WS_TYPE_UPLOAD_STRAIN_IMAGE,
    websocket_download_strain_image,
    websocket_get_external_strain_details,
    websocket_get_strain_library,
    websocket_query_external_strain,
    websocket_upload_strain_image,
)
from .irrigation import (
    SCHEMA_WS_GET_IRRIGATION_ANALYTICS,
    WS_TYPE_GET_IRRIGATION_ANALYTICS,
    websocket_get_irrigation_analytics,
)
from .subareas import (
    SCHEMA_WS_ADD_SUBAREA,
    SCHEMA_WS_GET_SUBAREAS,
    SCHEMA_WS_REMOVE_SUBAREA,
    SCHEMA_WS_UPDATE_SUBAREA,
    WS_TYPE_ADD_SUBAREA,
    WS_TYPE_GET_SUBAREAS,
    WS_TYPE_REMOVE_SUBAREA,
    WS_TYPE_UPDATE_SUBAREA,
    websocket_add_subarea,
    websocket_get_subareas,
    websocket_remove_subarea,
    websocket_update_subarea,
)
from .timeline import (
    SCHEMA_WS_ADD_GROWSPACE_NOTE,
    SCHEMA_WS_ADD_TIMELINE_NOTE,
    SCHEMA_WS_REMOVE_TIMELINE_EVENT,
    WS_TYPE_ADD_GROWSPACE_NOTE,
    WS_TYPE_ADD_TIMELINE_NOTE,
    WS_TYPE_REMOVE_TIMELINE_EVENT,
    websocket_add_growspace_note,
    websocket_add_timeline_note,
    websocket_remove_timeline_event,
)
from .vision import (
    SCHEMA_WS_CAPTURE_SNAPSHOT,
    SCHEMA_WS_GET_SNAPSHOTS,
    SCHEMA_WS_GET_VISION_HISTORY,
    SCHEMA_WS_UPDATE_VISION_CHECKUP_CONFIG,
    WS_TYPE_CAPTURE_SNAPSHOT,
    WS_TYPE_GET_SNAPSHOTS,
    WS_TYPE_GET_VISION_HISTORY,
    WS_TYPE_UPDATE_VISION_CHECKUP_CONFIG,
    websocket_capture_snapshot,
    websocket_get_snapshots,
    websocket_get_vision_history,
    websocket_update_vision_checkup_config,
)

_LOGGER = logging.getLogger(__name__)

_MODULES = [
    data,
    logbook,
    nutrients,
    strain,
    lineage,
    timeline,
    genetics,
    environment,
    subareas,
    vision,
    irrigation,
]


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register all WebSocket API commands."""
    _LOGGER.debug("Registering WebSocket API for growspace_manager")

    for module in _MODULES:
        for ws_type, handler, schema, is_sync in module.COMMANDS:
            registered = handler if is_sync else websocket_api.async_response(handler)
            websocket_api.async_register_command(hass, ws_type, registered, schema)


__all__ = [
    "async_register_websocket_api",
    # Common helpers
    "_EPOCH_SENTINEL",
    "_extract_ts",
    "_merge_logbook_event",
    # Coordinator (needed for patch target resolution in tests)
    "GrowspaceCoordinator",
    # Data
    "websocket_get_growspace_data",
    "WS_TYPE_GET_DATA",
    "SCHEMA_WS_GET_DATA",
    "WS_TYPE_GET_GROW_REPORT",
    "SCHEMA_WS_GET_GROW_REPORT",
    # Logbook
    "websocket_get_event_log",
    "websocket_get_alerts",
    "WS_TYPE_GET_LOG",
    "SCHEMA_WS_GET_LOG",
    "WS_TYPE_GET_ALERTS",
    "SCHEMA_WS_GET_ALERTS",
    # Nutrients
    "websocket_get_nutrient_presets",
    "websocket_get_ipm_presets",
    "websocket_get_ec_ramp_curves",
    "websocket_get_nutrient_inventory",
    "websocket_update_nutrient_stock",
    "websocket_remove_nutrient_stock",
    "WS_TYPE_GET_NUTRIENT_PRESETS",
    "WS_TYPE_GET_IPM_PRESETS",
    "WS_TYPE_GET_EC_RAMP_CURVES",
    "WS_TYPE_GET_NUTRIENT_INVENTORY",
    "WS_TYPE_UPDATE_NUTRIENT_STOCK",
    "WS_TYPE_REMOVE_NUTRIENT_STOCK",
    # Strain
    "websocket_get_strain_library",
    "websocket_upload_strain_image",
    "websocket_download_strain_image",
    "websocket_query_external_strain",
    "websocket_get_external_strain_details",
    # Lineage
    "websocket_get_lineage_tree",
    "websocket_get_strain_lineage_tree",
    "websocket_update_strain_lineage_tree",
    "websocket_import_strain_lineage_tree",
    # Timeline
    "websocket_add_timeline_note",
    "websocket_add_growspace_note",
    "websocket_remove_timeline_event",
    # Genetics
    "websocket_get_genetics_data",
    "websocket_update_breeder",
    "websocket_delete_breeder",
    # Environment
    "websocket_get_history_stats",
    "websocket_update_sensor_coordinates",
    "_get_statistics_data",
    "_get_history_with_binary_search_downsample",
    "_downsample_entity_binary_search",
    # Subareas
    "websocket_get_subareas",
    "websocket_add_subarea",
    "websocket_update_subarea",
    "websocket_remove_subarea",
    # Vision
    "websocket_capture_snapshot",
    "websocket_get_snapshots",
    "websocket_get_vision_history",
    "websocket_update_vision_checkup_config",
    # Irrigation analytics
    "websocket_get_irrigation_analytics",
    "WS_TYPE_GET_IRRIGATION_ANALYTICS",
    "SCHEMA_WS_GET_IRRIGATION_ANALYTICS",
]
