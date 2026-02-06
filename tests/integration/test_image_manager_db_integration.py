"""Integration tests for ImageManager to achieve 95%+ coverage.

Uses real aiosqlite to test database path update logic.
"""

import base64
from io import BytesIO
from pathlib import Path
import shutil
from unittest.mock import MagicMock

import aiosqlite
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


async def test_db_path_update_with_jpg_entries(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test database path update logic using real aiosqlite."""
    # Create JPG file
    jpg_path = tmp_path / "test_strain_pheno.jpg"
    test_img = PILImage.new("RGB", (100, 100))
    test_img.save(jpg_path, "JPEG")

    # Create real aiosqlite database
    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row

        await db.execute("""
            CREATE TABLE phenotypes (
                phenotype_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT
            )
        """)

        # Insert record with .jpg path
        await db.execute(
            "INSERT INTO phenotypes (image_path) VALUES (?)",
            ("/local/growspace_manager/strains/test_strain_pheno.jpg",),
        )
        await db.commit()

        # Run migration
        result = await image_manager.async_migrate_to_webp(db)

        # Should return True (paths were updated)
        assert result is True

        # Verify database was updated
        async with db.execute(
            "SELECT image_path FROM phenotypes WHERE phenotype_id = 1"
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert (
                row["image_path"]
                == "/local/growspace_manager/strains/test_strain_pheno.webp"
            )


async def test_db_path_update_no_jpg_entries(image_manager: ImageManager) -> None:
    """Test database update returns 0 when no .jpg paths exist."""

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row

        await db.execute("""
            CREATE TABLE phenotypes (
                phenotype_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT
            )
        """)

        # Insert record with .webp path (already migrated)
        await db.execute(
            "INSERT INTO phenotypes (image_path) VALUES (?)",
            ("/local/growspace_manager/strains/test.webp",),
        )
        await db.commit()

        # Run migration
        result = await image_manager.async_migrate_to_webp(db)

        # Should return False (no updates needed)
        assert result is False


async def test_db_path_update_multiple_entries(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test database update with multiple .jpg entries."""
    # Create JPG files
    for i in range(3):
        jpg_path = tmp_path / f"strain_{i}.jpg"
        test_img = PILImage.new("RGB", (50, 50))
        test_img.save(jpg_path, "JPEG")

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row

        await db.execute("""
            CREATE TABLE phenotypes (
                phenotype_id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT
            )
        """)

        # Insert 3 records with .jpg paths
        for i in range(3):
            await db.execute(
                "INSERT INTO phenotypes (image_path) VALUES (?)",
                (f"/local/growspace_manager/strains/strain_{i}.jpg",),
            )
        await db.commit()

        # Run migration
        result = await image_manager.async_migrate_to_webp(db)

        # Should return True
        assert result is True

        # Verify all paths were updated
        async with db.execute("SELECT image_path FROM phenotypes") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                assert row["image_path"].endswith(".webp")


async def test_db_path_update_handles_error(image_manager: ImageManager) -> None:
    """Test database update handles exceptions gracefully."""

    # Create mock db that raises error
    mock_db = MagicMock()
    mock_db.execute = MagicMock(side_effect=Exception("DB error"))

    # Should not raise, returns 0
    result = await image_manager._update_db_paths(mock_db)
    assert result == 0


async def test_migration_nonexistent_storage_dir(
    mock_hass: MagicMock, tmp_path: Path
) -> None:
    """Test migration when storage directory doesn't exist."""

    storage_path = tmp_path / "to_be_deleted"
    image_manager = ImageManager(mock_hass, str(storage_path))
    await image_manager.async_setup()

    # Delete the directory AFTER initialization (simulates directory being deleted)
    shutil.rmtree(storage_path)

    # Should log debug and return False without error
    result = await image_manager.async_migrate_to_webp(None)

    assert result is False


async def test_save_image_with_grayscale(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a grayscale image (needs RGB conversion)."""

    # Create a grayscale PNG and encode as base64
    gray_img = PILImage.new("L", (50, 50), color=128)
    buffer = BytesIO()
    gray_img.save(buffer, format="PNG")
    image_base64 = base64.b64encode(buffer.getvalue()).decode()

    # Save should convert to RGB and succeed
    path = await image_manager.save_strain_image("gray_strain", None, image_base64)

    assert path is not None
    assert "gray_strain.webp" in path

    # Verify saved file is RGB/RGBA WebP
    saved_path = tmp_path / "gray_strain.webp"
    with PILImage.open(saved_path) as img:
        assert img.format == "WEBP"
        assert img.mode in ("RGB", "RGBA")
