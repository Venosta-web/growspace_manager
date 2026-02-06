"""Tank depletion predictor for irrigation tanks.

This module implements a time-series analysis system that predicts when an
irrigation tank will reach its warning level. It uses a sliding window linear
regression approach to calculate depletion rates while accounting for sensor
noise and environmental factors.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from .models import EnvironmentConfig, IrrigationTank

_LOGGER = logging.getLogger(__name__)

# Constants
DEFAULT_WINDOW_HOURS = 72
DEADBAND_THRESHOLD = 0.1  # %/hour - ignore slope changes below this
VPD_WEIGHTING_BASE = 1.2  # kPa threshold for VPD multiplier
MIN_DATA_POINTS = 4  # Minimum points needed for regression


@dataclass(slots=True)
class TankPrediction:
    """Result of a tank depletion prediction."""

    hours_remaining: float | None
    status: str  # "depleting", "refilling", "static", "insufficient_data"
    slope_pct_per_hour: float | None
    daily_usage_rate: float | None
    active_consumption_rate: float | None
    dormant_consumption_rate: float | None
    data_points: int


class TankDepletionPredictor:
    """Predicts time until tank reaches refill threshold using sliding window regression.

    This predictor maintains a rolling buffer of tank level readings and uses
    Ordinary Least Squares (OLS) linear regression to calculate the depletion
    slope. It supports optional features like lights-on/off rate segregation
    and VPD-based consumption weighting.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        tank: IrrigationTank,
        window_hours: int = DEFAULT_WINDOW_HOURS,
        environment_config: EnvironmentConfig | None = None,
    ) -> None:
        """Initialize the tank depletion predictor.

        Args:
            hass: Home Assistant instance
            tank: IrrigationTank configuration with sensor_entity and warning_level
            window_hours: Size of rolling window in hours (default 72)
            environment_config: Optional environment config for light sensors and VPD
        """
        self.hass = hass
        self.tank = tank
        self.window_hours = window_hours
        self.environment_config = environment_config

        # Rolling buffer: (timestamp, level_pct)
        self._buffer: deque[tuple[datetime, float]] = deque(
            maxlen=window_hours * 4  # 4 readings per hour max
        )

        # Cache for performance
        self._last_prediction: TankPrediction | None = None
        self._last_update: datetime | None = None

        # Segregated rates for lights-on/off
        self._active_rate: float | None = None
        self._dormant_rate: float | None = None

    async def async_update(self) -> None:
        """Fetch latest tank level reading and update internal buffer."""
        state = self.hass.states.get(self.tank.sensor_entity)

        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug(
                "Tank sensor %s unavailable, skipping update", self.tank.sensor_entity
            )
            return

        try:
            level = float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid tank level from %s: %s",
                self.tank.sensor_entity,
                state.state,
            )
            return

        now = utcnow()
        self._buffer.append((now, level))
        self._last_update = now

        # Expire old data points
        cutoff_time = now - timedelta(hours=self.window_hours)
        while self._buffer and self._buffer[0][0] < cutoff_time:
            self._buffer.popleft()

        _LOGGER.debug(
            "Updated tank %s buffer: %d points, level=%.1f%%",
            self.tank.name,
            len(self._buffer),
            level,
        )

    def get_prediction(self) -> TankPrediction:
        """Calculate hours remaining until refill threshold.

        Returns:
            TankPrediction with status, hours remaining, and consumption rates
        """
        if len(self._buffer) < MIN_DATA_POINTS:
            return TankPrediction(
                hours_remaining=None,
                status="insufficient_data",
                slope_pct_per_hour=None,
                daily_usage_rate=None,
                active_consumption_rate=None,
                dormant_consumption_rate=None,
                data_points=len(self._buffer),
            )

        # Apply SMA filter to reduce noise
        filtered_data = self._apply_sma_filter(list(self._buffer))

        # Calculate slope using OLS
        slope = self._calculate_slope(filtered_data)

        # Determine status
        status = self._determine_status(slope)

        # Calculate hours remaining if depleting
        current_level = self._buffer[-1][1]
        hours_remaining = None

        if status == "depleting" and slope < 0:
            # Hours = (current_level - threshold) / |slope|
            distance_to_threshold = current_level - self.tank.warning_level
            hours_remaining = distance_to_threshold / abs(slope)

            # Apply VPD weighting if enabled
            if self.tank.enable_vpd_weighting and self.environment_config:
                vpd_multiplier = self._get_vpd_multiplier()
                if vpd_multiplier:
                    hours_remaining /= vpd_multiplier

        # Calculate daily usage rate
        daily_usage_rate = abs(slope) * 24 if slope else None

        # Calculate segregated rates if lights bias enabled
        if self.tank.enable_lights_bias and self.environment_config:
            self._calculate_segregated_rates()

        return TankPrediction(
            hours_remaining=hours_remaining,
            status=status,
            slope_pct_per_hour=slope,
            daily_usage_rate=daily_usage_rate,
            active_consumption_rate=self._active_rate,
            dormant_consumption_rate=self._dormant_rate,
            data_points=len(self._buffer),
        )

    def _apply_sma_filter(
        self, data: list[tuple[datetime, float]], window: int = 3
    ) -> list[tuple[datetime, float]]:
        """Apply Simple Moving Average filter to reduce noise.

        Args:
            data: List of (timestamp, level) tuples
            window: SMA window size (default 3)

        Returns:
            Smoothed data points
        """
        if len(data) < window:
            return data

        filtered = []
        for i in range(len(data)):
            start_idx = max(0, i - window + 1)
            window_values = [val for _, val in data[start_idx : i + 1]]
            avg_value = sum(window_values) / len(window_values)
            filtered.append((data[i][0], avg_value))

        return filtered

    def _calculate_slope(self, data: list[tuple[datetime, float]]) -> float:
        """Calculate slope using Ordinary Least Squares regression.

        OLS formula: slope = Σ(x-x̄)(y-ȳ) / Σ(x-x̄)²

        Args:
            data: List of (timestamp, level) tuples

        Returns:
            Slope in percentage points per hour
        """
        if len(data) < 2:
            return 0.0

        # Convert timestamps to hours since first reading
        first_time = data[0][0]
        x_values = [(ts - first_time).total_seconds() / 3600 for ts, _ in data]
        y_values = [level for _, level in data]

        # Calculate means
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(y_values) / len(y_values)

        # Calculate slope
        numerator = sum(
            (x - x_mean) * (y - y_mean)
            for x, y in zip(x_values, y_values, strict=False)
        )
        denominator = sum((x - x_mean) ** 2 for x in x_values)

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def _determine_status(self, slope: float) -> str:
        """Determine tank status based on slope with deadband.

        Args:
            slope: Current slope in %/hour

        Returns:
            Status string: "depleting", "refilling", or "static"
        """
        if slope < -DEADBAND_THRESHOLD:
            return "depleting"
        if slope > DEADBAND_THRESHOLD:
            return "refilling"
        return "static"

    def _get_vpd_multiplier(self) -> float | None:
        """Calculate VPD-based consumption multiplier.

        Returns:
            Multiplier (1.0-2.0) or None if VPD unavailable
        """
        if not self.environment_config or not self.environment_config.vpd_sensor:
            return None

        vpd_state = self.hass.states.get(self.environment_config.vpd_sensor)
        if not vpd_state or vpd_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        try:
            vpd = float(vpd_state.state)
        except (ValueError, TypeError):
            return None

        # Apply multiplier for high VPD (increased transpiration)
        if vpd > VPD_WEIGHTING_BASE:
            return 1 + (vpd - VPD_WEIGHTING_BASE) * 0.3

        return 1.0

    def _calculate_segregated_rates(self) -> None:
        """Calculate separate consumption rates for lights-on vs lights-off.

        Updates self._active_rate and self._dormant_rate.
        """
        if not self.environment_config or not self.environment_config.light_sensors:
            return

        light_entity = self.environment_config.light_sensors[0]
        light_state = self.hass.states.get(light_entity)

        if not light_state:
            return

        # Segregate buffer by light state
        lights_on_data = []
        lights_off_data = []

        for timestamp, level in self._buffer:
            # Get historical light state (simplified - uses current state)
            # In production, would need to query history for exact state at timestamp
            is_on = light_state.state == "on"

            if is_on:
                lights_on_data.append((timestamp, level))
            else:
                lights_off_data.append((timestamp, level))

        # Calculate slopes for each period
        if len(lights_on_data) >= MIN_DATA_POINTS:
            active_slope = self._calculate_slope(lights_on_data)
            self._active_rate = abs(active_slope) * 24

        if len(lights_off_data) >= MIN_DATA_POINTS:
            dormant_slope = self._calculate_slope(lights_off_data)
            self._dormant_rate = abs(dormant_slope) * 24
