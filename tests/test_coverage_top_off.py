"""Tests to close identified coverage gaps in growspace_manager."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from aiohttp import web

from custom_components.growspace_manager import (
    DOMAIN,
    StrainLibraryImageView,
    StrainLibraryUploadView,
    _get_statistics_data,
    websocket_get_event_log,
)
from custom_components.growspace_manager.binary_sensor import (
    BayesianMoldRiskSensor,
    GrowspaceBinarySensorDescription,
)
from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_GROWSPACE_ID,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    ATTR_STRAIN,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.models import (
    BaseModel,
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    Plant,
)
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.services.plant import (
    handle_add_plants,
    handle_add_timeline_note,
)
from custom_components.growspace_manager.bayesian_evaluator import (
    _is_vpd_trend_gated,
)

# --- Dehumidifier Coordinator Coverage ---


@pytest.mark.asyncio
async def test_dehumidifier_stages_coverage(hass: HomeAssistant) -> None:
    """Test _get_growth_stage returns for dry, cure, and seedling."""
    mock_coordinator = MagicMock()
    mock_config_entry = MagicMock()

    # Test CURE stage
    plant_cure = Plant(
        plant_id="p1", growspace_id="gs1", strain="S1", cure_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_cure]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "cure" else 0
    )

    coordinator = DehumidifierCoordinator(hass, mock_config_entry, "gs1", mock_coordinator)
    assert coordinator._get_growth_stage() == "cure"

    # Test DRY stage
    plant_dry = Plant(
        plant_id="p1", growspace_id="gs1", strain="S1", dry_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_dry]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "dry" else 0
    )
    assert coordinator._get_growth_stage() == "dry"

    # Test SEEDLING stage
    plant_seedling = Plant(
        plant_id="p1", growspace_id="gs1", strain="S1", seedling_start="2024-01-01"
    )
    mock_coordinator.get_growspace_plants.return_value = [plant_seedling]
    mock_coordinator.serializer.calculate_days_in_stage.side_effect = (
        lambda p, s: 1 if s == "seedling" else 0
    )
    assert coordinator._get_growth_stage() == "seedling"


# --- Models Nesting Coverage ---


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
        "plants_dict": {"p2": {"plant_id": "p2", "strain": "S2", "growspace_id": "gs1"}},
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

    sensor = BayesianMoldRiskSensor(
        mock_coordinator, "gs1", mock_growspace.environment_config, description
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
    mock_coordinator = MagicMock()
    mock_coordinator._lock = AsyncMock()
    mock_coordinator.async_commit = AsyncMock()

    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="S1",
        stage="veg",
        stage_history=[{"stage": "veg", "start": "2024-01-01", "end": None}],
    )
    mock_coordinator.plants = {"p1": plant}

    manager = PlantLifecycleManager(mock_coordinator)
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
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {"mother": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)
    mock_coordinator.async_add_plant = AsyncMock()

    call = MagicMock()
    call.data = {ATTR_GROWSPACE_ID: "mother", ATTR_STRAIN: "Strain A", ATTR_AMOUNT: 1}

    await handle_add_plants(hass, mock_coordinator, MagicMock(), call)
    args, kwargs = mock_coordinator.async_add_plant.call_args
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
        "custom_components.growspace_manager.recorder_stats.async_statistics_during_period",
        new_callable=AsyncMock,
        create=True,
    ) as mock_stats:
        mock_stats.return_value = {"other": []}
        res = await _get_statistics_data(hass, ["sensor.test"], start, end, 3600)
        assert res["sensor.test"] == []


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
        patch("custom_components.growspace_manager.web.FileResponse", return_value=MagicMock(status=200)),
        patch("custom_components.growspace_manager.pathlib.Path") as mock_path_cls,
    ):
        mock_path_cls.return_value = mock_path
        mock_path.resolve.return_value = mock_path
        mock_path.__truediv__.return_value = mock_path
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = True
        # str(file_path).startswith(str(storage_dir.resolve()))
        mock_path.__str__.return_value = "/tmp/test.jpg"
        
        resp = await view.get(None, "test.jpg")
        assert resp.status == 200


# --- Websocket Event Log Spam Filter Coverage ---


@pytest.mark.asyncio
async def test_websocket_get_event_log_spam_filter_coverage(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log spam filter limits."""
    connection = MagicMock()
    msg = {"id": 1, "type": "growspace_manager/get_event_log", "limit": 10}

    # Create 300 spammy events and 20 normal events
    spam_data = json.dumps({"category": "optimal", "growspace_id": "gs1"})
    normal_data = json.dumps({"category": "info", "growspace_id": "gs1"})

    class MockEvent:
        def __init__(self, event_id, time_fired_ts):
            self.event_id = event_id
            self.time_fired_ts = time_fired_ts

    class MockData:
        def __init__(self, shared_data):
            self.shared_data = shared_data

    events_to_return = []
    # Mix them a bit
    for i in range(250):
        events_to_return.append((MockEvent(i, 1000.0 + i), MockData(spam_data)))
    for i in range(20):
        events_to_return.append((MockEvent(300 + i, 2000.0 + i), MockData(normal_data)))

    mock_query = MagicMock()
    mock_query.join.return_value.filter.return_value.order_by.return_value.limit.return_value = events_to_return
    
    # Mock EventTypes query
    mock_session = MagicMock()
    mock_session.query.side_effect = [
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=(1,))))),
        mock_query
    ]

    with (
        patch("custom_components.growspace_manager.get_instance") as mock_get_recorder,
        patch("custom_components.growspace_manager.session_scope") as mock_session_scope,
        patch("homeassistant.util.dt.utcnow", return_value=datetime.now()),
    ):
        mock_session_scope.return_value.__enter__.return_value = mock_session
        
        async def mock_add_job(func, *args):
            return func(*args)
        mock_get_recorder.return_value.async_add_executor_job.side_effect = mock_add_job

        await websocket_get_event_log(hass, connection, msg)

        connection.send_result.assert_called_once()
        result = connection.send_result.call_args[0][1]
        
        # gs1 should have spam_limit (200) + limit (10) = 210 events
        assert "gs1" in result
        assert len(result["gs1"]) == 210


# --- Targeted Coverage Gaps ---

def test_vpd_trend_gated_none_coverage() -> None:
    """Test _is_vpd_trend_gated returns False when vpd is None."""
    state = EnvironmentState(
        temp=20.0, humidity=50.0, vpd=None, co2=400.0, veg_days=0, flower_days=0, is_lights_on=True, fan_off=False
    )
    assert _is_vpd_trend_gated(state) is False

@pytest.mark.asyncio
async def test_websocket_get_event_log_recorder_missing_coverage(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log when recorder is missing."""
    connection = MagicMock()
    msg = {"id": 1, "type": "growspace_manager/get_event_log"}
    
    with patch("custom_components.growspace_manager.get_instance", side_effect=ImportError("No recorder")):
        await websocket_get_event_log(hass, connection, msg)
        connection.send_result.assert_called_once()

@pytest.mark.asyncio
async def test_merge_logbook_event_exception_coverage() -> None:
    """Test _merge_logbook_event catches ValueError on invalid dates."""
    from custom_components.growspace_manager import _merge_logbook_event
    
    formatted = [{"growspace_id": "gs1", "category": "info", "sensor_type": "temp", "start_time": "INVALID", "severity": 1.0}]
    d = {"growspace_id": "gs1", "category": "info", "sensor_type": "temp", "end_time": "2024-01-01", "severity": 1.0}
    
    # This should return False and not crash
    assert _merge_logbook_event(formatted, d, MagicMock()) is False

@pytest.mark.asyncio
async def test_strain_library_upload_view_error_cleanup_coverage(hass: HomeAssistant) -> None:
    """Test StrainLibraryUploadView cleanup on failure."""
    view = StrainLibraryUploadView(hass, MagicMock())
    
    mock_field = AsyncMock()
    mock_field.name = "file"
    mock_field.read_chunk.side_effect = Exception("Write failed")
    
    with (
        patch("custom_components.growspace_manager.tempfile.mkstemp", return_value=(1, "/tmp/test.zip")),
        patch("custom_components.growspace_manager.pathlib.Path") as mock_path_cls,
    ):
        mock_path = MagicMock()
        mock_path_cls.return_value = mock_path
        mock_path.exists.return_value = True
        
        with pytest.raises(Exception, match="Write failed"):
            await view._save_upload_to_temp(mock_field)
        
        mock_path.unlink.assert_called_once()