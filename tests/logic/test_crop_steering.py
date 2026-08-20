"""Tests for crop steering score calculation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.crop_steering import (
    calculate_crop_steering_score,
    get_crop_steering_state,
)
from custom_components.growspace_manager.domain.ec_state import runoff_score_component
from custom_components.growspace_manager.models import CropSteeringState, DrainReading

# Dryback value (absolute VWC points) inside the neutral band (8-15),
# used when a test exercises a non-dryback component.
NEUTRAL_DRYBACK = 10.0


# ---------------------------------------------------------------------------
# calculate_crop_steering_score
# ---------------------------------------------------------------------------


class TestCalculateCropSteeringScore:
    """Tests for calculate_crop_steering_score."""

    # Dryback component branches (absolute VWC points: peak - trough)

    @pytest.mark.parametrize(
        ("dryback_points", "expected"),
        [
            pytest.param(25.0, 0.4, id="high-dryback-generative"),
            pytest.param(18.0, 0.2, id="medium-high-dryback"),
            pytest.param(3.0, -0.4, id="low-dryback-vegetative"),
            pytest.param(6.0, -0.2, id="medium-low-dryback"),
            pytest.param(10.0, 0.0, id="neutral-dryback"),
            pytest.param(20.0, 0.2, id="boundary-20-medium-high"),
            pytest.param(15.0, 0.0, id="boundary-15-neutral"),
            pytest.param(8.0, 0.0, id="boundary-8-neutral"),
            pytest.param(5.0, -0.2, id="boundary-5-medium-low"),
        ],
    )
    def test_dryback_component(self, dryback_points: float, expected: float) -> None:
        """Dryback in absolute VWC points maps to the expected score band."""
        score = calculate_crop_steering_score(dryback_points, "stable")
        assert score == pytest.approx(expected)

    # EC trend component branches

    @pytest.mark.parametrize(
        ("ec_trend", "expected"),
        [
            pytest.param("rising", 0.3, id="rising"),
            pytest.param("falling", -0.3, id="falling"),
            pytest.param("stable", 0.0, id="stable"),
            pytest.param(None, 0.0, id="unavailable-neutral"),
        ],
    )
    def test_ec_trend_component(self, ec_trend: str | None, expected: float) -> None:
        """EC trend direction maps to the expected score contribution."""
        score = calculate_crop_steering_score(NEUTRAL_DRYBACK, ec_trend)
        assert score == pytest.approx(expected)

    # Shot count component branches

    @pytest.mark.parametrize(
        ("shot_count", "expected"),
        [
            pytest.param(None, 0.0, id="none-unknown"),
            pytest.param(0, 0.3, id="zero-shots-generative"),
            pytest.param(3, 0.3, id="three-shots-generative"),
            pytest.param(4, 0.0, id="four-shots-neutral"),
            pytest.param(5, 0.0, id="five-shots-neutral"),
            pytest.param(6, 0.0, id="six-shots-neutral"),
            pytest.param(7, 0.0, id="seven-shots-neutral"),
            pytest.param(8, -0.3, id="eight-shots-vegetative"),
            pytest.param(20, -0.3, id="many-shots-vegetative"),
        ],
    )
    def test_shot_count_component(
        self, shot_count: int | None, expected: float
    ) -> None:
        """Shot count maps to the expected score contribution."""
        score = calculate_crop_steering_score(
            NEUTRAL_DRYBACK, "stable", shot_count=shot_count
        )
        assert score == pytest.approx(expected)

    # Shared EC axis: runoff fill vs pore trend (ADR-0016)

    @pytest.mark.parametrize(
        ("ec_trend", "runoff_bucket", "expected"),
        [
            # Trend absent/stable → runoff fills the axis.
            pytest.param(None, 0.3, 0.3, id="no-trend-runoff-fills-generative"),
            pytest.param("stable", -0.2, -0.2, id="stable-trend-runoff-fills-veg"),
            pytest.param(None, 0.0, 0.0, id="no-trend-no-runoff-neutral"),
            # Measured trend wins; runoff is ignored even when it disagrees.
            pytest.param("rising", -0.3, 0.3, id="rising-trend-overrides-runoff"),
            pytest.param("falling", 0.3, -0.3, id="falling-trend-overrides-runoff"),
        ],
    )
    def test_shared_ec_axis(
        self, ec_trend: str | None, runoff_bucket: float, expected: float
    ) -> None:
        """Pore trend wins the shared EC axis; runoff fills only when absent/stable."""
        score = calculate_crop_steering_score(
            NEUTRAL_DRYBACK, ec_trend, runoff_delta_bucket=runoff_bucket
        )
        assert score == pytest.approx(expected)

    def test_runoff_fill_never_exceeds_ec_axis_budget(self) -> None:
        """Runoff fills the same ±0.3 axis — it cannot stack on a pore trend.

        High dryback (+0.4) + rising trend (+0.3) maxes the EC axis; a positive
        runoff bucket adds nothing because the trend already won the axis.
        """
        with_runoff = calculate_crop_steering_score(
            25.0, "rising", runoff_delta_bucket=0.3
        )
        without_runoff = calculate_crop_steering_score(25.0, "rising")
        assert with_runoff == pytest.approx(without_runoff)

    # Clamping and combinations

    def test_score_clamped_at_positive_one(self) -> None:
        """Maximum generative scenario is clamped to 1.0."""
        # high dryback (+0.4) + rising EC (+0.3) + low shots (+0.3) = 1.0
        score = calculate_crop_steering_score(25.0, "rising", shot_count=1)
        assert score == pytest.approx(1.0)

    def test_score_clamped_at_negative_one(self) -> None:
        """Maximum vegetative scenario is clamped to -1.0."""
        # low dryback (-0.4) + falling EC (-0.3) + many shots (-0.3) = -1.0
        score = calculate_crop_steering_score(3.0, "falling", shot_count=10)
        assert score == pytest.approx(-1.0)

    def test_combined_mixed_signals(self) -> None:
        """Mixed signals produce intermediate score."""
        # high dryback (+0.4) + falling EC (-0.3) = 0.1
        score = calculate_crop_steering_score(25.0, "falling")
        assert score == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# runoff_score_component — the ratified bucket table (ADR-0016 §3)
# ---------------------------------------------------------------------------


def _drain(feed_ec: float, drain_ec: float) -> DrainReading:
    """Build a drain reading with the given feed/drain EC."""
    return DrainReading(timestamp="t", feed_ec=feed_ec, drain_ec=drain_ec)


class TestRunoffScoreComponent:
    """The sustained Feed-to-Runoff EC Delta bucket (Δmax = max_ec_delta = 0.7)."""

    @pytest.mark.parametrize(
        ("deltas", "expected"),
        [
            # Δmax 0.7 → tiers at ±0.7 / ±1.4. Bucketed on the weakest reading.
            pytest.param([1.5, 1.6, 2.0], 0.3, id="all-ge-2dmax-strong-generative"),
            pytest.param([0.8, 1.0, 1.3], 0.2, id="all-ge-dmax-moderate-generative"),
            pytest.param([0.8, 0.5, 1.0], 0.0, id="one-below-dmax-not-sustained"),
            pytest.param([-0.8, -1.0, -1.3], -0.2, id="all-le-negdmax-moderate-veg"),
            pytest.param([-1.5, -1.6, -2.0], -0.3, id="all-le-neg2dmax-strong-veg"),
            pytest.param([1.0, -1.0, 1.2], 0.0, id="straddles-zero-neutral"),
            pytest.param([0.1, 0.2, 0.3], 0.0, id="within-band-neutral"),
        ],
    )
    def test_bucket(self, deltas: list[float], expected: float) -> None:
        """The weakest agreeing reading in the tail sets the bucket."""
        readings = [_drain(2.0, 2.0 + d) for d in deltas]
        assert runoff_score_component(readings, max_ec_delta=0.7) == pytest.approx(
            expected
        )

    def test_only_tail_considered(self) -> None:
        """Older readings outside the last 3 do not affect the bucket."""
        # First two are diluting; the last three all stack ≥ 2·Δmax → +0.3.
        readings = [_drain(2.0, 1.0), _drain(2.0, 1.0)] + [
            _drain(2.0, 3.5) for _ in range(3)
        ]
        assert runoff_score_component(readings, max_ec_delta=0.7) == pytest.approx(0.3)

    def test_too_few_readings_is_neutral(self) -> None:
        """A single reading is never 'sustained' → 0.0."""
        assert runoff_score_component([_drain(2.0, 4.0)], max_ec_delta=0.7) == 0.0
        assert runoff_score_component([], max_ec_delta=0.7) == 0.0

    def test_non_positive_max_ec_delta_is_neutral(self) -> None:
        """A non-positive Δmax disables the component (no division-by-zero tiers)."""
        readings = [_drain(2.0, 4.0), _drain(2.0, 4.0)]
        assert runoff_score_component(readings, max_ec_delta=0.0) == 0.0


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
    declared_intent: object | None = None,
) -> MagicMock:
    """Build a minimal coordinator mock for crop steering tests."""
    coordinator = MagicMock()

    # Growspace
    growspace = MagicMock()
    growspace.irrigation_strategy.enabled = irrigation_enabled
    growspace.irrigation_strategy.target_vwc_percent = target_vwc
    growspace.irrigation_strategy.maintenance_dryback_percent = maintenance_dryback
    growspace.irrigation_strategy.declared_steering_mode = declared_intent
    growspace.environment_config.soil_moisture_sensor = soil_moisture_sensor
    # Real drain values so the runoff fill (ADR-0016) reads cleanly; default to
    # no readings → runoff contributes 0.0 unless a test sets them.
    growspace.drain_config.readings = []
    growspace.drain_config.max_ec_delta = 0.7
    coordinator.growspaces.get.return_value = growspace

    # Irrigation coordinator
    if has_vwc_coord:
        coordinator.services.growspaces.get_irrigation_coordinator.return_value = (
            MagicMock()
        )
    else:
        coordinator.services.growspaces.get_irrigation_coordinator.return_value = None

    # HA state
    state_mock = MagicMock()
    state_mock.state = sensor_state
    coordinator.hass.states.get.return_value = state_mock

    # No SubstrateTracker by default → exercise the target-derived fallback.
    coordinator.services.growspaces.get_substrate_tracker.return_value = None

    return coordinator


class TestGetCropSteeringState:
    """Tests for get_crop_steering_state."""

    def test_returns_none_when_growspace_missing(self) -> None:
        """Returns None if growspace does not exist."""
        coordinator = MagicMock()
        coordinator.growspaces.get.return_value = None
        result = get_crop_steering_state(coordinator, "missing")
        assert result is None

    def test_returns_none_when_irrigation_disabled(self) -> None:
        """Returns None if irrigation strategy is not enabled."""
        coordinator = _make_coordinator(irrigation_enabled=False)
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is None

    def test_returns_empty_state_when_no_vwc_coord(self) -> None:
        """Returns default CropSteeringState when no VWC coordinator is active."""
        coordinator = _make_coordinator(has_vwc_coord=False)
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0
        assert result.dryback_percent == 0.0

    def test_returns_empty_state_when_no_soil_sensor(self) -> None:
        """Returns default CropSteeringState when soil moisture sensor is not configured."""
        coordinator = _make_coordinator(soil_moisture_sensor=None)
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    @pytest.mark.parametrize(
        "sensor_state",
        [
            pytest.param("unavailable", id="unavailable"),
            pytest.param("unknown", id="unknown"),
            pytest.param("not_a_number", id="non-numeric"),
        ],
    )
    def test_returns_empty_state_when_sensor_unusable(self, sensor_state: str) -> None:
        """Returns default CropSteeringState when the sensor state is unusable."""
        coordinator = _make_coordinator(sensor_state=sensor_state)
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_empty_state_when_sensor_state_missing(self) -> None:
        """Returns default CropSteeringState when hass.states.get returns None."""
        coordinator = _make_coordinator()
        coordinator.hass.states.get.return_value = None
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.score == 0.0

    def test_returns_full_state_with_valid_sensor(self) -> None:
        """Returns populated CropSteeringState when all data is available.

        Dryback is absolute VWC points: peak 55, trough 45 yields 10.0,
        which sits in the neutral band (8-15) so the score is 0.0.
        """
        # current_vwc=45, target=55 → peak=55, trough=min(45, 55-5)=45
        coordinator = _make_coordinator(
            sensor_state="45.0",
            target_vwc=55.0,
            maintenance_dryback=5.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert isinstance(result, CropSteeringState)
        assert result.peak_vwc == pytest.approx(55.0)
        assert result.trough_vwc == pytest.approx(45.0)
        assert result.dryback_percent == pytest.approx(10.0)
        # No pore-EC sensors / tracker → trend unavailable, never "stable".
        assert result.ec_trend is None
        assert result.ec_trend_available is False
        assert result.score == pytest.approx(0.0)

    def test_peak_vwc_uses_current_when_above_target(self) -> None:
        """Peak VWC is current_vwc when it exceeds target_vwc."""
        # current=70 > target=55 → peak=70, trough=min(70,55-5)=50
        # dryback = 70 - 50 = 20.0 absolute points → +0.2 (mildly generative)
        coordinator = _make_coordinator(
            sensor_state="70.0",
            target_vwc=55.0,
            maintenance_dryback=5.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.peak_vwc == pytest.approx(70.0)
        assert result.trough_vwc == pytest.approx(50.0)
        assert result.dryback_percent == pytest.approx(20.0)
        assert result.score == pytest.approx(0.2)

    def test_dryback_zero_when_no_spread(self) -> None:
        """Dryback is 0.0 absolute points when peak and trough coincide."""
        coordinator = _make_coordinator(
            sensor_state="0.0",
            target_vwc=0.0,
            maintenance_dryback=0.0,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.dryback_percent == pytest.approx(0.0)

    def test_uses_measured_tracker_values_over_synthetic(self) -> None:
        """Measured peak/trough/dryback from the tracker replace the synthetic estimate."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        tracker = MagicMock()
        # Measured high dryback (60 - 38 = 22.0) → +0.4; 2 shots (<=3) → +0.3.
        tracker.get_measured_peak_trough.return_value = (60.0, 38.0, 22.0)
        tracker.get_shot_count_today.return_value = 2
        coordinator.services.growspaces.get_substrate_tracker.return_value = tracker

        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.peak_vwc == pytest.approx(60.0)
        assert result.trough_vwc == pytest.approx(38.0)
        assert result.dryback_percent == pytest.approx(22.0)
        # High measured dryback + few shots drives a generative score.
        assert result.score == pytest.approx(0.7)

    def test_measured_ec_trend_rising_feeds_score(self) -> None:
        """A measured rising EC trend adds +0.3 and is reported in the state."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        tracker = MagicMock()
        tracker.get_measured_peak_trough.return_value = None
        tracker.get_shot_count_today.return_value = None
        tracker.get_ec_trend.return_value = {
            "trend": "rising",
            "day_start_ec": 2.0,
            "current_ec": 2.8,
            "delta": 0.8,
        }
        coordinator.services.growspaces.get_substrate_tracker.return_value = tracker

        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.ec_trend == "rising"
        assert result.ec_trend_available is True
        assert result.ec_day_start == pytest.approx(2.0)
        assert result.ec_current == pytest.approx(2.8)
        # neutral dryback (10.0) + rising EC (+0.3) → 0.3
        assert result.score == pytest.approx(0.3)

    def test_unavailable_ec_trend_keeps_ec_component_neutral(self) -> None:
        """No pore-EC sensors → trend None, unavailable, EC contributes zero."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        tracker = MagicMock()
        tracker.get_measured_peak_trough.return_value = None
        tracker.get_shot_count_today.return_value = None
        tracker.get_ec_trend.return_value = None
        coordinator.services.growspaces.get_substrate_tracker.return_value = tracker

        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.ec_trend is None
        assert result.ec_trend_available is False
        assert result.ec_day_start is None
        assert result.ec_current is None
        # neutral dryback (10.0) + unavailable EC (0) → 0.0
        assert result.score == pytest.approx(0.0)

    def test_runoff_fills_ec_axis_when_no_trend(self) -> None:
        """Without a pore-EC trend, a sustained runoff delta fills the EC axis."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        tracker = MagicMock()
        tracker.get_measured_peak_trough.return_value = None
        tracker.get_shot_count_today.return_value = None
        tracker.get_ec_trend.return_value = None  # no pore-EC sensors
        coordinator.services.growspaces.get_substrate_tracker.return_value = tracker
        # Δmax 0.7; two readings each delta 1.0 (≥ Δmax) → +0.2 fill.
        gs = coordinator.growspaces.get.return_value
        gs.drain_config.readings = [_drain(2.0, 3.0), _drain(2.0, 3.0)]

        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        # neutral dryback (10.0) + runoff fill (+0.2) → 0.2
        assert result.score == pytest.approx(0.2)
        assert result.runoff_score == pytest.approx(0.2)

    def test_pore_trend_overrides_runoff_and_zeroes_runoff_score(self) -> None:
        """A measured trend wins the axis; the reported runoff_score is then 0.0."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        tracker = MagicMock()
        tracker.get_measured_peak_trough.return_value = None
        tracker.get_shot_count_today.return_value = None
        tracker.get_ec_trend.return_value = {
            "trend": "rising",
            "day_start_ec": 2.0,
            "current_ec": 2.8,
            "delta": 0.8,
        }
        coordinator.services.growspaces.get_substrate_tracker.return_value = tracker
        # Runoff would say diluting (−0.2), but the rising trend wins the axis.
        gs = coordinator.growspaces.get.return_value
        gs.drain_config.readings = [_drain(3.0, 2.0), _drain(3.0, 2.0)]

        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        # neutral dryback (10.0) + rising trend (+0.3); runoff ignored → 0.3
        assert result.score == pytest.approx(0.3)
        assert result.runoff_score == pytest.approx(0.0)

    def test_measured_classification_derived_from_score(self) -> None:
        """The state carries the measured classification bucket for the score."""
        # current=70 > target=55, dryback 20 → score 0.2 → balanced bucket.
        coordinator = _make_coordinator(sensor_state="70.0", target_vwc=55.0)
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.measured_classification == "balanced"

    def test_intent_deviation_against_declared_mode(self) -> None:
        """Deviation compares the measurement against the declared mode."""
        from custom_components.growspace_manager.const import SteeringMode

        # Measured balanced (score 0.2) vs declared generative → more_vegetative.
        coordinator = _make_coordinator(
            sensor_state="70.0",
            target_vwc=55.0,
            declared_intent=SteeringMode.GENERATIVE,
        )
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.measured_classification == "balanced"
        assert result.intent_deviation == "more_vegetative"

    def test_intent_deviation_none_when_undeclared(self) -> None:
        """No declared intent → deviation is None."""
        coordinator = _make_coordinator(sensor_state="45.0", target_vwc=55.0)
        result = get_crop_steering_state(coordinator, "tent1")
        assert result is not None
        assert result.intent_deviation is None
