"""Growspace Manager integration."""

from __future__ import annotations

import logging
import pathlib
import tempfile
from typing import Any

import voluptuous as vol
from aiohttp import BodyPartReader, web
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .dehumidifier_coordinator import DehumidifierCoordinator
from .intent import async_setup_intents
from .irrigation_coordinator import IrrigationCoordinator
from .service_registration import get_coordinator_for_call, register_services
from .services.strain_library import StrainLibrary
from .vwc_irrigation_coordinator import VWCIrrigationCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


type GrowspaceConfigEntry = ConfigEntry[GrowspaceCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Growspace Manager component."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize and load Strain Library (global instance)
    strain_library_instance = StrainLibrary(hass)
    await strain_library_instance.async_setup()
    hass.data[DOMAIN]["strain_library"] = strain_library_instance

    # Register View
    hass.http.register_view(StrainLibraryUploadView(hass, strain_library_instance))

    # Register all custom services
    _LOGGER.debug("Registering services for domain %s", DOMAIN)
    await register_services(hass, strain_library_instance)

    # Register WebSocket API
    WS_TYPE_GET_LOG = f"{DOMAIN}/get_log"
    SCHEMA_WS_GET_LOG = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_GET_LOG,
            vol.Optional("growspace_id"): str,
        }
    )

    @websocket_api.async_response
    async def websocket_get_event_log(hass: HomeAssistant, connection, msg):
        """Handle get event log command."""
        growspace_id = msg.get("growspace_id")
        events_data = {}

        if growspace_id:
            try:
                coordinator = get_coordinator_for_call(hass, msg)
                events = coordinator.events.get(growspace_id, [])
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
                        events_data[gid] = [e.to_dict() for e in evts]

        connection.send_result(msg["id"], events_data)

    websocket_api.async_register_command(
        hass, WS_TYPE_GET_LOG, websocket_get_event_log, SCHEMA_WS_GET_LOG
    )

    # Growspace Data
    WS_TYPE_GET_DATA = f"{DOMAIN}/get_data"
    SCHEMA_WS_GET_DATA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_GET_DATA,
            vol.Optional("growspace_id"): str,
        }
    )

    @websocket_api.async_response
    async def websocket_get_growspace_data(hass: HomeAssistant, connection, msg):
        """Handle get growspace data command."""
        growspace_id = msg.get("growspace_id")
        try:
            coordinator = get_coordinator_for_call(hass, msg)
            data = coordinator.get_growspace_data(growspace_id)
            connection.send_result(msg["id"], data)
        except ServiceValidationError as err:
            connection.send_error(msg["id"], "invalid_args", str(err))
        except Exception as e:
            connection.send_error(msg["id"], "unknown_error", str(e))

    websocket_api.async_register_command(
        hass, WS_TYPE_GET_DATA, websocket_get_growspace_data, SCHEMA_WS_GET_DATA
    )

    # Set up intents
    await async_setup_intents(hass)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Set up Growspace Manager from a config entry."""
    _LOGGER.debug(
        "Setting up Growspace Manager integration for entry %s", entry.entry_id
    )

    # Initialize Storage and Coordinator
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}

    # Retrieve global Strain Library
    strain_library_instance = hass.data[DOMAIN]["strain_library"]

    coordinator = GrowspaceCoordinator(
        hass,
        data,
        options=dict(entry.options),
        strain_library=strain_library_instance,
    )
    await coordinator.async_load()  # Load data into the coordinator

    entry.runtime_data = coordinator

    for growspace_id, gs in coordinator.growspaces.items():
        # ADD THIS DEBUG LOGGING
        irrigation_config = entry.options.get("irrigation", {}).get(growspace_id, {})
        _LOGGER.debug(
            "IRRIGATION INIT - Growspace: %s, Config: %s",
            growspace_id,
            irrigation_config,
        )

        if gs.irrigation_strategy.enabled:
            _LOGGER.info(
                "Initializing VWC Irrigation Coordinator for growspace %s", growspace_id
            )
            irrigation_coordinator = VWCIrrigationCoordinator(
                hass, entry, growspace_id, coordinator
            )
        else:
            _LOGGER.debug(
                "Initializing Standard Irrigation Coordinator for growspace %s",
                growspace_id,
            )
            irrigation_coordinator = IrrigationCoordinator(
                hass, entry, growspace_id, coordinator
            )

        await irrigation_coordinator.async_setup()
        entry.runtime_data.irrigation_coordinators[growspace_id] = (
            irrigation_coordinator
        )

        dehumidifier_coordinator = DehumidifierCoordinator(
            hass, entry, growspace_id, coordinator
        )

        entry.runtime_data.dehumidifier_coordinators[growspace_id] = (
            dehumidifier_coordinator
        )

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
            create_notification(
                hass,
                (
                    f"Failed to create pending growspace '{pending.get('name', 'unknown')}'"
                ),
                title="Growspace Manager Error",
            )

    # Forward entry setup to platforms (e.g., sensors, switches)
    _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Perform the first refresh to populate data
    await coordinator.async_config_entry_first_refresh()

    return True


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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
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


def create_notification(
    hass: HomeAssistant, message: str, title: str = "Growspace Manager"
) -> None:
    """Create a persistent notification."""
    hass.components.persistent_notification.create(
        message, title=title, notification_id=f"{DOMAIN}_notification"
    )
