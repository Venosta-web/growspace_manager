from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.notification_config_handler import (
    NotificationConfigHandler,
)
from custom_components.growspace_manager.config_handlers.strain_config_handler import (
    StrainConfigHandler,
)
from homeassistant.data_entry_flow import FlowResultType


@pytest.mark.asyncio
async def test_notification_flow_missing_entry() -> None:
    """Test handling of missing config entry."""
    handler = NotificationConfigHandler()
    handler.config_entry = None

    # Mock flow context
    handler.flow = MagicMock()
    handler.flow.async_abort.return_value = {"type": FlowResultType.ABORT}

    result = await handler.async_step_manage_timed_notifications()
    assert result["type"] == FlowResultType.ABORT

    result = await handler.async_step_add_timed_notification()
    assert result["type"] == FlowResultType.ABORT

    result = await handler.async_step_edit_timed_notification()
    assert result["type"] == FlowResultType.ABORT

    result = await handler.async_step_delete_timed_notification()
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_notification_flow_missing_coordinator() -> None:
    """Test handling of missing coordinator."""
    handler = NotificationConfigHandler()
    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data = None

    handler.flow = MagicMock()
    handler.flow.async_abort.return_value = {"type": FlowResultType.ABORT}

    result = await handler.async_step_manage_timed_notifications()
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_notification_flow_edit_missing_id() -> None:
    """Test editing a non-existent notification."""
    handler = NotificationConfigHandler()
    coordinator = MagicMock()
    coordinator.get_timed_notifications.return_value = []

    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data = coordinator

    handler.flow = MagicMock()
    handler.flow.selected_notification_id = "missing_id"
    handler.flow.async_abort.return_value = {"type": FlowResultType.ABORT}

    result = await handler.async_step_edit_timed_notification()
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_strain_flow_missing_entry() -> None:
    """Test handling of missing config entry/coordinator in strain handler."""
    handler = StrainConfigHandler()
    handler.config_entry = None
    handler.flow = MagicMock()
    handler.flow.async_abort.return_value = {"type": FlowResultType.ABORT}

    result = await handler.async_step_manage_strain_library()
    assert result["type"] == FlowResultType.ABORT

    result = await handler.async_step_add_strain()
    assert result["type"] == FlowResultType.ABORT

    result = await handler.async_step_export_strain_library()
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_strain_flow_delete_error() -> None:
    """Test error handling during strain deletion."""
    handler = StrainConfigHandler()
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.config.strain_library = MagicMock()
    coordinator.services.config.strain_library.remove_strain = AsyncMock(
        side_effect=Exception("Del error")
    )
    coordinator.services.config.strain_library.get_all.return_value = {}

    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data = coordinator

    handler.flow = MagicMock()
    handler.flow.async_show_form.return_value = {"type": FlowResultType.FORM}

    user_input = {"action": "delete_strain", "strain_id": "s1"}
    await handler.async_step_manage_strain_library(user_input)

    # Should show form with error
    call_args = handler.flow.async_show_form.call_args[1]
    assert call_args["errors"] == {"base": "delete_failed"}


@pytest.mark.asyncio
async def test_strain_flow_import_exceptions() -> None:
    """Test exception handling during import."""
    handler = StrainConfigHandler()
    handler.config_entry = MagicMock()

    # 1. FileNotFoundError
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.config.strain_library = MagicMock()
    coordinator.services.config.strain_library.import_library_from_zip = AsyncMock(
        side_effect=FileNotFoundError
    )
    handler.config_entry.runtime_data = coordinator

    handler.flow = MagicMock()
    handler.flow.async_show_form.return_value = {"type": FlowResultType.FORM}

    user_input = {"file_path": "badconfig.zip"}
    await handler.async_step_import_strain_library(user_input)
    assert (
        handler.flow.async_show_form.call_args[1]["errors"]["base"] == "file_not_found"
    )

    # 2. ValueError (invalid zip)
    coordinator.services.config.strain_library.import_library_from_zip = AsyncMock(
        side_effect=ValueError
    )
    await handler.async_step_import_strain_library(user_input)
    assert handler.flow.async_show_form.call_args[1]["errors"]["base"] == "invalid_zip"

    # 3. Generic Exception
    coordinator.services.config.strain_library.import_library_from_zip = AsyncMock(
        side_effect=Exception("Boom")
    )
    await handler.async_step_import_strain_library(user_input)
    assert (
        handler.flow.async_show_form.call_args[1]["errors"]["base"] == "import_failed"
    )
