"""Tests for crop steering score calculation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.crop_steering import (
    calculate_crop_steering_score,
    get_crop_steering_state,
)
from custom_components.growspace_manager.models import CropSteeringState


# ---------------------------------------------------------------------------
# calculate_crop_steering_score
# ---------------------------------------------------------------------------


class TestCalculateCropSteeringScore:
    """Tests for calculate_crop_steering_score."""

    # Dryback component branches

    def test_high_dryback_generative(self):
        """Dryback >30% adds +0.4 (generative)."""
        score = calculate_crop_steering_score(35.0, "stable")
        assert score == pytest.approx(0.4)

    def test_medium_high_dryback(self):
        """Dryback >20% and <=30% adds +0.2."""
        score = calculate_crop_steering_score(25.0, "stable")
        assert score == pytest.approx(0.2)

    def test_low_dryback_vegetative(self):
        """Dryback <10% subtracts 0.4 (vegetative)."""
        score = calculate_crop_steering_score(5.0, "stable")
        assert score == pytest.approx(-0.4)

    def test_medium_low_dryback(self):
        """Dryback >=10% and <15% subtracts 0.2."""
        score = calculate_crop_steering_score(12.0, "stable")
        assert score == pytest.approx(-0.2)

    def test_neutral_dryback(self):
        """Dryback between 15% and 20% (inclusive) contributes 0."""
        score = calculate_crop_steering_score(17.0, "stable")
        assert score == pytest.approx(0.0)

    def test_dryback_boundary_30(self):
        """Dryback exactly 30% falls into medium-high bucket (+0.2, not +0.4)."""
        score = calculate_crop_steering_score(30.0, "stable")
        assert score == pytest.approx(0.2)

    def test_dryback_boundary_20(self):
        """Dryback exactly 20% falls into neutral bucket (0)."""
        score = calculate_crop_steering_score(20.0, "stable")
        assert score == pytest.approx(0.0)

    def test_dryback_boundary_10(self):
        """Dryback exactly 10% falls into the medium-low bucket (-0.2), not -0.4."""
        # < 10 is false for exactly 10, so it falls into the elif < 15 branch.
        score = calculate_crop_steering_score(10.0, "stable")
        assert score == pytest.approx(-0.2)

    def test_dryback_boundary_15(self):
        """Dryback exactly 15% falls into neutral bucket (0), not -0.2."""
        score = calculate_crop_steering_score(15.0, "stable")
        assert score == pytest.approx(0.0)

    # EC trend component branches

    def test_ec_trend_rising(self):
        """Rising EC adds +0.3."""
        score = calculate_crop_steering_score(17.0, "rising")
        assert score == pytest.approx(0.3)

    def test_ec_trend_falling(self):
        """Falling EC subtracts 0.3."""
        score = calculate_crop_steering_score(17.0, "falling")
        assert score == pytest.approx(-0.3)

    def test_ec_trend_stable(self):
        """Stable EC contributes 0."""
        score = calculate_crop_steering_score(17.0, "stable")
        assert score == pytest.approx(0.0)

    # Shot count component branches

    def test_shot_count_none(self):
        """No shot count does not affect score."""
        score_with = calculate_crop_steering_score(17.0, "stable", shot_count=5)
        score_without = calculate_crop_steering_score(17.0, "stable", shot_count=None)
        assert score_without == pytest.approx(0.0)
        assert score_with == pytest.approx(0.0)  # 5 shots is in neutral band too

    def test_shot_count_low_generative(self):
        """<=3 shots adds +0.3 (generative)."""
        score = calculate_crop_steering_score(17.0, "stable", shot_count=3)
        assert score == pytest.approx(0.3)

    def test_shot_count_zero(self):
        """0 shots is <=3, adds +0.3."""
        score = calculate_crop_steering_score(17.0, "stable", shot_count=0)
        assert score == pytest.approx(0.3)

    def test_shot_count_high_vegetative(self):
        """>=8 shots subtracts 0.3 (vegetative)."""
        score = calculate_crop_steering_score(17.0, "stable", shot_count=8)
        assert score == pytest.approx(-0.3)

    def test_shot_count_very_high(self):
        """Many shots (>8) subtracts 0.3."""
        score = calculate_crop_steering_score(17.0, "stable", shot_count=20)
        assert score == pytest.approx(-0.3)

    def test_shot_count_neutral_band(self):
        """4-7 shots do not affect score."""
        for shots in (4, 5, 6, 7):
            score = calculate_crop_steering_score(17.0, "stable", shot_count=shots)
            assert score == pytest.approx(0.0), f"shot_count={shots} should be neutral"

    # Clamping

    def test_score_clamped_at_positive_one(self):
        """Maximum generative scenario is clamped to 1.0."""
        # high dryback (+0.4) + rising EC (+0.3) + low shots (+0.3) = 1.0
        score = calculate_crop_steering_score(35.0, "rising", shot_count=1)
        assert score == pytest.approx(1.0)

    def test_score_clamped_at_negative_one(self):
        """Maximum vegetative scenario is clamped to -1.0."""
        # low dryback (-0.4) + falling EC (-0.3) + many shots (-0.3) = -1.0
        score = calculate_crop_steering_score(5.0, "falling", shot_count=10)
        assert score == pytest.approx(-1.0)

    def test_combined_mixed_signals(self):
        """Mixed signals produce intermediate score."""
        # high dryback (+0.4) + falling EC (-0.3) = 0.1
        score = calculate_crop_steering_score(35.0, "falling")
        assert score == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# get_crop_steering_state
# ---------------------------------------------------------------------------


def _make_coordinator(
    *,
    growspace_id: str = "tent1",
    irrigation_enabled: bool = True,
    has_vwc_coord: bool = True,
    soil_moisture_sensor: str | None = "sensor.soil",
    sensor_state: str = "45.0",
    target_vwc: float = 55.0,
    maintenance_dryback: float = 5.0,
) -> MagicMock:
    """Build a minimal coordinator mock for crop steering tests."""
    coordinator = MagicMock()

    # Growspace
    growspace = MagicMock()
    growspace.irrigation_strategy.enabled = irrigation_enabled
    growspace.irrigation_strategy.target_vwc_percent = target_vwc
    growspace.irrigation_strategy.maintenance_dryback_percent = maintenance_dryback
    growspace.environment_config.soil_moisture_sensor = soil_moisture_sensor
    coordinator.growspaces.get.return_value = growspace

    # Irrigation coordinator
    if has_vwc_coord:
        coordinator._subsystem_manager.irrigation_coordinators.get.return_value = MagicMock()
    else:
        coordinator._subsystem_manager.irrigation_coordinators.get.return_value = None

    # HA state
    state_mock = MagicMock()
    state_mock.state = sensor_state
    coordinator.hass.states.get.return_value = state_mock

    return coordinator


class TestGetCropSteeringState:
    """Tests for get_crop_steering_state."""

    def test_returns_none_when_growspace_missing(self):
        """Returns None if growspace does not exist."""
        coordinator = MagicMock()
        coordinator.growspaces.get.return_value = None
        result = get_crop_steering_state(coordinator, "missing")
        assert result is None

    def test_returns_none_when_irrigation_disabled(self):
        """Returns None if irrigation strategy is not enabled."""
        coordinator = _make_coordinator(irrigation_enabled=False)
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is None

    def test_returns_empty_state_when_no_vwc_coord(self):
        """Returns default CropSteeringState when no VWC coordinator is active."""
        coordinator = _make_coordinator(has_vwc_coord=False)
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_no_soil_sensor(self):
        """Returns default CropSteeringState when soil moisture sensor is not configured."""
        coordinator = _make_coordinator(soil_moisture_sensor=None)
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_sensor_unavailable(self):
        """Returns default CropSteeringState when sensor state is 'unavailable'."""
        coordinator = _make_coordinator(sensor_state="unavailable")
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_sensor_unknown(self):
        """Returns default CropSteeringState when sensor state is 'unknown'."""
        coordinator = _make_coordinator(sensor_state="unknown")
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_sensor_state_missing(self):
        """Returns default CropSteeringState when hass.states.get returns None."""
        coordinator = _make_coordinator()
        coordinator.hass.states.get.return_value = None
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_sensor_not_numeric(self):
        """Returns default CropSteeringState when sensor state is non-numeric."""
        coordinator = _make_coordinator(sensor_state="not_a_number")
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_full_state_with_valid_sensor(self):
        """Returns populated CropSteeringState when all data is available."""
        # current_vwc=45, target=55 → peak=55, trough=min(45, 55-5)=min(45,50)=45
        # dryback = (55-45)/55*100 ≈ 18.18%  → neutral band, score=0.0
        coordinator = _make_coordinator(
            sensor_state="45.0",
            target_vwc=55.0,
            maintenance_dryback=5.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.peak_vwc == pytest.approx(55.0)
        assert result.trough_vwc == pytest.approx(45.0)
        assert result.dryback_percent == pytest.approx((55.0 - 45.0) / 55.0 * 100)
        assert result.ec_trend == "stable"
        assert result.score == pytest.approx(0.0)

    def test_peak_vwc_uses_current_when_above_target(self):
        """Peak VWC is current_vwc when it exceeds target_vwc."""
        # current=70 > target=55 → peak=70, trough=min(70,55-5)=50
        coordinator = _make_coordinator(
            sensor_state="70.0",
            target_vwc=55.0,
            maintenance_dryback=5.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.peak_vwc == pytest.approx(70.0)
        assert result.trough_vwc == pytest.approx(50.0)

    def test_dryback_zero_when_peak_is_zero(self):
        """Dryback percent is 0.0 when peak VWC is 0 (no division by zero)."""
        coordinator = _make_coordinator(
            sensor_state="0.0",
            target_vwc=0.0,
            maintenance_dryback=0.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.dryback_percent == pytest.approx(0.0)
