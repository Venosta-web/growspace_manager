"""Tests for evaluate_optimal_vpd with per-stage vpd_optimal_overrides.

Veg default day thresholds: [(0.5, 0.9), (0.4, 0.8)]
SEEDLING acclimation default day: [(-0.1, 0.3), (0.0, 0.4)]
SEEDLING_STANDARD default day: [(0.4, 0.8), (0.3, 0.9)]
"""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.bayesian_data import PROB_VPD_STRESS_OUT_OF_RANGE
from custom_components.growspace_manager.bayesian_evaluator import evaluate_optimal_vpd
from custom_components.growspace_manager.models import EnvironmentState


def _veg_state(vpd: float, *, day: bool = True) -> EnvironmentState:
    state = MagicMock(spec=EnvironmentState)
    state.vpd = vpd
    state.is_lights_on = day
    state.flower_days = -1
    state.veg_days = 10
    state.seedling_days = -1
    state.clone_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1
    return state


def _seedling_acclimation_state(vpd: float) -> EnvironmentState:
    """First few days of seedling — resolves to BayesianStage.SEEDLING (acclimation)."""
    state = MagicMock(spec=EnvironmentState)
    state.vpd = vpd
    state.is_lights_on = True
    state.flower_days = -1
    state.veg_days = -1
    state.seedling_days = 2
    state.clone_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1
    return state


def _seedling_standard_state(vpd: float) -> EnvironmentState:
    """Past acclimation — resolves to BayesianStage.SEEDLING_STANDARD."""
    state = MagicMock(spec=EnvironmentState)
    state.vpd = vpd
    state.is_lights_on = True
    state.flower_days = -1
    state.veg_days = -1
    state.seedling_days = 20
    state.clone_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1
    return state


# ── Custom veg override ──────────────────────────────────────────────────────

def test_vpd_inside_custom_veg_window_but_outside_default_is_optimal() -> None:
    """VPD 1.1 is outside the default veg window (0.5–0.9) but inside custom (0.5–1.2).

    Without overrides this would be not-optimal; with the override it must be optimal.
    """
    overrides = {
        "veg": {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4, "high": 1.0}},
    }
    env_config = {"vpd_optimal_overrides": overrides}
    state = _veg_state(vpd=1.1)

    observations, reasons = evaluate_optimal_vpd(state, env_config)

    assert reasons == [], f"VPD 1.1 should be optimal under custom veg override; reasons={reasons}"
    assert observations[0] != PROB_VPD_STRESS_OUT_OF_RANGE


def test_vpd_inside_default_veg_window_but_outside_custom_is_not_optimal() -> None:
    """VPD 0.8 is inside the default veg window (0.5–0.9) but outside custom (0.5–0.7).

    Without overrides this would be optimal; with the override it must be not-optimal.
    """
    overrides = {
        "veg": {"day": {"low": 0.5, "high": 0.7}, "night": {"low": 0.4, "high": 0.6}},
    }
    env_config = {"vpd_optimal_overrides": overrides}
    state = _veg_state(vpd=0.8)

    observations, reasons = evaluate_optimal_vpd(state, env_config)

    assert len(reasons) == 1, f"VPD 0.8 should be not-optimal under custom narrow window; reasons={reasons}"
    assert observations[0] == PROB_VPD_STRESS_OUT_OF_RANGE


# ── No override → default behaviour ─────────────────────────────────────────

def test_no_override_uses_default_thresholds_optimal() -> None:
    """Without any override, VPD 0.7 is optimal under veg defaults."""
    state = _veg_state(vpd=0.7)
    observations, reasons = evaluate_optimal_vpd(state, {})
    assert reasons == []


def test_no_override_uses_default_thresholds_not_optimal() -> None:
    """Without any override, VPD 2.5 is not optimal under veg defaults."""
    state = _veg_state(vpd=2.5)
    observations, reasons = evaluate_optimal_vpd(state, {})
    assert len(reasons) == 1
    assert observations[0] == PROB_VPD_STRESS_OUT_OF_RANGE


# ── Acclimation stage is never overridden ────────────────────────────────────

def test_acclimation_seedling_ignores_seedling_override() -> None:
    """BayesianStage.SEEDLING (acclimation dome) is never overridden.

    VPD 0.2 is inside the hardcoded acclimation window (-0.1–0.3). A 'seedling'
    override with a high-VPD window (1.0–2.0) must NOT affect this sub-stage.
    """
    overrides = {
        "seedling": {"day": {"low": 1.0, "high": 2.0}, "night": {"low": 0.9, "high": 1.8}},
    }
    env_config = {"vpd_optimal_overrides": overrides}
    state = _seedling_acclimation_state(vpd=0.2)

    observations, reasons = evaluate_optimal_vpd(state, env_config)

    assert reasons == [], (
        "Acclimation seedling at VPD 0.2 must be optimal regardless of override"
    )


# ── SEEDLING_STANDARD uses the override ─────────────────────────────────────

def test_seedling_standard_uses_seedling_override() -> None:
    """BayesianStage.SEEDLING_STANDARD (past acclimation) does use the 'seedling' override.

    VPD 1.0 is outside the default SEEDLING_STANDARD day window (0.4–0.8 / 0.3–0.9)
    but inside the custom override (0.9–1.1), so it must be optimal.
    """
    overrides = {
        "seedling": {"day": {"low": 0.9, "high": 1.1}, "night": {"low": 0.8, "high": 1.0}},
    }
    env_config = {"vpd_optimal_overrides": overrides}
    state = _seedling_standard_state(vpd=1.0)

    observations, reasons = evaluate_optimal_vpd(state, env_config)

    assert reasons == [], (
        "VPD 1.0 should be optimal under custom seedling_standard override"
    )


# ── Mixed-override stage-transition does not crash ───────────────────────────


def test_mixed_override_transition_no_runtime_error() -> None:
    """Stage-transition with one overridden side and one default side must not crash.

    veg_days=1 resolves to (SEEDLING_STANDARD → VEG, factor≈0.33).
    Only 'veg' is overridden, so limits_a comes from hardcoded defaults
    (multi-band) while limits_b comes from the override (single band).
    The loop uses min(len(a), len(b)) so no IndexError occurs.
    """
    overrides = {
        "veg": {"day": {"low": 0.8, "high": 1.2}, "night": {"low": 0.6, "high": 1.0}},
    }
    env_config = {"vpd_optimal_overrides": overrides}
    state = MagicMock(spec=EnvironmentState)
    state.vpd = 0.7
    state.is_lights_on = True
    state.flower_days = -1
    state.veg_days = 1  # Within TRANSITION_WINDOW → SEEDLING_STANDARD→VEG transition
    state.seedling_days = -1
    state.clone_days = -1
    state.dry_days = -1
    state.cure_days = -1
    state.mother_days = -1

    observations, reasons = evaluate_optimal_vpd(state, env_config)

    assert len(observations) == 1, "Exactly one probability observation expected"
