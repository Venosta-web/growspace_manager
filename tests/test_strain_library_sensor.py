"""Tests for StrainLibrarySensor — lineage_trees unrecorded attribute."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.sensor import StrainLibrarySensor


def _make_sensor() -> StrainLibrarySensor:
    """Build a minimal StrainLibrarySensor without a live coordinator."""
    coordinator = MagicMock()
    coordinator.strain_library.get_all.return_value = {
        "OG Kush": {"meta": {}, "phenotypes": {}},
    }
    coordinator.strain_library.get_analytics.return_value = {
        "strains": {"OG Kush": {}},
        "strain_list": ["OG Kush"],
        "lineage_trees": {
            "OG Kush": {"name": "OG Kush", "parents": []},
        },
    }
    coordinator.strain_library.get_strain_lineage_tree.return_value = {
        "name": "OG Kush",
        "parents": [],
    }
    sensor = StrainLibrarySensor.__new__(StrainLibrarySensor)
    sensor.coordinator = coordinator
    return sensor


def test_strain_library_sensor_has_unrecorded_lineage_trees() -> None:
    sensor = _make_sensor()
    assert "lineage_trees" in sensor._unrecorded_attributes


def test_strain_library_sensor_extra_attrs_include_lineage_trees() -> None:
    sensor = _make_sensor()
    attrs = sensor.extra_state_attributes
    assert "lineage_trees" in attrs
    assert isinstance(attrs["lineage_trees"], dict)


def test_strain_library_sensor_lineage_trees_keyed_by_strain_name() -> None:
    sensor = _make_sensor()
    attrs = sensor.extra_state_attributes
    assert "OG Kush" in attrs["lineage_trees"]
    assert attrs["lineage_trees"]["OG Kush"] == {"name": "OG Kush", "parents": []}
