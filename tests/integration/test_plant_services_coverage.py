"""Test plant services coverage."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_IMAGES,
    ATTR_METADATA,
    ATTR_NOTES,
    ATTR_TAGS,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.plant import (
    async_add_timeline_note,
    handle_add_plants,
    handle_add_timeline_note,
    handle_harvest_plant,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


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


@pytest.mark.asyncio
async def test_add_timeline_note_images(tmp_path: Path) -> None:
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
    fallback_path = tmp_path / "image.jpg"
    image_manager.save_timeline_image.return_value = str(fallback_path)
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
    assert data[ATTR_IMAGES] == [f"timeline/{fallback_path.name}"]

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


@pytest.mark.asyncio
async def test_handle_add_plants_success(
    hass: HomeAssistant,
) -> None:
    """Test handle_add_plants service."""
    mock_coordinator = MagicMock()
    mock_coordinator.plant_manager = MagicMock()
    mock_coordinator.plant_manager.add_plant = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    mock_strain_library = MagicMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {
        "growspace_id": "gs1",
        "strain": "Strain A",
        "amount": 2,
        "start_number": 10,
    }

    await handle_add_plants(hass, mock_coordinator, mock_strain_library, mock_call)

    assert mock_coordinator.plant_manager.add_plant.call_count == 2
    # Check that phenotype uses start_number
    args = mock_coordinator.plant_manager.add_plant.call_args_list[0].kwargs
    assert args["phenotype"] == "Strain A #10"


@pytest.mark.asyncio
async def test_add_timeline_note_extra_metadata() -> None:
    """Test async_add_timeline_note with ph, ec, amount_ml and corrupt sensors."""
    hass = MagicMock()
    coordinator = MagicMock()
    strain_library = MagicMock()

    plant_mock = MagicMock()
    plant_mock.growspace_id = "gs1"
    coordinator.plants = {"plant1": plant_mock}

    growspace_mock = MagicMock()
    env_config = MagicMock()
    env_config.temperature_sensor = "sensor.temp"
    env_config.humidity_sensor = None  # Trigger 759
    growspace_mock.environment_config = env_config
    coordinator.growspaces = {"gs1": growspace_mock}

    # Mock corrupt state
    state = MagicMock()
    state.state = "NOT_A_NUMBER"
    hass.states.get.return_value = state

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
            notes="Test extras",
            ph=6.0,
            ec=1.2,
            amount_ml=500.0,
        )

    data = hass.bus.async_fire.call_args[0][1]
    metadata = data[ATTR_METADATA]
    assert metadata["ph"] == 6.0
    assert metadata["ec"] == 1.2
    assert metadata["amount_ml"] == 500.0
    assert metadata["temperature"] is None  # Failed conversion (764-765)
    assert metadata["humidity"] is None  # Missing sensor (759)


@pytest.mark.asyncio
async def test_handle_add_timeline_note_service() -> None:
    """Test handle_add_timeline_note service entry point."""
    hass = MagicMock()
    coordinator = MagicMock()
    strain_library = MagicMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"plant_id": "plant1", "notes": "Service call note"}

    with patch(
        "custom_components.growspace_manager.services.plant.async_add_timeline_note"
    ) as mock_logic:
        await handle_add_timeline_note(hass, coordinator, strain_library, mock_call)
        mock_logic.assert_called_once()


@pytest.mark.asyncio
async def test_handle_harvest_plant_not_loaded() -> None:
    """Test handle_harvest_plant when plant cannot be loaded."""
    hass = MagicMock()
    coordinator = MagicMock()
    strain_library = MagicMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"plant_id": "missing_plant"}

    with patch(
        "custom_components.growspace_manager.services.plant._ensure_plant_loaded",
        return_value=False,
    ):
        result = await handle_harvest_plant(
            hass, coordinator, strain_library, mock_call
        )
        assert result is None


@pytest.mark.asyncio
async def test_handle_add_plants_errors(hass: HomeAssistant) -> None:
    """Test handle_add_plants error paths."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    mock_call = MagicMock(spec=ServiceCall)

    # 1. Growspace not found (245-246)
    mock_call.data = {"growspace_id": "missing", "strain": "S1", "amount": 1}
    with pytest.raises(ServiceValidationError, match=".*does not exist.*"):
        await handle_add_plants(hass, mock_coordinator, MagicMock(), mock_call)

    # 2. GrowspaceError during add (297-299)
    mock_call.data = {"growspace_id": "gs1", "strain": "S1", "amount": 2}
    mock_coordinator.plant_manager.add_plant = AsyncMock(
        side_effect=GrowspaceError("Fail")
    )
    await handle_add_plants(hass, mock_coordinator, MagicMock(), mock_call)
    assert (
        mock_coordinator.plant_manager.add_plant.call_count == 1
    )  # Stopped after first error

    # 3. Unexpected exception (308-310)
    mock_coordinator.validator.find_first_available_position.side_effect = Exception(
        "Boom"
    )
    with pytest.raises(ServiceValidationError, match="Failed to batch add plants"):
        await handle_add_plants(hass, mock_coordinator, MagicMock(), mock_call)


@pytest.mark.asyncio
async def test_handle_add_plants_full(hass: HomeAssistant) -> None:
    """Test handle_add_plants when growspace is full (276-284)."""
    mock_coordinator = MagicMock()
    mock_coordinator.plant_manager = MagicMock()
    mock_coordinator.plant_manager.add_plant = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"growspace_id": "gs1", "strain": "S1", "amount": 2}

    # Case: Full from the start (282)
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)
    with pytest.raises(ServiceValidationError, match=".*is full.*"):
        await handle_add_plants(hass, mock_coordinator, MagicMock(), mock_call)

    # Case: Becomes full during batch (284)
    # 1. find_first_available_position (initial check)
    # 2. find_first_available_position (first plant)
    # 3. find_first_available_position (second plant - returns None)
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0),
        (0, 0),
        (None, None),
    ]
    await handle_add_plants(hass, mock_coordinator, MagicMock(), mock_call)
    assert mock_coordinator.plant_manager.add_plant.call_count == 1
