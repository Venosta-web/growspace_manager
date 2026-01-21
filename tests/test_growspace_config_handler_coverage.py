"""Test coverage for GrowspaceConfigHandler."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.growspace_config_handler import (
    GrowspaceConfigHandler,
)
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def mock_hass():
    """Mock the Home Assistant object."""
    hass = MagicMock()
    hass.services.async_services = MagicMock(return_value={})
    return hass


@pytest.fixture
def mock_flow(mock_hass):
    """Mock the config flow."""
    flow = MagicMock()
    flow.hass = mock_hass
    flow.config_entry = None
    flow.async_abort = MagicMock(
        return_value={"type": FlowResultType.ABORT, "reason": "setup_error"}
    )
    flow.async_show_form = MagicMock(return_value={"type": FlowResultType.FORM})
    flow.async_create_entry = MagicMock(
        return_value={"type": FlowResultType.CREATE_ENTRY}
    )
    return flow


@pytest.fixture
def handler(mock_flow):
    """Create a GrowspaceConfigHandler instance."""
    handler = GrowspaceConfigHandler(flow=mock_flow)
    handler.config_entry = None  # Explicitly set to None for testing the None checks
    return handler


@pytest.mark.asyncio
async def test_async_step_manage_growspaces_no_config_entry(handler) -> None:
    """Test async_step_manage_growspaces when config_entry is None."""
    result = await handler.async_step_manage_growspaces()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_async_step_add_growspace_no_config_entry(handler) -> None:
    """Test async_step_add_growspace when config_entry is None."""
    result = await handler.async_step_add_growspace()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_async_add_growspace_no_config_entry(handler) -> None:
    """Test async_add_growspace when config_entry is None."""
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_growspace(
            {"name": "Test", "rows": 4, "plants_per_row": 4}
        )


@pytest.mark.asyncio
async def test_async_step_confirm_remove_growspace_no_config_entry(handler) -> None:
    """Test async_step_confirm_remove_growspace when config_entry is None."""
    result = await handler.async_step_confirm_remove_growspace()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_async_remove_growspace_no_config_entry(handler) -> None:
    """Test async_remove_growspace when config_entry is None."""
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_remove_growspace("gs_id")


@pytest.mark.asyncio
async def test_async_step_update_growspace_no_config_entry(handler) -> None:
    """Test async_step_update_growspace when config_entry is None."""
    result = await handler.async_step_update_growspace()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_async_update_growspace_no_config_entry(handler) -> None:
    """Test async_update_growspace when config_entry is None."""
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_growspace("gs_id", {"name": "New Name"})
