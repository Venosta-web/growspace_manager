"""Unit tests for the Environment Patch write seam (ADR-0026).

These tests are pure: they build EnvironmentConfig literals and plain dicts,
then assert the EnvironmentPatchVerdict. No Home Assistant instance,
coordinator, or sensor is involved — the patch module's interface is the test
surface. They pin the regression table behind the seam: the exhaust-config
reset (ADR-0019), the Stage Hysteresis Threshold wipe, the tank runtime
clobber, the electricity-cost type violation, and the
singular-resurrects-cleared-plural hazard.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any

import pytest

from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatch,
    EnvironmentPatchError,
    apply_environment_patch,
    circulation_fan_patch,
    exhaust_fan_patch,
    patch_from_flow_options,
    patch_from_service_call,
    validate_stage_vpd_overrides,
    validate_vpd_optimal_overrides,
)
from custom_components.growspace_manager.models import (
    ENVIRONMENT_FIELD_OWNERSHIP,
    CirculationFanConfig,
    EnvironmentConfig,
    ExhaustFanConfig,
    FieldClass,
    FieldOwnership,
    GrowLightConfig,
    IrrigationTank,
    TankWaterHistory,
    VisionCheckupConfig,
)


def _lived_in_config() -> EnvironmentConfig:
    """An EnvironmentConfig with non-default values in every fragile corner."""
    return EnvironmentConfig(
        temperature_sensors=["sensor.temp_a"],
        humidity_sensors=["sensor.hum_a"],
        co2_sensor="sensor.co2",
        dli_target_veg=35.0,
        dli_target_flower=50.0,
        electricity_cost_per_kwh=0.31,
        stress_threshold=0.55,
        mold_threshold=0.65,
        snapshot_interval_hours=6,
        dehumidifier_thresholds={"veg": {"day": {"on": 1.4, "off": 1.1}}},
        humidifier_thresholds={"veg": {"day": {"on": 0.8, "off": 1.0}}},
        bayesian_options={"vpd_trend_duration": 30, "stress_prior": 0.2},
        exhaust_fan_config=ExhaustFanConfig(enabled=True, max_speed=80),
        circulation_fan_config=CirculationFanConfig(enabled=True, min_speed=20),
        growlight_config=GrowLightConfig(enabled=True, power=75),
        growlight_entities=["light.panel"],
        vpd_optimal_overrides={
            "veg": {
                "day": {"low": 0.8, "high": 1.2},
                "night": {"low": 0.7, "high": 1.1},
            }
        },
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank_a",
                name="Tank A",
                warning_level=25.0,
                last_recorded_level=42.0,
                peak_level=98.0,
                water_history=TankWaterHistory(
                    events=[{"timestamp": "2026-07-01T10:00:00", "liters": 3.5}]
                ),
            )
        ],
    )


# ---------------------------------------------------------------------------
# Apply: patch semantics
# ---------------------------------------------------------------------------


def test_empty_patch_is_identity() -> None:
    """An empty patch changes nothing and restarts nothing."""
    current = _lived_in_config()
    verdict = apply_environment_patch(current, EnvironmentPatch(values={}))
    assert verdict.config == current
    assert verdict.changed_fields == frozenset()
    assert verdict.controllers_to_restart == frozenset()
    assert verdict.exhaust_repair_relevant is False
    assert verdict.summary == "no changes"


@pytest.mark.parametrize(
    ("preserved_field", "expected"),
    [
        ("exhaust_fan_config", ExhaustFanConfig(enabled=True, max_speed=80)),
        ("dehumidifier_thresholds", {"veg": {"day": {"on": 1.4, "off": 1.1}}}),
        ("humidifier_thresholds", {"veg": {"day": {"on": 0.8, "off": 1.0}}}),
        ("bayesian_options", {"vpd_trend_duration": 30, "stress_prior": 0.2}),
        ("dli_target_veg", 35.0),
        ("dli_target_flower", 50.0),
        ("electricity_cost_per_kwh", 0.31),
        ("stress_threshold", 0.55),
        ("mold_threshold", 0.65),
        ("snapshot_interval_hours", 6),
        ("growlight_config", GrowLightConfig(enabled=True, power=75)),
        ("growlight_entities", ["light.panel"]),
        (
            "vpd_optimal_overrides",
            {
                "veg": {
                    "day": {"low": 0.8, "high": 1.2},
                    "night": {"low": 0.7, "high": 1.1},
                }
            },
        ),
    ],
)
def test_absent_fields_are_kept(preserved_field: str, expected: Any) -> None:
    """The regression table: every historically wiped field survives a patch."""
    current = _lived_in_config()
    patch = patch_from_service_call(
        {"growspace_id": "tent", "camera_entities": ["camera.tent"]}
    )
    verdict = apply_environment_patch(current, patch)
    assert getattr(verdict.config, preserved_field) == expected
    assert verdict.changed_fields == {"camera_entities"}


def test_explicit_empty_list_clears() -> None:
    """A present-but-empty list is a deliberate clear, not an omission."""
    current = _lived_in_config()
    patch = patch_from_service_call({"growlight_entities": []})
    verdict = apply_environment_patch(current, patch)
    assert verdict.config.growlight_entities == []
    assert "growlight_entities" in verdict.changed_fields


def test_explicit_null_for_non_nullable_keeps_existing() -> None:
    """The electricity-cost type violation: null never lands on a float field."""
    current = _lived_in_config()
    patch = patch_from_service_call({"electricity_cost_per_kwh": None})
    verdict = apply_environment_patch(current, patch)
    assert verdict.config.electricity_cost_per_kwh == 0.31
    assert [w.field for w in patch.warnings] == ["electricity_cost_per_kwh"]


def test_explicit_null_clears_nullable() -> None:
    """Null on an Optional field is a deliberate clear."""
    current = _lived_in_config()
    verdict = apply_environment_patch(
        current, patch_from_service_call({"co2_sensor": None})
    )
    assert verdict.config.co2_sensor is None
    assert "co2_sensor" in verdict.changed_fields


def test_restating_current_values_changes_nothing() -> None:
    """changed_fields is by value comparison, not key presence."""
    current = _lived_in_config()
    patch = patch_from_service_call(
        {"dli_target_veg": 35.0, "growlight_entities": ["light.panel"]}
    )
    verdict = apply_environment_patch(current, patch)
    assert verdict.changed_fields == frozenset()
    assert verdict.summary == "no changes"


def test_apply_onto_none_uses_defaults() -> None:
    """current=None applies onto dataclass defaults (the migration path)."""
    patch = patch_from_flow_options({"temperature_sensors": ["sensor.t"]})
    verdict = apply_environment_patch(None, patch)
    assert verdict.config.temperature_sensors == ["sensor.t"]
    assert verdict.config.veg_day_hours == 18


# ---------------------------------------------------------------------------
# Aliases and singular shadows
# ---------------------------------------------------------------------------


def test_singular_shadow_rewrites_to_plural() -> None:
    """A legacy singular key lands on the plural field and the shadow follows."""
    verdict = apply_environment_patch(
        None, patch_from_service_call({"temperature_sensor": "sensor.t"})
    )
    assert verdict.config.temperature_sensors == ["sensor.t"]
    assert verdict.config.temperature_sensor == "sensor.t"


def test_plural_wins_when_both_spellings_present() -> None:
    """The plural spelling is authoritative when both are sent."""
    verdict = apply_environment_patch(
        None,
        patch_from_service_call(
            {"temperature_sensor": "sensor.old", "temperature_sensors": ["sensor.new"]}
        ),
    )
    assert verdict.config.temperature_sensors == ["sensor.new"]
    assert verdict.config.temperature_sensor == "sensor.new"


def test_cleared_plural_is_not_resurrected_by_stale_singular() -> None:
    """Clearing the plural also clears the shadow, defusing __post_init__."""
    current = _lived_in_config()
    assert current.temperature_sensor == "sensor.temp_a"
    verdict = apply_environment_patch(
        current, patch_from_service_call({"temperature_sensors": []})
    )
    assert verdict.config.temperature_sensors == []
    assert verdict.config.temperature_sensor is None


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("exhaust_entity", "exhaust_fan_entities"),
        ("exhaust_fan_entity", "exhaust_fan_entities"),
        ("circulation_fan_entity", "circulation_fan_entities"),
        ("humidifier_entity", "humidifier_entities"),
        ("dehumidifier_entity", "dehumidifier_entities"),
        ("light_sensor", "light_sensors"),
        ("growlight_entity", "growlight_entities"),
        ("substrate_ec_sensor", "bulk_ec_sensors"),
    ],
)
def test_wire_aliases_rewrite_to_canonical(alias: str, canonical: str) -> None:
    """Historic wire spellings land on the canonical plural field."""
    patch = patch_from_service_call({alias: "sensor.x"})
    assert patch.values[canonical] == ["sensor.x"]


# ---------------------------------------------------------------------------
# Tank runtime carry-over
# ---------------------------------------------------------------------------


def test_tank_runtime_carried_over_for_matched_tank() -> None:
    """A re-sent tank keeps accumulated runtime while grower fields update."""
    current = _lived_in_config()
    patch = patch_from_service_call(
        {
            "irrigation_tanks": [
                {
                    "sensor_entity": "sensor.tank_a",
                    "name": "Tank A",
                    "warning_level": 15.0,
                }
            ]
        }
    )
    verdict = apply_environment_patch(current, patch)
    tank = verdict.config.irrigation_tanks[0]
    assert tank.warning_level == 15.0
    assert tank.last_recorded_level == 42.0
    assert tank.peak_level == 98.0
    assert tank.water_history.events == [
        {"timestamp": "2026-07-01T10:00:00", "liters": 3.5}
    ]


def test_restated_tank_without_runtime_is_not_a_change() -> None:
    """Runtime carry-over happens before diffing, so runtime never reads as change."""
    current = _lived_in_config()
    patch = patch_from_service_call(
        {
            "irrigation_tanks": [
                {
                    "sensor_entity": "sensor.tank_a",
                    "name": "Tank A",
                    "warning_level": 25.0,
                }
            ]
        }
    )
    verdict = apply_environment_patch(current, patch)
    assert "irrigation_tanks" not in verdict.changed_fields


def test_unmatched_tank_keeps_its_own_values() -> None:
    """A new tank starts fresh; a migrated blob's runtime values are adopted."""
    patch = patch_from_flow_options(
        {
            "irrigation_tanks": [
                {"sensor_entity": "sensor.tank_b", "last_recorded_level": 77.0}
            ]
        }
    )
    verdict = apply_environment_patch(None, patch)
    assert verdict.config.irrigation_tanks[0].last_recorded_level == 77.0


def test_removed_tank_is_gone_with_its_runtime() -> None:
    """An explicitly sent empty tank list is a deliberate clear."""
    current = _lived_in_config()
    verdict = apply_environment_patch(
        current, patch_from_service_call({"irrigation_tanks": []})
    )
    assert verdict.config.irrigation_tanks == []


def test_invalid_tank_item_dropped_with_warning() -> None:
    """A malformed list item is dropped leniently; valid siblings survive."""
    patch = patch_from_service_call(
        {
            "irrigation_tanks": [
                {"name": "no sensor_entity"},
                {"sensor_entity": "sensor.ok"},
            ]
        }
    )
    assert [t.sensor_entity for t in patch.values["irrigation_tanks"]] == ["sensor.ok"]
    assert [w.field for w in patch.warnings] == ["irrigation_tanks"]


# ---------------------------------------------------------------------------
# Catch-all mirror (bayesian_options)
# ---------------------------------------------------------------------------


def test_unknown_keys_merge_into_bayesian_options() -> None:
    """Advanced Bayesian/trend keys merge into bayesian_options, not replace it."""
    current = _lived_in_config()
    patch = patch_from_flow_options({"vpd_trend_sensitivity": 0.4})
    verdict = apply_environment_patch(current, patch)
    assert verdict.config.bayesian_options == {
        "vpd_trend_duration": 30,
        "stress_prior": 0.2,
        "vpd_trend_sensitivity": 0.4,
    }


def test_explicit_bayesian_options_replaces_before_updates_merge() -> None:
    """An explicit bayesian_options value replaces the dict; extras merge on top."""
    current = _lived_in_config()
    patch = patch_from_flow_options(
        {"bayesian_options": {}, "vpd_trend_sensitivity": 0.4}
    )
    verdict = apply_environment_patch(current, patch)
    assert verdict.config.bayesian_options == {"vpd_trend_sensitivity": 0.4}


def test_flow_bookkeeping_keys_are_dropped() -> None:
    """Flow navigation keys never leak into bayesian_options."""
    patch = patch_from_flow_options(
        {"configure_advanced": True, "configure_dehumidifier": True}
    )
    assert patch.values == {}
    assert patch.bayesian_updates == {}


def test_growspace_id_is_dropped_from_service_calls() -> None:
    """Routing keys never leak into bayesian_options."""
    patch = patch_from_service_call({"growspace_id": "tent"})
    assert patch.values == {}
    assert patch.bayesian_updates == {}


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------


def test_sub_config_dict_replaces_whole_with_defaults() -> None:
    """A partial sub-config dict replaces the whole sub-config (settled semantics)."""
    current = _lived_in_config()
    patch = patch_from_service_call(
        {"circulation_fan_config": {"enabled": True, "max_speed": 70}}
    )
    verdict = apply_environment_patch(current, patch)
    fan = verdict.config.circulation_fan_config
    assert fan.enabled is True
    assert fan.max_speed == 70
    assert fan.min_speed == 0  # sub-config default, not the previous 20


def test_circulation_fan_patch_builds_one_field_patch() -> None:
    """The narrow writer's payload becomes a whole-replace sub-config patch."""
    patch = circulation_fan_patch(
        {"growspace_id": "tent", "enabled": True, "wind_amplitude_pct": 15}
    )
    assert set(patch.values) == {"circulation_fan_config"}
    assert patch.values["circulation_fan_config"].wind_amplitude_pct == 15


def test_exhaust_fan_patch_builds_one_field_patch() -> None:
    """The exhaust twin mirrors the current handler's construction."""
    patch = exhaust_fan_patch({"enabled": True, "critical_temp_high": 32.0})
    cfg = patch.values["exhaust_fan_config"]
    assert cfg.enabled is True
    assert cfg.critical_temp_high == 32.0


def test_growlight_sub_config_parsed_from_dict() -> None:
    """Non-fan sub-configs parse via from_dict with key filtering."""
    patch = patch_from_service_call(
        {"growlight_config": {"enabled": True, "power": 60, "bogus": 1}}
    )
    assert patch.values["growlight_config"] == GrowLightConfig(enabled=True, power=60)


# ---------------------------------------------------------------------------
# Validation error modes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"not_a_stage": {"day": 1.0, "night": 1.0}},
        {"veg": {"day": 1.0}},
        {"veg": {"day": 9.0, "night": 1.0}},
        {"veg": {"day": "high", "night": 1.0}},
    ],
)
def test_stage_vpd_override_validation_raises(overrides: dict[str, Any]) -> None:
    """Bad stage VPD overrides fail the build, not the apply."""
    with pytest.raises(EnvironmentPatchError):
        validate_stage_vpd_overrides(overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "not_a_stage": {
                "day": {"low": 0.8, "high": 1.2},
                "night": {"low": 0.8, "high": 1.2},
            }
        },
        {"veg": {"day": {"low": 1.2, "high": 0.8}, "night": {"low": 0.8, "high": 1.2}}},
        {"veg": {"day": {"low": 0.8}, "night": {"low": 0.8, "high": 1.2}}},
        {"veg": {"day": {"low": 0.8, "high": 1.2}}},
    ],
)
def test_vpd_optimal_override_validation_raises(overrides: dict[str, Any]) -> None:
    """Bad optimal-band overrides fail the build."""
    with pytest.raises(EnvironmentPatchError):
        validate_vpd_optimal_overrides(overrides)


def test_bad_stage_override_inside_fan_payload_raises() -> None:
    """The narrow fan builder routes through the shared validator."""
    with pytest.raises(EnvironmentPatchError):
        circulation_fan_patch(
            {"stage_vpd_overrides": {"bogus": {"day": 1, "night": 1}}}
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"dehumidifier_thresholds": "not-a-dict"},
        {"camera_entities": 42},
        {"circulation_fan_config": "not-a-dict"},
        {"irrigation_tanks": "not-a-list"},
    ],
)
def test_structural_errors_raise(payload: dict[str, Any]) -> None:
    """Wrong-shaped payloads are build errors, not silent drops."""
    with pytest.raises(EnvironmentPatchError):
        patch_from_service_call(payload)


@pytest.mark.parametrize(
    "values",
    [
        {"no_such_field": 1},
        {"temperature_sensor": "sensor.t"},
    ],
)
def test_hand_built_patch_rejects_bad_keys(values: dict[str, Any]) -> None:
    """Unknown fields and singular shadows are rejected at patch construction."""
    with pytest.raises(EnvironmentPatchError):
        EnvironmentPatch(values=values)


def test_hand_built_patch_rejects_runtime_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime-accumulated field can never be patched directly."""
    monkeypatch.setitem(
        ENVIRONMENT_FIELD_OWNERSHIP,
        "fake_runtime_field",
        FieldOwnership(FieldClass.RUNTIME_ACCUMULATED),
    )
    with pytest.raises(EnvironmentPatchError):
        EnvironmentPatch(values={"fake_runtime_field": 1})


# ---------------------------------------------------------------------------
# Verdict: controllers, repair relevance, summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected_controllers"),
    [
        ({"circulation_fan_config": {"enabled": True}}, {"circulation_fan"}),
        ({"exhaust_fan_entities": ["fan.exhaust"]}, {"exhaust_fan"}),
        ({"growlight_entities": ["light.new"]}, {"growlight"}),
        ({"veg_day_hours": 20}, {"growlight"}),
        ({"camera_entities": ["camera.tent"]}, set()),
    ],
)
def test_controllers_to_restart_mapping(
    payload: dict[str, Any], expected_controllers: set[str]
) -> None:
    """The field→controller relevance table drives targeted restarts."""
    verdict = apply_environment_patch(
        _lived_in_config(), patch_from_service_call(payload)
    )
    assert verdict.controllers_to_restart == frozenset(expected_controllers)


@pytest.mark.parametrize(
    ("values", "expected_controllers"),
    [
        ({"control_dehumidifier": True}, {"dehumidifier"}),
        ({"control_humidifier": True}, {"humidifier"}),
        ({"dehumidifier_entities": ["switch.dehum"]}, {"dehumidifier"}),
        ({"humidifier_entities": ["switch.hum"]}, {"humidifier"}),
    ],
)
def test_control_flag_flips_mark_the_matching_controller_for_restart(
    values: dict[str, Any], expected_controllers: set[str]
) -> None:
    """set_dehumidifier_control / set_humidifier_control's lone-key patch (the
    shape ``handle_set_dehumidifier_control`` / ``handle_set_humidifier_control``
    build) must restart the coordinator it flips — otherwise the long-lived
    controller instance never notices the flag changed and keeps controlling
    (or not controlling) the device with whatever it read at HA startup.
    """
    verdict = apply_environment_patch(_lived_in_config(), EnvironmentPatch(values=values))
    assert verdict.controllers_to_restart == frozenset(expected_controllers)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"control_dehumidifier": True}, True),
        ({"exhaust_fan_entities": ["fan.exhaust"]}, True),
        ({"exhaust_fan_config": {"enabled": True}}, True),
        ({"camera_entities": ["camera.tent"]}, False),
    ],
)
def test_exhaust_repair_relevance(payload: dict[str, Any], expected: bool) -> None:
    """The ADR-0019 repair re-evaluation fires from the verdict, not memory."""
    verdict = apply_environment_patch(
        _lived_in_config(), patch_from_service_call(payload)
    )
    assert verdict.exhaust_repair_relevant is expected


def test_summary_names_changed_fields() -> None:
    """The summary is pure-formatted logbook text."""
    verdict = apply_environment_patch(
        _lived_in_config(),
        patch_from_service_call({"veg_day_hours": 20, "camera_entities": ["camera.a"]}),
    )
    assert verdict.summary == "updated camera_entities, veg_day_hours"


def test_inputs_are_not_mutated() -> None:
    """Apply builds a fresh config; the existing instance is untouched."""
    current = _lived_in_config()
    verdict = apply_environment_patch(
        current, patch_from_service_call({"veg_day_hours": 20})
    )
    assert current.veg_day_hours == 18
    assert verdict.config is not current


# ---------------------------------------------------------------------------
# Classification table sanity
# ---------------------------------------------------------------------------


def test_every_canonical_alias_targets_a_real_plural_field() -> None:
    """Shadow rows must point at existing list fields."""
    model_fields = {f.name for f in fields(EnvironmentConfig)}
    canonicals = {
        ownership.canonical
        for ownership in ENVIRONMENT_FIELD_OWNERSHIP.values()
        if ownership.canonical is not None
    }
    assert canonicals <= model_fields


def test_item_runtime_spec_matches_irrigation_tank() -> None:
    """The nested runtime spec names real IrrigationTank fields."""
    ownership = ENVIRONMENT_FIELD_OWNERSHIP["irrigation_tanks"]
    tank_fields = {f.name for f in fields(IrrigationTank)}
    assert ownership.item_identity in tank_fields
    assert set(ownership.item_runtime_fields) <= tank_fields


# ---------------------------------------------------------------------------
# Edge branches: helpers, None normalisation, passthroughs, error wraps
# ---------------------------------------------------------------------------


def test_verdict_changed_helper() -> None:
    """changed() answers per-field questions for the commit shell."""
    verdict = apply_environment_patch(
        _lived_in_config(), patch_from_service_call({"veg_day_hours": 20})
    )
    assert verdict.changed("veg_day_hours", "co2_sensor") is True
    assert verdict.changed("co2_sensor") is False


def test_validators_treat_none_as_empty() -> None:
    """None overrides mean 'no overrides', not an error."""
    assert validate_stage_vpd_overrides(None) == {}
    assert validate_vpd_optimal_overrides(None) == {}


def test_validators_reject_non_dict() -> None:
    """A non-dict overrides payload is a structural error."""
    with pytest.raises(EnvironmentPatchError):
        validate_stage_vpd_overrides("not-a-dict")
    with pytest.raises(EnvironmentPatchError):
        validate_vpd_optimal_overrides("not-a-dict")


def test_vpd_optimal_out_of_range_raises() -> None:
    """Optimal-band values outside 0.1-3.0 kPa fail the build."""
    with pytest.raises(EnvironmentPatchError):
        validate_vpd_optimal_overrides(
            {
                "veg": {
                    "day": {"low": 0.05, "high": 1.2},
                    "night": {"low": 0.8, "high": 1.2},
                }
            }
        )


def test_vpd_optimal_overrides_validated_through_builder() -> None:
    """The top-level overrides field routes through the shared validator."""
    good = {
        "veg": {"day": {"low": 0.8, "high": 1.2}, "night": {"low": 0.7, "high": 1.1}}
    }
    patch = patch_from_service_call({"vpd_optimal_overrides": good})
    assert patch.values["vpd_optimal_overrides"] == good
    with pytest.raises(EnvironmentPatchError):
        patch_from_service_call(
            {
                "vpd_optimal_overrides": {
                    "veg": {
                        "day": {"low": 1.2, "high": 0.8},
                        "night": {"low": 0.8, "high": 1.2},
                    }
                }
            }
        )


def test_alias_with_null_value_clears_plural() -> None:
    """An explicit null singular is a deliberate clear of the plural."""
    patch = patch_from_service_call({"light_sensor": None})
    assert patch.values["light_sensors"] == []


def test_alias_with_list_value_passes_through() -> None:
    """A list under a singular alias lands on the plural unchanged."""
    patch = patch_from_service_call({"light_sensor": ["sensor.a", "sensor.b"]})
    assert patch.values["light_sensors"] == ["sensor.a", "sensor.b"]


def test_builder_drops_runtime_field_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime-classified key arriving on the wire is dropped, not applied."""
    monkeypatch.setitem(
        ENVIRONMENT_FIELD_OWNERSHIP,
        "fake_runtime_field",
        FieldOwnership(FieldClass.RUNTIME_ACCUMULATED),
    )
    patch = patch_from_service_call({"fake_runtime_field": 1})
    assert patch.values == {}
    assert patch.bayesian_updates == {}
    assert [w.field for w in patch.warnings] == ["fake_runtime_field"]


def test_explicit_null_list_field_clears() -> None:
    """Null on a list field normalises to a deliberate empty list."""
    patch = patch_from_service_call({"camera_entities": None})
    assert patch.values["camera_entities"] == []


def test_explicit_null_dict_field_clears() -> None:
    """Null on a dict field normalises to a deliberate empty dict."""
    patch = patch_from_service_call({"sensor_coordinates": None})
    assert patch.values["sensor_coordinates"] == {}


def test_bare_string_for_list_field_is_wrapped() -> None:
    """Historic singular-value tolerance: a bare string becomes a one-item list."""
    patch = patch_from_service_call({"camera_entities": "camera.tent"})
    assert patch.values["camera_entities"] == ["camera.tent"]


def test_sub_config_instance_passes_through() -> None:
    """An already-typed sub-config is accepted as-is."""
    cfg = GrowLightConfig(enabled=True, power=40)
    patch = patch_from_service_call({"growlight_config": cfg})
    assert patch.values["growlight_config"] is cfg


def test_sub_config_null_means_keep() -> None:
    """Null sub-config keeps the existing one (historic service contract)."""
    patch = patch_from_service_call({"vision_checkup_config": None})
    assert "vision_checkup_config" not in patch.values


def test_sub_config_empty_dict_resets_to_defaults() -> None:
    """The explicit reset is an empty dict, replacing whole with defaults."""
    patch = patch_from_service_call({"vision_checkup_config": {}})
    assert patch.values["vision_checkup_config"] == VisionCheckupConfig()


def test_sub_config_bad_numeric_falls_back_to_default() -> None:
    """BaseModel numeric sanitization keeps generic sub-config parsing lenient."""
    patch = patch_from_service_call(
        {
            "vision_checkup_config": {
                "enabled": True,
                "early_check_offset_minutes": "soon",
            }
        }
    )
    cfg = patch.values["vision_checkup_config"]
    assert cfg.enabled is True
    assert cfg.early_check_offset_minutes == 60


def test_circulation_fan_numeric_error_wrapped() -> None:
    """Bad numeric payloads surface as EnvironmentPatchError, not ValueError."""
    with pytest.raises(EnvironmentPatchError):
        circulation_fan_patch({"min_speed": "slow"})


def test_exhaust_fan_numeric_error_wrapped() -> None:
    """The exhaust twin wraps conversion errors identically."""
    with pytest.raises(EnvironmentPatchError):
        exhaust_fan_patch({"min_speed": "slow"})


def test_exhaust_bad_stage_override_raises_unwrapped() -> None:
    """A validator error inside the exhaust payload keeps its message."""
    with pytest.raises(EnvironmentPatchError, match="Unknown stage key"):
        exhaust_fan_patch({"stage_vpd_overrides": {"bogus": {"day": 1, "night": 1}}})


def test_item_list_accepts_typed_instances() -> None:
    """Already-parsed items pass through the item list untouched."""
    tank = IrrigationTank(sensor_entity="sensor.tank_c")
    patch = patch_from_service_call({"irrigation_tanks": [tank]})
    assert patch.values["irrigation_tanks"] == [tank]


def test_item_list_drops_non_mapping_entry() -> None:
    """A non-mapping list entry is dropped with a warning; siblings survive."""
    patch = patch_from_service_call(
        {"irrigation_tanks": [42, {"sensor_entity": "sensor.ok"}]}
    )
    assert [t.sensor_entity for t in patch.values["irrigation_tanks"]] == ["sensor.ok"]
    assert [w.field for w in patch.warnings] == ["irrigation_tanks"]


def test_item_list_null_clears() -> None:
    """Null on a dataclass-list field is a deliberate clear."""
    patch = patch_from_service_call({"irrigation_tanks": None})
    assert patch.values["irrigation_tanks"] == []


# -- Acceptable Moisture Band ----------------------------------------------


def test_moisture_band_saves_a_complete_decimal_pair() -> None:
    """Both bounds are stored, coerced to float, in one atomic write."""
    verdict = apply_environment_patch(
        EnvironmentConfig(),
        patch_from_service_call(
            {"growspace_id": "gs1", "soil_moisture_min": 32.5, "soil_moisture_max": 54}
        ),
    )
    assert verdict.config.soil_moisture_min == 32.5
    assert verdict.config.soil_moisture_max == 54.0
    assert verdict.changed("soil_moisture_min", "soil_moisture_max")


def test_moisture_band_both_null_clears_back_to_inherited() -> None:
    """Reset-and-save removes the override rather than storing 20–60."""
    stored = EnvironmentConfig(soil_moisture_min=32.5, soil_moisture_max=54.0)
    verdict = apply_environment_patch(
        stored,
        patch_from_service_call({"soil_moisture_min": None, "soil_moisture_max": None}),
    )
    assert verdict.config.soil_moisture_min is None
    assert verdict.config.soil_moisture_max is None


def test_moisture_band_untouched_payload_preserves_a_stored_pair() -> None:
    """Patch semantics: a save that omits both bounds keeps the override."""
    stored = EnvironmentConfig(soil_moisture_min=32.5, soil_moisture_max=54.0)
    verdict = apply_environment_patch(
        stored, patch_from_service_call({"co2_sensor": "sensor.co2"})
    )
    assert verdict.config.soil_moisture_min == 32.5
    assert verdict.config.soil_moisture_max == 54.0


def test_moisture_band_survives_replacing_and_removing_the_sensor() -> None:
    """The override outlives the sensor it was configured against."""
    stored = EnvironmentConfig(
        soil_moisture_sensor="sensor.old",
        soil_moisture_min=32.5,
        soil_moisture_max=54.0,
    )
    replaced = apply_environment_patch(
        stored, patch_from_service_call({"soil_moisture_sensor": "sensor.new"})
    ).config
    assert (replaced.soil_moisture_min, replaced.soil_moisture_max) == (32.5, 54.0)

    removed = apply_environment_patch(
        replaced, patch_from_service_call({"soil_moisture_sensor": None})
    ).config
    assert removed.soil_moisture_sensor is None
    assert (removed.soil_moisture_min, removed.soil_moisture_max) == (32.5, 54.0)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"soil_moisture_min": 30.0}, id="minimum-alone"),
        pytest.param({"soil_moisture_max": 55.0}, id="maximum-alone"),
        pytest.param(
            {"soil_moisture_min": 30.0, "soil_moisture_max": None}, id="half-cleared"
        ),
        pytest.param(
            {"soil_moisture_min": None, "soil_moisture_max": 55.0}, id="half-set"
        ),
    ],
)
def test_moisture_band_rejects_a_partial_pair(payload: dict[str, Any]) -> None:
    """A lone bound would combine with the stored one into an unintended band."""
    with pytest.raises(EnvironmentPatchError, match="Acceptable Moisture Band"):
        patch_from_service_call(payload)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        pytest.param(60.0, 30.0, id="inverted"),
        pytest.param(40.0, 40.0, id="equal-bounds"),
        pytest.param(-1.0, 50.0, id="below-floor"),
        pytest.param(20.0, 101.0, id="above-ceiling"),
        pytest.param(float("nan"), 50.0, id="not-finite"),
    ],
)
def test_moisture_band_rejects_an_invalid_pair(minimum: float, maximum: float) -> None:
    """0 ≤ minimum < maximum ≤ 100 is enforced at the write seam."""
    with pytest.raises(EnvironmentPatchError, match="Acceptable Moisture Band"):
        patch_from_service_call(
            {"soil_moisture_min": minimum, "soil_moisture_max": maximum}
        )


def test_moisture_band_round_trips_through_serialization() -> None:
    """The pair survives a to_dict/from_dict cycle (storage + restart)."""
    stored = apply_environment_patch(
        EnvironmentConfig(),
        patch_from_service_call({"soil_moisture_min": 32.5, "soil_moisture_max": 54.0}),
    ).config
    restored = EnvironmentConfig.from_dict(stored.to_dict())
    assert restored.soil_moisture_min == 32.5
    assert restored.soil_moisture_max == 54.0
