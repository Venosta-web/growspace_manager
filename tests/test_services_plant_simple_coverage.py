"""Simple coverage tests for services/plant.py and plant_lifecycle_manager.py."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.models import PlantStage
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.services.plant import async_add_timeline_note
from homeassistant.core import HomeAssistant

from .common import create_plant


async def test_transition_closes_existing_history(hass: HomeAssistant) -> None:
    """Test that transitioning a plant closes the previous open history item."""
    coordinator = MagicMock()
    coordinator.plants = {}
    manager = PlantLifecycleManager(coordinator)

    # Setup plant with existing open history
    plant_id = "test_plant"
    plant = create_plant(
        plant_id=plant_id,
        growspace_id="tent",
        strain="Test Strain",
        stage=PlantStage.FLOWER,
        stage_history=[
            {"stage": "seedling", "start": "2023-01-01", "end": "2023-02-01"},
            {"stage": "veg", "start": "2023-02-01", "end": None},  # Open item
        ],
    )
    coordinator.plants[plant_id] = plant

    # Mock async_update_plant to verify the update
    # We patch the method on the instance we created
    manager.async_update_plant = AsyncMock()  # type: ignore[method-assign]
    manager.move_to_dry_growspace = AsyncMock()  # type: ignore[method-assign]

    # Transition
    today = date.today().isoformat()
    await manager.transition_plant_stage(plant_id, PlantStage.FLOWER, date.today())

    # Verify async_update_plant called with updated history
    manager.async_update_plant.assert_called_once()
    call_args = manager.async_update_plant.call_args
    assert call_args[0][0] == plant_id  # arg 0: plant_id
    updates = call_args[1]  # kwargs

    assert "stage_history" in updates
    history = updates["stage_history"]

    # Verify previous item closed
    assert history[1]["stage"] == "veg"
    assert history[1]["end"] == today

    # Verify new item added
    assert history[2]["stage"] == PlantStage.FLOWER
    assert history[2]["start"] == today
    assert history[2]["end"] is None


async def test_add_timeline_note_coverage(hass: HomeAssistant) -> None:
    """Test async_add_timeline_note coverage (ph, ec, amount_ml, entity parsing)."""
    coordinator = MagicMock()
    coordinator.plants = {}
    strain_library = MagicMock()

    plant_id = "test_plant"
    plant = MagicMock()
    plant.growspace_id = "tent"
    coordinator.plants[plant_id] = plant

    growspace = MagicMock()
    # Setup environment config with sensors
    env_config = MagicMock()
    env_config.temperature_sensor = "sensor.temp"  # Valid
    env_config.humidity_sensor = "sensor.hum"  # Invalid value
    env_config.vpd_sensor = None  # Missing entity
    # (Other sensors irrelevant for logical coverage of branches)

    growspace.environment_config = env_config
    coordinator.growspaces = {"tent": growspace}

    # Mock HASS states
    hass.states.async_set("sensor.temp", "25.0")
    hass.states.async_set("sensor.hum", "invalid")

    # Use a listener to verify the event
    events = []

    def capture_event(event):
        events.append(event.data)

    hass.bus.async_listen(EVENT_GROWSPACE_LOG_ENTRY, capture_event)

    # Call with coverage arguments
    await async_add_timeline_note(
        hass,
        coordinator,
        strain_library,
        plant_id=plant_id,
        notes="Coverage test",
        ph=6.5,
        ec=1.2,
        amount_ml=500.0,
        images_base64=None,
        tags=["test"],
    )

    await hass.async_block_till_done()

    assert len(events) == 1
    data = events[0]
    metadata = data["metadata"]

    # Verify coverage of _get_state branches
    assert metadata["temperature"] == 25.0  # Normal path
    assert metadata["humidity"] is None  # ValueError/TypeError path
    assert metadata["vpd"] is None  # None entity_id path

    # Verify coverage of optional args
    assert metadata["ph"] == 6.5
    assert metadata["ec"] == 1.2
    assert metadata["amount_ml"] == 500.0
