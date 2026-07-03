"""Tests for the Grow Light Controller config on EnvironmentConfig."""

from custom_components.growspace_manager.models import (
    ACInfinityGrowLight,
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


def test_ac_infinity_growlight_defaults_to_empty_list() -> None:
    """The AC Infinity grow light bundle list defaults to empty when absent."""
    config = EnvironmentConfig.from_dict({})
    assert config.growlight_ac_infinity_devices == []


def test_ac_infinity_growlight_round_trips() -> None:
    """An AC Infinity grow light bundle serializes and deserializes unchanged."""
    device = ACInfinityGrowLight(
        mode_entity="select.port_mode",
        on_time_entity="time.port_on",
        off_time_entity="time.port_off",
        power_entity="number.port_power",
    )
    config = EnvironmentConfig(growlight_ac_infinity_devices=[device])
    restored = EnvironmentConfig.from_dict(config.to_dict())
    assert restored.growlight_ac_infinity_devices == [device]


def test_ac_infinity_growlight_coerces_null_stored_value() -> None:
    """A null stored bundle list coerces to an empty list."""
    config = EnvironmentConfig.from_dict({"growlight_ac_infinity_devices": None})
    assert config.growlight_ac_infinity_devices == []


def test_growlight_config_sunrise_defaults() -> None:
    """Sunrise is off by default with a zero ramp."""
    cfg = GrowLightConfig()
    assert cfg.sunrise_enabled is False
    assert cfg.sunrise_minutes == 0


def test_growlight_config_sunrise_round_trips() -> None:
    """Sunrise settings serialize and deserialize unchanged."""
    config = EnvironmentConfig(
        growlight_config=GrowLightConfig(
            enabled=True, power=90, sunrise_enabled=True, sunrise_minutes=15
        )
    )
    restored = EnvironmentConfig.from_dict(config.to_dict())
    assert restored.growlight_config == GrowLightConfig(
        enabled=True, power=90, sunrise_enabled=True, sunrise_minutes=15
    )


def test_ac_infinity_growlight_sunrise_entities_round_trip() -> None:
    """The AC Infinity bundle carries its sunrise switch and duration entities."""
    device = ACInfinityGrowLight(
        mode_entity="select.port_mode",
        on_time_entity="time.port_on",
        off_time_entity="time.port_off",
        power_entity="number.port_power",
        sunrise_switch_entity="switch.port_sunrise",
        sunrise_duration_entity="number.port_sunrise_minutes",
    )
    config = EnvironmentConfig(growlight_ac_infinity_devices=[device])
    restored = EnvironmentConfig.from_dict(config.to_dict())
    assert restored.growlight_ac_infinity_devices == [device]
