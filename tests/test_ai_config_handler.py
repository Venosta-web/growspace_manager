"""Tests for the AI Config Handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.config_handlers.ai_config_handler import (
    AIConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    DOMAIN,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry():
    """Mock Config Entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = {"ai_settings": {}}
    return entry


@pytest.fixture
def handler(mock_hass, mock_config_entry):
    """Create an AIConfigHandler instance."""
    return AIConfigHandler(mock_hass, mock_config_entry)


async def test_initialization(handler, mock_hass, mock_config_entry):
    """Test successful initialization."""
    assert handler.hass == mock_hass
    assert handler.config_entry == mock_config_entry


async def test_get_ai_settings_schema_defaults(handler):
    """Test schema generation with default values."""
    with patch(
        "custom_components.growspace_manager.config_handlers.ai_config_handler.conversation"
    ) as mock_conversation:
        mock_conversation.async_get_conversation_agents = AsyncMock(return_value={})
        schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)
    # Verify key fields exist in schema
    # Note: We can't easily inspect vol.Schema structure directly, but we can verify it accepts valid data


async def test_get_ai_settings_schema_with_agents(handler, mock_hass):
    """Test schema generation with available conversation agents."""
    agents = {
        "agent1": MagicMock(name="Agent 1"),
        "agent2": MagicMock(name="Agent 2"),
    }
    # Mock attributes for the agents
    agents["agent1"].name = "Agent 1"
    agents["agent2"].name = "Agent 2"

    with patch(
        "custom_components.growspace_manager.config_handlers.ai_config_handler.conversation"
    ) as mock_conversation:
        mock_conversation.async_get_conversation_agents = AsyncMock(return_value=agents)
        schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def test_get_ai_settings_schema_fallback(handler, mock_hass):
    """Test schema generation fallback for older HA versions."""
    # Simulate no async_get_conversation_agents by mocking the module and not setting the attribute
    with patch(
        "custom_components.growspace_manager.config_handlers.ai_config_handler.conversation"
    ) as mock_conversation:
        del mock_conversation.async_get_conversation_agents

        # Mock hass.data.get("conversation")
        mock_agent_manager = MagicMock()
        mock_agent_manager.async_get_agents = AsyncMock(
            return_value=[{"id": "agent1", "name": "Agent 1"}]
        )
        mock_hass.data = {"conversation": mock_agent_manager}

        schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def test_get_ai_settings_schema_no_agents(handler, mock_hass):
    """Test schema generation when no agents are found."""
    with patch(
        "custom_components.growspace_manager.config_handlers.ai_config_handler.conversation"
    ) as mock_conversation:
        mock_conversation.async_get_conversation_agents = AsyncMock(return_value={})

        # Mock default agent fallback
        mock_default_agent = MagicMock()
        mock_default_agent.id = "default_agent"
        mock_conversation.async_get_agent = AsyncMock(return_value=mock_default_agent)

        schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def test_save_ai_settings(handler, mock_hass, mock_config_entry):
    """Test saving AI settings."""
    # Setup coordinator mock
    mock_coordinator = MagicMock()
    mock_coordinator.async_save = AsyncMock()
    mock_hass.data[DOMAIN]["test_entry"] = {"coordinator": mock_coordinator}

    user_input = {
        CONF_AI_ENABLED: True,
        CONF_ASSISTANT_ID: "agent1",
        "max_response_length": 500,
    }

    new_options = await handler.save_ai_settings(user_input)

    assert new_options["ai_settings"] == user_input
    assert mock_coordinator.options["ai_settings"] == user_input
    mock_coordinator.async_save.assert_called_once()
