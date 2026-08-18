"""Tests for StrainLibrarySensor — performance optimization."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.sensor import StrainLibrarySensor


def _make_sensor() -> StrainLibrarySensor:
    """Build a minimal StrainLibrarySensor without a live coordinator."""
    coordinator = MagicMock()
    coordinator.services.config.strain_library.get_all.return_value = {
        "OG Kush": {"meta": {}, "phenotypes": {}},
        "Hindu Kush": {"meta": {"is_stub": True}, "phenotypes": {}},
    }
    coordinator.services.config.strain_library.get_analytics.return_value = {
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
    assert attrs["ancestor_strain_count"] == 1
    assert attrs["total_strain_count"] == 2
    assert attrs["strain_list"] == ["OG Kush"]


def test_strain_library_sensor_state_counts_only_catalogued_strains() -> None:
    """The state excludes lineage-only ancestor strains."""
    sensor = _make_sensor()
    assert sensor.native_value == 1


def test_strain_library_sensor_native_value_no_library() -> None:
    """native_value returns 0 when the strain library hasn't loaded yet."""
    coordinator = MagicMock()
    coordinator.services.config.strain_library = None
    sensor = StrainLibrarySensor.__new__(StrainLibrarySensor)
    sensor.coordinator = coordinator
    assert sensor.native_value == 0


def test_strain_library_sensor_extra_attrs_no_library() -> None:
    """extra_state_attributes returns {} when the strain library hasn't loaded yet."""
    coordinator = MagicMock()
    coordinator.services.config.strain_library = None
    sensor = StrainLibrarySensor.__new__(StrainLibrarySensor)
    sensor.coordinator = coordinator
    assert sensor.extra_state_attributes == {}


def test_strain_library_sensor_uses_dedicated_device() -> None:
    """The Strain Library sensor uses the same dedicated device identifier."""
    coordinator = MagicMock()
    sensor = StrainLibrarySensor(coordinator)
    assert sensor.device_info is not None
    assert sensor.device_info["identifiers"] == {
        ("growspace_manager", "strain_library")
    }
