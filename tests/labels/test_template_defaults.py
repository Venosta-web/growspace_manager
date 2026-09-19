"""Effective Defaults, and the Factory Templates behind them (hub issue #217).

One override per Label Size, and a shipped fallback under it. The property
worth stating plainly is that **losing an override never costs a stock its
printing**: a default naming something that has gone, or a revision the
catalogues have moved past, exposes the factory fallback rather than failing.

The other half is that Factory Templates are the integration's. An
administrator may start from one, copy one and select one -- and may not
rename, publish to or otherwise change one, because an upgrade that rewrote
somebody's label would be the exact failure a Named Template exists to
prevent.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    FACTORY_TEMPLATES,
    LABEL_SIZES,
    factory_template_for_size,
    validate_document,
)
from custom_components.growspace_manager.labels.library import (
    FACTORY_FALLBACK,
    OVERRIDE,
    LabelSizeImmutable,
    LabelTemplateError,
    LabelTemplateLibrary,
    LibraryState,
    NoEffectiveDefault,
    RevisionNotFound,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateRef,
    UnsupportedLabelSize,
    blank_document,
)

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


# ---------------------------------------------------------------------------
# The shipped set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template", list(FACTORY_TEMPLATES.values()), ids=lambda t: t.id
)
def test_every_shipped_factory_template_validates(template: Any) -> None:
    """The one document nothing else checks.

    A Factory Template is the fallback every other failure resolves to, so an
    invalid one would take the fallback down with whatever raised it.
    """
    validation = validate_document(dict(template.document))

    assert validation.diagnostics == ()
    assert validation.layout is not None
    assert validation.layout.label_size_id == template.label_size_id
    assert template.label_size_id in LABEL_SIZES


def test_each_stock_designates_at_most_one_factory_template() -> None:
    """A fallback is a designation, not a search that could return two."""
    for size in LABEL_SIZES:
        shipped = [
            template
            for template in FACTORY_TEMPLATES.values()
            if template.label_size_id == size
        ]
        assert len(shipped) <= 1
        assert factory_template_for_size(size) == (shipped[0] if shipped else None)


async def test_a_fresh_library_already_resolves_the_factory_fallback(
    library: LabelTemplateLibrary, viewer: Any
) -> None:
    """Nothing has to be configured before a label can be printed."""
    resolved = await library.async_resolve_default(viewer, SIZE)

    assert resolved.via == FACTORY_FALLBACK
    assert resolved.ref == TemplateRef.factory(FACTORY_50X30.id)
    assert resolved.revision == FACTORY_50X30.revision
    assert resolved.layout.digest == FACTORY_50X30.layout.digest


async def test_a_stock_with_no_shipped_template_says_so(
    library: LabelTemplateLibrary, viewer: Any
) -> None:
    """Never an invented emergency layout, and never a preview of another size."""
    with pytest.raises(NoEffectiveDefault):
        await library.async_resolve_default(viewer, UNSHIPPED_SIZE)


async def test_publishing_from_a_factory_derived_draft_leaves_the_factory_alone(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Deriving copies. The shipped definition is where it was."""
    before = FACTORY_50X30.layout.as_dict()
    await library.async_create_draft(
        admin, derive_from=TemplateRef.factory(FACTORY_50X30.id)
    )
    document = blank_document(SIZE)
    await library.async_autosave_draft(
        admin, label_size_id=SIZE, document=document, name="Mine now"
    )
    published = await library.async_publish_draft(admin, label_size_id=SIZE)

    assert FACTORY_50X30.layout.as_dict() == before
    assert published.template.id != FACTORY_50X30.id
    assert published.revision.document == document


# ---------------------------------------------------------------------------
# Selecting and clearing
# ---------------------------------------------------------------------------


async def test_selecting_a_named_template_overrides_the_fallback(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """The override wins, and resolution pins its head revision."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)

    changed = await library.async_set_default(admin, SIZE, ref)

    assert changed.unchanged is False
    assert changed.override == ref
    assert changed.effective is not None
    assert changed.effective.via == OVERRIDE
    resolved = await library.async_resolve_default(viewer, SIZE)
    assert resolved.ref == ref
    assert resolved.revision == 1


async def test_a_factory_template_may_be_selected_as_the_override(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Choosing the shipped one explicitly is choosing to follow its upgrades."""
    ref = TemplateRef.factory(FACTORY_50X30.id)

    await library.async_set_default(admin, SIZE, ref)

    resolved = await library.async_resolve_default(viewer, SIZE)
    assert resolved.ref == ref
    assert resolved.via == OVERRIDE


async def test_selecting_the_same_default_twice_writes_nothing(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """There is no change for another client to be told about."""
    published = await _named_template(library, admin)
    ref = TemplateRef.named(published.template.id)
    first = await library.async_set_default(admin, SIZE, ref)

    again = await library.async_set_default(admin, SIZE, ref)

    assert again.unchanged is True
    assert again.generation == first.generation


async def test_clearing_an_override_exposes_the_factory_fallback(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """The fallback is what a cleared default resolves to, in the same breath."""
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )

    cleared = await library.async_clear_default(admin, SIZE)

    assert cleared.override is None
    assert cleared.effective is not None
    assert cleared.effective.ref == TemplateRef.factory(FACTORY_50X30.id)
    assert (await library.async_resolve_default(viewer, SIZE)).via == FACTORY_FALLBACK


async def test_clearing_an_absent_override_writes_nothing(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Idempotent in the plainest sense: asking twice changes nothing twice."""
    before = library.state.generation

    cleared = await library.async_clear_default(admin, SIZE)

    assert cleared.unchanged is True
    assert cleared.generation == before


async def test_clearing_a_stock_with_no_shipped_template_still_succeeds(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """An administrator can always undo their own selection.

    What comes back says nothing resolves any more, which is a state this
    stock is in rather than a reason to refuse the command.
    """
    published = await _named_template(library, admin, label_size_id=UNSHIPPED_SIZE)
    await library.async_set_default(
        admin, UNSHIPPED_SIZE, TemplateRef.named(published.template.id)
    )

    cleared = await library.async_clear_default(admin, UNSHIPPED_SIZE)

    assert cleared.override is None
    assert cleared.effective is None
    assert UNSHIPPED_SIZE not in library.state.defaults


async def test_an_override_must_be_for_that_label_size(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A default is a promise about one stock, which another cannot keep."""
    published = await _named_template(library, admin)

    with pytest.raises(LabelSizeImmutable):
        await library.async_set_default(
            admin, UNSHIPPED_SIZE, TemplateRef.named(published.template.id)
        )


async def test_an_override_naming_nothing_is_refused_rather_than_stored(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """A default pointing at nothing would be a fallback that fails later."""
    with pytest.raises(TemplateNotFound):
        await library.async_set_default(
            admin, SIZE, TemplateRef.named("11111111-2222-3333-4444-555555555555")
        )
    assert library.state.defaults == {}


async def test_one_override_per_label_size(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """Selecting a second template replaces the first rather than joining it."""
    first = await _named_template(library, admin, name="First")
    second = await _named_template(library, admin, name="Second")

    await library.async_set_default(admin, SIZE, TemplateRef.named(first.template.id))
    await library.async_set_default(admin, SIZE, TemplateRef.named(second.template.id))

    assert library.state.defaults == {SIZE: TemplateRef.named(second.template.id)}


# ---------------------------------------------------------------------------
# An override that stops resolving
# ---------------------------------------------------------------------------


async def test_an_override_naming_a_vanished_template_falls_back(
    libraries: Any, library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Resolution steps past it. It does not rewrite the stored override.

    Removing a template is the recovery route's operation; what is exercised
    here is only what resolution does when it meets one that is gone.
    """
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    await library._store.async_save(replace(library.state, templates={}))

    reopened = libraries()
    await reopened.async_load()

    resolved = await reopened.async_resolve_default(viewer, SIZE)
    assert resolved.via == FACTORY_FALLBACK
    assert reopened.state.defaults[SIZE] == TemplateRef.named(published.template.id)


async def test_an_override_whose_revision_stopped_validating_falls_back(
    libraries: Any, library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """A catalogue that moved on beneath a revision does not stop the stock.

    The revision is left exactly as published -- preserving it for repair,
    export or historical restore is the recovery route's; here it simply is
    not what the stock resolves to.
    """
    published = await _named_template(library, admin)
    await library.async_set_default(
        admin, SIZE, TemplateRef.named(published.template.id)
    )
    stale = replace(
        published.template,
        revisions=(replace(published.revision, document={"gone": "stale"}),),
    )
    await library._store.async_save(replace(library.state, templates={stale.id: stale}))

    reopened = libraries()
    await reopened.async_load()

    resolved = await reopened.async_resolve_default(viewer, SIZE)
    assert resolved.via == FACTORY_FALLBACK
    assert reopened.state.templates[stale.id].head.document == {"gone": "stale"}


async def test_a_default_for_a_stock_nothing_ships_reports_nothing(
    library: LabelTemplateLibrary, admin: Any
) -> None:
    """The snapshot says which stocks can be printed and which cannot."""
    snapshot = await library.async_snapshot(admin)

    assert snapshot["effective_defaults"][SIZE]["via"] == FACTORY_FALLBACK
    assert snapshot["effective_defaults"][UNSHIPPED_SIZE] is None
    assert [item["id"] for item in snapshot["factory_templates"]] == list(
        FACTORY_TEMPLATES
    )
    assert all(item["valid"] for item in snapshot["factory_templates"])


def test_an_empty_library_is_the_shape_a_fresh_install_starts_at() -> None:
    """Nothing is written before somebody does something."""
    state = LibraryState()

    assert state.generation == 0
    assert state.templates == {}
    assert state.drafts == {}
    assert state.defaults == {}


# ---------------------------------------------------------------------------
# References nothing answers
# ---------------------------------------------------------------------------


async def test_an_unknown_stock_is_refused_by_name(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """A size is a catalogue identity, never a string a client invents."""
    for call in (
        library.async_resolve_default(viewer, "growspace.stock.99x99.v1"),
        library.async_clear_default(admin, "growspace.stock.99x99.v1"),
    ):
        with pytest.raises(UnsupportedLabelSize):
            await call


async def test_a_reference_of_an_unknown_kind_is_refused(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Only the two kinds of template exist, and neither is inferred."""
    invented = TemplateRef(kind="borrowed", id=FACTORY_50X30.id)

    with pytest.raises(TemplateNotFound):
        await library.async_resolve(viewer, invented)
    with pytest.raises(LabelTemplateError, match="not a kind of template"):
        await library.async_set_default(admin, SIZE, invented)


async def test_an_override_of_an_unknown_kind_falls_back_rather_than_raising(
    libraries: Any, library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Resolution reads a stored override it cannot interpret and steps past it."""
    await library._store.async_save(
        replace(
            library.state, defaults={SIZE: TemplateRef(kind="borrowed", id="whatever")}
        )
    )
    reopened = libraries()
    await reopened.async_load()

    assert (await reopened.async_resolve_default(viewer, SIZE)).via == FACTORY_FALLBACK


async def test_a_factory_identity_nothing_ships_is_not_found(
    library: LabelTemplateLibrary, viewer: Any
) -> None:
    """A namespaced ID is still an identity that has to exist."""
    with pytest.raises(TemplateNotFound):
        await library.async_resolve(viewer, TemplateRef.factory("growspace.factory.x"))


async def test_a_revision_a_template_never_had_is_not_found(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Distinct from one that exists and stopped validating."""
    published = await _named_template(library, admin)

    with pytest.raises(RevisionNotFound):
        await library.async_resolve(
            viewer, TemplateRef.named(published.template.id), revision=7
        )
    with pytest.raises(RevisionNotFound):
        await library.async_resolve(
            viewer,
            TemplateRef.factory(FACTORY_50X30.id),
            revision=FACTORY_50X30.revision + 1,
        )


async def test_a_historical_revision_resolves_at_the_number_asked_for(
    library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """History stays readable; the head is only the default answer."""
    first = await _named_template(library, admin)
    await library.async_open_draft(admin, first.template.id)
    moved = blank_document(SIZE)
    moved["elements"][0]["frame"]["x_mm"] = 3.0
    await library.async_autosave_draft(
        admin, template_id=first.template.id, document=moved
    )
    await library.async_publish_draft(admin, template_id=first.template.id)

    head = await library.async_resolve(viewer, TemplateRef.named(first.template.id))
    original = await library.async_resolve(
        viewer, TemplateRef.named(first.template.id), revision=1
    )

    assert head.revision == 2
    assert original.revision == 1
    assert original.layout.digest == first.revision.digest


# ---------------------------------------------------------------------------
# A shipped template that stopped being valid
# ---------------------------------------------------------------------------


def _broken_factory() -> Any:
    """A shipped template whose document no longer validates."""
    return replace(FACTORY_50X30, document={"schema": "growspace.label-layout"})


async def test_an_invalid_shipped_template_disables_only_its_stock(
    library: LabelTemplateLibrary, viewer: Any, admin: Any
) -> None:
    """A packaging failure is reported, never worked around.

    The integration does not invent an approximate emergency layout and does
    not quietly print a known-invalid one: the stock says it has no Effective
    Default, and every other stock is untouched.
    """
    broken = _broken_factory()
    with (
        patch.dict(
            "custom_components.growspace_manager.labels.library.library.FACTORY_TEMPLATES",
            {broken.id: broken},
            clear=True,
        ),
        patch(
            "custom_components.growspace_manager.labels.library.library.factory_template_for_size",
            lambda size: broken if size == broken.label_size_id else None,
        ),
    ):
        with pytest.raises(NoEffectiveDefault):
            await library.async_resolve_default(viewer, SIZE)
        with pytest.raises(TemplateNotResolvable):
            await library.async_resolve(viewer, TemplateRef.factory(broken.id))
        with pytest.raises(TemplateNotResolvable):
            await library.async_set_default(admin, SIZE, TemplateRef.factory(broken.id))
        snapshot = await library.async_snapshot(admin)

    assert snapshot["factory_templates"] == [
        {
            "kind": "factory",
            "id": broken.id,
            "revision": broken.revision,
            "name": broken.name,
            "label_size_id": broken.label_size_id,
            "valid": False,
        }
    ]
    assert snapshot["effective_defaults"][SIZE] is None
    # And with the shipped set back, the same stock resolves again.
    assert (await library.async_resolve_default(viewer, SIZE)).via == FACTORY_FALLBACK


async def test_an_override_naming_an_invalid_shipped_template_falls_back(
    libraries: Any, library: LabelTemplateLibrary, admin: Any, viewer: Any
) -> None:
    """Even the override cannot make an invalid layout the one that prints."""
    await library.async_set_default(admin, SIZE, TemplateRef.factory(FACTORY_50X30.id))
    reopened = libraries()
    await reopened.async_load()
    broken = _broken_factory()

    with patch.dict(
        "custom_components.growspace_manager.labels.library.library.FACTORY_TEMPLATES",
        {broken.id: broken},
    ):
        with pytest.raises(NoEffectiveDefault):
            await reopened.async_resolve_default(viewer, SIZE)

    assert reopened.state.defaults[SIZE] == TemplateRef.factory(FACTORY_50X30.id)
