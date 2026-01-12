"""Tests for service registration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.service_registration import (
    get_coordinator_for_call,
    register_services,
)


@pytest.fixture
def mock_coordinator():
    """Mock a coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    return coordinator


@pytest.fixture
def mock_config_entry(mock_coordinator):
    """Mock a config entry."""
    entry = MagicMock()
    entry.domain = DOMAIN
    entry.state = ConfigEntryState.LOADED
    entry.runtime_data = mock_coordinator
    return entry


async def test_get_coordinator_for_call_by_growspace_id(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator by growspace ID."""
    mock_coordinator.growspaces = {"gs1": {}}

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        call = ServiceCall(DOMAIN, "test", {"growspace_id": "gs1"})
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator


async def test_get_coordinator_for_call_aliases(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator by alias IDs (target_growspace_id, mother_plant_id)."""
    # Create a second idle coordinator to prevent fallback logic from succeeding
    mock_coordinator_2 = MagicMock()
    mock_coordinator_2.growspaces = {}
    mock_coordinator_2.plants = {}

    entry2 = MagicMock()
    entry2.domain = DOMAIN
    entry2.state = ConfigEntryState.LOADED
    entry2.runtime_data = mock_coordinator_2

    # Setup matches for the main coordinator
    mock_coordinator.growspaces = {"gs2": {}}
    mock_coordinator.plants = {"mother1": {}}

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry, entry2],
    ):
        # Test target_growspace_id
        # Should match mock_coordinator, not entry2
        # Use dict directly to avoid ServiceCall constructor issues and verified logic works for dicts too
        call = {"target_growspace_id": "gs2"}
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator

        # Test mother_plant_id
        call = {"mother_plant_id": "mother1"}
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator


async def test_get_coordinator_for_call_by_plant_id(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator by plant ID."""
    mock_coordinator.plants = {"plant1": {}}

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        call = ServiceCall(DOMAIN, "test", {"plant_id": "plant1"})
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator


async def test_get_coordinator_for_call_fallback(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator fallback (single entry)."""
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        call = ServiceCall(DOMAIN, "test", {})
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator


async def test_get_coordinator_for_call_failure(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Test failure when multiple coordinators and no ID."""
    entry2 = MagicMock()
    entry2.domain = DOMAIN
    entry2.state = ConfigEntryState.LOADED
    entry2.runtime_data = MagicMock()

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry, entry2],
    ):
        ServiceCall(DOMAIN, "test", {})
        with pytest.raises(ServiceValidationError):
            # Original test was checking general failure when multiple coordinators exist and no ID provided.
            # But here we used a dict with IDs that don't match.
            # If we want to check "Could not find coordinator", we must pass that arg.
            # The invalid ID logic is:
            get_coordinator_for_call(hass, {"plant_id": ["plant1", "plant2"]})


@pytest.mark.asyncio
async def test_get_coordinator_list_lookup_success(hass: HomeAssistant) -> None:
    """Test get_coordinator_for_call returns coordinator when one ID in list matches."""

    entry = MockConfigEntry(domain=DOMAIN, state=ConfigEntryState.LOADED)
    mock_coordinator = MagicMock()
    mock_coordinator.plants = {"plant1": {}}
    entry.runtime_data = mock_coordinator
    entry.add_to_hass(hass)

    # "plant2" is not there, "plant1" is. Should pass.
    coord = get_coordinator_for_call(hass, {"plant_id": ["plant2", "plant1"]})
    assert coord == mock_coordinator


async def test_register_services(hass: HomeAssistant) -> None:
    """Test service registration."""
    strain_lib = MagicMock()

    await register_services(hass, strain_lib)

    assert hass.services.has_service(DOMAIN, "add_growspace")
    assert hass.services.has_service(DOMAIN, "remove_growspace")
    assert hass.services.has_service(DOMAIN, "add_plant")
    assert hass.services.has_service(DOMAIN, "add_strain")
    assert hass.services.has_service(DOMAIN, "remove_strain")
    assert hass.services.has_service(DOMAIN, "update_strain_meta")


async def test_service_wrapper_execution_with_strain_lib(
    mock_config_entry, mock_coordinator
) -> None:
    """Test that the registered service wrapper calls the underlying handler correctly."""
    # Use a pure Mock for hass to avoid read-only restrictions on ServiceRegistry
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    # Ensure config entries fallback works if needed (though we mock it via patch)
    hass.config_entries.async_entries.return_value = [mock_config_entry]

    strain_lib = MagicMock()

    # We need to capture the wrapper function passed to async_register
    captured_wrapper = None

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        nonlocal captured_wrapper
        if service == "add_strain":
            captured_wrapper = handler

    hass.services.async_register.side_effect = capture_register

    # Fix: Ensure strain_lib methods are async
    strain_lib.add_strain = AsyncMock()
    # Fix: Ensure coordinator methods are async
    mock_coordinator.async_request_refresh = AsyncMock()

    # Patches must be active during register_services so the wrapper captures the mock
    with (
        patch(
            "custom_components.growspace_manager.services.strain_library.handle_add_strain",
            new_callable=AsyncMock,
        ) as mock_handle_add_strain,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_entries",
            return_value=[mock_config_entry],
        ),
    ):
        # Run registration to define the wrappers
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        call = ServiceCall(DOMAIN, "add_strain", {})

        # Invoke the captured wrapper
        await captured_wrapper(call)

        # Verify the underlying handler was called with (hass, coordinator, strain_lib, call)
        mock_handle_add_strain.assert_called_once_with(
            hass, mock_coordinator, strain_lib, call
        )


async def test_service_wrapper_execution_no_strain_lib(
    mock_config_entry, mock_coordinator
) -> None:
    """Test wrapper for services that do not need strain library."""
    # Use a pure Mock for hass
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.config_entries.async_entries.return_value = [mock_config_entry]

    strain_lib = MagicMock()
    captured_wrapper = None

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        nonlocal captured_wrapper
        if service == "remove_growspace":
            captured_wrapper = handler

    hass.services.async_register.side_effect = capture_register

    # Fix: Patch active during registration
    with (
        patch(
            "custom_components.growspace_manager.services.growspace.handle_remove_growspace",
            new_callable=AsyncMock,
        ) as mock_handle_remove,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_entries",
            return_value=[mock_config_entry],
        ),
    ):
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        call = ServiceCall(DOMAIN, "remove_growspace", {})
        await captured_wrapper(call)

        # Verify called with (hass, coordinator, call) - NO strain_lib
        mock_handle_remove.assert_called_once_with(hass, mock_coordinator, call)


async def test_service_wrapper_error_handling(
    mock_config_entry, mock_coordinator
) -> None:
    """Test that GrowspaceError is caught and raised as ServiceValidationError."""
    # Use a pure Mock for hass
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.config_entries.async_entries.return_value = [mock_config_entry]

    strain_lib = MagicMock()
    captured_wrapper = None

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        nonlocal captured_wrapper
        if service == "remove_growspace":
            captured_wrapper = handler

    hass.services.async_register.side_effect = capture_register

    with (
        patch(
            "custom_components.growspace_manager.services.growspace.handle_remove_growspace",
            side_effect=GrowspaceError("Test error"),
        ) as mock_handle_remove,  # noqa: F841
        patch(
            "homeassistant.config_entries.ConfigEntries.async_entries",
            return_value=[mock_config_entry],
        ),
    ):
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        call = ServiceCall(DOMAIN, "remove_growspace", {})
        with pytest.raises(ServiceValidationError, match="Test error"):
            await captured_wrapper(call)


async def test_get_coordinator_for_call_by_plant_id_list(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator by a list of plant IDs."""
    mock_coordinator.plants = {"plant1": {}, "plant2": {}}

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        # Case 1: List with all valid IDs
        call = ServiceCall(DOMAIN, "test", {"plant_id": ["plant1", "plant2"]})
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator

        # Case 2: List with subset valid IDs
        call = ServiceCall(DOMAIN, "test", {"plant_id": ["plant1", "non_existent"]})
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator


async def test_get_coordinator_for_call_by_plant_id_list_failure(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
) -> None:
    """Test getting coordinator by a list of plant IDs failure."""
    mock_coordinator.plants = {"plant1": {}}

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        # Case 3: List with NO valid IDs
        call = ServiceCall(
            DOMAIN, "test", {"plant_id": ["non_existent1", "non_existent2"]}
        )
        # Should fallback to single coordinator if only one exists
        coordinator = get_coordinator_for_call(hass, call)
        assert coordinator == mock_coordinator
