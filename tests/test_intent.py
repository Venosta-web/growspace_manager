"""Tests for the Growspace Manager intent handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.intent import (
    INTENT_ASK_GROW_ADVICE,
    AskGrowAdviceIntent,
    async_setup_intents,
)


@pytest.fixture
def mock_growspace():
    """Create a mock growspace."""
    gs = MagicMock()
    gs.name = "Test Growspace"
    return gs


@pytest.fixture
def mock_coordinator(mock_growspace):
    """Create a mock coordinator with a growspace."""
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    return coordinator


@pytest.fixture
def mock_hass_full(mock_coordinator):
    """Create a fully mocked hass instance for service call tests."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "coordinator": mock_coordinator,
            }
        }
    }
    return hass


@pytest.fixture
def mock_intent_obj():
    """Create a mock intent object."""
    intent_obj = MagicMock(spec=intent.Intent)
    intent_obj.slots = {
        "growspace": MagicMock(value="Test Growspace"),
        "query": MagicMock(value="How are my plants doing?"),
    }
    # Create a mock response
    mock_response = MagicMock(spec=intent.IntentResponse)
    intent_obj.create_response.return_value = mock_response
    return intent_obj


# =============================================================================
# Tests for async_setup_intents
# =============================================================================


class TestAsyncSetupIntents:
    """Tests for async_setup_intents function."""

    @pytest.mark.asyncio
    async def test_registers_intent_handler(self, hass: HomeAssistant):
        """Test that the intent handler is registered."""
        with patch.object(intent, "async_register") as mock_register:
            await async_setup_intents(hass)

            mock_register.assert_called_once()
            # Verify the handler is an AskGrowAdviceIntent instance
            call_args = mock_register.call_args
            assert call_args[0][0] is hass
            assert isinstance(call_args[0][1], AskGrowAdviceIntent)


# =============================================================================
# Tests for AskGrowAdviceIntent
# =============================================================================


class TestAskGrowAdviceIntent:
    """Tests for AskGrowAdviceIntent class."""

    def test_init(self, hass: HomeAssistant):
        """Test intent handler initialization."""
        handler = AskGrowAdviceIntent(hass)
        assert handler.hass is hass
        assert handler.intent_type == INTENT_ASK_GROW_ADVICE

    def test_slot_schema(self, hass: HomeAssistant):
        """Test slot schema is defined correctly."""
        handler = AskGrowAdviceIntent(hass)
        assert "growspace" in str(handler.slot_schema)

    @pytest.mark.asyncio
    async def test_async_handle_success(self, mock_hass_full, mock_intent_obj):
        """Test successful intent handling with response."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        # Configure service call response
        mock_hass_full.services.async_call.return_value = {
            "response": "Your plants are doing great!"
        }

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
                "query": {"value": "How are my plants?"},
            },
        ):
            response = await handler.async_handle(mock_intent_obj)

            # Verify service was called correctly
            mock_hass_full.services.async_call.assert_awaited_once_with(
                DOMAIN,
                "ask_grow_advice",
                {"growspace_id": "gs1", "user_query": "How are my plants?"},
                blocking=True,
                return_response=True,
            )

            # Verify response was set
            mock_intent_obj.create_response.assert_called_once()
            response.async_set_speech.assert_called_once_with(
                "Your plants are doing great!"
            )

    @pytest.mark.asyncio
    async def test_async_handle_without_query(self, mock_hass_full, mock_intent_obj):
        """Test intent handling without optional query."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        mock_hass_full.services.async_call.return_value = {
            "response": "General advice here."
        }

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            await handler.async_handle(mock_intent_obj)

            # Verify service was called without user_query
            mock_hass_full.services.async_call.assert_awaited_once_with(
                DOMAIN,
                "ask_grow_advice",
                {"growspace_id": "gs1"},
                blocking=True,
                return_response=True,
            )

    @pytest.mark.asyncio
    async def test_async_handle_growspace_not_found(
        self, mock_hass_full, mock_intent_obj
    ):
        """Test intent handling when growspace is not found."""
        # Set up mock with no growspaces
        mock_hass_full.data[DOMAIN]["test_entry"]["coordinator"].growspaces = {}

        handler = AskGrowAdviceIntent(mock_hass_full)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Nonexistent Growspace"},
            },
        ):
            with pytest.raises(intent.IntentHandleError) as exc_info:
                await handler.async_handle(mock_intent_obj)

            assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_handle_no_domain_data(self, mock_intent_obj):
        """Test intent handling when domain data is missing."""
        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.data = {}  # No domain data

        handler = AskGrowAdviceIntent(mock_hass)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            with pytest.raises(intent.IntentHandleError) as exc_info:
                await handler.async_handle(mock_intent_obj)

            assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_handle_entry_not_dict(self, mock_intent_obj):
        """Test intent handling when entry data is not a dict."""
        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.data = {
            DOMAIN: {
                "test_entry": "not_a_dict",
            }
        }

        handler = AskGrowAdviceIntent(mock_hass)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            with pytest.raises(intent.IntentHandleError) as exc_info:
                await handler.async_handle(mock_intent_obj)

            assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_handle_no_coordinator_key(self, mock_intent_obj):
        """Test intent handling when coordinator key is missing."""
        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.data = {
            DOMAIN: {
                "test_entry": {"other_key": "value"},
            }
        }

        handler = AskGrowAdviceIntent(mock_hass)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            with pytest.raises(intent.IntentHandleError) as exc_info:
                await handler.async_handle(mock_intent_obj)

            assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_handle_case_insensitive_match(
        self, mock_hass_full, mock_intent_obj
    ):
        """Test growspace name matching is case-insensitive."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        mock_hass_full.services.async_call.return_value = {"response": "Found it!"}

        # Use different case in query
        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "test growspace"},  # lowercase
            },
        ):
            await handler.async_handle(mock_intent_obj)

            # Should still find the growspace
            mock_hass_full.services.async_call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_handle_empty_response(self, mock_hass_full, mock_intent_obj):
        """Test handling when service returns empty response."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        # Service returns empty dict
        mock_hass_full.services.async_call.return_value = {}

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            response = await handler.async_handle(mock_intent_obj)

            # Should use fallback message
            response.async_set_speech.assert_called_once_with(
                "I couldn't get a response from the grow assistant."
            )

    @pytest.mark.asyncio
    async def test_async_handle_none_response(self, mock_hass_full, mock_intent_obj):
        """Test handling when service returns None."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        mock_hass_full.services.async_call.return_value = None

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            response = await handler.async_handle(mock_intent_obj)

            response.async_set_speech.assert_called_once_with(
                "I couldn't get a response from the grow assistant."
            )

    @pytest.mark.asyncio
    async def test_async_handle_service_exception(
        self, mock_hass_full, mock_intent_obj
    ):
        """Test handling when service call raises exception."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        mock_hass_full.services.async_call.side_effect = Exception("Service error")

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            with pytest.raises(intent.IntentHandleError) as exc_info:
                await handler.async_handle(mock_intent_obj)

            assert "Error getting advice" in str(exc_info.value)
            assert "Service error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_handle_multiple_coordinators(self, mock_intent_obj):
        """Test finding growspace across multiple coordinators."""
        # First coordinator doesn't have the growspace
        mock_gs1 = MagicMock()
        mock_gs1.name = "Other Growspace"

        # Second coordinator has it
        mock_gs2 = MagicMock()
        mock_gs2.name = "Test Growspace"

        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock(
            return_value={"response": "Found in second coordinator!"}
        )
        mock_hass.data = {
            DOMAIN: {
                "entry1": {
                    "coordinator": MagicMock(growspaces={"other": mock_gs1}),
                },
                "entry2": {
                    "coordinator": MagicMock(growspaces={"target": mock_gs2}),
                },
            }
        }

        handler = AskGrowAdviceIntent(mock_hass)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            response = await handler.async_handle(mock_intent_obj)

            # Should find growspace in second coordinator
            mock_hass.services.async_call.assert_awaited_once()
            call_args = mock_hass.services.async_call.call_args
            # Verify it found the 'target' growspace
            service_data = call_args[0][2]
            assert service_data["growspace_id"] == "target"

    @pytest.mark.asyncio
    async def test_async_handle_with_user_query_value(
        self, mock_hass_full, mock_intent_obj
    ):
        """Test user query is properly extracted and passed."""
        handler = AskGrowAdviceIntent(mock_hass_full)

        mock_hass_full.services.async_call.return_value = {"response": "Query response"}

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
                "query": {"value": "What nutrients should I use?"},
            },
        ):
            await handler.async_handle(mock_intent_obj)

            call_args = mock_hass_full.services.async_call.call_args
            service_data = call_args[0][2]
            assert service_data["user_query"] == "What nutrients should I use?"

    @pytest.mark.asyncio
    async def test_async_handle_breaks_on_first_match(self, mock_intent_obj):
        """Test that search stops after finding first matching growspace."""
        # Create multiple coordinators with same-named growspace
        mock_gs1 = MagicMock()
        mock_gs1.name = "Test Growspace"

        mock_gs2 = MagicMock()
        mock_gs2.name = "Test Growspace"  # Same name, should not be reached

        mock_hass = MagicMock(spec=HomeAssistant)
        mock_hass.services = MagicMock()
        mock_hass.services.async_call = AsyncMock(return_value={"response": "Response"})
        mock_hass.data = {
            DOMAIN: {
                "entry1": {
                    "coordinator": MagicMock(growspaces={"first": mock_gs1}),
                },
                "entry2": {
                    "coordinator": MagicMock(growspaces={"second": mock_gs2}),
                },
            }
        }

        handler = AskGrowAdviceIntent(mock_hass)

        with patch.object(
            handler,
            "async_validate_slots",
            return_value={
                "growspace": {"value": "Test Growspace"},
            },
        ):
            await handler.async_handle(mock_intent_obj)

            # Should use the first matching growspace
            call_args = mock_hass.services.async_call.call_args
            service_data = call_args[0][2]
            assert service_data["growspace_id"] == "first"
