"""Growspace Manager integration."""

from __future__ import annotations

import logging
import os
import tempfile

from aiohttp import web
import homeassistant.helpers.config_validation as cv
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import (
    ADD_GROWSPACE_SCHEMA,
    ADD_PLANT_SCHEMA,
    ADD_STRAIN_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    DOMAIN,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    STORAGE_KEY,
    STORAGE_KEY_STRAIN_LIBRARY,
    STORAGE_VERSION,
    SWITCH_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
    ADD_DRAIN_TIME_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
)
from .coordinator import GrowspaceCoordinator
from .irrigation_coordinator import IrrigationCoordinator
from .services import (
    debug,
    irrigation,
    environment,
    growspace,
    plant,
    strain_library as strain_library_services,
    ai_assistant,
)
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "switch", "calendar"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)  # pylint: disable=invalid-name


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading entry."""
    _LOGGER.debug("Options updated for entry %s, reloading.", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(_hass: HomeAssistant, _config: dict):
    """Set up the integration via YAML (optional)."""
    _LOGGER.debug("Running async_setup for %s", DOMAIN)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Growspace Manager from a config entry."""
    _LOGGER.debug(
        "Setting up Growspace Manager integration for entry %s", entry.entry_id
    )

    # Initialize Storage and Coordinator
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    data = await store.async_load() or {}

    # Initialize and load Strain Library (global instance)
    strain_library_instance = StrainLibrary(
        hass,
        storage_version=STORAGE_VERSION,
        storage_key=STORAGE_KEY_STRAIN_LIBRARY,
    )
    await strain_library_instance.load()
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["strain_library"] = strain_library_instance

    hass.http.register_view(StrainLibraryUploadView(hass, strain_library_instance))

    coordinator = GrowspaceCoordinator(
        hass,
        data,
        options=entry.options,
        strain_library=strain_library_instance,
    )
    await coordinator.async_load()  # Load data into the coordinator

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "store": store,
        "created_entities": [],
        "irrigation_coordinators": {},
    }

    for growspace_id in coordinator.growspaces:
        # ADD THIS DEBUG LOGGING
        irrigation_config = entry.options.get("irrigation", {}).get(growspace_id, {})
        _LOGGER.debug(
            "IRRIGATION INIT - Growspace: %s, Config: %s",
            growspace_id,
            irrigation_config
        )
        
        irrigation_coordinator = IrrigationCoordinator(hass, entry, growspace_id, coordinator)
        await irrigation_coordinator.async_setup()
        hass.data[DOMAIN][entry.entry_id]["irrigation_coordinators"][
            growspace_id
        ] = irrigation_coordinator

    entry.add_update_listener(_async_update_listener)

    # Register all custom services
    _LOGGER.debug("Registering services for domain %s", DOMAIN)
    await _register_services(hass, coordinator, strain_library_instance)

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
        except (KeyError, RuntimeError) as err:
            _LOGGER.exception(
                "Failed to create pending growspace %s: %s",
                pending.get("name", "unknown"),
                err,
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


async def _register_services(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library_instance: StrainLibrary,
) -> None:
    """Register all Growspace Manager services."""

    # Define all services with their handler functions and schemas
    services_to_register = [
        ("add_growspace", growspace.handle_add_growspace, ADD_GROWSPACE_SCHEMA),
        (
            "remove_growspace",
            growspace.handle_remove_growspace,
            REMOVE_GROWSPACE_SCHEMA,
        ),
        ("add_plant", plant.handle_add_plant, ADD_PLANT_SCHEMA),
        ("update_plant", plant.handle_update_plant, UPDATE_PLANT_SCHEMA),
        ("remove_plant", plant.handle_remove_plant, REMOVE_PLANT_SCHEMA),
        ("move_plant", plant.handle_move_plant, MOVE_PLANT_SCHEMA),
        ("switch_plants", plant.handle_switch_plants, SWITCH_PLANT_SCHEMA),
        (
            "transition_plant_stage",
            plant.handle_transition_plant_stage,
            TRANSITION_PLANT_SCHEMA,
        ),
        ("take_clone", plant.handle_take_clone, TAKE_CLONE_SCHEMA),
        ("move_clone", plant.handle_move_clone, MOVE_CLONE_SCHEMA),
        ("harvest_plant", plant.handle_harvest_plant, HARVEST_PLANT_SCHEMA),
        (
            "export_strain_library",
            strain_library_services.handle_export_strain_library,
            EXPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "import_strain_library",
            strain_library_services.handle_import_strain_library,
            IMPORT_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "clear_strain_library",
            strain_library_services.handle_clear_strain_library,
            CLEAR_STRAIN_LIBRARY_SCHEMA,
        ),
        (
            "add_strain",
            strain_library_services.handle_add_strain,
            ADD_STRAIN_SCHEMA,
        ),
        (
            "remove_strain",
            strain_library_services.handle_remove_strain,
            REMOVE_STRAIN_SCHEMA,
        ),
        (
            "update_strain_meta",
            strain_library_services.handle_update_strain_meta,
            UPDATE_STRAIN_META_SCHEMA,
        ),
        ("test_notification", debug.handle_test_notification, None),
        (
            "debug_cleanup_legacy",
            debug.debug_cleanup_legacy,
            DEBUG_CLEANUP_LEGACY_SCHEMA,
        ),
        (
            "debug_list_growspaces",
            debug.debug_list_growspaces,
            DEBUG_LIST_GROWSPACES_SCHEMA,
        ),
        (
            "debug_reset_special_growspaces",
            debug.debug_reset_special_growspaces,
            DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        ),
        (
            "debug_consolidate_growspaces",
            debug.debug_consolidate_duplicate_special,
            DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        ),
        (
            "configure_environment",
            environment.handle_configure_environment,
            CONFIGURE_ENVIRONMENT_SCHEMA,
        ),
        (
            "remove_environment",
            environment.handle_remove_environment,
            REMOVE_ENVIRONMENT_SCHEMA,
        ),
        (
            "set_irrigation_settings",
            irrigation.handle_set_irrigation_settings,
            SET_IRRIGATION_SETTINGS_SCHEMA,
        ),
        (
            "add_irrigation_time",
            irrigation.handle_add_irrigation_time,
            ADD_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "remove_irrigation_time",
            irrigation.handle_remove_irrigation_time,
            REMOVE_IRRIGATION_TIME_SCHEMA,
        ),
        (
            "add_drain_time",
            irrigation.handle_add_drain_time,
            ADD_DRAIN_TIME_SCHEMA,
        ),
        (
            "remove_drain_time",
            irrigation.handle_remove_drain_time,
            REMOVE_DRAIN_TIME_SCHEMA,
        ),
    ]

    # Register services using a wrapper to pass necessary context
    for service_name, handler_func, schema in services_to_register:

        async def service_wrapper(call: ServiceCall, _handler=handler_func):
            await _handler(hass, coordinator, strain_library_instance, call)

        hass.services.async_register(
            DOMAIN, service_name, service_wrapper, schema=schema
        )
        _LOGGER.debug("Registered service: %s", service_name)

    # --- AI Services Registration (SupportsResponse.ONLY) ---

    # 1. Ask Grow Advice (Switched to ai_assistant handler)
    async def ask_grow_advice_wrapper(
        call: ServiceCall, _handler=ai_assistant.handle_ask_grow_advice
    ):
         return await _handler(hass, coordinator, strain_library_instance, call)

    hass.services.async_register(
        DOMAIN, 
        "ask_grow_advice", 
        ask_grow_advice_wrapper, 
        schema=ASK_GROW_ADVICE_SCHEMA, 
        supports_response=SupportsResponse.ONLY
    )

    # 2. Analyze All Growspaces (New)
    async def analyze_all_wrapper(
        call: ServiceCall, _handler=ai_assistant.handle_analyze_all_growspaces
    ):
         return await _handler(hass, coordinator, strain_library_instance, call)

    hass.services.async_register(
        DOMAIN, 
        "analyze_all_growspaces", 
        analyze_all_wrapper, 
        schema=ANALYZE_ALL_GROWSPACES_SCHEMA, 
        supports_response=SupportsResponse.ONLY
    )

    # 3. Strain Recommendation (New)
    async def strain_rec_wrapper(
        call: ServiceCall, _handler=ai_assistant.handle_strain_recommendation
    ):
         return await _handler(hass, coordinator, strain_library_instance, call)

    hass.services.async_register(
        DOMAIN, 
        "strain_recommendation", 
        strain_rec_wrapper, 
        schema=STRAIN_RECOMMENDATION_SCHEMA, 
        supports_response=SupportsResponse.ONLY
    )

    _LOGGER.debug("Registered AI services: ask_grow_advice, analyze_all_growspaces, strain_recommendation")

    # Register the standalone 'get_strain_library' service
    async def get_strain_library_wrapper(
        call: ServiceCall, _handler=strain_library_services.handle_get_strain_library
    ):
        await _handler(hass, coordinator, strain_library_instance, call)

    hass.services.async_register(
        DOMAIN, "get_strain_library", get_strain_library_wrapper
    )
    _LOGGER.debug("Registered service: get_strain_library")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry %s for Growspace Manager", entry.entry_id)

    # Clean up dynamically created entities before unloading platforms
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})

    # Cancel irrigation listeners
    if "irrigation_coordinators" in entry_data:
        for coordinator in entry_data["irrigation_coordinators"].values():
            coordinator.async_cancel_listeners()

    created_unique_ids = entry_data.get("created_entities", [])
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

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug("Removed coordinator for entry %s", entry.entry_id)

        # Cleanup global resources if this is the last entry for the domain
        if DOMAIN in hass.data and not hass.data[DOMAIN]:
            hass.data[DOMAIN].pop("strain_library", None)
            hass.data.pop(DOMAIN)
            _LOGGER.debug(
                "Removed global strain_library and domain data as no entries remain."
            )

        # Remove all registered services
        service_names_to_remove = [
            "add_growspace",
            "remove_growspace",
            "add_plant",
            "update_plant",
            "remove_plant",
            "move_plant",
            "switch_plants",
            "transition_plant_stage",
            "take_clone",
            "move_clone",
            "harvest_plant",
            "export_strain_library",
            "import_strain_library",
            "clear_strain_library",
            "add_strain",
            "update_strain_meta",
            "test_notification",
            "debug_cleanup_legacy",
            "debug_list_growspaces",
            "debug_reset_special_growspaces",
            "debug_con",
            "get_strain_library",
            "configure_environment",
            "remove_environment",
            "ask_grow_advice",
        ]

        for service_name in service_names_to_remove:
            if hass.services.has_service(DOMAIN, service_name):
                hass.services.async_remove(DOMAIN, service_name)
                _LOGGER.debug("Removed service: %s", service_name)

        _LOGGER.info("Unloaded Growspace Manager for entry %s", entry.entry_id)
        return True
    else:
        _LOGGER.error("Failed to unload platforms for entry %s", entry.entry_id)
        return False


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

    def __init__(self, hass: HomeAssistant, strain_library: StrainLibrary) -> None:
        """Initialize the view."""
        self.hass = hass
        self.strain_library = strain_library

    async def post(self, request: web.Request) -> web.Response:
        """Handle the POST request for file upload."""
        # 1. Read the multipart data (file)
        reader = await request.multipart()
        file_field = await reader.next()

        if not file_field or file_field.name != "file":
            return web.Response(status=400, text="No file provided")

        # 2. Save to temp file
        # (Use a scalable chunk write to avoid memory issues)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            temp_path = tmp.name
            while True:
                chunk = await file_field.read_chunk()
                if not chunk:
                    break
                tmp.write(chunk)

        try:
            # 3. Process Import
            count = await self.strain_library.import_library_from_zip(
                temp_path, merge=True
            )
            await self.strain_library.save()
            return self.json({"success": True, "imported_count": count})

        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception("Error processing strain library upload")
            return self.json({"success": False, "error": str(err)})

        finally:
            # Cleanup
            if os.path.exists(temp_path):
                os.remove(temp_path)
