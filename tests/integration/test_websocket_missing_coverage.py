"""Tests targeting uncovered branches in websocket.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket import (
    websocket_add_growspace_note,
    websocket_add_subarea,
    websocket_download_strain_image,
    websocket_get_external_strain_details,
    websocket_get_lineage_tree,
    websocket_get_strain_lineage_tree,
    websocket_import_strain_lineage_tree,
    websocket_query_external_strain,
    websocket_remove_subarea,
    websocket_update_strain_lineage_tree,
    websocket_update_subarea,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_connection() -> MagicMock:
    """Return a mock WebSocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# Nutrient inventory ServiceValidationError paths (lines 524, 552, 575)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_add_growspace_note_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover ServiceValidationError branch in websocket_add_growspace_note."""
    msg = {"id": 7, "growspace_id": "gs1", "notes": "hello"}
    coordinator = MagicMock()
    coordinator.services.growspaces.add_growspace_note = AsyncMock(
        side_effect=ServiceValidationError("invalid growspace")
    )
    if True:
        with pytest.raises(ServiceValidationError, match=r"invalid\ growspace"):
            await websocket_add_growspace_note(hass, coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_add_growspace_note_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_add_growspace_note."""
    msg = {"id": 8, "growspace_id": "gs1", "notes": "hello"}
    coordinator = MagicMock()
    coordinator.services.growspaces.add_growspace_note = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    if True:
        with pytest.raises(Exception, match=r"boom"):
            await websocket_add_growspace_note(hass, coordinator, msg)


# ---------------------------------------------------------------------------
# Subarea error paths (lines 1432, 1447-1448, 1461-1464, 1475-1478)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_add_subarea_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_add_subarea."""
    msg = {"id": 9, "growspace_id": "gs1", "name": "Sub1"}
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.add_subarea = AsyncMock(
            side_effect=RuntimeError("fail")
        )
        with pytest.raises(Exception, match=r"fail"):
            await websocket_add_subarea(hass, mock_get.return_value, msg)


@pytest.mark.asyncio
async def test_websocket_update_subarea_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_update_subarea."""
    msg = {
        "id": 11,
        "growspace_id": "gs1",
        "subarea_id": "sub1",
        "environment_config": {},
    }
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.update_subarea = AsyncMock(
            side_effect=RuntimeError("oops")
        )
        with pytest.raises(Exception, match=r"oops"):
            await websocket_update_subarea(hass, mock_get.return_value, msg)


@pytest.mark.asyncio
async def test_websocket_remove_subarea_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_remove_subarea."""
    msg = {"id": 13, "growspace_id": "gs1", "subarea_id": "sub1"}
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.remove_subarea = AsyncMock(
            side_effect=RuntimeError("fail")
        )
        with pytest.raises(Exception, match=r"fail"):
            await websocket_remove_subarea(hass, mock_get.return_value, msg)


# ---------------------------------------------------------------------------
# websocket_get_lineage_tree error paths (lines 1497-1502, 1521-1522)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_get_lineage_tree_inner_exception(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover the inner Exception branch when genetics_manager.get_lineage_tree raises."""
    msg = {"id": 16, "plant_id": "p1"}
    mock_coordinator = MagicMock()
    mock_coordinator.plants = {"p1": MagicMock()}
    mock_coordinator.services.genetics.get_lineage_tree.side_effect = RuntimeError(
        "inner crash"
    )
    if True:
        with pytest.raises(Exception, match=r"inner\ crash"):
            await websocket_get_lineage_tree(hass, mock_coordinator, msg)


# ---------------------------------------------------------------------------
# Lineage tree generic Exception paths (lines 1561-1562, 1580-1581)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_get_strain_lineage_tree_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_get_strain_lineage_tree."""
    msg = {"id": 17, "strain_name": "OG Kush"}
    mock_coordinator = MagicMock()
    mock_coordinator._strain_library.get_strain_lineage_tree.side_effect = RuntimeError(
        "fail"
    )
    mock_coordinator.services.config.strain_library = mock_coordinator._strain_library
    if True:
        with pytest.raises(Exception, match=r"fail"):
            await websocket_get_strain_lineage_tree(hass, mock_coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_update_strain_lineage_tree_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_update_strain_lineage_tree."""
    msg = {
        "id": 18,
        "strain_name": "OG Kush",
        "parents": [{"name": "A", "source": "manual"}],
    }
    mock_coordinator = MagicMock()
    mock_coordinator._strain_library = AsyncMock()
    mock_coordinator.services.config.strain_library = mock_coordinator._strain_library
    mock_coordinator._strain_library.update_strain_lineage_tree.side_effect = (
        RuntimeError("fail")
    )
    if True:
        with pytest.raises(Exception, match=r"fail"):
            await websocket_update_strain_lineage_tree(hass, mock_coordinator, msg)


# ---------------------------------------------------------------------------
# websocket_import_strain_lineage_tree (lines 1598-1610)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_import_strain_lineage_tree_success(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover success path in websocket_import_strain_lineage_tree."""
    msg = {"id": 19, "strain_name": "Gelato", "tree": {"name": "Gelato", "parents": []}}
    mock_coordinator = MagicMock()
    mock_coordinator._strain_library = AsyncMock()
    mock_coordinator.services.config.strain_library = mock_coordinator._strain_library
    mock_coordinator._strain_library.async_import_seedfinder_lineage_tree = AsyncMock()
    if True:
        result = await websocket_import_strain_lineage_tree(hass, mock_coordinator, msg)
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_websocket_import_strain_lineage_tree_generic_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover generic Exception branch in websocket_import_strain_lineage_tree."""
    msg = {"id": 21, "strain_name": "Gelato", "tree": {}}
    mock_coordinator = MagicMock()
    mock_coordinator._strain_library = AsyncMock()
    mock_coordinator.services.config.strain_library = mock_coordinator._strain_library
    mock_coordinator._strain_library.async_import_seedfinder_lineage_tree.side_effect = RuntimeError(
        "import failed"
    )
    if True:
        with pytest.raises(Exception, match=r"import\ failed"):
            await websocket_import_strain_lineage_tree(hass, mock_coordinator, msg)


# ---------------------------------------------------------------------------
# websocket_query_external_strain (lines 1619-1632)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_query_external_strain_success(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover success path in websocket_query_external_strain."""
    msg = {"id": 22, "query": "OG Kush"}
    mock_coordinator = MagicMock()
    mock_coordinator.config_entry.options.get.return_value = ["BadBreeder"]
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_search_strains = AsyncMock(
        return_value=[{"name": "OG Kush", "breeder": "GoodBreeder"}]
    )
    if True:
        result = await websocket_query_external_strain(hass, mock_coordinator, msg)
    assert result == [{"name": "OG Kush", "breeder": "GoodBreeder"}]


@pytest.mark.asyncio
async def test_websocket_query_external_strain_blacklist_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover the blacklist retrieval error path in websocket_query_external_strain."""
    msg = {"id": 23, "query": "Gelato"}
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_search_strains = AsyncMock(
        return_value=[]
    )
    # Make the second get_any call (blacklist retrieval) raise AttributeError
    call_count = 0

    def side_effect_get_any(h: HomeAssistant) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_coordinator
        raise AttributeError("no config")

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
        side_effect=side_effect_get_any,
    ):
        result = await websocket_query_external_strain(hass, mock_coordinator, msg)
    assert result == []


@pytest.mark.asyncio
async def test_websocket_query_external_strain_service_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover ServiceValidationError branch in websocket_query_external_strain."""
    msg = {"id": 22, "query": "OG Kush"}
    mock_coordinator = MagicMock()
    mock_coordinator.config_entry.options.get.return_value = []
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_search_strains = AsyncMock(
        side_effect=ServiceValidationError("unavailable")
    )
    if True:
        with pytest.raises(ServiceValidationError, match=r"unavailable"):
            await websocket_query_external_strain(hass, mock_coordinator, msg)


# ---------------------------------------------------------------------------
# websocket_get_external_strain_details (lines 1641-1659)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_get_external_strain_details_none(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover the None raw result path in websocket_get_external_strain_details."""
    msg = {"id": 24, "url": "https://example.com/strain/og-kush"}
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_get_strain_details = AsyncMock(
        return_value=None
    )
    if True:
        result = await websocket_get_external_strain_details(
            hass, mock_coordinator, msg
        )
    assert result is None


@pytest.mark.asyncio
async def test_websocket_get_external_strain_details_with_data(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover full data path including flowering_time range parsing."""
    msg = {"id": 25, "url": "https://example.com/strain/gelato"}
    raw = {
        "name": "Gelato #41",
        "breeder": "Cookies",
        "type": "hybrid",
        "composition": {"indica": 60, "sativa": 40},
        "flowering_time": "56-63 days",
        "description": "Great strain",
        "image": "https://example.com/img.jpg",
        "yield_potential": "high",
        "height": "medium",
        "thc": 25,
        "cbd": 0.1,
        "cbg": None,
        "awards": [],
        "lineage_tree": {"parents": []},
        "lineage_str": "Sunset Sherbet × Thin Mint GSC",
        "effects": ["relaxed"],
        "aroma": ["sweet"],
        "taste": ["citrus"],
    }
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_get_strain_details = AsyncMock(
        return_value=raw
    )
    if True:
        result = await websocket_get_external_strain_details(
            hass, mock_coordinator, msg
        )

    assert result["name"] == "Gelato #41"
    assert result["flowering_days"] == round((56 + 63) / 2)
    assert result["indica_percentage"] == 60
    assert result["parents"] == {"parents": []}


@pytest.mark.asyncio
async def test_websocket_get_external_strain_details_single_flowering_time(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover single-value flowering_time parsing (e.g. '60 days')."""
    msg = {"id": 26, "url": "https://example.com/strain/og-kush"}
    raw = {
        "name": "OG Kush",
        "breeder": "DNA Genetics",
        "type": "indica",
        "composition": None,
        "flowering_time": "60 days",
        "description": None,
        "image": None,
        "yield_potential": None,
        "height": None,
        "thc": None,
        "cbd": None,
        "cbg": None,
        "awards": None,
        "lineage_tree": None,
        "lineage_str": None,
        "effects": None,
        "aroma": None,
        "taste": None,
    }
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_get_strain_details = AsyncMock(
        return_value=raw
    )
    if True:
        result = await websocket_get_external_strain_details(
            hass, mock_coordinator, msg
        )

    assert result["flowering_days"] == 60
    assert result["parents"] is None


@pytest.mark.asyncio
async def test_websocket_get_external_strain_details_service_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover ServiceValidationError branch in websocket_get_external_strain_details."""
    msg = {"id": 25, "url": "https://example.com/strain/gelato"}
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_get_strain_details = AsyncMock(
        side_effect=ServiceValidationError("unavailable")
    )
    if True:
        with pytest.raises(ServiceValidationError, match=r"unavailable"):
            await websocket_get_external_strain_details(hass, mock_coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_get_external_strain_details_no_flowering_time_match(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Cover the branch where flowering_time pattern does not match."""
    msg = {"id": 27, "url": "https://example.com/strain/og-kush"}
    raw = {
        "name": "OG Kush",
        "breeder": "DNA Genetics",
        "type": "indica",
        "composition": None,
        "flowering_time": "unknown days",
        "description": None,
        "image": None,
        "yield_potential": None,
        "height": None,
        "thc": None,
        "cbd": None,
        "cbg": None,
        "awards": None,
        "lineage_tree": None,
        "lineage_str": None,
        "effects": None,
        "aroma": None,
        "taste": None,
    }
    mock_coordinator = MagicMock()
    mock_coordinator.seedfinder_scraper = AsyncMock()
    mock_coordinator.seedfinder_scraper.async_get_strain_details = AsyncMock(
        return_value=raw
    )
    if True:
        result = await websocket_get_external_strain_details(
            hass, mock_coordinator, msg
        )

    assert result["flowering_days"] is None


# ---------------------------------------------------------------------------
# websocket_download_strain_image – MIME type from Content-Type header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_download_strain_image_uses_content_type_header(
    hass: HomeAssistant,
) -> None:
    """download_strain_image builds the data URI using the Content-Type from the HTTP response."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    msg = {
        "id": 1,
        "url": "https://example.com/photo.png",
        "strain": "OG Kush",
        "phenotype": "a",
    }

    raw_bytes = b"\x89PNG\r\n"
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.headers = {"Content-Type": "image/png"}
    mock_response.read = AsyncMock(return_value=raw_bytes)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_ctx

    mock_image_manager = MagicMock()
    mock_image_manager.save_strain_image = AsyncMock(
        return_value="/config/www/growspace_manager/strains/og-kush_a_abc.png"
    )

    mock_coordinator = MagicMock()
    mock_coordinator.services.config.strain_library.image_manager = mock_image_manager

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_any",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.growspace_manager.websocket.strain.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        await websocket_download_strain_image(hass, mock_coordinator, msg)

    saved_base64: str = mock_image_manager.save_strain_image.call_args[0][2]
    assert saved_base64.startswith("data:image/png;base64,"), (
        f"Expected 'data:image/png;base64,' prefix but got: {saved_base64[:40]}"
    )
