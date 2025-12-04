"""Tests for the Strain Library Import/Export config flow steps."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.config_flow import OptionsFlowHandler
from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_coordinator(hass: HomeAssistant, tmp_path: Path):
    """Create a mock coordinator with import/export manager."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.import_export_manager = AsyncMock()
    coordinator.strain_library = MagicMock()
    coordinator.strain_library.get_all.return_value = {"strain1": {}}
    coordinator.strain_library.async_load = AsyncMock()
    coordinator.strain_library.get_all_strains.return_value = []
    return coordinator


@pytest.mark.asyncio
async def test_import_strain_library_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the import step shows the form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_import_strain_library()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "import_strain_library"


@pytest.mark.asyncio
async def test_import_strain_library_success(
    hass: HomeAssistant, mock_coordinator, tmp_path: Path
) -> None:
    """Test successful import."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    with patch(
        "custom_components.growspace_manager.config_flow.OptionsFlowHandler.async_step_manage_strain_library",
        return_value={"type": FlowResultType.FORM, "step_id": "manage_strain_library"},
    ):
        result = await flow.async_step_import_strain_library(
            user_input={"file_path": str(tmp_path / "test.zip")}
        )

        assert result.get("type") == FlowResultType.FORM
        assert result.get("step_id") == "manage_strain_library"

        mock_coordinator.import_export_manager.import_library.assert_awaited_once()
        mock_coordinator.strain_library.async_load.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_strain_library_file_not_found(
    hass: HomeAssistant, mock_coordinator, tmp_path: Path
) -> None:
    """Test import with file not found error."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    mock_coordinator.import_export_manager.import_library.side_effect = (
        FileNotFoundError
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_import_strain_library(
        user_input={"file_path": str(tmp_path / "missing.zip")}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "file_not_found"}


@pytest.mark.asyncio
async def test_import_strain_library_invalid_zip(
    hass: HomeAssistant, mock_coordinator, tmp_path: Path
) -> None:
    """Test import with invalid zip error."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    mock_coordinator.import_export_manager.import_library.side_effect = ValueError

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_import_strain_library(
        user_input={"file_path": str(tmp_path / "invalid.zip")}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "invalid_zip"}


@pytest.mark.asyncio
async def test_export_strain_library_success(
    hass: HomeAssistant, mock_coordinator, tmp_path: Path
) -> None:
    """Test successful export."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    mock_coordinator.import_export_manager.export_library.return_value = str(
        tmp_path / "export.zip"
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_export_strain_library()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "export_strain_library"
    assert result.get("description_placeholders") == {
        "path": str(tmp_path / "export.zip")
    }

    mock_coordinator.import_export_manager.export_library.assert_awaited_once()


@pytest.mark.asyncio
async def test_export_strain_library_failure(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test export failure."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data.coordinator = mock_coordinator

    mock_coordinator.import_export_manager.export_library.side_effect = Exception(
        "Export failed"
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_export_strain_library()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "export_failed"
