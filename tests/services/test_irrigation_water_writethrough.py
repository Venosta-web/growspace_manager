"""Tests for pump-cycle water write-through into WaterUsageData (ADR-0017).

A completed irrigation cycle on a growspace that is *not* in Tank-Derived
Water Mode persists its estimated volume (pump runtime × flow rate) into
``WaterUsageData`` tagged ``pump_estimate``, so pump-only / no-flow growspaces
report water end-to-end and survive a restart. In tank mode the write is
skipped (the reservoir already measures that water — see ADR-0017).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.domain.water_aggregation import (
    WATER_SOURCE_PUMP_ESTIMATE,
    compute_growspace_water,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"

_REAL_ASYNCIO_SLEEP = asyncio.sleep


def _pump_growspace(*, tank_mode: bool) -> Growspace:
    """Build a growspace with a known pump flow rate.

    ``tank_mode`` toggles the *only* trigger that flips
    ``is_tank_derived_mode``: a tank with ``volume_liters`` configured and no
    flow/drain-volume sensors. Everything else is held constant so the gating
    tests prove the gate and nothing else.
    """
    env = EnvironmentConfig()
    if tank_mode:
        env.irrigation_tanks = [
            IrrigationTank(sensor_entity="sensor.tank", volume_liters=50.0)
        ]
    return Growspace(
        id=GROWSPACE_ID,
        name="Test Growspace",
        environment_config=env,
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity="switch.irrigation_pump",
            pump_flow_rate_ml_per_sec=100.0,
        ),
    )


@pytest.fixture
def make_coordinator(mock_hass: MagicMock, mock_config_entry: MagicMock):
    """Return a factory building a coordinator around a given growspace."""

    def _build(growspace: Growspace) -> IrrigationCoordinator:
        main = MagicMock()
        main.growspaces = {GROWSPACE_ID: growspace}
        main.add_event = MagicMock()
        main.async_commit = AsyncMock()
        mock_config_entry.runtime_data = main
        coordinator = IrrigationCoordinator(
            mock_hass, mock_config_entry, GROWSPACE_ID, main
        )
        return coordinator

    return _build


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.async_create_task = asyncio.create_task
    hass.async_create_background_task = MagicMock(
        side_effect=lambda target, name: asyncio.create_task(target)
    )
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = ENTRY_ID
    entry.options = {}
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass, target, name: asyncio.create_task(target)
    )
    return entry


async def _run_cycle(coordinator: IrrigationCoordinator, duration: int) -> None:
    """Drive one full irrigation cycle with instant sleeps and switch confirms."""
    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", duration, {"time": "10:00:00"}
        )


async def _drain_tasks() -> None:
    """Await any background tasks spawned by a fired shot."""
    await _REAL_ASYNCIO_SLEEP(0)
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    for task in pending:
        await task


async def test_completed_cycle_records_pump_estimate_when_not_tank_mode(
    make_coordinator,
) -> None:
    """A completed cycle persists its volume tagged pump_estimate (ADR-0017)."""
    growspace = _pump_growspace(tank_mode=False)
    coordinator = make_coordinator(growspace)

    # 30s × 100 ml/s = 3000 ml = 3.0 L
    await _run_cycle(coordinator, 30)

    readings = growspace.water_usage.daily_readings
    assert len(readings) == 1
    assert readings[0]["source"] == WATER_SOURCE_PUMP_ESTIMATE
    assert readings[0]["liters"] == pytest.approx(3.0)
    assert growspace.water_usage.total_liters == pytest.approx(3.0)


async def test_completed_cycle_skips_write_in_tank_mode(make_coordinator) -> None:
    """No pump-estimate write occurs in Tank-Derived Water Mode (ADR-0017)."""
    growspace = _pump_growspace(tank_mode=True)
    coordinator = make_coordinator(growspace)

    await _run_cycle(coordinator, 30)

    assert growspace.water_usage.daily_readings == []
    assert growspace.water_usage.total_liters == 0.0


async def test_recorded_pump_water_is_committed_for_persistence(
    make_coordinator,
) -> None:
    """The write is committed through the coordinator so it survives a restart."""
    growspace = _pump_growspace(tank_mode=False)
    coordinator = make_coordinator(growspace)

    await _run_cycle(coordinator, 30)

    # Persistence path, not only the in-memory daily-cap counter.
    coordinator._main_coordinator.async_commit.assert_awaited()


async def test_pump_water_appears_in_aggregate_water_use(make_coordinator) -> None:
    """Pump-only / no-flow water surfaces in the briefing Water Use KPI."""
    growspace = _pump_growspace(tank_mode=False)
    coordinator = make_coordinator(growspace)

    await _run_cycle(coordinator, 30)

    # No tank trackers (pump-only growspace); KPI must still report the water.
    figures = compute_growspace_water(growspace, [])
    assert figures.today == pytest.approx(3.0)
    assert figures.cycle == pytest.approx(3.0)
    assert figures.source == "measured"


async def test_vwc_fired_shot_records_pump_estimate(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """A real crop-steering shot writes through the pump-cycle path (AC #2).

    Drives the actual shot-firing path (machine shot evaluation + ``_fire_shot``)
    rather than calling ``_run_pump_cycle`` directly, so the test exercises the
    ``event_type`` the VWC coordinator really passes — the value the write-through gate keys on. A weaker
    test that called the inherited method directly would only prove subclassing.
    """
    growspace = _pump_growspace(tank_mode=False)
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=True,
        p1_shot_duration_seconds=20,
        p1_shot_interval_minutes=15,
    )
    main = MagicMock()
    main.growspaces = {GROWSPACE_ID: growspace}
    main.add_event = MagicMock()
    main.async_commit = AsyncMock()
    main.services.growspaces.get_substrate_tracker.return_value = None
    mock_config_entry.runtime_data = main
    coordinator = VWCIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, main
    )

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        inputs = coordinator._tick_inputs(
            40.0, growspace.irrigation_strategy, growspace
        )
        fire, _note = coordinator._machine._evaluate_shot(
            inputs, "P1", reset_pending=False
        )
        assert fire is not None
        coordinator._fire_shot(growspace.irrigation_strategy, fire)
        await _drain_tasks()

    # 20s × 100 ml/s = 2000 ml = 2.0 L
    readings = growspace.water_usage.daily_readings
    assert len(readings) == 1
    assert readings[0]["source"] == WATER_SOURCE_PUMP_ESTIMATE
    assert readings[0]["liters"] == pytest.approx(2.0)
    main.async_commit.assert_awaited()
