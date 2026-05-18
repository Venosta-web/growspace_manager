"""Tests for the ImportExportManager."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from custom_components.growspace_manager.import_export_manager import (
    ImportExportManager,
)
from homeassistant.core import HomeAssistant


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
    hass.config.path = MagicMock(side_effect=lambda *args: f"/config/{'/'.join(args)}")

    return hass


@pytest.fixture
def manager(mock_hass: MagicMock) -> ImportExportManager:
    """Fixture for ImportExportManager."""
    return ImportExportManager(mock_hass)


async def test_export_library_success(
    manager: ImportExportManager, mock_hass: MagicMock, tmp_path: Path
) -> None:
    """Test successful library export."""
    output_dir = tmp_path / "output"

    # Setup source image in tmp_path
    source_dir = tmp_path / "config"
    www_dir = source_dir / "www"
    image_dir = www_dir / "images"
    image_dir.mkdir(parents=True)
    source_image = image_dir / "strain1.jpg"
    source_image.touch()

    # Override hass.config.path to use our tmp source_dir
    def mock_path_side_effect(*args):
        return str(source_dir.joinpath(*args))

    mock_hass.config.path.side_effect = mock_path_side_effect

    library_data = {
        "strain1": {
            "name": "Strain 1",
            "phenotypes": {"pheno1": {"image_path": "/local/images/strain1.jpg"}},
        }
    }

    with (
        patch("zipfile.ZipFile") as mock_zip_cls,
        patch(
            "custom_components.growspace_manager.import_export_manager.dt_util"
        ) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "20230101_120000"

        mock_zip = MagicMock()
        mock_zip_cls.return_value.__enter__.return_value = mock_zip

        zip_path = await manager.export_library(library_data, str(output_dir))

        assert zip_path == str(output_dir / "strain_library_export_20230101_120000.zip")
        assert output_dir.exists()

        # Verify image was added to zip
        mock_zip.write.assert_called_with(source_image, "images/strain1.jpg")

        # Verify JSON was written
        # We need to check the content of the written JSON
        args, _ = mock_zip.writestr.call_args
        assert args[0] == "library.json"
        exported_json = json.loads(args[1])
        assert (
            exported_json["strain1"]["phenotypes"]["pheno1"]["image_path"]
            == "images/strain1.jpg"
        )


async def test_import_library_success(
    manager: ImportExportManager, tmp_path: Path
) -> None:
    """Test successful library import."""
    target_image_dir = tmp_path / "target_images"
    zip_path = tmp_path / "import.zip"
    zip_path.touch()
    library_data = {"strain1": {"name": "Strain 1"}}

    with (
        patch("zipfile.is_zipfile", return_value=True),
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
            result = await manager.import_library(str(zip_path), str(target_image_dir))

        assert result == library_data
        assert target_image_dir.exists()
        assert mock_copy.call_count == 1  # One image copied


async def test_import_library_file_not_found(
    manager: ImportExportManager, tmp_path: Path
) -> None:
    """Test import with missing file."""
    target_image_dir = str(tmp_path / "target_images")
    with pytest.raises(FileNotFoundError):
        await manager.import_library("/missing.zip", target_image_dir)


async def test_import_library_invalid_zip(
    manager: ImportExportManager, tmp_path: Path
) -> None:
    """Test import with invalid zip file."""
    target_image_dir = str(tmp_path / "target_images")
    zip_path = tmp_path / "invalid.zip"
    zip_path.write_text("not a zip")

    with (
        patch("zipfile.is_zipfile", return_value=False),
        pytest.raises(ValueError, match="Not a valid ZIP file"),
    ):
        await manager.import_library(str(zip_path), target_image_dir)


async def test_import_library_missing_json(
    manager: ImportExportManager, tmp_path: Path
) -> None:
    """Test import with missing library.json."""
    target_image_dir = str(tmp_path / "target_images")
    zip_path = tmp_path / "test.zip"
    zip_path.touch()

    with (
        patch("zipfile.is_zipfile", return_value=True),
        patch("zipfile.ZipFile") as mock_zip_cls,
    ):
        mock_zip = MagicMock()
        mock_zip_cls.return_value.__enter__.return_value = mock_zip
        mock_zip.namelist.return_value = ["images/only.jpg"]

        with pytest.raises(ValueError, match="library.json missing"):
            await manager.import_library(str(zip_path), target_image_dir)
