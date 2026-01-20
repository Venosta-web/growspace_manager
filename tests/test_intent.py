"""Tests for the Growspace Manager intents."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.intent import (
    INTENT_ASK_GROW_ADVICE,
    GrowspaceIntentHandler,
    async_setup_intents,
)
from custom_components.growspace_manager.models import Growspace
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent

GROWSPACE_ID = "test_growspace"
GROWSPACE_NAME = "Test Growspace"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name=GROWSPACE_NAME,
        )
    }
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    # Mock config entries
    mock_entry = MagicMock()
    mock_entry.runtime_data = MagicMock()
    mock_entry.runtime_data = mock_coordinator
    hass.config_entries.async_entries.return_value = [mock_entry]
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def intent_handler(mock_hass: MagicMock) -> GrowspaceIntentHandler:
    """Fixture for GrowspaceIntentHandler."""
    return GrowspaceIntentHandler(mock_hass)


async def test_handle_intent_success(
    intent_handler: GrowspaceIntentHandler, mock_hass: MagicMock
) -> None:
    """Test successful intent handling."""
    intent_obj = intent.Intent(
        hass=mock_hass,
        platform="test_platform",
        intent_type=INTENT_ASK_GROW_ADVICE,
        slots={
            "growspace": {"value": GROWSPACE_NAME},
            "query": {"value": "How are my plants?"},
        },
        text_input=None,
        context=Context(),
        language="en",
    )

    # Mock service response
    mock_hass.services.async_call.return_value = {"response": "They are doing great!"}

    response = await intent_handler.async_handle(intent_obj)

    assert response.speech["plain"]["speech"] == "They are doing great!"
    mock_hass.services.async_call.assert_awaited_once_with(
        DOMAIN,
        "ask_grow_advice",
        {"growspace_id": GROWSPACE_ID, "user_query": "How are my plants?"},
        blocking=True,
        return_response=True,
    )


async def test_handle_intent_growspace_not_found(
    intent_handler: GrowspaceIntentHandler, mock_hass: MagicMock
) -> None:
    """Test intent handling when growspace is not found."""
    intent_obj = intent.Intent(
        hass=mock_hass,
        platform="test_platform",
        intent_type=INTENT_ASK_GROW_ADVICE,
        slots={
            "growspace": {"value": "NonExistent"},
            "query": {"value": "Query"},
        },
        text_input=None,
        context=Context(),
        language="en",
    )

    with pytest.raises(
        intent.IntentHandleError, match="Growspace 'NonExistent' not found"
    ):
        await intent_handler.async_handle(intent_obj)


async def test_handle_intent_service_error(
    intent_handler: GrowspaceIntentHandler, mock_hass: MagicMock
) -> None:
    """Test intent handling when service call fails."""
    intent_obj = intent.Intent(
        hass=mock_hass,
        platform="test_platform",
        intent_type=INTENT_ASK_GROW_ADVICE,
        slots={
            "growspace": {"value": GROWSPACE_NAME},
            "query": {"value": "Query"},
        },
        text_input=None,
        context=Context(),
        language="en",
    )

    mock_hass.services.async_call.side_effect = Exception("Service error")

    with pytest.raises(
        intent.IntentHandleError, match="Error getting advice: Service error"
    ):
        await intent_handler.async_handle(intent_obj)


async def test_handle_intent_no_response(
    intent_handler: GrowspaceIntentHandler, mock_hass: MagicMock
) -> None:
    """Test intent handling when service returns no response."""
    intent_obj = intent.Intent(
        hass=mock_hass,
        platform="test_platform",
        intent_type=INTENT_ASK_GROW_ADVICE,
        slots={
            "growspace": {"value": GROWSPACE_NAME},
            "query": {"value": "Query"},
        },
        text_input=None,
        context=Context(),
        language="en",
    )

    mock_hass.services.async_call.return_value = None

    response = await intent_handler.async_handle(intent_obj)

    assert (
        response.speech["plain"]["speech"]
        == "I couldn't get a response from the grow assistant."
    )


async def test_setup_intents(mock_hass: MagicMock) -> None:
    """Test setting up intents."""

    mock_hass.data = {}

    with patch("homeassistant.helpers.intent.async_register") as mock_register:
        # First setup
        await async_setup_intents(mock_hass)
        mock_register.assert_called_once()
        assert mock_hass.data[f"{DOMAIN}_intent_registered"] is True

        mock_register.reset_mock()

        # Second setup (should skip)
        await async_setup_intents(mock_hass)
        mock_register.assert_not_called()
