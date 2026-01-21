from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_db.sqlite"  # noqa: S108
    return hass


@pytest.mark.asyncio
async def test_library_methods_no_db(mock_hass) -> None:
    """Test library methods when database is not connected."""
    lib = StrainLibrary(mock_hass)
    # Ensure db is None
    lib._db = None

    # 1. load
    await lib.load()
    # Log warning should be emitted, but no error raised

    # 2. record_harvest
    await lib.record_harvest("Strain A", "Pheno 1", 30, 60)

    # 3. add_strain
    await lib.add_strain("Strain B")

    # 4. remove_strain_phenotype
    await lib.remove_strain_phenotype("Strain A", "Pheno 1")

    # 5. remove_strain
    await lib.remove_strain("Strain A")

    # 6. import_library
    result = await lib.import_library({"Strain A": {}})
    assert result == 0

    # 7. clear
    count = await lib.clear()
    assert count == 0

    # 8. ensure_strain_and_phenotype_exist (internal)
    with pytest.raises(RuntimeError, match="Database not connected"):
        await lib._ensure_strain_and_phenotype_exist("S", "P")

    # 9. import_strains with list check (though covered by type hint usually, explicit None check in code?)
    # The code has `if not isinstance(strains, list): return 0`
    assert await lib.import_strains("not a list") == 0


@pytest.mark.asyncio
async def test_ensure_phenotype_creation_failure(mock_hass) -> None:
    """Test failure to retrieve phenotype ID after insertion."""
    lib = StrainLibrary(mock_hass)

    # Mock DB connection
    mock_db = MagicMock()
    mock_db.commit = AsyncMock()
    lib._db = mock_db

    # Helper to mock an object that is both awaitable and an async context manager
    class AwaitableAsyncContextManager:
        def __init__(self, mock_cursor) -> None:
            self.mock_cursor = mock_cursor

        def __await__(self):
            async def _return_cursor():
                return self.mock_cursor

            return _return_cursor().__await__()

        async def __aenter__(self):
            return self.mock_cursor

        async def __aexit__(self, exc_type, exc, tb):
            pass

    # Mock cursor
    mock_cursor = AsyncMock()

    # Configure fetchone side effects later

    # Mock execute to return the helper
    mock_db.execute = MagicMock(return_value=AwaitableAsyncContextManager(mock_cursor))

    # Scenario:
    # 1. Check strain -> Found (return strain_id)
    # 2. Check phenotype -> Not Found
    # 3. Insert phenotype -> Success
    # 4. Check phenotype again -> Still Not Found (Simulation of race condition or failure)

    mock_cursor.fetchone = AsyncMock(
        side_effect=[
            (1,),  # Strain ID found
            None,  # Phenotype not found first time
            None,  # Phenotype still not found after insert
        ]
    )

    with pytest.raises(RuntimeError, match="Failed to retrieve phenotype ID"):
        await lib._ensure_strain_and_phenotype_exist("StrainX", "PhenoY")


@pytest.mark.asyncio
async def test_hybrid_percentage_validation(mock_hass) -> None:
    """Test hybrid percentage validation error."""
    lib = StrainLibrary(mock_hass)
    lib._db = MagicMock()  # Connected

    with pytest.raises(
        ValueError, match="Combined Sativa/Indica percentage cannot exceed 100%"
    ):
        await lib.add_strain(
            "Hybrid Strain",
            strain_type="Hybrid",
            sativa_percentage=60,
            indica_percentage=60,
        )
