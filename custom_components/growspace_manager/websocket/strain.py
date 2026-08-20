"""Strain library WebSocket handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import ClientTimeout
import voluptuous as vol

from custom_components.growspace_manager.const import CONF_BLACKLIST_BREEDERS, DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    GrowspaceError,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from ._common import WSCommand

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


def websocket_get_strain_library(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle get strain library command via WebSocket."""
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    all_strains = strain_library.get_all()
    return {
        "strains": all_strains,
        "strain_list": list(all_strains.keys()),
    }


async def websocket_upload_strain_image(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Upload a strain image to disk and return its local path."""
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    image_manager = strain_library.image_manager
    abs_path = await image_manager.save_strain_image(
        slugify(msg["strain"]), slugify(msg["phenotype"]), msg["image_base64"]
    )
    filename = Path(abs_path).name
    return {"path": f"/local/growspace_manager/strains/{filename}"}


async def websocket_download_strain_image(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Download a remote image URL and save it as a local strain image."""
    import base64 as _base64  # noqa: PLC0415

    url = msg["url"]
    strain_library = coordinator.services.config.strain_library
    if strain_library is None:
        raise CoordinatorNotReadyError("Strain library not initialized")
    image_manager = strain_library.image_manager

    session = async_get_clientsession(hass)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant)",
        "Accept": "image/webp,image/png,image/jpeg,*/*",
        "Referer": "https://en.seedfinder.eu/",
    }
    async with session.get(
        url,
        timeout=ClientTimeout(total=15),
        headers=headers,
        allow_redirects=True,
        max_redirects=20,
    ) as response:
        if response.status != 200:
            raise GrowspaceError(f"Image download failed: HTTP {response.status}")
        raw = await response.read()

    mime_type = response.headers.get("Content-Type", "image/jpeg")
    image_base64 = f"data:{mime_type};base64," + _base64.b64encode(raw).decode()
    abs_path = await image_manager.save_strain_image(
        slugify(msg["strain"]), slugify(msg["phenotype"]), image_base64
    )
    filename = Path(abs_path).name
    return {"path": f"/local/growspace_manager/strains/{filename}"}


async def websocket_query_external_strain(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> Any:
    """Query external strain database."""
    scraper = coordinator.seedfinder_scraper
    if scraper is None:
        raise CoordinatorNotReadyError("Seedfinder scraper not initialized")

    blacklist = []
    try:
        blacklist = coordinator.config_entry.options.get(CONF_BLACKLIST_BREEDERS, [])
    except AttributeError, KeyError, RuntimeError:
        _LOGGER.debug("Could not retrieve blacklist, using empty list")

    return await scraper.async_search_strains(msg["query"], blacklist=blacklist)


async def websocket_get_external_strain_details(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any] | None:
    """Get details for an external strain."""
    import re  # noqa: PLC0415

    scraper = coordinator.seedfinder_scraper
    if scraper is None:
        raise CoordinatorNotReadyError("Seedfinder scraper not initialized")

    raw = await scraper.async_get_strain_details(msg["url"])
    if raw is None:
        return None

    flowering_days: int | None = None
    ft = raw.get("flowering_time") or ""
    ft_match = re.search(r"(\d+)(?:\s*-\s*(\d+))?", ft)
    if ft_match:
        lo = int(ft_match.group(1))
        hi = int(ft_match.group(2)) if ft_match.group(2) else lo
        flowering_days = round((lo + hi) / 2)

    return {
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
    }


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_STRAIN_LIBRARY,
        websocket_get_strain_library,
        SCHEMA_WS_GET_STRAIN_LIBRARY,
        resolve="any",
        sync=True,
    ),
    WSCommand(
        WS_TYPE_UPLOAD_STRAIN_IMAGE,
        websocket_upload_strain_image,
        SCHEMA_WS_UPLOAD_STRAIN_IMAGE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_DOWNLOAD_STRAIN_IMAGE,
        websocket_download_strain_image,
        SCHEMA_WS_DOWNLOAD_STRAIN_IMAGE,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_QUERY_EXTERNAL_STRAIN,
        websocket_query_external_strain,
        SCHEMA_WS_QUERY_EXTERNAL_STRAIN,
        resolve="any",
    ),
    WSCommand(
        WS_TYPE_GET_EXTERNAL_STRAIN_DETAILS,
        websocket_get_external_strain_details,
        SCHEMA_WS_GET_EXTERNAL_STRAIN_DETAILS,
        resolve="any",
    ),
]
