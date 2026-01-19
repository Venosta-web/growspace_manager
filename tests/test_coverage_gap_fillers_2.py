from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.binary_sensor import (
    BayesianEnvironmentSensor,
    GrowspaceBinarySensorDescription,
)
from custom_components.growspace_manager.const import (
    CONF_AI_AUTO_ALERTS,
    GrowspaceSensorType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)


async def test_lifecycle_manager_transition_closing_previous(
    hass: HomeAssistant,
) -> None:
    """Test transition_plant_stage explicitly closing previous stage."""
    coordinator = Mock()
    coordinator.hass = hass
    coordinator.plant_services = Mock()
    coordinator.plants = {}

    lifecycle_mgr = PlantLifecycleManager(coordinator)

    plant_id = "plant_123"
    # Stage history where the last item is open (end=None)
    stage_history = [
        {"stage": "seedling", "start": "2023-01-01", "end": "2023-01-10"},
        {"stage": "vegetative", "start": "2023-01-10", "end": None},
    ]

    # Mock Plant object behaving like a dict/object as needed
    mock_plant = Mock()
    mock_plant.plant_id = plant_id
    mock_plant.stage_history = stage_history
    mock_plant.growspace_id = "gs1"

    coordinator.plants[plant_id] = mock_plant
    coordinator.update_plant = AsyncMock()
    coordinator.async_commit = AsyncMock()
    # Fix for async with self.coordinator._lock
    coordinator._lock = AsyncMock()
    coordinator._lock.__aenter__ = AsyncMock(return_value=None)
    coordinator._lock.__aexit__ = AsyncMock(return_value=None)

    await lifecycle_mgr.transition_plant_stage(plant_id, "flower")

    # Check if 'stage_history' attribute on mock_plant was updated
    assert len(mock_plant.stage_history) == 3
    # Previous stage (index 1) should now have an end date
    assert mock_plant.stage_history[1]["end"] is not None
    # New stage (index 2) should be flower
    assert mock_plant.stage_history[2]["stage"] == "flower"


async def test_coordinator_water_growspace_error(hass: HomeAssistant) -> None:
    """Test async_water_growspace raises error when inputs missing."""
    coordinator = GrowspaceCoordinator(hass, Mock())
    coordinator.validator = Mock()
    coordinator.plants = {}  # growspace empty?
    # Ensure validate_growspace_exists passes mock
    coordinator.validator.validate_growspace_exists = Mock()
    coordinator.get_growspace_plants = Mock(return_value=[Mock(plant_id="p1")])

    with pytest.raises(GrowspaceError, match="required"):
        await coordinator.async_water_growspace(
            "gs1", amount=None, amount_per_plant=None
        )


async def test_binary_sensor_mold_risk_branches(hass: HomeAssistant) -> None:
    """Test BayesianMoldRiskSensor branches for probability calculation."""
    coordinator = Mock()  # Removing spec to avoid missing attribute issues
    coordinator.hass = hass
    coordinator.notification_manager = Mock()
    coordinator.growspaces = {}

    coordinator.growspaces = {
        "gs1": SimpleNamespace(name="Growspace 1", device_id="device_1")
    }

    desc = GrowspaceBinarySensorDescription(
        key="mold",
        sensor_type=GrowspaceSensorType.MOLD,
        prior_key="prior_mold",
        threshold_key="thresh",
    )
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.t", humidity_sensor="sensor.h"
    )

    sensor = BayesianEnvironmentSensor(
        coordinator, "gs1", env_config, desc, MoldRiskEvaluatorStrategy
    )

    strategy = sensor.strategy

    # Mock state object
    state = Mock()
    state.temp = 20
    state.humidity = 90
    state.fan_off = True
    state.humidifier_on = True
    state.flower_days = 0
    state.veg_days = 20
    state.seedling_days = 0
    state.clone_days = 0

    # 1. Veg + High Humidity (85+) + Fan Off + Humidifier On
    obs, reasons = await strategy.async_evaluate(state)
    assert len(obs) >= 3  # Humid (>85), Fan Off (Veg logic), Humidifier On (Veg logic)

    # 2. Late Flower + Humidity > 60
    state.flower_days = 45
    state.humidity = 65
    obs, reasons = await strategy.async_evaluate(state)
    # Humidity Risk (65>60 in late flower), Fan Off (Triggered?), Humidifier On (65>60)
    assert any("humidity" in r[1].lower() for r in reasons)

    # 3. Notification Logic
    title_msg = strategy.get_notification_title_message(True)
    assert title_msg is not None
    assert "High Mold Risk" in title_msg[0]


async def test_binary_sensor_notification_failure(hass: HomeAssistant) -> None:
    """Test notification service failure handling in binary sensor."""
    # Fix NameError
    coordinator = Mock()
    coordinator.hass = hass
    coordinator.notification_manager = Mock()

    coordinator.growspaces = {
        "gs1": SimpleNamespace(name="Growspace 1", device_id="device_1")
    }
    coordinator.options = {
        CONF_AI_AUTO_ALERTS: True
    }  # Enable AI to test that path too if desired

    desc = GrowspaceBinarySensorDescription(
        key="stress",
        sensor_type=GrowspaceSensorType.STRESS,
        prior_key="p",
        threshold_key="t",
    )
    # Need a valid strategy class for init

    sensor = BayesianEnvironmentSensor(
        coordinator,
        "gs1",
        EnvironmentConfig(temperature_sensor="s.t"),
        desc,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = Mock()
    sensor.notification_manager.async_send_notification.side_effect = Exception(
        "Notification Service Down"
    )

    # We need to trigger _send_notification.
    # It's usually triggered when probability > threshold in _async_update_probability -> _handle_alert_state
    # Or explicit call.

    await sensor._send_notification("Title", "Message")
    # Should not raise, exception caught and logged
