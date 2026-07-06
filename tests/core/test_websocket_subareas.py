"""Tests for subarea WebSocket commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.get_subareas.return_value = [
            mock_subarea
        ]
        result = await websocket_get_subareas(hass, mock_get.return_value, msg)
    assert result[0]["id"] == "sub1"
    assert result[0]["name"] == "Undercanopy"


@pytest.mark.asyncio
async def test_websocket_add_subarea_success(
    hass: HomeAssistant, mock_connection: MagicMock, mock_subarea: Subarea
) -> None:
    msg = {
        "id": 1,
        "type": "growspace_manager/add_subarea",
        "growspace_id": "gs1",
        "name": "Undercanopy",
    }
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.add_subarea = AsyncMock(
            return_value=mock_subarea
        )
        result = await websocket_add_subarea(hass, mock_get.return_value, msg)
    assert result["name"] == "Undercanopy"


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
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.update_subarea = AsyncMock(
            return_value=mock_subarea
        )
        await websocket_update_subarea(hass, mock_get.return_value, msg)


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
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.remove_subarea = AsyncMock()
        result = await websocket_remove_subarea(hass, mock_get.return_value, msg)
    assert result == {"success": True}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_websocket_add_subarea_validation_error(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    msg = {
        "id": 1,
        "type": "growspace_manager/add_subarea",
        "growspace_id": "gs1",
        "name": "X",
    }
    if True:
        mock_get = MagicMock()
        mock_get.return_value.services.growspaces.add_subarea = AsyncMock(
            side_effect=ServiceValidationError("not found")
        )
        with pytest.raises(ServiceValidationError, match="not found"):
            await websocket_add_subarea(hass, mock_get.return_value, msg)
