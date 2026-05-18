"""Comprehensive tests for ServiceFacade to increase coverage."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN, PlantStage
from custom_components.growspace_manager.models import (
    DrainConfig,
    ECRampCurve,
    EnvironmentConfig,
    Growspace,
    HarvestMetrics,
    IrrigationConfig,
    IrrigationTank,
    PhenotypeScore,
    Plant,
    PlantGenetics,
    WaterUsageData,
)
from custom_components.growspace_manager.services.facade import ServiceFacade
from homeassistant.exceptions import ServiceValidationError


def test_getattr_unknown_raises(mock_coordinator) -> None:
    """Accessing an unknown attribute should raise AttributeError."""
    facade = ServiceFacade(mock_coordinator)
    with pytest.raises(AttributeError):
        _ = facade.does_not_exist_at_all


# ---------------------------------------------------------------------------
# save / request_refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_delegates_to_commit(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.async_commit = AsyncMock()
    await facade.save()
    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_refresh_delegates(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.async_request_refresh = AsyncMock()
    await facade.request_refresh()
    mock_coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# add_growspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_growspace_registers_device(mock_coordinator) -> None:
    """add_growspace should create a device entry in the HA registry."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    gs.id = "gs1"
    gs.name = "Tent 1"
    gs.growspace_type = None
    mock_coordinator.growspace_manager.add_growspace = AsyncMock(return_value=gs)
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = (
        AsyncMock()
    )

    mock_dr = MagicMock()
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.add_growspace(name="Tent 1")

    assert result is gs
    mock_dr.async_get_or_create.assert_called_once()
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators.assert_awaited_once_with(
        "gs1", gs
    )


@pytest.mark.asyncio
async def test_add_growspace_with_type(mock_coordinator) -> None:
    """add_growspace passes growspace_type to device model."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    gs.id = "gs2"
    gs.name = "Veg Room"
    gs_type = MagicMock()
    gs_type.value = "veg_room"
    gs.growspace_type = gs_type
    mock_coordinator.growspace_manager.add_growspace = AsyncMock(return_value=gs)
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = (
        AsyncMock()
    )

    mock_dr = MagicMock()
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        await facade.add_growspace(name="Veg Room", growspace_type=gs_type)

    call_kwargs = mock_dr.async_get_or_create.call_args.kwargs
    assert call_kwargs["model"] == "veg_room"


# ---------------------------------------------------------------------------
# update_growspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_growspace_no_name_change(mock_coordinator) -> None:
    """update_growspace without name kwarg should not touch device registry."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    mock_coordinator.growspace_manager.update_growspace = AsyncMock(return_value=gs)

    mock_dr = MagicMock()
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.update_growspace("gs1", rows=5)

    assert result is gs
    mock_dr.async_update_device.assert_not_called()


@pytest.mark.asyncio
async def test_update_growspace_with_name_change(mock_coordinator) -> None:
    """update_growspace with name kwarg should update the device name."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    mock_coordinator.growspace_manager.update_growspace = AsyncMock(return_value=gs)

    mock_dr = MagicMock()
    mock_device = MagicMock()
    mock_device.id = "dev_id"
    mock_dr.async_get_device.return_value = mock_device
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        await facade.update_growspace("gs1", name="New Name")

    mock_dr.async_update_device.assert_called_once_with("dev_id", name="New Name")


# ---------------------------------------------------------------------------
# add_plant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_plant_registers_device(mock_coordinator) -> None:
    """add_plant should create a device entry for the plant."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.genetics = MagicMock()
    plant.genetics.strain_name = "OG Kush"
    mock_coordinator.plant_manager.add_plant = AsyncMock(return_value=plant)

    mock_dr = MagicMock()
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.add_plant(growspace_id="gs1", strain="OG Kush")

    assert result is plant
    mock_dr.async_get_or_create.assert_called_once()


@pytest.mark.asyncio
async def test_add_plant_no_genetics(mock_coordinator) -> None:
    """add_plant should handle missing genetics gracefully."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.plant_id = "p2"
    plant.growspace_id = "gs1"
    plant.genetics = None
    mock_coordinator.plant_manager.add_plant = AsyncMock(return_value=plant)

    mock_dr = MagicMock()
    with patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr):
        result = await facade.add_plant(growspace_id="gs1", strain="")

    assert result is plant
    call_kwargs = mock_dr.async_get_or_create.call_args.kwargs
    assert call_kwargs["name"] == "Unknown"


# ---------------------------------------------------------------------------
# Subarea operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_subarea(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    sub = MagicMock()
    mock_coordinator.growspace_manager.add_subarea = AsyncMock(return_value=sub)
    result = await facade.add_subarea("gs1", "Zone A")
    mock_coordinator.growspace_manager.add_subarea.assert_awaited_once_with(
        "gs1", "Zone A"
    )
    assert result is sub


@pytest.mark.asyncio
async def test_update_subarea(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspace_manager.update_subarea = AsyncMock(return_value=None)
    await facade.update_subarea("gs1", "sub1", {"temperature": 25})
    mock_coordinator.growspace_manager.update_subarea.assert_awaited_once_with(
        "gs1", "sub1", {"temperature": 25}
    )


@pytest.mark.asyncio
async def test_remove_subarea(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspace_manager.remove_subarea = AsyncMock()
    await facade.remove_subarea("gs1", "sub1")
    mock_coordinator.growspace_manager.remove_subarea.assert_awaited_once_with(
        "gs1", "sub1"
    )


def test_get_subareas(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspace_manager.get_subareas = MagicMock(return_value=["sub1"])
    result = facade.get_subareas("gs1")
    assert result == ["sub1"]


# ---------------------------------------------------------------------------
# Sync getters / properties
# ---------------------------------------------------------------------------


def test_get_growspace(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    assert facade.get_growspace("gs1") is gs


def test_get_sorted_growspace_options(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Tent")]
    )
    assert facade.get_sorted_growspace_options() == [("gs1", "Tent")]


def test_properties(mock_coordinator) -> None:
    """All pass-through properties should return the coordinator's values."""
    facade = ServiceFacade(mock_coordinator)

    assert facade.growspaces is mock_coordinator.growspaces
    assert facade.plants is mock_coordinator.plants
    assert facade.growspace_manager is mock_coordinator.growspace_manager
    assert facade.plant_manager is mock_coordinator.plant_manager
    assert facade.strain_library is mock_coordinator.strain_library
    assert facade.nutrient_manager is mock_coordinator.nutrient_manager
    assert facade.watering_service is mock_coordinator._watering_service
    assert facade.training_service is mock_coordinator._training_service
    assert facade.ipm_service is mock_coordinator._ipm_service
    assert facade.notification_manager is mock_coordinator.notification_manager
    assert facade.notification_settings is mock_coordinator.notification_settings


def test_get_growspace_grid(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    grid = [[None, None]]
    mock_coordinator.data_repository.get_growspace_grid = MagicMock(return_value=grid)
    assert facade.get_growspace_grid("gs1") is grid


def test_get_canonical_special(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspace_manager.get_canonical_special = MagicMock(
        return_value=("veg", "Veg")
    )
    assert facade.get_canonical_special("veg") == ("veg", "Veg")


# ---------------------------------------------------------------------------
# set_lighting_schedule / async_set_lighting_schedule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_lighting_schedule_invalid_growspace(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    with pytest.raises(ServiceValidationError):
        await facade.async_set_lighting_schedule("missing", 18, 12)


@pytest.mark.asyncio
async def test_set_lighting_schedule_alias(mock_coordinator) -> None:
    """set_lighting_schedule (sync alias) should call the async version."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    gs.environment_config = MagicMock()
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    await facade.set_lighting_schedule("gs1", 18, 12)
    assert gs.environment_config.veg_day_hours == 18
    assert gs.environment_config.flower_day_hours == 12


@pytest.mark.asyncio
async def test_set_lighting_schedule_no_dli(mock_coordinator) -> None:
    """async_set_lighting_schedule without dli_veg should not set dli_target_veg."""
    from custom_components.growspace_manager.models import EnvironmentConfig

    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    original_dli = gs.environment_config.dli_target_veg
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    await facade.async_set_lighting_schedule("gs1", 18, 12, dli_veg=None)
    assert gs.environment_config.dli_target_veg == original_dli  # unchanged


# ---------------------------------------------------------------------------
# Notification settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_notifications_enabled_unknown_growspace(mock_coordinator) -> None:
    """set_notifications_enabled for unknown growspace calls set_notifications_state directly."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    mock_coordinator.notification_settings.set_notifications_state = MagicMock()

    await facade.set_notifications_enabled("unknown_gs", True)
    mock_coordinator.notification_settings.set_notifications_state.assert_called_once_with(
        "unknown_gs", True
    )
    mock_coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_notifications_enabled_known_growspace(mock_coordinator) -> None:
    """set_notifications_enabled for known growspace persists via async_commit."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.notification_settings.set_notifications_state = MagicMock(
        return_value={"gs1": True}
    )
    mock_coordinator.async_commit = AsyncMock()

    await facade.set_notifications_enabled("gs1", True)
    mock_coordinator.async_commit.assert_awaited_once()


def test_get_timed_notifications(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notification_settings.get_timed_notifications = MagicMock(
        return_value=[{"id": "n1"}]
    )
    assert facade.get_timed_notifications() == [{"id": "n1"}]


@pytest.mark.asyncio
async def test_add_timed_notification(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notification_settings.get_timed_notifications = MagicMock(
        return_value=[]
    )
    new_note = {"id": "n1", "message": "Water time!"}
    mock_coordinator.notification_settings.create_timed_notification = MagicMock(
        return_value=new_note
    )
    # update_options calls async_commit
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.config_entry = MagicMock()
    mock_coordinator.config_entry.options = {}

    await facade.add_timed_notification("Water time!", "day", 7)
    mock_coordinator.notification_settings.create_timed_notification.assert_called_once()


@pytest.mark.asyncio
async def test_update_timed_notification(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notification_settings.get_timed_notifications = MagicMock(
        return_value=[{"id": "n1"}]
    )
    mock_coordinator.notification_settings.update_timed_notification_in_list = (
        MagicMock(return_value=True)
    )
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.config_entry = MagicMock()
    mock_coordinator.config_entry.options = {}

    await facade.update_timed_notification("n1", "Updated", "day", 7)
    mock_coordinator.notification_settings.update_timed_notification_in_list.assert_called_once()


@pytest.mark.asyncio
async def test_remove_timed_notification(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notification_settings.get_timed_notifications = MagicMock(
        return_value=[{"id": "n1"}]
    )
    mock_coordinator.notification_settings.remove_timed_notification_from_list = (
        MagicMock(return_value=[])
    )
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.config_entry = MagicMock()
    mock_coordinator.config_entry.options = {}

    await facade.remove_timed_notification("n1")
    mock_coordinator.notification_settings.remove_timed_notification_from_list.assert_called_once()


def test_is_notifications_enabled(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notification_settings.is_notifications_enabled = MagicMock(
        return_value=True
    )
    assert facade.is_notifications_enabled("gs1") is True


# ---------------------------------------------------------------------------
# add_mother_plant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_mother_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    mock_coordinator.plant_manager.add_mother_plant = AsyncMock(return_value=plant)
    mock_coordinator.async_request_refresh = AsyncMock()

    result = await facade.add_mother_plant(
        phenotype="A", strain="Strain X", row=0, col=0
    )
    assert result is plant
    mock_coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_irrigation_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_irrigation_config_not_found(mock_coordinator) -> None:
    """update_irrigation_config raises error if growspace not found."""
    from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError

    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    with pytest.raises(GrowspaceNotFoundError):
        await facade.update_irrigation_config("missing", {})


@pytest.mark.asyncio
async def test_update_irrigation_config_clear(mock_coordinator) -> None:
    """Clear flag resets irrigation config."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    gs.irrigation_config = MagicMock()
    gs.irrigation_strategy = MagicMock()
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()

    await facade.update_irrigation_config("gs1", {"clear": True})

    assert isinstance(gs.irrigation_config, IrrigationConfig)
    assert gs.irrigation_strategy.enabled is False
    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_irrigation_config_vwc_steering(mock_coordinator) -> None:
    """use_vwc_steering sets strategy.enabled."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.cache = MagicMock()

    await facade.update_irrigation_config("gs1", {"use_vwc_steering": True})
    assert gs.irrigation_strategy.enabled is True


@pytest.mark.asyncio
async def test_update_irrigation_config_sets_fields(mock_coordinator) -> None:
    """update_irrigation_config updates IrrigationConfig fields."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.cache = MagicMock()

    await facade.update_irrigation_config(
        "gs1",
        {
            "target_vwc": 0.35,
            "irrigation_pump_entity": "",  # falsy -> None
            "drain_pump_entity": "",  # falsy -> None
        },
    )
    assert gs.irrigation_config.irrigation_pump_entity is None


# ---------------------------------------------------------------------------
# take_clones / promote_clone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_clones(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    clones = [MagicMock(), MagicMock()]
    mock_coordinator.plant_manager.take_clones = AsyncMock(return_value=clones)

    result = await facade.take_clones("mother_1", 2)
    assert result is clones
    mock_coordinator.plant_manager.take_clones.assert_awaited_once_with(
        mother_plant_id="mother_1",
        num_clones=2,
        target_growspace_id=None,
        target_growspace_name=None,
        transition_date=None,
    )


@pytest.mark.asyncio
async def test_promote_clone(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.promote_clone = AsyncMock()
    await facade.promote_clone("clone_1", "veg")
    mock_coordinator.plant_manager.promote_clone.assert_awaited_once_with(
        clone_id="clone_1", target_growspace_id="veg", transition_date=None
    )


# ---------------------------------------------------------------------------
# Irrigation schedule methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_irrigation_settings(mock_coordinator) -> None:
    """set_irrigation_settings delegates to update_irrigation_config."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.cache = MagicMock()

    await facade.set_irrigation_settings("gs1", {"target_vwc": 0.4})


@pytest.mark.asyncio
async def test_add_irrigation_schedule_item_with_duration(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    irr_coord = MagicMock()
    irr_coord.async_add_schedule_item = AsyncMock()
    mock_coordinator.irrigation_coordinators = {"gs1": irr_coord}

    await facade.add_irrigation_schedule_item("gs1", "irrigation_times", "08:00", 15)
    irr_coord.async_add_schedule_item.assert_awaited_once_with(
        "irrigation_times", "08:00", 15
    )


@pytest.mark.asyncio
async def test_add_irrigation_schedule_item_default_duration(mock_coordinator) -> None:
    """When duration_minutes is None, it uses the coordinator's default."""
    facade = ServiceFacade(mock_coordinator)
    irr_coord = MagicMock()
    irr_coord.get_default_duration = MagicMock(return_value=20)
    irr_coord.async_add_schedule_item = AsyncMock()
    mock_coordinator.irrigation_coordinators = {"gs1": irr_coord}

    await facade.add_irrigation_schedule_item("gs1", "irrigation_times", "09:00")
    irr_coord.get_default_duration.assert_called_once_with("irrigation")
    irr_coord.async_add_schedule_item.assert_awaited_once_with(
        "irrigation_times", "09:00", 20
    )


@pytest.mark.asyncio
async def test_remove_irrigation_schedule_item(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    irr_coord = MagicMock()
    irr_coord.async_remove_schedule_item = AsyncMock()
    mock_coordinator.irrigation_coordinators = {"gs1": irr_coord}

    await facade.remove_irrigation_schedule_item("gs1", "irrigation_times", "08:00")
    irr_coord.async_remove_schedule_item.assert_awaited_once_with(
        "irrigation_times", "08:00"
    )


@pytest.mark.asyncio
async def test_get_irrigation_coordinator_lazy_init(mock_coordinator) -> None:
    """_get_irrigation_coordinator should lazy-init if growspace exists."""
    facade = ServiceFacade(mock_coordinator)
    gs = MagicMock()
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = (
        AsyncMock()
    )
    irr_coord = MagicMock()
    irr_coord.get_default_duration = MagicMock(return_value=10)
    irr_coord.async_add_schedule_item = AsyncMock()

    # After lazy init, the coordinator exists
    def _setup_side_effect(gs_id, gs_obj):
        mock_coordinator.irrigation_coordinators[gs_id] = irr_coord

    mock_coordinator.irrigation_coordinators = {}
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators.side_effect = (
        _setup_side_effect
    )

    await facade.add_irrigation_schedule_item("gs1", "irrigation_times", "10:00")
    mock_coordinator.subsystem_manager.async_setup_growspace_sub_coordinators.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_irrigation_coordinator_missing_raises(mock_coordinator) -> None:
    """_get_irrigation_coordinator raises if growspace not found."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.irrigation_coordinators = {}
    mock_coordinator.growspaces = {}

    with pytest.raises(ServiceValidationError):
        await facade.add_irrigation_schedule_item("gs1", "irrigation_times", "08:00")


# ---------------------------------------------------------------------------
# Plant operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_plants(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.switch_plants = AsyncMock()
    await facade.switch_plants("p1", "p2")
    mock_coordinator.plant_manager.switch_plants.assert_awaited_once_with("p1", "p2")


@pytest.mark.asyncio
async def test_move_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.move_plant = AsyncMock()
    await facade.move_plant("p1", 1, 2)
    mock_coordinator.plant_manager.move_plant.assert_awaited_once_with("p1", 1, 2)


@pytest.mark.asyncio
async def test_transition_plant_stage(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.transition_plant_stage = AsyncMock()
    await facade.transition_plant_stage("p1", PlantStage.FLOWER)
    mock_coordinator.plant_manager.transition_plant_stage.assert_awaited_once_with(
        "p1", PlantStage.FLOWER, None
    )


@pytest.mark.asyncio
async def test_harvest(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    mock_coordinator.plant_manager.harvest = AsyncMock(return_value=plant)
    result = await facade.harvest("p1")
    assert result is plant


@pytest.mark.asyncio
async def test_harvest_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plant_manager.harvest_plant = AsyncMock()
    await facade.harvest_plant("p1", wet_weight=100.0)
    mock_coordinator.plant_manager.harvest_plant.assert_awaited_once()


# ---------------------------------------------------------------------------
# Water / nutrient operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_water_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    mock_coordinator._watering_service.async_water_plant = AsyncMock(return_value=plant)
    result = await facade.water_plant("p1", 500.0)
    assert result is plant
    mock_coordinator._watering_service.async_water_plant.assert_awaited_once_with(
        "p1", 500.0, None, None
    )


@pytest.mark.asyncio
async def test_water_growspace(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator._watering_service.async_water_growspace = AsyncMock(return_value=3)
    result = await facade.water_growspace("gs1", amount_per_plant=500.0)
    assert result == 3


@pytest.mark.asyncio
async def test_save_nutrient_preset(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    preset = MagicMock()
    mock_coordinator.nutrient_manager.async_save_nutrient_preset = AsyncMock(
        return_value=preset
    )
    result = await facade.save_nutrient_preset("Bloom", [{"name": "N", "amount": 2.0}])
    assert result is preset


@pytest.mark.asyncio
async def test_remove_nutrient_preset(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.nutrient_manager.async_remove_nutrient_preset = AsyncMock()
    await facade.remove_nutrient_preset("preset_1")
    mock_coordinator.nutrient_manager.async_remove_nutrient_preset.assert_awaited_once_with(
        "preset_1"
    )


def test_get_applicable_presets(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    presets = [MagicMock()]
    mock_coordinator.nutrient_manager.get_applicable_presets = MagicMock(
        return_value=presets
    )
    assert facade.get_applicable_presets("p1") is presets


# ---------------------------------------------------------------------------
# Training / IPM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_training_event(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator._training_service.async_log_training_event = AsyncMock()
    await facade.log_training_event("gs1", "LST", notes="Tied down")
    mock_coordinator._training_service.async_log_training_event.assert_awaited_once_with(
        "gs1", "LST", "Tied down", None
    )


@pytest.mark.asyncio
async def test_save_ipm_preset_legacy_type_kwarg(mock_coordinator) -> None:
    """save_ipm_preset accepts 'type' as a kwarg for backward compat."""
    facade = ServiceFacade(mock_coordinator)
    preset = MagicMock()
    mock_coordinator._ipm_service.async_save_ipm_preset = AsyncMock(return_value=preset)
    result = await facade.save_ipm_preset("Neem", items=[], type="Foliar")
    assert result is preset


@pytest.mark.asyncio
async def test_save_ipm_preset_missing_type_raises(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    with pytest.raises(TypeError, match="preset_type"):
        await facade.save_ipm_preset("Test", items=[])


@pytest.mark.asyncio
async def test_save_ipm_preset_missing_items_raises(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    with pytest.raises(TypeError, match="items"):
        await facade.save_ipm_preset("Test", preset_type="Foliar")


# ---------------------------------------------------------------------------
# log_drain_reading — alert path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_drain_reading_fires_alert(mock_coordinator) -> None:
    """When drain EC delta exceeds threshold, a notification is sent."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    gs.drain_config.enabled = True
    gs.drain_config.max_ec_delta = 0.3
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.notification_manager.async_send_notification = AsyncMock()

    # drain_ec - feed_ec = 2.0 - 1.0 = 1.0 > 0.3
    await facade.log_drain_reading("gs1", feed_ec=1.0, drain_ec=2.0)

    mock_coordinator.notification_manager.async_send_notification.assert_awaited_once()
    call_args = mock_coordinator.notification_manager.async_send_notification.call_args
    assert call_args[0][0] == "gs1"  # positional growspace_id arg


@pytest.mark.asyncio
async def test_log_drain_reading_no_alert_when_disabled(mock_coordinator) -> None:
    """When drain monitoring disabled, no notification is sent even if delta is high."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    gs.drain_config.enabled = False
    gs.drain_config.max_ec_delta = 0.3
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.notification_manager.async_send_notification = AsyncMock()

    await facade.log_drain_reading("gs1", feed_ec=1.0, drain_ec=2.0)
    mock_coordinator.notification_manager.async_send_notification.assert_not_awaited()


# ---------------------------------------------------------------------------
# configure_drain_monitoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_drain_monitoring(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()

    await facade.configure_drain_monitoring(
        "gs1", enabled=True, max_ec_delta=0.5, target_runoff_percent=25.0
    )
    assert gs.drain_config.enabled is True
    assert gs.drain_config.max_ec_delta == 0.5
    assert gs.drain_config.target_runoff_percent == 25.0


@pytest.mark.asyncio
async def test_configure_drain_monitoring_not_found(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    with pytest.raises(ServiceValidationError):
        await facade.configure_drain_monitoring("missing", enabled=True)


# ---------------------------------------------------------------------------
# reset_water_tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_water_tracking(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    gs.water_usage.total_liters = 500.0
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()

    await facade.reset_water_tracking("gs1")
    assert gs.water_usage.total_liters == 0.0
    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_water_tracking_not_found(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    with pytest.raises(ServiceValidationError):
        await facade.reset_water_tracking("missing")


# ---------------------------------------------------------------------------
# configure_tank
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_tank_updates_volume(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    tank = IrrigationTank(sensor_entity="sensor.tank_level", volume_liters=100.0)
    gs = Growspace(id="gs1", name="GS1")
    gs.environment_config.irrigation_tanks.append(tank)
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    mock_coordinator.async_commit = AsyncMock()

    await facade.configure_tank("gs1", "sensor.tank_level", volume_liters=200.0)
    assert tank.volume_liters == 200.0
    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_configure_tank_unknown_growspace(mock_coordinator) -> None:
    """configure_tank should return early if growspace not found."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=None)
    mock_coordinator.async_commit = AsyncMock()
    await facade.configure_tank("missing", "sensor.tank", volume_liters=100.0)
    mock_coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_configure_tank_unknown_entity(mock_coordinator) -> None:
    """configure_tank should return early if tank entity not found."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    mock_coordinator.async_commit = AsyncMock()
    await facade.configure_tank("gs1", "sensor.unknown_tank", volume_liters=100.0)
    mock_coordinator.async_commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# EC ramp curve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_ec_ramp_curve(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    curve = MagicMock()
    mock_coordinator.nutrient_manager.async_save_ec_ramp_curve = AsyncMock(
        return_value=curve
    )
    mock_coordinator.growspaces = {"gs1": MagicMock()}

    result = await facade.save_ec_ramp_curve(
        growspace_id="gs1", name="Flower Ramp", points=[{"week": 1, "ec_min": 1.0}]
    )
    assert result is curve


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_no_growspace_id_fallback(mock_coordinator) -> None:
    """When growspace_id is None, use the first available growspace."""
    facade = ServiceFacade(mock_coordinator)
    curve = MagicMock()
    mock_coordinator.nutrient_manager.async_save_ec_ramp_curve = AsyncMock(
        return_value=curve
    )
    mock_coordinator.growspaces = {"gs1": MagicMock()}

    result = await facade.save_ec_ramp_curve(
        growspace_id=None, name="Curve", points=[{"week": 1}]
    )
    assert result is curve


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_no_growspace_raises(mock_coordinator) -> None:
    """When no growspaces exist and growspace_id is None, raise ValueError."""
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    with pytest.raises(ValueError, match="No growspaces"):
        await facade.save_ec_ramp_curve(
            growspace_id=None, name="Curve", points=[{"week": 1}]
        )


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_missing_name_raises(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    with pytest.raises(TypeError):
        await facade.save_ec_ramp_curve(growspace_id="gs1", points=[])


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_missing_points_raises(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    with pytest.raises(TypeError):
        await facade.save_ec_ramp_curve(growspace_id="gs1", name="Curve")


@pytest.mark.asyncio
async def test_remove_ec_ramp_curve(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.nutrient_manager.async_remove_ec_ramp_curve = AsyncMock()
    await facade.remove_ec_ramp_curve("gs1", "curve_1")
    mock_coordinator.nutrient_manager.async_remove_ec_ramp_curve.assert_awaited_once_with(
        "curve_1"
    )


# ---------------------------------------------------------------------------
# add_timeline_note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_timeline_note_basic(mock_coordinator) -> None:
    """add_timeline_note fires event with correct data."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.growspaces = {}

    await facade.add_timeline_note("p1", "Looking healthy!")
    mock_coordinator.hass.bus.async_fire.assert_called_once()
    args = mock_coordinator.hass.bus.async_fire.call_args[0]
    assert args[1]["plant_id"] == "p1"
    assert args[1]["notes"] == "Looking healthy!"


@pytest.mark.asyncio
async def test_add_timeline_note_plant_not_found(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plants = {}
    with pytest.raises(ServiceValidationError, match="Plant p1 not found"):
        await facade.add_timeline_note("p1", "Note")


@pytest.mark.asyncio
async def test_add_timeline_note_with_metadata(mock_coordinator) -> None:
    """add_timeline_note includes sensor readings when growspace has sensors."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": plant}

    gs = MagicMock()
    gs.environment_config = MagicMock()
    gs.environment_config.temperature_sensor = "sensor.temp"
    gs.environment_config.humidity_sensor = None
    gs.environment_config.vpd_sensor = None
    gs.environment_config.soil_moisture_sensor = None
    gs.environment_config.light_sensor = None
    mock_coordinator.growspaces = {"gs1": gs}

    state = MagicMock()
    state.state = "25.0"
    mock_coordinator.hass.states.get = MagicMock(return_value=state)

    await facade.add_timeline_note("p1", "Test", ph=6.5, ec=1.8, amount_ml=500.0)
    args = mock_coordinator.hass.bus.async_fire.call_args[0]
    metadata = args[1]["metadata"]
    assert metadata["temperature"] == 25.0
    assert metadata["ph"] == 6.5
    assert metadata["ec"] == 1.8
    assert metadata["amount_ml"] == 500.0


@pytest.mark.asyncio
async def test_add_timeline_note_with_images(mock_coordinator) -> None:
    """add_timeline_note saves images via image_manager."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.growspaces = {}

    image_manager = MagicMock()
    image_manager.save_timeline_image = AsyncMock(return_value="/path/img.jpg")
    mock_coordinator.strain_library = MagicMock()
    mock_coordinator.strain_library.image_manager = image_manager

    await facade.add_timeline_note("p1", "Test", images_base64=["base64data"])
    image_manager.save_timeline_image.assert_awaited_once()


# ---------------------------------------------------------------------------
# score_plant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.phenotype_score = PhenotypeScore()
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.plant_manager.update_plant = AsyncMock()

    await facade.score_plant("p1", vigor=8, structure=7, aroma=9, resin=6)
    assert plant.phenotype_score.vigor == 8
    assert plant.phenotype_score.internodal_spacing == 7
    assert plant.phenotype_score.terpene_intensity == 9
    assert plant.phenotype_score.resin == 6
    mock_coordinator.plant_manager.update_plant.assert_awaited_once()


@pytest.mark.asyncio
async def test_score_plant_not_found(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plants = {}
    with pytest.raises(ServiceValidationError):
        await facade.score_plant("missing", vigor=5)


# ---------------------------------------------------------------------------
# update_harvest_metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_harvest_metrics(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.harvest_metrics = HarvestMetrics()
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.plant_manager.update_plant = AsyncMock()

    await facade.update_harvest_metrics(
        "p1",
        wet_weight=500.0,
        dry_weight=100.0,
        thc_percentage=22.5,
        terpene_profile="citrus",
    )
    assert plant.harvest_metrics.wet_weight == 500.0
    assert plant.harvest_metrics.dry_weight == 100.0
    assert plant.harvest_metrics.thc_percentage == 22.5
    assert plant.harvest_metrics.terpene_profile == "citrus"
    mock_coordinator.plant_manager.update_plant.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_harvest_metrics_no_updates(mock_coordinator) -> None:
    """No-op when all fields are None."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.harvest_metrics = HarvestMetrics()
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.plant_manager.update_plant = AsyncMock()

    await facade.update_harvest_metrics("p1")
    mock_coordinator.plant_manager.update_plant.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_harvest_metrics_not_found(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.plants = {}
    with pytest.raises(ServiceValidationError):
        await facade.update_harvest_metrics("missing", wet_weight=100.0)


# ---------------------------------------------------------------------------
# Strain library methods
# ---------------------------------------------------------------------------


def test_get_strain_options_with_library(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    library = MagicMock()
    library.get_all = MagicMock(return_value={"OG Kush": {}, "Blue Dream": {}})
    mock_coordinator.strain_library = library
    result = facade.get_strain_options()
    assert result == ["Blue Dream", "OG Kush"]


def test_get_strain_options_no_library(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.strain_library = None
    assert facade.get_strain_options() == []


def test_export_strain_library(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    library = MagicMock()
    library.get_all = MagicMock(return_value={"OG Kush": {}})
    mock_coordinator.strain_library = library
    assert facade.export_strain_library() == ["OG Kush"]


@pytest.mark.asyncio
async def test_clear_strains(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    library = MagicMock()
    library.clear = AsyncMock(return_value=5)
    mock_coordinator.strain_library = library
    result = await facade.clear_strains()
    assert result == 5


@pytest.mark.asyncio
async def test_clear_strains_no_library(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.strain_library = None
    assert await facade.clear_strains() == 0


# ---------------------------------------------------------------------------
# Plant query methods
# ---------------------------------------------------------------------------


def test_get_growspace_plants(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plants = [MagicMock()]
    mock_coordinator.data_repository.get_growspace_plants = MagicMock(
        return_value=plants
    )
    assert facade.get_growspace_plants("gs1") is plants


def test_get_plant(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    mock_coordinator.data_repository.get_plant = MagicMock(return_value=plant)
    assert facade.get_plant("p1") is plant


# ---------------------------------------------------------------------------
# get_tank_tracker
# ---------------------------------------------------------------------------


def test_get_tank_tracker_no_growspace(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=None)
    assert facade.get_tank_tracker("gs1", "sensor.tank") is None


def test_get_tank_tracker_no_tank(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    assert facade.get_tank_tracker("gs1", "sensor.nonexistent") is None


def test_get_tank_tracker_no_volume(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    tank = IrrigationTank(sensor_entity="sensor.tank", volume_liters=None)
    gs = Growspace(id="gs1", name="GS1")
    gs.environment_config.irrigation_tanks.append(tank)
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    assert facade.get_tank_tracker("gs1", "sensor.tank") is None


def test_get_tank_tracker_creates_tracker(mock_coordinator) -> None:
    """get_tank_tracker creates and caches a TankWaterTracker."""
    facade = ServiceFacade(mock_coordinator)
    tank = IrrigationTank(sensor_entity="sensor.tank", volume_liters=100.0)
    gs = Growspace(id="gs1", name="GS1")
    gs.environment_config.irrigation_tanks.append(tank)
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)

    tracker1 = facade.get_tank_tracker("gs1", "sensor.tank")
    tracker2 = facade.get_tank_tracker("gs1", "sensor.tank")
    assert tracker1 is not None
    assert tracker1 is tracker2  # cached


# ---------------------------------------------------------------------------
# async_unsubscribe_all_trackers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_unsubscribe_all_trackers(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    tracker = MagicMock()
    tracker.async_unsubscribe = AsyncMock()
    facade._tank_water_trackers = {"gs1": {"sensor.tank": tracker}}

    await facade.async_unsubscribe_all_trackers()
    tracker.async_unsubscribe.assert_awaited_once()
    assert facade._tank_water_trackers == {}


# ---------------------------------------------------------------------------
# get_growspace_data / build_growspace_payload
# ---------------------------------------------------------------------------


def test_get_growspace_data_single(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.view_model_builder.build_serialized_growspace = MagicMock(
        return_value={"id": "gs1"}
    )
    result = facade.get_growspace_data("gs1")
    assert result == {"id": "gs1"}


def test_get_growspace_data_all(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {"gs1": MagicMock(), "gs2": MagicMock()}
    mock_coordinator.view_model_builder.build_serialized_growspace = MagicMock(
        side_effect=lambda gid: {"id": gid}
    )
    result = facade.get_growspace_data()
    assert set(result.keys()) == {"gs1", "gs2"}


def test_get_growspace_data_missing(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.growspaces = {}
    assert facade.get_growspace_data("missing") == {}


def test_build_growspace_payload(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.view_model_builder.build_serialized_growspace = MagicMock(
        return_value={"data": "test"}
    )
    assert facade.build_growspace_payload("gs1") == {"data": "test"}


# ---------------------------------------------------------------------------
# guess_overview_entity_id
# ---------------------------------------------------------------------------


def test_guess_overview_entity_id_found_in_registry(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_er = MagicMock()
    mock_er.async_get_entity_id = MagicMock(return_value="sensor.gs1_overview")
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        result = facade.guess_overview_entity_id("gs1")
    assert result == "sensor.gs1_overview"


def test_guess_overview_entity_id_fallback_slug(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_er = MagicMock()
    mock_er.async_get_entity_id = MagicMock(return_value=None)
    gs = MagicMock()
    gs.name = "My Tent"
    mock_coordinator.data_repository.get_growspace = MagicMock(return_value=gs)
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        result = facade.guess_overview_entity_id("custom_gs")
    assert result.startswith("sensor.")


# ---------------------------------------------------------------------------
# should_send_notification / mark_notification_sent
# ---------------------------------------------------------------------------


def test_should_send_notification_not_sent(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notifications_sent = {}
    assert facade.should_send_notification("p1", "flower", 14) is True


def test_should_send_notification_already_sent(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notifications_sent = {"p1": {"flower": {"14": True}}}
    assert facade.should_send_notification("p1", "flower", 14) is False


@pytest.mark.asyncio
async def test_mark_notification_sent(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.notifications_sent = {}
    mock_coordinator.async_commit = AsyncMock()

    await facade.mark_notification_sent("p1", "veg", 7)
    assert mock_coordinator.notifications_sent["p1"]["veg"]["7"] is True
    mock_coordinator.async_commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# fire_event
# ---------------------------------------------------------------------------


def test_fire_event(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    facade.fire_event("plant_added", {"plant_id": "p1"})
    mock_coordinator.hass.bus.async_fire.assert_called_once_with(
        "growspace_manager_updated",
        {"event_type": "plant_added", "data": {"plant_id": "p1"}},
    )


# ---------------------------------------------------------------------------
# handle_position_update
# ---------------------------------------------------------------------------


def test_handle_position_update_no_position(mock_coordinator) -> None:
    """handle_position_update is a no-op when row/col not in kwargs."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    facade.handle_position_update("p1", plant, False, {})
    mock_coordinator.validator.validate_position_bounds.assert_not_called()


def test_handle_position_update_with_position(mock_coordinator) -> None:
    """handle_position_update validates bounds and occupancy."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    plant.row = 0
    plant.col = 0

    facade.handle_position_update("p1", plant, False, {"row": 1, "col": 2})
    mock_coordinator.validator.validate_position_bounds.assert_called_once_with(
        "gs1", 1, 2
    )
    mock_coordinator.validator.validate_position_not_occupied.assert_called_once_with(
        "gs1", 1, 2, "p1"
    )


def test_handle_position_update_force_skips_occupancy(mock_coordinator) -> None:
    """With force_position=True, occupancy check is skipped."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    plant.row = 0
    plant.col = 0

    facade.handle_position_update("p1", plant, True, {"row": 1, "col": 2})
    mock_coordinator.validator.validate_position_bounds.assert_called_once()
    mock_coordinator.validator.validate_position_not_occupied.assert_not_called()


# ---------------------------------------------------------------------------
# validate_plants_after_growspace_resize
# ---------------------------------------------------------------------------


def test_validate_plants_after_growspace_resize(mock_coordinator) -> None:
    facade = ServiceFacade(mock_coordinator)
    mock_coordinator.config_entry = MagicMock()
    mock_coordinator.growspace_manager._validate_plants_after_growspace_resize = (
        MagicMock(return_value=MagicMock())
    )
    facade.validate_plants_after_growspace_resize("gs1", 5, 5)
    mock_coordinator.config_entry.async_create_background_task.assert_called_once()


# ---------------------------------------------------------------------------
# Remaining gap coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_irrigation_config_sets_strategy_field(mock_coordinator) -> None:
    """Fields on irrigation_strategy (not irrigation_config) should still be set."""
    facade = ServiceFacade(mock_coordinator)
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.async_commit = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()
    mock_coordinator.cache = MagicMock()

    # 'enabled' exists on irrigation_strategy but not irrigation_config
    await facade.update_irrigation_config("gs1", {"enabled": True})
    assert gs.irrigation_strategy.enabled is True


@pytest.mark.asyncio
async def test_save_ipm_preset_items_in_kwargs(mock_coordinator) -> None:
    """save_ipm_preset should pick items from **kwargs if items param is None."""
    facade = ServiceFacade(mock_coordinator)
    preset = MagicMock()
    mock_coordinator._ipm_service.async_save_ipm_preset = AsyncMock(return_value=preset)
    # Pass items via kwargs, not as the named parameter
    result = await facade.save_ipm_preset("Test", preset_type="Foliar", items=[{"name": "Neem"}])
    assert result is preset


@pytest.mark.asyncio
async def test_save_ec_ramp_curve_points_name_in_kwargs(mock_coordinator) -> None:
    """save_ec_ramp_curve should pick points/name from **kwargs if provided there."""
    facade = ServiceFacade(mock_coordinator)
    curve = MagicMock()
    mock_coordinator.nutrient_manager.async_save_ec_ramp_curve = AsyncMock(
        return_value=curve
    )
    mock_coordinator.growspaces = {"gs1": MagicMock()}

    result = await facade.save_ec_ramp_curve(
        growspace_id="gs1", points=[{"week": 1}], name="My Curve"
    )
    assert result is curve


@pytest.mark.asyncio
async def test_add_timeline_note_state_parse_error(mock_coordinator) -> None:
    """_get_state handles a ValueError from float() gracefully."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": plant}

    gs = MagicMock()
    gs.environment_config = MagicMock()
    gs.environment_config.temperature_sensor = "sensor.temp"
    gs.environment_config.humidity_sensor = None
    gs.environment_config.vpd_sensor = None
    gs.environment_config.soil_moisture_sensor = None
    gs.environment_config.light_sensor = None
    mock_coordinator.growspaces = {"gs1": gs}

    state = MagicMock()
    state.state = "not_a_number"  # will raise ValueError
    mock_coordinator.hass.states.get = MagicMock(return_value=state)

    await facade.add_timeline_note("p1", "Test")
    args = mock_coordinator.hass.bus.async_fire.call_args[0]
    assert args[1]["metadata"]["temperature"] is None


@pytest.mark.asyncio
async def test_add_timeline_note_image_save_error(mock_coordinator) -> None:
    """Image save errors are caught and logged; note is still added."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.growspaces = {}

    image_manager = MagicMock()
    image_manager.save_timeline_image = AsyncMock(side_effect=OSError("disk error"))
    mock_coordinator.strain_library = MagicMock()
    mock_coordinator.strain_library.image_manager = image_manager

    # Should not raise even though image save fails
    await facade.add_timeline_note("p1", "Test", images_base64=["base64data"])
    mock_coordinator.hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_score_plant_pest_resistance(mock_coordinator) -> None:
    """score_plant maps pest_resistance to mold_resistance."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.phenotype_score = PhenotypeScore()
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.plant_manager.update_plant = AsyncMock()

    await facade.score_plant("p1", pest_resistance=9)
    assert plant.phenotype_score.mold_resistance == 9


@pytest.mark.asyncio
async def test_update_harvest_metrics_trim_and_cbd(mock_coordinator) -> None:
    """update_harvest_metrics handles trim_weight and cbd_percentage."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.harvest_metrics = HarvestMetrics()
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.plant_manager.update_plant = AsyncMock()

    await facade.update_harvest_metrics(
        "p1", trim_weight=50.0, cbd_percentage=5.5
    )
    assert plant.harvest_metrics.trim_weight == 50.0
    assert plant.harvest_metrics.cbd_percentage == 5.5


def test_guess_overview_entity_id_special_growspace_entity_found(
    mock_coordinator,
) -> None:
    """guess_overview_entity_id returns entity_id for a special growspace alias."""
    facade = ServiceFacade(mock_coordinator)
    mock_er = MagicMock()
    call_count = 0

    def _get_entity_id(platform, domain, uid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # First call: primary unique_id
        return "sensor.dry_overview"  # Second call: canonical special

    mock_er.async_get_entity_id = MagicMock(side_effect=_get_entity_id)
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        result = facade.guess_overview_entity_id("dry_overview")
    assert result == "sensor.dry_overview"


def test_guess_overview_entity_id_special_growspace_no_entity(
    mock_coordinator,
) -> None:
    """guess_overview_entity_id falls back to sensor.<canonical_id> for special growspaces."""
    facade = ServiceFacade(mock_coordinator)
    mock_er = MagicMock()
    mock_er.async_get_entity_id = MagicMock(return_value=None)
    with patch("homeassistant.helpers.entity_registry.async_get", return_value=mock_er):
        result = facade.guess_overview_entity_id("dry_overview")
    assert result == "sensor.dry"


def test_handle_position_update_only_row(mock_coordinator) -> None:
    """handle_position_update uses plant.col when only row is updated."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    plant.row = 2
    plant.col = 3

    facade.handle_position_update("p1", plant, False, {"row": 1})
    # new_col should default to plant.col (3)
    mock_coordinator.validator.validate_position_bounds.assert_called_once_with(
        "gs1", 1, 3
    )


def test_handle_position_update_only_col(mock_coordinator) -> None:
    """handle_position_update uses plant.row when only col is updated."""
    facade = ServiceFacade(mock_coordinator)
    plant = MagicMock()
    plant.growspace_id = "gs1"
    plant.row = 2
    plant.col = 3

    facade.handle_position_update("p1", plant, False, {"col": 5})
    mock_coordinator.validator.validate_position_bounds.assert_called_once_with(
        "gs1", 2, 5
    )
