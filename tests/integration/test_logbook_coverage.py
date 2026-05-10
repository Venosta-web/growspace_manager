from unittest.mock import ANY, Mock

from custom_components.growspace_manager.const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.logbook import async_describe_events
from homeassistant.core import HomeAssistant


async def test_async_describe_events(hass: HomeAssistant) -> None:
    """Test async_describe_events registers the callback."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    mock_async_describe_event.assert_called_once_with(
        DOMAIN, EVENT_GROWSPACE_LOG_ENTRY, ANY
    )


async def test_log_entry_note(hass: HomeAssistant) -> None:
    """Test log entry description for notes."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    # Simple note
    event = Mock()
    event.data = {
        "category": "note",
        "notes": "Test note",
    }
    result = callback(event)
    assert result["name"] == "Plant Note"
    assert result["message"] == "Test note"

    # Note with tags and images
    event.data = {
        "category": "note",
        "notes": "Test note",
        "tags": ["tag1", "tag2"],
        "images": ["img1.jpg", "img2.jpg"],
    }
    result = callback(event)
    assert result["name"] == "Plant Note"
    assert "Test note [Tags: tag1, tag2 | 2 Images]" in result["message"]

    # Note without message but with extras
    event.data = {
        "category": "note",
        "tags": ["tag1"],
    }
    result = callback(event)
    assert result["name"] == "Plant Note"
    assert result["message"] == "[Tags: tag1]"


async def test_log_entry_watering(hass: HomeAssistant) -> None:
    """Test log entry description for watering."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    # Basic watering
    event = Mock()
    event.data = {"category": "water"}
    result = callback(event)
    assert result["name"] == "Watering"
    assert result["message"] == "Watered"

    # Watering with amount and recipe
    event.data = {
        "category": "watering",
        "amount_ml": 500,
        "recipe": "Veg A",
    }
    result = callback(event)
    assert result["name"] == "Watering"
    assert result["message"] == "Watered 500ml with Veg A"


async def test_log_entry_training(hass: HomeAssistant) -> None:
    """Test log entry description for training."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    # Training logic
    event = Mock()
    event.data = {
        "category": "training",
        "sensor_type": "low_stress_training",
        "notes": "Bent stems",
    }
    result = callback(event)
    assert result["name"] == "Low Stress Training"
    assert result["message"] == "Bent stems"

    # Missing sensor_type
    event.data = {
        "category": "training",
    }
    result = callback(event)
    assert result["name"] == "Training"


async def test_log_entry_ipm(hass: HomeAssistant) -> None:
    """Test log entry description for IPM."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    # IPM logic
    event = Mock()
    event.data = {
        "category": "ipm",
        "sensor_type": "ipm_neem_oil",
        "notes": "Sprayed leaves",
    }
    result = callback(event)
    assert result["name"] == "IPM Treatment"
    assert result["message"] == "Neem Oil: Sprayed leaves"


async def test_log_entry_dehumidifier(hass: HomeAssistant) -> None:
    """Test log entry description for dehumidifier control events."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    event = Mock()

    # Turned ON with detail reasons
    event.data = {
        "category": "dehumidifier",
        "reasons": ["Turned ON", "VPD too low", "High humidity"],
    }
    result = callback(event)
    assert result["name"] == "Dehumidifier Control"
    assert result["message"] == "Turned ON • VPD too low, High humidity"

    # Turned OFF with no detail reasons
    event.data = {
        "category": "dehumidifier",
        "reasons": ["Turned OFF"],
    }
    result = callback(event)
    assert result["name"] == "Dehumidifier Control"
    assert result["message"] == "Turned OFF"

    # No matching action reasons — falls back to "Controlled"
    event.data = {
        "category": "dehumidifier",
        "reasons": ["VPD stable"],
    }
    result = callback(event)
    assert result["name"] == "Dehumidifier Control"
    assert result["message"] == "Controlled • VPD stable"

    # Empty reasons list
    event.data = {"category": "dehumidifier", "reasons": []}
    result = callback(event)
    assert result["name"] == "Dehumidifier Control"
    assert result["message"] == "Controlled"


async def test_log_entry_humidifier(hass: HomeAssistant) -> None:
    """Test log entry description for humidifier control events."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    event = Mock()

    # Turned ON with detail reasons
    event.data = {
        "category": "humidifier",
        "reasons": ["Turned ON", "VPD too high"],
    }
    result = callback(event)
    assert result["name"] == "Humidifier Control"
    assert result["message"] == "Turned ON • VPD too high"

    # Turned OFF with no detail reasons
    event.data = {
        "category": "humidifier",
        "reasons": ["Turned OFF"],
    }
    result = callback(event)
    assert result["name"] == "Humidifier Control"
    assert result["message"] == "Turned OFF"

    # No matching action reasons — falls back to "Controlled"
    event.data = {
        "category": "humidifier",
        "reasons": [],
    }
    result = callback(event)
    assert result["name"] == "Humidifier Control"
    assert result["message"] == "Controlled"


async def test_log_entry_default(hass: HomeAssistant) -> None:
    """Test log entry description for default/fallback."""
    mock_async_describe_event = Mock()
    async_describe_events(hass, mock_async_describe_event)
    callback = mock_async_describe_event.call_args[0][2]

    # Unknown category
    event = Mock()
    event.data = {
        "category": "harvest",
        "notes": "Chopped",
    }
    result = callback(event)
    assert result["name"] == "Growspace Harvest"
    assert result["message"] == "Chopped"

    # No notes, fallback to sensor_type
    event.data = {
        "category": "system",
        "sensor_type": "Alert",
    }
    result = callback(event)
    assert result["name"] == "Growspace System"
    assert result["message"] == "Alert"

    # Fallback to generic message
    event.data = {"category": "unknown"}
    result = callback(event)
    assert result["name"] == "Growspace Unknown"
    assert result["message"] == "Event recorded"
