"""Unit tests for EnvironmentStateAssembler.

These tests are pure: ``get_state`` is a lambda returning fake ``State``-like
objects, and growspace/plant access are lambdas. No Home Assistant instance or
coordinator is involved. They pin the sensor-reading logic that moved off
``BayesianEnvironmentSensor``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

from custom_components.growspace_manager.domain.environment_state_assembler import (
    EnvironmentStateAssembler,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.util import dt as dt_util


@dataclass
class FakeState:
    """Minimal stand-in for homeassistant.core.State."""

    state: str
    domain: str = "sensor"
    attributes: dict[str, object] = field(default_factory=dict)


def make_get_state(states: dict[str, FakeState]):
    """Build a ``get_state`` callable backed by a dict."""
    return lambda entity_id: states.get(entity_id)


def make_growspace(
    growspace_id: str = "gs1",
    growspace_type: GrowspaceType = GrowspaceType.FLOWER,
    env_config: EnvironmentConfig | None = None,
) -> Growspace:
    """Build a Growspace with the given type and config."""
    return Growspace(
        id=growspace_id,
        name="Test",
        growspace_type=growspace_type,
        environment_config=env_config or EnvironmentConfig(),
    )


def build_assembler(
    env_config: EnvironmentConfig,
    states: dict[str, FakeState] | None = None,
    growspace: Growspace | None = None,
    plants: list[Plant] | None = None,
) -> EnvironmentStateAssembler:
    """Construct an assembler wired with in-memory lambdas."""
    gs = growspace if growspace is not None else make_growspace(env_config=env_config)
    return EnvironmentStateAssembler(
        growspace_id="gs1",
        env_config=env_config,
        get_state=make_get_state(states or {}),
        get_growspace=lambda gid: gs,
        get_plants=lambda gid: plants or [],
    )


# -- aggregation / unavailable skipping ------------------------------------


def test_aggregated_value_averages_valid_readings() -> None:
    """Multiple temperature sensors are averaged."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.t1",
        temperature_sensors=["sensor.t2"],
        humidity_sensor="sensor.h",
        vpd_sensor="sensor.v",
    )
    states = {
        "sensor.t1": FakeState("20"),
        "sensor.t2": FakeState("30"),
        "sensor.h": FakeState("50"),
        "sensor.v": FakeState("1.0"),
    }
    result = build_assembler(config, states).assemble()
    assert result.state.temp == pytest.approx(25.0)
    assert result.observations["temperature"] == pytest.approx(25.0)


def test_singular_shadow_of_a_plural_list_is_counted_once() -> None:
    """The shadow repeats the head of its list; averaging both would skew it.

    This is the shape the Environment Patch actually writes: configuring
    ``temperature_sensors`` re-derives ``temperature_sensor`` from its head.
    """
    config = EnvironmentConfig(
        temperature_sensor="sensor.t1",
        temperature_sensors=["sensor.t1", "sensor.t2"],
    )
    states = {"sensor.t1": FakeState("20"), "sensor.t2": FakeState("30")}

    result = build_assembler(config, states).assemble()

    assert result.state.temp == pytest.approx(25.0)
    assert result.observations["temperature"] == pytest.approx(25.0)


def test_unavailable_and_unknown_readings_are_skipped() -> None:
    """Unavailable/unknown/non-numeric sensors do not count toward the average."""
    config = EnvironmentConfig(
        temperature_sensors=["sensor.t1", "sensor.t2", "sensor.t3", "sensor.t4"],
    )
    states = {
        "sensor.t1": FakeState("20"),
        "sensor.t2": FakeState(STATE_UNAVAILABLE),
        "sensor.t3": FakeState(STATE_UNKNOWN),
        "sensor.t4": FakeState("not-a-number"),
    }
    result = build_assembler(config, states).assemble()
    assert result.state.temp == pytest.approx(20.0)


def test_aggregated_value_all_invalid_yields_none() -> None:
    """Non-empty sensor list with no valid readings averages to None."""
    config = EnvironmentConfig(temperature_sensors=["sensor.t1", "sensor.t2"])
    states = {
        "sensor.t1": FakeState(STATE_UNAVAILABLE),
        "sensor.t2": FakeState(STATE_UNKNOWN),
    }
    assert build_assembler(config, states).assemble().state.temp is None


def test_missing_sensors_yield_none() -> None:
    """An empty config produces None readings, not errors."""
    result = build_assembler(EnvironmentConfig()).assemble()
    assert result.state.temp is None
    assert result.state.humidity is None
    assert result.state.vpd is None
    assert result.state.co2 is None


# -- VPD fallback + LST zeroing --------------------------------------------


def test_vpd_fallback_calculated_when_no_sensor() -> None:
    """VPD is computed from temp+humidity using lst_offset when no VPD sensor."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.t",
        humidity_sensor="sensor.h",
        lst_offset=-2.0,
    )
    states = {"sensor.t": FakeState("25"), "sensor.h": FakeState("60")}
    result = build_assembler(config, states).assemble()
    assert result.state.vpd is not None
    assert result.observations["lst_offset"] == pytest.approx(-2.0)


def test_vpd_sensor_takes_precedence_over_fallback() -> None:
    """A configured VPD sensor is used directly; no calculation occurs."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.t",
        humidity_sensor="sensor.h",
        vpd_sensor="sensor.v",
    )
    states = {
        "sensor.t": FakeState("25"),
        "sensor.h": FakeState("60"),
        "sensor.v": FakeState("1.23"),
    }
    result = build_assembler(config, states).assemble()
    assert result.state.vpd == pytest.approx(1.23)


@pytest.mark.parametrize("gs_type", [GrowspaceType.DRY, GrowspaceType.CURE])
def test_lst_offset_zeroed_for_dry_and_cure(gs_type: GrowspaceType) -> None:
    """DRY/CURE growspaces force lst_offset to 0 for VPD fallback."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.t",
        humidity_sensor="sensor.h",
        lst_offset=-2.0,
    )
    states = {"sensor.t": FakeState("25"), "sensor.h": FakeState("60")}
    growspace = make_growspace(growspace_type=gs_type, env_config=config)
    result = build_assembler(config, states, growspace=growspace).assemble()
    assert result.observations["lst_offset"] == pytest.approx(0.0)


# -- device-state logic: AND / OR / max ------------------------------------


def test_fan_all_off_and_logic() -> None:
    """fan_off is True only when every valid fan is off."""
    config = EnvironmentConfig(circulation_fan_entities=["switch.f1", "switch.f2"])

    one_on = {
        "switch.f1": FakeState("on", "switch"),
        "switch.f2": FakeState("off", "switch"),
    }
    assert build_assembler(config, one_on).assemble().state.fan_off is False

    all_off = {
        "switch.f1": FakeState("off", "switch"),
        "switch.f2": FakeState("off", "switch"),
    }
    assert build_assembler(config, all_off).assemble().state.fan_off is True

    unavail = {
        "switch.f1": FakeState(STATE_UNAVAILABLE, "switch"),
        "switch.f2": FakeState(STATE_UNAVAILABLE, "switch"),
    }
    assert build_assembler(config, unavail).assemble().state.fan_off is None


def test_fan_off_none_when_no_entities() -> None:
    """No fan entities -> fan_off is None."""
    assert build_assembler(EnvironmentConfig()).assemble().state.fan_off is None


def test_dehumidifier_any_on_or_logic() -> None:
    """dehumidifier_on is True when any valid entity is on."""
    config = EnvironmentConfig(dehumidifier_entities=["switch.d1", "switch.d2"])

    one_on = {
        "switch.d1": FakeState("on", "switch"),
        "switch.d2": FakeState("off", "switch"),
    }
    assert build_assembler(config, one_on).assemble().state.dehumidifier_on is True

    all_off = {
        "switch.d1": FakeState("off", "switch"),
        "switch.d2": FakeState("off", "switch"),
    }
    assert build_assembler(config, all_off).assemble().state.dehumidifier_on is False

    unavail = {
        "switch.d1": FakeState(STATE_UNAVAILABLE, "switch"),
        "switch.d2": FakeState(STATE_UNKNOWN, "switch"),
    }
    assert build_assembler(config, unavail).assemble().state.dehumidifier_on is None


def test_humidifier_any_on_or_logic_and_value() -> None:
    """humidifier_on (OR) and humidifier_value (max) are both reported."""
    config = EnvironmentConfig(humidifier_entities=["switch.h1", "switch.h2"])

    states = {
        "switch.h1": FakeState("on", "switch"),
        "switch.h2": FakeState("off", "switch"),
    }
    result = build_assembler(config, states).assemble()
    assert result.state.humidifier_on is True
    # Non-numeric on/off states yield no max value.
    assert result.state.humidifier_value is None


def test_exhaust_max_value() -> None:
    """exhaust_value is the maximum numeric reading across entities."""
    config = EnvironmentConfig(exhaust_fan_entities=["sensor.e1", "sensor.e2"])

    states = {"sensor.e1": FakeState("25.0"), "sensor.e2": FakeState("45.0")}
    assert build_assembler(
        config, states
    ).assemble().state.exhaust_value == pytest.approx(45.0)

    partial = {
        "sensor.e1": FakeState(STATE_UNAVAILABLE),
        "sensor.e2": FakeState("15.0"),
    }
    assert build_assembler(
        config, partial
    ).assemble().state.exhaust_value == pytest.approx(15.0)

    none_valid = {
        "sensor.e1": FakeState(STATE_UNAVAILABLE),
        "sensor.e2": FakeState(STATE_UNAVAILABLE),
    }
    assert build_assembler(config, none_valid).assemble().state.exhaust_value is None

    assert build_assembler(EnvironmentConfig()).assemble().state.exhaust_value is None


# -- light sensor: numeric vs binary domain --------------------------------


def test_light_numeric_sensor_domain_on_when_positive() -> None:
    """A numeric ``sensor.`` light entity is on when its value is greater than 0."""
    config = EnvironmentConfig(light_sensors=["sensor.power"])

    on = {"sensor.power": FakeState("5.0", "sensor")}
    assert build_assembler(config, on).assemble().state.is_lights_on is True

    off = {"sensor.power": FakeState("0", "sensor")}
    assert build_assembler(config, off).assemble().state.is_lights_on is False


def test_light_binary_sensor_domain_on_when_state_on() -> None:
    """A non-sensor light entity is on when its state is the string ``on``."""
    config = EnvironmentConfig(light_sensors=["light.grow"])

    on = {"light.grow": FakeState("on", "light")}
    assert build_assembler(config, on).assemble().state.is_lights_on is True

    off = {"light.grow": FakeState("off", "light")}
    assert build_assembler(config, off).assemble().state.is_lights_on is False


def test_light_unavailable_is_invalid() -> None:
    """Unavailable light sensors are treated as invalid -> None."""
    config = EnvironmentConfig(light_sensors=["light.grow"])
    states = {"light.grow": FakeState(STATE_UNAVAILABLE, "light")}
    assert build_assembler(config, states).assemble().state.is_lights_on is None


def test_light_none_when_no_sensors() -> None:
    """No light sensors -> is_lights_on is None."""
    assert build_assembler(EnvironmentConfig()).assemble().state.is_lights_on is None


# -- stage-day computation --------------------------------------------------


def _plant(**starts: str) -> Plant:
    """Build a Plant with the given *_start dates."""
    return Plant(plant_id="p1", growspace_id="gs1", **starts)


def test_stage_days_max_across_plants() -> None:
    """Stage days take the maximum days-since across plants with that start."""
    # Anchor to the same clock production uses (UTC via HA's dt util); using the
    # system-local date.today() makes the day count off-by-one near the UTC
    # midnight boundary.
    today = dt_util.now().date()
    veg = (today - timedelta(days=10)).isoformat()
    veg_older = (today - timedelta(days=25)).isoformat()
    config = EnvironmentConfig()
    plants = [_plant(veg_start=veg), _plant(veg_start=veg_older)]
    result = build_assembler(config, plants=plants).assemble()
    assert result.state.veg_days == 25
    # Stages without any plant start fall back to the -1 sentinel.
    assert result.state.flower_days == -1


def test_stage_days_empty_growspace_sentinels() -> None:
    """An empty growspace yields -1 sentinels for all stages."""
    result = build_assembler(EnvironmentConfig(), plants=[]).assemble()
    assert result.state.veg_days == -1
    assert result.state.flower_days == -1
    assert result.state.seedling_days == -1
    assert result.state.clone_days == -1


@pytest.mark.parametrize("gs_type", [GrowspaceType.DRY, GrowspaceType.CURE])
def test_stage_days_dry_cure_sentinels(gs_type: GrowspaceType) -> None:
    """DRY/CURE growspaces report -1 stage sentinels regardless of plants."""
    today = date.today()
    plants = [_plant(veg_start=(today - timedelta(days=10)).isoformat())]
    growspace = make_growspace(growspace_type=gs_type)
    result = build_assembler(
        EnvironmentConfig(), growspace=growspace, plants=plants
    ).assemble()
    assert result.state.veg_days == -1


# -- config refresh / no-growspace -----------------------------------------


def test_no_growspace_returns_state_from_initial_config() -> None:
    """When get_growspace returns None, the initial config is still read."""
    config = EnvironmentConfig(temperature_sensor="sensor.t")
    states = {"sensor.t": FakeState("21")}
    assembler = EnvironmentStateAssembler(
        growspace_id="gs1",
        env_config=config,
        get_state=make_get_state(states),
        get_growspace=lambda gid: None,
        get_plants=lambda gid: [],
    )
    result = assembler.assemble()
    assert result.state.temp == pytest.approx(21.0)


def test_config_refreshed_from_growspace_each_assemble() -> None:
    """assemble() picks up the growspace's latest environment_config."""
    initial = EnvironmentConfig(temperature_sensor="sensor.old")
    updated = EnvironmentConfig(temperature_sensor="sensor.new")
    growspace = make_growspace(env_config=updated)
    states = {"sensor.old": FakeState("10"), "sensor.new": FakeState("30")}
    assembler = EnvironmentStateAssembler(
        growspace_id="gs1",
        env_config=initial,
        get_state=make_get_state(states),
        get_growspace=lambda gid: growspace,
        get_plants=lambda gid: [],
    )
    result = assembler.assemble()
    assert result.state.temp == pytest.approx(30.0)
    assert assembler.env_config is updated


def test_state_and_observations_share_one_read() -> None:
    """The state object and observation dict agree field-for-field."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.t",
        humidity_sensor="sensor.h",
        co2_sensor="sensor.co2",
        soil_moisture_sensor="sensor.soil",
    )
    states = {
        "sensor.t": FakeState("22"),
        "sensor.h": FakeState("55"),
        "sensor.co2": FakeState("800"),
        "sensor.soil": FakeState("40"),
    }
    result = build_assembler(config, states).assemble()
    assert result.observations["temperature"] == result.state.temp
    assert result.observations["humidity"] == result.state.humidity
    assert result.observations["co2"] == result.state.co2
    assert result.observations["soil_moisture"] == result.state.soil_moisture


# -- soil moisture unit compatibility --------------------------------------


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        pytest.param("%", 42.0, id="percentage-participates"),
        pytest.param(None, 42.0, id="legacy-no-unit-participates"),
        pytest.param("°C", None, id="temperature-excluded"),
        pytest.param("m³/m³", None, id="volumetric-ratio-excluded"),
    ],
)
def test_soil_moisture_excluded_for_non_percentage_units(
    unit: str | None, expected: float | None
) -> None:
    """Only percentage and unit-less sensors reach moisture classification."""
    config = EnvironmentConfig(soil_moisture_sensor="sensor.moisture")
    attributes: dict[str, object] = (
        {} if unit is None else {"unit_of_measurement": unit}
    )
    states = {"sensor.moisture": FakeState("42.0", attributes=attributes)}

    result = build_assembler(config, states).assemble()

    assert result.state.soil_moisture == expected
    assert result.observations["soil_moisture"] == expected


def test_soil_moisture_unavailable_reading_yields_none() -> None:
    """An unavailable sensor produces no reading to classify."""
    config = EnvironmentConfig(soil_moisture_sensor="sensor.moisture")
    states = {
        "sensor.moisture": FakeState(
            STATE_UNAVAILABLE, attributes={"unit_of_measurement": "%"}
        )
    }
    assert build_assembler(config, states).assemble().state.soil_moisture is None
