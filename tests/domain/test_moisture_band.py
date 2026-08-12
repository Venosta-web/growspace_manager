"""Unit tests for the Acceptable Moisture Band domain helper.

Pure tests: no Home Assistant instance, no coordinator. They pin the band
resolution and classification that both the Bayesian stress evaluator and the
outbound growspace payload share.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.growspace_manager.domain.moisture_band import (
    DEFAULT_MOISTURE_BAND,
    DEFAULT_MOISTURE_MAX,
    DEFAULT_MOISTURE_MIN,
    MoistureBand,
    effective_moisture_band,
    is_percentage_unit,
    is_valid_band,
)


def test_default_band_is_the_legacy_20_60_inclusive_range() -> None:
    """No override inherits the historic 20–60% band, marked as inherited."""
    assert DEFAULT_MOISTURE_MIN == 20.0
    assert DEFAULT_MOISTURE_MAX == 60.0
    assert MoistureBand(20.0, 60.0, is_custom=False) == DEFAULT_MOISTURE_BAND


def test_no_override_resolves_to_the_default_band() -> None:
    """Both bounds absent means the growspace inherits, not overrides."""
    band = effective_moisture_band(None, None)
    assert band == DEFAULT_MOISTURE_BAND
    assert band.is_custom is False


def test_complete_decimal_pair_resolves_to_a_custom_band() -> None:
    """A stored pair overrides the default and reports itself as custom."""
    band = effective_moisture_band(32.5, 54.5)
    assert band == MoistureBand(32.5, 54.5, is_custom=True)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        pytest.param(30.0, None, id="max-missing"),
        pytest.param(None, 55.0, id="min-missing"),
        pytest.param(60.0, 30.0, id="inverted"),
        pytest.param(40.0, 40.0, id="equal-bounds"),
        pytest.param(-0.5, 50.0, id="below-floor"),
        pytest.param(20.0, 100.5, id="above-ceiling"),
        pytest.param(float("nan"), 50.0, id="nan"),
        pytest.param(float("inf"), float("inf"), id="infinite"),
        pytest.param("not-a-number", 50.0, id="non-numeric"),
    ],
)
def test_incomplete_or_invalid_pairs_fall_back_to_the_default(
    minimum: Any, maximum: Any
) -> None:
    """Anything short of a complete valid pair inherits rather than half-applies."""
    assert is_valid_band(minimum, maximum) is False
    assert effective_moisture_band(minimum, maximum) == DEFAULT_MOISTURE_BAND


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        pytest.param(0.0, 100.0, id="full-range"),
        pytest.param(0.0, 0.1, id="floor-touching"),
        pytest.param(99.9, 100.0, id="ceiling-touching"),
        pytest.param(32.5, 54.5, id="decimal-pair"),
    ],
)
def test_valid_pairs_span_the_whole_permitted_range(
    minimum: float, maximum: float
) -> None:
    """0 ≤ minimum < maximum ≤ 100 is accepted, edges included."""
    assert is_valid_band(minimum, maximum) is True


@pytest.mark.parametrize(
    ("reading", "expected"),
    [
        pytest.param(19.9, "too_dry", id="just-below-minimum"),
        pytest.param(20.0, "in_band", id="exactly-on-minimum"),
        pytest.param(40.0, "in_band", id="mid-band"),
        pytest.param(60.0, "in_band", id="exactly-on-maximum"),
        pytest.param(60.1, "too_wet", id="just-above-maximum"),
    ],
)
def test_classification_boundaries_are_inclusive(
    reading: float, expected: str
) -> None:
    """A reading exactly on either bound sits inside the band."""
    assert DEFAULT_MOISTURE_BAND.classify(reading) == expected


def test_classification_follows_a_custom_band_not_the_default() -> None:
    """A reading in the default band can be out of a narrower custom band."""
    custom = effective_moisture_band(32.5, 54.0)
    assert DEFAULT_MOISTURE_BAND.classify(56.0) == "in_band"
    assert custom.classify(56.0) == "too_wet"
    assert custom.classify(30.0) == "too_dry"


def test_band_serializes_for_the_growspace_payload() -> None:
    """The wire shape carries both bounds and the inherited/custom distinction."""
    assert effective_moisture_band(32.5, 54.0).to_dict() == {
        "min": 32.5,
        "max": 54.0,
        "is_custom": True,
    }
    assert DEFAULT_MOISTURE_BAND.to_dict() == {
        "min": 20.0,
        "max": 60.0,
        "is_custom": False,
    }


@pytest.mark.parametrize(
    ("unit", "compatible"),
    [
        pytest.param("%", True, id="percentage"),
        pytest.param(" % ", True, id="percentage-padded"),
        pytest.param(None, True, id="legacy-no-unit-metadata"),
        pytest.param("°C", False, id="temperature"),
        pytest.param("m³/m³", False, id="volumetric-ratio"),
        pytest.param("", False, id="empty-string-unit"),
    ],
)
def test_only_percentage_and_unitless_sensors_participate(
    unit: str | None, compatible: bool
) -> None:
    """Explicitly non-percentage units are excluded; missing metadata is legacy."""
    assert is_percentage_unit(unit) is compatible
