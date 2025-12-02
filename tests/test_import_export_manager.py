"""Tests for the ImportExportManager."""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.import_export_manager import (
    ImportExportManager,
)

OUTPUT_DIR = "/test/output/dir"
TARGET_IMAGE_DIR = "/test/target/image/dir"


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)

    async def run_immediately(f, *args):
        return f(*args)

    # Mock async_add_executor_job to run the function immediately and return awaitable
    hass.async_add_executor_job = MagicMock(side_effect=run_immediately)

    # Mock config.path
    hass.config = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda p: f"/config/{p}")

    return hass


@pytest.fixture
def manager(mock_hass: MagicMock) -> ImportExportManager:
    """Fixture for ImportExportManager."""
    return ImportExportManager(mock_hass)


async def test_export_library_success(
    manager: ImportExportManager, mock_hass: MagicMock
):
    """Test successful library export."""
    library_data = {
        "strain1": {
            "name": "Strain 1",
            "phenotypes": {"pheno1": {"image_path": "/local/images/strain1.jpg"}},
        }
    }

    with (
        patch("os.makedirs") as mock_makedirs,
        patch("zipfile.ZipFile") as mock_zip_cls,
        patch("os.path.exists", return_value=True),
        patch("datetime.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value.strftime.return_value = "20230101_120000"
        mock_zip = MagicMock()
        mock_zip_cls.return_value.__enter__.return_value = mock_zip

        zip_path = await manager.export_library(library_data, OUTPUT_DIR)

        assert zip_path == f"{OUTPUT_DIR}/strain_library_export_20230101_120000.zip"
        mock_makedirs.assert_called_with(OUTPUT_DIR, exist_ok=True)

        # Verify image was added to zip
        mock_zip.write.assert_called_with(
            "/config/images/strain1.jpg", "images/strain1.jpg"
        )

        # Verify JSON was written
        # We need to check the content of the written JSON
        args, _ = mock_zip.writestr.call_args
        assert args[0] == "library.json"
        exported_json = json.loads(args[1])
        assert (
            exported_json["strain1"]["phenotypes"]["pheno1"]["image_path"]
            == "images/strain1.jpg"
        )


async def test_import_library_success(manager: ImportExportManager):
    """Test successful library import."""
    zip_path = "/test/import.zip"
    library_data = {"strain1": {"name": "Strain 1"}}

    with (
        patch("os.path.exists", return_value=True),
        patch("zipfile.is_zipfile", return_value=True),
        patch("os.makedirs") as mock_makedirs,
        patch("zipfile.ZipFile") as mock_zip_cls,
        patch("shutil.copyfileobj") as mock_copy,
    ):
        mock_zip = MagicMock()
        mock_zip_cls.return_value.__enter__.return_value = mock_zip
        mock_zip.namelist.return_value = ["library.json", "images/strain1.jpg"]

        # Mock opening library.json
        mock_open_file = MagicMock()
        mock_open_file.__enter__.return_value.read.return_value = json.dumps(
            library_data
        ).encode()

        # Mock zip info for image
        mock_zip_info = MagicMock()
        mock_zip_info.filename = "images/strain1.jpg"
        mock_zip_info.is_dir.return_value = False
        mock_zip.infolist.return_value = [mock_zip_info]

        # Handle multiple calls to zip.open
        def zip_open_side_effect(name, *args, **kwargs):
            if name == "library.json":
                return mock_open_file
            return MagicMock()  # For image file

        mock_zip.open.side_effect = zip_open_side_effect

        # Mock built-in open for writing image
        with patch("builtins.open", mock_open()):
            result = await manager.import_library(zip_path, TARGET_IMAGE_DIR)

        assert result == library_data
        mock_makedirs.assert_called_with(TARGET_IMAGE_DIR, exist_ok=True)
        assert mock_copy.call_count == 1  # One image copied


async def test_import_library_file_not_found(manager: ImportExportManager):
    """Test import with missing file."""
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            await manager.import_library("/missing.zip", TARGET_IMAGE_DIR)


async def test_import_library_invalid_zip(manager: ImportExportManager):
    """Test import with invalid zip file."""
    with (
        patch("os.path.exists", return_value=True),
        patch("zipfile.is_zipfile", return_value=False),
    ):
        with pytest.raises(ValueError, match="Not a valid ZIP file"):
            await manager.import_library("/invalid.zip", TARGET_IMAGE_DIR)


async def test_import_library_missing_json(manager: ImportExportManager):
    """Test import with missing library.json."""
    with (
        patch("os.path.exists", return_value=True),
        patch("zipfile.is_zipfile", return_value=True),
        patch("zipfile.ZipFile") as mock_zip_cls,
        patch("os.makedirs"),
    ):
        mock_zip = MagicMock()
        mock_zip_cls.return_value.__enter__.return_value = mock_zip
        mock_zip.namelist.return_value = ["images/only.jpg"]

        with pytest.raises(ValueError, match="library.json missing"):
            await manager.import_library("/test.zip", TARGET_IMAGE_DIR)
