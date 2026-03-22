"""Tests for update_vision_checkup_config WebSocket handler."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    VisionCheckupConfig,
)


@pytest.fixture
def mock_growspace():
    env = EnvironmentConfig(
        temperature_sensors=["sensor.temp"],
        humidity_sensors=["sensor.hum"],
    )
    gs = MagicMock(spec=Growspace)
    gs.environment_config = env
    return gs


@pytest.fixture
def mock_coordinator(mock_growspace):
    coord = MagicMock()
    coord.growspaces = {"tent1": mock_growspace}
    coord.async_commit = AsyncMock()
    coord.vision_scheduler = MagicMock()
    coord.vision_scheduler.schedule_all_growspaces = MagicMock()
    return coord


@pytest.mark.asyncio
async def test_update_vision_checkup_config_success(mock_coordinator, mock_growspace):
    from custom_components.growspace_manager.websocket import (
        websocket_update_vision_checkup_config,
    )

    connection = MagicMock()
    connection.send_result = MagicMock()
    msg = {
        "id": 1,
        "growspace_id": "tent1",
        "enabled": True,
        "early_check_offset_minutes": 90,
        "mid_check_hours": 8,
        "late_check_offset_minutes": 45,
    }
    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        await websocket_update_vision_checkup_config(MagicMock(), connection, msg)

    cfg = mock_growspace.environment_config.vision_checkup_config
    assert cfg.enabled is True
    assert cfg.early_check_offset_minutes == 90
    assert cfg.mid_check_hours == 8
    assert cfg.late_check_offset_minutes == 45
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.vision_scheduler.schedule_all_growspaces.assert_called_once()
    connection.send_result.assert_called_once_with(1, {"success": True})


@pytest.mark.asyncio
async def test_update_vision_checkup_config_growspace_not_found(mock_coordinator):
    from custom_components.growspace_manager.websocket import (
        websocket_update_vision_checkup_config,
    )

    connection = MagicMock()
    connection.send_error = MagicMock()
    msg = {"id": 2, "growspace_id": "nonexistent", "enabled": False}
    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        await websocket_update_vision_checkup_config(MagicMock(), connection, msg)

    connection.send_error.assert_called_once()
    args = connection.send_error.call_args[0]
    assert args[0] == 2
    assert args[1] == "not_found"


@pytest.mark.asyncio
async def test_update_vision_checkup_config_no_env_config(mock_coordinator):
    from custom_components.growspace_manager.websocket import (
        websocket_update_vision_checkup_config,
    )

    gs = MagicMock()
    gs.environment_config = None
    mock_coordinator.growspaces = {"tent1": gs}
    connection = MagicMock()
    connection.send_error = MagicMock()
    msg = {"id": 3, "growspace_id": "tent1", "enabled": True}
    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        await websocket_update_vision_checkup_config(MagicMock(), connection, msg)

    connection.send_error.assert_called_once()
    args = connection.send_error.call_args[0]
    assert args[0] == 3
    assert args[1] == "no_environment"


@pytest.mark.asyncio
async def test_update_vision_checkup_config_partial_update(mock_coordinator, mock_growspace):
    from custom_components.growspace_manager.websocket import (
        websocket_update_vision_checkup_config,
    )

    # Pre-set values
    mock_growspace.environment_config.vision_checkup_config.enabled = False
    mock_growspace.environment_config.vision_checkup_config.early_check_offset_minutes = 60

    connection = MagicMock()
    msg = {"id": 4, "growspace_id": "tent1", "enabled": True}  # Only update enabled
    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        await websocket_update_vision_checkup_config(MagicMock(), connection, msg)

    cfg = mock_growspace.environment_config.vision_checkup_config
    assert cfg.enabled is True
    # early_check_offset_minutes should remain 60 (not updated)
    assert cfg.early_check_offset_minutes == 60


@pytest.mark.asyncio
async def test_update_vision_checkup_config_coordinator_not_loaded():
    from custom_components.growspace_manager.websocket import (
        websocket_update_vision_checkup_config,
    )
    from homeassistant.exceptions import ServiceValidationError

    connection = MagicMock()
    connection.send_error = MagicMock()
    msg = {"id": 5, "growspace_id": "tent1", "enabled": True}

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("Integration not loaded"),
    ):
        await websocket_update_vision_checkup_config(MagicMock(), connection, msg)

    connection.send_error.assert_called_once()
    args = connection.send_error.call_args[0]
    assert args[0] == 5
    assert args[1] == "not_loaded"
