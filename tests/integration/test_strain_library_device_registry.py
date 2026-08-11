"""Tests for the Strain Library device-registry boundary."""

from unittest.mock import MagicMock

from custom_components.growspace_manager.sensor import (
    GrowspaceListSensor,
    SeedInventorySensor,
    StrainLibrarySensor,
    VpdSensor,
)


def test_genetics_entities_share_one_dedicated_device() -> None:
    """Strain Library and Seed Inventory resolve to one dedicated device."""
    coordinator = MagicMock()

    strain_library = StrainLibrarySensor(coordinator)
    seed_inventory = SeedInventorySensor(coordinator)

    assert strain_library.device_info == seed_inventory.device_info
    assert strain_library.device_info["identifiers"] == {
        ("growspace_manager", "strain_library")
    }


def test_general_overview_and_vpd_remain_on_service_device() -> None:
    """General overview and global VPD retain service-device ownership."""
    coordinator = MagicMock()
    coordinator.plants = {}
    coordinator.growspaces = {}

    overview = GrowspaceListSensor(coordinator)
    vpd = VpdSensor(coordinator, "outside", "Outside VPD", None, None, None)

    assert overview.device_info["identifiers"] == {("growspace_manager", "service")}
    assert vpd.device_info["identifiers"] == {("growspace_manager", "service")}
