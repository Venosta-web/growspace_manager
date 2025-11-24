"""Services related to Strain Library."""

import base64
import logging
import os
import tempfile
from typing import Any

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

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
    try:
        output_dir = hass.config.path("www", "growspace_manager", "exports")

        zip_path = await strain_library.export_library_to_zip(output_dir)

        # Calculate web accessible path
        # /config/www/ maps to /local/
        relative_path = zip_path.replace(hass.config.path("www"), "/local")

        _LOGGER.info("Exported strain library to %s (web: %s)", zip_path, relative_path)

        await coordinator.async_save()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_exported",
            {
                "file_path": zip_path,
                "url": relative_path,
                "strains_count": len(strain_library.get_all())
            }
        )

        create_notification(
            hass,
            f"Strain library exported successfully.\nPath: {zip_path}",
            title="Strain Library Export",
        )

    except Exception as err:
        _LOGGER.exception("Failed to export strain library: %s", err)
        create_notification(
            hass,
            f"Failed to export strain library: {str(err)}",
            title="Growspace Manager Error",
        )
        raise


async def handle_import_strain_library(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle import strain library service call."""
    file_path = call.data.get("file_path")
    zip_base64 = call.data.get("zip_base64")

    # 'replace' argument in service call: True means overwrite.
    # 'merge' argument in library method: True means merge.
    # So merge = not replace.
    replace_existing = call.data.get("replace", False)
    merge_data = not replace_existing

    temp_file_path = None

    # 1. Handle Base64 Upload (Frontend)
    if zip_base64:
        try:
            # Strip Data URI header if present (e.g., "data:application/zip;base64,...")
            if "," in zip_base64:
                _, zip_base64 = zip_base64.split(",", 1)

            file_data = base64.b64decode(zip_base64)

            # Create a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                tmp.write(file_data)
                temp_file_path = tmp.name
                file_path = tmp.name  # Use this temp path for import

        except Exception as err:
            _LOGGER.error("Failed to process uploaded zip file: %s", err)
            create_notification(
                hass, "Failed to process uploaded file.", title="Import Error"
            )
            return

    # 2. Validate we have a path (either from arg or temp file)
    if not file_path:
        _LOGGER.warning("No file path or base64 data provided for import.")
        return

    try:
        strains_count = await strain_library.import_library_from_zip(
            zip_path=file_path,
            merge=merge_data,
        )

        # Save the updated library to storage
        await strain_library.save()

        _LOGGER.info(
            "Imported strain library from %s. Total strains: %d", file_path, strains_count
        )

        await coordinator.async_request_refresh()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_imported",
            {"strains_count": strains_count, "merged": merge_data},
        )

        create_notification(
            hass,
            f"Strain library imported successfully.\nTotal Strains: {strains_count}",
            title="Strain Library Import",
        )

    except Exception as err:
        _LOGGER.exception("Failed to import strain library: %s", err)
        create_notification(
            hass,
            f"Failed to import strain library: {str(err)}",
            title="Growspace Manager Error",
        )
        raise

    finally:
        # 3. Cleanup Temporary File
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError as e:
                _LOGGER.warning("Could not remove temp file %s: %s", temp_file_path, e)


async def handle_add_strain(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the add_strain service call."""
    strain = call.data.get("strain")
    phenotype = call.data.get("phenotype")
    breeder = call.data.get("breeder")
    strain_type = call.data.get("type")
    lineage = call.data.get("lineage")
    sex = call.data.get("sex")
    flower_days_min = call.data.get("flower_days_min")
    if flower_days_min is None:
        flower_days_min = call.data.get("flowering_days_min")

    flower_days_max = call.data.get("flower_days_max")
    if flower_days_max is None:
        flower_days_max = call.data.get("flowering_days_max")

    description = call.data.get("description")

    image_base64 = call.data.get("image_base64")
    if not image_base64:
        image_base64 = call.data.get("image")

    image_path = call.data.get("image_path")
    image_crop_meta = call.data.get("image_crop_meta")
    sativa_percentage = call.data.get("sativa_percentage")
    indica_percentage = call.data.get("indica_percentage")

    try:
        await strain_library.add_strain(
            strain=strain,
            phenotype=phenotype,
            breeder=breeder,
            strain_type=strain_type,
            lineage=lineage,
            sex=sex,
            flower_days_min=flower_days_min,
            flower_days_max=flower_days_max,
            description=description,
            image_base64=image_base64,
            image_path=image_path,
            image_crop_meta=image_crop_meta,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

    await coordinator.async_request_refresh()


async def handle_update_strain_meta(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the update_strain_meta service call."""
    strain = call.data.get("strain")
    phenotype = call.data.get("phenotype")
    breeder = call.data.get("breeder")
    strain_type = call.data.get("type")
    lineage = call.data.get("lineage")
    sex = call.data.get("sex")
    flower_days_min = call.data.get("flower_days_min")
    if flower_days_min is None:
        flower_days_min = call.data.get("flowering_days_min")

    flower_days_max = call.data.get("flower_days_max")
    if flower_days_max is None:
        flower_days_max = call.data.get("flowering_days_max")

    description = call.data.get("description")

    image_base64 = call.data.get("image_base64")
    if not image_base64:
        image_base64 = call.data.get("image")

    image_path = call.data.get("image_path")
    image_crop_meta = call.data.get("image_crop_meta")
    sativa_percentage = call.data.get("sativa_percentage")
    indica_percentage = call.data.get("indica_percentage")

    try:
        await strain_library.set_strain_meta(
            strain=strain,
            phenotype=phenotype,
            breeder=breeder,
            strain_type=strain_type,
            lineage=lineage,
            sex=sex,
            flower_days_min=flower_days_min,
            flower_days_max=flower_days_max,
            description=description,
            image_base64=image_base64,
            image_path=image_path,
            image_crop_meta=image_crop_meta,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
        )
    except ValueError as err:
        raise HomeAssistantError(str(err)) from err

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
