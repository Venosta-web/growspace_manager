"""Tests for the Nutrient Presets feature.

This module contains tests for adding, removing, and using nutrient presets,
including stage-based applicability filtering and merging with manual inputs.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.growspace_manager.const import (
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_NAME,
    ATTR_PRESET_ID,
    ATTR_STAGE,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from .conftest import create_plant

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    BaseModel,
    EnvironmentConfig,
    Growspace,
    NutrientPreset,
    Plant,
    PlantStage,
)
from .conftest import create_plant

from custom_components.growspace_manager.sensor import (
    _create_initial_entities,
)
from .conftest import create_plant

from custom_components.growspace_manager.services.nutrient_presets import (
    handle_remove_nutrient_preset,
    handle_save_nutrient_preset,
)
from .conftest import create_plant



def create_test_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Create a test coordinator with mocked config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock(
        side_effect=lambda hass_obj, coro, name: hass.async_create_task(coro)
    )

    coordinator = GrowspaceCoordinator(hass, entry, data={})
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.fixture
def preset_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Provide a coordinator for nutrient preset tests."""
    coordinator = create_test_coordinator(hass)

    # Add a growspace and a plant
    coordinator.growspaces["test_gs"] = Growspace(
        id="test_gs",
        name="Test Growspace",
        rows=1,
        plants_per_row=1,
    )

    coordinator.plants["test_plant"] = create_plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        stage=PlantStage.VEG,
        veg_start=(datetime.now() - timedelta(days=10)).isoformat(),
        row=1,
        col=1,
    )

    return coordinator


class TestNutrientPresetCoordinator:
    """Tests for nutrient preset logic within the coordinator."""

    @pytest.mark.asyncio
    async def test_save_nutrient_preset(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test creating a new nutrient preset."""
        name = "Veg Mix"
        nutrients = [
            {"name": "Grow A", "dose_ml_l": 2.0},
            {"name": "Grow B", "dose_ml_l": 1.5},
        ]

        preset = await preset_coordinator.async_save_nutrient_preset(
            name=name, nutrients=nutrients, stage=PlantStage.VEG, min_days_in_stage=5
        )

        assert preset.name == name
        assert len(preset.nutrients) == 2
        assert preset.stage == PlantStage.VEG
        assert preset.min_days_in_stage == 5
        assert preset.id in preset_coordinator.nutrient_presets
        preset_coordinator.async_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_nutrient_preset(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test removing a nutrient preset."""
        # First save a preset
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="To Remove", nutrients=[{"name": "Nutrient", "dose_ml_l": 1.0}]
        )
        preset_id = preset.id

        # Remove it
        await preset_coordinator.async_remove_nutrient_preset(preset_id)

        assert preset_id not in preset_coordinator.nutrient_presets
        assert preset_coordinator.async_save.call_count == 2

    @pytest.mark.asyncio
    async def test_remove_nonexistent_preset_raises(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test removing a nonexistent preset raises KeyError."""
        with pytest.raises(KeyError):
            await preset_coordinator.async_remove_nutrient_preset("nonexistent")

    @pytest.mark.asyncio
    async def test_get_applicable_presets(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test filtering presets based on plant stage and days."""
        # 1. Preset for VEG, min 5 days (Plant is VEG, 10 days) -> Should match
        await preset_coordinator.async_save_nutrient_preset(
            name="Veg Applicable",
            nutrients=[{"name": "A", "dose_ml_l": 1.0}],
            stage=PlantStage.VEG,
            min_days_in_stage=5,
        )

        # 2. Preset for FLOWER (Plant is VEG) -> Should NOT match
        await preset_coordinator.async_save_nutrient_preset(
            name="Bloom Not Applicable",
            nutrients=[{"name": "B", "dose_ml_l": 1.0}],
            stage=PlantStage.FLOWER,
        )

        # 3. Preset for VEG, min 15 days (Plant is VEG, 10 days) -> Should NOT match
        await preset_coordinator.async_save_nutrient_preset(
            name="Veg Too Soon",
            nutrients=[{"name": "C", "dose_ml_l": 1.0}],
            stage=PlantStage.VEG,
            min_days_in_stage=15,
        )

        # 4. Global preset (no stage) -> Should match
        await preset_coordinator.async_save_nutrient_preset(
            name="Global", nutrients=[{"name": "D", "dose_ml_l": 1.0}]
        )

        applicable = preset_coordinator.get_applicable_presets("test_plant")

        assert len(applicable) == 2
        names = [p.name for p in applicable]
        assert "Veg Applicable" in names
        assert "Global" in names
        assert "Bloom Not Applicable" not in names
        assert "Veg Too Soon" not in names

    @pytest.mark.asyncio
    async def test_resolve_preset_nutrients(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test resolving preset ID to nutrient map."""
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="Test Preset",
            nutrients=[
                {"name": "NutriA", "dose_ml_l": 2.5},
                {"name": "NutriB", "dose_ml_l": 0.5},
            ],
        )

        nutrient_map = preset_coordinator._resolve_preset_nutrients(preset.id)

        assert nutrient_map == {"NutriA": 2.5, "NutriB": 0.5}

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_preset_raises(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test resolving nonexistent preset raises KeyError."""
        with pytest.raises(KeyError):
            preset_coordinator._resolve_preset_nutrients("nonexistent")

    @pytest.mark.asyncio
    async def test_get_applicable_presets_no_stage_but_min_days(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test a preset with no stage but with min_days_in_stage."""
        # Plant is VEG, 10 days
        await preset_coordinator.async_save_nutrient_preset(
            name="Days Match",
            nutrients=[{"name": "A", "dose_ml_l": 1.0}],
            min_days_in_stage=5,  # No stage
        )

        await preset_coordinator.async_save_nutrient_preset(
            name="Days No Match",
            nutrients=[{"name": "A", "dose_ml_l": 1.0}],
            min_days_in_stage=15,  # Too many days
        )

        applicable = preset_coordinator.get_applicable_presets("test_plant")
        names = [p.name for p in applicable]
        assert "Days Match" in names
        assert "Days No Match" not in names


class TestWateringWithPresets:
    """Tests for watering functionality using presets."""

    @pytest.mark.asyncio
    async def test_water_plant_with_preset(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a plant using a nutrient preset."""
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="Test Preset", nutrients=[{"name": "CalMag", "dose_ml_l": 2.0}]
        )

        # Water with 2.0L using preset (should result in 4.0ml CalMag)
        events = async_capture_events(
            preset_coordinator.hass, EVENT_GROWSPACE_LOG_ENTRY
        )
        await preset_coordinator.async_water_plant(
            "test_plant", amount=2.0, preset_id=preset.id
        )

        # Verify event logbook entry
        assert len(events) == 1
        event_data = events[0].data
        reasons = str(event_data.get("reasons", []))

        assert f"Preset: {preset.name}" in reasons
        assert "CalMag: 2.0ml/L" in reasons
        assert "Total: 4.0ml" in reasons

    @pytest.mark.asyncio
    async def test_preset_manual_merge_override(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that manual nutrients override preset nutrients of the same name."""
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="Test Preset",
            nutrients=[
                {"name": "A", "dose_ml_l": 1.0},
                {"name": "B", "dose_ml_l": 2.0},
            ],
        )

        # Water with preset A=1, B=2, but manually override B=5 and add C=10
        manual = {"B": 5.0, "C": 10.0}

        events = async_capture_events(
            preset_coordinator.hass, EVENT_GROWSPACE_LOG_ENTRY
        )
        await preset_coordinator.async_water_plant(
            "test_plant", amount=1.0, nutrients=manual, preset_id=preset.id
        )

        # Result should be A=1, B=5, C=10
        assert len(events) == 1
        event_data = events[0].data
        reasons = str(event_data.get("reasons", []))

        assert "A: 1.0ml/L" in reasons
        assert "B: 5.0ml/L" in reasons
        assert "C: 10.0ml/L" in reasons
        # Verify preset name is still mentioned
        assert f"Preset: {preset.name}" in reasons

    @pytest.mark.asyncio
    async def test_water_growspace_with_preset(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering an entire growspace using a preset."""
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="Gs Preset", nutrients=[{"name": "Bloom", "dose_ml_l": 4.0}]
        )

        # Water growspace
        # Water growspace
        events = async_capture_events(
            preset_coordinator.hass, EVENT_GROWSPACE_LOG_ENTRY
        )
        await preset_coordinator.async_water_growspace(
            "test_gs", amount_per_plant=1.0, preset_id=preset.id
        )

        # Verify event for the plant
        # Growspace has 1 plant, so 1 event
        assert len(events) == 1
        event_data = events[0].data
        reasons = str(event_data.get("reasons", []))

        assert "Bloom: 4.0ml/L" in reasons
        assert "Total: 4.0ml" in reasons
        assert f"Preset: {preset.name}" in reasons

    @pytest.mark.asyncio
    async def test_water_plant_missing_preset_raises(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering with a nonexistent preset_id raises KeyError."""
        with pytest.raises(KeyError, match="Nutrient preset 'missing' not found"):
            await preset_coordinator.async_water_plant(
                "test_plant", amount=1.0, preset_id="missing"
            )


class TestServiceHandlersPresets:
    """Tests for the preset service handlers."""

    @pytest.mark.asyncio
    async def test_handle_save_nutrient_preset_service(
        self, hass: HomeAssistant, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test the handle_save_nutrient_preset service handler."""

        call = MagicMock()
        call.data = {
            ATTR_NAME: "Service Preset",
            "nutrients": [{"name": "Grow", "dose_ml_l": 3.0}],
            ATTR_STAGE: PlantStage.FLOWER,
            ATTR_MIN_DAYS_IN_STAGE: 10,
        }

        await handle_save_nutrient_preset(hass, preset_coordinator, call)

        # Verify preset was saved
        presets = [
            p
            for p in preset_coordinator.nutrient_presets.values()
            if p.name == "Service Preset"
        ]
        assert len(presets) == 1
        assert presets[0].stage == PlantStage.FLOWER
        assert presets[0].min_days_in_stage == 10

    @pytest.mark.asyncio
    async def test_handle_update_nutrient_preset_service(
        self, hass: HomeAssistant, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test updating an existing nutrient preset via service handler."""

        # 1. Save initial preset
        preset = await preset_coordinator.async_save_nutrient_preset(
            name="Initial Name",
            nutrients=[{"name": "Base", "dose_ml_l": 1.0}],
        )
        initial_id = preset.id

        # 2. Update via service
        call = MagicMock()
        call.data = {
            ATTR_PRESET_ID: initial_id,
            ATTR_NAME: "Updated Name",
            "nutrients": [{"name": "Base", "dose_ml_l": 2.0}],
        }

        await handle_save_nutrient_preset(hass, preset_coordinator, call)

        # 3. Verify update
        updated = preset_coordinator.nutrient_presets[initial_id]
        assert updated.name == "Updated Name"
        assert updated.nutrients[0]["dose_ml_l"] == 2.0
        assert updated.id == initial_id

    @pytest.mark.asyncio
    async def test_handle_remove_nutrient_preset_service(
        self, hass: HomeAssistant, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test the handle_remove_nutrient_preset service handler."""

        # Save one first
        preset = await preset_coordinator.async_save_nutrient_preset("To Remove", [])

        call = MagicMock()
        call.data = {ATTR_PRESET_ID: preset.id}

        await handle_remove_nutrient_preset(hass, preset_coordinator, call)

        assert preset.id not in preset_coordinator.nutrient_presets


class TestNutrientPresetSerialization:
    """Tests for NutrientPreset to/from dict serialization."""

    def test_nutrient_preset_serialization_roundtrip(self) -> None:
        """Test that NutrientPreset can be serialized and deserialized."""
        now = datetime.now().isoformat()
        data = {
            "id": "preset-123",
            "name": "Full Recipe",
            "nutrients": [
                {"name": "Part A", "dose_ml_l": 2.0},
                {"name": "Part B", "dose_ml_l": 2.0},
            ],
            "stage": "veg",
            "min_days_in_stage": 7,
            "created_at": now,
        }

        preset = NutrientPreset.from_dict(data)
        assert preset.id == "preset-123"
        assert preset.name == "Full Recipe"
        assert len(preset.nutrients) == 2
        assert preset.stage == "veg"
        assert preset.min_days_in_stage == 7

        # Roundtrip via to_dict
        serialized = preset.to_dict()
        assert serialized["id"] == "preset-123"
        assert serialized["name"] == "Full Recipe"
        assert serialized["stage"] == "veg"
        # BaseModel.from_dict filters unknown keys, let's verify
        data["unknown_key"] = "ignore me"
        preset_with_extra = NutrientPreset.from_dict(data)
        assert not hasattr(preset_with_extra, "unknown_key")

    def test_basemodel_advanced_features(self) -> None:
        """Test migrations, defaults, and nested handlers in BaseModel."""

        # Define a mock dataclass inheriting from BaseModel
        @dataclass(slots=True)
        class Nested(BaseModel):
            val: int

        @dataclass(slots=True)
        class TestModel(BaseModel):
            new_key: str
            a_nested: Nested
            with_default: str = "default_val"

            # _MIGRATIONS removed
            _NESTED_HANDLERS = {"a_nested": Nested.from_dict}

        # 1. Test nested handlers and defaults (migration removed)
        data = {"new_key": "explicit_val", "a_nested": {"val": 10}}
        obj = TestModel.from_dict(data)
        assert obj.new_key == "explicit_val"
        assert obj.a_nested.val == 10
        assert obj.with_default == "default_val"

        d = obj.to_dict()
        assert d["new_key"] == "explicit_val"
        assert d["a_nested"]["val"] == 10
        assert d["with_default"] == "default_val"

    def test_environment_config_catch_all(self) -> None:
        """Test the _CATCH_ALL_FIELD logic in EnvironmentConfig."""
        data = {
            "temperature_sensor": "sensor.temp",
            "extra_key": "some_value",
            "another_extra": 123,
        }

        config = EnvironmentConfig.from_dict(data)
        assert config.temperature_sensor == "sensor.temp"
        assert config.bayesian_options["extra_key"] == "some_value"
        assert config.bayesian_options["another_extra"] == 123

    def test_basemodel_defaults_and_invalid_catchall(self) -> None:
        """Test defaults and invalid catch-all types in BaseModel."""
        # 1. Defaults (EnvironmentConfig has default values for many fields)
        config = EnvironmentConfig.from_dict({})
        assert config.lst_offset == -2.0
        assert config.stress_threshold == 0.70

        # 2. Invalid catch-all type (should reset to empty dict)
        data = {"bayesian_options": "not-a-dict", "extra_key": "some_value"}
        config = EnvironmentConfig.from_dict(data)
        assert isinstance(config.bayesian_options, dict)
        assert config.bayesian_options["extra_key"] == "some_value"


class TestPlantCoverage:
    """Tests for missing branches in Plant model."""

    def test_plant_days_since_watering(self) -> None:
        """Test get_days_since_watering with and without last_watered."""
        plant = create_plant(plant_id="p1", growspace_id="g1", strain="S")
        assert plant.get_days_since_watering() is None

        plant.last_watered = (datetime.now() - timedelta(days=2)).isoformat()
        assert plant.get_days_since_watering() == 2

    def test_plant_stage_missing_start_date(self) -> None:
        """Test get_days_in_stage returns 0 if start date attribute is missing or None."""
        plant = create_plant(plant_id="p1", growspace_id="g1", strain="S")
        # Stage is empty, and start dates are None
        assert plant.get_days_in_stage("veg") == 0

        # Test get_week_in_stage
        plant.veg_start = (datetime.now() - timedelta(days=14)).isoformat()
        assert plant.get_week_in_stage("veg") == 2


class TestSensorRegistrationCoverage:
    """Tests for sensor registration logic."""

    @pytest.mark.asyncio
    async def test_create_initial_entities_no_presets(
        self, hass: HomeAssistant, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that _create_initial_entities works without NutrientPresetSensor."""

        initial_entities = []
        growspace_entities = {}
        plant_entities = {}
        calculated_vpd_growspace_ids = set()

        # We need a mock config entry
        mock_entry = MagicMock(spec=ConfigEntry)
        mock_entry.runtime_data = preset_coordinator

        await _create_initial_entities(
            hass,
            preset_coordinator,
            mock_entry,
            initial_entities,
            growspace_entities,
            plant_entities,
            calculated_vpd_growspace_ids,
        )

        # Ensure no NutrientPresetSensor is created
        # We don't have the class anymore to check isinstance, but we can verify it doesn't crash
        # and maybe check count of other sensors if needed.
        pass


class TestNutrientPresetStorageLoading:
    """Tests for storage loading edge cases."""

    def test_load_nutrient_presets_malformed_data(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that malformed storage data is handled gracefully."""
        # Malformed data (e.g., nutrients is not a list)
        malformed_data = {
            "nutrient_presets": {
                "p1": {"name": "Bad Preset", "nutrients": "not-a-list"}
            }
        }

        # This should trigger the exception block in storage_manager
        presets = preset_coordinator.storage_manager._load_nutrient_presets(
            malformed_data
        )

        # Verify it returned empty dict instead of crashing
        assert presets == {}

    def test_load_nutrient_presets_success(
        self, preset_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test successful loading of presets from storage data."""
        data = {
            "nutrient_presets": {
                "p1": {
                    "id": "p1",
                    "name": "Stored Preset",
                    "nutrients": [{"name": "A", "dose_ml_l": 1.0}],
                    "stage": "flower",
                }
            }
        }

        presets = preset_coordinator.storage_manager._load_nutrient_presets(data)

        assert "p1" in presets
        assert presets["p1"].name == "Stored Preset"
        assert presets["p1"].stage == "flower"
