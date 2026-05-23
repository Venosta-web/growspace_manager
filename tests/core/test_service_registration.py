"""Tests for service registration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import GrowspaceError
import custom_components.growspace_manager.service_registration as service_registration_module
from custom_components.growspace_manager.service_registration import register_services
from custom_components.growspace_manager.services._definition import ServiceDefinition
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


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
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.config_entries.async_entries.return_value = [mock_config_entry]

    strain_lib = MagicMock()
    captured_wrapper = None

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        nonlocal captured_wrapper
        if service == "add_strain":
            captured_wrapper = handler

    hass.services.async_register.side_effect = capture_register

    strain_lib.add_strain = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        # Use strict kwargs, NO 'hass' argument here!
        call = ServiceCall(
            hass, domain=DOMAIN, service="add_strain", data={"strain": "Test Strain"}
        )
        await captured_wrapper(call)

        strain_lib.add_strain.assert_called_once()


async def test_service_wrapper_execution_no_strain_lib(
    mock_config_entry, mock_coordinator
) -> None:
    """Test wrapper for services that do not need strain library."""
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

    # Mock the CORRECT async method that the handler actually awaits!
    mock_coordinator.services.growspaces.remove_growspace = AsyncMock()

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        call = ServiceCall(
            hass,
            domain=DOMAIN,
            service="remove_growspace",
            data={"growspace_id": "gs1"},
        )
        await captured_wrapper(call)

        mock_coordinator.services.growspaces.remove_growspace.assert_called_once_with("gs1")


async def test_service_wrapper_error_handling(
    mock_config_entry, mock_coordinator
) -> None:
    """Test that GrowspaceError is caught and raised as ServiceValidationError."""
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

    # Throw the error from the correct async method
    mock_coordinator.services.growspaces.remove_growspace = AsyncMock(
        side_effect=GrowspaceError("Test error")
    )

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_entries",
        return_value=[mock_config_entry],
    ):
        await register_services(hass, strain_lib)

        assert captured_wrapper is not None

        call = ServiceCall(
            hass,
            domain=DOMAIN,
            service="remove_growspace",
            data={"growspace_id": "gs1"},
        )

        # Match the "Test error" text that is bubbled up
        with pytest.raises(ServiceValidationError, match="Test error"):
            await captured_wrapper(call)


async def test_register_services_subset_modules(hass: HomeAssistant) -> None:
    """Test that only services from the provided _SERVICE_MODULES are registered."""
    from custom_components.growspace_manager.services import plant

    strain_lib = MagicMock()

    with patch.object(service_registration_module, "_SERVICE_MODULES", [plant]):
        await register_services(hass, strain_lib)

    assert hass.services.has_service(DOMAIN, "add_plant")
    assert not hass.services.has_service(DOMAIN, "add_growspace")


async def test_register_services_handler_raises_growspace_error(
    mock_config_entry, mock_coordinator
) -> None:
    """Test that GrowspaceError raised directly by handler in _wrap_dynamic raises ServiceValidationError."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.config_entries.async_entries.return_value = [mock_config_entry]

    strain_lib = MagicMock()
    captured_wrapper = None

    def capture_register(domain, service, handler, schema=None, supports_response=None):
        nonlocal captured_wrapper
        if service == "custom_error_service":
            captured_wrapper = handler

    hass.services.async_register.side_effect = capture_register

    async def dummy_handler(hass, coordinator, call) -> None:
        raise GrowspaceError("Direct GrowspaceError")

    custom_service = ServiceDefinition(
        name="custom_error_service",
        handler=dummy_handler,
        needs_strain_lib=False,
    )

    mock_module = MagicMock()
    mock_module.SERVICES = [custom_service]

    with patch.object(service_registration_module, "_SERVICE_MODULES", [mock_module]), \
         patch("homeassistant.config_entries.ConfigEntries.async_entries", return_value=[mock_config_entry]):
        await register_services(hass, strain_lib)

    assert captured_wrapper is not None

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="custom_error_service",
        data={},
    )

    with pytest.raises(ServiceValidationError, match="Direct GrowspaceError"):
        await captured_wrapper(call)

