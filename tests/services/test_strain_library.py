"""Tests for the StrainLibrary class."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from custom_components.growspace_manager.image_manager import ImageManager
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
    # We patch aiosqlite.connect to return a connection to :memory:
    # regardless of the path passed to it.

    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        return await real_connect(":memory:", **kwargs)

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=mock_image_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.ImportExportManager",
            return_value=mock_import_export_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.aiosqlite.connect",
            side_effect=mock_connect,
        ),
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()

        yield library

        await library.async_close()


@pytest.mark.asyncio
async def test_add_strain_and_load(strain_library: StrainLibrary) -> None:
    """Test adding a strain and verifying it loads correctly."""
    await strain_library.add_strain(
        strain="Blue Dream",
        breeder="Humboldt",
        strain_type="Hybrid",
        sativa_percentage=60,
    )

    assert "Blue Dream" in strain_library.strains
    strain_data = strain_library.strains["Blue Dream"]
    assert strain_data["meta"]["breeder"] == "Humboldt"
    assert strain_data["meta"]["sativa_percentage"] == 60
    assert strain_data["meta"]["indica_percentage"] == 40  # Auto-calculated


@pytest.mark.asyncio
async def test_add_strain_with_phenotype(strain_library: StrainLibrary) -> None:
    """Test adding a strain with a specific phenotype."""
    await strain_library.add_strain(
        strain="Gorilla Glue",
        phenotype="#4",
        description="Sticky",
        flower_days_min=60,
        flower_days_max=65,
    )


@pytest.mark.asyncio
async def test_add_strain_fetch_failure(strain_library: StrainLibrary) -> None:
    """Test RuntimeError when strain is not found after adding."""

    # Cursor for the SELECT
    class MockCursor:
        def __await__(self):
            async def _inner():
                return self

            return _inner().__await__()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def fetchone(self):
            return None

    with patch.object(strain_library._db, "execute") as mock_execute:
        mock_execute.return_value = MockCursor()

        with pytest.raises(RuntimeError, match="Strain Test Strain not found"):
            await strain_library.add_strain(strain="Test Strain")


@pytest.mark.asyncio
async def test_record_harvest_and_analytics(strain_library: StrainLibrary) -> None:
    """Test recording harvests and analytics calculation."""
    await strain_library.add_strain("OG Kush", "Original")

    await strain_library.record_harvest(
        "OG Kush", "Original", veg_days=30, flower_days=60
    )
    await strain_library.record_harvest(
        "OG Kush", "Original", veg_days=35, flower_days=65
    )

    # Check in-memory update
    pheno = strain_library.strains["OG Kush"]["phenotypes"]["Original"]
    assert len(pheno["harvests"]) == 2

    # Check analytics
    analytics = strain_library.get_analytics()
    strain_stats = analytics["strains"]["OG Kush"]["analytics"]

    assert strain_stats["total_harvests"] == 2
    assert (
        strain_stats["avg_veg_days"] == 32
    )  # (30+35)/2 = 32.5 -> 32 (round half to even? or standard round?)
    # Python 3 round(32.5) is 32 (nearest even). Let's check implementation.
    # Implementation uses round().
    assert strain_stats["avg_flower_days"] == 62  # (60+65)/2 = 62.5 -> 62


@pytest.mark.asyncio
async def test_remove_strain_phenotype(
    strain_library: StrainLibrary, mock_image_manager
) -> None:
    """Test removing a phenotype."""
    await strain_library.add_strain("Gelato", "#33")
    await strain_library.add_strain("Gelato", "#41")

    assert len(strain_library.strains["Gelato"]["phenotypes"]) == 2

    await strain_library.remove_strain_phenotype("Gelato", "#33")

    assert len(strain_library.strains["Gelato"]["phenotypes"]) == 1
    assert "#41" in strain_library.strains["Gelato"]["phenotypes"]
    mock_image_manager.delete_image.assert_called()


@pytest.mark.asyncio
async def test_remove_strain(strain_library: StrainLibrary) -> None:
    """Test removing an entire strain."""
    await strain_library.add_strain("Sour Diesel")
    assert "Sour Diesel" in strain_library.strains

    await strain_library.remove_strain("Sour Diesel")
    assert "Sour Diesel" not in strain_library.strains


@pytest.mark.asyncio
async def test_import_library(strain_library: StrainLibrary) -> None:
    """Test importing a library dictionary."""
    import_data = {
        "Imported Strain": {
            "meta": {"breeder": "Imported"},
            "phenotypes": {
                "Imported Pheno": {
                    "description": "Imported desc",
                    "harvests": [
                        {
                            "veg_days": 20,
                            "flower_days": 50,
                            "harvest_date": "2023-01-01",
                        }
                    ],
                }
            },
        }
    }

    await strain_library.import_library(import_data, replace=True)

    assert "Imported Strain" in strain_library.strains
    assert strain_library.strains["Imported Strain"]["meta"]["breeder"] == "Imported"
    pheno = strain_library.strains["Imported Strain"]["phenotypes"]["Imported Pheno"]
    assert len(pheno["harvests"]) == 1
    assert pheno["harvests"][0]["veg_days"] == 20


@pytest.mark.asyncio
async def test_import_strains_list(strain_library: StrainLibrary) -> None:
    """Test importing a list of strain names."""
    strains = ["Strain A", "Strain B"]
    await strain_library.import_strains(strains, replace=True)

    assert "Strain A" in strain_library.strains
    assert "Strain B" in strain_library.strains
    assert len(strain_library.strains) == 2


@pytest.mark.asyncio
async def test_hybrid_percentage_validation(strain_library: StrainLibrary) -> None:
    """Test validation of hybrid percentages."""
    with pytest.raises(
        ValueError, match="Combined Sativa/Indica percentage cannot exceed 100%"
    ):
        await strain_library.add_strain(
            "Bad Hybrid",
            strain_type="Hybrid",
            sativa_percentage=60,
            indica_percentage=50,
        )


@pytest.mark.asyncio
async def test_image_handling(
    strain_library: StrainLibrary, mock_image_manager
) -> None:
    """Test image saving during add_strain."""
    await strain_library.add_strain(
        "Photo Strain", "Pheno", image_base64="data:image/jpeg;base64,..."
    )

    mock_image_manager.save_strain_image.assert_awaited()
    pheno = strain_library.strains["Photo Strain"]["phenotypes"]["Pheno"]
    assert pheno["image_path"] == "/local/growspace_manager/strains/image.jpg"


@pytest.mark.asyncio
async def test_save_noop(strain_library: StrainLibrary) -> None:
    """Test that save() is a no-op."""
    await strain_library.save()  # Should not raise


@pytest.mark.asyncio
async def test_get_all(strain_library: StrainLibrary) -> None:
    """Test get_all() returns the strains dictionary."""
    await strain_library.add_strain("Test Strain")
    all_strains = strain_library.get_all()
    assert "Test Strain" in all_strains


@pytest.mark.asyncio
async def test_analytics_with_zero_harvests(strain_library: StrainLibrary) -> None:
    """Test analytics calculation when phenotype has zero harvests."""
    await strain_library.add_strain("No Harvest Strain", "Pheno1")

    analytics = strain_library.get_analytics()
    strain_stats = analytics["strains"]["No Harvest Strain"]["analytics"]

    assert strain_stats["total_harvests"] == 0
    assert strain_stats["avg_veg_days"] == 0
    assert strain_stats["avg_flower_days"] == 0

    # Test phenotype analytics
    pheno_stats = analytics["strains"]["No Harvest Strain"]["phenotypes"]["Pheno1"]
    assert pheno_stats["total_harvests"] == 0
    assert pheno_stats["avg_veg_days"] == 0
    assert pheno_stats["avg_flower_days"] == 0


@pytest.mark.asyncio
async def test_analytics_caching(strain_library: StrainLibrary) -> None:
    """Test that analytics are cached."""
    await strain_library.add_strain("Cache Test")

    # First call should calculate
    analytics1 = strain_library.get_analytics()

    # Second call should return cached value
    analytics2 = strain_library.get_analytics()

    assert analytics1 is analytics2


@pytest.mark.asyncio
async def test_set_strain_meta(strain_library: StrainLibrary) -> None:
    """Test set_strain_meta() updates metadata."""
    await strain_library.add_strain("Meta Strain")

    await strain_library.set_strain_meta(
        "Meta Strain", breeder="New Breeder", strain_type="Indica"
    )

    assert strain_library.strains["Meta Strain"]["meta"]["breeder"] == "New Breeder"
    assert strain_library.strains["Meta Strain"]["meta"]["type"] == "Indica"


@pytest.mark.asyncio
async def test_remove_strain_phenotype_nonexistent(
    strain_library: StrainLibrary,
) -> None:
    """Test removing a non-existent phenotype (should not error)."""
    await strain_library.remove_strain_phenotype("NonExistent", "Pheno")
    # Should not raise


@pytest.mark.asyncio
async def test_remove_strain_nonexistent(strain_library: StrainLibrary) -> None:
    """Test removing a non-existent strain (should not error)."""
    await strain_library.remove_strain("NonExistent")
    # Should not raise


@pytest.mark.asyncio
async def test_remove_strain_phenotype_deletes_strain_when_no_phenotypes_remain(
    strain_library: StrainLibrary, mock_image_manager: ImageManager
) -> None:
    """Test that strain is deleted when all phenotypes are removed."""
    await strain_library.add_strain("Single Pheno Strain", "OnlyOne")

    assert "Single Pheno Strain" in strain_library.strains

    await strain_library.remove_strain_phenotype("Single Pheno Strain", "OnlyOne")

    assert "Single Pheno Strain" not in strain_library.strains


@pytest.mark.asyncio
async def test_record_harvest_creates_strain_if_not_exists(
    strain_library: StrainLibrary,
) -> None:
    """Test that record_harvest creates strain/phenotype if they don't exist."""
    await strain_library.record_harvest("New Strain", "New Pheno", 30, 60)

    assert "New Strain" in strain_library.strains
    assert "New Pheno" in strain_library.strains["New Strain"]["phenotypes"]
    assert (
        len(strain_library.strains["New Strain"]["phenotypes"]["New Pheno"]["harvests"])
        == 1
    )


@pytest.mark.asyncio
async def test_ensure_strain_and_phenotype_exist_creates_phenotype(
    strain_library: StrainLibrary,
) -> None:
    """Test _ensure_strain_and_phenotype_exist creates phenotype if only strain exists."""
    await strain_library.add_strain("Existing Strain", "Pheno1")

    # Now request a different phenotype
    phenotype_id = await strain_library._ensure_strain_and_phenotype_exist(
        "Existing Strain", "Pheno2"
    )

    assert phenotype_id is not None
    await strain_library.load()
    assert "Pheno2" in strain_library.strains["Existing Strain"]["phenotypes"]


@pytest.mark.asyncio
async def test_hybrid_sativa_percentage_auto_calc(
    strain_library: StrainLibrary,
) -> None:
    """Test that indica percentage is auto-calculated for hybrid."""
    await strain_library.add_strain(
        "Auto Calc Hybrid", strain_type="Hybrid", sativa_percentage=70
    )

    assert strain_library.strains["Auto Calc Hybrid"]["meta"]["sativa_percentage"] == 70
    assert strain_library.strains["Auto Calc Hybrid"]["meta"]["indica_percentage"] == 30


@pytest.mark.asyncio
async def test_hybrid_indica_percentage_auto_calc(
    strain_library: StrainLibrary,
) -> None:
    """Test that sativa percentage is auto-calculated for hybrid."""
    await strain_library.add_strain(
        "Auto Calc Hybrid 2", strain_type="Hybrid", indica_percentage=80
    )

    assert (
        strain_library.strains["Auto Calc Hybrid 2"]["meta"]["indica_percentage"] == 80
    )
    assert (
        strain_library.strains["Auto Calc Hybrid 2"]["meta"]["sativa_percentage"] == 20
    )


@pytest.mark.asyncio
async def test_add_strain_with_image_path(strain_library: StrainLibrary) -> None:
    """Test adding strain with image_path instead of image_base64."""
    await strain_library.add_strain(
        "Path Strain", "Pheno", image_path="/local/custom/path.jpg"
    )

    pheno = strain_library.strains["Path Strain"]["phenotypes"]["Pheno"]
    assert pheno["image_path"] == "/local/custom/path.jpg"


@pytest.mark.asyncio
async def test_import_library_invalid_data(strain_library: StrainLibrary) -> None:
    """Test that import_library handles invalid data gracefully."""
    # Import with non-dict data
    result = await strain_library.import_library("not a dict", replace=False)  # type: ignore[arg-type]
    assert result == 0  # Should return current count


@pytest.mark.asyncio
async def test_import_strains_invalid_data(strain_library: StrainLibrary) -> None:
    """Test that import_strains handles invalid data gracefully."""
    # Import with non-list data
    result = await strain_library.import_strains("not a list", replace=False)  # type: ignore[arg-type]
    assert result == 0  # Should return current count


@pytest.mark.asyncio
async def test_import_library_with_legacy_image_path(
    strain_library: StrainLibrary,
) -> None:
    """Test importing library with legacy image path format."""
    import_data = {
        "Legacy Strain": {
            "meta": {},
            "phenotypes": {
                "Pheno": {"image_path": "images/old_image.jpg", "harvests": []}
            },
        }
    }

    await strain_library.import_library(import_data, replace=True)

    pheno = strain_library.strains["Legacy Strain"]["phenotypes"]["Pheno"]
    assert pheno["image_path"] == "/local/growspace_manager/strains/old_image.jpg"


@pytest.mark.asyncio
async def test_export_library_to_zip(
    strain_library: StrainLibrary, mock_import_export_manager, tmp_path: Path
) -> None:
    """Test exporting library to ZIP."""
    await strain_library.add_strain("Export Strain")

    result = await strain_library.export_library_to_zip(str(tmp_path))

    assert result == "/path/to/export.zip"
    mock_import_export_manager.export_library.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_library_from_zip(
    strain_library: StrainLibrary, mock_import_export_manager
) -> None:
    """Test importing library from ZIP."""
    mock_import_export_manager.import_library.return_value = {
        "Imported Strain": {"meta": {}, "phenotypes": {"Pheno": {"harvests": []}}}
    }

    result = await strain_library.import_library_from_zip(
        "/path/to/import.zip", merge=True
    )

    assert result == 1  # Should have 1 strain
    mock_import_export_manager.import_library.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_with_invalid_json_in_image_crop_meta(
    strain_library: StrainLibrary, mock_hass
) -> None:
    """Test load() handles invalid JSON in image_crop_meta gracefully."""
    # Manually insert a phenotype with invalid JSON in image_crop_meta
    assert strain_library._db is not None
    await strain_library._db.execute(
        """
        INSERT INTO strains (strain_name) VALUES (?)
        """,
        ("Bad JSON Strain",),
    )
    await strain_library._db.execute(
        """
        INSERT INTO phenotypes (strain_id, phenotype_name, image_crop_meta)
        SELECT strain_id, 'Pheno', 'invalid json'
        FROM strains WHERE strain_name = 'Bad JSON Strain'
        """
    )
    await strain_library._db.commit()

    # This should not raise, but log a warning
    await strain_library.load()

    assert "Bad JSON Strain" in strain_library.strains
    pheno = strain_library.strains["Bad JSON Strain"]["phenotypes"]["Pheno"]
    # image_crop_meta should not be in the phenotype data due to the None filter
    assert "image_crop_meta" not in pheno


@pytest.mark.asyncio
async def test_ensure_strain_and_phenotype_exist_strain_creation_failure(
    strain_library: StrainLibrary,
) -> None:
    """Test RuntimeError when strain creation fails unexpectedly."""
    # This is a very edge case scenario. We need to simulate a situation where
    # add_strain completes but the strain is not actually created.
    # This is difficult to simulate without deep mocking.
    # One approach is to mock add_strain to not actually add anything.

    with (
        patch.object(strain_library, "add_strain", new_callable=AsyncMock),
        pytest.raises(RuntimeError, match="Failed to create strain"),
    ):
        # add_strain will be called but won't actually create the strain
        await strain_library._ensure_strain_and_phenotype_exist(
            "Failing Strain", "Pheno"
        )


@pytest.mark.asyncio
async def test_breeder_logo_propagation(strain_library: StrainLibrary) -> None:
    """Test that breeder logos are propagated across strains from the same breeder."""
    # 1. Add first strain with breeder and logo
    await strain_library.add_strain(
        strain="Strain 1",
        breeder="Paradise Seeds",
        breeder_logo="https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Gold.webp",
    )

    assert "Strain 1" in strain_library.strains
    assert (
        strain_library.strains["Strain 1"]["meta"]["breeder_logo"]
        == "https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Gold.webp"
    )

    # 2. Add second strain with same breeder but NO logo
    await strain_library.add_strain(
        strain="Strain 2",
        breeder="Paradise Seeds",
    )

    assert "Strain 2" in strain_library.strains
    # Should have automatically picked up the logo from Strain 1
    assert (
        strain_library.strains["Strain 2"]["meta"]["breeder_logo"]
        == "https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Gold.webp"
    )

    # 3. Update logo for Strain 1
    await strain_library.add_strain(
        strain="Strain 1",
        breeder="Paradise Seeds",
        breeder_logo="https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Black.webp",
    )

    # Strain 2 should have been updated as well
    await strain_library.load()
    assert (
        strain_library.strains["Strain 1"]["meta"]["breeder_logo"]
        == "https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Black.webp"
    )
    assert (
        strain_library.strains["Strain 2"]["meta"]["breeder_logo"]
        == "https://www.paradise-seeds.com/wp-content/uploads/Logo-paradise-seeds-Black.webp"
    )


@pytest.mark.asyncio
async def test_update_breeder(strain_library: StrainLibrary) -> None:
    """Test updating breeder name and logo."""
    await strain_library.add_strain("Strain 1", breeder="Breeder A")
    await strain_library.add_strain("Strain 2", breeder="Breeder A")

    # Update name
    await strain_library.update_breeder("Breeder A", "Breeder B")
    assert strain_library.strains["Strain 1"]["meta"]["breeder"] == "Breeder B"
    assert strain_library.strains["Strain 2"]["meta"]["breeder"] == "Breeder B"

    # Update logo (path)
    await strain_library.update_breeder(
        "Breeder B", "Breeder B", logo="/local/logo.png"
    )
    assert (
        strain_library.strains["Strain 1"]["meta"]["breeder_logo"] == "/local/logo.png"
    )

    # Update logo (base64)
    with patch.object(
        strain_library.image_manager,
        "save_breeder_logo",
        AsyncMock(return_value="/abs/path/to/logo.webp"),
    ):
        await strain_library.update_breeder(
            "Breeder B", "Breeder C", logo="data:image/webp;base64,..."
        )
        assert strain_library.strains["Strain 1"]["meta"]["breeder"] == "Breeder C"
        assert (
            strain_library.strains["Strain 1"]["meta"]["breeder_logo"]
            == "/local/growspace_manager/strains/logo.webp"
        )

    # Clear logo
    await strain_library.update_breeder("Breeder C", "Breeder C", logo="")
    assert "breeder_logo" not in strain_library.strains["Strain 1"]["meta"]


@pytest.mark.asyncio
async def test_delete_breeder(strain_library: StrainLibrary) -> None:
    """Test deleting breeder association."""
    await strain_library.add_strain("Strain 1", breeder="Breeder A", breeder_logo="L")
    await strain_library.delete_breeder("Breeder A")

    assert "breeder" not in strain_library.strains["Strain 1"]["meta"]
    assert "breeder_logo" not in strain_library.strains["Strain 1"]["meta"]


@pytest.mark.asyncio
async def test_delete_breeder_invalid(strain_library: StrainLibrary) -> None:
    """Test deleting breeder with empty name."""
    assert await strain_library.delete_breeder("") == 0
    assert await strain_library.delete_breeder("  ") == 0


@pytest.mark.asyncio
async def test_update_breeder_invalid(strain_library: StrainLibrary) -> None:
    """Test updating breeder with empty names."""
    assert await strain_library.update_breeder("", "New") == 0
    assert await strain_library.update_breeder("Old", "") == 0


@pytest.mark.asyncio
async def test_db_migration_breeder_logo(mock_hass, mock_image_manager) -> None:
    """Test that breeder_logo column is added if missing."""
    # Create schema without breeder_logo
    LEGACY_SCHEMA = """
    CREATE TABLE strains (
        strain_id INTEGER PRIMARY KEY,
        strain_name TEXT UNIQUE NOT NULL,
        breeder TEXT,
        type TEXT,
        lineage TEXT,
        sex TEXT,
        sativa_percentage INTEGER,
        indica_percentage INTEGER
    );
    """

    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        conn = await real_connect(":memory:", **kwargs)
        await conn.executescript(LEGACY_SCHEMA)
        await conn.commit()
        return conn

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=mock_image_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.aiosqlite.connect",
            side_effect=mock_connect,
        ),
    ):
        library = StrainLibrary(mock_hass)
        # async_setup should run ALTER TABLE
        await library.async_setup()

        # Check if column exists
        async with library._db.execute("PRAGMA table_info(strains)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]
            assert "breeder_logo" in columns

        await library.async_close()


@pytest.mark.asyncio
async def test_async_setup_with_migration_reload(
    mock_hass, mock_image_manager, mock_import_export_manager
) -> None:
    """Test load() is called again if migration happens."""
    mock_image_manager.async_migrate_to_webp.return_value = True

    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        return await real_connect(":memory:", **kwargs)

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=mock_image_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.ImportExportManager",
            return_value=mock_import_export_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.aiosqlite.connect",
            side_effect=mock_connect,
        ),
        patch.object(StrainLibrary, "load", AsyncMock()) as mock_load,
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()

        # Should be called during async_setup AND after migration
        assert mock_load.call_count == 2
        await library.async_close()


@pytest.mark.asyncio
async def test_record_harvest_no_db(mock_hass) -> None:
    """Test record_harvest when DB is not connected."""
    library = StrainLibrary(mock_hass)
    assert library._db is None
    await library.record_harvest("S", "P", 1, 1)
    # Should log warning and return


@pytest.mark.asyncio
async def test_update_breeder_no_db(mock_hass) -> None:
    """Test update_breeder when DB is not connected."""
    library = StrainLibrary(mock_hass)
    assert await library.update_breeder("O", "N") == 0


@pytest.mark.asyncio
async def test_delete_breeder_no_db(mock_hass) -> None:
    """Test delete_breeder when DB is not connected."""
    library = StrainLibrary(mock_hass)
    assert await library.delete_breeder("B") == 0


@pytest.mark.asyncio
async def test_add_strain_no_db(mock_hass) -> None:
    """Test add_strain when DB is not connected."""
    library = StrainLibrary(mock_hass)
    await library.add_strain("S")
    # Should log warning and return


@pytest.mark.asyncio
async def test_remove_strain_phenotype_no_db(mock_hass) -> None:
    """Test remove_strain_phenotype when DB is not connected."""
    library = StrainLibrary(mock_hass)
    await library.remove_strain_phenotype("S", "P")
    # Should log warning and return


@pytest.mark.asyncio
async def test_remove_strain_no_db(mock_hass) -> None:
    """Test remove_strain when DB is not connected."""
    library = StrainLibrary(mock_hass)
    await library.remove_strain("S")
    # Should log warning and return


@pytest.mark.asyncio
async def test_import_library_no_db(mock_hass) -> None:
    """Test import_library when DB is not connected."""
    library = StrainLibrary(mock_hass)
    assert await library.import_library({}) == 0


@pytest.mark.asyncio
async def test_clear_no_db(mock_hass) -> None:
    """Test clear when DB is not connected."""
    library = StrainLibrary(mock_hass)
    assert await library.clear() == 0


@pytest.mark.asyncio
async def test_analytics_snapshot(strain_library: StrainLibrary, snapshot) -> None:
    """Test analytics output with snapshot."""
    await strain_library.add_strain(
        "Blue Dream",
        breeder="Humboldt",
        strain_type="Hybrid",
        sativa_percentage=60,
    )
    await strain_library.record_harvest("Blue Dream", "default", 30, 60)

    analytics = strain_library.get_analytics()
    assert analytics == snapshot


# --- Image Gallery ---

@pytest.mark.asyncio
async def test_add_strain_with_images_gallery(strain_library: StrainLibrary) -> None:
    """Phenotype data contains the full images array after add_strain with images."""
    images = [
        {"path": "/local/growspace_manager/strains/og-kush_default_a.webp", "crop_meta": None, "is_thumbnail": True},
        {"path": "/local/growspace_manager/strains/og-kush_default_b.webp", "crop_meta": {"x": 50, "y": 50, "scale": 1.2}, "is_thumbnail": False},
    ]

    await strain_library.add_strain(strain="OG Kush", images=images)

    pheno = strain_library.strains["OG Kush"]["phenotypes"]["default"]
    assert pheno["images"] == images


@pytest.mark.asyncio
async def test_images_gallery_replace_all(strain_library: StrainLibrary) -> None:
    """Saving a new images list replaces the existing gallery entirely."""
    original = [
        {"path": "/local/a.webp", "crop_meta": None, "is_thumbnail": True},
        {"path": "/local/b.webp", "crop_meta": None, "is_thumbnail": False},
    ]
    await strain_library.add_strain(strain="OG Kush", images=original)

    replacement = [
        {"path": "/local/c.webp", "crop_meta": None, "is_thumbnail": True},
    ]
    await strain_library.add_strain(strain="OG Kush", images=replacement)

    pheno = strain_library.strains["OG Kush"]["phenotypes"]["default"]
    assert pheno["images"] == replacement


@pytest.mark.asyncio
async def test_migration_image_path_to_images_gallery(strain_library: StrainLibrary) -> None:
    """Phenotypes with image_path but no images get migrated to the gallery format on load."""
    # Simulate pre-gallery data: insert directly into DB leaving images NULL
    await strain_library._db.execute(
        "INSERT OR IGNORE INTO strains (strain_name) VALUES (?)", ("Blue Dream",)
    )
    await strain_library._db.execute(
        """
        INSERT INTO phenotypes (strain_id, phenotype_name, image_path, image_crop_meta)
        SELECT strain_id, 'default',
               '/local/growspace_manager/strains/blue-dream.webp',
               '{"x": 50, "y": 50, "scale": 1.0}'
        FROM strains WHERE strain_name = 'Blue Dream'
        """
    )
    await strain_library._db.commit()

    # Re-load triggers the migration
    await strain_library.load()

    pheno = strain_library.strains["Blue Dream"]["phenotypes"]["default"]
    assert "images" in pheno
    assert len(pheno["images"]) == 1
    assert pheno["images"][0]["path"] == "/local/growspace_manager/strains/blue-dream.webp"
    assert pheno["images"][0]["is_thumbnail"] is True
    assert pheno["images"][0]["crop_meta"] == {"x": 50, "y": 50, "scale": 1.0}


# --- Thumbnail resolution ---

@pytest.mark.asyncio
async def test_resolve_thumbnail_own_images(strain_library: StrainLibrary) -> None:
    """resolve_thumbnail returns the thumbnail entry from the phenotype's own gallery."""
    images = [
        {"path": "/local/a.webp", "crop_meta": None, "is_thumbnail": False},
        {"path": "/local/b.webp", "crop_meta": {"x": 30, "y": 70, "scale": 1.1}, "is_thumbnail": True},
    ]
    await strain_library.add_strain(strain="OG Kush", images=images)

    thumbnail = strain_library.resolve_thumbnail("OG Kush", "default")
    assert thumbnail == {"path": "/local/b.webp", "crop_meta": {"x": 30, "y": 70, "scale": 1.1}, "is_thumbnail": True}


@pytest.mark.asyncio
async def test_resolve_thumbnail_falls_back_to_default_phenotype(strain_library: StrainLibrary) -> None:
    """resolve_thumbnail falls back to 'default' sibling when phenotype has no images."""
    default_image = {"path": "/local/default.webp", "crop_meta": None, "is_thumbnail": True}
    await strain_library.add_strain(strain="OG Kush", phenotype=None, images=[default_image])
    await strain_library.add_strain(strain="OG Kush", phenotype="Pheno A")

    thumbnail = strain_library.resolve_thumbnail("OG Kush", "Pheno A")
    assert thumbnail == default_image


@pytest.mark.asyncio
async def test_resolve_thumbnail_falls_back_alphabetical_when_no_default(strain_library: StrainLibrary) -> None:
    """resolve_thumbnail falls back alphabetically when 'default' has no images."""
    bravo_image = {"path": "/local/bravo.webp", "crop_meta": None, "is_thumbnail": True}
    await strain_library.add_strain(strain="OG Kush", phenotype="Bravo")
    await strain_library.add_strain(strain="OG Kush", phenotype="Alpha", images=[bravo_image])
    await strain_library.add_strain(strain="OG Kush", phenotype="Zeta")

    # Zeta has no images, default has no images — should get Alpha's thumbnail (first alphabetically)
    thumbnail = strain_library.resolve_thumbnail("OG Kush", "Zeta")
    assert thumbnail == bravo_image


# --- Additional Targeted Coverage Tests ---

@pytest.mark.asyncio
async def test_db_migration_harvests_columns(mock_hass, mock_image_manager) -> None:
    """Test that harvests table columns are added if missing during setup."""
    legacy_schema = """
    CREATE TABLE harvests (
        harvest_id INTEGER PRIMARY KEY,
        phenotype_id INTEGER,
        veg_days INTEGER NOT NULL,
        flower_days INTEGER NOT NULL,
        harvest_date TEXT NOT NULL,
        wet_weight REAL,
        dry_weight REAL,
        trim_weight REAL,
        thc_percentage REAL,
        cbd_percentage REAL,
        terpene_profile TEXT
    );
    """
    real_connect = aiosqlite.connect

    async def mock_connect(database, **kwargs):
        conn = await real_connect(":memory:", **kwargs)
        await conn.executescript(legacy_schema)
        await conn.commit()
        return conn

    with (
        patch(
            "custom_components.growspace_manager.strain_library.ImageManager",
            return_value=mock_image_manager,
        ),
        patch(
            "custom_components.growspace_manager.strain_library.aiosqlite.connect",
            side_effect=mock_connect,
        ),
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()

        # Check if the missing columns were added
        async with library._db.execute("PRAGMA table_info(harvests)") as cursor:
            columns = [row["name"] for row in await cursor.fetchall()]
            for col in ["vigor", "structure", "aroma", "resin", "pest_resistance"]:
                assert col in columns

        await library.async_close()



@pytest.mark.asyncio
async def test_async_migrate_image_gallery_no_db(mock_hass: MagicMock) -> None:
    """Verify that _async_migrate_image_gallery exits early when db is None."""
    library = StrainLibrary(mock_hass)
    assert library._db is None
    # This should return None early and not raise any errors
    await library._async_migrate_image_gallery()


@pytest.mark.asyncio
async def test_async_migrate_image_gallery_operational_error(strain_library: StrainLibrary) -> None:
    """Verify that _async_migrate_image_gallery handles operational error gracefully."""
    with patch.object(
        strain_library._db, "execute", side_effect=aiosqlite.OperationalError("Mock database error")
    ):
        await strain_library._async_migrate_image_gallery()


@pytest.mark.asyncio
async def test_async_migrate_image_gallery_invalid_crop_json(strain_library: StrainLibrary) -> None:
    """Verify that _async_migrate_image_gallery handles invalid crop JSON gracefully."""
    await strain_library._db.execute(
        "INSERT OR IGNORE INTO strains (strain_name) VALUES (?)", ("Blue Dream",)
    )
    await strain_library._db.execute(
        """
        INSERT INTO phenotypes (strain_id, phenotype_name, image_path, image_crop_meta)
        SELECT strain_id, 'default',
               '/local/growspace_manager/strains/blue-dream.webp',
               '{invalid json'
        FROM strains WHERE strain_name = 'Blue Dream'
        """
    )
    await strain_library._db.commit()

    # Re-load triggers the migration
    await strain_library.load()

    pheno = strain_library.strains["Blue Dream"]["phenotypes"]["default"]
    assert "images" in pheno
    assert len(pheno["images"]) == 1
    assert pheno["images"][0]["crop_meta"] is None


@pytest.mark.asyncio
async def test_load_with_invalid_images_json(strain_library: StrainLibrary) -> None:
    """Verify load logs warning and sets images to None on invalid JSON."""
    await strain_library._db.execute(
        "INSERT OR IGNORE INTO strains (strain_name) VALUES (?)", ("Sour Diesel",)
    )
    await strain_library._db.execute(
        """
        INSERT INTO phenotypes (strain_id, phenotype_name, images)
        SELECT strain_id, 'default', 'not valid json'
        FROM strains WHERE strain_name = 'Sour Diesel'
        """
    )
    await strain_library._db.commit()

    await strain_library.load()

    pheno = strain_library.strains["Sour Diesel"]["phenotypes"]["default"]
    assert pheno.get("images") is None


@pytest.mark.asyncio
async def test_resolve_thumbnail_nonexistent_strain(strain_library: StrainLibrary) -> None:
    """Verify resolve_thumbnail returns None when strain does not exist."""
    assert strain_library.resolve_thumbnail("Nonexistent Strain", "default") is None


@pytest.mark.asyncio
async def test_resolve_thumbnail_no_thumbnail_fallback(strain_library: StrainLibrary) -> None:
    """Verify resolve_thumbnail falls back to the first image when no thumbnail is specified."""
    images = [
        {"path": "/local/first.webp", "crop_meta": None, "is_thumbnail": False},
        {"path": "/local/second.webp", "crop_meta": None, "is_thumbnail": False},
    ]
    await strain_library.add_strain(strain="OG Kush", images=images)

    thumbnail = strain_library.resolve_thumbnail("OG Kush", "default")
    assert thumbnail == images[0]


@pytest.mark.asyncio
async def test_resolve_thumbnail_none_exists(strain_library: StrainLibrary) -> None:
    """Verify resolve_thumbnail returns None when neither requested phenotype nor fallback has images."""
    await strain_library.add_strain(strain="OG Kush", phenotype="default")
    await strain_library.add_strain(strain="OG Kush", phenotype="Pheno A")

    thumbnail = strain_library.resolve_thumbnail("OG Kush", "Pheno A")
    assert thumbnail is None

