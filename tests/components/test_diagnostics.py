"""Test the Growspace Manager diagnostics."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.climate_safety import ClimateSafety
from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.diagnostics import (
    _irrigation_diagnostics,
    _safe,
    async_get_config_entry_diagnostics,
)
from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    BaseIrrigationCoordinator,
    IrrigationCoordinator,
)
from custom_components.growspace_manager.services.growspace_facade import (
    GrowspaceFacade,
)
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics(hass: HomeAssistant) -> None:
    """Test diagnostics."""
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

    assert "entry" in result
    assert "coordinator_data" in result

    # Check redaction
    assert result["entry"]["data"]["latitude"] == "**REDACTED**"
    assert (
        result["coordinator_data"]["growspaces"]["gs1"]["unique_id"] == "**REDACTED**"
    )
    assert result["coordinator_data"]["growspaces"]["gs1"]["name"] == "Test Growspace"


def test_nested_private_diagnostics_values_are_redacted() -> None:
    """Redaction covers both named fields and URLs embedded in arbitrary fields."""
    data = {
        "notification_target": "notify.phone",
        "settings": [
            {"camera_url": "rtsp://user:pass@example.local/live"},
            {"vision_access_token": "secret", "note": "https://private.example/path"},
            {"sensor_coordinates": {"sensor.a": {"x": 1.0}}},
        ],
    }
    assert _safe(data) == {
        "notification_target": "**REDACTED**",
        "settings": [
            {"camera_url": "**REDACTED**"},
            {"vision_access_token": "**REDACTED**", "note": "**REDACTED**"},
            {"sensor_coordinates": "**REDACTED**"},
        ],
    }


def test_tank_diagnostics_keeps_invalid_readings_visible() -> None:
    """A missing sensor remains in the report with an explicit validity flag."""
    coordinator = object.__new__(BaseIrrigationCoordinator)
    tank = SimpleNamespace(name="Feed", sensor_entity="sensor.tank", warning_level=20.0)
    growspace = SimpleNamespace(
        environment_config=SimpleNamespace(irrigation_tanks=[tank])
    )
    coordinator._growspace_id = "gs1"
    coordinator._main_coordinator = SimpleNamespace(growspaces={"gs1": growspace})
    coordinator._get_sensor_value = MagicMock(return_value=None)
    assert coordinator.tank_diagnostics() == [
        {
            "name": "Feed",
            "sensor_entity": "sensor.tank",
            "valid": False,
            "level": None,
            "warning_level": 20.0,
        }
    ]
    coordinator._get_sensor_value.return_value = 42.0
    assert coordinator.tank_diagnostics()[0]["level"] == 42.0
    assert coordinator.tank_diagnostics()[0]["valid"] is True


def test_schedule_irrigation_diagnostics_uses_live_state() -> None:
    """The schedule coordinator does not depend on invented legacy fields."""
    coordinator = MagicMock(spec=IrrigationCoordinator)
    coordinator.active_events = {}
    coordinator.cycles_today = 3
    coordinator.volume_dispensed_today = 1.25
    coordinator.last_cycle_timestamp = "2024-01-01T11:00:00"
    coordinator.next_scheduled_cycle = "2024-01-01T14:00:00"
    coordinator.controller_snapshot.return_value = SimpleNamespace(
        state=SimpleNamespace(value="ready"),
        attributes=lambda: {"reasons": [], "fault_id": None},
    )
    coordinator.tank_diagnostics.return_value = []
    result = _irrigation_diagnostics(coordinator)
    assert result["mode"] == "schedule"
    assert result["cycles_today"] == 3
    assert result["next_scheduled_cycle"] == "2024-01-01T14:00:00"
    assert result["controller"]["state"] == "ready"


def test_dehumidifier_diagnostics_reports_current_thresholds() -> None:
    """The live controller reports its configured outputs and current VPD band."""
    coordinator = object.__new__(DehumidifierCoordinator)
    coordinator.control_enabled = True
    coordinator.vpd_sensor = "sensor.vpd"
    coordinator.light_sensors = []
    coordinator.hass = MagicMock()
    coordinator.growspace = SimpleNamespace(
        environment_config=SimpleNamespace(
            dehumidifier_entities=["switch.dehumidifier"],
            dehumidifier_ac_infinity_devices=[],
        )
    )
    coordinator._day_night = SimpleNamespace(determine=lambda _hass, _sensors: True)
    coordinator._get_growth_stage = MagicMock(return_value=PlantStage.VEG)
    coordinator._get_current_thresholds = MagicMock(
        return_value={"on": 0.6, "off": 0.7}
    )
    coordinator._last_command = "on"
    coordinator._last_command_at = "2024-01-01T12:00:00"
    coordinator._safety = ClimateSafety(MagicMock(), "gs1", MagicMock())
    assert coordinator.diagnostics_snapshot() == {
        "control_enabled": True,
        "entities": ["switch.dehumidifier"],
        "ac_infinity_ports": [],
        "vpd_sensor": "sensor.vpd",
        "stage": PlantStage.VEG.value,
        "period": "day",
        "thresholds": {"on": 0.6, "off": 0.7},
        "last_command": "on",
        "last_command_at": "2024-01-01T12:00:00",
        "fail_safe": False,
    }


def test_fan_diagnostics_reports_targets_and_commands() -> None:
    """Both fan controllers expose live targets and the last commanded speed."""
    common = {
        "enabled": True,
        "temperature_target": 25.0,
        "humidity_target": 60.0,
        "vpd_target": 1.2,
        "stage_vpd_enabled": False,
    }
    env = SimpleNamespace(
        exhaust_fan_config=SimpleNamespace(**common),
        circulation_fan_config=SimpleNamespace(
            **common, regulation_mode=SimpleNamespace(value="vpd")
        ),
        exhaust_fan_entities=["fan.exhaust"],
        circulation_fan_entities=["fan.circulation"],
        exhaust_fan_ac_infinity_devices=[],
        circulation_fan_ac_infinity_devices=[],
    )
    main = SimpleNamespace(growspaces={"gs1": SimpleNamespace(environment_config=env)})
    for cls, entity in (
        (ExhaustFanCoordinator, "fan.exhaust"),
        (CirculationFanCoordinator, "fan.circulation"),
    ):
        controller = object.__new__(cls)
        controller.growspace_id = "gs1"
        controller.main_coordinator = main
        controller._last_command = 55
        controller._last_command_at = "2024-01-01T12:00:00"
        controller._safety = ClimateSafety(MagicMock(), "gs1", main)
        result = controller.diagnostics_snapshot()
        assert result["entities"] == [entity]
        assert result["thresholds"] == {
            "temperature": 25.0,
            "humidity": 60.0,
            "vpd": 1.2,
        }
        assert result["last_command"] == 55
        assert result["last_command_at"] == "2024-01-01T12:00:00"


def test_fan_diagnostics_handles_missing_and_stage_targets() -> None:
    """A removed growspace has no snapshot; stage VPD overrides are resolved."""
    main = SimpleNamespace(growspaces={})
    exhaust = object.__new__(ExhaustFanCoordinator)
    exhaust.growspace_id = "gs1"
    exhaust.main_coordinator = main
    assert exhaust.diagnostics_snapshot() == {}

    circulation = object.__new__(CirculationFanCoordinator)
    circulation.growspace_id = "gs1"
    circulation.main_coordinator = main
    assert circulation.diagnostics_snapshot() == {}

    cfg = SimpleNamespace(
        enabled=True,
        stage_vpd_enabled=True,
        vpd_target=1.0,
        regulation_mode=SimpleNamespace(value="vpd"),
        temperature_target=25.0,
        humidity_target=60.0,
    )
    env = SimpleNamespace(
        circulation_fan_config=cfg,
        circulation_fan_entities=[],
        circulation_fan_ac_infinity_devices=[],
        light_sensors=[],
    )
    main.growspaces["gs1"] = SimpleNamespace(environment_config=env)
    circulation.hass = MagicMock()
    circulation._day_night = SimpleNamespace(determine=lambda _hass, _sensors: True)
    circulation._get_stage_vpd_target = MagicMock(return_value=1.5)
    circulation._last_command = None
    circulation._last_command_at = None
    assert circulation.diagnostics_snapshot()["thresholds"]["vpd"] == 1.5
    circulation._get_stage_vpd_target.assert_called_once_with(cfg, True)


def test_climate_facade_reaches_each_controller() -> None:
    """Diagnostics getters use the subsystem manager's typed lookup."""
    facade = object.__new__(GrowspaceFacade)
    manager = SimpleNamespace(
        get_humidifier_controller=MagicMock(return_value="humidifier"),
        get_circulation_fan_controller=MagicMock(return_value="circulation"),
        get_exhaust_fan_controller=MagicMock(return_value="exhaust"),
    )
    facade._coordinator = SimpleNamespace(_subsystem_manager=manager)
    assert facade.get_humidifier_coordinator("gs1") == "humidifier"
    assert facade.get_circulation_fan_coordinator("gs1") == "circulation"
    assert facade.get_exhaust_fan_coordinator("gs1") == "exhaust"
    manager.get_humidifier_controller.assert_called_once_with("gs1")
    manager.get_circulation_fan_controller.assert_called_once_with("gs1")
    manager.get_exhaust_fan_controller.assert_called_once_with("gs1")
