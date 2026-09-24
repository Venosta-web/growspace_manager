"""Durable reliability evidence and the user-requested export shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
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
    store._store.async_save.assert_not_awaited()


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
