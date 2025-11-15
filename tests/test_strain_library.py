"""Tests for the StrainLibrary class."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_store():
    """Fixture for a mock Store instance."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    return store


@pytest.fixture
def strain_library(mock_store):
    """Fixture for a StrainLibrary instance."""
    hass = MagicMock()
    return StrainLibrary(hass, 1, "test_strain_library")


@pytest.mark.asyncio
async def test_load_new_format(strain_library, mock_store):
    """Test loading data in the new dictionary format."""
    mock_store.async_load.return_value = {"strain|pheno": {"harvests": []}}
    strain_library.store = mock_store

    await strain_library.load()

    assert "strain|pheno" in strain_library.strains


@pytest.mark.asyncio
async def test_load_old_format(strain_library, mock_store):
    """Test loading and migrating data from the old list format."""
    mock_store.async_load.return_value = ["Strain A", "Strain B"]
    strain_library.store = mock_store

    await strain_library.load()

    assert "Strain A|default" in strain_library.strains
    assert "Strain B|default" in strain_library.strains
    mock_store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_harvest(strain_library):
    """Test recording a new harvest."""
    strain_library.store = MagicMock()
    strain_library.store.async_save = AsyncMock()
    await strain_library.record_harvest("OG Kush", "pheno1", 30, 60)

    key = "OG Kush|pheno1"
    assert key in strain_library.strains
    assert len(strain_library.strains[key]["harvests"]) == 1
    strain_library.store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_strain_phenotype(strain_library):
    """Test removing a strain/phenotype."""
    strain_library.strains = {"OG Kush|pheno1": {"harvests": []}}
    strain_library.store = MagicMock()
    strain_library.store.async_save = AsyncMock()

    await strain_library.remove_strain_phenotype("OG Kush", "pheno1")

    assert "OG Kush|pheno1" not in strain_library.strains
    strain_library.store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_library(strain_library):
    """Test importing a library."""
    strain_library.store = MagicMock()
    strain_library.store.async_save = AsyncMock()
    import_data = {"New Strain|default": {"harvests": []}}

    await strain_library.import_library(import_data, replace=False)

    assert "New Strain|default" in strain_library.strains
    strain_library.store.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_library_replace(strain_library):
    """Test importing a library with replace=True."""
    strain_library.strains = {"Old Strain|default": {}}
    strain_library.store = MagicMock()
    strain_library.store.async_save = AsyncMock()
    import_data = {"New Strain|default": {"harvests": []}}

    await strain_library.import_library(import_data, replace=True)

    assert "Old Strain|default" not in strain_library.strains
    assert "New Strain|default" in strain_library.strains


@pytest.mark.asyncio
async def test_clear_library(strain_library):
    """Test clearing the library."""
    strain_library.strains = {"OG Kush|pheno1": {}}
    strain_library.store = MagicMock()
    strain_library.store.async_save = AsyncMock()

    cleared_count = await strain_library.clear()

    assert not strain_library.strains
    assert cleared_count == 1
    strain_library.store.async_save.assert_awaited_once()
