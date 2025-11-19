"""Services related to Strain Library."""

import logging
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
) -> list[str]:  # Returning list[str] as per original type hint
    """Return the list of strains."""
    # Ensure strain library is loaded; async_setup_entry should have done this, but it's safe.
    await strain_library.load()
    strains = list(strain_library.strains)

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
    # The original code called coordinator.get_strain_options().
    # Assuming strain_library.strains contains the data to be exported.
    strains_to_export = list(strain_library.strains)
    _LOGGER.info("Exporting strain library: %s strains", len(strains_to_export))

    # Save coordinator data, which might include references to strains,
    # but the strain library itself might use its own storage.
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
    strains_to_import = call.data.get("strains", [])
    replace_existing = call.data.get("replace", False)

    if not strains_to_import:
        _LOGGER.warning("No strains provided for import.")
        return

    try:
        # Convert list of strings to the expected dictionary format for import_library
        # This ensures compatibility if the StrainLibrary class definition hasn't updated yet.
        library_data = {
            strain.strip() + "|": {"harvests": []} for strain in strains_to_import
        }
        
        # Note: The key format in StrainLibrary._get_key is f"{strain.strip()}|{phenotype.strip() or 'default'}"
        # Since we don't have phenotypes here, we might need to be careful.
        # Let's check how import_strains implemented it:
        # self._get_key(strain, "") -> strain|default (if empty phenotype becomes default?)
        # Let's look at _get_key again.
        
        # Re-reading _get_key from previous view_file:
        # return f"{strain.strip()}|{phenotype.strip() or 'default'}"
        
        # So if phenotype is empty string "", it becomes "default".
        # So key is "StrainName|default".
        
        library_data = {
            f"{strain.strip()}|default": {"harvests": []} for strain in strains_to_import
        }

        added_count = await strain_library.import_library(
            library_data=library_data,
            replace=replace_existing,
        )
        _LOGGER.info(
            "Imported %s strains to library (replace=%s)", added_count, replace_existing
        )

        await coordinator.async_save()  # Save coordinator data
        await (
            coordinator.async_request_refresh()
        )  # Refresh entities if strain data affects them

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
    await coordinator.async_add_strain(strain, phenotype)


async def handle_clear_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle clear strain library service call."""
    # The original code had `StrainLibrary.clear(self)`.
    # Assuming `clear_strains` is an instance method on `StrainLibrary` that returns the count cleared.
    # If `StrainLibrary.clear` was a static/class method, the call would be `StrainLibrary.clear(strain_library)`.
    try:
        # Assuming StrainLibrary has an instance method to clear its strains.
        # If not, you might need to adapt this based on its actual API.
        cleared_count = await strain_library.clear()

        _LOGGER.info("Cleared %s strains from library", cleared_count)
        await coordinator.async_save()
        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_cleared", {"cleared_count": cleared_count}
        )
    except AttributeError:
        _LOGGER.error(
            "StrainLibrary instance does not have a 'clear' method. Please verify the method name."
        )
        create_notification(
            hass,
            "Error clearing strain library: Method not found.",
            title="Growspace Manager Error",
        )
        raise
    except Exception as err:
        _LOGGER.exception("Failed to clear strain library: %s", err)
        create_notification(
            hass,
            f"Failed to clear strain library: {str(err)}",
            title="Growspace Manager Error",
        )
        raise
