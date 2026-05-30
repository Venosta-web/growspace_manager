from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
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
from homeassistant.exceptions import ServiceValidationError


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
    coordinator.strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

        # Call synchronously as it is now a callback
        websocket_get_strain_library(hass, mock_connection, msg)

        expected_response = {
            "strains": expected_strains,
            "strain_list": ["Strain A"],
        }
        mock_connection.send_result.assert_called_once_with(1, expected_response)


@pytest.mark.asyncio
async def test_websocket_get_strain_library_not_loaded(mock_connection) -> None:
    """Test error when strain library is not loaded."""
    hass = Mock(spec=HomeAssistant)

    msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
        side_effect=ServiceValidationError("Not loaded"),
    ):
        websocket_get_strain_library(hass, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            1, "not_loaded", "Growspace Manager strain library not loaded"
        )


@pytest.mark.asyncio
async def test_websocket_get_strain_library_exception(mock_connection) -> None:
    """Test exception handling during retrieval."""
    hass = Mock(spec=HomeAssistant)

    mock_library = Mock()
    mock_library.get_all.side_effect = RuntimeError("Unexpected error")

    coordinator = MagicMock()
    coordinator.strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

        websocket_get_strain_library(hass, mock_connection, msg)

        mock_connection.send_error.assert_called_once_with(
            1, "unknown_error", "Unexpected error"
        )


@pytest.mark.asyncio
async def test_websocket_get_nutrient_presets_success(mock_connection) -> None:
    """Test successful retrieval of nutrient presets via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = {"preset_1": {"id": "preset_1", "name": "Veg A"}}
    coordinator.nutrient_manager.get_serialization_data.return_value = {
        "nutrient_presets": expected_data
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_NUTRIENT_PRESETS}
        websocket_get_nutrient_presets(hass, mock_connection, msg)
        mock_connection.send_result.assert_called_once_with(1, expected_data)


@pytest.mark.asyncio
async def test_websocket_get_ipm_presets_success(mock_connection) -> None:
    """Test successful retrieval of IPM presets via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = {"ipm_1": {"id": "ipm_1", "name": "Neem"}}
    coordinator.nutrient_manager.get_serialization_data.return_value = {
        "ipm_presets": expected_data
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_IPM_PRESETS}
        websocket_get_ipm_presets(hass, mock_connection, msg)
        mock_connection.send_result.assert_called_once_with(1, expected_data)


@pytest.mark.asyncio
async def test_websocket_get_ec_ramp_curves_success(mock_connection) -> None:
    """Test successful retrieval of EC ramp curves via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    coordinator = Mock()
    expected_data = [{"id": "curve_1", "name": "Standard Curve"}]
    coordinator.nutrient_manager.get_serialization_data.return_value = {
        "ec_ramp_curves": expected_data
    }

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_EC_RAMP_CURVES}
        websocket_get_ec_ramp_curves(hass, mock_connection, msg)
        mock_connection.send_result.assert_called_once_with(1, expected_data)


@pytest.mark.asyncio
async def test_websocket_get_strain_lineage_tree_success(mock_connection) -> None:
    """Test successful retrieval of strain lineage tree via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    # Mock strain library
    mock_library = Mock()
    expected_tree = {"name": "Strain A", "parents": []}
    mock_library.get_strain_lineage_tree.return_value = expected_tree

    coordinator = MagicMock()
    coordinator.strain_library = mock_library
    coordinator.services.config.strain_library = mock_library

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {
            "id": 1,
            "type": WS_TYPE_GET_STRAIN_LINEAGE_TREE,
            "strain_name": "Strain A",
        }

        await websocket_get_strain_lineage_tree(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(1, expected_tree)


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

    with patch(
        "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {
            "id": 5,
            "type": f"{DOMAIN}/upload_strain_image",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
            "image_base64": "data:image/jpeg;base64,abc123",
        }
        await websocket_upload_strain_image(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(
        5, {"path": "/local/growspace_manager/strains/og_kush__pheno1.jpg"}
    )


@pytest.mark.asyncio
async def test_websocket_upload_strain_image_not_loaded(mock_connection: Mock) -> None:
    """Test upload error when strain library is not loaded."""
    hass = Mock(spec=HomeAssistant)

    with patch(
        "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
        side_effect=ServiceValidationError("Not loaded"),
    ):
        msg = {
            "id": 6,
            "type": f"{DOMAIN}/upload_strain_image",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
            "image_base64": "data:image/jpeg;base64,abc123",
        }
        await websocket_upload_strain_image(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(6, "not_loaded", "Strain library not loaded")


@pytest.mark.asyncio
async def test_websocket_upload_strain_image_generic_error(mock_connection: Mock) -> None:
    """Test upload generic exception handling."""
    hass = Mock(spec=HomeAssistant)

    mock_image_manager = MagicMock()
    mock_image_manager.save_strain_image = AsyncMock(side_effect=OSError("disk full"))

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = mock_image_manager

    with patch(
        "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {
            "id": 7,
            "type": f"{DOMAIN}/upload_strain_image",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
            "image_base64": "data:image/jpeg;base64,abc123",
        }
        await websocket_upload_strain_image(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(7, "unknown_error", "disk full")


@pytest.mark.asyncio
async def test_websocket_download_strain_image_http_error(mock_connection: Mock) -> None:
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
            "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
            return_value=coordinator,
        ),
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
        await websocket_download_strain_image(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(8, "fetch_failed", "HTTP 404")


@pytest.mark.asyncio
async def test_websocket_download_strain_image_not_loaded(mock_connection: Mock) -> None:
    """Test download error when strain library is not loaded."""
    hass = Mock(spec=HomeAssistant)

    with patch(
        "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
        side_effect=ServiceValidationError("Not loaded"),
    ):
        msg = {
            "id": 9,
            "type": f"{DOMAIN}/download_strain_image",
            "url": "https://example.com/img.jpg",
            "strain": "OG Kush",
            "phenotype": "Pheno 1",
        }
        await websocket_download_strain_image(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(9, "not_loaded", "Strain library not loaded")


@pytest.mark.asyncio
async def test_websocket_download_strain_image_generic_error(mock_connection: Mock) -> None:
    """Test download generic exception handling."""
    hass = Mock(spec=HomeAssistant)

    coordinator = MagicMock()
    coordinator.services.config.strain_library.image_manager = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.websocket.strain.GrowspaceCoordinator.get_any",
            return_value=coordinator,
        ),
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
        await websocket_download_strain_image(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(10, "unknown_error", "session error")
