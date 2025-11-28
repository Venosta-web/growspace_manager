"""Tests for the Strain Library services."""

import pytest
import os
import base64
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.services.strain_library import (
    handle_get_strain_library,
    handle_export_strain_library,
    handle_import_strain_library,
    handle_clear_strain_library,
    handle_add_strain,
    handle_update_strain_meta,
)
from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.data = {}
    hass.config = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.async_save = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    strain_library = MagicMock(spec=StrainLibrary)
    strain_library.load = AsyncMock()
    strain_library.strains = {"Strain A", "Strain B"}
    # Corrected method names
    strain_library.import_library_from_zip = AsyncMock(return_value=2)
    strain_library.clear = AsyncMock(return_value=2)
    strain_library.add_strain = AsyncMock()
    strain_library.set_strain_meta = AsyncMock()
    strain_library.save = AsyncMock()
    strain_library.export_library_to_zip = AsyncMock(return_value="/tmp/mock_export.zip")
    strain_library.get_all = MagicMock(return_value={"Strain A": {}, "Strain B": {}})
    return strain_library


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    return MagicMock(spec=ServiceCall)


@pytest.mark.asyncio
async def test_handle_get_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_get_strain_library service."""
    strains = await handle_get_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.load.assert_awaited_once()
    assert set(strains) == {"Strain A", "Strain B"}
    fired_event = mock_hass.bus.async_fire.call_args[0][0]
    fired_data = mock_hass.bus.async_fire.call_args[0][1]
    assert fired_event == f"{DOMAIN}_strain_library_fetched"
    assert set(fired_data["strains"]) == {"Strain A", "Strain B"}


@pytest.mark.asyncio
async def test_handle_export_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_export_strain_library service."""
    mock_hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))

    await handle_export_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()
    fired_event = mock_hass.bus.async_fire.call_args[0][0]
    fired_data = mock_hass.bus.async_fire.call_args[0][1]
    assert fired_event == f"{DOMAIN}_strain_library_exported"
    assert fired_data["file_path"] == "/tmp/mock_export.zip"


@pytest.mark.asyncio
async def test_handle_import_strain_library_path(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_import_strain_library service with file path."""
    mock_call.data = {"file_path": "/tmp/test.zip", "replace": True}

    await handle_import_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    # Note: replace=True in service call means merge=False in method call
    mock_strain_library.import_library_from_zip.assert_awaited_once_with(
        zip_path="/tmp/test.zip", merge=False
    )
    mock_strain_library.save.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_strain_library_imported", {"strains_count": 2, "merged": False}
    )


@pytest.mark.asyncio
async def test_handle_import_strain_library_base64(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_import_strain_library service with base64 data."""
    # Create dummy zip content
    dummy_content = b"PK\x03\x04dummyzipcontent"
    encoded_content = base64.b64encode(dummy_content).decode("utf-8")

    # Simulate a Data URI prefix
    zip_base64 = f"data:application/zip;base64,{encoded_content}"

    mock_call.data = {"zip_base64": zip_base64, "replace": False}

    # We need to mock os.remove to avoid actual file deletion error if temp file doesn't exist (though it should)
    # And we want to capture the temp file path

    with patch("custom_components.growspace_manager.services.strain_library.tempfile.NamedTemporaryFile") as mock_temp:
        mock_temp_obj = MagicMock()
        mock_temp_obj.name = "/tmp/random_temp_file.zip"
        # Context manager support
        mock_temp.return_value.__enter__.return_value = mock_temp_obj

        # Patch os.remove
        with patch("os.remove") as mock_remove, patch("os.path.exists", return_value=True):
            await handle_import_strain_library(
                mock_hass, mock_coordinator, mock_strain_library, mock_call
            )

            # verify write was called with decoded data
            mock_temp_obj.write.assert_called_with(dummy_content)

            # verify import was called with temp path
            mock_strain_library.import_library_from_zip.assert_awaited_once_with(
                zip_path="/tmp/random_temp_file.zip", merge=True
            )

            # verify cleanup
            mock_remove.assert_called_with("/tmp/random_temp_file.zip")


@pytest.mark.asyncio
async def test_handle_import_strain_library_no_input(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_import_strain_library with no input."""
    mock_call.data = {}

    await handle_import_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.import_library_from_zip.assert_not_called()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_import_strain_library_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_import_strain_library with an exception."""
    mock_call.data = {"file_path": "/tmp/test.zip", "replace": False}
    mock_strain_library.import_library_from_zip.side_effect = Exception("Import failed")

    with pytest.raises(Exception, match="Import failed"):
        await handle_import_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
async def test_handle_add_strain_with_image(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_add_strain service uses 'image' parameter if 'image_base64' is missing."""
    mock_call.data = {
        "strain": "Strain A",
        "image": "base64encodedstring"
    }

    await handle_add_strain(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.add_strain.assert_awaited_once()
    call_args = mock_strain_library.add_strain.call_args.kwargs
    assert call_args["strain"] == "Strain A"
    assert call_args["image_base64"] == "base64encodedstring"


@pytest.mark.asyncio
async def test_handle_add_strain_with_image_base64(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_add_strain service uses 'image_base64' if present."""
    mock_call.data = {
        "strain": "Strain A",
        "image_base64": "base64encodedstring",
        "image": "ignored"
    }

    await handle_add_strain(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.add_strain.assert_awaited_once()
    call_args = mock_strain_library.add_strain.call_args.kwargs
    assert call_args["strain"] == "Strain A"
    assert call_args["image_base64"] == "base64encodedstring"


@pytest.mark.asyncio
async def test_handle_update_strain_meta_with_image(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_update_strain_meta service uses 'image' parameter if 'image_base64' is missing."""
    mock_call.data = {
        "strain": "Strain A",
        "image": "base64encodedstring"
    }

    await handle_update_strain_meta(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.set_strain_meta.assert_awaited_once()
    call_args = mock_strain_library.set_strain_meta.call_args.kwargs
    assert call_args["strain"] == "Strain A"
    assert call_args["image_base64"] == "base64encodedstring"


@pytest.mark.asyncio
async def test_handle_clear_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_clear_strain_library service."""
    await handle_clear_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.clear.assert_awaited_once()
    mock_coordinator.async_save.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_strain_library_cleared", {"cleared_count": 2}
    )


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_clear_strain_library_attribute_error(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_clear_strain_library with AttributeError."""
    mock_strain_library.clear.side_effect = AttributeError("Method not found")

    with pytest.raises(AttributeError, match="Method not found"):
        await handle_clear_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_clear_strain_library_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_clear_strain_library with a generic exception."""
    mock_strain_library.clear.side_effect = Exception("Clear failed")

    with pytest.raises(Exception, match="Clear failed"):
        await handle_clear_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()
