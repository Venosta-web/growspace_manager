"""Tests for the ImageManager."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.image_manager import ImageManager

STORAGE_DIR = "/test/storage/dir"


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
def image_manager(mock_hass: MagicMock) -> ImageManager:
    """Fixture for ImageManager."""
    with patch("os.path.exists", return_value=True), patch("os.makedirs"):
        return ImageManager(mock_hass, STORAGE_DIR)


def test_initialization(mock_hass: MagicMock):
    """Test initialization creates storage directory if it doesn't exist."""
    with (
        patch("os.path.exists", return_value=False) as mock_exists,
        patch("os.makedirs") as mock_makedirs,
    ):
        ImageManager(mock_hass, STORAGE_DIR)
        mock_exists.assert_called_with(STORAGE_DIR)
        mock_makedirs.assert_called_with(STORAGE_DIR, exist_ok=True)


async def test_save_strain_image_success(image_manager: ImageManager):
    """Test successfully saving a strain image."""
    strain_id = "strain_123"
    image_base64 = "data:image/jpeg;base64,some_base64_data"

    with (
        patch("base64.b64decode", return_value=b"image_data") as mock_b64decode,
        patch("PIL.Image.open") as mock_open,
        patch("os.path.join") as mock_join,
    ):
        mock_image = MagicMock()
        mock_image.mode = "RGBA"
        mock_open.return_value = mock_image
        mock_converted_image = MagicMock()
        mock_image.convert.return_value = mock_converted_image

        expected_path = f"{STORAGE_DIR}/{strain_id}.jpg"
        mock_join.return_value = expected_path

        path = await image_manager.save_strain_image(strain_id, None, image_base64)

        assert path == expected_path
        mock_b64decode.assert_called_with("some_base64_data")
        mock_image.convert.assert_called_with("RGB")
        mock_converted_image.save.assert_called_with(
            expected_path, "JPEG", quality=85, optimize=True
        )


async def test_save_strain_image_with_phenotype(image_manager: ImageManager):
    """Test saving an image with a phenotype ID."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    image_base64 = "raw_base64_data"

    with (
        patch("base64.b64decode", return_value=b"image_data"),
        patch("PIL.Image.open") as mock_open,
        patch("os.path.join") as mock_join,
    ):
        mock_image = MagicMock()
        mock_image.mode = "RGB"
        mock_open.return_value = mock_image

        expected_path = f"{STORAGE_DIR}/{strain_id}_{phenotype_id}.jpg"
        mock_join.return_value = expected_path

        await image_manager.save_strain_image(strain_id, phenotype_id, image_base64)

        mock_join.assert_called_with(STORAGE_DIR, f"{strain_id}_{phenotype_id}.jpg")
        mock_image.save.assert_called()


async def test_save_strain_image_error(image_manager: ImageManager):
    """Test error handling during image save."""
    with patch("base64.b64decode", side_effect=ValueError("Invalid base64")):
        with pytest.raises(ValueError):
            await image_manager.save_strain_image("id", None, "bad_data")


def test_get_image_path_exists(image_manager: ImageManager):
    """Test getting path for an existing image."""
    strain_id = "strain_123"
    expected_path = f"{STORAGE_DIR}/{strain_id}.jpg"

    with (
        patch("os.path.join", return_value=expected_path),
        patch("os.path.exists", return_value=True),
    ):
        path = image_manager.get_image_path(strain_id, None)
        assert path == expected_path


def test_get_image_path_not_exists(image_manager: ImageManager):
    """Test getting path for a non-existent image."""
    with patch("os.path.exists", return_value=False):
        path = image_manager.get_image_path("strain_123", None)
        assert path is None


def test_delete_image_success(image_manager: ImageManager):
    """Test successfully deleting an image."""
    strain_id = "strain_123"
    expected_path = f"{STORAGE_DIR}/{strain_id}.jpg"

    with (
        patch.object(image_manager, "get_image_path", return_value=expected_path),
        patch("os.path.exists", return_value=True),
        patch("os.remove") as mock_remove,
    ):
        image_manager.delete_image(strain_id, None)
        mock_remove.assert_called_with(expected_path)


def test_delete_image_not_found(image_manager: ImageManager):
    """Test deleting a non-existent image."""
    with (
        patch.object(image_manager, "get_image_path", return_value=None),
        patch("os.remove") as mock_remove,
    ):
        image_manager.delete_image("strain_123", None)
        mock_remove.assert_not_called()


def test_delete_image_error(image_manager: ImageManager):
    """Test error handling during image deletion."""
    expected_path = f"{STORAGE_DIR}/strain_123.jpg"

    with (
        patch.object(image_manager, "get_image_path", return_value=expected_path),
        patch("os.path.exists", return_value=True),
        patch("os.remove", side_effect=OSError("Permission denied")),
    ):
        # Should not raise exception, just log error
        image_manager.delete_image("strain_123", None)
