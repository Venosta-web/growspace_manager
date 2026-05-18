"""Tests for StrainLibrarySensor — performance optimization."""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.sensor import StrainLibrarySensor


def _make_sensor() -> StrainLibrarySensor:
    """Build a minimal StrainLibrarySensor without a live coordinator."""
    coordinator = MagicMock()
    coordinator.strain_library.get_all.return_value = {
        "OG Kush": {"meta": {}, "phenotypes": {}},
    }
    # Mock analytics result without lineage_trees
    coordinator.strain_library.get_analytics.return_value = {
        "strains": {"OG Kush": {}},
        "strain_list": ["OG Kush"],
    }
    sensor = StrainLibrarySensor.__new__(StrainLibrarySensor)
    sensor.coordinator = coordinator
    return sensor


def test_strain_library_sensor_no_longer_has_unrecorded_lineage_trees() -> None:
    """Verify lineage_trees is removed from _unrecorded_attributes."""
    sensor = _make_sensor()
    assert "lineage_trees" not in sensor._unrecorded_attributes


def test_strain_library_sensor_extra_attrs_exclude_lineage_trees() -> None:
    """Verify lineage_trees is excluded from extra_state_attributes."""
    sensor = _make_sensor()
    attrs = sensor.extra_state_attributes
    assert "lineage_trees" not in attrs


def test_strain_library_sensor_analytics_basics() -> None:
    """Verify basic analytics are still present."""
    sensor = _make_sensor()
    attrs = sensor.extra_state_attributes
    assert attrs["strain_count"] == 1
    assert attrs["strain_list"] == ["OG Kush"]
