"""Tests for new sensor classes in sensor.py to increase coverage."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.models import (
    CropSteeringState,
    DryingData,
    ECRampCurve,
    ECRampPoint,
    EnergyTracking,
    EnvironmentConfig,
    Plant,
    Subarea,
    WaterUsageData,
)
from custom_components.growspace_manager.sensor import (
    CropSteeringSensor,
    DLISensor,
    ECTargetSensor,
    EnergyUsageSensor,
    PlantEntity,
    SubareaCalculatedVpdSensor,
    WaterUsageSensor,
    _async_create_derivative_sensors,
    _check_calculated_vpd_sensor,
    _check_subarea_calculated_vpd_sensors,
    _create_initial_entities,
)
from custom_components.growspace_manager.sensor.usage import PowerUsageSensor
from homeassistant.util import dt as dt_util


def _make_coordinator(**kwargs):
    """Create a minimal mock coordinator suitable for CoordinatorEntity subclasses."""
    coordinator = MagicMock()
    coordinator.growspaces = kwargs.get("growspaces", {})
    coordinator.plants = kwargs.get("plants", {})
    coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=kwargs.get("plants_list", [])
    )
    coordinator.async_add_listener = MagicMock()
    return coordinator


# ---------------------------------------------------------------------------
# Small branch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_create_derivative_sensors_no_env_config() -> None:
    """Line 80: returns early when environment_config is falsy."""
    growspace = Mock(environment_config=None)
    config_entry = Mock()
    config_entry.runtime_data = Mock(created_entity_ids=[])
    # Should complete without error and without calling any setup helpers
    await _async_create_derivative_sensors(MagicMock(), config_entry, growspace)


@pytest.mark.asyncio
async def test_async_create_derivative_sensors_singular_sensor_inserts() -> None:
    """Line 117: singular_val is prepended to sensors list when absent from plural list."""
    growspace = Mock(id="gs1", name="GS1")
    # Plural list is empty; singular key has a value not yet in the list
    growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "temperature_sensors": [],
        "humidity_sensor": None,
        "humidity_sensors": [],
        "vpd_sensor": None,
        "vpd_sensors": [],
    }
    config_entry = Mock()
    config_entry.runtime_data = Mock(created_entity_ids=[])

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
            return_value="uid1",
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
            return_value="uid2",
        ),
    ):
        await _async_create_derivative_sensors(MagicMock(), config_entry, growspace)
    # If line 117 executed, sensors list contained "sensor.temp" and setup was called


def test_check_calculated_vpd_sensor_no_env_config() -> None:
    """Line 436: returns [] when environment_config is None."""
    growspace = Mock(environment_config=None)
    result = _check_calculated_vpd_sensor(MagicMock(), growspace)
    assert result == []


def test_check_calculated_vpd_sensor_singular_fallback() -> None:
    """Lines 451, 453: singular temp/humidity sensors used when plural lists are empty."""
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        # temperature_sensors and humidity_sensors default to []
    )
    growspace = Mock(id="gs1", name="GS1", environment_config=env_config)
    result = _check_calculated_vpd_sensor(MagicMock(), growspace)
    # Exactly one T/H pair → one CalculatedVpdSensor
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _create_initial_entities branch tests
# ---------------------------------------------------------------------------


class _DictEnvConfig(dict):
    """Dict subclass that passes isinstance(x, dict) while exposing attributes."""

    light_sensors: list = []
    energy_sensors: list = []
    power_sensors: list = []


@pytest.mark.asyncio
async def test_create_initial_entities_dli_and_energy_sensors_created() -> None:
    """Lines 325, 337: DLI and EnergyUsage sensors created when configured."""
    hass = MagicMock()
    env_config = EnvironmentConfig(
        light_sensors=["sensor.ppfd"],
        energy_sensors=["sensor.energy"],
    )
    growspace = Mock(
        id="gs1",
        name="Tent 1",
        environment_config=env_config,
        irrigation_strategy=Mock(enabled=False),
        subareas=[],
    )
    coordinator = _make_coordinator(growspaces={"gs1": growspace})
    coordinator.created_entity_ids = []
    config_entry = Mock()
    config_entry.runtime_data = coordinator

    initial_entities: list = []
    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await _create_initial_entities(
            hass,
            coordinator,
            config_entry,
            initial_entities,
            {},
            {},
            set(),
            set(),
            set(),
        )

    assert any(isinstance(e, DLISensor) for e in initial_entities)
    assert any(isinstance(e, EnergyUsageSensor) for e in initial_entities)


@pytest.mark.asyncio
async def test_create_initial_entities_dict_env_config_with_tank() -> None:
    """Lines 272, 280: dict-based env_config with dict tanks is handled."""
    hass = MagicMock()
    dict_env_config = _DictEnvConfig(
        irrigation_tanks=[
            {
                "name": "Tank A",
                "sensor_entity": "sensor.tank_a",
                "enable_prediction": True,
            }
        ]
    )
    growspace = Mock(
        id="gs1",
        name="Tent 1",
        environment_config=dict_env_config,
        irrigation_strategy=Mock(enabled=False),
        subareas=[],
    )
    coordinator = _make_coordinator(growspaces={"gs1": growspace})
    coordinator.created_entity_ids = []
    config_entry = Mock()
    config_entry.runtime_data = coordinator

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.TankDepletionPredictor"
        ) as mock_tdp,
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        mock_tdp.return_value.async_update = AsyncMock()
        await _create_initial_entities(
            hass, coordinator, config_entry, [], {}, {}, set(), set(), set()
        )

    mock_tdp.assert_called_once()


# ---------------------------------------------------------------------------
# PlantEntity PHI test
# ---------------------------------------------------------------------------


def test_plant_entity_phi_days_remaining() -> None:
    """Lines 1018-1019: PHI clearance days remaining computed from date."""
    coordinator = _make_coordinator()

    plant = Mock()
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.strain = "OG"
    plant.phenotype = ""
    plant.row = 1
    plant.col = 1
    plant.phi_clearance_date = "2026-01-20"  # 8 days from frozen "2026-01-12"
    plant.last_watered = None
    plant.get_days_in_stage = Mock(return_value=0)
    plant.get_week_in_stage = Mock(return_value=1)
    plant.get_days_since_watering = Mock(return_value=None)
    plant.scores = Mock(to_dict=Mock(return_value={}))
    plant.harvest_metrics = Mock(to_dict=Mock(return_value={}), wet_weight=None)
    plant.drying_data = DryingData()

    coordinator.plants = {"p1": plant}
    coordinator.growspaces = {"gs1": Mock(name="GS")}

    entity = PlantEntity(coordinator, plant)
    attrs = entity.extra_state_attributes

    assert attrs["phi_clearance_date"] == "2026-01-20"
    assert attrs["phi_days_remaining"] == 8


# ---------------------------------------------------------------------------
# DLISensor tests
# ---------------------------------------------------------------------------


def _make_dli_sensor():
    coordinator = _make_coordinator()
    sensor = DLISensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    sensor.async_write_ha_state = MagicMock()
    return sensor, coordinator


def test_dli_sensor_init() -> None:
    """Lines 1148-1155: DLISensor initialises correctly."""
    sensor, _ = _make_dli_sensor()
    assert sensor._growspace_id == "gs1"
    assert sensor._accumulated_mol == 0.0
    assert sensor._last_sample_time is None
    assert sensor._last_reset_date == ""


def test_dli_sensor_get_current_ppfd_returns_value() -> None:
    """Lines 1164-1171: _get_current_ppfd returns float from first valid state."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(environment_config=Mock(light_sensors=["sensor.ppfd"]))
    coordinator.growspaces = {"gs1": growspace}
    sensor.hass.states.get.return_value = Mock(state="450.0")

    assert sensor._get_current_ppfd() == 450.0


def test_dli_sensor_get_current_ppfd_no_growspace() -> None:
    """_get_current_ppfd returns None when growspace is absent."""
    sensor, coordinator = _make_dli_sensor()
    coordinator.growspaces = {}
    assert sensor._get_current_ppfd() is None


def test_dli_sensor_get_current_ppfd_unavailable_state() -> None:
    """Lines 1172-1173: _get_current_ppfd skips unavailable states and returns None."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(environment_config=Mock(light_sensors=["sensor.ppfd"]))
    coordinator.growspaces = {"gs1": growspace}
    sensor.hass.states.get.return_value = Mock(state="unavailable")

    assert sensor._get_current_ppfd() is None


def test_dli_sensor_native_value_zero() -> None:
    """Line 1180: native_value returns 0.0 when accumulated mol is 0."""
    sensor, _ = _make_dli_sensor()
    assert sensor.native_value == 0.0


def test_dli_sensor_native_value_nonzero() -> None:
    """Line 1180: native_value rounds to 1 decimal when accumulated mol > 0."""
    sensor, _ = _make_dli_sensor()
    sensor._accumulated_mol = 12.345
    assert sensor.native_value == 12.3


def test_dli_sensor_extra_state_attributes_flower() -> None:
    """Lines 1186-1212: extra_state_attributes for a flower-type growspace."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(
        environment_config=Mock(
            light_sensors=["sensor.ppfd"],
            flower_day_hours=12.0,
            dli_target_flower=40.0,
        )
    )
    growspace.growspace_type = Mock(value="flower")
    coordinator.growspaces = {"gs1": growspace}
    sensor._accumulated_mol = 10.0
    sensor.hass.states.get.return_value = Mock(state="450.0")

    attrs = sensor.extra_state_attributes
    assert attrs["target_dli"] == 40.0
    assert attrs["percentage_of_target"] == 25.0
    assert attrs["ppfd_current"] == 450.0


def test_dli_sensor_extra_state_attributes_veg() -> None:
    """Lines 1203-1205: veg-type growspace uses veg_day_hours and dli_target_veg."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(
        environment_config=Mock(
            light_sensors=["sensor.ppfd"],
            veg_day_hours=18.0,
            dli_target_veg=30.0,
        )
    )
    growspace.growspace_type = Mock(value="veg")
    coordinator.growspaces = {"gs1": growspace}
    sensor._accumulated_mol = 15.0
    sensor.hass.states.get.return_value = Mock(state="300.0")

    attrs = sensor.extra_state_attributes
    assert attrs["target_dli"] == 30.0


def test_dli_sensor_handle_coordinator_update_resets_at_midnight() -> None:
    """Lines 1216-1233: _handle_coordinator_update resets when date changes."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(environment_config=Mock(light_sensors=[]))
    coordinator.growspaces = {"gs1": growspace}
    sensor.hass.states.get.return_value = None  # No ppfd sensor

    # First call with empty _last_reset_date triggers reset
    sensor._handle_coordinator_update()

    assert sensor._last_reset_date == "2026-01-12"
    assert sensor._accumulated_mol == 0.0
    assert sensor._last_sample_time is not None
    sensor.async_write_ha_state.assert_called()


# ---------------------------------------------------------------------------
# CropSteeringSensor tests
# ---------------------------------------------------------------------------


def _make_crop_sensor():
    coordinator = _make_coordinator()
    sensor = CropSteeringSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator


def test_crop_steering_sensor_native_value() -> None:
    """Lines 1266-1269: native_value returns rounded score when state is present."""
    sensor, _ = _make_crop_sensor()
    state = CropSteeringState(score=0.75)
    with patch(
        "custom_components.growspace_manager.sensor.crop_steering.get_crop_steering_state",
        return_value=state,
    ):
        assert sensor.native_value == 0.75


def test_crop_steering_sensor_native_value_none() -> None:
    """native_value returns None when get_crop_steering_state returns None."""
    sensor, _ = _make_crop_sensor()
    with patch(
        "custom_components.growspace_manager.sensor.crop_steering.get_crop_steering_state",
        return_value=None,
    ):
        assert sensor.native_value is None


@pytest.mark.parametrize(
    ("score", "expected_mode"),
    [
        (0.5, "generative"),
        (-0.5, "vegetative"),
        (0.0, "balanced"),
    ],
)
def test_crop_steering_sensor_extra_attrs_mode(score, expected_mode) -> None:
    """extra_state_attributes surfaces the measured classification from the state."""
    sensor, _ = _make_crop_sensor()
    state = CropSteeringState(
        score=score,
        dryback_percent=15.0,
        peak_vwc=40.0,
        trough_vwc=25.0,
        ec_trend="stable",
        measured_classification=expected_mode,
    )
    with patch(
        "custom_components.growspace_manager.sensor.crop_steering.get_crop_steering_state",
        return_value=state,
    ):
        attrs = sensor.extra_state_attributes
    assert attrs["measured_classification"] == expected_mode


def test_crop_steering_sensor_extra_attrs_no_state() -> None:
    """extra_state_attributes returns {} when crop steering state is None."""
    sensor, _ = _make_crop_sensor()
    with patch(
        "custom_components.growspace_manager.sensor.crop_steering.get_crop_steering_state",
        return_value=None,
    ):
        assert sensor.extra_state_attributes == {}


def test_crop_steering_sensor_exposes_measured_classification_and_deviation() -> None:
    """The sensor surfaces the measured classification and intent deviation."""
    sensor, _ = _make_crop_sensor()
    state = CropSteeringState(
        score=0.2,
        dryback_percent=20.0,
        peak_vwc=70.0,
        trough_vwc=50.0,
        measured_classification="balanced",
        intent_deviation="more_vegetative",
    )
    with patch(
        "custom_components.growspace_manager.sensor.crop_steering.get_crop_steering_state",
        return_value=state,
    ):
        attrs = sensor.extra_state_attributes
    assert attrs["intent_deviation"] == "more_vegetative"
    assert attrs["measured_classification"] == "balanced"
    # The old ambiguous key is gone; declared intent lives in the strategy
    # payload's declared_steering_mode, not duplicated on the sensor.
    assert "steering_mode" not in attrs
    assert "declared_intent" not in attrs


# ---------------------------------------------------------------------------
# EnergyUsageSensor tests
# ---------------------------------------------------------------------------


def _make_energy_sensor():
    coordinator = _make_coordinator()
    growspace = Mock()
    growspace.energy_tracking = EnergyTracking(
        cycle_start_kwh=50.0, cycle_start_date="2026-01-01"
    )
    growspace.environment_config = Mock(
        energy_sensors=["sensor.energy"],
        electricity_cost_per_kwh=0.15,
    )
    coordinator.growspaces = {"gs1": growspace}

    sensor = EnergyUsageSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator, growspace


def test_energy_sensor_init() -> None:
    """Lines 1315-1319: EnergyUsageSensor initialises with correct identifiers."""
    sensor, _, _ = _make_energy_sensor()
    assert sensor._growspace_id == "gs1"
    assert "gs1_energy_usage" in sensor._attr_unique_id


def test_energy_sensor_get_total_kwh() -> None:
    """Lines 1328-1339: _get_total_kwh sums states from configured energy sensors."""
    sensor, coordinator, growspace = _make_energy_sensor()
    growspace.environment_config.energy_sensors = ["sensor.e1", "sensor.e2"]
    sensor.hass.states.get.side_effect = lambda eid: {
        "sensor.e1": Mock(state="100.0"),
        "sensor.e2": Mock(state="50.5"),
    }.get(eid)

    assert sensor._get_total_kwh() == 150.5


def test_energy_sensor_get_total_kwh_no_growspace() -> None:
    """_get_total_kwh returns 0.0 when growspace is missing."""
    sensor, coordinator, _ = _make_energy_sensor()
    coordinator.growspaces = {}
    assert sensor._get_total_kwh() == 0.0


def test_energy_sensor_get_total_kwh_invalid_state() -> None:
    """Lines 1337-1338: _get_total_kwh skips sensors with non-numeric states."""
    sensor, _, growspace = _make_energy_sensor()
    growspace.environment_config.energy_sensors = ["sensor.bad"]
    sensor.hass.states.get.return_value = Mock(state="not-a-number")
    assert sensor._get_total_kwh() == 0.0


def test_energy_sensor_native_value() -> None:
    """Lines 1345-1350: native_value returns usage above cycle start."""
    sensor, _, _ = _make_energy_sensor()
    sensor.hass.states.get.return_value = Mock(state="150.0")  # 150 - 50 = 100
    assert sensor.native_value == 100.0


def test_energy_sensor_extra_state_attributes() -> None:
    """Lines 1356-1361: extra_state_attributes includes cost and cycle start date."""
    sensor, _, _ = _make_energy_sensor()
    sensor.hass.states.get.return_value = Mock(state="150.0")  # 100 kWh used

    attrs = sensor.extra_state_attributes
    assert attrs["cost_total"] == 15.0  # 100 * 0.15
    assert attrs["cycle_start_date"] == "2026-01-01"


def test_energy_sensor_extra_state_attributes_no_growspace() -> None:
    """extra_state_attributes returns {} when growspace is missing."""
    sensor, coordinator, _ = _make_energy_sensor()
    coordinator.growspaces = {}
    assert sensor.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# WaterUsageSensor tests
# ---------------------------------------------------------------------------


def _make_water_sensor():
    coordinator = _make_coordinator()
    growspace = Mock()
    growspace.water_usage = WaterUsageData(
        total_liters=25.5,
        cycle_start_date="2026-01-01",
        daily_readings=[{"date": "2026-01-12", "liters": 5.0}],
    )
    coordinator.growspaces = {"gs1": growspace}
    coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[Mock(), Mock()]
    )

    sensor = WaterUsageSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator, growspace


def test_water_sensor_native_value() -> None:
    """Lines 1399-1402: native_value returns rounded total liters."""
    sensor, _, _ = _make_water_sensor()
    assert sensor.native_value == 25.5


def test_water_sensor_native_value_no_growspace() -> None:
    """native_value returns None when growspace is missing."""
    sensor, coordinator, _ = _make_water_sensor()
    coordinator.growspaces = {}
    assert sensor.native_value is None


def test_water_sensor_extra_state_attributes() -> None:
    """Lines 1408-1438: extra_state_attributes computes per-plant and today usage."""
    sensor, _, _ = _make_water_sensor()
    attrs = sensor.extra_state_attributes

    # Frozen date: 2026-01-12; cycle_start: 2026-01-01 → 11 days, 2 plants
    expected_per_plant = round(25.5 / 2 / 11, 2)
    assert attrs["liters_per_plant_per_day"] == expected_per_plant
    assert attrs["liters_today"] == 5.0
    assert attrs["cycle_start_date"] == "2026-01-01"


def test_water_sensor_extra_state_attributes_no_growspace() -> None:
    """extra_state_attributes returns {} when growspace is missing."""
    sensor, coordinator, _ = _make_water_sensor()
    coordinator.growspaces = {}
    assert sensor.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# WaterUsageSensor — tank-derived mode
# ---------------------------------------------------------------------------


def _make_water_sensor_tank_derived(
    tracker_liters_since: float = 30.0,
    tracker_liters_today: float = 8.0,
    cycle_start_date: str = "2026-01-01",
    num_trackers: int = 1,
):
    """Factory for WaterUsageSensor in tank-derived mode.

    Returns (sensor, coordinator, growspace, trackers).
    """
    coordinator = _make_coordinator()
    growspace = Mock()
    growspace.water_usage = WaterUsageData(
        total_liters=0.0,
        cycle_start_date=cycle_start_date,
        daily_readings=[],
    )
    env = Mock()
    env.irrigation_flow_sensors = []
    env.drain_volume_sensors = []
    env.irrigation_tanks = [Mock(volume_liters=50.0)]
    growspace.environment_config = env
    coordinator.growspaces = {"gs1": growspace}
    coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[Mock(), Mock()]
    )

    trackers = {}
    for i in range(num_trackers):
        tracker = MagicMock()
        tracker.get_total_liters_since.return_value = tracker_liters_since
        tracker.get_total_liters_today.return_value = tracker_liters_today
        trackers[f"sensor.tank_{i}"] = tracker

    coordinator.services.growspaces.get_all_trackers_for_growspace = MagicMock(
        return_value=trackers
    )

    sensor = WaterUsageSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator, growspace, trackers


def test_water_sensor_native_value_tank_derived_adds_manual() -> None:
    """Tank mode reports tank-derived + manual on top (ADR-0017)."""
    sensor, _, growspace, _ = _make_water_sensor_tank_derived(
        tracker_liters_since=42.0, tracker_liters_today=8.0
    )
    # Manual water lives in WaterUsageData; pump estimates are write-gated out
    # of tank mode, so this adds manual only.
    growspace.water_usage.total_liters = 10.0
    growspace.water_usage.daily_readings = [
        {"date": "2026-01-12", "liters": 3.0, "source": "manual"}
    ]

    assert sensor.native_value == 52.0  # 42 tank cycle + 10 manual cycle
    attrs = sensor.extra_state_attributes
    assert attrs["liters_today"] == 11.0  # 8 tank today + 3 manual today
    assert attrs["liters_cycle"] == 52.0


def test_water_sensor_native_value_tank_derived() -> None:
    """native_value reads from TankWaterTracker when tank-derived mode is active."""
    sensor, _, _, _ = _make_water_sensor_tank_derived(tracker_liters_since=42.0)
    assert sensor.native_value == 42.0


def test_water_sensor_native_value_tank_derived_multiple_trackers() -> None:
    """native_value sums across all qualifying trackers."""
    sensor, _, _, _ = _make_water_sensor_tank_derived(
        tracker_liters_since=15.0, num_trackers=3
    )
    assert sensor.native_value == 45.0  # 3 × 15.0


def test_water_sensor_extra_state_attributes_tank_derived() -> None:
    """extra_state_attributes uses tracker data for liters_today and total."""
    sensor, _, _, _ = _make_water_sensor_tank_derived(
        tracker_liters_since=30.0,
        tracker_liters_today=8.0,
        cycle_start_date="2026-01-01",
    )
    attrs = sensor.extra_state_attributes

    # cycle_start_date passed through unchanged
    assert attrs["cycle_start_date"] == "2026-01-01"
    # liters_today comes from tracker, not daily_readings
    assert attrs["liters_today"] == 8.0
    # liters_per_plant_per_day uses tracker total (30 L / 2 plants / 11 days)
    expected = round(30.0 / 2 / 11, 2)
    assert attrs["liters_per_plant_per_day"] == expected


def test_water_sensor_tank_derived_mode_disabled_when_flow_sensors_configured() -> None:
    """native_value falls back to WaterUsageData when flow sensors are configured."""
    sensor, coordinator, growspace, _ = _make_water_sensor_tank_derived(
        tracker_liters_since=99.0
    )
    growspace.environment_config.irrigation_flow_sensors = ["sensor.flow_1"]
    growspace.water_usage.total_liters = 25.0

    assert sensor.native_value == 25.0


def test_water_sensor_tank_derived_mode_disabled_when_drain_sensors_configured() -> (
    None
):
    """native_value falls back to WaterUsageData when drain sensors are configured."""
    sensor, coordinator, growspace, _ = _make_water_sensor_tank_derived(
        tracker_liters_since=99.0
    )
    growspace.environment_config.drain_volume_sensors = ["sensor.drain_1"]
    growspace.water_usage.total_liters = 18.0

    assert sensor.native_value == 18.0


def test_water_sensor_tank_derived_no_trackers_falls_back_to_usage_data() -> None:
    """native_value falls back to WaterUsageData when no trackers are registered."""
    sensor, coordinator, growspace, _ = _make_water_sensor_tank_derived()
    coordinator.services.growspaces.get_all_trackers_for_growspace = MagicMock(
        return_value={}
    )
    growspace.water_usage.total_liters = 7.5

    assert sensor.native_value == 7.5


# ---------------------------------------------------------------------------
# ECTargetSensor tests
# ---------------------------------------------------------------------------


def _make_ec_sensor():
    coordinator = _make_coordinator()
    sensor = ECTargetSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator


def _flower_curve() -> ECRampCurve:
    return ECRampCurve(
        id="c1",
        name="Bloom",
        stage="flower",
        points=[
            ECRampPoint(week=1, ec_min=1.2, ec_max=1.6),
            ECRampPoint(week=2, ec_min=1.4, ec_max=1.8),
        ],
        created_at="2026-01-01",
    )


def _flower_plant(days_in_flower: int) -> Plant:
    """A real plant N days into flower, for exercising the real stage/week seam."""
    start = (dt_util.now() - timedelta(days=days_in_flower)).isoformat()
    return Plant(plant_id="p1", growspace_id="gs1", flower_start=start)


def test_ec_sensor_get_active_curve_no_growspace() -> None:
    """Lines 1482-1484: _get_active_curve returns None when growspace is missing."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.growspaces = {}
    coordinator.services.config.ec_ramp_curves = {}
    assert sensor._get_active_curve() is None


def test_ec_sensor_get_active_curve_no_plants() -> None:
    """Lines 1486-1488: _get_active_curve returns None when no plants in growspace."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.config.ec_ramp_curves = {"c1": _flower_curve()}
    coordinator.services.growspaces.get_growspace_plants.return_value = []
    assert sensor._get_active_curve() is None


def test_ec_sensor_get_active_curve_matches() -> None:
    """_get_active_curve returns the curve matching the feed stage."""
    sensor, coordinator = _make_ec_sensor()
    curve = _flower_curve()
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(7)
    ]

    assert sensor._get_active_curve() is curve


def test_ec_sensor_get_active_curve_no_match() -> None:
    """_get_active_curve returns None when no curve matches the feed stage."""
    sensor, coordinator = _make_ec_sensor()
    veg_curve = ECRampCurve(
        id="c1", name="Veg", stage="veg", points=[], created_at="2026-01-01"
    )
    coordinator.services.config.ec_ramp_curves = {"c1": veg_curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(7)
    ]

    assert sensor._get_active_curve() is None


def test_ec_sensor_get_current_week() -> None:
    """_get_current_week uses the canonical days_to_week (14 days → week 2)."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(14)
    ]
    assert sensor._get_current_week() == 2  # days_to_week(14), was (14//7)+1=3


def test_ec_sensor_get_current_week_no_plants() -> None:
    """_get_current_week returns 0 when no live plants exist."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.services.growspaces.get_growspace_plants.return_value = []
    assert sensor._get_current_week() == 0


def test_ec_sensor_native_value_exact_week_match() -> None:
    """native_value returns the midpoint for an exact week match."""
    sensor, coordinator = _make_ec_sensor()
    curve = _flower_curve()
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(10)  # days_to_week(10) → week 2
    ]

    assert sensor.native_value == 1.6  # (1.4 + 1.8) / 2


def test_ec_sensor_native_value_fallback_last_point() -> None:
    """native_value falls back to the last point for weeks beyond the curve."""
    sensor, coordinator = _make_ec_sensor()
    curve = ECRampCurve(
        id="c1",
        name="Ramp",
        stage="flower",
        points=[ECRampPoint(week=1, ec_min=1.2, ec_max=1.6)],
        created_at="2026-01-01",
    )
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(21)  # week 3 > last week 1
    ]

    assert sensor.native_value == 1.4  # (1.2 + 1.6) / 2


def test_ec_sensor_native_value_no_curve() -> None:
    """native_value returns None when no active curve exists."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.services.config.ec_ramp_curves = {}
    coordinator.growspaces = {}
    assert sensor.native_value is None


def test_ec_sensor_extra_state_attributes_exact_match() -> None:
    """extra_state_attributes reports band, week, stage and curve name."""
    sensor, coordinator = _make_ec_sensor()
    curve = _flower_curve()
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(10)  # days_to_week(10) → week 2
    ]

    attrs = sensor.extra_state_attributes

    assert attrs["ec_min"] == 1.4
    assert attrs["ec_max"] == 1.8
    assert attrs["current_week"] == 2
    assert attrs["stage"] == "flower"
    assert attrs["curve_name"] == "Bloom"


def test_ec_sensor_extra_state_attributes_fallback_last_point() -> None:
    """extra_state_attributes falls back to the last point beyond the curve."""
    sensor, coordinator = _make_ec_sensor()
    curve = ECRampCurve(
        id="c1",
        name="Ramp",
        stage="flower",
        points=[ECRampPoint(week=1, ec_min=1.2, ec_max=1.6)],
        created_at="2026-01-01",
    )
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(21)  # week 3 > last week 1
    ]

    attrs = sensor.extra_state_attributes

    assert attrs["ec_min"] == 1.2
    assert attrs["ec_max"] == 1.6


def test_ec_sensor_extra_state_attributes_no_curve() -> None:
    """extra_state_attributes returns {} when no active curve."""
    sensor, coordinator = _make_ec_sensor()
    coordinator.services.config.ec_ramp_curves = {}
    coordinator.growspaces = {}
    assert sensor.extra_state_attributes == {}


# ---------------------------------------------------------------------------
# Additional tests for remaining uncovered lines
# ---------------------------------------------------------------------------


def test_check_calculated_vpd_sensor_dict_singular_fallback() -> None:
    """Lines 451, 453: dict env_config with empty plural lists uses singular fields."""
    env_config = {
        "temperature_sensors": [],
        "humidity_sensors": [],
        "vpd_sensors": [],
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": None,
        "lst_offset": 0.0,
    }
    growspace = Mock(id="gs1", name="GS1", environment_config=env_config)
    result = _check_calculated_vpd_sensor(MagicMock(), growspace)
    assert len(result) == 1


def test_dli_sensor_get_current_ppfd_invalid_state() -> None:
    """Lines 1172-1173: _get_current_ppfd continues past non-numeric state values."""
    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(environment_config=Mock(light_sensors=["sensor.ppfd"]))
    coordinator.growspaces = {"gs1": growspace}
    sensor.hass.states.get.return_value = Mock(state="not-a-number")
    assert sensor._get_current_ppfd() is None


def test_dli_sensor_handle_coordinator_update_accumulates_ppfd() -> None:
    """Lines 1227-1230: _handle_coordinator_update accumulates mol when elapsed > 0."""
    from datetime import datetime as dt_cls

    from homeassistant.util import dt as dt_util

    sensor, coordinator = _make_dli_sensor()
    growspace = Mock(environment_config=Mock(light_sensors=["sensor.ppfd"]))
    coordinator.growspaces = {"gs1": growspace}
    sensor.hass.states.get.return_value = Mock(state="500.0")

    # Already on today's date to skip midnight reset
    sensor._last_reset_date = "2026-01-12"
    # Set last sample to 1 minute before the frozen "2026-01-12 12:00:00"
    sensor._last_sample_time = dt_util.as_local(dt_cls(2026, 1, 12, 11, 59, 0))

    sensor._handle_coordinator_update()

    # 500 ppfd * 60 seconds / 1_000_000 = 0.03 mol
    assert sensor._accumulated_mol > 0.0


def test_energy_sensor_native_value_no_growspace() -> None:
    """Line 1347: native_value returns None when growspace is missing."""
    sensor, coordinator, _ = _make_energy_sensor()
    coordinator.growspaces = {}
    assert sensor.native_value is None


def test_water_sensor_extra_state_attributes_invalid_date() -> None:
    """Lines 1421-1422: extra_state_attributes handles invalid cycle_start_date."""
    sensor, coordinator, growspace = _make_water_sensor()
    growspace.water_usage = WaterUsageData(
        total_liters=10.0,
        cycle_start_date="not-a-valid-date",
        daily_readings=[],
    )
    attrs = sensor.extra_state_attributes
    # Days defaults to 1, no exception raised
    assert "liters_per_plant_per_day" in attrs


def test_ec_sensor_get_active_curve_no_nutrient_manager() -> None:
    """_get_active_curve returns None when ec_ramp_curves is empty."""
    sensor, _ = _make_ec_sensor()
    coordinator = MagicMock()
    coordinator.services.config.ec_ramp_curves = {}
    sensor.coordinator = coordinator
    assert sensor._get_active_curve() is None


def test_ec_sensor_get_active_curve_no_ec_ramp_curves_attr() -> None:
    """_get_active_curve returns None when ec_ramp_curves is None/falsy."""
    sensor, _ = _make_ec_sensor()
    coordinator = MagicMock()
    coordinator.services.config.ec_ramp_curves = None
    sensor.coordinator = coordinator
    assert sensor._get_active_curve() is None


def test_ec_sensor_native_value_before_first_point() -> None:
    """Line 1520: native_value returns None when current week is before first point's week."""
    sensor, coordinator = _make_ec_sensor()
    curve = ECRampCurve(
        id="c1",
        name="Ramp",
        stage="flower",
        points=[ECRampPoint(week=5, ec_min=1.6, ec_max=2.0)],
        created_at="2026-01-01",
    )
    coordinator.services.config.ec_ramp_curves = {"c1": curve}
    coordinator.growspaces = {"gs1": Mock()}
    coordinator.services.growspaces.get_growspace_plants.return_value = [
        _flower_plant(14)  # week 2 < first point's week 5
    ]

    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# SubareaCalculatedVpdSensor and _check_subarea_calculated_vpd_sensors tests
# ---------------------------------------------------------------------------


def _make_subarea(
    subarea_id: str = "sub1",
    subarea_name: str = "Corner A",
    temp_sensors: list | None = None,
    hum_sensors: list | None = None,
    vpd_sensors: list | None = None,
) -> Subarea:
    env_config = EnvironmentConfig(
        temperature_sensors=temp_sensors or [],
        humidity_sensors=hum_sensors or [],
        vpd_sensors=vpd_sensors or [],
    )
    return Subarea(id=subarea_id, name=subarea_name, environment_config=env_config)


def test_check_subarea_no_subareas() -> None:
    """Returns empty list when growspace has no subareas."""
    growspace = Mock(subareas=[])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert result == []


def test_check_subarea_no_env_config() -> None:
    """Returns empty list when subarea has no environment_config."""
    subarea = Subarea(id="sub1", name="Zone A")
    subarea.environment_config = None  # type: ignore[assignment]
    growspace = Mock(subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert result == []


def test_check_subarea_missing_humidity() -> None:
    """Returns empty list when subarea has temperature but no humidity sensor."""
    subarea = _make_subarea(temp_sensors=["sensor.temp"])
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert result == []


def test_check_subarea_creates_sensor_when_no_vpd() -> None:
    """Creates one SubareaCalculatedVpdSensor when T+H sensors exist but no VPD."""
    subarea = _make_subarea(
        temp_sensors=["sensor.temp"],
        hum_sensors=["sensor.hum"],
    )
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert len(result) == 1
    assert isinstance(result[0], SubareaCalculatedVpdSensor)
    assert result[0]._attr_name == "Corner A Calculated VPD"
    assert "subarea_sub1" in result[0]._attr_unique_id


def test_check_subarea_skips_when_real_vpd_sensor_exists() -> None:
    """Does not create a sensor when a physical VPD sensor is already assigned."""
    subarea = _make_subarea(
        temp_sensors=["sensor.temp"],
        hum_sensors=["sensor.hum"],
        vpd_sensors=["sensor.real_vpd"],
    )
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert result == []


def test_check_subarea_replaces_calculated_vpd_placeholder() -> None:
    """Creates a sensor even when the existing VPD entry is a previous calculated sensor."""
    subarea = _make_subarea(
        temp_sensors=["sensor.temp"],
        hum_sensors=["sensor.hum"],
        vpd_sensors=["sensor.growspace_manager_gs1_subarea_sub1_calculated_vpd"],
    )
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert len(result) == 1


def test_check_subarea_multiple_pairs_indexed() -> None:
    """Creates indexed sensors when multiple T/H pairs are present."""
    subarea = _make_subarea(
        subarea_id="subA",
        subarea_name="Zone A",
        temp_sensors=["sensor.temp1", "sensor.temp2"],
        hum_sensors=["sensor.hum1", "sensor.hum2"],
    )
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert len(result) == 2
    assert result[0]._attr_name == "Zone A Calculated VPD 1"
    assert result[1]._attr_name == "Zone A Calculated VPD 2"


def test_check_subarea_singular_sensor_fallback() -> None:
    """Falls back to singular temperature_sensor / humidity_sensor fields."""
    env_config = EnvironmentConfig()
    env_config.temperature_sensor = "sensor.t"  # type: ignore[attr-defined]
    env_config.humidity_sensor = "sensor.h"  # type: ignore[attr-defined]
    subarea = Subarea(id="sub1", name="Top", environment_config=env_config)
    growspace = Mock(id="gs1", name="Tent", subareas=[subarea])
    result = _check_subarea_calculated_vpd_sensors(MagicMock(), growspace)
    assert len(result) == 1


def test_subarea_calculated_vpd_sensor_unique_id_and_name() -> None:
    """SubareaCalculatedVpdSensor generates correct unique_id and name."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    sensor = SubareaCalculatedVpdSensor(
        coordinator=coordinator,
        growspace_id="tent1",
        growspace_name="My Tent",
        subarea_id="zone_a",
        subarea_name="Zone A",
        temp_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
    )
    assert sensor._attr_name == "Zone A Calculated VPD"
    assert "subarea_zone_a" in sensor._attr_unique_id
    assert "tent1" in sensor._attr_unique_id


# ---------------------------------------------------------------------------
# PowerUsageSensor tests
# ---------------------------------------------------------------------------


def _make_power_sensor(power_sensors: list[str] | None = None):
    """Build a PowerUsageSensor with a minimal mock coordinator."""
    coordinator = _make_coordinator()
    growspace = Mock()
    growspace.environment_config = Mock(power_sensors=power_sensors or [])
    coordinator.growspaces = {"gs1": growspace}

    sensor = PowerUsageSensor(coordinator, "gs1", "Tent 1")
    sensor.hass = MagicMock()
    return sensor, coordinator, growspace


def test_power_sensor_init() -> None:
    """Lines 102-106: __init__ sets unique_id and device_info correctly."""
    sensor, _, _ = _make_power_sensor()
    assert "gs1_power_usage" in sensor._attr_unique_id
    assert sensor._growspace_id == "gs1"
    assert sensor._attr_device_info is not None


def test_power_sensor_native_value_no_growspace() -> None:
    """Line 118-119: native_value returns None when growspace is absent."""
    sensor, coordinator, _ = _make_power_sensor()
    coordinator.growspaces = {}
    assert sensor.native_value is None


def test_power_sensor_native_value_no_environment_config() -> None:
    """Line 118-119: native_value returns None when environment_config is falsy."""
    sensor, _, growspace = _make_power_sensor()
    growspace.environment_config = None
    assert sensor.native_value is None


def test_power_sensor_native_value_none_power_sensors() -> None:
    """Line 124: native_value returns None safely when power_sensors is None."""
    sensor, _, growspace = _make_power_sensor()
    growspace.environment_config.power_sensors = None
    assert sensor.native_value is None


def test_power_sensor_native_value_sums_valid_sensors() -> None:
    """Lines 120-130: native_value sums wattage from all valid power sensors."""
    sensor, _, growspace = _make_power_sensor(["sensor.p1", "sensor.p2"])
    growspace.environment_config.power_sensors = ["sensor.p1", "sensor.p2"]
    sensor.hass.states.get.side_effect = lambda eid: {
        "sensor.p1": Mock(state="500.0"),
        "sensor.p2": Mock(state="250.5"),
    }.get(eid)
    assert sensor.native_value == 750.5


def test_power_sensor_native_value_all_sensors_unavailable() -> None:
    """Lines 122-124: native_value returns None when all states are unavailable."""
    sensor, _, growspace = _make_power_sensor(["sensor.p1"])
    growspace.environment_config.power_sensors = ["sensor.p1"]
    sensor.hass.states.get.return_value = Mock(state="unavailable")
    assert sensor.native_value is None


def test_power_sensor_native_value_skips_non_numeric_state() -> None:
    """Lines 125-129: native_value skips sensors with non-numeric state values."""
    sensor, _, growspace = _make_power_sensor(["sensor.bad", "sensor.good"])
    growspace.environment_config.power_sensors = ["sensor.bad", "sensor.good"]
    sensor.hass.states.get.side_effect = lambda eid: {
        "sensor.bad": Mock(state="not-a-number"),
        "sensor.good": Mock(state="300.0"),
    }.get(eid)
    assert sensor.native_value == 300.0
