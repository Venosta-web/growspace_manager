"""Previewing a draft and a published revision (hub issue #217).

There is one render operation, and this is it reached with a draft instead of
a record: the same compiler, the same safety pass, the same adapter payload and
the same decoded raster a print produces. A preview that took any other path
would be a second renderer, and a second renderer is the fidelity bug the
canonical seam exists to end.

What a preview may *not* do is stand in for validation. A document that does
not pass the document layer cannot be compiled at all, so the diagnostics come
back as a refusal rather than as an approximate picture of an invalid layout.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    PREVIEW,
    SPARSE_STRAIN,
)
from custom_components.growspace_manager.labels.library import (
    DraftNotPublishable,
    LabelTemplateLibrary,
    TemplateRef,
    blank_document,
)
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from tests.labels.support import StubFonts

SIZE = "growspace.stock.50x30.v1"
UNSHIPPED_SIZE = "growspace.stock.50x50.v1"


async def _named_template(
    library: LabelTemplateLibrary,
    admin: Any,
    *,
    name: str = "Clone tags",
    label_size_id: str = SIZE,
) -> Any:
    """Publish one Named Template of a given stock."""
    await library.async_create_draft(admin, label_size_id=label_size_id)
    await library.async_autosave_draft(
        admin,
        label_size_id=label_size_id,
        document=blank_document(label_size_id),
        name=name,
    )
    return await library.async_publish_draft(admin, label_size_id=label_size_id)


async def test_previewing_a_draft_reaches_the_adapter(
    library: LabelTemplateLibrary, admin: Any, printer: list[dict[str, Any]]
) -> None:
    """The raster comes back decoded, attributable, and marked as a preview."""
    document = blank_document(SIZE)
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=document, name="Clone tags"
    )

    result = await library.async_preview_draft(
        admin, label_size_id=SIZE, fonts=StubFonts()
    )

    assert result.raster is not None
    assert result.raster.monochrome is True
    assert result.context.operation == PREVIEW
    assert result.context.layout_digest
    assert len(printer) == 1
    assert printer[0]["preview"] is True
    assert printer[0]["payload"]


async def test_a_draft_preview_is_of_the_draft(
    library: LabelTemplateLibrary, admin: Any, printer: list[dict[str, Any]]
) -> None:
    """Unpublished work is what the editor is looking at, not the saved base."""
    published = await _named_template(library, admin)
    await library.async_open_draft(admin, published.template.id)
    moved = blank_document(SIZE)
    moved["elements"][0]["frame"]["x_mm"] = 4.0
    edited = await library.async_autosave_draft(
        admin, template_id=published.template.id, document=moved
    )

    draft_preview = await library.async_preview_draft(
        admin, template_id=published.template.id, fonts=StubFonts()
    )
    saved_preview = await library.async_preview_template(
        admin, TemplateRef.named(published.template.id), fonts=StubFonts()
    )

    assert edited.check.publishable is True
    assert draft_preview.context.layout_digest != saved_preview.context.layout_digest
    assert saved_preview.context.layout_digest == published.revision.digest


async def test_previewing_an_invalid_draft_reports_the_diagnostics(
    library: LabelTemplateLibrary, admin: Any, printer: list[dict[str, Any]]
) -> None:
    """No picture of an invalid layout, and nothing sent to the printer."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"nothing": "yet"}, name="Clone tags"
    )

    with pytest.raises(DraftNotPublishable) as refusal:
        await library.async_preview_draft(admin, label_size_id=SIZE)

    assert refusal.value.diagnostics
    assert printer == []


async def test_previewing_a_draft_changes_nothing(
    library: LabelTemplateLibrary, admin: Any, printer: list[dict[str, Any]]
) -> None:
    """Looking at a label is not publishing one."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    before = library.state

    await library.async_preview_draft(admin, label_size_id=SIZE, fonts=StubFonts())

    assert library.state is before
    assert library.state.templates == {}


async def test_a_factory_template_previews_against_any_representative_subject(
    library: LabelTemplateLibrary, viewer: Any, printer: list[dict[str, Any]]
) -> None:
    """The shipped layout, and a subject with every optional value absent."""
    result = await library.async_preview_template(
        viewer,
        TemplateRef.factory(FACTORY_50X30.id),
        subject=SPARSE_STRAIN,
        fonts=StubFonts(),
    )

    assert result.raster is not None
    assert result.context.layout_digest == FACTORY_50X30.layout.digest
    assert result.context.content_context == str(SPARSE_STRAIN.context)
    assert result.context.content_identity


async def test_a_stock_with_no_capability_profile_says_which_is_missing(
    library: LabelTemplateLibrary, admin: Any, printer: list[dict[str, Any]]
) -> None:
    """A layout can be perfectly valid and still have nothing to render it on."""
    await library.async_create_draft(admin, label_size_id=UNSHIPPED_SIZE)

    with pytest.raises(HomeAssistantError, match="Capability Profile"):
        await library.async_preview_draft(
            admin, label_size_id=UNSHIPPED_SIZE, fonts=StubFonts()
        )


async def test_a_non_administrator_cannot_preview_a_draft(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """A test print of unpublished work is a management operation."""
    await library.async_create_draft(admin, label_size_id=SIZE)

    with pytest.raises(Unauthorized):
        await library.async_preview_draft(viewer, label_size_id=SIZE)
