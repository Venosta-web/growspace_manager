"""Losing a Label Template, and getting it back (hub issue #220).

Four things that all say the same thing in different vocabulary: **nothing is
destroyed to make something work**.

A deletion is a thirty-day tombstone holding the whole template -- identity,
name, every revision -- so a restoration returns the thing that was deleted
rather than something that resembles it. The drafts aimed at it become orphans
rather than disappearing with it. A template whose head has stopped validating
is quarantined: kept, listed, exportable, openable as a draft, and refused only
where using it would mean printing it. And a store written by a newer
integration is not read at all -- the library reports itself contained, Home
Assistant raises a repair issue naming both versions, and every other feature
carries on around it.

The one thing here that does destroy something is garbage collection, which is
why it is explicit, administrator-only, and says exactly what it took.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30
from custom_components.growspace_manager.labels.library import (
    COLLECTED,
    DELETED,
    EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED,
    FACTORY_FALLBACK,
    RENAME,
    STORE_SCHEMA,
    STORE_VERSION,
    TOMBSTONE_DAYS,
    UNDELETED,
    DraftIsOrphaned,
    DuplicateTemplateName,
    IdempotencyKeyReused,
    IncompatibleTemplateStore,
    LabelTemplateLibrary,
    TemplateDeleted,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateProtected,
    TemplateRef,
    TombstoneExpired,
    TombstoneNotFound,
    async_get_library,
    blank_document,
    issue_id,
    storage_key,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

SIZE = "growspace.stock.50x30.v1"


async def _named_template(
    library: LabelTemplateLibrary, admin: Any, *, name: str = "Clone tags"
) -> Any:
    """Publish one Named Template, for the tests about losing it."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name=name
    )
    return await library.async_publish_draft(admin, label_size_id=SIZE)


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
    """Append one more revision, with a layout that really moved."""
    draft = await library.async_open_draft(admin, template_id)
    await library.async_autosave_draft(
        admin, template_id=template_id, document=_edited(draft.document, y_mm=y_mm)
    )
    return await library.async_publish_draft(admin, template_id=template_id)


async def _damage_head(
    libraries: Callable[..., LabelTemplateLibrary],
    library: LabelTemplateLibrary,
    template_id: str,
) -> LabelTemplateLibrary:
    """Write a head revision the catalogues have moved past, and reopen.

    The way a template really becomes quarantined -- a document saved against
    catalogues that have since changed -- reproduced by writing the damage
    under the library rather than by asking it to save something invalid,
    which it would rightly refuse.
    """
    state = library.state
    template = state.templates[template_id]
    damaged = replace(template.head, document={"schema": "growspace.label-layout"})
    await library._store.async_save(
        replace(
            state,
            templates={
                **state.templates,
                template_id: replace(
                    template, revisions=(*template.revisions[:-1], damaged)
                ),
            },
        )
    )
    reopened = libraries()
    await reopened.async_load()
    return reopened


@pytest.fixture
def changes(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Collect every library change event this instance fires."""
    seen: list[dict[str, Any]] = []

    @callback
    def record(event: Event) -> None:
        """Record one event, synchronously.

        A listener that is not a `callback` is dispatched as a job, so the
        assertion that follows a mutation races it. Every one of these
        suites reads the list immediately after the call that fires into it,
        which makes running in the loop part of what is being asserted.
        """
        seen.append(dict(event.data))

    hass.bus.async_listen(EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED, record)
    return seen


# ---------------------------------------------------------------------------
# Deleting is setting aside
# ---------------------------------------------------------------------------


async def test_a_deletion_keeps_the_whole_template_in_a_tombstone(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Identity, name and every revision, for thirty days."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    history = library.state.templates[published.template.id].revisions

    deleted = await library.async_delete_template(admin, published.template.id)

    assert published.template.id not in library.state.templates
    stone = library.state.tombstones[published.template.id]
    assert stone.template.revisions == history
    assert stone.name == "Clone tags"
    assert stone.deleted_by == admin.user_id
    assert deleted.tombstone == stone
    window = dt_util.parse_datetime(stone.expires_at) - dt_util.parse_datetime(
        stone.deleted_at
    )
    assert window == timedelta(days=TOMBSTONE_DAYS)


async def test_deleting_the_default_falls_back_in_the_same_commit(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Acceptance case 5, from the deletion side: one transaction, not two."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )

    deleted = await library.async_delete_template(admin, published.template.id)

    assert deleted.cleared_default is True
    assert deleted.tombstone.was_default is True
    assert library.state.defaults == {}
    assert deleted.effective is not None
    assert deleted.effective.via == FACTORY_FALLBACK
    resolved = await library.async_resolve_default(viewer, SIZE)
    assert resolved.ref == TemplateRef.factory(FACTORY_50X30.id)


async def test_a_deleted_identity_says_so_rather_than_going_missing(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """A different fact from an identity nobody ever had, with a different remedy."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    stone = library.state.tombstones[published.template.id]

    with pytest.raises(TemplateDeleted) as refused:
        await library.async_rename_template(admin, published.template.id, "Anything")

    assert refused.value.expires_at == stone.expires_at
    with pytest.raises(TemplateDeleted):
        await library.async_open_draft(admin, published.template.id)
    with pytest.raises(TemplateNotFound):
        await library.async_resolve(viewer, TemplateRef.named(published.template.id))


async def test_deleting_frees_the_name_it_was_using(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Which is the whole reason a restoration can need a new one."""
    published = await _named_template(library, admin, name="Clone tags")
    await library.async_delete_template(admin, published.template.id)

    replacement = await _named_template(library, admin, name="Clone tags")

    assert replacement.template.id != published.template.id
    assert replacement.template.name == "Clone tags"


async def test_a_factory_template_cannot_be_deleted(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """It is the integration's, and it is what everything else falls back to."""
    with pytest.raises(TemplateProtected):
        await library.async_delete_template(admin, FACTORY_50X30.id)

    assert library.state.tombstones == {}


async def test_a_deletion_announces_itself(
    library: LabelTemplateLibrary,
    admin: Any,
    changes: list[dict[str, Any]],
    hass: HomeAssistant,
) -> None:
    """Another client's selection list just got shorter."""
    published = await _named_template(library, admin)
    changes.clear()

    deleted = await library.async_delete_template(admin, published.template.id)
    await hass.async_block_till_done()

    assert [item["operation"] for item in changes] == [DELETED]
    assert changes[0]["template_id"] == published.template.id
    assert changes[0]["generation"] == deleted.generation
    assert changes[0]["previous_generation"] == deleted.generation - 1


# ---------------------------------------------------------------------------
# Orphaned drafts
# ---------------------------------------------------------------------------


async def test_a_deletion_leaves_everybody_drafts_as_orphans(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Acceptance case 14: unpublished work is not somebody else's to delete."""
    published = await _named_template(library, admin)
    mine = await library.async_open_draft(admin, published.template.id)
    theirs = await library.async_open_draft(other_admin, published.template.id)

    deleted = await library.async_delete_template(admin, published.template.id)

    assert set(deleted.orphaned) == {mine.id, theirs.id}
    assert len(library.state.drafts) == 2
    snapshot = await library.async_snapshot(other_admin)
    assert [item["id"] for item in snapshot["drafts"]] == [theirs.id]
    assert snapshot["drafts"][0]["orphaned"] is True
    assert snapshot["drafts"][0]["stale"] is False


async def test_an_orphan_is_recovery_work_rather_than_editing_work(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Read it, preview it, save it under a new identity, discard it. Not edit it."""
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    await library.async_delete_template(admin, published.template.id)

    with pytest.raises(DraftIsOrphaned) as refused:
        await library.async_autosave_draft(
            admin, template_id=published.template.id, document=draft.document
        )
    assert refused.value.template_id == published.template.id
    with pytest.raises(DraftIsOrphaned):
        await library.async_publish_draft(admin, template_id=published.template.id)

    rescued = await library.async_save_as(
        admin, "Rescued tags", template_id=published.template.id
    )

    assert rescued.template.id != published.template.id
    assert rescued.revision.revision == 1
    assert library.state.drafts == {}


async def test_an_orphan_can_simply_be_discarded(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The other half of what an owner may do with one."""
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    await library.async_delete_template(admin, published.template.id)

    discarded = await library.async_discard_draft(
        admin, template_id=published.template.id
    )

    assert discarded.draft_id == draft.id
    assert library.state.drafts == {}


# ---------------------------------------------------------------------------
# Restoring a deletion
# ---------------------------------------------------------------------------


async def test_a_restoration_returns_the_same_identity_and_history(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """The template that was deleted, not one that resembles it."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    history = library.state.templates[published.template.id].revisions
    await library.async_delete_template(admin, published.template.id)

    restored = await library.async_restore_template(admin, published.template.id)

    assert restored.template.id == published.template.id
    assert restored.template.revisions == history
    assert restored.renamed is False
    assert library.state.tombstones == {}
    assert (
        await library.async_resolve(viewer, TemplateRef.named(published.template.id))
    ).revision == 2


async def test_a_restoration_does_not_take_the_default_back(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Acceptance case 15: whatever has been printing since keeps printing."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    await library.async_delete_template(admin, published.template.id)
    chosen = await _named_template(library, admin, name="Stand-in tags")
    await library.async_set_default(admin, SIZE, TemplateRef.named(chosen.template.id))

    await library.async_restore_template(admin, published.template.id)

    assert library.state.defaults[SIZE] == TemplateRef.named(chosen.template.id)


async def test_a_restoration_refuses_a_name_that_has_been_taken(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """And the new name arrives as a rename revision, because names live on one."""
    published = await _named_template(library, admin, name="Clone tags")
    await library.async_delete_template(admin, published.template.id)
    holder = await _named_template(library, admin, name="Clone tags")

    with pytest.raises(DuplicateTemplateName) as refused:
        await library.async_restore_template(admin, published.template.id)
    assert refused.value.template_id == holder.template.id
    assert published.template.id in library.state.tombstones

    restored = await library.async_restore_template(
        admin, published.template.id, name="Clone tags (2026)"
    )

    assert restored.renamed is True
    assert restored.template.id == published.template.id
    assert restored.template.name == "Clone tags (2026)"
    assert restored.revision.operation == RENAME
    assert restored.revision.revision == 2
    assert restored.template.revisions[0] == published.revision


async def test_restoring_reconnects_the_drafts_that_were_orphaned(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A draft names its template, so restoring the template is the reconnection."""
    published = await _named_template(library, admin)
    draft = await library.async_open_draft(admin, published.template.id)
    await library.async_delete_template(admin, published.template.id)

    restored = await library.async_restore_template(admin, published.template.id)

    assert restored.reconnected == (draft.id,)
    saved = await library.async_autosave_draft(
        admin,
        template_id=published.template.id,
        document=_edited(draft.document, y_mm=6.0),
    )
    assert saved.stale is False


async def test_an_expired_tombstone_is_not_restorable(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Thirty days that sometimes meant ninety would be no promise at all."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    _expire(library, published.template.id)

    with pytest.raises(TombstoneExpired) as refused:
        await library.async_restore_template(admin, published.template.id)

    assert refused.value.template_id == published.template.id
    assert published.template.id in library.state.tombstones


async def test_restoring_something_that_was_never_deleted_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Asking about a deletion is not asking about a template."""
    published = await _named_template(library, admin)

    with pytest.raises(TombstoneNotFound):
        await library.async_restore_template(admin, published.template.id)

    assert library.state.templates[published.template.id] == published.template


async def test_a_restoration_announces_itself(
    library: LabelTemplateLibrary,
    admin: Any,
    changes: list[dict[str, Any]],
    hass: HomeAssistant,
) -> None:
    """Another client's selection list just got longer again."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    changes.clear()

    await library.async_restore_template(admin, published.template.id)
    await hass.async_block_till_done()

    assert [item["operation"] for item in changes] == [UNDELETED]
    assert changes[0]["template_id"] == published.template.id


# ---------------------------------------------------------------------------
# Collecting what has expired
# ---------------------------------------------------------------------------


def _expire(library: LabelTemplateLibrary, template_id: str) -> None:
    """Age one tombstone past its window, without waiting thirty days."""
    state = library.state
    stone = state.tombstones[template_id]
    library._state = replace(
        state,
        tombstones={
            **state.tombstones,
            template_id: replace(
                stone,
                expires_at=(dt_util.utcnow() - timedelta(minutes=1)).isoformat(),
            ),
        },
    )


async def test_collecting_removes_only_what_has_expired(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Including the orphaned drafts that were still waiting on it."""
    gone = await _named_template(library, admin, name="Old tags")
    orphan = await library.async_open_draft(admin, gone.template.id)
    recent = await _named_template(library, admin, name="Newer tags")
    live = await _named_template(library, admin, name="Still here")
    working = await library.async_open_draft(admin, live.template.id)
    await library.async_delete_template(admin, gone.template.id)
    await library.async_delete_template(admin, recent.template.id)
    _expire(library, gone.template.id)

    collected = await library.async_collect_tombstones(admin)

    assert collected.collected == (gone.template.id,)
    assert collected.drafts == (orphan.id,)
    assert list(library.state.tombstones) == [recent.template.id]
    assert [draft.id for draft in library.state.drafts.values()] == [working.id]


async def test_collecting_nothing_writes_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """There is no change for another client to hear about."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    before = library.state
    changes.clear()

    collected = await library.async_collect_tombstones(admin)

    assert collected.unchanged is True
    assert collected.collected == ()
    assert library.state is before
    assert changes == []


async def test_a_collected_deletion_is_gone_for_good(
    library: LabelTemplateLibrary,
    admin: Any,
    changes: list[dict[str, Any]],
    hass: HomeAssistant,
) -> None:
    """The one operation here that really destroys something, saying so."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    _expire(library, published.template.id)
    changes.clear()

    await library.async_collect_tombstones(admin)
    await hass.async_block_till_done()

    assert [item["operation"] for item in changes] == [COLLECTED]
    with pytest.raises(TombstoneNotFound):
        await library.async_restore_template(admin, published.template.id)
    with pytest.raises(TemplateNotFound):
        await library.async_rename_template(admin, published.template.id, "Anything")


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


async def test_a_template_whose_head_stopped_validating_is_quarantined(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, viewer: Any
) -> None:
    """Acceptance case 20: one template withdrawn, the rest of the library fine."""
    library = libraries()
    await library.async_load()
    broken = await _named_template(library, admin, name="Broken tags")
    await _revise(library, admin, broken.template.id, y_mm=4.0)
    fine = await _named_template(library, admin, name="Fine tags")
    reopened = await _damage_head(libraries, library, broken.template.id)

    snapshot = await reopened.async_snapshot(admin)

    listed = {item["id"]: item for item in snapshot["templates"]}
    assert listed[broken.template.id]["quarantined"] is True
    assert listed[broken.template.id]["quarantine"]["revision"] == 2
    assert listed[broken.template.id]["quarantine"]["diagnostics"]
    assert listed[fine.template.id]["quarantined"] is False
    assert listed[fine.template.id]["quarantine"] is None
    assert (
        await reopened.async_resolve(viewer, TemplateRef.named(fine.template.id))
    ).revision == 1
    with pytest.raises(TemplateNotResolvable):
        await reopened.async_resolve(viewer, TemplateRef.named(broken.template.id))


async def test_a_quarantined_default_exposes_the_factory_fallback(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, viewer: Any
) -> None:
    """Losing a template must not cost a stock its printing."""
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    reopened = await _damage_head(libraries, library, published.template.id)

    resolved = await reopened.async_resolve_default(viewer, SIZE)

    assert resolved.ref == TemplateRef.factory(FACTORY_50X30.id)
    assert resolved.via == FACTORY_FALLBACK
    assert reopened.state.defaults[SIZE] == TemplateRef.named(published.template.id)


async def test_a_quarantined_template_cannot_be_chosen_as_a_default(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Selecting one would be selecting something nothing can print."""
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    reopened = await _damage_head(libraries, library, published.template.id)

    with pytest.raises(TemplateNotResolvable):
        await reopened.async_set_default(
            admin, SIZE, TemplateRef.named(published.template.id)
        )

    assert reopened.state.defaults == {}


async def test_an_unknown_label_size_quarantines_rather_than_migrating(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Opaque preserved data, never moved to the nearest stock we do have.

    A stock the catalogues have dropped is the case where repairing would be
    most tempting and worst: the millimetres mean something different on
    different paper, so the neighbouring size is a different label.
    """
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    state = library.state
    template = state.templates[published.template.id]
    retired = replace(
        template.head,
        document={
            **template.head.document,
            "label_size_id": "growspace.stock.60x40.v1",
        },
    )
    await library._store.async_save(
        replace(
            state,
            templates={
                **state.templates,
                template.id: replace(template, revisions=(retired,)),
            },
        )
    )
    reopened = libraries()
    await reopened.async_load()

    snapshot = await reopened.async_snapshot(admin)

    (listed,) = snapshot["templates"]
    assert listed["quarantined"] is True
    stored = reopened.state.templates[published.template.id].head.document
    assert stored["label_size_id"] == "growspace.stock.60x40.v1"


async def test_a_quarantined_template_can_still_be_exported(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Handing it to a newer integration is the repair, so export never validates."""
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    reopened = await _damage_head(libraries, library, published.template.id)

    bundle = await reopened.async_export_templates(admin)

    (entry,) = bundle["templates"]
    assert entry["id"] == published.template.id
    assert entry["document"] == {"schema": "growspace.label-layout"}


async def test_a_quarantined_template_can_be_repaired_or_reached_past(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, viewer: Any
) -> None:
    """Kept for diagnostics, a new draft, or a restore of what still works."""
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)
    reopened = await _damage_head(libraries, library, published.template.id)

    restored = await reopened.async_restore_revision(admin, published.template.id, 1)

    assert restored.revision.revision == 3
    assert (
        await reopened.async_resolve(viewer, TemplateRef.named(published.template.id))
    ).revision == 3
    snapshot = await reopened.async_snapshot(admin)
    listed = {item["id"]: item for item in snapshot["templates"]}
    assert listed[published.template.id]["quarantined"] is False


# ---------------------------------------------------------------------------
# A store this integration cannot read
# ---------------------------------------------------------------------------


def _from_the_future(hass_storage: dict[str, Any], entry_id: str) -> dict[str, Any]:
    """Write a library at a store version this integration does not have."""
    written = {
        "schema": STORE_SCHEMA,
        "version": STORE_VERSION + 1,
        "generation": 9,
        "templates": {"unknown": {"shape": "from a later version"}},
    }
    hass_storage[storage_key(entry_id)] = {
        "version": STORE_VERSION + 1,
        "key": storage_key(entry_id),
        "data": written,
    }
    return written


async def test_a_newer_store_contains_itself_and_raises_a_repair(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any
) -> None:
    """Acceptance case 19: byte-identical, read-only, and somebody is told."""
    written = _from_the_future(hass_storage, "entry-a")

    library = await async_get_library(hass, "entry-a")

    assert library.read_only is True
    assert hass_storage[storage_key("entry-a")]["data"] == written
    issue = ir.async_get(hass).async_get_issue("growspace_manager", issue_id("entry-a"))
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is False
    assert issue.translation_placeholders == {
        "found": str(STORE_VERSION + 1),
        "supported": str(STORE_VERSION),
    }


async def test_a_contained_library_answers_with_the_containment(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any
) -> None:
    """An empty list and an unreadable store are different things to show."""
    _from_the_future(hass_storage, "entry-a")
    library = await async_get_library(hass, "entry-a")

    snapshot = await library.async_snapshot(admin)

    assert snapshot["store"] == {
        "readable": False,
        "version": STORE_VERSION,
        "found_version": STORE_VERSION + 1,
    }
    assert snapshot["generation"] is None
    assert snapshot["templates"] == []
    assert snapshot["effective_defaults"] == {}
    assert snapshot["factory_templates"]


#: Everything a contained library must refuse, mutations and reads alike. A
#: read is refused for the same reason a write is: half a library answered
#: confidently is how a newer store quietly becomes a lossy older one.
CONTAINED: dict[
    str, Callable[[LabelTemplateLibrary, Any], Coroutine[Any, Any, Any]]
] = {
    "create_draft": lambda lib, actor: lib.async_create_draft(
        actor, label_size_id=SIZE
    ),
    "publish_draft": lambda lib, actor: lib.async_publish_draft(
        actor, label_size_id=SIZE
    ),
    "set_default": lambda lib, actor: lib.async_set_default(
        actor, SIZE, TemplateRef.factory(FACTORY_50X30.id)
    ),
    "delete_template": lambda lib, actor: lib.async_delete_template(actor, "anything"),
    "restore_template": lambda lib, actor: lib.async_restore_template(
        actor, "anything"
    ),
    "collect_tombstones": lambda lib, actor: lib.async_collect_tombstones(actor),
    "export_templates": lambda lib, actor: lib.async_export_templates(actor),
    "import_templates": lambda lib, actor: lib.async_import_templates(actor, {}),
    "backup": lambda lib, actor: lib.async_backup(actor),
    "restore_backup": lambda lib, actor: lib.async_restore_backup(actor, {}),
    "resolve_default": lambda lib, actor: lib.async_resolve_default(actor, SIZE),
    "resolve": lambda lib, actor: lib.async_resolve(
        actor, TemplateRef.factory(FACTORY_50X30.id)
    ),
}


@pytest.mark.parametrize("operation", list(CONTAINED), ids=list(CONTAINED))
async def test_a_contained_library_does_nothing_at_all(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any, operation: str
) -> None:
    """No best-effort downgrade, and no best-effort read either."""
    written = _from_the_future(hass_storage, "entry-a")
    library = await async_get_library(hass, "entry-a")

    with pytest.raises(IncompatibleTemplateStore) as refused:
        await CONTAINED[operation](library, admin)

    assert refused.value.found == STORE_VERSION + 1
    assert refused.value.supported == STORE_VERSION
    assert hass_storage[storage_key("entry-a")]["data"] == written


async def test_another_entry_is_unaffected_by_a_contained_one(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any
) -> None:
    """One entry is one library, and the repair names the one that is stuck."""
    _from_the_future(hass_storage, "entry-a")
    await async_get_library(hass, "entry-a")

    healthy = await async_get_library(hass, "entry-b")
    published = await _named_template(healthy, admin)

    assert healthy.read_only is False
    assert list(healthy.state.templates) == [published.template.id]
    registry = ir.async_get(hass)
    assert registry.async_get_issue("growspace_manager", issue_id("entry-a"))
    assert registry.async_get_issue("growspace_manager", issue_id("entry-b")) is None


async def test_the_repair_clears_when_the_store_reads_again(
    hass: HomeAssistant, hass_storage: dict[str, Any], admin: Any
) -> None:
    """Create or clear, from the one predicate, so it heals itself."""
    _from_the_future(hass_storage, "entry-a")
    await async_get_library(hass, "entry-a")
    assert ir.async_get(hass).async_get_issue("growspace_manager", issue_id("entry-a"))

    hass_storage.pop(storage_key("entry-a"))
    library = LabelTemplateLibrary(hass, "entry-a")
    await library.async_load()

    assert library.read_only is False
    assert (
        ir.async_get(hass).async_get_issue("growspace_manager", issue_id("entry-a"))
        is None
    )


# ---------------------------------------------------------------------------
# One commit, and a retry is not a second one
# ---------------------------------------------------------------------------

#: The recovery operations that write, as the call a client would make with a
#: key. Parametrized because every property below is a property of all three.
RECOVERY: dict[
    str,
    Callable[[LabelTemplateLibrary, Any, str, str], Coroutine[Any, Any, Any]],
] = {
    "delete": lambda lib, actor, template_id, key: lib.async_delete_template(
        actor, template_id, idempotency_key=key
    ),
    "restore": lambda lib, actor, template_id, key: lib.async_restore_template(
        actor, template_id, idempotency_key=key
    ),
    "collect": lambda lib, actor, template_id, key: lib.async_collect_tombstones(
        actor, idempotency_key=key
    ),
}


async def _recoverable(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> str:
    """Put the library in the state each operation needs, and name the template."""
    published = await _named_template(library, admin)
    await library.async_open_draft(admin, published.template.id)
    if operation in {"restore", "collect"}:
        await library.async_delete_template(admin, published.template.id)
    if operation == "collect":
        _expire(library, published.template.id)
    return str(published.template.id)


@pytest.mark.parametrize("operation", list(RECOVERY), ids=list(RECOVERY))
async def test_a_replayed_recovery_call_performs_nothing_a_second_time(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """A retry of a call whose answer was lost finds the first attempt."""
    template_id = await _recoverable(library, admin, operation)
    await RECOVERY[operation](library, admin, template_id, "key-1")
    after = library.state

    replay = await RECOVERY[operation](library, admin, template_id, "key-1")

    assert replay.replayed is True
    assert library.state.generation == after.generation
    assert library.state.as_dict() == after.as_dict()


@pytest.mark.parametrize("operation", list(RECOVERY), ids=list(RECOVERY))
async def test_a_failed_recovery_commit_leaves_the_library_as_it_was(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """The next state is published only once the write returned."""
    template_id = await _recoverable(library, admin, operation)
    before = library.state

    with (
        patch.object(
            library._store,
            "async_save",
            AsyncMock(side_effect=OSError("disk full")),
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await RECOVERY[operation](library, admin, template_id, "key-1")

    assert library.state is before


@pytest.mark.parametrize("operation", list(RECOVERY), ids=list(RECOVERY))
async def test_a_recovery_key_spent_on_a_different_call_is_refused(
    library: LabelTemplateLibrary, admin: Any, operation: str
) -> None:
    """Performing the second call under the first one's key is the one bad answer."""
    template_id = await _recoverable(library, admin, operation)
    await RECOVERY[operation](library, admin, template_id, "key-1")

    with pytest.raises(IdempotencyKeyReused):
        await library.async_duplicate_template(
            admin,
            TemplateRef.factory(FACTORY_50X30.id),
            "Something else entirely",
            idempotency_key="key-1",
        )


@pytest.mark.parametrize("operation", list(RECOVERY), ids=list(RECOVERY))
async def test_a_recovery_call_survives_a_restart(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, operation: str
) -> None:
    """What was committed is what the next instance reads back."""
    library = libraries()
    await library.async_load()
    template_id = await _recoverable(library, admin, operation)
    await RECOVERY[operation](library, admin, template_id, "key-1")
    expected = library.state

    reopened = libraries()
    await reopened.async_load()

    assert reopened.state.as_dict() == expected.as_dict()


# ---------------------------------------------------------------------------
# The refusals on the way in
# ---------------------------------------------------------------------------


async def test_a_restoration_still_needs_a_name(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Asking for one and then supplying whitespace is not supplying one."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)

    with pytest.raises(TemplateNameRequired):
        await library.async_restore_template(admin, published.template.id, name="   ")

    assert published.template.id in library.state.tombstones


async def test_a_draft_slot_is_addressed_by_something_that_could_hold_one(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A Factory Template and an identity nobody has are different refusals.

    Both reach the draft lookup, which has to answer about the *template*
    before it can say whether there is a draft of it -- a shipped template
    cannot have one, and an unknown identity is not a slot at all.
    """
    with pytest.raises(TemplateProtected):
        await library.async_discard_draft(admin, template_id=FACTORY_50X30.id)
    with pytest.raises(TemplateNotFound):
        await library.async_discard_draft(admin, template_id="nobody-has-this")


async def test_a_replayed_deletion_whose_tombstone_was_collected_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Reconstructing one from the ledger would invent a window that has closed."""
    published = await _named_template(library, admin)
    await library.async_delete_template(
        admin, published.template.id, idempotency_key="key-1"
    )
    _expire(library, published.template.id)
    await library.async_collect_tombstones(admin)

    with pytest.raises(TombstoneNotFound):
        await library.async_delete_template(
            admin, published.template.id, idempotency_key="key-1"
        )


async def test_a_replayed_restoration_of_a_deleted_template_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A replay answers what is true now, and what is true now is that it is gone."""
    published = await _named_template(library, admin)
    await library.async_delete_template(admin, published.template.id)
    await library.async_restore_template(
        admin, published.template.id, idempotency_key="key-1"
    )
    await library.async_delete_template(admin, published.template.id)

    with pytest.raises(TemplateNotFound):
        await library.async_restore_template(
            admin, published.template.id, idempotency_key="key-1"
        )
