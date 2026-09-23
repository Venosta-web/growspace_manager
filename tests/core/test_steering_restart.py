"""A restart mid-day resumes crop steering where it left off (#786).

Each case builds the growspace the way storage hands it back after a restart —
round-tripped through ``to_dict``/``from_dict`` — starts a fresh
``VWCIrrigationCoordinator`` on a real Home Assistant with frozen time, and
drives the minute loop. ``_run_pump_cycle`` is replaced by a recorder, so what
is asserted is the shot the steering shell decided to fire; the Pump Cycle
Gate's own startup rule is pinned in ``tests/domain/test_pump_cycle.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.growspace_manager.domain.irrigation_safety import (
    STARTUP_INHIBIT,
    ControllerState,
)
from custom_components.growspace_manager.domain.steering_phase import (
    PHASE_P1,
    PHASE_P2,
    SUPPRESSED_BY_COOLDOWN,
    SUPPRESSED_BY_STARTUP,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    STARTUP_INHIBIT_POLL,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

GROWSPACE_ID = "gs1"
VWC = "sensor.vwc"
PUMP = "switch.pump"
DAY = "2026-06-15"


def _at(clock: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}T{clock}:00+00:00")


def _growspace(**config: Any) -> Growspace:
    """Lights on 06:00, target 55 %, P2 trigger 53 %, P1 every 15, P2 every 30."""
    growspace = Growspace(
        id=GROWSPACE_ID,
        name="Tent",
        environment_config=EnvironmentConfig(soil_moisture_sensor=VWC),
        irrigation_config=IrrigationConfig(irrigation_pump_entity=PUMP, **config),
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=True,
        lights_on_time="06:00:00",
        target_vwc_percent=55.0,
        maintenance_dryback_percent=2.0,
        p1_shot_interval_minutes=15,
        p2_shot_interval_minutes=30,
    )
    return growspace


def _restarted(growspace: Growspace) -> Growspace:
    """Return what storage hands back after a restart."""
    return Growspace.from_dict(growspace.to_dict())


def _coordinator(hass: HomeAssistant, growspace: Growspace) -> VWCIrrigationCoordinator:
    main = MagicMock()
    main.growspaces = {GROWSPACE_ID: growspace}
    main.services.growspaces.get_substrate_tracker.return_value = None
    main.services.growspaces.get_growspace_plants.return_value = []
    entry = MagicMock()
    entry.async_create_background_task.side_effect = lambda hass_, target, name: (
        hass.async_create_task(target)
    )
    return VWCIrrigationCoordinator(hass, entry, GROWSPACE_ID, main)


@pytest.fixture
def pump_cycles() -> Any:
    with patch.object(
        VWCIrrigationCoordinator, "_run_pump_cycle", new_callable=AsyncMock
    ) as recorder:
        yield recorder


def _phases_fired(recorder: AsyncMock) -> list[str]:
    return [call.args[3]["phase"] for call in recorder.call_args_list]


async def _tick(
    hass: HomeAssistant, coordinator: VWCIrrigationCoordinator
) -> str | None:
    """Run one minute-loop tick and return why it withheld a shot, if it did."""
    await coordinator._update_loop(dt_util.now())
    await hass.async_block_till_done()
    return coordinator.shot_composition_payload()["suppressed_by"]


async def test_restart_mid_p2_resumes_p2_behind_the_startup_inhibit(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, pump_cycles: AsyncMock
) -> None:
    """P1 completed at 09:30, the last shot fired at 13:45, HA restarts at 14:00."""
    before = _growspace()
    before.substrate_history.p1_completed_on = DAY
    before.substrate_history.last_confirmed_shot_at = _at("13:45").isoformat()

    # The reading predates the restart: it has not reported since the start.
    freezer.move_to(_at("13:59"))
    hass.states.async_set(VWC, "50")
    freezer.move_to(_at("14:00"))
    coordinator = _coordinator(hass, _restarted(before))
    await coordinator.async_setup()

    # Below the P2 trigger and past P1's 15-minute interval, yet nothing fires.
    assert await _tick(hass, coordinator) == SUPPRESSED_BY_STARTUP
    assert coordinator._machine.current_phase == PHASE_P2
    snapshot = coordinator.controller_snapshot()
    assert snapshot.state is ControllerState.INHIBITED
    assert [reason.code for reason in snapshot.reasons] == [STARTUP_INHIBIT]
    assert snapshot.reasons[0].detail == (
        "starting up: grace period until 2026-06-15T14:05:00+00:00; "
        f"waiting for a first report from {VWC}"
    )

    # The sensor repeats its value: a report, not a state change.
    freezer.move_to(_at("14:02"))
    hass.states.async_set(VWC, "50")
    assert await _tick(hass, coordinator) == SUPPRESSED_BY_STARTUP

    freezer.move_to(_at("14:05"))
    async_fire_time_changed(hass, _at("14:05") + STARTUP_INHIBIT_POLL)
    await hass.async_block_till_done()
    assert coordinator.controller_snapshot().state is ControllerState.READY

    # Clear of the inhibit, the P2 cooldown still runs from the persisted shot.
    assert await _tick(hass, coordinator) == SUPPRESSED_BY_COOLDOWN
    assert pump_cycles.call_count == 0

    freezer.move_to(_at("14:15"))
    assert await _tick(hass, coordinator) is None
    assert _phases_fired(pump_cycles) == ["P2"]

    await coordinator.async_unload()


async def test_restart_before_p1_completes_resumes_p1_with_its_cooldown(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, pump_cycles: AsyncMock
) -> None:
    """The last P1 shot fired at 09:55 and HA restarts at 10:00, mid-ramp."""
    before = _growspace(startup_grace_minutes=0)
    before.substrate_history.last_confirmed_shot_at = _at("09:55").isoformat()

    freezer.move_to(_at("10:00"))
    coordinator = _coordinator(hass, _restarted(before))
    await coordinator.async_setup()
    hass.states.async_set(VWC, "50")

    assert await _tick(hass, coordinator) == SUPPRESSED_BY_COOLDOWN
    assert coordinator._machine.current_phase == PHASE_P1

    freezer.move_to(_at("10:10"))
    assert await _tick(hass, coordinator) is None
    assert _phases_fired(pump_cycles) == ["P1"]

    await coordinator.async_unload()


async def test_completing_p1_persists_the_date_a_restart_restores(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, pump_cycles: AsyncMock
) -> None:
    freezer.move_to(_at("09:30"))
    growspace = _growspace()
    coordinator = _coordinator(hass, growspace)
    hass.states.async_set(VWC, "56")

    await _tick(hass, coordinator)

    assert growspace.substrate_history.p1_completed_on == DAY
    coordinator._main_coordinator.async_schedule_save.assert_called_once()


async def test_an_unreadable_completion_date_restores_nothing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    pump_cycles: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = _growspace(startup_grace_minutes=0)
    before.substrate_history.p1_completed_on = "not-a-date"

    freezer.move_to(_at("14:00"))
    coordinator = _coordinator(hass, _restarted(before))
    await coordinator.async_setup()
    hass.states.async_set(VWC, "54")

    await _tick(hass, coordinator)

    assert coordinator._machine.current_phase == PHASE_P1
    assert "Ignoring unreadable P1 completion date" in caplog.text

    await coordinator.async_unload()
