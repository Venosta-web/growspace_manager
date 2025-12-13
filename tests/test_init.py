"""Tests for the initialization and unloading of the Growspace Manager integration.

This file contains tests to ensure that the integration can be successfully set up
and unloaded within Home Assistant.
"""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import BodyPartReader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager import (
    StrainLibraryUploadView,
    _async_update_listener,
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
    register_services,
)
from custom_components.growspace_manager.const import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_GROWSPACE_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    ADD_PLANT_SCHEMA,
    ADD_STRAIN_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    DEBUG_CLEANUP_LEGACY_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    DOMAIN,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
    UPDATE_GROWSPACE_SCHEMA,
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
    hass.http = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_remove = MagicMock()
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
async def test_async_setup(mock_hass) -> None:
    """Test async_setup registers global components."""
    with (
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ) as mock_lib_cls,
        patch(
            "custom_components.growspace_manager.register_services",
            return_value=AsyncMock(),
        ) as mock_reg,
        patch(
            "custom_components.growspace_manager.websocket_api.async_register_command"
        ) as mock_ws_reg,
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            return_value=AsyncMock(),
        ),
    ):
        mock_lib = mock_lib_cls.return_value
        assert await async_setup(mock_hass, {})

        # Verify StrainLibrary init
        mock_lib_cls.assert_called_once_with(mock_hass)
        mock_lib.async_setup.assert_called_once()
        assert mock_hass.data[DOMAIN]["strain_library"] == mock_lib

        # Verify View registration
        mock_hass.http.register_view.assert_called_once()

        # Verify Services
        mock_reg.assert_called_once_with(mock_hass, mock_lib)

        # Verify WebSocket
        assert mock_ws_reg.call_count >= 2


@pytest.mark.asyncio
async def test_async_setup_entry(mock_hass) -> None:
    """Test a successful setup of the integration entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(mock_hass)

    # Mock global components
    mock_lib = AsyncMock()
    mock_hass.data[DOMAIN] = {"strain_library": mock_lib}

    coordinator_mock = AsyncMock()
    coordinator_mock.growspaces = {}

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
    ):
        assert await async_setup_entry(mock_hass, entry)
        # Services are NOT registered here anymore


@pytest.mark.asyncio
async def test_register_services(mock_hass, mock_strain_library_for_services) -> None:
    """Test that register_services correctly registers all services."""
    mock_hass.services.async_register = MagicMock()
    # Mock has_service to return False so services are registered
    mock_hass.services.has_service = MagicMock(return_value=False)

    # Note: Coordinator is now dynamically looked up, so simple mock verifies registration call
    await register_services(mock_hass, mock_strain_library_for_services)
    expected_services = {
        "add_growspace": ADD_GROWSPACE_SCHEMA,
        "update_growspace": UPDATE_GROWSPACE_SCHEMA,
        "remove_growspace": REMOVE_GROWSPACE_SCHEMA,
        "add_plant": ADD_PLANT_SCHEMA,
        "update_plant": UPDATE_PLANT_SCHEMA,
        "remove_plant": REMOVE_PLANT_SCHEMA,
        "move_plant": MOVE_PLANT_SCHEMA,
        "switch_plants": SWITCH_PLANT_SCHEMA,
        "transition_plant_stage": TRANSITION_PLANT_SCHEMA,
        "take_clone": TAKE_CLONE_SCHEMA,
        "move_clone": MOVE_CLONE_SCHEMA,
        "harvest_plant": HARVEST_PLANT_SCHEMA,
        "export_strain_library": EXPORT_STRAIN_LIBRARY_SCHEMA,
        "import_strain_library": IMPORT_STRAIN_LIBRARY_SCHEMA,
        "clear_strain_library": CLEAR_STRAIN_LIBRARY_SCHEMA,
        "test_notification": None,
        "debug_cleanup_legacy": DEBUG_CLEANUP_LEGACY_SCHEMA,
        "debug_list_growspaces": DEBUG_LIST_GROWSPACES_SCHEMA,
        "debug_reset_special_growspaces": DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        "debug_consolidate_duplicate_special": DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        "configure_environment": CONFIGURE_ENVIRONMENT_SCHEMA,
        "remove_environment": REMOVE_ENVIRONMENT_SCHEMA,
        "add_strain": ADD_STRAIN_SCHEMA,
        "remove_strain": REMOVE_STRAIN_SCHEMA,
        "update_strain_meta": UPDATE_STRAIN_META_SCHEMA,
        "set_dehumidifier_control": SET_DEHUMIDIFIER_CONTROL_SCHEMA,
        "set_irrigation_settings": SET_IRRIGATION_SETTINGS_SCHEMA,
        "add_irrigation_time": ADD_IRRIGATION_TIME_SCHEMA,
        "remove_irrigation_time": REMOVE_IRRIGATION_TIME_SCHEMA,
        "add_drain_time": ADD_DRAIN_TIME_SCHEMA,
        "remove_drain_time": REMOVE_DRAIN_TIME_SCHEMA,
        "get_strain_library": None,
        "ask_grow_advice": ASK_GROW_ADVICE_SCHEMA,
        "analyze_all_growspaces": ANALYZE_ALL_GROWSPACES_SCHEMA,
        "strain_recommendation": STRAIN_RECOMMENDATION_SCHEMA,
    }

    # Verify call count
    assert mock_hass.services.async_register.call_count == len(expected_services)

    # Verify each service registration
    registered_calls = mock_hass.services.async_register.call_args_list
    registered_services = {}
    for call_args in registered_calls:
        domain, service_name, _ = call_args.args
        schema = call_args.kwargs.get("schema")
        if domain == DOMAIN:
            registered_services[service_name] = schema

    for service_name, schema in expected_services.items():
        assert service_name in registered_services
        if service_name == "get_strain_library":
            continue
        assert registered_services[service_name] == schema


@pytest.mark.asyncio
async def test_async_unload_entry(mock_hass) -> None:
    """Test a successful unload of the integration entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    entry.runtime_data = MagicMock()
    entry.runtime_data.irrigation_coordinators = {}
    entry.runtime_data.dehumidifier_coordinators = {}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    # mock_hass.config_entries.async_entries.return_value = [] # Simulate no other entries

    assert await async_unload_entry(mock_hass, entry)
    # Service removal is no longer guaranteed on single entry unload as it's global
    # But unload should succeed


@pytest.mark.asyncio
async def test_async_unload_entry_failure(mock_hass) -> None:
    """Test a failure during unload."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    entry.runtime_data = MagicMock()
    entry.runtime_data.irrigation_coordinators = {}
    entry.runtime_data.dehumidifier_coordinators = {}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

    assert not await async_unload_entry(mock_hass, entry)


@pytest.mark.asyncio
async def test_async_reload_entry(mock_hass) -> None:
    """Test async_reload_entry reloads the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    mock_hass.config_entries.async_reload = AsyncMock()

    await async_reload_entry(mock_hass, entry)
    mock_hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_async_update_listener(mock_hass) -> None:
    """Test _async_update_listener reloads the config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    mock_hass.config_entries.async_reload = AsyncMock()

    await _async_update_listener(mock_hass, entry)
    mock_hass.config_entries.async_reload.assert_called_once_with(entry.entry_id)


@pytest.mark.asyncio
async def test_async_setup_entry_with_growspaces(mock_hass) -> None:
    """Test setup with existing growspaces to trigger coordinator creation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"irrigation": {"gs1": {"some": "config"}}},
        entry_id="test_entry",
    )
    entry.add_to_hass(mock_hass)

    # Mock global components
    mock_lib = AsyncMock()
    mock_hass.data[DOMAIN] = {"strain_library": mock_lib}

    coordinator_mock = AsyncMock()
    mock_gs1 = MagicMock()
    mock_gs1.irrigation_strategy.enabled = False
    coordinator_mock.growspaces = {"gs1": mock_gs1}
    coordinator_mock.irrigation_coordinators = {}
    coordinator_mock.dehumidifier_coordinators = {}

    with (
        patch("custom_components.growspace_manager.Store", return_value=AsyncMock()),
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
        patch(
            "custom_components.growspace_manager.IrrigationCoordinator"
        ) as mock_irrigation,
        patch(
            "custom_components.growspace_manager.DehumidifierCoordinator"
        ) as mock_dehumidifier,
    ):
        mock_irrigation.return_value.async_setup = AsyncMock()

        assert await async_setup_entry(mock_hass, entry)

        mock_irrigation.assert_called_once()
        mock_dehumidifier.assert_called_once()
        assert entry.runtime_data.irrigation_coordinators
        assert "gs1" in entry.runtime_data.irrigation_coordinators
        assert entry.runtime_data.dehumidifier_coordinators
        assert "gs1" in entry.runtime_data.dehumidifier_coordinators


@pytest.mark.asyncio
async def test_async_unload_entry_with_coordinators(mock_hass) -> None:
    """Test unload with irrigation and dehumidifier coordinators."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={}, entry_id="test_entry")
    entry.add_to_hass(mock_hass)

    mock_irrigation = MagicMock()
    mock_irrigation.async_cancel_listeners = MagicMock()

    mock_dehumidifier = MagicMock()
    mock_dehumidifier.unload = MagicMock()

    entry.runtime_data = MagicMock()
    entry.runtime_data.created_entity_ids = []
    entry.runtime_data.irrigation_coordinators = {"gs1": mock_irrigation}
    entry.runtime_data.dehumidifier_coordinators = {"gs1": mock_dehumidifier}
    mock_hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    assert await async_unload_entry(mock_hass, entry)

    mock_irrigation.async_cancel_listeners.assert_called_once()
    mock_dehumidifier.unload.assert_called_once()


@pytest.mark.asyncio
async def test_strain_library_upload_view(mock_hass) -> None:
    """Test StrainLibraryUploadView."""
    mock_strain_library = AsyncMock()
    mock_strain_library.import_library_from_zip = AsyncMock(return_value=5)

    # NO coordinator in init now
    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    # Test missing file
    mock_request = MagicMock()
    mock_reader = AsyncMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)
    mock_reader.next = AsyncMock(return_value=None)

    response = await view.post(mock_request)
    assert response.status == 400
    assert response.text == "No file provided or invalid type"

    # Test successful upload
    mock_field = AsyncMock(spec=BodyPartReader)
    mock_field.name = "file"
    mock_field.read_chunk = AsyncMock(side_effect=[b"some data", b""])
    mock_reader.next = AsyncMock(return_value=mock_field)

    # Mock hass.async_add_executor_job to handle mkstemp and file ops
    async def mock_executor_side_effect(target, *args):
        if target == tempfile.mkstemp:
            return (1, "mock_test.zip")
        return None

    mock_hass.async_add_executor_job = AsyncMock(side_effect=mock_executor_side_effect)

    # Mock hass.config_entries.async_entries to return list of mock entries with coordinators
    mock_entry1 = MagicMock()
    mock_entry1.state = ConfigEntryState.LOADED
    mock_coord1 = AsyncMock()
    mock_entry1.runtime_data = mock_coord1
    mock_hass.config_entries.async_entries.return_value = [mock_entry1]

    with (
        patch(
            "custom_components.growspace_manager.tempfile.mkstemp",
            side_effect=tempfile.mkstemp,
        ),
        patch("pathlib.Path.exists", return_value=True),
    ):
        response = await view.post(mock_request)

        assert response.status == 200
        body = json.loads(response.body)
        assert body["success"] is True
        assert body["imported_count"] == 5

        mock_strain_library.import_library_from_zip.assert_called_once()
        # Verify coordinator refresh requested
        mock_coord1.async_request_refresh.assert_called_once()

    # Test exception handling
    mock_reader.next = AsyncMock(return_value=mock_field)
    mock_field.read_chunk = AsyncMock(side_effect=[b"data", b""])
    mock_strain_library.import_library_from_zip.side_effect = Exception("Test Error")

    # Reset mock
    mock_strain_library.import_library_from_zip.reset_mock()
    mock_hass.async_add_executor_job = AsyncMock(side_effect=mock_executor_side_effect)

    with (
        patch("pathlib.Path.unlink"),
        patch("pathlib.Path.exists", return_value=True),
    ):
        response = await view.post(mock_request)
        assert response.status == 200
        body = json.loads(response.body)
        assert body["success"] is False
        assert body["error"] == "Test Error"
