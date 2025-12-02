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
    hass.states = MagicMock()
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


async def test_get_ai_settings_schema_defaults(handler, mock_hass):
    """Test schema generation with default values."""
    mock_hass.states.async_all.return_value = []
    schema = await handler.get_ai_settings_schema()

    assert isinstance(schema, vol.Schema)


async def test_get_ai_settings_schema_with_agents(handler, mock_hass):
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


async def test_get_ai_settings_schema_no_agents(handler, mock_hass):
    """Test schema generation when no agents are found."""
    mock_hass.states.async_all.return_value = []

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
