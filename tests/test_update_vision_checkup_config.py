"""Tests for update_vision_checkup_config WebSocket handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.websocket import (
    websocket_update_vision_checkup_config,
)
from homeassistant.exceptions import ServiceValidationError


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
    msg = {
        "id": 1,
        "growspace_id": "tent1",
        "enabled": True,
        "early_check_offset_minutes": 90,
        "mid_check_hours": 8,
        "late_check_offset_minutes": 45,
    }
    result = await websocket_update_vision_checkup_config(
        MagicMock(), mock_coordinator, msg
    )

    cfg = mock_growspace.environment_config.vision_checkup_config
    assert cfg.enabled is True
    assert cfg.early_check_offset_minutes == 90
    assert cfg.mid_check_hours == 8
    assert cfg.late_check_offset_minutes == 45
    mock_coordinator.async_commit.assert_awaited_once()
    mock_coordinator.vision_scheduler.schedule_all_growspaces.assert_called_once()
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_update_vision_checkup_config_growspace_not_found(mock_coordinator):
    msg = {"id": 2, "growspace_id": "nonexistent", "enabled": False}
    with pytest.raises(GrowspaceNotFoundError):
        await websocket_update_vision_checkup_config(MagicMock(), mock_coordinator, msg)


@pytest.mark.asyncio
async def test_update_vision_checkup_config_no_env_config(mock_coordinator):
    gs = MagicMock()
    gs.environment_config = None
    mock_coordinator.growspaces = {"tent1": gs}
    msg = {"id": 3, "growspace_id": "tent1", "enabled": True}
    with pytest.raises(ServiceValidationError, match="No environment config"):
        await websocket_update_vision_checkup_config(MagicMock(), mock_coordinator, msg)


@pytest.mark.asyncio
async def test_update_vision_checkup_config_partial_update(
    mock_coordinator, mock_growspace
):
    # Pre-set values
    mock_growspace.environment_config.vision_checkup_config.enabled = False
    mock_growspace.environment_config.vision_checkup_config.early_check_offset_minutes = 999

    msg = {"id": 4, "growspace_id": "tent1", "enabled": True}  # Only update enabled
    await websocket_update_vision_checkup_config(MagicMock(), mock_coordinator, msg)

    cfg = mock_growspace.environment_config.vision_checkup_config
    assert cfg.enabled is True
    # early_check_offset_minutes should remain 999 (not updated)
    assert cfg.early_check_offset_minutes == 999
