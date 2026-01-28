"""Snapshot tests for Growspace Manager models."""

from unittest.mock import MagicMock

import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from homeassistant.core import HomeAssistant


def test_growspace_serialization_snapshot(snapshot: SnapshotAssertion) -> None:
    """Test Growspace model serialization yields expected structure."""
    gs = Growspace(
        id="gs_test",
        name="Test Growspace",
        rows=2,
        plants_per_row=4,
        growspace_type=GrowspaceType.VEG,
    )
    # Using to_dict() from DataClassDictMixin (mashumaro)
    assert gs.to_dict() == snapshot


def test_plant_serialization_snapshot(snapshot: SnapshotAssertion) -> None:
    """Test Plant model serialization yields expected structure."""
    plant = Plant(
        plant_id="plant_1",
        growspace_id="gs_test",
        row=1,
        col=2,
        stage="veg",
    )
    assert plant.to_dict() == snapshot


def test_environment_config_serialization_snapshot(snapshot: SnapshotAssertion) -> None:
    """Test EnvironmentConfig model serialization yields expected structure."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        control_dehumidifier=True,
    )
    assert config.to_dict() == snapshot


@pytest.mark.asyncio
async def test_diagnostics_snapshot(
    hass: HomeAssistant, snapshot: SnapshotAssertion
) -> None:
    """Test diagnostics output matches snapshot and handles redaction correctly."""
    entry = MagicMock()
    entry.as_dict.return_value = {
        "entry_id": "test_entry",
        "data": {"some": "data", "latitude": 12.34},
    }

    coordinator = MagicMock()
    coordinator.data = {
        "growspaces": {"gs1": {"name": "Test Growspace", "unique_id": "sensitive"}},
        "plants": {},
    }
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result == snapshot
