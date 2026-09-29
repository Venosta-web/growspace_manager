"""Tests for the StorageManager."""

from datetime import UTC, datetime
import glob
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.grow_run import PlantMovementFact
from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.growspaces = {}
    mock.plants = {}
    mock.load_growspaces.side_effect = lambda gs: mock.growspaces.update(gs)
    mock.load_plants.side_effect = lambda ps: mock.plants.update(ps)
    mock.get_all_growspaces.side_effect = lambda: list(mock.growspaces.values())
    mock.get_all_plants.side_effect = lambda: list(mock.plants.values())
    return mock


@pytest.fixture
def nutrient_manager_mock():
    """Mock the NutrientManager."""
    mock = MagicMock()
    mock.nutrient_presets = {}
    mock.ipm_presets = {}
    mock.inventory = None
    mock.get_serialization_data.return_value = {}
    return mock


@pytest.fixture
def genetics_manager_mock():
    """Mock the GeneticsManager."""
    mock = MagicMock()
    mock.get_serialization_data.return_value = {}
    return mock


@pytest.fixture
def storage(hass, repository_mock, nutrient_manager_mock, genetics_manager_mock):
    """Provide a StorageManager instance."""
    return StorageManager(
        hass, repository_mock, nutrient_manager_mock, genetics_manager_mock
    )


@pytest.mark.asyncio
async def test_load_growspaces_uses_mashumaro(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, storage
) -> None:
    """Test that loading growspaces correctly uses Mashumaro deserialization."""

    # Mock data
    raw_data = {
        "growspaces": {
            "gs1": {
                "id": "gs1",
                "name": "Test",
                "rows": 2,
                "plants_per_row": 3,
                "irrigation_config": {
                    "irrigation_times": [{"time": "08:00:00", "duration": 60}]
                },
            }
        }
    }

    # Setup store mocks
    with patch("homeassistant.helpers.storage.Store.async_load") as mock_load:
        mock_load.return_value = raw_data

        await storage.async_load()

        # VERIFICATION: Ensure growspaces were loaded into repository
        assert len(repository_mock.growspaces) == 1
        assert "gs1" in repository_mock.growspaces
        assert repository_mock.growspaces["gs1"].name == "Test"


@pytest.mark.asyncio
async def test_backup_logic_with_corrupt_data(
    hass: HomeAssistant,
    repository_mock,
    nutrient_manager_mock,
    storage,
    tmp_path: Path,
) -> None:
    """Test that corrupt data triggers a backup file creation."""

    # Mock hass.config.path to return a temp directory
    with patch.object(hass.config, "path", return_value=str(tmp_path)):
        # Trigger load with structural corruption (not just single item)
        # to trigger the outer try-except block that calls _backup_corrupt_data
        corrupt_data = MagicMock()
        corrupt_data.get.side_effect = Exception("Structural corruption!")

        storage._load_growspaces(corrupt_data)

        # Verify empty growspaces set (reset happened)
        assert repository_mock.growspaces == {}

        # Verify backup file creation
        files = glob.glob(f"{tmp_path}/growspace_manager_growspaces_CORRUPT_*.json")
        assert len(files) >= 1, "Backup file was not created"

        # Cleanup
        for f in files:
            Path(f).unlink()


async def test_schedule_save_only_debounces_runtime_config(storage) -> None:
    """A delayed save cannot persist a Plant without its Activity Fact."""
    with (
        patch.object(storage.config_store, "async_delay_save") as config,
        patch.object(storage.plants_store, "async_delay_save") as plants,
        patch.object(storage.genetics_store, "async_delay_save") as genetics,
    ):
        storage.async_schedule_save()

    config.assert_called_once_with(storage._get_config_data, 10)
    plants.assert_not_called()
    genetics.assert_not_called()


def test_harvest_movement_is_a_durable_activity_fact(storage) -> None:
    """Moving a flowering Plant to drying is classified at the save boundary."""
    storage._committed_plants = {
        "plant-1": {"growspace_id": "flower", "row": 1, "col": 1, "stage": "flower"}
    }
    facts = storage._stage_movement_facts(
        {"plant-1": {"growspace_id": "dry", "row": 1, "col": 1, "stage": "dry"}}
    )
    assert len(facts) == 1
    assert facts[0].kind == "harvest"
    assert facts[0].source_growspace_id == "flower"
    assert facts[0].target_growspace_id == "dry"
    assert facts[0].fact_id


@pytest.mark.parametrize("bad_facts", [None, "duplicate"])
async def test_corrupt_activity_outbox_holds_every_plant_write(
    storage, bad_facts
) -> None:
    """A damaged outbox is backed up and never replaced by an empty one."""
    if bad_facts == "duplicate":
        fact = PlantMovementFact(
            fact_id="f1",
            plant_id="p1",
            at=datetime.now(UTC),
            kind="entry",
            source_growspace_id=None,
            target_growspace_id="tent",
            source_run_id=None,
            target_run_id=None,
        ).as_dict()
        bad_facts = [fact, fact]
    with patch.object(storage, "_backup_corrupt_data") as backup:
        storage._load_plants({"plants": {}, "activity_facts": bad_facts})
    backup.assert_called_once()
    assert storage.activity_unreadable
    with patch.object(storage.config_store, "async_delay_save") as delayed:
        storage.async_schedule_save()
    delayed.assert_not_called()
    with pytest.raises(ValueError, match="outbox is unreadable"):
        await storage.async_force_save()
    with pytest.raises(ValueError, match="outbox is unreadable"):
        await storage.async_mark_fact_projected("f1")
    with pytest.raises(ValueError, match="outbox is unreadable"):
        await storage.async_save_plant_layout_snapshot("tent", 1, [], "now", 1, 1)
