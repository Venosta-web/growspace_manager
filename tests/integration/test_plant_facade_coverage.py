"""Coverage-focused integration tests for PlantFacade."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN, NotificationTier, PlantStage, VERSION
from custom_components.growspace_manager.models import (
    HarvestMetrics,
    PhenotypeScore,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.services.plant_facade import PlantFacade
from homeassistant.exceptions import ServiceValidationError


@pytest.mark.asyncio
async def test_plants_property(mock_coordinator: MagicMock) -> None:
    """Test plants property returns coordinator's plants."""
    facade = PlantFacade(mock_coordinator)
    plants = {"plant_1": Plant(plant_id="plant_1", growspace_id="gs1")}
    mock_coordinator.plants = plants
    assert facade.plants == plants


@pytest.mark.asyncio
async def test_get_plant(mock_coordinator: MagicMock) -> None:
    """Test get_plant calls data_repository."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_1", growspace_id="gs1")
    mock_coordinator._data_repository.get_plant.return_value = plant
    assert facade.get_plant("plant_1") == plant
    mock_coordinator._data_repository.get_plant.assert_called_once_with("plant_1")


@pytest.mark.asyncio
async def test_get_applicable_presets(mock_coordinator: MagicMock) -> None:
    """Test get_applicable_presets calls nutrient_manager."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._nutrient_manager.get_applicable_presets.return_value = ["preset1"]
    assert facade.get_applicable_presets("plant_1") == ["preset1"]
    mock_coordinator._nutrient_manager.get_applicable_presets.assert_called_once_with("plant_1")


@pytest.mark.asyncio
async def test_add_plant_success(mock_coordinator: MagicMock) -> None:
    """Test add_plant successfully registers HA device."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_1", growspace_id="gs1")
    plant.genetics = PlantGenetics(strain_name="OG Kush", phenotype_name="Pheno 1")
    mock_coordinator._plant_manager.add_plant = AsyncMock(return_value=plant)
    
    mock_dr = MagicMock()
    mock_dr.async_get_or_create = MagicMock()
    
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.add_plant(strain="OG Kush")
        
    assert result == plant
    mock_dr.async_get_or_create.assert_called_once_with(
        config_entry_id=mock_coordinator.config_entry.entry_id,
        identifiers={(DOMAIN, "plant_1")},
        name="OG Kush",
        model="Plant (OG Kush)",
        manufacturer="Growspace Manager",
        sw_version=VERSION,
        suggested_area="gs1",
    )


@pytest.mark.asyncio
async def test_add_plant_success_no_genetics(mock_coordinator: MagicMock) -> None:
    """Test add_plant successfully registers HA device with no genetics."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_1", growspace_id="gs1")
    plant.genetics = None
    mock_coordinator._plant_manager.add_plant = AsyncMock(return_value=plant)
    
    mock_dr = MagicMock()
    mock_dr.async_get_or_create = MagicMock()
    
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.add_plant()
        
    assert result == plant
    mock_dr.async_get_or_create.assert_called_once_with(
        config_entry_id=mock_coordinator.config_entry.entry_id,
        identifiers={(DOMAIN, "plant_1")},
        name="Unknown",
        model="Plant (Unknown)",
        manufacturer="Growspace Manager",
        sw_version=VERSION,
        suggested_area="gs1",
    )


@pytest.mark.asyncio
async def test_update_plant_name_no_device(mock_coordinator: MagicMock) -> None:
    """Test update_plant when device is not found in the device registry."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator._plant_manager.update_plant = AsyncMock(return_value=plant)

    # Mock device registry to return None (device not found)
    mock_dr = MagicMock()
    mock_dr.async_get_device.return_value = None

    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.update_plant("plant_123", name="New Name")

    assert result == plant
    mock_dr.async_get_device.assert_called_once_with(identifiers={(DOMAIN, "plant_123")})
    mock_dr.async_update_device.assert_not_called()


@pytest.mark.asyncio
async def test_update_plant_device_success(mock_coordinator: MagicMock) -> None:
    """Test update_plant when device is found and its name is updated in HA."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator._plant_manager.update_plant = AsyncMock(return_value=plant)

    mock_dr = MagicMock()
    mock_device = MagicMock()
    mock_device.id = "dev_123"
    mock_dr.async_get_device.return_value = mock_device

    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.update_plant("plant_123", name="New Name")

    assert result == plant
    mock_dr.async_get_device.assert_called_once_with(identifiers={(DOMAIN, "plant_123")})
    mock_dr.async_update_device.assert_called_once_with("dev_123", name="New Name")


@pytest.mark.asyncio
async def test_remove_plant_not_removed(mock_coordinator: MagicMock) -> None:
    """Test remove_plant when coordinator remove_plant returns False."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.remove_plant = AsyncMock(return_value=False)

    # We patch remove_plant_entities to verify it is not called
    with patch.object(facade, "remove_plant_entities", new_callable=AsyncMock) as mock_remove_entities:
        result = await facade.remove_plant("plant_123")

    assert result is False
    mock_remove_entities.assert_not_called()


@pytest.mark.asyncio
async def test_remove_plant_success(mock_coordinator: MagicMock) -> None:
    """Test remove_plant when coordinator remove_plant returns True."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.remove_plant = AsyncMock(return_value=True)

    with patch.object(facade, "remove_plant_entities", new_callable=AsyncMock) as mock_remove_entities:
        result = await facade.remove_plant("plant_123")

    assert result is True
    mock_remove_entities.assert_called_once_with("plant_123")


@pytest.mark.asyncio
async def test_async_remove_plant(mock_coordinator: MagicMock) -> None:
    """Test async_remove_plant alias."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.remove_plant = AsyncMock(return_value=True)

    # Patch remove_plant_entities to avoid HA registry calls
    with patch.object(facade, "remove_plant_entities", new_callable=AsyncMock) as mock_remove_entities:
        result = await facade.async_remove_plant("plant_123")

    assert result is True
    mock_remove_entities.assert_called_once_with("plant_123")


@pytest.mark.asyncio
async def test_remove_plant_entities(mock_coordinator: MagicMock) -> None:
    """Test remove_plant_entities removes correct HA entities."""
    facade = PlantFacade(mock_coordinator)
    mock_er = MagicMock()
    
    entry1 = MagicMock()
    entry1.unique_id = "plant_123_sensor"
    entry2 = MagicMock()
    entry2.unique_id = "plant_456_sensor"
    
    mock_er.entities = {
        "sensor.plant_123_sensor": entry1,
        "sensor.plant_456_sensor": entry2,
    }
    
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        await facade.remove_plant_entities("plant_123")
        
    mock_er.async_remove.assert_called_once_with("sensor.plant_123_sensor")


@pytest.mark.asyncio
async def test_add_mother_plant(mock_coordinator: MagicMock) -> None:
    """Test add_mother_plant calls coordinator plant_manager."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator._plant_manager.add_mother_plant = AsyncMock(return_value=plant)
    mock_coordinator.async_request_refresh = AsyncMock()

    result = await facade.add_mother_plant(
        phenotype="pheno1",
        strain="strain1",
        row=1,
        col=2,
        mother_start=date(2026, 5, 18),
    )

    assert result == plant
    mock_coordinator._plant_manager.add_mother_plant.assert_called_once_with(
        phenotype="pheno1",
        strain="strain1",
        row=1,
        col=2,
        mother_start=date(2026, 5, 18),
    )
    mock_coordinator.async_request_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_take_clones(mock_coordinator: MagicMock) -> None:
    """Test take_clones calls coordinator plant_manager."""
    facade = PlantFacade(mock_coordinator)
    clones = [Plant(plant_id="clone_1", growspace_id="gs1")]
    mock_coordinator._plant_manager.take_clones = AsyncMock(return_value=clones)

    result = await facade.take_clones(
        mother_plant_id="plant_123",
        num_clones=5,
        target_growspace_id="gs_clone",
    )

    assert result == clones
    mock_coordinator._plant_manager.take_clones.assert_called_once_with(
        mother_plant_id="plant_123",
        num_clones=5,
        target_growspace_id="gs_clone",
        target_growspace_name=None,
        transition_date=None,
    )


@pytest.mark.asyncio
async def test_promote_clone(mock_coordinator: MagicMock) -> None:
    """Test promote_clone calls coordinator."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.promote_clone = AsyncMock()

    await facade.promote_clone("clone_123", target_growspace_id="veg")

    mock_coordinator._plant_manager.promote_clone.assert_called_once_with(
        clone_id="clone_123",
        target_growspace_id="veg",
        transition_date=None,
    )


@pytest.mark.asyncio
async def test_switch_plants(mock_coordinator: MagicMock) -> None:
    """Test switch_plants calls coordinator."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.switch_plants = AsyncMock()

    await facade.switch_plants("plant1", "plant2")

    mock_coordinator._plant_manager.switch_plants.assert_called_once_with("plant1", "plant2")


@pytest.mark.asyncio
async def test_move_plant(mock_coordinator: MagicMock) -> None:
    """Test move_plant calls coordinator."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.move_plant = AsyncMock()

    await facade.move_plant("plant1", 2, 3)

    mock_coordinator._plant_manager.move_plant.assert_called_once_with("plant1", 2, 3)


@pytest.mark.asyncio
async def test_transition_plant_stage(mock_coordinator: MagicMock) -> None:
    """Test transition_plant_stage calls coordinator."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.transition_plant_stage = AsyncMock()

    await facade.transition_plant_stage("plant1", PlantStage.FLOWER)

    mock_coordinator._plant_manager.transition_plant_stage.assert_called_once_with(
        "plant1", PlantStage.FLOWER, None
    )


@pytest.mark.asyncio
async def test_harvest(mock_coordinator: MagicMock) -> None:
    """Test harvest calls coordinator."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant1", growspace_id="gs1")
    mock_coordinator._plant_manager.harvest = AsyncMock(return_value=plant)

    result = await facade.harvest("plant1")

    assert result == plant
    mock_coordinator._plant_manager.harvest.assert_called_once_with("plant1")


@pytest.mark.asyncio
async def test_async_harvest_plant(mock_coordinator: MagicMock) -> None:
    """Test async_harvest_plant alias."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator._plant_manager.transition_plant = AsyncMock()

    await facade.async_transition_plant(
        plant_id="plant_123",
        target_growspace_id="gs_dry",
        wet_weight=100.0,
    )

    mock_coordinator._plant_manager.transition_plant.assert_called_once_with(
        plant_id="plant_123",
        target_growspace_id="gs_dry",
        target_growspace_name=None,
        transition_date=None,
        wet_weight=100.0,
        dry_weight=None,
        trim_weight=None,
        thc_percentage=None,
        cbd_percentage=None,
        terpene_profile=None,
    )


@pytest.mark.asyncio
async def test_async_auto_harvest(mock_coordinator: MagicMock) -> None:
    """Test _async_auto_harvest auto-harvests eligible flowering plants only."""
    facade = PlantFacade(mock_coordinator)
    
    plant1 = Plant(plant_id="plant1", growspace_id="gs1")
    plant1.genetics = PlantGenetics(strain_name="OG Kush")
    plant1.transition_date = "2026-01-10"  # before frozen "2026-01-12"
    plant1.stage = PlantStage.FLOWER
    
    plant2 = Plant(plant_id="plant2", growspace_id="gs1")
    plant2.genetics = PlantGenetics(strain_name="LSD")
    plant2.transition_date = "2026-01-15"  # after frozen
    plant2.stage = PlantStage.FLOWER

    mock_coordinator.plants = {"plant1": plant1, "plant2": plant2}
    mock_coordinator._plant_manager.harvest = AsyncMock()
    mock_coordinator._notification_manager.async_send_notification = AsyncMock()

    # Call private method
    await facade._async_auto_harvest()

    mock_coordinator._plant_manager.harvest.assert_called_once_with(
        plant_id="plant1",
        transition_date="2026-01-12",
    )
    mock_coordinator._notification_manager.async_send_notification.assert_called_once_with(
        growspace_id="gs1",
        title="Auto-harvest complete",
        message="Plant OG Kush has been auto-harvested",
        tier=NotificationTier.INFO,
    )


@pytest.mark.asyncio
async def test_water_plant(mock_coordinator: MagicMock) -> None:
    """Test water_plant calls watering service."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant1", growspace_id="gs1")
    mock_coordinator.watering_service.async_water_plant = AsyncMock(return_value=plant)

    result = await facade.water_plant("plant1", 500.0, preset_id="p1")

    assert result == plant
    mock_coordinator.watering_service.async_water_plant.assert_called_once_with(
        "plant1", 500.0, None, "p1"
    )


@pytest.mark.asyncio
async def test_apply_ipm(mock_coordinator: MagicMock) -> None:
    """Test apply_ipm calls ipm service."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.ipm_service.async_apply_ipm = AsyncMock(return_value=["plant1"])

    result = await facade.apply_ipm(preset_id="p1", growspace_id="gs1")

    assert result == ["plant1"]
    mock_coordinator.ipm_service.async_apply_ipm.assert_called_once_with(
        "p1", "gs1", None, None
    )


@pytest.mark.asyncio
async def test_log_training_event(mock_coordinator: MagicMock) -> None:
    """Test log_training_event calls training service."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.training_service.async_log_training_event = AsyncMock()

    await facade.log_training_event("gs1", "LST", notes="bent main stem")

    mock_coordinator.training_service.async_log_training_event.assert_called_once_with(
        "gs1", "LST", "bent main stem", None
    )


@pytest.mark.asyncio
async def test_log_drying_weight_success(mock_coordinator: MagicMock) -> None:
    """Test logging drying weight successfully with standard and default dates."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}

    # Test with custom date
    await facade.log_drying_weight("plant_123", 45.2, "2026-05-18")
    assert len(plant.drying_data.weight_log) == 1
    assert plant.drying_data.weight_log[0].weight_grams == 45.2
    assert plant.drying_data.weight_log[0].date == "2026-05-18"

    # Test with default/frozen date (frozen to 2026-01-12 in freeze_time fixture)
    await facade.log_drying_weight("plant_123", 43.1)
    assert len(plant.drying_data.weight_log) == 2
    assert plant.drying_data.weight_log[1].weight_grams == 43.1
    assert plant.drying_data.weight_log[1].date == "2026-01-12"

    mock_coordinator.async_commit.assert_called()


@pytest.mark.asyncio
async def test_log_drying_weight_not_found(mock_coordinator: MagicMock) -> None:
    """Test logging drying weight raises ServiceValidationError when plant is not found."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="Plant 'plant_123' not found"):
        await facade.log_drying_weight("plant_123", 45.2)


@pytest.mark.asyncio
async def test_log_moisture_reading_success(mock_coordinator: MagicMock) -> None:
    """Test logging moisture reading successfully with standard and default dates."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}

    # Test with custom date
    await facade.log_moisture_reading("plant_123", 12.5, "2026-05-18")
    assert len(plant.drying_data.moisture_log) == 1
    assert plant.drying_data.moisture_log[0].moisture_percent == 12.5
    assert plant.drying_data.moisture_log[0].date == "2026-05-18"

    # Test with default/frozen date (frozen to 2026-01-12 in freeze_time fixture)
    await facade.log_moisture_reading("plant_123", 11.2)
    assert len(plant.drying_data.moisture_log) == 2
    assert plant.drying_data.moisture_log[1].moisture_percent == 11.2
    assert plant.drying_data.moisture_log[1].date == "2026-01-12"

    mock_coordinator.async_commit.assert_called()


@pytest.mark.asyncio
async def test_log_moisture_reading_not_found(mock_coordinator: MagicMock) -> None:
    """Test logging moisture reading raises ServiceValidationError when plant is not found."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="Plant 'plant_123' not found"):
        await facade.log_moisture_reading("plant_123", 12.5)


@pytest.mark.asyncio
async def test_set_visual_tag_success(mock_coordinator: MagicMock) -> None:
    """Test setting and clearing a visual tag on a plant."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}

    await facade.set_visual_tag("plant_123", "Blue-Tag")
    assert plant.drying_data.visual_tag == "Blue-Tag"

    await facade.set_visual_tag("plant_123", None)
    assert plant.drying_data.visual_tag is None

    mock_coordinator.async_commit.assert_called()


@pytest.mark.asyncio
async def test_set_visual_tag_not_found(mock_coordinator: MagicMock) -> None:
    """Test setting visual tag raises ServiceValidationError when plant is not found."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="Plant 'plant_123' not found"):
        await facade.set_visual_tag("plant_123", "Tag")


@pytest.mark.asyncio
async def test_score_plant_not_found(mock_coordinator: MagicMock) -> None:
    """Test score_plant raises ServiceValidationError when plant is not found."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="Plant plant_123 not found"):
        await facade.score_plant("plant_123")


@pytest.mark.asyncio
async def test_score_plant_success_full(mock_coordinator: MagicMock) -> None:
    """Test score_plant success path covering all fields, legacy names, and standard fields."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}
    mock_coordinator._plant_manager.update_plant = AsyncMock()

    # Pass all standard, custom and legacy fields to cover all branches in score_plant
    await facade.score_plant(
        plant_id="plant_123",
        vigor=8,
        structure=7,
        aroma=9,
        resin=8,
        pest_resistance=6,
        yield_potential=9,
        keeper=True,
        notes="Amazing vigor and resin",
    )

    ps = plant.phenotype_score
    assert ps.vigor == 8
    assert ps.internodal_spacing == 7
    assert ps.terpene_intensity == 9
    assert ps.resin == 8
    assert ps.mold_resistance == 6
    assert ps.yield_potential == 9
    assert ps.keeper is True
    assert ps.notes == "Amazing vigor and resin"

    mock_coordinator._plant_manager.update_plant.assert_called_once_with("plant_123", phenotype_score=ps)


@pytest.mark.asyncio
async def test_score_plant_success_alternative_names(mock_coordinator: MagicMock) -> None:
    """Test score_plant success path covering non-legacy names (e.g. internodal_spacing, terpene_intensity, mold_resistance)."""
    facade = MagicMock()
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}
    mock_coordinator._plant_manager.update_plant = AsyncMock()

    await facade.score_plant(
        plant_id="plant_123",
        internodal_spacing=6,
        terpene_intensity=8,
        mold_resistance=7,
    )

    ps = plant.phenotype_score
    assert ps.internodal_spacing == 6
    assert ps.terpene_intensity == 8
    assert ps.mold_resistance == 7

    mock_coordinator._plant_manager.update_plant.assert_called_once_with("plant_123", phenotype_score=ps)


@pytest.mark.asyncio
async def test_update_harvest_metrics_not_found(mock_coordinator: MagicMock) -> None:
    """Test update_harvest_metrics raises ServiceValidationError when plant is not found."""
    facade = PlantFacade(mock_coordinator)
    mock_coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="Plant plant_123 not found"):
        await facade.update_harvest_metrics("plant_123")


@pytest.mark.asyncio
async def test_update_harvest_metrics_success(mock_coordinator: MagicMock) -> None:
    """Test update_harvest_metrics success path when plant is found and all fields are provided."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}
    mock_coordinator._plant_manager.update_plant = AsyncMock()

    await facade.update_harvest_metrics(
        plant_id="plant_123",
        wet_weight=150.0,
        dry_weight=35.5,
        trim_weight=12.2,
        thc_percentage=22.4,
        cbd_percentage=0.8,
        terpene_profile="Myrcene, Limonene",
    )

    metrics = plant.harvest_metrics
    assert metrics.wet_weight == 150.0
    assert metrics.dry_weight == 35.5
    assert metrics.trim_weight == 12.2
    assert metrics.thc_percentage == 22.4
    assert metrics.cbd_percentage == 0.8
    assert metrics.terpene_profile == "Myrcene, Limonene"

    mock_coordinator._plant_manager.update_plant.assert_called_once_with("plant_123", harvest_metrics=metrics)


@pytest.mark.asyncio
async def test_update_harvest_metrics_no_update(mock_coordinator: MagicMock) -> None:
    """Test update_harvest_metrics when no metrics are provided and thus no update is triggered."""
    facade = PlantFacade(mock_coordinator)
    plant = Plant(plant_id="plant_123", growspace_id="gs1")
    mock_coordinator.plants = {"plant_123": plant}
    mock_coordinator._plant_manager.update_plant = AsyncMock()

    await facade.update_harvest_metrics("plant_123")

    mock_coordinator._plant_manager.update_plant.assert_not_called()
