from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import CATEGORY_IPM, DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    IPMPreset,
    Plant,
)


@pytest.fixture
def mock_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coord = GrowspaceCoordinator(hass, entry, data={}, strain_library=MagicMock())
    coord.async_save = AsyncMock()
    # Ensure properties are initialized
    coord.ipm_presets = {}
    coord.plants = {}
    coord.growspaces = {}
    coord.events = {}
    coord._serialized_cache = {}
    return coord


@pytest.mark.asyncio
async def test_async_save_ipm_preset(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test creating and updating an IPM preset."""
    # Test Create
    items = [{"name": "Neem Oil", "dose_amount": 5.0, "dose_unit": "ml/L"}]
    preset = await mock_coordinator.async_save_ipm_preset(
        name="Bug Free", type="foliar", items=items, stage="veg", min_days_in_stage=0
    )

    assert preset.id in mock_coordinator.ipm_presets
    assert mock_coordinator.ipm_presets[preset.id].name == "Bug Free"
    assert mock_coordinator.ipm_presets[preset.id].items == items
    mock_coordinator.async_save.assert_called()

    # Test Update
    updated_items = [{"name": "Neem Oil", "dose_amount": 10.0, "dose_unit": "ml/L"}]
    updated_preset = await mock_coordinator.async_save_ipm_preset(
        name="Bug Free V2", type="drench", items=updated_items, preset_id=preset.id
    )

    assert updated_preset.id == preset.id
    assert mock_coordinator.ipm_presets[preset.id].name == "Bug Free V2"
    assert mock_coordinator.ipm_presets[preset.id].type == "drench"
    assert mock_coordinator.ipm_presets[preset.id].items == updated_items


@pytest.mark.asyncio
async def test_async_remove_ipm_preset(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test removing an IPM preset."""
    # Setup
    mock_coordinator.ipm_presets = {
        "ipm1": IPMPreset(id="ipm1", name="Delete Me", type="foliar", items=[])
    }

    # Test Remove
    await mock_coordinator.async_remove_ipm_preset("ipm1")
    assert "ipm1" not in mock_coordinator.ipm_presets
    mock_coordinator.async_save.assert_called()

    # Test Missing
    with pytest.raises(KeyError):
        await mock_coordinator.async_remove_ipm_preset("ipm1")


@pytest.mark.asyncio
async def test_async_apply_ipm_to_growspace(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test applying IPM to an entire growspace."""
    # Setup
    gs = Growspace(id="gs1", name="Veg Tent")
    mock_coordinator.growspaces["gs1"] = gs

    p1 = Plant(plant_id="p1", growspace_id="gs1", strain="Strain A")
    p2 = Plant(plant_id="p2", growspace_id="gs1", strain="Strain B")
    mock_coordinator.plants = {"p1": p1, "p2": p2}

    preset = IPMPreset(
        id="ipm1",
        name="Weekly Maintenance",
        type="foliar",
        items=[{"name": "Soap", "dose_amount": 1.0, "dose_unit": "tbsp"}],
    )
    mock_coordinator.ipm_presets["ipm1"] = preset

    # Execute
    affected = await mock_coordinator.async_apply_ipm("ipm1", growspace_id="gs1")

    # Verify return
    assert set(affected) == {"p1", "p2"}

    # Verify Plant Updates
    assert p1.last_ipm is not None
    assert p1.last_ipm_type == "foliar"
    assert p2.last_ipm is not None

    # Verify Events
    assert "gs1" in mock_coordinator.events
    event = mock_coordinator.events["gs1"][0]
    assert event.category == CATEGORY_IPM
    assert event.sensor_type == "ipm_foliar"
    assert "IPM Treatment: Weekly Maintenance" in event.reasons
    assert "Recipe: Soap (1.0tbsp)" in event.reasons
    # Verify Plant ID tracking for timeline filtering
    assert "plant_id:p1" in event.reasons
    assert "plant_id:p2" in event.reasons


@pytest.mark.asyncio
async def test_async_apply_ipm_to_plants(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test applying IPM to specific plants."""
    # Setup
    gs = Growspace(id="gs1", name="Veg Tent")
    mock_coordinator.growspaces["gs1"] = gs

    p1 = Plant(plant_id="p1", growspace_id="gs1", strain="Strain A")
    p2 = Plant(plant_id="p2", growspace_id="gs1", strain="Strain B")
    mock_coordinator.plants = {"p1": p1, "p2": p2}

    preset = IPMPreset(id="ipm1", name="Spot Treat", type="drench", items=[])
    mock_coordinator.ipm_presets["ipm1"] = preset

    # Execute - Only p1
    affected = await mock_coordinator.async_apply_ipm(
        "ipm1", plant_ids=["p1"], notes="Mites found"
    )

    # Verify
    assert affected == ["p1"]
    assert p1.last_ipm is not None
    assert p1.last_ipm_type == "drench"
    assert p2.last_ipm is None  # p2 untouched

    # Verify Event checks "Plants: ..." context
    event = mock_coordinator.events["gs1"][0]
    assert "Plants: Strain A" in event.reasons
    assert "Notes: Mites found" in event.reasons
    # Verify Plant ID tracking
    assert "plant_id:p1" in event.reasons
    assert "plant_id:p2" not in event.reasons


@pytest.mark.asyncio
async def test_async_apply_ipm_errors(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test error handling in apply_ipm."""
    preset = IPMPreset(id="ipm1", name="Test", type="foliar", items=[])
    mock_coordinator.ipm_presets["ipm1"] = preset

    # No target
    with pytest.raises(ValueError):
        await mock_coordinator.async_apply_ipm("ipm1")

    # Missing preset
    with pytest.raises(KeyError):
        await mock_coordinator.async_apply_ipm("missing_id", growspace_id="gs1")
