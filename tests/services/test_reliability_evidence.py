"""Durable reliability evidence and the user-requested export shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
)
from custom_components.growspace_manager.reliability_store import (
    MAX_KEYS_PER_FAMILY,
    SAVE_DELAY_SECONDS,
    ReliabilityCounter,
    ReliabilityStore,
    automated_seconds,
    inhibited,
    skipped,
)
from custom_components.growspace_manager.sensor.reliability import (
    GrowspaceReliabilitySensor,
)
from custom_components.growspace_manager.services.report import (
    handle_export_reliability_evidence,
)
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE, MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.dt import utcnow

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


async def test_reliability_survives_restart_and_bounds_recent_buckets(
    hass: HomeAssistant,
) -> None:
    """Lifetime survives the 30-day cutoff while recent buckets expire."""
    store = ReliabilityStore(hass, "evidence")
    store.record("tent", ReliabilityCounter.REQUESTED, at=NOW - timedelta(days=31))
    store.record("tent", ReliabilityCounter.REQUESTED, at=NOW - timedelta(hours=2))
    store.record("tent", ReliabilityCounter.REQUESTED, at=NOW)
    store.record("tent", ReliabilityCounter.OBSERVED_MINUTES, 4, at=NOW)
    store.record("tent", ReliabilityCounter.AUTOMATION_ELIGIBLE_MINUTES, 3, at=NOW)
    store.record("tent", ReliabilityCounter.FAULT_LATCHED, at=NOW)
    store.mark_active("tent", "switch.pump")
    # The shutdown flush is what persists a delayed save.
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()

    restarted = ReliabilityStore(hass, "evidence")
    await restarted.async_load()
    assert restarted.active_outputs("tent") == ("switch.pump",)
    snapshot = restarted.snapshot("tent", at=NOW)
    assert snapshot["lifetime"]["irrigation.requested"] == 3
    assert snapshot["last_24h"]["irrigation.requested"] == 2
    assert snapshot["last_30d"]["irrigation.requested"] == 2
    assert snapshot["lifetime"]["runtime.automation_uptime_percent"] == 75
    assert snapshot["days_since_last_fault"] == 0
    assert len(restarted._data["tent"]["days"]) == 1
    restarted.clear_active("tent", "switch.pump")
    assert restarted.active_outputs("tent") == ()


async def test_recording_never_waits_on_the_disk(hass: HomeAssistant) -> None:
    """A counter is visible at once; its write is coalesced, a marker's is not."""
    store = ReliabilityStore(hass, "delayed")
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    store._store.async_delay_save = MagicMock()

    store.record("tent", ReliabilityCounter.REQUESTED)
    store.mark_active("tent", "switch.pump")
    store.clear_active("tent", "switch.pump")
    store.clear_active("tent", "switch.pump")
    store.clear_active("missing", "switch.pump")

    assert store.snapshot("tent")["lifetime"]["irrigation.requested"] == 1
    store._store.async_save.assert_not_awaited()
    assert [call.args[1] for call in store._store.async_delay_save.call_args_list] == [
        SAVE_DELAY_SECONDS,
        0,
        SAVE_DELAY_SECONDS,
    ]
    (data_func, _delay) = store._store.async_delay_save.call_args.args
    assert data_func() is store._data


async def test_unreadable_evidence_is_not_overwritten(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed record is logged once, and nothing is ever written over it."""
    store = ReliabilityStore(hass, "corrupt")
    store._store.async_load = AsyncMock(
        return_value={"tent": {"lifetime": {"irrigation.requested": -1}}}
    )
    store._store.async_delay_save = MagicMock()
    await store.async_load()
    assert store.snapshot("tent")["unreadable"] is True

    caplog.clear()
    for _ in range(3):
        store.record("tent", ReliabilityCounter.REQUESTED)
    store.mark_active("tent", "switch.pump")
    store.clear_active("tent", "switch.pump")
    store.record_start(["tent"])

    store._store.async_delay_save.assert_not_called()
    assert caplog.records == []


@pytest.mark.parametrize(
    "record",
    [
        [],
        {1: {}},
        {"tent": {"active": []}},
        {"tent": {"last_fault_at": 123}},
        {"tent": {"last_fault_at": "2026-09-24T12:00:00"}},
        {"tent": {"lifetime": []}},
        {"tent": {"minutes": {"bucket": []}}},
    ],
)
async def test_invalid_reliability_documents_are_preserved(
    hass: HomeAssistant, record: object
) -> None:
    """Reject invalid persisted structures without replacing their file."""
    store = ReliabilityStore(hass, "invalid-document")
    store._store.async_load = AsyncMock(return_value=record)
    store._store.async_delay_save = MagicMock()

    await store.async_load()

    assert store.unreadable
    store._store.async_delay_save.assert_not_called()


@pytest.mark.parametrize("present", [False, True])
async def test_missing_and_undecodable_reliability_file(
    hass: HomeAssistant, present: bool
) -> None:
    """Only a genuinely missing store initializes an empty record."""
    store = ReliabilityStore(hass, "load-none")
    store._store.async_load = AsyncMock(return_value=None)
    with patch(
        "custom_components.growspace_manager.reliability_store.exists",
        return_value=present,
    ):
        await store.async_load()
    assert store.unreadable is present


@pytest.mark.parametrize(
    ("counter", "amount"),
    [
        ("", 1),
        (ReliabilityCounter.REQUESTED, float("nan")),
        (ReliabilityCounter.REQUESTED, float("inf")),
        (ReliabilityCounter.REQUESTED, -1),
        (ReliabilityCounter.REQUESTED, True),
    ],
)
async def test_invalid_increments_are_dropped(
    hass: HomeAssistant, counter: str, amount: Any
) -> None:
    """An increment that cannot be stored is logged and never raises."""
    store = ReliabilityStore(hass, "increments")
    store.record("tent", counter, amount)
    assert store.snapshot("tent")["lifetime"] == {
        "runtime.automation_uptime_percent": None
    }


@pytest.mark.parametrize("family", [skipped, inhibited, automated_seconds])
async def test_open_counter_families_are_bounded(
    hass: HomeAssistant, family: Any
) -> None:
    """A new reason or actuator past the limit folds into ``<family>.other``."""
    store = ReliabilityStore(hass, "families")
    names = [family(f"key_{index}") for index in range(MAX_KEYS_PER_FAMILY + 2)]
    for name in names:
        store.record("tent", name)
    store.record("tent", names[0])

    counters = store.snapshot("tent")["lifetime"]
    other = family("other")
    assert counters[other] == 2
    assert counters[names[0]] == 2
    prefix = other.removesuffix("other")
    assert len([key for key in counters if key.startswith(prefix)]) == (
        MAX_KEYS_PER_FAMILY + 1
    )


async def test_start_is_counted_once_and_removed_growspaces_are_dropped(
    hass: HomeAssistant,
) -> None:
    """A start counts once per process and forgets growspaces that are gone."""
    store = ReliabilityStore(hass, "starts")
    store.record("removed", ReliabilityCounter.REQUESTED)
    store.mark_active("tent", "switch.pump")

    store.record_start(["tent", "veg"])
    store.record_start(["tent", "veg"])

    assert "removed" not in store._data
    tent = store.snapshot("tent")["lifetime"]
    assert tent[ReliabilityCounter.HA_START] == 1
    assert tent[ReliabilityCounter.HA_START_INFLIGHT] == 1
    assert store.active_outputs("tent") == ()
    veg = store.snapshot("veg")["lifetime"]
    assert veg[ReliabilityCounter.HA_START] == 1
    assert ReliabilityCounter.HA_START_INFLIGHT not in veg


async def test_reliability_export_shape(
    hass: HomeAssistant, snapshot: SnapshotAssertion
) -> None:
    """The response service returns the documented, versioned document."""
    store = ReliabilityStore(hass, "export")
    store.record("tent", ReliabilityCounter.REQUESTED, at=NOW - timedelta(days=3))
    store.record("tent", ReliabilityCounter.COMPLETED_VERIFIED, at=NOW)
    store.record("tent", skipped("dark"), at=NOW)
    store.record("tent", ReliabilityCounter.OBSERVED_MINUTES, 2, at=NOW)
    store.record("tent", ReliabilityCounter.AUTOMATION_ELIGIBLE_MINUTES, at=NOW)
    store.record("tent", ReliabilityCounter.FAULT_LATCHED, at=NOW - timedelta(days=2))
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": MagicMock()}
    coordinator.reliability = store
    call = MagicMock()
    call.data = {"growspace_id": "tent"}

    with freeze_time(NOW):
        result = await handle_export_reliability_evidence(hass, coordinator, call)
    assert result == snapshot

    call.data = {"growspace_id": "missing"}
    with pytest.raises(ServiceValidationError, match="Unknown growspace"):
        await handle_export_reliability_evidence(hass, coordinator, call)


async def test_reliability_sensor_shows_key_counters_unrecorded(
    hass: HomeAssistant, snapshot: SnapshotAssertion
) -> None:
    """The entity carries key counters only, and the Recorder keeps none of them."""
    store = ReliabilityStore(hass, "sensor")
    store.record("tent", ReliabilityCounter.COMPLETED_VERIFIED)
    store.record("tent", ReliabilityCounter.REQUESTED)
    coordinator = MagicMock()
    coordinator.reliability = store
    coordinator.last_update_success = True

    sensor = GrowspaceReliabilitySensor(coordinator, "tent", "Demo Tent")

    assert sensor.native_value == 1
    assert sensor.extra_state_attributes == snapshot
    assert sensor._unrecorded_attributes == frozenset({MATCH_ALL})
    assert sensor.available

    store.record("tent", ReliabilityCounter.COMPLETED_VERIFIED)
    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
    assert sensor.native_value == 2

    store.unreadable = True
    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()
    assert not sensor.available
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def _probe(hass: HomeAssistant, growspace: Growspace) -> IrrigationCoordinator:
    runtime = MagicMock()
    runtime.reliability = ReliabilityStore(hass, "sensor-probe")
    runtime.irrigation_safety = None
    runtime.growspaces = {growspace.id: growspace}
    return IrrigationCoordinator(
        hass, MagicMock(runtime_data=runtime), growspace.id, runtime
    )


def _lifetime(irrigation: IrrigationCoordinator) -> dict[str, Any]:
    return irrigation._reliability.snapshot("tent")["lifetime"]


async def test_control_sensor_probe_counts_unavailable_and_implausible_edges(
    hass: HomeAssistant,
) -> None:
    """Each missing minute counts, and one bad value is one implausible edge."""
    irrigation = _probe(
        hass,
        Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.vwc"),
            irrigation_strategy=IrrigationStrategy(enabled=True),
        ),
    )
    irrigation._async_probe_control_sensors()
    assert _lifetime(irrigation)["sensors.control_unavailable_minutes"] == 1

    hass.states.async_set("sensor.vwc", "101")
    irrigation._async_probe_control_sensors()
    irrigation._async_probe_control_sensors()
    hass.states.async_set("sensor.vwc", "40")
    irrigation._async_probe_control_sensors()
    hass.states.async_set("sensor.vwc", "nan")
    irrigation._async_probe_control_sensors()
    counters = _lifetime(irrigation)
    assert counters["sensors.implausible_readings"] == 2
    assert counters["sensors.control_unavailable_minutes"] == 1
    assert counters["runtime.observed_minutes"] == 5


def _quiet_state(value: str, *, minutes: float) -> MagicMock:
    state = MagicMock()
    state.state = value
    state.last_changed = state.last_reported = utcnow() - timedelta(minutes=minutes)
    return state


@pytest.mark.parametrize(
    ("stale_after_minutes", "quiet_minutes", "stale_events"),
    [(120, 121, 1), (120, 60, 0), (0, 10_000, 0)],
)
async def test_control_sensor_probe_uses_each_tanks_staleness_window(
    hass: HomeAssistant,
    stale_after_minutes: int,
    quiet_minutes: float,
    stale_events: int,
) -> None:
    """A tank is stale only past its own window, and never when that is off."""
    irrigation = _probe(
        hass,
        Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(
                irrigation_tanks=[
                    IrrigationTank(
                        name="Feed",
                        sensor_entity="sensor.tank",
                        stale_after_minutes=stale_after_minutes,
                    )
                ]
            ),
        ),
    )
    quiet = _quiet_state("50", minutes=quiet_minutes)
    with patch.object(type(hass.states), "get", return_value=quiet):
        irrigation._async_probe_control_sensors()
        irrigation._async_probe_control_sensors()

    assert _lifetime(irrigation).get("sensors.stale_events", 0) == stale_events


async def test_control_sensor_probe_counts_implausible_tanks(
    hass: HomeAssistant,
) -> None:
    """A tank outside 0-100 % is implausible, like the moisture sensor."""
    irrigation = _probe(
        hass,
        Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(
                irrigation_tanks=[IrrigationTank(name="Feed", sensor_entity="sensor.t")]
            ),
        ),
    )
    hass.states.async_set("sensor.t", "140")
    irrigation._async_probe_control_sensors()
    assert _lifetime(irrigation)["sensors.implausible_readings"] == 1


async def test_moisture_sensor_is_never_stale(hass: HomeAssistant) -> None:
    """No staleness window is configured for moisture, so a quiet one is valid."""
    irrigation = _probe(
        hass,
        Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.vwc"),
            irrigation_strategy=IrrigationStrategy(enabled=True),
        ),
    )
    quiet = _quiet_state("50", minutes=10_000)
    with patch.object(type(hass.states), "get", return_value=quiet):
        irrigation._async_probe_control_sensors()
    assert "sensors.stale_events" not in _lifetime(irrigation)


async def test_armed_runtime_and_unexpected_on_are_observed(
    hass: HomeAssistant,
) -> None:
    """Sample eligibility and record a pump already ON at startup."""
    growspace = Growspace(
        id="tent",
        name="Tent",
        irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
    )
    safety = IrrigationSafetyStore(hass, "armed-observation")
    await safety.async_load()
    await safety.async_initialize_controls({"tent": growspace})
    await safety.async_set_control("tent", "irrigation_armed", True, "operator")
    runtime = MagicMock()
    runtime.irrigation_safety = safety
    runtime.reliability = ReliabilityStore(hass, "armed-observation")
    runtime.growspaces = {"tent": growspace}
    irrigation = IrrigationCoordinator(
        hass, MagicMock(runtime_data=runtime), "tent", runtime
    )
    hass.states.async_set("switch.pump", "on")

    irrigation._async_probe_control_sensors()
    with patch.object(irrigation, "_async_record_controller_state", new=AsyncMock()):
        await irrigation._async_begin_startup_inhibit()
    irrigation.async_cancel_listeners()

    counters = _lifetime(irrigation)
    assert counters["runtime.automation_eligible_minutes"] == 1
    assert counters["irrigation.readback.unexpected_on"] == 1
