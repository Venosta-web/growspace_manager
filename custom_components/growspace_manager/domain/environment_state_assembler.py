"""Assemble an EnvironmentState from raw Home Assistant sensor states.

The assembler concentrates the ~250 lines of ``_determine_*`` / ``_get_*``
reading logic that used to live on ``BayesianEnvironmentSensor``.  It performs a
single pass over the configured sensor entities and produces both the
structured :class:`EnvironmentState` consumed by the evaluator strategies and
the flat observation dict surfaced as the sensor's ``ATTR_OBSERVATIONS``
attribute.  Both come from the same read pass so they can never disagree.

It is pure with respect to Home Assistant: no writes, no manager calls, no
entity state.  Dependencies are injected as callables, so it can be unit-tested
with lambdas returning fake ``State`` objects.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)

from ..models import (
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    GrowspaceType,
    Plant,
)
from ..utils import VPDCalculator
from .current_stage import resolve_stage_and_age
from .moisture_band import is_percentage_unit

if TYPE_CHECKING:
    from homeassistant.core import State


@dataclass(frozen=True, slots=True)
class AssembledEnvironment:
    """Result of a single assembly pass.

    ``state`` and ``observations`` are derived from the same read of Home
    Assistant state, so callers can use both without risk of divergence.
    """

    state: EnvironmentState
    observations: dict[str, Any]


def _sensor_ids(shadow: str | None, canonical: list[str]) -> list[str]:
    """Merge a legacy singular field with its plural, counting each sensor once.

    The Environment Patch re-derives the singular shadow from the head of the
    plural list (ADR-0026), so the two overlap by construction: averaging both
    would weight the first sensor double and pull every multi-sensor reading
    toward it. Mirrors ``utils.read_environment_vpd``.
    """

    return list(dict.fromkeys(s for s in (shadow, *canonical) if s is not None))


class EnvironmentStateAssembler:
    """Builds an :class:`EnvironmentState` for one growspace from HA states."""

    def __init__(
        self,
        growspace_id: str,
        env_config: EnvironmentConfig,
        get_state: Callable[[str], State | None],
        get_growspace: Callable[[str], Growspace | None],
        get_plants: Callable[[str], list[Plant]],
    ) -> None:
        """Initialize the assembler with injected data-access callables."""
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._get_state = get_state
        self._get_growspace = get_growspace
        self._get_plants = get_plants

    def assemble(self) -> AssembledEnvironment:
        """Read sensor states once and return the state plus observation dict."""
        # Always refresh config from the coordinator so config edits flow through.
        growspace = self._get_growspace(self.growspace_id)
        if growspace and growspace.environment_config:
            self.env_config = growspace.environment_config

        config = self.env_config

        temp = self._aggregated_value(
            _sensor_ids(config.temperature_sensor, config.temperature_sensors)
        )
        humidity = self._aggregated_value(
            _sensor_ids(config.humidity_sensor, config.humidity_sensors)
        )
        vpd = self._aggregated_value(_sensor_ids(config.vpd_sensor, config.vpd_sensors))

        # DRY/CURE spaces ignore the leaf-surface offset; there is no canopy.
        active_lst_offset = config.lst_offset
        if growspace and growspace.growspace_type in (
            GrowspaceType.DRY,
            GrowspaceType.CURE,
        ):
            active_lst_offset = 0.0

        # Fallback: calculate VPD when no sensor exists but temp/humidity do.
        if vpd is None and temp is not None and humidity is not None:
            vpd = VPDCalculator.calculate_vpd_with_lst_offset(
                temp, humidity, active_lst_offset
            )

        co2 = self._sensor_value(config.co2_sensor)
        soil_moisture = self._moisture_value(config.soil_moisture_sensor)
        substrate_temp = self._aggregated_value(config.substrate_temperature_sensors)

        # ``.get(..., 0)`` mirrors the historical default and tolerates the
        # partial dicts that white-box tests patch ``_growth_stage_info`` with.
        stage_info = self._growth_stage_info(growspace)
        veg_days = stage_info.get("veg_days", 0)
        flower_days = stage_info.get("flower_days", 0)
        seedling_days = stage_info.get("seedling_days", 0)
        clone_days = stage_info.get("clone_days", 0)

        is_lights_on = self._any_light_on(config.light_sensors)
        fan_off = self._all_off(config.circulation_fan_entities)
        dehumidifier_on = self._any_on(config.dehumidifier_entities)
        exhaust_value = self._max_value(config.exhaust_fan_entities)
        humidifier_value = self._max_value(config.humidifier_entities)
        humidifier_on = self._any_on(config.humidifier_entities)

        observations: dict[str, Any] = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "soil_moisture": soil_moisture,
            "substrate_temp": substrate_temp,
            "lst_offset": active_lst_offset,
            "veg_days": veg_days,
            "flower_days": flower_days,
            "seedling_days": seedling_days,
            "clone_days": clone_days,
            "is_lights_on": is_lights_on,
            "fan_off": fan_off,
            "dehumidifier_on": dehumidifier_on,
            "exhaust_value": exhaust_value,
            "humidifier_value": humidifier_value,
            "humidifier_on": humidifier_on,
        }

        state = EnvironmentState(
            temp=temp,
            humidity=humidity,
            vpd=vpd,
            co2=co2,
            veg_days=veg_days,
            flower_days=flower_days,
            seedling_days=seedling_days,
            clone_days=clone_days,
            is_lights_on=is_lights_on,
            fan_off=fan_off,
            dehumidifier_on=dehumidifier_on,
            exhaust_value=exhaust_value,
            humidifier_value=humidifier_value,
            humidifier_on=humidifier_on,
            soil_moisture=soil_moisture,
            substrate_temp=substrate_temp,
        )

        return AssembledEnvironment(state=state, observations=observations)

    # -- raw value helpers ---------------------------------------------------

    def _sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely read a numeric value from a sensor's state."""
        if not sensor_id:
            return None
        state = self._get_state(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError, TypeError:
            return None

    def _moisture_value(self, sensor_id: str | None) -> float | None:
        """Read a soil-moisture sensor, excluding non-percentage units.

        The Acceptable Moisture Band interprets readings as percentages, so a
        sensor explicitly reporting some other unit contributes nothing. A
        sensor with no unit metadata keeps the legacy 0–100 assumption.
        """
        if not sensor_id:
            return None
        value = self._sensor_value(sensor_id)
        if value is None:
            return None
        state = self._get_state(sensor_id)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if state else None
        return value if is_percentage_unit(unit) else None

    def _aggregated_value(self, sensor_ids: list[str]) -> float | None:
        """Average the valid numeric readings from a list of sensor ids."""
        if not sensor_ids:
            return None
        values = [
            value
            for sensor_id in sensor_ids
            if (value := self._sensor_value(sensor_id)) is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)

    def _max_value(self, entities: list[str]) -> float | None:
        """Return the maximum valid numeric reading from a list of entities."""
        if not entities:
            return None
        values = [
            value
            for entity in entities
            if (value := self._sensor_value(entity)) is not None
        ]
        return max(values) if values else None

    # -- device-state helpers ------------------------------------------------

    def _is_light_on(self, sensor_id: str) -> tuple[bool, bool]:
        """Return ``(is_on, is_valid)`` for a single light sensor.

        Numeric ``sensor.`` entities are on when their value is greater than
        zero; other domains are on when their state is ``"on"``.
        """
        state = self._get_state(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False, False
        if state.domain == "sensor":
            value = self._sensor_value(sensor_id)
            return value is not None and value > 0, value is not None
        return state.state == "on", True

    def _any_light_on(self, sensor_ids: list[str]) -> bool | None:
        """OR-aggregate light sensors; ``None`` when none has a valid reading."""
        if not sensor_ids:
            return None
        any_on = False
        any_valid = False
        for sensor_id in sensor_ids:
            is_on, valid = self._is_light_on(sensor_id)
            if valid:
                any_valid = True
                if is_on:
                    any_on = True
        return any_on if any_valid else None

    def _all_off(self, entities: list[str]) -> bool | None:
        """AND-aggregate: all valid entities off; ``None`` when none is valid."""
        if not entities:
            return None
        all_off = True
        any_valid = False
        for entity in entities:
            state = self._get_state(entity)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                if state.state != "off":
                    all_off = False
        return all_off if any_valid else None

    def _any_on(self, entities: list[str]) -> bool | None:
        """OR-aggregate: any valid entity on; ``None`` when none is valid."""
        if not entities:
            return None
        any_on = False
        any_valid = False
        for entity in entities:
            state = self._get_state(entity)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                if state.state == "on":
                    any_on = True
        return any_on if any_valid else None

    # -- stage-day helper ----------------------------------------------------

    def _growth_stage_info(self, growspace: Growspace | None) -> dict[str, int]:
        """Return per-stage day counts; ``-1`` sentinels for dry/cure/empty."""
        empty = {
            "veg_days": -1,
            "flower_days": -1,
            "seedling_days": -1,
            "clone_days": -1,
        }
        if growspace and growspace.growspace_type in (
            GrowspaceType.DRY,
            GrowspaceType.CURE,
        ):
            return empty

        plants = self._get_plants(self.growspace_id)
        if not plants:
            return empty

        stage_days = dict(empty)
        for plant in plants:
            stage, age = resolve_stage_and_age(plant)
            key = f"{stage}_days"
            if key in stage_days:
                stage_days[key] = max(stage_days[key], age)
        return stage_days
