"""Irrigation Zone ownership, the v1→v2 migration and its integrity check.

Pure tests of ``domain/irrigation_zone.py`` (ADR-0057, ADR-0063): no Home
Assistant, no store. The store and the golden upgrade live in
``tests/core/test_config_store_migration.py`` and
``tests/integration/test_zone_upgrade.py``.
"""

from __future__ import annotations

import copy
from dataclasses import fields
from typing import Any

import pytest

from custom_components.growspace_manager.domain.irrigation_zone import (
    LIGHT_CYCLE_FIELDS,
    ZONE_CONFIG_FIELDS,
    ZONE_ENVIRONMENT_FIELDS,
    apply_effective_irrigation,
    effective_config,
    effective_environment_probes,
    effective_strategy,
    migrate_growspace_document,
    sync_implicit_zone_cells,
    zone_integrity_problems,
    zone_of,
)
from custom_components.growspace_manager.models import (
    IMPLICIT_ZONE_ID,
    Growspace,
    GrowspaceIrrigationConfig,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationZone,
    LightCycle,
    SteeringStrategy,
    grid_cells,
)


def _v1_growspace(**overrides: Any) -> dict[str, Any]:
    """Return a pre-zones growspace document with every moved field set."""
    document: dict[str, Any] = {
        "id": "tent",
        "name": "Tent",
        "rows": 2,
        "plants_per_row": 2,
        "environment_config": {
            "temperature_sensors": ["sensor.t"],
            "soil_moisture_sensor": "sensor.vwc",
            "pore_ec_sensors": ["sensor.pore"],
            "bulk_ec_sensors": ["sensor.bulk"],
            "substrate_temperature_sensors": ["sensor.substrate_t"],
        },
        "irrigation_config": {
            "irrigation_pump_entity": "switch.pump",
            "drain_times": [{"time": "20:00:00", "duration": 30}],
            "irrigation_duration": 45,
            "irrigation_times": [{"time": "09:00:00", "duration": 45}],
            "pump_flow_rate_ml_per_sec": 12.5,
            "soil_trigger_percent": 38.0,
            "min_interval_minutes": 7,
            "daily_volume_cap_liters": 10.0,
            "max_cycles_per_day": 12,
            "active_steering_phase": "p1",
            "phase_changed_at": "2026-09-20T10:15:00+00:00",
        },
        "irrigation_strategy": {
            "enabled": True,
            "lights_on_time": "06:30:00",
            "auto_light_tracking": True,
            "detected_lights_on_time": "06:32:00",
            "target_vwc_percent": 52.0,
            "p1_shot_duration_seconds": 30,
        },
        "substrate_history": {"shots_today": 4, "current_day": "2026-09-20"},
        "subareas": [
            {
                "id": "left",
                "name": "Left",
                "environment_config": {
                    "temperature_sensors": ["sensor.left_t"],
                    "soil_moisture_sensor": "sensor.left_vwc",
                    "substrate_ec_sensor": "sensor.left_ec",
                    "substrate_temperature_sensors": ["sensor.left_root"],
                },
            }
        ],
    }
    document.update(overrides)
    return document


def test_ownership_is_read_off_the_models() -> None:
    """The zone's config half is exactly what the growspace no longer has."""
    growspace_fields = {f.name for f in fields(GrowspaceIrrigationConfig)}
    assert set(ZONE_CONFIG_FIELDS) == (
        {f.name for f in fields(IrrigationConfig)} - growspace_fields
    )
    assert set(ZONE_CONFIG_FIELDS) == {
        "pump_flow_rate_ml_per_sec",
        "irrigation_times",
        "irrigation_duration",
        "soil_trigger_percent",
        "min_interval_minutes",
        "active_steering_phase",
        "phase_changed_at",
    }
    assert set(LIGHT_CYCLE_FIELDS) == {
        "lights_on_time",
        "auto_light_tracking",
        "detected_lights_on_time",
    }
    assert not set(LIGHT_CYCLE_FIELDS) & {f.name for f in fields(SteeringStrategy)}


def test_migration_moves_every_zone_owned_field_into_the_implicit_zone() -> None:
    """Each moved fact lands on the zone and its growspace copy is gone."""
    migrated = migrate_growspace_document(_v1_growspace())

    (zone,) = migrated["irrigation_zones"]
    assert zone["id"] == IMPLICIT_ZONE_ID
    assert zone["name"] == ""
    assert zone["cells"] == [[1, 1], [1, 2], [2, 1], [2, 2]]
    assert zone["valves"] == []
    assert zone["soil_moisture_sensor"] == "sensor.vwc"
    assert zone["pore_ec_sensors"] == ["sensor.pore"]
    assert zone["bulk_ec_sensors"] == ["sensor.bulk"]
    assert zone["substrate_temperature_sensors"] == ["sensor.substrate_t"]
    assert zone["pump_flow_rate_ml_per_sec"] == 12.5
    assert zone["irrigation_times"] == [{"time": "09:00:00", "duration": 45}]
    assert zone["irrigation_duration"] == 45
    assert zone["soil_trigger_percent"] == 38.0
    assert zone["min_interval_minutes"] == 7
    assert zone["active_steering_phase"] == "p1"
    assert zone["phase_changed_at"] == "2026-09-20T10:15:00+00:00"
    assert zone["strategy"] == {
        "enabled": True,
        "target_vwc_percent": 52.0,
        "p1_shot_duration_seconds": 30,
    }
    assert zone["substrate_history"] == {"shots_today": 4, "current_day": "2026-09-20"}

    assert migrated["light_cycle"] == {
        "lights_on_time": "06:30:00",
        "auto_light_tracking": True,
        "detected_lights_on_time": "06:32:00",
    }
    assert "irrigation_strategy" not in migrated
    assert "substrate_history" not in migrated
    assert migrated["irrigation_config"] == {
        "irrigation_pump_entity": "switch.pump",
        "drain_times": [{"time": "20:00:00", "duration": 30}],
        "daily_volume_cap_liters": 10.0,
        "max_cycles_per_day": 12,
    }
    assert migrated["environment_config"] == {"temperature_sensors": ["sensor.t"]}
    assert zone_integrity_problems(migrated) == []


def test_migration_leaves_the_input_untouched_and_is_idempotent() -> None:
    """The Pre-Migration Copy depends on the input surviving the migration."""
    original = _v1_growspace()
    before = copy.deepcopy(original)

    migrated = migrate_growspace_document(original)

    assert original == before
    again = migrate_growspace_document(migrated)
    assert again == migrated
    assert again is not migrated


def test_migration_moves_subarea_substrate_probes_off_its_environment() -> None:
    """A Subarea keeps the temperature probes its editor round-trips; the rest go."""
    migrated = migrate_growspace_document(_v1_growspace())

    (subarea,) = migrated["subareas"]
    assert subarea["environment_config"] == {"temperature_sensors": ["sensor.left_t"]}
    assert subarea["substrate_temperature_sensors"] == ["sensor.left_root"]

    loaded = Growspace.from_dict(migrated).subareas[0]
    assert loaded.substrate_temperature_sensors == ["sensor.left_root"]
    wire = loaded.wire_dict()
    assert "substrate_temperature_sensors" not in wire
    assert wire["environment_config"]["substrate_temperature_sensors"] == [
        "sensor.left_root"
    ]
    assert "soil_moisture_sensor" not in wire["environment_config"]


def test_migration_adopts_legacy_bulk_ec_spellings() -> None:
    """``substrate_ec_sensor(s)`` were migrated on load; now the store does it."""
    migrated = migrate_growspace_document(
        _v1_growspace(environment_config={"substrate_ec_sensor": "sensor.old_ec"})
    )
    assert migrated["irrigation_zones"][0]["bulk_ec_sensors"] == ["sensor.old_ec"]
    assert migrated["environment_config"] == {}

    both = migrate_growspace_document(
        _v1_growspace(
            environment_config={
                "bulk_ec_sensors": ["sensor.new"],
                "substrate_ec_sensors": ["sensor.old"],
            }
        )
    )
    assert both["irrigation_zones"][0]["bulk_ec_sensors"] == ["sensor.new"]

    empty = migrate_growspace_document(
        _v1_growspace(environment_config={"substrate_ec_sensor": None})
    )
    assert empty["irrigation_zones"][0]["bulk_ec_sensors"] == []


def test_migration_of_a_growspace_with_nothing_irrigation_related() -> None:
    """An old or bare growspace still gets one zone owning its whole grid."""
    migrated = migrate_growspace_document(
        {
            "id": "bare",
            "name": "Bare",
            "rows": "3.0",
            "plants_per_row": "oops",
            "irrigation_config": None,
            "environment_config": None,
            "irrigation_strategy": None,
        }
    )

    (zone,) = migrated["irrigation_zones"]
    assert zone["cells"] == [list(cell) for cell in grid_cells(3, 3)]
    assert zone["strategy"] == {}
    assert zone["substrate_history"] == {}
    assert migrated["light_cycle"] == {}
    assert migrated["irrigation_config"] is None
    assert zone_integrity_problems(migrated) == []

    loaded = Growspace.from_dict(migrated)
    # Old stores had no caps; that choice survives the move.
    assert loaded.irrigation_config.daily_volume_cap_liters is None
    assert loaded.irrigation_config.max_cycles_per_day is None


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("irrigation_zones"), ["it has no irrigation zone"]),
        (lambda d: d.update(irrigation_zones=[]), ["it has no irrigation zone"]),
        (
            lambda d: d.update(irrigation_zones=["default"]),
            ["a stored irrigation zone is not an object"],
        ),
        (
            lambda d: d["irrigation_zones"][0].update(id="zone_a"),
            ["it has no implicit zone 'default'"],
        ),
        (
            lambda d: d["irrigation_zones"].append(
                {"id": "default", "cells": [[9, 9]]}
            ),
            [
                "zone id 'default' is used 2 times",
                "1 zone cell(s) lie outside the grid, first (9, 9)",
            ],
        ),
        (
            lambda d: d["irrigation_zones"][0].update(cells=[[1, 1], [1, 2], [2, 1]]),
            ["1 cell(s) belong to no zone, first (2, 2)"],
        ),
        (
            lambda d: d["irrigation_zones"].append({"id": "b", "cells": [[1, 1]]}),
            ["1 cell(s) belong to more than one zone, first (1, 1)"],
        ),
        (
            lambda d: d["irrigation_zones"][0]["cells"].append("x"),
            ["zone 'default' has an unreadable cell"],
        ),
        (
            lambda d: d["irrigation_zones"][0].update(id=[]),
            [
                "a stored irrigation zone has an invalid id",
                "it has no implicit zone 'default'",
            ],
        ),
        (
            lambda d: d["irrigation_zones"][0].update(cells=3),
            [
                "zone 'default' has an unreadable cell list",
                "4 cell(s) belong to no zone, first (1, 1)",
            ],
        ),
        (
            lambda d: d.update(
                irrigation_strategy={},
                irrigation_config={"pump_flow_rate_ml_per_sec": 1.0},
                environment_config={
                    "soil_moisture_sensor": None,
                    "substrate_ec_sensor": None,
                },
            ),
            [
                "zone-owned settings are still stored on the growspace: "
                "environment_config.soil_moisture_sensor, "
                "environment_config.substrate_ec_sensor, "
                "irrigation_config.pump_flow_rate_ml_per_sec, irrigation_strategy"
            ],
        ),
    ],
)
def test_integrity_check_names_each_problem(mutate: Any, expected: list[str]) -> None:
    """Every rule of ADR-0063 item 6 has its own refusal."""
    document = migrate_growspace_document(_v1_growspace())
    mutate(document)
    assert zone_integrity_problems(document) == expected


def test_a_new_growspace_has_its_implicit_zone() -> None:
    """Made without zones, a growspace gets one owning its grid."""
    growspace = Growspace(id="new", name="New", rows=2, plants_per_row=3)

    assert [zone.id for zone in growspace.irrigation_zones] == [IMPLICIT_ZONE_ID]
    assert growspace.default_zone.cells == grid_cells(2, 3)
    assert zone_of(growspace) is growspace.default_zone
    assert zone_of(growspace, IMPLICIT_ZONE_ID) is growspace.default_zone
    with pytest.raises(KeyError):
        zone_of(growspace, "missing")


def test_default_zone_falls_back_to_the_first_zone() -> None:
    """A growspace held for a missing ``default`` still has a zone to read."""
    zone = IrrigationZone(id="zone_a")
    growspace = Growspace(id="gs", name="Gs", irrigation_zones=[zone])
    assert growspace.default_zone is zone


def test_effective_views_put_both_halves_back_together() -> None:
    """The views are the pre-zones shapes the steering code always read."""
    growspace = Growspace.from_dict(migrate_growspace_document(_v1_growspace()))

    config = effective_config(growspace)
    strategy = effective_strategy(growspace)

    assert isinstance(config, IrrigationConfig)
    assert config.irrigation_pump_entity == "switch.pump"
    assert config.pump_flow_rate_ml_per_sec == 12.5
    assert config.irrigation_times == [{"time": "09:00:00", "duration": 45}]
    assert config.drain_times == [{"time": "20:00:00", "duration": 30}]
    assert isinstance(strategy, IrrigationStrategy)
    assert strategy.enabled is True
    assert strategy.lights_on_time == "06:30:00"
    assert strategy.detected_lights_on_time == "06:32:00"
    assert strategy.target_vwc_percent == 52.0
    assert effective_environment_probes(growspace) == {
        "soil_moisture_sensor": "sensor.vwc",
        "pore_ec_sensors": ["sensor.pore"],
        "bulk_ec_sensors": ["sensor.bulk"],
        "substrate_temperature_sensors": ["sensor.substrate_t"],
    }
    assert set(effective_environment_probes(growspace)) == set(ZONE_ENVIRONMENT_FIELDS)


def test_a_view_is_detached_until_it_is_applied() -> None:
    """Writing to a view changes nothing; applying it splits it back."""
    growspace = Growspace.from_dict(migrate_growspace_document(_v1_growspace()))
    zone = growspace.default_zone

    config = effective_config(growspace)
    strategy = effective_strategy(growspace)
    config.irrigation_times.append({"time": "10:00:00", "duration": 5})
    config.pump_flow_rate_ml_per_sec = 20.0
    config.max_cycle_seconds = 300
    strategy.target_vwc_percent = 60.0
    strategy.lights_on_time = "07:00:00"
    assert len(zone.irrigation_times) == 1
    assert zone.pump_flow_rate_ml_per_sec == 12.5

    apply_effective_irrigation(growspace, config, strategy)

    assert zone.pump_flow_rate_ml_per_sec == 20.0
    assert len(zone.irrigation_times) == 2
    assert growspace.irrigation_config.max_cycle_seconds == 300
    assert type(growspace.irrigation_config) is GrowspaceIrrigationConfig
    assert zone.strategy.target_vwc_percent == 60.0
    assert type(zone.strategy) is SteeringStrategy
    assert growspace.light_cycle == LightCycle(
        lights_on_time="07:00:00",
        auto_light_tracking=True,
        detected_lights_on_time="06:32:00",
    )


def test_grid_growth_inherits_the_boundary_zone() -> None:
    """New cells inherit the zone at the old grid boundary."""
    growspace = Growspace(id="gs", name="Gs", rows=2, plants_per_row=2)
    growspace.rows = 3
    sync_implicit_zone_cells(growspace)
    assert growspace.default_zone.cells == grid_cells(3, 2)

    growspace.irrigation_zones.append(IrrigationZone(id="b", cells=[]))
    growspace.rows = 4
    sync_implicit_zone_cells(growspace)
    assert growspace.default_zone.cells == grid_cells(4, 2)


def test_zone_model_reads_nulls_and_legacy_schedule_items() -> None:
    """A stored zone tolerates what an old or hand-edited store may hold."""
    zone = IrrigationZone.from_dict(
        {
            "id": "default",
            "cells": [[1, 1]],
            "valves": None,
            "pore_ec_sensors": None,
            "irrigation_times": [{"start_time": "08:00:00", "duration_seconds": "30"}],
            "strategy": None,
            "substrate_history": None,
        }
    )
    assert zone.cells == [(1, 1)]
    assert zone.valves == []
    assert zone.pore_ec_sensors == []
    assert zone.irrigation_times == [{"time": "08:00:00", "duration": 30}]
    assert zone.strategy == SteeringStrategy()
