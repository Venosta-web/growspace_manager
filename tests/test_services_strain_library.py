"""Tests for the Strain Library services."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.services.strain_library import (
    handle_add_strain,
    handle_clear_strain_library,
    handle_export_strain_library,
    handle_get_strain_library,
    handle_import_strain_library,
    handle_remove_strain,
    handle_update_strain_meta,
)


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library() -> MagicMock:
    """Mock the StrainLibrary."""
    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(return_value={"Strain A": {}})
    library.export_library_to_zip = AsyncMock(
        return_value="/config/www/growspace_manager/exports/export.zip"
    )
    library.import_library_from_zip = AsyncMock(return_value=5)
    library.save = AsyncMock()
    library.add_strain = AsyncMock()
    library.set_strain_meta = AsyncMock()
    library.remove_strain = AsyncMock()
    library.remove_strain_phenotype = AsyncMock()
    library.clear = AsyncMock(return_value=10)
    return library


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.config = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    return hass


async def test_handle_get_strain_library(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test getting the strain library."""
    call = ServiceCall(mock_hass, DOMAIN, "get_strain_library", {}, context=MagicMock())

    result = await handle_get_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, call
    )

    assert result == {"Strain A": {}}
    mock_strain_library.load.assert_awaited_once()
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_strain_library_fetched", {"strains": {"Strain A": {}}}
    )


async def test_handle_export_strain_library(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test exporting the strain library."""
    call = ServiceCall(
        mock_hass, DOMAIN, "export_strain_library", {}, context=MagicMock()
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        await handle_export_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        mock_strain_library.export_library_to_zip.assert_awaited_once()
        mock_coordinator.async_save.assert_awaited_once()
        mock_hass.bus.async_fire.assert_called_once()
        mock_notify.assert_called_once()


async def test_handle_export_strain_library_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test exporting the strain library with error."""
    mock_strain_library.export_library_to_zip.side_effect = Exception("Export Error")
    call = ServiceCall(
        mock_hass, DOMAIN, "export_strain_library", {}, context=MagicMock()
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception, match="Export Error"):
            await handle_export_strain_library(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        mock_notify.assert_called_once()


async def test_handle_import_strain_library_file_path(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library from file path."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "import_strain_library",
        {"file_path": "/tmp/import.zip", "replace": True},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        await handle_import_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        mock_strain_library.import_library_from_zip.assert_awaited_once_with(
            zip_path="/tmp/import.zip", merge=False
        )
        mock_strain_library.save.assert_awaited_once()
        mock_coordinator.async_request_refresh.assert_awaited_once()
        mock_hass.bus.async_fire.assert_called_once()
        mock_notify.assert_called_once()


async def test_handle_import_strain_library_base64(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library from base64."""
    zip_content = b"PK\x03\x04"  # Fake zip header
    zip_base64 = base64.b64encode(zip_content).decode("utf-8")

    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "import_strain_library",
        {"zip_base64": f"data:application/zip;base64,{zip_base64}"},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/temp_import.zip"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            with (
                patch("os.path.exists", return_value=True),
                patch("os.remove") as mock_remove,
            ):
                await handle_import_strain_library(
                    mock_hass, mock_coordinator, mock_strain_library, call
                )

                mock_temp_file.write.assert_called_once_with(zip_content)
                mock_strain_library.import_library_from_zip.assert_awaited_once_with(
                    zip_path="/tmp/temp_import.zip", merge=True
                )
                mock_remove.assert_called_once_with("/tmp/temp_import.zip")


async def test_handle_import_strain_library_temp_file_remove_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library with temp file removal error."""
    zip_content = b"PK\x03\x04"
    zip_base64 = base64.b64encode(zip_content).decode("utf-8")

    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "import_strain_library",
        {"zip_base64": f"data:application/zip;base64,{zip_base64}"},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ):
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_temp_file = MagicMock()
            mock_temp_file.name = "/tmp/temp_import.zip"
            mock_temp.return_value.__enter__.return_value = mock_temp_file

            with (
                patch("os.path.exists", return_value=True),
                patch("os.remove", side_effect=OSError("Remove Error")),
            ):
                await handle_import_strain_library(
                    mock_hass, mock_coordinator, mock_strain_library, call
                )

                mock_strain_library.import_library_from_zip.assert_awaited_once()


async def test_handle_import_strain_library_no_data(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library with no data."""
    call = ServiceCall(
        mock_hass, DOMAIN, "import_strain_library", {}, context=MagicMock()
    )

    await handle_import_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, call
    )

    mock_strain_library.import_library_from_zip.assert_not_awaited()


async def test_handle_import_strain_library_base64_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library with base64 error."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "import_strain_library",
        {"zip_base64": "invalid_base64"},
        context=MagicMock(),
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        await handle_import_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        mock_notify.assert_called_once()
        mock_strain_library.import_library_from_zip.assert_not_awaited()


async def test_handle_import_strain_library_import_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test importing strain library with import error."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "import_strain_library",
        {"file_path": "/tmp/import.zip"},
        context=MagicMock(),
    )
    mock_strain_library.import_library_from_zip.side_effect = Exception("Import Error")

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception, match="Import Error"):
            await handle_import_strain_library(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        mock_notify.assert_called_once()


async def test_handle_add_strain(mock_hass, mock_coordinator, mock_strain_library):
    """Test adding a strain."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "add_strain",
        {
            "strain": "Strain A",
            "phenotype": "Pheno 1",
            "breeder": "Breeder A",
            "type": "Sativa",
            "flower_days_min": 60,
            "image_base64": "base64data",
        },
        context=MagicMock(),
    )

    await handle_add_strain(mock_hass, mock_coordinator, mock_strain_library, call)

    mock_strain_library.add_strain.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_handle_add_strain_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test adding a strain with error."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "add_strain",
        {"strain": "Strain A"},
        context=MagicMock(),
    )
    mock_strain_library.add_strain.side_effect = ValueError("Invalid Strain")

    with pytest.raises(HomeAssistantError, match="Invalid Strain"):
        await handle_add_strain(mock_hass, mock_coordinator, mock_strain_library, call)


async def test_handle_update_strain_meta(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating strain metadata."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "update_strain_meta",
        {"strain": "Strain A", "description": "New Description"},
        context=MagicMock(),
    )

    await handle_update_strain_meta(
        mock_hass, mock_coordinator, mock_strain_library, call
    )

    mock_strain_library.set_strain_meta.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_handle_update_strain_meta_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test updating strain metadata with error."""
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "update_strain_meta",
        {"strain": "Strain A"},
        context=MagicMock(),
    )
    mock_strain_library.set_strain_meta.side_effect = ValueError("Invalid Update")

    with pytest.raises(HomeAssistantError, match="Invalid Update"):
        await handle_update_strain_meta(
            mock_hass, mock_coordinator, mock_strain_library, call
        )


async def test_handle_remove_strain(mock_hass, mock_coordinator, mock_strain_library):
    """Test removing a strain."""
    # Remove entire strain
    call = ServiceCall(
        mock_hass,
        DOMAIN,
        "remove_strain",
        {"strain": "Strain A"},
        context=MagicMock(),
    )
    await handle_remove_strain(mock_hass, mock_coordinator, mock_strain_library, call)
    mock_strain_library.remove_strain.assert_awaited_once_with("Strain A")
    mock_coordinator.async_request_refresh.assert_awaited_once()

    # Remove phenotype
    mock_coordinator.async_request_refresh.reset_mock()
    call_pheno = ServiceCall(
        mock_hass,
        DOMAIN,
        "remove_strain",
        {"strain": "Strain A", "phenotype": "Pheno 1"},
        context=MagicMock(),
    )
    await handle_remove_strain(
        mock_hass, mock_coordinator, mock_strain_library, call_pheno
    )
    mock_strain_library.remove_strain_phenotype.assert_awaited_once_with(
        "Strain A", "Pheno 1"
    )
    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_handle_clear_strain_library(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test clearing the strain library."""
    call = ServiceCall(
        mock_hass, DOMAIN, "clear_strain_library", {}, context=MagicMock()
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        await handle_clear_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, call
        )

        mock_strain_library.clear.assert_awaited_once()
        mock_coordinator.async_save.assert_awaited_once()
        mock_coordinator.async_request_refresh.assert_awaited_once()
        mock_hass.bus.async_fire.assert_called_once()


async def test_handle_clear_strain_library_error(
    mock_hass, mock_coordinator, mock_strain_library
):
    """Test clearing the strain library with error."""
    mock_strain_library.clear.side_effect = Exception("Clear Error")
    call = ServiceCall(
        mock_hass, DOMAIN, "clear_strain_library", {}, context=MagicMock()
    )

    with patch(
        "custom_components.growspace_manager.services.strain_library.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception, match="Clear Error"):
            await handle_clear_strain_library(
                mock_hass, mock_coordinator, mock_strain_library, call
            )

        mock_notify.assert_called_once()
