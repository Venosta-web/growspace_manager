"""Growspace Manager integration."""

from __future__ import annotations

import bisect
import logging
import pathlib
import tempfile
from typing import Any, override

import homeassistant.util.dt as dt_util
import voluptuous as vol
from aiohttp import BodyPartReader, web
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder import statistics as recorder_stats
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import service_registration
from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .intent import async_setup_intents
from .services.strain_library import StrainLibrary

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


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

        # Register View
        hass.http.register_view(StrainLibraryUploadView(hass, strain_library_instance))

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


async def websocket_get_event_log(hass: HomeAssistant, connection, msg):
    """Handle get event log command."""
    growspace_id = msg.get("growspace_id")
    limit = msg.get("limit")
    events_data = {}

    try:
        if growspace_id:
            try:
                coordinator = service_registration.get_coordinator_for_call(hass, msg)
                events = coordinator.events.get(growspace_id, [])
                # Apply limit if provided (get last N events)
                if limit and len(events) > limit:
                    events = events[-limit:]
                events_data[growspace_id] = [e.to_dict() for e in events]
            except (
                ServiceValidationError
            ):  # invalid growspace_id or no coordinator found
                _LOGGER.warning(
                    "Could not find coordinator for growspace %s", growspace_id
                )
        else:
            # Aggregate from all coordinators
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.state == ConfigEntryState.LOADED and hasattr(
                    entry, "runtime_data"
                ):
                    coord = entry.runtime_data
                    for gid, evts in coord.events.items():
                        # Apply limit if provided (get last N events)
                        if limit and len(evts) > limit:
                            evts = evts[-limit:]
                        events_data[gid] = [e.to_dict() for e in evts]

        connection.send_result(msg["id"], events_data)
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_event_log")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_get_growspace_data(hass: HomeAssistant, connection, msg):
    """Handle get growspace data command."""
    growspace_id = msg.get("growspace_id")
    try:
        coordinator = service_registration.get_coordinator_for_call(hass, msg)
        data = coordinator.get_growspace_data(growspace_id)
        connection.send_result(msg["id"], data)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as e:
        connection.send_error(msg["id"], "unknown_error", str(e))


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


async def _get_history_with_binary_search_downsample(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time,
    end_time,
    interval: int,
) -> dict[str, list[dict]]:
    """Fetch raw history and downsample using optimized binary search."""

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

    def _downsample_with_binary_search():
        result = {}
        interval_delta = dt_util.dt.timedelta(minutes=interval)

        for entity_id, states in history_data.items():
            if not states:
                result[entity_id] = []
                continue

            # Pre-parse all timestamps once (O(n))
            timestamps = []
            parsed_states = []
            for s in states:
                if isinstance(s, dict):
                    ts_raw = s.get("last_updated", s.get("last_changed"))
                    ts = (
                        dt_util.parse_datetime(ts_raw)
                        if isinstance(ts_raw, str)
                        else ts_raw
                    )
                    state_val = s.get("state")
                else:
                    ts = s.last_updated
                    state_val = s.state

                if ts is not None:
                    timestamps.append(ts)
                    parsed_states.append(state_val)

            if not timestamps:
                result[entity_id] = []
                continue

            # Use binary search to find states at each time bucket (O(m log n))
            downsampled = []
            current_time = start_time

            while current_time <= end_time:
                # Binary search: find rightmost state at or before current_time
                idx = bisect.bisect_right(timestamps, current_time) - 1

                if idx >= 0:
                    state_val = parsed_states[idx]
                    if state_val and state_val not in ("unknown", "unavailable"):
                        downsampled.append(
                            {
                                "s": state_val,
                                "lu": current_time.isoformat(),
                            }
                        )

                current_time += interval_delta

            result[entity_id] = downsampled

        return result

    return await hass.async_add_executor_job(_downsample_with_binary_search)
