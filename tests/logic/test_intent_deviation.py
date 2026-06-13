"""Tests for Measured Classification and Intent Deviation (ADR-0012)."""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.const import SteeringMode
from custom_components.growspace_manager.crop_steering import (
    classify_steering_score,
    compute_intent_deviation,
)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        pytest.param(0.5, SteeringMode.GENERATIVE, id="generative"),
        pytest.param(-0.5, SteeringMode.VEGETATIVE, id="vegetative"),
        pytest.param(0.0, SteeringMode.BALANCED, id="balanced-zero"),
        pytest.param(0.3, SteeringMode.BALANCED, id="boundary-0.3-balanced"),
        pytest.param(-0.3, SteeringMode.BALANCED, id="boundary--0.3-balanced"),
        pytest.param(0.31, SteeringMode.GENERATIVE, id="just-over-generative"),
    ],
)
def test_classify_steering_score(score: float, expected: SteeringMode) -> None:
    """Score maps to the measured classification bucket by fixed thresholds."""
    assert classify_steering_score(score) == expected


def test_deviation_on_target_when_buckets_match() -> None:
    """Measured bucket equal to declared mode reads on_target."""
    assert (
        compute_intent_deviation(SteeringMode.GENERATIVE, SteeringMode.GENERATIVE)
        == "on_target"
    )


def test_deviation_more_vegetative_when_substrate_reads_lower() -> None:
    """Declared generative but substrate measures vegetative => more_vegetative."""
    assert (
        compute_intent_deviation(SteeringMode.VEGETATIVE, SteeringMode.GENERATIVE)
        == "more_vegetative"
    )


def test_deviation_more_generative_when_substrate_reads_higher() -> None:
    """Declared vegetative but substrate measures generative => more_generative."""
    assert (
        compute_intent_deviation(SteeringMode.GENERATIVE, SteeringMode.VEGETATIVE)
        == "more_generative"
    )


def test_deviation_none_when_intent_undeclared() -> None:
    """No declared intent => nothing to deviate from => None."""
    assert compute_intent_deviation(SteeringMode.GENERATIVE, None) is None
