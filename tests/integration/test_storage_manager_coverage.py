"""Coverage tests for StorageManager."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.growspace_manager.const import IrrigationRecipeKind
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IPMPreset,
    IrrigationRecipe,
    NutrientInventory,
    NutrientPreset,
    Plant,
)
from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.get_all_growspaces.return_value = []
    mock.get_all_plants.return_value = []
    return mock


@pytest.fixture
def notification_state():
    """Real NotificationState for storage tests."""
    return NotificationState()


@pytest.fixture
def nutrient_manager_mock():
    """Mock the NutrientManager."""
    return MagicMock()


@pytest.fixture
def genetics_manager_mock():
    """Mock the GeneticsManager."""
    mock = MagicMock()
    mock.get_serialization_data.return_value = {}
    return mock


@pytest.fixture
def storage(
    hass: HomeAssistant,
    repository_mock,
    nutrient_manager_mock,
    genetics_manager_mock,
    notification_state,
):
    """Provide a StorageManager instance."""
    return StorageManager(
        hass,
        repository_mock,
        nutrient_manager_mock,
        genetics_manager_mock,
        notification_state,
    )


@pytest.mark.asyncio
async def test_storage_async_save(storage) -> None:
    """Test async_save debounced."""
    with (
        patch.object(storage, "_get_config_data", return_value={}),
        patch.object(storage, "_get_plants_data", return_value={}),
        patch.object(storage.config_store, "async_delay_save") as mock_config_save,
        patch.object(storage.plants_store, "async_delay_save") as mock_plants_save,
    ):
        await storage.async_save()
        mock_config_save.assert_called_once()
        mock_plants_save.assert_called_once()


@pytest.mark.asyncio
async def test_storage_async_force_save(storage) -> None:
    """Test async_force_save immediate."""
    with (
        patch.object(storage, "_get_config_data", return_value={}),
        patch.object(storage, "_get_plants_data", return_value={}),
        patch.object(
            storage.config_store, "async_save", new_callable=AsyncMock
        ) as mock_config_save,
        patch.object(
            storage.plants_store, "async_save", new_callable=AsyncMock
        ) as mock_plants_save,
    ):
        await storage.async_force_save()
        mock_config_save.assert_awaited_once()
        mock_plants_save.assert_awaited_once()


async def test_save_plant_layout_snapshot_uses_staged_documents(storage) -> None:
    """Atomic layout persistence writes staged values, not live repository state."""
    config_data = {"growspaces": {"tent": {"layout_revision": 2}}}
    plants_data = {"plants": {"p1": {"row": 1, "col": 1, "updated_at": "before"}}}
    storage.config_store.async_save = AsyncMock()
    storage.plants_store.async_save = AsyncMock()

    with (
        patch.object(storage, "_get_config_data", return_value=config_data),
        patch.object(storage, "_get_plants_data", return_value=plants_data),
    ):
        await storage.async_save_plant_layout_snapshot(
            "tent",
            3,
            [{"plant_id": "p1", "row": 2, "col": 2}],
            "after",
            2,
            3,
        )

    storage.config_store.async_save.assert_awaited_once_with(
        {
            "growspaces": {
                "tent": {
                    "layout_revision": 3,
                    "rows": 2,
                    "plants_per_row": 3,
                }
            }
        }
    )
    storage.plants_store.async_save.assert_awaited_once_with(
        {"plants": {"p1": {"row": 2, "col": 2, "updated_at": "after"}}}
    )


async def test_save_plant_layout_snapshot_restores_both_stores_on_failure(
    storage,
) -> None:
    """A segmented write failure restores the unpublished repository snapshot."""
    old_config = {"growspaces": {"tent": {"layout_revision": 2}}}
    old_plants = {"plants": {"p1": {"row": 1, "col": 1, "updated_at": "before"}}}
    storage.config_store.async_save = AsyncMock()
    storage.plants_store.async_save = AsyncMock(
        side_effect=[RuntimeError("disk full"), None]
    )

    with (
        patch.object(
            storage,
            "_get_config_data",
            side_effect=[
                {"growspaces": {"tent": {"layout_revision": 2}}},
                old_config,
            ],
        ),
        patch.object(
            storage,
            "_get_plants_data",
            side_effect=[
                {"plants": {"p1": {"row": 1, "col": 1, "updated_at": "before"}}},
                old_plants,
            ],
        ),
        pytest.raises(RuntimeError, match="disk full"),
    ):
        await storage.async_save_plant_layout_snapshot(
            "tent",
            3,
            [{"plant_id": "p1", "row": 2, "col": 2}],
            "after",
            2,
            3,
        )

    assert storage.config_store.async_save.await_args_list == [
        call(
            {
                "growspaces": {
                    "tent": {
                        "layout_revision": 3,
                        "rows": 2,
                        "plants_per_row": 3,
                    }
                }
            }
        ),
        call(old_config),
    ]
    assert storage.plants_store.async_save.await_args_list[-1] == call(old_plants)


def test_storage_get_config_data(
    storage, repository_mock, nutrient_manager_mock, notification_state
) -> None:
    """Test gathering config data for storage."""
    nutrient_manager_mock.get_serialization_data.return_value = {"nutrients": "data"}
    repository_mock.get_all_growspaces.return_value = [Growspace(id="gs1", name="Test")]
    notification_state.sent = {"gs1": ["notif1"]}
    notification_state.enabled = {"gs1": True}

    data = storage._get_config_data()

    assert data["growspaces"]["gs1"]["id"] == "gs1"
    assert data["nutrients"] == "data"
    assert data["notifications_sent"] == {"gs1": ["notif1"]}
    assert data["notifications_enabled"] == {"gs1": True}


def test_storage_get_plants_data(storage, repository_mock) -> None:
    """Test gathering plant data for storage."""
    repository_mock.get_all_plants.return_value = [
        Plant(plant_id="p1", growspace_id="gs1", row=1, col=1)
    ]

    data = storage._get_plants_data()

    assert data["plants"]["p1"]["plant_id"] == "p1"


@pytest.mark.asyncio
async def test_storage_backup_corrupt_data_success(
    storage, hass: HomeAssistant
) -> None:
    """Test _backup_corrupt_data success path (covers JSON dump)."""
    data = {"some": "corrupt_data"}
    with patch("pathlib.Path.open", create=True) as mock_open:
        storage._backup_corrupt_data("test", data)
        mock_open.assert_called_once()


@pytest.mark.asyncio
async def test_storage_apply_options_object(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, storage
) -> None:
    """A non-dict legacy blob is ignored — options are JSON, objects are bugs."""
    env_config = EnvironmentConfig(temperature_sensor="sensor.temp")
    options = {"gs1": env_config}
    gs = Growspace(id="gs1", name="Test")
    repository_mock.get_all_growspaces.return_value = [gs]

    storage._apply_options_to_growspaces(options)

    assert gs.environment_config == EnvironmentConfig()


@pytest.mark.asyncio
async def test_storage_load_nutrient_inventory_exception(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, storage
) -> None:
    """Test exception handling in _load_nutrient_inventory."""
    with patch(
        "custom_components.growspace_manager.models.NutrientInventory.from_dict",
        side_effect=ValueError("Test Error"),
    ):
        result = storage._load_nutrient_inventory({"nutrient_inventory": {}})
        assert isinstance(result, NutrientInventory)


def test_storage_load_config_notification_defaults(
    storage, repository_mock, nutrient_manager_mock, notification_state
) -> None:
    """Test _load_config sets notification defaults for new growspaces."""
    data = {
        "growspaces": {"gs1": {"id": "gs1", "name": "GS1"}},
        "notifications_sent": {},
        "notifications_enabled": {},  # Missing gs1
    }
    gs = Growspace(id="gs1", name="GS1")
    repository_mock.get_all_growspaces.return_value = [gs]

    with (
        patch.object(storage, "_load_growspaces"),
        patch.object(storage, "_load_nutrient_presets", return_value={}),
        patch.object(storage, "_load_ipm_presets", return_value={}),
        patch.object(
            storage, "_load_nutrient_inventory", return_value=NutrientInventory()
        ),
    ):
        storage._load_config(data)
        assert notification_state.enabled["gs1"] is True


@pytest.mark.asyncio
async def test_storage_async_load_segmented(storage) -> None:
    """Test loading from segmented storage."""
    config_data = {"nutrient_presets": {}}
    plants_data = {"plants": {}}

    with (
        patch.object(storage.config_store, "async_load", return_value=config_data),
        patch.object(storage.plants_store, "async_load", return_value=plants_data),
        patch.object(storage, "_load_config") as mock_load_config,
        patch.object(storage, "_load_plants") as mock_load_plants,
    ):
        await storage.async_load()
        mock_load_config.assert_called_once_with(config_data, None)
        mock_load_plants.assert_called_once_with(plants_data)


@pytest.mark.asyncio
async def test_storage_async_load_legacy_migration(storage) -> None:
    """Test migration from legacy storage."""
    legacy_data = {"plants": {}, "growspaces": {}}

    with (
        patch.object(storage.config_store, "async_load", return_value=None),
        patch.object(storage.plants_store, "async_load", return_value=None),
        patch.object(storage.legacy_store, "async_load", return_value=legacy_data),
        patch.object(storage, "_load_legacy") as mock_load_legacy,
        patch.object(storage.config_store, "async_save") as mock_save_config,
        patch.object(storage.plants_store, "async_save") as mock_save_plants,
    ):
        await storage.async_load()
        mock_load_legacy.assert_called_once_with(legacy_data, None)
        mock_save_config.assert_called_once()
        mock_save_plants.assert_called_once()


@pytest.mark.asyncio
async def test_storage_async_load_fresh(storage) -> None:
    """Test loading when no data exists (fresh start)."""
    with (
        patch.object(storage.config_store, "async_load", return_value=None),
        patch.object(storage.plants_store, "async_load", return_value=None),
        patch.object(storage.legacy_store, "async_load", return_value=None),
        patch.object(storage, "async_save") as mock_save,
    ):
        await storage.async_load()
        mock_save.assert_called_once()


def test_storage_load_config(
    storage, repository_mock, nutrient_manager_mock, notification_state
) -> None:
    """Test _load_config logic."""
    data = {
        "notifications_sent": {"gs1": []},
        "notifications_enabled": {"gs1": False},
        "growspaces": {"gs1": {"id": "gs1", "name": "GS1"}},
    }
    gs = Growspace(id="gs1", name="GS1")
    repository_mock.get_all_growspaces.return_value = [gs]

    with (
        patch.object(storage, "_load_growspaces"),
        patch.object(storage, "_load_nutrient_presets", return_value={}),
        patch.object(storage, "_load_ipm_presets", return_value={}),
        patch.object(
            storage, "_load_nutrient_inventory", return_value=NutrientInventory()
        ),
    ):
        storage._load_config(data)

        nutrient_manager_mock.load_data.assert_called_once()
        assert notification_state.sent == {"gs1": []}
        assert notification_state.enabled == {"gs1": False}


def test_storage_load_legacy(storage) -> None:
    """Test _load_legacy triggers plant and config loading."""
    data = {"some": "data"}
    with (
        patch.object(storage, "_load_plants") as mock_load_plants,
        patch.object(storage, "_load_config") as mock_load_config,
    ):
        storage._load_legacy(data, {"opt": "val"})
        mock_load_plants.assert_called_once_with(data)
        mock_load_config.assert_called_once_with(data, {"opt": "val"})


def test_storage_load_plants(storage, repository_mock) -> None:
    """Test _load_plants success, instance, and invalid type."""
    plant_dict = {"plant_id": "p1", "growspace_id": "gs1"}
    plant_obj = Plant(plant_id="p2", growspace_id="gs1")
    data = {"plants": {"p1": plant_dict, "p2": plant_obj, "p3": "invalid"}}

    with (
        patch(
            "custom_components.growspace_manager.models.Plant.from_dict",
            return_value=plant_obj,
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.error"
        ) as mock_log_error,
    ):
        storage._load_plants(data)
        loaded = repository_mock.load_plants.call_args[0][0]
        assert len(loaded) == 2
        assert "p1" in loaded
        assert "p2" in loaded
        mock_log_error.assert_called_once()


def test_storage_load_plants_inner_exception(storage, repository_mock) -> None:
    """Test _load_plants exception for a single plant."""
    data = {"plants": {"p1": {"some": "garbage"}}}
    with (
        patch(
            "custom_components.growspace_manager.models.Plant.from_dict",
            side_effect=Exception("Inner"),
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        storage._load_plants(data)
        mock_log_exc.assert_called_once()
        loaded = repository_mock.load_plants.call_args[0][0]
        assert len(loaded) == 0


def test_storage_load_plants_exception(storage, repository_mock) -> None:
    """Test _load_plants overall exception and backup."""
    with (
        patch.object(storage, "_backup_corrupt_data") as mock_backup,
        patch("custom_components.growspace_manager.storage_manager._LOGGER.exception"),
    ):
        storage._load_plants(None)
        mock_backup.assert_called_once_with("plants", None)


def test_storage_load_growspaces(storage, repository_mock) -> None:
    """Test _load_growspaces success, instance, and invalid type."""
    gs_dict = {"id": "gs1", "name": "GS1"}
    gs_obj = Growspace(id="gs2", name="GS2")
    data = {"growspaces": {"gs1": gs_dict, "gs2": gs_obj, "gs3": "invalid"}}

    with (
        patch(
            "custom_components.growspace_manager.models.Growspace.from_dict",
            return_value=gs_obj,
        ),
        patch.object(storage, "_apply_options_to_growspaces"),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.error"
        ) as mock_log_error,
    ):
        storage._load_growspaces(data)
        loaded = repository_mock.load_growspaces.call_args[0][0]
        assert len(loaded) == 2
        assert "gs1" in loaded
        assert "gs2" in loaded
        mock_log_error.assert_called_once()


def test_storage_load_growspaces_inner_exception(storage, repository_mock) -> None:
    """Test _load_growspaces exception for a single growspace."""
    data = {"growspaces": {"gs1": {"some": "garbage"}}}
    with (
        patch(
            "custom_components.growspace_manager.models.Growspace.from_dict",
            side_effect=Exception("Inner"),
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        storage._load_growspaces(data)
        mock_log_exc.assert_called_once()
        loaded = repository_mock.load_growspaces.call_args[0][0]
        assert len(loaded) == 0


def test_storage_load_growspaces_exception(storage, repository_mock) -> None:
    """Test _load_growspaces overall exception and backup."""
    with (
        patch.object(storage, "_backup_corrupt_data") as mock_backup,
        patch("custom_components.growspace_manager.storage_manager._LOGGER.exception"),
    ):
        storage._load_growspaces(None)
        mock_backup.assert_called_once_with("growspaces", None)


def test_storage_load_nutrient_presets(storage) -> None:
    """Test _load_nutrient_presets and error handling."""
    data = {"nutrient_presets": {"p1": {"name": "P1"}}}
    preset = NutrientPreset(id="p1", name="P1", items=[])

    with patch(
        "custom_components.growspace_manager.models.NutrientPreset.from_dict",
        return_value=preset,
    ):
        res = storage._load_nutrient_presets(data)
        assert "p1" in res

    with (
        patch(
            "custom_components.growspace_manager.models.NutrientPreset.from_dict",
            side_effect=ValueError,
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        res = storage._load_nutrient_presets(data)
        assert res == {}
        mock_log_exc.assert_called_once()


def test_storage_load_irrigation_recipes(storage) -> None:
    """Test _load_irrigation_recipes and error handling.

    A corrupt recipe must not brick startup: the library loads empty and the
    failure is logged, exactly as the nutrient and IPM libraries behave.
    """
    data = {"irrigation_recipes": {"r1": {"name": "R1"}}}
    recipe = IrrigationRecipe(
        id="r1", name="R1", kind=IrrigationRecipeKind.CROP_STEERING
    )

    with patch(
        "custom_components.growspace_manager.models.IrrigationRecipe.from_dict",
        return_value=recipe,
    ):
        res = storage._load_irrigation_recipes(data)
        assert "r1" in res

    with (
        patch(
            "custom_components.growspace_manager.models.IrrigationRecipe.from_dict",
            side_effect=ValueError,
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        res = storage._load_irrigation_recipes(data)
        assert res == {}
        mock_log_exc.assert_called_once()


def test_storage_load_ipm_presets(storage) -> None:
    """Test _load_ipm_presets and error handling."""
    data = {"ipm_presets": {"i1": {"name": "I1"}}}
    preset = IPMPreset(id="i1", name="I1", items=[], type="foliar")

    with patch(
        "custom_components.growspace_manager.models.IPMPreset.from_dict",
        return_value=preset,
    ):
        res = storage._load_ipm_presets(data)
        assert "i1" in res

    with (
        patch(
            "custom_components.growspace_manager.models.IPMPreset.from_dict",
            side_effect=ValueError,
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        res = storage._load_ipm_presets(data)
        assert res == {}
        mock_log_exc.assert_called_once()


def test_storage_apply_options_dict(storage, repository_mock) -> None:
    """Test applying dict options."""
    gs = Growspace(id="gs1", name="GS1")
    repository_mock.get_all_growspaces.return_value = [gs]
    options = {"gs1": {"temperature_sensor": "sensor.temp"}}
    storage._apply_options_to_growspaces(options)
    assert gs.environment_config.temperature_sensor == "sensor.temp"


def test_storage_load_nutrient_inventory_success(storage) -> None:
    """Test _load_nutrient_inventory success."""
    data = {"nutrient_inventory": {"items": {}}}
    with patch(
        "custom_components.growspace_manager.models.NutrientInventory.from_dict",
        return_value=NutrientInventory(),
    ):
        res = storage._load_nutrient_inventory(data)
        assert isinstance(res, NutrientInventory)


@pytest.mark.asyncio
async def test_storage_backup_corrupt_data_exception(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, storage
) -> None:
    """Test exception handling in _backup_corrupt_data."""
    with (
        patch("pathlib.Path.open", side_effect=PermissionError("No way")),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_logger,
    ):
        # This should log an error but not raise
        storage._backup_corrupt_data("test", {"some": "data"})
        mock_logger.assert_called_once()


def test_get_genetics_data_returns_empty_when_no_manager(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock
) -> None:
    """Test _get_genetics_data returns {} when genetics_manager is None (storage_manager.py:124)."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, genetics_manager=None
    )
    result = storage._get_genetics_data()
    assert result == {}


def test_load_genetics_early_return_when_no_manager(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock
) -> None:
    """Test _load_genetics returns early when genetics_manager is None (storage_manager.py:358)."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, genetics_manager=None
    )
    # Should not raise - early return when genetics_manager is None
    storage._load_genetics({"seed_batches": {}, "pollination_events": {}})


def test_load_genetics_exception_is_caught(
    hass: HomeAssistant,
    repository_mock,
    nutrient_manager_mock,
    genetics_manager_mock,
) -> None:
    """Test _load_genetics catches exceptions and logs them (storage_manager.py:374-375)."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, genetics_manager_mock
    )
    genetics_manager_mock.load_data.side_effect = Exception("Unexpected error")
    # Should not raise - exception is caught and logged
    storage._load_genetics({"seed_batches": {}, "pollination_events": {}})
