"""Tests for the VisionCheckupScheduler time calculation logic."""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock

import pytest

from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    calculate_checkup_times,
)


def test_calculate_checkup_times_veg_18_6():
    """Test checkup times for 18/6 vegetative cycle with lights on at 06:00."""
    lights_on = time(6, 0)
    day_hours = 18

    times = calculate_checkup_times(
        lights_on_time=lights_on,
        day_hours=day_hours,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(7, 0)   # 06:00 + 1h
    assert times["mid"] == time(12, 0)    # 06:00 + 6h
    assert times["late"] == time(23, 0)   # 06:00 + 18h - 1h = 23:00


def test_calculate_checkup_times_flower_12_12():
    """Test checkup times for 12/12 flowering cycle with lights on at 06:00."""
    times = calculate_checkup_times(
        lights_on_time=time(6, 0),
        day_hours=12,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(7, 0)   # 06:00 + 1h
    assert times["mid"] == time(12, 0)    # 06:00 + 6h
    assert times["late"] == time(17, 0)   # 06:00 + 12h - 1h = 17:00


def test_calculate_checkup_times_wraps_midnight():
    """Test checkup times that wrap past midnight."""
    # Lights on at 20:00, 18h cycle -> lights off at 14:00 next day
    times = calculate_checkup_times(
        lights_on_time=time(20, 0),
        day_hours=18,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(21, 0)  # 20:00 + 1h
    assert times["mid"] == time(2, 0)     # 20:00 + 6h = 02:00 next day
    assert times["late"] == time(13, 0)   # 20:00 + 18h - 1h = 13:00 next day


def test_calculate_checkup_times_flower_night_schedule():
    """Test 12/12 flower with lights on at 18:00 (common night schedule)."""
    times = calculate_checkup_times(
        lights_on_time=time(18, 0),
        day_hours=12,
        early_offset_minutes=60,
        mid_check_hours=6,
        late_offset_minutes=60,
    )

    assert times["early"] == time(19, 0)  # 18:00 + 1h
    assert times["mid"] == time(0, 0)     # 18:00 + 6h = 00:00
    assert times["late"] == time(5, 0)    # 18:00 + 12h - 1h = 05:00


def test_vision_checkup_scheduler_initializes():
    """Test VisionCheckupScheduler initializes with correct attributes."""
    hass = MagicMock(spec=HomeAssistant)
    coordinator = MagicMock()

    scheduler = VisionCheckupScheduler(hass, coordinator)

    assert scheduler.hass is hass
    assert scheduler.coordinator is coordinator
    assert scheduler._unsub_timers == {}
