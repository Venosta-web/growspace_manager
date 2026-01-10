from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager import (
    DOMAIN,
    WS_TYPE_GET_STRAIN_LIBRARY,
    websocket_get_strain_library,
)


@pytest.fixture
def mock_connection():
    return Mock()


@pytest.mark.asyncio
async def test_websocket_get_strain_library_success(mock_connection) -> None:
    """Test successful retrieval of strain library via WebSocket."""
    hass = Mock(spec=HomeAssistant)

    # Mock strain library
    mock_library = Mock()
    expected_analytics = {"strains": {"Strain A": {}}}
    # get_analytics is not async in the actual code (it returns a dict or cached dict),
    # but let's check if it calls anything async.
    # In strain_library.py: get_analytics() is a sync method.
    mock_library.get_analytics.return_value = expected_analytics

    hass.data = {DOMAIN: {"strain_library": mock_library}}

    msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

    # Call synchronously as it is now a callback
    websocket_get_strain_library(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(1, expected_analytics)


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
    mock_library.get_analytics.side_effect = RuntimeError("Unexpected error")

    hass.data = {DOMAIN: {"strain_library": mock_library}}

    msg = {"id": 1, "type": WS_TYPE_GET_STRAIN_LIBRARY}

    websocket_get_strain_library(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(
        1, "unknown_error", "Unexpected error"
    )
