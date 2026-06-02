"""Crop steering score calculation for Growspace Manager.

Calculates a vegetative-to-generative steering score from VWC dryback
patterns and environmental data. Score ranges from -1.0 (max vegetative)
to +1.0 (max generative).
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from .models import CropSteeringState

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator


def calculate_crop_steering_score(
    dryback_percent: float,
    ec_trend: str,
    shot_count: int | None = None,
) -> float:
    """Calculate the crop steering score from component metrics.

    Args:
        dryback_percent: Today's dryback percentage (peak - trough) / peak * 100.
        ec_trend: EC trend direction ("rising", "falling", "stable").
        shot_count: Number of irrigation shots today (None if unknown).

    Returns:
        Score clamped to [-1.0, 1.0].
    """
    score = 0.0

    # Dryback component: >30% = generative, <10% = vegetative
    if dryback_percent > 30:
        score += 0.4
    elif dryback_percent > 20:
        score += 0.2
    elif dryback_percent < 10:
        score -= 0.4
    elif dryback_percent < 15:
        score -= 0.2

    # EC trend component
    if ec_trend == "rising":
        score += 0.3
    elif ec_trend == "falling":
        score -= 0.3

    # Shot frequency component (if available)
    if shot_count is not None:
        if shot_count <= 3:
            score += 0.3  # Fewer, larger shots = generative
        elif shot_count >= 8:
            score -= 0.3  # Many small shots = vegetative

    return max(-1.0, min(1.0, score))


def get_crop_steering_state(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
) -> CropSteeringState | None:
    """Get the current crop steering state for a growspace.

    Args:
        coordinator: The growspace coordinator.
        growspace_id: The growspace to evaluate.

    Returns:
        CropSteeringState or None if VWC strategy is not active.
    """
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace or not growspace.irrigation_strategy.enabled:
        return None

    # Try to get VWC data from irrigation coordinator
    vwc_coord = coordinator.services.growspaces.get_irrigation_coordinator(growspace_id)
    if vwc_coord is None:
        return CropSteeringState()

    # Get VWC readings from the coordinator's soil moisture sensor
    soil_moisture_sensor = growspace.environment_config.soil_moisture_sensor
    if not soil_moisture_sensor:
        return CropSteeringState()

    state = coordinator.hass.states.get(soil_moisture_sensor)
    current_vwc = None
    if state and state.state not in ("unknown", "unavailable"):
        with contextlib.suppress(ValueError, TypeError):
            current_vwc = float(state.state)

    if current_vwc is None:
        return CropSteeringState()

    # Simple peak/trough tracking from strategy targets
    strategy = growspace.irrigation_strategy
    peak_vwc = max(current_vwc, strategy.target_vwc_percent)
    trough_vwc = min(
        current_vwc,
        strategy.target_vwc_percent - strategy.maintenance_dryback_percent,
    )

    dryback_percent = (
        (peak_vwc - trough_vwc) / peak_vwc * 100 if peak_vwc > 0 else 0.0
    )

    ec_trend = "stable"
    score = calculate_crop_steering_score(dryback_percent, ec_trend)

    return CropSteeringState(
        score=score,
        dryback_percent=dryback_percent,
        peak_vwc=peak_vwc,
        trough_vwc=trough_vwc,
        ec_trend=ec_trend,
    )
