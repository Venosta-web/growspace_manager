"""Tests for the canonical render operation (hub issue #214).

Preview and print are one implementation reached with one argument different,
and most of what follows is about proving that -- and about what the result
carries back, because a raster nobody can attribute to a request is a picture
rather than an oracle.

The golden fixture pins the compiled payload for the shipped 50x30 Factory
Template. Beside it sits the PNG that payload really produced through
`imagespec` 0.4.0, the renderer the `niimbot` integration pins. That render
happens out of band: the renderer and its two font files belong to another
integration and are not installable in this suite, so what CI holds to is the
payload, and the recorded raster is evidence that the payload prints.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.canonical import (
    DEFAULT_LABEL_SIZE_ID,
    FACTORY_50X30,
    NIIMBOT_B1_50X30,
    PRINT,
    TYPICAL_STRAIN,
    InkBasis,
    ProfileEvidence,
    async_render,
    async_render_factory_preview,
)
from custom_components.growspace_manager.labels.canonical.preview import _decode_raster
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from tests.labels.support import STUB_FONT_DIGEST, StubFonts

FIXTURES = Path(__file__).parent.parent / "fixtures" / "labels"
GOLDEN = json.loads((FIXTURES / "canonical_factory_50x30.json").read_text())
EVIDENCE_RASTER = (FIXTURES / "canonical_factory_50x30.png").read_bytes()

AS_OF = datetime(2026, 9, 18, tzinfo=UTC)
SNAPSHOT = TYPICAL_STRAIN.snapshot(as_of=AS_OF)


def _png(width: int = 384, height: int = 240, colours: int = 2) -> str:
    """A data URI in the shape the renderer returns one."""
    image = Image.new("RGB", (width, height), "white")
    if colours == 2:
        image.paste(Image.new("RGB", (4, 4), "black"), (1, 1))
    else:
        for index in range(colours):
            image.paste(Image.new("RGB", (2, 2), (index * 7, 0, 0)), (index * 3, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


def _hass(response: Any = None) -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(
        return_value={"image": _png()} if response is None else response
    )
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    return hass


# ---------------------------------------------------------------------------
# What a preview returns
# ---------------------------------------------------------------------------


async def test_a_preview_returns_the_authoritative_monochrome_png() -> None:
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)

    assert result.status == "current"
    assert result.raster is not None
    assert result.raster.content_type == "image/png"
    assert (result.raster.width, result.raster.height) == (384, 240)
    assert result.raster.monochrome is True
    assert result.raster.data_uri.startswith("data:image/png;base64,")


async def test_the_raster_is_the_renderer_s_rather_than_a_reconstruction() -> None:
    """The preview is the bitmap the driver would receive, not a picture of it."""
    image = _png()
    hass = _hass({"image": image})
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.raster is not None
    assert result.raster.data_uri == image


async def test_a_preview_carries_the_complete_render_context() -> None:
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    context = result.context.as_dict()

    assert context["layout_digest"] == FACTORY_50X30.layout.digest
    assert context["content_identity"] == SNAPSHOT.identity
    assert context["profile_id"] == NIIMBOT_B1_50X30.id
    assert context["profile_evidence"] == "provisional"
    assert context["label_size_id"] == "growspace.stock.50x30.v1"
    assert context["density"] == "normal"
    assert context["density_level"] == 3
    assert context["as_of"] == AS_OF.isoformat()
    assert context["operation"] == "preview"
    # Each identity is recorded separately, so a font, compiler or profile
    # update can invalidate a raster without pretending the layout changed.
    for key in (
        "compiler_version",
        "renderer_version",
        "adapter_version",
        "binding_catalogue_version",
        "style_token_catalogue_version",
        "label_size_catalogue_version",
        "capability_generation",
    ):
        assert context[key]


async def test_a_preview_reports_an_outcome_for_every_stable_element_id() -> None:
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert [item.element_id for item in result.outcomes] == [
        element.id for element in FACTORY_50X30.layout.elements
    ]
    assert all(item.pixel_frame is not None for item in result.outcomes)


async def test_the_cache_identity_covers_every_input_the_raster_depends_on() -> None:
    hass = _hass()
    first = await async_render_factory_preview(hass, content=SNAPSHOT)
    same = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert first.cache_identity == same.cache_identity

    later = await async_render_factory_preview(
        hass, content=TYPICAL_STRAIN.snapshot(as_of=datetime(2026, 9, 19, tzinfo=UTC))
    )
    assert later.cache_identity != first.cache_identity


async def test_density_changes_the_cache_identity_although_not_the_bitmap() -> None:
    """The old context cannot authorize the new request, and a cache that said
    otherwise would be the place that forgot."""
    hass = _hass()
    normal = await async_render_factory_preview(hass, content=SNAPSHOT)
    dark = await async_render_factory_preview(hass, content=SNAPSHOT, density="high")
    assert normal.cache_identity != dark.cache_identity


async def test_the_whole_result_serializes_for_the_wire() -> None:
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    wire = result.as_dict()
    assert set(wire) == {
        "status",
        "printable",
        "cache_identity",
        "raster_identity",
        "raster_input_digest",
        "render_context",
        "profile",
        "raster",
        "elements",
        "ink",
        "overlaps",
        "diagnostics",
        "eligibility",
    }
    json.dumps(wire)


# ---------------------------------------------------------------------------
# One implementation, two operations
# ---------------------------------------------------------------------------


async def test_preview_and_print_send_the_identical_payload() -> None:
    """The only difference is the flag that decides whether it reaches paper."""
    hass = _hass()
    await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=SNAPSHOT,
        profile=NIIMBOT_B1_50X30,
    )
    await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=SNAPSHOT,
        profile=NIIMBOT_B1_50X30,
        operation=PRINT,
        device_id="printer-1",
    )
    previewed, printed = [call.args[2] for call in hass.services.async_call.mock_calls]
    assert previewed["payload"] == printed["payload"]
    assert previewed["preview"] is True
    assert printed["preview"] is False
    assert printed["device_id"] == "printer-1"


async def test_no_public_operation_accepts_an_imagespec_payload() -> None:
    """`imagespec` is the adapter's private wire format, and stays there."""
    import inspect

    for operation in (async_render, async_render_factory_preview):
        parameters = set(inspect.signature(operation).parameters)
        assert not parameters & {"payload", "imagespec", "elements", "spec"}


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


async def test_a_provisional_profile_renders_but_cannot_authorize_paper() -> None:
    """An exact bitmap is a claim about the driver, not about the paper."""
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.raster is not None
    assert result.printable is False


async def test_a_verified_profile_with_a_clean_render_is_printable() -> None:
    hass = _hass()
    verified = replace(NIIMBOT_B1_50X30, evidence=ProfileEvidence.PRODUCT_VERIFIED)
    result = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=SNAPSHOT,
        profile=verified,
        local_calibration="calibration-1",
    )
    assert result.printable is True


async def test_a_blocking_diagnostic_keeps_a_rendered_result_off_paper() -> None:
    hass = _hass()
    verified = replace(NIIMBOT_B1_50X30, evidence=ProfileEvidence.PRODUCT_VERIFIED)
    result = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=replace(SNAPSHOT, values={}),
        profile=verified,
    )
    assert result.raster is not None
    assert result.printable is False
    assert "content.missing_required" in [item.code for item in result.diagnostics]


async def test_warnings_leave_a_result_printable_and_visible() -> None:
    hass = _hass()
    verified = replace(NIIMBOT_B1_50X30, evidence=ProfileEvidence.PRODUCT_VERIFIED)
    result = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=replace(SNAPSHOT, values={"strain.name": "Blue Dream"}),
        profile=verified,
        local_calibration="calibration-1",
    )
    assert result.printable is True
    assert {item.severity for item in result.diagnostics} == {"warning"}


# ---------------------------------------------------------------------------
# Failure stays attributable
# ---------------------------------------------------------------------------


async def test_a_renderer_failure_becomes_a_raster_diagnostic() -> None:
    """A missing font is not a printer being offline, and must not read as one."""
    hass = _hass()
    hass.services.async_call = AsyncMock(
        side_effect=HomeAssistantError("Failed to create image: unknown font")
    )
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.status == "failed"
    assert result.raster is None
    assert result.printable is False
    diagnostic = result.diagnostics[-1]
    assert (diagnostic.code, diagnostic.layer) == ("raster.render_failed", "raster")


async def test_a_response_without_an_image_is_reported_rather_than_assumed() -> None:
    hass = _hass({"status": "ok"})
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.status == "failed"
    assert "raster.missing" in [item.code for item in result.diagnostics]


def test_an_undecodable_raster_is_reported() -> None:
    raster, diagnostics = _decode_raster("data:image/png;base64,not-base64")
    assert raster is None
    assert [item.code for item in diagnostics] == ["raster.unreadable"]


def test_a_raster_with_more_than_two_colours_is_not_called_monochrome() -> None:
    """Monochrome is a claim the preview makes, so it is measured."""
    raster, _ = _decode_raster(_png(colours=5))
    assert raster is not None
    assert raster.monochrome is False


# ---------------------------------------------------------------------------
# The shipped Factory Template, pinned
# ---------------------------------------------------------------------------


async def test_the_factory_template_compiles_to_its_recorded_payload() -> None:
    """A change here is a change to what every label prints. Regenerate it
    deliberately, and re-record the raster beside it."""
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    sent = hass.services.async_call.mock_calls[0].args[2]

    assert sent["payload"] == GOLDEN["imagespec_payload"]
    assert sent["width"] == GOLDEN["canvas"]["width"]
    assert sent["height"] == GOLDEN["canvas"]["height"]
    assert sent["density"] == GOLDEN["density"]["device"]
    assert result.context.layout_digest == GOLDEN["layout_digest"]
    assert result.context.content_identity == GOLDEN["content_identity"]
    assert [item.as_dict() for item in result.outcomes] == GOLDEN["outcomes"]


def test_the_recorded_raster_matches_the_canvas_this_compiler_produces() -> None:
    """The evidence and the arithmetic are tied together: move the Printable
    Area and this fails until the raster is rendered again."""
    with Image.open(BytesIO(EVIDENCE_RASTER)) as image:
        assert image.size == (
            GOLDEN["canvas"]["width"],
            GOLDEN["canvas"]["height"],
        )
        assert len(image.getcolors(8) or ()) == GOLDEN["raster_evidence"]["colours"]


def test_the_recorded_raster_is_the_one_the_fixture_names() -> None:
    import hashlib

    assert (
        hashlib.sha256(EVIDENCE_RASTER).hexdigest()
        == GOLDEN["raster_evidence"]["sha256"]
    )


@pytest.mark.parametrize("key", ["factory_template", "profile", "content_fixture"])
def test_the_fixture_records_what_it_was_taken_against(key: str) -> None:
    assert GOLDEN[key]


# ---------------------------------------------------------------------------
# Choosing the template and the profile
# ---------------------------------------------------------------------------


async def test_a_shipped_stock_with_no_profile_is_named_rather_than_substituted() -> (
    None
):
    """Every stock has a layout, but it cannot borrow another stock's profile."""
    hass = _hass()
    with pytest.raises(HomeAssistantError, match="No Capability Profile can render"):
        await async_render_factory_preview(
            hass, content=SNAPSHOT, label_size_id="growspace.stock.50x80.v1"
        )


async def test_a_stock_with_no_compatible_profile_is_named_too() -> None:
    """The other half of the same question, and a different answer."""
    hass = _hass()
    unprofiled = replace(
        FACTORY_50X30,
        id="growspace.factory.50x80",
        label_size_id="growspace.stock.50x80.v1",
        document={
            **FACTORY_50X30.document,
            "label_size_id": "growspace.stock.50x80.v1",
        },
    )
    with pytest.raises(HomeAssistantError, match="No Capability Profile can render"):
        await async_render_factory_preview(hass, content=SNAPSHOT, template=unprofiled)


async def test_the_default_stock_is_the_one_with_a_shipped_layout_and_a_profile() -> (
    None
):
    hass = _hass()
    explicit = await async_render_factory_preview(
        hass, content=SNAPSHOT, label_size_id=DEFAULT_LABEL_SIZE_ID
    )
    implicit = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert explicit.cache_identity == implicit.cache_identity


# ---------------------------------------------------------------------------
# More of what the raster is checked for
# ---------------------------------------------------------------------------


def test_a_raster_that_is_not_a_png_is_returned_with_a_warning() -> None:
    """It is still the renderer's bitmap; what it is not is what was expected."""
    image = Image.new("RGB", (8, 8), "white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    mislabelled = (
        f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    )

    raster, diagnostics = _decode_raster(mislabelled)
    assert raster is not None
    assert [item.code for item in diagnostics] == ["raster.unexpected_format"]
    assert diagnostics[0].severity == "warning"


def test_a_raster_measures_its_own_bytes_rather_than_trusting_the_response() -> None:
    raster, diagnostics = _decode_raster(_png(width=120, height=64))
    assert raster is not None
    assert (raster.width, raster.height) == (120, 64)
    assert raster.byte_length > 0
    assert diagnostics == ()


def test_a_one_bit_raster_is_monochrome() -> None:
    """The mode the printer transport actually wants."""
    image = Image.new("1", (16, 16), 1)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    raster, _ = _decode_raster(
        f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    )
    assert raster is not None
    assert raster.monochrome is True


def test_an_empty_response_is_a_missing_raster_rather_than_a_crash() -> None:
    raster, diagnostics = _decode_raster("data:image/png;base64,")
    assert raster is None
    assert [item.code for item in diagnostics] == ["raster.unreadable"]


async def test_a_response_of_none_is_reported_rather_than_assumed() -> None:
    """The adapter returns whatever the printer integration did, `None` included."""
    hass = _hass(response=None)
    hass.services.async_call = AsyncMock(return_value=None)
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.status == "failed"
    assert "raster.missing" in [item.code for item in result.diagnostics]


async def test_a_raster_that_is_not_a_data_uri_is_refused() -> None:
    hass = _hass({"image": "https://printer.test/last-label.png"})
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.status == "failed"
    assert "raster.missing" in [item.code for item in result.diagnostics]


async def test_decoding_happens_off_the_event_loop() -> None:
    """Pillow initialises its native libraries lazily on the first decode."""
    hass = _hass()
    await async_render_factory_preview(hass, content=SNAPSHOT)
    assert hass.async_add_executor_job.await_count >= 1


# ---------------------------------------------------------------------------
# Diagnostics reach the result in layer order
# ---------------------------------------------------------------------------


async def test_compilation_diagnostics_precede_raster_ones() -> None:
    """Errors are read top-down, and the attributable layer comes first."""
    hass = _hass()
    hass.services.async_call = AsyncMock(
        side_effect=HomeAssistantError("Failed to create image")
    )
    result = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=replace(SNAPSHOT, values={}),
        profile=NIIMBOT_B1_50X30,
    )
    layers = [item.layer for item in result.diagnostics]
    assert layers[-1] == "raster"
    assert "content" in layers
    assert layers.index("content") < layers.index("raster")


async def test_a_failed_render_still_reports_every_element_outcome() -> None:
    """The compilation happened; only the raster did not."""
    hass = _hass()
    hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("no font"))
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.raster is None
    assert [item.element_id for item in result.outcomes] == [
        element.id for element in FACTORY_50X30.layout.elements
    ]


# ---------------------------------------------------------------------------
# What the result carries about safety (hub issue #216)
# ---------------------------------------------------------------------------


async def test_a_result_reports_the_ink_of_every_stable_element_id() -> None:
    hass = _hass()
    result = await async_render_factory_preview(
        hass, content=SNAPSHOT, fonts=StubFonts()
    )
    assert [item.element_id for item in result.ink] == [
        element.id for element in FACTORY_50X30.layout.elements
    ]
    rule = next(item for item in result.ink if item.kind == "divider")
    assert rule.basis is InkBasis.EXACT
    assert rule.bounds is not None
    assert rule.mask_digest


async def test_the_result_carries_the_profile_it_was_judged_against() -> None:
    """A card explaining why Print is disabled must not need a second request
    to find out what the limits were."""
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.profile is NIIMBOT_B1_50X30
    wire = result.as_dict()["profile"]
    assert wire["limits"]["measured"] is False
    assert wire["printable_area"]["width_mm"] == 48.0


async def test_the_result_answers_every_operation_rather_than_one_boolean() -> None:
    hass = _hass()
    result = await async_render_factory_preview(hass, content=SNAPSHOT)
    assert result.eligibility["preview"].allowed is True
    assert result.eligibility["test_print"].allowed is True
    assert result.eligibility["single_print"].allowed is False
    assert result.eligibility["single_print"].blocked_by == (
        "profile_not_product_verified",
        "local_calibration_missing",
    )
    assert result.printable is result.eligibility["single_print"].allowed


async def test_the_render_context_carries_the_toolchain_that_measured_it() -> None:
    hass = _hass()
    result = await async_render_factory_preview(
        hass, content=SNAPSHOT, fonts=StubFonts()
    )
    context = result.context.as_dict()
    assert context["font_identity"] == {
        "ppb.ttf": STUB_FONT_DIGEST,
        "rbm.ttf": STUB_FONT_DIGEST,
    }
    for key in ("text_toolchain_version", "qr_model_version", "safety_policy_version"):
        assert context[key]


async def test_a_font_change_invalidates_a_cached_raster() -> None:
    """The saved layout did not move, and the old raster still cannot stand
    for the new one."""

    class _OtherFonts(StubFonts):
        def digest(self, file: str) -> str:
            return "another-font"

        def load(self, file: str, size: int):
            return replace(super().load(file, size), digest="another-font")

    hass = _hass()
    first = await async_render_factory_preview(
        hass, content=SNAPSHOT, fonts=StubFonts()
    )
    second = await async_render_factory_preview(
        hass, content=SNAPSHOT, fonts=_OtherFonts()
    )
    assert first.context.layout_digest == second.context.layout_digest
    assert first.cache_identity != second.cache_identity


async def test_calibration_is_part_of_the_identity_a_raster_is_reused_under() -> None:
    hass = _hass()
    uncalibrated = await async_render(
        hass, layout=FACTORY_50X30.layout, content=SNAPSHOT, profile=NIIMBOT_B1_50X30
    )
    calibrated = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=SNAPSHOT,
        profile=NIIMBOT_B1_50X30,
        local_calibration="cal-1",
    )
    assert uncalibrated.cache_identity != calibrated.cache_identity


async def test_safety_is_judged_even_when_no_raster_comes_back() -> None:
    """A layout that cannot print says why whether or not the printer
    integration answered."""
    hass = _hass()
    hass.services.async_call = AsyncMock(
        side_effect=HomeAssistantError("Failed to create image")
    )
    result = await async_render(
        hass,
        layout=FACTORY_50X30.layout,
        content=SNAPSHOT,
        profile=NIIMBOT_B1_50X30,
        fonts=StubFonts(),
    )
    assert result.status == "failed"
    assert result.ink
    assert result.eligibility["preview"].blocked_by == ("no_raster",)


async def test_the_safety_measurement_does_not_run_on_the_event_loop() -> None:
    hass = _hass()
    await async_render_factory_preview(hass, content=SNAPSHOT)
    assert any(
        call.args and getattr(call.args[0], "__name__", "") == "evaluate_safety"
        for call in hass.async_add_executor_job.call_args_list
    )


async def test_overlapping_ink_reaches_the_result_as_a_pair() -> None:
    from tests.labels.support import divider_element, layout_of, text_element

    layout = layout_of(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
            binding="strain.name",
            size_mm=5.0,
            minimum_mm=5.0,
        ),
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 4.0, "width_mm": 30.0, "height_mm": 0.6}
        ),
    )
    hass = _hass()
    result = await async_render(
        hass,
        layout=layout,
        content=SNAPSHOT,
        profile=NIIMBOT_B1_50X30,
        fonts=StubFonts(),
    )
    assert result.overlaps
    wire = result.as_dict()["overlaps"][0]
    assert set(wire) == {
        "first_element_id",
        "second_element_id",
        "region",
        "kind",
        "severity",
    }
