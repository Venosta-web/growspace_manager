"""Utility functions for date parsing, formatting, and calculations in growspace_manager."""

from __future__ import annotations

from datetime import date, datetime
import math
from typing import TYPE_CHECKING

from dateutil import parser

from homeassistant.util.dt import as_local, now

from .const import DOMAIN, PlantStage
from .types import DateInput

if TYPE_CHECKING:
    from .models import Growspace, Plant


def parse_date_field(date_value: DateInput) -> datetime | None:
    """Parse various date inputs into a timezone-aware datetime object."""
    if date_value is None:
        return None

    dt: datetime | None = None

    match date_value:
        case datetime():
            dt = date_value
        case date():
            dt = datetime.combine(date_value, datetime.min.time())
        case str():
            try:
                # Optimization: Try standard library parsing first (significantly faster)
                dt = datetime.fromisoformat(date_value)
            except ValueError:
                try:
                    # Fallback to slower, more robust parser
                    dt = parser.isoparse(date_value)
                except (ValueError, TypeError):
                    return None

    if dt is None:
        return None  # type: ignore[unreachable]

    if dt.tzinfo is None:
        return as_local(dt)  # type: ignore[no-any-return]  # dateutil.parser returns Any
    return dt


def format_date(date_value: DateInput) -> str | None:
    """Format a date input into an ISO string."""
    dt = parse_date_field(date_value)
    if dt is None:
        return None
    return dt.date().isoformat()


def calculate_days_since(
    start_date: DateInput, end_date: DateInput | None = None
) -> int:
    """Returns the number of days from start_date to end_date.

    If end_date is None, uses current time.
    """
    start = parse_date_field(start_date)
    end = parse_date_field(end_date) if end_date else now()
    if start is None or end is None:
        return 0
    return int((end.date() - start.date()).days)


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

    # Return bottom-right if full (as per legacy test expectation)
    if total_rows > 0 and total_cols > 0:
        return total_rows, total_cols
    return None, None


def generate_growspace_grid(
    rows: int, cols: int, plant_positions: list[Plant]
) -> list[list[str | None]]:
    """Generate a grid representing the growspace with plant IDs."""
    grid: list[list[str | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for plant in plant_positions:
        r, c = plant.row - 1, plant.col - 1
        grid[r][c] = plant.plant_id
    return grid


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
        # Validate types specifically for non-static-typed callers
        if not isinstance(temperature_c, (int, float)) or not isinstance(
            humidity_rh, (int, float)
        ):
            return None  # type: ignore[unreachable]

        # Calculate saturation vapor pressure (SVP)
        svp = VPDCalculator._calculate_svp(temperature_c)

        # Calculate actual vapor pressure (AVP)
        avp = svp * (humidity_rh / 100)

        # Calculate VPD
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
        # Validate types specifically for non-static-typed callers
        if (
            not isinstance(air_temperature_c, (int, float))
            or not isinstance(humidity_rh, (int, float))
            or not isinstance(lst_offset, (int, float))
        ):
            return None  # type: ignore[unreachable]

        # Calculate leaf temperature
        leaf_temperature_c = air_temperature_c + lst_offset

        # Calculate SVP at leaf temperature (Leaf SVP) represents the saturated vapor pressure
        # within the leaf stomata.
        leaf_svp = VPDCalculator._calculate_svp(leaf_temperature_c)

        # Calculate SVP at air temperature (Air SVP)
        # Note: While simple VPD uses Air SVP to find AVP, for leaf-to-air VPD
        # we strictly compare Leaf SVP to Air AVP.

        # We need Air SVP only to calculate Air AVP from RH
        air_svp = VPDCalculator._calculate_svp(air_temperature_c)

        # Actual Vapor Pressure of the air (AVP) derived from Air SVP and RH
        air_avp = air_svp * (humidity_rh / 100)

        # Leaf-to-Air VPD = Leaf SVP - Air AVP
        vpd = leaf_svp - air_avp

        # VPD cannot be negative physically (implies condensation/dew point reached on leaf)
        # but returning 0.0 or negative is fine for tracking.
        return round(vpd, 2)


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

    if stage := _get_stage_from_dates(plant):
        return stage

    if stage := _get_stage_fallback(plant):
        return stage

    return PlantStage.SEEDLING


def _get_stage_from_growspace(plant: Plant) -> str | None:
    """Check if the plant is in a special growspace that dictates its stage."""
    # Note: These IDs must match the keys in SPECIAL_GROWSPACES or canonical IDs
    if plant.growspace_id in (
        PlantStage.MOTHER.value,
        PlantStage.CLONE.value,
        PlantStage.DRY.value,
        PlantStage.CURE.value,
    ):
        return plant.growspace_id
    return None


def _get_stage_from_dates(plant: Plant) -> str | None:
    """Determine stage based on start dates, prioritizing the most advanced stage."""
    current_time = now()
    # Check in reverse order of progression (most advanced first)
    dates = [
        (plant.cure_start, PlantStage.CURE),
        (plant.dry_start, PlantStage.DRY),
        (plant.flower_start, PlantStage.FLOWER),
        (plant.veg_start, PlantStage.VEG),
        (plant.clone_start, PlantStage.CLONE),
        (plant.mother_start, PlantStage.MOTHER),
        (plant.seedling_start, PlantStage.SEEDLING),
    ]
    for date_val, stage in dates:
        if (dt := parse_date_field(date_val)) and dt <= current_time:
            return stage
    return None


def _get_stage_fallback(plant: Plant) -> str | None:
    """Fallback to the explicitly set stage if it's valid."""
    valid_stages = {stage.value for stage in PlantStage}
    if plant.stage in valid_stages:
        return plant.stage
    return None


def generate_vpd_sensor_unique_id(growspace_id: str) -> str:
    """Generate a consistent unique ID for a calculated VPD sensor."""
    return f"{DOMAIN}_{growspace_id}_calculated_vpd"


def generate_growspace_overview_unique_id(growspace_id: str) -> str:
    """Generate a consistent unique ID for a growspace overview sensor."""
    return f"{DOMAIN}_{growspace_id}"
