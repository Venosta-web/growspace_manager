"""Seed a coordinator's Dispensed Volume the way the pump would have charged it.

The daily caps are derived from today's Delivery Attempts (ADR-0054/0055), so a
test that needs a growspace "already at 3 cycles" charges three attempts rather
than setting a counter.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
)
from homeassistant.util import dt as dt_util


def charged_attempt(
    growspace_id: str,
    *,
    liters: float = 0.0,
    day: date | None = None,
    at: datetime | None = None,
    attempt_id: str | None = None,
) -> DeliveryAttempt:
    """Return an open attempt charged ``liters`` on ``day`` (today by default)."""
    confirmed = at or dt_util.utcnow()
    return DeliveryAttempt(
        attempt_id=attempt_id or f"seed-{confirmed.timestamp()}-{liters}",
        growspace_id=growspace_id,
        output="switch.irrigation_pump",
        trigger=AttemptTrigger.SCHEDULE,
        planned_s=0.0,
        flow_rate_ml_per_sec=0.0,
        on_commanded_at=confirmed - timedelta(seconds=1),
        on_confirmed_at=confirmed,
        charge_date=day or dt_util.now().date(),
        charged_l=liters,
    )


def charge_today(coordinator: object, *, cycles: int, liters: float = 0.0) -> None:
    """Charge ``cycles`` pump starts totalling ``liters`` against today's caps."""
    if liters and cycles < 1:
        raise ValueError("litres are charged by a cycle")
    deliveries = coordinator._deliveries  # type: ignore[attr-defined]
    for index in range(cycles):
        deliveries.attempts.append(
            charged_attempt(
                deliveries.growspace_id,
                liters=liters if index == 0 else 0.0,
                attempt_id=f"seed-{len(deliveries.attempts)}",
            )
        )
