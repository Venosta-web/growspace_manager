"""Tests for the Growspace Config Handler."""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.growspace_config_handler import (
    GrowspaceConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@dataclass
class MockGrowspace:
    id: str
    name: str
    rows: int = 4
    plants_per_row: int = 4
    notification_target: str = ""
    dimensions: dict = field(
        default_factory=lambda: {"length": 120, "width": 120, "height": 200}
    )


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    hass.services = MagicMock()
    hass.services.async_services.return_value = {"notify": {"mobile_app_phone": {}}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.runtime_data = MagicMock()
    return entry


@pytest.fixture
def handler(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> GrowspaceConfigHandler:
    """Create a GrowspaceConfigHandler instance."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_growspace_id = "gs1"
    return handler


async def test_async_step_manage_growspaces_abort_no_entry(
    mock_hass: MagicMock,
) -> None:
    handler = GrowspaceConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_manage_growspaces()
    assert result == {"type": "abort"}


async def test_async_step_manage_growspaces_get(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspace_service.get_sorted_growspace_options.return_value = []
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_manage_growspaces()
    assert result["type"] == "form"


async def test_async_step_manage_growspaces_post_actions(
    handler: GrowspaceConfigHandler,
) -> None:
    handler.async_step_add_growspace = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_growspaces({"action": "add"})
    handler.async_step_add_growspace.assert_called_once()

    handler.async_step_update_growspace = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_growspaces(
        {"action": "update", "growspace_id": "gs1"}
    )
    handler.async_step_update_growspace.assert_called_once()

    handler.async_step_confirm_remove_growspace = AsyncMock(
        return_value={"type": "form"}
    )
    await handler.async_step_manage_growspaces(
        {"action": "remove", "growspace_id": "gs1"}
    )
    handler.async_step_confirm_remove_growspace.assert_called_once()

    handler.flow.async_step_init = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_growspaces({"action": "back"})
    handler.flow.async_step_init.assert_called_once()


async def test_async_step_manage_growspaces_post_no_id(
    handler: GrowspaceConfigHandler,
) -> None:
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_manage_growspaces({"action": "update"})
    assert result["type"] == "form"
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "select_growspace"
    }

    result = await handler.async_step_manage_growspaces({"action": "remove"})
    assert result["type"] == "form"


async def test_async_step_add_growspace_success(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.async_add_growspace = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {
        "name": "GS1",
        "rows": 4,
        "plants_per_row": 4,
        "length": 100,
        "width": 100,
        "height": 200,
    }
    result = await handler.async_step_add_growspace(user_input)
    assert result["type"] == "create_entry"
    coordinator.async_add_growspace.assert_called_once()


async def test_async_step_add_growspace_fail(handler: GrowspaceConfigHandler) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.async_add_growspace = AsyncMock(side_effect=Exception)
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_add_growspace(
        {
            "name": "GS1",
            "rows": 4,
            "plants_per_row": 4,
            "length": 100,
            "width": 100,
            "height": 200,
        }
    )
    assert result["type"] == "form"
    assert handler.flow.async_show_form.call_args[1]["errors"] == {"base": "add_failed"}


async def test_async_step_confirm_remove_growspace_success(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MockGrowspace(id="gs1", name="GS1")}
    coordinator.async_remove_growspace = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    result = await handler.async_step_confirm_remove_growspace({"confirm": True})
    assert result["type"] == "create_entry"
    coordinator.async_remove_growspace.assert_called_once_with("gs1")


async def test_async_step_confirm_remove_growspace_fail(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MockGrowspace(id="gs1", name="GS1")}
    coordinator.async_remove_growspace = AsyncMock(side_effect=Exception)
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_confirm_remove_growspace({"confirm": True})
    assert result["type"] == "form"
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "remove_failed"
    }


async def test_async_step_update_growspace_success(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MockGrowspace(id="gs1", name="GS1")}
    coordinator.async_update_growspace = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {
        "name": "GS2",
        "rows": 5,
        "plants_per_row": 5,
        "length": 120,
        "width": 120,
        "height": 210,
    }
    result = await handler.async_step_update_growspace(user_input)
    assert result["type"] == "create_entry"
    coordinator.async_update_growspace.assert_called_once()


async def test_async_step_update_growspace_fail(
    handler: GrowspaceConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MockGrowspace(id="gs1", name="GS1")}
    coordinator.async_update_growspace = AsyncMock(side_effect=Exception)
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_update_growspace({"name": "GS2"})
    assert result["type"] == "form"
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "update_failed"
    }


async def test_get_add_growspace_schema_no_notify(
    handler: GrowspaceConfigHandler,
) -> None:
    handler.hass.services.async_services.return_value = {}
    schema = handler.get_add_growspace_schema()
    assert isinstance(schema, vol.Schema)


def test_get_update_growspace_schema_none(handler: GrowspaceConfigHandler) -> None:
    result = handler.get_update_growspace_schema(None)
    assert result.schema == {}


async def test_async_steps_no_coordinator(
    handler: GrowspaceConfigHandler, mock_hass: MagicMock
) -> None:
    # Use a real handler with None entry
    handler_no_entry = GrowspaceConfigHandler(mock_hass, None)
    handler_no_entry.flow = handler.flow
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    assert await handler_no_entry.async_step_manage_growspaces() == {"type": "abort"}
    # async_step_add_growspace and others access coordinator before user_input check
    assert await handler_no_entry.async_step_add_growspace() == {"type": "abort"}
    assert await handler_no_entry.async_step_confirm_remove_growspace() == {
        "type": "abort"
    }
    assert await handler_no_entry.async_step_update_growspace() == {"type": "abort"}


async def test_async_step_add_growspace_no_coord(
    handler: GrowspaceConfigHandler,
) -> None:
    handler.config_entry.runtime_data = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    assert await handler.async_step_add_growspace() == {"type": "abort"}


async def test_async_add_growspace_no_entry(mock_hass: MagicMock) -> None:
    # Use a real handler with None entry
    handler = GrowspaceConfigHandler(mock_hass, None)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_growspace({})


async def test_async_remove_growspace_no_entry(mock_hass: MagicMock) -> None:
    handler = GrowspaceConfigHandler(mock_hass, None)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_remove_growspace("gs1")


async def test_async_update_growspace_no_entry(mock_hass: MagicMock) -> None:
    handler = GrowspaceConfigHandler(mock_hass, None)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_growspace("gs1", {})


async def test_async_steps_coordinator_is_none(
    handler: GrowspaceConfigHandler,
) -> None:
    """Test steps when config_entry.runtime_data is None."""
    handler.config_entry.runtime_data = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    assert await handler.async_step_manage_growspaces() == {"type": "abort"}
    assert await handler.async_step_add_growspace() == {"type": "abort"}
    assert await handler.async_step_confirm_remove_growspace() == {"type": "abort"}
    assert await handler.async_step_update_growspace() == {"type": "abort"}


async def test_async_add_remove_update_runtime_data_is_none(
    handler: GrowspaceConfigHandler,
) -> None:
    """Test helpers when runtime_data is None."""
    handler.config_entry.runtime_data = None

    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_growspace({})
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_remove_growspace("gs1")
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_growspace("gs1", {})


async def test_async_step_confirm_remove_growspace_not_found(
    handler: GrowspaceConfigHandler,
) -> None:
    """Test remove step when growspace is not found."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    result = await handler.async_step_confirm_remove_growspace()
    assert result == {"type": "abort"}
    assert handler.flow.async_abort.call_args[1]["reason"] == "growspace_not_found"


async def test_async_step_update_growspace_not_found(
    handler: GrowspaceConfigHandler,
) -> None:
    """Test update step when growspace is not found."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    result = await handler.async_step_update_growspace()
    assert result == {"type": "abort"}
    assert handler.flow.async_abort.call_args[1]["reason"] == "growspace_not_found"


def test_get_update_growspace_schema_no_notify(handler: GrowspaceConfigHandler) -> None:
    """Test update schema when no notify services available."""
    handler.hass.services.async_services.return_value = {}
    growspace = MockGrowspace(id="gs1", name="GS1")
    schema = handler.get_update_growspace_schema(growspace)
    assert isinstance(schema, vol.Schema)


async def test_async_steps_initial_show(handler: GrowspaceConfigHandler) -> None:
    """Test initial form show (user_input is None)."""

    def mock_show_form(step_id, **kwargs):
        return {"type": "form", "step_id": step_id}

    handler.flow.async_show_form = MagicMock(side_effect=mock_show_form)
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {"gs1": MockGrowspace(id="gs1", name="GS1")}

    # Add growspace initial
    result = await handler.async_step_add_growspace(None)
    assert result["type"] == "form"
    assert result["step_id"] == "add_growspace"

    # Confirm remove initial
    result = await handler.async_step_confirm_remove_growspace(None)
    assert result["type"] == "form"
    assert result["step_id"] == "confirm_remove_growspace"

    # Update growspace initial
    result = await handler.async_step_update_growspace(None)
    assert result["type"] == "form"
    assert result["step_id"] == "update_growspace"
