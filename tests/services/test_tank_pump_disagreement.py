"""The Tank–Pump Disagreement on a running coordinator (ADR-0064 item 9, #889).

Each case runs the irrigation coordinator's minute tick on a real Home Assistant
with frozen time. Days are made the way they happen: the pump's Delivery
Attempts are recorded in the growspace's store, and the tank's consumption
events on the tank itself. A restart is a new ``DeliveryAttemptStore`` reading
what the last one wrote, and a new coordinator set up on it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.growspace_manager.const import (
    CATEGORY_CALIBRATION,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.delivery_attempt_store import (
    CLOSE_SAVE_DELAY_SECONDS,
    DeliveryAttemptStore,
)
from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationTank,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

GROWSPACE_ID = "gs1"
ENTRY_ID = "entry1"
PUMP = "switch.pump"
TANK = "sensor.reservoir"
KEY = f"growspace_manager.deliveries_{ENTRY_ID}_{GROWSPACE_ID}"


def _at(day: int, clock: str = "00:00:30") -> datetime:
    """Return a moment on a day of September 2026, in the tests' UTC."""
    return datetime.fromisoformat(f"2026-09-{day:02d}T{clock}+00:00")


def _growspace(volume_liters: float | None = 100.0) -> Growspace:
    return Growspace(
        id=GROWSPACE_ID,
        name="Tent",
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity=PUMP,
            irrigation_duration=60,
            pump_flow_rate_ml_per_sec=10.0,
        ),
        environment_config=EnvironmentConfig(
            irrigation_tanks=[
                # Reports only on change, so the days the clock jumps over
                # leave it valid rather than stale.
                IrrigationTank(
                    sensor_entity=TANK,
                    name="Reservoir",
                    volume_liters=volume_liters,
                    stale_after_minutes=0,
                )
            ]
        ),
    )


async def _start(hass: HomeAssistant, growspace: Growspace) -> IrrigationCoordinator:
    """Start one growspace's irrigation the way setup does, on a fresh store."""
    main = MagicMock()
    main.growspaces = {GROWSPACE_ID: growspace}
    main.async_commit = AsyncMock()
    main.deliveries = DeliveryAttemptStore(hass, ENTRY_ID)
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data = main
    coordinator = IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)
    await coordinator._async_load_deliveries()
    return coordinator


def _water_day(
    coordinator: IrrigationCoordinator, day: int, *, tank_l: float, pump_l: float
) -> None:
    """Record one day: a shot delivering ``pump_l`` and the tank dropping ``tank_l``."""
    on = _at(day, "08:00:00")
    attempt = (
        DeliveryAttempt.requested(
            attempt_id=f"shot-{day}",
            growspace_id=GROWSPACE_ID,
            output=PUMP,
            trigger=AttemptTrigger.SCHEDULE,
            planned_s=pump_l * 100,
            flow_rate_ml_per_sec=10.0,
            requested_at=on,
        )
        .commanded(on)
        .confirmed_on(on, on.date())
        .closed(off_commanded_at=on + timedelta(seconds=pump_l * 100))
    )
    coordinator._deliveries.attempts.append(attempt)
    coordinator.growspace.environment_config.irrigation_tanks[
        0
    ].water_history.events.append(
        {
            "timestamp": _at(day, "08:30:00").isoformat(),
            "event_type": "consumption",
            "pct_delta": -tank_l,
            "liters": tank_l,
        }
    )


@pytest.fixture
def logbook(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Collect every growspace logbook line."""
    lines: list[dict[str, Any]] = []

    @callback
    def collect(event: Event) -> None:
        lines.append(dict(event.data))

    hass.bus.async_listen(EVENT_GROWSPACE_LOG_ENTRY, collect)
    return lines


@pytest.fixture(autouse=True)
def reservoir(hass: HomeAssistant) -> None:
    """A tank that reads validly."""
    hass.states.async_set(TANK, "60")


async def _tick(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    coordinator: IrrigationCoordinator,
    at: datetime,
) -> None:
    freezer.move_to(at)
    coordinator._watch_calibration()
    await hass.async_block_till_done()


async def _flush_batch(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(CLOSE_SAVE_DELAY_SECONDS + 1)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_two_disagreeing_days_raise_it_and_it_survives_a_restart(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    logbook: list[dict[str, Any]],
) -> None:
    """Judged after each midnight, raised on the second, and read back after."""
    growspace = _growspace()
    coordinator = await _start(hass, growspace)
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    for day in (25, 26):
        _water_day(coordinator, day, tank_l=8.0, pump_l=5.0)

    await _tick(hass, freezer, coordinator, _at(26))
    assert coordinator.calibration_payload()["tank_pump_disagreement"]["state"] == (
        "clear"
    )
    assert logbook == []

    await _tick(hass, freezer, coordinator, _at(27))
    view = coordinator.calibration_payload()["tank_pump_disagreement"]
    assert view["state"] == "raised"
    assert view["raised_on"] == "2026-09-26"
    assert [day["verdict"] for day in view["days"]] == ["disagrees", "disagrees"]
    assert view["message"] == (
        "The tank dropped 8.0 L yesterday; the pump delivered 5.0 L (38% less)."
        " A flow rate set too low, a leak, or water drawn from the tank can cause"
        " this."
    )
    assert [line["category"] for line in logbook] == [CATEGORY_CALIBRATION]
    assert logbook[0]["growspace_id"] == GROWSPACE_ID
    assert logbook[0]["message"] == f"Tank–Pump Disagreement raised. {view['message']}"

    # A tick later the same day judges nothing again.
    await _tick(hass, freezer, coordinator, _at(27, "00:01:30"))
    assert len(logbook) == 1

    await _flush_batch(hass, freezer)
    assert hass_storage[KEY]["data"]["calibration"]["raised_on"] == "2026-09-26"

    restarted = await _start(hass, growspace)
    assert restarted.calibration_payload()["tank_pump_disagreement"] == view


async def test_two_agreeing_days_clear_it_with_a_logbook_line(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    logbook: list[dict[str, Any]],
) -> None:
    """A corrected flow rate brings the two figures back together."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(20, "10:00:00"))
    for day in (21, 22):
        _water_day(coordinator, day, tank_l=8.0, pump_l=5.0)
    for day in (23, 24):
        _water_day(coordinator, day, tank_l=8.0, pump_l=7.5)

    await _tick(hass, freezer, coordinator, _at(25))

    view = coordinator.calibration_payload()["tank_pump_disagreement"]
    assert view["state"] == "clear"
    assert view["message"] is None
    assert [line["message"] for line in logbook] == [
        logbook[0]["message"],
        "Tank–Pump Disagreement cleared: the tank drop and the pump agreed on 2"
        " days in a row.",
    ]
    assert logbook[0]["message"].startswith(
        "Tank–Pump Disagreement raised. The tank dropped 8.0 L on 22 September;"
    )


async def test_a_day_with_the_tank_unknown_counts_neither_way(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    logbook: list[dict[str, Any]],
) -> None:
    """One unreadable minute is enough to set the day aside."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    for day in (25, 26):
        _water_day(coordinator, day, tank_l=8.0, pump_l=5.0)
    await _tick(hass, freezer, coordinator, _at(26))

    hass.states.async_set(TANK, "unavailable")
    await _tick(hass, freezer, coordinator, _at(26, "13:00:00"))
    hass.states.async_set(TANK, "60")
    await _tick(hass, freezer, coordinator, _at(26, "13:01:00"))
    await _tick(hass, freezer, coordinator, _at(27))

    view = coordinator.calibration_payload()["tank_pump_disagreement"]
    assert [day["verdict"] for day in view["days"]] == ["disagrees", "tank_unknown"]
    assert view["state"] == "clear"
    assert logbook == []


async def test_a_day_without_an_attempt_counts_neither_way(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A tank that dropped with the pump idle is a leak or a draw, not a rate."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    _water_day(coordinator, 25, tank_l=8.0, pump_l=5.0)
    coordinator.growspace.environment_config.irrigation_tanks[
        0
    ].water_history.events.append(
        {
            "timestamp": _at(26, "12:00:00").isoformat(),
            "event_type": "consumption",
            "liters": 6.0,
        }
    )
    _water_day(coordinator, 27, tank_l=8.0, pump_l=5.0)

    await _tick(hass, freezer, coordinator, _at(28))

    view = coordinator.calibration_payload()["tank_pump_disagreement"]
    assert [day["verdict"] for day in view["days"]] == [
        "disagrees",
        "no_attempt",
        "disagrees",
    ]
    assert view["state"] == "raised"


async def test_hand_watering_from_the_tank_is_not_blamed_on_the_pump(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The jug drawn from the tank is taken off its drop."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    _water_day(coordinator, 25, tank_l=8.0, pump_l=5.0)
    coordinator.growspace.water_usage.daily_readings.append(
        {
            "date": "2026-09-25",
            "liters": 3.0,
            "source": "manual",
            "from_monitored_tank": True,
        }
    )

    await _tick(hass, freezer, coordinator, _at(26))

    (day,) = coordinator.calibration_payload()["tank_pump_disagreement"]["days"]
    assert day == {
        "date": "2026-09-25",
        "verdict": "agrees",
        "tank_drop_l": 8.0,
        "hand_watering_l": 3.0,
        "pump_l": 5.0,
    }


async def test_a_tank_that_stops_being_measured_restarts_the_comparison(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    logbook: list[dict[str, Any]],
) -> None:
    """Without a tank in litres there is nothing left to disagree with."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    for day in (25, 26):
        _water_day(coordinator, day, tank_l=8.0, pump_l=5.0)
    await _tick(hass, freezer, coordinator, _at(27))

    coordinator.growspace.environment_config.irrigation_tanks[0].volume_liters = None
    assert coordinator.calibration_payload()["tank_pump_disagreement"] == {
        "state": "no_tank",
        "raised_on": None,
        "message": None,
        "days": [],
    }
    await _tick(hass, freezer, coordinator, _at(27, "09:00:00"))

    assert logbook[-1]["message"] == (
        "Tank–Pump Disagreement cleared: the growspace's measured tanks changed,"
        " so the comparison starts again."
    )


async def test_the_first_day_watched_is_never_judged(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Only part of it was watched for an unknown tank."""
    coordinator = await _start(hass, _growspace())
    _water_day(coordinator, 24, tank_l=8.0, pump_l=5.0)
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))

    await _tick(hass, freezer, coordinator, _at(25))

    assert coordinator.calibration_payload()["tank_pump_disagreement"]["days"] == []


async def test_unreadable_calibration_evidence_starts_again_and_holds_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """It is never enforced, so it never fails the delivery record closed."""
    freezer.move_to(_at(25, "10:00:00"))
    hass_storage[KEY] = {
        "version": 1,
        "key": KEY,
        "data": {
            "growspace_id": GROWSPACE_ID,
            "attempts": [],
            "calibration": {"tanks": "garbage"},
        },
    }

    coordinator = await _start(hass, _growspace())

    assert not coordinator._deliveries.unreadable
    assert coordinator._deliveries.calibration.tanks == ()


async def test_an_unchanged_record_is_not_saved_again(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    """A quiet minute writes nothing."""
    coordinator = await _start(hass, _growspace())
    await _tick(hass, freezer, coordinator, _at(24, "10:00:00"))
    await _flush_batch(hass, freezer)
    hass_storage.pop(KEY)

    await _tick(hass, freezer, coordinator, _at(24, "10:05:00"))
    await _flush_batch(hass, freezer)

    assert KEY not in hass_storage
