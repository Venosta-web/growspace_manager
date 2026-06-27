"""Tests for vpd_optimal_overrides field on EnvironmentConfig."""


from custom_components.growspace_manager.models import EnvironmentConfig


def test_vpd_optimal_overrides_defaults_to_empty_dict() -> None:
    """New field defaults to empty dict when absent from stored data."""
    config = EnvironmentConfig.from_dict({})
    assert config.vpd_optimal_overrides == {}


def test_vpd_optimal_overrides_round_trip() -> None:
    """vpd_optimal_overrides survives to_dict() → from_dict() without loss."""
    overrides = {
        "veg": {"day": {"low": 0.5, "high": 1.2}, "night": {"low": 0.4, "high": 1.0}},
        "flower_early": {
            "day": {"low": 0.9, "high": 1.4},
            "night": {"low": 0.8, "high": 1.2},
        },
    }
    config = EnvironmentConfig(vpd_optimal_overrides=overrides)
    data = config.to_dict()
    assert data["vpd_optimal_overrides"] == overrides
    restored = EnvironmentConfig.from_dict(data)
    assert restored.vpd_optimal_overrides == overrides


def test_vpd_optimal_overrides_sparse_single_stage() -> None:
    """A single-stage override round-trips correctly."""
    overrides = {
        "seedling": {"day": {"low": 0.3, "high": 0.7}, "night": {"low": 0.3, "high": 0.6}},
    }
    config = EnvironmentConfig(vpd_optimal_overrides=overrides)
    restored = EnvironmentConfig.from_dict(config.to_dict())
    assert restored.vpd_optimal_overrides == overrides


def test_vpd_optimal_overrides_empty_dict_round_trip() -> None:
    """An explicit empty override dict round-trips correctly."""
    config = EnvironmentConfig(vpd_optimal_overrides={})
    data = config.to_dict()
    assert data["vpd_optimal_overrides"] == {}
    restored = EnvironmentConfig.from_dict(data)
    assert restored.vpd_optimal_overrides == {}
