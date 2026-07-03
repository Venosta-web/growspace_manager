"""Tests for the Grow Light Controller config on EnvironmentConfig."""

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    GrowLightConfig,
)


def test_growlight_fields_default_when_absent() -> None:
    """A stored config without grow-light fields loads sane defaults."""
    config = EnvironmentConfig.from_dict({})
    assert config.growlight_entities == []
    assert config.growlight_config == GrowLightConfig()
    assert config.growlight_config.enabled is False
    assert config.growlight_config.power == 100


def test_growlight_fields_round_trip() -> None:
    """Grow-light entities and config serialize and deserialize unchanged."""
    config = EnvironmentConfig(
        growlight_entities=["switch.tent_light", "light.bar"],
        growlight_config=GrowLightConfig(enabled=True, power=80),
    )
    restored = EnvironmentConfig.from_dict(config.to_dict())
    assert restored.growlight_entities == ["switch.tent_light", "light.bar"]
    assert restored.growlight_config == GrowLightConfig(enabled=True, power=80)


def test_growlight_fields_coerce_null_stored_values() -> None:
    """Null stored values coerce to an empty list and default config."""
    config = EnvironmentConfig.from_dict(
        {"growlight_entities": None, "growlight_config": None}
    )
    assert config.growlight_entities == []
    assert config.growlight_config == GrowLightConfig()
