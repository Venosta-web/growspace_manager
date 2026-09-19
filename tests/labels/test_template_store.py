"""What the library keeps, and who it keeps it apart from (hub issue #217).

One Home Assistant config entry owns one library. The isolation is not a rule
applied on top of a shared store -- it is the store: the config entry ID is in
the `.storage` key, so two entries are two documents and an identity from one
is simply absent from the other.

The rest of this is about the persisted shape being deliberate. Every record
spells its own serialization rather than taking `asdict`, because this is
somebody's saved work and a renamed field must be a migration. And a document
written by a *newer* integration is refused and left exactly as found: a
best-effort read is how a newer store quietly becomes a lossy older one.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30
from custom_components.growspace_manager.labels.library import (
    STORE_SCHEMA,
    STORE_VERSION,
    IncompatibleTemplateStore,
    LabelTemplateLibrary,
    LibraryState,
    NamedTemplate,
    Provenance,
    TemplateDraft,
    TemplateNotFound,
    TemplateRef,
    TemplateRevision,
    async_get_library,
    async_release_library,
    blank_document,
    draft_key,
    normalized_name,
    storage_key,
)
from homeassistant.core import HomeAssistant

SIZE = "growspace.stock.50x30.v1"


async def _named_template(
    library: LabelTemplateLibrary, admin: Any, *, name: str = "Clone tags"
) -> Any:
    """Publish one Named Template."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name=name
    )
    return await library.async_publish_draft(admin, label_size_id=SIZE)


# ---------------------------------------------------------------------------
# One entry, one library
# ---------------------------------------------------------------------------


def test_the_storage_key_carries_the_config_entry() -> None:
    """The whole of the isolation, in one string."""
    assert storage_key("abc") == "growspace_manager.label_templates.abc"
    assert storage_key("abc") != storage_key("def")


async def test_two_config_entries_share_nothing(
    libraries: Any, admin: Any, viewer: Any
) -> None:
    """Acceptance case 1: the same names and a real UUID, and no shared state.

    The UUID one entry minted is not "hidden" from the other -- it does not
    exist there, which is why the answer is the ordinary one for an identity
    nobody has.
    """
    first = libraries("entry-a")
    second = libraries("entry-b")
    await first.async_load()
    await second.async_load()

    mine = await _named_template(first, admin, name="Clone tags")
    theirs = await _named_template(second, admin, name="Clone tags")
    await first.async_set_default(admin, SIZE, TemplateRef.named(mine.template.id))

    assert mine.template.id != theirs.template.id
    assert list(second.state.templates) == [theirs.template.id]
    assert second.state.defaults == {}
    with pytest.raises(TemplateNotFound):
        await second.async_resolve(viewer, TemplateRef.named(mine.template.id))
    assert (
        await second.async_resolve_default(viewer, SIZE)
    ).ref == TemplateRef.factory(FACTORY_50X30.id)


async def test_a_config_entry_gets_one_library_instance(
    hass: HomeAssistant,
) -> None:
    """One instance, because the lock only serializes callers that share it."""
    first = await async_get_library(hass, "entry-a")
    again = await async_get_library(hass, "entry-a")
    other = await async_get_library(hass, "entry-b")

    assert first is again
    assert first is not other

    async_release_library(hass, "entry-a")
    assert await async_get_library(hass, "entry-a") is not first


async def test_releasing_a_library_keeps_what_it_stored(
    hass: HomeAssistant, admin: Any
) -> None:
    """An unload is not a deletion."""
    library = await async_get_library(hass, "entry-a")
    published = await _named_template(library, admin)

    async_release_library(hass, "entry-a")
    reopened = await async_get_library(hass, "entry-a")

    assert list(reopened.state.templates) == [published.template.id]


# ---------------------------------------------------------------------------
# What survives a restart
# ---------------------------------------------------------------------------


async def test_a_published_library_comes_back_whole(
    libraries: Any, admin: Any, viewer: Any
) -> None:
    """Templates, history, drafts, defaults and the generation, all of them."""
    first = libraries()
    await first.async_load()
    published = await _named_template(first, admin)
    await first.async_set_default(admin, SIZE, TemplateRef.named(published.template.id))
    await first.async_create_draft(admin, label_size_id=SIZE)
    await first.async_autosave_draft(
        admin, label_size_id=SIZE, document={"work": "in progress"}, name="Next one"
    )

    reopened = libraries()
    state = await reopened.async_load()

    assert state.generation == first.state.generation
    assert state.templates == first.state.templates
    assert state.drafts == first.state.drafts
    assert state.defaults == first.state.defaults
    assert (await reopened.async_resolve_default(viewer, SIZE)).revision == 1


async def test_the_persisted_document_names_itself(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A stray `.storage` file can be recognised for what it is."""
    await _named_template(library, admin)

    document = library.state.as_dict()

    assert document["schema"] == STORE_SCHEMA
    assert document["version"] == STORE_VERSION
    assert set(document) == {
        "schema",
        "version",
        "generation",
        "templates",
        "drafts",
        "defaults",
        "tombstones",
        "commits",
    }


async def test_a_committed_library_round_trips_through_its_own_form(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Reading back what was written produces the same records, not similar ones."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    await library.async_create_draft(admin, label_size_id=SIZE)

    assert LibraryState.from_dict(library.state.as_dict()) == library.state


def test_an_absent_document_reads_as_an_empty_library() -> None:
    """A fresh install has no file, which is not an error."""
    assert LibraryState.from_dict(None) == LibraryState()
    assert LibraryState.from_dict({}) == LibraryState()


def test_a_newer_store_is_refused_rather_than_interpreted() -> None:
    """Rollback containment starts here: nothing is read out of it at all."""
    with pytest.raises(IncompatibleTemplateStore) as refusal:
        LibraryState.from_dict(
            {"schema": STORE_SCHEMA, "version": STORE_VERSION + 1, "templates": {}}
        )

    assert refusal.value.found == STORE_VERSION + 1
    assert refusal.value.supported == STORE_VERSION


async def test_a_newer_store_is_left_byte_for_byte(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Refusing to read it is only half of it; not writing over it is the rest."""
    written = {
        "schema": STORE_SCHEMA,
        "version": STORE_VERSION + 1,
        "generation": 9,
        "templates": {"unknown": {"shape": "from the future"}},
    }
    hass_storage[storage_key("entry-a")] = {
        "version": STORE_VERSION + 1,
        "key": storage_key("entry-a"),
        "data": written,
    }

    with pytest.raises(IncompatibleTemplateStore):
        await LabelTemplateLibrary(hass, "entry-a").async_load()

    assert hass_storage[storage_key("entry-a")]["data"] == written


# ---------------------------------------------------------------------------
# The records themselves
# ---------------------------------------------------------------------------


def test_a_draft_occupies_one_slot_per_owner_and_subject() -> None:
    """One active draft per administrator and template, one per size."""
    assert draft_key("u1", template_id="t1", label_size_id=SIZE) != draft_key(
        "u2", template_id="t1", label_size_id=SIZE
    )
    assert draft_key("u1", template_id=None, label_size_id=SIZE) != draft_key(
        "u1", template_id="t1", label_size_id=SIZE
    )
    assert draft_key("u1", template_id="t1", label_size_id=SIZE) == draft_key(
        "u1", template_id="t1", label_size_id="ignored"
    )


def test_names_compare_trimmed_and_case_insensitively() -> None:
    """The comparison a person reading a label off a shelf would make."""
    assert normalized_name("  Clone   Tags ") == normalized_name("clone tags")
    assert normalized_name("Clone tags") != normalized_name("Clone tag")


def test_a_revision_summary_leaves_the_document_behind() -> None:
    """A listing must not grow with every layout ever published."""
    revision = TemplateRevision(
        revision=2,
        name="Clone tags",
        document=blank_document(SIZE),
        digest="sha256:whatever",
        published_at="2026-09-19T00:00:00+00:00",
        published_by="admin-user",
        operation="publish",
        parent_revision=1,
        provenance=Provenance(source="blank"),
    )

    summary = revision.summary()

    assert "document" not in summary
    assert summary["revision"] == 2
    assert summary["parent_revision"] == 1


def test_a_template_reads_its_name_from_its_head() -> None:
    """One name, and it lives in history rather than beside it."""
    first = TemplateRevision(
        revision=1,
        name="Clone tags",
        document=blank_document(SIZE),
        digest="sha256:one",
        published_at="2026-09-19T00:00:00+00:00",
        published_by="admin-user",
        operation="publish",
        parent_revision=None,
        provenance=Provenance(source="blank"),
    )
    template = NamedTemplate(
        id="11111111-2222-3333-4444-555555555555",
        label_size_id=SIZE,
        created_at=first.published_at,
        created_by="admin-user",
        revisions=(first,),
    )

    grown = template.with_revision(replace(first, revision=2, name="Cutting tags"))

    assert template.name == "Clone tags"
    assert grown.name == "Cutting tags"
    assert grown.head.revision == 2
    assert grown.revision(1) == first
    assert grown.revision(7) is None


def test_a_draft_round_trips_with_whatever_payload_it_holds() -> None:
    """Including one that is not a document at all."""
    draft = TemplateDraft(
        id="01M2W7M1G6P52TA09X4BATS4NG",
        owner="admin-user",
        label_size_id=SIZE,
        version=4,
        document=["not", "a", "layout"],
        created_at="2026-09-19T00:00:00+00:00",
        modified_at="2026-09-19T00:05:00+00:00",
        provenance=Provenance(source="blank"),
        name="Work in progress",
    )

    assert TemplateDraft.from_dict(draft.as_dict()) == draft


def test_a_reference_names_a_kind_as_well_as_an_identity() -> None:
    """So a UUID-shaped factory ID could never read as somebody's template."""
    assert TemplateRef.factory("growspace.factory.50x30").as_dict() == {
        "kind": "factory",
        "id": "growspace.factory.50x30",
    }
    assert TemplateRef.named("abc") != TemplateRef.factory("abc")
    assert TemplateRef.from_dict(
        TemplateRef.named("abc").as_dict()
    ) == TemplateRef.named("abc")


async def test_removing_a_library_document_is_the_entry_lifecycle(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any
) -> None:
    """Deleting the config entry deletes its templates. Nothing else does.

    No lifecycle operation calls this: a template is soft-deleted and
    recoverable, and dropping the whole document is the enclosing Home
    Assistant data lifecycle rather than a management shortcut.
    """
    library = LabelTemplateLibrary(hass, "entry-a")
    await library.async_load()
    await _named_template(library, admin)
    assert storage_key("entry-a") in hass_storage

    await library._store.async_remove()

    assert storage_key("entry-a") not in hass_storage
    assert await LabelTemplateLibrary(hass, "entry-a").async_load() == LibraryState()


def test_a_stored_number_that_is_not_one_is_refused() -> None:
    """A store read never coerces: `True` is not revision 1."""
    with pytest.raises(TypeError):
        Provenance.from_dict({"source": "blank", "draft_version": True})

    assert Provenance.from_dict({"source": "blank"}).draft_version is None
    assert (
        Provenance.from_dict({"source": "blank", "draft_version": 3}).draft_version == 3
    )
