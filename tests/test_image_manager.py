"""Tests for the ImageManager."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from PIL import Image

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
    # Minimal 1x1 pixel PNG as base64 (works with PIL)
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_strain_image(strain_id, None, image_base64)

    expected_filename = f"{strain_id}.webp"
    expected_path = tmp_path / expected_filename
    expected_small_path = tmp_path / f"{strain_id}_small.webp"

    # Verify return path
    assert path == str(expected_path.absolute())

    # Verify both files were created
    assert expected_path.exists()
    assert expected_small_path.exists()

    # Verify they're valid WebP files
    with Image.open(expected_path) as img:
        assert img.format == "WEBP"
    with Image.open(expected_small_path) as img:
        assert img.format == "WEBP"
        # Thumbnail should be small
        assert img.width <= 320
        assert img.height <= 320


async def test_save_strain_image_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving an image with a phenotype ID."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    # Minimal 1x1 pixel PNG as base64
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    await image_manager.save_strain_image(strain_id, phenotype_id, image_base64)

    expected_filename = f"{strain_id}_{phenotype_id}.webp"
    expected_path = tmp_path / expected_filename
    expected_small_path = tmp_path / f"{strain_id}_{phenotype_id}_small.webp"

    # Verify both files were created
    assert expected_path.exists()
    assert expected_small_path.exists()

    # Verify they're valid WebP files
    with Image.open(expected_path) as img:
        assert img.format == "WEBP"
    with Image.open(expected_small_path) as img:
        assert img.format == "WEBP"


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

    image_manager._image_cache.add(filename)  # Prerequisite for delete_image to proceed

    with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
        image_manager.delete_image(strain_id, None)
        # Should catch and log error
        assert file_path.exists()  # Should still exist if unlink failed


def test_build_cache_error(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test error handling during cache build."""
    with patch("pathlib.Path.glob", side_effect=OSError("Disk error")):
        # Should not raise
        manager = ImageManager(mock_hass, str(tmp_path))
        assert manager._image_cache == set()


def test_get_image_path_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test getting path for an existing image with phenotype."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    filename = f"{strain_id}_{phenotype_id}.jpg"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    path = image_manager.get_image_path(strain_id, phenotype_id)
    assert path == str(file_path.absolute())


def test_delete_image_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test deleting an image with phenotype."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    filename = f"{strain_id}_{phenotype_id}.jpg"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    image_manager.delete_image(strain_id, phenotype_id)
    assert not file_path.exists()


async def test_save_timeline_image_success(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test successfully saving a timeline image."""
    plant_id = "plant_123"
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_timeline_image(plant_id, image_base64)

    # Path should be relative to storage_dir for timeline images
    assert "timeline/" in path
    assert path.endswith(".webp")

    full_path = tmp_path / path
    assert full_path.exists()

    # Small thumbnail should also exist
    thumb_path = tmp_path / path.replace(".webp", "_small.webp")
    assert thumb_path.exists()
