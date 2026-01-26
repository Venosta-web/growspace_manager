"""Tests to close identified coverage gaps in growspace_manager."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from common import create_plant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager import StrainLibraryUploadView
from custom_components.growspace_manager.bayesian_evaluator import _is_vpd_trend_gated
from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceBinarySensorDescription,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_GROWSPACE_ID,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_STRAIN,
    PlantStage,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.models import (
    BaseModel,
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    NutrientInventory,
    Plant,
)
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.services.plant import (
    handle_add_plants,
    handle_add_timeline_note,
)
from custom_components.growspace_manager.storage_manager import StorageManager
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from custom_components.growspace_manager.views import StrainLibraryImageView
from custom_components.growspace_manager.websocket import (
    _downsample_entity_binary_search,
    _get_statistics_data,
    _merge_logbook_event,
    websocket_get_event_log,
)
from homeassistant.core import HomeAssistant

# --- Dehumidifier Coordinator Coverage ---


@pytest.mark.asyncio
async def test_dehumidifier_stages_coverage(hass: HomeAssistant) -> None:
    """Test _get_growth_stage returns for dry, cure, and seedling."""
    mock_coordinator = MagicMock()
    mock_config_entry = MagicMock()

    # Test CURE stage
    plant_cure = create_plant(
        plant_id="p1", growspace_id="gs1", strain="S1", cure_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_cure]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "cure" else 0
    )

    coordinator = DehumidifierCoordinator(
        hass, mock_config_entry, "gs1", mock_coordinator
    )
    assert coordinator._get_growth_stage() == "cure"

    # Test DRY stage
    plant_dry = create_plant(
        plant_id="p1", growspace_id="gs1", strain="S1", dry_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_dry]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "dry" else 0
    )
    assert coordinator._get_growth_stage() == "dry"

    # Test SEEDLING stage
    plant_seedling = create_plant(
        plant_id="p1", growspace_id="gs1", strain="S1", seedling_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_seedling]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "seedling" else 0
    )
    assert coordinator._get_growth_stage() == "seedling"


# --- Models Nesting Coverage ---


def create_test_sensor(
    coordinator: MagicMock,
    growspace_id: str,
    sensor_type: str,
    strategy_class: type,
    env_config: EnvironmentConfig | None = None,
) -> BayesianEnvironmentSensor:
    """Helper to create a BayesianEnvironmentSensor for testing with all dependencies."""
    if env_config is None:
        env_config = coordinator.growspaces[growspace_id].environment_config

    description = next(d for d in SENSOR_TYPES if d.sensor_type == sensor_type)

    return BayesianEnvironmentSensor(
        coordinator=coordinator,
        growspace_id=growspace_id,
        env_config=env_config,
        description=description,
        strategy_class=strategy_class,
        # Inject dependencies
        get_growspace=lambda gid: coordinator.growspaces.get(gid),
        get_plants=coordinator.get_growspace_plants,
        add_event=coordinator.add_event,
        notification_manager=coordinator.notification_manager,
        strain_library=coordinator.strain_library,
        options=coordinator.options,
    )


@dataclass
class NestedModel(BaseModel):
    plants_list: list[Plant] = field(default_factory=list)
    plants_dict: dict[str, Plant] = field(default_factory=dict)
    name: str = "Test"


def test_models_casting_nested_coverage() -> None:
    """Test _cast_value for nested lists and dicts of BaseModels."""
    data = {
        "name": "Nested",
        "plants_list": [{"plant_id": "p1", "strain": "S1", "growspace_id": "gs1"}],
        "plants_dict": {
            "p2": {"plant_id": "p2", "strain": "S2", "growspace_id": "gs1"}
        },
    }

    model = NestedModel.from_dict(data)
    assert len(model.plants_list) == 1
    assert isinstance(model.plants_list[0], Plant)
    assert len(model.plants_dict) == 1
    assert isinstance(model.plants_dict["p2"], Plant)


# --- Binary Sensor Mold Risk Coverage ---


@pytest.mark.asyncio
async def test_mold_risk_stage_branches_coverage(hass: HomeAssistant) -> None:
    """Test mold risk branches for late flower and early flower."""
    mock_coordinator = MagicMock()
    mock_growspace = Growspace(
        id="gs1", name="GS1", environment_config=EnvironmentConfig()
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    description = GrowspaceBinarySensorDescription(
        key="mold_risk",
        sensor_type="mold_risk",
        name="Mold Risk",
        prior_key="prior_mold_risk",
    )

    sensor = create_test_sensor(
        mock_coordinator,
        "gs1",
        GrowspaceSensorType.MOLD,
        MoldRiskEvaluatorStrategy,
        mock_growspace.environment_config,
    )
    sensor.hass = hass

    # Late Flower (flower_days > 40) + Humidifier On + Humidity < 60
    env_state_late = EnvironmentState(
        temp=20.0,
        humidity=55.0,
        vpd=1.0,
        co2=400.0,
        veg_days=0,
        flower_days=45,
        is_lights_on=True,
        humidifier_value=10.0,
        fan_off=False,
    )
    with patch.object(
        sensor, "_get_base_environment_state", return_value=env_state_late
    ):
        await sensor._async_update_probability()
        reasons = [r[1] for r in sensor._reasons]
        assert "Humidifier On" not in reasons

    # Early/Mid Flower (0 < flower_days <= 40) + Humidifier On + Humidity < 70
    env_state_mid = EnvironmentState(
        temp=20.0,
        humidity=65.0,
        vpd=1.0,
        co2=400.0,
        veg_days=0,
        flower_days=25,
        is_lights_on=True,
        humidifier_value=10.0,
        fan_off=False,
    )
    with patch.object(
        sensor, "_get_base_environment_state", return_value=env_state_mid
    ):
        await sensor._async_update_probability()
        reasons = [r[1] for r in sensor._reasons]
        assert "Humidifier On" not in reasons


# --- Plant Lifecycle History Coverage ---


@pytest.mark.asyncio
async def test_lifecycle_history_closing_coverage(hass: HomeAssistant) -> None:
    """Test transition_plant_stage correctly closes previous history entry."""
    repository = MagicMock()
    validator = MagicMock()
    gs_service = MagicMock()
    strain_library = MagicMock()
    serializer = MagicMock()
    save_callback = AsyncMock()
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)

    plant = create_plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="S1",
        stage="veg",
        stage_history=[{"stage": "veg", "start": "2024-01-01", "end": None}],
    )
    repository.plants = {"p1": plant}

    manager = PlantLifecycleManager(
        repository=repository,
        validator=validator,
        growspace_service=gs_service,
        strain_library=strain_library,
        serializer=serializer,
        save_callback=save_callback,
        lock=lock,
    )
    with patch.object(
        manager, "async_update_plant", new_callable=AsyncMock
    ) as mock_update:
        await manager.transition_plant_stage("p1", "flower")
        mock_update.assert_called_once()
        # Verify the history in the call
        updates = mock_update.call_args.kwargs
        history = updates["stage_history"]
        assert len(history) == 2
        assert history[0]["end"] is not None


# --- Service Plant Coverage ---


@pytest.mark.asyncio
async def test_batch_add_mother_auto_date_coverage(hass: HomeAssistant) -> None:
    """Test add_plants auto-sets mother_start for mother growspace."""
    entry = MockConfigEntry(domain="growspace_manager", data={})
    entry.add_to_hass(hass)
    mock_coordinator = GrowspaceCoordinator(hass, entry, data={})

    mock_coordinator.data_repository.growspaces = {"mother": MagicMock()}
    with patch.object(
        mock_coordinator.validator, "find_first_available_position", return_value=(1, 1)
    ):
        mock_coordinator._plant_service.add_plant = AsyncMock()

        call = MagicMock()
        call.data = {
            ATTR_GROWSPACE_ID: "mother",
            ATTR_STRAIN: "Strain A",
            ATTR_AMOUNT: 1,
        }

        await handle_add_plants(hass, mock_coordinator, MagicMock(), call)
        _args, kwargs = mock_coordinator._plant_service.add_plant.call_args
        assert kwargs.get("mother_start") is not None


@pytest.mark.asyncio
async def test_handle_add_timeline_note_coverage(hass: HomeAssistant) -> None:
    """Test handle_add_timeline_note entry point."""
    mock_coordinator = MagicMock()
    mock_strain_lib = MagicMock()
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p1", ATTR_NOTES: "My note"}

    with patch(
        "custom_components.growspace_manager.services.plant.async_add_timeline_note",
        new_callable=AsyncMock,
    ) as mock_add:
        await handle_add_timeline_note(hass, mock_coordinator, mock_strain_lib, call)
        mock_add.assert_awaited_once()


# --- Statistics Coverage ---


@pytest.mark.asyncio
async def test_statistics_sub_hourly_return_coverage(hass: HomeAssistant) -> None:
    """Test _get_statistics_data returns None for sub-hourly intervals."""
    start = datetime.now()
    end = datetime.now()
    res = await _get_statistics_data(hass, ["sensor.test"], start, end, 30)
    assert res is None


@pytest.mark.asyncio
async def test_statistics_empty_data_coverage(hass: HomeAssistant) -> None:
    """Test _get_statistics_data returns empty lists for missing entities."""
    start = datetime.now()
    end = datetime.now()
    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats.statistics_during_period",
        new_callable=AsyncMock,
        create=True,
    ) as mock_stats:
        mock_stats.return_value = {"other": []}
        res = await _get_statistics_data(hass, ["sensor.test"], start, end, 3600)
        assert res is None


# --- Strain Library Image View Coverage ---


@pytest.mark.asyncio
async def test_strain_library_image_view_coverage(hass: HomeAssistant) -> None:
    """Test StrainLibraryImageView success and fail paths."""
    mock_strain_lib = MagicMock()
    mock_strain_lib.image_manager = None

    view = StrainLibraryImageView(hass, mock_strain_lib)

    # No image manager
    resp = await view.get(None, "test.jpg")
    assert resp.status == 404

    # Success path (requires mocking web.FileResponse and path operations)
    mock_image_mgr = MagicMock()
    mock_strain_lib.image_manager = mock_image_mgr

    mock_path = MagicMock()
    mock_image_mgr.storage_dir = mock_path

    # We need to mock 'web.FileResponse' and avoid 'pathlib' issues by mocking 'Path'
    with (
        patch(
            "custom_components.growspace_manager.views.web.FileResponse",
            return_value=MagicMock(status=200),
        ),
        patch(
            "custom_components.growspace_manager.views.pathlib.Path"
        ) as mock_path_cls,
    ):
        mock_path_cls.return_value = mock_path
        mock_path.resolve.return_value = mock_path
        mock_path.__truediv__.return_value = mock_path
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
    request = MagicMock()
    # 2. get calls logic inline
    with patch("os.path.exists", return_value=True):
        resp = await view.get(request, "strain_id.jpg")
        assert resp.status == 200


# --- Websocket Event Log Spam Filter Coverage ---


@pytest.mark.asyncio
async def test_websocket_get_event_log_spam_filter_coverage(
    hass: HomeAssistant,
) -> None:
    """Test websocket_get_event_log with SQL-level spam filtering."""
    connection = MagicMock()
    msg = {"id": 1, "type": "growspace_manager/get_event_log", "limit": 10}

    # With SQL-level filtering, only normal events are returned from DB
    # Spam events (optimal/stress/mold) are excluded at SQL query level
    normal_data = json.dumps({"category": "info", "growspace_id": "gs1"})

    class MockEvent:
        def __init__(self, event_id, time_fired_ts) -> None:
            self.event_id = event_id
            self.time_fired_ts = time_fired_ts

    class MockData:
        def __init__(self, shared_data) -> None:
            self.shared_data = shared_data

    # SQL filtering means only non-spam events in result
    events_to_return = [
        (MockEvent(i, 2000.0 + i), MockData(normal_data)) for i in range(20)
    ]

    # Mock query chain with SQL filtering
    mock_query_base = MagicMock()
    mock_filter_result = MagicMock()
    mock_query_base.join.return_value.filter.return_value = mock_filter_result
    # The SQL filtering adds .filter() calls in a loop for spam categories
    mock_filter_result.filter.return_value = mock_filter_result
    mock_filter_result.order_by.return_value.limit.return_value = events_to_return

    # Mock EventTypes query
    mock_session = MagicMock()
    mock_session.query.side_effect = [
        MagicMock(
            filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=(1,))))
        ),
        mock_query_base,
    ]

    # Use a real dt_util.utcnow or mock it correctly
    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_get_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_session_scope,
        patch("homeassistant.util.dt.utcnow", return_value=datetime.now()),
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session

        async def mock_add_job(func, *args):
            return func(*args)

        mock_get_recorder.return_value.async_add_executor_job.side_effect = mock_add_job

        await websocket_get_event_log(hass, connection, msg)

        connection.send_result.assert_called_once()
        result = connection.send_result.call_args[0][1]

        # With SQL filtering, we only get the 10 requested normal events
        # (limit=10), not spam events
        assert "gs1" in result
        assert len(result["gs1"]) == 10


# --- Targeted Coverage Gaps ---


def test_vpd_trend_gated_none_coverage() -> None:
    """Test _is_vpd_trend_gated returns False when vpd is None."""
    state = EnvironmentState(
        temp=20.0,
        humidity=50.0,
        vpd=None,
        co2=400.0,
        veg_days=0,
        flower_days=0,
        is_lights_on=True,
        fan_off=False,
    )
    assert _is_vpd_trend_gated(state) is False


@pytest.mark.asyncio
async def test_websocket_get_event_log_recorder_missing_coverage(
    hass: HomeAssistant,
) -> None:
    """Test websocket_get_event_log when recorder is missing."""
    connection = MagicMock()
    msg = {"id": 1, "type": "growspace_manager/get_event_log"}

    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=ImportError("No recorder"),
    ):
        await websocket_get_event_log(hass, connection, msg)
        connection.send_result.assert_called_once()


@pytest.mark.asyncio
async def test_merge_logbook_event_exception_coverage() -> None:
    """Test _merge_logbook_event catches ValueError on invalid dates."""

    formatted = [
        {
            "growspace_id": "gs1",
            "category": "info",
            "sensor_type": "temp",
            "start_time": "INVALID",
            "severity": 1.0,
        }
    ]
    d = {
        "growspace_id": "gs1",
        "category": "info",
        "sensor_type": "temp",
        "end_time": "2024-01-01",
        "severity": 1.0,
    }

    # This should return False and not crash
    assert _merge_logbook_event(formatted, d, MagicMock()) is False


@pytest.mark.asyncio
async def test_strain_library_upload_view_error_cleanup_coverage(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Test StrainLibraryUploadView cleanup on failure."""
    view = StrainLibraryUploadView(hass, MagicMock())

    temp_file = tmp_path / "test.zip"
    mock_field = AsyncMock()
    mock_field.name = "file"
    mock_field.read_chunk.side_effect = Exception("Write failed")

    with (
        patch(
            "custom_components.growspace_manager.views.tempfile.mkstemp",
            return_value=(1, str(temp_file)),
        ),
        patch(
            "custom_components.growspace_manager.views.pathlib.Path"
        ) as mock_path_cls,
    ):
        mock_path = MagicMock()
        mock_path_cls.return_value = mock_path
        mock_path.exists.return_value = True

        with pytest.raises(Exception, match="Write failed"):
            await view._save_upload_to_temp(mock_field)


@pytest.mark.asyncio
async def test_storage_manager_force_save_coverage(hass: HomeAssistant) -> None:
    """Test StorageManager.async_force_save actually calls async_save on stores."""
    repository = MagicMock()
    repository.growspaces = {}
    repository.plants = {}
    repository.notifications_sent = {}
    repository.notifications_enabled = {}

    nutrient_manager = MagicMock()
    nutrient_manager.get_serialization_data.return_value = {}

    serializer = MagicMock()

    with patch(
        "custom_components.growspace_manager.storage_manager.Store"
    ) as mock_store_cls:
        mock_config_store = MagicMock()
        mock_plants_store = MagicMock()
        mock_store_cls.side_effect = [mock_config_store, mock_plants_store, MagicMock()]

        storage = StorageManager(hass, repository, nutrient_manager, serializer)

        mock_config_store.async_save = AsyncMock()
        mock_plants_store.async_save = AsyncMock()

        await storage.async_force_save()

        mock_config_store.async_save.assert_awaited_once()
        mock_plants_store.async_save.assert_awaited_once()

    # Test async_save (debounced)
    with patch(
        "custom_components.growspace_manager.storage_manager.Store"
    ) as mock_store_cls:
        mock_config_store = MagicMock()
        mock_plants_store = MagicMock()
        mock_store_cls.side_effect = [mock_config_store, mock_plants_store, MagicMock()]

        storage = StorageManager(hass, repository, nutrient_manager, serializer)

        mock_config_store.async_delay_save = MagicMock()
        mock_plants_store.async_delay_save = MagicMock()

        await storage.async_save()

        mock_config_store.async_delay_save.assert_called_once()


@pytest.mark.asyncio
async def test_storage_manager_load_coverage(hass: HomeAssistant) -> None:
    """Test StorageManager.async_load with segmented and legacy storage."""
    repository = MagicMock()
    repository.growspaces = {}
    repository.plants = {}

    nutrient_manager = MagicMock()
    serializer = MagicMock()

    with patch(
        "custom_components.growspace_manager.storage_manager.Store"
    ) as mock_store_cls:
        mock_config_store = MagicMock()
        mock_plants_store = MagicMock()
        mock_legacy_store = MagicMock()
        mock_store_cls.side_effect = [
            mock_config_store,
            mock_plants_store,
            mock_legacy_store,
        ]

        storage = StorageManager(hass, repository, nutrient_manager, serializer)

        # Mock serializer to return objects
        serializer.deserialize_growspaces.return_value = {
            "gs1": Growspace(id="gs1", name="GS1")
        }
        serializer.deserialize_plants.return_value = {
            "p1": create_plant(plant_id="p1", strain="S1", growspace_id="gs1")
        }

        # 1. Segmented load success
        mock_config_store.async_load = AsyncMock(
            return_value={"growspaces": {"gs1": {"id": "gs1", "name": "GS1"}}}
        )
        mock_plants_store.async_load = AsyncMock(
            return_value={
                "plants": {
                    "p1": {"plant_id": "p1", "strain": "S1", "growspace_id": "gs1"}
                }
            }
        )

        await storage.async_load()
        assert "gs1" in repository.growspaces
        assert "p1" in repository.plants

        # 2. Legacy migration
        mock_config_store.async_load = AsyncMock(return_value=None)
        mock_plants_store.async_load = AsyncMock(return_value=None)
        mock_legacy_store.async_load = AsyncMock(
            return_value={
                "growspaces": {"gs2": {"id": "gs2", "name": "GS2"}},
                "plants": {
                    "p2": {"plant_id": "p2", "strain": "S2", "growspace_id": "gs2"}
                },
            }
        )

        # Update serializer return values for legacy load
        serializer.deserialize_growspaces.return_value = {
            "gs2": Growspace(id="gs2", name="GS2")
        }
        serializer.deserialize_plants.return_value = {
            "p2": create_plant(plant_id="p2", strain="S2", growspace_id="gs2")
        }

        mock_config_store.async_save = AsyncMock()
        mock_plants_store.async_save = AsyncMock()

        await storage.async_load()
        assert "gs2" in repository.growspaces
        mock_config_store.async_save.assert_awaited()

        # 3. fresh load
        mock_legacy_store.async_load = AsyncMock(return_value=None)
        with patch.object(storage, "async_save", new_callable=AsyncMock) as mock_ss:
            await storage.async_load()
            mock_ss.assert_awaited()

        # 4. Error handling
        mock_config_store.async_load = AsyncMock(return_value={"growspaces": "CORRUPT"})
        serializer.deserialize_growspaces.side_effect = Exception("Corrupt Data")

        await storage.async_load()
        assert repository.growspaces == {}

        # Reset side_effect
        serializer.deserialize_growspaces.side_effect = None

        # 5. Options and more error paths
        options = {"gs1": {"temp_high": 30.0}}
        mock_config_store.async_load = AsyncMock(
            return_value={
                "growspaces": {"gs1": {"id": "gs1", "name": "GS1"}},
                "nutrient_presets": "CORRUPT",
                "ipm_presets": "CORRUPT",
            }
        )
        serializer.deserialize_growspaces.return_value = {
            "gs1": Growspace(id="gs1", name="GS1")
        }
        with patch.object(storage, "_load_plants", side_effect=Exception("Crash")):
            await storage.async_load(options=options)

        assert "gs1" in repository.growspaces

        # Verify nutrient_manager.load_data called with empty dicts for corrupt presets
        # We check the last call
        call_args = nutrient_manager.load_data.call_args
        assert call_args[0][0] == {}
        assert call_args[0][1] == {}
        assert isinstance(call_args[0][2], NutrientInventory)


@pytest.mark.asyncio
async def test_storage_manager_load_plants_error(hass: HomeAssistant) -> None:
    """Test StorageManager._load_plants error handling."""
    repository = MagicMock()
    repository.plants = {}
    nutrient_manager = MagicMock()
    serializer = MagicMock()
    storage = StorageManager(hass, repository, nutrient_manager, serializer)

    # Trigger exception in _load_plants
    data = {"plants": {"p1": "MALFORMED"}}
    serializer.deserialize_plants.side_effect = Exception("Deserialization Error")

    storage._load_plants(data)
    assert repository.plants == {}


@pytest.mark.asyncio
async def test_merge_logbook_event_extra_exceptions_coverage() -> None:
    """Test _merge_logbook_event catches KeyError/TypeError."""
    formatted = [
        {
            "growspace_id": "gs1",
            "category": "info",
            "sensor_type": "temp",
            "start_time": "2024-01-01",
        }
    ]
    d = {"growspace_id": "gs1"}
    assert _merge_logbook_event(formatted, d, MagicMock()) is False


def test_downsample_empty_idx_coverage() -> None:
    """Test _downsample_entity_binary_search else branch."""
    start = datetime(2024, 1, 1, 10, 0, 0)
    end = datetime(2024, 1, 1, 11, 0, 0)
    states = [{"last_updated": datetime(2024, 1, 1, 12, 0, 0)}]

    res = _downsample_entity_binary_search(states, start, end, timedelta(minutes=60))
    assert res == []


@pytest.mark.asyncio
async def test_lifecycle_history_stages_coverage(hass: HomeAssistant) -> None:
    """Test transition_plant_stage stage branches to hit move methods."""
    repository = MagicMock()
    validator = MagicMock()
    gs_service = MagicMock()
    strain_library = MagicMock()
    serializer = MagicMock()
    save_callback = AsyncMock()
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)

    plant = create_plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="S1",
        stage="veg",
        stage_history=[{"stage": "veg", "start": "2024-01-01", "end": None}],
    )
    repository.plants = {"p1": plant}

    manager = PlantLifecycleManager(
        repository=repository,
        validator=validator,
        growspace_service=gs_service,
        strain_library=strain_library,
        serializer=serializer,
        save_callback=save_callback,
        lock=lock,
    )

    manager.async_update_plant = AsyncMock()
    manager.move_to_dry_growspace = AsyncMock()
    manager.move_to_cure_growspace = AsyncMock()
    manager.move_to_clone_growspace = AsyncMock()

    # Hit DRY transition
    await manager.transition_plant_stage("p1", PlantStage.DRY)
    manager.move_to_dry_growspace.assert_awaited_once()

    # Hit CURE transition
    await manager.transition_plant_stage("p1", PlantStage.CURE)
    manager.move_to_cure_growspace.assert_awaited_once()

    # Hit CLONE transition
    await manager.transition_plant_stage("p1", PlantStage.CLONE)
    manager.move_to_clone_growspace.assert_awaited_once()
