"""Durable reliability evidence and the user-requested export shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
)
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from custom_components.growspace_manager.sensor.reliability import (
    GrowspaceReliabilitySensor,
)
from custom_components.growspace_manager.services.report import (
    handle_export_reliability_evidence,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.dt import utcnow


async def test_reliability_survives_restart_and_bounds_recent_buckets(
    hass: HomeAssistant,
) -> None:
    """Lifetime survives the 30-day cutoff while recent buckets expire."""
    now = datetime(2026, 9, 24, 12, tzinfo=UTC)
    store = ReliabilityStore(hass, "evidence")
    await store.async_add("tent", "irrigation.requested", at=now - timedelta(days=31))
    await store.async_add("tent", "irrigation.requested", at=now - timedelta(hours=2))
    await store.async_add("tent", "irrigation.requested", at=now)
    await store.async_add("tent", "runtime.observed_minutes", 4, at=now)
    await store.async_add("tent", "runtime.automation_eligible_minutes", 3, at=now)
    await store.async_add("tent", "controller.fault_latched", at=now)
    await store.async_set_active("tent", "switch.pump", True)

    restarted = ReliabilityStore(hass, "evidence")
    await restarted.async_load()
    assert restarted.active_outputs("tent") == ("switch.pump",)
    snapshot = restarted.snapshot("tent", at=now)
    assert snapshot["lifetime"]["irrigation.requested"] == 3
    assert snapshot["last_24h"]["irrigation.requested"] == 2
    assert snapshot["last_30d"]["irrigation.requested"] == 2
    assert snapshot["lifetime"]["runtime.automation_uptime_percent"] == 75
    assert snapshot["days_since_last_fault"] == 0
    assert len(restarted._data["tent"]["days"]) == 1
    await restarted.async_set_active("tent", "switch.pump", False)
    assert restarted.active_outputs("tent") == ()


async def test_failed_reliability_write_does_not_publish_counter(
    hass: HomeAssistant,
) -> None:
    """A failed atomic write leaves the in-memory export unchanged."""
    store = ReliabilityStore(hass, "write-failure")
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError, match="disk full"):
        await store.async_add("tent", "irrigation.requested")
    assert "irrigation.requested" not in store.snapshot("tent")["lifetime"]


async def test_unreadable_evidence_is_not_overwritten(hass: HomeAssistant) -> None:
    """A malformed persisted record leaves control running but holds evidence."""
    store = ReliabilityStore(hass, "corrupt")
    store._store.async_load = AsyncMock(
        return_value={"tent": {"lifetime": {"irrigation.requested": -1}}}
    )
    store._store.async_save = AsyncMock()
    await store.async_load()
    assert store.snapshot("tent")["unreadable"] is True
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_add("tent", "irrigation.requested")
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_set_active("tent", "switch.pump", True)
    store._store.async_save.assert_not_awaited()


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
    store._store.async_save = AsyncMock()

    await store.async_load()

    assert store.unreadable
    store._store.async_save.assert_not_awaited()


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


async def test_failed_reliability_writes_restore_previous_record(
    hass: HomeAssistant,
) -> None:
    """A failed counter or marker write does not change the exported snapshot."""
    store = ReliabilityStore(hass, "rollback")
    await store.async_add("tent", "irrigation.requested")
    previous = store.snapshot("tent")["lifetime"]
    store._store.async_save = AsyncMock(side_effect=OSError("full"))

    with pytest.raises(OSError, match="full"):
        await store.async_add("tent", "irrigation.requested")
    with pytest.raises(OSError, match="full"):
        await store.async_set_active("tent", "switch.pump", True)
    with pytest.raises(OSError, match="full"):
        await store.async_set_active("new", "switch.pump", True)

    assert store.snapshot("tent")["lifetime"] == previous
    assert store.active_outputs("tent") == ()
    assert "new" not in store._data


async def test_reliability_rejects_invalid_increments_and_bounds_actuators(
    hass: HomeAssistant,
) -> None:
    """Unexpected values cannot enter storage and actuator keys stay bounded."""
    store = ReliabilityStore(hass, "increments")
    for counter, amount in (("", 1), ("irrigation.requested", float("nan"))):
        with pytest.raises(ValueError, match="Invalid reliability increment"):
            await store.async_add("tent", counter, amount)
    for index in range(17):
        await store.async_add("tent", f"runtime.automated_seconds.switch.pump_{index}")
    counters = store.snapshot("tent")["lifetime"]
    assert counters["runtime.automated_seconds.other"] == 1
    assert (
        len([key for key in counters if key.startswith("runtime.automated_seconds.")])
        == 17
    )


async def test_reliability_export_and_sensor(hass: HomeAssistant) -> None:
    """The response service and entity expose the same versioned summary."""
    store = ReliabilityStore(hass, "export")
    await store.async_add("tent", "irrigation.completed_verified")
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": MagicMock()}
    coordinator.reliability = store
    call = MagicMock()
    call.data = {"growspace_id": "tent"}

    result = await handle_export_reliability_evidence(hass, coordinator, call)
    assert set(result) == {
        "schema_version",
        "unreadable",
        "growspace_id",
        "as_of",
        "lifetime",
        "days_since_last_fault",
        "last_24h",
        "last_30d",
    }
    assert result["schema_version"] == 1
    assert result["lifetime"]["irrigation.completed_verified"] == 1
    sensor = GrowspaceReliabilitySensor(coordinator, "tent", "Demo Tent")
    assert sensor.native_value == 1
    assert (
        sensor.extra_state_attributes["last_24h"]["irrigation.completed_verified"] == 1
    )
    store.unreadable = True
    assert not sensor.available
    assert sensor.native_value is None

    call.data = {"growspace_id": "missing"}
    with pytest.raises(ServiceValidationError, match="Unknown growspace"):
        await handle_export_reliability_evidence(hass, coordinator, call)


async def test_control_sensor_probe_counts_unavailable_and_implausible_edges(
    hass: HomeAssistant,
) -> None:
    """The effects shell counts each missing minute and one bad-value edge."""
    runtime = MagicMock()
    runtime.reliability = ReliabilityStore(hass, "sensor-probe")
    runtime.irrigation_safety = None
    runtime.growspaces = {
        "tent": Growspace(
            id="tent",
            name="Tent",
            environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.vwc"),
            irrigation_strategy=IrrigationStrategy(enabled=True),
        )
    }
    entry = MagicMock(runtime_data=runtime)
    irrigation = IrrigationCoordinator(hass, entry, "tent", runtime)
    await irrigation._async_probe_control_sensors()
    assert (
        runtime.reliability.snapshot("tent")["lifetime"][
            "sensors.control_unavailable_minutes"
        ]
        == 1
    )

    hass.states.async_set("sensor.vwc", "101")
    await irrigation._async_probe_control_sensors()
    await irrigation._async_probe_control_sensors()
    counters = runtime.reliability.snapshot("tent")["lifetime"]
    assert counters["sensors.implausible_readings"] == 1
    assert counters["runtime.observed_minutes"] == 3

    old_state = MagicMock()
    old_state.state = "50"
    old_state.last_reported = utcnow() - timedelta(minutes=6)
    with patch.object(type(hass.states), "get", return_value=old_state):
        await irrigation._async_probe_control_sensors()
        await irrigation._async_probe_control_sensors()
    counters = runtime.reliability.snapshot("tent")["lifetime"]
    assert counters["sensors.stale_events"] == 1


async def test_pump_reliability_failure_does_not_interrupt_control(
    hass: HomeAssistant,
) -> None:
    """The pump's evidence adapter contains both failed write paths."""
    runtime = MagicMock()
    runtime.reliability = ReliabilityStore(hass, "pump-write-failure")
    runtime.reliability._store.async_save = AsyncMock(side_effect=OSError("full"))
    runtime.growspaces = {"tent": Growspace(id="tent", name="Tent")}
    irrigation = IrrigationCoordinator(
        hass, MagicMock(runtime_data=runtime), "tent", runtime
    )

    await irrigation._count_reliability("irrigation.requested")
    await irrigation._set_reliability_active("switch.pump", True)

    assert (
        runtime.reliability.snapshot("tent")["lifetime"].get("irrigation.requested", 0)
        == 0
    )
    assert runtime.reliability.active_outputs("tent") == ()


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

    await irrigation._async_probe_control_sensors()
    with patch.object(irrigation, "_async_record_controller_state", new=AsyncMock()):
        await irrigation._async_begin_startup_inhibit()
    irrigation.async_cancel_listeners()

    counters = runtime.reliability.snapshot("tent")["lifetime"]
    assert counters["runtime.automation_eligible_minutes"] == 1
    assert counters["irrigation.readback.unexpected_on"] == 1
