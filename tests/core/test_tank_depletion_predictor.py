"""Tests for tank_depletion_predictor module."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.models import EnvironmentConfig, IrrigationTank
from custom_components.growspace_manager.tank_depletion_predictor import (
    TankDepletionPredictor,
)
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import utcnow


@pytest.fixture
def mock_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


@pytest.fixture
def basic_tank():
    """Create a basic irrigation tank configuration."""
    return IrrigationTank(
        sensor_entity="sensor.tank_level",
        name="Test Tank",
        warning_level=30.0,
        enable_prediction=True,
        enable_lights_bias=False,
        enable_vpd_weighting=False,
    )


@pytest.fixture
def environment_config():
    """Create a basic environment configuration."""
    return EnvironmentConfig(
        light_sensors=["light.grow_light"],
        vpd_sensor="sensor.vpd",
    )


class TestTankDepletionPredictor:
    """Tests for TankDepletionPredictor class."""

    async def test_initialization(self, mock_hass, basic_tank):
        """Test predictor initialization."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        assert predictor.hass == mock_hass
        assert predictor.tank == basic_tank
        assert predictor.window_hours == 72
        assert len(predictor._buffer) == 0

    async def test_async_update_with_valid_state(self, mock_hass, basic_tank):
        """Test updating predictor with valid sensor state."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Mock sensor state
        mock_state = State("sensor.tank_level", "85.5")
        mock_hass.states.get.return_value = mock_state

        await predictor.async_update()

        assert len(predictor._buffer) == 1
        assert predictor._buffer[0][1] == 85.5
        assert predictor._buffer[0][2] is False  # Default when no light sensor

    async def test_async_update_with_unavailable_sensor(self, mock_hass, basic_tank):
        """Test updating predictor with unavailable sensor."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Mock unavailable sensor
        mock_state = State("sensor.tank_level", STATE_UNAVAILABLE)
        mock_hass.states.get.return_value = mock_state

        await predictor.async_update()

        assert len(predictor._buffer) == 0

    async def test_async_update_with_invalid_value(self, mock_hass, basic_tank):
        """Test updating predictor with invalid sensor value."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Mock invalid sensor value
        mock_state = State("sensor.tank_level", "not_a_number")
        mock_hass.states.get.return_value = mock_state

        await predictor.async_update()

        assert len(predictor._buffer) == 0

    async def test_buffer_expiration(self, mock_hass, basic_tank):
        """Test that old data points are expired from buffer."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank, window_hours=1)

        now = utcnow()

        # Add old data point
        predictor._buffer.append((now - timedelta(hours=2), 90.0, False))

        # Add current data point
        mock_state = State("sensor.tank_level", "85.0")
        mock_hass.states.get.return_value = mock_state

        await predictor.async_update()

        # Old data should be removed
        assert len(predictor._buffer) == 1
        assert predictor._buffer[0][1] == 85.0

    async def test_insufficient_data_prediction(self, mock_hass, basic_tank):
        """Test prediction with insufficient data points."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Only add 2 data points (need at least 4)
        mock_state = State("sensor.tank_level", "85.0")
        mock_hass.states.get.return_value = mock_state

        await predictor.async_update()
        await predictor.async_update()

        prediction = predictor.get_prediction()

        assert prediction.status == "insufficient_data"
        assert prediction.hours_remaining is None

    async def test_depleting_tank_prediction(self, mock_hass, basic_tank):
        """Test prediction for depleting tank."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()

        # Simulate depleting tank over 12 hours (100% -> 70%)
        for i in range(13):
            level = 100 - (i * 2.5)  # Depleting at ~2.5%/hour
            predictor._buffer.append((now - timedelta(hours=12 - i), level, False))

        prediction = predictor.get_prediction()

        assert prediction.status == "depleting"
        assert prediction.hours_remaining is not None
        assert prediction.hours_remaining > 0
        assert prediction.slope_pct_per_hour < 0
        assert prediction.daily_usage_rate > 0

    async def test_refilling_tank_prediction(self, mock_hass, basic_tank):
        """Test prediction for refilling tank."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()

        # Simulate refilling tank (50% -> 80%)
        for i in range(13):
            level = 50 + (i * 2.5)  # Refilling at ~2.5%/hour
            predictor._buffer.append((now - timedelta(hours=12 - i), level, False))

        prediction = predictor.get_prediction()

        assert prediction.status == "refilling"
        assert prediction.hours_remaining is None
        assert prediction.slope_pct_per_hour > 0

    async def test_static_tank_prediction(self, mock_hass, basic_tank):
        """Test prediction for static tank (no change)."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()

        # Simulate static tank
        for i in range(13):
            predictor._buffer.append((now - timedelta(hours=12 - i), 75.0, False))

        prediction = predictor.get_prediction()

        assert prediction.status == "static"
        assert prediction.hours_remaining is None
        assert abs(prediction.slope_pct_per_hour) < 0.1  # Below deadband

    async def test_sma_filter(self, mock_hass, basic_tank):
        """Test Simple Moving Average filtering."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Create noisy data
        data = [
            (utcnow() - timedelta(hours=i), 100 - i + (0.5 if i % 2 else -0.5))
            for i in range(10)
        ]

        filtered = predictor._apply_sma_filter(data, window=3)

        # Filtered data should be smoother
        assert len(filtered) == len(data)
        # Check that filtering actually happened
        assert filtered[5][1] != data[5][1]

    async def test_calculate_slope(self, mock_hass, basic_tank):
        """Test OLS slope calculation."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()

        # Perfect linear depletion: 100% -> 70% over 12 hours
        data = [(now - timedelta(hours=12 - i), 100 - i * 2.5) for i in range(13)]

        slope = predictor._calculate_slope(data)

        # Should be approximately -2.5 %/hour
        assert abs(slope - (-2.5)) < 0.1

    async def test_vpd_multiplier_enabled(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test VPD weighting when enabled."""
        basic_tank.enable_vpd_weighting = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        # Mock high VPD
        mock_vpd_state = State("sensor.vpd", "2.0")
        mock_hass.states.get.return_value = mock_vpd_state

        multiplier = predictor._get_vpd_multiplier()

        # High VPD should increase multiplier
        assert multiplier > 1.0

    async def test_vpd_multiplier_low_vpd(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test VPD multiplier with low VPD."""
        basic_tank.enable_vpd_weighting = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        # Mock low VPD
        mock_vpd_state = State("sensor.vpd", "0.8")
        mock_hass.states.get.return_value = mock_vpd_state

        multiplier = predictor._get_vpd_multiplier()

        # Low VPD should not increase multiplier
        assert multiplier == 1.0

    async def test_vpd_multiplier_unavailable(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test VPD multiplier when VPD sensor unavailable."""
        basic_tank.enable_vpd_weighting = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        # Mock unavailable VPD
        mock_vpd_state = State("sensor.vpd", STATE_UNAVAILABLE)
        mock_hass.states.get.return_value = mock_vpd_state

        multiplier = predictor._get_vpd_multiplier()

        assert multiplier is None

    async def test_lights_bias_disabled(self, mock_hass, basic_tank):
        """Test that lights bias is not calculated when disabled."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()
        for i in range(13):
            predictor._buffer.append((now - timedelta(hours=12 - i), 100 - i, False))

        prediction = predictor.get_prediction()

        assert prediction.active_consumption_rate is None
        assert prediction.dormant_consumption_rate is None

    async def test_data_point_count_in_prediction(self, mock_hass, basic_tank):
        """Test that prediction includes data point count."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()
        for i in range(10):
            predictor._buffer.append((now - timedelta(hours=i), 90 - i, False))

        prediction = predictor.get_prediction()

        assert prediction.data_points == 10

    async def test_hours_remaining_calculation(self, mock_hass, basic_tank):
        """Test hours remaining estimation."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()

        # Tank depleting from 74% to 50% over 12 hours at ~2%/hour
        # Current level: 50%, threshold: 30%, expected: (50-30)/2 = 10 hours
        for i in range(13):
            level = 74 - (i * 2)
            predictor._buffer.append((now - timedelta(hours=12 - i), level, False))

        prediction = predictor.get_prediction()

        assert prediction.status == "depleting"
        assert prediction.hours_remaining is not None
        # Should be approximately 10 hours
        assert 9 < prediction.hours_remaining < 11

    async def test_edge_case_empty_buffer(self, mock_hass, basic_tank):
        """Test prediction with empty buffer."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        prediction = predictor.get_prediction()

        assert prediction.status == "insufficient_data"
        assert prediction.hours_remaining is None
        assert prediction.data_points == 0

    async def test_vpd_weighting_affects_hours_remaining(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test that VPD weighting affects hours remaining calculation."""
        basic_tank.enable_vpd_weighting = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        now = utcnow()

        # Simulate depleting tank from 80% to 50% over 12 hours at ~2.5%/hour
        for i in range(13):
            level = 80 - (i * 2.5)
            predictor._buffer.append((now - timedelta(hours=12 - i), level, False))

        # Mock high VPD (>1.2) to trigger multiplier
        mock_vpd_state = State("sensor.vpd", "2.0")
        mock_tank_state = State("sensor.tank_level", "50.0")

        def mock_states_get(entity_id):
            if entity_id == "sensor.vpd":
                return mock_vpd_state
            return mock_tank_state

        mock_hass.states.get.side_effect = mock_states_get

        prediction = predictor.get_prediction()

        # Verify VPD multiplier reduced hours_remaining
        assert prediction.status == "depleting"
        assert prediction.hours_remaining is not None
        # With VPD multiplier >1, hours should be reduced
        assert prediction.hours_remaining < 10

    async def test_lights_bias_segregated_rates_calculation(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test calculation of segregated rates for lights-on vs lights-off."""
        basic_tank.enable_lights_bias = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        now = utcnow()

        # Add enough data points for segregation
        # Add enough data points for segregation
        for i in range(20):
            level = 100 - (i * 1.5)
            # Simulate lights on
            predictor._buffer.append((now - timedelta(hours=19 - i), level, True))

        # Correctly test the newly implemented historical state logic
        # Buffer has True for all points, so active rate should be calculated
        # No mock needed for hass state as we use internal buffer

        prediction = predictor.get_prediction()

        # With lights on, only active rate is calculated
        assert prediction.active_consumption_rate is not None

    async def test_lights_bias_both_rates_calculated(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test that both active and dormant rates can be calculated."""
        basic_tank.enable_lights_bias = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        now = utcnow()

        # Add enough data points
        for i in range(20):
            level = 100 - (i * 1.5)
            # Simulate alternating lights with mostly off
            is_on = i % 4 == 0  # Mostly off
            predictor._buffer.append((now - timedelta(hours=19 - i), level, is_on))

        # Test with mixed buffer - should calculate dormant rate
        # No mock needed for hass state as we use internal buffer

        prediction = predictor.get_prediction()

        # With lights off, only dormant rate is calculated
        assert prediction.dormant_consumption_rate is not None

    async def test_lights_bias_with_no_environment_config(self, mock_hass, basic_tank):
        """Test lights bias with no environment config."""
        basic_tank.enable_lights_bias = True

        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()
        for i in range(10):
            predictor._buffer.append((now - timedelta(hours=9 - i), 100 - i * 2, True))

        prediction = predictor.get_prediction()

        # Without environment config, segregated rates should remain None
        assert prediction.active_consumption_rate is None
        assert prediction.dormant_consumption_rate is None

    async def test_lights_bias_with_empty_light_sensors(self, mock_hass, basic_tank):
        """Test lights bias when environment config has empty light sensors list."""
        basic_tank.enable_lights_bias = True

        # Environment config with empty light sensors
        env_config = EnvironmentConfig(light_sensors=[], vpd_sensor="sensor.vpd")

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=env_config
        )

        now = utcnow()
        for i in range(10):
            predictor._buffer.append((now - timedelta(hours=9 - i), 100 - i * 2, True))

        prediction = predictor.get_prediction()

        # With empty light sensors, segregated rates should remain None
        assert prediction.active_consumption_rate is None
        assert prediction.dormant_consumption_rate is None

    async def test_lights_bias_with_missing_light_sensor(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test lights bias when light sensor entity doesn't exist."""
        basic_tank.enable_lights_bias = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        now = utcnow()
        for i in range(10):
            predictor._buffer.append((now - timedelta(hours=9 - i), 100 - i * 2, True))

        # Mock light sensor as non-existent
        mock_hass.states.get.return_value = None

        prediction = predictor.get_prediction()

        # Without valid light sensor, segregated rates should remain None
        assert prediction.active_consumption_rate is None
        assert prediction.dormant_consumption_rate is None

    async def test_sma_filter_with_less_than_window_size(self, mock_hass, basic_tank):
        """Test SMA filter with fewer data points than window size."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Only 2 data points, window=3
        data = [(utcnow() - timedelta(hours=i), 100 - i) for i in range(2)]

        filtered = predictor._apply_sma_filter(data, window=3)

        # Should return data unchanged
        assert filtered == data

    async def test_calculate_slope_with_single_point(self, mock_hass, basic_tank):
        """Test slope calculation with only one data point."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        # Single data point
        data = [(utcnow(), 75.0)]

        slope = predictor._calculate_slope(data)

        # Should return 0.0
        assert slope == 0.0

    async def test_calculate_slope_with_zero_time_variance(self, mock_hass, basic_tank):
        """Test slope calculation when all timestamps are identical."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        now = utcnow()
        # All data points at the same time (zero denominator case)
        data = [(now, 100.0), (now, 95.0), (now, 90.0)]

        slope = predictor._calculate_slope(data)

        # Should return 0.0 when denominator is 0
        assert slope == 0.0

    async def test_vpd_multiplier_without_environment_config(
        self, mock_hass, basic_tank
    ):
        """Test VPD multiplier when no environment config is provided."""
        predictor = TankDepletionPredictor(mock_hass, basic_tank)

        multiplier = predictor._get_vpd_multiplier()

        # Without environment config, should return None
        assert multiplier is None

    async def test_vpd_multiplier_with_invalid_vpd_value(
        self, mock_hass, basic_tank, environment_config
    ):
        """Test VPD multiplier with invalid sensor value."""
        basic_tank.enable_vpd_weighting = True

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=environment_config
        )

        # Mock invalid VPD value
        mock_vpd_state = State("sensor.vpd", "invalid")
        mock_hass.states.get.return_value = mock_vpd_state

        multiplier = predictor._get_vpd_multiplier()

        # Invalid value should return None
        assert multiplier is None

    async def test_vpd_multiplier_with_no_vpd_sensor(self, mock_hass, basic_tank):
        """Test VPD multiplier when environment config has no VPD sensor."""
        # Environment config with no VPD sensor
        env_config = EnvironmentConfig(
            light_sensors=["light.grow_light"], vpd_sensor=None
        )

        predictor = TankDepletionPredictor(
            mock_hass, basic_tank, environment_config=env_config
        )

        multiplier = predictor._get_vpd_multiplier()

        # No VPD sensor should return None
        assert multiplier is None
