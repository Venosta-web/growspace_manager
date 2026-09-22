"""Behavior tests for Home Assistant's history-relative Frame Quality Gate."""

from custom_components.growspace_manager.domain.vision_quality import (
    QualityHistory,
    QualitySignals,
    RelativeQualityReason,
)


def _signals(
    *,
    luminance: float = 100.0,
    gradient: float = 10.0,
    clipped_fraction: float = 0.1,
) -> QualitySignals:
    return QualitySignals(
        mean_luminance=luminance,
        clipped_pixel_fraction=clipped_fraction,
        mean_absolute_gradient=gradient,
    )


def _ready_history() -> QualityHistory:
    return QualityHistory(accepted=(_signals(),) * 10)


def test_quality_history_warms_up_before_evaluating_relative_rails() -> None:
    """The first ten service-accepted captures establish camera-relative history."""
    history = QualityHistory(accepted=(_signals(),) * 9)

    decision = history.evaluate(
        _signals(luminance=20.0, gradient=2.0),
        service_accepted=True,
    )

    assert decision.accepted is True
    assert decision.reasons == ()
    assert decision.reanchored is False
    assert len(decision.next_history.accepted) == 10


def test_relative_rails_reject_an_excursion_without_learning_from_it() -> None:
    """Exposure and detail excursions cannot move the history that rejects them."""
    history = _ready_history()

    decision = history.evaluate(
        _signals(luminance=201.0, gradient=4.9),
        service_accepted=True,
    )

    assert decision.accepted is False
    assert decision.reasons == (
        RelativeQualityReason.EXPOSURE_EXCURSION,
        RelativeQualityReason.DETAIL_COLLAPSE,
    )
    assert decision.next_history.accepted == history.accepted
    assert decision.next_history.relative_rejection_streak == 1


def test_third_relative_excursion_reanchors_instead_of_blinding_camera() -> None:
    """A persistent new regime becomes a fresh warm-up after two rejections."""
    excursion = _signals(luminance=40.0)
    first = _ready_history().evaluate(excursion, service_accepted=True)
    second = first.next_history.evaluate(excursion, service_accepted=True)

    third = second.next_history.evaluate(excursion, service_accepted=True)

    assert third.accepted is True
    assert third.reasons == ()
    assert third.reanchored is True
    assert third.next_history.accepted == (excursion,)
    assert third.next_history.relative_rejection_streak == 0


def test_absolute_rejections_are_uncapped_and_never_enter_quality_history() -> None:
    """The service floor keeps rejecting an unusable frame for any streak length."""
    history = _ready_history()

    for _ in range(4):
        decision = history.evaluate(
            _signals(luminance=2.0, gradient=0.1),
            service_accepted=False,
            service_reasons=("too_dark", "low_detail"),
        )
        assert decision.accepted is False
        assert decision.reasons == ("too_dark", "low_detail")
        assert decision.next_history == history
        history = decision.next_history


def test_accepted_quality_history_is_camera_wide_and_trails_thirty_captures() -> None:
    """Accepted signals roll across light windows behind one camera-level seam."""
    accepted = tuple(_signals(luminance=float(value)) for value in range(1, 31))
    history = QualityHistory(accepted=accepted)

    decision = history.evaluate(_signals(luminance=20.0), service_accepted=True)

    assert decision.accepted is True
    assert len(decision.next_history.accepted) == 30
    assert decision.next_history.accepted[0] == accepted[1]
    assert decision.next_history.accepted[-1] == _signals(luminance=20.0)
