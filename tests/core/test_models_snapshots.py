"""Snapshot tests for Growspace Manager models."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.core import HomeAssistant


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
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


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
def test_environment_config_serialization_snapshot(snapshot: SnapshotAssertion) -> None:
    """Test EnvironmentConfig model serialization yields expected structure."""
    config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        control_dehumidifier=True,
    )
    assert config.to_dict() == snapshot


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
@pytest.mark.asyncio
async def test_diagnostics_snapshot(
    hass: HomeAssistant, snapshot: SnapshotAssertion
) -> None:
    """Test diagnostics output matches snapshot and handles redaction correctly."""
    entry = MagicMock()
    entry.as_dict.return_value = {
        "entry_id": "test_entry",
        "data": {"some": "data", "latitude": 12.34, "vision_access_token": "secret"},
    }

    coordinator = MagicMock()
    coordinator.data = {
        "growspaces": {
            "gs1": {
                "name": "Test Growspace",
                "unique_id": "sensitive",
                "notification_target": "notify.phone",
                "camera_url": "rtsp://private",
            }
        },
        "plants": {},
    }
    coordinator.growspaces = {"gs1": object()}
    coordinator.plants = {}
    coordinator.services.config.strain_library = None
    irrigation = MagicMock(spec=VWCIrrigationCoordinator)
    irrigation.active_events = {"irrigation": {"start_time": "2024-01-01T12:00:00"}}
    irrigation.cycles_today = 2
    irrigation.volume_dispensed_today = 1.5
    irrigation.last_cycle_timestamp = "2024-01-01T11:00:00"
    irrigation.next_scheduled_cycle = None
    irrigation.projected_shot_window = {
        "start": "2024-01-01T13:00:00",
        "end": "2024-01-01T13:10:00",
    }
    irrigation.controller_snapshot.return_value = SimpleNamespace(
        state=SimpleNamespace(value="running"),
        attributes=lambda: {
            "reasons": [],
            "fault_id": None,
            "requires_ack": False,
            "since": None,
        },
    )
    irrigation.growspace = SimpleNamespace(
        irrigation_strategy=SimpleNamespace(active_steering_phase="P2")
    )
    irrigation.tank_diagnostics.return_value = [
        {
            "name": "Feed",
            "sensor_entity": "sensor.tank",
            "valid": False,
            "level": None,
            "warning_level": 20.0,
        }
    ]
    irrigation.shot_composition_payload.return_value = {
        "suppressed_by": "infiltrating",
        "last_shot": None,
    }
    irrigation.ec_state_payload.return_value = {
        "recommendation": "hold",
        "pore_ec": None,
    }
    dehumidifier = MagicMock(spec=DehumidifierCoordinator)
    dehumidifier.diagnostics_snapshot.return_value = {
        "control_enabled": True,
        "entities": ["switch.dehumidifier"],
        "ac_infinity_ports": [],
        "vpd_sensor": "sensor.vpd",
        "stage": "veg",
        "period": "day",
        "thresholds": {"on": 0.6, "off": 0.7},
        "last_command": None,
        "last_command_at": None,
    }
    coordinator.services.growspaces.get_irrigation_coordinator.return_value = irrigation
    coordinator.services.growspaces.get_dehumidifier_coordinator.return_value = (
        dehumidifier
    )
    coordinator.services.growspaces.get_humidifier_coordinator.return_value = None
    coordinator.services.growspaces.get_circulation_fan_coordinator.return_value = None
    coordinator.services.growspaces.get_exhaust_fan_coordinator.return_value = None
    coordinator.irrigation_safety = SimpleNamespace(
        faults={}, emergency_stops={}, unreadable=False, ledger=[]
    )
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "None" not in str(result["subsystems"])
    assert result == snapshot
