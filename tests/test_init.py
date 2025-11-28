"""Tests for the initialization and unloading of the Growspace Manager integration.

This file contains tests to ensure that the integration can be successfully set up
and unloaded within Home Assistant.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.helpers import entity_registry as er

from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.growspace_manager import async_setup_entry, async_unload_entry, _register_services, async_reload_entry, _async_update_listener
from custom_components.growspace_manager.const import (
    DOMAIN,
    ADD_GROWSPACE_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    ADD_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    MOVE_PLANT_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    MOVE_CLONE_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    ADD_STRAIN_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA
)
from custom_components.growspace_manager.services import (
    debug,
    environment,
    growspace,
    plant,
    strain_library as strain_library_services,
)


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.data = {}
    hass.config = MagicMock()
    hass.config.config_dir = "/config"
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_remove = AsyncMock()
    return hass

@pytest.fixture
def mock_coordinator_for_services():
    """Fixture for a mock GrowspaceCoordinator instance for service testing."""
    coordinator = MagicMock()
    return coordinator

@pytest.fixture
def mock_strain_library_for_services():
    """Fixture for a mock StrainLibrary instance for service testing."""
    strain_library = MagicMock()
    return strain_library

@pytest.mark.asyncio
async def test_async_setup_entry(mock_hass):
    """Test a successful setup of the integration entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)
    
    with patch("custom_components.growspace_manager.Store", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager.GrowspaceCoordinator", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager.StrainLibrary", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager._register_services", return_value=AsyncMock()):
        
        assert await async_setup_entry(mock_hass, entry)

@pytest.mark.asyncio
async def test_async_setup_entry_with_pending_growspace(mock_hass):
    """Test setup with a pending growspace."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)
    
    mock_hass.data[DOMAIN] = {"pending_growspace": {"name": "Test", "rows": 1, "plants_per_row": 1}}
    
    coordinator_mock = AsyncMock()
    
    with patch("custom_components.growspace_manager.Store", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager.GrowspaceCoordinator", return_value=coordinator_mock), \
         patch("custom_components.growspace_manager.StrainLibrary", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager._register_services", return_value=AsyncMock()):
        
        assert await async_setup_entry(mock_hass, entry)
        coordinator_mock.async_add_growspace.assert_called_once()

@pytest.mark.asyncio
async def test_async_setup_entry_with_pending_growspace_error(mock_hass):
    """Test setup with an error during pending growspace creation."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)
    
    mock_hass.data[DOMAIN] = {"pending_growspace": {"name": "Test"}} # Missing required fields
    
    coordinator_mock = AsyncMock()
    coordinator_mock.async_add_growspace.side_effect = KeyError("Test Error")
    
    with patch("custom_components.growspace_manager.Store", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager.GrowspaceCoordinator", return_value=coordinator_mock), \
         patch("custom_components.growspace_manager.StrainLibrary", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager._register_services", return_value=AsyncMock()), \
         patch("custom_components.growspace_manager.create_notification") as mock_create_notification:
        
        assert await async_setup_entry(mock_hass, entry)
        mock_create_notification.assert_called_once()

@pytest.mark.asyncio
async def test_register_services(
    mock_hass, mock_coordinator_for_services, mock_strain_library_for_services
):
    """Test that _register_services correctly registers all services."""
    mock_hass.services.async_register = AsyncMock()

    await _register_services(
        mock_hass, mock_coordinator_for_services, mock_strain_library_for_services
    )

    # Assertions for services_to_register
    expected_services = [
        ("add_growspace", ADD_GROWSPACE_SCHEMA),
        ("remove_growspace", REMOVE_GROWSPACE_SCHEMA),
        ("add_plant", ADD_PLANT_SCHEMA),
        ("update_plant", UPDATE_PLANT_SCHEMA),
        ("remove_plant", REMOVE_PLANT_SCHEMA),
        ("move_plant", MOVE_PLANT_SCHEMA),
        ("switch_plants", SWITCH_PLANT_SCHEMA),
        ("transition_plant_stage", TRANSITION_PLANT_SCHEMA),
        ("take_clone", TAKE_CLONE_SCHEMA),
        ("move_clone", MOVE_CLONE_SCHEMA),
        ("harvest_plant", HARVEST_PLANT_SCHEMA),
        ("export_strain_library", EXPORT_STRAIN_LIBRARY_SCHEMA),
        ("import_strain_library", IMPORT_STRAIN_LIBRARY_SCHEMA),
        ("clear_strain_library", CLEAR_STRAIN_LIBRARY_SCHEMA),
        ("test_notification", None),
        ("debug_cleanup_legacy", DEBUG_CLEANUP_LEGACY_SCHEMA),
        ("debug_list_growspaces", DEBUG_LIST_GROWSPACES_SCHEMA),
        ("debug_reset_special_growspaces", DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA),
        ("debug_consolidate_growspaces", DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA),
        ("configure_environment", CONFIGURE_ENVIRONMENT_SCHEMA),
        ("remove_environment", REMOVE_ENVIRONMENT_SCHEMA),
        ("add_strain", ADD_STRAIN_SCHEMA),
        ("remove_strain", REMOVE_STRAIN_SCHEMA),
        ("update_strain_meta", UPDATE_STRAIN_META_SCHEMA)
    ]

    # +2 for get_strain_library and ask_grow_advice
    assert mock_hass.services.async_register.call_count == len(expected_services) + 2

    registered_calls = mock_hass.services.async_register.call_args_list

    # Check each expected service
    for service_name, schema in expected_services:
        found = False
        for call_args in registered_calls:
            domain, registered_service_name, service_wrapper_mock = call_args.args
            registered_schema = call_args.kwargs.get("schema")
            if (
                domain == DOMAIN
                and registered_service_name == service_name
                and registered_schema == schema
            ):
                found = True
                break
        assert found, f"Service {service_name} not registered correctly."

    # Check get_strain_library separately
    found_get_strain_library = False
    for call_args in registered_calls:
        domain, service_name, service_wrapper_mock = call_args.args
        registered_schema = call_args.kwargs.get("schema") # Also check schema for get_strain_library
        if domain == DOMAIN and service_name == "get_strain_library":
            found_get_strain_library = True
            break
    assert found_get_strain_library, "Service get_strain_library not registered correctly."

    # Check ask_grow_advice separately
    found_ask_grow_advice = False
    for call_args in registered_calls:
        domain, service_name, service_wrapper_mock = call_args.args
        registered_schema = call_args.kwargs.get("schema")
        if domain == DOMAIN and service_name == "ask_grow_advice":
            if registered_schema == ASK_GROW_ADVICE_SCHEMA:
                found_ask_grow_advice = True
            break
    assert found_ask_grow_advice, "Service ask_grow_advice not registered correctly."
@pytest.mark.asyncio
async def test_async_unload_entry(mock_hass):
    """Test a successful unload of the integration entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)
    
    mock_hass.data[DOMAIN] = {entry.entry_id: {"created_entities": []}}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    assert await async_unload_entry(mock_hass, entry)
    assert DOMAIN not in mock_hass.data

@pytest.mark.asyncio
async def test_async_unload_entry_with_dynamic_entities(mock_hass):
    """Test unload with dynamic entities."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)
    
    entity_registry = er.async_get(mock_hass)
    entity_registry.async_get_entity_id = MagicMock(return_value="sensor.test_trend")
    entity_registry.async_get = MagicMock(return_value=True)
    entity_registry.async_remove = MagicMock()
    
    mock_hass.data[DOMAIN] = {entry.entry_id: {"created_entities": ["test_trend", "test_stats"]}}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    with patch("custom_components.growspace_manager.er.async_get", return_value=entity_registry):
        assert await async_unload_entry(mock_hass, entry)
        assert entity_registry.async_remove.call_count == 2

@pytest.mark.asyncio
async def test_async_unload_entry_with_unknown_dynamic_entities(mock_hass):
    """Test unload with an unknown dynamic entity."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)
    
    entity_registry = er.async_get(mock_hass)
    entity_registry.async_remove = MagicMock()
    
    mock_hass.data[DOMAIN] = {entry.entry_id: {"created_entities": ["test_unknown"]}}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    with patch("custom_components.growspace_manager.er.async_get", return_value=entity_registry):
        assert await async_unload_entry(mock_hass, entry)
        entity_registry.async_remove.assert_not_called()

@pytest.mark.asyncio
async def test_async_unload_entry_last_entry(mock_hass):
    """Test unload of the last entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)
    
    mock_hass.data[DOMAIN] = {entry.entry_id: {"created_entities": []}}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    
    assert await async_unload_entry(mock_hass, entry)
    assert DOMAIN not in mock_hass.data

@pytest.mark.asyncio
async def test_async_unload_entry_failure(mock_hass):
    """Test a failure during unload."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)
    
    mock_hass.data[DOMAIN] = {entry.entry_id: {"created_entities": []}}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    
    assert not await async_unload_entry(mock_hass, entry)


@pytest.mark.asyncio
async def test_async_reload_entry(mock_hass):
    """Test async_reload_entry reloads the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    mock_hass.config_entries.async_reload = AsyncMock()

    await async_reload_entry(mock_hass, entry)
    mock_hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)

@pytest.mark.asyncio
async def test_async_update_listener(mock_hass):
    """Test _async_update_listener reloads the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    mock_hass.config_entries.async_reload = AsyncMock()

    await _async_update_listener(mock_hass, entry)
    mock_hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)
