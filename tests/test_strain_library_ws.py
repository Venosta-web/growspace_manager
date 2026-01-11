from unittest.mock import MagicMock, Mock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager import (
    DOMAIN,
    WS_TYPE_GET_IPM_PRESETS,
    WS_TYPE_GET_NUTRIENT_PRESETS,
    WS_TYPE_GET_STRAIN_LIBRARY,
    websocket_get_ipm_presets,
    websocket_get_nutrient_presets,
    websocket_get_strain_library,
)

from dataclasses import dataclass


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

    hass.data = {DOMAIN: {"strain_library": mock_library}}

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
    hass.data = {}  # Empty data

    msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

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

    hass.data = {DOMAIN: {"strain_library": mock_library}}

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
    preset = DummyPreset(id="preset_1", name="Veg A")
    coordinator.nutrient_presets = {"preset_1": preset}

    expected_data = {"preset_1": {"id": "preset_1", "name": "Veg A"}}

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
    preset = DummyPreset(id="ipm_1", name="Neem")
    coordinator.ipm_presets = {"ipm_1": preset}

    expected_data = {"ipm_1": {"id": "ipm_1", "name": "Neem"}}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        msg = {"id": 1, "type": WS_TYPE_GET_IPM_PRESETS}
        websocket_get_ipm_presets(hass, mock_connection, msg)
        mock_connection.send_result.assert_called_once_with(1, expected_data)
