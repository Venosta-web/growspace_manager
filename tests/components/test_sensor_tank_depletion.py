"""Tests for TankDepletionSensor in the Growspace Manager integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.sensor import (
    TankDepletionSensor,
    async_setup_entry,
)
from custom_components.growspace_manager.tank_depletion_predictor import TankPrediction
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_predictor():
    """Create a mock TankDepletionPredictor."""
    predictor = MagicMock()
    predictor.get_prediction.return_value = TankPrediction(
        status="depleting",
        data_points=10,
        hours_remaining=12.5,
        slope_pct_per_hour=-0.5,
        daily_usage_rate=12.0,
        active_consumption_rate=0.8,
        dormant_consumption_rate=0.2,
    )
    predictor.async_update = AsyncMock()
    return predictor


@pytest.fixture
def sensor(mock_coordinator, mock_predictor):
    """Create a TankDepletionSensor instance."""
    return TankDepletionSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        tank_name="Main Tank",
        predictor=mock_predictor,
    )


class TestTankDepletionSensor:
    """Tests for TankDepletionSensor class."""

    def test_initialization(self, sensor, mock_predictor):
        """Test basic initialization."""
        assert sensor._growspace_id == "gs1"
        assert sensor._tank_name == "Main Tank"
        assert sensor._predictor == mock_predictor
        assert sensor.name == "gs1 Tank Depletion Main Tank"
        assert sensor.unique_id == f"{DOMAIN}_gs1_tank_depletion_Main Tank"

    def test_available(self, sensor, mock_coordinator):
        """Test availability property."""
        mock_coordinator.last_update_success = True
        assert sensor.available is True

        mock_coordinator.last_update_success = False
        assert sensor.available is False

    def test_native_value_depleting(self, sensor):
        """Test value when depleting."""
        assert sensor.native_value == 12.5

    def test_native_value_insufficient_data(self, sensor, mock_predictor):
        """Test value when insufficient data."""
        mock_predictor.get_prediction.return_value = TankPrediction(
            status="insufficient_data",
            data_points=2,
            hours_remaining=None,
            slope_pct_per_hour=None,
            daily_usage_rate=None,
            active_consumption_rate=None,
            dormant_consumption_rate=None,
        )
        assert sensor.native_value is None

    def test_native_value_refilling_static(self, sensor, mock_predictor):
        """Test value when refilling or static."""
        # Refilling
        mock_predictor.get_prediction.return_value = TankPrediction(
            status="refilling",
            data_points=10,
            hours_remaining=None,
            slope_pct_per_hour=0.5,
            daily_usage_rate=12.0,
            active_consumption_rate=None,
            dormant_consumption_rate=None,
        )
        assert sensor.native_value is None

        # Static
        mock_predictor.get_prediction.return_value = TankPrediction(
            status="static",
            data_points=10,
            hours_remaining=None,
            slope_pct_per_hour=0.0,
            daily_usage_rate=0.0,
            active_consumption_rate=None,
            dormant_consumption_rate=None,
        )
        assert sensor.native_value is None

    def test_extra_state_attributes(self, sensor):
        """Test attributes."""
        attrs = sensor.extra_state_attributes
        assert attrs["status"] == "depleting"
        assert attrs["data_points"] == 10
        assert attrs["slope_pct_per_hour"] == -0.5
        assert attrs["daily_usage_rate"] == 12.0
        assert attrs["active_consumption_rate"] == 0.8
        assert attrs["dormant_consumption_rate"] == 0.2

    @pytest.mark.asyncio
    async def test_async_update(self, sensor, mock_predictor):
        """Test async_update calls predictor."""
        await sensor.async_update()
        mock_predictor.async_update.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_setup_entry_with_tanks(hass: HomeAssistant, mock_coordinator):
    """Test that TankDepletionSensor is created during setup if tanks enabled."""
    hass.config.config_dir = "/config"

    # Mock IrrigationTank class to avoid complex instantiation
    with patch(
        "custom_components.growspace_manager.sensor.TankDepletionPredictor"
    ) as mock_predictor_cls:
        mock_predictor_instance = MagicMock()
        mock_predictor_instance.async_update = AsyncMock()
        mock_predictor_cls.return_value = mock_predictor_instance

        # Configure a tank in environment_config
        tank_data = {
            "name": "Irrigation Tank",
            "sensor_entity": "sensor.tank_level",
            "warning_level": 25.0,
            "enable_prediction": True,
        }

        gs_mock = MagicMock()
        gs_mock.id = "gs1"
        gs_mock.name = "Growspace 1"
        gs_mock.environment_config = {"irrigation_tanks": [tank_data]}

        mock_coordinator.growspaces = {"gs1": gs_mock}
        mock_coordinator.get_growspace_plants.return_value = []
        mock_coordinator.async_request_refresh = AsyncMock()

        added_entities = []

        def async_add_entities(entities):
            added_entities.extend(entities)

        # We need to mock IrrigationTank.from_dict if it's imported
        with patch(
            "custom_components.growspace_manager.models.IrrigationTank.from_dict",
            return_value=MagicMock(),
        ):
            await async_setup_entry(
                hass,
                MagicMock(runtime_data=mock_coordinator, options={}),
                async_add_entities,
            )

        # Check if TankDepletionSensor was added
        tank_sensor = next(
            (e for e in added_entities if isinstance(e, TankDepletionSensor)), None
        )
        assert tank_sensor is not None
        assert tank_sensor._tank_name == "Irrigation Tank"
        mock_predictor_instance.async_update.assert_awaited_once()
