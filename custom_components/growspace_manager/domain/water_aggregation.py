"""Shared water-use aggregation — the single source of truth (ADR-0017).

A growspace receives water three ways, tracked three ways:

* **manual** — explicit watering events; liters supplied by the caller, stored
  on ``WaterUsageData`` (``total_liters`` + ``daily_readings``).
* **tank-derived** — inferred from reservoir-level change by ``TankWaterTracker``
  when the growspace is in Tank-Derived Water Mode.
* **pump-cycle** — estimated from pump runtime × flow rate, persisted *into*
  ``WaterUsageData`` write-through with a ``source: "pump_estimate"`` tag, but
  only when the growspace is **not** in tank mode.

The canonical figure is ``manual + (tank-derived if tank-mode else pump-estimate)``.
Because the pump estimate is write-gated out of tank mode, ``WaterUsageData`` holds
manual-only in tank mode and manual+pump otherwise — so this helper only ever adds
the tank-derived sum on top of ``WaterUsageData``, never the pump path twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from custom_components.growspace_manager.models import Growspace
from homeassistant.util import dt as dt_util

# Source tags written onto WaterUsageData.daily_readings entries.
WATER_SOURCE_MANUAL = "manual"
WATER_SOURCE_PUMP_ESTIMATE = "pump_estimate"


def _trim_daily_readings(growspace: Growspace) -> None:
    """Keep the newest local days while preserving every report on each day."""
    usage = growspace.water_usage
    daily = usage.daily_readings
    daily.sort(key=lambda reading: reading.get("date", ""))
    dates = sorted({reading.get("date", "") for reading in daily})
    if len(dates) > usage.max_daily_readings:
        keep = set(dates[-usage.max_daily_readings :])
        usage.daily_readings = [
            reading for reading in daily if reading.get("date") in keep
        ]


class _TankTracker(Protocol):
    """The slice of TankWaterTracker this helper reads."""

    def get_total_liters_today(self, reference_ts: str | None = None) -> float: ...

    def get_total_liters_since(self, cycle_start_date: str | None = None) -> float: ...


@dataclass(slots=True)
class WaterUseFigures:
    """Aggregate water use for a growspace.

    ``today`` is liters since local midnight; ``cycle`` is liters since
    ``cycle_start_date``. ``source`` names the winning measurement source
    (``"tank_derived"`` or ``"measured"`` — the latter being manual + pump
    held together in ``WaterUsageData``).
    """

    today: float
    cycle: float
    source: str


def record_daily_water(
    growspace: Growspace,
    liters: float,
    *,
    source: str,
    reference_date: str | None = None,
) -> None:
    """Write ``liters`` into WaterUsageData, tagged by ``source`` (ADR-0017).

    Bumps ``total_liters`` and merges into today's ``daily_readings`` entry for
    that source (one entry per (date, source) pair so a pump estimate and a
    manual event on the same day stay distinguishable), then enforces the
    rolling window. Shared by the manual watering path and the pump-cycle path.
    """
    if liters <= 0:
        return
    if reference_date is None:
        reference_date = dt_util.now().date().isoformat()

    usage = growspace.water_usage
    usage.total_liters = round(usage.total_liters + liters, 3)

    daily = usage.daily_readings
    for reading in daily:
        if (
            reading.get("date") == reference_date
            and reading.get("source") == source
            and "watering_id" not in reading
        ):
            reading["liters"] = round(reading.get("liters", 0.0) + liters, 3)
            break
    else:
        daily.append(
            {"date": reference_date, "liters": round(liters, 3), "source": source}
        )

    _trim_daily_readings(growspace)


def record_hand_watering(
    growspace: Growspace,
    liters: float,
    *,
    watering_id: str,
    user_id: str | None,
    plant_id: str,
    watered_at: str,
    from_monitored_tank: bool,
    reference_date: str,
) -> None:
    """Preserve each hand-watering report in the existing manual water store."""
    if liters <= 0:
        return
    usage = growspace.water_usage
    usage.total_liters = round(usage.total_liters + liters, 3)
    if from_monitored_tank:
        usage.monitored_tank_liters = round(usage.monitored_tank_liters + liters, 3)
    usage.daily_readings.append(
        {
            "date": reference_date,
            "liters": round(liters, 3),
            "source": WATER_SOURCE_MANUAL,
            "watering_id": watering_id,
            "user_id": user_id,
            "plant_id": plant_id,
            "watered_at": watered_at,
            "from_monitored_tank": from_monitored_tank,
        }
    )
    _trim_daily_readings(growspace)


def is_tank_derived_mode(growspace: Growspace) -> bool:
    """Return True when reservoir-level inference is the measurement source.

    Active when at least one tank has ``volume_liters`` configured.
    ``irrigation_flow_sensors`` and ``drain_volume_sensors`` play no part: no
    reading of either is converted to litres, so letting them switch this off
    traded the tank figure for the Pump-Cycle Water Estimate (#853).
    """
    return any(
        tank.volume_liters is not None
        for tank in growspace.environment_config.irrigation_tanks
    )


def _water_usage_today(
    growspace: Growspace, reference_date: str, *, exclude_monitored_tank: bool = False
) -> float:
    """Sum today's liters across all sources in WaterUsageData.daily_readings."""
    return round(
        sum(
            float(reading.get("liters", 0.0))
            for reading in growspace.water_usage.daily_readings
            if reading.get("date") == reference_date
            and not (exclude_monitored_tank and reading.get("from_monitored_tank"))
        ),
        2,
    )


def compute_growspace_water(
    growspace: Growspace,
    trackers: Iterable[_TankTracker],
    *,
    reference_date: str | None = None,
) -> WaterUseFigures:
    """Compute the canonical [[Aggregate Water Use]] for one growspace.

    ``trackers`` are the growspace's cached ``TankWaterTracker`` instances
    (callers pass ``get_all_trackers_for_growspace(...).values()``). They are
    only consulted when the growspace is in Tank-Derived Water Mode.
    """
    if reference_date is None:
        reference_date = dt_util.now().date().isoformat()

    usage = growspace.water_usage
    tracker_list = list(trackers)
    if is_tank_derived_mode(growspace) and tracker_list:
        usage_today = _water_usage_today(
            growspace, reference_date, exclude_monitored_tank=True
        )
        usage_cycle = round(usage.total_liters - usage.monitored_tank_liters, 2)
        cycle_start = usage.cycle_start_date or None
        tank_today = sum(t.get_total_liters_today() for t in tracker_list)
        tank_cycle = sum(t.get_total_liters_since(cycle_start) for t in tracker_list)
        # Manual lives in WaterUsageData; pump estimates are write-gated out of
        # tank mode, so adding usage_* here adds manual only (per ADR-0017).
        return WaterUseFigures(
            today=round(tank_today + usage_today, 2),
            cycle=round(tank_cycle + usage_cycle, 2),
            source="tank_derived",
        )

    tank_mode = is_tank_derived_mode(growspace)
    return WaterUseFigures(
        today=_water_usage_today(
            growspace, reference_date, exclude_monitored_tank=tank_mode
        ),
        cycle=round(
            usage.total_liters - (usage.monitored_tank_liters if tank_mode else 0), 2
        ),
        source="measured",
    )
