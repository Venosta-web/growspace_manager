"""Shot Size Conversion: the two-way percent ↔ pump-seconds conversion.

The one place a [[Volume-Based Shot Sizing]] percent becomes pump seconds and
back. Pure functions over plain numbers — no strategy, no growspace, no
coordinator — so the live plant count and the growspace's plumbing arrive as
explicit arguments rather than being read from ambient state.

Both directions are anchored on the same physical identity::

    shot volume (ml) = percent/100 × liters_per_pot × live_plant_count × 1000
    pump seconds     = shot volume (ml) / pump flow rate (ml/s)

The forward direction sizes a steering shot for the tent as it is right now:
the [[Substrate Profile]]'s per-pot volume is constant per-plant dosing, so the
total volume — and therefore the seconds — scales with the live plant count
(ADR-0011).

The inverse direction exists for the opposite purpose: recovering the per-pot
percent a growspace's configured seconds actually deliver, so a shot size can
be carried between growspaces with different plumbing. Because the forward
direction multiplied the live plant count in, **the inverse must divide it back
out**. Doing so is what makes the recovered percent plant-count-independent:
two growspaces dosing the same per-pot percent need different seconds when they
run different plant counts, and only dividing the count out maps both back to
the one percent. Skipping that division would scale the percent by the count,
and every growspace the value is later applied to would be silently mis-watered
by that factor.
"""

from __future__ import annotations

# A composed shot never rounds down to a no-op: any positive volume that the
# pump can deliver is worth at least one second. Zero volume is a suspend
# (None), not a floored shot — see ADR-0011's zero-plant rule.
MIN_SHOT_SECONDS = 1


def shot_volume_ml(
    percent: float, *, liters_per_pot: float, live_plant_count: int
) -> float:
    """Return the total shot volume in millilitres for a percent-of-volume size.

    Per-plant dosing: the percent is of one pot's substrate volume, and the
    tent's total is that dose times the number of live plants.
    """
    return (percent / 100.0) * liters_per_pot * live_plant_count * 1000.0


def percent_to_seconds(
    percent: float,
    *,
    liters_per_pot: float,
    live_plant_count: int,
    flow_rate_ml_per_sec: float,
) -> int | None:
    """Return the pump seconds delivering a percent-of-volume shot, or None.

    None means there is nothing to fire: no live plants, a non-positive percent
    or pot volume, or no measured flow rate to convert millilitres with. The
    caller suspends rather than substituting a fallback duration.
    """
    if flow_rate_ml_per_sec <= 0.0:
        return None
    volume_ml = shot_volume_ml(
        percent, liters_per_pot=liters_per_pot, live_plant_count=live_plant_count
    )
    if volume_ml <= 0.0:
        return None
    return max(MIN_SHOT_SECONDS, round(volume_ml / flow_rate_ml_per_sec))


def seconds_to_percent(
    seconds: float,
    *,
    liters_per_pot: float,
    live_plant_count: int,
    flow_rate_ml_per_sec: float,
) -> float | None:
    """Return the per-pot percent-of-volume a pump duration delivers, or None.

    The exact inverse of :func:`percent_to_seconds`: the live plant count the
    forward direction multiplied in is divided back out, so the result is the
    per-pot dose and is independent of how many plants the growspace it was
    derived from happens to hold.

    None means the percent cannot be derived at all — no live plants, no pot
    volume, or no flow rate — which callers report as a missing prerequisite
    rather than storing a guess.
    """
    if live_plant_count <= 0 or liters_per_pot <= 0.0 or flow_rate_ml_per_sec <= 0.0:
        return None
    volume_ml = seconds * flow_rate_ml_per_sec
    return volume_ml / (liters_per_pot * live_plant_count * 1000.0) * 100.0
