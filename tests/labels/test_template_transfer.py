"""Moving Label Templates between installations (hub issue #220).

Two operations that look similar and promise opposite things, which is exactly
why they are two.

A **portable bundle** shares designs. It carries current revisions and the
identities, stock and dependencies they need, and deliberately nothing else --
no history, no drafts, no defaults, no tombstones, no Home Assistant user IDs.
Importing one is additive, all-or-nothing, and never resolves an identity
collision on its own: whichever side it picked would silently discard a design
somebody made.

A **backup** moves a library. It carries everything, including the things a
share leaves out, and restoring one *replaces* rather than merges -- because
two libraries cannot be reconciled without choosing, silently, for every UUID
they both hold.

What they have in common is the order of operations: verify, stage, validate
all of it, and only then write once. A refusal from either leaves the library
exactly as it was.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.labels.canonical import FACTORY_50X30, digest
from custom_components.growspace_manager.labels.library import (
    BUNDLE_SCHEMA,
    BUNDLE_VERSION,
    EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED,
    FROM_IMPORT,
    IMPORT,
    IMPORTED,
    RESTORED_BACKUP,
    STORE_VERSION,
    BackupNotRestorable,
    BundleNotReadable,
    DuplicateTemplateName,
    IdempotencyKeyReused,
    ImportCollision,
    IncompatibleBundle,
    IncompatibleTemplateStore,
    LabelTemplateLibrary,
    TemplateNotResolvable,
    TemplateProtected,
    TemplateRef,
    UnsupportedDependency,
    blank_document,
)
from homeassistant.core import Event, HomeAssistant, callback

SIZE = "growspace.stock.50x30.v1"


async def _named_template(
    library: LabelTemplateLibrary, admin: Any, *, name: str = "Clone tags"
) -> Any:
    """Publish one Named Template, for the tests about moving it."""
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


def _resealed(document: dict[str, Any]) -> dict[str, Any]:
    """Re-checksum an edited bundle or backup, the way its writer would have.

    Tampering tests need a document that is *wrong* rather than one that is
    merely unsigned: a refusal for a bad checksum would otherwise stand in for
    every refusal below it and prove none of them.
    """
    payload = {key: value for key, value in document.items() if key != "checksum"}
    return {**payload, "checksum": digest(payload)}


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
# What a bundle carries, and what it deliberately does not
# ---------------------------------------------------------------------------


async def test_a_bundle_carries_current_revisions_and_their_dependencies(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The design, what it is for, and everything it needs to print."""
    published = await _named_template(library, admin)
    await _revise(library, admin, published.template.id, y_mm=4.0)

    bundle = await library.async_export_templates(admin)

    assert bundle["schema"] == BUNDLE_SCHEMA
    assert bundle["version"] == BUNDLE_VERSION
    assert bundle["layout_schema_version"] == 1
    assert set(bundle["catalogues"]) == {"label_sizes", "bindings", "style_tokens"}
    (entry,) = bundle["templates"]
    assert entry["id"] == published.template.id
    assert entry["revision"] == 2
    assert entry["label_size_id"] == SIZE
    assert entry["dependencies"]["label_sizes"] == [SIZE]
    assert "strain.name" in entry["dependencies"]["bindings"]
    assert entry["dependencies"]["fonts"]
    assert entry["digest"] == library.state.templates[published.template.id].head.digest


async def test_a_bundle_is_a_share_rather_than_a_backup(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """No history, no drafts, no defaults, no tombstones, nobody's user ID."""
    kept = await _named_template(library, admin, name="Clone tags")
    await _revise(library, admin, kept.template.id, y_mm=4.0)
    await library.async_set_default(admin, SIZE, TemplateRef.named(kept.template.id))
    await library.async_open_draft(admin, kept.template.id)
    deleted = await _named_template(library, admin, name="Old tags")
    await library.async_delete_template(admin, deleted.template.id)

    bundle = await library.async_export_templates(admin)

    assert [entry["id"] for entry in bundle["templates"]] == [kept.template.id]
    (entry,) = bundle["templates"]
    assert "revisions" not in entry
    assert "published_by" not in entry
    assert entry["provenance"]["draft_id"] is None
    assert entry["provenance"]["draft_version"] is None
    assert "defaults" not in bundle
    assert "drafts" not in bundle
    assert "tombstones" not in bundle


async def test_a_factory_template_is_not_shipped_inside_a_bundle(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The other installation has its own, and two copies would disagree."""
    with pytest.raises(TemplateProtected):
        await library.async_export_templates(
            admin, [TemplateRef.factory(FACTORY_50X30.id)]
        )


async def test_exporting_names_which_templates_to_carry(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """All of them, or the ones asked for."""
    first = await _named_template(library, admin, name="Clone tags")
    await _named_template(library, admin, name="Mother tags")

    everything = await library.async_export_templates(admin)
    chosen = await library.async_export_templates(
        admin, [TemplateRef.named(first.template.id)]
    )

    assert len(everything["templates"]) == 2
    assert [entry["id"] for entry in chosen["templates"]] == [first.template.id]


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------


async def test_an_identity_nobody_has_arrives_as_itself(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, viewer: Any
) -> None:
    """Preserved UUID, revision 1, saved, and not anybody's default."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    await _revise(source, admin, published.template.id, y_mm=4.0)
    bundle = await source.async_export_templates(admin)

    imported = await target.async_import_templates(admin, bundle)

    (arrived,) = imported.imported
    assert arrived.id == published.template.id
    assert arrived.head.revision == 1
    assert arrived.head.operation == IMPORT
    assert arrived.head.provenance.source == FROM_IMPORT
    assert arrived.head.provenance.source_template_id == published.template.id
    assert arrived.head.provenance.source_revision == 2
    assert target.state.defaults == {}
    assert target.state.drafts == {}
    assert (
        await target.async_resolve(viewer, TemplateRef.named(published.template.id))
    ).layout.digest == bundle["templates"][0]["digest"]


async def test_importing_the_same_bundle_twice_changes_nothing(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Acceptance case 17: identical identity and content is already here."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    await target.async_import_templates(admin, bundle)
    after = target.state

    again = await target.async_import_templates(admin, bundle)

    assert again.unchanged == (published.template.id,)
    assert again.imported == ()
    assert again.generation == after.generation
    assert target.state is after


async def test_a_divergent_identity_is_the_administrator_to_settle(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Acceptance case 17 again: neither side may be discarded silently."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    await target.async_import_templates(admin, bundle)
    await _revise(source, admin, published.template.id, y_mm=8.0)
    moved = await source.async_export_templates(admin)
    before = target.state

    with pytest.raises(ImportCollision) as refused:
        await target.async_import_templates(admin, moved)
    assert refused.value.template_id == published.template.id
    assert target.state is before

    copied = await target.async_import_templates(
        admin,
        moved,
        as_copy=[published.template.id],
        names={published.template.id: "Clone tags (theirs)"},
    )

    (fresh,) = copied.imported
    assert fresh.id != published.template.id
    assert copied.copies == {published.template.id: fresh.id}
    assert (
        target.state.templates[published.template.id].head.digest != fresh.head.digest
    )


async def test_an_identity_deleted_here_is_a_collision_too(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Importing over a tombstone would resurrect it behind somebody's back."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    await target.async_import_templates(admin, bundle)
    await target.async_delete_template(admin, published.template.id)
    before = target.state

    with pytest.raises(ImportCollision) as refused:
        await target.async_import_templates(admin, bundle)

    assert "deleted" in str(refused.value)
    assert target.state is before


async def test_a_name_another_template_holds_must_be_resolved_first(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Names are unique within a stock, however the template got here."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin, name="Clone tags")
    bundle = await source.async_export_templates(admin)
    holder = await _named_template(target, admin, name="Clone tags")
    incoming = bundle["templates"][0]["id"]
    before = target.state

    with pytest.raises(DuplicateTemplateName) as refused:
        await target.async_import_templates(admin, bundle)
    assert refused.value.template_id == holder.template.id
    assert target.state is before

    imported = await target.async_import_templates(
        admin, bundle, names={incoming: "Clone tags (theirs)"}
    )

    (arrived,) = imported.imported
    assert arrived.name == "Clone tags (theirs)"
    assert arrived.id == incoming


async def test_two_entries_of_one_bundle_cannot_claim_the_same_name(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Names are checked against the library as this import would leave it."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    first = await _named_template(source, admin, name="Clone tags")
    second = await _named_template(source, admin, name="Mother tags")
    bundle = await source.async_export_templates(admin)

    with pytest.raises(DuplicateTemplateName):
        await target.async_import_templates(
            admin,
            bundle,
            names={first.template.id: "Same", second.template.id: "Same"},
        )

    assert target.state.templates == {}


async def test_an_import_is_all_of_it_or_none_of_it(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Acceptance case 16: the second entry colliding stops the first arriving."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin, name="Clone tags")
    clashing = await _named_template(source, admin, name="Mother tags")
    bundle = await source.async_export_templates(admin)
    await _named_template(target, admin, name="Mother tags")
    before = target.state

    with pytest.raises(DuplicateTemplateName):
        await target.async_import_templates(admin, bundle)

    assert target.state is before
    assert clashing.template.id not in target.state.templates
    assert len(target.state.templates) == 1


async def test_one_identity_twice_in_a_bundle_collides_with_itself(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """The entries of a bundle are checked against each other, not only against us.

    A bundle carrying one UUID twice with two layouts is broken however it got
    that way, and taking the last one silently would be the library picking
    between two designs -- the one thing an import never does.
    """
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    await _revise(source, admin, published.template.id, y_mm=8.0)
    moved = await source.async_export_templates(admin)
    doubled = _resealed(
        {**bundle, "templates": [bundle["templates"][0], moved["templates"][0]]}
    )

    with pytest.raises(ImportCollision):
        await target.async_import_templates(admin, doubled)

    assert target.state.templates == {}


async def test_a_newer_bundle_fails_preflight_and_names_the_version(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Acceptance case 16: an upgrade, never a partial import."""
    source_template = await _named_template(library, admin)
    bundle = await library.async_export_templates(admin)
    before = library.state

    with pytest.raises(IncompatibleBundle) as refused:
        await library.async_import_templates(
            admin, _resealed({**bundle, "version": BUNDLE_VERSION + 1})
        )

    assert refused.value.found == BUNDLE_VERSION + 1
    assert refused.value.supported == BUNDLE_VERSION
    assert library.state is before
    assert list(library.state.templates) == [source_template.template.id]


async def test_a_damaged_bundle_is_not_partially_read(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A wrong checksum and a missing field are the same refusal."""
    await _named_template(library, admin)
    bundle = await library.async_export_templates(admin)
    before = library.state

    with pytest.raises(BundleNotReadable):
        await library.async_import_templates(
            admin, {**bundle, "checksum": "sha256:not-the-one"}
        )
    with pytest.raises(BundleNotReadable):
        await library.async_import_templates(
            admin, _resealed({**bundle, "schema": "something.else"})
        )

    assert library.state is before


async def test_a_bundle_whose_digest_does_not_describe_its_layout_is_refused(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The entry's own claim about its content has to be true."""
    await _named_template(library, admin)
    bundle = await library.async_export_templates(admin)
    entry = {**bundle["templates"][0], "digest": "sha256:something-else"}

    with pytest.raises(BundleNotReadable, match="digest"):
        await library.async_import_templates(
            admin, _resealed({**bundle, "templates": [entry]})
        )


async def test_a_dependency_this_installation_lacks_is_named_not_dropped(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """A label missing its lineage line prints wrongly without saying so."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    entry = bundle["templates"][0]
    entry = {
        **entry,
        "dependencies": {
            **entry["dependencies"],
            "bindings": [*entry["dependencies"]["bindings"], "strain.horoscope"],
        },
    }

    with pytest.raises(UnsupportedDependency) as refused:
        await target.async_import_templates(
            admin, _resealed({**bundle, "templates": [entry]})
        )

    assert refused.value.missing == ("bindings:strain.horoscope",)
    assert target.state.templates == {}


async def test_a_layout_this_installation_cannot_compile_is_refused(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Import is where a document has to be something we can print."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    entry = {
        **bundle["templates"][0],
        "document": {"schema": "growspace.label-layout", "version": 1},
    }

    with pytest.raises(TemplateNotResolvable):
        await target.async_import_templates(
            admin, _resealed({**bundle, "templates": [entry]})
        )

    assert target.state.templates == {}


async def test_an_import_announces_itself_once(
    libraries: Callable[..., LabelTemplateLibrary],
    admin: Any,
    changes: list[dict[str, Any]],
    hass: HomeAssistant,
) -> None:
    """One generation advance for the bundle, however many templates it held."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin, name="Clone tags")
    await _named_template(source, admin, name="Mother tags")
    bundle = await source.async_export_templates(admin)
    changes.clear()

    imported = await target.async_import_templates(admin, bundle)
    await hass.async_block_till_done()

    assert len(imported.imported) == 2
    assert [item["operation"] for item in changes if item["entry_id"] == "entry-b"] == [
        IMPORTED
    ]
    assert target.state.generation == 1


async def test_a_replayed_import_imports_once(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Acceptance case 11, for an import."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    published = await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    first = await target.async_import_templates(admin, bundle, idempotency_key="key-1")
    after = target.state

    replay = await target.async_import_templates(admin, bundle, idempotency_key="key-1")

    assert replay.replayed is True
    assert [item.id for item in replay.imported] == [item.id for item in first.imported]
    assert target.state.as_dict() == after.as_dict()
    assert list(target.state.templates) == [published.template.id]

    with pytest.raises(IdempotencyKeyReused):
        await target.async_import_templates(
            admin, bundle, as_copy=[published.template.id], idempotency_key="key-1"
        )


async def test_a_failed_import_commit_leaves_the_library_as_it_was(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """The next state is published only once the write returned."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    await _named_template(source, admin)
    bundle = await source.async_export_templates(admin)
    before = target.state

    with (
        patch.object(
            target._store, "async_save", AsyncMock(side_effect=OSError("disk full"))
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await target.async_import_templates(admin, bundle)

    assert target.state is before


# ---------------------------------------------------------------------------
# Backing a library up, and putting it back
# ---------------------------------------------------------------------------


async def _worked_library(library: LabelTemplateLibrary, admin: Any, other: Any) -> Any:
    """A library with some of everything a backup has to carry."""
    kept = await _named_template(library, admin, name="Clone tags")
    await _revise(library, admin, kept.template.id, y_mm=4.0)
    await library.async_set_default(admin, SIZE, TemplateRef.named(kept.template.id))
    await library.async_open_draft(admin, kept.template.id)
    await library.async_create_draft(other, label_size_id=SIZE)
    await library.async_autosave_draft(
        other, label_size_id=SIZE, document={"work": "in progress"}, name="Theirs"
    )
    gone = await _named_template(library, admin, name="Old tags")
    await library.async_delete_template(admin, gone.template.id)
    return kept


async def test_a_backup_carries_the_whole_library(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """History, drafts, defaults, tombstones, provenance and the generation."""
    kept = await _worked_library(library, admin, other_admin)

    document = await library.async_backup(admin)

    assert document["store_version"] == STORE_VERSION
    assert document["entry_id"] == library.entry_id
    assert document["library"] == library.state.as_dict()
    saved = document["library"]
    assert len(saved["templates"][kept.template.id]["revisions"]) == 2
    assert saved["templates"][kept.template.id]["revisions"][0]["provenance"]
    assert len(saved["drafts"]) == 2
    assert saved["defaults"][SIZE]["id"] == kept.template.id
    assert len(saved["tombstones"]) == 1
    assert saved["generation"] == library.state.generation


async def test_a_restore_replaces_the_library_exactly(
    libraries: Callable[..., LabelTemplateLibrary],
    admin: Any,
    other_admin: Any,
    changes: list[dict[str, Any]],
    hass: HomeAssistant,
) -> None:
    """Acceptance case 18: everything comes back, and the generation with it."""
    library = libraries()
    await library.async_load()
    await _worked_library(library, admin, other_admin)
    document = await library.async_backup(admin)
    expected = library.state
    await library.async_delete_template(admin, next(iter(library.state.templates)))
    await _named_template(library, admin, name="Something newer")
    changes.clear()

    restored = await library.async_restore_backup(admin, document)
    await hass.async_block_till_done()

    assert restored.generation == expected.generation
    assert restored.previous_generation > expected.generation
    assert restored.templates == len(expected.templates)
    assert restored.tombstones == len(expected.tombstones)
    assert library.state.templates == expected.templates
    assert library.state.drafts == expected.drafts
    assert library.state.defaults == expected.defaults
    assert library.state.tombstones == expected.tombstones
    assert [item["operation"] for item in changes] == [RESTORED_BACKUP]
    assert changes[0]["previous_generation"] > changes[0]["generation"]
    reopened = libraries()
    await reopened.async_load()
    assert reopened.state.templates == expected.templates


async def test_a_backup_restores_into_another_config_entry(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any, other_admin: Any
) -> None:
    """Which is what a backup taken before a reinstall is for."""
    source = libraries("entry-a")
    target = libraries("entry-b")
    await source.async_load()
    await target.async_load()
    kept = await _worked_library(source, admin, other_admin)

    await target.async_restore_backup(admin, await source.async_backup(admin))

    assert target.state.templates == source.state.templates
    assert target.state.defaults[SIZE] == TemplateRef.named(kept.template.id)


@pytest.mark.parametrize(
    ("damage", "refusal"),
    [
        pytest.param(
            lambda doc: {**doc, "checksum": "sha256:nope"},
            BackupNotRestorable,
            id="checksum",
        ),
        pytest.param(
            lambda doc: _resealed({**doc, "schema": "something.else"}),
            BackupNotRestorable,
            id="schema",
        ),
        pytest.param(
            lambda doc: _resealed({**doc, "version": 99}),
            BackupNotRestorable,
            id="newer_format",
        ),
        pytest.param(
            lambda doc: _resealed(
                {**doc, "library": {**doc["library"], "version": STORE_VERSION + 1}}
            ),
            IncompatibleTemplateStore,
            id="newer_store",
        ),
        pytest.param(
            lambda doc: _resealed(
                {
                    **doc,
                    "library": {
                        **doc["library"],
                        "templates": {
                            "somebody-elses-key": next(
                                iter(doc["library"]["templates"].values())
                            )
                        },
                    },
                }
            ),
            BackupNotRestorable,
            id="misfiled_template",
        ),
        pytest.param(
            lambda doc: _resealed({**doc, "library": "not a library"}),
            BackupNotRestorable,
            id="no_library",
        ),
    ],
)
async def test_a_backup_that_does_not_stage_changes_nothing(
    library: LabelTemplateLibrary,
    admin: Any,
    other_admin: Any,
    damage: Callable[[dict[str, Any]], dict[str, Any]],
    refusal: type[Exception],
) -> None:
    """Validation is complete before the one write, so a failure is a refusal.

    A backup whose *envelope* this version cannot read and one whose library
    was written by a newer store are different refusals, because they have
    different remedies: one document is not a backup this integration wrote,
    and the other is a perfectly good backup of something only a newer
    integration can hold.
    """
    await _worked_library(library, admin, other_admin)
    document = await library.async_backup(admin)
    before = library.state

    with pytest.raises(refusal):
        await library.async_restore_backup(admin, damage(document))

    assert library.state is before


async def test_a_failed_restore_write_leaves_the_library_as_it_was(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """The one operation whose success overwrites everything, failing safely."""
    await _worked_library(library, admin, other_admin)
    document = await library.async_backup(admin)
    await _named_template(library, admin, name="Something newer")
    before = library.state

    with (
        patch.object(
            library._store, "async_save", AsyncMock(side_effect=OSError("disk full"))
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await library.async_restore_backup(admin, document)

    assert library.state is before


async def test_a_replayed_restore_restores_once(
    library: LabelTemplateLibrary, admin: Any, other_admin: Any
) -> None:
    """Acceptance case 11, for a restore."""
    await _worked_library(library, admin, other_admin)
    document = await library.async_backup(admin)
    await _named_template(library, admin, name="Something newer")
    await library.async_restore_backup(admin, document, idempotency_key="key-1")
    after = library.state

    replay = await library.async_restore_backup(
        admin, document, idempotency_key="key-1"
    )

    assert replay.replayed is True
    assert library.state.as_dict() == after.as_dict()


async def test_a_backup_restores_a_quarantined_template_as_it_was(
    libraries: Callable[..., LabelTemplateLibrary], admin: Any
) -> None:
    """Structural validation, not layout validation: the damage travels too."""
    library = libraries()
    await library.async_load()
    published = await _named_template(library, admin)
    state = library.state
    template = state.templates[published.template.id]
    damaged = replace(template.head, document={"schema": "growspace.label-layout"})
    await library._store.async_save(
        replace(
            state,
            templates={
                **state.templates,
                template.id: replace(template, revisions=(damaged,)),
            },
        )
    )
    reopened = libraries()
    await reopened.async_load()

    document = await reopened.async_backup(admin)
    await reopened.async_restore_backup(admin, document)

    assert reopened.state.templates[published.template.id].head.document == {
        "schema": "growspace.label-layout"
    }
    snapshot = await reopened.async_snapshot(admin)
    assert snapshot["templates"][0]["quarantined"] is True
