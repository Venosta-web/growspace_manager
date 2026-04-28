"""Tests for subarea WebSocket commands."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import Subarea
from custom_components.growspace_manager.websocket import (
    websocket_add_subarea,
    websocket_get_subareas,
    websocket_remove_subarea,
    websocket_update_subarea,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def mock_subarea() -> Subarea:
    return Subarea(id="sub1", name="Undercanopy")


@pytest.mark.asyncio
async def test_websocket_get_subareas_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_subarea: Subarea
) -> None:
    msg = {"id": 1, "type": "growspace_manager/get_subareas", "growspace_id": "gs1"}
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.get_subareas.return_value = [mock_subarea]
        await websocket_get_subareas(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result[0]["id"] == "sub1"
    assert result[0]["name"] == "Undercanopy"


@pytest.mark.asyncio
async def test_websocket_add_subarea_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_subarea: Subarea
) -> None:
    msg = {"id": 1, "type": "growspace_manager/add_subarea", "growspace_id": "gs1", "name": "Undercanopy"}
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.async_add_subarea = AsyncMock(return_value=mock_subarea)
        await websocket_add_subarea(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once()
    assert mock_connection.send_result.call_args[0][1]["name"] == "Undercanopy"


@pytest.mark.asyncio
async def test_websocket_update_subarea_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_subarea: Subarea
) -> None:
    msg = {
        "id": 1,
        "type": "growspace_manager/update_subarea",
        "growspace_id": "gs1",
        "subarea_id": "sub1",
        "environment_config": {"temperature_sensors": ["sensor.t"]},
    }
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.async_update_subarea = AsyncMock(return_value=mock_subarea)
        await websocket_update_subarea(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_remove_subarea_success(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {
        "id": 1,
        "type": "growspace_manager/remove_subarea",
        "growspace_id": "gs1",
        "subarea_id": "sub1",
    }
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.async_remove_subarea = AsyncMock()
        await websocket_remove_subarea(hass, mock_connection, msg)
    mock_connection.send_result.assert_called_once_with(1, {"success": True})


@pytest.mark.asyncio
async def test_websocket_get_subareas_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {"id": 1, "type": "growspace_manager/get_subareas", "growspace_id": "gs1"}
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("boom"),
    ):
        await websocket_get_subareas(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once()


@pytest.mark.asyncio
async def test_websocket_add_subarea_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {"id": 1, "type": "growspace_manager/add_subarea", "growspace_id": "gs1", "name": "X"}
    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call"
    ) as mock_get:
        mock_get.return_value.async_add_subarea = AsyncMock(
            side_effect=ServiceValidationError("not found")
        )
        await websocket_add_subarea(hass, mock_connection, msg)
    mock_connection.send_error.assert_called_once()
    assert mock_connection.send_error.call_args[0][1] == "invalid_args"
