"""Vision checkup scheduler for AI-powered plant health analysis.

Schedules automated camera snapshots at 3 points during each light cycle
and sends them to an AI vision model for plant health analysis.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


def calculate_checkup_times(
    lights_on_time: time,
    day_hours: int,
    early_offset_minutes: int = 60,
    mid_check_hours: int = 6,
    late_offset_minutes: int = 60,
) -> dict[str, time]:
    """Calculate the 3 checkup times within a light cycle.

    Args:
        lights_on_time: Time when lights turn on (e.g., 06:00).
        day_hours: Hours of light per day (18 for veg, 12 for flower).
        early_offset_minutes: Minutes after lights on for early check.
        mid_check_hours: Hours into light cycle for mid check.
        late_offset_minutes: Minutes before lights off for late check.

    Returns:
        Dict with "early", "mid", "late" keys mapped to time objects.

    """
    # Use a reference date for time arithmetic that may cross midnight
    ref = datetime(2000, 1, 1, lights_on_time.hour, lights_on_time.minute)

    early_dt = ref + timedelta(minutes=early_offset_minutes)
    mid_dt = ref + timedelta(hours=mid_check_hours)
    late_dt = ref + timedelta(hours=day_hours) - timedelta(minutes=late_offset_minutes)

    return {
        "early": early_dt.time(),
        "mid": mid_dt.time(),
        "late": late_dt.time(),
    }


class VisionCheckupScheduler:
    """Schedules and executes AI vision checkups for growspaces."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the vision checkup scheduler."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_timers: dict[str, list[CALLBACK_TYPE]] = {}
