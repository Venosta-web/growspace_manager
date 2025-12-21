"""Tests for the Growspace Manager data update coordinator.

This file contains a suite of tests for the `GrowspaceCoordinator`, which is the
central hub for managing all data within the Growspace Manager integration.
These tests cover the full lifecycle of growspaces and plants, including
creation, updating, removal, and various stage transitions. It also tests
data migration, validation, and helper methods.
"""

from datetime import date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.dt import now
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import (
    DOMAIN,
    PLANT_STAGES,
    SPECIAL_GROWSPACES,
    PlantStage,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceEvent,
    GrowspaceType,
    IrrigationConfig,
    Plant,
)
from custom_components.growspace_manager.utils import calculate_plant_stage


def create_test_coordinator(
    hass: HomeAssistant, data=None, options=None, strain_library=None
) -> GrowspaceCoordinator:
    """Helper to create a coordinator with a mock config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()
    return GrowspaceCoordinator(
        hass,
        entry,
        data=data or {},
        options=options,
        strain_library=strain_library,
    )


@pytest.fixture
def mock_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Provide a fresh `GrowspaceCoordinator` instance for each test.

    Args:
        hass: The Home Assistant instance.

    Returns:
        A new `GrowspaceCoordinator` instance with mocked update methods.
    """
    strain_library = MagicMock()
    strain_library.record_harvest = AsyncMock()
    mock_entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    # Add async_create_background_task mock to entry
    mock_entry.async_create_background_task = MagicMock()

    coordinator = GrowspaceCoordinator(
        hass, mock_entry, data={}, strain_library=strain_library
    )
    coordinator.async_save = AsyncMock()
    setattr(coordinator, "async_set_updated_data", MagicMock())
    return coordinator


@pytest.mark.asyncio
async def test_add_and_remove_plant(coordinator: GrowspaceCoordinator) -> None:
    """Test the basic addition and removal of a plant.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Plant GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A", row=1, col=1)
    assert plant.plant_id in coordinator.plants
    assert plant.strain == "Strain A"

    removed = await coordinator.async_remove_plant(plant.plant_id)
    assert removed
    assert plant.plant_id not in coordinator.plants
    coordinator.async_set_updated_data.assert_called()


@pytest.mark.asyncio
async def test_transition_plant_stage(coordinator: GrowspaceCoordinator) -> None:
    """Test transitioning a plant through various growth stages.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Stage GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain B")

    transition_date = "2025-11-03"  # ISO string

    # Only test the stages you want to transition through
    for stage in PLANT_STAGES:
        if stage not in ["veg", "flower", "dry", "cure"]:
            continue  # skip stages that don't have *_start fields

        await coordinator.async_transition_plant_stage(
            plant.plant_id, stage, transition_date=transition_date
        )
        updated = coordinator.plants[plant.plant_id]

        assert updated.stage == stage

        if stage == "veg":
            assert updated.veg_start.startswith(transition_date)
        elif stage == "flower":
            assert updated.flower_start.startswith(transition_date)
        elif stage == "dry":
            assert updated.dry_start.startswith(transition_date)
        elif stage == "cure":
            assert updated.cure_start.startswith(transition_date)


@pytest.mark.asyncio
async def test_async_create_mum(coordinator: GrowspaceCoordinator) -> None:
    """Test the creation of a mother plant.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    start_time_date = date(2025, 3, 1)
    start_time_iso = start_time_date.isoformat()
    with freeze_time(start_time_iso):
        mother = await coordinator.async_add_mother_plant(
            "Pheno1", "StrainC", 1, 1, start_time_iso
        )

    assert mother.mother_start == start_time_iso
    assert mother.plant_id in coordinator.plants
    assert mother.type == "mother"
    assert mother.strain == "StrainC"
    assert mother.phenotype == "Pheno1"


@pytest.mark.asyncio
async def test_async_take_clones(coordinator: GrowspaceCoordinator) -> None:
    """Test taking clones from a mother plant.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    mother_time_date = date(2025, 4, 1)
    mother_time_iso = mother_time_date.isoformat()
    clone_time_date = date(2025, 4, 2)
    clone_time_iso = clone_time_date.isoformat()

    with freeze_time(mother_time_iso):
        mother = await coordinator.async_add_mother_plant("Pheno1", "StrainC", 1, 1)

    with freeze_time(clone_time_iso):
        clone_ids = await coordinator.async_take_clones(
            mother_plant_id=mother.plant_id,
            num_clones=3,
            target_growspace_id=None,
            target_growspace_name="",
            transition_date=None,
        )

    assert len(clone_ids) == 3
    for clone in clone_ids:
        assert clone.plant_id in coordinator.plants
        assert clone.stage == "clone"
        assert clone.source_mother == mother.plant_id
        assert clone.strain == mother.strain
        assert clone.clone_start == clone_time_iso


@pytest.mark.asyncio
async def test_ensure_special_growspace(coordinator: GrowspaceCoordinator) -> None:
    """Test that special growspaces are created with the correct properties.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs_id = coordinator.ensure_special_growspace("mother", "Mother GS", 3, 3)
    assert gs_id in coordinator.growspaces
    gs = coordinator.growspaces[gs_id]
    assert gs.name == "Mother GS"
    assert gs.rows == 3
    assert gs.plants_per_row == 3


@pytest.mark.asyncio
async def test_update_plant_position(coordinator: GrowspaceCoordinator) -> None:
    """Test updating a plant's position within a growspace.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Position GS", 3, 3)
    plant = await coordinator.async_add_plant(gs.id, "Strain D", row=1, col=1)

    await coordinator.async_update_plant(plant.plant_id, row=2, col=2)
    updated = coordinator.plants[plant.plant_id]
    assert updated.row == 2
    assert updated.col == 2


@pytest.mark.asyncio
async def test_switch_plants(coordinator: GrowspaceCoordinator) -> None:
    """Test switching the positions of two plants in the same growspace.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Switch GS", 2, 2)
    plant1 = await coordinator.async_add_plant(gs.id, "Strain1", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "Strain2", row=2, col=2)

    await coordinator.async_switch_plants(plant1.plant_id, plant2.plant_id)
    p1 = coordinator.plants[plant1.plant_id]
    p2 = coordinator.plants[plant2.plant_id]
    assert (p1.row, p1.col) == (2, 2)
    assert (p2.row, p2.col) == (1, 1)


@pytest.mark.asyncio
async def test_remove_nonexistent_plant_returns_false(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test that attempting to remove a nonexistent plant returns False.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    result = await coordinator.async_remove_plant("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_get_growspace_options(coordinator: GrowspaceCoordinator) -> None:
    """Test that `get_growspace_options` returns a correct dictionary.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add some growspaces
    gs1 = await coordinator.async_add_growspace("Veg GS", rows=2, plants_per_row=2)
    gs2 = await coordinator.async_add_growspace("Flower GS", rows=3, plants_per_row=3)

    options = coordinator.get_growspace_options()

    # Check that it's a dict
    assert isinstance(options, dict)

    # Check that the IDs match the growspaces we added
    assert gs1.id in options
    assert gs2.id in options

    # Check that the names are correct
    assert options[gs1.id] == gs1.name
    assert options[gs2.id] == gs2.name

    # If we remove a growspace, it should no longer be in options
    await coordinator.async_remove_growspace(gs1.id)
    options = coordinator.get_growspace_options()
    assert gs1.id not in options
    assert gs2.id in options


@pytest.mark.asyncio
async def test_get_sorted_growspace_options(coordinator: GrowspaceCoordinator) -> None:
    """Test that `get_sorted_growspace_options` returns a list sorted by name.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add growspaces with names in unsorted order
    gs1 = await coordinator.async_add_growspace("C-GS", rows=2, plants_per_row=2)
    gs2 = await coordinator.async_add_growspace("A-GS", rows=2, plants_per_row=2)
    gs3 = await coordinator.async_add_growspace("B-GS", rows=2, plants_per_row=2)

    sorted_options = coordinator.get_sorted_growspace_options()

    # Check it's a list of tuples
    assert isinstance(sorted_options, list)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in sorted_options)

    # Check the order by name
    expected_order = [gs2, gs3, gs1]  # sorted by name: A-GS, B-GS, C-GS
    sorted_ids = [item[0] for item in sorted_options]
    assert sorted_ids == [gs.id for gs in expected_order]

    # Check the names match
    sorted_names = [item[1] for item in sorted_options]
    assert sorted_names == [gs.name for gs in expected_order]


@pytest.mark.asyncio
async def test_migrate_legacy_growspaces(coordinator: GrowspaceCoordinator) -> None:
    """Test that legacy growspace aliases are correctly migrated.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Patch the _migrate_special_alias_if_needed method to track calls
    with patch.object(
        coordinator.migration_manager,
        "_migrate_special_alias_if_needed",
        wraps=coordinator.migration_manager._migrate_special_alias_if_needed,
    ) as mock_migrate:
        # Call the private migration method
        coordinator._migrate_legacy_growspaces()

        # Ensure it was called for each alias in SPECIAL_GROWSPACES
        total_aliases = sum(
            len(config["aliases"]) for config in SPECIAL_GROWSPACES.values()
        )
        assert mock_migrate.call_count == total_aliases

        # Optionally, verify the first call arguments (example)
        first_config = list(SPECIAL_GROWSPACES.values())[0]
        first_alias = first_config["aliases"][0]
        mock_migrate.assert_any_call(
            first_alias, first_config["canonical_id"], first_config["canonical_name"]
        )


@pytest.mark.asyncio
async def test_create_canonical_from_alias(coordinator: GrowspaceCoordinator) -> None:
    """Test creating a new canonical growspace from a legacy alias.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    alias_id = "alias_gs"
    canonical_id = "canonical_gs"
    canonical_name = "Canonical GS"

    coordinator.growspaces[alias_id] = Growspace(
        id=alias_id,
        name="Alias GS",
        rows=4,
        plants_per_row=5,
        notification_target="notify_me",
        device_id="device_1",
    )

    # Patch migrate_plants_to_growspace and update_data_property
    coordinator.migration_manager.migrate_plants_to_growspace = Mock()
    coordinator.update_data_property = Mock()

    # Call the internal method
    coordinator.migration_manager._create_canonical_from_alias(
        alias_id, canonical_id, canonical_name
    )

    # Assert the canonical growspace exists
    new_gs = coordinator.growspaces[canonical_id]
    assert new_gs.id == canonical_id
    assert new_gs.name == canonical_name
    assert new_gs.rows == 4
    assert new_gs.plants_per_row == 5
    assert new_gs.notification_target == "notify_me"
    assert new_gs.device_id == "device_1"  # Now preserves device_id from source

    # Alias removed
    assert alias_id not in coordinator.growspaces

    # Helpers called
    coordinator.migration_manager.migrate_plants_to_growspace.assert_called_once_with(
        alias_id, canonical_id
    )
    coordinator.update_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_consolidate_alias_into_canonical(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test consolidating plants from an alias growspace into a canonical one.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    alias_id = "alias_gs"
    canonical_id = "canonical_gs"

    # Setup growspaces
    # Setup growspaces
    coordinator.growspaces[alias_id] = Growspace(id=alias_id, name="Alias GS")
    coordinator.growspaces[canonical_id] = Growspace(
        id=canonical_id, name="Canonical GS"
    )

    # Patch helpers
    coordinator.migration_manager.migrate_plants_to_growspace = Mock()
    coordinator.update_data_property = Mock()

    # Call the method
    coordinator.migration_manager._consolidate_alias_into_canonical(
        alias_id, canonical_id
    )

    # Assert alias removed
    assert alias_id not in coordinator.growspaces

    # Assert canonical still exists
    assert canonical_id in coordinator.growspaces

    # Helpers called
    coordinator.migration_manager.migrate_plants_to_growspace.assert_called_once_with(
        alias_id, canonical_id
    )
    coordinator.update_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_migrate_plants_to_growspace(coordinator: GrowspaceCoordinator) -> None:
    """Test that `_migrate_plants_to_growspace` moves all plants correctly.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Use actual Growspace instances
    coordinator.growspaces["gs1"] = Growspace(
        id="gs1", name="Growspace 1", rows=3, plants_per_row=3
    )
    coordinator.growspaces["gs2"] = Growspace(
        id="gs2", name="Growspace 2", rows=3, plants_per_row=3
    )

    # Add plants
    plant1 = await coordinator.async_add_plant("gs1", "Strain1")
    plant2 = await coordinator.async_add_plant("gs1", "Strain2")
    plant3 = await coordinator.async_add_plant("gs2", "Strain3")  # Should remain

    # Migrate plants
    coordinator.migration_manager.migrate_plants_to_growspace("gs1", "gs2")

    # Assert all plants from gs1 are now in gs2
    assert coordinator.plants[plant1.plant_id].growspace_id == "gs2"
    assert coordinator.plants[plant2.plant_id].growspace_id == "gs2"
    # Plant already in gs2 remains
    assert coordinator.plants[plant3.plant_id].growspace_id == "gs2"


@pytest.mark.asyncio
async def test_get_plant_stage(coordinator: GrowspaceCoordinator) -> None:
    """Test that `_get_plant_stage` correctly determines the stage from dates.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Helper to create a plant with only one stage set
    def make_plant_with_stage(stage_attr: str):
        kwargs: dict[str, Any] = {f"{stage_attr}_start": date(2025, 1, 1).isoformat()}
        return Plant(
            plant_id=f"{stage_attr}_id", strain="Test", growspace_id="gs1", **kwargs
        )

    stages = ["cure", "dry", "flower", "veg", "clone", "mother", "seedling"]

    for stage in stages:
        if stage == "seedling":
            plant = Plant(plant_id="seedling_id", strain="Test", growspace_id="gs1")
        else:
            plant = make_plant_with_stage(stage)
        result = calculate_plant_stage(plant)
        assert result == stage, f"Expected stage {stage}, got {result}"


@pytest.mark.asyncio
async def test_get_plant(coordinator: GrowspaceCoordinator) -> None:
    """Test retrieving a plant by its ID using `get_plant`.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add a plant
    plant = await coordinator.async_add_plant("gs1", "StrainX", row=1, col=1)

    # Retrieve the plant
    fetched = coordinator.get_plant(plant.plant_id)
    assert fetched is not None
    assert fetched.plant_id == plant.plant_id
    assert fetched.strain == "StrainX"

    # Nonexistent plant returns None
    assert coordinator.get_plant("nonexistent") is None


@pytest.mark.asyncio
async def test_validate_growspace_exists(coordinator: GrowspaceCoordinator) -> None:
    """Test the `_validate_growspace_exists` helper method.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add a growspace
    gs = await coordinator.async_add_growspace("Test GS")

    # Existing growspace should not raise
    coordinator.validator.validate_growspace_exists(gs.id)

    # Nonexistent growspace should raise GrowspaceNotFoundError
    with pytest.raises(
        GrowspaceNotFoundError, match="Growspace nonexistent does not exist"
    ):
        coordinator.validator.validate_growspace_exists("nonexistent")


@pytest.mark.asyncio
async def test_validate_plant_exists(coordinator: GrowspaceCoordinator) -> None:
    """Test the `_validate_plant_exists` helper method.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add a growspace and plant
    gs = await coordinator.async_add_growspace("Test GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain X", row=1, col=1)

    # Existing plant should not raise
    coordinator.validator.validate_plant_exists(plant.plant_id)

    # Nonexistent plant should raise PlantNotFoundError
    with pytest.raises(PlantNotFoundError, match="Plant nonexistent does not exist"):
        coordinator.validator.validate_plant_exists("nonexistent")


@pytest.mark.asyncio
async def test_validate_position_bounds(coordinator: GrowspaceCoordinator) -> None:
    """Test the `_validate_position_bounds` helper method.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add a growspace
    gs = await coordinator.async_add_growspace("Bounds GS", rows=3, plants_per_row=3)

    # Valid positions should not raise
    coordinator.validator.validate_position_bounds(gs.id, row=1, col=1)
    coordinator.validator.validate_position_bounds(gs.id, row=3, col=3)

    # Row out of bounds
    with pytest.raises(
        ValidationChangeError, match="Row 0 is outside growspace bounds"
    ):
        coordinator.validator.validate_position_bounds(gs.id, row=0, col=1)
    with pytest.raises(
        ValidationChangeError, match="Row 4 is outside growspace bounds"
    ):
        coordinator.validator.validate_position_bounds(gs.id, row=4, col=1)

    # Column out of bounds
    with pytest.raises(
        ValidationChangeError, match="Column 0 is outside growspace bounds"
    ):
        coordinator.validator.validate_position_bounds(gs.id, row=1, col=0)
    with pytest.raises(
        ValidationChangeError, match="Column 4 is outside growspace bounds"
    ):
        coordinator.validator.validate_position_bounds(gs.id, row=1, col=4)


@pytest.mark.asyncio
async def test_validate_position_not_occupied(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test the `_validate_position_not_occupied` helper method.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """

    # Add a growspace
    gs = await coordinator.async_add_growspace("Occupy GS", rows=2, plants_per_row=2)

    # Add a plant at (1,1)
    plant1 = await coordinator.async_add_plant(gs.id, "Strain1", row=1, col=1)

    # Valid: empty position
    coordinator.validator.validate_position_not_occupied(gs.id, row=2, col=2)

    # Invalid: occupied position
    with pytest.raises(
        ValidationChangeError, match=r"Position \(1,1\) is already occupied by Strain1"
    ):
        coordinator.validator.validate_position_not_occupied(gs.id, row=1, col=1)

    # Valid if excluding the same plant
    coordinator.validator.validate_position_not_occupied(
        gs.id, row=1, col=1, exclude_plant_id=plant1.plant_id
    )


@pytest.mark.asyncio
async def test_calculate_days(coordinator: GrowspaceCoordinator) -> None:
    """Test the `calculate_days` helper for various input types.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    today = date.today()

    # Using string
    days = coordinator.calculate_days("2025-01-01")
    expected = (today - date(2025, 1, 1)).days
    assert days == expected

    # Using date
    start = date(2024, 12, 31)
    days = coordinator.calculate_days(start)
    expected = (today - start).days
    assert days == expected

    # Using datetime
    start_dt = datetime(2024, 12, 30, 15, 0)
    days = coordinator.calculate_days(start_dt)
    expected = (today - start_dt.date()).days
    assert days == expected

    # None or 'None' should return 0
    assert coordinator.calculate_days(None) == 0
    assert coordinator.calculate_days("None") == 0

    # Invalid string returns 0 (logs warning)
    assert coordinator.calculate_days("invalid-date") == 0


@pytest.mark.asyncio
async def test_generate_unique_name(coordinator: GrowspaceCoordinator) -> None:
    """Test that `_generate_unique_name` creates unique, non-conflicting names.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: add a growspace with the base name
    await coordinator.async_add_growspace("MyGrowspace")

    # First call: should append " 1" because "MyGrowspace" exists
    name2 = coordinator._generate_unique_name("MyGrowspace")
    assert name2 == "MyGrowspace 1"

    # Add the new growspace
    await coordinator.async_add_growspace(name2)

    # Next call: should append " 2"
    name3 = coordinator._generate_unique_name("MyGrowspace")
    assert name3 == "MyGrowspace 2"

    # Test a completely new base name returns unchanged
    name4 = coordinator._generate_unique_name("UniqueName")
    assert name4 == "UniqueName"


@pytest.mark.asyncio
async def test_update_special_growspace_name(coordinator: GrowspaceCoordinator) -> None:
    """Test updating the name of a special growspace.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: add a growspace with a different name
    gs = await coordinator.async_add_growspace("OldName")
    gs_id = gs.id

    # Update to a new canonical name
    coordinator._update_special_growspace_name(gs_id, "NewName")
    assert coordinator.growspaces[gs_id].name == "NewName"

    # Update again with the same name: should remain unchanged
    coordinator._update_special_growspace_name(gs_id, "NewName")
    assert coordinator.growspaces[gs_id].name == "NewName"


@pytest.mark.asyncio
async def test_async_update_data(coordinator: GrowspaceCoordinator) -> None:
    """Test the `_async_update_data` method of the coordinator.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: manually set some data
    coordinator.data = {"example": 123}

    # Spy on update_data_property to ensure it is called
    called = False
    original_update = coordinator.update_data_property

    def spy_update_data_property():
        nonlocal called
        called = True
        original_update()

    coordinator.update_data_property = spy_update_data_property

    # Call the async method
    result = await coordinator._async_update_data()

    # Assertions
    assert called, "update_data_property should be called"
    assert result == coordinator.data, "Returned data should match coordinator.data"


@pytest.mark.asyncio
async def test_async_load(coordinator: GrowspaceCoordinator) -> None:
    """Test loading data from storage.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Prepare fake stored data
    fake_data = {
        "plants": {
            "p1": {"plant_id": "p1", "strain": "StrainX", "growspace_id": "gs1"}
        },
        "growspaces": {
            "gs1": {"id": "gs1", "name": "Growspace1", "rows": 3, "plants_per_row": 3}
        },
        "notifications_sent": {"gs1": []},
        "notifications_enabled": {"gs1": True},
        "strain_library": [{"name": "StrainX"}],
    }

    # Mock the store to return this data
    coordinator.storage_manager.store.async_load = AsyncMock(return_value=fake_data)
    coordinator.async_save = AsyncMock()
    coordinator.strain_library.import_strains = AsyncMock()
    coordinator.storage_manager.async_save = AsyncMock()

    # Patch the ensure methods to avoid side effects (creating default growspaces)
    with (
        patch.object(
            coordinator, "_ensure_default_growspaces", new_callable=AsyncMock
        ) as mock_ensure_defaults,
        patch.object(coordinator, "_ensure_calculated_sensors") as mock_ensure_calc,
    ):
        await coordinator.async_load()
        mock_ensure_defaults.assert_awaited_once()
        mock_ensure_calc.assert_called_once()

    # Assertions
    assert "p1" in coordinator.plants
    assert "gs1" in coordinator.growspaces
    assert coordinator._notifications_sent == {"gs1": []}
    assert coordinator._notifications_enabled == {"gs1": True}

    # Ensure save called
    coordinator.storage_manager.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_async_remove_growspace(coordinator: GrowspaceCoordinator) -> None:
    """Test the complete removal of a growspace and its contents.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: add a growspace with plants
    gs = await coordinator.async_add_growspace("Test GS", 2, 2)

    # Create a device entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={}, entry_id="test_entry")
    config_entry.add_to_hass(coordinator.hass)

    dev_reg = dr.async_get(coordinator.hass)

    plant1 = await coordinator.async_add_plant(gs.id, "StrainA", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "StrainB", row=2, col=2)

    # Add dummy notification states
    coordinator._notifications_sent[plant1.plant_id] = ["alert1"]
    coordinator._notifications_sent[plant2.plant_id] = ["alert2"]
    coordinator._notifications_enabled[gs.id] = True

    # Mock async_commit and async_set_updated_data
    with (
        patch.object(coordinator, "async_commit", new_callable=AsyncMock),
        patch.object(coordinator, "async_set_updated_data", MagicMock()),
    ):
        # Call async_remove_growspace
        await coordinator.async_remove_growspace(gs.id)

        # Data update methods called
        coordinator.async_commit.assert_awaited_once()

    # Assertions: growspace removed
    assert gs.id not in coordinator.growspaces
    # Plants removed
    assert plant1.plant_id not in coordinator.plants
    assert plant2.plant_id not in coordinator.plants
    # Notifications cleared
    assert plant1.plant_id not in coordinator._notifications_sent
    assert plant2.plant_id not in coordinator._notifications_sent
    assert gs.id not in coordinator._notifications_enabled

    # Verify device removed
    assert dev_reg.async_get_device(identifiers={(DOMAIN, gs.id)}) is None


@pytest.mark.asyncio
async def test_async_update_growspace(coordinator: GrowspaceCoordinator) -> None:
    """Test updating the properties of a growspace.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: create a growspace
    gs = await coordinator.async_add_growspace("Old Name", 2, 2)

    # Mock async_commit and async_set_updated_data
    with (
        patch.object(coordinator, "async_commit", new_callable=AsyncMock),
        patch.object(coordinator, "async_set_updated_data", MagicMock()),
    ):
        # Update name, rows, plants_per_row, notification_target
        await coordinator.async_update_growspace(
            growspace_id=gs.id,
            name="New Name",
            rows=3,
            plants_per_row=4,
            notification_target="notify@example.com",
        )

        # Ensure async_commit and async_set_updated_data were called
        coordinator.async_commit.assert_awaited_once()

    updated_gs = coordinator.growspaces[gs.id]

    # Assertions
    assert updated_gs.name == "New Name"
    assert updated_gs.rows == 3
    assert updated_gs.plants_per_row == 4
    assert updated_gs.notification_target == "notify@example.com"


@pytest.mark.asyncio
async def test_async_update_growspace_no_changes(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test that updating a growspace with no changes does not trigger a save.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: create a growspace
    gs = await coordinator.async_add_growspace(
        "Same Name", 2, 2, notification_target=""
    )

    # Mock async_commit and async_set_updated_data
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    # Call update with the same values
    await coordinator.async_update_growspace(
        growspace_id=gs.id,
        name="Same Name",
        rows=2,
        plants_per_row=2,
        notification_target="",  # matches existing exactly
    )

    # async_commit and async_set_updated_data should NOT be called
    coordinator.async_commit.assert_not_called()
    coordinator.async_set_updated_data.assert_not_called()


@pytest.mark.asyncio
async def test_async_update_growspace_invalid_id(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test that updating a growspace with an invalid ID raises a ValueError.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    with pytest.raises(GrowspaceNotFoundError, match="Growspace invalid_id not found"):
        await coordinator.async_update_growspace("invalid_id", name="Test")


@pytest.mark.asyncio
async def test_validate_plants_after_growspace_resize_logs_warnings(
    coordinator: GrowspaceCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that resizing a growspace logs warnings for out-of-bounds plants.

    Args:
        coordinator: The mock GrowspaceCoordinator.
        caplog: The pytest log capture fixture.
    """
    # Setup: create growspace 2x2
    gs = await coordinator.async_add_growspace("Resize GS", 2, 2)
    # Add a plant outside the new resized bounds
    plant = await coordinator.async_add_plant(gs.id, "StrainX", row=3, col=1)

    # Set log level synchronously
    caplog.set_level("WARNING")

    # Resize growspace to smaller grid
    await coordinator._validate_plants_after_growspace_resize(
        gs.id, new_rows=2, new_plants_per_row=2
    )

    # Check that warnings were logged about invalid plant
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any(f"Plant {plant.plant_id}" in w for w in warnings)
    assert any("outside new grid" in w for w in warnings)


@pytest.mark.asyncio
async def test_is_notifications_enabled(coordinator: GrowspaceCoordinator) -> None:
    """Test the `is_notifications_enabled` method.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Create a growspace
    gs = await coordinator.async_add_growspace("Notify GS", 2, 2)

    # By default, notifications should be enabled
    assert coordinator.is_notifications_enabled(gs.id) is True

    # Disable notifications manually
    coordinator._notifications_enabled[gs.id] = False
    assert coordinator.is_notifications_enabled(gs.id) is False

    # If growspace ID is unknown, it should default to True
    assert coordinator.is_notifications_enabled("nonexistent") is True


@pytest.mark.asyncio
async def test_set_notifications_enabled(coordinator: GrowspaceCoordinator) -> None:
    """Test enabling and disabling notifications for a growspace.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Create a growspace
    gs = await coordinator.async_add_growspace("Notify GS", 2, 2)

    # Mock async_commit and async_set_updated_data
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()

    # Initialize self.data so set_notifications_enabled doesn't fail
    coordinator.update_data_property()

    # Disable notifications
    await coordinator.set_notifications_enabled(gs.id, False)
    assert coordinator.is_notifications_enabled(gs.id) is False
    coordinator.async_commit.assert_awaited_once()

    # Enable notifications
    coordinator.async_commit.reset_mock()
    coordinator.async_set_updated_data.reset_mock()
    await coordinator.set_notifications_enabled(gs.id, True)
    assert coordinator.is_notifications_enabled(gs.id) is True
    coordinator.async_commit.assert_awaited_once()

    # Non-existent growspace
    coordinator.async_commit.reset_mock()
    coordinator.async_set_updated_data.reset_mock()
    await coordinator.set_notifications_enabled("nonexistent", True)
    coordinator.async_commit.assert_not_awaited()
    coordinator.async_set_updated_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_clone_creation(coordinator: GrowspaceCoordinator) -> None:
    """Test the logic for creating a clone plant.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Setup: create a mother plant
    mother = await coordinator.async_add_mother_plant("PhenoA", "StrainX", 1, 1)
    # Force the stage to 'mother' so auto-find works
    mother.stage = PlantStage.MOTHER
    coordinator.update_data_property()

    # Mock async_commit and async_set_updated_data
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.update_data_property()  # ensure self.data is initialized

    clone_id = "clone123"

    # Test clone creation using explicit source_mother
    returned_id = await coordinator.lifecycle_manager.handle_clone_creation(
        plant_id=clone_id,
        growspace_id=mother.growspace_id,
        strain="StrainX",
        row=1,
        col=2,
        source_mother_id=mother.plant_id,
        phenotype="PhenoA",
    )

    assert returned_id == clone_id
    clone_plant = coordinator.plants[clone_id]
    assert clone_plant.stage == PlantStage.CLONE
    assert clone_plant.source_mother == mother.plant_id
    assert clone_plant.phenotype == mother.phenotype
    assert clone_plant.row == 1
    assert clone_plant.col == 2

    # Ensure async_commit and async_set_updated_data were called
    coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_transition_clone_to_veg(coordinator: GrowspaceCoordinator) -> None:
    """Test transitioning a clone plant to the vegetative stage.

    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Step 1: create a mother plant
    mother = await coordinator.async_add_mother_plant("PhenoA", "StrainX", 1, 1)

    # Step 2: create a clone using _handle_clone_creation
    clone_id = "clone123"
    fixed_time = "2025-11-03 16:44:40"

    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.update_data_property()

    with freeze_time(fixed_time):
        await coordinator.lifecycle_manager.handle_clone_creation(
            plant_id=clone_id,
            growspace_id=mother.growspace_id,
            strain="StrainX",
            row=1,
            col=2,
            source_mother_id=mother.plant_id,
            phenotype="PhenoA",
        )

        # Step 3: transition the clone to veg
        await coordinator.async_promote_clone(clone_id)

    clone = coordinator.plants[clone_id]
    assert clone.stage == PlantStage.VEG
    assert clone.growspace_id == "veg"
    assert clone.veg_start == "2025-11-03"

    coordinator.async_commit.assert_awaited()


@pytest.mark.asyncio
async def test_find_first_available_position(coordinator: GrowspaceCoordinator) -> None:
    """Test finding the first available position in a growspace.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Position GS", 2, 2)
    # Fill up (1,1) and (1,2)
    await coordinator.async_add_plant(gs.id, "Strain A", row=1, col=1)
    await coordinator.async_add_plant(gs.id, "Strain B", row=1, col=2)
    # First available should be (2,1)
    row, col = coordinator.validator.find_first_available_position(gs.id)
    assert (row, col) == (2, 1)
    # Fill (2,1)
    await coordinator.async_add_plant(gs.id, "Strain C", row=2, col=1)
    # First available should now be (2,2)
    row, col = coordinator.validator.find_first_available_position(gs.id)
    assert (row, col) == (2, 2)


@pytest.mark.asyncio
async def test_handle_position_update_force_position(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test _handle_position_update with force_position=True.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Force GS", 2, 2)
    await coordinator.async_add_plant(gs.id, "Strain A", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "Strain B", row=1, col=2)
    # This would normally fail because (1,1) is occupied
    # But with force_position=True, it should pass validation
    coordinator._handle_position_update(
        plant2.plant_id, plant2, True, {"row": 1, "col": 1}
    )
    # Test without force, should raise ValidationChangeError
    with pytest.raises(ValidationChangeError):
        coordinator._handle_position_update(
            plant2.plant_id, plant2, False, {"row": 1, "col": 1}
        )


@pytest.mark.asyncio
async def test_async_start_flowering(coordinator: GrowspaceCoordinator) -> None:
    """Test the async_start_flowering method.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Flower GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A")
    await coordinator.async_start_flowering(plant.plant_id)
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.stage == PlantStage.FLOWER
    assert updated_plant.flower_start == date.today().isoformat()
    assert updated_plant.updated_at == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_start_drying(coordinator: GrowspaceCoordinator) -> None:
    """Test the async_start_drying method.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Dry GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A")
    await coordinator.async_start_drying(plant.plant_id)
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.stage == PlantStage.DRY
    assert updated_plant.dry_start == date.today().isoformat()
    assert updated_plant.updated_at == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_start_curing(coordinator: GrowspaceCoordinator) -> None:
    """Test the async_start_curing method.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Cure GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A")
    await coordinator.async_start_curing(plant.plant_id)
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.stage == PlantStage.CURE
    assert updated_plant.cure_start == date.today().isoformat()
    assert updated_plant.updated_at == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_harvest(coordinator: GrowspaceCoordinator) -> None:
    """Test the async_harvest method.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Harvest GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A")
    await coordinator.async_harvest(plant.plant_id)
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.stage == PlantStage.DRY
    assert updated_plant.dry_start == date.today().isoformat()
    assert updated_plant.updated_at == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_start_flowering_no_plant(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_start_flowering with a non-existent plant.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    with pytest.raises(PlantNotFoundError):
        await coordinator.async_start_flowering("non-existent-plant")


@pytest.mark.asyncio
async def test_async_start_drying_no_plant(coordinator: GrowspaceCoordinator) -> None:
    """Test async_start_drying with a non-existent plant.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    with pytest.raises(PlantNotFoundError):
        await coordinator.async_start_drying("non-existent-plant")


@pytest.mark.asyncio
async def test_async_start_curing_no_plant(coordinator: GrowspaceCoordinator) -> None:
    """Test async_start_curing with a non-existent plant.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    with pytest.raises(PlantNotFoundError):
        await coordinator.async_start_curing("non-existent-plant")


@pytest.mark.asyncio
async def test_async_harvest_no_plant(coordinator: GrowspaceCoordinator) -> None:
    """Test async_harvest with a non-existent plant.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    with pytest.raises(PlantNotFoundError):
        await coordinator.async_harvest("non-existent-plant")


@pytest.mark.asyncio
async def test_async_harvest_plant_explicit_target(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test harvesting a plant to an explicit target growspace.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs1 = await coordinator.async_add_growspace("Source GS")
    gs2 = await coordinator.async_add_growspace("Target GS")
    plant = await coordinator.async_add_plant(gs1.id, "Strain A")
    await coordinator.async_harvest_plant(
        plant.plant_id, gs2.id, gs2.name, date.today().isoformat()
    )
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.growspace_id == gs2.id


@pytest.mark.asyncio
async def test_async_harvest_plant_auto_flow_to_dry(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test harvesting a plant with auto-flow to the dry growspace.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await mock_coordinator.async_add_growspace("Flower GS")
    plant = await mock_coordinator.async_add_plant(
        gs.id, "Strain A", stage=PlantStage.FLOWER, flower_start=date(2025, 1, 1)
    )
    await mock_coordinator.async_harvest_plant(plant.plant_id, None, None, None)
    updated_plant = mock_coordinator.get_plant(plant.plant_id)
    assert updated_plant.growspace_id == "dry"
    assert updated_plant.stage == PlantStage.DRY
    assert updated_plant.dry_start == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_harvest_plant_auto_flow_to_cure(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test harvesting a plant with auto-flow to the cure growspace.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    # Manually create the 'dry' growspace as a special growspace
    coordinator.growspaces["dry"] = Growspace(
        id="dry", name="Dry GS", rows=3, plants_per_row=3
    )
    plant = await coordinator.async_add_plant(
        "dry", "Strain A", stage=PlantStage.DRY, dry_start=date(2025, 1, 1)
    )
    await coordinator.async_harvest_plant(plant.plant_id, None, None, None)
    updated_plant = coordinator.get_plant(plant.plant_id)
    assert updated_plant.growspace_id == "cure"
    assert updated_plant.stage == PlantStage.CURE
    assert updated_plant.cure_start == date.today().isoformat()


@pytest.mark.asyncio
async def test_async_switch_plants_different_growspaces(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test switching plants in different growspaces raises ValueError.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs1 = await coordinator.async_add_growspace("GS1")
    gs2 = await coordinator.async_add_growspace("GS2")
    plant1 = await coordinator.async_add_plant(gs1.id, "Strain A")
    plant2 = await coordinator.async_add_plant(gs2.id, "Strain B")
    with pytest.raises(ValidationChangeError):
        await coordinator.async_switch_plants(plant1.plant_id, plant2.plant_id)


@pytest.mark.asyncio
async def test_async_check_timed_notifications(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test the _async_check_timed_notifications method.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs = await coordinator.async_add_growspace("Notify GS", notification_target="test")
    await coordinator.async_add_plant(
        gs.id, "Strain A", veg_start=now().date() - timedelta(days=5)
    )
    coordinator.options = {
        "timed_notifications": [
            {
                "trigger_type": "veg",
                "day": 5,
                "message": "Test message",
                "growspace_ids": [gs.id],
                "id": "test-notif",
            }
        ]
    }
    # Correctly mock the service call on the hass object
    coordinator.hass.services = MagicMock()
    coordinator.hass.services.async_call = AsyncMock()
    await coordinator.notification_manager.async_check_timed_notifications()
    coordinator.hass.services.async_call.assert_called_once_with(
        "notify",
        "test",
        {
            "message": "Test message",
            "title": "Notify GS - Veg Day 5",
        },
        blocking=False,
    )


async def test_async_update_air_exchange_recommendations(hass: HomeAssistant) -> None:
    """Test the air exchange recommendation logic.
    Args:
        hass: The Home Assistant instance.
    """
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Stress GS")

    # Define valid, slugified entity IDs for the test
    # This matches what HA would create from the name "Stress GS"
    stress_sensor_entity_id = "binary_sensor.stress_gs_plants_under_stress"
    vpd_sensor_entity_id = "sensor.stress_gs_vpd"

    gs.environment_config = EnvironmentConfig(vpd_sensor=vpd_sensor_entity_id)
    coordinator.data = {"bayesian_sensors_reason": {gs.id: {"target_vpd": 1.2}}}

    # Mock the entity registry to return the correct entity ID
    entity_registry = er.async_get(hass)
    stress_sensor_unique_id = f"{DOMAIN}_{gs.id}_stress"

    with patch.object(
        entity_registry,
        "async_get_entity_id",
        return_value=stress_sensor_entity_id,
    ) as mock_get_id:
        # Mock states using the *valid* entity IDs
        hass.states.async_set(stress_sensor_entity_id, "on")
        hass.states.async_set(
            "weather.test", "sunny", {"temperature": 20, "humidity": 50}
        )
        hass.states.async_set("sensor.lung_room_temp", "22")
        hass.states.async_set("sensor.lung_room_humidity", "55")
        hass.states.async_set(vpd_sensor_entity_id, "1.5")

        coordinator.options = {
            "global_settings": {
                "weather_entity": "weather.test",
                "lung_room_temp_sensor": "sensor.lung_room_temp",
                "lung_room_humidity_sensor": "sensor.lung_room_humidity",
            }
        }

        await (
            coordinator.environment_analyzer.async_update_air_exchange_recommendations()
        )

        # Verify the registry was queried correctly
        mock_get_id.assert_called_with("binary_sensor", DOMAIN, stress_sensor_unique_id)

    assert (
        coordinator.data["air_exchange_recommendations"][gs.id] == "Ventilate Lung Room"
    )
    coordinator.options = {
        "global_settings": {
            "weather_entity": "weather.test",
            "lung_room_temp_sensor": "sensor.lung_room_temp",
            "lung_room_humidity_sensor": "sensor.lung_room_humidity",
        }
    }
    await coordinator.environment_analyzer.async_update_air_exchange_recommendations()
    assert coordinator.data["air_exchange_recommendations"][gs.id] == "Idle"


@pytest.mark.asyncio
async def test_get_growspace_plants(coordinator: GrowspaceCoordinator) -> None:
    """Test retrieving plants from a specific growspace.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    gs1 = await coordinator.async_add_growspace("GS1")
    gs2 = await coordinator.async_add_growspace("GS2")
    plant1 = await coordinator.async_add_plant(gs1.id, "Strain A")
    plant2 = await coordinator.async_add_plant(gs1.id, "Strain B")
    plant3 = await coordinator.async_add_plant(gs2.id, "Strain C")
    gs1_plants = coordinator.get_growspace_plants(gs1.id)
    assert len(gs1_plants) == 2
    assert plant1 in gs1_plants
    assert plant2 in gs1_plants
    gs2_plants = coordinator.get_growspace_plants(gs2.id)
    assert len(gs2_plants) == 1
    assert plant3 in gs2_plants


def test_calculate_days_in_stage(coordinator: GrowspaceCoordinator) -> None:
    """Test calculating the number of days a plant has been in a stage.
    Args:
        coordinator: The mock GrowspaceCoordinator.
    """
    plant = Plant(
        plant_id="p1",
        strain="Test",
        growspace_id="gs1",
        veg_start=(now().date() - timedelta(days=10)).isoformat(),
    )
    days = coordinator.serializer.calculate_days_in_stage(plant, PlantStage.VEG)
    assert days == 10


@pytest.fixture
def coordinator(hass: HomeAssistant):
    """Provide a fresh `GrowspaceCoordinator` instance for each test."""
    coordinator = create_test_coordinator(hass, data={})
    setattr(coordinator, "async_set_updated_data", MagicMock())
    return coordinator


@pytest.mark.asyncio
async def test_init_with_invalid_growspace_data(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test coordinator initialization with invalid growspace data."""
    caplog.set_level("ERROR")

    invalid_data = {
        "growspaces": {"gs1": "not_a_growspace_object"},
    }

    create_test_coordinator(hass, data=invalid_data)

    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("Failed to load growspace gs1" in e for e in errors)


@pytest.mark.asyncio
async def test_init_with_invalid_plant_data(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test coordinator initialization with invalid plant data."""
    caplog.set_level("ERROR")

    invalid_data = {
        "growspaces": {
            "gs1": {"id": "gs1", "name": "Test GS", "rows": 1, "plants_per_row": 1}
        },
        "plants": {"p1": "not_a_plant_object"},
    }

    create_test_coordinator(hass, data=invalid_data)

    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("Failed to load plant p1" in e for e in errors)


@pytest.mark.asyncio
async def test_init_with_plant_object(hass: HomeAssistant) -> None:
    """Test coordinator initialization with a Plant object instead of a dict."""

    plant_obj = Plant(plant_id="p1", strain="Test Strain", growspace_id="gs1")
    data = {"plants": {"p1": plant_obj}}

    coordinator = create_test_coordinator(hass, data=data)

    assert "p1" in coordinator.plants
    assert coordinator.plants["p1"] == plant_obj


@pytest.mark.asyncio
async def test_migrate_legacy_growspaces_error_handling(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test error handling in _migrate_legacy_growspaces."""
    caplog.set_level("DEBUG")
    coordinator = create_test_coordinator(hass, data={})

    with patch.object(
        coordinator.migration_manager,
        "_migrate_special_alias_if_needed",
        side_effect=ValueError("Test error"),
    ):
        coordinator.migration_manager.migrate_legacy_growspaces()

    assert any(
        "Special growspace migration skipped" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_migrate_special_alias_if_needed_no_op(hass: HomeAssistant) -> None:
    """Test that no migration happens if alias and canonical IDs are the same."""
    coordinator = create_test_coordinator(hass, data={})
    with (
        patch.object(
            coordinator.migration_manager, "_create_canonical_from_alias"
        ) as mock_create,
        patch.object(
            coordinator.migration_manager, "_consolidate_alias_into_canonical"
        ) as mock_consolidate,
    ):
        coordinator.migration_manager._migrate_special_alias_if_needed(
            "test", "test", "Test"
        )
        mock_create.assert_not_called()
        mock_consolidate.assert_not_called()


@pytest.mark.asyncio
async def test_migrate_special_alias_if_needed_create_canonical(
    hass: HomeAssistant,
) -> None:
    """Test that a new canonical growspace is created from an alias."""
    coordinator = create_test_coordinator(hass, data={})
    coordinator.growspaces["alias"] = Growspace(id="alias", name="Alias")
    with (
        patch.object(
            coordinator.migration_manager, "_create_canonical_from_alias"
        ) as mock_create,
        patch.object(
            coordinator.migration_manager, "_consolidate_alias_into_canonical"
        ) as mock_consolidate,
    ):
        coordinator.migration_manager._migrate_special_alias_if_needed(
            "alias", "canonical", "Canonical"
        )
        mock_create.assert_called_once_with("alias", "canonical", "Canonical")
        mock_consolidate.assert_not_called()


@pytest.mark.asyncio
async def test_migrate_special_alias_if_needed_consolidate(hass: HomeAssistant) -> None:
    """Test that an existing alias is consolidated into a canonical growspace."""
    coordinator = create_test_coordinator(hass, data={})
    coordinator.growspaces["alias"] = Growspace(id="alias", name="Alias")
    coordinator.growspaces["canonical"] = Growspace(id="canonical", name="Canonical")
    with (
        patch.object(
            coordinator.migration_manager, "_create_canonical_from_alias"
        ) as mock_create,
        patch.object(
            coordinator.migration_manager, "_consolidate_alias_into_canonical"
        ) as mock_consolidate,
    ):
        coordinator.migration_manager._migrate_special_alias_if_needed(
            "alias", "canonical", "Canonical"
        )
        mock_create.assert_not_called()
        mock_consolidate.assert_called_once_with("alias", "canonical")


@pytest.mark.asyncio
async def test_get_plant_stage_special_growspaces(hass: HomeAssistant) -> None:
    """Test _get_plant_stage for special growspaces."""

    plant_mother = Plant(plant_id="p1", strain="Test", growspace_id="mother")
    assert calculate_plant_stage(plant_mother) == "mother"

    plant_clone = Plant(plant_id="p2", strain="Test", growspace_id="clone")
    assert calculate_plant_stage(plant_clone) == "clone"

    plant_cure = Plant(plant_id="p3", strain="Test", growspace_id="cure")
    assert calculate_plant_stage(plant_cure) == "cure"


@pytest.mark.asyncio
async def test_get_plant_stage_seedling(hass: HomeAssistant) -> None:
    """Test _get_plant_stage for the seedling stage."""

    plant = Plant(
        plant_id="p1",
        strain="Test",
        growspace_id="gs1",
        seedling_start=date.today().isoformat(),
    )
    assert calculate_plant_stage(plant) == "seedling"


@pytest.mark.asyncio
async def test_get_plant_stage_fallback(hass: HomeAssistant) -> None:
    """Test _get_plant_stage fallback to the explicitly set stage."""

    plant = Plant(plant_id="p1", strain="Test", growspace_id="gs1", stage="veg")
    assert calculate_plant_stage(plant) == "veg"


@pytest.mark.asyncio
async def test_canonical_special_not_found(hass: HomeAssistant) -> None:
    """Test _canonical_special when the growspace is not found."""
    coordinator = create_test_coordinator(hass, data={})
    canonical_id, canonical_name = coordinator._canonical_special("nonexistent")
    assert canonical_id == "nonexistent"
    assert canonical_name == "nonexistent"


@pytest.mark.asyncio
async def test_async_load_error_handling(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test error handling in async_load."""

    caplog.set_level("ERROR")
    coordinator = create_test_coordinator(hass, data={})
    invalid_data = {
        "plants": {"p1": "not_a_plant_object"},
        "growspaces": {"gs1": "not_a_growspace_object"},
    }
    setattr(
        coordinator.storage_manager.store,
        "async_load",
        AsyncMock(return_value=invalid_data),
    )

    await coordinator.async_load()

    errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
    assert any("Error loading plants" in e for e in errors)
    assert any("Error loading growspaces" in e for e in errors)


@pytest.mark.asyncio
async def test_async_load_with_options(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test async_load with options."""

    caplog.set_level("DEBUG")
    options = {"gs1": {"vpd_sensor": "sensor.vpd"}}
    coordinator = create_test_coordinator(hass, data={}, options=options)
    data = {
        "growspaces": {
            "gs1": {
                "id": "gs1",
                "name": "Test GS",
                "rows": 1,
                "plants_per_row": 1,
            }
        }
    }
    setattr(
        coordinator.storage_manager.store,
        "async_load",
        AsyncMock(return_value=data),
    )

    await coordinator.async_load()

    assert "APPLYING OPTIONS TO GROWSPACES" in caplog.text
    assert "SUCCESS: Applied env_config to 'Test GS'" in caplog.text


@pytest.mark.asyncio
async def test_async_load_ensures_notifications_enabled(hass: HomeAssistant) -> None:
    """Test that async_load ensures all growspaces are in the notifications_enabled dict."""

    coordinator = create_test_coordinator(hass, data={})
    data = {
        "growspaces": {
            "gs1": {
                "id": "gs1",
                "name": "Test GS",
                "rows": 1,
                "plants_per_row": 1,
            }
        },
        "notifications_enabled": {},
    }
    setattr(
        coordinator.storage_manager.store,
        "async_load",
        AsyncMock(return_value=data),
    )

    await coordinator.async_load()

    assert "gs1" in coordinator._notifications_enabled
    assert coordinator._notifications_enabled["gs1"] is True


@pytest.mark.asyncio
async def test_ensure_special_growspace_updates_name(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that _ensure_special_growspace updates the name of an existing growspace."""

    caplog.set_level("INFO")
    coordinator = create_test_coordinator(hass, data={})
    coordinator.growspaces["dry"] = Growspace(
        id="dry", name="Old Dry Name", rows=1, plants_per_row=1
    )

    coordinator.ensure_special_growspace("dry", "Dry")

    assert coordinator.growspaces["dry"].name == "Dry"
    assert "Updated growspace name" in caplog.text


@pytest.mark.asyncio
async def test_cleanup_legacy_aliases(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that _cleanup_legacy_aliases removes legacy aliases and migrates plants."""

    caplog.set_level("INFO")
    coordinator = create_test_coordinator(hass, data={})

    # Add a canonical growspace and a legacy alias with a plant
    coordinator.growspaces["dry"] = Growspace(
        id="dry", name="Dry", rows=1, plants_per_row=1
    )
    coordinator.growspaces["drying"] = Growspace(
        id="drying", name="Drying", rows=1, plants_per_row=1
    )
    plant = Plant(plant_id="p1", strain="Test", growspace_id="drying")
    coordinator.plants[plant.plant_id] = plant

    coordinator.migration_manager.cleanup_legacy_aliases("dry")

    assert "drying" not in coordinator.growspaces
    assert coordinator.plants["p1"].growspace_id == "dry"
    assert "Removed legacy growspace: drying" in caplog.text


@pytest.mark.asyncio
async def test_async_move_plant(hass: HomeAssistant) -> None:
    """Test the async_move_plant method."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS", rows=2, plants_per_row=2)
    plant = await coordinator.async_add_plant(gs.id, "Test Plant", row=1, col=1)

    await coordinator.async_move_plant(plant.plant_id, 2, 2)

    assert coordinator.plants[plant.plant_id].row == 2
    assert coordinator.plants[plant.plant_id].col == 2


@pytest.mark.asyncio
async def test_async_switch_plants_service(hass: HomeAssistant) -> None:
    """Test the async_switch_plants_service method."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS", rows=2, plants_per_row=2)
    plant1 = await coordinator.async_add_plant(gs.id, "Test Plant 1", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "Test Plant 2", row=2, col=2)

    await coordinator.switch_plants_service(plant1.plant_id, plant2.plant_id)

    assert coordinator.plants[plant1.plant_id].row == 2
    assert coordinator.plants[plant1.plant_id].col == 2
    assert coordinator.plants[plant2.plant_id].row == 1
    assert coordinator.plants[plant2.plant_id].col == 1


@pytest.mark.asyncio
async def test_async_transition_plant_stage_invalid_stage(hass: HomeAssistant) -> None:
    """Test that async_transition_plant_stage raises ValueError for an invalid stage."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS")
    plant = await coordinator.async_add_plant(gs.id, "Test Plant")

    with pytest.raises(ValidationChangeError, match="Invalid stage"):
        await coordinator.async_transition_plant_stage(
            plant.plant_id, "invalid_stage", None
        )


@pytest.mark.asyncio
async def test_handle_harvest_logic_explicit_target(hass: HomeAssistant) -> None:
    """Test _handle_harvest_logic with an explicit target."""

    coordinator = create_test_coordinator(hass, data={})
    plant = MagicMock()
    coordinator.growspaces["gs1"] = Growspace(id="gs1", name="gs1_name")

    with patch.object(
        coordinator.lifecycle_manager,
        "_harvest_to_explicit_target",
        new_callable=AsyncMock,
    ) as mock_harvest:
        mock_harvest.return_value = True
        result = await coordinator.lifecycle_manager.handle_harvest_logic(
            "p1", plant, "gs1", "gs1_name", "2025-01-01"
        )

        assert result is True
        mock_harvest.assert_called_once_with(
            "p1", plant, "gs1", "gs1_name", "2025-01-01"
        )


@pytest.mark.asyncio
async def test_handle_harvest_logic_auto_flow(hass: HomeAssistant) -> None:
    """Test _handle_harvest_logic with auto-flow."""

    coordinator = create_test_coordinator(hass, data={})
    plant = MagicMock()

    with patch.object(
        coordinator.lifecycle_manager, "_harvest_auto_flow", new_callable=AsyncMock
    ) as mock_auto_flow:
        mock_auto_flow.return_value = True
        result = await coordinator.lifecycle_manager.handle_harvest_logic(
            "p1", plant, None, "gs1_name", "2025-01-01"
        )

        assert result is True
        mock_auto_flow.assert_called_once_with("p1", plant, "gs1_name", "2025-01-01")


@pytest.mark.asyncio
async def test_harvest_auto_flow_with_target_name_hint(hass: HomeAssistant) -> None:
    """Test _harvest_auto_flow with a target name hint."""

    coordinator = create_test_coordinator(hass, data={})
    plant = MagicMock()

    with patch.object(
        coordinator.lifecycle_manager, "move_to_dry_growspace", new_callable=AsyncMock
    ) as mock_move:
        mock_move.return_value = True
        result = await coordinator.lifecycle_manager._harvest_auto_flow(
            "p1", plant, "dry something", "2025-01-01"
        )

        assert result is True
        mock_move.assert_called_once_with("p1", plant, "2025-01-01")


@pytest.mark.asyncio
async def test_harvest_auto_flow_mother_to_clone(hass: HomeAssistant) -> None:
    """Test _harvest_auto_flow for a mother plant."""

    coordinator = create_test_coordinator(hass, data={})
    plant = MagicMock()
    plant.stage = "mother"

    with patch.object(
        coordinator.lifecycle_manager, "move_to_clone_growspace", new_callable=AsyncMock
    ) as mock_move:
        mock_move.return_value = True
        result = await coordinator.lifecycle_manager._harvest_auto_flow(
            "p1", plant, None, "2025-01-01"
        )

        assert result is True
        mock_move.assert_called_once_with("p1", plant, "2025-01-01")


@pytest.mark.asyncio
async def test_harvest_auto_flow_fallback_to_dry(hass: HomeAssistant) -> None:
    """Test _harvest_auto_flow fallback to dry."""

    coordinator = create_test_coordinator(hass, data={})
    plant = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.coordinator.calculate_plant_stage",
            return_value="some_other_stage",
        ),
        patch.object(
            coordinator.lifecycle_manager,
            "move_to_dry_growspace",
            new_callable=AsyncMock,
        ) as mock_move,
    ):
        mock_move.return_value = True

        result = await coordinator.lifecycle_manager._harvest_auto_flow(
            "p1", plant, None, "2025-01-01"
        )

        assert result is True
        mock_move.assert_called_once_with("p1", plant, "2025-01-01")


@pytest.mark.asyncio
async def test_harvest_to_explicit_target_no_position(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test _harvest_to_explicit_target when no position is available."""

    caplog.set_level("WARNING")
    coordinator = create_test_coordinator(hass, data={})
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="strain1",
        phenotype="pheno1",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    setattr(
        coordinator.validator,
        "find_first_available_position",
        MagicMock(side_effect=ValueError("No position")),
    )
    coordinator.growspaces = {"gs1": MagicMock()}
    coordinator.plants["p1"] = plant  # Ensure plant exists

    with patch.object(
        coordinator.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
    ):
        await coordinator.lifecycle_manager._harvest_to_explicit_target(
            "p1", plant, "gs1", "gs1_name", "2025-01-01"
        )

    assert "Failed to find position" in caplog.text


@pytest.mark.asyncio
async def test_harvest_to_explicit_target_cure(hass: HomeAssistant) -> None:
    """Test _harvest_to_explicit_target to cure growspace."""

    coordinator = create_test_coordinator(hass, data={})
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="strain1",
        phenotype="pheno1",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    setattr(
        coordinator.validator,
        "find_first_available_position",
        MagicMock(return_value=(1, 1)),
    )
    coordinator.growspaces = {"cure": MagicMock()}

    coordinator.plants["p1"] = plant  # Ensure plant exists in coordinator

    with patch.object(
        coordinator.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.lifecycle_manager._harvest_to_explicit_target(
            "p1", plant, "cure", "cure", "2025-01-01"
        )

        mock_update.assert_called_with(
            "p1",
            growspace_id="cure",
            row=1,
            col=1,
            stage="cure",
            cure_start="2025-01-01",
        )


@pytest.mark.asyncio
async def test_harvest_to_explicit_target_clone(hass: HomeAssistant) -> None:
    """Test _harvest_to_explicit_target to clone growspace."""

    coordinator = create_test_coordinator(hass, data={})
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="strain1",
        phenotype="pheno1",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    setattr(
        coordinator.validator,
        "find_first_available_position",
        MagicMock(return_value=(1, 1)),
    )
    coordinator.growspaces = {"clone": MagicMock()}

    coordinator.plants["p1"] = plant  # Ensure plant exists in coordinator

    with patch.object(
        coordinator.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.lifecycle_manager._harvest_to_explicit_target(
            "p1", plant, "clone", "clone", "2025-01-01"
        )

        mock_update.assert_called_with(
            "p1",
            growspace_id="clone",
            row=1,
            col=1,
            stage="clone",
            clone_start="2025-01-01",
        )


@pytest.mark.asyncio
async def test_harvest_to_explicit_target_mother(hass: HomeAssistant) -> None:
    """Test _harvest_to_explicit_target to mother growspace."""

    coordinator = create_test_coordinator(hass, data={})
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="strain1",
        phenotype="pheno1",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    setattr(
        coordinator.validator,
        "find_first_available_position",
        MagicMock(return_value=(1, 1)),
    )
    coordinator.growspaces = {"mother": MagicMock()}

    coordinator.plants["p1"] = plant  # Ensure plant exists in coordinator

    with patch.object(
        coordinator.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.lifecycle_manager._harvest_to_explicit_target(
            "p1", plant, "mother", "mother", "2025-01-01"
        )

        mock_update.assert_called_with(
            "p1",
            growspace_id="mother",
            row=1,
            col=1,
            stage=PlantStage.MOTHER,
            mother_start="2025-01-01",
        )


@pytest.mark.asyncio
async def test_move_to_clone_growspace_no_position(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test _move_to_clone_growspace when no position is available."""
    caplog.set_level("WARNING")
    coordinator = create_test_coordinator(hass, data={})
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="strain1",
        phenotype="pheno1",
        row=1,
        col=1,
        stage="veg",
        created_at="2025-01-01",
        updated_at="2025-01-01",
    )
    setattr(coordinator, "ensure_special_growspace", MagicMock(return_value="clone"))
    setattr(
        coordinator.validator,
        "find_first_available_position",
        MagicMock(side_effect=ValueError("No position")),
    )
    coordinator.growspaces = {"clone": MagicMock()}
    coordinator.plants["p1"] = plant  # Ensure plant exists in coordinator

    with patch.object(
        coordinator.lifecycle_manager, "async_update_plant", new_callable=AsyncMock
    ):
        await coordinator.lifecycle_manager.move_to_clone_growspace(
            "p1", plant, "2025-01-01"
        )

    assert "Failed to find position in clone growspace" in caplog.text


@pytest.mark.asyncio
async def test_async_update_air_exchange_recommendations_no_stress_sensor(
    hass: HomeAssistant,
) -> None:
    """Test _async_update_air_exchange_recommendations when stress sensor is not found."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS")
    coordinator.data = {}

    with patch(
        "homeassistant.helpers.entity_registry.EntityRegistry.async_get_entity_id",
        return_value=None,
    ):
        await (
            coordinator.environment_analyzer.async_update_air_exchange_recommendations()
        )

    assert coordinator.data["air_exchange_recommendations"][gs.id] == "Idle"


@pytest.mark.asyncio
async def test_async_update_air_exchange_recommendations_no_vpd(
    hass: HomeAssistant,
) -> None:
    """Test _async_update_air_exchange_recommendations when VPD is not available."""
    coordinator = create_test_coordinator(hass, data={})
    gs = await coordinator.async_add_growspace("Test GS")
    gs.environment_config = EnvironmentConfig(vpd_sensor="sensor.vpd")
    coordinator.data = {"bayesian_sensors_reason": {gs.id: {"target_vpd": None}}}

    with patch(
        "homeassistant.helpers.entity_registry.EntityRegistry.async_get_entity_id",
        return_value="binary_sensor.test_gs_plants_under_stress",
    ):
        hass.states.async_set("binary_sensor.test_gs_plants_under_stress", "on")
        await (
            coordinator.environment_analyzer.async_update_air_exchange_recommendations()
        )

    assert coordinator.data["air_exchange_recommendations"][gs.id] == "Idle"


@pytest.mark.asyncio
async def test_async_initialize_sub_coordinators(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test sub-coordinator initialization."""
    coordinator.growspaces = {}

    # 1. Add growspace with irrigation enabled
    gs1 = await coordinator.async_add_growspace("GS1")
    gs1.irrigation_strategy.enabled = True

    # 2. Add growspace with irrigation disabled
    gs2 = await coordinator.async_add_growspace("GS2")
    gs2.irrigation_strategy.enabled = False

    entry = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.coordinator.VWCIrrigationCoordinator"
        ) as mock_vwc,
        patch(
            "custom_components.growspace_manager.coordinator.IrrigationCoordinator"
        ) as mock_irrigation,
        patch(
            "custom_components.growspace_manager.coordinator.DehumidifierCoordinator"
        ) as mock_dehumidifier,
    ):
        mock_vwc.return_value.async_setup = AsyncMock()
        mock_irrigation.return_value.async_setup = AsyncMock()

        await coordinator.async_initialize_sub_coordinators(entry)

        # Verify GS1 getting VWC
        mock_vwc.assert_called_with(coordinator.hass, entry, gs1.id, coordinator)
        mock_vwc.return_value.async_setup.assert_called_once()
        assert coordinator.irrigation_coordinators[gs1.id] == mock_vwc.return_value

        # Verify GS2 getting Standard
        mock_irrigation.assert_called_with(coordinator.hass, entry, gs2.id, coordinator)
        mock_irrigation.return_value.async_setup.assert_called_once()
        assert (
            coordinator.irrigation_coordinators[gs2.id] == mock_irrigation.return_value
        )

        # Verify Dehumidifiers
        assert mock_dehumidifier.call_count == 2
        assert len(coordinator.dehumidifier_coordinators) == 2


# Tests merged from test_coordinator_coverage.py
@pytest.mark.asyncio
async def test_load_growspaces_legacy_migration(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test loading legacy growspace data without growspace_type."""
    raw_growspaces = {
        "dry": {"id": "dry", "name": "Dry Room", "rows": 3, "plants_per_row": 3},
        "cure": {"id": "cure", "name": "Curing", "rows": 3, "plants_per_row": 3},
        "mother": {"id": "mother", "name": "Mothers", "rows": 3, "plants_per_row": 3},
        "veg": {"id": "veg", "name": "Veg", "rows": 3, "plants_per_row": 3},
        "clone": {"id": "clone", "name": "Clones", "rows": 3, "plants_per_row": 3},
        "gs1": {"id": "gs1", "name": "Flower 1", "rows": 3, "plants_per_row": 3},
        "custom": {"id": "custom", "name": "Custom", "rows": 3, "plants_per_row": 3},
        "drying": {
            "id": "drying",
            "name": "Dry Alias",
            "rows": 3,
            "plants_per_row": 3,
        },  # alias check
    }

    mock_coordinator._load_growspaces(raw_growspaces)

    assert mock_coordinator.growspaces["dry"].growspace_type == GrowspaceType.DRY
    assert mock_coordinator.growspaces["cure"].growspace_type == GrowspaceType.CURE
    assert mock_coordinator.growspaces["mother"].growspace_type == GrowspaceType.MOTHER
    assert mock_coordinator.growspaces["veg"].growspace_type == GrowspaceType.VEG
    assert mock_coordinator.growspaces["clone"].growspace_type == GrowspaceType.CLONE
    assert mock_coordinator.growspaces["gs1"].growspace_type == GrowspaceType.FLOWER
    assert mock_coordinator.growspaces["custom"].growspace_type == GrowspaceType.FLOWER
    assert mock_coordinator.growspaces["drying"].growspace_type == GrowspaceType.DRY


@pytest.mark.asyncio
async def test_load_growspaces_invalid_data(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test loading invalid growspace data."""
    raw_growspaces = {
        "valid": {
            "id": "valid",
            "name": "Valid",
            "rows": 3,
            "plants_per_row": 3,
            "growspace_type": "flower",
        },
        "invalid": "this is not a dict",
    }

    with patch(
        "custom_components.growspace_manager.coordinator._LOGGER"
    ) as mock_logger:
        mock_coordinator._load_growspaces(raw_growspaces)

        assert "valid" in mock_coordinator.growspaces
        assert "invalid" not in mock_coordinator.growspaces
        # The exception handler calls logger.exception
        assert mock_logger.exception.call_count >= 1


@pytest.mark.asyncio
async def test_load_plants_invalid_data_logging(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test loading invalid plant data logs exception."""
    raw_plants = {"p1": "invalid_string_data"}
    with patch(
        "custom_components.growspace_manager.coordinator._LOGGER"
    ) as mock_logger:
        mock_coordinator._load_plants(raw_plants)
        assert mock_logger.exception.call_count == 1


@pytest.mark.asyncio
async def test_calculate_days_caps(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test calculate_days with end_date capping and various inputs."""
    today = date.today()
    start = today - timedelta(days=10)

    # 1. No end date
    assert mock_coordinator.calculate_days(start) == 10

    # 2. Future end date
    future = today + timedelta(days=5)
    assert mock_coordinator.calculate_days(start, future) == 10

    # 3. Past end date (should cap)
    past_end = today - timedelta(days=5)
    assert mock_coordinator.calculate_days(start, past_end) == 5

    # 4. Invalid start date
    assert mock_coordinator.calculate_days(None) == 0


@pytest.mark.asyncio
async def test_ensure_calculated_sensors_logic(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test _ensure_calculated_sensors patches missing VPD sensor."""
    gs = Growspace(
        id="gs_test",
        name="Test Room",
        growspace_type=GrowspaceType.FLOWER,
        environment_config=EnvironmentConfig(
            temperature_sensor="sensor.temp",
            humidity_sensor="sensor.humidity",
            vpd_sensor=None,  # Missing
        ),
    )
    mock_coordinator.growspaces["gs_test"] = gs

    mock_coordinator._ensure_calculated_sensors()

    assert gs.environment_config.vpd_sensor == "sensor.test_room_calculated_vpd"


@pytest.mark.asyncio
async def test_async_update_irrigation_config(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_update_irrigation_config."""
    # Setup growspace with initial config
    gs = Growspace(id="gs1", name="GS1", growspace_type=GrowspaceType.FLOWER)
    gs.irrigation_config.irrigation_pump_entity = "switch.pump1"
    mock_coordinator.growspaces["gs1"] = gs

    # 1. Update with read-only fields (should be ignored) and valid fields
    user_input = {
        "irrigation_pump_entity": "switch.pump2",
        "current_irrigation_times": "ignored",
        "growspace_id_read_only": "ignored",
    }

    await mock_coordinator.async_update_irrigation_config("gs1", user_input)

    assert gs.irrigation_config.irrigation_pump_entity == "switch.pump2"

    # 2. Calling with non-existent GS raises GrowspaceNotFoundError
    with pytest.raises(GrowspaceNotFoundError):
        await mock_coordinator.async_update_irrigation_config("missing", {})


@pytest.mark.asyncio
async def test_async_remove_growspace_device_removal_error(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_remove_growspace handles device removal errors."""
    gs = await mock_coordinator.async_add_growspace("Test GS")

    # Mock device registry
    mock_dr = MagicMock()
    # Raise exception when getting device
    mock_dr.async_get_device.side_effect = Exception("Registry Error")

    with (
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_dr),
        patch("custom_components.growspace_manager.coordinator._LOGGER") as mock_logger,
    ):
        await mock_coordinator.async_remove_growspace(gs.id)

        # Should have logged the exception but not crashed
        assert mock_logger.exception.call_count >= 1
        assert gs.id not in mock_coordinator.growspaces


@pytest.mark.asyncio
async def test_clone_creation_retrieval_failure(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_take_clones handling when clone retrieval fails from plants dict."""
    mother = await mock_coordinator.async_add_mother_plant("Pheno", "Strain", 1, 1)

    with (
        patch.object(
            mock_coordinator.lifecycle_manager,
            "handle_clone_creation",
            return_value="ghost_clone_id",
        ),
        patch("custom_components.growspace_manager.coordinator._LOGGER") as mock_logger,
    ):
        # Clone not in plants dict
        clones = await mock_coordinator.async_take_clones(mother.plant_id, 1)

        assert len(clones) == 0
        assert mock_logger.error.call_count >= 1


@pytest.mark.asyncio
async def test_async_promote_clone_error_checks(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_promote_clone error conditions."""
    # 1. Promote non-existent plant
    with pytest.raises(PlantNotFoundError):
        await mock_coordinator.async_promote_clone("missing")

    # 2. Promote plant in wrong stage
    gs = await mock_coordinator.async_add_growspace("Veg")
    plant = await mock_coordinator.async_add_plant(
        gs.id, "Strain", stage=PlantStage.VEG
    )
    with pytest.raises(ValidationChangeError, match="not in clone stage"):
        await mock_coordinator.async_promote_clone(plant.plant_id)

    # 3. Promote to non-existent target growspace
    plant.stage = PlantStage.CLONE
    with pytest.raises(
        GrowspaceNotFoundError, match="Target growspace missing_gs does not exist"
    ):
        await mock_coordinator.async_promote_clone(
            plant.plant_id, target_growspace_id="missing_gs"
        )


@pytest.mark.asyncio
async def test_guess_overview_entity_id(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test _guess_overview_entity_id fallback logic."""
    # 1. Registry lookup (mocked) returning ID
    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.return_value = "sensor.found_id"

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        eid = mock_coordinator._guess_overview_entity_id("some_gs")
        assert eid == "sensor.found_id"

    # 2. Registry returns None, Special growspace ID
    mock_registry.async_get_entity_id.return_value = None
    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        eid = mock_coordinator._guess_overview_entity_id(
            "mother"
        )  # 'mother' is special
        # Should fallback to canonical ID if not found in registry
        assert eid == "sensor.mother"

    # 3. Standard fallback with slugify
    # Use a growspace that is in the coordinator map
    gs = Growspace(id="complex_id", name="My Complex Name")
    mock_coordinator.growspaces["complex_id"] = gs

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        eid = mock_coordinator._guess_overview_entity_id("complex_id")
        assert eid == "sensor.my_complex_name"


@pytest.mark.asyncio
async def test_initialization_failure_exception_group(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_initialize_sub_coordinators handling ExceptionGroup from TaskGroup."""
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces["gs1"] = gs

    with (
        patch.object(
            mock_coordinator,
            "_setup_growspace_sub_coordinators",
            side_effect=ValueError("Init Fail"),
        ),
        patch("custom_components.growspace_manager.coordinator._LOGGER") as mock_logger,
    ):
        await mock_coordinator.async_initialize_sub_coordinators(None)

        # Should have logged error
        assert mock_logger.error.call_count >= 1
        assert (
            "Failed to initialize sub-coordinator" in mock_logger.error.call_args[0][0]
        )


@pytest.mark.asyncio
async def test_should_send_notification(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test should_send_notification logic."""
    plant_id = "p1"
    stage = "flower"
    day = 10

    # Initially should be True
    assert mock_coordinator.should_send_notification(plant_id, stage, day) is True

    # Mark sent
    await mock_coordinator.mark_notification_sent(plant_id, stage, day)

    # Now should be False
    assert mock_coordinator.should_send_notification(plant_id, stage, day) is False


@pytest.mark.asyncio
async def test_async_update_growspace_full(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test full coverage of async_update_growspace including structure and config updates."""
    # 1. Setup Growspace
    gs = await mock_coordinator.async_add_growspace("Update GS", 3, 3)

    # 2. Update structure only
    with patch(
        "custom_components.growspace_manager.coordinator.async_fire_growspace_event"
    ) as mock_fire:
        await mock_coordinator.async_update_growspace(gs.id, rows=4, plants_per_row=4)
        mock_fire.assert_called_once()  # Should fire event

    assert gs.rows == 4
    assert gs.plants_per_row == 4

    # 3. Update config (name)
    await mock_coordinator.async_update_growspace(gs.id, name="New Name")
    assert gs.name == "New Name"

    # 4. Update notification target
    await mock_coordinator.async_update_growspace(
        gs.id, notification_target="mobile_app_test"
    )
    assert gs.notification_target == "mobile_app_test"

    # 5. Update environment config
    new_env_config = EnvironmentConfig(temperature_sensor="sensor.new_temp")
    await mock_coordinator.async_update_growspace(
        gs.id, environment_config=new_env_config
    )
    assert gs.environment_config == new_env_config

    # 6. Update irrigation config
    irr_config_obj = IrrigationConfig(irrigation_pump_entity="switch.new_pump")
    await mock_coordinator.async_update_growspace(
        gs.id, irrigation_config=irr_config_obj
    )
    assert gs.irrigation_config == irr_config_obj

    # 7. No changes
    with patch(
        "custom_components.growspace_manager.coordinator.async_fire_growspace_event"
    ) as mock_fire:
        await mock_coordinator.async_update_growspace(gs.id)  # no kwargs
        mock_fire.assert_not_called()

    # 8. Validation after resize warnings
    # Add a plant at 4,4
    await mock_coordinator.async_add_plant(gs.id, "Strain", row=4, col=4)

    # Resize to 3x3 (plant now out of bounds)
    with patch(
        "custom_components.growspace_manager.coordinator._LOGGER"
    ) as mock_logger:
        await mock_coordinator.async_update_growspace(gs.id, rows=3, plants_per_row=3)
        assert (
            mock_logger.warning.call_count >= 1
        )  # Should warn about plants outside grid


@pytest.mark.asyncio
async def test_async_harvest_plant_full_flow(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_harvest_plant including moving to target growspace."""
    # 1. Setup Flowering plant
    gs_flower = await mock_coordinator.async_add_growspace("Flower Room")
    plant = await mock_coordinator.async_add_plant(
        gs_flower.id, "Strain", stage="flower", flower_start=date.today().isoformat()
    )

    # 2. Setup Dry Room
    gs_dry = await mock_coordinator.async_add_growspace(
        "Dry Room"
    )  # ID logic? Default "Dry Room" -> "Dry Room". Special "dry" exists.
    # In test env, standard add creates "Dry Room" id="dry_room" slugified usually or unique.

    # Check manual movement
    await mock_coordinator.async_harvest_plant(
        plant.plant_id,
        target_growspace_id=gs_dry.id,
        target_growspace_name="Dry Room",
        transition_date=None,
    )

    assert plant.stage == PlantStage.DRY
    assert plant.growspace_id == gs_dry.id
    assert plant.dry_start is not None


@pytest.mark.asyncio
async def test_ensure_default_growspaces_logic(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test _ensure_default_growspaces creation logic."""
    # Verify defaults are NOT present initially if we clear them (carefully)
    mock_coordinator.growspaces.clear()

    await mock_coordinator._ensure_default_growspaces()

    # Check if 'mother', 'clone', 'veg', 'dry', 'cure' exist
    defaults = ["mother", "clone", "veg", "dry", "cure"]
    for gid in defaults:
        assert gid in mock_coordinator.growspaces
        assert (
            mock_coordinator.growspaces[gid].growspace_type.value == gid
        )  # Map 1:1 in enum


@pytest.mark.asyncio
async def test_notifications_logic_full(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test notification enable/disable logic."""
    gs = await mock_coordinator.async_add_growspace("Notify GS")

    # Default is enabled
    assert mock_coordinator.is_notifications_enabled(gs.id) is True

    # Disable
    await mock_coordinator.set_notifications_enabled(gs.id, False)
    assert mock_coordinator.is_notifications_enabled(gs.id) is False
    assert mock_coordinator._notifications_enabled[gs.id] is False

    # Enable
    await mock_coordinator.set_notifications_enabled(gs.id, True)
    assert mock_coordinator.is_notifications_enabled(gs.id) is True

    # Non-existent GS
    with patch(
        "custom_components.growspace_manager.coordinator._LOGGER"
    ) as mock_logger:
        await mock_coordinator.set_notifications_enabled("missing", False)
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_remove_plant_entities(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test _remove_plant_entities."""
    # 1. Mock Entity Registry
    mock_registry = MagicMock()
    # Mock entities dict
    entry_match = MagicMock()
    entry_match.unique_id = "p1_sensor_temp"

    entry_no_match = MagicMock()
    entry_no_match.unique_id = "other_sensor"

    mock_registry.entities = {
        "sensor.p1_temp": entry_match,
        "sensor.other": entry_no_match,
    }

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        await mock_coordinator._remove_plant_entities("p1")

        # Verify match removal
        mock_registry.async_remove.assert_called_once_with("sensor.p1_temp")


@pytest.mark.asyncio
async def test_setup_sub_coordinators(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test _setup_growspace_sub_coordinators with different configurations."""
    gs_normal = Growspace(id="gs1", name="Normal")
    gs_vwc = Growspace(id="gs2", name="VWC")
    gs_vwc.irrigation_strategy.enabled = True

    mock_entry = MagicMock()

    with (
        patch(
            "custom_components.growspace_manager.coordinator.IrrigationCoordinator"
        ) as mock_irr,
        patch(
            "custom_components.growspace_manager.coordinator.VWCIrrigationCoordinator"
        ) as mock_vwc,
        patch(
            "custom_components.growspace_manager.coordinator.DehumidifierCoordinator"
        ) as mock_dehum,
    ):
        # Setup standard
        mock_irr_instance = AsyncMock()
        mock_irr.return_value = mock_irr_instance

        await mock_coordinator._setup_growspace_sub_coordinators(
            mock_entry, "gs1", gs_normal
        )

        mock_irr.assert_called_once()
        mock_vwc.assert_not_called()
        mock_irr_instance.async_setup.assert_awaited_once()
        assert "gs1" in mock_coordinator.irrigation_coordinators

        mock_dehum.assert_called_once()
        assert "gs1" in mock_coordinator.dehumidifier_coordinators

    # Setup VWC
    with (
        patch(
            "custom_components.growspace_manager.coordinator.IrrigationCoordinator"
        ) as mock_irr,
        patch(
            "custom_components.growspace_manager.coordinator.VWCIrrigationCoordinator"
        ) as mock_vwc,
        patch(
            "custom_components.growspace_manager.coordinator.DehumidifierCoordinator"
        ) as mock_dehum,
    ):
        mock_vwc_instance = AsyncMock()
        mock_vwc.return_value = mock_vwc_instance

        await mock_coordinator._setup_growspace_sub_coordinators(
            mock_entry, "gs2", gs_vwc
        )

        mock_vwc.assert_called_once()
        mock_irr.assert_not_called()
        mock_vwc_instance.async_setup.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_growspace_data(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test get_growspace_data for specific ID and all IDs."""
    gs1 = Growspace(id="gs1", name="GS1")
    gs2 = Growspace(id="gs2", name="GS2")

    mock_coordinator.growspaces = {"gs1": gs1, "gs2": gs2}

    # Needs serializer mock usually, but we can rely on real one if it doesn't fail.
    # The coordinator creates `GrowspaceSerializer` in init.
    # serializer.serialize_growspace needs plants list and environment analyzer.

    # Mock serializer to keep it simple and avoid dependencies
    mock_coordinator.serializer = MagicMock()
    mock_coordinator.serializer.serialize_growspace.return_value = {"id": "serialized"}

    # 1. Specific valid ID
    data = mock_coordinator.get_growspace_data("gs1")
    assert data == {"id": "serialized"}
    mock_coordinator.serializer.serialize_growspace.assert_called()

    # 2. Specific invalid ID
    data = mock_coordinator.get_growspace_data("missing")
    assert data == {}

    # 3. All (None) - with caching, serialize_growspace is called once per growspace
    mock_coordinator.serializer.serialize_growspace.reset_mock()
    data = mock_coordinator.get_growspace_data(None)
    assert len(data) == 2
    assert "gs1" in data
    assert "gs2" in data
    # With caching: each growspace is serialized once and cached
    # The exact count depends on cache state, but should be at least 1 (could be 2 if cache was cleared)
    assert mock_coordinator.serializer.serialize_growspace.call_count >= 1


@pytest.mark.asyncio
async def test_async_remove_plant_event(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test async_remove_plant fires event."""
    plant = await mock_coordinator.async_add_plant("gs1", "Strain")

    with patch(
        "custom_components.growspace_manager.coordinator.async_fire_plant_event"
    ) as mock_fire:
        # success
        result = await mock_coordinator.async_remove_plant(plant.plant_id)
        assert result is True
        mock_fire.assert_called_with(
            mock_coordinator.hass, "growspace_manager_plant_removed", plant
        )

    # Fail (already removed)
    result = await mock_coordinator.async_remove_plant(plant.plant_id)
    assert result is False


@pytest.mark.asyncio
async def test_coordinator_wrapper_methods_sweeper(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test various wrapper methods to ensure 100% coverage."""
    # 1. Strain Library Options
    # Mock strain library get_all to return a dict
    # Mock return value to be a dict, avoiding MagicMock iteration issue
    mock_coordinator.strain_library.get_all = MagicMock(return_value={"S1": "Strain 1"})
    assert mock_coordinator.get_strain_options() == ["S1"]

    # Export / Clear
    mock_coordinator.strain_library.export_library = MagicMock(return_value="data")
    assert mock_coordinator.export_strain_library() == ["S1"]

    mock_coordinator.strain_library.clear = AsyncMock()
    await mock_coordinator.clear_strains()
    mock_coordinator.strain_library.clear.assert_awaited()

    # 2. Plant Lifecycle Wrappers
    # Create a plant
    gs = await mock_coordinator.async_add_growspace("Wrappers")
    plant = await mock_coordinator.async_add_plant(gs.id, "Strain")

    # async_start_flowering(plant_id) -> calls transition with today
    with patch.object(
        mock_coordinator,
        "async_transition_plant_stage",
        new_callable=AsyncMock,
    ) as mock_trans:
        await mock_coordinator.async_start_flowering(plant.plant_id)
        mock_trans.assert_awaited_with(plant.plant_id, PlantStage.FLOWER, date.today())

    # async_start_drying -> calls transition with today (NOT harvest_plant directly in this implementation)
    with patch.object(
        mock_coordinator,
        "async_transition_plant_stage",
        new_callable=AsyncMock,
    ) as mock_trans:
        await mock_coordinator.async_start_drying(plant.plant_id)
        mock_trans.assert_awaited_with(plant.plant_id, PlantStage.DRY, date.today())

    # async_start_curing -> calls transition with today
    with patch.object(
        mock_coordinator,
        "async_transition_plant_stage",
        new_callable=AsyncMock,
    ) as mock_trans:
        await mock_coordinator.async_start_curing(plant.plant_id)
        mock_trans.assert_awaited_with(plant.plant_id, PlantStage.CURE, date.today())

    # async_harvest(plant_id) -> calls async_start_drying
    with patch.object(
        mock_coordinator,
        "async_start_drying",
        new_callable=AsyncMock,
    ) as mock_start_drying:
        await mock_coordinator.async_harvest(plant.plant_id)
        mock_start_drying.assert_awaited_with(plant.plant_id)

    # 3. get_growspace_options
    options = mock_coordinator.get_growspace_options()
    assert gs.id in options
    assert options[gs.id] == "Wrappers"


@pytest.mark.asyncio
async def test_ensure_special_growspace_branches(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test branches in ensure_special_growspace."""
    # 1. Create fresh (Synchronous method!)
    # Need to patch _create_special_growspace to avoid actual creation logic if it's complex,
    # but actual logic is fine if dependencies are mocked.
    # We need to mock migration_manager too.
    mock_coordinator.migration_manager = MagicMock()

    # ensure_special_growspace(id, name, type)
    gs_id = mock_coordinator.ensure_special_growspace(
        "mother", "Mother Room", growspace_type=GrowspaceType.MOTHER
    )
    assert "mother" in gs_id
    assert "mother" in mock_coordinator.growspaces
    assert mock_coordinator.growspaces["mother"].growspace_type == GrowspaceType.MOTHER

    # 2. Retrieve existing
    gs_id2 = mock_coordinator.ensure_special_growspace(
        "mother", "Mother Room New Name", growspace_type=GrowspaceType.MOTHER
    )
    assert gs_id2 == "mother"
    assert (
        mock_coordinator.growspaces["mother"].name == "Mother Room New Name"
    )  # Updates name

    # 3. Create another type
    mock_coordinator.ensure_special_growspace(
        "dry", "Dry Room", growspace_type=GrowspaceType.DRY
    )
    assert mock_coordinator.growspaces["dry"].growspace_type == GrowspaceType.DRY


@pytest.mark.asyncio
async def test_get_growspace_grid(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test get_growspace_grid."""
    gs = await mock_coordinator.async_add_growspace(
        "Grid Test", rows=2, plants_per_row=2
    )
    p1 = await mock_coordinator.async_add_plant(gs.id, "Strain", row=1, col=1)

    # Test valid GS
    grid = mock_coordinator.get_growspace_grid(gs.id)
    # Grid should be a list of lists.
    # row 1 col 1 (1-indexed for user) -> depends on implementation.
    # Usually grid[row_idx][col_idx].
    # If 2 rows, len(grid) == 2.
    assert len(grid) == 2
    # Verify plant presence.
    found = False
    for row in grid:
        if p1.plant_id in row or p1 in row:  # Grid might contain IDs or Objects
            found = True
    assert found

async def test_coverage_init_with_empty_data(hass):
    """Test initialization with None data (line 153)."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()
    
    with (
        patch("custom_components.growspace_manager.coordinator.StorageManager"),
        patch("custom_components.growspace_manager.coordinator.MigrationManager"),
        patch("custom_components.growspace_manager.coordinator.StrainLibrary"),
    ):
        # Initialize with no data
        coord = GrowspaceCoordinator(hass, entry, data=None)

        # Should initialize empty dicts
        assert coord.plants == {}
        assert coord.growspaces == {}


async def test_coverage_load_plant_object_directly(coordinator):
    """Test loading a Plant object directly (line 196)."""
    plant = Plant(
        plant_id="test_plant",
        growspace_id="gs1",
        strain="Test Strain",
        phenotype="Original",
        veg_start="2024-01-01",
    )

    coordinator._load_plants({"test_plant": plant})

    assert "test_plant" in coordinator.plants
    assert coordinator.plants["test_plant"] == plant


async def test_coverage_load_growspace_object_directly(coordinator):
    """Test loading a Growspace object directly (line 214)."""
    growspace = Growspace(
        id="test_gs",
        name="Test GS",
        rows=3,
        plants_per_row=3,
    )

    coordinator._load_growspaces({"test_gs": growspace})

    assert "test_gs" in coordinator.growspaces
    assert coordinator.growspaces["test_gs"] == growspace


async def test_coverage_event_rolling_buffer_limit(coordinator):
    """Test event buffer enforces 50 event limit (lines 323-335)."""
    growspace_id = "test_gs"

    # Add 55 events (should trigger rolling buffer at 50)
    for i in range(55):
        event = GrowspaceEvent(
            sensor_type="test_sensor",
            growspace_id=growspace_id,
            start_time=f"2024-01-01T12:{i:02d}:00",
            end_time=f"2024-01-01T12:{i:02d}:01",
            duration_sec=1,
            severity=0.5,
            category="test",
            reasons=[f"reason {i}"],
        )
        coordinator.add_event(growspace_id, event)

    # Should only keep last 50
    assert len(coordinator.events[growspace_id]) == 50

    # First event should be reason 5 (0-4 were removed)
    assert coordinator.events[growspace_id][0].reasons == ["reason 5"]

    # Last event should be reason 54
    assert coordinator.events[growspace_id][-1].reasons == ["reason 54"]


async def test_coverage_migrate_plant_image_paths(coordinator):
    """Test migrate_plant_image_paths method (lines 599-622)."""
    # Create plant with .jpg image path
    plant_with_jpg = Plant(
        plant_id="plant1",
        growspace_id="gs1",
        strain="Strain1",
        phenotype="Pheno1",
        veg_start="2024-01-01",
    )
    # Manually set phenotype as dict with image_path
    plant_with_jpg.phenotype = {"image_path": "/local/test.jpg"}

    # Create plant with .jpeg path
    plant_with_jpeg = Plant(
        plant_id="plant2",
        growspace_id="gs1",
        strain="Strain2",
        phenotype="Pheno2",
        veg_start="2024-01-01",
    )
    plant_with_jpeg.phenotype = {"image_path": "/local/test2.jpeg"}

    # Create plant without image_path
    plant_no_image = Plant(
        plant_id="plant3",
        growspace_id="gs1",
        strain="Strain3",
        phenotype="Pheno3",
        veg_start="2024-01-01",
    )
    plant_no_image.phenotype = {}

    # Create plant without image_path but with other data (for line 609)
    plant_other_data = Plant(
        plant_id="plant4",
        growspace_id="gs1",
        strain="Strain4",
        phenotype="Pheno4",
        veg_start="2024-01-01",
    )
    plant_other_data.phenotype = {"other": "value"}

    coordinator.plants = {
        "plant1": plant_with_jpg,
        "plant2": plant_with_jpeg,
        "plant3": plant_no_image,
        "plant4": plant_other_data,
    }

    # Run migration
    updated = coordinator.migrate_plant_image_paths()

    # Should update 2 paths
    assert updated == 2
    assert coordinator.plants["plant1"].phenotype["image_path"] == "/local/test.webp"
    assert coordinator.plants["plant2"].phenotype["image_path"] == "/local/test2.webp"
    assert coordinator.plants["plant3"].phenotype == {}
    assert coordinator.plants["plant4"].phenotype.get("image_path") is None


async def test_coverage_load_plants_from_dict(coordinator):
    """Test loading plants from dictionary (line 196)."""
    plant_data = {
        "test_plant": {
            "plant_id": "test_plant",
            "name": "Test",
            "growspace_id": "gs1",
            "strain": "Test Strain",
            "phenotype": "Original",
            "veg_start": "2024-01-01",
            "stage": "vegetative",  # Ensure stage is calculated or preserved
        }
    }

    coordinator._load_plants(plant_data)

    assert "test_plant" in coordinator.plants
    assert coordinator.plants["test_plant"].plant_id == "test_plant"


async def test_coverage_ensure_special_growspace_type_update(coordinator):
    """Test growspace type change (line 484)."""
    # Create a growspace with wrong type
    growspace = Growspace(
        id="dry",
        name="Dry",
        rows=3,
        plants_per_row=3,
        growspace_type=GrowspaceType.FLOWER,  # Wrong type for dry room
    )
    coordinator.growspaces["dry"] = growspace

    # Mock the cache invalidation
    coordinator._serialized_cache = {"dry": "cached_data"}

    # Ensure special growspace (should update type)
    # Note: ensure_special_growspace is synchronous
    result = coordinator.ensure_special_growspace(
        "dry", "Dry", growspace_type=GrowspaceType.DRY
    )

    # Should update type
    assert coordinator.growspaces["dry"].growspace_type == GrowspaceType.DRY
    assert result == "dry"


async def test_coverage_async_commit_with_irrigation_coordinators(coordinator):
    """Test async_commit refreshes irrigation coordinators (lines 569-575)."""
    # Setup growspaces
    coordinator.growspaces = {
        "gs1": Growspace(
            id="gs1",
            name="GS1",
            rows=3,
            plants_per_row=3,
        )
    }

    # Setup mock irrigation coordinator
    mock_irrigation = MagicMock()
    mock_irrigation.async_request_refresh = AsyncMock()
    coordinator.irrigation_coordinators = {"gs1": mock_irrigation}

    # Mock storage manager (if not already mocked by fixture, but coordinator fixture usually has real one)
    # However, create_test_coordinator creates a real StorageManager. 
    # We should mock async_save to avoid file IO.
    coordinator.storage_manager.async_save = AsyncMock()

    # Run commit
    await coordinator.async_commit()

    # Should create background task for irrigation refresh
    coordinator.config_entry.async_create_background_task.assert_called()


async def test_coverage_ensure_calculated_sensors_no_env_config(coordinator):
    """Test ensure_calculated_sensors with no env_config (line 654)."""
    # Create growspace without environment_config
    growspace = Growspace(
        id="test_gs",
        name="Test",
        rows=3,
        plants_per_row=3,
    )
    growspace.environment_config = None
    coordinator.growspaces = {"test_gs": growspace}

    # Should not raise error
    coordinator._ensure_calculated_sensors()
