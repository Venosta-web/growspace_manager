"""Growspace Manager integration."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import service_registration
from .const import DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .intent import async_setup_intents
from .strain_library import StrainLibrary
from .views import StrainLibraryImageView, StrainLibraryUploadView
from .websocket import async_register_websocket_api

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


if TYPE_CHECKING:
    from typing import TypeAlias

GrowspaceConfigEntry: TypeAlias = ConfigEntry["GrowspaceCoordinator"]  # noqa: UP040


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Growspace Manager component."""
    hass.data.setdefault(DOMAIN, {})
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

        # Register WebSocket API commands
        async_register_websocket_api(hass)

        # Register static path for assets
        static_path = pathlib.Path(__file__).parent / "static"
        if static_path.exists():
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/growspace_manager/static",
                        str(static_path),
                        cache_headers=False,
                    )
                ]
            )

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
            await coordinator._growspace_service.add_growspace(
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
        # Persist data before final unload
        try:
            await entry.runtime_data.async_shutdown()
        except Exception:
            _LOGGER.exception("Error saving data during unload")

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
