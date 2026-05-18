"""Tests for the AI Config Handler."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.ai_config_handler import (
    AIConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {"ai_settings": {}}
    return entry


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator with ServiceFacade support."""
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.save = AsyncMock()
    coordinator.options = {}
    return coordinator


@pytest.fixture
def handler(mock_hass: MagicMock, mock_config_entry: MagicMock) -> AIConfigHandler:
    """Create an AIConfigHandler instance."""
    return AIConfigHandler(mock_hass, mock_config_entry)


async def test_initialization(
    handler: AIConfigHandler, mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test successful initialization."""
    assert handler.hass == mock_hass
    assert handler.config_entry == mock_config_entry


async def testget_ai_settings_schema_defaults(
    handler: AIConfigHandler, mock_hass: MagicMock
) -> None:
    """Test schema generation with default values."""
    mock_hass.states.async_all.return_value = []
    schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def testget_ai_settings_schema_with_agents(
    handler: AIConfigHandler, mock_hass: MagicMock
) -> None:
    """Test schema generation with available conversation agents."""
    agent1 = MagicMock()
    agent1.entity_id = "conversation.agent_1"
    agent1.attributes = {"friendly_name": "Agent 1"}

    agent2 = MagicMock()
    agent2.entity_id = "conversation.agent_2"
    agent2.attributes = {"friendly_name": "Agent 2"}

    mock_hass.states.async_all.return_value = [agent1, agent2]

    schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def testget_ai_settings_schema_no_agents(
    handler: AIConfigHandler, mock_hass: MagicMock
) -> None:
    """Test schema generation when no agents are found."""
    mock_hass.states.async_all.return_value = []

    schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def test_save_ai_settings(
    handler: AIConfigHandler,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_coordinator: MagicMock,
) -> None:
    """Test saving AI settings."""
    # Update to use runtime_data
    mock_config_entry.runtime_data = mock_coordinator

    user_input = {
        CONF_AI_ENABLED: True,
        CONF_ASSISTANT_ID: "agent1",
        "max_response_length": 500,
    }

    new_options = await handler.save_ai_settings(user_input)

    assert new_options["ai_settings"] == user_input
    assert mock_coordinator.options["ai_settings"] == user_input
    mock_coordinator.services.save.assert_awaited_once()


async def test_error_cases(mock_hass: MagicMock, mock_config_entry: MagicMock) -> None:
    """Test error cases for AIConfigHandler."""
    mock_flow = MagicMock()
    mock_flow.async_abort = MagicMock(
        return_value={"type": FlowResultType.ABORT, "reason": "setup_error"}
    )

    # Test get_ai_settings_schema with None config_entry
    handler_no_entry = AIConfigHandler(mock_hass, None)
    handler_no_entry.flow = mock_flow
    schema = await handler_no_entry.get_ai_settings_schema()
    assert isinstance(schema, vol.Schema)

    # Test async_step_configure_ai with None config_entry
    result = await handler_no_entry.async_step_configure_ai()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"

    # Test async_step_configure_ai with None coordinator
    mock_config_entry.runtime_data = None
    handler_no_coord = AIConfigHandler(mock_hass, mock_config_entry)
    handler_no_coord.flow = mock_flow
    result = await handler_no_coord.async_step_configure_ai()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"

    # Test save_ai_settings with None config_entry
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler_no_entry.save_ai_settings({})

    # Test save_ai_settings with None coordinator
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler_no_coord.save_ai_settings({})


async def test_async_step_configure_ai_success(
    handler: AIConfigHandler,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_coordinator: MagicMock,
) -> None:
    """Test successful AI configuration step."""
    mock_config_entry.runtime_data = mock_coordinator

    mock_flow = MagicMock()
    mock_flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    handler.flow = mock_flow

    user_input = {
        CONF_AI_ENABLED: True,
        CONF_ASSISTANT_ID: "agent1",
        "max_response_length": 500,
    }

    result = await handler.async_step_configure_ai(user_input)

    assert result["type"] == "create_entry"
    mock_coordinator.services.save.assert_awaited_once()


async def test_async_step_configure_ai_validation_error(
    handler: AIConfigHandler, mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test validation error in AI configuration step."""
    mock_coordinator = MagicMock()
    mock_config_entry.runtime_data = mock_coordinator

    mock_flow = MagicMock()
    mock_flow.async_show_form = MagicMock(return_value={"type": "form"})
    handler.flow = mock_flow

    # AI enabled but no assistant selected
    user_input = {
        CONF_AI_ENABLED: True,
        CONF_ASSISTANT_ID: None,
    }

    result = await handler.async_step_configure_ai(user_input)

    assert result["type"] == FlowResultType.FORM
    mock_flow.async_show_form.assert_called_once()
    args = mock_flow.async_show_form.call_args[1]
    assert args["errors"] == {"base": "assistant_required"}


async def test_async_step_configure_ai_disabled(
    handler: AIConfigHandler,
    mock_hass: MagicMock,
    mock_config_entry: MagicMock,
    mock_coordinator: MagicMock,
) -> None:
    """Test AI configuration step with AI disabled."""
    mock_config_entry.runtime_data = mock_coordinator

    mock_flow = MagicMock()
    mock_flow.async_create_entry = MagicMock(return_value=FlowResultType.CREATE_ENTRY)
    handler.flow = mock_flow

    user_input = {
        CONF_AI_ENABLED: False,
        CONF_ASSISTANT_ID: None,
    }

    result = await handler.async_step_configure_ai(user_input)

    assert result == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.save.assert_awaited_once()


async def testget_ai_settings_schema_exception(
    handler: AIConfigHandler, mock_hass: MagicMock
) -> None:
    """Test get_ai_settings_schema when an exception occurs."""
    mock_hass.states.async_all.side_effect = Exception("Test error")
    schema = await handler.get_ai_settings_schema()
    assert isinstance(schema, vol.Schema)
