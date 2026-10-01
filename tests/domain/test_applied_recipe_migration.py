"""The unreleased v2 migration backfills Applied Recipe copies (ADR-0065)."""

import copy

import pytest

from custom_components.growspace_manager.storage_manager import _migrate_growspaces


@pytest.mark.parametrize("kind", ["crop_steering", "schedule"])
def test_v2_backfills_detached_recipe_values_and_provenance(kind):
    """Old stamps retain a portable copy; deleted recipes get none."""
    values = (
        {
            "lights_on_time": "09:00:00",
            "auto_light_tracking": True,
            "target_vwc_percent": 61,
            "p1_shot_volume_percent": 3,
        }
        if kind == "crop_steering"
        else {
            "irrigation_times": [{"time": "09:00:00", "duration": 45}],
            "irrigation_duration": 45,
            "drain_times": [{"time": "10:00:00", "duration": 20}],
            "drain_duration": 20,
            "daily_volume_cap_liters": 12,
            "max_cycles_per_day": 6,
            "skip_during_dark": True,
        }
    )
    raw = {
        "growspaces": {
            "live": {
                "rows": 1,
                "plants_per_row": 1,
                "irrigation_strategy": {
                    "applied_recipe_id": "r",
                    "recipe_applied_at": "then",
                },
            },
            "deleted": {"irrigation_strategy": {"applied_recipe_id": "gone"}},
            "invalid": "malformed",
        },
        "irrigation_recipes": {
            "r": {"id": "r", "name": "R", "kind": kind, kind: values}
        },
    }
    before = copy.deepcopy(raw)
    migrated = _migrate_growspaces(raw)
    assert raw == before
    recipe = migrated["irrigation_recipes"]["r"]
    assert recipe["revision"] == 1
    applied = migrated["growspaces"]["live"]["irrigation_zones"][0]["strategy"]
    assert "applied_recipe_id" not in applied
    assert applied["recipe_applied_at"] == "then"
    assert applied["applied_recipe"] == {
        "id": "r",
        "revision": 1,
        "values": recipe[kind],
    }
    assert (
        migrated["growspaces"]["deleted"]["irrigation_zones"][0]["strategy"][
            "applied_recipe"
        ]
        is None
    )
    assert _migrate_growspaces(migrated) == migrated
    key = "lights_on_time" if kind == "crop_steering" else "drain_times"
    assert (
        key in recipe["provenance"] and key not in applied["applied_recipe"]["values"]
    )
    recipe[kind][
        "target_vwc_percent" if kind == "crop_steering" else "irrigation_duration"
    ] = 999
    assert applied["applied_recipe"]["values"] != recipe[kind]


def test_migration_preserves_documents_without_growspaces():
    """The legacy missing-document case remains a no-op."""
    assert _migrate_growspaces({}) == {}
