"""Strain library WebSocket handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import CONF_BLACKLIST_BREEDERS, DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_STRAIN_LIBRARY = f"{DOMAIN}/get_strain_library"
SCHEMA_WS_GET_STRAIN_LIBRARY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_STRAIN_LIBRARY,
    }
)

WS_TYPE_QUERY_EXTERNAL_STRAIN = f"{DOMAIN}/query_external_strain"
SCHEMA_WS_QUERY_EXTERNAL_STRAIN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_QUERY_EXTERNAL_STRAIN,
        vol.Required("query"): str,
        vol.Optional("source"): str,  # Default to seedfinder
    }
)

WS_TYPE_GET_EXTERNAL_STRAIN_DETAILS = f"{DOMAIN}/get_external_strain_details"
SCHEMA_WS_GET_EXTERNAL_STRAIN_DETAILS = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_GET_EXTERNAL_STRAIN_DETAILS,
            vol.Required("url"): str,
            vol.Optional("source"): str,
        }
    )
)

WS_TYPE_UPLOAD_STRAIN_IMAGE = f"{DOMAIN}/upload_strain_image"
SCHEMA_WS_UPLOAD_STRAIN_IMAGE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPLOAD_STRAIN_IMAGE,
        vol.Required("strain"): str,
        vol.Required("phenotype"): str,
        vol.Required("image_base64"): str,
    }
)

WS_TYPE_DOWNLOAD_STRAIN_IMAGE = f"{DOMAIN}/download_strain_image"
SCHEMA_WS_DOWNLOAD_STRAIN_IMAGE = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_DOWNLOAD_STRAIN_IMAGE,
        vol.Required("url"): str,
        vol.Required("strain"): str,
        vol.Required("phenotype"): str,
    }
)


@callback
def websocket_get_strain_library(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get strain library command via WebSocket."""
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        strain_library: StrainLibrary = coordinator.services.config.strain_library
        all_strains = strain_library.get_all()
        response = {
            "strains": all_strains,
            "strain_list": list(all_strains.keys()),
        }
        connection.send_result(msg["id"], response)
    except ServiceValidationError:
        connection.send_error(
            msg["id"], "not_loaded", "Growspace Manager strain library not loaded"
        )
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_strain_library")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_upload_strain_image(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Upload a strain image to disk and return its local path."""
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        image_manager = coordinator.services.config.strain_library.image_manager
        abs_path = await image_manager.save_strain_image(
            slugify(msg["strain"]), slugify(msg["phenotype"]), msg["image_base64"]
        )
        filename = Path(abs_path).name
        local_path = f"/local/growspace_manager/strains/{filename}"
        connection.send_result(msg["id"], {"path": local_path})
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_loaded", "Strain library not loaded")
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_download_strain_image(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Download a remote image URL and save it as a local strain image."""
    import base64 as _base64  # noqa: PLC0415

    url = msg["url"]
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        image_manager = coordinator.services.config.strain_library.image_manager

        session = async_get_clientsession(hass)
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant)",
            "Accept": "image/webp,image/png,image/jpeg,*/*",
            "Referer": "https://en.seedfinder.eu/",
        }
        async with session.get(url, timeout=15, headers=headers, allow_redirects=True, max_redirects=20) as response:
            if response.status != 200:
                connection.send_error(msg["id"], "fetch_failed", f"HTTP {response.status}")
                return
            raw = await response.read()

        mime_type = response.headers.get("Content-Type", "image/jpeg")
        image_base64 = f"data:{mime_type};base64," + _base64.b64encode(raw).decode()
        abs_path = await image_manager.save_strain_image(
            slugify(msg["strain"]), slugify(msg["phenotype"]), image_base64
        )
        filename = Path(abs_path).name
        local_path = f"/local/growspace_manager/strains/{filename}"
        connection.send_result(msg["id"], {"path": local_path})
    except ServiceValidationError:
        connection.send_error(msg["id"], "not_loaded", "Strain library not loaded")
    except Exception as e:  # noqa: BLE001
        connection.send_error(msg["id"], "unknown_error", str(e))


async def websocket_query_external_strain(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Query external strain database."""
    query = msg["query"]
    coordinator = GrowspaceCoordinator.get_any(hass)
    scraper = coordinator.seedfinder_scraper

    blacklist = []
    try:
        coordinator = GrowspaceCoordinator.get_any(hass)
        blacklist = coordinator.config_entry.options.get(CONF_BLACKLIST_BREEDERS, [])
    except (AttributeError, KeyError, RuntimeError):
        _LOGGER.debug("Could not retrieve coordinator for blacklist, using empty list")

    try:
        results = await scraper.async_search_strains(query, blacklist=blacklist)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "seedfinder_unavailable", str(err))
        return
    connection.send_result(msg["id"], results)


async def websocket_get_external_strain_details(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get details for an external strain."""
    import re  # noqa: PLC0415

    url = msg["url"]
    coordinator = GrowspaceCoordinator.get_any(hass)
    scraper = coordinator.seedfinder_scraper

    try:
        raw = await scraper.async_get_strain_details(url)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "seedfinder_unavailable", str(err))
        return
    if raw is None:
        connection.send_result(msg["id"], None)
        return

    flowering_days: int | None = None
    ft = raw.get("flowering_time") or ""
    ft_match = re.search(r"(\d+)(?:\s*-\s*(\d+))?", ft)
    if ft_match:
        lo = int(ft_match.group(1))
        hi = int(ft_match.group(2)) if ft_match.group(2) else lo
        flowering_days = round((lo + hi) / 2)

    connection.send_result(
        msg["id"],
        {
            "name": raw.get("name"),
            "breeder": raw.get("breeder"),
            "type": raw.get("type"),
            "indica_percentage": (raw.get("composition") or {}).get("indica"),
            "sativa_percentage": (raw.get("composition") or {}).get("sativa"),
            "flowering_days": flowering_days,
            "description": raw.get("description"),
            "images": raw.get("images", []),
            "yield_potential": raw.get("yield_potential"),
            "height": raw.get("height"),
            "thc": raw.get("thc"),
            "cbd": raw.get("cbd"),
            "cbg": raw.get("cbg"),
            "awards": raw.get("awards"),
            "parents": raw.get("lineage_tree") or None,
            "lineage_str": raw.get("lineage_str"),
            "effects": raw.get("effects"),
            "aroma": raw.get("aroma"),
            "taste": raw.get("taste"),
        },
    )


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_STRAIN_LIBRARY, websocket_get_strain_library, SCHEMA_WS_GET_STRAIN_LIBRARY, True),
    (WS_TYPE_UPLOAD_STRAIN_IMAGE, websocket_upload_strain_image, SCHEMA_WS_UPLOAD_STRAIN_IMAGE, False),
    (WS_TYPE_DOWNLOAD_STRAIN_IMAGE, websocket_download_strain_image, SCHEMA_WS_DOWNLOAD_STRAIN_IMAGE, False),
    (WS_TYPE_QUERY_EXTERNAL_STRAIN, websocket_query_external_strain, SCHEMA_WS_QUERY_EXTERNAL_STRAIN, False),
    (WS_TYPE_GET_EXTERNAL_STRAIN_DETAILS, websocket_get_external_strain_details, SCHEMA_WS_GET_EXTERNAL_STRAIN_DETAILS, False),
]
