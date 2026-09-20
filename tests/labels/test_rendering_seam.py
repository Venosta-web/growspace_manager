"""Tests for the canonical label rendering seam (hub issue #213).

The golden suite in `tests/services/test_print_label_golden.py` proves the
Classic output is unchanged. These tests prove the *shape* that makes it safe
to change later: one renderer, pure and printer-blind, reached by every caller.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.labels.classic import (
    _canonical_size,
    resolve_classic_request,
)
from custom_components.growspace_manager.labels.model import (
    Canvas,
    LabelContent,
    Logo,
    QrCode,
    TextBlock,
    TextLine,
)
from custom_components.growspace_manager.labels.renderer import (
    LABEL_SIZE_CANVASES,
    REFERENCE_CANVAS,
    canvas_for,
    render,
)
from custom_components.growspace_manager.services.strain_library import (
    handle_print_label,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

CONTENT = LabelContent(
    title="Blue Dream",
    info_lines=("Pheno A", "Humboldt"),
    logo="http://example.test/logo.png",
    qr_data="http://ha.test/plant/p1",
    printed_on="18.09.2026",
)


# ---------------------------------------------------------------------------
# The renderer is pure
# ---------------------------------------------------------------------------


def test_rendering_needs_no_home_assistant_and_no_printer() -> None:
    """`render` takes resolved content and returns geometry. That is all."""
    plan = render(CONTENT, label_size="50x30", density="normal")
    assert plan.canvas == REFERENCE_CANVAS
    assert plan.density == "normal"


def test_the_same_content_renders_identically_every_time() -> None:
    """Determinism is what lets a preview stand in for the print."""
    first = render(CONTENT, label_size="50x50", density="high")
    second = render(CONTENT, label_size="50x50", density="high")
    assert first == second


def test_density_reaches_the_plan_unmapped() -> None:
    """Density is a printer's business; the renderer only carries the word."""
    assert render(CONTENT, label_size=None, density="scorching").density == "scorching"


# ---------------------------------------------------------------------------
# Composition follows the content snapshot rather than re-deciding it
# ---------------------------------------------------------------------------


def test_suppressed_logo_and_qr_leave_no_element_behind() -> None:
    bare = LabelContent(
        title="Blue Dream",
        info_lines=(),
        logo=None,
        qr_data=None,
        printed_on="18.09.2026",
    )
    kinds = {
        type(element)
        for element in render(bare, label_size=None, density="normal").elements
    }
    assert Logo not in kinds
    assert QrCode not in kinds


def test_the_title_is_the_only_thing_the_renderer_restyles() -> None:
    """Upper-casing is presentation, so it belongs here and not in content."""
    plan = render(CONTENT, label_size=None, density="normal")
    title = next(e for e in plan.elements if isinstance(e, TextBlock))
    assert title.value == "BLUE DREAM"


def test_info_lines_are_joined_in_the_order_the_caller_filtered_them() -> None:
    plan = render(CONTENT, label_size=None, density="normal")
    body = [e for e in plan.elements if isinstance(e, TextBlock)][1]
    assert body.value == "Pheno A\nHumboldt"


# ---------------------------------------------------------------------------
# Label sizes and scaling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label_size", sorted(LABEL_SIZE_CANVASES))
def test_each_supported_size_places_its_own_canvas(label_size: str) -> None:
    plan = render(CONTENT, label_size=label_size, density="normal")
    assert plan.canvas == LABEL_SIZE_CANVASES[label_size]


def test_an_unknown_or_absent_size_keeps_the_documented_default() -> None:
    """Classic callers have always been allowed to send a size we don't know."""
    assert canvas_for(None) == REFERENCE_CANVAS
    assert canvas_for("99x99") == REFERENCE_CANVAS


def test_scaling_moves_geometry_and_leaves_typography_alone() -> None:
    """Font size and QR module size are already fitted; scaling them twice is wrong."""
    reference = render(CONTENT, label_size="50x30", density="normal")
    tall = render(CONTENT, label_size="50x80", density="normal")

    reference_qr = next(e for e in reference.elements if isinstance(e, QrCode))
    tall_qr = next(e for e in tall.elements if isinstance(e, QrCode))
    assert tall_qr.y == round(reference_qr.y * 640 / 240)
    assert tall_qr.boxsize == reference_qr.boxsize

    reference_stamp = next(e for e in reference.elements if isinstance(e, TextLine))
    tall_stamp = next(e for e in tall.elements if isinstance(e, TextLine))
    assert tall_stamp.size == reference_stamp.size


def test_scaling_to_the_canvas_a_plan_already_has_changes_nothing() -> None:
    plan = render(CONTENT, label_size="50x30", density="normal")
    assert plan.scaled_to(Canvas(width=400, height=240)) is plan


# ---------------------------------------------------------------------------
# The Classic adapter resolves once, and stores nothing
# ---------------------------------------------------------------------------


def _world(plants: dict[str, Any] | None = None, library: dict[str, Any] | None = None):
    hass = MagicMock(spec=HomeAssistant)
    coordinator = MagicMock()
    coordinator.plants = plants or {}
    strain_library = MagicMock()
    strain_library.load = AsyncMock()
    strain_library.get_all = MagicMock(return_value=library or {})
    return hass, coordinator, strain_library


def _plant(strain: str = "Northern Lights", phenotype: str | None = "Pheno A"):
    return SimpleNamespace(
        genetics=SimpleNamespace(strain_name=strain, phenotype_name=phenotype)
    )


@pytest.mark.asyncio
async def test_a_classic_request_writes_nothing() -> None:
    """A compatibility print is transient: no revision, draft, default, or save."""
    hass, coordinator, strain_library = _world()
    request = await resolve_classic_request(
        hass, coordinator, strain_library, {"strain": "Gelato"}
    )

    # Loading the library and reading it is the whole of its effect on the world.
    assert {call[0] for call in strain_library.mock_calls} == {"load", "get_all"}
    # A strain request never even reaches the coordinator.
    assert coordinator.mock_calls == []
    assert request.layout_id == "growspace.classic-layout.v1"
    assert request.label_size_id == "growspace.stock.50x30.v1"


@pytest.mark.asyncio
async def test_classic_sizes_map_to_canonical_stock_identities() -> None:
    hass, coordinator, strain_library = _world()
    request = await resolve_classic_request(
        hass,
        coordinator,
        strain_library,
        {"strain": "Gelato", "label_size": "50x80"},
    )
    assert request.label_size_id == "growspace.stock.50x80.v1"


@pytest.mark.asyncio
async def test_an_unknown_classic_size_keeps_the_documented_default_identity() -> None:
    hass, coordinator, strain_library = _world()
    request = await resolve_classic_request(
        hass,
        coordinator,
        strain_library,
        {"strain": "Gelato", "label_size": "99x99"},
    )
    assert request.label_size_id == "growspace.stock.50x30.v1"


def test_a_broken_catalogue_cannot_invent_a_classic_default() -> None:
    with patch(
        "custom_components.growspace_manager.labels.classic.LABEL_SIZES",
        {},
    ):
        with pytest.raises(RuntimeError, match="default Label Size is absent"):
            _canonical_size(None)


@pytest.mark.asyncio
async def test_a_missing_plant_is_refused_before_anything_is_rendered() -> None:
    hass, coordinator, strain_library = _world()
    with pytest.raises(HomeAssistantError, match="Plant ghost not found"):
        await resolve_classic_request(
            hass, coordinator, strain_library, {"plant_id": "ghost"}
        )


@pytest.mark.asyncio
async def test_a_request_with_no_subject_is_refused() -> None:
    hass, coordinator, strain_library = _world()
    with pytest.raises(HomeAssistantError, match="Neither plant_id nor strain"):
        await resolve_classic_request(hass, coordinator, strain_library, {})


@pytest.mark.asyncio
async def test_a_strain_label_carries_no_qr_however_it_is_flagged() -> None:
    """There is no instance to point a strain's QR code at."""
    hass, coordinator, strain_library = _world()
    request = await resolve_classic_request(
        hass, coordinator, strain_library, {"strain": "Gelato", "fields": {"qr": True}}
    )
    assert request.content.qr_data is None


@pytest.mark.asyncio
async def test_caller_overrides_win_over_library_meta() -> None:
    hass, coordinator, strain_library = _world(
        library={"Gelato": {"meta": {"breeder": "Cookie Fam", "lineage": "SS x TK"}}}
    )
    request = await resolve_classic_request(
        hass, coordinator, strain_library, {"strain": "Gelato", "breeder": "Mine"}
    )
    assert request.content.info_lines == ("Mine", "SS x TK")


@pytest.mark.asyncio
async def test_placeholder_values_never_reach_the_label_as_text() -> None:
    """The card sends "-" for "nothing recorded"; printing it would be a lie."""
    hass, coordinator, strain_library = _world()
    request = await resolve_classic_request(
        hass,
        coordinator,
        strain_library,
        {"strain": "Gelato", "breeder": "-", "lineage": "–"},
    )
    assert request.content.info_lines == ()


# ---------------------------------------------------------------------------
# Every caller reaches the seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_service_handler_composes_only_through_the_renderer() -> None:
    """Strain, plant and every batch item share one `print_label`, one `render`."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))

    coordinator = MagicMock()
    coordinator.plants = {"p1": _plant()}
    strain_library = MagicMock()
    strain_library.load = AsyncMock()
    strain_library.get_all = MagicMock(return_value={})

    call = MagicMock(spec=ServiceCall)
    call.data = {"plant_id": "p1", "label_size": "50x50", "density": "high"}

    with (
        patch(
            "custom_components.growspace_manager.labels.classic.get_url",
            return_value="http://ha.test",
        ),
        patch(
            "custom_components.growspace_manager.labels.classic.render",
            wraps=render,
        ) as spy,
    ):
        await handle_print_label(hass, coordinator, strain_library, call)

    spy.assert_called_once()
    content = spy.call_args.args[0]
    assert isinstance(content, LabelContent)
    assert content.title == "Northern Lights"
    assert spy.call_args.kwargs == {"label_size": "50x50", "density": "high"}
