"""Tests for _validate_vpd_optimal_overrides in the environment service."""

import pytest

from custom_components.growspace_manager.services.environment import (
    _validate_vpd_optimal_overrides,
)
from homeassistant.exceptions import ServiceValidationError


def _valid_entry() -> dict:
    return {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4, "high": 1.0}}


def test_accepts_empty_dict() -> None:
    """Empty override dict is valid and returned as-is."""
    assert _validate_vpd_optimal_overrides({}) == {}


def test_accepts_valid_sparse_dict() -> None:
    """A dict with a single valid stage entry is accepted and returned."""
    overrides = {"veg": _valid_entry()}
    assert _validate_vpd_optimal_overrides(overrides) == overrides


def test_accepts_all_nine_valid_stages() -> None:
    """All nine valid stage keys are accepted."""
    overrides = {
        stage: _valid_entry()
        for stage in (
            "seedling",
            "clone",
            "mother",
            "veg",
            "flower_early",
            "flower_mid",
            "flower_late",
            "dry",
            "cure",
        )
    }
    result = _validate_vpd_optimal_overrides(overrides)
    assert result == overrides


def test_rejects_unknown_stage_key() -> None:
    """An unrecognised stage key raises ServiceValidationError."""
    with pytest.raises(ServiceValidationError, match="Unknown stage key"):
        _validate_vpd_optimal_overrides({"typo_stage": _valid_entry()})


def test_rejects_missing_day_key() -> None:
    """An entry missing the 'day' key raises ServiceValidationError."""
    bad = {"night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="both 'day' and 'night'"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_night_key() -> None:
    """An entry missing the 'night' key raises ServiceValidationError."""
    bad = {"day": {"low": 0.5, "high": 1.2}}
    with pytest.raises(ServiceValidationError, match="both 'day' and 'night'"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_low_key() -> None:
    """An entry missing 'low' in the day period raises ServiceValidationError."""
    bad = {"day": {"high": 1.2}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="'low' and 'high'"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_high_key() -> None:
    """An entry missing 'high' in the night period raises ServiceValidationError."""
    bad = {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4}}
    with pytest.raises(ServiceValidationError, match="'low' and 'high'"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_low_greater_than_or_equal_to_high() -> None:
    """low >= high raises ServiceValidationError."""
    bad = {"day": {"low": 1.2, "high": 0.5}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="low.*<.*high"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_low_equal_to_high() -> None:
    """low == high raises ServiceValidationError."""
    bad = {"day": {"low": 1.0, "high": 1.0}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="low.*<.*high"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_value_below_minimum() -> None:
    """A VPD value below 0.1 kPa raises ServiceValidationError."""
    bad = {"day": {"low": 0.05, "high": 1.0}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="out of range"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_value_above_maximum() -> None:
    """A VPD value above 3.0 kPa raises ServiceValidationError."""
    bad = {"day": {"low": 0.5, "high": 3.5}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(ServiceValidationError, match="out of range"):
        _validate_vpd_optimal_overrides({"veg": bad})


def test_none_treated_as_empty_dict() -> None:
    """None input is treated as an empty dict (no overrides)."""
    assert _validate_vpd_optimal_overrides(None) == {}
