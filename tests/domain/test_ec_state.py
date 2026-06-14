"""Tests for the EC State seam (ADR-0015, issue #463).

The resolver is pure: every dependency is injected, so these drive it with a
plain ``IrrigationStrategy`` and a lambda pore-EC reader — no coordinator, no
Home Assistant.
"""

from collections.abc import Callable

import pytest

from custom_components.growspace_manager.domain.ec_state import (
    ECRecommendation,
    ECState,
    ECStateResolver,
)
from custom_components.growspace_manager.models import IrrigationStrategy


def _strategy(
    *,
    enabled: bool = True,
    band_min: float | None = 2.0,
    band_max: float | None = 3.0,
) -> IrrigationStrategy:
    """Return a strategy with the given pore-EC band and opt-in flag."""
    return IrrigationStrategy(
        ec_modulation_enabled=enabled,
        pore_ec_target_min=band_min,
        pore_ec_target_max=band_max,
    )


def _resolve(
    strategy: IrrigationStrategy, read_pore_ec: Callable[[], float | None]
) -> ECState:
    """Resolve an ECState for the given strategy and pore reader."""
    return ECStateResolver(strategy, read_pore_ec).resolve()


def test_modulation_disabled_is_unavailable() -> None:
    """Opt-in off → UNAVAILABLE and no pore reading carried, even with a band."""
    state = _resolve(_strategy(enabled=False), lambda: 5.0)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


@pytest.mark.parametrize(
    ("band_min", "band_max"),
    [(None, 3.0), (2.0, None), (None, None), (3.0, 3.0), (3.0, 2.0)],
)
def test_absent_or_inverted_band_is_unavailable(
    band_min: float | None, band_max: float | None
) -> None:
    """A missing or non-increasing band → UNAVAILABLE (graceful, no raise)."""
    state = _resolve(_strategy(band_min=band_min, band_max=band_max), lambda: 2.5)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


def test_no_pore_reading_is_unavailable() -> None:
    """Enabled with a valid band but no reading → UNAVAILABLE."""
    state = _resolve(_strategy(), lambda: None)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


@pytest.mark.parametrize(
    ("pore_ec", "expected"),
    [
        (1.0, ECRecommendation.STACK),  # below band
        (2.5, ECRecommendation.HOLD),  # within band
        (4.0, ECRecommendation.FLUSH),  # above band
        (2.0, ECRecommendation.HOLD),  # exactly at band_min → within (strict)
        (3.0, ECRecommendation.HOLD),  # exactly at band_max → within (strict)
    ],
)
def test_classification_against_band(
    pore_ec: float, expected: ECRecommendation
) -> None:
    """Direction matches the factor helper's strict above/within/below split."""
    state = _resolve(_strategy(), lambda: pore_ec)
    assert state.recommendation is expected
    assert state.pore_ec == pytest.approx(pore_ec)


def test_forward_fields_default_absent() -> None:
    """Feed-target and runoff fields (later slices) default to absent."""
    state = _resolve(_strategy(), lambda: 2.5)
    assert state.active_feed_ec is None
    assert state.feed_ec_source == "none"
    assert state.runoff_ec is None
    assert state.feed_to_runoff_delta is None
