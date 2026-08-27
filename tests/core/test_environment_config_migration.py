"""Tests for EnvironmentConfig field rename: substrate_ec_sensors → bulk_ec_sensors."""

from custom_components.growspace_manager.models import EnvironmentConfig


def test_substrate_ec_sensors_migrates_to_bulk_ec_sensors() -> None:
    """Existing stored data with substrate_ec_sensors loads as bulk_ec_sensors."""
    data = {"substrate_ec_sensors": ["sensor.ec_1", "sensor.ec_2"]}
    config = EnvironmentConfig.from_dict(data)
    assert config.bulk_ec_sensors == ["sensor.ec_1", "sensor.ec_2"]


def test_pore_ec_sensors_defaults_to_empty_list() -> None:
    """New field pore_ec_sensors defaults to empty list when absent from stored data."""
    config = EnvironmentConfig.from_dict({})
    assert config.pore_ec_sensors == []


def test_substrate_ec_sensors_field_removed() -> None:
    """EnvironmentConfig no longer has a substrate_ec_sensors field."""
    config = EnvironmentConfig()
    assert not hasattr(config, "substrate_ec_sensors")


def test_bulk_ec_sensors_and_pore_ec_sensors_round_trip() -> None:
    """Both fields serialize and deserialize correctly."""
    config = EnvironmentConfig(
        bulk_ec_sensors=["sensor.bulk_1"],
        pore_ec_sensors=["sensor.pore_1"],
    )
    data = config.to_dict()
    assert data["bulk_ec_sensors"] == ["sensor.bulk_1"]
    assert data["pore_ec_sensors"] == ["sensor.pore_1"]
    assert "substrate_ec_sensors" not in data
