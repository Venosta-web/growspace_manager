"""Two people editing one Label Template library at once (hub issue #218).

Everything here is a claim about what happens when a second client exists. The
suites beside this one prove what the library does; these prove what it refuses
to do to somebody else's work.

Four properties, and the file is organized as them.

**A write never overwrites a version it has not seen.** An autosave is
compare-and-swap on the draft version and a publication compares the draft's
base with the current head. Both refusals keep the work: the stored draft is
left exactly as it was and the rejected payload goes into the draft's recovery
slot, so being refused costs a client nothing but the round trip.

**A retry is not a second call.** Every mutation may carry an idempotency key,
and replaying one returns the first attempt rather than publishing a second
revision or advancing the Library Generation again.

**A client can tell what it missed.** Every committed library mutation fires
one change event naming the new generation and the one it replaced, so a gap is
arithmetic rather than a guess -- and the snapshot that recovers from a gap is
a read, which is why recovering cannot cost an editor its unsaved work.

**Nothing is merged.** A stale draft stays whole, stays previewable, and is
discarded, reloaded or kept by its owner -- never quietly combined with the
revision that overtook it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.labels.library import (
    COMMIT_LEDGER_LIMIT,
    DEFAULT_CLEARED,
    DEFAULT_SET,
    EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED,
    PUBLISHED,
    REJECTED_SAVE,
    RELOADED,
    DraftIsStale,
    DraftNotFound,
    DraftVersionConflict,
    IdempotencyKeyReused,
    LabelTemplateLibrary,
    LabelTemplateStore,
    NoRecoveryPayload,
    RevisionNotFound,
    TemplateRef,
    blank_document,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import Unauthorized

SIZE = "growspace.stock.50x30.v1"


async def _named_template(
    library: LabelTemplateLibrary, admin: Any, *, name: str = "Clone tags"
) -> Any:
    """Publish one Named Template, for the tests about editing it afterwards."""
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
# Autosave is compare-and-swap
# ---------------------------------------------------------------------------


async def test_a_save_over_a_version_it_has_not_seen_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One administrator, the editor open twice: the older tab does not win.

    This is the failure a debounced autosave makes easy -- two tabs, one of
    them minutes behind, both saving the same slot. Version 1 is what the
    second tab last read; the first has already moved the draft past it.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)
    current = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"from": "the newer tab"}, name="Clone tags"
    )

    with pytest.raises(DraftVersionConflict) as refused:
        await library.async_autosave_draft(
            admin,
            label_size_id=SIZE,
            document={"from": "the older tab"},
            expected_version=1,
        )

    assert refused.value.expected == 1
    assert refused.value.found == current.draft.version
    stored = library.state.drafts[current.draft.key]
    assert stored.document == {"from": "the newer tab"}
    assert stored.version == current.draft.version


async def test_the_refused_payload_is_kept_for_recovery(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Refusing a save must not be the same thing as deleting it.

    The rejected client may be the one that has been edited for an hour. Its
    payload is kept beside the draft, with both versions recorded, so its owner
    can look at what they lost before deciding to throw it away.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"from": "the newer tab"}
    )

    with pytest.raises(DraftVersionConflict) as refused:
        await library.async_autosave_draft(
            admin,
            label_size_id=SIZE,
            document={"from": "the older tab"},
            expected_version=1,
        )

    kept = refused.value.draft.recovery  # type: ignore[attr-defined]
    assert kept is not None
    assert kept.reason == REJECTED_SAVE
    assert kept.document == {"from": "the older tab"}
    assert kept.expected_version == 1
    assert kept.draft_version == 2


async def test_a_refused_payload_survives_a_restart(libraries: Any, admin: Any) -> None:
    """Because the client that lost it may not come back before the reboot."""
    library = libraries()
    await library.async_load()
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"kept": True}
    )
    with pytest.raises(DraftVersionConflict):
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document={"lost": True}, expected_version=1
        )

    reopened = libraries()
    await reopened.async_load()

    draft = next(iter(reopened.state.drafts.values()))
    assert draft.document == {"kept": True}
    assert draft.recovery is not None
    assert draft.recovery.document == {"lost": True}


async def test_a_save_that_names_no_version_is_taken_at_its_word(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A client that has read nothing is not pretending to have read something.

    Compare-and-swap is the caller's protection, and making it mandatory would
    refuse the first autosave of every editor that has not implemented it yet.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"first": True}
    )

    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"second": True}
    )

    assert saved.draft.document == {"second": True}
    assert saved.draft.version == 3
    assert saved.draft.recovery is None


async def test_a_save_at_the_version_it_read_lands(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The ordinary path: read version N, write version N, get N+1."""
    created = await library.async_create_draft(admin, label_size_id=SIZE)

    saved = await library.async_autosave_draft(
        admin,
        label_size_id=SIZE,
        document={"edited": True},
        expected_version=created.version,
    )

    assert saved.draft.version == created.version + 1
    assert saved.draft.document == {"edited": True}


async def test_an_ordinary_save_leaves_the_recovery_payload_alone(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A client saving newer work has not necessarily looked at what was kept.

    Clearing the slot on the next keystroke would make the promise worthless
    exactly when it matters: the tab that was refused is not the tab that is
    still typing.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)
    with pytest.raises(DraftVersionConflict):
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document={"refused": True}, expected_version=99
        )

    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"carrying on": True}
    )

    assert saved.draft.recovery is not None
    assert saved.draft.recovery.document == {"refused": True}


async def test_only_its_owner_clears_the_recovery_payload(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One explicit call, and it refuses when there is nothing kept."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    with pytest.raises(NoRecoveryPayload):
        await library.async_discard_recovery(admin, label_size_id=SIZE)
    with pytest.raises(DraftVersionConflict):
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document={"refused": True}, expected_version=99
        )

    cleared = await library.async_discard_recovery(admin, label_size_id=SIZE)

    assert cleared.recovery is None
    assert cleared.document is not None


async def test_the_most_recent_rejection_is_the_one_kept(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One slot. A second refusal is newer work than the first, not extra work."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    for attempt in ("first", "second"):
        with pytest.raises(DraftVersionConflict):
            await library.async_autosave_draft(
                admin,
                label_size_id=SIZE,
                document={"attempt": attempt},
                expected_version=99,
            )

    draft = next(iter(library.state.drafts.values()))
    assert draft.recovery is not None
    assert draft.recovery.document == {"attempt": "second"}


# ---------------------------------------------------------------------------
# Publication compares the base revision
# ---------------------------------------------------------------------------


async def test_two_administrators_on_one_base_and_the_first_publication_wins(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Neither of them locked anything, so the check has to be the revision.

    Both open the same head, both edit, and the second publication would append
    over a revision it never saw -- dropping the first administrator's work out
    of a history that claims to be complete.
    """
    published = await _named_template(library, admin)
    template_id = published.template.id
    head = published.revision.document
    await library.async_open_draft(admin, template_id)
    await library.async_open_draft(other_admin, template_id)
    await library.async_autosave_draft(
        admin, template_id=template_id, document=_edited(head, y_mm=6.0)
    )
    await library.async_autosave_draft(
        other_admin, template_id=template_id, document=_edited(head, y_mm=9.0)
    )

    first = await library.async_publish_draft(admin, template_id=template_id)
    with pytest.raises(DraftIsStale) as refused:
        await library.async_publish_draft(other_admin, template_id=template_id)

    assert first.revision.revision == 2
    assert refused.value.base_revision == 1
    assert refused.value.head == 2
    assert library.state.templates[template_id].head.revision == 2


async def test_a_refused_publication_leaves_the_stale_draft_exactly_as_it_was(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """The work is not the problem; its base is."""
    published = await _named_template(library, admin)
    template_id = published.template.id
    head = published.revision.document
    await library.async_open_draft(admin, template_id)
    losing = await library.async_open_draft(other_admin, template_id)
    saved = await library.async_autosave_draft(
        other_admin, template_id=template_id, document=_edited(head, y_mm=9.0)
    )
    await library.async_autosave_draft(
        admin, template_id=template_id, document=_edited(head, y_mm=6.0)
    )
    await library.async_publish_draft(admin, template_id=template_id)

    with pytest.raises(DraftIsStale):
        await library.async_publish_draft(other_admin, template_id=template_id)

    stale = library.state.drafts[losing.key]
    assert stale.document == saved.draft.document
    assert stale.version == saved.draft.version
    assert stale.base_revision == 1


async def test_a_draft_at_the_head_publishes(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The ordinary path, so the staleness check is not refusing everything."""
    published = await _named_template(library, admin)
    template_id = published.template.id
    await library.async_open_draft(admin, template_id)
    await library.async_autosave_draft(
        admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=6.0),
    )

    again = await library.async_publish_draft(admin, template_id=template_id)

    assert again.revision.revision == 2
    assert again.revision.parent_revision == 1


async def test_an_untitled_draft_is_never_stale(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """It is based on nothing, so there is no head for it to fall behind."""
    await library.async_create_draft(other_admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        other_admin, label_size_id=SIZE, document=blank_document(SIZE), name="Mine"
    )
    await _named_template(library, admin, name="Somebody else's")

    published = await library.async_publish_draft(other_admin, label_size_id=SIZE)

    assert published.revision.revision == 1
    assert published.template.name == "Mine"


async def test_a_snapshot_says_which_of_an_administrators_drafts_are_stale(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """So an editor can disable Publish before the refusal rather than after it."""
    published = await _named_template(library, admin)
    template_id = published.template.id
    await library.async_open_draft(admin, template_id)
    await library.async_open_draft(other_admin, template_id)
    await library.async_autosave_draft(
        admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=6.0),
    )
    await library.async_publish_draft(admin, template_id=template_id)

    snapshot = await library.async_snapshot(other_admin)

    assert [item["stale"] for item in snapshot["drafts"]] == [True]
    assert [item["head_revision"] for item in snapshot["drafts"]] == [2]


async def test_an_autosave_answers_with_its_own_staleness(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """The editor learns it on the next keystroke, not on the failed publish."""
    published = await _named_template(library, admin)
    template_id = published.template.id
    await library.async_open_draft(admin, template_id)
    await library.async_open_draft(other_admin, template_id)
    await library.async_autosave_draft(
        admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=6.0),
    )
    await library.async_publish_draft(admin, template_id=template_id)

    saved = await library.async_autosave_draft(
        other_admin, template_id=template_id, document={"still typing": True}
    )

    assert saved.stale is True
    assert saved.head_revision == 2
    assert saved.as_dict()["stale"] is True


# ---------------------------------------------------------------------------
# A retry is not a second call
# ---------------------------------------------------------------------------


async def test_a_retried_publication_creates_exactly_one_revision(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The timeout case: the write landed and the answer did not come back."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )

    first = await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )
    again = await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )

    assert first.replayed is False
    assert again.replayed is True
    assert again.template.id == first.template.id
    assert again.revision.revision == first.revision.revision
    assert len(library.state.templates) == 1
    assert library.state.generation == 1


async def test_a_retried_default_change_advances_the_generation_once(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Because the generation is what every other client reconciles against."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)

    first = await library.async_set_default(
        admin, SIZE, ref, idempotency_key="default-1"
    )
    again = await library.async_set_default(
        admin, SIZE, ref, idempotency_key="default-1"
    )

    assert first.generation == 2
    assert again.generation == 2
    assert again.replayed is True
    assert again.override == ref


async def test_a_retried_autosave_does_not_advance_the_draft_version(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A retried save is the same save; a second version would be a second edit.

    It is also what makes compare-and-swap survivable: a client that retries a
    save it has already made would otherwise be told its own write was stale.
    """
    created = await library.async_create_draft(admin, label_size_id=SIZE)

    first = await library.async_autosave_draft(
        admin,
        label_size_id=SIZE,
        document={"edited": True},
        expected_version=created.version,
        idempotency_key="save-1",
    )
    again = await library.async_autosave_draft(
        admin,
        label_size_id=SIZE,
        document={"edited": True},
        expected_version=created.version,
        idempotency_key="save-1",
    )

    assert first.draft.version == 2
    assert again.draft.version == 2
    assert again.replayed is True
    assert again.draft.document == {"edited": True}


async def test_a_retried_draft_creation_returns_the_same_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Rather than a second untitled draft in the same slot."""
    first = await library.async_create_draft(
        admin, label_size_id=SIZE, idempotency_key="create-1"
    )
    again = await library.async_create_draft(
        admin, label_size_id=SIZE, idempotency_key="create-1"
    )

    assert again.id == first.id
    assert len(library.state.drafts) == 1


async def test_a_retried_discard_reports_what_it_removed_and_removes_nothing(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The draft is gone either way; only one of the two calls removed it.

    The replay carries no payload, because the work it names was removed by the
    first attempt -- handing one back would claim this call had it to lose.
    """
    created = await library.async_create_draft(admin, label_size_id=SIZE)

    first = await library.async_discard_draft(
        admin, label_size_id=SIZE, idempotency_key="discard-1"
    )
    again = await library.async_discard_draft(
        admin, label_size_id=SIZE, idempotency_key="discard-1"
    )

    assert first.draft_id == created.id
    assert first.draft is not None
    assert again.draft_id == created.id
    assert again.draft is None
    assert again.replayed is True
    assert library.state.drafts == {}


async def test_a_discard_without_a_key_is_refused_the_second_time(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Idempotency is the client's to ask for; without it the slot is empty."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_discard_draft(admin, label_size_id=SIZE)

    with pytest.raises(DraftNotFound):
        await library.async_discard_draft(admin, label_size_id=SIZE)


async def test_a_key_presented_for_a_different_call_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One key identifies one intended mutation, not a licence to write twice."""
    created = await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin,
        label_size_id=SIZE,
        document={"first": True},
        expected_version=created.version,
        idempotency_key="save-1",
    )

    with pytest.raises(IdempotencyKeyReused) as refused:
        await library.async_autosave_draft(
            admin,
            label_size_id=SIZE,
            document={"different": True},
            idempotency_key="save-1",
        )

    assert refused.value.key == "save-1"
    assert library.state.drafts[created.key].document == {"first": True}


async def test_another_administrators_identical_key_is_not_a_replay(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """A key is a client's private token, and keys are opaque strings.

    Answering somebody else's key would let one administrator learn that
    another had published, and would hand them a draft that is not theirs.
    """
    await library.async_create_draft(
        admin, label_size_id=SIZE, idempotency_key="shared-string"
    )

    mine = await library.async_create_draft(
        other_admin, label_size_id=SIZE, idempotency_key="shared-string"
    )

    assert mine.owner == other_admin.user_id
    assert len(library.state.drafts) == 2


async def test_a_replay_survives_a_restart(libraries: Any, admin: Any) -> None:
    """The failure a key protects against is the one that also loses answers."""
    library = libraries()
    await library.async_load()
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    first = await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )

    reopened = libraries()
    await reopened.async_load()
    again = await reopened.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )

    assert again.replayed is True
    assert again.revision.revision == first.revision.revision
    assert len(reopened.state.templates) == 1


async def test_the_ledger_remembers_a_retry_window_rather_than_a_history(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """It is persisted, so an unbounded one would grow with every autosave."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    for index in range(COMMIT_LEDGER_LIMIT + 5):
        await library.async_autosave_draft(
            admin,
            label_size_id=SIZE,
            document={"keystroke": index},
            idempotency_key=f"save-{index}",
        )

    keys = [record.key for record in library.state.commits]
    assert len(keys) == COMMIT_LEDGER_LIMIT
    assert keys[-1] == f"save-{COMMIT_LEDGER_LIMIT + 4}"
    assert "save-0" not in keys


async def test_a_mutation_without_a_key_records_nothing(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A caller that does not retry does not have to carry a token."""
    await _named_template(library, admin)

    assert library.state.commits == ()


# ---------------------------------------------------------------------------
# Change events, and the gap they make visible
# ---------------------------------------------------------------------------


async def test_a_publication_announces_the_generation_it_replaced(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Identities and numbers, never the document.

    A client that treated the event as the state would be assembling a second
    source of truth out of messages it might not have received.
    """
    published = await _named_template(library, admin)

    assert changes == [
        {
            "entry_id": library.entry_id,
            "generation": 1,
            "previous_generation": 0,
            "operation": PUBLISHED,
            "template_id": published.template.id,
            "revision": 1,
            "label_size_id": SIZE,
        }
    ]


async def test_default_changes_announce_themselves(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Selecting and clearing are both committed library state."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)

    await library.async_set_default(admin, SIZE, ref)
    await library.async_clear_default(admin, SIZE)

    assert [item["operation"] for item in changes] == [
        PUBLISHED,
        DEFAULT_SET,
        DEFAULT_CLEARED,
    ]
    assert changes[1]["template_id"] == published.template.id
    assert changes[2]["label_size_id"] == SIZE


async def test_every_event_names_the_generation_before_it(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Which is the whole of gap detection: a client holding N applies an event
    whose previous is N, and refreshes its snapshot when it is anything else."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    await library.async_clear_default(admin, SIZE)

    assert [(item["previous_generation"], item["generation"]) for item in changes] == [
        (0, 1),
        (1, 2),
        (2, 3),
    ]


async def test_a_draft_announces_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """A draft is private and unpublished, so no other client can act on it.

    The same reason it does not advance the Library Generation: announcing
    every keystroke would make everybody refresh for something none of them
    can read.
    """
    created = await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"typing": True}
    )
    await library.async_discard_draft(admin, label_size_id=SIZE)

    assert created.version == 1
    assert changes == []
    assert library.state.generation == 0


async def test_a_replayed_mutation_announces_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Nothing committed, so there is nothing for anybody to reconcile."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )

    await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )

    assert len(changes) == 1


async def test_selecting_what_is_already_selected_announces_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """Nothing was written, so there is no change to be told about."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)
    await library.async_set_default(admin, SIZE, ref)

    unchanged = await library.async_set_default(admin, SIZE, ref)

    assert unchanged.unchanged is True
    assert len(changes) == 2


async def test_a_failed_commit_announces_nothing(
    library: LabelTemplateLibrary, admin: Any, changes: list[dict[str, Any]]
) -> None:
    """An event for a write that did not land would send every client to fetch
    the state it was told had been replaced."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )

    with (
        patch.object(
            library._store,
            "async_save",
            AsyncMock(side_effect=OSError("disk full")),
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await library.async_publish_draft(admin, label_size_id=SIZE)

    assert changes == []
    assert library.state.generation == 0


async def test_recovering_from_a_gap_does_not_touch_an_open_draft(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """The refresh after a missed event is a read.

    If catching up cost an editor its unsaved work, a dropped websocket would
    be more destructive than the concurrent edit it exists to survive.
    """
    published = await _named_template(library, admin)
    template_id = published.template.id
    await library.async_open_draft(admin, template_id)
    mine = await library.async_open_draft(other_admin, template_id)
    saved = await library.async_autosave_draft(
        other_admin, template_id=template_id, document={"unsaved": "work"}
    )
    await library.async_autosave_draft(
        admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=6.0),
    )
    await library.async_publish_draft(admin, template_id=template_id)

    snapshot = await library.async_snapshot(other_admin)

    assert snapshot["generation"] == 2
    kept = library.state.drafts[mine.key]
    assert kept.document == {"unsaved": "work"}
    assert kept.version == saved.draft.version
    assert snapshot["drafts"][0]["document"] == {"unsaved": "work"}


# ---------------------------------------------------------------------------
# A stale draft is its owner's to resolve
# ---------------------------------------------------------------------------


async def _stale_draft(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> tuple[str, Any]:
    """Leave `other_admin` holding a valid draft of an overtaken revision."""
    published = await _named_template(library, admin)
    template_id = published.template.id
    await library.async_open_draft(admin, template_id)
    await library.async_open_draft(other_admin, template_id)
    mine = await library.async_autosave_draft(
        other_admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=12.0),
    )
    await library.async_autosave_draft(
        admin,
        template_id=template_id,
        document=_edited(published.revision.document, y_mm=6.0),
    )
    await library.async_publish_draft(admin, template_id=template_id)
    return template_id, mine.draft


async def test_a_stale_draft_can_still_be_previewed(
    library: LabelTemplateLibrary,
    admin: Any,
    other_admin: Any,
    printer: list[dict[str, Any]],
) -> None:
    """Seeing it beside the revision that overtook it is how its owner decides."""
    template_id, _ = await _stale_draft(library, admin, other_admin)

    result = await library.async_preview_draft(other_admin, template_id=template_id)

    assert result.raster is not None
    assert printer


async def test_a_stale_draft_can_be_discarded(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Throwing it away is always available, and says what it threw away."""
    template_id, draft = await _stale_draft(library, admin, other_admin)

    discarded = await library.async_discard_draft(other_admin, template_id=template_id)

    assert discarded.draft_id == draft.id
    assert discarded.draft is not None
    assert discarded.draft.document == draft.document
    assert draft.key not in library.state.drafts


async def test_reloading_takes_the_head_and_keeps_the_payload_it_replaced(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Reload is discard-and-reopen in one commit, and it merges nothing.

    The new draft is the published head, byte for byte. What the owner was
    working on moves into the recovery slot, which is what "reapply the parts
    worth keeping" reads from -- by hand, because two independently moved
    layouts compose into overlap and clipping neither editor asked for.
    """
    template_id, mine = await _stale_draft(library, admin, other_admin)
    head = library.state.templates[template_id].head

    reloaded = await library.async_reload_draft(other_admin, template_id)

    assert reloaded.base_revision == head.revision == 2
    assert reloaded.document == head.document
    assert reloaded.version == 1
    assert reloaded.recovery is not None
    assert reloaded.recovery.reason == RELOADED
    assert reloaded.recovery.document == mine.document
    assert len(library.state.drafts) == 1


async def test_a_reloaded_draft_publishes(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Which is the point: reloading is how a stale editor becomes current."""
    template_id, _ = await _stale_draft(library, admin, other_admin)
    await library.async_reload_draft(other_admin, template_id)
    await library.async_autosave_draft(
        other_admin,
        template_id=template_id,
        document=_edited(library.state.templates[template_id].head.document, y_mm=15.0),
    )

    published = await library.async_publish_draft(other_admin, template_id=template_id)

    assert published.revision.revision == 3
    assert published.revision.parent_revision == 2


async def test_a_retried_reload_returns_the_same_draft(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """A second reload of a reloaded draft would throw away the recovery slot."""
    template_id, _ = await _stale_draft(library, admin, other_admin)

    first = await library.async_reload_draft(
        other_admin, template_id, idempotency_key="reload-1"
    )
    again = await library.async_reload_draft(
        other_admin, template_id, idempotency_key="reload-1"
    )

    assert again.id == first.id
    assert again.recovery == first.recovery


async def test_reload_and_recovery_are_administrators_only(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Every draft mutation is, and these two are draft mutations."""
    published = await _named_template(library, admin)

    with pytest.raises(Unauthorized):
        await library.async_reload_draft(viewer, published.template.id)
    with pytest.raises(Unauthorized):
        await library.async_discard_recovery(viewer, label_size_id=SIZE)


async def test_a_replayed_creation_whose_draft_has_gone_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A spent key does not get to create a second draft in an empty slot.

    The first attempt's work was discarded between the two calls. Answering
    with a fresh draft would be indistinguishable from the retry having worked,
    and would quietly undo the discard.
    """
    await library.async_create_draft(
        admin, label_size_id=SIZE, idempotency_key="create-1"
    )
    await library.async_discard_draft(admin, label_size_id=SIZE)

    with pytest.raises(DraftNotFound):
        await library.async_create_draft(
            admin, label_size_id=SIZE, idempotency_key="create-1"
        )

    assert library.state.drafts == {}


async def test_a_replayed_publication_whose_revision_has_gone_says_so(
    hass: HomeAssistant, libraries: Any, admin: Any
) -> None:
    """Revisions are immutable and nothing removes one today, so this is the
    ledger outliving what it points at -- which soft deletion will make real."""
    library = libraries()
    await library.async_load()
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    await library.async_publish_draft(
        admin, label_size_id=SIZE, idempotency_key="publish-1"
    )
    await LabelTemplateStore(hass, library.entry_id).async_save(
        replace(library.state, templates={})
    )

    reopened = libraries()
    await reopened.async_load()

    with pytest.raises(RevisionNotFound):
        await reopened.async_publish_draft(
            admin, label_size_id=SIZE, idempotency_key="publish-1"
        )


async def test_a_retried_recovery_discard_returns_the_cleared_draft(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Rather than refusing because there is nothing left to clear."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    with pytest.raises(DraftVersionConflict):
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document={"refused": True}, expected_version=99
        )

    first = await library.async_discard_recovery(
        admin, label_size_id=SIZE, idempotency_key="clear-1"
    )
    again = await library.async_discard_recovery(
        admin, label_size_id=SIZE, idempotency_key="clear-1"
    )

    assert first.recovery is None
    assert again.id == first.id
    assert again.recovery is None


async def test_a_retried_clear_of_a_default_advances_the_generation_once(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The same guarantee selecting one has, for the call that undoes it."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )

    first = await library.async_clear_default(admin, SIZE, idempotency_key="clear-1")
    again = await library.async_clear_default(admin, SIZE, idempotency_key="clear-1")

    assert first.generation == 3
    assert again.generation == 3
    assert again.replayed is True
    assert again.override is None
