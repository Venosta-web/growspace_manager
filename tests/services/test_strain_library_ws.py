from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.websocket import (
    WS_TYPE_GET_EC_RAMP_CURVES,
    WS_TYPE_GET_IPM_PRESETS,
    WS_TYPE_GET_NUTRIENT_PRESETS,
    WS_TYPE_GET_STRAIN_LIBRARY,
    WS_TYPE_GET_STRAIN_LINEAGE_TREE,
    websocket_get_ec_ramp_curves,
    websocket_get_ipm_presets,
    websocket_get_nutrient_presets,
    websocket_get_strain_library,
    websocket_get_strain_lineage_tree,
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

    coordinator = Mock(spec=GrowspaceCoordinator)
    coordinator.strain_library = mock_library

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

    coordinator = Mock(spec=GrowspaceCoordinator)
    coordinator.strain_library = mock_library

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

    coordinator = Mock(spec=GrowspaceCoordinator)
    coordinator.strain_library = mock_library

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_any",
        return_value=coordinator,
    ):
        msg = {
            "id": 1,
            "type": WS_TYPE_GET_STRAIN_LINEAGE_TREE,
            "strain_name": "Strain A",
        }

        # Call synchronously as it is now a callback (if it was)
        # Wait, let's check if it's a callback or async
        await websocket_get_strain_lineage_tree(hass, mock_connection, msg)

        mock_connection.send_result.assert_called_once_with(1, expected_tree)
