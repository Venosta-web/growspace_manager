"""Meter declarations are strict; HA owns kind and unit (ADR-0064)."""

import copy

import pytest

from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatchError,
    apply_environment_patch,
    patch_from_service_call,
)
from custom_components.growspace_manager.domain.flow_meter import (
    FlowMeterError,
    classify_flow_meter,
    parse_flow_meters,
    validate_meter_placements,
)
from custom_components.growspace_manager.models import EnvironmentConfig, FlowMeter
from custom_components.growspace_manager.storage_manager import _migrate_flow_meters


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        "sensor.flow",
        [None],
        [{}],
        [{"entity_id": "sensor.flow", "placement": "supply", "unit": "L"}],
        [{"entity_id": "switch.flow", "placement": "supply"}],
        [{"entity_id": "sensor.", "placement": "supply"}],
        [{"entity_id": None, "placement": "supply"}],
        [{"entity_id": "sensor.flow", "placement": ""}],
        [{"entity_id": "sensor.flow", "placement": 1}],
    ],
)
def test_refuse_malformed_declarations(raw):
    with pytest.raises(FlowMeterError):
        parse_flow_meters(raw)
    with pytest.raises(EnvironmentPatchError):
        patch_from_service_call({"flow_meters": raw})


def test_roundtrip_and_patch_clear():
    meter = FlowMeter("sensor.flow", "default")
    assert meter.to_dict() == {"entity_id": "sensor.flow", "placement": "default"}
    assert parse_flow_meters([meter]) == [meter]
    assert EnvironmentConfig.from_dict({"flow_meters": None}).flow_meters == []
    env = EnvironmentConfig(flow_meters=[meter])
    assert EnvironmentConfig.from_dict(env.to_dict()) == env
    assert apply_environment_patch(
        env, patch_from_service_call({})
    ).config.flow_meters == [meter]
    assert (
        apply_environment_patch(
            env, patch_from_service_call({"flow_meters": []})
        ).config.flow_meters
        == []
    )


@pytest.mark.parametrize("key", ["irrigation_flow_sensor", "irrigation_flow_sensors"])
def test_retired_field_never_promoted_or_hidden_in_bayesian_options(key):
    env = EnvironmentConfig.from_dict(
        {key: ["sensor.old"], "bayesian_options": {key: ["sensor.hidden"]}}
    )
    assert env.flow_meters == []
    assert key not in env.to_dict()
    assert key not in env.bayesian_options
    with pytest.raises(EnvironmentPatchError, match="retired"):
        patch_from_service_call({key: ["sensor.old"]})


@pytest.mark.parametrize("placement", ["supply", "default"])
def test_placement_cardinality(placement):
    with pytest.raises(FlowMeterError, match="At most one"):
        validate_meter_placements(
            [FlowMeter("sensor.a", placement), FlowMeter("sensor.b", placement)],
            {"default"},
        )


def test_unknown_zone_and_coexisting_meters():
    with pytest.raises(FlowMeterError, match="unknown irrigation zone"):
        validate_meter_placements([FlowMeter("sensor.a", "gone")], {"default"})
    validate_meter_placements(
        [FlowMeter("sensor.a", "supply"), FlowMeter("sensor.b", "default")], {"default"}
    )


@pytest.mark.parametrize(
    ("device_class", "state_class", "unit", "kind", "converted"),
    [
        ("water", "total", "L", "cumulative_total", 1),
        ("volume", "total_increasing", "m³", "cumulative_total", 1000),
        ("water", "total_increasing", "gal", "cumulative_total", 3.785411784),
        ("volume", "total", "mL", "cumulative_total", 0.001),
        ("volume_flow_rate", None, "L/min", "rate", 1 / 60),
        ("volume_flow_rate", "measurement", "m³/h", "rate", 1000 / 3600),
        ("volume_flow_rate", "measurement", "gal/min", "rate", 3.785411784 / 60),
    ],
)
def test_classification_and_ha_conversion(
    device_class, state_class, unit, kind, converted
):
    metadata = classify_flow_meter(
        "sensor.flow",
        {
            "device_class": device_class,
            "state_class": state_class,
            "unit_of_measurement": unit,
        },
    )
    assert metadata.kind == kind
    assert metadata.unit == unit
    assert metadata.convert(1) == pytest.approx(converted)


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {
            "device_class": "water",
            "state_class": "measurement",
            "unit_of_measurement": "L",
        },
        {"device_class": "volume", "unit_of_measurement": "L"},
        {
            "device_class": "energy",
            "state_class": "total",
            "unit_of_measurement": "kWh",
        },
        {
            "device_class": "water",
            "state_class": "total",
            "unit_of_measurement": "pulses",
        },
        {"device_class": "volume_flow_rate", "unit_of_measurement": "L"},
        {"device_class": "volume_flow_rate", "unit_of_measurement": None},
    ],
)
def test_metadata_refusal_names_entity_and_fix(attributes):
    with pytest.raises(FlowMeterError) as error:
        classify_flow_meter("sensor.bad", attributes)
    for text in ("sensor.bad", "template", "utility_meter", "customize"):
        assert text in str(error.value)


def test_retirement_logs_entries_once_and_preserves_new_meters(caplog):
    meter = {"entity_id": "sensor.new", "placement": "supply"}
    data = {
        "growspaces": {
            "tent": {
                "environment_config": {
                    "irrigation_flow_sensors": ["sensor.old"],
                    "flow_meters": [meter],
                },
                "subareas": [
                    "malformed retained entry",
                    {
                        "environment_config": {
                            "irrigation_flow_sensor": "sensor.subarea"
                        }
                    },
                ],
            },
            "broken": "not a growspace",
            "empty": {"environment_config": None},
        }
    }
    original = copy.deepcopy(data)
    migrated = _migrate_flow_meters(data)
    assert data == original
    assert migrated["growspaces"]["tent"]["environment_config"] == {
        "flow_meters": [meter]
    }
    assert migrated["growspaces"]["tent"]["subareas"][1]["environment_config"] == {
        "flow_meters": []
    }
    assert "sensor.old" in caplog.text and "sensor.subarea" in caplog.text
    assert len(caplog.records) == 2
    caplog.clear()
    assert _migrate_flow_meters(migrated) == migrated
    assert not caplog.records
    assert (
        _migrate_flow_meters(
            {
                "growspaces": {
                    "tent": {
                        "environment_config": {
                            "irrigation_flow_sensors": [],
                            "bayesian_options": None,
                        }
                    }
                }
            }
        )["growspaces"]["tent"]["environment_config"]["flow_meters"]
        == []
    )
