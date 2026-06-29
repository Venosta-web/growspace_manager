"""Tests for the ShotComposer seam (domain/shot_composer.py).

The composer is a stateful controller, so these drive it with deterministic
``observe``/``reset``/``compose`` sequences and plain ``FeedbackTuning`` values —
no coordinator, no Home Assistant. The feedback-math cases were migrated here
from ``tests/integration/test_vwc_irrigation_coordinator.py`` (where they had to
poke private coordinator attributes through a full fixture); ``compose`` is
covered directly for the first time.
"""

from custom_components.growspace_manager.domain.shot_composer import (
    FeedbackTuning,
    ShotComposer,
)

# A timestamp is opaque to the composer (it only stores it), so a fixed string
# keeps the composition assertions deterministic.
_TS = "2023-01-01T12:00:00+00:00"


def _tuning(
    *,
    enabled: bool = True,
    target_vwc_percent: float = 50.0,
    aggressiveness: float = 1.0,
    recovery: float = 0.1,
    size_floor: float = 0.5,
    interval_ceiling: float = 1.5,
) -> FeedbackTuning:
    """Build a FeedbackTuning with the strategy defaults, overridable per case."""
    return FeedbackTuning(
        enabled=enabled,
        target_vwc_percent=target_vwc_percent,
        aggressiveness=aggressiveness,
        recovery=recovery,
        size_floor=size_floor,
        interval_ceiling=interval_ceiling,
    )


def test_observe_overshoot_shrinks_size_factor() -> None:
    """Overshooting the target reduces the size factor, clamped at the floor."""
    # Target delta 10.0, actual delta 15.0, ratio 1.5 -> factor drops by 0.5.
    composer = ShotComposer()
    composer.observe(40.0, 55.0, _tuning())
    assert composer.size_factor == 0.5

    # A further overshoot is clamped at the 0.5 floor, never below.
    composer.observe(40.0, 55.0, _tuning())
    assert composer.size_factor == 0.5


def test_observe_undershoot_recovers_size_factor() -> None:
    """Undershooting/meeting the target recovers the size factor toward 1.0."""
    # Target delta 10.0, actual delta 5.0, ratio 0.5 -> recover by 0.1 * 0.5 = 0.05.
    composer = ShotComposer()
    composer.size_factor = 0.6
    composer.observe(40.0, 45.0, _tuning())
    assert abs(composer.size_factor - 0.65) < 1e-6

    # Recovery clamps at nominal 1.0, never above.
    composer.size_factor = 0.98
    composer.observe(40.0, 45.0, _tuning())
    assert composer.size_factor == 1.0


def test_observe_guards_leave_factors_untouched() -> None:
    """Tiny expected delta, non-positive actual delta, and None readings are inert."""
    composer = ShotComposer()
    composer.size_factor = 0.7

    # Tiny expected delta (<= 0.5%): target 50.0, before 49.6 -> 0.4% expected.
    composer.observe(49.6, 52.0, _tuning())
    assert composer.size_factor == 0.7

    # Non-positive actual delta.
    composer.observe(40.0, 39.0, _tuning())
    assert composer.size_factor == 0.7

    # Missing readings.
    composer.observe(None, 45.0, _tuning())
    assert composer.size_factor == 0.7
    composer.observe(40.0, None, _tuning())
    assert composer.size_factor == 0.7


def test_observe_overshoot_lengthens_interval_factor() -> None:
    """Overshoot lengthens the interval factor (ADR-0014), clamped to the ceiling."""
    # ratio 1.5, error 0.5, aggressiveness 1.0 -> 1.0 + 0.5 = 1.5 (== ceiling).
    composer = ShotComposer()
    composer.observe(40.0, 55.0, _tuning())
    assert composer.interval_factor == 1.5

    # Clamped at the ceiling on a further overshoot.
    composer.observe(40.0, 55.0, _tuning())
    assert composer.interval_factor == 1.5


def test_observe_undershoot_recovers_interval_factor() -> None:
    """Undershoot recovers the interval factor toward nominal 1.0."""
    # ratio 0.5, error 0.5, recovery 0.1 -> 1.4 - 0.05 = 1.35.
    composer = ShotComposer()
    composer.interval_factor = 1.4
    composer.observe(40.0, 45.0, _tuning())
    assert abs(composer.interval_factor - 1.35) < 1e-6

    # Clamps at nominal 1.0, never below.
    composer.interval_factor = 1.02
    composer.observe(40.0, 45.0, _tuning())
    assert composer.interval_factor == 1.0


def test_observe_disabled_is_inert() -> None:
    """When Adaptive Shot Control is disabled, neither factor moves."""
    composer = ShotComposer()
    composer.size_factor = 0.7
    composer.interval_factor = 1.2
    tuning = _tuning(enabled=False)

    composer.observe(40.0, 55.0, tuning)  # would overshoot
    composer.observe(40.0, 45.0, tuning)  # would undershoot
    assert composer.size_factor == 0.7
    assert composer.interval_factor == 1.2


def test_observe_respects_custom_tunables() -> None:
    """Custom aggressiveness/floor/ceiling drive the factors and clamps."""
    # ratio 1.5, error 0.5, aggressiveness 2.0:
    #   size 1.0 - 2.0*0.5 = 0.0 -> floor 0.2;
    #   interval 1.0 + 2.0*0.5 = 2.0 (below the 3.0 ceiling).
    composer = ShotComposer()
    composer.observe(
        40.0,
        55.0,
        _tuning(aggressiveness=2.0, size_floor=0.2, interval_ceiling=3.0),
    )
    assert composer.size_factor == 0.2
    assert composer.interval_factor == 2.0


def test_reset_returns_both_factors_to_nominal() -> None:
    """reset() sets size and interval factors back to 1.0."""
    composer = ShotComposer()
    composer.size_factor = 0.6
    composer.interval_factor = 1.4
    composer.reset()
    assert composer.size_factor == 1.0
    assert composer.interval_factor == 1.0


def test_compose_p2_applies_vwc_and_ec_factors() -> None:
    """A P2 shot multiplies base by the size factor and the injected EC factor."""
    composer = ShotComposer()
    composer.size_factor = 0.5

    composition = composer.compose(
        "P2",
        20,
        lambda: (1.2, True),
        lambda secs: False,
        _TS,
    )

    # 20 * 0.5 * 1.2 = 12.0 -> 12
    assert composition.composed_seconds == 12
    assert composition.effective_seconds == 12
    assert composition.capped is False
    assert composition.vwc_factor == 0.5
    assert composition.ec_factor == 1.2
    assert composition.ec_modulation_available is True
    assert composition.phase == "P2"
    assert composition.base_seconds == 20
    assert composition.timestamp == _TS
    # The returned record is also retained for diagnostics.
    assert composer.last_composition is composition


def test_compose_p1_keeps_neutral_ec_and_never_calls_resolver() -> None:
    """P1 shots keep a neutral EC factor and never invoke the EC resolver."""

    def _must_not_be_called() -> tuple[float, bool]:
        raise AssertionError("get_ec_factor must not be called for P1 shots")

    composer = ShotComposer()
    composer.size_factor = 0.6

    composition = composer.compose(
        "P1", 10, _must_not_be_called, lambda secs: False, _TS
    )

    # 10 * 0.6 * 1.0 = 6
    assert composition.composed_seconds == 6
    assert composition.ec_factor == 1.0
    assert composition.ec_modulation_available is False


def test_compose_records_cap_without_lowering_composed_seconds() -> None:
    """A capped shot reports effective_seconds 0 but keeps the composed value."""
    composer = ShotComposer()

    composition = composer.compose(
        "P2", 20, lambda: (1.0, True), lambda secs: True, _TS
    )

    assert composition.composed_seconds == 20
    assert composition.effective_seconds == 0
    assert composition.capped is True


def test_compose_floors_composed_seconds_at_one() -> None:
    """A shot that rounds below 1 second is floored to 1, never zero."""
    composer = ShotComposer()
    composer.size_factor = 0.5

    composition = composer.compose(
        "P1", 1, lambda: (1.0, False), lambda secs: False, _TS
    )

    # round(1 * 0.5) = 0 -> floored to 1.
    assert composition.composed_seconds == 1
