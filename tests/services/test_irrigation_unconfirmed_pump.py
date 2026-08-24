"""Tests for a pump cycle whose switch never confirms 'on'.

``switch.turn_on`` is fired with ``blocking=True`` *before* the confirmation
wait starts, so on a timeout the pump may already be running. Timing the shot
from the end of that wait would run the pump for ``duration`` plus the whole
confirmation timeout and still book ``duration`` of water. The coordinator
therefore dates an unconfirmed cycle from the ``turn_on`` call, shortens the
sleep by the wait, and bills whichever of planned/measured runtime is larger.

The confirmed path is deliberately untouched: a device that reports the relay
closing tells us when water actually started moving (the Matter smart-plug
case the wait exists for).
"""

from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"
PUMP = "switch.irrigation_pump"
FLOW_ML_PER_SEC = 100.0
START_TIME = "2026-01-12 12:00:00"


@pytest.fixture
def coordinator() -> IrrigationCoordinator:
    """Build a coordinator over a growspace with a known pump flow rate."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.data = {DOMAIN: {}}

    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = ENTRY_ID
    entry.options = {}

    main = MagicMock()
    main.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity=PUMP,
                pump_flow_rate_ml_per_sec=FLOW_ML_PER_SEC,
            ),
        )
    }
    main.async_commit = AsyncMock()
    entry.runtime_data = main

    return IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)


async def _run_cycle(
    coordinator: IrrigationCoordinator,
    *,
    duration: int,
    confirmed: bool,
    wait_seconds: float,
) -> tuple[list[float], float, AsyncMock]:
    """Run one irrigation cycle against a clock only this test advances.

    Returns the seconds passed to every ``asyncio.sleep``, the pump's total ON
    time (turn_on call → turn_off call) and the water-recording spy.
    """
    record_water = AsyncMock()
    slept: list[float] = []

    with freeze_time(START_TIME) as clock:
        pump_on_at: list[float] = []
        elapsed = 0.0

        async def fake_wait(
            entity_id: str, target_state: str, **kwargs: object
        ) -> bool:
            nonlocal elapsed
            clock.tick(wait_seconds)
            elapsed += wait_seconds
            return confirmed

        async def fake_sleep(seconds: float) -> None:
            nonlocal elapsed
            slept.append(seconds)
            clock.tick(seconds)
            elapsed += seconds

        async def fake_service_call(domain: str, service: str, *args, **kwargs) -> None:
            if service in ("turn_on", "turn_off"):
                pump_on_at.append(elapsed)

        coordinator.hass.services.async_call = AsyncMock(side_effect=fake_service_call)

        with (
            patch("asyncio.sleep", new=fake_sleep),
            patch.object(coordinator, "_async_wait_for_switch_state", new=fake_wait),
            patch.object(coordinator, "_async_record_pump_water", new=record_water),
            patch.object(coordinator, "_async_spawn_settling_report", MagicMock()),
        ):
            await coordinator._run_pump_cycle(
                "irrigation", PUMP, duration, {"time": "10:00:00"}
            )

    on_seconds = pump_on_at[-1] - pump_on_at[0]
    return slept, on_seconds, record_water


def _liters(seconds: float) -> float:
    """Litres a pump at the fixture's flow rate delivers in ``seconds``."""
    return seconds * FLOW_ML_PER_SEC / 1000.0


async def test_confirmed_switch_sleeps_the_full_duration(
    coordinator: IrrigationCoordinator,
) -> None:
    """A confirmed switch still starts the timer at the confirmation."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=30, confirmed=True, wait_seconds=2.0
    )

    assert slept == [30]
    # Timer starts at the confirmation, so the wait is on top — the device only
    # began moving water when it reported 'on'.
    assert on_seconds == pytest.approx(32.0)
    record_water.assert_awaited_once_with(pytest.approx(_liters(30)))
    assert coordinator._volume_dispensed_today == pytest.approx(_liters(30))


async def test_unconfirmed_switch_shortens_the_sleep_by_the_wait(
    coordinator: IrrigationCoordinator,
) -> None:
    """An unconfirmed pump runs for the shot, not the shot plus the timeout."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=30, confirmed=False, wait_seconds=10.0
    )

    assert slept == [pytest.approx(20.0)]
    assert on_seconds == pytest.approx(30.0)
    record_water.assert_awaited_once_with(pytest.approx(_liters(30)))
    assert coordinator._volume_dispensed_today == pytest.approx(_liters(30))


async def test_unconfirmed_wait_longer_than_the_shot_bills_the_overrun(
    coordinator: IrrigationCoordinator,
) -> None:
    """When the wait outlasts the shot the sleep clamps and the water is billed."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=5, confirmed=False, wait_seconds=10.0
    )

    assert slept == [0.0]
    assert on_seconds == pytest.approx(10.0)
    # 10s of pump, not the planned 5s: the daily cap must see the real water.
    record_water.assert_awaited_once_with(pytest.approx(_liters(10)))
    assert coordinator._volume_dispensed_today == pytest.approx(_liters(10))


async def test_unconfirmed_switch_still_turns_the_pump_off(
    coordinator: IrrigationCoordinator,
) -> None:
    """Non-confirmation is not a halt — the cycle completes normally."""
    await _run_cycle(coordinator, duration=5, confirmed=False, wait_seconds=10.0)

    services = coordinator.hass.services.async_call
    called = [(c.args[0], c.args[1]) for c in services.await_args_list]
    assert ("switch", "turn_on") in called
    assert ("switch", "turn_off") in called
    assert coordinator._cycles_today == 1
