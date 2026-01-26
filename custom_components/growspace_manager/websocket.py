"""WebSocket API for the Growspace Manager integration."""

from __future__ import annotations

import bisect
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.recorder import (
    get_instance,
    history,
    statistics as recorder_stats,
)
from homeassistant.components.recorder.db_schema import EventData, Events, EventTypes
from homeassistant.components.recorder.util import session_scope
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
import homeassistant.util.dt as dt_util

from .const import (
    ALERT_LOG_LOOKBACK_DAYS,
    ATTR_AMOUNT_ML,
    ATTR_EC,
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_PH,
    ATTR_PLANT_ID,
    ATTR_TAGS,
    ATTR_TRANSITION_DATE,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    EVENT_LOG_LOOKBACK_DAYS,
    MERGE_ALERT_GAP_SECONDS,
)
from .coordinator import GrowspaceCoordinator
from .services.plant import async_add_timeline_note
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

# Sentinel for invalid timestamps
_EPOCH_SENTINEL: datetime = datetime.min.replace(tzinfo=dt_util.UTC)


def _extract_ts(state_obj: Any) -> datetime:
    """Extract timestamp from state object or dict."""
    if isinstance(state_obj, dict):
        ts_raw = state_obj.get("last_updated", state_obj.get("last_changed"))
    else:
        ts_raw = state_obj.last_updated

    if ts_raw is None:
        return _EPOCH_SENTINEL
    if isinstance(ts_raw, str):
        parsed = dt_util.parse_datetime(ts_raw)
        return parsed if parsed else _EPOCH_SENTINEL  # type: ignore[no-any-return]
    if isinstance(ts_raw, datetime):
        return ts_raw
    return _EPOCH_SENTINEL


WS_TYPE_GET_LOG = f"{DOMAIN}/get_log"
SCHEMA_WS_GET_LOG = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_LOG,
        vol.Optional("growspace_id"): str,
        vol.Optional("limit"): vol.Any(int, None),
    }
)

WS_TYPE_GET_ALERTS = f"{DOMAIN}/get_alerts"
SCHEMA_WS_GET_ALERTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_ALERTS,
        vol.Optional("growspace_id"): str,
        vol.Optional("limit"): vol.Any(int, None),
    }
)

WS_TYPE_GET_DATA = f"{DOMAIN}/get_data"
SCHEMA_WS_GET_DATA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_DATA,
        vol.Optional("growspace_id"): str,
    }
)


async def websocket_get_growspace_data(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get growspace data command."""
    growspace_id = msg.get("growspace_id")
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        data = coordinator.get_growspace_data(growspace_id)
        connection.send_result(msg["id"], data)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


def _merge_logbook_event(
    formatted_events_list: list[dict[str, Any]],
    data_dict: dict[str, Any],
    evt_row: EventData,
) -> bool:
    """Try to merge an event into the last one if they are similar alerts."""
    if not formatted_events_list:
        return False

    last_evt = formatted_events_list[-1]
    # Check shared properties for merging (same type, growspace, severity)
    if (
        data_dict.get("category") == "alert"
        and last_evt.get("category") == "alert"
        and data_dict.get("growspace_id") == last_evt.get("growspace_id")
        and data_dict.get("sensor_type") == last_evt.get("sensor_type")
        and "severity" in data_dict
        and "severity" in last_evt
        and round(float(data_dict["severity"]), 2)
        == round(float(last_evt["severity"]), 2)
    ):
        # Check time gap (DESC order means last is NEWER than data)
        try:
            l_start_iso = last_evt.get("start_time")
            d_end_iso = data_dict.get("end_time")

            if l_start_iso and d_end_iso:
                l_dt = datetime.fromisoformat(l_start_iso)
                d_dt = datetime.fromisoformat(d_end_iso)
                gap_sec = (l_dt - d_dt).total_seconds()

                # Merge if gap is small (e.g., < 10 minutes)
                if 0 <= gap_sec <= MERGE_ALERT_GAP_SECONDS:
                    last_evt["start_time"] = data_dict["start_time"]
                    last_evt["duration_sec"] = last_evt.get(
                        "duration_sec", 0
                    ) + data_dict.get("duration_sec", 0)

                    if "reasons" in data_dict and "reasons" in last_evt:
                        comb = list(
                            dict.fromkeys(last_evt["reasons"] + data_dict["reasons"])
                        )
                        last_evt["reasons"] = comb[:5]
                    return True  # type: ignore[no-any-return]
        except (ValueError, TypeError, KeyError):
            pass
    return False


def _query_logbook_events_impl(
    hass: HomeAssistant,
    start_time: datetime,
    end_time: datetime,
    limit: int,
    growspace_id: str | None,
    exclude_categories: set[str] | None = None,
    include_categories: set[str] | None = None,
    limit_multiplier: int = 2,
) -> list[dict[str, Any]]:
    """Execute the logbook query with filtering logic."""
    formatted: list[dict[str, Any]] = []
    count = 0

    with session_scope(hass=hass, read_only=True) as session:
        t_row = (
            session.query(EventTypes.event_type_id)
            .filter(EventTypes.event_type == EVENT_GROWSPACE_LOG_ENTRY)
            .first()
        )
        if not t_row:
            return []

        q = (
            session.query(Events, EventData)
            .join(EventData, Events.data_id == EventData.data_id, isouter=False)
            .filter(
                Events.event_type_id == t_row[0],
                Events.time_fired_ts >= start_time.timestamp(),
                Events.time_fired_ts <= end_time.timestamp(),
            )
        )

        # SQL level exclusion
        if exclude_categories:
            for cat in exclude_categories:
                # Match both compact and spaced JSON formatting
                q = q.filter(
                    ~EventData.shared_data.like(f'%"category":"{cat}"%'),
                    ~EventData.shared_data.like(f'%"category": "{cat}"%'),
                )

        q = q.order_by(Events.time_fired_ts.desc())

        if limit:
            q = q.limit(limit * limit_multiplier)

        for e_row, d_row in q:
            if not d_row or not d_row.shared_data:
                continue
            try:
                d = json.loads(d_row.shared_data)
                if growspace_id and d.get("growspace_id") != growspace_id:
                    continue

                if include_categories and d.get("category") not in include_categories:
                    continue

                if count >= limit:
                    break
                count += 1

                if "timestamp" not in d and e_row.time_fired_ts:
                    d["timestamp"] = e_row.time_fired_ts * 1000

                if not _merge_logbook_event(formatted, d, e_row):
                    d["event_id"] = e_row.event_id
                    formatted.append(d)

            except (json.JSONDecodeError, AttributeError):
                continue
    return formatted


async def websocket_get_event_log(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get event log command via Recorder.

    Excludes high-frequency environmental alerts (optimal, stress, mold).
    """
    growspace_id = msg.get("growspace_id")
    limit = msg.get("limit", 50)
    # Categories to EXCLUDE from the main log
    spam_cats = {"optimal", "stress", "mold", "alert", "environment"}

    try:
        recorder = get_instance(hass)
        end_time = dt_util.utcnow()
        # Look back for manual logs since they are sparse
        start_time = end_time - timedelta(days=EVENT_LOG_LOOKBACK_DAYS)

        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            limit,
            growspace_id,
            spam_cats,
            None,
            2,
        )
        res = {}
        if growspace_id:
            res[growspace_id] = evts
        else:
            for v in evts:
                gid = v.get("growspace_id", "global")
                res.setdefault(gid, []).append(v)

        connection.send_result(msg["id"], res)

    except (ImportError, KeyError) as err:
        _LOGGER.warning("Recorder not available: %s", err)
        connection.send_result(msg["id"], {growspace_id: []} if growspace_id else {})
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_event_log")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_get_alerts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get alerts command via Recorder.

    ONLY includes high-frequency environmental alerts (optimal, stress, mold).
    """
    growspace_id = msg.get("growspace_id")
    limit = msg.get("limit", 200)
    # Categories to INCLUDE in the alerts log
    alert_cats = {"optimal", "stress", "mold", "alert", "environment"}

    try:
        recorder = get_instance(hass)
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(days=ALERT_LOG_LOOKBACK_DAYS)

        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            limit,
            growspace_id,
            None,
            alert_cats,
            5,
        )
        res = {}
        if growspace_id:
            res[growspace_id] = evts
        else:
            for v in evts:
                gid = v.get("growspace_id", "global")
                res.setdefault(gid, []).append(v)

        connection.send_result(msg["id"], res)

    except (ImportError, KeyError) as err:
        _LOGGER.warning("Recorder not available: %s", err)
        connection.send_result(msg["id"], {growspace_id: []} if growspace_id else {})
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_alerts")
        connection.send_error(msg["id"], "unknown_error", str(err))


# WebSocket API Constants
WS_TYPE_GET_STRAIN_LIBRARY = f"{DOMAIN}/get_strain_library"
SCHEMA_WS_GET_STRAIN_LIBRARY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_STRAIN_LIBRARY,
    }
)

WS_TYPE_GET_NUTRIENT_PRESETS = f"{DOMAIN}/get_nutrient_presets"
SCHEMA_WS_GET_NUTRIENT_PRESETS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_NUTRIENT_PRESETS,
    }
)

WS_TYPE_GET_IPM_PRESETS = f"{DOMAIN}/get_ipm_presets"
SCHEMA_WS_GET_IPM_PRESETS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_IPM_PRESETS,
    }
)

WS_TYPE_ADD_TIMELINE_NOTE = f"{DOMAIN}/add_timeline_note"
SCHEMA_WS_ADD_TIMELINE_NOTE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_ADD_TIMELINE_NOTE,
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required(ATTR_NOTES): str,
        vol.Optional(ATTR_TRANSITION_DATE): vol.Any(str, None),
        vol.Optional(ATTR_IMAGES): [str],
        vol.Optional(ATTR_TAGS): [str],
        vol.Optional(ATTR_PH): vol.Any(float, int),
        vol.Optional(ATTR_EC): vol.Any(float, int),
        vol.Optional(ATTR_AMOUNT_ML): vol.Any(float, int),
        vol.Optional(ATTR_METADATA): dict,
    }
)

WS_TYPE_REMOVE_TIMELINE_EVENT = f"{DOMAIN}/remove_timeline_event"
SCHEMA_WS_REMOVE_TIMELINE_EVENT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_TIMELINE_EVENT,
        vol.Required("event_id"): int,
    }
)


@callback
def websocket_get_strain_library(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get strain library command via WebSocket."""
    try:
        # Retrieve the global strain library instance
        if DOMAIN not in hass.data or "strain_library" not in hass.data[DOMAIN]:
            connection.send_error(
                msg["id"], "not_loaded", "Growspace Manager strain library not loaded"
            )
            return

        strain_library: StrainLibrary = hass.data[DOMAIN]["strain_library"]
        # Return full strain data (including image_path) for frontend display
        all_strains = strain_library.get_all()
        response = {
            "strains": all_strains,
            "strain_list": list(all_strains.keys()),
        }
        connection.send_result(msg["id"], response)
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_strain_library")
        connection.send_error(msg["id"], "unknown_error", str(err))


# Nutrient Inventory WebSockets
WS_TYPE_GET_NUTRIENT_INVENTORY = f"{DOMAIN}/get_nutrient_inventory"
SCHEMA_WS_GET_NUTRIENT_INVENTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_NUTRIENT_INVENTORY,
    }
)

WS_TYPE_UPDATE_NUTRIENT_STOCK = f"{DOMAIN}/update_nutrient_stock"
SCHEMA_WS_UPDATE_NUTRIENT_STOCK = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_NUTRIENT_STOCK,
        vol.Required("nutrient_id"): str,
        vol.Required("name"): str,
        vol.Required("current_ml"): vol.Any(float, int),
        vol.Required("initial_ml"): vol.Any(float, int),
    }
)

WS_TYPE_REMOVE_NUTRIENT_STOCK = f"{DOMAIN}/remove_nutrient_stock"
SCHEMA_WS_REMOVE_NUTRIENT_STOCK = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REMOVE_NUTRIENT_STOCK,
        vol.Required("nutrient_id"): str,
    }
)


@callback
def websocket_get_nutrient_inventory(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get nutrient inventory command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        if coordinator.nutrient_inventory_service:
            inventory = coordinator.nutrient_inventory_service.get_inventory()
            connection.send_result(msg["id"], asdict(inventory))
        else:
            connection.send_result(msg["id"], {"stocks": {}})
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_nutrient_inventory")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_update_nutrient_stock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle update nutrient stock command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        if coordinator.nutrient_inventory_service:
            coordinator.nutrient_inventory_service.update_stock(
                nutrient_id=msg["nutrient_id"],
                name=msg["name"],
                current_ml=float(msg["current_ml"]),
                initial_ml=float(msg["initial_ml"]),
            )
            # Persist changes
            hass.async_create_task(coordinator.async_save())
            connection.send_result(msg["id"])
        else:
            connection.send_error(msg["id"], "not_initialized", "Service not ready")
    except Exception as err:
        _LOGGER.exception("Error handling websocket_update_nutrient_stock")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_remove_nutrient_stock(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle remove nutrient stock command."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )
        if coordinator.nutrient_inventory_service:
            coordinator.nutrient_inventory_service.remove_stock(msg["nutrient_id"])
            # Persist changes
            hass.async_create_task(coordinator.async_save())
            connection.send_result(msg["id"])
        else:
            connection.send_error(msg["id"], "not_initialized", "Service not ready")
    except Exception as err:
        _LOGGER.exception("Error handling websocket_remove_nutrient_stock")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_get_nutrient_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get nutrient presets command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )

        # Use the manager's serialization logic to ensure consistency
        data = coordinator.nutrient_manager.get_serialization_data()
        connection.send_result(msg["id"], data["nutrient_presets"])
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_nutrient_presets")
        connection.send_error(msg["id"], "unknown_error", str(err))


@callback
def websocket_get_ipm_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get IPM presets command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )

        # Use the manager's serialization logic to ensure consistency
        data = coordinator.nutrient_manager.get_serialization_data()
        connection.send_result(msg["id"], data["ipm_presets"])
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_ipm_presets")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_add_timeline_note(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle add timeline note command via WebSocket."""
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        strain_library = hass.data[DOMAIN]["strain_library"]

        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id=msg[ATTR_PLANT_ID],
            notes=msg[ATTR_NOTES],
            transition_date_raw=msg.get(ATTR_TRANSITION_DATE),
            images_base64=msg.get(ATTR_IMAGES),
            tags=msg.get(ATTR_TAGS),
            ph=msg.get(ATTR_PH),
            ec=msg.get(ATTR_EC),
            amount_ml=msg.get(ATTR_AMOUNT_ML),
            external_metadata=msg.get(ATTR_METADATA),
        )
        connection.send_result(msg["id"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as err:
        _LOGGER.exception("Error handling websocket_add_timeline_note")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_remove_timeline_event(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle remove timeline event command via WebSocket."""
    event_id = msg["event_id"]
    try:
        recorder = get_instance(hass)

        def _delete_event() -> None:
            with session_scope(hass=hass) as session:
                # Delete the event from the Events table
                # We don't delete from EventData as it might be shared
                session.query(Events).filter(Events.event_id == event_id).delete(
                    synchronize_session=False
                )

        await recorder.async_add_executor_job(_delete_event)
        connection.send_result(msg["id"])

    except Exception as err:
        _LOGGER.exception("Error handling websocket_remove_timeline_event")
        connection.send_error(msg["id"], "unknown_error", str(err))


WS_TYPE_GET_HISTORY_STATS = f"{DOMAIN}/get_history_stats"
SCHEMA_WS_GET_HISTORY_STATS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_HISTORY_STATS,
        vol.Required("entity_ids"): [str],
        vol.Required("start_time"): str,
        vol.Optional("end_time"): str,
        vol.Optional("interval_minutes", default=5): int,
        vol.Optional("significant_changes_only", default=True): bool,
    }
)


async def websocket_get_history_stats(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get history stats command with server-side optimization.

    Uses Recorder Statistics API for long periods (pre-aggregated hourly data)
    with fallback to optimized binary search downsampling for shorter periods.
    """
    entity_ids = msg["entity_ids"]
    start_time_str = msg["start_time"]
    end_time_str = msg.get("end_time")
    interval = msg["interval_minutes"]

    start_time = dt_util.parse_datetime(start_time_str)
    end_time = (
        dt_util.parse_datetime(end_time_str) if end_time_str else dt_util.utcnow()
    )

    if not start_time:
        connection.send_error(msg["id"], "invalid_args", "Invalid start_time")
        return

    if not end_time:
        connection.send_error(msg["id"], "invalid_args", "Invalid end_time")
        return

    try:
        # For long intervals (>=60 min), use Recorder Statistics API (pre-aggregated)
        # This is orders of magnitude faster than raw history + downsampling
        if interval >= 60:
            stats_result = await _get_statistics_data(
                hass, entity_ids, start_time, end_time, interval
            )
            if stats_result:
                connection.send_result(msg["id"], stats_result)
                return

        # Fallback: Use optimized binary search downsampling for short intervals
        # or entities without statistics
        result = await _get_history_with_binary_search_downsample(
            hass, entity_ids, start_time, end_time, interval
        )
        connection.send_result(msg["id"], result)

    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_history_stats")
        connection.send_error(msg["id"], "unknown_error", str(err))


WS_TYPE_UPDATE_SENSOR_COORDINATES = f"{DOMAIN}/update_sensor_coordinates"
SCHEMA_WS_UPDATE_SENSOR_COORDINATES = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_SENSOR_COORDINATES,
        vol.Required("growspace_id"): str,
        vol.Required("entity_id"): str,
        vol.Required("x"): int,
        vol.Required("y"): int,
        vol.Required("z"): int,
        vol.Optional("rotation"): int,
    }
)


async def websocket_update_sensor_coordinates(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle update sensor coordinates command."""
    growspace_id = msg["growspace_id"]
    entity_id = msg["entity_id"]
    x = msg["x"]
    y = msg["y"]
    z = msg["z"]
    rotation = msg.get("rotation")

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            connection.send_error(
                msg["id"], "not_found", f"Growspace {growspace_id} not found"
            )
            return

        # Update sensor coordinates in growspace data
        if (
            not hasattr(growspace, "environment_config")
            or not growspace.environment_config
        ):
            connection.send_error(
                msg["id"],
                "invalid_state",
                "Grow space has no environment configuration",
            )
            return

        if not growspace.environment_config.sensor_coordinates:
            growspace.environment_config.sensor_coordinates = {}

        data = {
            "x": x,
            "y": y,
            "z": z,
        }
        if rotation is not None:
            data["rotation"] = rotation

        growspace.environment_config.sensor_coordinates[entity_id] = data

        # Save the coordinator data
        await coordinator.async_save()

        # Trigger a coordinator refresh to update all sensors
        await coordinator.async_request_refresh()

        connection.send_result(msg["id"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as err:
        _LOGGER.exception("Error handling websocket_update_sensor_coordinates")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def _get_statistics_data(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time: datetime,
    end_time: datetime,
    interval: int,
) -> dict[str, list[dict[str, Any]]] | None:
    """Fetch data using Recorder Statistics API (pre-aggregated hourly data)."""
    # Determine the appropriate period based on interval
    if interval >= 1440:  # 24 hours or more
        period = "day"
    elif interval >= 60:  # 1 hour or more
        period = "hour"
    else:
        return None  # Statistics API doesn't support sub-hourly

    try:
        # Fetch statistics from the recorder (native async method)
        # Use async_statistics_during_period if available (standard)
        if hasattr(recorder_stats, "async_statistics_during_period"):
            stats_data = await recorder_stats.async_statistics_during_period(
                hass,
                start_time,
                end_time,
                set(entity_ids),
                period,
                None,  # units (use default)
                {"mean", "state"},  # types to fetch
            )
        else:
            # Fallback for when async helper is missing (unlikely, but safe)
            # Run sync version in executor
            stats_data = await get_instance(hass).async_add_executor_job(
                recorder_stats.statistics_during_period,
                hass,
                start_time,
                end_time,
                set(entity_ids),
                period,
                None,
                {"mean", "state"},
            )

        if not stats_data:
            return None

        # Convert statistics format to our expected output format
        result: dict[str, list[dict[str, Any]]] = {}
        for entity_id in entity_ids:
            if entity_id in stats_data:
                points = stats_data[entity_id]
                # Fix: Use explicit None check to correctly handle mean=0
                # (0 is falsy in Python, so `mean or state` would incorrectly
                # fall back when mean is zero)
                result[entity_id] = []
                for p in points:
                    val = p.get("mean")
                    if val is None:
                        val = p.get("state")

                    if val is not None:
                        result[entity_id].append(
                            {
                                "s": str(val),
                                "lu": (
                                    dt_util.utc_from_timestamp(p["start"]).isoformat()
                                    if isinstance(p["start"], (int, float))
                                    else p["start"]
                                ),
                            }
                        )
            else:
                result[entity_id] = []

    except Exception:  # noqa: BLE001
        # Catch any error from Statistics API to ensure fallback to raw history
        _LOGGER.debug("Statistics API failed, falling back to raw history")
        return None
    else:
        return result


def _downsample_entity_binary_search(
    states: list[Any],
    start_time: datetime,
    end_time: datetime,
    interval_delta: timedelta,
) -> list[dict[str, Any]]:
    """Downsample states using binary search with finger optimization."""
    downsampled = []
    current_time = start_time

    # Optimize: Start search from the index found in previous iteration
    # Since we iterate forward in time, the simplified search space is [last_idx:]
    last_idx = 0

    while current_time <= end_time:
        # key argument allows us to avoid pre-parsing the whole list O(N)
        idx = (
            bisect.bisect_right(states, current_time, key=_extract_ts, lo=last_idx) - 1
        )

        if idx >= 0:
            # Update search lower bound for next iteration
            last_idx = idx

            s = states[idx]

            # Skip states with invalid (sentinel) timestamps
            if _extract_ts(s) == _EPOCH_SENTINEL:
                current_time += interval_delta
                continue

            if isinstance(s, dict):
                state_val = s.get("state")
            else:
                state_val = s.state

            if state_val and state_val not in ("unknown", "unavailable"):
                downsampled.append(
                    {
                        "s": state_val,
                        "lu": current_time.isoformat(),
                    }
                )
        else:
            last_idx = 0

        current_time += interval_delta
    return downsampled


async def _get_history_with_binary_search_downsample(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time: datetime,
    end_time: datetime,
    interval: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch raw history and downsample using optimized binary search.

    Optimized to avoid O(N) pre-parsing of timestamps. uses bisect with key (Py3.10+)
    and 'lo' parameter to perform efficient 'finger search'.
    """

    def _get_history() -> dict[str, list[Any]]:
        return history.get_significant_states(
            hass,
            start_time,
            end_time,
            entity_ids,
            significant_changes_only=True,
            minimal_response=True,
            no_attributes=True,
        )

    # Fetch raw history data
    history_data = await get_instance(hass).async_add_executor_job(_get_history)

    # Helper to extract and ensure datetime from state object/dict
    # (Moved to module level: _extract_ts)

    def _downsample_with_binary_search() -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        interval_delta = timedelta(minutes=interval)

        for entity_id, states in history_data.items():
            if not states:
                result[entity_id] = []
                continue

            result[entity_id] = _downsample_entity_binary_search(
                states, start_time, end_time, interval_delta
            )

        return result

    return await hass.async_add_executor_job(_downsample_with_binary_search)  # type: ignore[no-any-return]  # executor returns Any


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API commands."""
    _LOGGER.debug("Registering WebSocket API for %s", DOMAIN)

    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_LOG,
        websocket_api.async_response(websocket_get_event_log),
        SCHEMA_WS_GET_LOG,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_ALERTS,
        websocket_api.async_response(websocket_get_alerts),
        SCHEMA_WS_GET_ALERTS,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_STRAIN_LIBRARY,
        websocket_get_strain_library,
        SCHEMA_WS_GET_STRAIN_LIBRARY,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_NUTRIENT_PRESETS,
        websocket_get_nutrient_presets,
        SCHEMA_WS_GET_NUTRIENT_PRESETS,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_IPM_PRESETS,
        websocket_get_ipm_presets,
        SCHEMA_WS_GET_IPM_PRESETS,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_DATA,
        websocket_api.async_response(websocket_get_growspace_data),
        SCHEMA_WS_GET_DATA,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_NUTRIENT_INVENTORY,
        websocket_get_nutrient_inventory,
        SCHEMA_WS_GET_NUTRIENT_INVENTORY,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_UPDATE_NUTRIENT_STOCK,
        websocket_update_nutrient_stock,
        SCHEMA_WS_UPDATE_NUTRIENT_STOCK,
    )
    websocket_api.async_register_command(
        hass,
        WS_TYPE_REMOVE_NUTRIENT_STOCK,
        websocket_remove_nutrient_stock,
        SCHEMA_WS_REMOVE_NUTRIENT_STOCK,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_GET_HISTORY_STATS,
        websocket_api.async_response(websocket_get_history_stats),
        SCHEMA_WS_GET_HISTORY_STATS,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_UPDATE_SENSOR_COORDINATES,
        websocket_api.async_response(websocket_update_sensor_coordinates),
        SCHEMA_WS_UPDATE_SENSOR_COORDINATES,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_ADD_TIMELINE_NOTE,
        websocket_api.async_response(websocket_add_timeline_note),
        SCHEMA_WS_ADD_TIMELINE_NOTE,
    )

    websocket_api.async_register_command(
        hass,
        WS_TYPE_REMOVE_TIMELINE_EVENT,
        websocket_api.async_response(websocket_remove_timeline_event),
        SCHEMA_WS_REMOVE_TIMELINE_EVENT,
    )
