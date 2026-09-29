"""Write the golden pre-zones ``.storage`` documents with v1.2.3's own models.

The documents beside this file are what v1.2.3 persisted, not what today's
code thinks it persisted: they were produced by running this script from a
checkout of the ``v1.2.3`` tag, so every key, default and nesting is that
release's. Re-running it anywhere else would produce today's shape and defeat
the point, so it refuses unless the models still have the pre-zones fields.

    git worktree add --detach /tmp/gsm-v123 v1.2.3
    cd /tmp/gsm-v123
    <a venv with this repo's requirements>/bin/python \
        <this repo>/tests/fixtures/upgrade/write_v1_2_3_storage.py <this directory>

Everything in it is anonymised: invented ids, names and entity ids.
"""

from __future__ import annotations

from dataclasses import asdict, fields
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

from custom_components.growspace_manager.const import (
    STORAGE_KEY_CONFIG,
    STORAGE_KEY_PLANTS,
    STORAGE_VERSION,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
    Plant,
    Subarea,
    SubstrateHistory,
    SubstrateProfile,
)

if "irrigation_strategy" not in {f.name for f in fields(Growspace)}:
    raise SystemExit("Run this from a v1.2.3 checkout, not a zoned one.")

CREATED = "2026-06-01T08:00:00+00:00"

steered = Growspace(
    id="tent_steered",
    name="Tent Steered",
    rows=2,
    plants_per_row=3,
    created_at=CREATED,
    environment_config=EnvironmentConfig(
        temperature_sensor="sensor.tent_steered_temperature",
        humidity_sensor="sensor.tent_steered_humidity",
        soil_moisture_sensor="sensor.tent_steered_substrate_moisture",
        pore_ec_sensors=["sensor.tent_steered_pore_ec"],
        bulk_ec_sensors=["sensor.tent_steered_bulk_ec"],
        substrate_temperature_sensors=["sensor.tent_steered_substrate_temperature"],
        feed_ec_sensors=["sensor.reservoir_feed_ec"],
        light_sensors=["binary_sensor.tent_steered_lights"],
        flower_day_hours=12,
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.reservoir_level",
                name="Reservoir",
                volume_liters=60.0,
                last_recorded_level=72.5,
                peak_level=95.0,
            )
        ],
    ),
    irrigation_config=IrrigationConfig(
        irrigation_pump_entity="switch.tent_steered_pump",
        drain_pump_entity="switch.tent_steered_drain",
        irrigation_duration=45,
        drain_duration=120,
        irrigation_times=[{"time": "09:00:00", "duration": 45}],
        drain_times=[{"time": "21:00:00", "duration": 120}],
        pump_flow_rate_ml_per_sec=12.5,
        soil_trigger_percent=38.0,
        daily_volume_cap_liters=18.0,
        max_cycles_per_day=40,
        skip_during_dark=True,
        auto_advance_p1_to_p2=True,
        active_steering_phase="p2",
        phase_changed_at="2026-09-20T10:15:00+00:00",
    ),
    irrigation_strategy=IrrigationStrategy(
        enabled=True,
        lights_on_time="06:30:00",
        p0_duration_minutes=45,
        p2_stop_before_lights_off_minutes=150,
        target_vwc_percent=52.0,
        maintenance_dryback_percent=3.0,
        p1_shot_duration_seconds=30,
        p1_shot_interval_minutes=15,
        p2_shot_duration_seconds=20,
        p2_shot_interval_minutes=30,
        auto_light_tracking=True,
        detected_lights_on_time="06:32:00",
        substrate_profile=SubstrateProfile(liters_per_pot=11.0),
        pore_ec_target_min=3.0,
        pore_ec_target_max=5.5,
        ec_modulation_enabled=True,
    ),
    substrate_history=SubstrateHistory(
        events=[
            {
                "event_type": "overnight",
                "peak_timestamp": "2026-09-19T17:40:00+00:00",
                "trough_timestamp": "2026-09-20T06:50:00+00:00",
                "peak_vwc": 55.0,
                "trough_vwc": 47.5,
                "dryback": 7.5,
            }
        ],
        pending_incycle_peak=53.1,
        pending_incycle_peak_ts="2026-09-20T12:05:00+00:00",
        current_day="2026-09-20",
        shots_today=6,
    ),
    subareas=[
        Subarea(
            id="canopy_left",
            name="Canopy left",
            environment_config=EnvironmentConfig(
                temperature_sensor="sensor.tent_steered_left_temperature"
            ),
        )
    ],
)

scheduled = Growspace(
    id="tent_scheduled",
    name="Tent Scheduled",
    rows=3,
    plants_per_row=2,
    created_at=CREATED,
    environment_config=EnvironmentConfig(
        temperature_sensor="sensor.tent_scheduled_temperature",
        veg_day_hours=18,
        irrigation_tanks=[
            IrrigationTank(sensor_entity="sensor.veg_tank_level", name="Veg tank")
        ],
    ),
    irrigation_config=IrrigationConfig(
        irrigation_pump_entity="switch.tent_scheduled_pump",
        irrigation_duration=60,
        irrigation_times=[
            {"time": "08:00:00", "duration": 60},
            {"time": "14:00:00", "duration": 60},
        ],
        pump_flow_rate_ml_per_sec=8.0,
        daily_volume_cap_liters=None,
        max_cycles_per_day=None,
    ),
)

plants = [
    Plant(
        plant_id="plant_a1",
        growspace_id="tent_steered",
        row=1,
        col=1,
        stage="flower",
        veg_start="2026-07-20",
        flower_start="2026-08-24",
        created_at=CREATED,
    ),
    Plant(
        plant_id="plant_a2",
        growspace_id="tent_steered",
        row=1,
        col=2,
        stage="flower",
        veg_start="2026-07-20",
        flower_start="2026-08-24",
        created_at=CREATED,
    ),
    Plant(
        plant_id="plant_b1",
        growspace_id="tent_scheduled",
        row=2,
        col=1,
        stage="veg",
        veg_start="2026-09-01",
        created_at=CREATED,
    ),
]


def _envelope(key: str, data: dict) -> dict:
    return {"version": STORAGE_VERSION, "minor_version": 1, "key": key, "data": data}


out = Path(sys.argv[1])
config = _envelope(
    STORAGE_KEY_CONFIG,
    {
        "growspaces": {gs.id: asdict(gs) for gs in (steered, scheduled)},
        "notifications_sent": {},
        "notifications_enabled": {"tent_steered": True, "tent_scheduled": True},
    },
)
plant_doc = _envelope(
    STORAGE_KEY_PLANTS,
    {"plants": {p.plant_id: asdict(p) for p in plants}, "quarantined_plants": {}},
)
for key, doc in ((STORAGE_KEY_CONFIG, config), (STORAGE_KEY_PLANTS, plant_doc)):
    (out / key).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
