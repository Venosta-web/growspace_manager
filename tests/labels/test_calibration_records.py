"""Tests for what a local calibration is, and what stales it (hub issue #221).

Three claims are under test, and they are the three the product's whole
position on calibration rests on.

**A measurement is only true of what it was taken on.** Its dependencies are
captured from the render that produced the sheet in the operator's hand, and
the same values are computable before a print so that a print can know what it
requires. The two have to agree, and one test here is exactly that.

**A changed dependency stales it, by name.** "Recalibrate" with no reason is
indistinguishable from the product having forgotten something, so a refusal
names the field that moved.

**Elapsed time does not.** A printer measured a year ago and untouched since
still puts ink where it put ink. Age warns and recommends; it never refuses.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.labels.calibration import (
    AGE_WARNING,
    CURRENT,
    RECHECK_AFTER,
    SHEET_VERSION,
    STALE,
    CalibrationDependencies,
    CalibrationScope,
    LocalCalibration,
    MeasurementBounds,
    MeasurementInvalid,
    PlacementMeasurement,
    evaluate,
    validate_measurement,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    CalibratedLimits,
    FeedAxis,
    ProfileEvidence,
    RenderContext,
)
from tests.labels.support import product_verified

PROFILE = NIIMBOT_B1_50X30
DEVICE = "printer-in-the-drying-room"
FONTS = {"ppb.ttf": "sha256:aaa", "rbm.ttf": "sha256:bbb"}
NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

MEASURED = PlacementMeasurement(
    top_mm=0.5, right_mm=1.0, bottom_mm=0.0, left_mm=0.5, feed_mm=-0.8
)


def _dependencies(profile=PROFILE, **overrides) -> CalibrationDependencies:
    return CalibrationDependencies.for_profile(
        profile,
        device_id=overrides.pop("device_id", DEVICE),
        sheet_version=overrides.pop("sheet_version", SHEET_VERSION),
        font_identity=overrides.pop("font_identity", FONTS),
        firmware=overrides.pop("firmware", None),
    )


def _record(
    dependencies: CalibrationDependencies | None = None,
    *,
    recorded_at: datetime = NOW,
) -> LocalCalibration:
    return LocalCalibration(
        id="01ABCDEF",
        recorded_at=recorded_at.isoformat(),
        recorded_by="admin-user",
        measurement=MEASURED,
        dependencies=dependencies or _dependencies(),
        sheet_raster_identity="sha256:sheet",
        printed_density="normal",
    )


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def test_a_measurement_carries_all_four_offsets_and_the_feed() -> None:
    assert set(MEASURED.as_dict()) == {
        "top_mm",
        "right_mm",
        "bottom_mm",
        "left_mm",
        "feed_mm",
    }


def test_feed_alignment_is_signed_because_media_runs_both_early_and_long() -> None:
    bounds = MeasurementBounds.of_profile(PROFILE)
    assert validate_measurement(replace(MEASURED, feed_mm=-2.0), bounds)
    assert validate_measurement(replace(MEASURED, feed_mm=2.0), bounds)


def test_an_edge_offset_cannot_be_negative() -> None:
    """It is how much of the Printable Area is lost, and a printer that
    reaches further than declared is a profile that understates itself."""
    with pytest.raises(MeasurementInvalid, match="top_mm"):
        validate_measurement(
            replace(MEASURED, top_mm=-0.5), MeasurementBounds.of_profile(PROFILE)
        )


def test_an_offset_larger_than_the_printable_area_is_a_mistyped_digit() -> None:
    """Storing it would silently make every later print ineligible for a
    reason nobody could find."""
    with pytest.raises(MeasurementInvalid, match="left_mm"):
        validate_measurement(
            replace(MEASURED, left_mm=60.0), MeasurementBounds.of_profile(PROFILE)
        )


def test_a_large_but_possible_offset_is_accepted() -> None:
    """A badly loaded roll really does lose four millimetres, and refusing
    that would refuse the measurement most worth having."""
    assert validate_measurement(
        replace(MEASURED, left_mm=4.0), MeasurementBounds.of_profile(PROFILE)
    )


def test_a_measurement_finer_than_the_millimetre_quantum_is_refused() -> None:
    """Rather than rounded: a calibration cannot carry a precision the
    document model does not have."""
    with pytest.raises(MeasurementInvalid, match="right_mm"):
        validate_measurement(
            replace(MEASURED, right_mm=0.123), MeasurementBounds.of_profile(PROFILE)
        )


def test_feed_bounds_follow_the_declared_feed_axis() -> None:
    """The B1 feeds along the 30 mm axis, so a 40 mm feed error is impossible
    on it even though the stock is 50 mm the other way."""
    bounds = MeasurementBounds.of_profile(PROFILE)
    assert bounds.feed_axis == str(FeedAxis.Y)
    with pytest.raises(MeasurementInvalid, match="feed_mm"):
        validate_measurement(replace(MEASURED, feed_mm=40.0), bounds)


def test_bounds_come_from_the_record_s_own_dependencies_not_the_current_profile() -> (
    None
):
    """A measurement must be admitted against the geometry it was taken on."""
    narrow = _dependencies(replace(PROFILE, printable_width_mm=10.0))
    with pytest.raises(MeasurementInvalid):
        validate_measurement(
            replace(MEASURED, left_mm=20.0), MeasurementBounds.of_dependencies(narrow)
        )


# ---------------------------------------------------------------------------
# What a measurement was true of
# ---------------------------------------------------------------------------


def test_the_scope_is_the_installed_printer_stock_and_mounting() -> None:
    scope = _dependencies().scope
    assert scope == CalibrationScope(
        device_id=DEVICE,
        printer_class=PROFILE.printer_class,
        label_size_id=PROFILE.label_size_id,
        orientation=str(PROFILE.orientation),
    )


def test_a_difference_names_the_field_that_moved() -> None:
    changed = _dependencies(replace(PROFILE, dpi=300))
    assert _dependencies().differences(changed) == ("dpi",)


def test_every_independent_change_is_named_rather_than_the_first() -> None:
    changed = _dependencies(
        replace(PROFILE, dpi=300, printhead_pixels=576), sheet_version="other"
    )
    assert set(_dependencies().differences(changed)) == {
        "dpi",
        "printhead_pixels",
        "sheet_version",
    }


def test_two_ways_of_asking_what_a_print_depends_on_agree() -> None:
    """`for_profile` answers before anything is rendered, so that the
    calibration identity can go *into* the Render Context; `from_render`
    answers afterwards, from the print that happened. A print whose
    requirement disagreed with the record it just wrote would stale itself
    immediately."""

    context = RenderContext(
        layout_digest="sha256:layout",
        label_size_id=PROFILE.label_size_id,
        profile_id=PROFILE.id,
        profile_evidence=str(PROFILE.evidence),
        content_identity="sha256:content",
        content_context="strain",
        content_source="calibration",
        locale="en",
        time_zone="UTC",
        as_of=NOW.isoformat(),
        density="normal",
        density_level=3,
        operation="test_print",
    )
    from_render = CalibrationDependencies.from_render(
        context,
        PROFILE,
        device_id=DEVICE,
        sheet_version=SHEET_VERSION,
        font_identity=FONTS,
    )
    assert from_render.identity == _dependencies().identity


# ---------------------------------------------------------------------------
# What stales it, and what only warns
# ---------------------------------------------------------------------------


def test_an_unchanged_dependency_set_is_current() -> None:
    status = evaluate(_record(), required=_dependencies(), now=NOW)
    assert status.state == CURRENT
    assert status.is_current
    assert status.identity == _record().identity
    assert status.stale_reasons == ()


def test_a_changed_renderer_stales_the_measurement_and_says_so() -> None:
    changed = replace(_dependencies(), renderer_version="growspace.label-renderer.v2")
    status = evaluate(_record(), required=changed, now=NOW)
    assert status.state == STALE
    assert status.stale_reasons == ("renderer_version",)
    assert not status.is_current


def test_a_stale_record_contributes_no_identity_but_is_still_on_file() -> None:
    """Its audit value is intact. What it may not do is authorize a raster."""
    changed = replace(_dependencies(), dpi=300)
    status = evaluate(_record(), required=changed, now=NOW)
    assert status.identity is None
    assert status.record is not None


def test_replacing_a_font_file_stales_every_printer_at_once() -> None:
    """Which is correct: the faces are the installation's, not one label's."""
    changed = replace(_dependencies(), font_identity={"ppb.ttf": "sha256:new"})
    assert evaluate(_record(), required=changed, now=NOW).stale_reasons == (
        "font_identity",
    )


def test_a_redefined_density_mapping_stales_it_but_printing_darker_does_not() -> None:
    """Density is heat, not placement. A record that went stale every time
    somebody printed darker would be asking for a re-measurement of something
    that did not move -- but a profile that redefines what `normal` means on
    this hardware has changed what the sheet was printed with."""
    darker = _dependencies()
    assert evaluate(_record(), required=darker, now=NOW).state == CURRENT

    remapped = _dependencies(
        replace(PROFILE, density_levels={"low": 1, "normal": 4, "high": 5})
    )
    assert evaluate(_record(), required=remapped, now=NOW).stale_reasons == (
        "density_levels",
    )


def test_promoting_a_profile_to_product_verified_does_not_stale_it() -> None:
    """Promotion is exactly the transition a calibration is taken in
    anticipation of. Staling every installation's measurement at the moment
    the product learns its printer works would mean nobody could be ready."""
    verified = _dependencies(product_verified(PROFILE))
    assert evaluate(_record(), required=verified, now=NOW).state == CURRENT


def test_promotion_that_also_changes_the_measured_limits_does_stale_it() -> None:
    """Because the limits are a field, and a field that moved is named."""
    measured = replace(
        PROFILE,
        evidence=ProfileEvidence.PRODUCT_VERIFIED,
        limits=replace(PROFILE.limits, measured=True, text_readable_floor_mm=1.9),
    )
    assert evaluate(
        _record(), required=_dependencies(measured), now=NOW
    ).stale_reasons == ("limits_digest",)


def test_elapsed_time_alone_only_warns() -> None:
    old = _record(recorded_at=NOW - RECHECK_AFTER - timedelta(days=5))
    status = evaluate(old, required=_dependencies(), now=NOW)
    assert status.state == CURRENT
    assert status.is_current
    assert status.warnings == (AGE_WARNING,)
    assert status.age_days is not None


def test_a_fresh_measurement_carries_no_age_warning() -> None:
    status = evaluate(
        _record(recorded_at=NOW - timedelta(days=3)),
        required=_dependencies(),
        now=NOW,
    )
    assert status.warnings == ()
    assert status.age_days == 3


def test_an_old_record_whose_dependencies_moved_says_both() -> None:
    status = evaluate(
        _record(recorded_at=NOW - RECHECK_AFTER - timedelta(days=1)),
        required=replace(_dependencies(), dpi=300),
        now=NOW,
    )
    assert status.state == STALE
    assert status.stale_reasons == ("dpi",)
    assert status.warnings == (AGE_WARNING,)


def test_an_unparseable_timestamp_loses_the_recommendation_not_the_record() -> None:
    """Losing the nudge to re-check is a smaller harm than refusing a
    measurement that is otherwise intact."""
    broken = replace(_record(), recorded_at="whenever")
    status = evaluate(broken, required=_dependencies(), now=NOW)
    assert status.state == CURRENT
    assert status.age_days is None
    assert status.warnings == ()


# ---------------------------------------------------------------------------
# Identity and the wire
# ---------------------------------------------------------------------------


def test_the_identity_covers_the_numbers_and_what_they_were_taken_on() -> None:
    assert (
        _record().identity
        != replace(_record(), measurement=replace(MEASURED, top_mm=1.5)).identity
    )
    assert (
        _record().identity != _record(_dependencies(replace(PROFILE, dpi=300))).identity
    )


def test_who_held_the_ruler_does_not_change_what_was_measured() -> None:
    """Two administrators entering the same numbers for the same printer have
    measured the same thing, and a cached raster should not be invalidated
    because a different person submitted the form."""
    assert (
        replace(_record(), recorded_by="other-admin", id="01ZZZ").identity
        == _record().identity
    )


def test_a_record_round_trips_through_its_persisted_form() -> None:
    restored = LocalCalibration.from_dict(_record().as_dict())
    assert restored == _record()
    assert restored.identity == _record().identity


def test_the_limits_digest_moves_with_any_calibrated_limit() -> None:
    tighter = replace(
        PROFILE,
        limits=CalibratedLimits(
            **{**PROFILE.limits.as_dict(), "qr_minimum_dots_per_module": 3}
        ),
    )
    assert _dependencies().differences(_dependencies(tighter)) == ("limits_digest",)
