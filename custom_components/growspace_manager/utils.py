"""Utility functions for date parsing, formatting, and calculations in growspace_manager."""

from __future__ import annotations

from datetime import datetime
import math
from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import now

from .const import DOMAIN
from .domain.date_logic import (
    calculate_days_since as calculate_days_since_logic,
    format_date as format_date_logic,
    parse_date_field,
)
from .domain.stage import (
    SPECIAL_GROWSPACE_STAGES,
    STAGES_ORDERED,
    BayesianStage,
    PlantStage,
)
from .integration_types import DateInput

if TYPE_CHECKING:
    from .models import EnvironmentConfig, Growspace, GrowspaceType, Plant


# =========================================================================
# DATE AND STAGE PROXIES (Logic in .domain.date_logic)
# =========================================================================


def parse_date_field_v2(date_value: DateInput) -> datetime | None:
    """Parse various date inputs into a timezone-aware datetime object."""
    return parse_date_field(date_value)


def calculate_days_since(
    start_date: DateInput, end_date: DateInput | None = None
) -> int:
    """Calculate the number of days since a start date."""
    return calculate_days_since_logic(start_date, end_date)


def format_date(date_value: DateInput) -> str | None:
    """Format a date for display."""
    return format_date_logic(date_value)


def days_to_week(days: int) -> int:
    """Convert a number of days into a week number (1-indexed).

    Args:
        days: The number of days.

    Returns:
        The corresponding week number.
    """
    if days <= 0:
        return 0
    return (days - 1) // 7 + 1


# =========================================================================
# GROWSPACE AND POSITIONING
# =========================================================================


def find_first_free_position(
    growspace: Growspace, occupied_positions: set[tuple[int, int]]
) -> tuple[int | None, int | None]:
    """Return the first (row, col) position not in occupied_positions, or the last cell if all are taken."""

    total_rows = int(growspace.rows)
    total_cols = int(growspace.plants_per_row)
    for r in range(1, total_rows + 1):
        for c in range(1, total_cols + 1):
            if (r, c) not in occupied_positions:
                return r, c

    if total_rows > 0 and total_cols > 0:
        return total_rows, total_cols
    return None, None


def generate_growspace_grid(
    rows: int, cols: int, plant_positions: list[Plant]
) -> list[list[str | None]]:
    """Generate a grid representing the growspace with plant IDs."""
    grid: list[list[str | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for plant in plant_positions:
        # Avoid out-of-bounds if data is corrupted
        r, c = int(plant.row) - 1, int(plant.col) - 1
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = plant.plant_id
    return grid


# =========================================================================
# VPD CALCULATIONS
# =========================================================================


class VPDCalculator:
    """A utility class for calculating Vapor Pressure Deficit (VPD)."""

    @staticmethod
    def _calculate_svp(temperature_c: float) -> float:
        """Calculate Saturation Vapor Pressure (SVP) using the Magnus formula.

        Args:
            temperature_c: Temperature in degrees Celsius.

        Returns:
            SVP in kilopascals (kPa).
        """
        return 0.61094 * math.exp((17.625 * temperature_c) / (243.04 + temperature_c))

    @staticmethod
    def calculate_vpd(temperature_c: float, humidity_rh: float) -> float | None:
        """Calculate Vapor Pressure Deficit (VPD) in kPa.

        Args:
            temperature_c: Temperature in degrees Celsius.
            humidity_rh: Relative humidity in percent (e.g., 65.5).

        Returns:
            The calculated VPD in kilopascals (kPa), or None if inputs are invalid.
        """
        if not isinstance(temperature_c, (int, float)) or not isinstance(
            humidity_rh, (int, float)
        ):
            return None

        svp = VPDCalculator._calculate_svp(temperature_c)
        avp = svp * (humidity_rh / 100)
        vpd = svp - avp
        return round(vpd, 2)

    @staticmethod
    def calculate_vpd_with_lst_offset(
        air_temperature_c: float, humidity_rh: float, lst_offset: float = -2.0
    ) -> float | None:
        """Calculate Vapor Pressure Deficit (VPD) with Leaf Surface Temperature offset.

        Args:
            air_temperature_c: Air temperature in degrees Celsius.
            humidity_rh: Relative humidity in percent (e.g., 65.5).
            lst_offset: Temperature offset for leaf surface (default: -2.0°C).

        Returns:
            The calculated VPD in kilopascals (kPa), or None if inputs are invalid.
        """
        if (
            not isinstance(air_temperature_c, (int, float))
            or not isinstance(humidity_rh, (int, float))
            or not isinstance(lst_offset, (int, float))
        ):
            return None

        leaf_temperature_c = air_temperature_c + lst_offset
        leaf_svp = VPDCalculator._calculate_svp(leaf_temperature_c)
        air_svp = VPDCalculator._calculate_svp(air_temperature_c)
        air_avp = air_svp * (humidity_rh / 100)

        vpd = leaf_svp - air_avp
        return round(vpd, 2)


# =========================================================================
# STAGE TRANSITION AND INTERPOLATION logic
# =========================================================================


def calculate_plant_stage(plant: Plant) -> str:
    """Determine the current growth stage of the plant.

    The stage is determined by a hierarchy: first by the special growspace
    it's in, then by the most recent start date, and finally by the
    explicitly set stage property.

    Args:
        plant: The Plant object to analyze.

    Returns:
        The determined stage as a string.
    """
    if stage := _get_stage_from_growspace(plant):
        return stage

    current_time = now()
    # Check in reverse order (STAGES_ORDERED is ascending, so we reverse)
    for stage_def in reversed(STAGES_ORDERED):
        date_val = getattr(plant, stage_def.start_field, None)
        if (dt := parse_date_field(date_val)) and dt <= current_time:
            return stage_def.id.value

    if stage := _get_stage_fallback(plant):
        return stage

    return PlantStage.SEEDLING


def _get_stage_fallback(plant: Plant) -> str | None:
    """Fallback to the explicitly set stage if it's valid."""
    valid_stages = {stage.value for stage in PlantStage}
    if plant.stage in valid_stages:
        return plant.stage
    return None


def _get_stage_from_growspace(plant: Plant) -> str | None:
    """Check if the plant is in a special growspace that dictates its stage."""
    if not plant.growspace_id:
        return None

    stage_id = plant.growspace_id.lower()
    if stage_id in SPECIAL_GROWSPACE_STAGES:
        return stage_id

    return None



def interpolate_value(val_a: float, val_b: float, factor: float) -> float:
    """Linearly interpolate between two values based on a factor."""
    if factor <= 0:
        return val_a
    if factor >= 1:
        return val_b
    return round(float(val_a) + (float(val_b) - float(val_a)) * float(factor), 3)


# =========================================================================
# HA STATE MACHINE SENSOR READERS
# =========================================================================


def read_sensor_value(hass: HomeAssistant, sensor_id: str | None) -> float | None:
    """Safely read a numeric value from an HA sensor entity."""
    if not sensor_id:
        return None
    state = hass.states.get(sensor_id)
    if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


def is_light_sensor_on(hass: HomeAssistant, sensor_id: str) -> tuple[bool, bool]:
    """Return (is_on, is_valid) for a light sensor.

    Numeric `sensor.` domain entities (e.g. power-consumption sensors) are
    considered on when their value is greater than zero. Binary-style entities
    (binary_sensor, switch, etc.) are considered on when their state is "on".
    Unavailable/unknown/missing entities are reported as invalid.
    """
    state = hass.states.get(sensor_id)
    if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return False, False

    if state.domain == "sensor":
        value = read_sensor_value(hass, sensor_id)
        return value is not None and value > 0, value is not None

    return state.state == "on", True


def any_light_sensor_on(hass: HomeAssistant, sensor_ids: list[str]) -> bool | None:
    """OR-aggregate light sensor states; None when no sensor has a valid reading."""
    any_on = False
    any_valid = False
    for sensor_id in sensor_ids:
        is_on, valid = is_light_sensor_on(hass, sensor_id)
        if valid:
            any_valid = True
            if is_on:
                any_on = True
    return any_on if any_valid else None


def read_aggregated_sensor_value(
    hass: HomeAssistant, sensor_ids: list[str]
) -> float | None:
    """Read the average value from a list of HA sensor entity IDs."""
    values = [read_sensor_value(hass, sid) for sid in sensor_ids]
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else None


def read_environment_vpd(
    hass: HomeAssistant,
    env_config: EnvironmentConfig,
    growspace_type: GrowspaceType | None = None,
) -> float | None:
    """Return the current VPD for a growspace from HA sensor states.

    Prefers a directly configured VPD sensor; falls back to calculation from
    temperature + humidity when none is configured.  DRY/CURE spaces use
    lst_offset=0 because leaf-surface temperature correction is irrelevant
    for post-harvest environments.
    """
    from .models import GrowspaceType as _GrowspaceType  # noqa: PLC0415

    sensor_ids = list(
        dict.fromkeys(
            s
            for s in [env_config.vpd_sensor, *env_config.vpd_sensors]
            if s is not None
        )
    )
    vpd = read_aggregated_sensor_value(hass, sensor_ids)
    if vpd is not None:
        return vpd

    temp = read_aggregated_sensor_value(
        hass,
        list(
            dict.fromkeys(
                s
                for s in [env_config.temperature_sensor, *env_config.temperature_sensors]
                if s is not None
            )
        ),
    )
    humidity = read_aggregated_sensor_value(
        hass,
        list(
            dict.fromkeys(
                s
                for s in [env_config.humidity_sensor, *env_config.humidity_sensors]
                if s is not None
            )
        ),
    )
    if temp is None or humidity is None:
        return None

    lst_offset = (
        0.0
        if growspace_type in (_GrowspaceType.DRY, _GrowspaceType.CURE)
        else env_config.lst_offset
    )
    return VPDCalculator.calculate_vpd_with_lst_offset(temp, humidity, lst_offset)


# =========================================================================
# UNIQUE ID GENERATORS
# =========================================================================


def generate_vpd_sensor_unique_id(growspace_id: str, index: int | None = None) -> str:
    """Generate a consistent unique ID for a calculated VPD sensor."""
    suffix = f"_{index}" if index is not None else ""
    return f"{DOMAIN}_{growspace_id}_calculated_vpd{suffix}"


def generate_subarea_vpd_sensor_unique_id(
    growspace_id: str, subarea_id: str, index: int | None = None
) -> str:
    """Generate a consistent unique ID for a subarea calculated VPD sensor."""
    suffix = f"_{index}" if index is not None else ""
    return f"{DOMAIN}_{growspace_id}_subarea_{subarea_id}_calculated_vpd{suffix}"


def generate_growspace_overview_unique_id(growspace_id: str) -> str:
    """Generate a consistent unique ID for a growspace overview sensor."""
    return f"{DOMAIN}_{growspace_id}"


def strip_markdown_fence(text: str) -> str:
    """Strip a leading ```[lang] / trailing ``` markdown code fence from *text*.

    LLMs commonly wrap JSON output in fences; this normalises the string so
    callers can pass the result directly to ``json.loads``.
    """
    triple_backtick = "`" * 3
    stripped = text.strip()
    if stripped.startswith(triple_backtick):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline:].strip()
        if stripped.endswith(triple_backtick):
            stripped = stripped[:-3].strip()
    return stripped
