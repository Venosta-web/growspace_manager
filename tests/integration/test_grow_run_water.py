"""Irrigation reports and durable attempts project into Run water facts."""

from datetime import timedelta
from unittest.mock import patch

from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
)
from custom_components.growspace_manager.domain.grow_run import provisional_metrics
from custom_components.growspace_manager.grow_run_store import GrowRunStore
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry
from tests.integration.test_grow_runs import _started, _tent


async def test_manual_and_pump_water_project_once_and_survive_restart(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, plant_ids = await _tent(init_integration, plants=1)
    run = await _started(hass, coordinator, growspace_id)

    await coordinator.watering_service.async_water_plant(
        plant_ids[0], 1.5, from_monitored_tank=True
    )
    now = dt_util.utcnow()
    attempt = DeliveryAttempt.requested(
        attempt_id="pump-for-run",
        growspace_id=growspace_id,
        output="switch.pump",
        trigger=AttemptTrigger.SCHEDULE,
        planned_s=10,
        flow_rate_ml_per_sec=100,
        requested_at=now,
    )
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    await deliveries.async_request(attempt)
    attempt = attempt.commanded(now).confirmed_on(now, dt_util.as_local(now).date())
    await deliveries.async_charge(attempt)
    deliveries.close(
        attempt.closed(off_commanded_at=now + timedelta(seconds=10)).read_back_off(
            now + timedelta(seconds=11)
        )
    )
    await coordinator.async_project_water()
    await coordinator.async_project_water()

    projected = coordinator.grow_runs.ledger(growspace_id).find(run.run_id)
    assert [(row.source, row.liters) for row in projected.water_applications] == [
        ("manual", 1.5),
        ("pump_estimate", 1.0),
    ]
    assert (
        next(
            row.value
            for row in provisional_metrics(projected)
            if row.metric == "water_applied"
        )
        == 2.5
    )

    restored = GrowRunStore(hass, init_integration.entry_id)
    await restored.async_load()
    assert restored.ledger(growspace_id).find(run.run_id).water_applications == (
        projected.water_applications
    )


async def test_unconfirmed_pump_is_a_missing_water_fact(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    now = dt_util.utcnow()
    attempt = DeliveryAttempt.requested(
        attempt_id="unconfirmed-for-run",
        growspace_id=growspace_id,
        output="switch.pump",
        trigger=AttemptTrigger.MANUAL,
        planned_s=10,
        flow_rate_ml_per_sec=100,
        requested_at=now,
    ).commanded(now)
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    await deliveries.async_request(attempt)
    deliveries.close(
        attempt.unconfirmed(
            off_commanded_at=now + timedelta(seconds=2), reason="on_unconfirmed"
        ).read_back_off(now + timedelta(seconds=3))
    )
    await coordinator.async_project_water()

    projected = coordinator.grow_runs.ledger(growspace_id).find(run.run_id)
    assert projected.water_applications[0].source == "unknown"
    assert projected.water_applications[0].liters is None
    assert (
        next(
            row
            for row in provisional_metrics(projected)
            if row.metric == "water_applied"
        ).value
        is None
    )


async def test_unreadable_delivery_record_marks_water_coverage_missing(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    deliveries.unreadable = True
    await coordinator.async_project_water()
    marked = coordinator.grow_runs.ledger(growspace_id).find(run.run_id)
    assert marked.water_coverage_started_at is None
    assert (
        next(
            row for row in provisional_metrics(marked) if row.metric == "water_applied"
        ).value
        is None
    )


async def test_projection_skips_nonapplications_and_retries_bad_sources(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    growspace = coordinator.growspaces[growspace_id]
    growspace.water_usage.daily_readings.extend(
        [
            {"date": "2026-01-01", "source": "pump_estimate", "liters": 1},
            {"date": "2026-01-01", "source": "manual", "liters": 1},
            {
                "date": "2026-01-01",
                "source": "manual",
                "liters": 1,
                "watering_id": "invalid-time",
                "watered_at": "invalid",
            },
            {
                "date": "2026-01-01",
                "source": "manual",
                "liters": "invalid",
                "watering_id": "invalid-volume",
                "watered_at": dt_util.utcnow().isoformat(),
            },
        ]
    )
    now = dt_util.utcnow()
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    deliveries.attempts.extend(
        [
            DeliveryAttempt.requested(
                attempt_id="open",
                growspace_id=growspace_id,
                output="switch.pump",
                trigger=AttemptTrigger.SCHEDULE,
                planned_s=10,
                flow_rate_ml_per_sec=100,
                requested_at=now,
            ),
            DeliveryAttempt.requested(
                attempt_id="drain",
                growspace_id=growspace_id,
                output="switch.drain",
                trigger=AttemptTrigger.DRAIN,
                planned_s=10,
                flow_rate_ml_per_sec=100,
                requested_at=now,
            ).refused("held"),
            DeliveryAttempt.requested(
                attempt_id="suppressed",
                growspace_id=growspace_id,
                output="switch.pump",
                trigger=AttemptTrigger.SCHEDULE,
                planned_s=10,
                flow_rate_ml_per_sec=100,
                requested_at=now,
            ).refused("held"),
        ]
    )
    await coordinator.async_project_water()
    assert (
        coordinator.grow_runs.ledger(growspace_id).find(run.run_id).water_applications
        == ()
    )
    with patch.object(
        coordinator.deliveries, "async_load", side_effect=RuntimeError("offline")
    ):
        await coordinator.async_project_water()
