"""ADR-0060: seven days at the full envelope, using the real supply effects.

Only physical waits and disk I/O are stubbed. Tick timing includes the sensor
and steering callbacks across the instance; asynchronous supply tasks drain
outside that timing, as they do outside the minute callback in production.
Every synchronous and delayed store write is serialized with HA's encoder.
"""

import asyncio
from collections import Counter
from datetime import datetime, timedelta
import logging
import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from freezegun import api as freezegun_api
import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.delivery_attempt_store import (
    DeliveryAttemptStore,
)
from custom_components.growspace_manager.domain.delivery_attempt import ROW_LIMIT
from custom_components.growspace_manager.domain.zone_edit import (
    MAX_PROBES_PER_QUANTITY,
    MAX_ZONES_PER_GROWSPACE,
)
from custom_components.growspace_manager.envelope import (
    CONFIRMATION_OVERHEAD_SECONDS,
    DEFAULT_INTERVAL_SECONDS,
    MAX_ENVELOPE_SHOT_SECONDS,
    MAX_IRRIGATED_GROWSPACES,
)
from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationConfig,
    IrrigationZone,
    SteeringStrategy,
)
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from custom_components.growspace_manager.substrate_tracker import SubstrateTracker
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.core import callback
from homeassistant.helpers.json import prepare_save_json
from homeassistant.util import dt as dt_util

REAL_SLEEP = asyncio.sleep
DAYS = 7
SHOTS_PER_DAY = 40
WRITE_LIMIT_BYTES = 150_000


def test_pump_time_is_derived_from_runtime_constants():
    assert SteeringStrategy().p1_shot_interval_minutes * 60 == DEFAULT_INTERVAL_SECONDS
    assert CONFIRMATION_OVERHEAD_SECONDS == 32
    assert (
        MAX_ZONES_PER_GROWSPACE
        * (MAX_ENVELOPE_SHOT_SECONDS + CONFIRMATION_OVERHEAD_SECONDS)
        <= DEFAULT_INTERVAL_SECONDS
    )


class MeasuredStore:
    """A stub disk that checks every payload, including coalesced closes."""

    def __init__(self, deliveries):
        self.deliveries = deliveries
        self.maximum_bytes = 0
        self.writes = 0
        self.today_ids = set()
        self.day = None
        self.last_document = None

    async def async_save(self, document):
        self.measure(document)

    def async_delay_save(self, document, delay):
        # The most conservative batching: check even intermediate close writes.
        self.measure(document())

    def measure(self, document):
        _mode, encoded = prepare_save_json(
            {
                "version": 1,
                "minor_version": 1,
                "key": self.deliveries._key,
                "data": document,
            }
        )
        size = len(encoded.encode() if isinstance(encoded, str) else encoded)
        self.maximum_bytes = max(size, self.maximum_bytes)
        assert size <= WRITE_LIMIT_BYTES, (self.deliveries.growspace_id, size)
        rows = self.deliveries.attempts
        assert len(rows) <= ROW_LIMIT
        today = dt_util.now().date()
        if today != self.day:
            self.today_ids.clear()
            self.day = today
        ids = {a.attempt_id for a in rows if a.charge_date == today}
        assert self.today_ids <= ids, "a charged row dated today was evicted"
        self.today_ids = ids
        self.last_document = document
        self.writes += 1


@pytest.fixture
async def envelope_rig(hass, freezer):
    start = datetime(2026, 6, 15, tzinfo=dt_util.UTC)
    freezer.move_to(start)

    def noop(*args, **kwargs):
        return None

    async def async_noop(*args, **kwargs):
        return None

    main = SimpleNamespace(
        growspaces={},
        reliability=ReliabilityStore(hass, "envelope"),
        data={},
        async_commit=async_noop,
        async_project_water=async_noop,
        async_refresh_growspace_data=async_noop,
        async_schedule_save=noop,
        async_set_updated_data=noop,
        async_update_listeners=noop,
        add_event=noop,
        services=SimpleNamespace(
            config=SimpleNamespace(ec_ramp_curves={}),
            notifications=SimpleNamespace(
                manager=SimpleNamespace(async_send_notification=async_noop)
            ),
            growspaces=SimpleNamespace(get_growspace_plants=lambda gs: []),
        ),
        deliveries=DeliveryAttemptStore(hass, "envelope"),
    )
    entry = MagicMock()
    entry.runtime_data = main
    entry.async_create_background_task.side_effect = lambda ha, target, name: (
        ha.async_create_task(target)
    )
    runtimes, supplies, stores = [], [], []
    commands = Counter()
    outputs = {}

    @callback
    def actuate(call):
        output = call.data["entity_id"]
        gs = outputs[output]
        if (
            output == gs.irrigation_config.irrigation_pump_entity
            and call.service == "turn_on"
        ):
            opened = [
                z.id
                for z in gs.irrigation_zones
                if hass.states.get(z.valves[0]).state == "on"
            ]
            assert len(opened) == 1, "a supply must serve exactly one zone"
            commands[(gs.id, opened[0], dt_util.now().date())] += 1
        hass.states.async_set(output, "on" if call.service == "turn_on" else "off")

    for service in ("turn_on", "turn_off"):
        hass.services.async_register("switch", service, actuate)
    for service in ("create", "dismiss"):
        hass.services.async_register(
            "persistent_notification", service, lambda call: None
        )
    for i in range(MAX_IRRIGATED_GROWSPACES):
        gs = Growspace(
            id=f"tent_{i}",
            name=f"Tent {i}",
            rows=1,
            plants_per_row=MAX_ZONES_PER_GROWSPACE,
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity=f"switch.pump_{i}",
                startup_grace_minutes=0,
                max_cycles_per_day=MAX_ZONES_PER_GROWSPACE * SHOTS_PER_DAY,
            ),
        )
        gs.environment_config.veg_day_hours = 10
        gs.environment_config.flower_day_hours = 10
        gs.light_cycle.lights_on_time = "06:00:00"
        main.growspaces[gs.id] = gs
        gs.irrigation_zones = [
            IrrigationZone(
                id="default" if j == 0 else f"zone_{j}",
                name=f"Zone {j}",
                cells=[(1, j + 1)],
            )
            for j in range(MAX_ZONES_PER_GROWSPACE)
        ]
        deliveries = await main.deliveries.async_load(gs.id)
        deliveries._store = store = MeasuredStore(deliveries)
        stores.append(store)
        supply = None
        for j, zone in enumerate(gs.irrigation_zones):
            prefix = f"{i}_{j}"
            zone.valves = [f"switch.valve_{prefix}"]
            zone.soil_moisture_sensor = f"sensor.vwc_{prefix}_0"
            zone.moisture_witness_sensors = [
                f"sensor.vwc_{prefix}_{k}" for k in range(1, MAX_PROBES_PER_QUANTITY)
            ]
            zone.pore_ec_sensors = [
                f"sensor.ec_{prefix}_{k}" for k in range(MAX_PROBES_PER_QUANTITY)
            ]
            zone.strategy.enabled = True
            zone.strategy.p0_duration_minutes = 0
            zone.strategy.p2_stop_before_lights_off_minutes = 0
            zone.strategy.p1_shot_duration_seconds = 1
            zone.strategy.p2_shot_duration_seconds = 1
            zone.strategy.dynamic_shot_enabled = False
            zone.irrigation_duration = 1
            zone.pump_flow_rate_ml_per_sec = 10
            for output in [gs.irrigation_config.irrigation_pump_entity, *zone.valves]:
                outputs[output] = gs
                hass.states.async_set(output, "off")
            runtime = VWCIrrigationCoordinator(
                hass, entry, gs.id, main, zone_id=zone.id, supply=supply
            )
            if supply is None:
                supply = runtime
                supplies.append(runtime)
            else:
                supply.register_zone_runtime(runtime)
            runtimes.append(runtime)
            await runtime.async_setup()
    trackers = {
        (r._growspace_id, r._zone.id): SubstrateTracker(r.growspace, r._zone.id)
        for r in runtimes
    }
    main.services.growspaces.get_substrate_tracker = lambda gs, zone=None: trackers[
        (gs, zone or "default")
    ]

    async def elapsed(seconds):
        # Device waits complete instantly; only minute ticks advance fake time.
        await REAL_SLEEP(0)

    main.reliability._store = MagicMock()

    # Suppress HA state-event scheduling; callbacks below receive every report
    # explicitly, so listener task buildup is not a hidden part of the benchmark.
    for runtime in runtimes:
        runtime.async_cancel_listeners(cancel_tasks=False)
    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        side_effect=elapsed,
    ):
        yield start, runtimes, supplies, stores, commands, main
    for supply in supplies:
        await supply.async_unload()
    await hass.async_block_till_done()


@pytest.mark.no_cover
async def test_seven_days_at_full_envelope(
    hass, freezer, envelope_rig, record_property
):
    start, runtimes, supplies, stores, commands, _main = envelope_rig
    samples = []
    for minute in range(DAYS * 24 * 60):
        if minute % 1440 == 0:
            logging.getLogger(__name__).info(
                "Envelope simulation day %s/%s", minute // 1440 + 1, DAYS
            )
        instant = start + timedelta(minutes=minute)
        freezer.move_to(instant)
        for runtime in runtimes:
            zone = runtime._zone
            for entity in [zone.soil_moisture_sensor, *zone.moisture_witness_sensors]:
                hass.states.async_set(entity, str(40 if minute % 15 == 0 else 42))
            for entity in zone.pore_ec_sensors:
                hass.states.async_set(entity, "1.5")
        began = freezegun_api.real_perf_counter()
        for runtime in runtimes:
            await runtime._async_sensor_tick()
            await runtime._update_loop(instant)
        samples.append((freezegun_api.real_perf_counter() - began) * 1000)
        await asyncio.gather(
            *(s._supply_task for s in supplies if s._supply_task is not None)
        )
    p99 = sorted(samples)[math.ceil(len(samples) * 0.99) - 1]
    record_property("instance_minute_tick_p99_ms", p99)
    assert p99 <= 100, f"instance minute-tick p99: {p99:.2f} ms"
    assert len(commands) == MAX_IRRIGATED_GROWSPACES * MAX_ZONES_PER_GROWSPACE * DAYS
    assert set(commands.values()) == {SHOTS_PER_DAY}
    for store in stores:
        deliveries = store.deliveries
        assert (
            len(deliveries.attempts) == MAX_ZONES_PER_GROWSPACE * SHOTS_PER_DAY * DAYS
        )
        assert all(a.outcome.value == "completed" for a in deliveries.attempts)
        restored = deliveries._decode(store.last_document)
        assert restored == deliveries.attempts
        record_property(
            f"{deliveries.growspace_id}_max_write_bytes", store.maximum_bytes
        )


async def test_envelope_zone_entities(hass, envelope_rig, snapshot):
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.sensor._setup import (
        _create_initial_entities,
    )
    from tests.common import MockConfigEntry

    _start, _runtimes, _supplies, _stores, _commands, main = envelope_rig
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    entry.runtime_data = coordinator
    coordinator._data_repository.add_growspace(main.growspaces["tent_0"])
    entities = []
    await _create_initial_entities(
        hass, coordinator, entry, entities, {}, {}, set(), set(), set()
    )
    assert (
        sum(type(entity).__name__ == "CropSteeringSensor" for entity in entities)
        == MAX_ZONES_PER_GROWSPACE
    )
    assert sorted(entity.unique_id for entity in entities) == snapshot
