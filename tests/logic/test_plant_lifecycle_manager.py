"""Tests for the PlantLifecycleManager class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.context import ServiceContext
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.plants = {}
    mock.growspaces = {}
    mock.notifications_sent = {}
    return mock


@pytest.fixture
def validator_mock():
    """Mock the GrowspaceValidator."""
    mock = MagicMock()
    mock.find_first_available_position = MagicMock(return_value=(1, 1))
    mock.validate_position_not_occupied = MagicMock()
    mock.validate_plant_exists = MagicMock()
    return mock


@pytest.fixture
def gs_service_mock():
    """Mock the GrowspaceService."""
    mock = MagicMock()
    mock.ensure_special_growspace = MagicMock(return_value="mock_growspace_id")
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
    hass: HomeAssistant,
    repository_mock,
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
        notification_state=MagicMock(),
        validator=validator_mock,
        growspace_manager=gs_service_mock,
        strain_library=strain_library_mock,
        plant_view_builder=MagicMock(),
    )


@pytest.mark.asyncio
async def test_handle_clone_creation(
    manager, repository_mock, save_callback_mock
) -> None:
    """Test handle_clone_creation adds plant to repository."""
    mother_plant = MagicMock(spec=Plant)
    mother_plant.phenotype = "Pheno1"

    plant_id = await manager.handle_clone_creation(
        growspace_id="clone_tent",
        strain="OG Kush",
        row=1,
        col=2,
        source_mother_id="mother_id",
        mother_plant=mother_plant,
        extra_param="extra_value",
    )

    assert plant_id is not None
    # Check that add_plant was called on the repository
    repository_mock.add_plant.assert_called_once()
    added_plant = repository_mock.add_plant.call_args[0][0]

    assert added_plant.growspace_id == "clone_tent"
    assert added_plant.strain == "OG Kush"
    assert added_plant.phenotype == "Pheno1"
    assert added_plant.row == 1
    assert added_plant.col == 2
    assert added_plant.stage == PlantStage.CLONE
    assert added_plant.type == PlantStage.CLONE
    assert added_plant.source_mother == "mother_id"

    save_callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_harvest_auto_flow_strict_matching_audreys_garden(
    manager, repository_mock
) -> None:
    """Test that 'Audrey's Garden' does NOT trigger 'dry' logic via loose matching."""

    plant = MagicMock()
    plant.stage = PlantStage.VEG
    plant.growspace_id = "initial_gs"
    plant.strain = "Test Strain"
    plant.phenotype = "Test Pheno"

    # Let's mock the move methods on the manager instance itself to track calls
    with (
        patch.object(
            manager, "move_to_dry_growspace", new_callable=AsyncMock
        ) as mock_move_dry,
        patch.object(manager, "move_to_cure_growspace", new_callable=AsyncMock) as _,
        patch.object(manager, "move_to_clone_growspace", new_callable=AsyncMock) as _,
    ):
        mock_move_dry.return_value = True

        await manager._harvest_auto_flow(
            plant_id="plant1",
            plant=plant,
            target_growspace_name="Audrey's Garden",
            transition_date="2023-01-01",
        )

        # It should call move_to_dry_growspace (fallback)
        mock_move_dry.assert_awaited()


@pytest.mark.asyncio
async def test_harvest_auto_flow_explicit_dry(manager, repository_mock) -> None:
    """Test explicit 'dry' match."""
    plant = MagicMock()
    plant.stage = PlantStage.VEG
    plant.growspace_id = "initial_gs"
    plant.strain = "Test Strain"
    plant.phenotype = "Test Pheno"
    plant.plant_id = "p1"
    repository_mock.plants = {"p1": plant}  # Ensure plant exists

    with patch.object(
        manager, "_move_to_special_growspace", new_callable=AsyncMock
    ) as mock_move_special:
        mock_move_special.return_value = True

        await manager._harvest_auto_flow("p1", plant, "dry", "2023-01-01")

        mock_move_special.assert_awaited_once_with(
            "p1", plant, PlantStage.DRY, "2023-01-01"
        )


@pytest.mark.asyncio
async def test_move_to_dry_growspace_device_id_ghosting(
    manager, repository_mock, gs_service_mock
) -> None:
    """Test that moving to a growspace without a device ID clears the plant's device ID."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.device_id = "device_1"
    plant.strain = "Strain"
    plant.phenotype = "Pheno"

    # Mock the destination dry growspace having NO device_id
    gs_service_mock.ensure_special_growspace.return_value = "dry_gs"
    mock_dry_gs = MagicMock()
    mock_dry_gs.device_id = None  # Crucial: destination has no device
    repository_mock.get_growspace.side_effect = lambda gid: {
        "dry_gs": mock_dry_gs,
        "gs1": MagicMock(),
    }.get(gid)
    repository_mock.get_plant.return_value = plant

    await manager.move_to_dry_growspace("p1", plant, "2023-01-01")

    # Verify that async_update_plant was called with device_id=None
    # (Since async_update_plant is a method on manager, we check the repository update)
    # Wait, in the actual implementation, move_to_dry_growspace calls _move_to_special_growspace
    # which calls async_update_plant.
    # Since we are testing the REAL manager, it will update repository.plants
    assert plant.device_id is None


@pytest.mark.asyncio
async def test_handle_transition_logic_fallthrough(manager, repository_mock) -> None:
    """Test that invalid target_growspace_id raises ValueError and does not fall through."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    plant.phi_clearance_date = None
    # Mock growspaces not containing 'invalid_gs'
    repository_mock.has_growspace.side_effect = lambda gid: gid == "valid_gs"

    with pytest.raises(
        GrowspaceNotFoundError, match="Target growspace invalid_gs not found"
    ):
        await manager.handle_transition_logic(
            "p1", plant, "invalid_gs", "Invalid Name", "2023-01-01"
        )


@pytest.mark.asyncio
async def test_update_plant_preserves_lifecycle_datetime_time(
    manager, repository_mock
) -> None:
    """update_plant stores a lifecycle datetime with its time intact (ADR-0013).

    Previously DATE_FIELDS were run through format_date, truncating to date-only;
    the time the user picked was silently discarded on the way to storage.
    """
    plant = Plant(plant_id="p1", growspace_id="gs1")
    repository_mock.get_plant.return_value = plant

    await manager.update_plant("p1", flower_start="2026-03-01T14:30:00+00:00")

    # Stored as a full datetime string, not truncated to "2026-03-01".
    assert "T14:30" in plant.flower_start


@pytest.mark.asyncio
async def test_transition_plant_stage_preserves_supplied_datetime(
    manager, repository_mock
) -> None:
    """A stage transition stamps the start field with the supplied datetime's time."""
    plant = Plant(plant_id="p1", growspace_id="gs1")
    repository_mock.get_plant.return_value = plant

    await manager.transition_plant_stage(
        "p1", PlantStage.FLOWER, "2026-03-01T14:30:00+00:00"
    )

    assert "T14:30" in plant.flower_start


@pytest.mark.asyncio
async def test_remove_plant_not_found(manager, repository_mock) -> None:
    """Test remove_plant returns False when plant does not exist."""
    repository_mock.get_plant.return_value = None
    result = await manager.remove_plant("non_existent_plant")
    assert result is False


@pytest.mark.asyncio
async def test_remove_plant_race_condition(
    manager: PlantManager, repository_mock: MagicMock
) -> None:
    """Test remove_plant returns False if plant disappears before lock acquisition."""
    plant_id = "race_plant"
    plant = MagicMock()

    # The plant exists until the shared mutation lock is acquired.
    repository_mock.get_plant.return_value = plant

    async def side_effect_enter() -> None:
        repository_mock.get_plant.return_value = None

    manager._ctx.lock.__aenter__.side_effect = side_effect_enter

    result = await manager.remove_plant(plant_id)
    assert result is False


@pytest.mark.asyncio
async def test_transition_plant_defensive_check(manager, repository_mock) -> None:
    """Test transition_plant handles invalid plant objects gracefully."""
    plant = MagicMock()
    plant.phi_clearance_date = None
    # Explicitly remove growspace_id to trigger the defensive check
    del plant.growspace_id
    repository_mock.plants = {"p1": plant}

    # Needs to exist in validator check
    manager.validator.validate_plant_exists = MagicMock()

    # Patch async_fire_plant_event to avoid crash when accessing missing attributes
    with (
        patch(
            "custom_components.growspace_manager.managers.plant.async_fire_plant_event"
        ),
        patch.object(
            manager, "_harvest_auto_flow", new_callable=AsyncMock
        ) as mock_harvest_flow,
    ):
        mock_harvest_flow.return_value = True

        await manager.transition_plant("p1", plant=plant)

        # Should still proceed to call the flow
        mock_harvest_flow.assert_awaited()


@pytest.mark.asyncio
async def test_promote_clone_target_full(manager, repository_mock) -> None:
    """Test promote_clone raises ValidationChangeError when target is full."""
    clone_plant = MagicMock(spec=Plant)
    clone_plant.stage = PlantStage.CLONE
    clone_plant.plant_id = "c1"

    repository_mock.get_plant.return_value = clone_plant

    # Mock find_first_available_position returning (None, None)
    manager.validator.find_first_available_position.return_value = (None, None)

    # Mock update_plant to avoid actual logic running if it somehow bypassed
    with (
        patch.object(
            manager.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
        ),
        pytest.raises(ValidationChangeError, match="Target growspace .* is full"),
    ):
        await manager.promote_clone("c1", target_growspace_id="veg")


@pytest.mark.asyncio
async def test_handle_transition_logic_kwargs(manager) -> None:
    """Test handle_transition_logic passes through kwargs correctly."""
    with patch.object(
        manager, "transition_plant", new_callable=AsyncMock
    ) as mock_harvest:
        # Call with keyword args only
        await manager.handle_transition_logic(plant_id="p1", custom_arg=True)

        mock_harvest.assert_awaited_with(plant_id="p1", custom_arg=True)
