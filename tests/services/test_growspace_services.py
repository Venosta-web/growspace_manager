"""Tests for the Growspace services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import CONF_AI_ENABLED, CONF_ASSISTANT_ID
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.ai_assistant import (
    handle_ask_grow_advice,
)
from custom_components.growspace_manager.services.growspace import (
    handle_add_growspace,
    handle_remove_growspace,
    handle_update_growspace,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import Context, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def obsolete_mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator._growspace_service.add_growspace = AsyncMock(return_value="gs1")
    coordinator.async_remove_growspace = AsyncMock()
    # Mock growspaces dict
    mock_gs = MagicMock()
    mock_gs.name = "Test Growspace"
    mock_gs.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
    }
    coordinator.growspaces = {"gs1": mock_gs}
    coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "test_agent"}
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
) -> None:
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

    mock_coordinator._growspace_service.add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target="mobile_app_test"
    )
    mock_hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_handle_update_growspace(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_update_growspace service."""
    mock_call.data = {
        "growspace_id": "gs1",
        "name": "Updated GS",
        "rows": 5,
        "plants_per_row": 5,
    }

    await handle_update_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator._growspace_service.update_growspace.assert_awaited_once_with(
        growspace_id="gs1",
        name="Updated GS",
        rows=5,
        plants_per_row=5,
        notification_target=None,
    )


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_no_mobile_app_notification(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
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

    mock_coordinator._growspace_service.add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target=None
    )
    mock_coordinator._growspace_service.add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target=None
    )
    mock_hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_exception(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_add_growspace with an exception."""
    mock_call.data = {"name": "Test GS", "rows": 2, "plants_per_row": 3}
    mock_coordinator._growspace_service.add_growspace.side_effect = Exception(
        "Add failed"
    )
    mock_async_get.return_value.devices = {}

    with pytest.raises(
        ServiceValidationError, match="Failed to add growspace: Add failed"
    ):
        await handle_add_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_handle_remove_growspace(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_remove_growspace service."""
    mock_call.data = {"growspace_id": "gs1"}

    await handle_remove_growspace(mock_hass, mock_coordinator, mock_call)

    mock_coordinator.async_remove_growspace.assert_awaited_once_with("gs1")
    mock_coordinator.async_remove_growspace.assert_awaited_once_with("gs1")
    mock_hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_handle_remove_growspace_exception(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_remove_growspace with an exception."""
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.async_remove_growspace.side_effect = Exception("Remove failed")

    with pytest.raises(
        ServiceValidationError, match="Failed to remove growspace: Remove failed"
    ):
        await handle_remove_growspace(mock_hass, mock_coordinator, mock_call)


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
    new_callable=AsyncMock,
    create=True,
)
async def test_handle_ask_grow_advice_success(
    mock_converse,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_ask_grow_advice with successful response."""
    # Set up AI settings properly
    mock_coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "test_agent"},
    }
    mock_call.data = {"growspace_id": "gs1", "user_query": "How are things?"}
    # Mock growspace with environment config
    mock_gs = MagicMock()
    mock_gs.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": None,
        "vpd_sensor": None,
        "co2_sensor": None,
    }
    mock_coordinator.growspaces = {"gs1": mock_gs}

    # Mock environment sensors
    def get_state(entity_id):
        if entity_id == "sensor.temp":
            return State("sensor.temp", "25", {"unit_of_measurement": "°C"})
        if entity_id == "binary_sensor.gs1_plants_under_stress":
            return State(
                "binary_sensor.gs1_plants_under_stress",
                "on",
                {"reasons": ["Temp high"]},
            )
        return None

    mock_hass.states.get.side_effect = get_state

    # Mock LLM response
    mock_response = MagicMock()
    mock_response.response.speech = {"plain": {"speech": "Things are hot."}}
    mock_converse.return_value = mock_response

    result = await handle_ask_grow_advice(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert result["response"] == "Things are hot."
    mock_converse.assert_awaited_once()

    # Verify prompt contains sensor data
    call_args = mock_converse.call_args
    prompt = call_args.kwargs["text"]
    assert "25 °C" in prompt
    assert "STRESS DETECTED" in prompt
    assert "Temp high" in prompt


@pytest.mark.asyncio
async def test_handle_ask_grow_advice_ai_disabled(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_ask_grow_advice when AI is disabled."""
    # Set AI as disabled
    mock_coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: False},
    }
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.growspaces = {"gs1": MagicMock()}

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
) -> None:
    """Test handle_ask_grow_advice for non-existent growspace."""
    mock_call.data = {"growspace_id": "gs_invalid"}

    with pytest.raises(ServiceValidationError, match="Growspace gs_invalid not found"):
        await handle_ask_grow_advice(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.ai_assistant.conversation.async_converse",
    new_callable=AsyncMock,
    create=True,
)
async def test_handle_ask_grow_advice_llm_failure(
    mock_converse,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_ask_grow_advice when LLM returns no response."""
    # Set up AI settings properly
    mock_coordinator.options = {
        "ai_settings": {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "test_agent"},
    }
    mock_call.data = {"growspace_id": "gs1"}
    # Mock growspace with environment config
    mock_gs = MagicMock()
    mock_gs.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": None,
        "vpd_sensor": None,
        "co2_sensor": None,
    }
    mock_coordinator.growspaces = {"gs1": mock_gs}

    # Mock LLM returns None or empty response
    mock_converse.return_value = MagicMock(response=None)

    with pytest.raises(
        ServiceValidationError, match="AI assistant returned an empty response"
    ):
        await handle_ask_grow_advice(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_growspace_error(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_add_growspace with a GrowspaceError."""
    mock_call.data = {"name": "Test GS", "rows": 2, "plants_per_row": 3}
    mock_coordinator._growspace_service.add_growspace.side_effect = GrowspaceError(
        "Specific error"
    )
    mock_async_get.return_value.devices = {}

    with pytest.raises(ServiceValidationError, match="Specific error"):
        await handle_add_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_handle_update_growspace_exception(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_update_growspace with an exception."""
    mock_call.data = {"growspace_id": "gs1", "name": "Test GS"}
    mock_coordinator._growspace_service.update_growspace.side_effect = Exception(
        "Update failed"
    )

    with pytest.raises(
        ServiceValidationError, match="Failed to update growspace: Update failed"
    ):
        await handle_update_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_handle_update_growspace_growspace_error(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_update_growspace with a GrowspaceError."""
    mock_call.data = {"growspace_id": "gs1", "name": "Test GS"}
    mock_coordinator._growspace_service.update_growspace.side_effect = GrowspaceError(
        "Update error"
    )

    with pytest.raises(ServiceValidationError, match="Update error"):
        await handle_update_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_handle_remove_growspace_growspace_error(
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
) -> None:
    """Test handle_remove_growspace with a GrowspaceError."""
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.async_remove_growspace.side_effect = GrowspaceError("Remove error")

    with pytest.raises(ServiceValidationError, match="Remove error"):
        await handle_remove_growspace(mock_hass, mock_coordinator, mock_call)
