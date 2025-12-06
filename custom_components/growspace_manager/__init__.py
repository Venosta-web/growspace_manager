"""Growspace Manager integration."""

from __future__ import annotations

import logging
import pathlib
import tempfile
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from aiohttp import BodyPartReader, web
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .dehumidifier_coordinator import DehumidifierCoordinator
from .intent import async_setup_intents
from .irrigation_coordinator import IrrigationCoordinator
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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


@dataclass
class GrowspaceRuntimeData:
    """Runtime data for the Growspace Manager integration."""

    coordinator: GrowspaceCoordinator
    store: Store
    created_entities: list[str]
    irrigation_coordinators: dict[str, IrrigationCoordinator]
    dehumidifier_coordinators: dict[str, DehumidifierCoordinator]


type GrowspaceConfigEntry = ConfigEntry[GrowspaceRuntimeData]


async def _register_services(
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Growspace Manager component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Set up Growspace Manager from a config entry."""
    _LOGGER.debug(
        "Setting up Growspace Manager integration for entry %s", entry.entry_id
    )

    # Initialize Storage and Coordinator
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}

    # Initialize and load Strain Library (global instance)
    strain_library_instance = StrainLibrary(hass)
    await strain_library_instance.async_setup()
    hass.data.setdefault(DOMAIN, {})

    coordinator = GrowspaceCoordinator(
        hass,
        data,
        options=dict(entry.options),
        strain_library=strain_library_instance,
    )
    await coordinator.async_load()  # Load data into the coordinator

    hass.http.register_view(
        StrainLibraryUploadView(hass, strain_library_instance, coordinator)
    )

    entry.runtime_data = GrowspaceRuntimeData(
        coordinator=coordinator,
        store=store,
        created_entities=[],
        irrigation_coordinators={},
        dehumidifier_coordinators={},
    )

    for growspace_id in coordinator.growspaces:
        # ADD THIS DEBUG LOGGING
        irrigation_config = entry.options.get("irrigation", {}).get(growspace_id, {})
        _LOGGER.debug(
            "IRRIGATION INIT - Growspace: %s, Config: %s",
            growspace_id,
            irrigation_config,
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

    entry.add_update_listener(_async_update_listener)

    # Register all custom services
    _LOGGER.debug("Registering services for domain %s", DOMAIN)
    await _register_services(hass, coordinator, strain_library_instance)

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
            events = coordinator.events.get(growspace_id, [])
            events_data[growspace_id] = [e.to_dict() for e in events]
        else:
            for gid, evts in coordinator.events.items():
                events_data[gid] = [e.to_dict() for e in evts]

        connection.send_result(msg["id"], events_data)

    hass.components.websocket_api.async_register_command(
        WS_TYPE_GET_LOG, websocket_get_event_log, SCHEMA_WS_GET_LOG
    )

    # Set up intents
    await async_setup_intents(hass)

    # Handle pending growspace if initiated before entry setup completion
    if "pending_growspace" in hass.data.get(DOMAIN, {}):
        pending = hass.data[DOMAIN].pop("pending_growspace")
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


# ... _register_services ...


def _async_cancel_coordinators(runtime_data: GrowspaceRuntimeData) -> None:
    """Cancel irrigation and dehumidifier listeners."""
    for irr_coordinator in runtime_data.irrigation_coordinators.values():
        irr_coordinator.async_cancel_listeners()
    for dehum_coordinator in runtime_data.dehumidifier_coordinators.values():
        dehum_coordinator.unload()


def _async_remove_dynamic_entities(
    hass: HomeAssistant, runtime_data: GrowspaceRuntimeData
) -> None:
    """Remove dynamically created entities."""
    created_unique_ids = runtime_data.created_entities
    entity_registry = er.async_get(hass)

    for unique_id in created_unique_ids:
        # Determine the domain and platform from the unique_id
        if "trend" in unique_id:
            domain = "binary_sensor"
            platform = "trend"
        elif "stats" in unique_id:
            domain = "sensor"
            platform = "statistics"
        else:
            _LOGGER.warning("Unknown platform for unique_id: %s", unique_id)
            continue

        entity_id = entity_registry.async_get_entity_id(domain, platform, unique_id)
        if entity_id and entity_registry.async_get(entity_id):
            entity_registry.async_remove(entity_id)
            _LOGGER.info(
                "Removed dynamically created entity: %s (unique_id: %s)",
                entity_id,
                unique_id,
            )


# ... _async_remove_services ...


async def async_unload_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry %s for Growspace Manager", entry.entry_id)

    # Clean up dynamically created entities before unloading platforms
    # entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}) # OLD

    _async_cancel_coordinators(entry.runtime_data)
    _async_remove_dynamic_entities(hass, entry.runtime_data)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        entries = hass.config_entries.async_entries(DOMAIN)
        if (
            len(entries) == 1
        ):  # This is the last one (it's still in the list until fully unloaded?)
            # Actually async_unload_entry is called before it's removed from entries list?
            # Let's assume if we are unloading, we might want to clean up if no other entries.
            pass

        # For now, let's just remove services.
        _async_remove_services(hass)

        _LOGGER.info("Unloaded Growspace Manager for entry %s", entry.entry_id)
        return True

    _LOGGER.error("Failed to unload platforms for entry %s", entry.entry_id)
    return False


def _async_remove_services(hass: HomeAssistant) -> None:
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
        coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_lib
        self.coordinator = coordinator

    async def post(self, request: web.Request) -> web.Response:
        """Handle the POST request for file upload."""
        # 1. Read the multipart data (file)
        reader = await request.multipart()
        file_field = await reader.next()

        if not file_field:
            return web.Response(status=400, text="No file provided")

        if not isinstance(file_field, BodyPartReader):
            return web.Response(status=400, text="Invalid file upload type")

        if file_field.name != "file":
            return web.Response(status=400, text="No file provided")

        # 2. Save to temp file
        # (Use a scalable chunk write to avoid memory issues)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            temp_path = pathlib.Path(tmp.name)
            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                tmp.write(chunk)

        try:
            # 3. Process Import
            count = await self.strain_library.import_library_from_zip(
                str(temp_path), merge=True
            )
            await self.strain_library.save()
            await self.coordinator.async_request_refresh()
            return self.json({"success": True, "imported_count": count})

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Error processing strain library upload")
            return self.json({"success": False, "error": str(err)})

        finally:
            # Cleanup
            if temp_path.exists():
                temp_path.unlink()


def create_notification(
    hass: HomeAssistant, message: str, title: str = "Growspace Manager"
) -> None:
    """Create a persistent notification."""
    hass.components.persistent_notification.create(
        message, title=title, notification_id=f"{DOMAIN}_notification"
    )
