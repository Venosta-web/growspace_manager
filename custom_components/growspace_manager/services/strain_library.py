"""Services related to Strain Library."""

from __future__ import annotations

import base64
import binascii
from io import BytesIO
import logging
from pathlib import Path
import tempfile
from typing import TYPE_CHECKING, Any

from PIL import Image

from custom_components.growspace_manager.const import (
    ATTR_BREEDER,
    ATTR_BREEDER_LOGO,
    ATTR_LINEAGE,
    ATTR_PHENOTYPE,
    ATTR_STRAIN,
    DOMAIN,
    GrowspaceService,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.schemas import (
    ADD_STRAIN_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    PRINT_LABEL_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.network import get_url
from homeassistant.util import dt as dt_util

from ._definition import ServiceDefinition

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

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


def _downscale_logo_if_needed(logo_data: str | None) -> str | None:
    """Downscale breeder logo if it's a large base64 string or return as is.

    This prevents hitting the 32KB Home Assistant event bus limit and
    possible printer buffer issues.
    """
    if not logo_data or not logo_data.startswith("data:image/"):
        return logo_data

    # If the string is already small enough, skip processing
    if len(logo_data) < 25000:
        return logo_data

    try:
        # Extract base64 part
        _, encoded = logo_data.split(",", 1)
        image_data = base64.b64decode(encoded)

        # Load image
        img = Image.open(BytesIO(image_data))

        # Size constraint for Niimbot print label (100x100)
        img.thumbnail((100, 100))

        # Save back to base64 as PNG (Niimbot handles data URIs)
        output = BytesIO()
        img.save(output, format="PNG", optimize=True)
        new_encoded = base64.b64encode(output.getvalue()).decode("utf-8")
        result = f"data:image/png;base64,{new_encoded}"

        # If it's still large due to complexity, convert to 1-bit monochrome
        if len(result) >= 25000:
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background

            img = img.convert("1")
            output = BytesIO()
            img.save(output, format="PNG", optimize=True)
            new_encoded = base64.b64encode(output.getvalue()).decode("utf-8")
            result = f"data:image/png;base64,{new_encoded}"

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.warning("Failed to downscale breeder logo: %s", err)
        return logo_data
    else:
        return result


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

        await coordinator.services.save()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_exported",
            {
                "file_path": zip_path,
                "url": relative_path,
                "strains_count": len(strain_library.get_all()),
            },
        )

        create_notification(
            hass,
            f"Strain library exported successfully.\nPath: {zip_path}",
            title="Strain Library Export",
        )

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as err:
        _LOGGER.exception("Failed to export strain library")
        create_notification(
            hass,
            f"Failed to export strain library: {err!s}",
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

        except (binascii.Error, OSError):
            _LOGGER.exception("Failed to process uploaded zip file")
            create_notification(
                hass, "Failed to process uploaded file.", title="Import Error"
            )
            return

    # 2. Validate we have a path (either from arg or temp file)
    if not file_path:
        _LOGGER.warning("No file path or base64 data provided for import")
        return

    try:
        strains_count = await strain_library.import_library_from_zip(
            zip_path=file_path,
            merge=merge_data,
        )

        # Save the updated library to storage
        await strain_library.save()

        _LOGGER.info(
            "Imported strain library from %s. Total strains: %d",
            file_path,
            strains_count,
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

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as err:
        _LOGGER.exception("Failed to import strain library")
        create_notification(
            hass,
            f"Failed to import strain library: {err!s}",
            title="Growspace Manager Error",
        )
        raise

    finally:
        # 3. Cleanup Temporary File
        if temp_file_path and Path(temp_file_path).exists():
            try:
                Path(temp_file_path).unlink()
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
    images = call.data.get("images")
    sativa_percentage = call.data.get("sativa_percentage")
    indica_percentage = call.data.get("indica_percentage")
    breeder_logo = call.data.get("breeder_logo")

    if not strain:
        _LOGGER.warning("Service call add_strain missing required 'strain' parameter")
        return

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
            images=images,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
            breeder_logo=breeder_logo,
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
    images = call.data.get("images")
    sativa_percentage = call.data.get("sativa_percentage")
    indica_percentage = call.data.get("indica_percentage")
    breeder_logo = call.data.get("breeder_logo")

    yield_potential = call.data.get("yield_potential")
    height = call.data.get("height")
    thc = call.data.get("thc")
    awards = call.data.get("awards")
    cbd = call.data.get("cbd")
    cbg = call.data.get("cbg")
    lineage_tree = call.data.get("lineage_tree")

    if not strain:
        _LOGGER.warning(
            "Service call update_strain_meta missing required 'strain' parameter"
        )
        return

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
            images=images,
            sativa_percentage=sativa_percentage,
            indica_percentage=indica_percentage,
            breeder_logo=breeder_logo,
            yield_potential=yield_potential,
            height=height,
            thc=thc,
            cbd=cbd,
            cbg=cbg,
            awards=awards,
            lineage_tree=lineage_tree,
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

    if not strain:
        _LOGGER.warning(
            "Service call remove_strain missing required 'strain' parameter"
        )
        return

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
        await coordinator.services.save()
        await coordinator.services.request_refresh()

        hass.bus.async_fire(
            f"{DOMAIN}_strain_library_cleared", {"cleared_count": cleared_count}
        )
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,
    ) as err:
        _LOGGER.exception("Failed to clear strain library")
        create_notification(
            hass,
            f"Failed to clear strain library: {err!s}",
            title="Growspace Manager Error",
        )
        raise


async def handle_print_label(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the print_label service call."""
    plant_id = call.data.get("plant_id")
    device_id = call.data.get("device_id")
    preview = call.data.get("preview", False)

    strain_name = None
    phenotype_name = None
    breeder = None
    lineage = None
    breeder_logo = None

    if plant_id:
        plant = coordinator.plants.get(plant_id)
        if not plant:
            raise HomeAssistantError(f"Plant {plant_id} not found")

        strain_name = plant.genetics.strain_name
        phenotype_name = plant.genetics.phenotype_name or "default"
    else:
        strain_name = call.data.get(ATTR_STRAIN)
        phenotype_name = call.data.get(ATTR_PHENOTYPE) or "default"
        breeder = call.data.get(ATTR_BREEDER)
        lineage = call.data.get(ATTR_LINEAGE)
        breeder_logo = call.data.get(ATTR_BREEDER_LOGO)

    base_url = call.data.get("base_url")
    fields: dict[str, bool] = call.data.get("fields") or {}
    density_key: str = call.data.get("density", "normal")
    qr_target: str = call.data.get("qr_target", "web")

    if not strain_name:
        raise HomeAssistantError(
            "Neither plant_id nor strain name provided for label printing"
        )

    if phenotype_name == "default":
        phenotype_name = "-"

    # Ensure library is loaded to get meta if not provided or to augment plant data
    await strain_library.load()
    library_data = strain_library.get_all()
    strain_meta = library_data.get(strain_name, {}).get("meta", {})

    # Use provided values or fall back to library meta
    breeder = breeder or strain_meta.get(ATTR_BREEDER, "-")
    lineage = lineage or strain_meta.get(ATTR_LINEAGE, "-")
    breeder_logo = breeder_logo or strain_meta.get(ATTR_BREEDER_LOGO)

    # Construct Niimbot payload based on the "Perfect Label" mockup
    payload = []

    # 1. Main Header: Strain Name (Large and Bold)
    payload.append(
        {
            "type": "new_multiline",
            "value": strain_name.upper(),
            "x": 0,
            "y": 20,
            "x_end": 260,
            "size": 50,
            "width": 250,
            "height": 50,
            "fit": True,
            "font": "ppb.ttf",
        }
    )

    # 2. Horizontal Divider Line (under header)
    payload.append(
        {
            "type": "rectangle",
            "x_start": 0,
            "x_end": 260,
            "y_start": 85,
            "y_end": 88,
            "fill": "black",
        }
    )

    # 3. Multiline Info (Pheno, Breeder, Lineage) — each line respects its field flag
    info_lines = []
    if fields.get("phenotype", True) and phenotype_name and phenotype_name not in ("-", "–"):
        info_lines.append(phenotype_name)
    if fields.get("breeder", True) and breeder and breeder not in ("-", "–"):
        info_lines.append(breeder)
    if fields.get("lineage", True) and lineage and lineage not in ("-", "–"):
        info_lines.append(lineage)
    multiline_value = "\n".join(info_lines)
    payload.append(
        {
            "type": "new_multiline",
            "x": 0,
            "y": 100,
            "x_end": 260,
            "size": 40,
            "width": 250,
            "height": 100,
            "fit": True,
            "font": "rbm.ttf",
            "value": multiline_value,
        }
    )

    # 4. Breeder Logo (Framed)
    if breeder_logo and fields.get("logo", True):
        # Downscale if it's a base64 string to avoid event bus and printer issues.
        # Run in executor to avoid blocking the event loop on PIL's lazy native lib init.
        breeder_logo = await hass.async_add_executor_job(
            _downscale_logo_if_needed, breeder_logo
        )

        payload.append(
            {
                "type": "dlimg",
                "url": breeder_logo,
                "x": 290,
                "y": 20,
                "xsize": 100,
                "ysize": 100,
            }
        )

    # 5. QR Code — only if plant_id is present and field is enabled
    if plant_id and fields.get("qr", True):
        if qr_target == "deeplink":
            qr_data = f"homeassistant://navigate/growspace/plant/{plant_id}"
        elif base_url:
            qr_data = f"{base_url}?plantId={plant_id}"
        else:
            qr_data = f"{get_url(hass)}/plant/{plant_id}"
        payload.append(
            {
                "type": "qrcode",
                "data": qr_data,
                "x": 290,
                "y": 130,
                "boxsize": 3,
            }
        )

    # 6. Small Timestamp (Bottom Right)
    now = dt_util.now().strftime("%d.%m.%Y")
    payload.append(
        {
            "type": "text",
            "value": now,
            "x": 290,
            "y": 224,
            "size": 6,
            "font": "rbm.ttf",
        }
    )
    _density_map = {"low": 3, "normal": 5, "high": 8}
    niimbot_density = _density_map.get(density_key, 5)

    # Call Niimbot service
    service_data = {
        "width": 400,
        "height": 240,
        "rotate": 0,
        "density": niimbot_density,
        "payload": payload,
        "preview": preview,
    }
    if device_id:
        service_data["device_id"] = device_id

    try:
        response = await hass.services.async_call(
            "niimbot", "print", service_data, blocking=True, return_response=True
        )
    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
    ) as err:
        _LOGGER.error("Failed to print Niimbot label: %s", err)
        raise HomeAssistantError(f"Failed to print Niimbot label: {err}") from err
    else:
        log_id = plant_id or strain_name
        _LOGGER.info("Sent label to Niimbot for %s", log_id)
        return response


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.ADD_STRAIN,
        handle_add_strain,
        ADD_STRAIN_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_STRAIN,
        handle_remove_strain,
        REMOVE_STRAIN_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.UPDATE_STRAIN_META,
        handle_update_strain_meta,
        UPDATE_STRAIN_META_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.IMPORT_STRAIN_LIBRARY,
        handle_import_strain_library,
        IMPORT_STRAIN_LIBRARY_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.EXPORT_STRAIN_LIBRARY,
        handle_export_strain_library,
        EXPORT_STRAIN_LIBRARY_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.CLEAR_STRAIN_LIBRARY,
        handle_clear_strain_library,
        CLEAR_STRAIN_LIBRARY_SCHEMA,
        needs_strain_lib=True,
    ),
    ServiceDefinition(
        GrowspaceService.GET_STRAIN_LIBRARY,
        handle_get_strain_library,
        None,
        needs_strain_lib=True,
        supports_response=SupportsResponse.ONLY,
    ),
    ServiceDefinition(
        GrowspaceService.PRINT_LABEL,
        handle_print_label,
        PRINT_LABEL_SCHEMA,
        needs_strain_lib=True,
        supports_response=SupportsResponse.OPTIONAL,
    ),
]
