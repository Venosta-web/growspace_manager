"""The substrate EC probes: renamed to bulk_ec_sensors, then moved to the zone.

``substrate_ec_sensors`` became ``bulk_ec_sensors`` on EnvironmentConfig, and
ADR-0057 then moved every substrate probe to the growspace's Irrigation Zone.
A stored document of either age still arrives with its probes on the zone.
"""

from custom_components.growspace_manager.domain.irrigation_zone import (
    migrate_growspace_document,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationZone,
)


def _load(environment: dict) -> Growspace:
    return Growspace.from_dict(
        migrate_growspace_document(
            {"id": "gs", "name": "Gs", "environment_config": environment}
        )
    )


def test_substrate_ec_sensors_migrates_to_bulk_ec_sensors() -> None:
    """Existing stored data with substrate_ec_sensors loads as the zone's bulk EC."""
    growspace = _load({"substrate_ec_sensors": ["sensor.ec_1", "sensor.ec_2"]})
    assert growspace.default_zone.bulk_ec_sensors == ["sensor.ec_1", "sensor.ec_2"]


def test_pore_ec_sensors_defaults_to_empty_list() -> None:
    """pore_ec_sensors defaults to an empty list when absent from stored data."""
    assert _load({}).default_zone.pore_ec_sensors == []


def test_substrate_ec_sensors_field_removed() -> None:
    """EnvironmentConfig holds no substrate probe of any spelling."""
    config = EnvironmentConfig()
    for name in (
        "substrate_ec_sensors",
        "bulk_ec_sensors",
        "pore_ec_sensors",
        "soil_moisture_sensor",
        "substrate_temperature_sensors",
    ):
        assert not hasattr(config, name)


def test_bulk_ec_sensors_and_pore_ec_sensors_round_trip() -> None:
    """Both probe lists serialize and deserialize on the zone."""
    zone = IrrigationZone(
        id="default",
        bulk_ec_sensors=["sensor.bulk_1"],
        pore_ec_sensors=["sensor.pore_1"],
    )
    data = zone.to_dict()
    assert data["bulk_ec_sensors"] == ["sensor.bulk_1"]
    assert data["pore_ec_sensors"] == ["sensor.pore_1"]
    assert "substrate_ec_sensors" not in data
    assert IrrigationZone.from_dict(data) == zone
