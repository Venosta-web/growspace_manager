"""Additional tests for plant_lifecycle_manager coverage."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.exceptions import ValidationChangeError
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.context import ServiceContext

from .common import create_plant


@pytest.fixture
def notification_state() -> NotificationState:
    """Real NotificationState for testing."""
    return NotificationState()


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.get_plant.return_value = None
    mock.has_plant.return_value = False
    mock.has_growspace.side_effect = lambda gid: gid == "test_growspace"
    mock.get_growspace.side_effect = lambda gid: Growspace(id=gid, name=gid) if gid == "test_growspace" else None
    return mock


@pytest.fixture
def validator_mock():
    """Mock the GrowspaceValidator."""
    mock = MagicMock()
    mock.find_first_available_position.return_value = (1, 1)
    return mock


@pytest.fixture
def gs_service_mock():
    """Mock the GrowspaceService."""
    mock = MagicMock()
    mock.ensure_special_growspace.return_value = "dry"
    return mock


@pytest.fixture
def strain_library_mock():
    """Mock the StrainLibrary."""
    mock = MagicMock()
    mock.record_harvest = AsyncMock()
    return mock


@pytest.fixture
def lock_mock():
    """Mock the asyncio Lock."""
    mock = MagicMock()
    mock.__aenter__ = AsyncMock(return_value=None)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def save_callback_mock():
    """Mock the save callback."""
    return AsyncMock()


@pytest.fixture
def manager(
    hass,
    repository_mock,
    notification_state,
    validator_mock,
    gs_service_mock,
    strain_library_mock,
    save_callback_mock,
    lock_mock,
):
    """Fixture for PlantManager."""
    return PlantManager(
        ctx=ServiceContext(
            save_callback=save_callback_mock,
            lock=lock_mock,
            add_event=MagicMock(),
            invalidate_cache=MagicMock(),
        ),
        hass=hass,
        repository=repository_mock,
        notification_state=notification_state,
        validator=validator_mock,
        growspace_manager=gs_service_mock,
        strain_library=strain_library_mock,
        plant_view_builder=MagicMock(),
    )


@pytest.mark.asyncio
async def test_async_remove_plant_not_found(manager, save_callback_mock) -> None:
    """Test async_remove_plant when plant doesn't exist."""
    # Try to remove non-existent plant
    result = await manager.async_remove_plant("nonexistent_plant_id")

    # Should return False
    assert result is False
    save_callback_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_remove_plant_with_notifications(
    manager, repository_mock, notification_state, save_callback_mock
) -> None:
    """Test async_remove_plant removes from notifications_sent dict."""
    # Add a plant and notification
    plant_id = "test_plant_123"
    plant = create_plant(
        plant_id=plant_id,
        growspace_id="test_growspace",
        strain="Test Strain",
    )
    repository_mock.get_plant.return_value = plant
    repository_mock.has_plant.return_value = True
    notification_state.sent[plant_id] = True

    # Remove the plant
    result = await manager.async_remove_plant(plant_id)

    # Should remove from notifications_sent
    assert result is True
    assert plant_id not in notification_state.sent
    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_analytics_exception_handling(
    manager, strain_library_mock
) -> None:
    """Test _record_analytics handles exceptions gracefully."""
    # Create a plant with veg and flower days
    plant = create_plant(
        plant_id="test_plant",
        growspace_id="test_growspace",
        strain="Test Strain",
        veg_start="2024-01-01",
        flower_start="2024-02-01",
    )

    # Patch calculate_days_in_stage to return positive days
    with patch(
        "custom_components.growspace_manager.managers.plant.calculate_days_in_stage",
        side_effect=[30, 60],
    ):
        # Mock strain_library.record_harvest to raise exception
        strain_library_mock.record_harvest = AsyncMock(
            side_effect=Exception("Database error")
        )

        # Should not raise, exception is caught and logged
        await manager._record_analytics(plant)

    # Verify record_harvest was called with scores (all None since plant has no scores set)
    strain_library_mock.record_harvest.assert_awaited_once_with(
        "Test Strain",
        "",
        30,
        60,
        None,
        None,
        None,
        None,
        None,
        wet_weight=None,
        dry_weight=None,
        trim_weight=None,
        thc_percentage=None,
        cbd_percentage=None,
        terpene_profile=None,
    )


@pytest.mark.asyncio
async def test_transition_plant_stage_to_clone(
    manager, repository_mock, validator_mock, gs_service_mock
) -> None:
    """Test transition_plant_stage to CLONE stage."""
    # Create a plant
    plant_id = "test_plant"
    plant = create_plant(
        plant_id=plant_id,
        growspace_id="test_growspace",
        strain="Test Strain",
    )
    repository_mock.get_plant.return_value = plant

    # Transition to CLONE stage
    await manager.transition_plant_stage(plant_id, PlantStage.CLONE, date(2024, 1, 15))

    # Verify move_to_clone_growspace was called via service
    gs_service_mock.ensure_special_growspace.assert_called()


@pytest.mark.asyncio
async def test_async_add_plant_full_growspace(manager, validator_mock) -> None:
    """Test async_add_plant when growspace is full."""

    # Mock validator to simulate occupied position and no available space
    validator_mock.validate_position_not_occupied.side_effect = ValidationChangeError(
        "Occupied"
    )
    validator_mock.find_first_available_position.return_value = (None, None)

    # Adding a plant should raise ValidationChangeError with the "full" message
    with pytest.raises(ValidationChangeError, match="is full, cannot add/move plant"):
        await manager.async_add_plant(
            growspace_id="test_growspace",
            strain="Test Strain",
            row=1,
            col=1,
        )


@pytest.mark.asyncio
async def test_async_update_plant_genetics(
    manager, repository_mock, save_callback_mock
) -> None:
    """Test async_update_plant covers strain and phenotype updates."""
    # Create a plant
    plant_id = "test_plant"
    plant = create_plant(
        plant_id=plant_id,
        growspace_id="test_growspace",
        strain="Old Strain",
        phenotype="Old Pheno",
    )
    repository_mock.get_plant.return_value = plant

    # Update strain and phenotype
    updated_plant = await manager.async_update_plant(
        plant_id, strain="New Strain", phenotype="New Pheno"
    )

    # Verify updates
    assert updated_plant.genetics.strain_name == "New Strain"
    assert updated_plant.genetics.phenotype_name == "New Pheno"
    save_callback_mock.assert_awaited_once()
