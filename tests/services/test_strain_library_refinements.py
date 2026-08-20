"""Tests for strain library refinements (stubs and 0% percentages)."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass():
    """Fixture for a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    return hass

@pytest.fixture
def mock_image_manager():
    """Fixture for a mock ImageManager."""
    manager = MagicMock()
    manager.save_strain_image = AsyncMock(return_value="/abs/path/to/image.jpg")
    manager.delete_image = MagicMock()
    manager.async_migrate_to_webp = AsyncMock(return_value=False)
    manager.async_setup = AsyncMock()
    return manager

@pytest.fixture
def mock_import_export_manager():
    """Fixture for a mock ImportExportManager."""
    manager = MagicMock()
    manager.export_library = AsyncMock(return_value="/path/to/export.zip")
    manager.import_library = AsyncMock(return_value={})
    return manager

@pytest.fixture
async def strain_library(mock_hass, mock_image_manager, mock_import_export_manager):
    """Fixture for a StrainLibrary instance with in-memory DB."""
    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        return await real_connect(":memory:", **kwargs)

    with (
        patch("custom_components.growspace_manager.strain_library.ImageManager", return_value=mock_image_manager),
        patch("custom_components.growspace_manager.strain_library.ImportExportManager", return_value=mock_import_export_manager),
        patch("custom_components.growspace_manager.strain_library.aiosqlite.connect", side_effect=mock_connect),
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()
        yield library
        await library.async_close()

@pytest.mark.asyncio
async def test_add_strain_0_percentages(strain_library: StrainLibrary) -> None:
    """Test that 0% / 0% sativa/indica values are treated as unknown (NULL)."""
    # 1. Both are 0 -> should be None
    await strain_library.add_strain(
        strain="Unknown Strain",
        strain_type="Hybrid",
        sativa_percentage=0,
        indica_percentage=0,
    )

    meta = strain_library.strains["Unknown Strain"]["meta"]
    assert "sativa_percentage" not in meta
    assert "indica_percentage" not in meta

    # 2. Pure strain (100/0) -> 0 should be kept
    await strain_library.add_strain(
        strain="Pure Sativa",
        strain_type="Hybrid",
        sativa_percentage=100,
        indica_percentage=0,
    )

    meta = strain_library.strains["Pure Sativa"]["meta"]
    assert meta["sativa_percentage"] == 100
    assert meta["indica_percentage"] == 0

    # 3. Pure strain (0/100) -> 0 should be kept
    await strain_library.add_strain(
        strain="Pure Indica",
        strain_type="Hybrid",
        sativa_percentage=0,
        indica_percentage=100,
    )

    meta = strain_library.strains["Pure Indica"]["meta"]
    assert meta["sativa_percentage"] == 0
    assert meta["indica_percentage"] == 100

@pytest.mark.asyncio
async def test_export_filters_stubs(strain_library: StrainLibrary, mock_import_export_manager) -> None:
    """Test that is_stub strains are excluded from exports."""
    # Add a real strain
    await strain_library.add_strain(strain="Real Strain", breeder="Real")

    # Add a stub strain (simulating ancestor resolution)
    await strain_library._db.execute(
        "INSERT INTO strains (strain_name, is_stub) VALUES (?, ?)",
        ("Stub Strain", 1)
    )
    await strain_library._db.commit()
    await strain_library.load()

    assert "Real Strain" in strain_library.strains
    assert "Stub Strain" in strain_library.strains
    assert strain_library.strains["Stub Strain"]["meta"]["is_stub"] is True

    # Export
    await strain_library.export_library_to_zip("/tmp/growspace_test_export")

    # Verify mock was called with filtered data
    exported_data = mock_import_export_manager.export_library.call_args[0][0]
    assert "Real Strain" in exported_data
    assert "Stub Strain" not in exported_data
