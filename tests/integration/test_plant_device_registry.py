"""Tests for the Plant device-registry boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.growspace_manager import _async_remove_legacy_plant_devices
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.plant_facade import PlantFacade
from homeassistant.core import ServiceCall


async def test_adding_single_plant_leaves_device_count_unchanged() -> None:
    """Adding one Plant must not create a Home Assistant device."""
    coordinator = MagicMock()
    coordinator._plant_manager.add_plant = AsyncMock(
        return_value=Plant(plant_id="plant-1", growspace_id="growspace-1")
    )
    facade = PlantFacade(coordinator)
    device_registry = MagicMock()
    device_registry.devices = {"growspace-device": MagicMock()}
    initial_device_count = len(device_registry.devices)

    with patch(
        "homeassistant.helpers.device_registry.async_get",
        return_value=device_registry,
    ) as async_get_registry:
        await facade.add_plant(growspace_id="growspace-1", strain="OG Kush")

    assert len(device_registry.devices) == initial_device_count
    async_get_registry.assert_not_called()


async def test_adding_plant_batch_leaves_device_count_unchanged() -> None:
    """Adding a Plant batch must not create Home Assistant devices."""
    coordinator = MagicMock()
    coordinator.growspaces = {"growspace-1": MagicMock()}
    coordinator.validator.find_first_available_position.return_value = (1, 1)
    coordinator._plant_manager.add_plant = AsyncMock(
        side_effect=[
            Plant(plant_id="plant-1", growspace_id="growspace-1"),
            Plant(plant_id="plant-2", growspace_id="growspace-1"),
        ]
    )
    facade = PlantFacade(coordinator)
    call = MagicMock(spec=ServiceCall)
    call.data = {
        "growspace_id": "growspace-1",
        "strain": "OG Kush",
        "amount": 2,
    }
    device_registry = MagicMock()
    device_registry.devices = {"growspace-device": MagicMock()}
    initial_device_count = len(device_registry.devices)

    with patch(
        "homeassistant.helpers.device_registry.async_get",
        return_value=device_registry,
    ) as async_get_registry:
        await facade.add_plants_from_call(MagicMock(), MagicMock(), call)

    assert len(device_registry.devices) == initial_device_count
    async_get_registry.assert_not_called()


def test_cleanup_removes_only_legacy_plant_devices_for_entry() -> None:
    """Cleanup removes active and stale legacy devices without false positives."""
    entry = SimpleNamespace(entry_id="target-entry")
    devices = {
        "active": SimpleNamespace(
            id="active",
            manufacturer="Growspace Manager",
            model="Plant (OG Kush)",
        ),
        "stale": SimpleNamespace(
            id="stale",
            manufacturer="Growspace Manager",
            model="Plant",
        ),
        "other-entry": SimpleNamespace(
            id="other-entry",
            manufacturer="Growspace Manager",
            model="Plant (OG Kush)",
        ),
        "wrong-manufacturer": SimpleNamespace(
            id="wrong-manufacturer",
            manufacturer="Another Manufacturer",
            model="Plant (OG Kush)",
        ),
        "similar-model": SimpleNamespace(
            id="similar-model",
            manufacturer="Growspace Manager",
            model="Plant Sensor",
        ),
        "growspace": SimpleNamespace(
            id="growspace",
            manufacturer="Growspace Manager",
            model="Growspace",
        ),
        "strain-library": SimpleNamespace(
            id="strain-library",
            manufacturer="Growspace Manager",
            model="Strain Library",
        ),
        "service": SimpleNamespace(
            id="service",
            manufacturer="Growspace Manager",
            model="Service",
        ),
    }
    target_entry_device_ids = {
        "active",
        "stale",
        "wrong-manufacturer",
        "similar-model",
        "growspace",
        "strain-library",
        "service",
    }
    device_registry = MagicMock()

    def remove_entry_device(device_id: str, *, remove_config_entry_id: str) -> None:
        assert remove_config_entry_id == entry.entry_id
        devices.pop(device_id)

    device_registry.async_update_device.side_effect = remove_entry_device

    def devices_for_entry(
        _device_registry: MagicMock, config_entry_id: str
    ) -> list[SimpleNamespace]:
        assert config_entry_id == entry.entry_id
        return [
            device
            for device_id, device in devices.items()
            if device_id in target_entry_device_ids
        ]

    with (
        patch(
            "custom_components.growspace_manager.dr.async_get",
            return_value=device_registry,
        ),
        patch(
            "custom_components.growspace_manager.dr.async_entries_for_config_entry",
            side_effect=devices_for_entry,
        ),
    ):
        assert _async_remove_legacy_plant_devices(MagicMock(), entry) == 2
        assert set(devices) == {
            "other-entry",
            "wrong-manufacturer",
            "similar-model",
            "growspace",
            "strain-library",
            "service",
        }

        preserved_device_ids = set(devices)
        assert _async_remove_legacy_plant_devices(MagicMock(), entry) == 0
        assert set(devices) == preserved_device_ids
