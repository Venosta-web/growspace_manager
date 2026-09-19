"""Who may do what to the template library (hub issue #217).

Two lines of policy. Home Assistant administrators manage the library; any
authenticated user may list published templates, resolve the Effective Default
and render one. There is a third rule that matters more than either: **a
permission is not a lease**. Authority is asked again on every call, from the
acting user, so an editor opened by an administrator who is then demoted keeps
its draft and refuses its next save.

Drafts are the other half of this. A draft is unpublished work owned by one
administrator: another administrator cannot read it, save over it, discard it,
publish it or preview it, and it does not appear in their snapshot.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30
from custom_components.growspace_manager.labels.library import (
    Actor,
    DraftNotFound,
    LabelTemplateLibrary,
    TemplateRef,
    blank_document,
)
from homeassistant.exceptions import Unauthorized

SIZE = "growspace.stock.50x30.v1"


async def _named_template(library: LabelTemplateLibrary, admin: Actor) -> Any:
    """Publish one Named Template to have something to read."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    return await library.async_publish_draft(admin, label_size_id=SIZE)


#: Every mutation, spelled as the call a client would make. Parametrized
#: rather than written out per test, because the property is that *none* of
#: them is reachable -- and a new operation added without a row here is the
#: failure this shape is meant to make obvious.
MUTATIONS: dict[
    str, Callable[[LabelTemplateLibrary, Actor], Coroutine[Any, Any, Any]]
] = {
    "create_draft": lambda lib, actor: lib.async_create_draft(
        actor, label_size_id=SIZE
    ),
    "create_derived_draft": lambda lib, actor: lib.async_create_draft(
        actor, derive_from=TemplateRef.factory(FACTORY_50X30.id)
    ),
    "open_draft": lambda lib, actor: lib.async_open_draft(actor, "any-template"),
    "autosave_draft": lambda lib, actor: lib.async_autosave_draft(
        actor, label_size_id=SIZE, document=blank_document(SIZE)
    ),
    "discard_draft": lambda lib, actor: lib.async_discard_draft(
        actor, label_size_id=SIZE
    ),
    "publish_draft": lambda lib, actor: lib.async_publish_draft(
        actor, label_size_id=SIZE
    ),
    "set_default": lambda lib, actor: lib.async_set_default(
        actor, SIZE, TemplateRef.factory(FACTORY_50X30.id)
    ),
    "clear_default": lambda lib, actor: lib.async_clear_default(actor, SIZE),
    "preview_draft": lambda lib, actor: lib.async_preview_draft(
        actor, label_size_id=SIZE
    ),
}

READS: dict[str, Callable[[LabelTemplateLibrary, Actor], Coroutine[Any, Any, Any]]] = {
    "snapshot": lambda lib, actor: lib.async_snapshot(actor),
    "resolve_default": lambda lib, actor: lib.async_resolve_default(actor, SIZE),
    "resolve": lambda lib, actor: lib.async_resolve(
        actor, TemplateRef.factory(FACTORY_50X30.id)
    ),
}


@pytest.mark.parametrize("operation", list(MUTATIONS), ids=list(MUTATIONS))
async def test_a_non_administrator_can_mutate_nothing(
    library: LabelTemplateLibrary, admin: Actor, viewer: Actor, operation: str
) -> None:
    """Every management command is denied, and nothing is written."""
    await _named_template(library, admin)
    before = library.state

    with pytest.raises(Unauthorized):
        await MUTATIONS[operation](library, viewer)

    assert library.state is before


@pytest.mark.parametrize("operation", list(MUTATIONS), ids=list(MUTATIONS))
async def test_an_unattributed_request_mutates_nothing(
    library: LabelTemplateLibrary, nobody: Actor, operation: str
) -> None:
    """A mutation nobody made could not own a draft or sign a revision."""
    with pytest.raises(Unauthorized):
        await MUTATIONS[operation](library, nobody)


@pytest.mark.parametrize("operation", list(READS), ids=list(READS))
async def test_an_unattributed_request_reads_nothing(
    library: LabelTemplateLibrary, nobody: Actor, operation: str
) -> None:
    """Authenticated is the floor, including for reads."""
    with pytest.raises(Unauthorized):
        await READS[operation](library, nobody)


@pytest.mark.parametrize("operation", list(READS), ids=list(READS))
async def test_an_authenticated_user_may_read(
    library: LabelTemplateLibrary, admin: Actor, viewer: Actor, operation: str
) -> None:
    """Listing, resolving and using a published template is not privileged."""
    await _named_template(library, admin)

    assert await READS[operation](library, viewer) is not None


async def test_a_non_administrator_resolves_and_uses_the_published_revision(
    library: LabelTemplateLibrary, admin: Actor, viewer: Actor, printer: Any
) -> None:
    """The whole of what a non-administrator needs: which layout, and its raster."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )

    resolved = await library.async_resolve_default(viewer, SIZE)
    result = await library.async_preview_template(viewer, resolved.ref)

    assert resolved.revision == 1
    assert resolved.document == published.revision.document
    assert result.raster is not None
    assert printer


async def test_a_non_administrators_snapshot_carries_no_drafts(
    library: LabelTemplateLibrary, admin: Actor, viewer: Actor
) -> None:
    """Unpublished work is not part of what the library publishes."""
    await library.async_create_draft(admin, label_size_id=SIZE)

    assert (await library.async_snapshot(viewer))["drafts"] == []
    assert len((await library.async_snapshot(admin))["drafts"]) == 1


async def test_one_administrator_sees_only_their_own_drafts(
    library: LabelTemplateLibrary, admin: Actor, other_admin: Actor
) -> None:
    """Two administrators, two drafts, and neither snapshot holds the other."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_create_draft(other_admin, label_size_id=SIZE)

    mine = await library.async_snapshot(admin)
    theirs = await library.async_snapshot(other_admin)

    assert [draft["owner"] for draft in mine["drafts"]] == [admin.user_id]
    assert [draft["owner"] for draft in theirs["drafts"]] == [other_admin.user_id]


@pytest.mark.parametrize(
    "operation",
    ["autosave_draft", "discard_draft", "publish_draft", "preview_draft"],
)
async def test_another_administrator_cannot_reach_a_draft(
    library: LabelTemplateLibrary, admin: Actor, other_admin: Actor, operation: str
) -> None:
    """A draft is addressed through its owner, so there is no other way in."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )

    with pytest.raises(DraftNotFound):
        await MUTATIONS[operation](library, other_admin)

    assert len(library.state.drafts) == 1


async def test_a_demoted_administrators_draft_survives_and_stops_saving(
    library: LabelTemplateLibrary, admin: Actor
) -> None:
    """Permission at editor-open time is not a capability lease.

    The work is theirs and stays theirs. What they lose is the authority to
    change it, immediately -- and they get it back if the role comes back.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    demoted = Actor(user_id=admin.user_id, is_admin=False)

    with pytest.raises(Unauthorized):
        await library.async_autosave_draft(
            demoted, label_size_id=SIZE, document=blank_document(SIZE)
        )

    assert len(library.state.drafts) == 1
    restored = await library.async_publish_draft(admin, label_size_id=SIZE)
    assert restored.revision.published_by == admin.user_id


def test_an_actor_is_taken_from_the_home_assistant_user() -> None:
    """Identity and authority come from the user, never from the request body."""

    class _User:
        id = "abc123"
        is_admin = True

    assert Actor.from_user(_User()) == Actor(user_id="abc123", is_admin=True)
    assert Actor.from_user(None) == Actor(user_id=None, is_admin=False)
    assert Actor.from_user(None).is_authenticated is False
