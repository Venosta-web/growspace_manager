"""Managing a Label Template once it exists (hub issue #219).

Five operations, and between them they are the whole of what an administrator
does to a template after the first publication: rename it, duplicate it, save
the open draft as a template of its own, start that draft again from a shipped
layout, and bring an older layout back.

Two properties everything here is a claim about.

**An identity is not a name, and history is not a cursor.** A rename keeps the
UUID, so every default override and every print that referenced this template
still means this template. A restore appends the old layout as a *new* head, so
the design it was taken back from is still in the history that claims to be
complete. Nothing in this route rewinds, rewrites or removes a revision.

**Each operation touches exactly one layer.** Rename and restore append saved
revisions. Duplicate and Save As mint an identity. Replacing from the factory
changes one administrator's draft and no saved state at all -- which is why it
is the one of the five that advances no generation and announces nothing. The
interface must never collapse them into a generic "reset", and neither may the
library underneath it.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30
from custom_components.growspace_manager.labels.library import (
    DUPLICATE,
    DUPLICATED,
    EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED,
    FROM_FACTORY,
    FROM_NAMED,
    OVERRIDE,
    PUBLISH,
    RENAME,
    RENAMED,
    REPLACED_FROM_FACTORY,
    RESTORE,
    RESTORED,
    SAVE_AS,
    SAVED_AS,
    DraftIsStale,
    DraftNotFound,
    DraftNotPublishable,
    DuplicateTemplateName,
    IdempotencyKeyReused,
    LabelSizeImmutable,
    LabelTemplateLibrary,
    NoFactoryTemplate,
    RevisionNotFound,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateProtected,
    TemplateRef,
    blank_document,
)
from homeassistant.core import Event, HomeAssistant

SIZE = "growspace.stock.50x30.v1"
OTHER_SIZE = "growspace.stock.50x50.v1"


async def _named_template(
    library: LabelTemplateLibrary,
    admin: Any,
    *,
    name: str = "Clone tags",
    label_size_id: str = SIZE,
) -> Any:
    """Publish one Named Template, for the tests about managing it."""
    await library.async_create_draft(admin, label_size_id=label_size_id)
    await library.async_autosave_draft(
        admin,
        label_size_id=label_size_id,
        document=blank_document(label_size_id),
        name=name,
    )
    return await library.async_publish_draft(admin, label_size_id=label_size_id)


def _edited(document: Any, *, y_mm: float) -> dict[str, Any]:
    """Return one valid layout moved somewhere, so two saves really differ."""
    moved = dict(document)
    elements = [dict(item) for item in moved["elements"]]
    elements[0] = {**elements[0], "frame": {**elements[0]["frame"], "y_mm": y_mm}}
    moved["elements"] = elements
    return moved


async def _revise(
    library: LabelTemplateLibrary, admin: Any, template_id: str, *, y_mm: float
) -> Any:
    """Append one more revision to a template, with a layout that really moved."""
    draft = await library.async_open_draft(admin, template_id)
    await library.async_autosave_draft(
        admin, template_id=template_id, document=_edited(draft.document, y_mm=y_mm)
    )
    return await library.async_publish_draft(admin, template_id=template_id)


@pytest.fixture
def changes(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Collect every library change event this instance fires."""
    seen: list[dict[str, Any]] = []

    def record(event: Event) -> None:
        seen.append(dict(event.data))

    hass.bus.async_listen(EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED, record)
    return seen


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------


async def test_a_rename_keeps_the_identity_and_the_layout(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """The name is new; the UUID, the document and its digest are not."""
    published = await _named_template(library, admin, name="Clone tags")

    renamed = await library.async_rename_template(
        admin, published.template.id, "Mother tags"
    )

    assert renamed.template.id == published.template.id
    assert renamed.revision.revision == 2
    assert renamed.revision.name == "Mother tags"
    assert renamed.revision.document == published.revision.document
    assert renamed.revision.digest == published.revision.digest
    assert renamed.revision.operation == RENAME
    assert renamed.revision.parent_revision == 1
    assert renamed.revision.provenance.source == FROM_NAMED
    assert renamed.revision.provenance.source_template_id == published.template.id
    assert renamed.revision.provenance.source_revision == 1
    assert renamed.generation == published.generation + 1
    assert changes[-1]["operation"] == RENAMED
    assert changes[-1]["revision"] == 2


async def test_a_rename_is_history_rather_than_a_rewrite(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """What the template used to be called is still readable afterwards.

    A print's audit record names the revision it used. Rewriting the name in
    place would silently change what an old print claims about itself.
    """
    published = await _named_template(library, admin, name="Clone tags")

    await library.async_rename_template(admin, published.template.id, "Mother tags")
    template = library.state.templates[published.template.id]

    assert [item.name for item in template.revisions] == ["Clone tags", "Mother tags"]
    assert [item.operation for item in template.revisions] == [PUBLISH, RENAME]
    assert template.name == "Mother tags"


async def test_a_rename_is_refused_when_the_stock_already_holds_the_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Trimmed and case-insensitively, and nothing is written."""
    first = await _named_template(library, admin, name="Clone tags")
    second = await _named_template(library, admin, name="Mother tags")
    before = library.state.generation

    with pytest.raises(DuplicateTemplateName) as refused:
        await library.async_rename_template(admin, second.template.id, " CLONE  tags ")

    assert refused.value.template_id == first.template.id
    assert library.state.generation == before
    assert library.state.templates[second.template.id].name == "Mother tags"


async def test_a_name_held_at_another_stock_is_not_a_collision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The same words on different paper are a different label."""
    await _named_template(library, admin, name="Clone tags")
    elsewhere = await _named_template(
        library, admin, name="Bench tags", label_size_id=OTHER_SIZE
    )

    renamed = await library.async_rename_template(
        admin, elsewhere.template.id, "Clone tags"
    )

    assert renamed.template.name == "Clone tags"
    assert renamed.template.label_size_id == OTHER_SIZE


async def test_renaming_a_template_to_the_name_it_has_writes_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """History records deliberate acts, not calls that asked for the status quo."""
    published = await _named_template(library, admin, name="Clone tags")
    before = len(changes)

    renamed = await library.async_rename_template(
        admin, published.template.id, "  Clone   tags  "
    )

    assert renamed.unchanged is True
    assert renamed.revision == published.revision
    assert renamed.generation == published.generation
    assert len(library.state.templates[published.template.id].revisions) == 1
    assert len(changes) == before


async def test_changing_only_the_capitalization_of_a_name_is_a_rename(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Uniqueness is case-insensitive; the stored display name is as typed."""
    published = await _named_template(library, admin, name="Clone tags")

    renamed = await library.async_rename_template(
        admin, published.template.id, "Clone Tags"
    )

    assert renamed.unchanged is False
    assert renamed.revision.name == "Clone Tags"
    assert renamed.revision.revision == 2


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
async def test_a_rename_needs_a_name(
    library: LabelTemplateLibrary, admin: Any, name: str
) -> None:
    """Whitespace is not a name a shelf can be read by."""
    published = await _named_template(library, admin)

    with pytest.raises(TemplateNameRequired):
        await library.async_rename_template(admin, published.template.id, name)


async def test_a_factory_template_cannot_be_renamed(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A shipped design belongs to the integration; a copy belongs to you."""
    with pytest.raises(TemplateProtected):
        await library.async_rename_template(admin, FACTORY_50X30.id, "Mine now")


async def test_a_rename_leaves_an_open_draft_untouched_and_stale(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The head moved, so the draft is stale -- and nobody rewrote its payload.

    A rename is a publication like any other. Its consequence for an open
    editor is the documented one rather than a special case: the work is kept
    whole and its owner reloads or saves it as a template of its own.
    """
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    edited = await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=4.0),
    )

    await library.async_rename_template(admin, published.template.id, "Mother tags")
    snapshot = await library.async_snapshot(admin)

    assert library.state.drafts[draft.key].document == edited.draft.document
    assert snapshot["drafts"][0]["stale"] is True
    assert snapshot["drafts"][0]["head_revision"] == 2
    with pytest.raises(DraftIsStale):
        await library.async_publish_draft(admin, template_id=published.template.id)


# ---------------------------------------------------------------------------
# Duplicate
# ---------------------------------------------------------------------------


async def test_a_duplicate_copies_the_saved_head_into_a_new_identity(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """A second template, at revision 1, saying where it was copied from."""
    published = await _named_template(library, admin, name="Clone tags")
    await _revise(library, admin, published.template.id, y_mm=4.0)
    head = library.state.templates[published.template.id].head

    copy = await library.async_duplicate_template(
        admin, TemplateRef.named(published.template.id), "Clone tags (spare)"
    )

    assert copy.template.id != published.template.id
    assert copy.template.name == "Clone tags (spare)"
    assert copy.template.label_size_id == SIZE
    assert copy.revision.revision == 1
    assert copy.revision.parent_revision is None
    assert copy.revision.operation == DUPLICATE
    assert copy.revision.document == head.document
    assert copy.revision.provenance.source == FROM_NAMED
    assert copy.revision.provenance.source_template_id == published.template.id
    assert copy.revision.provenance.source_revision == head.revision
    assert changes[-1]["operation"] == DUPLICATED


async def test_a_duplicate_leaves_the_template_it_copied_alone(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Copying is not an edit of the thing copied."""
    published = await _named_template(library, admin)
    before = library.state.templates[published.template.id]

    await library.async_duplicate_template(
        admin, TemplateRef.named(published.template.id), "A spare"
    )

    assert library.state.templates[published.template.id] == before


async def test_a_duplicate_copies_the_saved_head_and_not_the_open_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Duplicate and Save As are different acts and must not be one control.

    An administrator with unpublished work open who presses Duplicate is
    asking for a copy of what the library holds. Quietly copying the draft
    instead would publish work they had not chosen to publish.
    """
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=6.0),
    )

    copy = await library.async_duplicate_template(
        admin, TemplateRef.named(published.template.id), "A spare"
    )

    assert copy.revision.document == published.revision.document
    assert library.state.drafts[draft.key].version == 2


async def test_a_factory_template_can_be_duplicated(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Taking a copy is the documented way to own a shipped design."""
    copy = await library.async_duplicate_template(
        admin, TemplateRef.factory(FACTORY_50X30.id), "Shipped, but mine"
    )

    assert copy.revision.document == FACTORY_50X30.layout.as_dict()
    assert copy.revision.provenance.source == FROM_FACTORY
    assert copy.revision.provenance.factory_id == FACTORY_50X30.id
    assert copy.revision.provenance.factory_revision == FACTORY_50X30.revision
    assert copy.template.label_size_id == FACTORY_50X30.label_size_id


async def test_a_duplicate_needs_a_free_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Two templates of one stock cannot be told apart by name alone."""
    published = await _named_template(library, admin, name="Clone tags")
    before = library.state.generation

    with pytest.raises(DuplicateTemplateName):
        await library.async_duplicate_template(
            admin, TemplateRef.named(published.template.id), "clone TAGS"
        )

    assert library.state.generation == before
    assert len(library.state.templates) == 1


async def test_a_duplicate_needs_a_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A copy without a name could not be selected or found again."""
    published = await _named_template(library, admin)

    with pytest.raises(TemplateNameRequired):
        await library.async_duplicate_template(
            admin, TemplateRef.named(published.template.id), "  "
        )


async def test_duplicating_something_this_library_does_not_hold_is_not_found(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """An opaque UUID is not a way into another config entry's library."""
    with pytest.raises(TemplateNotFound):
        await library.async_duplicate_template(
            admin, TemplateRef.named("8a2e0e2e-0000-4000-8000-000000000000"), "A spare"
        )


# ---------------------------------------------------------------------------
# Save As
# ---------------------------------------------------------------------------


async def test_save_as_publishes_the_draft_under_a_new_identity_and_clears_it(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """The draft becomes revision 1 of a second template, in one commit."""
    published = await _named_template(library, admin, name="Clone tags")
    draft = await library.async_open_draft(admin, published.template.id)
    edited = await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=5.0),
    )

    saved = await library.async_save_as(
        admin, "Clone tags, tall", template_id=published.template.id
    )

    assert saved.template.id != published.template.id
    assert saved.revision.revision == 1
    assert saved.revision.operation == SAVE_AS
    assert saved.revision.document == edited.draft.document
    assert saved.revision.provenance.draft_id == draft.id
    assert saved.revision.provenance.draft_version == edited.draft.version
    assert draft.key not in library.state.drafts
    assert library.state.templates[published.template.id].revisions == (
        published.revision,
    )
    assert changes[-1]["operation"] == SAVED_AS


async def test_a_stale_draft_can_be_saved_as_a_template_of_its_own(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """The whole reason Save As exists.

    Somebody published while this draft was open. It cannot become the next
    revision without dropping theirs, and the two layouts are never merged --
    so the remaining honest outcome is that this work becomes a label of its
    own, and it must not be blocked by the staleness that sent it here.
    """
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=7.0),
    )
    await _revise(library, other_admin, published.template.id, y_mm=9.0)

    with pytest.raises(DraftIsStale):
        await library.async_publish_draft(admin, template_id=published.template.id)
    saved = await library.async_save_as(
        admin, "Clone tags, mine", template_id=published.template.id
    )

    assert saved.revision.document["elements"][0]["frame"]["y_mm"] == 7.0
    assert library.state.templates[published.template.id].head.revision == 2
    assert draft.key not in library.state.drafts


async def test_save_as_publishes_an_untitled_draft_under_the_name_it_is_given(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The name on the call wins; the draft's own is not a second opinion."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Working title"
    )

    saved = await library.async_save_as(admin, "Clone tags", label_size_id=SIZE)

    assert saved.template.name == "Clone tags"
    assert library.state.drafts == {}


async def test_save_as_refuses_a_draft_that_does_not_validate(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Being refused must not be how the work is lost."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"not": "a layout"}
    )
    before = library.state.generation

    with pytest.raises(DraftNotPublishable) as refused:
        await library.async_save_as(admin, "Clone tags", label_size_id=SIZE)

    assert refused.value.diagnostics
    assert library.state.drafts
    assert library.state.templates == {}
    assert library.state.generation == before


async def test_save_as_needs_a_free_name_and_keeps_the_draft_when_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A collision is a question to answer, not work to throw away."""
    published = await _named_template(library, admin, name="Clone tags")
    draft = await library.async_open_draft(admin, published.template.id)

    with pytest.raises(DuplicateTemplateName):
        await library.async_save_as(
            admin, "Clone tags", template_id=published.template.id
        )

    assert library.state.drafts[draft.key].id == draft.id
    assert len(library.state.templates) == 1


async def test_save_as_needs_a_draft_to_save(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """There is no implicit draft to fall back on."""
    published = await _named_template(library, admin)

    with pytest.raises(DraftNotFound):
        await library.async_save_as(
            admin, "Clone tags, spare", template_id=published.template.id
        )


async def test_a_replayed_save_as_returns_its_own_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A retry after a lost answer finds the template it already made."""
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    first = await library.async_save_as(
        admin, "Clone tags, spare", template_id=published.template.id, draft_id=draft.id
    )

    replay = await library.async_save_as(
        admin, "Clone tags, spare", template_id=published.template.id, draft_id=draft.id
    )

    assert replay.replayed is True
    assert replay.template.id == first.template.id
    assert len(library.state.templates) == 2


# ---------------------------------------------------------------------------
# Replace from factory
# ---------------------------------------------------------------------------


async def test_replacing_from_the_factory_changes_only_the_draft(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """The saved template is untouched, and nothing is announced.

    This is the acceptance criterion the operation exists for: reaching for
    the shipped design is an editing decision, and the library's saved state
    changes when that draft is published and at no other moment.
    """
    published = await _named_template(library, admin)
    before = library.state.templates[published.template.id]
    announced = len(changes)

    replaced = await library.async_replace_from_factory(admin, published.template.id)

    assert replaced.document == FACTORY_50X30.layout.as_dict()
    assert replaced.template_id == published.template.id
    assert replaced.base_revision == 1
    assert replaced.version == 1
    assert replaced.provenance.source == FROM_FACTORY
    assert replaced.provenance.factory_id == FACTORY_50X30.id
    assert replaced.provenance.factory_revision == FACTORY_50X30.revision
    assert library.state.templates[published.template.id] == before
    assert library.state.generation == published.generation
    assert len(changes) == announced


async def test_replacing_from_the_factory_keeps_what_it_replaced(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The same promise a reload makes: nothing typed is dropped."""
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    edited = await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=8.0),
    )

    replaced = await library.async_replace_from_factory(admin, published.template.id)

    assert replaced.recovery is not None
    assert replaced.recovery.reason == REPLACED_FROM_FACTORY
    assert replaced.recovery.document == edited.draft.document
    assert replaced.recovery.draft_version == edited.draft.version


async def test_replacing_from_the_factory_starts_a_draft_where_there_was_none(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Opening the editor is not a precondition for choosing where to start."""
    published = await _named_template(library, admin)

    replaced = await library.async_replace_from_factory(admin, published.template.id)

    assert replaced.recovery is None
    assert library.state.drafts[replaced.key].id == replaced.id


async def test_replacing_from_the_factory_rebases_a_stale_draft(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """A fresh draft over the current head is not stale by construction."""
    published = await _named_template(library, admin)
    await library.async_open_draft(admin, published.template.id)
    await _revise(library, other_admin, published.template.id, y_mm=3.0)

    replaced = await library.async_replace_from_factory(admin, published.template.id)
    snapshot = await library.async_snapshot(admin)

    assert replaced.base_revision == 2
    assert [item["stale"] for item in snapshot["drafts"]] == [False]


async def test_a_stock_the_integration_ships_nothing_for_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A packaging gap is named, never worked around with another size's design."""
    published = await _named_template(
        library, admin, name="Bench tags", label_size_id=OTHER_SIZE
    )

    with pytest.raises(NoFactoryTemplate) as refused:
        await library.async_replace_from_factory(admin, published.template.id)

    assert refused.value.label_size_id == OTHER_SIZE
    assert library.state.drafts == {}


async def test_a_shipped_layout_for_another_stock_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Millimetres mean something else on different paper."""
    published = await _named_template(
        library, admin, name="Bench tags", label_size_id=OTHER_SIZE
    )

    with pytest.raises(LabelSizeImmutable):
        await library.async_replace_from_factory(
            admin, published.template.id, factory_id=FACTORY_50X30.id
        )


async def test_a_shipped_layout_that_does_not_exist_is_not_found(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """An unknown factory ID is absent rather than approximated."""
    published = await _named_template(library, admin)

    with pytest.raises(TemplateNotFound):
        await library.async_replace_from_factory(
            admin, published.template.id, factory_id="growspace.factory.nothing"
        )


async def test_a_factory_template_has_no_draft_to_replace(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Shipped templates are not edited, from the factory or from anywhere."""
    with pytest.raises(TemplateProtected):
        await library.async_replace_from_factory(admin, FACTORY_50X30.id)


# ---------------------------------------------------------------------------
# Historical restore
# ---------------------------------------------------------------------------


async def test_a_restore_appends_the_old_layout_as_a_new_head(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Forward to an older design, never backwards through the history."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    await _revise(library, admin, published.template.id, y_mm=6.0)

    restored = await library.async_restore_revision(admin, published.template.id, 1)

    assert restored.revision.revision == 4
    assert restored.revision.parent_revision == 3
    assert restored.revision.operation == RESTORE
    assert restored.revision.document == published.revision.document
    assert restored.revision.digest == published.revision.digest
    assert restored.revision.provenance.source == FROM_NAMED
    assert restored.revision.provenance.source_template_id == published.template.id
    assert restored.revision.provenance.source_revision == 1
    assert changes[-1]["operation"] == RESTORED


async def test_a_restore_leaves_every_revision_it_reached_past(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The design it was taken back *from* is still in the history."""
    published = await _named_template(library, admin)
    second = await _revise(library, admin, published.template.id, y_mm=4.0)

    await library.async_restore_revision(admin, published.template.id, 1)
    template = library.state.templates[published.template.id]

    assert [item.revision for item in template.revisions] == [1, 2, 3]
    assert template.revisions[1] == second.revision
    assert [item.operation for item in template.revisions] == [
        PUBLISH,
        PUBLISH,
        RESTORE,
    ]


async def test_a_restore_brings_back_the_layout_and_not_the_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Content and identity are separate axes, and only one was asked about."""
    published = await _named_template(library, admin, name="Clone tags")
    await _revise(library, admin, published.template.id, y_mm=4.0)
    await library.async_rename_template(admin, published.template.id, "Mother tags")

    restored = await library.async_restore_revision(admin, published.template.id, 1)

    assert restored.revision.name == "Mother tags"
    assert restored.revision.document == published.revision.document


async def test_restoring_the_revision_that_is_already_the_head_writes_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Asking for what is already true is not a deliberate act to record."""
    published = await _named_template(library, admin)
    second = await _revise(library, admin, published.template.id, y_mm=4.0)
    announced = len(changes)

    restored = await library.async_restore_revision(admin, published.template.id, 2)

    assert restored.unchanged is True
    assert restored.revision == second.revision
    assert restored.generation == second.generation
    assert len(library.state.templates[published.template.id].revisions) == 2
    assert len(changes) == announced


async def test_restoring_a_revision_that_was_never_published_is_not_found(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A reference to something that never existed says exactly that."""
    published = await _named_template(library, admin)

    with pytest.raises(RevisionNotFound):
        await library.async_restore_revision(admin, published.template.id, 7)


async def test_a_revision_that_no_longer_validates_cannot_be_restored(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """History is preserved; making it the head is a different question.

    A revision the catalogues have moved past stays exactly where it is and
    stays readable. Putting it in front of every print that resolves this
    template would be repairing nothing and breaking something.
    """
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    state = library.state
    template = state.templates[published.template.id]
    damaged = replace(
        template.revisions[0], document={"schema": "growspace.label-layout"}
    )
    await library._store.async_save(
        replace(
            state,
            templates={
                **state.templates,
                template.id: replace(
                    template, revisions=(damaged, *template.revisions[1:])
                ),
            },
        )
    )
    reopened = libraries()
    await reopened.async_load()

    with pytest.raises(TemplateNotResolvable) as refused:
        await reopened.async_restore_revision(admin, template.id, 1)

    assert refused.value.revision == 1
    assert refused.value.diagnostics
    assert len(reopened.state.templates[template.id].revisions) == 2


async def test_a_factory_template_has_no_history_to_restore(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A shipped template's revisions are the integration's, not a history."""
    with pytest.raises(TemplateProtected):
        await library.async_restore_revision(admin, FACTORY_50X30.id, 1)


async def test_a_restore_leaves_an_open_draft_untouched(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Somebody else's unpublished work is not part of what a restore decides."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    draft = await library.async_open_draft(admin, published.template.id)

    await library.async_restore_revision(admin, published.template.id, 1)

    assert library.state.drafts[draft.key].document == draft.document
    assert library.state.drafts[draft.key].base_revision == 2


# ---------------------------------------------------------------------------
# What all of this does to the Effective Default
# ---------------------------------------------------------------------------


async def test_an_override_follows_the_identity_through_a_rename(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """A default selects a UUID, so no display name can move it."""
    published = await _named_template(library, admin, name="Clone tags")
    ref = TemplateRef.named(published.template.id)
    await library.async_set_default(admin, SIZE, ref)

    await library.async_rename_template(admin, published.template.id, "Mother tags")
    resolved = await library.async_resolve_default(viewer, SIZE)

    assert library.state.defaults[SIZE] == ref
    assert resolved.ref == ref
    assert resolved.revision == 2
    assert resolved.name == "Mother tags"
    assert resolved.via == OVERRIDE


async def test_an_override_resolves_to_the_restored_layout(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Restoring is how the selected default goes back to an older design."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )

    await library.async_restore_revision(admin, published.template.id, 1)
    resolved = await library.async_resolve_default(viewer, SIZE)

    assert resolved.revision == 3
    assert resolved.document == published.revision.document
    assert resolved.layout.digest == published.revision.digest


@pytest.mark.parametrize("operation", ["duplicate", "save_as", "replace_from_factory"])
async def test_the_selected_default_is_never_moved_by_an_operation_on_something_else(
    library: LabelTemplateLibrary, admin: Any, viewer: Any, operation: str
) -> None:
    """Minting an identity and editing a draft both leave the selection alone."""
    published = await _named_template(library, admin, name="Clone tags")
    ref = TemplateRef.named(published.template.id)
    await library.async_set_default(admin, SIZE, ref)
    await library.async_open_draft(admin, published.template.id)

    if operation == "duplicate":
        await library.async_duplicate_template(admin, ref, "A spare")
    elif operation == "save_as":
        await library.async_save_as(admin, "A spare", template_id=published.template.id)
    else:
        await library.async_replace_from_factory(admin, published.template.id)
    resolved = await library.async_resolve_default(viewer, SIZE)

    assert library.state.defaults[SIZE] == ref
    assert resolved.ref == ref
    assert resolved.revision == 1
    assert resolved.document == published.revision.document


async def test_a_resolution_is_captured_and_does_not_follow_later_changes(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """One operation, one revision. A rename mid-print cannot reach into it."""
    published = await _named_template(library, admin, name="Clone tags")
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    captured = await library.async_resolve_default(viewer, SIZE)

    await library.async_rename_template(admin, published.template.id, "Mother tags")
    await library.async_restore_revision(admin, published.template.id, 1)

    assert captured.revision == 1
    assert captured.name == "Clone tags"
    assert captured.document == published.revision.document


# ---------------------------------------------------------------------------
# A management operation is one commit, and a retry is not a second one
# ---------------------------------------------------------------------------

#: Every management operation, as the call a client would make with a key.
#: Parametrized rather than written out, because each property below is a
#: property of all five -- and an operation added without a row here is the
#: gap this shape exists to make obvious.
MANAGEMENT: dict[
    str,
    Callable[[LabelTemplateLibrary, Any, str, str], Coroutine[Any, Any, Any]],
] = {
    "rename": lambda lib, actor, template_id, key: lib.async_rename_template(
        actor, template_id, "Mother tags", idempotency_key=key
    ),
    "duplicate": lambda lib, actor, template_id, key: lib.async_duplicate_template(
        actor, TemplateRef.named(template_id), "A spare", idempotency_key=key
    ),
    "save_as": lambda lib, actor, template_id, key: lib.async_save_as(
        actor, "A spare", template_id=template_id, idempotency_key=key
    ),
    "replace_from_factory": (
        lambda lib, actor, template_id, key: lib.async_replace_from_factory(
            actor, template_id, idempotency_key=key
        )
    ),
    "restore": lambda lib, actor, template_id, key: lib.async_restore_revision(
        actor, template_id, 1, idempotency_key=key
    ),
}


async def _manageable(library: LabelTemplateLibrary, admin: Any) -> str:
    """A template with history and an open draft, so all five calls apply."""
    published = await _named_template(library, admin, name="Clone tags")
    await _revise(library, admin, published.template.id, y_mm=4.0)
    await library.async_open_draft(admin, published.template.id)
    return str(published.template.id)


@pytest.mark.parametrize("operation", list(MANAGEMENT), ids=list(MANAGEMENT))
async def test_a_replayed_management_call_performs_nothing_a_second_time(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """A retry of a call whose answer was lost finds the first attempt."""
    template_id = await _manageable(library, admin)
    first = await MANAGEMENT[operation](library, admin, template_id, "key-1")
    after = library.state

    replay = await MANAGEMENT[operation](library, admin, template_id, "key-1")

    assert library.state.generation == after.generation
    assert len(library.state.templates) == len(after.templates)
    if hasattr(replay, "replayed"):
        assert replay.replayed is True
        assert replay.template.id == first.template.id
        assert replay.revision.revision == first.revision.revision
    else:
        assert replay.id == first.id


@pytest.mark.parametrize("operation", list(MANAGEMENT), ids=list(MANAGEMENT))
async def test_a_failed_commit_leaves_the_library_exactly_as_it_was(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """The next state is published only once the write returned."""
    template_id = await _manageable(library, admin)
    before = library.state

    with (
        patch.object(
            library._store,
            "async_save",
            AsyncMock(side_effect=OSError("disk full")),
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await MANAGEMENT[operation](library, admin, template_id, "key-1")

    assert library.state is before


@pytest.mark.parametrize("operation", list(MANAGEMENT), ids=list(MANAGEMENT))
async def test_a_key_spent_on_a_different_call_is_refused(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """Performing the second call under the first one's key is the one bad answer."""
    template_id = await _manageable(library, admin)
    await MANAGEMENT[operation](library, admin, template_id, "key-1")

    with pytest.raises(IdempotencyKeyReused):
        await library.async_duplicate_template(
            admin,
            TemplateRef.named(template_id),
            "Something else entirely",
            idempotency_key="key-1",
        )


@pytest.mark.parametrize("operation", list(MANAGEMENT), ids=list(MANAGEMENT))
async def test_a_management_call_survives_a_restart(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, operation: str
) -> None:
    """What was committed is what the next instance reads back."""
    library = libraries()
    await library.async_load()
    template_id = await _manageable(library, admin)
    await MANAGEMENT[operation](library, admin, template_id, "key-1")
    expected = library.state

    reopened = libraries()
    await reopened.async_load()

    assert reopened.state.as_dict() == expected.as_dict()
