"""Test plant services coverage."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from custom_components.growspace_manager.const import (
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_TAGS,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.services.plant import async_add_timeline_note


async def test_add_timeline_note_defaults() -> None:
    """Test async_add_timeline_note with default arguments."""
    hass = MagicMock()
    coordinator = MagicMock()
    strain_library = MagicMock()

    # Mock plant and growspace
    plant_mock = MagicMock()
    plant_mock.growspace_id = "gs1"
    coordinator.plants = {"plant1": plant_mock}
    # Ensure get returns None properly if key missing (standard dict behavior)
    coordinator.growspaces = {}

    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded"
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="plant1",
        ),
    ):
        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id="plant1",
            notes="Test note",
        )

    # Verify event fired with defaults
    hass.bus.async_fire.assert_called_once()
    call_args = hass.bus.async_fire.call_args
    assert call_args[0][0] == EVENT_GROWSPACE_LOG_ENTRY
    data = call_args[0][1]
    assert data[ATTR_NOTES] == "Test note"
    assert data[ATTR_IMAGES] == []
    assert data[ATTR_TAGS] == []
    assert data[ATTR_METADATA] == {}


async def test_add_timeline_note_sensor_snapshot() -> None:
    """Test async_add_timeline_note capturing sensor data."""
    hass = MagicMock()
    coordinator = MagicMock()
    strain_library = MagicMock()

    plant_mock = MagicMock()
    plant_mock.growspace_id = "gs1"
    coordinator.plants = {"plant1": plant_mock}

    growspace_mock = MagicMock()
    env_config = MagicMock()
    env_config.temperature_sensor = "sensor.temp"
    env_config.humidity_sensor = "sensor.hum"
    growspace_mock.environment_config = env_config
    coordinator.growspaces = {"gs1": growspace_mock}

    # Set up states
    def get_state(entity_id):
        state = MagicMock()
        if entity_id == "sensor.temp":
            state.state = "25.5"
        elif entity_id == "sensor.hum":
            state.state = "60.0"
        else:
            return None
        return state

    hass.states.get.side_effect = get_state

    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded"
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="plant1",
        ),
    ):
        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id="plant1",
            notes="Test sensors",
        )

    data = hass.bus.async_fire.call_args[0][1]
    metadata = data[ATTR_METADATA]
    assert metadata["temperature"] == 25.5
    assert metadata["humidity"] == 60.0
    assert metadata["vpd"] is None  # Not set


async def test_add_timeline_note_images() -> None:
    """Test async_add_timeline_note image processing."""
    hass = MagicMock()
    coordinator = MagicMock()

    strain_library = MagicMock()
    image_manager = MagicMock()
    # Configure save_timeline_image as AsyncMock
    image_manager.save_timeline_image = AsyncMock()

    type(strain_library).image_manager = PropertyMock(return_value=image_manager)
    strain_library.image_manager = image_manager

    plant_mock = MagicMock()
    plant_mock.growspace_id = "gs1"
    coordinator.plants = {"plant1": plant_mock}
    coordinator.growspaces = {}

    # Case 1: Normal save
    image_manager.save_timeline_image.return_value = (
        "/config/growspace/timeline/image.webp"
    )

    hass.bus.async_fire.reset_mock()

    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded"
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="plant1",
        ),
    ):
        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id="plant1",
            notes="Img note",
            images_base64=["base64data"],
        )

    assert hass.bus.async_fire.called
    data = hass.bus.async_fire.call_args[0][1]
    assert data[ATTR_IMAGES] == ["timeline/image.webp"]

    # Case 2: Save returns path without /timeline/ (fallback)
    image_manager.save_timeline_image.return_value = "/tmp/image.jpg"
    hass.bus.async_fire.reset_mock()

    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded"
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="plant1",
        ),
    ):
        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id="plant1",
            notes="Img note 2",
            images_base64=["base64data"],
        )

    data = hass.bus.async_fire.call_args[0][1]
    assert data[ATTR_IMAGES] == ["timeline/image.jpg"]

    # Case 3: Exception during save
    image_manager.save_timeline_image.side_effect = Exception("Save failed")
    hass.bus.async_fire.reset_mock()

    with (
        patch(
            "custom_components.growspace_manager.services.plant._ensure_plant_loaded"
        ),
        patch(
            "custom_components.growspace_manager.services.plant._resolve_plant_id",
            return_value="plant1",
        ),
    ):
        await async_add_timeline_note(
            hass,
            coordinator,
            strain_library,
            plant_id="plant1",
            notes="Img failure",
            images_base64=["base64data"],
        )

    data = hass.bus.async_fire.call_args[0][1]
    assert data[ATTR_IMAGES] == []  # Should be empty since save failed
