"""Test for WebP auto-migration."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image as PILImage

from custom_components.growspace_manager.image_manager import ImageManager


async def test_webp_migration(tmp_path: Path) -> None:
    """Test that JPG files are automatically migrated to WebP."""
    # Create a mock hass
    mock_hass = MagicMock()

    async def run_immediately(f, *args):
        return f(*args)

    mock_hass.async_add_executor_job = MagicMock(side_effect=run_immediately)

    # Create a test JPG file
    jpg_path = tmp_path / "test_strain.jpg"
    test_img = PILImage.new("RGB", (100, 100), color=(255, 0, 0))
    test_img.save(jpg_path, "JPEG")

    # Create ImageManager
    image_manager = ImageManager(mock_hass, str(tmp_path))

    # Create a mock database connection
    mock_db = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.__aiter__.return_value = [
        {
            "phenotype_id": 1,
            "image_path": "/local/growspace_manager/strains/test_strain.jpg",
        }
    ]
    mock_db.execute.return_value.__aenter__.return_value = mock_cursor

    # Run migration
    await image_manager.async_migrate_to_webp(mock_db)

    # Verify WebP files were created
    webp_path = tmp_path / "test_strain.webp"
    small_webp_path = tmp_path / "test_strain_small.webp"

    assert webp_path.exists(), "Full-size WebP should be created"
    assert small_webp_path.exists(), "Thumbnail WebP should be created"

    # Verify they're valid WebP files
    with PILImage.open(webp_path) as img:
        assert img.format == "WEBP"
        assert img.size == (100, 100)

    with PILImage.open(small_webp_path) as img:
        assert img.format == "WEBP"
        # Thumbnail should be scaled down
        assert img.width <= 320
        assert img.height <= 320

    # Verify database was updated
    mock_db.execute.assert_called()
