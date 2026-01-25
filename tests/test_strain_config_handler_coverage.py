"""Tests for the Strain Config Handler."""

from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.strain_config_handler import (
    StrainConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    hass.states = MagicMock()
    hass.config = MagicMock()
    hass.config.path.return_value = "/config/exports"
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.runtime_data = MagicMock()
    return entry


@pytest.fixture
def handler(mock_hass: MagicMock, mock_config_entry: MagicMock) -> StrainConfigHandler:
    """Create a StrainConfigHandler instance."""
    handler = StrainConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    return handler


async def test_async_step_manage_strain_library_abort_no_entry(
    mock_hass: MagicMock,
) -> None:
    """Test abortion if config entry is missing."""
    handler = StrainConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    result = await handler.async_step_manage_strain_library()
    assert result == {"type": "abort"}
    handler.flow.async_abort.assert_called_once_with(reason="setup_error")


async def test_async_step_manage_strain_library_abort_no_coordinator(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test abortion if coordinator is missing."""
    mock_config_entry.runtime_data = None
    handler = StrainConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    result = await handler.async_step_manage_strain_library()
    assert result == {"type": "abort"}
    handler.flow.async_abort.assert_called_once_with(reason="setup_error")


async def test_async_step_manage_strain_library_get(
    handler: StrainConfigHandler,
) -> None:
    """Test showing the form."""
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library()
    assert result["type"] == "form"


async def test_async_step_manage_strain_library_post_add(
    handler: StrainConfigHandler,
) -> None:
    """Test routing to add strain."""
    handler.async_step_add_strain = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library({"action": "add_strain"})
    assert result["type"] == "form"
    handler.async_step_add_strain.assert_called_once()


async def test_async_step_manage_strain_library_post_edit(
    handler: StrainConfigHandler,
) -> None:
    """Test routing to edit strain."""
    handler.async_step_edit_strain = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library(
        {"action": "edit_strain", "strain_id": "test_strain"}
    )
    assert result["type"] == "form"
    assert handler.flow.selected_strain_id == "test_strain"


async def test_async_step_manage_strain_library_post_delete_success(
    handler: StrainConfigHandler,
) -> None:
    """Test deleting a strain successfully."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.remove_strain = AsyncMock()
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_manage_strain_library(
        {"action": "delete_strain", "strain_id": "test_strain"}
    )
    assert result["type"] == "form"
    coordinator.strain_library.remove_strain.assert_called_once_with("test_strain")


async def test_async_step_manage_strain_library_post_delete_fail(
    handler: StrainConfigHandler,
) -> None:
    """Test deleting a strain failure."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.remove_strain = AsyncMock(side_effect=Exception("Error"))
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_manage_strain_library(
        {"action": "delete_strain", "strain_id": "test_strain"}
    )
    assert result["type"] == "form"
    handler.flow.async_show_form.assert_called_with(
        step_id="manage_strain_library",
        data_schema=ANY,
        errors={"base": "delete_failed"},
    )


async def test_async_step_manage_strain_library_post_import(
    handler: StrainConfigHandler,
) -> None:
    """Test routing to import."""
    handler.async_step_import_strain_library = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library({"action": "import"})
    assert result["type"] == "form"


async def test_async_step_manage_strain_library_post_export(
    handler: StrainConfigHandler,
) -> None:
    """Test routing to export."""
    handler.async_step_export_strain_library = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library({"action": "export"})
    assert result["type"] == "form"


async def test_async_step_manage_strain_library_post_back(
    handler: StrainConfigHandler,
) -> None:
    """Test routing back."""
    handler.flow.async_step_init = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library({"action": "back"})
    assert result["type"] == "form"


async def test_async_step_import_strain_library_success(
    handler: StrainConfigHandler,
) -> None:
    """Test importing successfully."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.import_library_from_zip = AsyncMock()
    coordinator.strain_library.async_load = AsyncMock()
    handler.async_step_manage_strain_library = AsyncMock(return_value={"type": "form"})

    result = await handler.async_step_import_strain_library({"file_path": "test.zip"})
    assert result["type"] == "form"
    coordinator.strain_library.import_library_from_zip.assert_called_once_with(
        "test.zip", merge=True
    )


async def test_async_step_import_strain_library_no_entry(mock_hass: MagicMock) -> None:
    """Test import with no entry."""
    handler = StrainConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_import_strain_library({"file_path": "test.zip"})
    assert result["type"] == "form"
    args = handler.flow.async_show_form.call_args[1]
    assert args["errors"] == {"base": "setup_error"}


async def test_async_step_import_strain_library_errors(
    handler: StrainConfigHandler,
) -> None:
    """Test import error cases."""
    coordinator = handler.config_entry.runtime_data
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    # FileNotFoundError
    coordinator.strain_library.import_library_from_zip = AsyncMock(
        side_effect=FileNotFoundError
    )
    await handler.async_step_import_strain_library({"file_path": "test.zip"})
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "file_not_found"
    }

    # ValueError
    coordinator.strain_library.import_library_from_zip = AsyncMock(
        side_effect=ValueError
    )
    await handler.async_step_import_strain_library({"file_path": "test.zip"})
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "invalid_zip"
    }

    # Generic Exception
    coordinator.strain_library.import_library_from_zip = AsyncMock(
        side_effect=Exception
    )
    await handler.async_step_import_strain_library({"file_path": "test.zip"})
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "import_failed"
    }


async def test_async_step_export_strain_library_success(
    handler: StrainConfigHandler,
) -> None:
    """Test exporting successfully."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.export_library_to_zip = AsyncMock(
        return_value="/path/to/zip"
    )
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_export_strain_library()
    assert result["type"] == "form"
    coordinator.strain_library.export_library_to_zip.assert_called_once()
    assert (
        handler.flow.async_show_form.call_args[1]["description_placeholders"]["path"]
        == "/path/to/zip"
    )


async def test_async_step_export_strain_library_post(
    handler: StrainConfigHandler,
) -> None:
    """Test post from export screen."""
    handler.async_step_manage_strain_library = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_export_strain_library({"some": "input"})
    assert result["type"] == "form"


async def test_async_step_export_strain_library_no_entry(mock_hass: MagicMock) -> None:
    """Test export with no entry."""
    handler = StrainConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_export_strain_library()
    assert result["type"] == "abort"


async def test_async_step_export_strain_library_fail(
    handler: StrainConfigHandler,
) -> None:
    """Test export failure."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.export_library_to_zip = AsyncMock(side_effect=Exception)
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_export_strain_library()
    assert result["type"] == "abort"
    assert handler.flow.async_abort.call_args[1]["reason"] == "export_failed"


async def test_async_step_add_strain_success(handler: StrainConfigHandler) -> None:
    """Test adding a strain successfully."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.async_add_strain = AsyncMock()
    handler.async_step_manage_strain_library = AsyncMock(return_value={"type": "form"})

    user_input = {
        "strain": "Test Strain",
        "breeder": "Test Breeder",
        "type": "Indica",
        "sex": "Feminized",
        "description": "Desc",
        "flower_days_max": 60,
    }
    result = await handler.async_step_add_strain(user_input)
    assert result["type"] == "form"
    coordinator.strain_library.async_add_strain.assert_called_once()


async def test_async_step_add_strain_no_entry(mock_hass: MagicMock) -> None:
    """Test add strain with no entry."""
    handler = StrainConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_add_strain()
    assert result["type"] == "abort"


async def test_async_step_edit_strain(handler: StrainConfigHandler) -> None:
    """Test edit strain flow."""
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_edit_strain()
    assert result["type"] == "form"

    handler.async_step_manage_strain_library = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_edit_strain({"some": "input"})
    assert result["type"] == "form"


def test_get_strain_library_menu_schema_no_strains(
    handler: StrainConfigHandler,
) -> None:
    """Test schema when no strains are present."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.get_all.return_value = {}

    schema = handler._get_strain_library_menu_schema(coordinator)
    assert isinstance(schema, vol.Schema)
    # Action should still be present
    assert "action" in schema.schema


def test_get_strain_library_menu_schema_no_library(
    handler: StrainConfigHandler,
) -> None:
    """Test schema when library is missing."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library = None

    schema = handler._get_strain_library_menu_schema(coordinator)
    assert isinstance(schema, vol.Schema)
    assert schema.schema == {}


def test_get_strain_library_menu_schema_with_strains(
    handler: StrainConfigHandler,
) -> None:
    """Test schema when strains are present."""
    coordinator = handler.config_entry.runtime_data
    coordinator.strain_library.get_all.return_value = {"strain1": {}}

    schema = handler._get_strain_library_menu_schema(coordinator)
    assert isinstance(schema, vol.Schema)
    assert "strain_id" in schema.schema


async def test_async_step_manage_strain_library_post_delete_none(
    handler: StrainConfigHandler,
) -> None:
    """Test delete without strain_id."""
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_manage_strain_library({"action": "delete_strain"})
    assert result["type"] == "form"
    handler.flow.async_show_form.assert_called()


async def test_async_step_add_strain_get(handler: StrainConfigHandler) -> None:
    """Test add_strain GET."""
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_add_strain()
    assert result["type"] == "form"
