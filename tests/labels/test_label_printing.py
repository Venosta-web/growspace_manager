"""Tests for the three print routes (hub issue #221).

The acceptance boundary this suite guards is the one the whole calibration
route exists for: **what comes out of the printer is what the operator
approved, on a printer somebody measured, from a layout somebody published.**

Four properties carry that, and each has its own section below.

*Nothing reaches paper unjudged.* `async_render` sends to the printer
integration and only then reports its diagnostics, so every route here renders
a preview first and commits only if that preview is allowed. The tests assert
it the way it matters -- by counting what the printer was actually asked to
do -- rather than by asserting that a function was called.

*A provisional profile prints exactly two things.* The standardized
calibration label and an administrator's test output. Never a real record.

*Production asserts five things, each refused by its own name.* A published
revision, a real record's snapshot, the approved raster, a product-verified
profile, and a current local calibration.

*One Render Context, one bitmap.* Preview, test print, production print and
retry hand the adapter byte-identical inputs, and the routes prove it with a
digest of the payload that really went to the printer integration rather than
one reconstructed beside it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from typing import Any

import pytest

from custom_components.growspace_manager.labels.calibration import (
    CalibrationSheetNotPrinted,
    LocalCalibrationLedger,
    PlacementMeasurement,
)
from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    NIIMBOT_B1_50X30,
    TYPICAL_STRAIN,
    Blocker,
    Operation,
    async_render,
)
from custom_components.growspace_manager.labels.canonical.preview import PREVIEW
from custom_components.growspace_manager.labels.canonical.subjects import RECORD_SOURCE
from custom_components.growspace_manager.labels.printing import (
    LayoutSource,
    PrintRefused,
    async_print_calibration_label,
    async_print_record,
    async_test_print,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized
from tests.labels.support import product_verified

from .support import StubFonts, layout_of, text_element

PROVISIONAL = NIIMBOT_B1_50X30
VERIFIED = product_verified(NIIMBOT_B1_50X30)
DEVICE = "printer-a"
AS_OF = datetime(2026, 9, 19, 9, 30, tzinfo=UTC)
FONTS = StubFonts()

MEASUREMENT = PlacementMeasurement(
    top_mm=0.5, right_mm=0.5, bottom_mm=0.0, left_mm=0.5, feed_mm=-0.4
)


@pytest.fixture
def calibration_ledger(hass: HomeAssistant) -> LocalCalibrationLedger:
    """One empty ledger, over the real store."""
    return LocalCalibrationLedger(hass, "entry-a")


@pytest.fixture
def fixture_content():
    """A representative subject's snapshot: valid, and not a record's."""
    return TYPICAL_STRAIN.snapshot(as_of=AS_OF)


@pytest.fixture
def record_content(fixture_content):
    """The same values, declared as one real record's immutable snapshot."""
    return replace(fixture_content, source=RECORD_SOURCE)


@pytest.fixture
def published() -> LayoutSource:
    """A published layout: the shipped Factory Template at its revision."""
    return LayoutSource.from_factory(FACTORY_50X30)


@pytest.fixture
def draft() -> LayoutSource:
    """An administrator's unpublished work on the same stock."""
    return LayoutSource.from_draft(
        layout_of(
            text_element(
                "name",
                {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
                binding="strain.name",
                size_mm=5.0,
                minimum_mm=3.0,
            )
        ),
        draft_key="admin-user:growspace.stock.50x30.v1",
    )


def _committed(printer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The calls that put something on paper rather than answering a preview."""
    return [call for call in printer if not call["preview"]]


async def _calibrate(
    hass, ledger, admin, *, profile=VERIFIED, firmware=None, printer=None
) -> None:
    """Print the standardized sheet and record what was read off it."""
    printed = await async_print_calibration_label(
        hass,
        profile=profile,
        actor=admin,
        device_id=DEVICE,
        as_of=AS_OF,
        firmware=firmware,
        fonts=FONTS,
    )
    await ledger.async_record(
        admin,
        measurement=MEASUREMENT,
        dependencies=printed.dependencies,
        sheet_raster_identity=printed.sheet_raster_identity,
        printed_density="normal",
    )
    if printer is not None:
        printer.clear()


async def _approved(hass, source, content, *, profile=VERIFIED) -> str:
    """The raster identity of a preview the operator has looked at."""
    result = await async_render(
        hass,
        layout=source.layout,
        content=content,
        profile=profile,
        operation=PREVIEW,
        fonts=FONTS,
    )
    return result.raster_identity


# ---------------------------------------------------------------------------
# Nothing reaches paper unjudged
# ---------------------------------------------------------------------------


async def test_a_print_is_judged_before_it_is_committed(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, record_content)
    printer.clear()

    await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    assert [call["preview"] for call in printer] == [True, False]


async def test_a_refused_print_puts_nothing_on_paper(
    hass, printer, admin, published, fixture_content, calibration_ledger
) -> None:
    """The refusal is the point, but so is the order: the label is not in the
    tray by the time the reason arrives."""
    with pytest.raises(PrintRefused):
        await async_print_record(
            hass,
            source=published,
            content=fixture_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity="sha256:whatever",
            fonts=FONTS,
        )
    assert _committed(printer) == []


# ---------------------------------------------------------------------------
# What a provisional profile may print
# ---------------------------------------------------------------------------


async def test_a_provisional_profile_prints_its_own_calibration_label(
    hass, printer, admin
) -> None:
    """Which is how it stops being provisional."""
    printed = await async_print_calibration_label(
        hass,
        profile=PROVISIONAL,
        actor=admin,
        device_id=DEVICE,
        as_of=AS_OF,
        fonts=FONTS,
    )
    assert printed.outcome.operation == str(Operation.TEST_PRINT)
    assert len(_committed(printer)) == 1


async def test_a_provisional_profile_test_prints_an_administrator_s_own_draft(
    hass, printer, admin, draft, fixture_content
) -> None:
    outcome = await async_test_print(
        hass,
        source=draft,
        content=fixture_content,
        profile=PROVISIONAL,
        actor=admin,
        fonts=FONTS,
    )
    assert outcome.decision.allowed
    assert len(_committed(printer)) == 1


async def test_a_provisional_profile_never_production_prints(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """One alignment label cannot establish readable fonts, QR scanning or
    density mapping, so measuring this printer does not make its class
    supported."""
    await _calibrate(hass, calibration_ledger, admin, profile=PROVISIONAL)
    approved = await _approved(hass, published, record_content, profile=PROVISIONAL)
    printer.clear()

    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=published,
            content=record_content,
            profile=PROVISIONAL,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED) in refusal.value.blockers
    assert _committed(printer) == []


async def test_a_layout_that_cannot_print_does_not_print_because_it_is_a_test(
    hass, printer, admin, fixture_content
) -> None:
    unprintable = LayoutSource.from_draft(
        layout_of(
            text_element(
                "name",
                {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
                binding="strain.name",
                size_mm=0.8,
                minimum_mm=0.4,
            )
        ),
        draft_key="admin-user:tiny",
    )
    with pytest.raises(PrintRefused) as refusal:
        await async_test_print(
            hass,
            source=unprintable,
            content=fixture_content,
            profile=PROVISIONAL,
            actor=admin,
            fonts=FONTS,
        )
    assert str(Blocker.BLOCKING_DIAGNOSTICS) in refusal.value.blockers
    assert _committed(printer) == []


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


async def test_calibration_hands_back_what_the_printed_sheet_depended_on(
    hass, printer, admin
) -> None:
    """So four numbers can never be recorded against a render that did not
    happen."""
    printed = await async_print_calibration_label(
        hass,
        profile=PROVISIONAL,
        actor=admin,
        device_id=DEVICE,
        as_of=AS_OF,
        fonts=FONTS,
    )
    assert printed.dependencies.scope.device_id == DEVICE
    assert printed.dependencies.scope.label_size_id == PROVISIONAL.label_size_id
    assert printed.sheet_raster_identity == printed.outcome.raster_identity


async def test_only_an_administrator_calibrates(hass, printer, viewer) -> None:
    with pytest.raises(Unauthorized):
        await async_print_calibration_label(
            hass, profile=PROVISIONAL, actor=viewer, device_id=DEVICE, fonts=FONTS
        )
    assert printer == []


async def test_a_calibration_sheet_that_cannot_print_says_so_rather_than_failing_late(
    hass, printer, admin
) -> None:
    """A profile whose declared density is not in its own range cannot render
    the sheet, and the operator hears that instead of holding a blank label."""
    broken = replace(PROVISIONAL, density_levels={})
    with pytest.raises(CalibrationSheetNotPrinted):
        await async_print_calibration_label(
            hass,
            profile=broken,
            actor=admin,
            device_id=DEVICE,
            as_of=AS_OF,
            fonts=FONTS,
        )
    assert _committed(printer) == []


# ---------------------------------------------------------------------------
# What a production print asserts
# ---------------------------------------------------------------------------


async def test_a_calibrated_verified_profile_prints_a_published_revision(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, record_content)
    printer.clear()

    outcome = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    assert outcome.decision.allowed
    assert outcome.operation == str(Operation.SINGLE_PRINT)
    assert outcome.source.published


async def test_any_authenticated_user_may_print_a_real_label(
    hass, printer, admin, viewer, published, record_content, calibration_ledger
) -> None:
    """Printing a label for a plant is ordinary work."""
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, record_content)
    outcome = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=viewer,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    assert outcome.decision.allowed


async def test_an_unattributed_request_prints_nothing(
    hass, printer, nobody, published, record_content, calibration_ledger
) -> None:
    with pytest.raises(Unauthorized):
        await async_print_record(
            hass,
            source=published,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=nobody,
            device_id=DEVICE,
            expected_raster_identity="sha256:anything",
            fonts=FONTS,
        )
    assert printer == []


async def test_a_draft_never_production_prints(
    hass, printer, admin, draft, record_content, calibration_ledger
) -> None:
    """A label in a grow room outlives the session that printed it."""
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, draft, record_content)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=draft,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.REVISION_NOT_PUBLISHED),)


async def test_a_representative_fixture_never_production_prints(
    hass, printer, admin, published, fixture_content, calibration_ledger
) -> None:
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, fixture_content)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=published,
            content=fixture_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.CONTENT_NOT_ACTUAL),)


async def test_an_uncalibrated_printer_routes_to_calibration_rather_than_printing(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    approved = await _approved(hass, published, record_content)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=published,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.LOCAL_CALIBRATION_MISSING),)


async def test_a_stale_calibration_is_refused_by_name_and_not_as_missing(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """ "Recalibrate" with no reason is indistinguishable from the product
    having forgotten, and sending somebody to measure a printer they have
    already measured is worse than saying nothing."""
    # The printer's firmware was updated after it was measured, which is a
    # real staleness of a real record: it is genuinely this printer's, and it
    # is genuinely no longer true of what is about to print.
    await _calibrate(hass, calibration_ledger, admin, firmware="1.0", printer=printer)
    approved = await _approved(hass, published, record_content)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=published,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            firmware="1.1",
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.LOCAL_CALIBRATION_STALE),)
    assert "firmware" in str(refusal.value)


async def test_a_production_print_without_an_approved_preview_is_refused(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """An identity the caller never presented is not a match."""
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=published,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity="",
            fonts=FONTS,
        )
    assert str(Blocker.RESULT_NOT_CURRENT) in refusal.value.blockers


async def test_every_independent_reason_is_named_rather_than_the_first(
    hass, printer, admin, draft, fixture_content, calibration_ledger
) -> None:
    approved = await _approved(hass, draft, fixture_content, profile=PROVISIONAL)
    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=draft,
            content=fixture_content,
            profile=PROVISIONAL,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        str(Blocker.LOCAL_CALIBRATION_MISSING),
        str(Blocker.REVISION_NOT_PUBLISHED),
        str(Blocker.CONTENT_NOT_ACTUAL),
    )


# ---------------------------------------------------------------------------
# One Render Context, one bitmap
# ---------------------------------------------------------------------------


async def test_preview_test_print_and_production_print_hand_over_the_same_inputs(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """The property the whole seam exists for, asserted on the payload that
    really went to the printer integration rather than on the picture."""
    await _calibrate(hass, calibration_ledger, admin, printer=printer)

    preview = await async_render(
        hass,
        layout=published.layout,
        content=record_content,
        profile=VERIFIED,
        operation=PREVIEW,
        fonts=FONTS,
    )
    tested = await async_test_print(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        actor=admin,
        fonts=FONTS,
    )
    produced = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=preview.raster_identity,
        fonts=FONTS,
    )

    assert (
        preview.raster_input_digest
        == tested.raster_input_digest
        == produced.raster_input_digest
    )
    assert preview.raster_identity == tested.raster_identity == produced.raster_identity


async def test_a_retry_reprints_the_same_bitmap(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, record_content)

    first = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    retried = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    assert first.raster_input_digest == retried.raster_input_digest


async def test_calibrating_between_the_preview_and_the_print_changes_no_bitmap(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """The operator previews, is told the printer needs measuring, measures
    it, and prints the raster they looked at. Eligibility is re-asked at the
    print; the bitmap is not a different one."""
    approved = await _approved(hass, published, record_content)
    await _calibrate(hass, calibration_ledger, admin, printer=printer)

    outcome = await async_print_record(
        hass,
        source=published,
        content=record_content,
        profile=VERIFIED,
        ledger=calibration_ledger,
        actor=admin,
        device_id=DEVICE,
        expected_raster_identity=approved,
        fonts=FONTS,
    )
    assert outcome.raster_identity == approved


async def test_a_changed_layout_refuses_the_retry_rather_than_printing_something_else(
    hass, printer, admin, published, record_content, calibration_ledger
) -> None:
    """Reprinting "the same label" from a template that has since been edited
    is the failure this prevents, and it cannot be prevented by looking at the
    picture."""
    await _calibrate(hass, calibration_ledger, admin, printer=printer)
    approved = await _approved(hass, published, record_content)
    edited = LayoutSource.from_revision(
        layout_of(
            text_element(
                "name",
                {"x_mm": 3.0, "y_mm": 3.0, "width_mm": 30.0, "height_mm": 6.0},
                binding="strain.name",
                size_mm=4.0,
                minimum_mm=2.5,
            )
        ),
        template_id="01TEMPLATE",
        revision=2,
    )
    printer.clear()

    with pytest.raises(PrintRefused) as refusal:
        await async_print_record(
            hass,
            source=edited,
            content=record_content,
            profile=VERIFIED,
            ledger=calibration_ledger,
            actor=admin,
            device_id=DEVICE,
            expected_raster_identity=approved,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.RESULT_NOT_CURRENT),)
    assert _committed(printer) == []


async def test_the_density_the_sheet_was_printed_at_is_on_the_record(
    hass, printer, admin, calibration_ledger
) -> None:
    printed = await async_print_calibration_label(
        hass,
        profile=PROVISIONAL,
        actor=admin,
        device_id=DEVICE,
        density="high",
        as_of=AS_OF,
        fonts=FONTS,
    )
    record = await calibration_ledger.async_record(
        admin,
        measurement=MEASUREMENT,
        dependencies=printed.dependencies,
        sheet_raster_identity=printed.sheet_raster_identity,
        printed_density="high",
    )
    assert record.printed_density == "high"
    assert record.sheet_raster_identity == printed.outcome.raster_identity


# ---------------------------------------------------------------------------
# What a source says about itself
# ---------------------------------------------------------------------------


def test_a_revision_and_a_factory_template_are_published_and_a_draft_is_not(
    draft, published
) -> None:
    assert published.published
    assert not draft.published
    assert LayoutSource.from_revision(
        published.layout, template_id="01T", revision=3
    ).published


def test_a_source_names_itself_for_an_audit_record(published, draft) -> None:
    assert published.reference == f"factory:{FACTORY_50X30.id}@{FACTORY_50X30.revision}"
    assert draft.reference.startswith("draft:")
    assert set(published.as_dict()) == {"kind", "reference", "published"}


async def test_an_outcome_serializes_for_the_wire(
    hass, printer, admin, draft, fixture_content
) -> None:
    outcome = await async_test_print(
        hass,
        source=draft,
        content=fixture_content,
        profile=PROVISIONAL,
        actor=admin,
        fonts=FONTS,
    )
    wire = outcome.as_dict()
    assert set(wire) == {
        "operation",
        "source",
        "raster_identity",
        "raster_input_digest",
        "decision",
        "result",
    }
    json.dumps(wire)
