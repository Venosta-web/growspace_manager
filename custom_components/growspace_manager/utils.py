"""Utility functions for date parsing, formatting, and calculations in growspace_manager."""

from __future__ import annotations

import math
from datetime import date, datetime

from dateutil import parser

from .models import Growspace, Plant

DateInput = str | datetime | date | None


def parse_date_field(date_value: DateInput) -> datetime | None:
    """Parse various date inputs into a datetime object."""
    if date_value is None:
        return None
    if isinstance(date_value, datetime):
        return date_value
    if isinstance(date_value, date):
        return datetime.combine(date_value, datetime.min.time())
    if isinstance(date_value, str):
        try:
            # Attempt to parse ISO format
            return parser.isoparse(date_value)
        except (ValueError, TypeError):
            return None
    return None


def format_date(date_value: DateInput) -> str | None:
    """Format a date input into an ISO string."""
    dt = parse_date_field(date_value)
    if dt is None:
        return None
    return dt.isoformat()


def calculate_days_since(
    start_date: DateInput, end_date: DateInput | None = None
) -> int:
    """Returns the number of days from start_date to end_date.

    If end_date is None, uses current time.
    """
    start = parse_date_field(start_date)
    end = parse_date_field(end_date) if end_date else datetime.now()
    if start is None or end is None:
        return 0
    return (end - start).days


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
) -> tuple[int, int]:
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
    return total_rows, total_cols


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
    def calculate_vpd(temperature_c: float, humidity_rh: float) -> float | None:
        """
        Calculate Vapor Pressure Deficit (VPD) in kPa.

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

        # Magnus formula to calculate saturation vapor pressure (SVP) in kPa
        svp = 0.61094 * math.exp((17.625 * temperature_c) / (243.04 + temperature_c))

        # Calculate actual vapor pressure (AVP)
        avp = svp * (humidity_rh / 100)

        # Calculate VPD
        vpd = svp - avp
        return round(vpd, 2)

    @staticmethod
    def calculate_vpd_with_lst_offset(
        air_temperature_c: float, humidity_rh: float, lst_offset: float = -2.0
    ) -> float | None:
        """
        Calculate Vapor Pressure Deficit (VPD) with Leaf Surface Temperature offset.

        Args:
            air_temperature_c: Air temperature in degrees Celsius.
            humidity_rh: Relative humidity in percent (e.g., 65.5).
            lst_offset: Temperature offset for leaf surface (default: -2.0°C).

        Returns:
            The calculated VPD in kilopascals (kPa), or None if inputs are invalid.
        """
        if not isinstance(air_temperature_c, (int, float)) or not isinstance(
            humidity_rh, (int, float)
        ):
            return None

        # Calculate leaf temperature
        leaf_temperature_c = air_temperature_c + lst_offset

        # Magnus formula for saturation vapor pressure at leaf temperature
        svp_leaf = 0.61094 * math.exp(
            (17.625 * leaf_temperature_c) / (243.04 + leaf_temperature_c)
        )

        # Magnus formula for saturation vapor pressure at air temperature
        svp_air = 0.61094 * math.exp(
            (17.625 * air_temperature_c) / (243.04 + air_temperature_c)
        )

        # Calculate actual vapor pressure from air
        avp = svp_air * (humidity_rh / 100)

        # VPD is the difference between leaf SVP and air AVP
        vpd = svp_leaf - avp
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

    return "seedling"


def _get_stage_from_growspace(plant: Plant) -> str | None:
    """Check if the plant is in a special growspace that dictates its stage."""
    if plant.growspace_id in ("mother", "clone", "dry", "cure"):
        return plant.growspace_id
    return None


def _get_stage_from_dates(plant: Plant) -> str | None:
    """Determine stage based on start dates, prioritizing the most advanced stage."""
    now = datetime.now()
    # Check in reverse order of progression (most advanced first)
    dates = [
        (plant.cure_start, "cure"),
        (plant.dry_start, "dry"),
        (plant.flower_start, "flower"),
        (plant.veg_start, "veg"),
        (plant.clone_start, "clone"),
        (plant.mother_start, "mother"),
        (plant.seedling_start, "seedling"),
    ]
    for date_val, stage in dates:
        if (dt := parse_date_field(date_val)) and dt <= now:
            return stage
    return None


def _get_stage_fallback(plant: Plant) -> str | None:
    """Fallback to the explicitly set stage if it's valid."""
    valid_stages = {
        "seedling",
        "mother",
        "clone",
        "veg",
        "flower",
        "dry",
        "cure",
    }
    if plant.stage in valid_stages:
        return plant.stage
    return None
