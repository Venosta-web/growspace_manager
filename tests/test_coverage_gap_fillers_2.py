from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.plant_lifecycle_manager import (
    PlantLifecycleManager,
)
from custom_components.growspace_manager.strategies.mold import (
    MoldRiskEvaluatorStrategy,
)
from custom_components.growspace_manager.strategies.stress import (
    StressEvaluatorStrategy,
)
from homeassistant.core import HomeAssistant


async def test_lifecycle_manager_transition_closing_previous(
    hass: HomeAssistant,
) -> None:
    """Test transition_plant_stage explicitly closing previous stage."""
    repository = MagicMock()
    validator = MagicMock()
    gs_service = MagicMock()
    strain_library = MagicMock()
    serializer = MagicMock()
    save_callback = AsyncMock()
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)

    lifecycle_mgr = PlantLifecycleManager(
        repository=repository,
        validator=validator,
        growspace_service=gs_service,
        strain_library=strain_library,
        serializer=serializer,
        save_callback=save_callback,
        lock=lock,
    )

    plant_id = "plant_123"
    # Stage history where the last item is open (end=None)
    stage_history = [
        {"stage": "seedling", "start": "2023-01-01", "end": "2023-01-10"},
        {"stage": "vegetative", "start": "2023-01-10", "end": None},
    ]

    # Mock Plant object behaving like a dict/object as needed
    mock_plant = MagicMock()
    mock_plant.plant_id = plant_id
    mock_plant.stage_history = stage_history
    mock_plant.growspace_id = "gs1"
    mock_plant.to_dict.return_value = {"stage_history": stage_history}

    repository.plants = {plant_id: mock_plant}

    await lifecycle_mgr.transition_plant_stage(plant_id, "flower")

    # Check if 'stage_history' attribute on mock_plant was updated
    assert len(mock_plant.stage_history) == 3
    # Previous stage (index 1) should now have an end date
    assert mock_plant.stage_history[1]["end"] is not None
    # New stage (index 2) should be flower
    assert mock_plant.stage_history[2]["stage"] == "flower"


async def test_coordinator_water_growspace_error(hass: HomeAssistant) -> None:
    """Test async_water_growspace raises error when inputs missing."""
    entry = MockConfigEntry(domain="growspace_manager", data={})
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator(hass, entry, data={})

    coordinator.data_repository.growspaces = {
        "gs1": Growspace(id="gs1", name="Growspace 1")
    }
    # Mock return_value for get_growspace_plants to have 1 plant
    with (
        patch.object(
            coordinator, "get_growspace_plants", return_value=[MagicMock(plant_id="p1")]
        ),
        pytest.raises(GrowspaceError, match="required"),
    ):
        await coordinator.async_water_growspace(
            "gs1", amount=None, amount_per_plant=None
        )


async def test_binary_sensor_mold_risk_branches(hass: HomeAssistant) -> None:
    """Test BayesianMoldRiskSensor branches for probability calculation."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.notification_manager = MagicMock()
    coordinator.growspaces = {
        "gs1": Growspace(id="gs1", name="Growspace 1", device_id="device_1")
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
    state = MagicMock()
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
    assert any("humidity" in r[1].lower() for r in reasons)

    # 3. Notification Logic
    title_msg = strategy.get_notification_title_message(True)
    assert title_msg is not None
    assert "High Mold Risk" in title_msg[0]


async def test_binary_sensor_notification_failure(hass: HomeAssistant) -> None:
    """Test notification service failure handling in binary sensor."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.notification_manager = MagicMock()

    coordinator.growspaces = {
        "gs1": Growspace(id="gs1", name="Growspace 1", device_id="device_1")
    }
    coordinator.options = {CONF_AI_AUTO_ALERTS: True}

    desc = GrowspaceBinarySensorDescription(
        key="stress",
        sensor_type=GrowspaceSensorType.STRESS,
        prior_key="p",
        threshold_key="t",
    )

    sensor = BayesianEnvironmentSensor(
        coordinator,
        "gs1",
        EnvironmentConfig(temperature_sensor="s.t"),
        desc,
        StressEvaluatorStrategy,
    )
    sensor.notification_manager = MagicMock()
    sensor.notification_manager.async_send_notification.side_effect = Exception(
        "Notification Service Down"
    )

    await sensor._send_notification("Title", "Message")
    # Should not raise, exception caught and logged
