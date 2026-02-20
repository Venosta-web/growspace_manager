"""Tests for the print_label service fix."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "success"})
    hass.config = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock()
    coordinator.plants = {}
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    strain_library = MagicMock()
    strain_library.load = AsyncMock()
    strain_library.get_all = MagicMock(return_value={})
    return strain_library


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    call.data = {"strain": "Test Strain", "phenotype": "Pheno 1"}
    return call


@pytest.mark.asyncio
async def test_handle_print_label_fix_verification(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Verify that handle_print_label works with the fixes."""

    # Mock get_url to ensure it's called and doesn't crash
    with patch(
        "custom_components.growspace_manager.services.strain_library.get_url",
        return_value="http://homeassistant.local",
    ):
        # We need to mock datetime.now() to avoid issues with return values in tests if needed,
        # but the main goal is to ensure they don't cause UndefinedName errors.

        # Test with plant_id to trigger get_url call
        mock_call.data = {"plant_id": "plant_1"}
        mock_coordinator.plants = {"plant_1": MagicMock()}
        mock_coordinator.plants["plant_1"].genetics.strain_name = "Test Strain"
        mock_coordinator.plants["plant_1"].genetics.phenotype_name = "Pheno 1"

        response = await handle_print_label(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

        assert response == {"status": "success"}
        mock_hass.services.async_call.assert_awaited_once()

        # Verify the payload contains the expected URL
        service_data = mock_hass.services.async_call.call_args.args[2]
        payload = service_data["payload"]

        qr_code_item = next(
            (item for item in payload if item["type"] == "qrcode"), None
        )
        assert qr_code_item is not None
        assert qr_code_item["data"] == "http://homeassistant.local/plant/plant_1"


@pytest.mark.asyncio
async def test_handle_print_label_with_base_url(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Verify that handle_print_label uses base_url if provided."""
    mock_call.data = {
        "plant_id": "plant_1",
        "base_url": "http://my-dashboard.local/lovelace/growspace",
    }
    mock_coordinator.plants = {"plant_1": MagicMock()}
    mock_coordinator.plants["plant_1"].genetics.strain_name = "Test Strain"
    mock_coordinator.plants["plant_1"].genetics.phenotype_name = "Pheno 1"

    await handle_print_label(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    # Verify the payload contains the custom base_url
    service_data = mock_hass.services.async_call.call_args.args[2]
    payload = service_data["payload"]

    qr_code_item = next((item for item in payload if item["type"] == "qrcode"), None)
    assert qr_code_item is not None
    assert (
        qr_code_item["data"]
        == "http://my-dashboard.local/lovelace/growspace?plantId=plant_1"
    )
