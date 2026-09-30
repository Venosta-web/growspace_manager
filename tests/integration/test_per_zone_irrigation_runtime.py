"""Independent zone loops share one physical supply across a lit day (#895)."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import ShotSizingMode
from custom_components.growspace_manager.domain.irrigation_safety import ControllerState
from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationZone,
    Plant,
    SubstrateProfile,
)
from custom_components.growspace_manager.substrate_tracker import SubstrateTracker
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.core import callback
from homeassistant.util import dt as dt_util
from tests.zones import set_strategy

DAY = "2026-06-15"
REAL_SLEEP = asyncio.sleep


def at(clock):
    return datetime.fromisoformat(f"{DAY}T{clock}:00+00:00")


@pytest.fixture
async def zone_rig(hass, freezer):
    freezer.move_to(at("06:00"))
    growspace = Growspace(
        id="tent",
        name="Tent",
        rows=1,
        plants_per_row=6,
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity="switch.pump", startup_grace_minutes=0
        ),
    )
    set_strategy(
        growspace,
        IrrigationStrategy(
            enabled=True,
            lights_on_time="06:00:00",
            target_vwc_percent=55,
            p0_duration_minutes=0,
            dynamic_shot_enabled=True,
            shot_sizing_mode=ShotSizingMode.VOLUME,
            substrate_profile=SubstrateProfile(liters_per_pot=1),
            p1_shot_volume_percent=1,
            p2_shot_volume_percent=1,
            p1_shot_interval_minutes=15,
            p2_shot_interval_minutes=30,
        ),
    )
    default = growspace.default_zone
    default.cells = [(1, 1)]
    for zone_id, cells in (
        ("north", [(1, 2), (1, 3)]),
        ("south", [(1, 4), (1, 5), (1, 6)]),
    ):
        from copy import deepcopy

        growspace.irrigation_zones.append(
            IrrigationZone(
                id=zone_id,
                name=zone_id.title(),
                cells=cells,
                strategy=deepcopy(default.strategy),
            )
        )
    plants = [
        Plant(plant_id=f"p{i}", growspace_id="tent", row=1, col=i, veg_start=DAY)
        for i in range(1, 7)
    ]
    main = MagicMock()
    main.growspaces = {"tent": growspace}
    main.async_commit = AsyncMock()
    main.async_project_water = AsyncMock()
    main.services.notifications.manager.async_send_notification = AsyncMock()
    main.services.growspaces.get_growspace_plants.return_value = plants
    trackers = {
        zone.id: SubstrateTracker(growspace, zone.id)
        for zone in growspace.irrigation_zones
    }
    main.services.growspaces.get_substrate_tracker.side_effect = lambda gs, zone=None: (
        trackers[zone or "default"]
    )
    entry = MagicMock()
    entry.runtime_data = main
    entry.async_create_background_task.side_effect = lambda ha, target, name: (
        ha.async_create_task(target)
    )
    trace = []

    @callback
    def actuate(call):
        output = call.data["entity_id"]
        if call.service == "turn_on" and output == "switch.pump":
            opened = [
                z.id
                for z in growspace.irrigation_zones
                if hass.states.get(z.valves[0]).state == "on"
            ]
            assert len(opened) == 1
            trace.append(opened[0])
        hass.states.async_set(output, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("persistent_notification", "create", lambda call: None)
    hass.services.async_register(
        "persistent_notification", "dismiss", lambda call: None
    )
    hass.services.async_register("switch", "turn_on", actuate)
    hass.services.async_register("switch", "turn_off", actuate)
    hass.states.async_set("switch.pump", "off")
    runtimes = []
    for zone in growspace.irrigation_zones:
        zone.valves = [f"switch.{zone.id}_valve"]
        zone.soil_moisture_sensor = f"sensor.{zone.id}_vwc"
        zone.pump_flow_rate_ml_per_sec = {"default": 10, "north": 5, "south": 10}[
            zone.id
        ]
        hass.states.async_set(zone.valves[0], "off")
        runtime = VWCIrrigationCoordinator(
            hass,
            entry,
            "tent",
            main,
            zone_id=zone.id,
            supply=runtimes[0] if runtimes else None,
        )
        if runtimes:
            runtimes[0].register_zone_runtime(runtime)
        runtimes.append(runtime)
    for runtime in runtimes:
        await runtime.async_setup()
    for zone in growspace.irrigation_zones:
        hass.states.async_set(zone.soil_moisture_sensor, "40")

    async def elapsed(seconds):
        freezer.tick(timedelta(seconds=seconds))
        await REAL_SLEEP(0)

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        side_effect=elapsed,
    ):
        yield growspace, runtimes, trace, plants
    await runtimes[0].async_unload()
    await hass.async_block_till_done()


async def tick(hass, runtimes):
    for runtime in runtimes:
        await runtime._update_loop(dt_util.now())
    task = runtimes[0]._supply_task
    if task is not None:
        await task
    await hass.async_block_till_done()


async def test_three_zones_one_lit_day(hass, freezer, zone_rig):
    growspace, runtimes, trace, plants = zone_rig
    freezer.move_to(at("06:01"))
    await tick(hass, runtimes)
    assert trace == ["default", "north", "south"], [
        (
            r._machine.current_phase,
            r._last_suppressed_by,
            r.startup_inhibit_reason(),
            r._live_plant_count(),
        )
        for r in runtimes
    ]
    attempts = runtimes[0]._deliveries.attempts
    assert [a.zone_id for a in attempts] == trace
    # Counts 1/2/3 at emitter rates 10/5/10 ml/s produce 1/4/3 seconds.
    assert [a.planned_s for a in attempts] == [1, 4, 3]
    assert all(a.outcome.value == "completed" and a.due_at for a in attempts)
    assert all(runtime.cycles_today == 3 for runtime in runtimes)
    assert all(
        runtime.volume_dispensed_today == pytest.approx(0.06) for runtime in runtimes
    )
    assert len({id(runtime._machine) for runtime in runtimes}) == 3
    assert len({id(runtime._composer) for runtime in runtimes}) == 3
    assert len({id(runtime._infiltration) for runtime in runtimes}) == 3
    assert all(
        zone.substrate_history.last_confirmed_shot_at
        for zone in growspace.irrigation_zones
    )

    freezer.move_to(at("08:00"))
    for zone in growspace.irrigation_zones:
        hass.states.async_set(
            zone.soil_moisture_sensor, "56" if zone.id == "default" else "40"
        )
    await tick(hass, runtimes)
    await tick(hass, runtimes)
    assert growspace.default_zone.substrate_history.p1_completed_on == DAY
    assert growspace.irrigation_zones[1].substrate_history.p1_completed_on is None
    assert growspace.default_zone.active_steering_phase == "p2"
    assert growspace.irrigation_zones[1].active_steering_phase == "p1"

    freezer.move_to(at("12:00"))
    for zone in growspace.irrigation_zones:
        hass.states.async_set(zone.soil_moisture_sensor, "56")
    await tick(hass, runtimes)
    assert all(
        zone.substrate_history.p1_completed_on == DAY
        for zone in growspace.irrigation_zones
    )
    freezer.move_to(at("13:00"))
    for zone in growspace.irrigation_zones:
        hass.states.async_set(zone.soil_moisture_sensor, "50")
    await tick(hass, runtimes)
    assert trace[-3:] == ["default", "north", "south"]
    assert all(
        a.trigger_evidence.phase == "P2" for a in runtimes[0]._deliveries.attempts[-3:]
    )
    assert all(runtime._pending_observation is not None for runtime in runtimes)
    # Physical membership follows a moved plant; the next composition sees it.
    plants[0].col = 2
    assert [runtime._live_plant_count() for runtime in runtimes] == [0, 3, 3]
    freezer.move_to(at("20:00"))
    for zone in growspace.irrigation_zones:
        hass.states.async_set(zone.soil_moisture_sensor, "50")
    before = len(trace)
    await tick(hass, runtimes)
    assert len(trace) == before
    assert all(
        zone.active_steering_phase == "p3" for zone in growspace.irrigation_zones
    )


async def test_one_zone_spends_the_shared_cap(hass, freezer, zone_rig):
    growspace, runtimes, trace, _plants = zone_rig
    growspace.irrigation_config.max_cycles_per_day = 1
    freezer.move_to(at("06:01"))
    await tick(hass, runtimes)
    assert trace == ["default"]
    attempts = runtimes[0]._deliveries.attempts
    assert [attempt.zone_id for attempt in attempts] == ["default", "north", "south"]
    assert [attempt.outcome.value for attempt in attempts] == [
        "completed",
        "suppressed",
        "suppressed",
    ]
    assert all(attempt.reason == "cycle_limit" for attempt in attempts[1:])


async def test_startup_probe_readiness_is_per_zone(hass, freezer, zone_rig):
    growspace, runtimes, _trace, _plants = zone_rig
    growspace.irrigation_config.startup_grace_minutes = 1
    # Pretend this probe has yet to report since the common startup instant.
    hass.states.async_remove("sensor.north_vwc")
    assert all(runtime.startup_inhibit_reason() is not None for runtime in runtimes)
    freezer.move_to(at("06:02"))
    for runtime in runtimes:
        await runtime._async_poll_startup_inhibit()
    assert runtimes[0].startup_inhibit_reason() is None
    assert runtimes[1].startup_inhibit_reason() is not None
    assert runtimes[2].startup_inhibit_reason() is None
    assert runtimes[0].controller_snapshot().state is ControllerState.READY
    assert runtimes[1].zone_snapshot().state is ControllerState.INHIBITED
    hass.states.async_set("sensor.north_vwc", "42")
    await runtimes[1]._async_poll_startup_inhibit()
    assert runtimes[1].startup_inhibit_reason() is None


async def test_refresh_adds_removes_zones_and_switches_to_schedule(
    hass, freezer, zone_rig
):
    growspace, runtimes, trace, _plants = zone_rig
    north = growspace.irrigation_zones[1]
    north.strategy.enabled = False
    north.irrigation_times = [{"time": "09:00:00", "duration": 2}]
    north.irrigation_duration = 2
    await runtimes[0].async_request_refresh()
    assert runtimes[1].next_scheduled_cycle is not None
    await runtimes[1]._handle_event(
        dt_util.now(), event_type="irrigation", event_data={}
    )
    await runtimes[0]._supply_task
    assert trace == ["north"]
    assert north.substrate_history.last_confirmed_shot_at
    assert growspace.default_zone.substrate_history.last_confirmed_shot_at is None
    # This zone's own minimum interval suppresses its next schedule claim.
    await runtimes[1]._handle_event(
        dt_util.now(), event_type="irrigation", event_data={}
    )
    await runtimes[0]._supply_task
    assert trace == ["north"]
    added = IrrigationZone(id="new", name="New", cells=[], valves=["switch.new_valve"])
    growspace.irrigation_zones.append(added)
    hass.states.async_set("switch.new_valve", "off")
    await runtimes[0].async_request_refresh()
    runtime = runtimes[0].zone_runtime("new")
    assert runtime is not None and runtime._supply is runtimes[0]
    growspace.irrigation_zones.remove(added)
    await runtimes[0].async_request_refresh()
    assert runtimes[0].zone_runtime("new") is None
    # Reset listeners remain registered after schedule refreshes.
    runtimes[1]._composer.size_factor = 2
    await runtimes[1]._async_reset_daily_counters()
    assert runtimes[1]._composer.size_factor == 1


async def test_zone_entity_inventory_preserves_implicit_identity(
    hass, zone_rig, snapshot
):
    from custom_components.growspace_manager.const import DOMAIN
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.sensor._setup import (
        _create_initial_entities,
    )
    from tests.common import MockConfigEntry

    growspace, _runtimes, _trace, _plants = zone_rig
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    entry.runtime_data = coordinator
    coordinator._data_repository.add_growspace(growspace)
    default_tracker = coordinator.services.growspaces.get_substrate_tracker("tent")
    assert default_tracker is coordinator.services.growspaces.get_substrate_tracker(
        "tent", "default"
    )
    assert default_tracker is not coordinator.services.growspaces.get_substrate_tracker(
        "tent", "north"
    )
    entities = []
    await _create_initial_entities(
        hass, coordinator, entry, entities, {}, {}, set(), set(), set()
    )
    assert sorted(entity.unique_id for entity in entities) == snapshot
    crops = [
        entity
        for entity in entities
        if entity.__class__.__name__ == "CropSteeringSensor"
    ]
    assert len(crops) == 3
    assert crops[0].unique_id == f"{DOMAIN}_tent_crop_steering"
    growspace.irrigation_zones.pop()
    assert not crops[-1].available
    assert crops[-1].native_value is None
    assert crops[-1].extra_state_attributes == {}


async def test_only_the_open_zone_reports_running(zone_rig):
    _growspace, runtimes, _trace, _plants = zone_rig
    supply = runtimes[0]
    supply._active_events["irrigation"] = {"zone_id": "north", "duration": 5}
    assert [runtime.zone_snapshot().state for runtime in runtimes] == [
        ControllerState.READY,
        ControllerState.RUNNING,
        ControllerState.READY,
    ]
    assert supply.controller_snapshot().state is ControllerState.RUNNING
    supply._active_events.clear()
    supply._active_events["drain"] = {"duration": 5}
    assert supply.controller_snapshot().state is ControllerState.RUNNING
    assert all(
        runtime.zone_snapshot().state is ControllerState.READY for runtime in runtimes
    )
    supply._active_events.clear()


async def test_manual_run_routes_to_named_zone_and_does_not_train(hass, zone_rig):
    _growspace, runtimes, trace, _plants = zone_rig
    await runtimes[0].async_manual_run(2, "grower", "north")
    await runtimes[0]._supply_task
    assert trace == ["north"]
    attempt = runtimes[0]._deliveries.attempts[-1]
    assert attempt.zone_id == "north" and attempt.trigger_evidence.user_id == "grower"
    assert all(runtime._pending_observation is None for runtime in runtimes)


async def test_removed_zone_claim_is_dropped_at_the_front(hass, zone_rig):
    growspace, runtimes, trace, _plants = zone_rig
    finished = asyncio.Event()
    running = hass.async_create_task(finished.wait())
    runtimes[0]._running_tasks["irrigation"] = running
    runtimes[1]._queue_supply_claim("schedule", dt_util.utcnow(), {"duration": 2})
    growspace.irrigation_zones.pop(1)
    await runtimes[0].async_request_refresh()
    finished.set()
    await runtimes[0]._supply_task
    assert not trace
    assert runtimes[0].supply_payload() == {"open_zone_id": None, "claims": []}


async def test_shared_tank_is_sampled_once_in_reliability(zone_rig):
    from custom_components.growspace_manager.models import IrrigationTank
    from custom_components.growspace_manager.reliability_store import ReliabilityCounter

    growspace, runtimes, _trace, _plants = zone_rig
    growspace.environment_config.irrigation_tanks = [
        IrrigationTank(name="Tank", sensor_entity="sensor.tank")
    ]
    main = runtimes[0]._main_coordinator
    main.reliability.record.reset_mock()
    for runtime in runtimes:
        runtime._async_probe_control_sensors()
    unavailable = [
        call
        for call in main.reliability.record.call_args_list
        if call.args[1] == ReliabilityCounter.SENSOR_UNAVAILABLE_MINUTES
    ]
    assert len(unavailable) == 1


async def test_subsystem_initializes_one_supply_with_three_runtimes(hass, zone_rig):
    from contextlib import ExitStack

    from custom_components.growspace_manager.managers.subsystem import SubsystemManager

    growspace, runtimes, _trace, _plants = zone_rig
    manager = SubsystemManager(
        hass, runtimes[0]._main_coordinator, runtimes[0]._config_entry
    )
    with ExitStack() as stack:
        for name in (
            "LightCycleTracker",
            "DehumidifierCoordinator",
            "HumidifierCoordinator",
            "CirculationFanCoordinator",
            "ExhaustFanCoordinator",
            "GrowLightCoordinator",
        ):
            mock = stack.enter_context(
                patch(f"custom_components.growspace_manager.managers.subsystem.{name}")
            )
            mock.return_value.async_setup = AsyncMock()
        await manager.async_setup_growspace_sub_coordinators("tent", growspace)
        supply = manager.irrigation_coordinators["tent"]
        assert [
            supply.zone_runtime(zone.id)._zone.id for zone in growspace.irrigation_zones
        ] == ["default", "north", "south"]
        manager.teardown_growspace_sub_coordinators("tent")


async def test_new_zone_entities_are_added_once(hass, zone_rig):
    from custom_components.growspace_manager.const import DOMAIN
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.sensor._setup import (
        _update_growspace_entities,
    )
    from tests.common import MockConfigEntry

    growspace, _runtimes, _trace, _plants = zone_rig
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    entry.runtime_data = coordinator
    coordinator._data_repository.add_growspace(growspace)
    ids = {f"{DOMAIN}_tent_crop_steering"}
    added = []
    overview = {"tent": MagicMock()}
    await _update_growspace_entities(
        hass, coordinator, entry, overview, added.extend, set(), set(), ids
    )
    assert [entity.unique_id for entity in added] == [
        f"{DOMAIN}_tent_north_crop_steering",
        f"{DOMAIN}_tent_south_crop_steering",
    ]
    await _update_growspace_entities(
        hass, coordinator, entry, overview, added.extend, set(), set(), ids
    )
    assert len(added) == 2


async def test_a_new_drain_replaces_the_previous_drain(hass, zone_rig):
    growspace, runtimes, trace, _plants = zone_rig
    growspace.irrigation_config.drain_pump_entity = "switch.drain"
    growspace.irrigation_config.drain_duration = 1
    hass.states.async_set("switch.drain", "off")
    running = hass.async_create_task(asyncio.Event().wait())
    runtimes[0]._running_tasks["drain"] = running
    await runtimes[0]._handle_event(dt_util.utcnow(), event_type="drain", event_data={})
    await runtimes[0]._running_tasks["drain"]
    assert running.cancelled()
    assert trace == []
    assert runtimes[0]._deliveries.attempts[-1].zone_id is None


async def test_degraded_zone_holds_only_its_shots_and_manual_keeps_the_caps(
    hass, freezer, zone_rig
):
    growspace, runtimes, trace, _plants = zone_rig
    north = runtimes[1]
    _ = north.control_measurement
    north._response_watch.failures = 3
    north._response_watch.unresponsive_since = dt_util.utcnow()
    freezer.move_to(at("06:01"))
    await tick(hass, runtimes)
    assert trace == ["default", "south"]
    assert north.zone_snapshot().state is ControllerState.INHIBITED
    assert [r.code for r in north.zone_snapshot().reasons] == ["probe_unresponsive"]
    assert north.current_vwc is None
    await runtimes[0].async_manual_run(2, "grower", "north")
    await runtimes[0]._supply_task
    assert trace == ["default", "south", "north"]
    assert north._pending_observation is None
    assert north._response_watch.failures == 3
    growspace.irrigation_config.max_cycles_per_day = 3
    await runtimes[0].async_manual_run(2, "grower", "north")
    await runtimes[0]._supply_task
    assert trace == ["default", "south", "north"]
    assert runtimes[0]._deliveries.attempts[-1].reason == "cycle_limit"
