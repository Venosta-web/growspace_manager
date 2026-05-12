"""Test specifically targeting coverage gaps with robust mocks."""

from datetime import timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.bayesian_evaluator import (
    evaluate_active_saturation,
    evaluate_direct_co2_stress,
    evaluate_optimal_temperature,
    evaluate_optimal_vpd,
)
from custom_components.growspace_manager.binary_sensor import (
    SENSOR_TYPES,
    BayesianEnvironmentSensor,
    GrowspaceSensorType,
    LightCycleVerificationSensor,
)
from custom_components.growspace_manager.calendar import GrowspaceCalendar
from custom_components.growspace_manager.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    IrrigationConfig,
    PlantStage,
)
from custom_components.growspace_manager.notification_manager import NotificationManager
from custom_components.growspace_manager.sensor import (
    BaseVpdSensor,
    CalculatedVpdSensor,
    GrowspaceOverviewSensor,
    _check_calculated_vpd_sensor,
    _update_growspace_entities,
)
from custom_components.growspace_manager.services.plant import handle_harvest_plant
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from custom_components.growspace_manager.websocket import (
    _get_history_with_binary_search_downsample,
    websocket_get_history_stats,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry

from .common import create_plant

# -----------------------------------------------------------------------------
# __init__.py Coverage
# -----------------------------------------------------------------------------


async def test_websocket_history_stats_sub_hourly(hass: HomeAssistant) -> None:
    """Test websocket history stats with interval < 60 minutes."""
    connection = MagicMock()
    msg = {
        "id": 1,
        "type": "get_history_stats",
        "entity_ids": ["sensor.test"],
        "start_time": dt_util.utcnow().isoformat(),
        "end_time": dt_util.utcnow().isoformat(),
        "interval_minutes": 30,
    }

    with patch(
        "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
        return_value={"sensor.test": []},
    ) as mock_downsample:
        await websocket_get_history_stats(hass, connection, msg)
        mock_downsample.assert_called_once()

    connection.send_result.assert_called_once()


async def test_websocket_history_stats_missing_in_stats_data(
    hass: HomeAssistant,
) -> None:
    """Test websocket history stats where entity is not in stats data."""
    connection = MagicMock()
    msg = {
        "id": 1,
        "type": "get_history_stats",
        "entity_ids": ["sensor.missing"],
        "start_time": dt_util.utcnow().isoformat(),
        "interval_minutes": 60,
    }

    # Patch local import for recorder_stats
    with patch(
        "custom_components.growspace_manager.websocket.recorder_stats"
    ) as mock_stats:
        mock_stats.statistics_during_period.return_value = {}

        # ALSO patch the fallback function to avoid it calling real recorder/history
        with patch(
            "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample",
            return_value={"sensor.missing": []},
        ) as mock_fallback:
            await websocket_get_history_stats(hass, connection, msg)
            mock_fallback.assert_called_once()

    connection.send_result.assert_called_with(1, {"sensor.missing": []})


async def test_downsample_empty_timestamps(hass: HomeAssistant) -> None:
    """Test binary search downsample with states but no valid timestamps."""
    start = dt_util.utcnow()
    end = start + timedelta(hours=1)

    mock_state = MagicMock()
    mock_state.last_updated = None
    mock_state.state = "10"

    # Create a mock recorder that has an async_add_executor_job method
    mock_recorder = MagicMock()

    async def run_job(target, *args, **kwargs):
        # Execute the target function immediately
        return target(*args, **kwargs)

    mock_recorder.async_add_executor_job = AsyncMock(side_effect=run_job)

    # Patch get_instance to return our mock recorder
    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance",
            return_value=mock_recorder,
        ),
        patch(
            "custom_components.growspace_manager.websocket.history.get_significant_states",
            return_value={"sensor.test": [mock_state]},
        ),
    ):
        result = await _get_history_with_binary_search_downsample(
            hass, ["sensor.test"], start, end, 5
        )

    assert result["sensor.test"] == []


# -----------------------------------------------------------------------------
# calendar.py Coverage
# -----------------------------------------------------------------------------


async def test_calendar_notification_not_for_growspace(hass: HomeAssistant) -> None:
    """Test calendar event generation when notification is for another growspace."""
    coordinator = MagicMock()
    coordinator.options = {
        "timed_notifications": [
            {
                "id": "1",
                "trigger_type": "veg",
                "day": 10,
                "message": "Test",
                "growspace_ids": ["other_gs"],
            }
        ]
    }

    gs = Growspace(id="our_gs", name="Our GS")
    coordinator.growspaces = {"our_gs": gs}
    plant = create_plant(
        plant_id="p1",
        growspace_id="our_gs",
        strain="Test Strain",
        veg_start="2023-01-01",
        stage="veg",
    )

    coordinator.get_growspace_plants.return_value = [plant]

    calendar = GrowspaceCalendar(coordinator, "our_gs")
    calendar._generate_events()

    assert len(calendar._events) == 0


# -----------------------------------------------------------------------------
# notification_manager.py Coverage
# -----------------------------------------------------------------------------


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


def test_trigger_cooldown_manual(hass: HomeAssistant) -> None:
    """Test manually triggering notification cooldown."""
    nm = NotificationManager(hass, MagicMock())
    nm.trigger_cooldown("gs1")
    assert "gs1" in nm._last_notification_sent


# -----------------------------------------------------------------------------
# sensor.py Coverage
# -----------------------------------------------------------------------------


async def test_check_calculated_vpd_sensor_creation() -> None:
    """Test creation logic for calculated VPD sensor."""
    coordinator = MagicMock()
    gs = Growspace(id="gs1", name="Test GS")
    gs.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp", humidity_sensor="sensor.hum"
    )

    sensors = _check_calculated_vpd_sensor(coordinator, gs)
    assert sensors
    assert isinstance(sensors[0], CalculatedVpdSensor)

    gs.environment_config.vpd_sensor = "sensor.calculated_vpd_gs1"
    sensors = _check_calculated_vpd_sensor(coordinator, gs)
    assert sensors


async def test_base_vpd_sensor_tracking(hass: HomeAssistant) -> None:
    """Test BaseVpdSensor tracking logic."""
    sensor = BaseVpdSensor()
    sensor.hass = hass
    sensor.entity_id = "sensor.test_vpd"
    sensor.async_write_ha_state = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.sensor.async_track_state_change_event"
        ) as mock_track,
        patch.object(
            BaseVpdSensor, "entities_to_track", property(lambda self: ["sensor.source"])
        ),
    ):
        await sensor.async_added_to_hass()
        mock_track.assert_called()


async def test_growspace_overview_sensor_tracking(hass: HomeAssistant) -> None:
    """Test GrowspaceOverviewSensor tracking."""
    coordinator = MagicMock()
    gs = Growspace(id="gs1", name="Test GS")
    gs.environment_config = EnvironmentConfig(
        soil_moisture_sensor="sensor.soil", vpd_sensor="sensor.vpd"
    )

    coordinator.growspaces.get.return_value = gs

    sensor = GrowspaceOverviewSensor(coordinator, "gs1", gs)
    sensor.hass = hass
    sensor.entity_id = "sensor.gs_overview"
    sensor.async_write_ha_state = MagicMock()

    with patch(
        "custom_components.growspace_manager.sensor.async_track_state_change_event"
    ) as mock_track:
        await sensor.async_added_to_hass()
        mock_track.assert_called()
        tracked = mock_track.call_args[0][1]
        assert "sensor.soil" in tracked


# -----------------------------------------------------------------------------
# bayesian_evaluator.py Coverage
# -----------------------------------------------------------------------------


def test_calculated_vpd_native_value() -> None:
    """Test calculated VPD sensor native value."""
    coordinator = MagicMock()
    sensor = CalculatedVpdSensor(coordinator, "gs1", "GS1", "sensor.t", "sensor.h")
    sensor.hass = MagicMock()

    with patch.object(sensor, "_get_float_state", side_effect=[25.0, 50.0]):
        val = sensor.native_value
        assert val is not None


def test_bayesian_branches() -> None:
    """Test various Bayesian evaluator branches."""
    base_args = {
        "temp": 25.0,
        "humidity": 50.0,
        "vpd": 1.0,
        "co2": 800.0,
        "veg_days": 10,
        "flower_days": -1,
        "is_lights_on": True,
        "fan_off": False,
    }

    state = EnvironmentState(**dict[str, float | None](base_args | {"vpd": None}))  # type: ignore[arg-type]
    obs, _reasons = evaluate_optimal_vpd(state, {})
    assert not obs

    state = EnvironmentState(
        **cast(dict[str, Any], base_args | {"humidifier_value": None})
    )
    obs, _reasons = evaluate_active_saturation(state, {})
    assert not obs

    state = EnvironmentState(
        **cast(
            dict[str, Any],
            base_args | {"humidifier_value": 1, "humidity": 90, "flower_days": -1},
        )
    )
    obs, _reasons = evaluate_active_saturation(state, {})
    assert len(obs) > 0


# -----------------------------------------------------------------------------
# strain_library.py Coverage
# -----------------------------------------------------------------------------


async def test_strain_library_webp_migration(hass: HomeAssistant) -> None:
    """Test that StrainLibrary reloads if WebP migration occurred."""
    library = StrainLibrary(hass)

    # Mock database
    library._db = MagicMock()
    # Mock load to avoid DB calls
    library.load = AsyncMock()  # type: ignore[method-assign]

    # Mock image_manager.async_migrate_to_webp to return True
    library.image_manager.async_migrate_to_webp = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # Mock aiosqlite.connect to be an async context manager or awaitable
    mock_db = MagicMock()
    # Ensure executescript is awaitable
    mock_db.executescript = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    async def connect_side_effect(*args, **kwargs):
        return mock_db

    with patch("aiosqlite.connect", side_effect=connect_side_effect):
        result = await library.async_setup()

        assert result is True
        # Load called twice: once in setup, once after migration
        assert library.load.call_count == 2


# -----------------------------------------------------------------------------
# config_flow.py Coverage
# -----------------------------------------------------------------------------


async def test_config_flow_user_step_exception(hass: HomeAssistant) -> None:
    """Test exception handling in config flow user step."""
    flow = ConfigFlow()
    flow.hass = hass

    # Patch async_create_entry to raise an exception
    with patch.object(flow, "async_create_entry", side_effect=ValueError("Boom")):
        result = await flow.async_step_user(user_input={"name": "Test"})

        # Should return form with error
        assert result["type"] == "form"
        assert result["errors"] == {"base": "Error: Boom"}


async def test_config_flow_missing_env_config_coverage(hass: HomeAssistant) -> None:
    """Test config flow with explicitly missing environment config path."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    mock_entry.add_to_hass(hass)

    mock_coordinator = MagicMock()
    mock_coordinator.services.get_growspace = MagicMock()
    mock_coordinator.data_repository.get_growspace = MagicMock()

    mock_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(mock_entry)
    flow.hass = hass

    real_gs = Growspace(id="gs1", name="GS1", environment_config=EnvironmentConfig())

    mock_coordinator.growspaces = {"gs1": real_gs}
    mock_coordinator.services.get_growspace.return_value = real_gs
    mock_coordinator.data_repository.get_growspace.return_value = real_gs

    flow.selected_growspace_id = "gs1"

    step_result = await flow.async_step_configure_environment(None)

    assert step_result["type"] == FlowResultType.FORM


# -----------------------------------------------------------------------------
# services/plant.py Coverage
# -----------------------------------------------------------------------------


async def test_handle_harvest_plant_not_loaded(hass: HomeAssistant) -> None:
    """Test harvest plant aborts if plant not loaded."""
    coordinator = MagicMock()
    # Ensure the facade is ready to be called or skipped
    coordinator.services.harvest_plant = AsyncMock()

    call = MagicMock()
    call.data = {"plant_id": "p1", "target_growspace_id": "dry"}

    # In Home Assistant, _ensure_plant_loaded usually raises an error to stop execution.
    # Mocking it to raise ServiceValidationError ensures the function exits.
    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
            side_effect=ServiceValidationError("Plant not found"),
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="p1",
        ),
    ):
        with pytest.raises(ServiceValidationError):
            await handle_harvest_plant(hass, coordinator, MagicMock(), call)

        # Verify the facade was never even reached
        coordinator.services.harvest_plant.assert_not_called()


# -----------------------------------------------------------------------------
# binary_sensor.py Coverage
# -----------------------------------------------------------------------------


async def test_binary_sensor_event_attributes(hass: HomeAssistant) -> None:
    """Test binary sensor extra attributes with active event."""
    sensor = create_test_sensor(
        MagicMock(),
        "gs1",
        GrowspaceSensorType.MOLD,
        MoldRiskEvaluatorStrategy,
        EnvironmentConfig(),
    )
    sensor._event_start_time = dt_util.utcnow() - timedelta(minutes=10)

    attrs = sensor.extra_state_attributes
    assert "time_in_current_state" in attrs
    assert attrs["time_in_current_state"] > 0


async def test_light_cycle_sensor_stages(hass: HomeAssistant) -> None:
    """Test light cycle sensor stage determination branches."""
    coordinator = MagicMock()
    sensor = LightCycleVerificationSensor(
        coordinator,
        "gs1",
        EnvironmentConfig(),
        get_plants=coordinator.get_growspace_plants,
        calculate_days=lambda d: 30,
    )

    # Mock 0 flower days -> Veg
    assert sensor._get_current_stage_key({"flower_days": -1}) == "veg"
    # Mock < 21 -> flower_early
    assert sensor._get_current_stage_key({"flower_days": 10}) == "flower_early"
    # Mock < 42 -> flower_mid
    assert sensor._get_current_stage_key({"flower_days": 30}) == "flower_mid"
    # Mock >= 42 -> flower_late
    assert sensor._get_current_stage_key({"flower_days": 50}) == "flower_late"


# -----------------------------------------------------------------------------
# bayesian_evaluator.py Coverage
# -----------------------------------------------------------------------------


def test_bayesian_none_checks() -> None:
    """Test None checks in bayesian evaluators."""

    state = EnvironmentState(
        temp=None,
        humidity=None,
        vpd=None,
        co2=None,
        veg_days=-1,
        flower_days=-1,
        is_lights_on=None,
        fan_off=None,
    )

    # CO2 None
    obs, _rsn = evaluate_direct_co2_stress(state, {})
    assert not obs

    # Humidity None in saturation
    state2 = EnvironmentState(
        temp=20,
        humidity=None,
        vpd=1.0,
        co2=800,
        veg_days=-1,
        flower_days=-1,
        is_lights_on=True,
        fan_off=False,
        humidifier_value=1,
    )
    obs, _rsn = evaluate_active_saturation(state2, {})
    assert not obs

    # Lights Unknown (None) in optimal temp
    # The fix ensures this falls back to day/active logic, so it SHOULD generate an observation
    # if the temp (25) is within the optimal range (or outside the range for stress).
    # Since 25 is optimal for veg, and we have 0 flower days, it evaluates as Veg Early.
    # The default 'active' prob should be returned.
    state3 = EnvironmentState(
        temp=25,
        humidity=50,
        vpd=1.0,
        co2=800,
        veg_days=10,  # Ensure we are clearly in Veg
        flower_days=-1,
        is_lights_on=None,
        fan_off=False,
    )
    obs, _rsn = evaluate_optimal_temperature(state3, {})
    # 25C is great for veg (active), so we expect high probability
    assert len(obs) > 0
    assert obs[0][0] > 0.8  # Expecting good probability


# -----------------------------------------------------------------------------
# coordinator.py & sensor.py interaction Coverage
# -----------------------------------------------------------------------------


async def test_coordinator_update_missing_pump_keys(hass: HomeAssistant) -> None:
    """Test async_update_irrigation_config handles missing pump entity keys."""

    lc_manager = MagicMock()
    coord = GrowspaceCoordinator(hass, lc_manager)

    # Setup mock growspace
    # Setup mock growspace
    config = IrrigationConfig(
        irrigation_pump_entity="switch.pump", drain_pump_entity="switch.drain"
    )

    gs = Growspace(id="gs1", name="GS1", irrigation_config=config)
    coord.growspaces = {"gs1": gs}

    await coord.async_update_irrigation_config("gs1", {"some_other_key": "val"})

    # Verify that pump entities were set to None on the config object
    assert gs.irrigation_config.irrigation_pump_entity is None
    assert gs.irrigation_config.drain_pump_entity is None


async def test_sensor_new_vpd_entity_creation_in_update(hass: HomeAssistant) -> None:
    """Test that new VPD sensor creation logic in coordinator update is covered."""
    coordinator = MagicMock()
    # Linking async and sync refresh mocks
    coordinator.request_refresh = MagicMock()
    coordinator.async_request_refresh = AsyncMock()

    gs = Growspace(id="gs1", name="GS1")
    gs.environment_config = EnvironmentConfig(vpd_sensor="sensor.calculated_vpd_gs1")
    coordinator.growspaces = {"gs1": gs}

    config_entry = MagicMock()
    config_entry.runtime_data = coordinator
    growspace_entities: dict[str, Any] = {}
    calculated_vpd_growspace_ids: set[str] = set()
    mock_add_entities = MagicMock()

    with patch(
        "custom_components.growspace_manager.sensor._check_calculated_vpd_sensor"
    ) as mock_check:
        mock_vpd_entity = MagicMock()
        mock_vpd_entity.unique_id = "gs1"
        mock_check.return_value = [mock_vpd_entity]

        with patch(
            "custom_components.growspace_manager.sensor._async_create_derivative_sensors"
        ):
            await _update_growspace_entities(
                hass,
                coordinator,
                config_entry,
                growspace_entities,
                mock_add_entities,
                calculated_vpd_growspace_ids,
            )

    assert (
        coordinator.request_refresh.called or coordinator.async_request_refresh.called
    )


async def test_config_flow_add_growspace_exception(hass: HomeAssistant) -> None:
    """Test exception handling in add growspace step."""
    flow = ConfigFlow()
    flow.hass = hass

    # Mock create_entry to raise exception
    flow.async_create_entry = MagicMock(side_effect=Exception("Failed"))

    user_input = {
        "name": "GS1",
        "rows": 1,
        "plants_per_row": 2,
    }

    result = await flow.async_step_add_growspace(user_input)

    assert result["type"] == "form"
    assert result["errors"] == {"base": "Error: Failed"}
    assert result["step_id"] == "add_growspace"


async def test_light_cycle_sensor_stages_negative(hass: HomeAssistant) -> None:
    """Test light cycle sensor with negative flower days (fallback)."""
    mock_coord = MagicMock()
    sensor = LightCycleVerificationSensor(
        mock_coord,
        "gs1",
        EnvironmentConfig(),
        get_plants=mock_coord.get_growspace_plants,
        calculate_days=lambda d: 30,
    )

    assert sensor._get_current_stage_key({"flower_days": -5}) == PlantStage.VEG


async def test_config_flow_missing_env_config_coverage(hass: HomeAssistant) -> None:
    """Test config flow with explicitly missing environment config path."""
    mock_entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    mock_entry.add_to_hass(hass)

    mock_coordinator = MagicMock()
    mock_entry.runtime_data = mock_coordinator

    real_gs = Growspace(id="gs1", name="GS1", environment_config=EnvironmentConfig())

    mock_coordinator.growspaces = {"gs1": real_gs}
    mock_coordinator.services.get_growspace.return_value = real_gs
    mock_coordinator.data_repository.get_growspace.return_value = real_gs

    flow = OptionsFlowHandler(mock_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    step_result = await flow.async_step_configure_environment(None)
    assert step_result["type"] == FlowResultType.FORM


async def test_async_remove_growspace_device_cleanup(hass: HomeAssistant) -> None:
    """Test removing a growspace cleans up the device registry."""
    coordinator = GrowspaceCoordinator(hass, MagicMock())
    coordinator.services.save = AsyncMock()  # type: ignore[method-assign]
    coordinator.invalidate_cache = MagicMock()  # type: ignore[method-assign]

    # Setup growspace
    coordinator.growspaces["gs1"] = Growspace(id="gs1", name="Test Only")

    # Mock device registry
    mock_dev_reg = MagicMock()
    mock_device = MagicMock()
    mock_device.id = "dev_123"
    mock_dev_reg.async_get_device.return_value = mock_device

    with patch(
        "homeassistant.helpers.device_registry.async_get", return_value=mock_dev_reg
    ):
        await coordinator.services.remove_growspace("gs1")

    mock_dev_reg.async_remove_device.assert_called_once_with("dev_123")


async def test_promote_clone_custom_target(hass: HomeAssistant) -> None:
    """Test promoting a clone to a custom growspace."""
    # 1. Initialize a real coordinator
    coordinator = GrowspaceCoordinator(hass, MagicMock())

    # 2. Setup standard AsyncMocks for anything awaited
    mock_update = AsyncMock()
    coordinator.services.save = AsyncMock()

    # 3. DEEP INJECTION: Manually override the methods on EVERY instance
    # This ensures that even if the facade has a 'stale' reference to a manager,
    # the method itself is replaced.
    coordinator.async_update_plant = mock_update
    if hasattr(coordinator, "lifecycle_manager"):
        coordinator.lifecycle_manager.async_update_plant = mock_update
    if hasattr(coordinator, "plant_manager"):
        coordinator.plant_manager.async_update_plant = mock_update

    # Check if the facade has its own internal references to managers
    # (Update these attribute names based on your actual facade implementation)
    for attr in dir(coordinator.services):
        if "manager" in attr:
            mgr = getattr(coordinator.services, attr)
            if hasattr(mgr, "async_update_plant"):
                mgr.async_update_plant = mock_update

    # 4. Prepare data
    plant = create_plant(
        plant_id="p1", growspace_id="clone_room", stage=PlantStage.CLONE
    )
    source_gs = Growspace(id="clone_room", name="Clone Room")
    target_gs = Growspace(id="custom_room", name="Custom Room")

    # 5. SATURATION MOCKING for lookups
    def get_gs_side_effect(gs_id):
        if gs_id == "clone_room":
            return source_gs
        if gs_id == "custom_room":
            return target_gs
        return None

    for obj in [coordinator, coordinator.data_repository, coordinator.services]:
        obj.get_growspace = MagicMock(side_effect=get_gs_side_effect)
        obj.get_plant = MagicMock(return_value=plant)

    coordinator.plants = {"p1": plant}
    coordinator.growspaces = {"clone_room": source_gs, "custom_room": target_gs}

    # 6. Execute
    with patch.object(
        coordinator.validator, "find_first_available_position", return_value=(1, 1)
    ):
        await coordinator.services.promote_clone(
            "p1", target_growspace_id="custom_room"
        )

    # 7. Final Check
    assert mock_update.called


async def test_resolve_entity_id_special_detected(hass: HomeAssistant) -> None:
    """Test resolving entity ID for special growspace."""
    coordinator = GrowspaceCoordinator(hass, MagicMock())
    mock_reg = MagicMock()

    def async_get_entity_id_side_effect(domain, platform, unique_id):
        return "sensor.dry" if unique_id == "dry_uid" else None

    mock_reg.async_get_entity_id.side_effect = async_get_entity_id_side_effect

    patch_path = "custom_components.growspace_manager.coordinator.generate_growspace_overview_unique_id"

    with (
        patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_reg),
        patch(patch_path, create=True) as mock_gen_uid,
    ):
        mock_gen_uid.side_effect = lambda gs_id: (
            "dry_uid" if gs_id == "dry" else "other_uid"
        )

        eid = coordinator._guess_overview_entity_id("drying")
        assert eid == "sensor.dry"
