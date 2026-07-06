from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.websocket import (
    WS_TYPE_GET_EC_RAMP_CURVES,
    WS_TYPE_GET_IPM_PRESETS,
    WS_TYPE_GET_NUTRIENT_PRESETS,
    WS_TYPE_GET_STRAIN_LIBRARY,
    WS_TYPE_GET_STRAIN_LINEAGE_TREE,
    websocket_download_strain_image,
    websocket_get_ec_ramp_curves,
    websocket_get_ipm_presets,
    websocket_get_nutrient_presets,
    websocket_get_strain_library,
    websocket_get_strain_lineage_tree,
    websocket_upload_strain_image,
)
from homeassistant.core import HomeAssistant


@dataclass
class DummyPreset:
    id: str
    name: str


@pytest.fixture
def mock_connection():
    return Mock()


@pytest.mark.asyncio
async def test_websocket_get_strain_library_success(mock_connection) -> None:
    """Test successful retrieval of strain library via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    # Mock strain library
    mock_library = Mock()
    expected_strains = {"Strain A": {"name": "Strain A"}}
    mock_library.get_all.return_value = expected_strains

    coordinator = MagicMock()
    coordinator._strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    if True:
        msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

        # Call synchronously as it is now a callback
        result = websocket_get_strain_library(hass, coordinator, msg)

        expected_response = {
            "strains": expected_strains,
            "strain_list": ["Strain A"],
        }
    assert result == expected_response


@pytest.mark.asyncio
async def test_websocket_get_strain_library_exception(mock_connection) -> None:
    """Test exception handling during retrieval."""
    hass = Mock(spec=HomeAssistant)

    mock_library = Mock()
    mock_library.get_all.side_effect = RuntimeError("Unexpected error")

    coordinator = MagicMock()
    coordinator._strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    if True:
        msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

        with pytest.raises(RuntimeError, match="Unexpected error"):
            websocket_get_strain_library(hass, coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_get_nutrient_presets_success(mock_connection) -> None:
    """Test successful retrieval of nutrient presets via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = {"preset_1": {"id": "preset_1", "name": "Veg A"}}
    coordinator.services.config.get_nutrient_serialization_data.return_value = {
        "nutrient_presets": expected_data
    }

    if True:
        msg = {"id": 1, "type": WS_TYPE_GET_NUTRIENT_PRESETS}
        result = websocket_get_nutrient_presets(hass, coordinator, msg)
    assert result == expected_data


@pytest.mark.asyncio
async def test_websocket_get_ipm_presets_success(mock_connection) -> None:
    """Test successful retrieval of IPM presets via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = {"ipm_1": {"id": "ipm_1", "name": "Neem"}}
    coordinator.services.config.get_nutrient_serialization_data.return_value = {
        "ipm_presets": expected_data
    }

    if True:
        msg = {"id": 1, "type": WS_TYPE_GET_IPM_PRESETS}
        result = websocket_get_ipm_presets(hass, coordinator, msg)
    assert result == expected_data


@pytest.mark.asyncio
async def test_websocket_get_ec_ramp_curves_success(mock_connection) -> None:
    """Test successful retrieval of EC ramp curves via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = [{"id": "curve_1", "name": "Standard Curve"}]
    coordinator.services.config.get_nutrient_serialization_data.return_value = {
        "ec_ramp_curves": expected_data
    }

    if True:
        msg = {"id": 1, "type": WS_TYPE_GET_EC_RAMP_CURVES}
        result = websocket_get_ec_ramp_curves(hass, coordinator, msg)
    assert result == expected_data


@pytest.mark.asyncio
async def test_websocket_get_strain_lineage_tree_success(mock_connection) -> None:
    """Test successful retrieval of strain lineage tree via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    # Mock strain library
    mock_library = Mock()
    expected_tree = {"name": "Strain A", "parents": []}
    mock_library.get_strain_lineage_tree.return_value = expected_tree

    coordinator = MagicMock()
    coordinator._strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    if True:
        msg = {
            "id": 1,
            "type": WS_TYPE_GET_STRAIN_LINEAGE_TREE,
            "strain_name": "Strain A",
        }

        result = await websocket_get_strain_lineage_tree(hass, coordinator, msg)

    assert result == expected_tree


@pytest.mark.asyncio
async def test_websocket_upload_strain_image_success(mock_connection: Mock) -> None:
    """Test successful upload of a strain image."""
    hass = Mock(spec=HomeAssistant)

    mock_image_manager = MagicMock()
    mock_image_manager.save_strain_image = AsyncMock(
        return_value="/config/www/growspace_manager/strains/og_kush__pheno1.jpg"
    )

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = mock_image_manager

    if True:
        msg = {
            "id": 5,
            "type": f"{DOMAIN}/upload_strain_image",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
            "image_base64": "data:image/jpeg;base64,abc123",
        }
        result = await websocket_upload_strain_image(hass, coordinator, msg)

    assert result == {"path": "/local/growspace_manager/strains/og_kush__pheno1.jpg"}


@pytest.mark.asyncio
async def test_websocket_upload_strain_image_generic_error(
    mock_connection: Mock,
) -> None:
    """Test upload generic exception handling."""
    hass = Mock(spec=HomeAssistant)

    mock_image_manager = MagicMock()
    mock_image_manager.save_strain_image = AsyncMock(side_effect=OSError("disk full"))

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = mock_image_manager

    if True:
        msg = {
            "id": 7,
            "type": f"{DOMAIN}/upload_strain_image",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
            "image_base64": "data:image/jpeg;base64,abc123",
        }
        with pytest.raises(OSError, match="disk full"):
            await websocket_upload_strain_image(hass, coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_download_strain_image_http_error(
    mock_connection: Mock,
) -> None:
    """Test download returns fetch_failed when HTTP response is non-200."""
    hass = Mock(spec=HomeAssistant)

    mock_response = MagicMock()
    mock_response.status = 404
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.websocket.strain.async_get_clientsession",
            return_value=mock_session,
        ),
    ):
        msg = {
            "id": 8,
            "type": f"{DOMAIN}/download_strain_image",
            "url": "https://example.com/img.jpg",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
        }
        with pytest.raises(GrowspaceError, match="HTTP 404"):
            await websocket_download_strain_image(hass, coordinator, msg)


@pytest.mark.asyncio
async def test_websocket_download_strain_image_generic_error(
    mock_connection: Mock,
) -> None:
    """Test download generic exception handling."""
    hass = Mock(spec=HomeAssistant)

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.websocket.strain.async_get_clientsession",
            side_effect=RuntimeError("session error"),
        ),
    ):
        msg = {
            "id": 10,
            "type": f"{DOMAIN}/download_strain_image",
            "url": "https://example.com/img.jpg",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
        }
        with pytest.raises(RuntimeError, match="session error"):
            await websocket_download_strain_image(hass, coordinator, msg)
