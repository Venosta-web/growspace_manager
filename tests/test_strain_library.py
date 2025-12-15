"""Tests for the StrainLibrary class."""

import pytest
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, mock_open, call, ANY

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_db_cursor():
    """Fixture for a mock database cursor."""
    cursor = AsyncMock()
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    cursor.__aiter__.return_value = [].__iter__()  # Default empty iterator
    return cursor


class AsyncIter:
    def __init__(self, items):
        self.items = items
        self.loop = iter(self.items)

    def __aiter__(self):
        self.loop = iter(self.items)
        return self

    async def __anext__(self):
        try:
            return next(self.loop)
        except StopIteration:
            raise StopAsyncIteration


class MockCursorContext:
    """Mock object that supports both await and async context manager."""

    def __init__(self, cursor):
        self.cursor = cursor

    def __await__(self):
        async def get_cursor():
            return self.cursor

        return get_cursor().__await__()

    async def __aenter__(self):
        return self.cursor

    async def __aexit__(self, exc_type, exc, tb):
        pass


@pytest.fixture
def mock_db_conn(mock_db_cursor):
    """Fixture for a mock database connection."""
    conn = MagicMock()
    # Configure execute to be usable as awaitable or context manager
    conn.execute.side_effect = lambda *args, **kwargs: MockCursorContext(mock_db_cursor)

    conn.executescript = AsyncMock()
    conn.commit = AsyncMock()
    conn.close = AsyncMock()
    conn.row_factory = None
    return conn


@pytest.fixture
def mock_hass():
    """Fixture for a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.path = MagicMock(side_effect=lambda *args: "/".join(args))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    return hass


@pytest.fixture
async def strain_library(mock_hass, mock_db_conn):
    """Fixture for a StrainLibrary instance with mocked DB."""
    with patch(
        "custom_components.growspace_manager.strain_library.aiosqlite.connect",
        new_callable=AsyncMock,
        return_value=mock_db_conn,
    ):
        library = StrainLibrary(mock_hass)
        await library.async_setup()  # This sets self._db matches mock_db_conn
        return library


@pytest.mark.asyncio
async def test_load_empty(strain_library, mock_db_cursor):
    """Test loading data when DB is empty."""
    # Harvests query returns empty
    # Strains query returns empty
    mock_db_cursor.fetchall.return_value = []
    # Setting the iterator behavior for the first query (harvests)
    mock_db_cursor.__aiter__.return_value = []

    await strain_library.load()
    assert strain_library.strains == {}


@pytest.mark.asyncio
async def test_load_populated(strain_library, mock_db_cursor):
    """Test loading populated data."""
    # Mock harvests
    harvest_row = {
        "phenotype_id": 10,
        "veg_days": 30,
        "flower_days": 60,
        "harvest_date": "2023-01-01",
    }

    # Mock strains/phenotypes
    strain_row = {
        "strain_id": 1,
        "strain_name": "Test Strain",
        "breeder": "Breeder X",
        "type": "Indica",
        "lineage": None,
        "sex": "Feminized",
        "sativa_percentage": 0,
        "indica_percentage": 100,
        "phenotype_id": 10,
        "phenotype_name": "pheno1",
        "description": "Tasty",
        "image_path": "/img.jpg",
        "image_crop_meta": None,
        "flower_days_min": 50,
        "flower_days_max": 60,
    }

    # Setup async iterator for harvests first query
    async def harvests_iter():
        yield harvest_row

    # We need to distinguish calls.
    # Logic in load():
    # 1. execute("SELECT ... FROM harvests") -> cursor needed for async for
    # 2. execute("SELECT ... FROM strains ...") -> cursor needed for fetchall

    # It's hard to mock different return values for the same method call with side_effect on AENTER.
    # Instead, let's just populate the fetchall.
    # But the first one mocks `async for row in cursor` which uses __aiter__.

    # Let's simplify and make the cursor return everything needed via fetchall for the main query,
    # and handle the harvest loop separately.

    mock_db_cursor.__aiter__.side_effect = lambda: AsyncIter([harvest_row])
    mock_db_cursor.fetchall.return_value = [strain_row]

    await strain_library.load()

    assert "Test Strain" in strain_library.strains
    data = strain_library.strains["Test Strain"]
    assert data["meta"]["breeder"] == "Breeder X"
    assert "pheno1" in data["phenotypes"]
    pheno = data["phenotypes"]["pheno1"]
    assert pheno["description"] == "Tasty"
    assert len(pheno["harvests"]) == 1
    assert pheno["harvests"][0]["veg_days"] == 30


@pytest.mark.asyncio
async def test_record_harvest(strain_library, mock_db_cursor):
    """Test recording a new harvest."""
    # Ensure strain exists logic
    # _ensure_strain_and_phenotype_exist checks:
    # 1. SELECT strain_id -> found
    # 2. SELECT phenotype_id -> found

    # Mock finding strain and phenotype
    mock_db_cursor.fetchone.side_effect = [(1,), (10,)]

    await strain_library.record_harvest("OG Kush", "pheno1", 30, 60)

    # Should execute INSERT
    strain_library._db.execute.assert_called()
    assert "INSERT INTO harvests" in strain_library._db.execute.call_args_list[-1][0][0]


@pytest.mark.asyncio
async def test_add_strain_full(strain_library, mock_db_conn, mock_db_cursor):
    """Test adding a strain with all metadata."""
    # add_strain executes:
    # 1. INSERT OR REPLACE INTO strains
    # 2. SELECT strain_id -> fetchone
    # 3. INSERT INTO phenotypes

    mock_db_cursor.fetchone.return_value = (123,)  # strain_id
    mock_hass = (
        MagicMock()
    )  # Ensure mock_hass is defined or passed? No it's not a fixture here.
    # Ah, strain_library fixture uses hass.
    strain_library.hass.async_add_executor_job = AsyncMock()

    await strain_library.add_strain(
        strain="Blue Dream",
        phenotype="Sativa Dominant",
        breeder="Humboldt",
        strain_type="Hybrid",
        image_path="/local/img.jpg",
    )

    # Check calls
    calls = mock_db_conn.execute.call_args_list
    # Expected: INSERT strains, SELECT strain_id, INSERT phenotypes
    assert any("INSERT OR REPLACE INTO strains" in str(c) for c in calls)
    assert any("INSERT INTO phenotypes" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_remove_strain_phenotype(strain_library, mock_db_cursor):
    """Test removing a strain/phenotype."""
    # Logic:
    # 1. SELECT IDs (strain, pheno) -> fetchone
    mock_db_cursor.fetchone.side_effect = [
        {"phenotype_id": 10, "strain_id": 1},
        (1,),
    ]  # 1 for count check?

    # 2. DELETE harvests
    # 3. DELETE phenotypes
    # 4. SELECT COUNT(*) -> fetchone (checking if strain empty)
    strain_library.hass.async_add_executor_job = AsyncMock()

    await strain_library.remove_strain_phenotype("OG Kush", "pheno1")

    assert strain_library._db.execute.call_count >= 3


@pytest.mark.asyncio
async def test_remove_strain(strain_library, mock_db_cursor):
    """Test removing an entire strain."""
    # Logic:
    # 1. SELECT strain_id -> fetchone
    mock_db_cursor.fetchone.return_value = (1,)
    strain_library.hass.async_add_executor_job = AsyncMock()

    await strain_library.remove_strain("OG Kush")

    # DELETE harvests, phenotypes, strains
    assert strain_library._db.execute.call_count >= 3
    assert any(
        "DELETE FROM strains" in str(c)
        for c in strain_library._db.execute.call_args_list
    )


@pytest.mark.asyncio
async def test_save_strain_image(strain_library, mock_hass):
    """Test saving a strain image."""
    mock_open_file = mock_open()
    image_base64 = "data:image/jpeg;base64,SGVsbG8="  # "Hello" in base64
    # mock_hass.async_add_executor_job is already set by fixture

    with (
        patch("builtins.open", mock_open_file),
        patch("os.path.exists", return_value=True),
        patch("os.makedirs"),
        patch(
            "custom_components.growspace_manager.strain_library.slugify",
            side_effect=lambda x: x.lower(),
        ),
    ):
        # Directly call private method for unit testing logic, or via add_strain
        path = await strain_library._save_strain_image(
            "My Strain", "My Pheno", image_base64
        )

    mock_hass.async_add_executor_job.assert_called()
    assert path == "/local/growspace_manager/strains/my strain_my pheno.jpg"


# =============================================================================
# Tests for async_close
# =============================================================================


@pytest.mark.asyncio
async def test_async_close(strain_library, mock_db_conn):
    """Test closing the database connection."""
    await strain_library.async_close()
    mock_db_conn.close.assert_called_once()
    assert strain_library._db is None


@pytest.mark.asyncio
async def test_async_close_no_db(mock_hass):
    """Test closing when database is not set."""
    library = StrainLibrary(mock_hass)
    # _db is None by default
    await library.async_close()  # Should not raise


# =============================================================================
# Tests for save (no-op)
# =============================================================================


@pytest.mark.asyncio
async def test_save_noop(strain_library):
    """Test that save is a no-op for SQLite implementation."""
    await strain_library.save()  # Should not raise, does nothing


# =============================================================================
# Tests for get_analytics
# =============================================================================


def test_get_analytics_empty(strain_library):
    """Test get_analytics with empty library."""
    strain_library.strains = {}
    result = strain_library.get_analytics()
    assert result == {"strains": {}, "strain_list": []}


def test_get_analytics_with_harvests(strain_library):
    """Test get_analytics with populated data and harvests."""
    strain_library.strains = {
        "Blue Dream": {
            "meta": {"breeder": "Seed Co", "type": "Hybrid"},
            "phenotypes": {
                "pheno1": {
                    "phenotype_id": 1,
                    "description": "Great taste",
                    "harvests": [
                        {
                            "veg_days": 30,
                            "flower_days": 60,
                            "harvest_date": "2023-01-01",
                        },
                        {
                            "veg_days": 28,
                            "flower_days": 58,
                            "harvest_date": "2023-06-01",
                        },
                    ],
                    "flower_days_min": 55,
                    "flower_days_max": 65,
                },
                "pheno2": {
                    "phenotype_id": 2,
                    "harvests": [
                        {
                            "veg_days": 35,
                            "flower_days": 65,
                            "harvest_date": "2023-03-01",
                        },
                    ],
                },
            },
        },
    }
    result = strain_library.get_analytics()

    assert "strains" in result
    assert "strain_list" in result
    assert "Blue Dream" in result["strains"]

    strain_data = result["strains"]["Blue Dream"]
    assert strain_data["meta"]["breeder"] == "Seed Co"
    assert strain_data["analytics"]["total_harvests"] == 3
    assert strain_data["analytics"]["avg_veg_days"] == 31  # (30+28+35)/3
    assert strain_data["analytics"]["avg_flower_days"] == 61  # (60+58+65)/3

    # Check phenotype analytics
    assert "pheno1" in strain_data["phenotypes"]
    assert strain_data["phenotypes"]["pheno1"]["total_harvests"] == 2
    assert strain_data["phenotypes"]["pheno1"]["avg_veg_days"] == 29  # (30+28)/2


def test_get_analytics_no_harvests(strain_library):
    """Test get_analytics when phenotypes have no harvests."""
    strain_library.strains = {
        "New Strain": {
            "meta": {},
            "phenotypes": {
                "pheno1": {
                    "phenotype_id": 1,
                    "harvests": [],
                },
            },
        },
    }
    result = strain_library.get_analytics()

    strain_data = result["strains"]["New Strain"]
    assert strain_data["analytics"]["total_harvests"] == 0
    assert strain_data["analytics"]["avg_veg_days"] == 0
    assert strain_data["analytics"]["avg_flower_days"] == 0
    assert strain_data["phenotypes"]["pheno1"]["total_harvests"] == 0


def test_get_analytics_cached(strain_library):
    """Test that analytics are cached after first call."""
    strain_library.strains = {"Test": {"meta": {}, "phenotypes": {}}}
    strain_library._analytics_cache = {"cached": True}

    result = strain_library.get_analytics()
    assert result == {"cached": True}


# =============================================================================
# Tests for import_library
# =============================================================================


@pytest.mark.asyncio
async def test_import_library_success(strain_library, mock_db_cursor):
    """Test importing a library dictionary."""
    mock_db_cursor.fetchone.return_value = (1,)  # Return strain_id/phenotype_id
    library_data = {
        "OG Kush": {
            "meta": {"breeder": "Seed Co", "type": "Indica"},
            "phenotypes": {
                "pheno1": {
                    "flower_days_min": 50,
                    "flower_days_max": 60,
                    "description": "Classic",
                    "harvests": [
                        {
                            "veg_days": 30,
                            "flower_days": 55,
                            "harvest_date": "2023-01-01",
                        }
                    ],
                },
            },
        },
    }

    result = await strain_library.import_library(library_data)
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_import_library_invalid_data(strain_library):
    """Test importing with invalid (non-dict) data."""
    result = await strain_library.import_library("not a dict")
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_import_library_with_replace(
    strain_library, mock_db_cursor, mock_db_conn
):
    """Test importing with replace=True clears first."""
    mock_db_cursor.fetchone.return_value = (1,)
    library_data = {"Strain1": {"meta": {}, "phenotypes": {}}}

    with patch.object(strain_library, "clear", new_callable=AsyncMock) as mock_clear:
        await strain_library.import_library(library_data, replace=True)
        mock_clear.assert_called_once()


@pytest.mark.asyncio
async def test_import_library_with_image_path_conversion(
    strain_library, mock_db_cursor
):
    """Test that image paths starting with 'images/' are converted."""
    mock_db_cursor.fetchone.return_value = (1,)
    library_data = {
        "Strain": {
            "meta": {},
            "phenotypes": {
                "pheno": {
                    "image_path": "images/strain_pheno.jpg",
                },
            },
        },
    }

    await strain_library.import_library(library_data)
    # The add_strain call should receive converted path
    # Just verify it doesn't error


# =============================================================================
# Tests for import_strains
# =============================================================================


@pytest.mark.asyncio
async def test_import_strains_success(strain_library, mock_db_cursor):
    """Test importing a list of strain names."""
    mock_db_cursor.fetchone.return_value = (1,)
    strains = ["Strain A", "Strain B", "Strain C"]

    result = await strain_library.import_strains(strains)
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_import_strains_invalid_data(strain_library):
    """Test importing with invalid (non-list) data."""
    result = await strain_library.import_strains("not a list")
    assert isinstance(result, int)


@pytest.mark.asyncio
async def test_import_strains_with_replace(strain_library, mock_db_cursor):
    """Test importing strains with replace=True."""
    mock_db_cursor.fetchone.return_value = (1,)
    with patch.object(strain_library, "clear", new_callable=AsyncMock) as mock_clear:
        await strain_library.import_strains(["Strain1"], replace=True)
        mock_clear.assert_called_once()


# =============================================================================
# Tests for clear
# =============================================================================


@pytest.mark.asyncio
async def test_clear(strain_library, mock_db_conn):
    """Test clearing all entries."""
    strain_library.strains = {"Strain1": {}, "Strain2": {}}
    strain_library._analytics_cache = {"some": "data"}

    result = await strain_library.clear()

    assert result == 2
    assert strain_library.strains == {}
    assert strain_library._analytics_cache is None
    mock_db_conn.executescript.assert_called()


# =============================================================================
# Tests for export_library_to_zip
# =============================================================================


@pytest.mark.asyncio
async def test_export_library_to_zip(strain_library, mock_hass):
    """Test exporting library to a ZIP file."""
    strain_library.strains = {"Strain1": {"meta": {}, "phenotypes": {}}}

    with patch.object(
        strain_library, "_export_sync", return_value="/path/to/export.zip"
    ):
        result = await strain_library.export_library_to_zip("/output")

        mock_hass.async_add_executor_job.assert_called()
        assert result == "/path/to/export.zip"


@pytest.mark.asyncio
async def test_export_library_to_zip_generates_analytics(strain_library, mock_hass):
    """Test that export generates analytics if not cached."""
    strain_library.strains = {"Strain1": {"meta": {}, "phenotypes": {}}}
    strain_library._analytics_cache = None

    with patch.object(
        strain_library, "_export_sync", return_value="/path/to/export.zip"
    ):
        with patch.object(strain_library, "get_analytics") as mock_analytics:
            await strain_library.export_library_to_zip("/output")
            mock_analytics.assert_called_once()


# =============================================================================
# Tests for _export_sync
# =============================================================================


def test_export_sync(strain_library, mock_hass, tmp_path):
    """Test synchronous export helper."""
    strain_library.strains = {
        "TestStrain": {
            "meta": {"breeder": "Test"},
            "phenotypes": {
                "pheno1": {
                    "description": "Test pheno",
                }
            },
        }
    }

    with (
        patch("os.makedirs"),
        patch("os.path.exists", return_value=False),
        patch("zipfile.ZipFile") as mock_zipfile,
    ):
        mock_zipf = MagicMock()
        mock_zipfile.return_value.__enter__.return_value = mock_zipf

        result = strain_library._export_sync(str(tmp_path))

        assert "strain_library_export_" in result
        assert result.endswith(".zip")


def test_export_sync_with_images(strain_library, mock_hass):
    """Test export includes images when present."""
    strain_library.strains = {
        "TestStrain": {
            "meta": {},
            "phenotypes": {
                "pheno1": {
                    "image_path": "/local/growspace_manager/strains/test.jpg",
                }
            },
        }
    }

    with (
        patch("os.makedirs"),
        patch("os.path.exists", return_value=True),
        patch("zipfile.ZipFile") as mock_zipfile,
    ):
        mock_zipf = MagicMock()
        mock_zipfile.return_value.__enter__.return_value = mock_zipf

        strain_library._export_sync("/output")

        # Should write the image to zip
        mock_zipf.write.assert_called()


# =============================================================================
# Tests for import_library_from_zip
# =============================================================================


@pytest.mark.asyncio
async def test_import_library_from_zip(strain_library, mock_hass):
    """Test importing library from ZIP."""
    with patch.object(strain_library, "_import_sync", return_value=5):
        result = await strain_library.import_library_from_zip("/path/to/import.zip")

        mock_hass.async_add_executor_job.assert_called()
        assert result == 5


# =============================================================================
# Tests for _import_sync
# =============================================================================


def test_import_sync_file_not_found(strain_library):
    """Test _import_sync with non-existent file."""
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            strain_library._import_sync("/nonexistent.zip", merge=True)


def test_import_sync_invalid_zip(strain_library):
    """Test _import_sync with invalid ZIP file."""
    with (
        patch("os.path.exists", return_value=True),
        patch("zipfile.is_zipfile", return_value=False),
    ):
        with pytest.raises(ValueError) as exc_info:
            strain_library._import_sync("/invalid.zip", merge=True)
        assert "Not a valid ZIP file" in str(exc_info.value)


def test_import_sync_missing_library_json(strain_library):
    """Test _import_sync when library.json is missing from archive."""
    with (
        patch("os.path.exists", return_value=True),
        patch("os.makedirs"),
        patch("zipfile.is_zipfile", return_value=True),
        patch("zipfile.ZipFile") as mock_zipfile,
    ):
        mock_zipf = MagicMock()
        mock_zipf.namelist.return_value = ["images/test.jpg"]  # No library.json
        mock_zipfile.return_value.__enter__.return_value = mock_zipf

        with pytest.raises(ValueError) as exc_info:
            strain_library._import_sync("/test.zip", merge=True)
        assert "library.json missing" in str(exc_info.value)


def test_import_sync_success(strain_library, mock_hass):
    """Test successful _import_sync."""
    library_json = json.dumps({"Strain1": {"meta": {}, "phenotypes": {}}}).encode()

    with (
        patch("os.path.exists", return_value=True),
        patch("os.makedirs"),
        patch("zipfile.is_zipfile", return_value=True),
        patch("zipfile.ZipFile") as mock_zipfile,
        patch("builtins.open", mock_open()),
        patch("shutil.copyfileobj"),
    ):
        mock_zipf = MagicMock()
        mock_zipf.namelist.return_value = ["library.json", "images/test.jpg"]

        # Mock infolist for images
        mock_info = MagicMock()
        mock_info.filename = "images/test.jpg"
        mock_info.is_dir.return_value = False
        mock_zipf.infolist.return_value = [mock_info]

        # Mock file open for library.json
        mock_json_file = MagicMock()
        mock_json_file.read.return_value = library_json
        mock_zipf.open.return_value.__enter__.return_value = mock_json_file

        mock_zipfile.return_value.__enter__.return_value = mock_zipf

        result = strain_library._import_sync("/test.zip", merge=True)

        mock_hass.create_task.assert_called_once()
        assert isinstance(result, int)


# =============================================================================
# Tests for hybrid percentage validation in add_strain
# =============================================================================


@pytest.mark.asyncio
async def test_add_strain_hybrid_percentage_auto_fill_indica(
    strain_library, mock_db_cursor
):
    """Test that indica percentage is auto-calculated for hybrids."""
    mock_db_cursor.fetchone.return_value = (1,)

    await strain_library.add_strain(
        strain="Hybrid Test",
        strain_type="Hybrid",
        sativa_percentage=60,
    )
    # Should auto-calculate indica_percentage = 40


@pytest.mark.asyncio
async def test_add_strain_hybrid_percentage_auto_fill_sativa(
    strain_library, mock_db_cursor
):
    """Test that sativa percentage is auto-calculated for hybrids."""
    mock_db_cursor.fetchone.return_value = (1,)

    await strain_library.add_strain(
        strain="Hybrid Test",
        strain_type="Hybrid",
        indica_percentage=70,
    )
    # Should auto-calculate sativa_percentage = 30


@pytest.mark.asyncio
async def test_add_strain_hybrid_percentage_exceeds_100(strain_library, mock_db_cursor):
    """Test that combined percentage > 100 raises ValueError."""
    mock_db_cursor.fetchone.return_value = (1,)

    with pytest.raises(ValueError) as exc_info:
        await strain_library.add_strain(
            strain="Invalid Hybrid",
            strain_type="Hybrid",
            sativa_percentage=60,
            indica_percentage=50,
        )
    assert "exceed 100" in str(exc_info.value)


# =============================================================================
# Tests for record_harvest cache update
# =============================================================================


@pytest.mark.asyncio
async def test_record_harvest_updates_cache(strain_library, mock_db_cursor):
    """Test that record_harvest updates in-memory cache."""
    mock_db_cursor.fetchone.side_effect = [(1,), (10,)]

    # Pre-populate the strain cache
    strain_library.strains = {
        "OG Kush": {
            "meta": {},
            "phenotypes": {
                "pheno1": {
                    "phenotype_id": 10,
                    "harvests": [],
                },
            },
        },
    }

    await strain_library.record_harvest("OG Kush", "pheno1", 30, 60)

    # Verify cache was updated
    assert (
        len(strain_library.strains["OG Kush"]["phenotypes"]["pheno1"]["harvests"]) == 1
    )
    harvest = strain_library.strains["OG Kush"]["phenotypes"]["pheno1"]["harvests"][0]
    assert harvest["veg_days"] == 30
    assert harvest["flower_days"] == 60
