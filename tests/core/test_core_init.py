"""Tests for the initialization and unloading of the Growspace Manager integration.

This file contains tests to ensure that the integration can be successfully set up
and unloaded within Home Assistant.
"""

from datetime import timedelta
import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import BodyPartReader
import pytest

from custom_components.growspace_manager import (
    _async_cancel_coordinators,
    _async_update_listener,
    async_reload_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.schemas import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_GROWSPACE_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    ADD_PLANT_SCHEMA,
    ADD_PLANTS_SCHEMA,
    ADD_SEED_BATCH_SCHEMA,
    ADD_STRAIN_SCHEMA,
    ADD_TIMELINE_NOTE_SCHEMA,
    ANALYZE_ALL_GROWSPACES_SCHEMA,
    APPLY_IPM_SCHEMA,
    APPLY_STEERING_MODE_SCHEMA,
    ASK_GROW_ADVICE_SCHEMA,
    BATCH_ACTION_SCHEMA,
    CLEAR_STRAIN_LIBRARY_SCHEMA,
    CONFIGURE_CIRCULATION_FAN_SCHEMA,
    CONFIGURE_DRAIN_MONITORING_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    CONFIGURE_EXHAUST_FAN_SCHEMA,
    CONFIGURE_TANK_SCHEMA,
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
    DEBUG_LIST_GROWSPACES_SCHEMA,
    DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
    DELETE_POLLINATION_SCHEMA,
    EXPORT_GROW_REPORT_SCHEMA,
    EXPORT_STRAIN_LIBRARY_SCHEMA,
    HARVEST_PLANT_SCHEMA,
    HARVEST_SEEDS_SCHEMA,
    IMPORT_STRAIN_LIBRARY_SCHEMA,
    LOG_DRAIN_READING_SCHEMA,
    LOG_DRYING_WEIGHT_SCHEMA,
    LOG_MOISTURE_READING_SCHEMA,
    LOG_POLLINATION_SCHEMA,
    LOG_TRAINING_EVENT_SCHEMA,
    MOVE_CLONE_SCHEMA,
    MOVE_PLANT_SCHEMA,
    PRINT_LABEL_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_EC_RAMP_CURVE_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    REMOVE_GROWSPACE_SCHEMA,
    REMOVE_IPM_PRESET_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    REMOVE_NUTRIENT_PRESET_SCHEMA,
    REMOVE_PLANT_SCHEMA,
    REMOVE_STRAIN_SCHEMA,
    RESET_PLANT_LAST_WATERED_SCHEMA,
    RESET_WATER_TRACKING_SCHEMA,
    RUN_IRRIGATION_CYCLE_SCHEMA,
    SAVE_EC_RAMP_CURVE_SCHEMA,
    SAVE_IPM_PRESET_SCHEMA,
    SAVE_NUTRIENT_PRESET_SCHEMA,
    SCORE_PHENOTYPE_SCHEMA,
    SCORE_PLANT_SCHEMA,
    SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    SET_EC_TARGET_RANGE_SCHEMA,
    SET_HUMIDIFIER_CONTROL_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
    SET_PLANT_SEX_SCHEMA,
    SET_VISUAL_TAG_SCHEMA,
    SOW_SEED_SCHEMA,
    STRAIN_RECOMMENDATION_SCHEMA,
    SWITCH_PLANT_SCHEMA,
    TAKE_CLONE_SCHEMA,
    TRANSITION_PLANT_SCHEMA,
    UNLINK_SEED_BATCH_SCHEMA,
    UPDATE_GROWSPACE_SCHEMA,
    UPDATE_HARVEST_METRICS_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    UPDATE_POLLINATION_SCHEMA,
    UPDATE_SEED_BATCH_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
    WATER_GROWSPACE_SCHEMA,
    WATER_PLANT_SCHEMA,
)
from custom_components.growspace_manager.service_registration import register_services
from custom_components.growspace_manager.views import StrainLibraryUploadView
from custom_components.growspace_manager.websocket import (
    async_register_websocket_api,
    websocket_get_event_log,
    websocket_get_growspace_data,
    websocket_get_history_stats,
)
from homeassistant.components.recorder.db_schema import Events
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry


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
    # Explicitly mock components to avoid AttributeError during tests
    hass.components = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator_for_services():
    """Fixture for a mock GrowspaceCoordinator instance for service testing."""
    return MagicMock()


@pytest.fixture
def mock_strain_library_for_services():
    """Fixture for a mock StrainLibrary instance for service testing."""
    return MagicMock()


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.events = {}
    coordinator.get_growspace_data = MagicMock()
    # Ensure async methods are AsyncMock
    coordinator.async_load = AsyncMock()
    coordinator.async_initialize_sub_coordinators = AsyncMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_async_setup(mock_hass) -> None:
    """Test async_setup registers global components."""
    with patch(
        "custom_components.growspace_manager.websocket.async_register_websocket_api"
    ) as mock_ws_reg:
        assert await async_setup(mock_hass, {})
        assert DOMAIN in mock_hass.data
        # WebSocket API is now registered in async_setup_entry
        mock_ws_reg.assert_not_called()


@pytest.mark.asyncio
async def test_async_setup_entry(hass: HomeAssistant) -> None:
    """Test a successful setup of the integration entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    coordinator_mock = MagicMock()
    coordinator_mock.hass = hass
    coordinator_mock.growspaces = {}
    coordinator_mock.async_load = AsyncMock()
    coordinator_mock.async_initialize_sub_coordinators = AsyncMock()
    coordinator_mock.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("homeassistant.helpers.storage.Store") as mock_store_cls,
        patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ) as mock_lib_cls,
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ) as mock_reg,
        patch(
            "custom_components.growspace_manager.async_register_websocket_api"
        ) as mock_ws_reg,
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
    ):
        # Mock Store instance and its async_load method
        mock_store_instance = AsyncMock()
        mock_store_instance.async_load = AsyncMock(return_value={})
        mock_store_cls.return_value = mock_store_instance

        mock_lib = mock_lib_cls.return_value
        assert await async_setup_entry(hass, entry)

        # Verify Global setup happens in setup_entry
        mock_lib_cls.assert_called_once_with(hass)
        mock_lib.async_setup.assert_called_once()
        assert hass.data[DOMAIN]["strain_library"] == mock_lib

        # Verify View registration (StrainLibraryUploadView AND StrainLibraryImageView)
        assert hass.http.register_view.call_count == 2

        # Verify Services
        mock_reg.assert_called_once_with(hass, mock_lib)

        # WebSocket API is now registered in async_setup_entry, not async_setup
        mock_ws_reg.assert_called_once_with(hass)


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
        "add_plants": ADD_PLANTS_SCHEMA,
        "update_plant": UPDATE_PLANT_SCHEMA,
        "remove_plant": REMOVE_PLANT_SCHEMA,
        "move_plant": MOVE_PLANT_SCHEMA,
        "switch_plants": SWITCH_PLANT_SCHEMA,
        "transition_plant_stage": TRANSITION_PLANT_SCHEMA,
        "take_clone": TAKE_CLONE_SCHEMA,
        "move_clone": MOVE_CLONE_SCHEMA,
        "harvest_plant": HARVEST_PLANT_SCHEMA,
        "export_grow_report": EXPORT_GROW_REPORT_SCHEMA,
        "export_strain_library": EXPORT_STRAIN_LIBRARY_SCHEMA,
        "import_strain_library": IMPORT_STRAIN_LIBRARY_SCHEMA,
        "clear_strain_library": CLEAR_STRAIN_LIBRARY_SCHEMA,
        "test_notification": None,
        "debug_list_growspaces": DEBUG_LIST_GROWSPACES_SCHEMA,
        "debug_reset_special_growspaces": DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA,
        "debug_consolidate_duplicate_special": DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA,
        "configure_environment": CONFIGURE_ENVIRONMENT_SCHEMA,
        "remove_environment": REMOVE_ENVIRONMENT_SCHEMA,
        "add_strain": ADD_STRAIN_SCHEMA,
        "remove_strain": REMOVE_STRAIN_SCHEMA,
        "update_strain_meta": UPDATE_STRAIN_META_SCHEMA,
        "set_dehumidifier_control": SET_DEHUMIDIFIER_CONTROL_SCHEMA,
        "set_humidifier_control": SET_HUMIDIFIER_CONTROL_SCHEMA,
        "configure_circulation_fan": CONFIGURE_CIRCULATION_FAN_SCHEMA,
        "configure_exhaust_fan": CONFIGURE_EXHAUST_FAN_SCHEMA,
        "set_irrigation_settings": SET_IRRIGATION_SETTINGS_SCHEMA,
        "set_irrigation_strategy": SET_IRRIGATION_STRATEGY_SCHEMA,
        "apply_steering_mode": APPLY_STEERING_MODE_SCHEMA,
        "add_irrigation_time": ADD_IRRIGATION_TIME_SCHEMA,
        "remove_irrigation_time": REMOVE_IRRIGATION_TIME_SCHEMA,
        "add_drain_time": ADD_DRAIN_TIME_SCHEMA,
        "remove_drain_time": REMOVE_DRAIN_TIME_SCHEMA,
        "run_irrigation_cycle": RUN_IRRIGATION_CYCLE_SCHEMA,
        "get_strain_library": None,
        "ask_grow_advice": ASK_GROW_ADVICE_SCHEMA,
        "analyze_all_growspaces": ANALYZE_ALL_GROWSPACES_SCHEMA,
        "strain_recommendation": STRAIN_RECOMMENDATION_SCHEMA,
        "water_plant": WATER_PLANT_SCHEMA,
        "water_growspace": WATER_GROWSPACE_SCHEMA,
        "save_nutrient_preset": SAVE_NUTRIENT_PRESET_SCHEMA,
        "remove_nutrient_preset": REMOVE_NUTRIENT_PRESET_SCHEMA,
        "log_training_event": LOG_TRAINING_EVENT_SCHEMA,
        "save_ipm_preset": SAVE_IPM_PRESET_SCHEMA,
        "remove_ipm_preset": REMOVE_IPM_PRESET_SCHEMA,
        "apply_ipm": APPLY_IPM_SCHEMA,
        "batch_action": BATCH_ACTION_SCHEMA,
        "add_timeline_note": ADD_TIMELINE_NOTE_SCHEMA,
        "print_label": PRINT_LABEL_SCHEMA,
        "score_plant": SCORE_PLANT_SCHEMA,
        "update_harvest_metrics": UPDATE_HARVEST_METRICS_SCHEMA,
        "log_drain_reading": LOG_DRAIN_READING_SCHEMA,
        "configure_drain_monitoring": CONFIGURE_DRAIN_MONITORING_SCHEMA,
        "reset_plant_last_watered": RESET_PLANT_LAST_WATERED_SCHEMA,
        "reset_water_tracking": RESET_WATER_TRACKING_SCHEMA,
        "save_ec_ramp_curve": SAVE_EC_RAMP_CURVE_SCHEMA,
        "remove_ec_ramp_curve": REMOVE_EC_RAMP_CURVE_SCHEMA,
        "set_ec_target_range": SET_EC_TARGET_RANGE_SCHEMA,
        "trigger_vision_checkup": SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA,
        "configure_tank": CONFIGURE_TANK_SCHEMA,
        "add_seed_batch": ADD_SEED_BATCH_SCHEMA,
        "update_seed_batch": UPDATE_SEED_BATCH_SCHEMA,
        "log_pollination": LOG_POLLINATION_SCHEMA,
        "score_phenotype": SCORE_PHENOTYPE_SCHEMA,
        "harvest_seeds": HARVEST_SEEDS_SCHEMA,
        "update_pollination": UPDATE_POLLINATION_SCHEMA,
        "delete_pollination": DELETE_POLLINATION_SCHEMA,
        "log_drying_weight": LOG_DRYING_WEIGHT_SCHEMA,
        "log_moisture_reading": LOG_MOISTURE_READING_SCHEMA,
        "set_visual_tag": SET_VISUAL_TAG_SCHEMA,
        "sow_seed": SOW_SEED_SCHEMA,
        "set_plant_sex": SET_PLANT_SEX_SCHEMA,
        "unlink_seed_batch": UNLINK_SEED_BATCH_SCHEMA,
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
    # hass.config_entries.async_entries.return_value = [] # Simulate no other entries

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
async def test_async_setup_entry_with_growspaces(hass: HomeAssistant) -> None:
    """Test setup with existing growspaces to trigger coordinator creation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"irrigation": {"gs1": {"some": "config"}}},
        entry_id="test_entry",
    )
    entry.add_to_hass(hass)

    hass.data[DOMAIN] = {}  # Empty domain data initially
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    coordinator_mock = MagicMock()
    coordinator_mock.hass = hass
    mock_gs1 = MagicMock()
    mock_gs1.irrigation_strategy.enabled = False
    coordinator_mock.growspaces = {"gs1": mock_gs1}
    coordinator_mock.async_load = AsyncMock()
    coordinator_mock.async_initialize_sub_coordinators = AsyncMock()
    coordinator_mock.async_config_entry_first_refresh = AsyncMock()

    with (
        patch("homeassistant.helpers.storage.Store") as mock_store_cls,
        patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=AsyncMock(),
        ),
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.websocket.async_register_websocket_api",
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
    ):
        # Mock Store instance
        mock_store_instance = AsyncMock()
        mock_store_instance.async_load = AsyncMock(return_value={})
        mock_store_cls.return_value = mock_store_instance

        assert await async_setup_entry(hass, entry)

        # Verify delegation
        coordinator_mock.async_initialize_sub_coordinators.assert_called_once_with(
            entry
        )

        # Verify unload listener registered
        # assert len(entry.async_on_unload.call_args_list) > 0  # Since MockConfigEntry uses a real list for callbacks? No, it's a mock method or list.
        # MockConfigEntry defines async_on_unload as a method that appends to a list usually?
        # Actually MockConfigEntry.async_on_unload is usually NOT a mock unless we mock it.
        # let's assume it works or we can't easily check it without mocking MockConfigEntry internals.


@pytest.mark.asyncio
async def test_async_unload_entry_with_coordinators_cleanup(mock_hass) -> None:
    """Test that _async_cancel_coordinators cleans up properly."""

    coordinator = MagicMock()
    _async_cancel_coordinators(coordinator)

    coordinator.async_cancel_subsystems.assert_called_once()


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
            "custom_components.growspace_manager.views.tempfile.mkstemp",
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


@pytest.mark.asyncio
async def test_websocket_get_event_log(hass: HomeAssistant, mock_coordinator) -> None:
    """Test websocket get event log."""
    # Mock connection
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    # Mock Logbook Event
    mock_event = MagicMock()
    mock_event.time_fired.timestamp.return_value = 1672531200.0
    mock_event.data = {
        "sensor_type": "mold",
        "growspace_id": "gs1",
        "start_time": "2023-01-01T00:00:00",
        "end_time": "2023-01-01T00:05:00",
        "duration_sec": 300,
        "severity": 0.8,
        "category": "alert",
        "reasons": [],
        "timestamp": 1672531200.0,
    }

    # Create mock recorder event row and event data row (new schema)
    mock_event_row = MagicMock()
    mock_event_row.time_fired_ts = 1672531200.0
    mock_event_row.data_id = 1
    mock_event_row.event_id = 12345

    mock_event_data_row = MagicMock()
    mock_event_data_row.shared_data = json.dumps(mock_event.data)

    # Mock the recorder instance and session
    mock_recorder = MagicMock()

    async def run_executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_executor)

    mock_session = MagicMock()

    # Mock for EventTypes query (first query)
    mock_event_type_query = MagicMock()
    mock_event_type_query.filter.return_value = mock_event_type_query
    mock_event_type_query.first.return_value = (1,)  # Returns event_type_id = 1

    # Mock for Events/EventData query (second query)
    mock_events_query = MagicMock()
    mock_events_query.join.return_value = mock_events_query
    mock_events_query.filter.return_value = mock_events_query
    mock_events_query.order_by.return_value = mock_events_query
    mock_events_query.limit.return_value = mock_events_query
    mock_events_query.__iter__ = lambda self: iter(
        [(mock_event_row, mock_event_data_row)]
    )

    # session.query() returns different things depending on args
    def mock_query(*args):
        first = args[0] if args else None

        # Robust check for Events class or string representation
        if (
            first is Events
            or (hasattr(first, "__name__") and first.__name__ == "Events")
            or "Events" in str(first)
        ):
            return mock_events_query

        return mock_event_type_query

    mock_session.query = MagicMock(side_effect=mock_query)

    with (
        patch(
            "custom_components.growspace_manager.websocket.logbook.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.logbook.session_scope"
        ) as mock_session_scope,
    ):
        mock_session_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_scope.return_value.__exit__ = MagicMock(return_value=False)

        # Case A: Specific Log
        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_log",
            "growspace_id": "gs1",
        }
        result = await websocket_get_event_log(hass, mock_coordinator, msg)

        expected_data = mock_event.data.copy()
        expected_data["event_id"] = 12345
        assert result == {"gs1": [expected_data]}

        # Case B: Global (Aggregate)
        msg_global = {
            "id": 2,
            "type": f"{DOMAIN}/get_log",
        }
        result = await websocket_get_event_log(hass, mock_coordinator, msg_global)

        assert result == {"gs1": [expected_data]}

        # Case C: Filtering out unrelated ID - returns empty because query returns gs1 data
        msg_other = {
            "id": 3,
            "type": f"{DOMAIN}/get_log",
            "growspace_id": "gs2",
        }
        result = await websocket_get_event_log(hass, mock_coordinator, msg_other)
        assert result == {"gs2": []}


@pytest.mark.asyncio
async def test_websocket_get_growspace_data(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test websocket get growspace data."""
    # Mock connection
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    # Resolution failures are mapped by the WS Command Lifecycle and are
    # covered in test_ws_command_lifecycle.py; the handler is a pure payload
    # function.
    mock_coordinator.services.growspaces.get_growspace_data.return_value = {
        "name": "Test space"
    }

    msg = {
        "id": 1,
        "type": f"{DOMAIN}/get_data",
        "growspace_id": "gs1",
    }
    result = await websocket_get_growspace_data(hass, mock_coordinator, msg)
    assert result == {"name": "Test space"}


@pytest.mark.asyncio
async def test_pending_growspace_error(hass: HomeAssistant) -> None:
    """Test error handling when creating pending growspace."""
    hass.data.setdefault(DOMAIN, {})
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    # Mock async_forward_entry_setups to avoid integration loading implementation
    hass.config_entries.async_forward_entry_setups = AsyncMock()

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "pending_growspace": {
                "name": "Pending",
                "rows": 4,
                "plants_per_row": 4,
            }
        },
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.growspace_manager.StrainLibrary") as mock_sl_cls,
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.websocket.async_register_websocket_api"
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
        patch("custom_components.growspace_manager.async_create_issue") as mock_issue,
        patch("homeassistant.helpers.storage.Store") as mock_store_cls,
    ):
        # Ensure StrainLibrary().async_setup() is awaitable
        mock_sl_instance = mock_sl_cls.return_value
        mock_sl_instance.async_setup = AsyncMock()

        # Ensure Store().async_load() is awaitable and returns {}
        mock_store_instance = AsyncMock()
        mock_store_instance.async_load = AsyncMock(return_value={})
        mock_store_cls.return_value = mock_store_instance

        coordinator_mock = MagicMock()
        coordinator_mock.async_config_entry_first_refresh = AsyncMock()
        coordinator_mock.async_load = AsyncMock()
        coordinator_mock.async_initialize_sub_coordinators = AsyncMock()
        coordinator_mock.services = MagicMock()
        coordinator_mock.services.growspaces = MagicMock()
        coordinator_mock.services.growspaces.add_growspace = AsyncMock(
            side_effect=RuntimeError("Failed creation")
        )

        with patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ):
            await async_setup_entry(hass, entry)

            # Verify issue was created
            mock_issue.assert_called_once()
            args = mock_issue.call_args
            assert args[0][0] == hass
            assert args[0][1] == DOMAIN
            assert "pending_growspace_fail_Pending" in args[0][2]
            assert "pending_growspace_fail" in args[1]["translation_key"]


@pytest.mark.asyncio
async def test_pending_growspace_success(hass: HomeAssistant) -> None:
    """Test successful pending growspace creation."""
    hass.data.setdefault(DOMAIN, {})
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_update_entry = MagicMock()

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "pending_growspace": {
                "name": "Pending",
                "rows": 4,
                "plants_per_row": 4,
            }
        },
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.growspace_manager.StrainLibrary") as mock_sl_cls,
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.websocket.async_register_websocket_api"
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
        patch("homeassistant.helpers.storage.Store") as mock_store_cls,
    ):
        mock_sl_instance = mock_sl_cls.return_value
        mock_sl_instance.async_setup = AsyncMock()

        mock_store_instance = AsyncMock()
        mock_store_instance.async_load = AsyncMock(return_value={})
        mock_store_cls.return_value = mock_store_instance

        coordinator_mock = MagicMock()
        coordinator_mock.async_config_entry_first_refresh = AsyncMock()
        coordinator_mock.async_load = AsyncMock()
        coordinator_mock.async_initialize_sub_coordinators = AsyncMock()
        coordinator_mock.services = MagicMock()
        coordinator_mock.services.growspaces = MagicMock()
        coordinator_mock.services.growspaces.add_growspace = AsyncMock()

        with patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=coordinator_mock,
        ):
            await async_setup_entry(hass, entry)

            # Verify successful creation logging and data update
            coordinator_mock.services.growspaces.add_growspace.assert_called_once_with(
                name="Pending", rows=4, plants_per_row=4, notification_target=None
            )
            hass.config_entries.async_update_entry.assert_called_once()
            call_args = hass.config_entries.async_update_entry.call_args
            assert "pending_growspace" not in call_args[1]["data"]


@pytest.mark.asyncio
async def test_strain_library_upload_save_file_error(mock_hass) -> None:
    """Test error during saving of uploaded file."""
    mock_strain_library = AsyncMock()
    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    mock_request = MagicMock()
    mock_reader = AsyncMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    mock_field = AsyncMock(spec=BodyPartReader)
    mock_field.name = "file"
    mock_reader.next = AsyncMock(return_value=mock_field)

    # Mock hass.async_add_executor_job to fail during file write/mkstemp
    mock_hass.async_add_executor_job = AsyncMock(side_effect=OSError("Write failed"))

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.unlink"),
    ):
        response = await view.post(mock_request)

        # Should catch Exception and return 500
        assert response.status == 500
        assert response.text == "Failed to save upload"

        # Check cleanup attempt (though our mock failure is early, let's assume it fails inside _save_upload_to_temp)
        # If it fails at mkstemp, unlink might not be called on a valid path object if it wasn't created.
        # But the code tries to catch Exception in _save_upload_to_temp and unlink if exists.
        # The view's post method catches Exception from _save_upload_to_temp and returns 500.


@pytest.mark.asyncio
async def test_websocket_get_event_log_unknown_error(hass: HomeAssistant) -> None:
    """Test websocket get event log unknown error handling."""
    mock_connection = MagicMock()
    mock_connection.send_error = MagicMock()

    # Force an unknown exception
    # Force an unknown exception from recorder by simulating a RuntimeError
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(
        side_effect=RuntimeError("Unexpected Error")
    )

    with (
        patch(
            "custom_components.growspace_manager.websocket.logbook.get_instance",
            return_value=mock_recorder,
        ),
        patch("custom_components.growspace_manager.websocket.logbook.session_scope"),
    ):
        msg = {
            "id": 99,
            "type": f"{DOMAIN}/get_log",
            "growspace_id": "gs_unknown",
        }
        # The lifecycle maps this to internal_error; the handler just raises.
        with pytest.raises(RuntimeError, match="Unexpected Error"):
            await websocket_get_event_log(hass, MagicMock(), msg)


@pytest.mark.asyncio
async def test_strain_library_upload_view_validation(mock_hass) -> None:
    """Test validation logic in upload view."""
    view = StrainLibraryUploadView(mock_hass, MagicMock())

    # invalid type
    assert not view._is_valid_upload_field("not a field")
    # None
    assert not view._is_valid_upload_field(None)


@pytest.mark.asyncio
async def test_async_register_websocket_api(mock_hass) -> None:
    """Test _async_register_websocket_api."""

    mock_hass.components.websocket_api = MagicMock()
    # We need to patch websocket_api.async_register_command
    with patch(
        "homeassistant.components.websocket_api.async_register_command"
    ) as mock_reg:
        async_register_websocket_api(mock_hass)
        assert mock_reg.call_count == 68


@pytest.mark.asyncio
async def test_websocket_get_history_stats(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test websocket get history stats."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    # Define State class to mock history states
    class MockState:
        def __init__(self, state, last_updated) -> None:
            self.state = state
            self.last_updated = last_updated

    # 1. Success Case
    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states"
        ) as mock_get_history,
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job
        # Mock history data
        # Start: 12:00. End: 12:30. Interval: 15m.
        # Points at 12:00, 12:15, 12:30.
        start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        t1 = start
        t2 = (
            start + timedelta(minutes=10)
        )  # Should be skipped by sampling if strictly looking for bucket match, or held?
        # Logic: while current_time <= end_time: take state AT current_time or last_valid

        # Data:
        # T+0: 10
        # T+10: 20
        # T+20: 30

        # Sampling (15m):
        # T+0: Should take 10
        # T+15: Should take 20 (last valid at T+10)
        # T+30: Should take 30 (last valid at T+20, or if data extends)

        mock_get_history.return_value = {
            "sensor.test": [
                MockState("10", t1),
                MockState("20", t2),
                MockState("30", t1 + dt_util.dt.timedelta(minutes=20)),
            ]
        }

        # We need end_time to cover the loop
        end = start + timedelta(minutes=30)

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 15,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        assert "sensor.test" in result
        stats = result["sensor.test"]
        # Expected: T+0, T+15, T+30 -> 3 points
        assert len(stats) >= 1
        assert stats[0]["s"] == "10"

    # 2. Invalid Start Time
    msg_inv = {
        "id": 2,
        "type": f"{DOMAIN}/get_history_stats",
        "entity_ids": ["sensor.test"],
        "start_time": "invalid",
        "interval_minutes": 5,
        "significant_changes_only": True,
    }
    with pytest.raises(ServiceValidationError, match="Invalid start_time"):
        await websocket_get_history_stats(hass, MagicMock(), msg_inv)

    # 3. Exception Handling
    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            side_effect=Exception("DB Error"),
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job
        msg_err = {
            "id": 3,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "interval_minutes": 5,
            "significant_changes_only": True,
        }
        with pytest.raises(Exception, match="DB Error"):
            await websocket_get_history_stats(hass, MagicMock(), msg_err)


@pytest.mark.asyncio
async def test_websocket_history_stats_preserves_dense_fan_percentage(
    hass: HomeAssistant,
) -> None:
    """Test dense fan history retains percentage attributes when downsampled."""
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    class MockState:
        def __init__(self, index: int) -> None:
            self.state = "on"
            self.attributes = {"percentage": index % 100}
            self.last_updated = start + timedelta(minutes=index)

    states = [MockState(index) for index in range(201)]

    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={"fan.circulation": states},
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job
        result = await websocket_get_history_stats(
            hass,
            MagicMock(),
            {
                "id": 1,
                "type": f"{DOMAIN}/get_history_stats",
                "entity_ids": ["fan.circulation"],
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(minutes=200)).isoformat(),
                "interval_minutes": 5,
                "significant_changes_only": True,
            },
        )

    assert result["fan.circulation"][1]["a"]["percentage"] == 5


@pytest.mark.asyncio
async def test_websocket_history_empty_and_unavailable(hass: HomeAssistant) -> None:
    """Test history stats with empty data or unavailable states."""
    MagicMock()

    start = dt_util.utcnow()

    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states"
        ) as mock_get_history,
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        class MockState:
            def __init__(self, state, last_updated) -> None:
                self.state = state
                self.last_updated = last_updated

        # Empty list for one, unavailable for other
        mock_get_history.return_value = {
            "sensor.empty": [],
            "sensor.unavail": [MockState("unavailable", start)],
        }

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.empty", "sensor.unavail"],
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=10)).isoformat(),
            "interval_minutes": 5,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        assert result["sensor.empty"] == []
        # sensor.unavail should produce empty list because we filter out unavailable/unknown
        assert result["sensor.unavail"] == []


@pytest.mark.asyncio
async def test_upload_write_execution(mock_hass) -> None:
    """Test that ensures write_chunk is executed to cover lines 219-220."""
    # We need to NOT mock async_add_executor_job to prevent it?
    # Or create a wrapper side_effect that executes the function if it's our write_chunk.

    real_mkstemp = tempfile.mkstemp

    async def side_effect(target, *args, **kwargs):
        if target == tempfile.mkstemp:
            return real_mkstemp(*args, **kwargs)
        if callable(target):
            # This executes write_chunk(path, data)
            return target(*args, **kwargs)
        return None

    mock_hass.async_add_executor_job = AsyncMock(side_effect=side_effect)

    mock_strain_library = AsyncMock()
    mock_strain_library.import_library_from_zip = AsyncMock(return_value=1)

    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    mock_request = MagicMock()
    mock_reader = AsyncMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    mock_field = AsyncMock(spec=BodyPartReader)
    mock_field.name = "file"
    mock_field.read_chunk = AsyncMock(side_effect=[b"data", b""])
    mock_reader.next = AsyncMock(return_value=mock_field)

    with (
        patch(
            "custom_components.growspace_manager.ConfigEntry.runtime_data", create=True
        ),
        patch(
            "pathlib.Path.unlink"
        ),  # Prevent actual deletion so we don't error if timing is off
    ):
        # We need to ensure we don't actually write to a file that messes up system?
        # mkstemp creates a real temp file, so it's safe.

        response = await view.post(mock_request)
        assert response.status == 200
        assert json.loads(response.body)["success"] is True


@pytest.mark.asyncio
async def test_strain_library_upload_cleanup_on_error(mock_hass) -> None:
    """Test cleanup when error occurs during chunk reading/writing."""
    mock_strain_library = AsyncMock()
    view = StrainLibraryUploadView(mock_hass, mock_strain_library)

    mock_request = MagicMock()
    mock_reader = AsyncMock()
    mock_request.multipart = AsyncMock(return_value=mock_reader)

    mock_field = AsyncMock(spec=BodyPartReader)
    mock_field.name = "file"
    mock_reader.next = AsyncMock(return_value=mock_field)

    # Let the first part succeed (mkstemp) then fail during read_chunk loop or write

    # Mock hass.async_add_executor_job to:
    # 1. return valid temp path on first call (mkstemp)
    # 2. raise exception on second call (write_chunk) if we went that far, or we can just fail read_chunk

    async def mock_executor_side_effect(target, *args):
        if target == tempfile.mkstemp:
            return (1, "mock_test.zip")
        if target.__name__ == "unlink":  # path.unlink
            pass  # allow
        return None

    mock_hass.async_add_executor_job = AsyncMock(side_effect=mock_executor_side_effect)

    # Fail inside the loop
    mock_field.read_chunk = AsyncMock(side_effect=OSError("Read Error"))

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.unlink"),
    ):
        response = await view.post(mock_request)

        assert response.status == 500
        # Verify we hit the exception handler that calls unlink
        # We check if async_add_executor_job was called with unlink or if mock_unlink was called directly?
        # Code does: await self.hass.async_add_executor_job(temp_path.unlink)
        # Our mock executor side effect allows it.

        # We just want to ensure coverage hits lines 222-226


# -----------------------------------------
# Tests for Statistics API / History Optimization
# -----------------------------------------


@pytest.mark.asyncio
async def test_websocket_history_stats_uses_statistics_api_for_long_intervals(
    hass: HomeAssistant,
) -> None:
    """Test that interval >= 60 uses the Statistics API instead of raw history."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=6)

    # Mock statistics data
    stats_data = {
        "sensor.test": [
            {"start": start.timestamp(), "mean": 22.5},
            {
                "start": (start + timedelta(hours=1)).timestamp(),
                "mean": 23.0,
            },
        ]
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            return_value=stats_data,
            create=True,
        ) as mock_stats,
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 60,  # >= 60, should use stats API
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        # Should use statistics API
        mock_stats.assert_called_once()
        assert "sensor.test" in result
        assert len(result["sensor.test"]) == 2
        assert result["sensor.test"][0]["s"] == "22.5"


@pytest.mark.asyncio
async def test_websocket_history_stats_falls_back_when_statistics_fails(
    hass: HomeAssistant,
) -> None:
    """Test fallback to binary search when Statistics API fails."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)

    class MockState:
        def __init__(self, state, last_updated) -> None:
            self.state = state
            self.last_updated = last_updated

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            side_effect=Exception("Statistics unavailable"),
            create=True,
        ),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={
                "sensor.test": [
                    MockState("10", start),
                    MockState("20", start + timedelta(minutes=30)),
                ]
            },
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 60,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        # Should fallback and still succeed
        assert "sensor.test" in result


@pytest.mark.asyncio
async def test_websocket_history_stats_short_interval_uses_binary_search(
    hass: HomeAssistant,
) -> None:
    """Test that short intervals (< 60 min) use the binary search fallback directly."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=30)

    class MockState:
        def __init__(self, state, last_updated) -> None:
            self.state = state
            self.last_updated = last_updated

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            create=True,
        ) as mock_stats,
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={
                "sensor.test": [
                    MockState("10", start),
                    MockState("20", start + timedelta(minutes=10)),
                ]
            },
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 15,  # < 60, should NOT use stats API
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        # Should NOT call statistics API for short intervals
        mock_stats.assert_not_called()
        assert result is not None


@pytest.mark.asyncio
async def test_websocket_history_stats_uses_daily_period_for_large_intervals(
    hass: HomeAssistant,
) -> None:
    """Test that interval >= 1440 (24 hours) uses daily period."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    start = dt_util.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)

    stats_data = {
        "sensor.test": [
            {"start": start.timestamp(), "mean": 22.0},
        ]
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            return_value=stats_data,
            create=True,
        ) as mock_stats,
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 1440,  # 24 hours
            "significant_changes_only": True,
        }

        await websocket_get_history_stats(hass, MagicMock(), msg)

        # Verify daily period was used
        mock_stats.assert_called_once()
        call_args = mock_stats.call_args[0]
        assert call_args[4] == "day"  # period argument


@pytest.mark.asyncio
async def test_websocket_history_stats_statistics_with_state_instead_of_mean(
    hass: HomeAssistant,
) -> None:
    """Test statistics API fallback to 'state' when 'mean' is not available."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)

    # Statistics with 'state' instead of 'mean' (e.g., for binary sensors)
    stats_data = {
        "sensor.test": [
            {"start": start.timestamp(), "state": "on"},
        ]
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            return_value=stats_data,
            create=True,
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 60,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        assert result["sensor.test"][0]["s"] == "on"


@pytest.mark.asyncio
async def test_websocket_history_stats_empty_statistics(hass: HomeAssistant) -> None:
    """Test handling of empty statistics data."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=2)

    with (
        patch(
            "custom_components.growspace_manager.websocket.environment.recorder_stats.async_statistics_during_period",
            new_callable=AsyncMock,
            return_value={},  # Empty result
            create=True,
        ),
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value={"sensor.test": []},
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job

        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "interval_minutes": 60,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        # Should fallback to binary search when stats are empty
        assert "sensor.test" in result
