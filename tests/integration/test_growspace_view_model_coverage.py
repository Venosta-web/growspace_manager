from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import (
    ACInfinityDevice,
    ACInfinityGrowLight,
    EnvironmentConfig,
    ExhaustFanConfig,
    GrowLightConfig,
    Growspace,
    IrrigationConfig,
    IrrigationTank,
    Plant,
    SensorGroup,
    Subarea,
    WaterUsageData,
)
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
    _compute_tank_water_summaries,
)
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


@pytest.fixture
def builder(hass: HomeAssistant) -> GrowspaceViewModelBuilder:
    """Fixture for GrowspaceViewModelBuilder."""
    return GrowspaceViewModelBuilder(hass)


def test_growspace_view_model_build_basic(hass: HomeAssistant, builder):
    """Test basic build functionality."""
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp", humidity_sensor="sensor.hum"
    )
    growspace = Growspace(
        id="gs1",
        name="Test Room",
        rows=2,
        plants_per_row=2,
        environment_config=env_config,
    )

    plant1 = Plant(plant_id="p1", growspace_id="gs1", row=1, col=1)
    plants = [plant1]

    # Mock EntityQueries and PlantViewModelBuilder on the builder instance
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_overview_entity_id.return_value = (
        "sensor.gs1_overview"
    )
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"

    builder.plant_builder = MagicMock()
    builder.plant_builder.build.return_value = {"plant_id": "p1", "rich": True}

    result = builder.build(
        growspace=growspace,
        plants=plants,
        biological_metrics={"metrics": True},
        max_veg_days=10,
        max_flower_days=20,
    )

    assert result["identity"]["growspace_id"] == "gs1"
    assert result["identity"]["name"] == "Test Room"
    assert result["grid"]["total_plants"] == 1
    assert result["metrics"]["veg_week"] == 2
    assert result["metrics"]["flower_week"] == 3
    assert result["metrics"]["metrics"] is True
    assert result["grid"]["grid"]["position_1_1"]["rich"] is True
    assert result["grid"]["grid"]["position_1_2"] is None


@pytest.mark.parametrize(
    ("liters_per_pot", "flow_rate", "expected"),
    [
        (6.0, 20.0, True),  # both prerequisites present
        (0.0, 20.0, False),  # no substrate profile
        (6.0, 0.0, False),  # no pump flow rate
        (0.0, 0.0, False),  # neither
    ],
)
def test_volume_mode_capable_flag(
    hass: HomeAssistant, builder, liters_per_pot, flow_rate, expected
):
    """The payload exposes volume_mode_capable per the Volume Mode prerequisites."""
    from custom_components.growspace_manager.models import (
        IrrigationStrategy,
        SubstrateProfile,
    )

    growspace = Growspace(
        id="gs1",
        name="Test Room",
        rows=1,
        plants_per_row=1,
        environment_config=EnvironmentConfig(),
        irrigation_config=IrrigationConfig(pump_flow_rate_ml_per_sec=flow_rate),
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        substrate_profile=SubstrateProfile(liters_per_pot=liters_per_pot)
    )

    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_overview_entity_id.return_value = "sensor.gs1"
    builder.plant_builder = MagicMock()

    result = builder.build(growspace=growspace, plants=[], biological_metrics={})

    assert result["irrigation"]["volume_mode_capable"] is expected


def test_get_sensor_types(builder):
    """Test mapping of entity IDs to sensor types."""
    env_config = EnvironmentConfig(
        temperature_sensors=["sensor.t1", "sensor.t2"],
        humidity_sensors=["sensor.h1"],
        vpd_sensor="sensor.v1",
        light_sensors=["sensor.l1"],
        co2_sensor="sensor.co2",
        soil_moisture_sensor="sensor.soil",
        exhaust_fan_entities=["switch.exhaust"],
        circulation_fan_entities=["switch.circ"],
        humidifier_entities=["switch.hum"],
        dehumidifier_entities=["switch.dehum"],
        irrigation_tanks=[IrrigationTank(sensor_entity="sensor.tank", name="Tank 1")],
    )
    irr_config = IrrigationConfig(
        irrigation_pump_entity="switch.pump", drain_pump_entity="switch.drain"
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
        irrigation_config=irr_config,
    )

    types = builder._get_sensor_types(growspace)

    assert types["sensor.t1"] == "temperature"
    assert types["sensor.t2"] == "temperature"
    assert types["sensor.h1"] == "humidity"
    assert types["sensor.v1"] == "vpd"
    assert types["sensor.l1"] == "light"
    assert types["sensor.co2"] == "co2"
    assert types["sensor.soil"] == "soil_moisture"
    assert types["switch.exhaust"] == "exhaust"
    assert types["switch.circ"] == "circulation"
    assert types["switch.hum"] == "humidifier"
    assert types["switch.dehum"] == "dehumidifier"
    assert types["switch.pump"] == "irrigation_pump"
    assert types["switch.drain"] == "drain_pump"
    assert types["sensor.tank"] == "irrigation_tank"


def test_get_environment_attributes(hass: HomeAssistant, builder):
    """Test extraction of environment attributes from hass states."""
    env_config = EnvironmentConfig(
        dehumidifier_entities=["humidifier.dehum"],
        exhaust_fan_entities=["fan.exhaust"],
        vpd_sensor="sensor.vpd",
        soil_moisture_sensor="sensor.soil",
        temperature_sensor="sensor.temp",
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank", name="Test Tank", warning_level=20
            )
        ],
        sensor_groups=[SensorGroup(id="g1", name="Group 1", x=1, y=2)],
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
        irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
    )

    # Mock states
    hass.states.async_set(
        "humidifier.dehum",
        "on",
        {"humidity": 50, "current_humidity": 55, "mode": "Normal"},
    )
    hass.states.async_set("fan.exhaust", "on")
    hass.states.async_set("sensor.vpd", "1.2")
    hass.states.async_set("sensor.soil", "45")
    hass.states.async_set("switch.pump", "off")
    hass.states.async_set("sensor.tank", "15")  # Below warning level

    with patch.object(builder.entity_queries, "parse_tank_level", return_value=15.0):
        attrs = builder._get_environment_attributes(growspace)

        assert attrs["dehumidifier_state"] == "on"
        assert attrs["dehumidifier_humidity"] == 50
        assert attrs["exhaust_state"] == "on"
        assert attrs["vpd"] == "1.2"
        assert attrs["soil_moisture_value"] == "45"
        assert attrs["irrigation_pump_state"] == "off"
        assert len(attrs["irrigation_tanks"]) == 1
        assert attrs["irrigation_tanks"][0]["is_warning"] is True
        assert attrs["sensor_groups"][0]["id"] == "g1"


def test_get_environment_attributes_exposes_ac_infinity_devices(
    hass: HomeAssistant, builder
):
    """AC Infinity bundles are serialized into the environment payload (ADR-0022)."""
    env_config = EnvironmentConfig(
        exhaust_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity="select.tent_port1_mode",
                speed_entity="number.tent_port1_on_speed",
                on_speed=8,
            )
        ],
    )
    growspace = Growspace(id="gs1", name="Test", environment_config=env_config)

    attrs = builder._get_environment_attributes(growspace)

    assert attrs["exhaust_fan_ac_infinity_devices"] == [
        {
            "mode_entity": "select.tent_port1_mode",
            "speed_entity": "number.tent_port1_on_speed",
            "on_speed": 8,
        }
    ]
    # Unconfigured roles serialize as empty lists, not omitted
    assert attrs["circulation_fan_ac_infinity_devices"] == []
    assert attrs["humidifier_ac_infinity_devices"] == []
    assert attrs["dehumidifier_ac_infinity_devices"] == []


def test_get_environment_attributes_exposes_growlight(hass: HomeAssistant, builder):
    """Grow light entities + controller config round-trip to the card on reopen.

    Without this the Growlights tab reads back empty and the grow-light chip
    never renders, even though configure_environment persisted the config.
    """
    env_config = EnvironmentConfig(
        growlight_entities=["light.sim_flower_grow_light"],
        growlight_config=GrowLightConfig(enabled=True, power=80),
        growlight_ac_infinity_devices=[
            ACInfinityGrowLight(
                mode_entity="select.tent_light_mode",
                on_time_entity="time.tent_light_on",
                off_time_entity="time.tent_light_off",
                power_entity="number.tent_light_power",
            )
        ],
    )
    growspace = Growspace(id="gs1", name="Test", environment_config=env_config)

    attrs = builder._get_environment_attributes(growspace)

    assert attrs["growlight_entities"] == ["light.sim_flower_grow_light"]
    assert attrs["growlight_config"]["enabled"] is True
    assert attrs["growlight_config"]["power"] == 80
    assert attrs["growlight_ac_infinity_devices"][0]["mode_entity"] == (
        "select.tent_light_mode"
    )


def test_build_special_growspace_types(builder):
    """Test building payload for special growspace IDs."""
    builder.entity_queries = MagicMock()
    builder.plant_builder = MagicMock()

    for gs_id in ("mother", "clone", "dry", "cure"):
        growspace = Growspace(id=gs_id, name=gs_id.capitalize())
        result = builder.build(growspace, [], {})
        assert result["identity"]["type"] == gs_id


def test_air_exchange_recommendation(hass: HomeAssistant, builder):
    """Test air exchange recommendation lookup."""
    hass.data[DOMAIN] = {"air_exchange_recommendations": {"gs1": "High"}}
    growspace = Growspace(id="gs1", name="Test")

    # Use a minimal mock for helpers that are called during build
    with (
        patch.multiple(
            builder,
            _build_rich_plant_grid=MagicMock(return_value={}),
            _get_sensor_types=MagicMock(return_value={}),
            _get_environment_attributes=MagicMock(return_value={}),
        ),
        patch.object(
            builder.entity_queries,
            "lookup_overview_entity_id",
            return_value="sensor.ov",
        ),
    ):
        result = builder.build(growspace, [], {})
        assert result["metrics"]["air_exchange"] == "High"


def test_missing_environment_config(builder):
    """Test functionality when environment_config is missing."""
    growspace = Growspace(id="gs1", name="Test Room", environment_config=None)

    # Line 194: _get_sensor_types
    sensor_types = builder._get_sensor_types(growspace)
    assert sensor_types == {}

    # Line 270: _get_environment_attributes
    attrs = builder._get_environment_attributes(growspace)
    assert attrs == {}

    # Verify build still works
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_overview_entity_id.return_value = "sensor.ov"
    result = builder.build(growspace, [], {})
    assert result["identity"]["growspace_id"] == "gs1"
    assert result["sensors"]["sensor_types"] == {}


def test_get_environment_attributes_malformed_depletion_state(
    hass: HomeAssistant, builder
):
    """Test _get_environment_attributes with non-float depletion sensor state."""
    env_config = EnvironmentConfig(
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank", name="Test Tank", warning_level=20
            )
        ],
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
    )

    # Mock depletion sensor with non-float state
    depletion_sensor_id = "sensor.gs1_tank_depletion_test_tank"
    hass.states.async_set(depletion_sensor_id, "invalid_float")
    hass.states.async_set("sensor.tank", "15")

    with patch.object(builder.entity_queries, "parse_tank_level", return_value=15.0):
        attrs = builder._get_environment_attributes(growspace)
        # hours_remaining should remain None due to ValueError
        assert attrs["irrigation_tanks"][0]["hours_remaining"] is None


def test_get_environment_attributes_depletion_status(hass: HomeAssistant, builder):
    """Test _get_environment_attributes covers depletion status line."""
    env_config = EnvironmentConfig(
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank", name="testtank", warning_level=20
            )
        ],
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
    )

    # Mock depletion sensor with valid float state and status attribute
    # Note: entity IDs are normalized to lowercase by hass.states.async_set
    depletion_sensor_id = "sensor.gs1_tank_depletion_testtank"
    hass.states.async_set(depletion_sensor_id, "10.5", {"status": "discharging"})
    hass.states.async_set("sensor.tank", "15")

    with patch.object(builder.entity_queries, "parse_tank_level", return_value=15.0):
        attrs = builder._get_environment_attributes(growspace)
        tank_data = attrs["irrigation_tanks"][0]
        assert tank_data["hours_remaining"] == 10.5
        assert tank_data["depletion_status"] == "discharging"


def test_get_sensor_types_fallback(builder: GrowspaceViewModelBuilder) -> None:
    """Test sensor type mapping fallback for single sensor entities."""
    config = EnvironmentConfig(
        temperature_sensors=["sensor.temp1"],
        temperature_sensor="sensor.temp2",  # Different from list
        humidity_sensors=["sensor.hum1"],
        humidity_sensor="sensor.hum2",
        vpd_sensors=["sensor.vpd1"],
        vpd_sensor="sensor.vpd2",
        light_sensors=["sensor.light1", "sensor.light2"],
        co2_sensor="sensor.co2",
        soil_moisture_sensor="sensor.soil",
        exhaust_fan_entities=["fan.exhaust"],
        circulation_fan_entities=["fan.circ"],
        humidifier_entities=["humidifier.main"],
        dehumidifier_entities=["dehumidifier.main"],
    )
    gs = Growspace(id="gs1", name="GS1", environment_config=config)
    gs.irrigation_config = IrrigationConfig(
        irrigation_pump_entity="switch.pump",
        drain_pump_entity="switch.drain",
    )
    gs.environment_config.irrigation_tanks = [
        IrrigationTank(name="Tank1", sensor_entity="sensor.tank1")
    ]

    sensor_types = builder._get_sensor_types(gs)

    assert sensor_types["sensor.temp1"] == "temperature"
    assert sensor_types["sensor.temp2"] == "temperature"
    assert sensor_types["sensor.hum1"] == "humidity"
    assert sensor_types["sensor.hum2"] == "humidity"
    assert sensor_types["sensor.vpd1"] == "vpd"
    assert sensor_types["sensor.vpd2"] == "vpd"
    assert sensor_types["sensor.light2"] == "light"
    assert sensor_types["sensor.co2"] == "co2"
    assert sensor_types["sensor.soil"] == "soil_moisture"
    assert sensor_types["fan.exhaust"] == "exhaust"
    assert sensor_types["switch.pump"] == "irrigation_pump"
    assert sensor_types["sensor.tank1"] == "irrigation_tank"


def test_get_environment_attributes_more_entities(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """Test environment attributes with more entities active (humidifier, fans)."""
    config = EnvironmentConfig(
        humidifier_entities=["humidifier.test"],
        circulation_fan_entities=["fan.circ_test"],
    )
    gs = Growspace(id="gs1", name="GS1", environment_config=config)
    gs.irrigation_config = IrrigationConfig(drain_pump_entity="switch.drain_test")

    hass.states.async_set("humidifier.test", "on")
    hass.states.async_set("fan.circ_test", "off")
    hass.states.async_set("switch.drain_test", "on")

    attrs = builder._get_environment_attributes(gs)

    assert attrs["humidifier_state"] == "on"
    assert attrs["circulation_fan_state"] == "off"
    assert attrs["drain_pump_state"] == "on"


def test_build_water_usage_mapping(builder: GrowspaceViewModelBuilder) -> None:
    """Test that build() correctly maps water usage data from the model."""
    usage = WaterUsageData(
        total_liters=250.0,
        cycle_start_date="2024-03-01",
        daily_readings=[{"date": "2024-03-01", "liters": 15.0}],
    )
    gs = Growspace(id="gs1", name="GS1", water_usage=usage)

    # Mock necessary dependencies for build()
    with (
        patch.object(builder, "_build_rich_plant_grid", return_value={}),
        patch.object(builder, "_get_sensor_types", return_value={}),
        patch.object(builder, "_get_environment_attributes", return_value={}),
    ):
        # Now passing required arguments: plants and biological_metrics
        data = builder.build(gs, plants=[], biological_metrics={})

        water_usage = data["irrigation"].get("water_usage")
        assert water_usage is not None
        assert water_usage["total_liters"] == 250.0
        assert water_usage["cycle_start_date"] == "2024-03-01"
        assert len(water_usage["daily_readings"]) == 1


def test_compute_tank_water_summaries_empty() -> None:
    """Empty event list returns empty summaries."""
    result = _compute_tank_water_summaries([])
    assert result["recent_refills"] == []
    assert result["daily_7d"] == []


def test_compute_tank_water_summaries_old_events_excluded() -> None:
    """Events older than 7 days must not appear in the output."""
    old_ts = (datetime.now(tz=UTC) - timedelta(days=8)).isoformat()
    events = [
        {"timestamp": old_ts, "event_type": "consumption", "liters": 5.0},
        {"timestamp": old_ts, "event_type": "refill", "liters": 50.0},
    ]
    result = _compute_tank_water_summaries(events)
    assert result["recent_refills"] == []
    assert result["daily_7d"] == []


def test_compute_tank_water_summaries_recent_events() -> None:
    """Recent events within 7 days must appear in output."""
    now = datetime.now(tz=UTC)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    today_ts = now.isoformat()
    yest_ts = (now - timedelta(days=1)).isoformat()

    events = [
        {"timestamp": yest_ts, "event_type": "consumption", "liters": 3.0},
        {"timestamp": today_ts, "event_type": "consumption", "liters": 2.5},
        {"timestamp": today_ts, "event_type": "refill", "liters": 40.0},
    ]
    result = _compute_tank_water_summaries(events)

    # recent_refills must only contain the refill event
    assert len(result["recent_refills"]) == 1
    assert result["recent_refills"][0]["event_type"] == "refill"

    # daily_7d must aggregate correctly per day
    daily_by_date = {d["date"]: d for d in result["daily_7d"]}
    assert daily_by_date[yesterday]["consumed"] == pytest.approx(3.0)
    assert daily_by_date[yesterday]["refilled"] == pytest.approx(0.0)
    assert daily_by_date[today]["consumed"] == pytest.approx(2.5)
    assert daily_by_date[today]["refilled"] == pytest.approx(40.0)


def test_compute_tank_water_summaries_recent_refills_capped_at_20() -> None:
    """recent_refills must be limited to 20 even when there are many refill events."""
    now = datetime.now(tz=UTC)
    events = [
        {
            "timestamp": (now - timedelta(hours=i)).isoformat(),
            "event_type": "refill",
            "liters": 1.0,
        }
        for i in range(30)  # 30 refills within last 7 days
    ]
    result = _compute_tank_water_summaries(events)
    assert len(result["recent_refills"]) == 20


def test_compute_tank_water_summaries_buckets_24h_not_truncated() -> None:
    """buckets_24h must reflect ALL 24h consumption, not just the last 20 events.

    Regression: the Water Analytics tab bucketed only the raw ``events[-20:]``
    slice sent in attributes, so consumption from earlier in the day vanished
    from the 24h chart while the headline "consumed today" (from ``daily_7d``,
    full data) stayed correct. ``buckets_24h`` is a compact, full-data 15-min
    summary so the chart no longer relies on the truncated raw events.
    """
    now = datetime.now(tz=UTC)
    # 40 consumption events, one every 20 minutes (~13h back), all within 24h.
    events = [
        {
            "timestamp": (now - timedelta(minutes=20 * i)).isoformat(),
            "event_type": "consumption",
            "liters": 1.0,
        }
        for i in range(40)
    ]
    result = _compute_tank_water_summaries(events)
    buckets = result["buckets_24h"]

    # Every event is within the 24h window, so the full 40 L must be present.
    # Truncation to the last 20 events would yield only 20 L.
    total = sum(b["liters"] for b in buckets)
    assert total == pytest.approx(40.0)

    # Earlier history must be present: the oldest bucket must predate the 20
    # most-recent events (i.e. cover more than the last ~6 hours).
    oldest_bucket_start = min(datetime.fromisoformat(b["ts"]) for b in buckets)
    twentieth_event_ts = datetime.fromisoformat(events[19]["timestamp"])
    assert oldest_bucket_start < twentieth_event_ts


def test_compute_tank_water_summaries_buckets_24h_empty() -> None:
    """Empty event list yields an empty buckets_24h list."""
    result = _compute_tank_water_summaries([])
    assert result["buckets_24h"] == []


def test_compute_tank_water_summaries_invalid_event_skipped() -> None:
    """Events with missing or invalid timestamps must be skipped gracefully."""
    good_ts = datetime.now(tz=UTC).isoformat()
    events = [
        {"event_type": "consumption", "liters": 1.0},  # no timestamp
        {"timestamp": "not-a-date", "event_type": "consumption", "liters": 1.0},
        {"timestamp": good_ts, "event_type": "consumption", "liters": 5.0},
    ]
    result = _compute_tank_water_summaries(events)
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    daily_by_date = {d["date"]: d for d in result["daily_7d"]}
    assert daily_by_date[today]["consumed"] == pytest.approx(5.0)


def test_water_usage_liters_today_present_when_passed(
    builder: GrowspaceViewModelBuilder,
) -> None:
    """liters_today appears in water_usage when passed to build()."""
    usage = WaterUsageData(total_liters=100.0, cycle_start_date="2024-01-01")
    gs = Growspace(id="gs1", name="GS1", water_usage=usage)

    with (
        patch.object(builder, "_build_rich_plant_grid", return_value={}),
        patch.object(builder, "_get_sensor_types", return_value={}),
        patch.object(builder, "_get_environment_attributes", return_value={}),
    ):
        data = builder.build(gs, plants=[], biological_metrics={}, liters_today=5.3)

    water_usage = data["irrigation"]["water_usage"]
    assert water_usage is not None
    assert water_usage["liters_today"] == pytest.approx(5.3)


def test_water_usage_liters_today_zero_not_absent(
    builder: GrowspaceViewModelBuilder,
) -> None:
    """liters_today of 0.0 must be included, not treated as absent."""
    usage = WaterUsageData(total_liters=50.0, cycle_start_date="2024-01-01")
    gs = Growspace(id="gs1", name="GS1", water_usage=usage)

    with (
        patch.object(builder, "_build_rich_plant_grid", return_value={}),
        patch.object(builder, "_get_sensor_types", return_value={}),
        patch.object(builder, "_get_environment_attributes", return_value={}),
    ):
        data = builder.build(gs, plants=[], biological_metrics={}, liters_today=0.0)

    water_usage = data["irrigation"]["water_usage"]
    assert "liters_today" in water_usage
    assert water_usage["liters_today"] == pytest.approx(0.0)


def test_water_usage_liters_today_absent_when_not_passed(
    builder: GrowspaceViewModelBuilder,
) -> None:
    """liters_today must be absent from water_usage when not in tank-derived mode."""
    usage = WaterUsageData(total_liters=50.0, cycle_start_date="2024-01-01")
    gs = Growspace(id="gs1", name="GS1", water_usage=usage)

    with (
        patch.object(builder, "_build_rich_plant_grid", return_value={}),
        patch.object(builder, "_get_sensor_types", return_value={}),
        patch.object(builder, "_get_environment_attributes", return_value={}),
    ):
        data = builder.build(gs, plants=[], biological_metrics={})

    water_usage = data["irrigation"]["water_usage"]
    assert "liters_today" not in water_usage


def test_water_history_includes_summaries_in_view_model(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """_get_environment_attributes must include recent_refills and daily_7d in water_history."""
    now = datetime.now(tz=UTC)
    events = [
        {"timestamp": now.isoformat(), "event_type": "consumption", "liters": 2.0},
        {"timestamp": now.isoformat(), "event_type": "refill", "liters": 30.0},
    ]
    tank = IrrigationTank(
        sensor_entity="sensor.tank1", name="Tank 1", volume_liters=100.0
    )
    tank.water_history.events = events

    env_config = EnvironmentConfig(irrigation_tanks=[tank])
    gs = Growspace(id="gs1", name="GS1", environment_config=env_config)

    # Patch hass.states to avoid real sensor lookups
    hass.states.async_set("sensor.tank1", "75")

    attrs = builder._get_environment_attributes(gs)

    tank_data = attrs["irrigation_tanks"][0]
    wh = tank_data["water_history"]

    assert "recent_refills" in wh
    assert "daily_7d" in wh
    assert len(wh["recent_refills"]) == 1
    assert wh["recent_refills"][0]["event_type"] == "refill"
    assert len(wh["daily_7d"]) == 1
    today_entry = wh["daily_7d"][0]
    assert today_entry["consumed"] == pytest.approx(2.0)
    assert today_entry["refilled"] == pytest.approx(30.0)


def _make_mock_coordinator(
    hass: HomeAssistant,
    growspace: Growspace,
    trackers: dict,
) -> MagicMock:
    """Build a minimal mock coordinator for ViewModelBuilder tests."""
    mock_coord = MagicMock()
    mock_coord.hass = hass
    mock_coord.growspaces = {growspace.id: growspace}
    mock_coord.plants = {}
    mock_coord.cache.get.return_value = None
    mock_coord.data = None
    mock_coord.notification_state.sent = {}
    mock_coord.notification_state.enabled = {}
    mock_coord.services.growspaces.get_growspace_plants.return_value = []
    mock_coord.services.growspaces.calculate_biological_metrics.return_value = {}
    mock_coord.services.growspaces.get_irrigation_coordinator.return_value = None
    mock_coord.services.growspaces.get_all_trackers_for_growspace.return_value = (
        trackers
    )
    return mock_coord


def test_view_model_builder_includes_notification_settings(
    hass: HomeAssistant,
) -> None:
    """Serialized payload carries global notification settings for the card.

    The card seeds the Config Dialog's Notifications tab from the device payload,
    so saved settings must ride the per-growspace payload to round-trip.
    """
    gs = Growspace(id="gs1", name="GS1", water_usage=WaterUsageData())
    coordinator = _make_mock_coordinator(hass, gs, {})
    coordinator.config_entry.options = {
        "notification_settings": {"criticalCooldownMinutes": 7},
        "ai_settings": {"ai_auto_alerts": False},
    }

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["notification_settings"] == {"criticalCooldownMinutes": 7}
    assert result["ai_auto_alerts"] is False


def test_view_model_builder_notification_settings_default_when_absent(
    hass: HomeAssistant,
) -> None:
    """Absent options yield an empty dict and ai_auto_alerts defaulting to True."""
    gs = Growspace(id="gs1", name="GS1", water_usage=WaterUsageData())
    coordinator = _make_mock_coordinator(hass, gs, {})
    coordinator.config_entry.options = {}

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["notification_settings"] == {}
    assert result["ai_auto_alerts"] is True


def test_view_model_builder_includes_timed_notifications(
    hass: HomeAssistant,
) -> None:
    """Serialized payload carries timed notifications so the card can round-trip."""
    gs = Growspace(id="gs1", name="GS1", water_usage=WaterUsageData())
    coordinator = _make_mock_coordinator(hass, gs, {})
    timed = [
        {
            "id": "n1",
            "message": "Feed me",
            "trigger_type": "veg_start",
            "day": 3,
            "growspace_ids": ["gs1"],
        }
    ]
    coordinator.config_entry.options = {"timed_notifications": timed}

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["timed_notifications"] == timed


def test_view_model_builder_timed_notifications_default_empty(
    hass: HomeAssistant,
) -> None:
    """Absent timed_notifications option yields an empty list."""
    gs = Growspace(id="gs1", name="GS1", water_usage=WaterUsageData())
    coordinator = _make_mock_coordinator(hass, gs, {})
    coordinator.config_entry.options = {}

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["timed_notifications"] == []


def test_view_model_builder_passes_liters_today_from_trackers(
    hass: HomeAssistant,
) -> None:
    """ViewModelBuilder sums tracker liters_today and passes it to the builder."""
    env = EnvironmentConfig(
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank1", name="Tank 1", volume_liters=100.0
            )
        ],
    )
    gs = Growspace(
        id="gs1", name="GS1", environment_config=env, water_usage=WaterUsageData()
    )

    mock_tracker = MagicMock()
    mock_tracker.get_total_liters_today.return_value = 7.5
    coordinator = _make_mock_coordinator(hass, gs, {"sensor.tank1": mock_tracker})

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    water_usage = result["irrigation"]["water_usage"]
    assert water_usage["liters_today"] == pytest.approx(7.5)


def test_view_model_builder_liters_today_additive_tank_plus_manual(
    hass: HomeAssistant,
) -> None:
    """In tank mode liters_today is tank-derived + manual, via the shared helper."""
    today = dt_util.now().date().isoformat()
    env = EnvironmentConfig(
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank1", name="Tank 1", volume_liters=100.0
            )
        ],
    )
    usage = WaterUsageData()
    usage.daily_readings = [{"date": today, "liters": 2.0, "source": "manual"}]
    gs = Growspace(id="gs1", name="GS1", environment_config=env, water_usage=usage)

    mock_tracker = MagicMock()
    mock_tracker.get_total_liters_today.return_value = 7.5
    coordinator = _make_mock_coordinator(hass, gs, {"sensor.tank1": mock_tracker})

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    water_usage = result["irrigation"]["water_usage"]
    assert water_usage["liters_today"] == pytest.approx(9.5)


def test_view_model_builder_liters_today_measured_with_flow_sensors(
    hass: HomeAssistant,
) -> None:
    """Flow sensors no longer gate liters_today; it reports the measured figure (ADR-0017)."""
    env = EnvironmentConfig(
        irrigation_flow_sensors=["sensor.flow1"],
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank1", name="Tank 1", volume_liters=100.0
            )
        ],
    )
    gs = Growspace(
        id="gs1", name="GS1", environment_config=env, water_usage=WaterUsageData()
    )
    coordinator = _make_mock_coordinator(hass, gs, {})

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    water_usage = result["irrigation"]["water_usage"]
    assert water_usage["liters_today"] == pytest.approx(0.0)


def test_view_model_builder_liters_today_measured_with_drain_volume_sensors(
    hass: HomeAssistant,
) -> None:
    """Drain volume sensors no longer gate liters_today; it reports the measured figure (ADR-0017)."""
    today = dt_util.now().date().isoformat()
    env = EnvironmentConfig(
        drain_volume_sensors=["sensor.drain1"],
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank1", name="Tank 1", volume_liters=100.0
            )
        ],
    )
    usage = WaterUsageData()
    usage.daily_readings = [
        {"date": today, "liters": 3.0, "source": "manual"},
        {"date": today, "liters": 1.5, "source": "pump_estimate"},
    ]
    gs = Growspace(id="gs1", name="GS1", environment_config=env, water_usage=usage)
    coordinator = _make_mock_coordinator(hass, gs, {})

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    water_usage = result["irrigation"]["water_usage"]
    assert water_usage["liters_today"] == pytest.approx(4.5)


def test_vpd_optimal_overrides_round_trips_in_environment_attributes(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """vpd_optimal_overrides must be returned by _get_environment_attributes so the dialog re-opens with saved values."""
    overrides = {
        "flower_mid": {
            "day": {"low": 0.5, "high": 1.45},
            "night": {"low": 0.6, "high": 1.0},
        }
    }
    env_config = EnvironmentConfig(vpd_optimal_overrides=overrides)
    gs = Growspace(id="gs1", name="GS1", environment_config=env_config)

    attrs = builder._get_environment_attributes(gs)

    assert attrs["vpd_optimal_overrides"] == overrides
    assert attrs["vpd_optimal_overrides"]["flower_mid"]["day"]["low"] == 0.5


def test_exhaust_fan_config_round_trips_in_environment_attributes(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """exhaust_fan_config must be returned by _get_environment_attributes so the dialog re-opens with saved values."""
    env_config = EnvironmentConfig(
        exhaust_fan_config=ExhaustFanConfig(enabled=True, max_speed=70)
    )
    gs = Growspace(id="gs1", name="GS1", environment_config=env_config)

    attrs = builder._get_environment_attributes(gs)

    assert attrs["exhaust_fan_config"] == asdict(env_config.exhaust_fan_config)
    assert attrs["exhaust_fan_config"]["enabled"] is True
    assert attrs["exhaust_fan_config"]["max_speed"] == 70


def test_build_includes_subareas(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """The growspace payload carries subareas in the get_subareas wire shape."""
    subarea_env = EnvironmentConfig(
        temperature_sensors=["sensor.shelf_temp"],
        humidity_sensors=["sensor.shelf_hum"],
    )
    growspace = Growspace(
        id="gs1",
        name="Test Room",
        subareas=[Subarea(id="sa1", name="Veg Shelf", environment_config=subarea_env)],
    )

    result = builder.build(growspace=growspace, plants=[], biological_metrics={})

    assert len(result["subareas"]) == 1
    serialized = result["subareas"][0]
    assert serialized["id"] == "sa1"
    assert serialized["name"] == "Veg Shelf"
    assert serialized["environment_config"]["temperature_sensors"] == [
        "sensor.shelf_temp"
    ]
    assert serialized["environment_config"]["humidity_sensors"] == ["sensor.shelf_hum"]


def test_build_subareas_empty_when_none_configured(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """Growspaces without subareas serialize an empty list, not a missing key."""
    growspace = Growspace(id="gs1", name="Test Room")

    result = builder.build(growspace=growspace, plants=[], biological_metrics={})

    assert result["subareas"] == []


def test_view_model_builder_serializes_subareas_for_websocket_payload(
    hass: HomeAssistant,
) -> None:
    """build_serialized_growspace (the get_growspace_data path) carries subareas."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        subareas=[
            Subarea(id="sa1", name="Veg Shelf"),
            Subarea(id="sa2", name="Flower Shelf"),
        ],
    )
    coordinator = _make_mock_coordinator(hass, gs, {})

    result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert [s["id"] for s in result["subareas"]] == ["sa1", "sa2"]
    assert all("environment_config" in s for s in result["subareas"])


def test_substrate_payload_surfaces_measured_steering_readout(
    hass: HomeAssistant,
) -> None:
    """The substrate block carries the measured steering readout.

    Score, Measured Classification, and Intent Deviation come from the computed
    CropSteeringState.
    """
    from custom_components.growspace_manager.models.irrigation import CropSteeringState

    gs = Growspace(id="gs1", name="GS1")
    coordinator = _make_mock_coordinator(hass, gs, {})

    state = CropSteeringState(
        score=0.6,
        measured_classification="generative",
        intent_deviation="more_generative",
    )
    with patch(
        "custom_components.growspace_manager.view_model_builder.get_crop_steering_state",
        return_value=state,
    ):
        result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    substrate = result["irrigation"]["substrate"]
    assert substrate["score"] == pytest.approx(0.6)
    assert substrate["measured_classification"] == "generative"
    assert substrate["intent_deviation"] == "more_generative"


def test_substrate_payload_steering_readout_null_when_no_state(
    hass: HomeAssistant,
) -> None:
    """Measured readout fields are present but null when no state is available.

    This is the strategy-disabled / no-reading-yet case.
    """
    gs = Growspace(id="gs1", name="GS1")
    coordinator = _make_mock_coordinator(hass, gs, {})

    with patch(
        "custom_components.growspace_manager.view_model_builder.get_crop_steering_state",
        return_value=None,
    ):
        result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    substrate = result["irrigation"]["substrate"]
    assert substrate["score"] is None
    assert substrate["measured_classification"] is None
    assert substrate["intent_deviation"] is None


def test_substrate_payload_includes_shot_composition(hass: HomeAssistant) -> None:
    """The substrate block carries the irrigation coordinator's shot composition."""
    gs = Growspace(id="gs1", name="GS1")
    coordinator = _make_mock_coordinator(hass, gs, {})

    irr_coord = MagicMock()
    irr_coord.active_events = {}
    irr_coord.last_cycle_timestamp = None
    irr_coord.next_scheduled_cycle = None
    irr_coord.projected_shot_window = None
    irr_coord.cycles_today = 0
    irr_coord.volume_dispensed_today = 0.0
    composition = {"ec_modulation_enabled": True, "last_shot": None}
    irr_coord.shot_composition_payload.return_value = composition
    coordinator.services.growspaces.get_irrigation_coordinator.return_value = irr_coord

    with patch(
        "custom_components.growspace_manager.view_model_builder.get_crop_steering_state",
        return_value=None,
    ):
        result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["irrigation"]["substrate"]["shot_composition"] == composition


def test_substrate_payload_shot_composition_null_without_irrigation_coordinator(
    hass: HomeAssistant,
) -> None:
    """Time-based irrigation (no VWC coordinator) leaves shot_composition null."""
    gs = Growspace(id="gs1", name="GS1")
    coordinator = _make_mock_coordinator(hass, gs, {})

    with patch(
        "custom_components.growspace_manager.view_model_builder.get_crop_steering_state",
        return_value=None,
    ):
        result = ViewModelBuilder(coordinator).build_serialized_growspace("gs1")

    assert result["irrigation"]["substrate"]["shot_composition"] is None


def test_get_environment_attributes_includes_lst_offset(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """Test that _get_environment_attributes includes lst_offset from config."""
    env_config = EnvironmentConfig(lst_offset=-3.5)
    growspace = Growspace(id="gs1", name="Test", environment_config=env_config)

    attrs = builder._get_environment_attributes(growspace)

    assert attrs["lst_offset"] == -3.5


def test_get_environment_attributes_includes_default_lst_offset(
    hass: HomeAssistant, builder: GrowspaceViewModelBuilder
) -> None:
    """Test that _get_environment_attributes includes default lst_offset."""
    env_config = EnvironmentConfig()
    growspace = Growspace(id="gs1", name="Test", environment_config=env_config)

    attrs = builder._get_environment_attributes(growspace)

    assert attrs["lst_offset"] == -2.0
