"""Tests for the Capability Profile (hub issue #216).

A profile is the only thing that turns saved millimetres into a claim about
one printer, so the suite is about what it must distinguish and never
conflate: the physical stock, the calibrated Printable Area inside it and the
recommended Safe Area inside that; the density words this hardware really
accepts; the element rotations this combination realises; and how far its
evidence has been taken.

The last of those is the one with teeth. Every number a render is judged
against lives here, and while they are declared rather than measured the
profile cannot authorize production printing -- which is what stops a
plausible constant from being the last thing between a layout and paper.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from custom_components.growspace_manager.labels.canonical import (
    LABEL_SIZES,
    NIIMBOT_B1_50X30,
    PROFILES,
    CalibratedLimits,
    ProfileEvidence,
    StockOrientation,
    profiles_for_size,
)
from custom_components.growspace_manager.labels.canonical.evidence import (
    EvidenceDimension,
)
from custom_components.growspace_manager.labels.canonical.profiles import (
    NIIMBOT_B1_50X30_EVIDENCE,
)
from tests.labels.support import product_verified

PROFILE = NIIMBOT_B1_50X30


# ---------------------------------------------------------------------------
# Three nested regions, in the stock's own millimetres
# ---------------------------------------------------------------------------


def test_the_stock_area_is_the_physical_label() -> None:
    size = LABEL_SIZES[PROFILE.label_size_id]
    assert PROFILE.stock_area.as_dict() == {
        "x_mm": 0.0,
        "y_mm": 0.0,
        "width_mm": size.width_mm,
        "height_mm": size.height_mm,
    }


def test_the_printable_area_is_narrower_than_the_stock_it_prints_on() -> None:
    """384 dots at 203 dpi is 48.05 mm, so two of the stock's fifty cannot be
    reached however the layout is drawn."""
    assert PROFILE.printable_area.width_mm < PROFILE.stock_area.width_mm
    assert PROFILE.printable_area.width_mm == 48.0


def test_the_safe_area_is_the_printable_area_inset_on_every_side() -> None:
    safe = PROFILE.safe_area
    printable = PROFILE.printable_area
    inset = PROFILE.safe_area_inset_mm
    assert safe.x_mm == printable.x_mm + inset
    assert safe.right_mm == printable.right_mm - inset
    assert safe.bottom_mm == printable.bottom_mm - inset


def test_an_inset_larger_than_the_area_collapses_rather_than_inverting() -> None:
    """A negative rectangle would pass every containment test it was given,
    which is the one way "nothing is safe" must not read."""
    absurd = replace(PROFILE, safe_area_inset_mm=40.0)
    assert absurd.safe_area.width_mm == 0.0
    assert absurd.safe_area.height_mm == 0.0


# ---------------------------------------------------------------------------
# Density, orientation and rotation
# ---------------------------------------------------------------------------


def test_density_resolves_to_this_printer_class_s_own_range() -> None:
    assert PROFILE.density_level("normal") == 3
    assert PROFILE.density_level("high") == 5
    assert PROFILE.density_level("ludicrous") is None


def test_whole_stock_orientation_belongs_to_the_profile() -> None:
    assert PROFILE.orientation is StockOrientation.LANDSCAPE


def test_the_profile_declares_which_element_rotations_it_realises() -> None:
    assert PROFILE.supports_rotation(0) is True
    assert PROFILE.supports_rotation(90) is False
    assert replace(PROFILE, supported_element_rotations=(0, 90)).supports_rotation(90)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_the_shipped_b1_profile_is_proven_by_its_own_record() -> None:
    """Hub issue #231: one exact combination, promoted on physical evidence."""
    assert PROFILE.evidence is ProfileEvidence.PRODUCT_VERIFIED
    assert PROFILE.evidence_record is NIIMBOT_B1_50X30_EVIDENCE
    assert PROFILE.evidence_problems == ()
    assert PROFILE.limits.measured is True
    assert PROFILE.authorizes_production is True


def test_the_b1_record_is_for_this_printer_stock_and_procedure() -> None:
    record = NIIMBOT_B1_50X30_EVIDENCE
    assert record.profile_id == PROFILE.id
    assert record.printer_model in PROFILE.device_models
    assert record.stock == PROFILE.label_size_id
    assert record.operator
    assert record.reviewed_by
    assert record.deviations


def test_the_retained_evidence_is_in_the_repository() -> None:
    """A reference nobody can open is not evidence anyone can review."""
    root = Path(__file__).parents[2]
    record = NIIMBOT_B1_50X30_EVIDENCE
    assert (root / record.reference).is_dir()
    for result in record.results.values():
        for artifact in result.artifacts:
            assert (root / artifact).is_file(), artifact


def test_the_text_floor_is_the_one_the_evidence_proved_readable() -> None:
    """Regular 1.6 mm was unreadable at every density; 2.2 mm was not."""
    assert PROFILE.limits.text_readable_floor_mm == 2.2
    measured = NIIMBOT_B1_50X30_EVIDENCE.results[EvidenceDimension.TEXT].measurements
    assert measured["adopted_floor_mm"] == PROFILE.limits.text_readable_floor_mm


def test_the_evidence_covers_only_the_tested_model() -> None:
    """A B21 shares the printhead and the resolution, and is still not this."""
    assert PROFILE.device_models == ("B1",)
    assert PROFILE.covers_device_model("B1")
    assert not PROFILE.covers_device_model("B21")
    assert not PROFILE.covers_device_model("B1 Pro")
    assert not PROFILE.covers_device_model(None)


def test_the_tested_models_are_part_of_what_was_measured() -> None:
    """Widening the models a record covers is a change the record must see."""
    widened = replace(PROFILE, device_models=("B1", "B21"))
    assert widened.definition_digest != PROFILE.definition_digest
    assert "evidence.profile_changed" in widened.evidence_problems


def test_no_shipped_profile_claims_evidence_nobody_recorded() -> None:
    for profile in PROFILES.values():
        assert (
            profile.evidence is ProfileEvidence.PROVISIONAL
            or profile.evidence_record is not None
        )


def test_promotion_is_a_state_change_rather_than_a_different_geometry() -> None:
    verified = product_verified(
        replace(PROFILE, limits=replace(PROFILE.limits, measured=True))
    )
    assert verified.authorizes_production is True
    assert verified.printable_area == PROFILE.printable_area


def test_the_quiet_zone_minimum_is_the_symbology_s_rather_than_a_preference() -> None:
    assert PROFILE.limits.qr_minimum_quiet_zone_modules == 4


# ---------------------------------------------------------------------------
# The wire form a client explains a refusal from
# ---------------------------------------------------------------------------


def test_the_wire_form_carries_every_region_limit_and_evidence_field() -> None:
    wire = PROFILE.as_dict()
    assert set(wire) == {
        "id",
        "printer_class",
        "label_size_id",
        "dpi",
        "printhead_pixels",
        "orientation",
        "feed_axis",
        "stock_area",
        "printable_area",
        "safe_area",
        "density_levels",
        "supported_element_rotations",
        "evidence",
        "evidence_recorded_at",
        "evidence_reference",
        "evidence_invalidated_by",
        "authorizes_production",
        "limits",
    }
    assert set(wire["limits"]) == {
        "text_readable_floor_mm",
        "text_comfort_threshold_mm",
        "qr_minimum_dots_per_module",
        "qr_minimum_quiet_zone_modules",
        "qr_maximum_encoded_bytes",
        "qr_error_correction_levels",
        "image_minimum_effective_dpi",
        "divider_minimum_thickness_mm",
        "measured",
    }


@pytest.mark.parametrize("size_id", sorted(LABEL_SIZES))
def test_only_a_stock_with_a_profile_can_be_rendered_at_all(size_id: str) -> None:
    profiles = profiles_for_size(size_id)
    assert all(profile.label_size_id == size_id for profile in profiles)
    assert bool(profiles) is (size_id == "growspace.stock.50x30.v1")


def test_a_limits_record_is_immutable() -> None:
    limits = PROFILE.limits
    assert isinstance(limits, CalibratedLimits)
    with pytest.raises(AttributeError):
        limits.text_readable_floor_mm = 0.1  # type: ignore[misc]
