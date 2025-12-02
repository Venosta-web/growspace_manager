"""Tests for the StrainLibrary class."""

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
async def test_add_strain_and_load(strain_library: StrainLibrary):
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
async def test_add_strain_with_phenotype(strain_library: StrainLibrary):
    """Test adding a strain with a specific phenotype."""
    await strain_library.add_strain(
        strain="Gorilla Glue",
        phenotype="#4",
        description="Sticky",
        flower_days_min=60,
        flower_days_max=65,
    )

    assert "Gorilla Glue" in strain_library.strains
    phenotypes = strain_library.strains["Gorilla Glue"]["phenotypes"]
    assert "#4" in phenotypes
    assert phenotypes["#4"]["description"] == "Sticky"
    assert phenotypes["#4"]["flower_days_min"] == 60


@pytest.mark.asyncio
async def test_record_harvest_and_analytics(strain_library: StrainLibrary):
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
):
    """Test removing a phenotype."""
    await strain_library.add_strain("Gelato", "#33")
    await strain_library.add_strain("Gelato", "#41")

    assert len(strain_library.strains["Gelato"]["phenotypes"]) == 2

    await strain_library.remove_strain_phenotype("Gelato", "#33")

    assert len(strain_library.strains["Gelato"]["phenotypes"]) == 1
    assert "#41" in strain_library.strains["Gelato"]["phenotypes"]
    mock_image_manager.delete_image.assert_called()


@pytest.mark.asyncio
async def test_remove_strain(strain_library: StrainLibrary):
    """Test removing an entire strain."""
    await strain_library.add_strain("Sour Diesel")
    assert "Sour Diesel" in strain_library.strains

    await strain_library.remove_strain("Sour Diesel")
    assert "Sour Diesel" not in strain_library.strains


@pytest.mark.asyncio
async def test_import_library(strain_library: StrainLibrary):
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
async def test_import_strains_list(strain_library: StrainLibrary):
    """Test importing a list of strain names."""
    strains = ["Strain A", "Strain B"]
    await strain_library.import_strains(strains, replace=True)

    assert "Strain A" in strain_library.strains
    assert "Strain B" in strain_library.strains
    assert len(strain_library.strains) == 2


@pytest.mark.asyncio
async def test_hybrid_percentage_validation(strain_library: StrainLibrary):
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
async def test_image_handling(strain_library: StrainLibrary, mock_image_manager):
    """Test image saving during add_strain."""
    await strain_library.add_strain(
        "Photo Strain", "Pheno", image_base64="data:image/jpeg;base64,..."
    )

    mock_image_manager.save_strain_image.assert_awaited()
    pheno = strain_library.strains["Photo Strain"]["phenotypes"]["Pheno"]
    assert pheno["image_path"] == "/local/growspace_manager/strains/image.jpg"


@pytest.mark.asyncio
async def test_save_noop(strain_library: StrainLibrary):
    """Test that save() is a no-op."""
    await strain_library.save()  # Should not raise


@pytest.mark.asyncio
async def test_get_all(strain_library: StrainLibrary):
    """Test get_all() returns the strains dictionary."""
    await strain_library.add_strain("Test Strain")
    all_strains = strain_library.get_all()
    assert "Test Strain" in all_strains


@pytest.mark.asyncio
async def test_analytics_with_zero_harvests(strain_library: StrainLibrary):
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
async def test_analytics_caching(strain_library: StrainLibrary):
    """Test that analytics are cached."""
    await strain_library.add_strain("Cache Test")

    # First call should calculate
    analytics1 = strain_library.get_analytics()

    # Second call should return cached value
    analytics2 = strain_library.get_analytics()

    assert analytics1 is analytics2


@pytest.mark.asyncio
async def test_set_strain_meta(strain_library: StrainLibrary):
    """Test set_strain_meta() updates metadata."""
    await strain_library.add_strain("Meta Strain")

    await strain_library.set_strain_meta(
        "Meta Strain", breeder="New Breeder", strain_type="Indica"
    )

    assert strain_library.strains["Meta Strain"]["meta"]["breeder"] == "New Breeder"
    assert strain_library.strains["Meta Strain"]["meta"]["type"] == "Indica"


@pytest.mark.asyncio
async def test_remove_strain_phenotype_nonexistent(strain_library: StrainLibrary):
    """Test removing a non-existent phenotype (should not error)."""
    await strain_library.remove_strain_phenotype("NonExistent", "Pheno")
    # Should not raise


@pytest.mark.asyncio
async def test_remove_strain_nonexistent(strain_library: StrainLibrary):
    """Test removing a non-existent strain (should not error)."""
    await strain_library.remove_strain("NonExistent")
    # Should not raise


@pytest.mark.asyncio
async def test_remove_strain_phenotype_deletes_strain_when_no_phenotypes_remain(
    strain_library: StrainLibrary, mock_image_manager
):
    """Test that strain is deleted when all phenotypes are removed."""
    await strain_library.add_strain("Single Pheno Strain", "OnlyOne")

    assert "Single Pheno Strain" in strain_library.strains

    await strain_library.remove_strain_phenotype("Single Pheno Strain", "OnlyOne")

    assert "Single Pheno Strain" not in strain_library.strains


@pytest.mark.asyncio
async def test_record_harvest_creates_strain_if_not_exists(
    strain_library: StrainLibrary,
):
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
):
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
async def test_hybrid_sativa_percentage_auto_calc(strain_library: StrainLibrary):
    """Test that indica percentage is auto-calculated for hybrid."""
    await strain_library.add_strain(
        "Auto Calc Hybrid", strain_type="Hybrid", sativa_percentage=70
    )

    assert strain_library.strains["Auto Calc Hybrid"]["meta"]["sativa_percentage"] == 70
    assert strain_library.strains["Auto Calc Hybrid"]["meta"]["indica_percentage"] == 30


@pytest.mark.asyncio
async def test_hybrid_indica_percentage_auto_calc(strain_library: StrainLibrary):
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
async def test_add_strain_with_image_path(strain_library: StrainLibrary):
    """Test adding strain with image_path instead of image_base64."""
    await strain_library.add_strain(
        "Path Strain", "Pheno", image_path="/local/custom/path.jpg"
    )

    pheno = strain_library.strains["Path Strain"]["phenotypes"]["Pheno"]
    assert pheno["image_path"] == "/local/custom/path.jpg"


@pytest.mark.asyncio
async def test_import_library_invalid_data(strain_library: StrainLibrary):
    """Test that import_library handles invalid data gracefully."""
    # Import with non-dict data
    result = await strain_library.import_library("not a dict", replace=False)
    assert result == 0  # Should return current count


@pytest.mark.asyncio
async def test_import_strains_invalid_data(strain_library: StrainLibrary):
    """Test that import_strains handles invalid data gracefully."""
    # Import with non-list data
    result = await strain_library.import_strains("not a list", replace=False)
    assert result == 0  # Should return current count


@pytest.mark.asyncio
async def test_import_library_with_legacy_image_path(strain_library: StrainLibrary):
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
    strain_library: StrainLibrary, mock_import_export_manager
):
    """Test exporting library to ZIP."""
    await strain_library.add_strain("Export Strain")

    result = await strain_library.export_library_to_zip("/tmp")

    assert result == "/path/to/export.zip"
    mock_import_export_manager.export_library.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_library_from_zip(
    strain_library: StrainLibrary, mock_import_export_manager
):
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
):
    """Test load() handles invalid JSON in image_crop_meta gracefully."""
    # Manually insert a phenotype with invalid JSON in image_crop_meta
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
):
    """Test RuntimeError when strain creation fails unexpectedly."""
    # This is a very edge case scenario. We need to simulate a situation where
    # add_strain completes but the strain is not actually created.
    # This is difficult to simulate without deep mocking.
    # One approach is to mock add_strain to not actually add anything.

    with patch.object(strain_library, "add_strain", new_callable=AsyncMock):
        # add_strain will be called but won't actually create the strain
        with pytest.raises(RuntimeError, match="Failed to create strain"):
            await strain_library._ensure_strain_and_phenotype_exist(
                "Failing Strain", "Pheno"
            )
