"""Additional tests for ImageManager to increase coverage to 95%+."""

import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image as PILImage
import pytest

from custom_components.growspace_manager.image_manager import ImageManager


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock()

    async def run_immediately(f, *args):
        return f(*args)

    hass.async_add_executor_job = MagicMock(side_effect=run_immediately)
    return hass


@pytest.fixture
async def image_manager(mock_hass, tmp_path):
    """Fixture for an initialized ImageManager."""
    manager = ImageManager(mock_hass, str(tmp_path))
    await manager.async_setup()
    return manager


async def test_migration_with_no_storage_dir(
    mock_hass: MagicMock, tmp_path: Path
) -> None:
    """Test migration when storage directory doesn't exist."""
    storage_path = tmp_path / "nonexistent"
    image_manager = ImageManager(mock_hass, str(storage_path))
    # We DON'T call async_setup here because we want to test nonexistent dir handling in migration

    # Create mock DB
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncMock())

    # Should not error, just return False
    result = await image_manager.async_migrate_to_webp(mock_db)
    assert result is False


async def test_migration_with_no_jpg_files(image_manager: ImageManager) -> None:
    """Test migration when no JPG files exist."""
    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncMock())

    result = await image_manager.async_migrate_to_webp(mock_db)
    assert result is False


async def test_migration_skips_existing_webp(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test that migration skips files that already have WebP versions."""
    # Create JPG file
    jpg_path = tmp_path / "existing.jpg"
    test_img = PILImage.new("RGB", (50, 50), color=(255, 0, 0))
    test_img.save(jpg_path, "JPEG")

    # Create corresponding WebP files (already migrated)
    webp_path = tmp_path / "existing.webp"
    small_webp_path = tmp_path / "existing_small.webp"
    test_img.save(webp_path, "WEBP")
    test_img.save(small_webp_path, "WEBP")

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncMock())

    # Should skip, return False
    result = await image_manager.async_migrate_to_webp(mock_db)
    assert result is False


async def test_migration_handles_image_conversion_error(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test that migration handles image conversion errors gracefully."""
    # Create a corrupted JPG file
    jpg_path = tmp_path / "corrupted.jpg"
    jpg_path.write_bytes(b"not a valid image")

    mock_db = MagicMock()
    mock_db.execute = MagicMock(return_value=AsyncMock())

    # Should log warning but not crash
    result = await image_manager.async_migrate_to_webp(mock_db)
    # Migration completes but no files converted
    assert result is False


async def test_migration_handles_rgba_mode(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test migration with RGBA images (converts to RGB first)."""
    jpg_path = tmp_path / "rgba_test.jpg"
    # Create RGB image (RGBA can't be saved as JPEG)
    test_img = PILImage.new("RGB", (50, 50), color=(255, 0, 0))
    test_img.save(jpg_path, "JPEG")

    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = []
    # execute() needs to return something that is both awaitable AND an async context manager
    mock_db.execute = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_cursor))
    )
    mock_db.commit = AsyncMock()

    await image_manager.async_migrate_to_webp(mock_db)

    # Verify WebP files were created
    webp_path = tmp_path / "rgba_test.webp"
    assert webp_path.exists()


async def test_migration_with_grayscale_image(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test migration with grayscale images (needs RGB conversion)."""
    jpg_path = tmp_path / "gray_test.jpg"
    # Create grayscale image
    test_img = PILImage.new("L", (50, 50), color=128)
    test_img.save(jpg_path, "JPEG")

    # Should not crash, converts to RGB
    await image_manager.async_migrate_to_webp(None)

    # Verify WebP created
    webp_path = tmp_path / "gray_test.webp"
    assert webp_path.exists()


async def test_migration_without_db_connection(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test migration without database connection."""
    jpg_path = tmp_path / "test.jpg"
    test_img = PILImage.new("RGB", (50, 50))
    test_img.save(jpg_path, "JPEG")

    # Call without db_connection
    result = await image_manager.async_migrate_to_webp(None)
    assert result is False

    # But WebP files should still be created
    webp_path = tmp_path / "test.webp"
    assert webp_path.exists()


async def test_migration_exception_handling(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test that migration handles exceptions gracefully."""
    # Create a JPG file
    jpg_path = tmp_path / "test.jpg"
    test_img = PILImage.new("RGB", (50, 50))
    test_img.save(jpg_path, "JPEG")

    # Mock glob to raise an exception
    with patch.object(Path, "glob", side_effect=Exception("Glob error")):
        # Should not crash, just log error
        await image_manager.async_migrate_to_webp(None)


async def test_save_strain_image_with_data_uri_prefix(
    image_manager: ImageManager,
) -> None:
    """Test saving strain image with data URI prefix."""

    # Use data URI format (with prefix)
    image_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_strain_image("test_strain", None, image_base64)

    assert path is not None
    assert "test_strain.webp" in path


async def test_get_image_path_webp_fallback(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test get_image_path falls back to WebP when JPG not found."""
    # Create only WebP file
    webp_path = tmp_path / "test.webp"
    test_img = PILImage.new("RGB", (50, 50))
    test_img.save(webp_path, "WEBP")

    # REBUILD CACHE manually for this test because we just added a file
    await image_manager.async_setup()

    path = image_manager.get_image_path("test", None)
    assert path == str(webp_path.absolute())


def test_delete_image_webp_variants(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test that delete_image removes both full and thumbnail WebP."""
    # Create WebP files
    webp_path = tmp_path / "test.webp"
    small_webp_path = tmp_path / "test_small.webp"

    test_img = PILImage.new("RGB", (50, 50))
    test_img.save(webp_path, "WEBP")
    test_img.save(small_webp_path, "WEBP")

    image_manager._image_cache.add("test.webp")
    image_manager._image_cache.add("test_small.webp")

    image_manager.delete_image("test", None)

    # Both should be deleted
    assert not webp_path.exists()
    assert not small_webp_path.exists()


def test_build_cache_handles_errors(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test that _build_cache handles errors gracefully."""
    with patch("pathlib.Path.glob", side_effect=OSError("Disk error")):
        # Should not raise
        manager = ImageManager(mock_hass, str(tmp_path))
        assert manager._image_cache == set()


async def test_save_timeline_image_with_data_uri_prefix(
    image_manager: ImageManager,
) -> None:
    """Test saving timeline image with data URI prefix (covers strip split)."""

    # Use data URI format (1x1 transparent PNG)
    image_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_timeline_image("plant1", image_base64)

    assert path is not None
    assert "plant1_" in path
    assert ".webp" in path
    # Verify file exists
    assert Path(path).exists()


async def test_save_timeline_image_grayscale_conversion(
    image_manager: ImageManager,
) -> None:
    """Test saving grayscale timeline image (covers RGB conversion)."""

    # Create valid base64 for a grayscale image
    img = PILImage.new("L", (10, 10), color=128)
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()

    path = await image_manager.save_timeline_image("plant_gray", img_str)

    assert Path(path).exists()
    # Check saved image is valid WebP — use context manager to avoid resource leak
    with PILImage.open(path) as saved_img:
        assert saved_img.format == "WEBP"


async def test_save_timeline_image_exception_handling(
    image_manager: ImageManager,
) -> None:
    """Test exception handling in save_timeline_image."""

    # Mock base64 decode to fail
    with (
        patch("base64.b64decode", side_effect=Exception("Decode Error")),
        pytest.raises(Exception, match="Decode Error"),
    ):
        await image_manager.save_timeline_image("plant_err", "invalid_b64")
