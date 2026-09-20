"""Creating, editing and publishing a Named Label Template (hub issue #217).

The route from "an administrator wants a label of their own" to "a revision
other people's prints resolve to", and the refusals along the way.

Two properties most of this is about. A **draft keeps whatever it is given** --
an autosave that dropped invalid work would make every diagnostic a threat to
the work, and half of editing is passing through states that do not validate.
And a **publication is one commit**: the revision appears, the draft is gone
and the generation has advanced, or none of those things happened.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    LABEL_SIZES,
    REQUIRED_BINDING,
    LabelSize,
    validate_document,
)
from custom_components.growspace_manager.labels.library import (
    FROM_BLANK,
    FROM_FACTORY,
    FROM_NAMED,
    PUBLISH,
    DraftNotFound,
    DraftNotPublishable,
    DuplicateTemplateName,
    LabelSizeImmutable,
    LabelTemplateError,
    LabelTemplateLibrary,
    TemplateNameRequired,
    TemplateProtected,
    TemplateRef,
    UnsupportedLabelSize,
    blank_document,
    blank_layout,
)

SIZE = "growspace.stock.50x30.v1"
OTHER_SIZE = "growspace.stock.50x50.v1"


async def _named_template(
    library: LabelTemplateLibrary, admin: Any, *, name: str = "Clone tags"
) -> Any:
    """Publish one Named Template the short way, for tests about what follows."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name=name
    )
    return await library.async_publish_draft(admin, label_size_id=SIZE)


# ---------------------------------------------------------------------------
# Starting a draft
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label_size_id", list(LABEL_SIZES))
async def test_a_blank_draft_is_valid_by_construction(
    library: LabelTemplateLibrary, admin: Any, label_size_id: str
) -> None:
    """Every stock's blank draft validates, and carries the required element.

    A blank draft that had to be corrected before it could be published would
    make the first thing a new template does a refusal.
    """
    draft = await library.async_create_draft(admin, label_size_id=label_size_id)

    validation = validate_document(draft.document)
    assert validation.diagnostics == ()
    assert validation.layout is not None
    assert validation.layout.label_size_id == label_size_id
    assert [
        element.content.binding
        for element in validation.layout.elements
        if getattr(element.content, "binding", None)
    ] == [REQUIRED_BINDING]
    assert draft.provenance.source == FROM_BLANK
    assert draft.is_untitled


async def test_a_blank_draft_needs_the_stock_it_is_for(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Millimetres mean nothing without the paper they are on."""
    with pytest.raises(Exception, match="Label Size it is for"):
        await library.async_create_draft(admin)


async def test_two_blank_drafts_do_not_share_an_element_identity(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Element IDs are per-document, so two blanks cannot address one element."""
    first = await library.async_create_draft(admin, label_size_id=SIZE)
    second = await library.async_create_draft(other_admin, label_size_id=SIZE)

    assert first.document["elements"][0]["id"] != second.document["elements"][0]["id"]


async def test_a_draft_derived_from_the_factory_copies_its_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Deriving is copying: the shipped layout arrives, with its identity recorded."""
    draft = await library.async_create_draft(
        admin, derive_from=TemplateRef.factory(FACTORY_50X30.id)
    )

    assert draft.document == FACTORY_50X30.layout.as_dict()
    assert draft.label_size_id == FACTORY_50X30.label_size_id
    assert draft.provenance.source == FROM_FACTORY
    assert draft.provenance.factory_id == FACTORY_50X30.id
    assert draft.provenance.factory_revision == FACTORY_50X30.revision


async def test_a_draft_derived_from_a_named_template_records_its_source(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A copy of somebody's template says which revision of it it came from."""
    published = await _named_template(library, admin)

    draft = await library.async_create_draft(
        admin, derive_from=TemplateRef.named(published.template.id)
    )

    assert draft.is_untitled
    assert draft.provenance.source == FROM_NAMED
    assert draft.provenance.source_template_id == published.template.id
    assert draft.provenance.source_revision == 1


async def test_deriving_into_a_different_stock_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A design is not converted between stocks by asking for it on other paper."""
    with pytest.raises(LabelSizeImmutable):
        await library.async_create_draft(
            admin,
            label_size_id=OTHER_SIZE,
            derive_from=TemplateRef.factory(FACTORY_50X30.id),
        )


async def test_opening_a_template_starts_a_draft_at_its_head(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Editing a saved template gives a draft bound to it, based on its head."""
    published = await _named_template(library, admin)

    draft = await library.async_open_draft(admin, published.template.id)

    assert draft.template_id == published.template.id
    assert draft.base_revision == 1
    assert draft.document == published.revision.document
    assert not draft.is_untitled


async def test_opening_a_template_twice_returns_the_same_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Opening an editor is not a claim, and must not discard what is there."""
    published = await _named_template(library, admin)
    first = await library.async_open_draft(admin, published.template.id)
    edited = await library.async_autosave_draft(
        admin, template_id=published.template.id, document={"half": "written"}
    )

    reopened = await library.async_open_draft(admin, published.template.id)

    assert reopened.id == first.id
    assert reopened.document == edited.draft.document


async def test_two_administrators_get_their_own_draft_of_one_template(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """A draft is private, so the same base revision yields two of them."""
    published = await _named_template(library, admin)

    mine = await library.async_open_draft(admin, published.template.id)
    theirs = await library.async_open_draft(other_admin, published.template.id)

    assert mine.id != theirs.id
    assert mine.base_revision == theirs.base_revision == 1


async def test_a_factory_template_cannot_be_opened_as_a_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A shipped template belongs to the integration, not to the library."""
    with pytest.raises(TemplateProtected):
        await library.async_open_draft(admin, FACTORY_50X30.id)


# ---------------------------------------------------------------------------
# Opening an editor (hub issue #225)
# ---------------------------------------------------------------------------


async def test_opening_an_editor_resumes_an_untitled_draft_rather_than_replacing_it(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One untitled draft per administrator and stock *is* the slot, so an
    editor that opened by creating would destroy the work it reopened."""
    first, created = await library.async_open_editing_draft(
        admin, label_size_id=FACTORY_50X30.label_size_id
    )
    await library.async_autosave_draft(
        admin,
        label_size_id=FACTORY_50X30.label_size_id,
        document={"mid": "edit"},
    )

    resumed, again = await library.async_open_editing_draft(
        admin, label_size_id=FACTORY_50X30.label_size_id
    )

    assert created is False
    assert again is True
    assert resumed.id == first.id
    assert resumed.document == {"mid": "edit"}


async def test_resuming_ignores_the_template_it_was_asked_to_derive_from(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Re-deriving over unsaved work is the same destruction with an argument."""
    await library.async_open_editing_draft(
        admin, label_size_id=FACTORY_50X30.label_size_id
    )
    await library.async_autosave_draft(
        admin, label_size_id=FACTORY_50X30.label_size_id, document={"mine": True}
    )

    resumed, again = await library.async_open_editing_draft(
        admin,
        label_size_id=FACTORY_50X30.label_size_id,
        derive_from=TemplateRef.factory(FACTORY_50X30.id),
    )

    assert again is True
    assert resumed.document == {"mine": True}


async def test_opening_an_editor_on_a_template_reports_whether_it_resumed(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    published = await _named_template(library, admin)

    first, created = await library.async_open_editing_draft(
        admin, template_id=published.template.id
    )
    again, resumed = await library.async_open_editing_draft(
        admin, template_id=published.template.id
    )

    assert created is False
    assert resumed is True
    assert again.id == first.id


async def test_opening_an_editor_needs_a_template_or_a_label_size(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Neither addresses a slot, and guessing one would open somebody's work."""
    with pytest.raises(LabelTemplateError):
        await library.async_open_editing_draft(admin)


# ---------------------------------------------------------------------------
# Autosave keeps the work
# ---------------------------------------------------------------------------


async def test_autosave_keeps_invalid_work_and_says_why(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The draft is stored whatever state it is in; the check explains it."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    broken: dict[str, Any] = {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": SIZE,
        "elements": [],
    }

    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=broken
    )

    assert saved.draft.document == broken
    assert saved.draft.version == 2
    assert saved.check.publishable is False
    assert "document.missing_required_strain_name" in {
        item.code for item in saved.check.diagnostics
    }


async def test_autosave_keeps_something_that_is_not_a_document_at_all(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A draft payload is opaque: this layer never inspects it to store it."""
    await library.async_create_draft(admin, label_size_id=SIZE)

    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document="mid-edit, not JSON yet"
    )

    assert saved.draft.document == "mid-edit, not JSON yet"
    assert saved.check.publishable is False


async def test_invalid_work_survives_a_restart(libraries: Any, admin: Any) -> None:
    """Acceptance case 7: the draft comes back, and still cannot be published."""
    first = libraries()
    await first.async_load()
    await first.async_create_draft(admin, label_size_id=SIZE)
    await first.async_autosave_draft(
        admin, label_size_id=SIZE, document={"still": "broken"}, name="Work in progress"
    )

    reopened = libraries()
    await reopened.async_load()

    saved = await reopened.async_autosave_draft(
        admin, label_size_id=SIZE, document={"still": "broken"}
    )
    assert saved.draft.name == "Work in progress"
    assert saved.check.publishable is False
    with pytest.raises(DraftNotPublishable):
        await reopened.async_publish_draft(admin, label_size_id=SIZE)


async def test_autosave_does_not_advance_the_library_generation(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A keystroke is not a library change, and no other client can see it."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    before = library.state.generation

    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE)
    )

    assert library.state.generation == before


async def test_a_template_bound_draft_cannot_be_given_a_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Renaming a template is its own operation, not a side effect of a save."""
    published = await _named_template(library, admin)
    await library.async_open_draft(admin, published.template.id)

    with pytest.raises(Exception, match="renaming"):
        await library.async_autosave_draft(
            admin,
            template_id=published.template.id,
            document=blank_document(SIZE),
            name="Something else",
        )


async def test_discarding_a_draft_leaves_every_other_one(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Explicit, and narrow: one administrator's one draft."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_create_draft(other_admin, label_size_id=SIZE)

    discarded = await library.async_discard_draft(admin, label_size_id=SIZE)

    assert discarded.owner == admin.user_id
    assert [draft.owner for draft in library.state.drafts.values()] == [
        other_admin.user_id
    ]
    with pytest.raises(DraftNotFound):
        await library.async_discard_draft(admin, label_size_id=SIZE)


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


async def test_publishing_an_untitled_draft_creates_a_template(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Revision 1 of a new UUID, signed, with the draft it came from recorded."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="  Clone tags  "
    )

    published = await library.async_publish_draft(admin, label_size_id=SIZE)

    assert published.replayed is False
    assert published.revision.revision == 1
    assert published.revision.parent_revision is None
    assert published.revision.operation == PUBLISH
    assert published.revision.published_by == admin.user_id
    # The name is stored trimmed, and otherwise exactly as it was typed.
    assert published.template.name == "Clone tags"
    assert published.revision.provenance.draft_id == saved.draft.id
    assert published.revision.provenance.draft_version == saved.draft.version
    assert published.revision.digest == published.template.head.digest


async def test_publishing_clears_the_draft_and_advances_the_generation(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One commit: the revision, the empty slot and the generation together."""
    before = library.state.generation
    published = await _named_template(library, admin)

    assert library.state.drafts == {}
    assert library.state.generation == before + 1
    assert list(library.state.templates) == [published.template.id]


async def test_publishing_a_template_bound_draft_appends_a_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """History grows; the identity and the name do not move."""
    first = await _named_template(library, admin)
    await library.async_open_draft(admin, first.template.id)
    changed = blank_document(SIZE)
    changed["elements"][0]["frame"]["x_mm"] = 3.0
    await library.async_autosave_draft(
        admin, template_id=first.template.id, document=changed
    )

    second = await library.async_publish_draft(admin, template_id=first.template.id)

    assert second.template.id == first.template.id
    assert second.revision.revision == 2
    assert second.revision.parent_revision == 1
    assert second.revision.name == first.revision.name
    assert [item.revision for item in second.template.revisions] == [1, 2]
    # Revision 1 is exactly what it was: publication appends and never edits.
    assert second.template.revisions[0] == first.revision


async def test_an_untitled_draft_needs_a_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A Named Template without a name is not one."""
    await library.async_create_draft(admin, label_size_id=SIZE)

    with pytest.raises(TemplateNameRequired):
        await library.async_publish_draft(admin, label_size_id=SIZE)


async def test_a_name_is_unique_within_its_stock_and_not_across_stocks(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Trimmed and case-insensitive within the size; free at another size."""
    await _named_template(library, admin, name="Clone tags")

    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name=" CLONE  tags "
    )
    with pytest.raises(DuplicateTemplateName):
        await library.async_publish_draft(admin, label_size_id=SIZE)

    await library.async_create_draft(admin, label_size_id=OTHER_SIZE)
    await library.async_autosave_draft(
        admin,
        label_size_id=OTHER_SIZE,
        document=blank_document(OTHER_SIZE),
        name="Clone tags",
    )
    elsewhere = await library.async_publish_draft(admin, label_size_id=OTHER_SIZE)

    assert elsewhere.template.name == "Clone tags"
    assert elsewhere.template.label_size_id == OTHER_SIZE


async def test_a_refused_publication_keeps_the_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Being told the work cannot be published must not be how it is lost."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"not": "a layout"}, name="Clone tags"
    )
    before = library.state.generation

    with pytest.raises(DraftNotPublishable) as refusal:
        await library.async_publish_draft(admin, label_size_id=SIZE)

    assert refusal.value.diagnostics
    assert library.state.drafts
    assert library.state.templates == {}
    assert library.state.generation == before


async def test_a_replayed_publication_returns_the_same_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A retry after a lost answer finds its own revision, not a second one."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    first = await library.async_publish_draft(
        admin, label_size_id=SIZE, draft_id=saved.draft.id
    )

    replay = await library.async_publish_draft(
        admin, label_size_id=SIZE, draft_id=saved.draft.id
    )

    assert replay.replayed is True
    assert replay.revision == first.revision
    assert replay.template.id == first.template.id
    assert len(library.state.templates) == 1
    assert library.state.generation == first.generation


async def test_a_replay_of_a_draft_nobody_published_is_still_not_found(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Idempotency is recognising your own commit, not inventing one."""
    with pytest.raises(DraftNotFound):
        await library.async_publish_draft(
            admin, label_size_id=SIZE, draft_id="01ANOTHERDRAFTTHATNEVERWAS"
        )


async def test_another_administrator_cannot_replay_a_publication(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """A publication is somebody's work; an opaque ID is not a way into it."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    await library.async_publish_draft(
        admin, label_size_id=SIZE, draft_id=saved.draft.id
    )

    with pytest.raises(DraftNotFound):
        await library.async_publish_draft(
            other_admin, label_size_id=SIZE, draft_id=saved.draft.id
        )


async def test_a_failed_commit_leaves_the_library_exactly_as_it_was(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The next state is published only once the write returned."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    before = library.state

    with (
        patch.object(
            library._store,
            "async_save",
            AsyncMock(side_effect=OSError("disk full")),
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await library.async_publish_draft(admin, label_size_id=SIZE)

    assert library.state is before
    assert library.state.templates == {}
    assert library.state.drafts


# ---------------------------------------------------------------------------
# The Label Size does not move
# ---------------------------------------------------------------------------


async def test_a_draft_whose_document_changed_stock_cannot_be_published(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Converting between stocks is a transform, and this is not one."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin,
        label_size_id=SIZE,
        document=blank_document(OTHER_SIZE),
        name="Clone tags",
    )

    with pytest.raises(LabelSizeImmutable):
        await library.async_publish_draft(admin, label_size_id=SIZE)


async def test_a_templates_stock_cannot_change_under_a_new_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The size belongs to the template for its whole life, not to a revision."""
    published = await _named_template(library, admin)
    await library.async_open_draft(admin, published.template.id)
    await library.async_autosave_draft(
        admin, template_id=published.template.id, document=blank_document(OTHER_SIZE)
    )

    with pytest.raises(LabelSizeImmutable):
        await library.async_publish_draft(admin, template_id=published.template.id)


# ---------------------------------------------------------------------------
# The required strain name has to be printable, not merely present
# ---------------------------------------------------------------------------


async def test_a_layout_without_the_strain_name_cannot_be_published(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A literal that reads like a strain name does not satisfy the binding."""
    document = blank_document(SIZE)
    document["elements"][0]["content"] = {"literal": "Blue Dream"}
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=document, name="Clone tags"
    )

    with pytest.raises(DraftNotPublishable) as refusal:
        await library.async_publish_draft(admin, label_size_id=SIZE)

    assert "document.missing_required_strain_name" in {
        item.code for item in refusal.value.diagnostics
    }


async def test_a_strain_name_off_the_paper_cannot_be_published(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Required and printable are the same requirement.

    An element placed past the edge of the stock is present in the document and
    absent from the label, which is the one way "required" could be satisfied
    without being true.
    """
    document = blank_document(SIZE)
    document["elements"][0]["frame"]["x_mm"] = 48.0
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=document, name="Clone tags"
    )

    with pytest.raises(DraftNotPublishable) as refusal:
        await library.async_publish_draft(admin, label_size_id=SIZE)

    assert "frame.outside_stock" in {item.code for item in refusal.value.diagnostics}


# ---------------------------------------------------------------------------
# Refusals that are programming errors rather than states
# ---------------------------------------------------------------------------


async def test_the_library_must_be_loaded_before_it_is_read(
    libraries: Any,
) -> None:
    """Reading the committed state is not an implicit load."""
    unopened = libraries()

    with pytest.raises(Exception, match="not been loaded"):
        _ = unopened.state


@pytest.mark.parametrize(
    ("template_id", "label_size_id"),
    [(None, None), ("some-template", SIZE)],
    ids=["neither", "both"],
)
async def test_a_draft_is_addressed_by_exactly_one_thing(
    library: LabelTemplateLibrary,
    admin: Any,
    template_id: str | None,
    label_size_id: str | None,
) -> None:
    """A template draft and an untitled one are different slots, not a fallback."""
    with pytest.raises(Exception, match="exactly one of them"):
        await library.async_discard_draft(
            admin, template_id=template_id, label_size_id=label_size_id
        )


async def test_publishing_with_another_drafts_identity_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A retry key names one draft. A live draft that is not it is not published."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )

    with pytest.raises(DraftNotFound):
        await library.async_publish_draft(
            admin, label_size_id=SIZE, draft_id="01SOMEOTHERDRAFTENTIRELY00"
        )

    assert library.state.templates == {}
    assert library.state.drafts


# ---------------------------------------------------------------------------
# The blank layout itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label_size_id", list(LABEL_SIZES))
def test_the_blank_layout_is_handed_over_validated(label_size_id: str) -> None:
    """The one document nothing upstream of it would have checked."""
    layout = blank_layout(label_size_id)

    assert layout.label_size_id == label_size_id
    assert len(layout.elements) == 1


def test_a_blank_for_a_stock_nobody_ships_is_refused_by_name() -> None:
    """A Label Size is a catalogue identity, not a string with millimetres in it."""
    with pytest.raises(UnsupportedLabelSize):
        blank_document("growspace.stock.99x99.v1")


def test_a_stock_too_thin_for_the_blank_margins_says_so() -> None:
    """The guard behind "valid by construction", for a catalogue that grows."""
    thin = LabelSize("growspace.stock.50x3.v1", 50.0, 3.0, "50x3")

    with (
        patch.dict(
            "custom_components.growspace_manager.labels.library.blank.LABEL_SIZES",
            {thin.id: thin},
        ),
        pytest.raises(LabelTemplateError, match="too small"),
    ):
        blank_layout(thin.id)
