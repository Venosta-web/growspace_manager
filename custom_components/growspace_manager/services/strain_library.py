"""Services related to Strain Library."""

import logging
from typing import Any
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def handle_get_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any]:
    """Return the full strain library hierarchy."""
    # Ensure strain library is loaded
    await strain_library.load()
    strains = strain_library.get_all()

    # Fire an event with the result
    hass.bus.async_fire(f"{DOMAIN}_strain_library_fetched", {"strains": strains})
    _LOGGER.debug("Fetched strain library: %d strains", len(strains))
    return strains


async def handle_export_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle export strain library service call."""
    strains_to_export = strain_library.get_all()
    _LOGGER.info("Exporting strain library with %d strains", len(strains_to_export))

    await coordinator.async_save()
    await coordinator.async_request_refresh()

    hass.bus.async_fire(
        f"{DOMAIN}_strain_library_exported", {"strains": strains_to_export}
    )


async def handle_import_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle import strain library service call."""
    strains_input = call.data.get("strains")
    replace_existing = call.data.get("replace", False)

    if not strains_input:
        _LOGGER.warning("No data provided for import.")
        return

    try:
        added_count = 0
        if isinstance(strains_input, dict):
            # New hierarchical format
            added_count = await strain_library.import_library(
                library_data=strains_input,
                replace=replace_existing,
            )
        elif isinstance(strains_input, list):
            # List of strain names (creates default structure)
            added_count = await strain_library.import_strains(
                strains=strains_input,
                replace=replace_existing,
            )
        else:
            raise ValueError("Invalid format for 'strains'. Must be a dictionary or list.")

        _LOGGER.info(
            "Imported strains to library (count=%s, replace=%s)", added_count, replace_existing
        )

        await coordinator.async_save()
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_imported",
            {"added_count": added_count, "replace": replace_existing},
        )
    except Exception as err:
        _LOGGER.exception("Failed to import strain library: %s", err)
        create_notification(
            hass,
            f"Failed to import strain library: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_add_strain(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the add_strain service call."""
    strain = call.data.get("strain")
    phenotype = call.data.get("phenotype")
    await strain_library.add_strain(strain, phenotype)
    await coordinator.async_request_refresh()


async def handle_update_strain_meta(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the update_strain_meta service call."""
    strain = call.data.get("strain")
    breeder = call.data.get("breeder")
    strain_type = call.data.get("type")

    await strain_library.set_strain_meta(strain, breeder, strain_type)
    await coordinator.async_request_refresh()


async def handle_remove_strain(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the remove_strain service call."""
    strain = call.data.get("strain")
    phenotype = call.data.get("phenotype")

    if phenotype:
        await strain_library.remove_strain_phenotype(strain, phenotype)
    else:
        # If no phenotype specified, remove the entire strain
        await strain_library.remove_strain(strain)

    await coordinator.async_request_refresh()


async def handle_clear_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle clear strain library service call."""
    try:
        cleared_count = await strain_library.clear()

        _LOGGER.info("Cleared %s strains from library", cleared_count)
        await coordinator.async_save()
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_cleared", {"cleared_count": cleared_count}
        )
    except Exception as err:
        _LOGGER.exception("Failed to clear strain library: %s", err)
        create_notification(
            hass,
            f"Failed to clear strain library: {str(err)}",
            title="Growspace Manager Error",
        )
        raise
