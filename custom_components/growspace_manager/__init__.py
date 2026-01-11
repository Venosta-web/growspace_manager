"""Growspace Manager integration."""

from __future__ import annotations

import bisect
import json  # Added for event data parsing
import logging
import pathlib
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, override

import homeassistant.util.dt as dt_util
import voluptuous as vol
from aiohttp import BodyPartReader, web
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder import statistics as recorder_stats
from homeassistant.components.recorder.db_schema import (
    EventData,
    Events,
    EventTypes,
)
from homeassistant.components.recorder.util import session_scope
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import service_registration
from .const import (
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
    PLATFORMS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import GrowspaceCoordinator
from .intent import async_setup_intents
from .services.plant import async_add_timeline_note
from .services.strain_library import StrainLibrary

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)

# Sentinel for invalid timestamps
_EPOCH_SENTINEL = dt_util.dt.datetime.min.replace(tzinfo=dt_util.dt.timezone.utc)


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
        return parsed if parsed else _EPOCH_SENTINEL
    return ts_raw


type GrowspaceConfigEntry = ConfigEntry[GrowspaceCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Growspace Manager component."""
    hass.data.setdefault(DOMAIN, {})
    # Register WebSocket API commands globally (once per HA instance)
    _async_register_websocket_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Set up Growspace Manager from a config entry."""
    _LOGGER.debug(
        "Setting up Growspace Manager integration for entry %s", entry.entry_id
    )

    # Initialize Storage and Coordinator
    store = Store[dict[str, Any]](hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}

    # Initialize and load Strain Library (global instance)
    if "strain_library" not in hass.data[DOMAIN]:
        strain_library_instance = StrainLibrary(hass)
        await strain_library_instance.async_setup()
        hass.data[DOMAIN]["strain_library"] = strain_library_instance

        # Register Views
        hass.http.register_view(StrainLibraryUploadView(hass, strain_library_instance))
        hass.http.register_view(StrainLibraryImageView(hass, strain_library_instance))

        # Register all custom services
        _LOGGER.debug("Registering services for domain %s", DOMAIN)
        await service_registration.register_services(hass, strain_library_instance)

        # Set up intents
        await async_setup_intents(hass)

    # Retrieve global Strain Library
    strain_library_instance = hass.data[DOMAIN]["strain_library"]

    coordinator = GrowspaceCoordinator(
        hass,
        entry,
        data,
        options=dict(entry.options),
        strain_library=strain_library_instance,
    )
    await coordinator.async_load()  # Load data into the coordinator

    entry.runtime_data = coordinator

    # Initialize sub-coordinators
    await coordinator.async_initialize_sub_coordinators(entry)

    entry.async_on_unload(lambda: _async_cancel_coordinators(entry.runtime_data))
    entry.add_update_listener(_async_update_listener)

    # Handle pending growspace if initiated before entry setup completion
    pending = entry.data.get("pending_growspace")
    if pending:
        try:
            await coordinator.async_add_growspace(
                name=pending["name"],
                rows=pending["rows"],
                plants_per_row=pending["plants_per_row"],
                notification_target=pending.get("notification_target"),
            )
            _LOGGER.info(
                "Created pending growspace: %s", pending.get("name", "unknown")
            )

            # Clean up pending data from config entry
            new_data = entry.data.copy()
            new_data.pop("pending_growspace")
            hass.config_entries.async_update_entry(entry, data=new_data)

        except (KeyError, RuntimeError):
            _LOGGER.exception(
                "Failed to create pending growspace %s",
                pending.get("name", "unknown"),
            )
            async_create_issue(
                hass,
                DOMAIN,
                f"pending_growspace_fail_{pending.get('name', 'unknown')}",
                is_fixable=False,
                severity=IssueSeverity.ERROR,
                translation_key="pending_growspace_fail",
                translation_placeholders={
                    "name": pending.get("name", "unknown"),
                    "error": "Failed to create pending growspace",
                },
            )

    # Forward entry setup to platforms (e.g., sensors, switches)
    _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Perform the first refresh to populate data
    await coordinator.async_config_entry_first_refresh()

    return True


@callback
def _async_cancel_coordinators(coordinator: GrowspaceCoordinator) -> None:
    """Cancel irrigation and dehumidifier listeners."""
    for irr_coordinator in coordinator.irrigation_coordinators.values():
        irr_coordinator.async_cancel_listeners()
    for dehum_coordinator in coordinator.dehumidifier_coordinators.values():
        dehum_coordinator.unload()


# Removed _async_remove_dynamic_entities per user request


async def async_unload_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry %s for Growspace Manager", entry.entry_id)

    # Clean up dynamically created entities before unloading platforms
    # _async_remove_dynamic_entities(hass, entry.runtime_data) # Removed per request

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Services remain registered until HA shutdown

        # Clean up global Strain Library
        if DOMAIN in hass.data and "strain_library" in hass.data[DOMAIN]:
            await hass.data[DOMAIN]["strain_library"].async_close()
            del hass.data[DOMAIN]["strain_library"]

        _LOGGER.info("Unloaded Growspace Manager for entry %s", entry.entry_id)
        return True

    _LOGGER.error("Failed to unload platforms for entry %s", entry.entry_id)
    return False


async def _async_update_listener(
    hass: HomeAssistant, entry: GrowspaceConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> None:
    """Reload a config entry."""
    _LOGGER.debug(
        "Reloading Growspace Manager integration for entry %s", entry.entry_id
    )
    await hass.config_entries.async_reload(entry.entry_id)


class StrainLibraryUploadView(HomeAssistantView):
    """View to handle strain library imports via HTTP upload."""

    url = "/api/growspace_manager/import_strains"
    name = "api:growspace_manager:import_strains"
    requires_auth = True

    def __init__(
        self,
        hass: HomeAssistant,
        strain_lib: StrainLibrary,
    ) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_lib

    def _is_valid_upload_field(self, file_field: Any) -> bool:
        """Validate the uploaded file field."""
        if not file_field:
            return False
        if not isinstance(file_field, BodyPartReader):
            return False
        return file_field.name == "file"

    async def _save_upload_to_temp(self, file_field: BodyPartReader) -> pathlib.Path:
        """Save uploaded stream to a temporary file."""
        temp_fd, temp_path_str = await self.hass.async_add_executor_job(
            tempfile.mkstemp, ".zip"
        )
        temp_path = pathlib.Path(temp_path_str)

        try:
            # We use a file object opened in binary write mode
            def write_chunk(path: str, data: bytes) -> None:
                with open(path, "ab") as f:
                    f.write(data)

            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                await self.hass.async_add_executor_job(
                    write_chunk, temp_path_str, chunk
                )
            return temp_path
        except Exception:
            # Clean up if writing fails
            if temp_path.exists():
                await self.hass.async_add_executor_job(temp_path.unlink)
            raise

    @override
    async def post(self, request: web.Request) -> web.Response:
        """Handle the POST request for file upload."""
        # 1. Read the multipart data (file)
        reader = await request.multipart()
        file_field = await reader.next()

        if not self._is_valid_upload_field(file_field):
            return web.Response(status=400, text="No file provided or invalid type")

        # 2. Save to temp file
        try:
            temp_path = await self._save_upload_to_temp(file_field)
        except Exception:
            return web.Response(status=500, text="Failed to save upload")

        try:
            # 3. Process Import
            count = await self.strain_library.import_library_from_zip(
                str(temp_path), merge=True
            )
            await self.strain_library.save()

            # Request refresh for all coordinators
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.state == ConfigEntryState.LOADED and hasattr(
                    entry, "runtime_data"
                ):
                    await entry.runtime_data.async_request_refresh()

            return self.json({"success": True, "imported_count": count})

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Error processing strain library upload")
            return self.json({"success": False, "error": str(err)})

        finally:
            # Cleanup
            if temp_path.exists():
                await self.hass.async_add_executor_job(temp_path.unlink)


class StrainLibraryImageView(HomeAssistantView):
    """View to serve images from the strain library storage."""

    url = "/api/growspace_manager/v1/images/{filename:.*}"
    name = "api:growspace_manager:v1:images"
    requires_auth = False  # Or True, depending on if you want auth for images

    def __init__(
        self,
        hass: HomeAssistant,
        strain_lib: StrainLibrary,
    ) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_lib

    @override
    async def get(self, request: web.Request, filename: str) -> web.Response:
        """Handle GET request for image."""
        if not self.strain_library.image_manager:
            return web.Response(status=404, text="Image manager not available")

        storage_dir = self.strain_library.image_manager.storage_dir

        # Security check: resolve path and ensure it's within storage_dir
        try:
            file_path = (storage_dir / filename).resolve()
            if not str(file_path).startswith(str(storage_dir.resolve())):
                _LOGGER.warning("Attempted directory traversal access: %s", filename)
                return web.Response(status=403, text="Access denied")

            if not file_path.exists() or not file_path.is_file():
                return web.Response(status=404, text="Image not found")

            return web.FileResponse(file_path)
        except Exception as e:
            _LOGGER.error("Error serving image %s: %s", filename, e)
            return web.Response(status=500, text="Internal server error")


WS_TYPE_GET_LOG = f"{DOMAIN}/get_log"
SCHEMA_WS_GET_LOG = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_LOG,
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


async def websocket_get_growspace_data(hass: HomeAssistant, connection, msg):
    """Handle get growspace data command."""
    growspace_id = msg.get("growspace_id")
    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        data = coordinator.get_growspace_data(growspace_id)
        connection.send_result(msg["id"], data)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:
        connection.send_error(msg["id"], "unknown_error", str(e))



def _merge_logbook_event(formatted_events_list, data_dict, evt_row):
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
                if 0 <= gap_sec <= 600:
                    last_evt["start_time"] = data_dict["start_time"]
                    last_evt["duration_sec"] = last_evt.get(
                        "duration_sec", 0
                    ) + data_dict.get("duration_sec", 0)

                    if "reasons" in data_dict and "reasons" in last_evt:
                        comb = list(
                            dict.fromkeys(last_evt["reasons"] + data_dict["reasons"])
                        )
                        last_evt["reasons"] = comb[:5]
                    return True
        except (ValueError, TypeError, KeyError):
            pass
    return False


async def websocket_get_event_log(hass: HomeAssistant, connection, msg):
    """Handle get event log command via Recorder."""
    growspace_id = msg.get("growspace_id")
    limit = msg.get("limit", 1000)
    spam_limit = 200
    spam_cats = {"optimal", "stress", "mold"}

    try:
        recorder = get_instance(hass)
        end_time = dt_util.utcnow()
        start_time = end_time - dt_util.dt.timedelta(days=7)

        def _query_events():
            formatted = []
            counts = {"normal": 0, "spammy": 0}

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
                    .order_by(Events.time_fired_ts.desc())
                )
                if limit:
                    q = q.limit(limit * 5)

                for e_row, d_row in q:
                    if not d_row or not d_row.shared_data:
                        continue
                    try:
                        d = json.loads(d_row.shared_data)
                        if growspace_id and d.get("growspace_id") != growspace_id:
                            continue

                        cat = d.get("category")
                        is_s = cat in spam_cats
                        c_key = "spammy" if is_s else "normal"
                        c_lim = spam_limit if is_s else limit

                        if counts[c_key] >= c_lim:
                            continue
                        counts[c_key] += 1

                        if "timestamp" not in d and e_row.time_fired_ts:
                            d["timestamp"] = e_row.time_fired_ts * 1000

                        if not _merge_logbook_event(formatted, d, e_row):
                            d["event_id"] = e_row.event_id
                            formatted.append(d)

                        if counts["spammy"] >= spam_limit and counts["normal"] >= limit:
                            break
                    except (json.JSONDecodeError, AttributeError):
                        continue
            return formatted

        evts = await recorder.async_add_executor_job(_query_events)
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


@callback
def websocket_get_nutrient_presets(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get nutrient presets command via WebSocket."""
    try:
        coordinator: GrowspaceCoordinator = GrowspaceCoordinator.get_for_service_call(
            hass, msg
        )

        response = {pid: asdict(p) for pid, p in coordinator.nutrient_presets.items()}
        connection.send_result(msg["id"], response)
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

        response = {pid: asdict(p) for pid, p in coordinator.ipm_presets.items()}
        connection.send_result(msg["id"], response)
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

        def _delete_event():
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


@callback
def _async_register_websocket_api(hass: HomeAssistant) -> None:
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
        WS_TYPE_GET_HISTORY_STATS,
        websocket_api.async_response(websocket_get_history_stats),
        SCHEMA_WS_GET_HISTORY_STATS,
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


async def websocket_get_history_stats(hass: HomeAssistant, connection, msg):
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


async def _get_statistics_data(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time,
    end_time,
    interval: int,
) -> dict[str, list[dict]] | None:
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
        stats_data = await recorder_stats.async_statistics_during_period(
            hass,
            start_time,
            end_time,
            set(entity_ids),
            period,
            None,  # units (use default)
            {"mean", "state"},  # types to fetch
        )

        if not stats_data:
            return None

        # Convert statistics format to our expected output format
        result: dict[str, list[dict]] = {}
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

        return result

    except Exception as err:
        _LOGGER.debug("Statistics API failed, falling back to raw history: %s", err)
        return None


def _downsample_entity_binary_search(
    states: list[Any],
    start_time: datetime,
    end_time: datetime,
    interval_delta: timedelta,
) -> list[dict]:
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
    start_time,
    end_time,
    interval: int,
) -> dict[str, list[dict]]:
    """Fetch raw history and downsample using optimized binary search.

    Optimized to avoid O(N) pre-parsing of timestamps. uses bisect with key (Py3.10+)
    and 'lo' parameter to perform efficient 'finger search'.
    """

    def _get_history():
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

    def _downsample_with_binary_search():
        result = {}
        interval_delta = dt_util.dt.timedelta(minutes=interval)

        for entity_id, states in history_data.items():
            if not states:
                result[entity_id] = []
                continue

            result[entity_id] = _downsample_entity_binary_search(
                states, start_time, end_time, interval_delta
            )

        return result

    return await hass.async_add_executor_job(_downsample_with_binary_search)
