"""Tests for the Growspace Manager report service."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.services.report import (
    _aggregate_plant_data,
    handle_export_grow_report,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_plant() -> Plant:
    """Mock plant."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "test_plant"
    plant.growspace_id = "test_growspace"
    plant.genetics.strain_name = "Test Strain"
    plant.genetics.phenotype_name = "#1"

    # Mock the properties that report.py accesses
    type(plant).strain = PropertyMock(return_value="Test Strain")
    type(plant).phenotype = PropertyMock(return_value="#1")

    plant.stage = "veg"
    plant.created_at = "2024-01-01T00:00:00+00:00"
    plant.stage_history = [
        {"stage": "seedling", "start": "2024-01-01T00:00:00+00:00"},
        {"stage": "veg", "start": "2024-01-14T00:00:00+00:00"},
    ]
    return plant


@pytest.fixture
def mock_growspace() -> Growspace:
    """Mock growspace."""
    growspace = MagicMock(spec=Growspace)
    growspace.id = "test_growspace"
    growspace.name = "Test Growspace"
    growspace.environment_config.temperature_sensor = "sensor.test_temp"
    growspace.environment_config.humidity_sensor = "sensor.test_humidity"
    growspace.environment_config.vpd_sensor = "sensor.test_vpd"
    return growspace


async def test_aggregate_plant_data(
    hass: HomeAssistant, mock_plant: Plant, mock_growspace: Growspace
) -> None:
    """Test data aggregation for the report."""
    mock_coordinator = MagicMock()
    mock_coordinator.get_growspace.return_value = mock_growspace
    mock_coordinator.get_plant.return_value = mock_plant

    with (
        patch(
            "custom_components.growspace_manager.services.report.get_instance"
        ) as mock_get_instance,
        patch(
            "custom_components.growspace_manager.websocket._get_statistics_data",
            new_callable=AsyncMock,
        ) as mock_get_stats,
    ):
        mock_recorder = MagicMock()
        mock_get_instance.return_value = mock_recorder

        # Mock logbook events
        mock_events = [
            {
                "plant_id": "test_plant",
                "category": "training",
                "notes": "Topped",
                "timestamp": 1705276800000,
            },
            {
                "growspace_id": "test_growspace",
                "category": "environment",
                "notes": "Light changed",
                "timestamp": 1705363200000,
            },
        ]
        mock_recorder.async_add_executor_job = AsyncMock(return_value=mock_events)

        # Mock statistics data
        mock_get_stats.return_value = {
            "sensor.test_temp": [{"lu": "2024-01-15T12:00:00+00:00", "s": 25.5}],
            "sensor.test_humidity": [{"lu": "2024-01-15T12:00:00+00:00", "s": 60.0}],
            "sensor.test_vpd": [{"lu": "2024-01-15T12:00:00+00:00", "s": 1.1}],
        }

        data = await _aggregate_plant_data(hass, mock_coordinator, mock_plant)

        assert data["plant_info"]["id"] == "test_plant"
        assert data["plant_info"]["strain"] == "Test Strain"
        assert data["plant_info"]["stage"] == "veg"
        assert len(data["timeline_events"]) == 2

        # Check environmental averages for veg stage
        assert "veg" in data["environmental_averages"]
        veg_stats = data["environmental_averages"]["veg"]
        assert veg_stats["temperature"] == 25.5
        assert veg_stats["humidity"] == 60.0
        assert veg_stats["vpd"] == 1.1


async def test_export_grow_report_json(
    hass: HomeAssistant, mock_plant: Plant, mock_growspace: Growspace, tmp_path: Path
) -> None:
    """Test generating a JSON report."""
    mock_coordinator = MagicMock()
    mock_coordinator.get_plant.return_value = mock_plant
    mock_coordinator.get_growspace.return_value = mock_growspace

    # Setup config path to point to tmp_path
    hass.config.path = MagicMock(return_value=str(tmp_path / "www"))

    with (
        patch(
            "custom_components.growspace_manager.services.report._aggregate_plant_data",
            new_callable=AsyncMock,
        ) as mock_aggregate,
        patch(
            "custom_components.growspace_manager.services.report.datetime"
        ) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "20240101_120000"
        mock_aggregate.return_value = {"plant_info": {"id": "test_plant"}}

        call = MagicMock()
        call.data = {"plant_id": "test_plant", "format": "json"}
        await handle_export_grow_report(hass, mock_coordinator, call)

        expected_file = tmp_path / "www" / "Test_Strain_#1_20240101_120000.json"
        assert expected_file.exists()

        data = json.loads(expected_file.read_text())
        assert data["plant_info"]["id"] == "test_plant"


async def test_export_grow_report_pdf(
    hass: HomeAssistant, mock_plant: Plant, mock_growspace: Growspace, tmp_path: Path
) -> None:
    """Test generating a PDF report."""
    mock_coordinator = MagicMock()
    mock_coordinator.get_plant.return_value = mock_plant
    mock_coordinator.get_growspace.return_value = mock_growspace

    hass.config.path = MagicMock(return_value=str(tmp_path / "www"))

    with (
        patch(
            "custom_components.growspace_manager.services.report._aggregate_plant_data",
            new_callable=AsyncMock,
        ) as mock_aggregate,
        patch(
            "custom_components.growspace_manager.services.report.datetime"
        ) as mock_dt,
    ):
        mock_dt.now.return_value.strftime.return_value = "20240101_120000"
        mock_dt.now.return_value.timestamp.return_value = 1704110400
        mock_aggregate.return_value = {
            "plant_info": {
                "id": "test_plant",
                "strain": "Test Strain",
                "phenotype": "#1",
                "growspace": "Test Growspace",
                "stage": "veg",
                "created_at": "2024-01-01T00:00:00+00:00",
            },
            "environmental_averages": {
                "veg": {"temperature": 25.0, "humidity": 60.0, "vpd": 1.0}
            },
            "timeline_events": [
                {
                    "timestamp": 1704110400000,
                    "category": "training",
                    "notes": "Topped",
                }
            ],
            "stage_history": [],
        }

        call = MagicMock()
        call.data = {"plant_id": "test_plant", "format": "pdf"}
        await handle_export_grow_report(hass, mock_coordinator, call)

        expected_file = tmp_path / "www" / "Test_Strain_#1_20240101_120000.pdf"
        assert expected_file.exists()
        # Verify it's a PDF file (starts with %PDF)
        header = expected_file.read_bytes()[:4]
        assert header == b"%PDF"


@pytest.mark.asyncio
async def test_export_plant_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test export service fails if plant not found."""
    mock_coordinator.get_plant.return_value = None
    call = MagicMock(data={"plant_id": "missing_plant", "format": "json"})

    with pytest.raises(HomeAssistantError, match="Plant missing_plant not found"):
        await handle_export_grow_report(hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_export_growspace_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock, mock_plant: Plant
) -> None:
    """Test aggregation fails if growspace not found."""
    mock_coordinator.get_growspace.return_value = None

    with pytest.raises(HomeAssistantError, match="Growspace test_growspace not found"):
        await _aggregate_plant_data(hass, mock_coordinator, mock_plant)


@pytest.mark.asyncio
async def test_export_no_stage_history_fallback(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test falling back to created_at if no stage_history."""
    mock_plant.stage_history = []
    mock_plant.created_at = "2024-01-01T00:00:00+00:00"

    with patch("custom_components.growspace_manager.services.report.get_instance"):
        result = await _aggregate_plant_data(hass, mock_coordinator, mock_plant)
        assert result["plant_info"]["stage"] == "veg"  # From mock_plant


@pytest.mark.asyncio
async def test_export_no_start_time_fallback(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test falling back to now if no stage_history and no created_at."""
    mock_plant.stage_history = []
    mock_plant.created_at = None

    with patch("custom_components.growspace_manager.services.report.get_instance"):
        result = await _aggregate_plant_data(hass, mock_coordinator, mock_plant)
        assert result["plant_info"]["stage"] == "veg"


@pytest.mark.asyncio
async def test_export_logbook_exception(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test exception during logbook fetch."""
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(
        side_effect=HomeAssistantError("DB Error")
    )

    with patch(
        "custom_components.growspace_manager.services.report.get_instance",
        return_value=mock_recorder,
    ):
        with pytest.raises(HomeAssistantError, match="DB Error"):
            await _aggregate_plant_data(hass, mock_coordinator, mock_plant)


@pytest.mark.asyncio
async def test_export_logbook_general_exception(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test generic exception during logbook fetch."""
    mock_recorder = MagicMock()
    mock_recorder.async_add_executor_job = AsyncMock(
        side_effect=Exception("Other DB Error")
    )

    with patch(
        "custom_components.growspace_manager.services.report.get_instance",
        return_value=mock_recorder,
    ):
        # Should catch Exception and just log warning, so no raise.
        result = await _aggregate_plant_data(hass, mock_coordinator, mock_plant)
        assert result["timeline_events"] == []


@pytest.mark.asyncio
async def test_export_statistics_exception(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test exception during statistics fetch."""
    mock_growspace.environment_config.temperature_sensor = "sensor.test_temp"

    with (
        patch("custom_components.growspace_manager.services.report.get_instance"),
        patch(
            "custom_components.growspace_manager.websocket._get_statistics_data",
            side_effect=HomeAssistantError("Stats Error"),
        ),
    ):
        with pytest.raises(HomeAssistantError, match="Stats Error"):
            await _aggregate_plant_data(hass, mock_coordinator, mock_plant)


@pytest.mark.asyncio
async def test_export_statistics_general_exception(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    mock_plant: Plant,
    mock_growspace: Growspace,
) -> None:
    """Test generic exception during statistics fetch."""
    mock_growspace.environment_config.temperature_sensor = "sensor.test_temp"

    with (
        patch("custom_components.growspace_manager.services.report.get_instance"),
        patch(
            "custom_components.growspace_manager.websocket._get_statistics_data",
            side_effect=Exception("Other Stats Error"),
        ),
    ):
        # Should catch Exception and just log warning.
        result = await _aggregate_plant_data(hass, mock_coordinator, mock_plant)
        assert result["environmental_averages"] == {}


@pytest.mark.asyncio
async def test_export_handle_general_exception(
    hass: HomeAssistant, mock_coordinator: MagicMock, mock_plant: Plant, tmp_path: Path
) -> None:
    """Test handle_export_grow_report handles generic exceptions."""
    call = MagicMock(data={"plant_id": "test_plant", "format": "json"})

    with (
        patch(
            "custom_components.growspace_manager.services.report._aggregate_plant_data",
            side_effect=Exception("Boom"),
        ),
        patch(
            "custom_components.growspace_manager.services.report.create_notification"
        ) as mock_create_notification,
    ):
        with pytest.raises(
            HomeAssistantError, match="Failed to export grow report: Boom"
        ):
            await handle_export_grow_report(hass, mock_coordinator, call)
        mock_create_notification.assert_called_once()
