"""Tests for the ImageManager."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.image_manager import ImageManager


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)

    async def run_immediately(f, *args):
        return f(*args)

    # Mock async_add_executor_job to run the function immediately and return awaitable
    hass.async_add_executor_job = MagicMock(side_effect=run_immediately)
    return hass


@pytest.fixture
def image_manager(mock_hass: MagicMock, tmp_path: Path) -> ImageManager:
    """Fixture for ImageManager using a temporary directory."""
    return ImageManager(mock_hass, str(tmp_path))


def test_initialization(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test initialization creates storage directory if it doesn't exist."""
    # tmp_path already exists, so let's use a subdir
    storage_dir = tmp_path / "subdir"
    assert not storage_dir.exists()

    ImageManager(mock_hass, str(storage_dir))

    assert storage_dir.exists()
    assert storage_dir.is_dir()


async def test_save_strain_image_success(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test successfully saving a strain image."""
    strain_id = "strain_123"
    image_base64 = "data:image/jpeg;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"  # minimal valid gif/image logic will be mocked anyway

    # We still mock base64/PIL because we don't want to rely on real image library internals for compression
    # But we want to verify the file write

    with (
        patch("base64.b64decode", return_value=b"image_data"),
        patch("PIL.Image.open") as mock_open,
    ):
        mock_image = MagicMock()
        mock_image.mode = "RGBA"
        mock_open.return_value = mock_image
        mock_converted_image = MagicMock()
        mock_image.convert.return_value = mock_converted_image

        expected_filename = f"{strain_id}.jpg"
        expected_path = tmp_path / expected_filename

        # We mock save because PIL real save requires valid image data
        # But we can verify it TRIED to save to the correct path

        path = await image_manager.save_strain_image(strain_id, None, image_base64)

        assert path == str(expected_path.absolute())
        mock_converted_image.save.assert_called_with(
            expected_path, "JPEG", quality=85, optimize=True
        )


async def test_save_strain_image_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving an image with a phenotype ID."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    image_base64 = "raw_base64_data"

    with (
        patch("base64.b64decode", return_value=b"image_data"),
        patch("PIL.Image.open") as mock_open,
    ):
        mock_image = MagicMock()
        mock_image.mode = "RGB"
        mock_open.return_value = mock_image

        expected_filename = f"{strain_id}_{phenotype_id}.jpg"
        expected_path = tmp_path / expected_filename

        await image_manager.save_strain_image(strain_id, phenotype_id, image_base64)

        mock_image.save.assert_called_with(
            expected_path, "JPEG", quality=85, optimize=True
        )


async def test_save_strain_image_error(image_manager: ImageManager) -> None:
    """Test error handling during image save."""
    with (
        patch("base64.b64decode", side_effect=ValueError("Invalid base64")),
        pytest.raises(ValueError),
    ):
        await image_manager.save_strain_image("id", None, "bad_data")


def test_get_image_path_exists(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test getting path for an existing image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.jpg"
    file_path = tmp_path / filename

    # Create dummy file
    file_path.touch()
    # Manually update cache since we bypassed save_strain_image
    image_manager._image_cache.add(filename)

    path = image_manager.get_image_path(strain_id, None)
    assert path == str(file_path.absolute())


def test_get_image_path_not_exists(image_manager: ImageManager) -> None:
    """Test getting path for a non-existent image."""
    path = image_manager.get_image_path("strain_123", None)
    assert path is None


def test_delete_image_success(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test successfully deleting an image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.jpg"
    file_path = tmp_path / filename

    # Create dummy file
    file_path.touch()
    # Manually update cache since we bypassed save_strain_image
    image_manager._image_cache.add(filename)

    assert file_path.exists()

    image_manager.delete_image(strain_id, None)
    assert not file_path.exists()


def test_delete_image_not_found(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test deleting a non-existent image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.jpg"
    file_path = tmp_path / filename

    assert not file_path.exists()
    # Should not raise
    image_manager.delete_image(strain_id, None)


def test_delete_image_error(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test error handling during image deletion."""
    strain_id = "strain_123"
    filename = f"{strain_id}.jpg"
    file_path = tmp_path / filename
    file_path.touch()

    # Patch Path.unlink to raise OSError
    # We need to construct the exact Path object or use side_effect on a mock
    # Be careful here, Path objects are immutable value types.
    # To test this, we can patch unlink on the Path CLASS, but that affects everything
    # Better to just use 'patch.object' if possible, or verify logging without exception

    with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
        image_manager.delete_image(strain_id, None)
        # Should catch and log error
        assert file_path.exists()  # Should still exist if unlink failed
