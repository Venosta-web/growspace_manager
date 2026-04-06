"""Tests for Niimbot label printing services."""

import base64
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
import pytest

from custom_components.growspace_manager.services.strain_library import (
    handle_add_strain,
    handle_print_label,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_hass():
    """Fixture for a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.plants = {}
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
async def strain_library(mock_hass):
    """Fixture for a StrainLibrary instance with in-memory DB."""
    with (
        patch("custom_components.growspace_manager.strain_library.ImageManager"),
        patch("custom_components.growspace_manager.strain_library.ImportExportManager"),
        patch("aiosqlite.connect", return_value=AsyncMock()),
    ):
        library = StrainLibrary(mock_hass)
        library.add_strain = AsyncMock()
        library.load = AsyncMock()
        library.get_all = MagicMock(return_value={})
        return library


@pytest.mark.asyncio
async def test_handle_add_strain_with_breeder_logo(
    mock_hass, mock_coordinator, strain_library
) -> None:
    """Test handle_add_strain service with breeder_logo."""
    call = MagicMock()
    call.data = {
        "strain": "Test Strain",
        "breeder": "Test Breeder",
        "breeder_logo": "https://example.com/logo.png",
    }

    await handle_add_strain(mock_hass, mock_coordinator, strain_library, call)

    strain_library.add_strain.assert_awaited_once_with(
        strain="Test Strain",
        phenotype=None,
        breeder="Test Breeder",
        breeder_logo="https://example.com/logo.png",
        strain_type=None,
        lineage=None,
        sex=None,
        flower_days_min=None,
        flower_days_max=None,
        description=None,
        image_base64=None,
        image_path=None,
        image_crop_meta=None,
        sativa_percentage=None,
        indica_percentage=None,
    )
    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_print_label(mock_hass, mock_coordinator, strain_library) -> None:
    """Test handle_print_label service constructs correct payload."""
    # Mock plant data
    plant_id = "plant_1"
    mock_plant = MagicMock()
    mock_plant.genetics.strain_name = "Blue Dream"
    mock_plant.genetics.phenotype_name = "Berry"
    mock_coordinator.plants = {plant_id: mock_plant}

    # Mock strain library meta
    strain_library.get_all.return_value = {
        "Blue Dream": {
            "meta": {
                "breeder": "Humboldt",
                "breeder_logo": "https://example.com/humboldt.png",
            },
            "phenotypes": {"Berry": {}},
        }
    }

    call = MagicMock()
    call.data = {"plant_id": plant_id, "device_id": "printer_1", "preview": True}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://homeassistant.local",
    ):
        await handle_print_label(mock_hass, mock_coordinator, strain_library, call)

    # Verify niimbot.print service call
    mock_hass.services.async_call.assert_awaited_once()
    args, _ = mock_hass.services.async_call.call_args
    assert args[0] == "niimbot"
    assert args[1] == "print"

    service_data = args[2]
    assert service_data["device_id"] == "printer_1"
    assert service_data["preview"] is True

    payload = service_data["payload"]
    # Check for core fields in payload
    values = [item["value"] for item in payload if "value" in item]
    assert "BLUE DREAM" in values
    assert "Berry\nHumboldt\n-" in values

    # Check for breeder logo
    logo_item = next((item for item in payload if item["type"] == "dlimg"), None)
    assert logo_item is not None
    assert logo_item["url"] == "https://example.com/humboldt.png"
    assert logo_item["xsize"] == 100
    assert logo_item["ysize"] == 100

    # Check for QR code
    qr_item = next((item for item in payload if item["type"] == "qrcode"), None)
    assert qr_item is not None
    assert qr_item["boxsize"] == 4


@pytest.mark.asyncio
async def test_handle_print_label_plant_not_found(
    mock_hass, mock_coordinator, strain_library
) -> None:
    """Test handle_print_label raises error if plant not found."""
    mock_coordinator.plants = {}
    call = MagicMock()
    call.data = {"plant_id": "none"}

    with pytest.raises(HomeAssistantError, match="Plant none not found"):
        await handle_print_label(mock_hass, mock_coordinator, strain_library, call)


@pytest.mark.asyncio
async def test_handle_print_label_service_error(
    mock_hass, mock_coordinator, strain_library
) -> None:
    """Test handle_print_label raises HomeAssistantError if niimbot service fails."""
    # Mock plant data
    plant_id = "plant_1"
    mock_plant = MagicMock()
    mock_plant.genetics.strain_name = "Blue Dream"
    mock_plant.genetics.phenotype_name = "Berry"
    mock_coordinator.plants = {plant_id: mock_plant}
    # Mock strain library meta
    strain_library.get_all.return_value = {
        "Blue Dream": {
            "meta": {"breeder": "Humboldt"},
            "phenotypes": {"Berry": {}},
        }
    }
    call = MagicMock()
    call.data = {"plant_id": plant_id}
    # Mock service call to fail
    mock_hass.services.async_call.side_effect = Exception("Service error")
    with (
        patch(
            "custom_components.growspace_manager.services.strain_library.get_url",
            return_value="http://homeassistant.local",
        ),
        pytest.raises(
            HomeAssistantError, match="Failed to print Niimbot label: Service error"
        ),
    ):
        await handle_print_label(mock_hass, mock_coordinator, strain_library, call)


@pytest.mark.asyncio
async def test_handle_print_label_with_base64_downscaling(
    mock_hass, mock_coordinator, strain_library
) -> None:
    """Test handle_print_label service downscales large base64 logos."""
    # Mock plant data
    plant_id = "plant_1"
    mock_plant = MagicMock()
    mock_plant.genetics.strain_name = "Blue Dream"
    mock_plant.genetics.phenotype_name = "Berry"
    mock_coordinator.plants = {plant_id: mock_plant}

    # Create a large "image" (mocking base64)
    # 300x300 white square
    img = Image.new("RGB", (300, 300), color="white")
    buff = BytesIO()
    img.save(buff, format="PNG")
    large_base64 = f"data:image/png;base64,{base64.b64encode(buff.getvalue()).decode()}"

    strain_library.get_all.return_value = {
        "Blue Dream": {
            "meta": {
                "breeder": "Humboldt",
                "breeder_logo": large_base64,
            },
            "phenotypes": {"Berry": {}},
        }
    }

    call = MagicMock()
    call.data = {"plant_id": plant_id}

    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://homeassistant.local",
    ):
        await handle_print_label(mock_hass, mock_coordinator, strain_library, call)

    # Verify niimbot.print service call
    args, _ = mock_hass.services.async_call.call_args
    payload = args[2]["payload"]

    logo_item = next((item for item in payload if item["type"] == "dlimg"), None)
    assert logo_item is not None
    assert logo_item["url"].startswith("data:image/png;base64,")
    assert logo_item["url"] != large_base64  # Should be changed (downscaled)

    # Decode and check size
    _, encoded = logo_item["url"].split(",", 1)
    decoded_img = Image.open(BytesIO(base64.b64decode(encoded)))
    assert decoded_img.width <= 200
    assert decoded_img.height <= 200
