"""Growspace Manager integration."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any

from homeassistant.components import panel_custom
from homeassistant.components.frontend import (
    async_remove_panel as frontend_async_remove_panel,
)
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from . import service_registration
from .const import CONF_SHOW_SIDEBAR, DOMAIN, PLATFORMS, STORAGE_KEY, STORAGE_VERSION
from .coordinator import GrowspaceCoordinator
from .coordinator_builder import CoordinatorBuilder
from .exhaust_migration import evaluate_exhaust_migration_issues
from .intent import async_setup_intents
from .services.seedfinder_scraper import SeedfinderScraper
from .strain_library import StrainLibrary
from .views import StrainLibraryImageView, StrainLibraryUploadView
from .websocket import async_register_websocket_api

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_LOGGER = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover
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

        # Initialize Seedfinder Scraper
        hass.data[DOMAIN]["seedfinder_scraper"] = SeedfinderScraper(hass)

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

    # Retrieve global Strain Library and Scraper
    strain_library_instance = hass.data[DOMAIN]["strain_library"]
    scraper_instance = hass.data[DOMAIN]["seedfinder_scraper"]

    # Use builder to create coordinator with all dependencies
    builder = CoordinatorBuilder(hass, entry)
    coordinator = builder.build(
        data=data,
        options=dict(entry.options),
        strain_library=strain_library_instance,
        seedfinder_scraper=scraper_instance,
    )
    await coordinator.async_load()  # Load data into the coordinator

    entry.runtime_data = coordinator

    # Initialize sub-coordinators
    await coordinator.async_initialize_sub_coordinators(entry)

    # Register/Unregister Sidebar Panel
    await async_register_sidebar_panel(hass, entry)

    # One-time ADR-0026 cleanup: per-growspace environment blobs in options are
    # legacy — the growspace store is the single source of truth, and any blob
    # worth keeping was adopted during coordinator load. Strip them before the
    # update listener is registered so this options write cannot trigger a
    # reload.
    stale_blob_ids = [gid for gid in coordinator.growspaces if gid in entry.options]
    if stale_blob_ids:
        new_options = {
            k: v for k, v in entry.options.items() if k not in stale_blob_ids
        }
        hass.config_entries.async_update_entry(entry, options=new_options)
        _LOGGER.info(
            "Removed %d legacy per-growspace environment blob(s) from config entry options",
            len(stale_blob_ids),
        )

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Handle pending growspace if initiated before entry setup completion
    pending = entry.data.get("pending_growspace")
    if pending:
        try:
            await coordinator.services.growspaces.add_growspace(
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

        except KeyError, RuntimeError:
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

    # Raise/clear the exhaust-fan sole-ownership migration repair (ADR-0019)
    evaluate_exhaust_migration_issues(hass, coordinator)

    entry.async_on_unload(lambda: _async_cancel_coordinators(entry.runtime_data))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.debug(
        "Reloading Growspace Manager integration for entry %s", entry.entry_id
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_register_sidebar_panel(
    hass: HomeAssistant, entry: GrowspaceConfigEntry
) -> None:
    """Register or unregister the sidebar panel based on options."""
    show_sidebar = entry.options.get(CONF_SHOW_SIDEBAR, True)

    # Remove existing panel first to avoid "Overwriting panel" error
    if DOMAIN in hass.data.get("frontend_panels", {}):
        _LOGGER.debug("Removing existing Growspace Manager sidebar panel")
        frontend_async_remove_panel(hass, DOMAIN)

    if show_sidebar:
        _LOGGER.debug("Registering Growspace Manager sidebar panel")
        await panel_custom.async_register_panel(
            hass=hass,
            frontend_url_path=DOMAIN,
            webcomponent_name="growspace-manager-redirect",
            module_url="/growspace_manager/static/redirect.js",
            sidebar_title="Growspace Manager",
            sidebar_icon="mdi:sprout",
            require_admin=True,
        )


@callback
def _async_cancel_coordinators(coordinator: GrowspaceCoordinator) -> None:
    """Cancel all sub-coordinator listeners via the subsystem manager."""
    coordinator.async_cancel_subsystems()


@callback
def _async_remove_dynamic_entities(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """No-op for dynamic entity removal (removed per request but kept for test compatibility)."""
    return


async def _async_update_listener(
    hass: HomeAssistant, entry: GrowspaceConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: GrowspaceConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading config entry %s for Growspace Manager", entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Persist data before final unload
        try:
            await entry.runtime_data.async_shutdown()
        except Exception:
            _LOGGER.exception("Error saving data during unload")

        # Remove sidebar panel
        if DOMAIN in hass.data.get("frontend_panels", {}):
            _LOGGER.debug("Removing Growspace Manager sidebar panel during unload")
            frontend_async_remove_panel(hass, DOMAIN)

        # Clean up global Strain Library and Scraper
        if DOMAIN in hass.data:
            if "strain_library" in hass.data[DOMAIN]:
                await hass.data[DOMAIN]["strain_library"].async_close()
                del hass.data[DOMAIN]["strain_library"]
            if "seedfinder_scraper" in hass.data[DOMAIN]:
                del hass.data[DOMAIN]["seedfinder_scraper"]

        _LOGGER.info("Unloaded Growspace Manager for entry %s", entry.entry_id)
        return True

    _LOGGER.error("Failed to unload platforms for entry %s", entry.entry_id)
    return False
