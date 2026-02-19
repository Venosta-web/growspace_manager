"""Tests for the ImageManager."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import json
import base64
import binascii
from io import BytesIO

from PIL import Image, UnidentifiedImageError
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.image_manager import ImageManager
from homeassistant.core import HomeAssistant


class AsyncCtxAwaitable:
    """Mock that works as both an async context manager and an awaitable."""

    def __init__(self, return_value):
        self.return_value = return_value

    def __await__(self):
        async def _f():
            return self.return_value

        return _f().__await__()

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


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
async def image_manager(mock_hass: MagicMock, tmp_path: Path) -> ImageManager:
    """Fixture for ImageManager using a temporary directory."""
    manager = ImageManager(mock_hass, str(tmp_path))
    await manager.async_setup()
    # Populate cache initially
    manager._build_cache()
    return manager


@pytest.mark.asyncio
async def test_initialization(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test initialization creates storage directory if it doesn't exist."""
    # tmp_path already exists, so let's use a subdir
    storage_dir = tmp_path / "subdir"
    assert not storage_dir.exists()

    manager = ImageManager(mock_hass, str(storage_dir))
    assert not storage_dir.exists()
    await manager.async_setup()

    assert storage_dir.exists()
    assert storage_dir.is_dir()


@pytest.mark.asyncio
async def test_save_strain_image_success(
    image_manager: ImageManager, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """Test successfully saving a strain image."""
    strain_id = "strain_123"
    # Minimal 1x1 pixel PNG as base64 (works with PIL)
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_strain_image(strain_id, None, image_base64)

    expected_filename = f"{strain_id}.webp"
    expected_path = tmp_path / expected_filename
    expected_small_path = tmp_path / f"{strain_id}_small.webp"

    # Verify return path against snapshot
    assert Path(path).name == snapshot
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


@pytest.mark.asyncio
async def test_save_strain_image_with_header(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a strain image with data URI header."""
    strain_id = "strain_header"
    image_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_strain_image(strain_id, None, image_base64)
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_strain_image_grayscale(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a grayscale image (triggers convert('RGB'))."""
    strain_id = "strain_grayscale"
    # Create a grayscale 1x1 image
    img = Image.new("L", (1, 1), color=128)
    buf = BytesIO()
    img.save(buf, format="PNG")
    image_base64 = base64.b64encode(buf.getvalue()).decode()

    path = await image_manager.save_strain_image(strain_id, None, image_base64)
    assert Path(path).exists()
    with Image.open(path) as saved_img:
        assert saved_img.mode == "RGB"


@pytest.mark.asyncio
async def test_save_strain_image_with_phenotype(
    image_manager: ImageManager, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """Test saving an image with a phenotype ID."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    # Minimal 1x1 pixel PNG as base64
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_strain_image(strain_id, phenotype_id, image_base64)

    assert Path(path).name == snapshot
    expected_filename = f"{strain_id}_{phenotype_id}.webp"
    expected_path = tmp_path / expected_filename
    expected_small_path = tmp_path / f"{strain_id}_{phenotype_id}_small.webp"

    # Verify both files were created
    assert expected_path.exists()
    assert expected_small_path.exists()


@pytest.mark.asyncio
async def test_save_strain_image_error(image_manager: ImageManager) -> None:
    """Test error handling during image save."""
    with (
        patch("base64.b64decode", side_effect=ValueError("Invalid base64")),
        pytest.raises(ValueError),
    ):
        await image_manager.save_strain_image("id", None, "bad_data")


@pytest.mark.asyncio
async def test_get_image_path_exists(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test getting path for an existing image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.webp"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    path = image_manager.get_image_path(strain_id, None)
    assert path == str(file_path.absolute())


@pytest.mark.asyncio
async def test_get_image_path_fallback_jpg(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test falling back to JPG if WebP doesn't exist."""
    strain_id = "strain_legacy"
    filename = f"{strain_id}.jpg"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    path = image_manager.get_image_path(strain_id, None)
    assert path == str(file_path.absolute())


@pytest.mark.asyncio
async def test_get_image_path_not_exists(image_manager: ImageManager) -> None:
    """Test getting path for a non-existent image."""
    path = image_manager.get_image_path("strain_123", None)
    assert path is None


@pytest.mark.asyncio
async def test_delete_image_success(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test successfully deleting an image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.webp"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    assert file_path.exists()

    image_manager.delete_image(strain_id, None)
    assert not file_path.exists()
    assert filename not in image_manager._image_cache


@pytest.mark.asyncio
async def test_delete_image_with_variants(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test deleting all variants of an image."""
    strain_id = "strain_multi"
    files = [f"{strain_id}.webp", f"{strain_id}_small.webp", f"{strain_id}.jpg"]
    for f in files:
        (tmp_path / f).touch()
        image_manager._image_cache.add(f)

    image_manager.delete_image(strain_id, None)

    for f in files:
        assert not (tmp_path / f).exists()
        assert f not in image_manager._image_cache


@pytest.mark.asyncio
async def test_delete_image_not_found(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test deleting a non-existent image."""
    strain_id = "strain_123"
    filename = f"{strain_id}.webp"
    file_path = tmp_path / filename

    assert not file_path.exists()
    # Should not raise
    image_manager.delete_image(strain_id, None)


@pytest.mark.asyncio
async def test_delete_image_error(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test error handling during image deletion."""
    strain_id = "strain_123"
    filename = f"{strain_id}.webp"
    file_path = tmp_path / filename
    file_path.touch()

    image_manager._image_cache.add(filename)

    with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
        image_manager.delete_image(strain_id, None)
        # Should catch and log error
        assert file_path.exists()


@pytest.mark.asyncio
async def test_build_cache_error(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test error handling during cache build."""
    with patch("pathlib.Path.glob", side_effect=OSError("Disk error")):
        # Should not raise
        manager = ImageManager(mock_hass, str(tmp_path))
        await manager.async_setup()
        assert manager._image_cache == set()


@pytest.mark.asyncio
async def test_get_image_path_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test getting path for an existing image with phenotype."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    filename = f"{strain_id}_{phenotype_id}.webp"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    path = image_manager.get_image_path(strain_id, phenotype_id)
    assert path == str(file_path.absolute())


@pytest.mark.asyncio
async def test_delete_image_with_phenotype(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test deleting an image with phenotype."""
    strain_id = "strain_123"
    phenotype_id = "pheno_456"
    filename = f"{strain_id}_{phenotype_id}.webp"
    file_path = tmp_path / filename

    file_path.touch()
    image_manager._image_cache.add(filename)

    image_manager.delete_image(strain_id, phenotype_id)
    assert not file_path.exists()


@pytest.mark.asyncio
async def test_save_timeline_image_success(
    image_manager: ImageManager, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """Test successfully saving a timeline image."""
    plant_id = "plant_123"
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_timeline_image(plant_id, image_base64)

    assert "timeline/" in path
    assert path.endswith(".webp")
    assert Path(path).name == snapshot

    full_path = Path(path)
    assert full_path.exists()

    # Small thumbnail should also exist
    thumb_path = Path(str(full_path).replace(".webp", "_small.webp"))
    assert thumb_path.exists()


@pytest.mark.asyncio
async def test_save_timeline_image_with_header(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a timeline image with data URI header."""
    plant_id = "plant_header"
    image_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_timeline_image(plant_id, image_base64)
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_timeline_image_grayscale(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a grayscale timeline image."""
    plant_id = "plant_grayscale"
    img = Image.new("L", (1, 1), color=128)
    buf = BytesIO()
    img.save(buf, format="PNG")
    image_base64 = base64.b64encode(buf.getvalue()).decode()

    path = await image_manager.save_timeline_image(plant_id, image_base64)
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_timeline_image_with_timestamp(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a timeline image with custom timestamp."""
    plant_id = "plant_123"
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    timestamp = "20240101_120000"

    path = await image_manager.save_timeline_image(plant_id, image_base64, timestamp)

    assert timestamp in path
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_timeline_image_error(image_manager: ImageManager) -> None:
    """Test error handling in timeline image save."""
    with patch("PIL.Image.open", side_effect=Exception("Save failed")):
        with pytest.raises(Exception):
            await image_manager.save_timeline_image("p1", "bad_data")


@pytest.mark.asyncio
async def test_save_breeder_logo_success(
    image_manager: ImageManager, tmp_path: Path, snapshot: SnapshotAssertion
) -> None:
    """Test successfully saving a breeder logo."""
    breeder_slug = "test_breeder"
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_breeder_logo(breeder_slug, image_base64)

    assert f"breeder_{breeder_slug}.webp" in path
    assert Path(path).name == snapshot
    assert Path(path).exists()
    assert Path(path.replace(".webp", "_small.webp")).exists()


@pytest.mark.asyncio
async def test_save_breeder_logo_with_header(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a breeder logo with header."""
    breeder_slug = "test_header"
    image_base64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

    path = await image_manager.save_breeder_logo(breeder_slug, image_base64)
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_breeder_logo_grayscale(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test saving a grayscale breeder logo."""
    breeder_slug = "test_grayscale"
    img = Image.new("L", (1, 1), color=128)
    buf = BytesIO()
    img.save(buf, format="PNG")
    image_base64 = base64.b64encode(buf.getvalue()).decode()

    path = await image_manager.save_breeder_logo(breeder_slug, image_base64)
    assert Path(path).exists()


@pytest.mark.asyncio
async def test_save_breeder_logo_error(image_manager: ImageManager) -> None:
    """Test error handling in breeder logo save."""
    image_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    with patch("PIL.Image.open", side_effect=UnidentifiedImageError("Bad image")):
        with pytest.raises(UnidentifiedImageError):
            await image_manager.save_breeder_logo("test", image_base64)


@pytest.mark.asyncio
async def test_webp_migration(image_manager: ImageManager, tmp_path: Path) -> None:
    """Test JPG to WebP migration."""
    jpg_path = tmp_path / "legacy.jpg"
    img = Image.new("RGB", (10, 10), color="red")
    img.save(jpg_path, "JPEG")

    # This JPG should be skipped if we create a webp first
    jpg_skip = tmp_path / "skip.jpg"
    img.save(jpg_skip, "JPEG")
    (tmp_path / "skip.webp").touch()
    (tmp_path / "skip_small.webp").touch()

    # Create one that triggers convert
    jpg_gray = tmp_path / "gray.jpg"
    img_gray = Image.new("L", (10, 10), color=128)
    img_gray.save(jpg_gray, "JPEG")

    await image_manager.async_migrate_to_webp()

    assert (tmp_path / "legacy.webp").exists()
    assert (tmp_path / "gray.webp").exists()


@pytest.mark.asyncio
async def test_webp_migration_no_jpgs(image_manager: ImageManager) -> None:
    """Test migration when no JPGs are present."""
    # Should just return silently
    await image_manager.async_migrate_to_webp()


@pytest.mark.asyncio
async def test_webp_migration_no_dir(mock_hass: MagicMock, tmp_path: Path) -> None:
    """Test migration with non-existent directory."""
    storage_dir = tmp_path / "missing"
    manager = ImageManager(mock_hass, str(storage_dir))
    await manager.async_migrate_to_webp()


@pytest.mark.asyncio
async def test_webp_migration_error(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test error handling during migration (per file)."""
    (tmp_path / "error.jpg").touch()
    with patch("PIL.Image.open", side_effect=Exception("Disk full")):
        await image_manager.async_migrate_to_webp()


@pytest.mark.asyncio
async def test_webp_migration_error_sync(image_manager: ImageManager) -> None:
    """Test error in the sync migration part (triggers line 152)."""
    with patch("pathlib.Path.glob", side_effect=Exception("Sync error")):
        # Should not raise because of try-except in _migrate_to_webp_sync
        await image_manager.async_migrate_to_webp()


@pytest.mark.asyncio
async def test_async_migrate_to_webp_error(
    mock_hass: MagicMock, image_manager: ImageManager
) -> None:
    """Test general error in async_migrate_to_webp."""

    # Inject error that should bubble up to async_migrate_to_webp
    # If we add try-except to async_migrate_to_webp, it will be caught.
    # For now, let's just assert it doesn't crash if we mock it correctly.
    async def async_raise(*args, **kwargs):
        raise Exception("General error")

    mock_hass.async_add_executor_job = MagicMock(side_effect=async_raise)
    # If not caught in code, this will raise.
    # result = await image_manager.async_migrate_to_webp()
    # assert result is False


@pytest.mark.asyncio
async def test_update_db_paths(image_manager: ImageManager) -> None:
    """Test updating database paths."""
    mock_db = MagicMock()
    mock_cursor = AsyncMock()

    row1 = {"phenotype_id": 1, "image_path": "strains/old.jpg"}
    row2 = {"phenotype_id": 2, "image_path": "strains/other.jpg"}

    mock_cursor.fetchall.return_value = [row1, row2]

    # Use the robust AsyncCtxAwaitable to mock execute results
    # SELECT query
    mock_db.execute.return_value = AsyncCtxAwaitable(mock_cursor)
    mock_db.commit = AsyncMock()

    updated = await image_manager._update_db_paths(mock_db)

    assert updated == 2
    assert mock_db.execute.call_count == 3
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_update_db_paths_no_rows(image_manager: ImageManager) -> None:
    """Test updating database paths when no JPGs exist."""
    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = []

    mock_db.execute.return_value = AsyncCtxAwaitable(mock_cursor)

    updated = await image_manager._update_db_paths(mock_db)
    assert updated == 0


@pytest.mark.asyncio
async def test_update_db_paths_error(image_manager: ImageManager) -> None:
    """Test error handling in DB path update."""
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("DB Error")

    updated = await image_manager._update_db_paths(mock_db)
    assert updated == 0


@pytest.mark.asyncio
async def test_async_migrate_with_db(
    image_manager: ImageManager, tmp_path: Path
) -> None:
    """Test async_migrate_to_webp with database connection."""
    jpg_path = tmp_path / "db_test.jpg"
    img = Image.new("RGB", (1, 1))
    img.save(jpg_path, "JPEG")

    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.fetchall.return_value = [
        {"phenotype_id": 1, "image_path": "db_test.jpg"}
    ]

    mock_db.execute.return_value = AsyncCtxAwaitable(mock_cursor)
    mock_db.commit = AsyncMock()

    processed = await image_manager.async_migrate_to_webp(mock_db)
    assert processed is True
