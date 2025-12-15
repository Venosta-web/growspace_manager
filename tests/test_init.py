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
from custom_components.growspace_manager import (
    async_setup_entry,
    async_unload_entry,
    _register_services,
    async_reload_entry,
    _async_update_listener,
)
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
    UPDATE_STRAIN_META_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    ADD_DRAIN_TIME_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
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

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager._register_services",
            return_value=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(mock_hass, entry)


@pytest.mark.asyncio
async def test_async_setup_entry_with_pending_growspace(mock_hass):
    """Test setup with a pending growspace."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)

    mock_hass.data[DOMAIN] = {
        "pending_growspace": {"name": "Test", "rows": 1, "plants_per_row": 1}
    }

    coordinator_mock = AsyncMock()

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager._register_services",
            return_value=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(mock_hass, entry)
        coordinator_mock.async_add_growspace.assert_called_once()


@pytest.mark.asyncio
async def test_async_setup_entry_with_pending_growspace_error(mock_hass):
    """Test setup with an error during pending growspace creation."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)

    mock_hass.data[DOMAIN] = {
        "pending_growspace": {"name": "Test"}
    }  # Missing required fields

    coordinator_mock = AsyncMock()
    coordinator_mock.async_add_growspace.side_effect = KeyError("Test Error")

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager._register_services",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager.create_notification"
        ) as mock_create_notification,
    ):
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
        ("update_strain_meta", UPDATE_STRAIN_META_SCHEMA),
        ("set_irrigation_settings", SET_IRRIGATION_SETTINGS_SCHEMA),
        ("add_irrigation_time", ADD_IRRIGATION_TIME_SCHEMA),
        ("remove_irrigation_time", REMOVE_IRRIGATION_TIME_SCHEMA),
        ("add_drain_time", ADD_DRAIN_TIME_SCHEMA),
        ("remove_drain_time", REMOVE_DRAIN_TIME_SCHEMA),
        ("analyze_all_growspaces", ANALYZE_ALL_GROWSPACES_SCHEMA),
        ("strain_recommendation", STRAIN_RECOMMENDATION_SCHEMA),
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
        registered_schema = call_args.kwargs.get(
            "schema"
        )  # Also check schema for get_strain_library
        if domain == DOMAIN and service_name == "get_strain_library":
            found_get_strain_library = True
            break
    assert found_get_strain_library, (
        "Service get_strain_library not registered correctly."
    )

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

    mock_hass.data[DOMAIN] = {
        entry.entry_id: {"created_entities": ["test_trend", "test_stats"]}
    }
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    with patch(
        "custom_components.growspace_manager.er.async_get", return_value=entity_registry
    ):
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

    with patch(
        "custom_components.growspace_manager.er.async_get", return_value=entity_registry
    ):
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


# =============================================================================
# Tests for async_setup
# =============================================================================


@pytest.mark.asyncio
async def test_async_setup():
    """Test the async_setup function."""
    from custom_components.growspace_manager import async_setup

    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}  # websocket_api.async_register_command needs hass.data
    config = {}

    with patch(
        "custom_components.growspace_manager.websocket_api.async_register_command"
    ):
        result = await async_setup(hass, config)
    assert result is True


# =============================================================================
# Tests for irrigation coordinator cleanup during unload
# =============================================================================


@pytest.mark.asyncio
async def test_async_unload_entry_with_irrigation_coordinators(mock_hass):
    """Test unload cancels irrigation coordinator listeners."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    # Create mock irrigation coordinators
    mock_irrigation_coord1 = MagicMock()
    mock_irrigation_coord2 = MagicMock()

    mock_hass.data[DOMAIN] = {
        entry.entry_id: {
            "created_entities": [],
            "irrigation_coordinators": {
                "gs1": mock_irrigation_coord1,
                "gs2": mock_irrigation_coord2,
            },
        }
    }
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(mock_hass, entry)

    # Verify both irrigation coordinators had listeners cancelled
    mock_irrigation_coord1.async_cancel_listeners.assert_called_once()
    mock_irrigation_coord2.async_cancel_listeners.assert_called_once()


# =============================================================================
# Tests for service wrapper registration (verifying wrappers are callable)
# Note: The actual handler invocation is tested in individual service tests
# =============================================================================


@pytest.mark.asyncio
async def test_service_wrappers_are_registered(
    mock_hass, mock_coordinator_for_services, mock_strain_library_for_services
):
    """Test that service wrappers are registered and callable."""
    mock_hass.services.async_register = MagicMock()

    await _register_services(
        mock_hass, mock_coordinator_for_services, mock_strain_library_for_services
    )

    # Get all registered wrappers
    registered_calls = mock_hass.services.async_register.call_args_list

    # Verify wrappers are callable functions
    for call_args in registered_calls:
        domain, service_name, wrapper = call_args.args
        assert callable(wrapper), f"Wrapper for {service_name} is not callable"


# =============================================================================
# Tests for StrainLibraryUploadView
# =============================================================================


@pytest.mark.asyncio
async def test_strain_library_upload_view_init():
    """Test StrainLibraryUploadView initialization."""
    from custom_components.growspace_manager import StrainLibraryUploadView

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_strain_library = MagicMock()

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    assert view.hass is mock_hass
    assert view.strain_library is mock_strain_library
    assert view.url == "/api/growspace_manager/import_strains"
    assert view.requires_auth is True


@pytest.mark.asyncio
async def test_strain_library_upload_view_post_no_file():
    """Test StrainLibraryUploadView.post with no file provided."""
    from aiohttp import web
    from custom_components.growspace_manager import StrainLibraryUploadView

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_strain_library = MagicMock()

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    # Mock request with no file
    mock_request = MagicMock()
    mock_reader = MagicMock()
    mock_reader.next = AsyncMock(return_value=None)
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    response = await view.post(mock_request)

    assert response.status == 400
    assert "No file provided" in response.text


@pytest.mark.asyncio
async def test_strain_library_upload_view_post_wrong_field_name():
    """Test StrainLibraryUploadView.post with wrong field name."""
    from custom_components.growspace_manager import StrainLibraryUploadView

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_strain_library = MagicMock()

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    # Mock request with wrong field name
    mock_file_field = MagicMock()
    mock_file_field.name = "wrong_name"

    mock_reader = MagicMock()
    mock_reader.next = AsyncMock(return_value=mock_file_field)
    mock_request = MagicMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    response = await view.post(mock_request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_strain_library_upload_view_post_success():
    """Test StrainLibraryUploadView.post successful upload."""
    from custom_components.growspace_manager import StrainLibraryUploadView

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_strain_library = MagicMock()
    mock_strain_library.import_library_from_zip = AsyncMock(return_value=5)
    mock_strain_library.save = AsyncMock()

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    # Mock file field that returns chunks then None
    mock_file_field = MagicMock()
    mock_file_field.name = "file"
    mock_file_field.read_chunk = AsyncMock(side_effect=[b"test data", None])

    mock_reader = MagicMock()
    mock_reader.next = AsyncMock(return_value=mock_file_field)
    mock_request = MagicMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    with (
        patch("tempfile.NamedTemporaryFile") as mock_tempfile,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
    ):
        mock_temp = MagicMock()
        mock_temp.name = "/tmp/test.zip"
        mock_temp.__enter__ = MagicMock(return_value=mock_temp)
        mock_temp.__exit__ = MagicMock(return_value=False)
        mock_tempfile.return_value = mock_temp

        # Mock json method on view
        view.json = MagicMock(return_value=MagicMock())

        response = await view.post(mock_request)

        mock_strain_library.import_library_from_zip.assert_awaited_once()
        mock_strain_library.save.assert_awaited_once()
        mock_remove.assert_called_once()


@pytest.mark.asyncio
async def test_strain_library_upload_view_post_error():
    """Test StrainLibraryUploadView.post with import error."""
    from custom_components.growspace_manager import StrainLibraryUploadView

    mock_hass = MagicMock(spec=HomeAssistant)
    mock_strain_library = MagicMock()
    mock_strain_library.import_library_from_zip = AsyncMock(
        side_effect=Exception("Import error")
    )

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    # Mock file field
    mock_file_field = MagicMock()
    mock_file_field.name = "file"
    mock_file_field.read_chunk = AsyncMock(side_effect=[b"test data", None])

    mock_reader = MagicMock()
    mock_reader.next = AsyncMock(return_value=mock_file_field)
    mock_request = MagicMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    with (
        patch("tempfile.NamedTemporaryFile") as mock_tempfile,
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
    ):
        mock_temp = MagicMock()
        mock_temp.name = "/tmp/test.zip"
        mock_temp.__enter__ = MagicMock(return_value=mock_temp)
        mock_temp.__exit__ = MagicMock(return_value=False)
        mock_tempfile.return_value = mock_temp

        # Mock json method
        view.json = MagicMock(return_value=MagicMock())

        response = await view.post(mock_request)

        # Error response should still clean up temp file
        mock_remove.assert_called_once()
        # json should be called with error info
        view.json.assert_called()


# =============================================================================
# Tests for async_setup_entry with irrigation coordinators
# =============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_creates_irrigation_coordinators(mock_hass):
    """Test that setup creates irrigation coordinators for each growspace."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)

    mock_coordinator = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock(), "gs2": MagicMock()}

    mock_irrigation_coord = AsyncMock()

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager.IrrigationCoordinator",
            return_value=mock_irrigation_coord,
        ) as mock_irrigation_class,
        patch(
            "custom_components.growspace_manager._register_services",
            return_value=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(mock_hass, entry)

        # Should create irrigation coordinators for each growspace
        assert mock_irrigation_class.call_count == 2
        assert mock_irrigation_coord.async_setup.call_count == 2
