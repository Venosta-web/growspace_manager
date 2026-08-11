"""Golden contract fixture for the growspace ``get_data`` payload."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.const import (
    DOMAIN,
    FanRegulationMode,
    PlantStage,
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    ACInfinityDevice,
    ACInfinityGrowLight,
    CirculationFanConfig,
    DrainConfig,
    DrainReading,
    DryingData,
    ECTargetRange,
    EnergyTracking,
    EnvironmentConfig,
    ExhaustFanConfig,
    GrowLightConfig,
    Growspace,
    GrowspaceType,
    HarvestMetrics,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
    MoistureEntry,
    PhenotypeScore,
    Plant,
    PlantGenetics,
    SensorGroup,
    Subarea,
    SubstrateHistory,
    SubstrateProfile,
    TankWaterHistory,
    VisionCheckupConfig,
    VisionCheckupResult,
    WaterUsageData,
    WeightEntry,
)
from custom_components.growspace_manager.websocket import websocket_get_growspace_data
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "contract" / "growspace_payload.json"
)
REGENERATION_COMMAND = (
    "../../.venv/bin/pytest tests/contract/test_growspace_payload_contract.py "
    "--regenerate-contract-fixture"
)
GROWSPACE_ID = "contract_growspace"


def _maximal_environment_config(prefix: str) -> EnvironmentConfig:
    """Return an environment config with every optional field populated."""
    temperature = f"sensor.{prefix}_temperature"
    humidity = f"sensor.{prefix}_humidity"
    vpd = f"sensor.{prefix}_vpd"
    light = f"sensor.{prefix}_light"
    tank = f"sensor.{prefix}_tank"
    return EnvironmentConfig(
        temperature_sensor=temperature,
        humidity_sensor=humidity,
        vpd_sensor=vpd,
        co2_sensor=f"sensor.{prefix}_co2",
        soil_moisture_sensor=f"sensor.{prefix}_soil_moisture",
        veg_day_hours=18,
        flower_day_hours=12,
        temperature_sensors=[temperature, f"sensor.{prefix}_temperature_2"],
        humidity_sensors=[humidity, f"sensor.{prefix}_humidity_2"],
        vpd_sensors=[vpd, f"sensor.{prefix}_vpd_2"],
        light_sensors=[light],
        exhaust_fan_entities=[f"fan.{prefix}_exhaust"],
        circulation_fan_entities=[f"fan.{prefix}_circulation"],
        humidifier_entities=[f"humidifier.{prefix}"],
        dehumidifier_entities=[f"humidifier.{prefix}_dehumidifier"],
        growlight_entities=[f"light.{prefix}_growlight"],
        exhaust_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity=f"select.{prefix}_exhaust_mode",
                speed_entity=f"number.{prefix}_exhaust_speed",
                on_speed=8,
            )
        ],
        circulation_fan_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity=f"select.{prefix}_circulation_mode",
                speed_entity=f"number.{prefix}_circulation_speed",
                on_speed=7,
            )
        ],
        humidifier_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity=f"select.{prefix}_humidifier_mode",
                speed_entity=f"number.{prefix}_humidifier_speed",
                on_speed=6,
            )
        ],
        dehumidifier_ac_infinity_devices=[
            ACInfinityDevice(
                mode_entity=f"select.{prefix}_dehumidifier_mode",
                speed_entity=f"number.{prefix}_dehumidifier_speed",
                on_speed=5,
            )
        ],
        growlight_ac_infinity_devices=[
            ACInfinityGrowLight(
                mode_entity=f"select.{prefix}_growlight_mode",
                on_time_entity=f"time.{prefix}_growlight_on",
                off_time_entity=f"time.{prefix}_growlight_off",
                power_entity=f"number.{prefix}_growlight_power",
                sunrise_switch_entity=f"switch.{prefix}_growlight_sunrise",
                sunrise_duration_entity=(f"number.{prefix}_growlight_sunrise_duration"),
            )
        ],
        sensor_coordinates={
            temperature: {"x": 0.25, "y": 0.5, "z": 1.25},
            humidity: {"x": 0.75, "y": 0.5, "z": 1.0},
        },
        sensor_groups=[
            SensorGroup(
                id=f"{prefix}-canopy",
                name="Canopy",
                x=0.5,
                y=0.5,
                z=1.2,
                temperature_sensors=[temperature],
                humidity_sensors=[humidity],
                vpd_sensors=[vpd],
            )
        ],
        substrate_temperature_sensors=[f"sensor.{prefix}_substrate_temperature"],
        camera_entities=[f"camera.{prefix}"],
        lung_room_temp_sensors=[f"sensor.{prefix}_lung_temperature"],
        snapshot_interval_hours=6,
        ph_sensors=[f"sensor.{prefix}_ph"],
        feed_ec_sensors=[f"sensor.{prefix}_feed_ec"],
        bulk_ec_sensors=[f"sensor.{prefix}_bulk_ec"],
        pore_ec_sensors=[f"sensor.{prefix}_pore_ec"],
        runoff_ec_sensors=[f"sensor.{prefix}_runoff_ec"],
        drain_volume_sensors=[f"sensor.{prefix}_drain_volume"],
        irrigation_flow_sensors=[f"sensor.{prefix}_irrigation_flow"],
        power_sensors=[f"sensor.{prefix}_power"],
        energy_sensors=[f"sensor.{prefix}_energy"],
        electricity_cost_per_kwh=0.32,
        dli_target_veg=32.0,
        dli_target_flower=44.0,
        lst_offset=-2.5,
        control_dehumidifier=True,
        dehumidifier_thresholds={"flower": {"target": 52.0, "tolerance": 3.0}},
        control_humidifier=True,
        humidifier_thresholds={"veg": {"target": 68.0, "tolerance": 4.0}},
        minimum_source_air_temperature=17.5,
        stress_threshold=0.65,
        mold_threshold=0.8,
        bayesian_options={"min_probability": 0.75, "observations": 4},
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity=tank,
                name="nutrient_tank",
                warning_level=25.0,
                enable_prediction=True,
                enable_lights_bias=True,
                enable_vpd_weighting=True,
                volume_liters=120.0,
                last_recorded_level=72.0,
                peak_level=95.0,
                water_history=TankWaterHistory(
                    snapshots=[
                        {
                            "timestamp": "2026-08-11T08:00:00+00:00",
                            "level_pct": 75.0,
                        }
                    ],
                    events=[
                        {
                            "timestamp": "2026-08-11T09:00:00+00:00",
                            "liters": 4.5,
                            "pct_delta": -3.75,
                            "event_type": "consumption",
                        },
                        {
                            "timestamp": "2026-08-10T18:00:00+00:00",
                            "liters": 30.0,
                            "pct_delta": 25.0,
                            "event_type": "refill",
                        },
                    ],
                ),
            )
        ],
        vision_checkup_config=VisionCheckupConfig(
            enabled=True,
            early_check_offset_minutes=45,
            mid_check_hours=5,
            late_check_offset_minutes=30,
            history_limit=20,
        ),
        circulation_fan_config=CirculationFanConfig(
            enabled=True,
            regulation_mode=FanRegulationMode.HUMIDITY,
            min_speed=20,
            max_speed=90,
            humidity_target=62.0,
            humidity_tolerance=4.0,
            temperature_target=25.5,
            temperature_tolerance=1.5,
            vpd_target=1.15,
            vpd_tolerance=0.15,
            critical_temp_low=17.0,
            critical_temp_high=33.0,
            critical_temp_hysteresis=1.5,
            wind_enabled=True,
            wind_period_seconds=90,
            wind_amplitude_pct=15,
            stage_vpd_enabled=True,
            stage_vpd_overrides={"flower": {"target": 1.3, "tolerance": 0.1}},
        ),
        exhaust_fan_config=ExhaustFanConfig(
            enabled=True,
            min_speed=15,
            max_speed=85,
            temperature_target=26.0,
            temperature_tolerance=2.5,
            humidity_target=58.0,
            humidity_tolerance=5.0,
            vpd_target=1.2,
            vpd_tolerance=0.2,
            stage_vpd_enabled=True,
            stage_vpd_overrides={"veg": {"target": 1.0, "tolerance": 0.15}},
            critical_temp_low=16.0,
            critical_temp_high=34.0,
            critical_temp_hysteresis=2.0,
        ),
        growlight_config=GrowLightConfig(
            enabled=True,
            power=80,
            sunrise_enabled=True,
            sunrise_minutes=30,
        ),
        vpd_optimal_overrides={
            "flower": {
                "day": {"low": 1.1, "high": 1.5},
                "night": {"low": 0.8, "high": 1.2},
            }
        },
    )


def _maximal_growspace() -> Growspace:
    """Return a growspace with every optional nested configuration populated."""
    return Growspace(
        id=GROWSPACE_ID,
        name="Contract Growspace",
        dimensions={"width": 240.0, "depth": 120.0, "height": 220.0, "unit": "cm"},
        rows=2,
        plants_per_row=2,
        notification_target="notify.mobile_app_grower",
        created_at="2026-01-01T00:00:00+00:00",
        device_id="contract-growspace-device",
        environment_config=_maximal_environment_config("contract"),
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity="switch.contract_irrigation_pump",
            drain_pump_entity="switch.contract_drain_pump",
            irrigation_duration=45,
            drain_duration=30,
            irrigation_times=[{"time": "06:30", "duration": 45}],
            drain_times=[{"time": "07:00", "duration": 30}],
            veg_day_hours=18,
            pump_flow_rate_ml_per_sec=25.0,
            soil_trigger_percent=42.0,
            daily_volume_cap_liters=18.0,
            max_cycles_per_day=12,
            skip_during_dark=True,
            pause_on_low_tank=True,
            log_to_logbook=True,
            ec_target_ranges=[
                ECTargetRange(stage="flower", feed_ec_min=1.8, feed_ec_max=2.2)
            ],
            auto_advance_p1_to_p2=True,
            auto_advance_p2_to_p3=True,
            halt_on_runoff_ec_threshold=2.8,
            active_steering_phase="p2",
            phase_changed_at="2026-08-11T06:00:00+00:00",
        ),
        dehumidifier_config={"mode": "vpd", "minimum_runtime_minutes": 5},
        humidifier_config={"mode": "humidity", "minimum_runtime_minutes": 3},
        irrigation_strategy=IrrigationStrategy(
            enabled=True,
            lights_on_time="06:00:00",
            p0_duration_minutes=90,
            p2_stop_before_lights_off_minutes=75,
            target_vwc_percent=58.0,
            maintenance_dryback_percent=3.5,
            p1_shot_duration_seconds=12,
            p1_shot_interval_minutes=20,
            p2_shot_duration_seconds=9,
            p2_shot_interval_minutes=30,
            auto_light_tracking=True,
            detected_lights_on_time="05:58:00",
            shot_sizing_mode=ShotSizingMode.VOLUME,
            substrate_profile=SubstrateProfile(
                media_type=SubstrateMediaType.ROCKWOOL,
                liters_per_pot=7.5,
            ),
            p1_shot_volume_percent=4.5,
            p2_shot_volume_percent=3.0,
            dynamic_shot_enabled=True,
            dynamic_aggressiveness=1.2,
            dynamic_recovery=0.15,
            dynamic_shot_size_floor=0.6,
            dynamic_interval_ceiling=1.8,
            pore_ec_target_min=2.1,
            pore_ec_target_max=2.8,
            ec_modulation_enabled=True,
            declared_steering_mode=SteeringMode.GENERATIVE,
        ),
        growspace_type=GrowspaceType.FLOWER,
        drain_config=DrainConfig(
            enabled=True,
            max_ec_delta=0.6,
            target_runoff_percent=18.0,
            readings=[
                DrainReading(
                    timestamp="2026-08-11T10:00:00+00:00",
                    feed_ec=2.0,
                    drain_ec=2.4,
                    drain_volume_ml=450.0,
                    feed_volume_ml=2500.0,
                )
            ],
            max_readings=150,
        ),
        energy_tracking=EnergyTracking(
            cycle_start_kwh=1024.5,
            cycle_start_date="2026-08-01",
            last_kwh_reading=1108.75,
        ),
        water_usage=WaterUsageData(
            total_liters=88.5,
            cycle_start_date="2026-08-01",
            daily_readings=[{"date": "2026-08-11", "liters": 6.25, "source": "manual"}],
            max_daily_readings=400,
        ),
        vision_checkup_history=[
            VisionCheckupResult(
                timestamp="2026-08-11T07:00:00+00:00",
                growspace_id=GROWSPACE_ID,
                check_type="early",
                snapshot_paths=["vision/contract-early.jpg"],
                analysis="Healthy canopy with even growth.",
                issues_detected=["minor_leaf_curl"],
                severity="low",
                recommendations=["Monitor source-air temperature."],
            )
        ],
        subareas=[
            Subarea(
                id="contract-subarea",
                name="Propagation Shelf",
                environment_config=_maximal_environment_config("subarea"),
            )
        ],
        substrate_history=SubstrateHistory(
            events=[
                {
                    "event_type": "overnight",
                    "peak_timestamp": "2026-08-10T18:00:00+00:00",
                    "trough_timestamp": "2026-08-11T05:55:00+00:00",
                    "peak_vwc": 61.0,
                    "trough_vwc": 52.0,
                    "dryback": 9.0,
                },
                {
                    "event_type": "in_cycle",
                    "peak_timestamp": "2026-08-11T08:00:00+00:00",
                    "trough_timestamp": "2026-08-11T09:00:00+00:00",
                    "peak_vwc": 59.0,
                    "trough_vwc": 55.0,
                    "dryback": 4.0,
                },
            ],
            pending_overnight_peak=60.0,
            pending_overnight_peak_ts="2026-08-11T10:00:00+00:00",
            pending_overnight_trough=56.0,
            pending_overnight_trough_ts="2026-08-11T11:00:00+00:00",
            pending_incycle_peak=59.0,
            pending_incycle_peak_ts="2026-08-11T10:00:00+00:00",
            pending_incycle_trough=56.0,
            pending_incycle_trough_ts="2026-08-11T11:00:00+00:00",
            lit_period_max=61.0,
            lit_period_max_ts="2026-08-11T09:30:00+00:00",
            current_day="2026-08-11",
            shots_today=4,
            ec_trend_day="2026-08-11",
            ec_day_start_value=2.2,
            ec_day_start_ts="2026-08-11T06:00:00+00:00",
            ec_latest_value=2.5,
            ec_latest_ts="2026-08-11T11:00:00+00:00",
        ),
    )


def _maximal_plant() -> Plant:
    """Return a plant that exercises all optional plant wire fields."""
    return Plant(
        plant_id="contract-plant",
        growspace_id=GROWSPACE_ID,
        genetics=PlantGenetics(
            strain_id=101,
            phenotype_id=202,
            strain_name="Contract Cultivar",
            phenotype_name="Keeper A",
            generation="F2",
        ),
        row=1,
        col=1,
        stage=PlantStage.CURE,
        type="seed",
        device_id="contract-plant-device",
        seedling_start="2026-01-01T00:00:00+00:00",
        mother_start="2026-01-08T00:00:00+00:00",
        clone_start="2026-01-15T00:00:00+00:00",
        veg_start="2026-02-01T00:00:00+00:00",
        flower_start="2026-04-01T00:00:00+00:00",
        dry_start="2026-07-20T00:00:00+00:00",
        cure_start="2026-08-01T00:00:00+00:00",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-08-11T11:00:00+00:00",
        transition_date="2026-08-01T00:00:00+00:00",
        source_mother="mother-contract",
        seed_batch_id="batch-contract",
        sex="female",
        last_watered="2026-08-10T09:00:00+00:00",
        last_trained="2026-03-15T09:00:00+00:00",
        last_training_technique="low_stress_training",
        last_ipm="2026-07-01T09:00:00+00:00",
        last_ipm_type="beneficial_insects",
        phi_clearance_date="2026-08-15",
        stage_history=[
            {
                "stage": "veg",
                "start": "2026-02-01T00:00:00+00:00",
                "end": "2026-04-01T00:00:00+00:00",
            },
            {
                "stage": "flower",
                "start": "2026-04-01T00:00:00+00:00",
                "end": "2026-07-20T00:00:00+00:00",
            },
        ],
        phenotype_score=PhenotypeScore(
            vigor=9,
            internodal_spacing=8,
            terpene_intensity=10,
            resin=9,
            mold_resistance=8,
            yield_potential=9,
            keeper=True,
            notes="Contract phenotype notes",
            updated_at="2026-08-01T12:00:00+00:00",
        ),
        harvest_metrics=HarvestMetrics(
            wet_weight=850.0,
            dry_weight=210.0,
            trim_weight=45.0,
            thc_percentage=24.5,
            cbd_percentage=0.8,
            terpene_profile="citrus, pine",
        ),
        drying_data=DryingData(
            weight_log=[
                WeightEntry(date="2026-07-20", weight_grams=850.0),
                WeightEntry(date="2026-07-25", weight_grams=260.0),
            ],
            moisture_log=[
                MoistureEntry(date="2026-07-24", moisture_percent=14.0),
                MoistureEntry(date="2026-07-25", moisture_percent=11.5),
            ],
            visual_tag="stems_snap",
        ),
    )


def _set_runtime_states(hass: HomeAssistant) -> None:
    """Populate live entity states read by the presentation layer."""
    states = {
        "sensor.contract_temperature": "25.4",
        "sensor.contract_temperature_2": "25.8",
        "sensor.contract_humidity": "58.0",
        "sensor.contract_humidity_2": "60.0",
        "sensor.contract_vpd": "1.25",
        "sensor.contract_vpd_2": "1.35",
        "sensor.contract_light": "on",
        "sensor.contract_soil_moisture": "56.0",
        "sensor.contract_bulk_ec": "2.1",
        "sensor.contract_pore_ec": "2.5",
        "sensor.contract_tank": "72.0",
        "sensor.contract_growspace_tank_depletion_nutrient_tank": "36.5",
        "fan.contract_exhaust": "on",
        "fan.contract_circulation": "on",
        "humidifier.contract": "on",
        "humidifier.contract_dehumidifier": "off",
        "switch.contract_irrigation_pump": "off",
        "switch.contract_drain_pump": "off",
    }
    for entity_id, state in states.items():
        attributes = (
            {"humidity": 52, "current_humidity": 58, "mode": "auto"}
            if entity_id == "humidifier.contract_dehumidifier"
            else {"status": "normal"}
            if "tank_depletion" in entity_id
            else None
        )
        hass.states.async_set(entity_id, state, attributes)


async def _build_contract_payload(hass: HomeAssistant) -> dict[str, object]:
    """Build the fixture payload through the real ``get_data`` path."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "notification_settings": {
                "criticalCooldownMinutes": 8,
                "warningCooldownMinutes": 45,
                "recoveryCooldownMinutes": 12,
                "escalationDelayMinutes": 20,
                "minStressDurationSeconds": 180,
                "warningPersistenceMinutes": 15,
            },
            "ai_settings": {"ai_auto_alerts": False},
            "timed_notifications": [
                {
                    "id": "contract-notification",
                    "message": "Inspect irrigation runoff",
                    "trigger_type": "flower_start",
                    "day": 14,
                    "growspace_ids": [GROWSPACE_ID],
                }
            ],
        },
    )
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator._data_repository.add_growspace(_maximal_growspace())
    coordinator._data_repository.add_plant(_maximal_plant())
    _set_runtime_states(hass)

    frozen_now = datetime(2026, 8, 11, 12, tzinfo=UTC)
    with (
        patch("homeassistant.util.dt.now", return_value=frozen_now),
        patch("homeassistant.util.dt.utcnow", return_value=frozen_now),
    ):
        payload = await websocket_get_growspace_data(
            hass,
            coordinator,
            {
                "id": 1,
                "type": f"{DOMAIN}/get_data",
                "growspace_id": GROWSPACE_ID,
            },
        )
    assert isinstance(payload, dict)
    return payload


@freeze_time("2026-08-11 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_growspace_payload_contract(
    hass: HomeAssistant, pytestconfig: pytest.Config
) -> None:
    """Keep the real ``get_data`` payload in sync with the golden fixture."""
    payload = json.loads(json.dumps(await _build_contract_payload(hass)))

    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            f"{json.dumps(payload, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )

    assert FIXTURE_PATH.exists(), (
        "Growspace contract fixture is missing. Regenerate it with: "
        f"{REGENERATION_COMMAND}"
    )
    assert payload == json.loads(FIXTURE_PATH.read_text(encoding="utf-8")), (
        "Growspace payload changed. Review the contract diff, then regenerate with: "
        f"{REGENERATION_COMMAND}"
    )
