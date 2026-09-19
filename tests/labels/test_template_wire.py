"""The wire forms the library answers in (hub issue #217).

Nothing is registered as a websocket command yet -- the Template Capability is
advertised as one complete envelope once every required v1 operation exists.
These are the payloads that envelope will carry, pinned here so the shape a
card reads is a decision rather than whatever `asdict` produced on the day.

Two rules run through them. A listing never carries a document: the snapshot
and every summary describe identities and history, and the layout comes back
only when something asked to resolve one. And a reference always names its
kind beside its identity, so a factory ID and a template UUID cannot be told
apart by their shape alone.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30
from custom_components.growspace_manager.labels.library import (
    FACTORY_FALLBACK,
    OVERRIDE,
    PUBLISH,
    REJECTED_SAVE,
    RENAME,
    RESTORE,
    DraftVersionConflict,
    LabelTemplateLibrary,
    TemplateRef,
    blank_document,
    check_document,
)

SIZE = "growspace.stock.50x30.v1"


async def _named_template(library: LabelTemplateLibrary, admin: Any) -> Any:
    """Publish one Named Template."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
    )
    return await library.async_publish_draft(admin, label_size_id=SIZE)


async def test_an_autosave_answers_with_the_draft_and_its_check(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Both halves at once: the work was kept, and here is why Publish is off."""
    await library.async_create_draft(admin, label_size_id=SIZE)

    saved = await library.async_autosave_draft(
        admin, label_size_id=SIZE, document={"nothing": "yet"}, name="Clone tags"
    )
    wire = saved.as_dict()

    assert wire["draft"]["version"] == 2
    assert wire["draft"]["name"] == "Clone tags"
    assert wire["draft"]["document"] == {"nothing": "yet"}
    assert wire["validation"]["operation"] == PUBLISH
    assert wire["validation"]["allowed"] is False
    assert wire["validation"]["diagnostics"][0]["code"]
    assert wire["validation"]["diagnostics"][0]["recovery"]


def test_a_publication_check_is_spelled_in_the_eligibility_vocabulary() -> None:
    """The card reads one answer per operation; this is publish's."""
    passing = check_document(blank_document(SIZE)).as_dict()

    assert passing == {"operation": PUBLISH, "allowed": True, "diagnostics": []}


async def test_a_publication_answers_with_summaries_rather_than_documents(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """History is what a listing needs; the layout is what resolution returns."""
    published = await _named_template(library, admin)

    wire = published.as_dict()

    assert wire["replayed"] is False
    assert wire["generation"] == 1
    assert wire["template"]["kind"] == "named"
    assert wire["template"]["name"] == "Clone tags"
    assert wire["template"]["head_revision"] == 1
    assert "document" not in wire["revision"]
    assert all("document" not in item for item in wire["template"]["revisions"])
    assert wire["revision"]["provenance"]["source"] == "blank"


async def test_a_default_change_answers_with_what_now_resolves(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The override and its consequence together, so neither is inferred."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)

    selected = (await library.async_set_default(admin, SIZE, ref)).as_dict()
    cleared = (await library.async_clear_default(admin, SIZE)).as_dict()

    assert selected["override"] == ref.as_dict()
    assert selected["effective"]["via"] == OVERRIDE
    assert selected["unchanged"] is False
    assert cleared["override"] is None
    assert (
        cleared["effective"]["ref"] == TemplateRef.factory(FACTORY_50X30.id).as_dict()
    )
    assert cleared["effective"]["via"] == FACTORY_FALLBACK
    assert "document" not in cleared["effective"]


async def test_a_resolution_is_the_one_answer_that_carries_the_layout(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Because a render is the only thing that needs it."""
    published = await _named_template(library, admin)

    wire = (
        await library.async_resolve(viewer, TemplateRef.named(published.template.id))
    ).as_dict()

    assert wire["revision"] == 1
    assert wire["name"] == "Clone tags"
    assert wire["label_size_id"] == SIZE
    assert wire["layout_digest"] == published.revision.digest
    assert wire["document"] == published.revision.document


async def test_a_snapshot_describes_the_whole_library_without_a_layout_in_it(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """One read a client can open the editor from."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    await library.async_create_draft(admin, label_size_id=SIZE)

    snapshot = await library.async_snapshot(admin)

    assert snapshot["entry_id"] == library.entry_id
    assert snapshot["generation"] == 2
    assert (
        snapshot["defaults"][SIZE] == TemplateRef.named(published.template.id).as_dict()
    )
    assert [item["name"] for item in snapshot["templates"]] == ["Clone tags"]
    assert all("document" not in item for item in snapshot["templates"])
    assert snapshot["drafts"][0]["owner"] == admin.user_id
    assert snapshot["drafts"][0]["document"]["label_size_id"] == SIZE


async def test_templates_are_listed_in_a_stable_order(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """By name, case-insensitively, so a listing does not reshuffle per save."""
    for name in ("zinnia", "Alpha", "mid"):
        await library.async_create_draft(admin, label_size_id=SIZE)
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document=blank_document(SIZE), name=name
        )
        await library.async_publish_draft(admin, label_size_id=SIZE)

    snapshot = await library.async_snapshot(admin)

    assert [item["name"] for item in snapshot["templates"]] == [
        "Alpha",
        "mid",
        "zinnia",
    ]


async def test_an_autosave_carries_the_staleness_the_draft_cannot_know(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Three answers in one payload: kept, publishable, and current.

    Staleness is a fact about the draft *and* its template, so it travels with
    the answer rather than being stored on the draft -- where somebody else's
    publication would have to reach back and rewrite it.
    """
    await library.async_create_draft(admin, label_size_id=SIZE)

    wire = (
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document=blank_document(SIZE), name="Clone tags"
        )
    ).as_dict()

    assert wire["stale"] is False
    assert wire["head_revision"] is None
    assert wire["replayed"] is False
    assert wire["draft"]["recovery"] is None


async def test_a_discard_answers_with_what_it_removed(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Identity first, payload beside it: an editor that has just thrown work
    away is the one place an undo could still be offered."""
    created = await library.async_create_draft(admin, label_size_id=SIZE)

    wire = (await library.async_discard_draft(admin, label_size_id=SIZE)).as_dict()

    assert wire["draft_id"] == created.id
    assert wire["owner"] == admin.user_id
    assert wire["label_size_id"] == SIZE
    assert wire["template_id"] is None
    assert wire["version"] == created.version
    assert wire["draft"]["id"] == created.id
    assert wire["replayed"] is False


async def test_a_refused_save_answers_with_the_payload_it_kept(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The recovery slot is part of the draft's wire form, so one read of the
    library tells an editor there is work waiting to be looked at."""
    await library.async_create_draft(admin, label_size_id=SIZE)
    with pytest.raises(DraftVersionConflict):
        await library.async_autosave_draft(
            admin, label_size_id=SIZE, document={"refused": True}, expected_version=99
        )

    snapshot = await library.async_snapshot(admin)

    kept = snapshot["drafts"][0]["recovery"]
    assert kept["reason"] == REJECTED_SAVE
    assert kept["document"] == {"refused": True}
    assert kept["expected_version"] == 99
    assert kept["draft_version"] == 1


async def test_a_managed_revision_says_which_act_appended_it(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """History is a record of deliberate acts, so each names the one it was.

    A client reading a template's revisions has to be able to tell a restore
    from the edit it reached back past, and a rename from a layout change --
    which is what turns a list of numbers into something worth showing.
    """
    published = await _named_template(library, admin)
    renamed = (
        await library.async_rename_template(admin, published.template.id, "Mother tags")
    ).as_dict()
    restored = (
        await library.async_restore_revision(admin, published.template.id, 1)
    ).as_dict()

    assert renamed["revision"]["operation"] == RENAME
    assert renamed["unchanged"] is False
    assert restored["revision"]["operation"] == RESTORE
    assert restored["revision"]["provenance"]["source_revision"] == 1
    assert [item["operation"] for item in restored["template"]["revisions"]] == [
        PUBLISH,
        RENAME,
        RESTORE,
    ]
    assert all("document" not in item for item in restored["template"]["revisions"])


async def test_a_call_that_asked_for_the_status_quo_says_so(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """`unchanged` is how a client distinguishes "nothing to do" from a write."""
    published = await _named_template(library, admin)

    wire = (
        await library.async_rename_template(admin, published.template.id, "Clone tags")
    ).as_dict()

    assert wire["unchanged"] is True
    assert wire["generation"] == published.generation
