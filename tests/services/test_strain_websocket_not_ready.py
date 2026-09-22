"""What the strain WebSocket handlers do before the integration is ready.

Every one of these commands reaches for something the coordinator builds
during setup — the Strain Library, or the Seedfinder scraper — and either can
still be `None`. A card subscribes as soon as the connection is up, so this is
not a defensive branch: it is the ordinary race between a browser that is
already open and a config entry that is still loading, and it happens again on
every reload.

What matters is that each handler says *which* thing is not ready, as a
`CoordinatorNotReadyError` the WebSocket layer turns into a typed error the
card can retry on — rather than an `AttributeError` on `None`, which reaches
the browser as an unrecognisable "unknown error" and gives it nothing to
decide with.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import CONF_BLACKLIST_BREEDERS
from custom_components.growspace_manager.exceptions import CoordinatorNotReadyError
from custom_components.growspace_manager.websocket.strain import (
    websocket_download_strain_image,
    websocket_get_external_strain_details,
    websocket_get_strain_library,
    websocket_query_external_strain,
    websocket_upload_strain_image,
)


async def _call(handler: Any, hass: Any, coordinator: Any, msg: Any) -> Any:
    """Invoke one handler, whether it happens to be a coroutine or not.

    `get_strain_library` reads state already in memory and is synchronous;
    the rest do I/O. That difference is invisible to the WebSocket layer,
    which awaits whatever a handler hands back, and it should be invisible
    here too — otherwise the table below would need two shapes for one claim.
    """
    result = handler(hass, coordinator, msg)
    return await result if inspect.isawaitable(result) else result


def _coordinator(
    *, strain_library: Any = None, scraper: Any = None, options: Any = None
) -> MagicMock:
    """A coordinator with exactly the parts a test wants present."""
    coordinator = MagicMock()
    coordinator.services.config.strain_library = strain_library
    coordinator.seedfinder_scraper = scraper
    coordinator.config_entry.options = options if options is not None else {}
    return coordinator


#: Every handler that needs the Strain Library, with the payload it takes.
#: Parametrized rather than written out, because the property is that *none*
#: of them dereferences a library that is not there.
_LIBRARY_COMMANDS: dict[str, tuple[Any, dict[str, Any]]] = {
    "get_strain_library": (websocket_get_strain_library, {}),
    "upload_strain_image": (
        websocket_upload_strain_image,
        {"strain": "Test", "phenotype": "Keeper", "image_base64": "data:,"},
    ),
    "download_strain_image": (
        websocket_download_strain_image,
        {"url": "https://example.invalid/x.jpg", "strain": "Test", "phenotype": "K"},
    ),
}

#: And every handler that needs the scraper.
_SCRAPER_COMMANDS: dict[str, tuple[Any, dict[str, Any]]] = {
    "query_external_strain": (websocket_query_external_strain, {"query": "Gelato"}),
    "get_external_strain_details": (
        websocket_get_external_strain_details,
        {"url": "https://example.invalid/strain"},
    ),
}


@pytest.mark.parametrize(
    "command", list(_LIBRARY_COMMANDS), ids=list(_LIBRARY_COMMANDS)
)
async def test_a_command_needing_the_strain_library_says_it_is_not_ready(
    hass: Any, command: str
) -> None:
    """Named, typed and retryable — not an attribute error on `None`."""
    handler, msg = _LIBRARY_COMMANDS[command]
    coordinator = _coordinator(strain_library=None)

    with pytest.raises(CoordinatorNotReadyError, match="Strain library"):
        await _call(handler, hass, coordinator, msg)


@pytest.mark.parametrize(
    "command", list(_SCRAPER_COMMANDS), ids=list(_SCRAPER_COMMANDS)
)
async def test_a_command_needing_the_scraper_says_it_is_not_ready(
    hass: Any, command: str
) -> None:
    """The external lookups name the scraper rather than the library."""
    handler, msg = _SCRAPER_COMMANDS[command]
    coordinator = _coordinator(scraper=None)

    with pytest.raises(CoordinatorNotReadyError, match="Seedfinder scraper"):
        await handler(hass, coordinator, msg)


async def test_an_external_query_passes_the_configured_breeder_blacklist(
    hass: Any,
) -> None:
    """The blacklist is configuration, so the search has to carry it."""
    scraper = MagicMock()
    scraper.async_search_strains = AsyncMock(return_value=["a result"])
    coordinator = _coordinator(
        scraper=scraper, options={CONF_BLACKLIST_BREEDERS: ["Nobody Seeds"]}
    )

    found = await websocket_query_external_strain(
        hass, coordinator, {"query": "Gelato"}
    )

    assert found == ["a result"]
    scraper.async_search_strains.assert_awaited_once_with(
        "Gelato", blacklist=["Nobody Seeds"]
    )


async def test_an_unreadable_blacklist_searches_without_one(hass: Any) -> None:
    """A search is still worth running when the options cannot be read.

    Reached when the config entry is being torn down under the call, or has
    no options mapping at all. Filtering out breeders is a convenience, and
    failing the whole lookup to protect it would trade the feature for its
    refinement.
    """
    scraper = MagicMock()
    scraper.async_search_strains = AsyncMock(return_value=[])
    coordinator = _coordinator(scraper=scraper)
    coordinator.config_entry.options = None

    await websocket_query_external_strain(hass, coordinator, {"query": "Gelato"})

    scraper.async_search_strains.assert_awaited_once_with("Gelato", blacklist=[])
