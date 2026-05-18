"""Date and time utility helpers for Growspace Manager."""

from __future__ import annotations

from datetime import date, datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .utils import parse_date_field

if TYPE_CHECKING:
    from .const import DateInput

_LOGGER = logging.getLogger(__name__)


class DateTimeHelper:
    """Helper class for date and time operations."""

    @staticmethod
    def to_date(date_value: DateInput) -> date | None:
        """Convert a date input to a date object.

        Args:
            date_value: The date value to convert.

        Returns:
            A date object or None if conversion fails.
        """
        if not date_value or str(date_value) == "None":
            return None
        try:
            if isinstance(date_value, datetime):
                return date_value.date()
            if isinstance(date_value, date):
                return date_value
            if isinstance(date_value, str):
                if dt := parse_date_field(date_value):
                    return dt.date()
        except Exception:
            _LOGGER.exception("Failed to parse date %s", date_value)
        return None

    @staticmethod
    def calculate_days(start_date: DateInput, end_date: DateInput = None) -> int:
        """Calculate the number of days that have passed since a given date.

        If an end_date is provided and is valid (i.e., not in the future relative
        to today), the calculation is capped at that date. Otherwise, it
        calculates up to today.

        Args:
            start_date: The start date to calculate from.
            end_date: The optional end date to cap the duration.

        Returns:
            The total number of days passed, or 0 if the date is invalid.
        """
        start_dt = DateTimeHelper.to_date(start_date)
        if not start_dt:
            return 0

        target_date = dt_util.now().date()

        if end_date:
            end_dt = DateTimeHelper.to_date(end_date)
            if end_dt and end_dt <= target_date:
                target_date = end_dt

        return (target_date - start_dt).days
