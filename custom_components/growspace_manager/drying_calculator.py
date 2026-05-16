"""Pure functions for drying and curing calculations."""

from __future__ import annotations

from custom_components.growspace_manager.models import MoistureEntry, WeightEntry

TARGET_DRY_WEIGHT_RATIO: float = 0.25
CURE_READY_MOISTURE_THRESHOLD: float = 12.0


def compute_weight_lost_pct(
    wet_weight: float | None, current_weight: float
) -> float | None:
    """Return percentage of weight lost relative to initial wet weight."""
    if not wet_weight:
        return None
    return (wet_weight - current_weight) / wet_weight * 100


def compute_days_to_target(
    wet_weight: float | None,
    weight_log: list[WeightEntry],
) -> float | None:
    """Project days until current weight reaches the target dry weight.

    Uses rolling average of all daily losses across the full log.
    Returns None if fewer than 2 entries or no weight loss is occurring.
    """
    if not wet_weight or len(weight_log) < 2:
        return None

    total_loss = weight_log[0].weight_grams - weight_log[-1].weight_grams
    days_elapsed = len(weight_log) - 1
    avg_daily_loss = total_loss / days_elapsed

    if avg_daily_loss <= 0:
        return None

    target_weight = wet_weight * TARGET_DRY_WEIGHT_RATIO
    remaining = weight_log[-1].weight_grams - target_weight
    return max(0.0, remaining / avg_daily_loss)


def is_cure_ready(moisture_log: list[MoistureEntry]) -> bool:
    """Return True if the latest moisture reading is at or below the cure threshold."""
    if not moisture_log:
        return False
    return moisture_log[-1].moisture_percent <= CURE_READY_MOISTURE_THRESHOLD
