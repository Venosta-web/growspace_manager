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
    FACTORY_50X30,
    NIIMBOT_B1_50X30,
    PRINT,
    TYPICAL_STRAIN,
    ProfileEvidence,
    async_render,
    async_render_factory_preview,
)
from custom_components.growspace_manager.labels.canonical.preview import _decode_raster
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

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
        "render_context",
        "raster",
        "elements",
        "diagnostics",
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
