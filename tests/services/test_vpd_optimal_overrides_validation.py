"""Tests for validate_vpd_optimal_overrides in the Environment Patch module."""

import pytest

from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatchError,
    validate_vpd_optimal_overrides,
)


def _valid_entry() -> dict:
    return {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4, "high": 1.0}}


def test_accepts_empty_dict() -> None:
    """Empty override dict is valid and returned as-is."""
    assert validate_vpd_optimal_overrides({}) == {}


def test_accepts_valid_sparse_dict() -> None:
    """A dict with a single valid stage entry is accepted and returned."""
    overrides = {"veg": _valid_entry()}
    assert validate_vpd_optimal_overrides(overrides) == overrides


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
    result = validate_vpd_optimal_overrides(overrides)
    assert result == overrides


def test_rejects_unknown_stage_key() -> None:
    """An unrecognised stage key raises EnvironmentPatchError."""
    with pytest.raises(EnvironmentPatchError, match="Unknown stage key"):
        validate_vpd_optimal_overrides({"typo_stage": _valid_entry()})


def test_rejects_missing_day_key() -> None:
    """An entry missing the 'day' key raises EnvironmentPatchError."""
    bad = {"night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="both 'day' and 'night'"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_night_key() -> None:
    """An entry missing the 'night' key raises EnvironmentPatchError."""
    bad = {"day": {"low": 0.5, "high": 1.2}}
    with pytest.raises(EnvironmentPatchError, match="both 'day' and 'night'"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_low_key() -> None:
    """An entry missing 'low' in the day period raises EnvironmentPatchError."""
    bad = {"day": {"high": 1.2}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="'low' and 'high'"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_missing_high_key() -> None:
    """An entry missing 'high' in the night period raises EnvironmentPatchError."""
    bad = {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4}}
    with pytest.raises(EnvironmentPatchError, match="'low' and 'high'"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_low_greater_than_or_equal_to_high() -> None:
    """low >= high raises EnvironmentPatchError."""
    bad = {"day": {"low": 1.2, "high": 0.5}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="low.*<.*high"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_low_equal_to_high() -> None:
    """low == high raises EnvironmentPatchError."""
    bad = {"day": {"low": 1.0, "high": 1.0}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="low.*<.*high"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_value_below_minimum() -> None:
    """A VPD value below 0.1 kPa raises EnvironmentPatchError."""
    bad = {"day": {"low": 0.05, "high": 1.0}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="out of range"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_rejects_value_above_maximum() -> None:
    """A VPD value above 3.0 kPa raises EnvironmentPatchError."""
    bad = {"day": {"low": 0.5, "high": 3.5}, "night": {"low": 0.4, "high": 1.0}}
    with pytest.raises(EnvironmentPatchError, match="out of range"):
        validate_vpd_optimal_overrides({"veg": bad})


def test_none_treated_as_empty_dict() -> None:
    """None input is treated as an empty dict (no overrides)."""
    assert validate_vpd_optimal_overrides(None) == {}
