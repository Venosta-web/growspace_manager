"""Utility functions for date parsing, formatting, and calculations in growspace_manager."""

from __future__ import annotations

from datetime import datetime
import math
from typing import TYPE_CHECKING

from homeassistant.util.dt import now

from .bayesian_constants import ACCLIMATION_END_DAYS, ACCLIMATION_START_DAYS
from .const import DOMAIN
from .domain.date_logic import (
    calculate_days_since as calculate_days_since_logic,
    format_date as format_date_logic,
    parse_date_field,
)
from .domain.stage import (
    DEFAULT_FLOWER_EARLY_DAYS,
    SPECIAL_GROWSPACE_STAGES,
    STAGES_ORDERED,
    TRANSITION_WINDOW,
    BayesianStage,
    PlantStage,
)
from .types import DateInput

if TYPE_CHECKING:
    from .models import Growspace, Plant


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
    """_Returns the first col/row thats free in growspace.

    Args:
        growspace (dict): _description_
        occupied_positions (set[tuple[int, int]]): _description_

    Returns:
        tuple[int, int]: _description_
    """

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


def calculate_stage_transition(
    flower_days: int = 0,
    veg_days: int = 0,
    seedling_days: int = 0,
    clone_days: int = 0,
    dry_days: int = 0,
    cure_days: int = 0,
    mother_days: int = 0,
) -> tuple[BayesianStage, BayesianStage, float]:
    """Calculate the current stage transition and interpolation factor."""
    # Post-harvest stages — no interpolation needed
    if cure_days > 0:
        return BayesianStage.CURE, BayesianStage.CURE, 0.0
    if dry_days > 0:
        return BayesianStage.DRY, BayesianStage.DRY, 0.0

    # Mother plants — perpetual vegetative, no sub-stage interpolation
    if mother_days > 0:
        return BayesianStage.MOTHER, BayesianStage.MOTHER, 0.0

    # Primary progression: Flower takes precedence
    if flower_days > 0:
        b1 = DEFAULT_FLOWER_EARLY_DAYS
        b2 = DEFAULT_FLOWER_EARLY_DAYS + 21

        if flower_days <= b1:
            if flower_days < b1 - TRANSITION_WINDOW:
                return BayesianStage.FLOWER_EARLY, BayesianStage.FLOWER_EARLY, 0.0
            factor = (flower_days - (b1 - TRANSITION_WINDOW)) / TRANSITION_WINDOW
            return (
                BayesianStage.FLOWER_EARLY,
                BayesianStage.FLOWER_MID,
                round(float(factor), 2),
            )

        if flower_days <= b2:
            if flower_days < b2 - TRANSITION_WINDOW:
                return BayesianStage.FLOWER_MID, BayesianStage.FLOWER_MID, 0.0
            factor = (flower_days - (b2 - TRANSITION_WINDOW)) / TRANSITION_WINDOW
            return (
                BayesianStage.FLOWER_MID,
                BayesianStage.FLOWER_LATE,
                round(float(factor), 2),
            )

        return BayesianStage.FLOWER_LATE, BayesianStage.FLOWER_LATE, 0.0

    if veg_days > 0:
        if veg_days < TRANSITION_WINDOW:
            # Transition from seedling/clone standard to veg
            factor = veg_days / TRANSITION_WINDOW
            return (
                BayesianStage.SEEDLING_STANDARD,
                BayesianStage.VEG,
                round(float(factor), 2),
            )
        return BayesianStage.VEG, BayesianStage.VEG, 0.0

    if seedling_days > 0:
        ac_start = ACCLIMATION_START_DAYS
        ac_end = ACCLIMATION_END_DAYS
        if seedling_days <= ac_end:
            if seedling_days <= ac_start:
                return BayesianStage.SEEDLING, BayesianStage.SEEDLING, 0.0

            window = ac_end - ac_start
            factor = (seedling_days - ac_start) / window
            return (
                BayesianStage.SEEDLING,
                BayesianStage.SEEDLING_STANDARD,
                round(float(factor), 2),
            )
        return BayesianStage.SEEDLING_STANDARD, BayesianStage.SEEDLING_STANDARD, 0.0

    if clone_days > 0:
        ac_start = ACCLIMATION_START_DAYS
        ac_end = ACCLIMATION_END_DAYS
        if clone_days <= ac_end:
            if clone_days <= ac_start:
                return BayesianStage.CLONE, BayesianStage.CLONE, 0.0

            window = ac_end - ac_start
            factor = (clone_days - ac_start) / window
            return (
                BayesianStage.CLONE,
                BayesianStage.CLONE_STANDARD,
                round(float(factor), 2),
            )
        return BayesianStage.CLONE_STANDARD, BayesianStage.CLONE_STANDARD, 0.0

    return BayesianStage.VEG, BayesianStage.VEG, 0.0


def interpolate_value(val_a: float, val_b: float, factor: float) -> float:
    """Linearly interpolate between two values based on a factor."""
    if factor <= 0:
        return val_a
    if factor >= 1:
        return val_b
    return round(float(val_a) + (float(val_b) - float(val_a)) * float(factor), 3)


# =========================================================================
# UNIQUE ID GENERATORS
# =========================================================================


def generate_vpd_sensor_unique_id(growspace_id: str, index: int | None = None) -> str:
    """Generate a consistent unique ID for a calculated VPD sensor."""
    suffix = f"_{index}" if index is not None else ""
    return f"{DOMAIN}_{growspace_id}_calculated_vpd{suffix}"


def generate_growspace_overview_unique_id(growspace_id: str) -> str:
    """Generate a consistent unique ID for a growspace overview sensor."""
    return f"{DOMAIN}_{growspace_id}"
