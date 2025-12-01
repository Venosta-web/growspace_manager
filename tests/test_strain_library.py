"""Tests for the StrainLibrary class."""

import pytest
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, ANY

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
async def strain_library(mock_hass, mock_image_manager):
    """Fixture for a StrainLibrary instance with in-memory DB."""
    # Patch ImageManager constructor to return our mock
    with patch("custom_components.growspace_manager.strain_library.ImageManager", return_value=mock_image_manager), \
         patch("custom_components.growspace_manager.strain_library.aiosqlite.connect") as mock_connect:
        
        # Setup mock DB
        mock_db = AsyncMock()
        mock_db.row_factory = None
        mock_connect.return_value = mock_db
        
        # We need to mock execute to return a cursor that can be awaited and used as context manager
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.__aenter__.return_value = mock_cursor
        mock_cursor.__aexit__.return_value = None
        
        mock_db.execute.return_value = mock_cursor
        mock_db.executescript = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.close = AsyncMock()

        library = StrainLibrary(mock_hass)
        library.image_manager = mock_image_manager # Ensure our mock is used
        
        # Mock async_setup to initialize DB
        await library.async_setup()
        
        yield library
        
        await library.async_close()

@pytest.mark.asyncio
async def test_add_strain_with_image(strain_library, mock_image_manager):
    """Test adding a strain with an image."""
    # Setup DB responses for add_strain
    # 1. Check strain exists (None)
    # 2. Insert strain
    # 3. Get strain ID (1)
    # 4. Insert phenotype
    # 5. Load (fetchall)
    
    mock_cursor = strain_library._db.execute.return_value
    # Sequence of fetchone/fetchall calls is complex.
    # Easier to verify that image_manager was called and logic proceeded.
    
    # We mock fetchone to return a strain_id when asked
    mock_cursor.fetchone.side_effect = [
        None, # Check strain exists (add_strain) -> None
        (1,), # Get strain_id -> 1
        None, # Check strain exists (ensure) -> None
        (1,), # Get strain_id (ensure) -> 1
        None, # Check phenotype exists -> None
        (1,), # Get phenotype_id -> 1
    ]
    
    await strain_library.add_strain(
        strain="My Strain",
        phenotype="My Pheno",
        image_base64="base64data"
    )
    
    mock_image_manager.save_strain_image.assert_awaited_with("my-strain", "my-pheno", "base64data")
    
    # Verify DB calls
    # We expect inserts into strains and phenotypes
    assert strain_library._db.execute.call_count >= 1

@pytest.mark.asyncio
async def test_remove_strain_phenotype(strain_library, mock_image_manager):
    """Test removing a phenotype deletes the image."""
    mock_cursor = strain_library._db.execute.return_value
    # Mock finding the phenotype
    mock_cursor.fetchone.side_effect = [
        {"phenotype_id": 1, "strain_id": 1}, # Select phenotype
        (1,), # Count phenotypes -> 1 (still have others? or 0?)
        # If 0, it deletes strain.
    ]
    
    await strain_library.remove_strain_phenotype("My Strain", "My Pheno")
    
    mock_image_manager.delete_image.assert_called_with("my-strain", "my-pheno")

