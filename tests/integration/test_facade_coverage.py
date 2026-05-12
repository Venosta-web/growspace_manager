from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.models import DrainConfig, Growspace
from custom_components.growspace_manager.services.facade import ServiceFacade
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.mark.asyncio
async def test_update_plant_name_change(
    hass: HomeAssistant, mock_coordinator, mock_plant
) -> None:
    """Test updating plant name updates the device name."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.async_update_plant = AsyncMock(
        return_value=mock_plant
    )

    # Mock device registry
    mock_dr = MagicMock()
    mock_device = MagicMock()
    mock_device.id = "device_1"
    mock_dr.async_get_device.return_value = mock_device

    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        await facade.update_plant("plant_1", name="New Plant Name")

    mock_dr.async_update_device.assert_called_once_with(
        "device_1", name="New Plant Name"
    )


@pytest.mark.asyncio
async def test_async_auto_harvest(
    hass: HomeAssistant, mock_coordinator, mock_plant
) -> None:
    """Test auto-harvesting plants that reached their transition date."""
    facade = ServiceFacade(mock_coordinator)

    # Setup plant to be harvested
    # Today is 2026-01-12 in frozen time (if frozen, otherwise use real date or mock it)
    # The integration uses datetime.now().date().isoformat()
    today = datetime.now().date().isoformat()

    mock_plant.plant_id = "p1"
    mock_plant.transition_date = today
    mock_plant.stage = PlantStage.FLOWER
    mock_plant.genetics.strain_name = "Blue Dream"
    mock_plant.growspace_id = "gs1"

    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.plant_manager.harvest = AsyncMock()
    mock_coordinator.notification_manager.async_send_notification = AsyncMock()

    await facade._async_auto_harvest()

    mock_coordinator.plant_manager.harvest.assert_called_once_with(
        plant_id="p1", transition_date=today
    )
    mock_coordinator.notification_manager.async_send_notification.assert_called_once()


@pytest.mark.asyncio
async def test_remove_plant_entities(hass: HomeAssistant, mock_coordinator) -> None:
    """Test removing HA entities associated with a plant."""
    facade = ServiceFacade(mock_coordinator)

    # Mock entity registry
    mock_er = MagicMock()
    entry1 = MagicMock()
    entry1.unique_id = "p1_sensor1"
    entry2 = MagicMock()
    entry2.unique_id = "p1_sensor2"
    entry3 = MagicMock()
    entry3.unique_id = "p2_sensor1"

    mock_er.entities = {
        "sensor.p1_s1": entry1,
        "sensor.p1_s2": entry2,
        "sensor.p2_s1": entry3,
    }

    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        # Service call to remove_plant will trigger _remove_plant_entities
        mock_coordinator.plant_manager.remove_plant = AsyncMock(return_value=True)
        await facade.remove_plant("p1")

    assert mock_er.async_remove.call_count == 2
    mock_er.async_remove.assert_any_call("sensor.p1_s1")
    mock_er.async_remove.assert_any_call("sensor.p1_s2")


@pytest.mark.asyncio
async def test_ipm_management(mock_coordinator) -> None:
    """Test IPM preset management services."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.ipm_service.async_save_ipm_preset = AsyncMock()
    mock_coordinator.ipm_service.async_remove_ipm_preset = AsyncMock()
    mock_coordinator.ipm_service.async_apply_ipm = AsyncMock()

    await facade.save_ipm_preset("Test", "Foliar", [])
    mock_coordinator.ipm_service.async_save_ipm_preset.assert_called_once()

    await facade.remove_ipm_preset("preset_1")
    mock_coordinator.ipm_service.async_remove_ipm_preset.assert_called_once_with(
        "preset_1"
    )

    await facade.apply_ipm("preset_1", growspace_id="gs1")
    mock_coordinator.ipm_service.async_apply_ipm.assert_called_once()


@pytest.mark.asyncio
async def test_log_drain_reading(mock_coordinator) -> None:
    """Test logging drain readings and rolling window logic."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    gs.drain_config = DrainConfig(max_readings=2)
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()

    # Test error
    with pytest.raises(ServiceValidationError):
        await facade.log_drain_reading("unknown", 2.0, 1.8)

    # Add readings
    await facade.log_drain_reading("gs1", 2.0, 1.8)
    await facade.log_drain_reading("gs1", 2.1, 1.7)
    assert len(gs.drain_config.readings) == 2

    # Trigger roll
    await facade.log_drain_reading("gs1", 2.2, 1.6)
    assert len(gs.drain_config.readings) == 2
    assert gs.drain_config.readings[-1].feed_ec == 2.2
    assert mock_coordinator.async_commit.call_count == 3


@pytest.mark.asyncio
async def test_growspace_lifecycle_services(mock_coordinator) -> None:
    """Test growspace management services (remove, options, lights)."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.services.remove_growspace = AsyncMock()
    mock_coordinator.services.update_options = AsyncMock()
    mock_coordinator.services.set_lighting_schedule = AsyncMock()

    await facade.remove_growspace("gs1")
    mock_coordinator.services.remove_growspace.assert_called_once_with("gs1")

    await facade.update_options({"opt": "val"})
    mock_coordinator.services.update_options.assert_called_once_with({"opt": "val"})

    await facade.async_set_lighting_schedule("gs1", 12, 12, 12)
    mock_coordinator.services.set_lighting_schedule.assert_called_once_with(
        "gs1", 12, 12, 12
    )
