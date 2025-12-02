"""Tests for the Growspace services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import Context, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    DOMAIN,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.services.growspace import (
    handle_add_growspace,
    handle_ask_grow_advice,
    handle_remove_growspace,
)
from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.async_add_growspace = AsyncMock(return_value="gs1")
    coordinator.async_remove_growspace = AsyncMock()
    # Mock growspaces dict
    mock_gs = MagicMock()
    mock_gs.name = "Test Growspace"
    mock_gs.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2"
    }
    coordinator.growspaces = {"gs1": mock_gs}
    coordinator.options = {
        "ai_settings": {
            CONF_AI_ENABLED: True,
            CONF_ASSISTANT_ID: "test_agent"
        }
    }
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    return MagicMock(spec=StrainLibrary)


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    call.context = Context()
    return call


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace service."""
    mock_call.data = {
        "name": "Test GS",
        "rows": 2,
        "plants_per_row": 3,
        "notification_target": "mobile_app_test",
    }
    mock_device = MagicMock()
    mock_device.name = "mobile_app_test"
    mock_device.config_entries = {"mobile_app_test"}
    mock_async_get.return_value.devices = {"device_id": mock_device}

    await handle_add_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target="mobile_app_test"
    )
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_added", {"growspace_id": "gs1", "name": "Test GS"}
    )


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_no_mobile_app_notification(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace when notification_target is not a mobile app."""
    mock_call.data = {
        "name": "Test GS",
        "rows": 2,
        "plants_per_row": 3,
        "notification_target": "non_existent_mobile_app",
    }
    mock_async_get.return_value.devices = {}  # No mobile devices registered

    await handle_add_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target=None
    )
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_added", {"growspace_id": "gs1", "name": "Test GS"}
    )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.create_notification"
)
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_exception(
    mock_async_get,
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace with an exception."""
    mock_call.data = {"name": "Test GS", "rows": 2, "plants_per_row": 3}
    mock_coordinator.async_add_growspace.side_effect = Exception("Add failed")
    mock_async_get.return_value.devices = {}

    with pytest.raises(Exception, match="Add failed"):
        await handle_add_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
async def test_handle_remove_growspace(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_remove_growspace service."""
    mock_call.data = {"growspace_id": "gs1"}

    await handle_remove_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_remove_growspace.assert_awaited_once_with("gs1")
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_removed", {"growspace_id": "gs1"}
    )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.create_notification"
)
async def test_handle_remove_growspace_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_remove_growspace with an exception."""
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.async_remove_growspace.side_effect = Exception("Remove failed")

    with pytest.raises(Exception, match="Remove failed"):
        await handle_remove_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.conversation.async_process",
    new_callable=AsyncMock,
    create=True,
)
async def test_handle_ask_grow_advice_success(
    mock_process,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_ask_grow_advice with successful response."""
    mock_call.data = {"growspace_id": "gs1", "user_query": "How are things?"}

    # Mock environment sensors
    def get_state(entity_id):
        if entity_id == "sensor.temp":
            return State("sensor.temp", "25", {"unit_of_measurement": "°C"})
        if entity_id == "binary_sensor.growspace_manager_gs1_stress":
             return State("binary_sensor.growspace_manager_gs1_stress", "on", {"reasons": ["Temp high"]})
        return None
    mock_hass.states.get.side_effect = get_state

    # Mock LLM response
    mock_response = MagicMock()
    mock_response.response.speech = {"plain": {"speech": "Things are hot."}}
    mock_process.return_value = mock_response

    result = await handle_ask_grow_advice(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert result["response"] == "Things are hot."
    mock_process.assert_awaited_once()

    # Verify prompt contains sensor data
    call_args = mock_process.call_args
    prompt = call_args.kwargs["text"]
    assert "25 °C" in prompt
    assert "Stress: Temp high" in prompt


@pytest.mark.asyncio
async def test_handle_ask_grow_advice_ai_disabled(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_ask_grow_advice when AI is disabled."""
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.options["ai_settings"][CONF_AI_ENABLED] = False

    with pytest.raises(
        ServiceValidationError,
        match="AI assistant is not enabled. Please go to the Growspace Manager integration settings to enable it.",
    ):
        await handle_ask_grow_advice(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_handle_ask_grow_advice_growspace_not_found(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_ask_grow_advice for non-existent growspace."""
    mock_call.data = {"growspace_id": "gs_invalid"}

    with pytest.raises(ServiceValidationError, match="Growspace gs_invalid not found"):
        await handle_ask_grow_advice(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.conversation.async_process",
    new_callable=AsyncMock,
    create=True,
)
async def test_handle_ask_grow_advice_llm_failure(
    mock_process,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_ask_grow_advice when LLM returns no response."""
    mock_call.data = {"growspace_id": "gs1"}

    # Mock LLM returns None or empty response
    mock_process.return_value = MagicMock(response=None)

    result = await handle_ask_grow_advice(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert result["response"] == "Sorry, I couldn't generate advice at this time."
