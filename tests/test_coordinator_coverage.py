from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    NutrientPreset,
    Plant,
)


@pytest.fixture
def mock_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()
    coord = GrowspaceCoordinator(hass, entry, data={}, strain_library=MagicMock())
    coord.async_save = AsyncMock()
    coord.add_event = MagicMock()
    return coord


@pytest.mark.asyncio
async def test_async_water_plant(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test async_water_plant success path."""
    # Setup
    gs = Growspace(id="gs1", name="Test GS")
    mock_coordinator.growspaces["gs1"] = gs
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="Strain A",
    )
    mock_coordinator.plants["p1"] = plant

    # Test valid watering with nutrients
    updated_plant = await mock_coordinator.async_water_plant(
        "p1", amount=1.5, nutrients={"CalMag": 2.0}
    )

    assert updated_plant.last_watered is not None

    # Verify event logged
    mock_coordinator.add_event.assert_called()
    args = mock_coordinator.add_event.call_args[0]
    assert args[0] == "gs1"
    event = args[1]
    assert event.sensor_type == "irrigation"
    assert "Watered with 1.5L" in event.reasons
    # Verify nutrient string
    assert any("CalMag: 2.0ml/L" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_async_water_plant_preset(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test async_water_plant with preset."""
    gs = Growspace(id="gs1", name="Test GS")
    mock_coordinator.growspaces["gs1"] = gs
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="Strain A",
    )
    mock_coordinator.plants["p1"] = plant

    # Mock preset
    preset = MagicMock(spec=NutrientPreset)
    preset.name = "Test Preset"
    preset.get_nutrient_map.return_value = {"A": 1.0}
    mock_coordinator.nutrient_presets = {"p_set": preset}

    await mock_coordinator.async_water_plant("p1", amount=1.0, preset_id="p_set")

    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert "Preset: Test Preset" in event.reasons


@pytest.mark.asyncio
async def test_async_water_plant_preset_not_found(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_water_plant with missing preset."""
    gs = Growspace(id="gs1", name="Test GS")
    mock_coordinator.growspaces["gs1"] = gs
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="Strain A",
    )
    mock_coordinator.plants["p1"] = plant

    with pytest.raises(KeyError, match="Nutrient preset 'unknown' not found"):
        await mock_coordinator.async_water_plant("p1", amount=1.0, preset_id="unknown")


@pytest.mark.asyncio
async def test_async_log_training_event(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test async_log_training_event."""
    # Setup
    gs = Growspace(id="gs1", name="Test GS")
    mock_coordinator.growspaces["gs1"] = gs
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="Strain A",
    )
    mock_coordinator.plants["p1"] = plant

    # Test logging by growspace_id (Growspace level)
    await mock_coordinator.async_log_training_event(
        growspace_id="gs1", technique="LST", notes="Test note"
    )
    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]

    assert event.category == "training"
    assert "Technique: Lst" in event.reasons

    # Test logging by plant_id (Plant level)
    # Add a SECOND plant to gs1 so that len(plant_ids) < len(all_plants) is True
    plant2 = Plant(plant_id="p2", growspace_id="gs1", strain="Strain B")
    mock_coordinator.plants["p2"] = plant2

    mock_coordinator.add_event.reset_mock()

    await mock_coordinator.async_log_training_event(
        growspace_id=None, technique="Topping", plant_ids=["p1"], notes="Cut top"
    )
    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert any("Plants: Strain A" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_async_water_growspace(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test async_water_growspace."""
    gs = Growspace(id="gs1", name="Test GS")
    mock_coordinator.growspaces["gs1"] = gs
    p1 = Plant(plant_id="p1", growspace_id="gs1", strain="Strain A")
    p2 = Plant(plant_id="p2", growspace_id="gs1", strain="Strain B")
    mock_coordinator.plants["p1"] = p1
    mock_coordinator.plants["p2"] = p2

    # Mock individual water plant calls?
    # Or just let it run (since async_water_plant is mocked/real?)
    # mock_coordinator is mostly real. async_water_plant is real.

    count = await mock_coordinator.async_water_growspace("gs1", amount_per_plant=1.0)
    assert count == 2
    assert p1.last_watered is not None
    assert p2.last_watered is not None


@pytest.mark.asyncio
async def test_nutrient_preset_management(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test save and remove nutrient presets."""
    # Test Create
    nutrients = [{"name": "A", "dose_ml_l": 1.0}]
    preset = await mock_coordinator.async_save_nutrient_preset(
        name="Test Preset", nutrients=nutrients
    )
    assert preset.id in mock_coordinator.nutrient_presets
    assert preset.name == "Test Preset"

    # Test Update
    updated = await mock_coordinator.async_save_nutrient_preset(
        name="Updated Preset", nutrients=nutrients, preset_id=preset.id
    )
    assert updated.id == preset.id
    assert updated.name == "Updated Preset"
    assert mock_coordinator.nutrient_presets[preset.id].name == "Updated Preset"

    # Test Remove
    await mock_coordinator.async_remove_nutrient_preset(preset.id)
    assert preset.id not in mock_coordinator.nutrient_presets

    # Test Remove Missing
    with pytest.raises(KeyError):
        await mock_coordinator.async_remove_nutrient_preset("missing")


@pytest.mark.asyncio
async def test_get_applicable_presets(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test get_applicable_presets filtering."""
    p1 = Plant(
        plant_id="p1",
        growspace_id="gs1",
        strain="Strain A",
        stage="veg",
        veg_start=datetime.now().isoformat(),
    )
    mock_coordinator.plants["p1"] = p1

    # Preset 1: No restrictions
    n1 = NutrientPreset(id="n1", name="Universal", nutrients=[])
    mock_coordinator.nutrient_presets["n1"] = n1

    # Preset 2: Wrong stage
    n2 = NutrientPreset(id="n2", name="Flower Only", nutrients=[], stage="flower")
    mock_coordinator.nutrient_presets["n2"] = n2

    # Preset 3: Correct stage, days requirement (not met)
    # Plant logic for days? Plant needs dates.
    # Provided veg_start=now -> days=0.
    n3 = NutrientPreset(
        id="n3", name="Veg Late", nutrients=[], stage="veg", min_days_in_stage=10
    )
    mock_coordinator.nutrient_presets["n3"] = n3

    # Preset 4: Correct stage, days met
    # Hack: mocked plant returns days? Or modify start date.

    results = mock_coordinator.get_applicable_presets("p1")
    assert n1 in results
    assert n2 not in results
    assert n3 not in results


@pytest.mark.asyncio
async def test_async_log_training_event_error(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_log_training_event missing args."""
    with pytest.raises(
        ValueError, match="Either growspace_id or plant_ids must be provided"
    ):
        await mock_coordinator.async_log_training_event(
            growspace_id=None, technique="LST"
        )


@pytest.mark.asyncio
async def test_async_log_training_event_empty_growspace(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_log_training_event with empty growspace."""
    # Ensure logs still occur even if no plants found?
    # Logic: if not target_plants and growspace_id: growspace_ids = {growspace_id}

    mock_coordinator.get_growspace_plants = MagicMock(return_value=[])

    await mock_coordinator.async_log_training_event(
        growspace_id="gs_empty", technique="LST"
    )

    # Verify event logged for growspace
    mock_coordinator.add_event.assert_called()
    event = mock_coordinator.add_event.call_args[0][1]
    assert event.growspace_id == "gs_empty"
    assert "Technique: Lst" in event.reasons


@pytest.mark.asyncio
async def test_resolve_preset_nutrients(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test _resolve_preset_nutrients helper."""
    # It is private, but we can test it wrapper or directly
    # async_water_plant uses it? Or we call private method

    # Test Missing
    with pytest.raises(KeyError):
        mock_coordinator._resolve_preset_nutrients("missing")
