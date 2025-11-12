from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from freezegun import freeze_time
import pytest

from homeassistant.core import HomeAssistant
from custom_components.growspace_manager.models import Growspace, Plant

from custom_components.growspace_manager.const import PLANT_STAGES
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

@pytest.fixture
def coordinator(hass: HomeAssistant):
    """Return a fresh coordinator for each test."""
    coordinator = GrowspaceCoordinator(hass, data={})
    coordinator.async_set_updated_data = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_add_and_remove_plant(coordinator) -> None:
    gs = await coordinator.async_add_growspace("Plant GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain A", row=1, col=1)
    assert plant.plant_id in coordinator.plants
    assert plant.strain == "Strain A"

    removed = await coordinator.async_remove_plant(plant.plant_id)
    assert removed
    assert plant.plant_id not in coordinator.plants


@pytest.mark.asyncio
async def test_transition_plant_stage(coordinator):
    gs = await coordinator.async_add_growspace("Stage GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain B")

    transition_date = "2025-11-03"  # ISO string

    # Only test the stages you want to transition through
    for stage in PLANT_STAGES:
        if stage not in ["veg", "flower", "dry", "cure"]:
            continue  # skip stages that don't have *_start fields

        await coordinator.async_transition_plant_stage(
            plant.plant_id,
            stage,
            transition_date=transition_date,
        )
        updated = coordinator.plants[plant.plant_id]

        assert updated.stage == stage

        if stage == "veg":
            assert updated.veg_start == transition_date
        elif stage == "flower":
            assert updated.flower_start == transition_date
        elif stage == "dry":
            assert updated.dry_start == transition_date
        elif stage == "cure":
            assert updated.cure_start == transition_date


@pytest.mark.asyncio
async def test_async_create_mum(coordinator):
    start_time = date(2025, 3, 1)
    start_time = start_time.isoformat()
    with freeze_time(start_time):
        mother = await coordinator.async_add_mother_plant(
            "Pheno1",
            "StrainC",
            1,
            1,
            start_time,
        )

    assert mother.mother_start == start_time
    assert mother.plant_id in coordinator.plants
    assert mother.type == "mother"
    assert mother.strain == "StrainC"
    assert mother.phenotype == "Pheno1"


@pytest.mark.asyncio
async def test_async_take_clones(coordinator):
    mother_time = date(2025, 4, 1)
    mother_time = mother_time.isoformat()
    clone_time = date(2025, 4, 2)
    clone_time = clone_time.isoformat()

    with freeze_time(mother_time):
        mother = await coordinator.async_add_mother_plant("Pheno1", "StrainC", 1, 1)

    with freeze_time(clone_time):
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
        assert clone.clone_start == clone_time


@pytest.mark.asyncio
async def test_ensure_special_growspace(coordinator):
    gs_id = coordinator._ensure_special_growspace("mother", "Mother GS", 3, 3)
    assert gs_id in coordinator.growspaces
    gs = coordinator.growspaces[gs_id]
    assert gs.name == "mother"
    assert gs.rows == 3
    assert gs.plants_per_row == 3


@pytest.mark.asyncio
async def test_update_plant_position(coordinator):
    gs = await coordinator.async_add_growspace("Position GS", 3, 3)
    plant = await coordinator.async_add_plant(gs.id, "Strain D", row=1, col=1)

    await coordinator.async_update_plant(plant.plant_id, row=2, col=2)
    updated = coordinator.plants[plant.plant_id]
    assert updated.row == 2
    assert updated.col == 2


@pytest.mark.asyncio
async def test_switch_plants(coordinator):
    gs = await coordinator.async_add_growspace("Switch GS", 2, 2)
    plant1 = await coordinator.async_add_plant(gs.id, "Strain1", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "Strain2", row=2, col=2)

    await coordinator.async_switch_plants(plant1.plant_id, plant2.plant_id)
    p1 = coordinator.plants[plant1.plant_id]
    p2 = coordinator.plants[plant2.plant_id]
    assert (p1.row, p1.col) == (2, 2)
    assert (p2.row, p2.col) == (1, 1)


@pytest.mark.asyncio
async def test_remove_nonexistent_plant_returns_false(coordinator):
    result = await coordinator.async_remove_plant("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_get_growspace_options(coordinator):
    """Test that get_growspace_options returns correct dict of growspace IDs to names."""
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
async def test_get_sorted_growspace_options(coordinator):
    """Test that get_sorted_growspace_options returns growspaces sorted by name."""
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
async def test_migrate_legacy_growspaces(coordinator):
    """Test that legacy growspace aliases are migrated correctly."""
    # Patch the _migrate_special_alias_if_needed method to track calls
    with patch.object(
        coordinator,
        "_migrate_special_alias_if_needed",
        wraps=coordinator._migrate_special_alias_if_needed,
    ) as mock_migrate:
        # Call the private migration method
        coordinator._migrate_legacy_growspaces()

        # Ensure it was called for each alias in SPECIAL_GROWSPACES
        from ..const import SPECIAL_GROWSPACES

        total_aliases = sum(
            len(config["aliases"]) for config in SPECIAL_GROWSPACES.values()
        )
        assert mock_migrate.call_count == total_aliases

        # Optionally, verify the first call arguments (example)
        first_config = list(SPECIAL_GROWSPACES.values())[0]
        first_alias = first_config["aliases"][0]
        mock_migrate.assert_any_call(
            first_alias,
            first_config["canonical_id"],
            first_config["canonical_name"],
        )


@pytest.mark.asyncio
async def test_create_canonical_from_alias(coordinator):
    """Test migrating a growspace from an alias to canonical."""
    alias_id = "alias_gs"
    canonical_id = "canonical_gs"
    canonical_name = "Canonical GS"

    # Use a dict to cover the "else" branch
    coordinator.growspaces[alias_id] = {
        "rows": 4,
        "plants_per_row": 5,
        "notification_target": "notify_me",
        "device_id": "device_1",
    }

    # Patch _migrate_plants_to_growspace and update_data_property
    coordinator._migrate_plants_to_growspace = Mock()
    coordinator.update_data_property = Mock()

    # Call the internal method
    coordinator._create_canonical_from_alias(alias_id, canonical_id, canonical_name)

    # Assert the canonical growspace exists
    new_gs = coordinator.growspaces[canonical_id]
    assert new_gs.id == canonical_id
    assert new_gs.name == canonical_name
    assert new_gs.rows == 4
    assert new_gs.plants_per_row == 5
    assert new_gs.notification_target == "notify_me"
    assert new_gs.device_id is None  # Because dict path always sets device_id to None

    # Alias removed
    assert alias_id not in coordinator.growspaces

    # Helpers called
    coordinator._migrate_plants_to_growspace.assert_called_once_with(
        alias_id,
        canonical_id,
    )
    coordinator.update_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_consolidate_alias_into_canonical(coordinator):
    """Test consolidating an alias growspace into a canonical one."""
    alias_id = "alias_gs"
    canonical_id = "canonical_gs"

    # Setup growspaces
    coordinator.growspaces[alias_id] = {"name": "Alias GS"}
    coordinator.growspaces[canonical_id] = {"name": "Canonical GS"}

    # Patch helpers
    coordinator._migrate_plants_to_growspace = Mock()
    coordinator.update_data_property = Mock()

    # Call the method
    coordinator._consolidate_alias_into_canonical(alias_id, canonical_id)

    # Assert alias removed
    assert alias_id not in coordinator.growspaces

    # Assert canonical still exists
    assert canonical_id in coordinator.growspaces

    # Helpers called
    coordinator._migrate_plants_to_growspace.assert_called_once_with(
        alias_id,
        canonical_id,
    )
    coordinator.update_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_migrate_plants_to_growspace(coordinator):
    """Test that plants are moved from one growspace to another."""
    # Use actual Growspace instances
    coordinator.growspaces["gs1"] = Growspace(
        id="gs1",
        name="Growspace 1",
        rows=3,
        plants_per_row=3,
    )
    coordinator.growspaces["gs2"] = Growspace(
        id="gs2",
        name="Growspace 2",
        rows=3,
        plants_per_row=3,
    )

    # Add plants
    plant1 = await coordinator.async_add_plant("gs1", "Strain1")
    plant2 = await coordinator.async_add_plant("gs1", "Strain2")
    plant3 = await coordinator.async_add_plant("gs2", "Strain3")  # Should remain

    # Migrate plants
    coordinator._migrate_plants_to_growspace("gs1", "gs2")

    # Assert all plants from gs1 are now in gs2
    assert coordinator.plants[plant1.plant_id].growspace_id == "gs2"
    assert coordinator.plants[plant2.plant_id].growspace_id == "gs2"
    # Plant already in gs2 remains
    assert coordinator.plants[plant3.plant_id].growspace_id == "gs2"


@pytest.mark.asyncio
async def test_get_plant_stage(coordinator: GrowspaceCoordinator):
    """Test _get_plant_stage returns correct stage based on start attributes."""

    # Helper to create a plant with only one stage set
    def make_plant_with_stage(stage_attr: str):
        kwargs = {f"{stage_attr}_start": date(2025, 1, 1)}
        return Plant(
            plant_id=f"{stage_attr}_id",
            strain="Test",
            growspace_id="gs1",
            **kwargs,
        )

    stages = ["cure", "dry", "flower", "veg", "clone", "mother", "seedling"]

    for stage in stages:
        if stage == "seedling":
            plant = Plant(plant_id="seedling_id", strain="Test", growspace_id="gs1")
        else:
            plant = make_plant_with_stage(stage)
        result = coordinator._get_plant_stage(plant)
        assert result == stage, f"Expected stage {stage}, got {result}"


@pytest.mark.asyncio
async def test_get_plant(coordinator: GrowspaceCoordinator):
    """Test retrieving a plant by its ID."""
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
async def test_validate_growspace_exists(coordinator: GrowspaceCoordinator):
    """Test that validating an existing growspace passes, and nonexistent raises."""
    # Add a growspace
    gs = await coordinator.async_add_growspace("Test GS")

    # Existing growspace should not raise
    coordinator._validate_growspace_exists(gs.id)

    # Nonexistent growspace should raise ValueError
    with pytest.raises(ValueError, match="Growspace nonexistent does not exist"):
        coordinator._validate_growspace_exists("nonexistent")


@pytest.mark.asyncio
async def test_validate_plant_exists(coordinator: GrowspaceCoordinator):
    """Test that validating an existing plant passes, and nonexistent raises."""
    # Add a growspace and plant
    gs = await coordinator.async_add_growspace("Test GS")
    plant = await coordinator.async_add_plant(gs.id, "Strain X", row=1, col=1)

    # Existing plant should not raise
    coordinator._validate_plant_exists(plant.plant_id)

    # Nonexistent plant should raise ValueError
    with pytest.raises(ValueError, match="Plant nonexistent does not exist"):
        coordinator._validate_plant_exists("nonexistent")


@pytest.mark.asyncio
async def test_validate_position_bounds(coordinator: GrowspaceCoordinator):
    """Test that valid positions pass and out-of-bounds raise ValueError."""
    # Add a growspace
    gs = await coordinator.async_add_growspace("Bounds GS", rows=3, plants_per_row=3)

    # Valid positions should not raise
    coordinator._validate_position_bounds(gs.id, row=1, col=1)
    coordinator._validate_position_bounds(gs.id, row=3, col=3)

    # Row out of bounds
    with pytest.raises(ValueError, match="Row 0 is outside growspace bounds"):
        coordinator._validate_position_bounds(gs.id, row=0, col=1)
    with pytest.raises(ValueError, match="Row 4 is outside growspace bounds"):
        coordinator._validate_position_bounds(gs.id, row=4, col=1)

    # Column out of bounds
    with pytest.raises(ValueError, match="Column 0 is outside growspace bounds"):
        coordinator._validate_position_bounds(gs.id, row=1, col=0)
    with pytest.raises(ValueError, match="Column 4 is outside growspace bounds"):
        coordinator._validate_position_bounds(gs.id, row=1, col=4)


@pytest.mark.asyncio
async def test_validate_position_not_occupied(coordinator: GrowspaceCoordinator):
    """Test that occupied positions raise and empty positions pass."""
    # Add a growspace
    gs = await coordinator.async_add_growspace("Occupy GS", rows=2, plants_per_row=2)

    # Add a plant at (1,1)
    plant1 = await coordinator.async_add_plant(gs.id, "Strain1", row=1, col=1)

    # Valid: empty position
    coordinator._validate_position_not_occupied(gs.id, row=2, col=2)

    # Invalid: occupied position
    with pytest.raises(
        ValueError,
        match="Position \\(1,1\\) is already occupied by Strain1",
    ):
        coordinator._validate_position_not_occupied(gs.id, row=1, col=1)

    # Valid if excluding the same plant
    coordinator._validate_position_not_occupied(
        gs.id,
        row=1,
        col=1,
        exclude_plant_id=plant1.plant_id,
    )


@pytest.mark.asyncio
async def test_parse_date_fields(coordinator: GrowspaceCoordinator):
    """Test that date fields in kwargs are parsed correctly."""
    kwargs = {
        "veg_start": "2025-01-01",
        "flower_start": date(2025, 2, 1),
        "dry_start": datetime(2025, 3, 1, 12, 0),
        "cure_start": None,
    }

    coordinator._parse_date_fields(kwargs)

    # Check against ISO strings
    assert kwargs["veg_start"] == "2025-01-01"
    assert kwargs["flower_start"] == "2025-02-01"
    assert kwargs["dry_start"] == "2025-03-01"
    assert kwargs["cure_start"] is None


@pytest.mark.asyncio
async def test_calculate_days(coordinator):
    today = date.today()

    # Using string
    days = coordinator._calculate_days("2025-01-01")
    expected = (today - date(2025, 1, 1)).days
    assert days == expected

    # Using date
    start = date(2024, 12, 31)
    days = coordinator._calculate_days(start)
    expected = (today - start).days
    assert days == expected

    # Using datetime
    start_dt = datetime(2024, 12, 30, 15, 0)
    days = coordinator._calculate_days(start_dt)
    expected = (today - start_dt.date()).days
    assert days == expected

    # None or 'None' should return 0
    assert coordinator._calculate_days(None) == 0
    assert coordinator._calculate_days("None") == 0

    # Invalid string returns 0 (logs warning)
    assert coordinator._calculate_days("invalid-date") == 0


@pytest.mark.asyncio
async def test_generate_unique_name(coordinator):
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
async def test_update_special_growspace_name(coordinator):
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
async def test_async_update_data(coordinator):
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
async def test_async_load(coordinator):
    # Prepare fake stored data
    fake_data = {
        "plants": {
            "p1": {"plant_id": "p1", "strain": "StrainX", "growspace_id": "gs1"},
        },
        "growspaces": {
            "gs1": {"id": "gs1", "name": "Growspace1", "rows": 3, "plants_per_row": 3},
        },
        "notifications_sent": {"gs1": []},
        "notifications_enabled": {"gs1": True},
        "strain_library": [{"name": "StrainX"}],
    }

    # Mock the store to return this data
    coordinator.store.async_load = AsyncMock(return_value=fake_data)
    coordinator.async_save = AsyncMock()
    coordinator.strains.import_strains = AsyncMock()

    # Mock Plant.from_dict and Growspace.from_dict

    Plant.from_dict = staticmethod(lambda p: MagicMock(**p))
    Growspace.from_dict = staticmethod(lambda g: MagicMock(**g))

    # Call the method
    await coordinator.async_load()

    # Assertions
    assert "p1" in coordinator.plants
    assert "gs1" in coordinator.growspaces
    assert coordinator._notifications_sent == {"gs1": []}
    assert coordinator._notifications_enabled == {"gs1": True}

    # Ensure strains imported
    coordinator.strains.import_strains.assert_called_once_with(
        fake_data["strain_library"],
        replace=True,
    )
    # Ensure save called
    coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_async_remove_growspace(coordinator):
    # Setup: add a growspace with plants
    gs = await coordinator.async_add_growspace("Test GS", 2, 2)
    plant1 = await coordinator.async_add_plant(gs.id, "StrainA", row=1, col=1)
    plant2 = await coordinator.async_add_plant(gs.id, "StrainB", row=2, col=2)

    # Add dummy notification states
    coordinator._notifications_sent[plant1.plant_id] = ["alert1"]
    coordinator._notifications_sent[plant2.plant_id] = ["alert2"]
    coordinator._notifications_enabled[gs.id] = True

    # Mock async_save and async_set_updated_data
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    # Call async_remove_growspace
    await coordinator.async_remove_growspace(gs.id)

    # Assertions: growspace removed
    assert gs.id not in coordinator.growspaces
    # Plants removed
    assert plant1.plant_id not in coordinator.plants
    assert plant2.plant_id not in coordinator.plants
    # Notifications cleared
    assert plant1.plant_id not in coordinator._notifications_sent
    assert plant2.plant_id not in coordinator._notifications_sent
    assert gs.id not in coordinator._notifications_enabled

    # Data update methods called
    coordinator.async_save.assert_called_once()
    coordinator.async_set_updated_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_growspace(coordinator):
    # Setup: create a growspace
    gs = await coordinator.async_add_growspace("Old Name", 2, 2)

    # Mock async_save and async_set_updated_data
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()
    # Update name, rows, plants_per_row, notification_target
    await coordinator.async_update_growspace(
        growspace_id=gs.id,
        name="New Name",
        rows=3,
        plants_per_row=4,
        notification_target="notify@example.com",
    )

    updated_gs = coordinator.growspaces[gs.id]

    # Assertions
    assert updated_gs.name == "New Name"
    assert updated_gs.rows == 3
    assert updated_gs.plants_per_row == 4
    assert updated_gs.notification_target == "notify@example.com"

    # Ensure async_save and async_set_updated_data were called
    coordinator.async_save.assert_called_once()
    coordinator.async_set_updated_data.assert_called_once()


@pytest.mark.asyncio
async def test_async_update_growspace_no_changes(coordinator):
    # Setup: create a growspace
    gs = await coordinator.async_add_growspace(
        "Same Name",
        2,
        2,
        notification_target="",
    )

    # Mock async_save and async_set_updated_data
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    # Call update with the same values
    await coordinator.async_update_growspace(
        growspace_id=gs.id,
        name="Same Name",
        rows=2,
        plants_per_row=2,
        notification_target="",  # matches existing exactly
    )

    # async_save and async_set_updated_data should NOT be called
    coordinator.async_save.assert_not_called()
    coordinator.async_set_updated_data.assert_not_called()


@pytest.mark.asyncio
async def test_async_update_growspace_invalid_id(coordinator):
    with pytest.raises(ValueError, match="Growspace invalid_id not found"):
        await coordinator.async_update_growspace("invalid_id", name="Test")


@pytest.mark.asyncio
async def test_validate_plants_after_growspace_resize_logs_warnings(
    coordinator,
    caplog,
):
    # Setup: create growspace 2x2
    gs = await coordinator.async_add_growspace("Resize GS", 2, 2)
    # Add a plant outside the new resized bounds
    plant = await coordinator.async_add_plant(gs.id, "StrainX", row=3, col=1)

    # Set log level synchronously
    caplog.set_level("WARNING")

    # Resize growspace to smaller grid
    await coordinator._validate_plants_after_growspace_resize(
        gs.id,
        new_rows=2,
        new_plants_per_row=2,
    )

    # Check that warnings were logged about invalid plant
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any(f"Plant {plant.plant_id}" in w for w in warnings)
    assert any("outside new grid" in w for w in warnings)


@pytest.mark.asyncio
async def test_is_notifications_enabled(coordinator):
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
async def test_set_notifications_enabled(coordinator):
    # Create a growspace
    gs = await coordinator.async_add_growspace("Notify GS", 2, 2)

    # Mock async_save and async_set_updated_data
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    # Initialize self.data so set_notifications_enabled doesn't fail
    coordinator.update_data_property()

    # Disable notifications
    await coordinator.set_notifications_enabled(gs.id, False)
    assert coordinator.is_notifications_enabled(gs.id) is False
    coordinator.async_save.assert_awaited_once()
    coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)

    # Enable notifications
    coordinator.async_save.reset_mock()
    coordinator.async_set_updated_data.reset_mock()
    await coordinator.set_notifications_enabled(gs.id, True)
    assert coordinator.is_notifications_enabled(gs.id) is True
    coordinator.async_save.assert_awaited_once()
    coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)

    # Non-existent growspace
    coordinator.async_save.reset_mock()
    coordinator.async_set_updated_data.reset_mock()
    await coordinator.set_notifications_enabled("nonexistent", True)
    coordinator.async_save.assert_not_awaited()
    coordinator.async_set_updated_data.assert_not_called()


@pytest.mark.asyncio
async def test_handle_clone_creation(coordinator):
    # Setup: create a mother plant
    mother = await coordinator.async_add_mother_plant("PhenoA", "StrainX", 1, 1)
    # Force the stage to 'mother' so auto-find works
    mother.stage = "mother"
    coordinator.update_data_property()

    # Mock async_save and async_set_updated_data
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()
    coordinator.update_data_property()  # ensure self.data is initialized

    clone_id = "clone123"

    # Test clone creation using explicit source_mother
    returned_id = await coordinator._handle_clone_creation(
        plant_id=clone_id,
        growspace_id=mother.growspace_id,
        strain="StrainX",
        phenotype="PhenoA",
        row=1,
        col=2,
        source_mother=mother.plant_id,
    )

    assert returned_id == clone_id
    clone_plant = coordinator.plants[clone_id]
    assert clone_plant.stage == "clone"
    assert clone_plant.source_mother == mother.plant_id
    assert clone_plant.phenotype == mother.phenotype
    assert clone_plant.row == 1
    assert clone_plant.col == 2

    # Ensure async_save and async_set_updated_data were called
    coordinator.async_save.assert_awaited_once()
    coordinator.async_set_updated_data.assert_called_once_with(coordinator.data)

    # Test clone creation without providing source_mother (auto-find)
    clone_id2 = "clone124"
    await coordinator._handle_clone_creation(
        plant_id=clone_id2,
        growspace_id=mother.growspace_id,
        strain="StrainX",
        phenotype="PhenoA",
        row=2,
        col=1,
    )

    clone_plant2 = coordinator.plants[clone_id2]
    assert clone_plant2.source_mother == mother.plant_id
    assert clone_plant2.stage == "clone"


@pytest.mark.asyncio
async def test_async_transition_clone_to_veg(coordinator):
    # Step 1: create a mother plant
    mother = await coordinator.async_add_mother_plant("PhenoA", "StrainX", 1, 1)

    # Step 2: create a clone using _handle_clone_creation
    clone_id = "clone123"
    fixed_time = "2025-11-03 16:44:40"

    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()
    coordinator.update_data_property()

    with freeze_time(fixed_time):
        await coordinator._handle_clone_creation(
            plant_id=clone_id,
            growspace_id=mother.growspace_id,
            strain="StrainX",
            phenotype="PhenoA",
            row=1,
            col=2,
            source_mother=mother.plant_id,
        )

        # Step 3: transition the clone to veg
        await coordinator.async_transition_clone_to_veg(clone_id)

    clone = coordinator.plants[clone_id]
    assert clone.stage == "veg"
    assert clone.growspace_id == "veg"
    assert clone.veg_start == "2025-11-03T16:44:40"

    coordinator.async_save.assert_awaited()
    coordinator.async_set_updated_data.assert_called_with(coordinator.data)
