"""Tests for the shared water-use aggregation helper (ADR-0017)."""

from __future__ import annotations

from custom_components.growspace_manager.domain.water_aggregation import (
    WATER_SOURCE_MANUAL,
    WATER_SOURCE_PUMP_ESTIMATE,
    WaterUseFigures,
    compute_growspace_water,
    is_tank_derived_mode,
    record_daily_water,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
    WaterUsageData,
)


class _FakeTracker:
    """Minimal stand-in for TankWaterTracker exposing only the read API used."""

    def __init__(self, today: float, since: float) -> None:
        self._today = today
        self._since = since

    def get_total_liters_today(self, reference_ts: str | None = None) -> float:
        return self._today

    def get_total_liters_since(self, cycle_start_date: str | None = None) -> float:
        return self._since


def _growspace(
    *,
    tank_volume: float | None = None,
    flow_sensors: list[str] | None = None,
    drain_sensors: list[str] | None = None,
    total_liters: float = 0.0,
    daily_readings: list[dict] | None = None,
) -> Growspace:
    tanks = (
        [IrrigationTank(sensor_entity="sensor.tank", volume_liters=tank_volume)]
        if tank_volume is not None
        else []
    )
    env = EnvironmentConfig(
        irrigation_tanks=tanks,
        irrigation_flow_sensors=flow_sensors or [],
        drain_volume_sensors=drain_sensors or [],
    )
    usage = WaterUsageData(
        total_liters=total_liters,
        cycle_start_date="2026-06-01",
        daily_readings=daily_readings or [],
    )
    return Growspace(id="gs", name="GS", environment_config=env, water_usage=usage)


# ── mode detection ──────────────────────────────────────────────────────────


def test_tank_mode_active_with_volume_and_no_sensors():
    gs = _growspace(tank_volume=200.0)
    assert is_tank_derived_mode(gs) is True


def test_tank_mode_inactive_without_volume():
    gs = _growspace(tank_volume=None)
    assert is_tank_derived_mode(gs) is False


def test_tank_mode_inactive_when_flow_sensor_present():
    gs = _growspace(tank_volume=200.0, flow_sensors=["sensor.flow"])
    assert is_tank_derived_mode(gs) is False


def test_tank_mode_inactive_when_drain_sensor_present():
    gs = _growspace(tank_volume=200.0, drain_sensors=["sensor.drain"])
    assert is_tank_derived_mode(gs) is False


# ── non-tank path: WaterUsageData holds manual + pump (both written through) ──


def test_non_tank_returns_water_usage_directly():
    gs = _growspace(
        total_liters=42.0,
        daily_readings=[
            {"date": "2026-06-15", "liters": 4.0, "source": "manual"},
            {"date": "2026-06-15", "liters": 6.0, "source": "pump_estimate"},
        ],
    )
    figures = compute_growspace_water(gs, [], reference_date="2026-06-15")
    assert isinstance(figures, WaterUseFigures)
    assert figures.cycle == 42.0
    assert figures.today == 10.0
    assert figures.source == "measured"


# ── tank path: tank-derived + manual on top (pump NOT in WaterUsageData) ──────


def test_tank_mode_adds_manual_on_top():
    """Tank-derived figures plus manual watering held in WaterUsageData."""
    gs = _growspace(
        tank_volume=200.0,
        total_liters=3.0,  # manual only (pump write-gated in tank mode)
        daily_readings=[{"date": "2026-06-15", "liters": 1.5, "source": "manual"}],
    )
    trackers = [_FakeTracker(today=8.0, since=50.0)]
    figures = compute_growspace_water(gs, trackers, reference_date="2026-06-15")
    assert figures.today == 8.0 + 1.5
    assert figures.cycle == 50.0 + 3.0
    assert figures.source == "tank_derived"


def test_tank_mode_sums_across_multiple_trackers():
    gs = _growspace(tank_volume=200.0)
    trackers = [_FakeTracker(today=2.0, since=10.0), _FakeTracker(today=3.0, since=15.0)]
    figures = compute_growspace_water(gs, trackers, reference_date="2026-06-15")
    assert figures.today == 5.0
    assert figures.cycle == 25.0


def test_tank_mode_with_no_trackers_falls_back_to_water_usage():
    """Tank configured but no tracker instances yet — use WaterUsageData."""
    gs = _growspace(tank_volume=200.0, total_liters=7.0)
    figures = compute_growspace_water(gs, [], reference_date="2026-06-15")
    assert figures.cycle == 7.0
    assert figures.source == "measured"


# ── write path: record_daily_water ──────────────────────────────────────────


def test_record_daily_water_appends_tagged_entry():
    gs = _growspace()
    record_daily_water(gs, 4.0, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    assert gs.water_usage.total_liters == 4.0
    assert gs.water_usage.daily_readings == [
        {"date": "2026-06-15", "liters": 4.0, "source": "manual"}
    ]


def test_record_daily_water_merges_same_date_and_source():
    gs = _growspace()
    record_daily_water(gs, 4.0, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    record_daily_water(gs, 1.5, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    assert len(gs.water_usage.daily_readings) == 1
    assert gs.water_usage.daily_readings[0]["liters"] == 5.5


def test_record_daily_water_keeps_sources_separate():
    gs = _growspace()
    record_daily_water(gs, 4.0, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    record_daily_water(
        gs, 6.0, source=WATER_SOURCE_PUMP_ESTIMATE, reference_date="2026-06-15"
    )
    assert len(gs.water_usage.daily_readings) == 2
    assert gs.water_usage.total_liters == 10.0
    # Both sum into today's aggregate
    figures = compute_growspace_water(gs, [], reference_date="2026-06-15")
    assert figures.today == 10.0


def test_record_daily_water_ignores_nonpositive():
    gs = _growspace()
    record_daily_water(gs, 0.0, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    record_daily_water(gs, -2.0, source=WATER_SOURCE_MANUAL, reference_date="2026-06-15")
    assert gs.water_usage.total_liters == 0.0
    assert gs.water_usage.daily_readings == []
