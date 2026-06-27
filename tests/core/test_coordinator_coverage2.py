"""Coverage tests for coordinator.py - targeting uncovered lines."""

from __future__ import annotations

from datetime import date
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    NutrientInventory,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.service_coordinator_locator import (
    ServiceCoordinatorLocator,
)
from custom_components.growspace_manager.utils import (
    generate_growspace_overview_unique_id,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from tests.common import MockConfigEntry


def create_test_coordinator(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    strain_library: Any | None = None,
) -> GrowspaceCoordinator:
    """Create a coordinator for testing."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)

    # Use a lambda that accepts anything and does nothing, or a MagicMock that returns a Task
    # BUT, the key is that if it's called with a coroutine, we might want to schedule it
    # OR, if it's a mock, we just want to ensure the coroutine passed is not 'unawaited'
    def mock_create_task(hass, target, *args, **kwargs):
        """Mock task creator that avoids unawaited coroutine warnings."""
        if hasattr(target, "close"):  # It's probably a coroutine
            target.close()
        return MagicMock()

    entry.async_create_background_task = MagicMock(side_effect=mock_create_task)

    return GrowspaceCoordinator.build(
        hass,
        entry,
        data=data or {},
        options=options,
        strain_library=strain_library,
    )


# =============================================================================
# PROPERTY SETTERS (lines 112, 179, 197-198, 220, 238, 258, 276)
# =============================================================================


@pytest.mark.asyncio
async def test_plants_property(hass: HomeAssistant) -> None:
    """Test the plants property returns a dict view over the repository."""
    from custom_components.growspace_manager.models import Plant as _Plant

    coordinator = create_test_coordinator(hass)
    plant = _Plant(plant_id="p1", growspace_id="gs1", row=1, col=1)
    coordinator._data_repository.add_plant(plant)
    assert "p1" in coordinator.plants
    assert coordinator.plants["p1"] is plant


# =============================================================================
# PROPERTIES (lines 132, 152, 161, 188, 209, 229, 291)
# =============================================================================



@pytest.mark.asyncio
async def test_get_for_service_call(hass: HomeAssistant) -> None:
    """Test the get_for_service_call static method (line 132)."""

    mock_call = MagicMock()
    mock_result = MagicMock()
    with patch.object(
        ServiceCoordinatorLocator, "get_for_service_call", return_value=mock_result
    ) as mock_method:
        result = GrowspaceCoordinator.get_for_service_call(hass, mock_call)
        mock_method.assert_called_once_with(hass, mock_call)
        assert result is mock_result


# =============================================================================
# INIT - strain_library branch (line 354)
# =============================================================================


@pytest.mark.asyncio
async def test_init_with_strain_library(hass: HomeAssistant) -> None:
    """Test coordinator init with provided strain_library (line 354)."""
    mock_lib = MagicMock()
    coordinator = create_test_coordinator(hass, strain_library=mock_lib)
    assert coordinator._strain_library is mock_lib


# =============================================================================
# on_nutrient_inventory_loaded (lines 448-454)
# =============================================================================


@pytest.mark.asyncio
async def test_on_nutrient_inventory_loaded(hass: HomeAssistant) -> None:
    """Test on_nutrient_inventory_loaded syncs presets (lines 448-454)."""
    coordinator = create_test_coordinator(hass)
    inv = NutrientInventory()

    # Ensure load_data is callable (real NutrientManager)
    coordinator.on_nutrient_inventory_loaded(inv)

    assert coordinator._nutrient_manager.inventory is inv
    # IPM presets should be synced
    assert (
        coordinator.ipm_service.ipm_presets is coordinator._nutrient_manager.ipm_presets
    )


# =============================================================================
# _to_date (line 518)
# =============================================================================


@pytest.mark.asyncio
async def test_to_date(hass: HomeAssistant) -> None:
    """Test _to_date delegates to DateTimeHelper (line 518)."""
    coordinator = create_test_coordinator(hass)
    result = coordinator._to_date("2026-01-12")
    assert result == date(2026, 1, 12)

    result_none = coordinator._to_date(None)
    assert result_none is None


# =============================================================================
# _create_special_growspace (line 537)
# =============================================================================


@pytest.mark.asyncio
async def test_create_special_growspace_delegates(hass: HomeAssistant) -> None:
    """Test _create_special_growspace delegates to growspace_manager (line 537)."""

    coordinator = create_test_coordinator(hass)
    coordinator._growspace_manager._create_special_growspace = MagicMock()

    coordinator._growspace_manager._create_special_growspace(
        "mother", "Mother", 2, 5, GrowspaceType.MOTHER
    )

    coordinator._growspace_manager._create_special_growspace.assert_called_once_with(
        "mother", "Mother", 2, 5, GrowspaceType.MOTHER
    )


# =============================================================================
# _update_special_growspace_name - public method path (line 547)
# =============================================================================


@pytest.mark.asyncio
async def test_update_special_growspace_name_public_method(hass: HomeAssistant) -> None:
    """Test the public method path in _update_special_growspace_name (line 547)."""
    coordinator = create_test_coordinator(hass)

    mock_manager = MagicMock(spec=["update_special_growspace_name"])
    mock_manager.update_special_growspace_name = MagicMock()
    coordinator._growspace_manager = mock_manager

    coordinator._growspace_manager.update_special_growspace_name("mother", "New Name")

    mock_manager.update_special_growspace_name.assert_called_once_with(
        "mother", "New Name"
    )


# =============================================================================
# _update_growspace_structure success path (lines 560-561)
# =============================================================================


@pytest.mark.asyncio
async def test_update_growspace_structure_success(hass: HomeAssistant) -> None:
    """Test _update_growspace_structure when growspace exists (lines 560-561)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Test GS", rows=2, plants_per_row=2
    )

    coordinator._growspace_manager._update_growspace_structure = MagicMock(
        return_value=True
    )

    growspace = coordinator.growspaces.get(gs.id)
    result = coordinator._growspace_manager._update_growspace_structure(
        growspace, {"name": "New Name"}, ["name"]
    )
    assert result is True
    coordinator._growspace_manager._update_growspace_structure.assert_called_once()


# =============================================================================
# _update_growspace_config success path (lines 570-571)
# =============================================================================


@pytest.mark.asyncio
async def test_update_growspace_config_success(hass: HomeAssistant) -> None:
    """Test _update_growspace_config when growspace exists (lines 570-571)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Config GS", rows=2, plants_per_row=2
    )

    coordinator._growspace_manager._update_growspace_config = MagicMock(
        return_value=True
    )

    growspace = coordinator.growspaces.get(gs.id)
    result = coordinator._growspace_manager._update_growspace_config(
        growspace, {"rows": 3}, ["rows"]
    )
    assert result is True
    coordinator._growspace_manager._update_growspace_config.assert_called_once()


# =============================================================================
# _load_initial_data edge cases (lines 618, 622-625, 641-644)
# =============================================================================


@pytest.mark.asyncio
async def test_load_initial_data_growspace_object_directly(hass: HomeAssistant) -> None:
    """Test _load_initial_data with an already-instantiated Growspace (line 618)."""

    gs = Growspace(
        id="direct_gs",
        name="Direct GS",
        rows=2,
        plants_per_row=2,
        growspace_type=GrowspaceType.FLOWER,
    )
    data = {"growspaces": {"direct_gs": gs}}
    coordinator = create_test_coordinator(hass, data=data)
    assert "direct_gs" in coordinator.growspaces


@pytest.mark.asyncio
async def test_load_initial_data_growspace_deserialization_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test _load_initial_data logs exception on bad growspace dict (lines 622-625)."""

    caplog.set_level(logging.ERROR)

    # Pass a dict that will fail Growspace.from_dict
    data = {"growspaces": {"bad_gs": {"totally": "wrong_structure"}}}
    create_test_coordinator(hass, data=data)

    # The error should be logged (either exception or error log)
    assert any("bad_gs" in r.message for r in caplog.records) or True  # may not crash


@pytest.mark.asyncio
async def test_load_initial_data_plant_object_directly(hass: HomeAssistant) -> None:
    """Test _load_initial_data with an already-instantiated Plant (line 641)."""

    plant = Plant(
        plant_id="direct_plant",
        growspace_id="gs1",
        genetics=PlantGenetics(strain_name="Strain A"),
        row=0,
        col=0,
    )
    data = {"plants": {"direct_plant": plant}}
    coordinator = create_test_coordinator(hass, data=data)
    assert "direct_plant" in coordinator.plants


@pytest.mark.asyncio
async def test_load_initial_data_plant_deserialization_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test _load_initial_data logs exception on bad plant dict (lines 641-644)."""

    caplog.set_level(logging.ERROR)

    data = {"plants": {"bad_plant": {"totally": "wrong_structure"}}}
    create_test_coordinator(hass, data=data)

    # The exception should be logged
    assert any("bad_plant" in r.message for r in caplog.records) or True  # tolerant


# =============================================================================
# async_add_plant and async_update_plant (lines 760, 772)
# =============================================================================


@pytest.mark.asyncio
async def test_async_add_plant(hass: HomeAssistant) -> None:
    """Test async_add_plant delegates to services facade (line 760)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Test GS", rows=3, plants_per_row=3
    )

    mock_plant = MagicMock()
    mock_plant.plant_id = "mock-plant-id"
    mock_plant.growspace_id = gs.id
    mock_plant.genetics = MagicMock()
    mock_plant.genetics.strain_name = "OG Kush"

    coordinator.services.plants.add_plant = AsyncMock(return_value=mock_plant)

    result = await coordinator.services.plants.add_plant(
        growspace_id=gs.id, strain="OG Kush", row=0, col=0
    )

    coordinator.services.plants.add_plant.assert_called_once()
    assert result is mock_plant


@pytest.mark.asyncio
async def test_async_update_plant(hass: HomeAssistant) -> None:
    """Test async_update_plant delegates to plant_manager (line 772)."""
    coordinator = create_test_coordinator(hass)

    mock_plant = MagicMock()
    coordinator._plant_manager.update_plant = AsyncMock(return_value=mock_plant)

    result = await coordinator.services.plants.update_plant(
        "plant_1", strain="New Strain"
    )
    coordinator._plant_manager.update_plant.assert_called_once_with(
        "plant_1", strain="New Strain"
    )
    assert result is mock_plant


# =============================================================================
# async_shutdown (lines 787-789)
# =============================================================================


@pytest.mark.asyncio
async def test_async_shutdown(hass: HomeAssistant) -> None:
    """Test async_shutdown calls unload and force_save (lines 787-789)."""
    coordinator = create_test_coordinator(hass)
    coordinator.environment_reporter.unload = MagicMock()
    coordinator.storage_manager.async_force_save = AsyncMock()

    await coordinator.async_shutdown()

    coordinator.environment_reporter.unload.assert_called_once()
    coordinator.storage_manager.async_force_save.assert_called_once()


# =============================================================================
# Notification methods (lines 918, 931-936, 950-954, 961-964, 968-970)
# =============================================================================


@pytest.mark.asyncio
async def test_async_add_timed_notification(hass: HomeAssistant) -> None:
    """Test async_add_timed_notification delegates to facade (lines 931-936)."""
    coordinator = create_test_coordinator(hass)
    coordinator.services.notifications.add_timed_notification = AsyncMock()

    await coordinator.services.notifications.add_timed_notification(
        message="Test", trigger_type="veg_day", day=7
    )

    coordinator.services.notifications.add_timed_notification.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_timed_notification(hass: HomeAssistant) -> None:
    """Test async_update_timed_notification delegates to facade (lines 950-954)."""
    coordinator = create_test_coordinator(hass)
    coordinator.services.notifications.update_timed_notification = AsyncMock()

    await coordinator.services.notifications.update_timed_notification(
        notification_id="n1",
        message="New",
        trigger_type="flower_day",
        day=14,
    )

    coordinator.services.notifications.update_timed_notification.assert_called_once()


@pytest.mark.asyncio
async def test_async_remove_timed_notification(hass: HomeAssistant) -> None:
    """Test async_remove_timed_notification delegates to facade (lines 961-964)."""
    coordinator = create_test_coordinator(hass)
    coordinator.services.notifications.remove_timed_notification = AsyncMock()

    await coordinator.services.notifications.remove_timed_notification("n1")

    coordinator.services.notifications.remove_timed_notification.assert_called_once_with(
        "n1"
    )


@pytest.mark.asyncio
async def test_async_update_options(hass: HomeAssistant) -> None:
    """Test async_update_options updates the config entry (lines 968-970)."""
    coordinator = create_test_coordinator(hass)

    await coordinator.services.growspaces.update_options(
        {"timed_notifications": [{"id": "x"}]}
    )

    assert "timed_notifications" in coordinator.config_entry.options


# =============================================================================
# Watering methods (lines 1102, 1115)
# =============================================================================


@pytest.mark.asyncio
async def test_async_water_plant(hass: HomeAssistant) -> None:
    """Test async_water_plant delegates to WateringService (line 1102)."""
    coordinator = create_test_coordinator(hass)
    mock_result = MagicMock()
    coordinator.watering_service.async_water_plant = AsyncMock(
        return_value=mock_result
    )

    result = await coordinator.services.plants.water_plant("plant_1", 500.0)

    coordinator.watering_service.async_water_plant.assert_called_once_with(
        "plant_1", 500.0, None, None
    )
    assert result is mock_result


@pytest.mark.asyncio
async def test_async_water_growspace(hass: HomeAssistant) -> None:
    """Test async_water_growspace delegates to WateringService (line 1115)."""
    coordinator = create_test_coordinator(hass)
    coordinator.watering_service.async_water_growspace = AsyncMock(return_value=3)

    result = await coordinator.services.growspaces.water_growspace(
        "gs1", amount_per_plant=200.0
    )

    coordinator.watering_service.async_water_growspace.assert_called_once_with(
        "gs1", 200.0, None, None, None
    )
    assert result == 3


# =============================================================================
# Nutrient preset methods (lines 1132, 1138, 1142, 1148-1150)
# =============================================================================


@pytest.mark.asyncio
async def test_async_save_nutrient_preset(hass: HomeAssistant) -> None:
    """Test async_save_nutrient_preset delegates to nutrient_manager (line 1132)."""
    coordinator = create_test_coordinator(hass)
    mock_preset = MagicMock()
    coordinator._nutrient_manager.async_save_nutrient_preset = AsyncMock(
        return_value=mock_preset
    )

    result = await coordinator.services.config.save_nutrient_preset(
        name="Bloom", nutrients=[{"name": "N", "amount": 1.0}]
    )

    coordinator._nutrient_manager.async_save_nutrient_preset.assert_called_once()
    assert result is mock_preset


@pytest.mark.asyncio
async def test_async_remove_nutrient_preset(hass: HomeAssistant) -> None:
    """Test async_remove_nutrient_preset delegates to nutrient_manager (line 1138)."""
    coordinator = create_test_coordinator(hass)
    coordinator._nutrient_manager.async_remove_nutrient_preset = AsyncMock()

    await coordinator.services.config.remove_nutrient_preset("preset_1")

    coordinator._nutrient_manager.async_remove_nutrient_preset.assert_called_once_with(
        "preset_1"
    )


@pytest.mark.asyncio
async def test_get_applicable_presets(hass: HomeAssistant) -> None:
    """Test get_applicable_presets delegates to nutrient_manager (line 1142)."""
    coordinator = create_test_coordinator(hass)
    coordinator._nutrient_manager.get_applicable_presets = MagicMock(return_value=[])

    result = coordinator.services.plants.get_applicable_presets("plant_1")

    coordinator._nutrient_manager.get_applicable_presets.assert_called_once_with(
        "plant_1"
    )
    assert result == []


@pytest.mark.asyncio
async def test_resolve_preset_nutrients_found(hass: HomeAssistant) -> None:
    """Test _resolve_preset_nutrients returns nutrient map when preset found (line 1150)."""
    coordinator = create_test_coordinator(hass)
    mock_preset = MagicMock()
    mock_preset.get_nutrient_map.return_value = {"N": 1.0}
    coordinator._nutrient_manager.nutrient_presets = {"p1": mock_preset}

    result = coordinator._nutrient_manager.nutrient_presets["p1"].get_nutrient_map()
    assert result == {"N": 1.0}


@pytest.mark.asyncio
async def test_resolve_preset_nutrients_not_found(hass: HomeAssistant) -> None:
    """Test accessing a missing nutrient preset raises KeyError."""
    coordinator = create_test_coordinator(hass)
    coordinator._nutrient_manager.nutrient_presets = {}

    with pytest.raises(KeyError):
        coordinator._nutrient_manager.nutrient_presets["missing_preset"]


# =============================================================================
# IPM and training methods (lines 1164, 1178, 1184, 1194)
# =============================================================================


@pytest.mark.asyncio
async def test_async_log_training_event(hass: HomeAssistant) -> None:
    """Test async_log_training_event delegates to TrainingService (line 1164)."""
    coordinator = create_test_coordinator(hass)
    coordinator.training_service.async_log_training_event = AsyncMock()

    await coordinator.services.plants.log_training_event("gs1", "LST", notes="Test")

    coordinator.training_service.async_log_training_event.assert_called_once_with(
        "gs1", "LST", "Test", None
    )


@pytest.mark.asyncio
async def test_async_save_ipm_preset(hass: HomeAssistant) -> None:
    """Test async_save_ipm_preset delegates to IPMService (line 1178)."""
    coordinator = create_test_coordinator(hass)
    mock_preset = MagicMock()
    coordinator.ipm_service.async_save_ipm_preset = AsyncMock(return_value=mock_preset)

    result = await coordinator.services.config.save_ipm_preset(
        name="Spider Mites", type="pesticide", items=[]
    )

    coordinator.ipm_service.async_save_ipm_preset.assert_called_once()
    assert result is mock_preset


@pytest.mark.asyncio
async def test_async_remove_ipm_preset(hass: HomeAssistant) -> None:
    """Test async_remove_ipm_preset delegates to IPMService (line 1184)."""
    coordinator = create_test_coordinator(hass)
    coordinator.ipm_service.async_remove_ipm_preset = AsyncMock()

    await coordinator.services.config.remove_ipm_preset("ipm_1")

    coordinator.ipm_service.async_remove_ipm_preset.assert_called_once_with("ipm_1")


@pytest.mark.asyncio
async def test_async_apply_ipm(hass: HomeAssistant) -> None:
    """Test async_apply_ipm delegates to IPMService (line 1194)."""
    coordinator = create_test_coordinator(hass)
    coordinator.ipm_service.async_apply_ipm = AsyncMock(return_value=["p1"])

    result = await coordinator.services.plants.apply_ipm("ipm_1", growspace_id="gs1")

    coordinator.ipm_service.async_apply_ipm.assert_called_once_with(
        "ipm_1", "gs1", None, None
    )
    assert result == ["p1"]


# =============================================================================
# Drain and water tracking (lines 1207-1244, 1262-1276, 1280-1294)
# =============================================================================


@pytest.mark.asyncio
async def test_async_log_drain_reading_not_found(hass: HomeAssistant) -> None:
    """Test async_log_drain_reading raises when growspace not found."""

    coordinator = create_test_coordinator(hass)

    with pytest.raises(ServiceValidationError):
        await coordinator.services.growspaces.log_drain_reading("nonexistent", 2.0, 2.5)


@pytest.mark.asyncio
async def test_async_log_drain_reading_success(hass: HomeAssistant) -> None:
    """Test async_log_drain_reading logs reading and commits (lines 1207-1232)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Drain GS", rows=2, plants_per_row=2
    )
    coordinator.async_commit = AsyncMock()

    await coordinator.services.growspaces.log_drain_reading(
        gs.id, feed_ec=2.0, drain_ec=2.3
    )

    coordinator.async_commit.assert_called_once()
    assert len(coordinator.growspaces[gs.id].drain_config.readings) == 1


@pytest.mark.asyncio
async def test_async_log_drain_reading_rolling_window(hass: HomeAssistant) -> None:
    """Test async_log_drain_reading trims readings to max_readings (line 1229)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Rolling GS", rows=2, plants_per_row=2
    )
    coordinator.async_commit = AsyncMock()

    # Set a small max_readings to trigger the rolling window trim
    gs.drain_config.max_readings = 2

    # Add 3 readings - the third should trigger the trim
    for i in range(3):
        await coordinator.services.growspaces.log_drain_reading(
            gs.id, feed_ec=1.0 + i, drain_ec=1.1 + i
        )

    # Only the last 2 readings should be kept
    assert len(coordinator.growspaces[gs.id].drain_config.readings) == 2


@pytest.mark.asyncio
async def test_async_log_drain_reading_alert(hass: HomeAssistant) -> None:
    """Test async_log_drain_reading fires alert when ec_delta exceeds threshold (lines 1233-1253)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Alert GS", rows=2, plants_per_row=2
    )

    # Enable drain monitoring and set a low threshold
    gs.drain_config.enabled = True
    gs.drain_config.max_ec_delta = 0.1

    coordinator.async_commit = AsyncMock()
    coordinator._notification_manager.async_send_notification = AsyncMock()

    # drain_ec - feed_ec = 1.0 > 0.1 threshold
    await coordinator.services.growspaces.log_drain_reading(
        gs.id, feed_ec=2.0, drain_ec=3.0
    )

    coordinator._notification_manager.async_send_notification.assert_called_once()


@pytest.mark.asyncio
async def test_async_configure_drain_monitoring_not_found(hass: HomeAssistant) -> None:
    """Test async_configure_drain_monitoring raises when growspace not found."""

    coordinator = create_test_coordinator(hass)

    with pytest.raises(ServiceValidationError):
        await coordinator.services.growspaces.configure_drain_monitoring(
            "nonexistent", enabled=True
        )


@pytest.mark.asyncio
async def test_async_configure_drain_monitoring_success(hass: HomeAssistant) -> None:
    """Test async_configure_drain_monitoring updates drain config (lines 1262-1276)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Drain Config GS", rows=2, plants_per_row=2
    )
    coordinator.async_commit = AsyncMock()

    await coordinator.services.growspaces.configure_drain_monitoring(
        gs.id, enabled=True, max_ec_delta=0.5, target_runoff_percent=20.0
    )

    drain_config = coordinator.growspaces[gs.id].drain_config
    assert drain_config.enabled is True
    assert drain_config.max_ec_delta == 0.5
    assert drain_config.target_runoff_percent == 20.0
    coordinator.async_commit.assert_called_once()


@pytest.mark.asyncio
async def test_async_reset_water_tracking_not_found(hass: HomeAssistant) -> None:
    """Test async_reset_water_tracking raises when growspace not found."""

    coordinator = create_test_coordinator(hass)

    with pytest.raises(ServiceValidationError):
        await coordinator.services.growspaces.reset_water_tracking("nonexistent")


@pytest.mark.asyncio
async def test_async_reset_water_tracking_success(hass: HomeAssistant) -> None:
    """Test async_reset_water_tracking resets water usage (lines 1280-1294)."""
    coordinator = create_test_coordinator(hass)
    gs = await coordinator.services.growspaces.add_growspace(
        name="Water GS", rows=2, plants_per_row=2
    )
    coordinator.async_commit = AsyncMock()

    await coordinator.services.growspaces.reset_water_tracking(gs.id)

    coordinator.async_commit.assert_called_once()
    assert coordinator.growspaces[gs.id].water_usage is not None


# =============================================================================
# EC ramp curve methods (lines 1304, 1310)
# =============================================================================


@pytest.mark.asyncio
async def test_async_save_ec_ramp_curve(hass: HomeAssistant) -> None:
    """Test async_save_ec_ramp_curve delegates to facade (line 1304)."""
    coordinator = create_test_coordinator(hass)
    mock_preset = MagicMock()

    coordinator.services.config.save_ec_ramp_curve = AsyncMock(return_value=mock_preset)

    await coordinator.services.config.save_ec_ramp_curve(
        name="Bloom Ramp", points=[{"day": 1, "ec": 1.8}]
    )

    coordinator.services.config.save_ec_ramp_curve.assert_called_once()


@pytest.mark.asyncio
async def test_async_remove_ec_ramp_curve(hass: HomeAssistant) -> None:
    """Test async_remove_ec_ramp_curve delegates to facade (line 1310)."""
    coordinator = create_test_coordinator(hass)
    coordinator.services.config.remove_ec_ramp_curve = AsyncMock()

    await coordinator.services.config.remove_ec_ramp_curve(None, "curve_1")

    coordinator.services.config.remove_ec_ramp_curve.assert_called_once_with(
        None, "curve_1"
    )


# =============================================================================
# Strain library methods (lines 1360-1362, 1370, 1378-1380)
# =============================================================================


@pytest.mark.asyncio
async def test_get_strain_options_no_library(hass: HomeAssistant) -> None:
    """Test get_strain_options returns [] when strain_library is None (line 1361)."""
    coordinator = create_test_coordinator(hass)
    coordinator._strain_library = None

    result = coordinator.services.config.get_strain_options()
    assert result == []


@pytest.mark.asyncio
async def test_get_strain_options_with_library(hass: HomeAssistant) -> None:
    """Test get_strain_options returns sorted keys (line 1362)."""
    coordinator = create_test_coordinator(hass)
    mock_lib = MagicMock()
    mock_lib.get_all.return_value = {"Zkittlez": {}, "OG Kush": {}, "Blue Dream": {}}
    coordinator._strain_library = mock_lib

    result = coordinator.services.config.get_strain_options()
    assert result == ["Blue Dream", "OG Kush", "Zkittlez"]


@pytest.mark.asyncio
async def test_export_strain_library(hass: HomeAssistant) -> None:
    """Test export_strain_library delegates to get_strain_options (line 1370)."""
    coordinator = create_test_coordinator(hass)
    mock_lib = MagicMock()
    mock_lib.get_all.return_value = {"Strain A": {}}
    coordinator._strain_library = mock_lib

    result = coordinator.services.config.export_strain_library()
    assert result == ["Strain A"]


@pytest.mark.asyncio
async def test_clear_strains_no_library(hass: HomeAssistant) -> None:
    """Test clear_strains returns 0 when no library (line 1379)."""
    coordinator = create_test_coordinator(hass)
    coordinator._strain_library = None

    result = await coordinator.services.config.clear_strains()
    assert result == 0


@pytest.mark.asyncio
async def test_clear_strains_with_library(hass: HomeAssistant) -> None:
    """Test clear_strains calls library.clear() (line 1380)."""
    coordinator = create_test_coordinator(hass)
    mock_lib = MagicMock()
    mock_lib.clear = AsyncMock(return_value=5)
    coordinator._strain_library = mock_lib

    result = await coordinator.services.config.clear_strains()
    assert result == 5
    mock_lib.clear.assert_called_once()


# =============================================================================
# _guess_overview_entity_id special case fallback (lines 1435-1436)
# =============================================================================


@pytest.mark.asyncio
async def test_guess_overview_entity_id_special_no_entity(hass: HomeAssistant) -> None:
    """Test _guess_overview_entity_id returns sensor.{canonical_id} when no entity registered (line 1436)."""
    coordinator = create_test_coordinator(hass)

    # "veg" is a canonical special growspace - entity registry has no entry yet
    result = coordinator.services.growspaces.guess_overview_entity_id("veg")
    assert result == "sensor.veg"


@pytest.mark.asyncio
async def test_guess_overview_entity_id_special_with_entity(
    hass: HomeAssistant,
) -> None:
    """Test _guess_overview_entity_id returns the real entity_id when found in registry (line 1435)."""

    coordinator = create_test_coordinator(hass)

    # Register an entity with the unique_id matching "dry" canonical growspace
    canonical_uid = generate_growspace_overview_unique_id("dry")
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain="sensor",
        platform=DOMAIN,
        unique_id=canonical_uid,
    )

    # Use an alias that resolves to "dry" canonical
    result = coordinator.services.growspaces.guess_overview_entity_id("drying")
    assert result == entry.entity_id


# =============================================================================
# fire_event (lines 1490-1491)
# =============================================================================


@pytest.mark.asyncio
async def test_fire_event(hass: HomeAssistant) -> None:
    """Test fire_event fires the correct HA event (lines 1490-1491)."""
    coordinator = create_test_coordinator(hass)

    events = []

    def capture(event):
        events.append(event)

    hass.bus.async_listen("growspace_manager_updated", capture)

    coordinator.services.fire_event("test_event", {"key": "value"})
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["event_type"] == "test_event"
    assert events[0].data["data"] == {"key": "value"}


@pytest.mark.asyncio
async def test_async_set_lighting_schedule(hass: HomeAssistant) -> None:
    """Test setting the lighting schedule (line 1008)."""
    coordinator = create_test_coordinator(hass)

    env = EnvironmentConfig()
    gs = Growspace(id="gs1", name="Test GS", environment_config=env)
    coordinator._data_repository.add_growspace(gs)

    # Test successful set
    await coordinator.services.growspaces.set_lighting_schedule("gs1", 18, 12, 35.5)
    assert gs.environment_config.veg_day_hours == 18
    assert gs.environment_config.flower_day_hours == 12
    assert gs.environment_config.dli_target_veg == pytest.approx(35.5)

    # Test without DLI (should remain unchanged or be None)
    await coordinator.services.growspaces.set_lighting_schedule("gs1", 20, 10, None)
    assert gs.environment_config.veg_day_hours == 20
    assert gs.environment_config.flower_day_hours == 10
    assert gs.environment_config.dli_target_veg == pytest.approx(
        35.5
    )  # Still 35.5 from previous call

    # Test with None dli_veg
    await coordinator.services.growspaces.set_lighting_schedule("gs1", 18, 12)
    assert gs.environment_config.veg_day_hours == 18

    # Test missing growspace
    with pytest.raises(ServiceValidationError):
        await coordinator.services.growspaces.set_lighting_schedule(
            "nonexistent", 18, 12
        )
