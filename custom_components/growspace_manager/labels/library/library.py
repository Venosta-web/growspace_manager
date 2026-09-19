"""The template library: one config entry's templates, drafts and defaults.

Everything a label print resolves through, and the operations that change it.
The shape of it is three ideas held apart:

    Factory Template   shipped, protected, follows the installed version
    Named Template     an administrator's, an opaque UUID, immutable history
    Template Draft     unpublished, durable, private to one administrator

An administrator starts a draft -- blank, or derived from a factory or named
template -- edits it through autosaves that keep whatever state it is in, and
publishes it. Publication validates the layout, appends one immutable revision
and clears the draft **in one commit**, so the two can never disagree. A
default override then selects a template per Label Size, and what resolves for
that size is the override where there is one and the designated Factory
Template where there is not.

Three rules run through all of it.

**Authorization is per request.** Every operation takes an `Actor` and asks it
again. An editor opened by an administrator who is then demoted keeps its
draft and refuses its next save; nothing here holds a capability from earlier.

**Nothing is repaired.** A draft that does not validate is kept and refused,
not corrected. A revision that has stopped validating is stepped past, not
rewritten. A default naming something that no longer resolves falls back to the
factory rather than being quietly re-pointed.

**A mutation is one commit.** The next state is composed in memory and written
once, under a lock, and the in-memory state is only replaced after the write
returns. A failed write therefore leaves the library exactly as it was.

**Nobody's work is lost to somebody else's.** More than one client edits this
library at once, so the last three rules have a fourth behind them. An autosave
is compare-and-swap on the draft version and a publication compares the draft's
base with the current head, so neither can overwrite something it has not seen.
A refused write keeps its payload in the draft's recovery slot rather than
dropping it. Every mutation may carry an idempotency key, so the retry of a
call whose answer was lost finds the first attempt. And every committed
mutation fires one change event naming the new generation and the one it
replaced, which is what lets a client detect the events it missed and refresh
its snapshot -- without its own open draft being touched by anybody.

What deliberately does *not* happen is a merge. Two layouts that diverged are
structurally mergeable and physically unsafe to merge: independent moves,
resizes and typography changes compose into overlap, clipping and unreadable
text that neither editor asked for. A stale draft is therefore kept whole and
previewable, and its owner chooses.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any
import uuid

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ...const import DOMAIN
from ..canonical import (
    FACTORY_TEMPLATES,
    LABEL_SIZES,
    PREVIEW,
    TYPICAL_STRAIN,
    CapabilityProfile,
    FactoryTemplate,
    FontLibrary,
    LabelLayout,
    RenderResult,
    RepresentativeSubject,
    async_render,
    factory_template_for_size,
    profiles_for_size,
)
from .actor import Actor
from .blank import blank_document
from .commits import (
    AUTOSAVE_DRAFT,
    CLEAR_DEFAULT,
    CREATE_DRAFT,
    DISCARD_DRAFT,
    DISCARD_RECOVERY,
    PUBLISH_DRAFT,
    RELOAD_DRAFT,
    SET_DEFAULT,
    committed,
    record_of,
    request_digest,
)
from .errors import (
    DraftIsStale,
    DraftNotFound,
    DraftNotPublishable,
    DraftVersionConflict,
    DuplicateTemplateName,
    LabelSizeImmutable,
    LabelTemplateError,
    NoEffectiveDefault,
    NoRecoveryPayload,
    RevisionNotFound,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateProtected,
    UnsupportedLabelSize,
)
from .events import DEFAULT_CLEARED, DEFAULT_SET, PUBLISHED, async_fire_library_changed
from .publication import PublicationCheck, check_document
from .records import (
    FACTORY,
    FROM_BLANK,
    FROM_FACTORY,
    FROM_NAMED,
    NAMED,
    PUBLISH,
    REJECTED_SAVE,
    RELOADED,
    CommitRecord,
    LibraryState,
    NamedTemplate,
    Provenance,
    RecoveryPayload,
    TemplateDraft,
    TemplateRef,
    TemplateRevision,
    display_name,
    draft_key,
)
from .store import LabelTemplateStore

#: Where the per-entry libraries are kept once opened.
_LIBRARIES = "label_template_libraries"

#: How one resolution arrived at the revision it returned.
EXPLICIT = "explicit"
OVERRIDE = "override"
FACTORY_FALLBACK = "factory_fallback"

#: Distinguishes "leave the name alone" from "set the name to nothing" on an
#: autosave, which `None` cannot do.
_UNSET = object()


@dataclass(frozen=True, slots=True)
class ResolvedTemplate:
    """One concrete revision, pinned for the whole of one operation.

    Default resolution produces one of these at the *start* of a render or
    print: later saves and default changes cannot reach back into an operation
    that already has its revision.
    """

    ref: TemplateRef
    revision: int
    name: str
    label_size_id: str
    layout: LabelLayout
    via: str

    @property
    def document(self) -> dict[str, Any]:
        """The normalized layout document this revision resolved to."""
        return self.layout.as_dict()

    def as_dict(self) -> dict[str, Any]:
        """Return the resolution's wire form."""
        return {
            "ref": self.ref.as_dict(),
            "revision": self.revision,
            "name": self.name,
            "label_size_id": self.label_size_id,
            "via": self.via,
            "layout_digest": self.layout.digest,
            "document": self.document,
        }


@dataclass(frozen=True, slots=True)
class DraftSaved:
    """One autosave's outcome: the stored draft, and what is wrong with it.

    The check travels with the draft because an editor needs both at once, and
    because being told the work was kept and being told it cannot yet be
    published are two different sentences. Staleness is a third: a draft can be
    perfectly valid and still unpublishable because somebody else published
    first, and that is not a diagnostic about the layout.
    """

    draft: TemplateDraft
    check: PublicationCheck
    #: Whether the template has moved past the revision this draft is based on.
    stale: bool = False
    #: The template's current head, so the editor can name what it would be
    #: publishing over. `None` for an untitled draft, which has no template.
    head_revision: int | None = None
    #: True when this call found its own earlier autosave rather than writing.
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the autosave's wire form."""
        return {
            "draft": self.draft.as_dict(),
            "validation": self.check.as_dict(),
            "stale": self.stale,
            "head_revision": self.head_revision,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class DraftDiscarded:
    """One removed draft, named by what it was.

    The removed draft travels back whole, because an editor that has just
    thrown work away is the one place an undo could still be offered. A replay
    carries no draft: the key's first attempt is what removed it, this call
    removed nothing, and inventing a payload to return would be a lie about
    which of the two happened.
    """

    draft_id: str
    owner: str
    label_size_id: str
    template_id: str | None
    version: int
    draft: TemplateDraft | None = None
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the discard's wire form."""
        return {
            "draft_id": self.draft_id,
            "owner": self.owner,
            "label_size_id": self.label_size_id,
            "template_id": self.template_id,
            "version": self.version,
            "draft": self.draft.as_dict() if self.draft else None,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class Publication:
    """One committed publication."""

    template: NamedTemplate
    revision: TemplateRevision
    generation: int
    #: True when this call found the revision its own draft had already
    #: become, rather than creating one. A retry after a lost response.
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the publication's wire form."""
        return {
            "template": self.template.summary(),
            "revision": self.revision.summary(),
            "generation": self.generation,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class DefaultChanged:
    """One committed change to a Label Size's default override."""

    label_size_id: str
    override: TemplateRef | None
    #: What now resolves for this stock. `None` means nothing does -- the
    #: override was the only thing selectable and the integration ships no
    #: valid Factory Template for this size, so template-based printing for it
    #: is unavailable. That is reported rather than refused: leaving an
    #: administrator unable to clear a default would be the worse failure.
    effective: ResolvedTemplate | None
    generation: int
    #: True when the override already had this value, so nothing was written.
    unchanged: bool = False
    #: True when this call found its own earlier change rather than making one.
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the change's wire form.

        What now resolves is summarized rather than resolved: a client that
        just chose a default is choosing, not rendering, and the layout comes
        back when something asks to resolve one.
        """
        return {
            "label_size_id": self.label_size_id,
            "override": self.override.as_dict() if self.override else None,
            "effective": _effective_summary(self.effective),
            "generation": self.generation,
            "unchanged": self.unchanged,
            "replayed": self.replayed,
        }


class LabelTemplateLibrary:
    """One config entry's authoritative Label Template library."""

    def __init__(
        self, hass: HomeAssistant, entry_id: str, store: Any | None = None
    ) -> None:
        """Bind a library to one config entry, without reading anything yet."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = store if store is not None else LabelTemplateStore(hass, entry_id)
        self._state: LibraryState | None = None
        self._lock = asyncio.Lock()

    # -- loading -----------------------------------------------------------

    async def async_load(self) -> LibraryState:
        """Read the committed library, once."""
        if self._state is None:
            self._state = await self._store.async_load()
        return self._state

    @property
    def state(self) -> LibraryState:
        """The committed library, which must already have been loaded."""
        if self._state is None:
            raise LabelTemplateError(
                "This Label Template library has not been loaded yet."
            )
        return self._state

    async def _async_commit(
        self, state: LibraryState, record: CommitRecord | None = None
    ) -> LibraryState:
        """Write one complete next state, and publish it only once it landed.

        The idempotency record goes into the same write as what it describes.
        A ledger written separately could survive a mutation that did not, and
        a replay would then report a commit that never happened.
        """
        next_state = (
            state
            if record is None
            else replace(state, commits=state.with_commit(record))
        )
        await self._store.async_save(next_state)
        self._state = next_state
        return next_state

    # -- reading -----------------------------------------------------------

    async def async_snapshot(self, actor: Actor) -> dict[str, Any]:
        """Return what this actor may see of the library, whole.

        Any authenticated user gets the factory catalogue, the Named Templates
        and what resolves per Label Size, because that is what choosing and
        printing a label needs. Drafts are unpublished and private, so only an
        administrator's own appear -- and a non-administrator's list is empty
        rather than absent, which is the same answer as having none.

        This is also the refresh a client falls back to after a missed change
        event, so it is complete rather than incremental -- and it *reads*:
        taking a snapshot never rebases, merges or clears anybody's draft, so
        recovering from a gap cannot cost an editor its unsaved work.
        """
        user_id = actor.authenticated()
        state = await self.async_load()
        drafts = (
            [
                _draft_wire(state, draft)
                for draft in state.drafts.values()
                if draft.owner == user_id
            ]
            if actor.is_admin
            else []
        )
        return {
            "entry_id": self.entry_id,
            "generation": state.generation,
            "factory_templates": [
                _factory_summary(template) for template in FACTORY_TEMPLATES.values()
            ],
            "templates": [
                template.summary()
                for template in sorted(
                    state.templates.values(), key=lambda item: item.name.casefold()
                )
            ],
            "defaults": {
                size: ref.as_dict() for size, ref in sorted(state.defaults.items())
            },
            "effective_defaults": {
                size: _effective_summary(self._effective_default(state, size))
                for size in LABEL_SIZES
            },
            "drafts": drafts,
        }

    async def async_resolve_default(
        self, actor: Actor, label_size_id: str
    ) -> ResolvedTemplate:
        """Resolve the Effective Default for one Label Size, to one revision.

        The administrator's override where there is a usable one, and the
        designated Factory Template where there is not. An override naming
        something that has been removed, or a revision that has stopped
        validating, exposes the factory fallback rather than failing: losing an
        override must not take the size's printing with it.
        """
        actor.authenticated()
        _require_known_size(label_size_id)
        state = await self.async_load()
        resolved = self._effective_default(state, label_size_id)
        if resolved is None:
            raise NoEffectiveDefault(label_size_id)
        return resolved

    async def async_resolve(
        self, actor: Actor, ref: TemplateRef, revision: int | None = None
    ) -> ResolvedTemplate:
        """Resolve one named template and revision, for any authenticated user."""
        actor.authenticated()
        state = await self.async_load()
        if ref.kind == FACTORY:
            return _resolve_factory(ref.id, revision, via=EXPLICIT)
        template = state.templates.get(ref.id)
        if template is None:
            raise TemplateNotFound(ref.id)
        return _resolve_named(template, revision, via=EXPLICIT)

    # -- drafts ------------------------------------------------------------

    async def async_create_draft(
        self,
        actor: Actor,
        *,
        label_size_id: str | None = None,
        derive_from: TemplateRef | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateDraft:
        """Start an untitled draft: blank, or derived from a published template.

        Derived means *copied*: the new draft carries the source's current
        revision as content and its identity as provenance, and publishing it
        creates a template of its own. Nothing about the source changes, which
        is what keeps a Factory Template protected while still being the most
        useful place to start.
        """
        owner = actor.administrator()
        digest = request_digest(
            CREATE_DRAFT,
            owner,
            label_size_id=label_size_id,
            derive_from=derive_from.as_dict() if derive_from else None,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=CREATE_DRAFT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_draft(state, record)
            if derive_from is None:
                if label_size_id is None:
                    raise LabelTemplateError(
                        "A blank draft needs the Label Size it is for."
                    )
                _require_known_size(label_size_id)
                document: Any = blank_document(label_size_id)
                provenance = Provenance(source=FROM_BLANK)
                size = label_size_id
            else:
                source = (
                    _resolve_factory(derive_from.id, None, via=EXPLICIT)
                    if derive_from.kind == FACTORY
                    else _resolve_named(
                        _require_template(state, derive_from.id), None, via=EXPLICIT
                    )
                )
                if label_size_id is not None and label_size_id != source.label_size_id:
                    raise LabelSizeImmutable(
                        template_id=derive_from.id,
                        expected=source.label_size_id,
                        found=label_size_id,
                    )
                document = source.document
                size = source.label_size_id
                provenance = (
                    Provenance(
                        source=FROM_FACTORY,
                        factory_id=source.ref.id,
                        factory_revision=source.revision,
                    )
                    if derive_from.kind == FACTORY
                    else Provenance(
                        source=FROM_NAMED,
                        source_template_id=source.ref.id,
                        source_revision=source.revision,
                    )
                )

            now = dt_util.utcnow().isoformat()
            draft = TemplateDraft(
                id=ulid_now(),
                owner=owner,
                label_size_id=size,
                version=1,
                document=document,
                created_at=now,
                modified_at=now,
                provenance=provenance,
            )
            await self._async_commit(
                _with_draft(state, draft),
                record_of(
                    key=idempotency_key,
                    operation=CREATE_DRAFT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={"draft_key": draft.key, "draft_id": draft.id},
                ),
            )
            return draft

    async def async_open_draft(self, actor: Actor, template_id: str) -> TemplateDraft:
        """Return this administrator's draft of one template, starting one if needed.

        Opening an editor is not a lock and not a claim: the draft is private,
        the template is untouched, and another administrator opening the same
        template gets their own draft of the same base revision.
        """
        owner = actor.administrator()
        async with self._lock:
            state = await self.async_load()
            template = _require_template(state, template_id)
            existing = state.drafts.get(
                draft_key(
                    owner,
                    template_id=template_id,
                    label_size_id=template.label_size_id,
                )
            )
            if existing is not None:
                return existing

            head = template.head
            now = dt_util.utcnow().isoformat()
            draft = TemplateDraft(
                id=ulid_now(),
                owner=owner,
                label_size_id=template.label_size_id,
                template_id=template.id,
                base_revision=head.revision,
                version=1,
                document=dict(head.document),
                created_at=now,
                modified_at=now,
                provenance=Provenance(
                    source=FROM_NAMED,
                    source_template_id=template.id,
                    source_revision=head.revision,
                ),
            )
            await self._async_commit(_with_draft(state, draft))
            return draft

    async def async_autosave_draft(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        document: Any,
        name: Any = _UNSET,
        expected_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> DraftSaved:
        """Keep whatever the editor last had, valid or not.

        This never refuses on content. An autosave that dropped invalid work
        would make every diagnostic a threat to the draft, and half of editing
        is passing through states that do not yet validate. What comes back
        beside the stored draft is the publication check, so the editor can say
        why the Publish control is unavailable without guessing.

        It does refuse on *version*. Passing `expected_version` makes the save
        a compare-and-swap: one administrator with the editor open in two
        places cannot have the older tab silently write over the newer one's
        work. The refused payload is not discarded -- it goes into the draft's
        recovery slot and comes back on the error -- and the stored draft is
        left exactly as it was. Omitting the version is a save that has not
        read anything, and is taken at its word.
        """
        owner = actor.administrator()
        named = name is not _UNSET
        digest = request_digest(
            AUTOSAVE_DRAFT,
            owner,
            template_id=template_id,
            label_size_id=label_size_id,
            document=document,
            name_set=named,
            name=name if named else None,
            expected_version=expected_version,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=AUTOSAVE_DRAFT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                saved = _replayed_draft(state, record)
                return DraftSaved(
                    draft=saved,
                    check=check_document(saved.document),
                    stale=_is_stale(state, saved),
                    head_revision=_head_revision(state, saved),
                    replayed=True,
                )
            draft = self._locate_draft(
                state, owner, template_id=template_id, label_size_id=label_size_id
            )
            now = dt_util.utcnow().isoformat()
            resolved_name = (
                None if not named or name is None else display_name(str(name))
            )
            if named and draft.template_id is not None:
                raise LabelTemplateError(
                    "A template-bound draft carries no name: renaming a "
                    "Label Template is its own operation."
                )
            if expected_version is not None and expected_version != draft.version:
                kept = replace(
                    draft,
                    recovery=RecoveryPayload(
                        reason=REJECTED_SAVE,
                        document=document,
                        expected_version=expected_version,
                        draft_version=draft.version,
                        at=now,
                        name=resolved_name,
                    ),
                )
                await self._async_commit(_with_draft(state, kept))
                raise DraftVersionConflict(
                    expected=expected_version, found=draft.version, draft=kept
                )

            fields: dict[str, Any] = {
                "document": document,
                "version": draft.version + 1,
                "modified_at": now,
            }
            if named:
                fields["name"] = resolved_name
            saved = replace(draft, **fields)
            await self._async_commit(
                _with_draft(state, saved),
                record_of(
                    key=idempotency_key,
                    operation=AUTOSAVE_DRAFT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={"draft_key": saved.key, "draft_id": saved.id},
                ),
            )
            return DraftSaved(
                draft=saved,
                check=check_document(saved.document),
                stale=_is_stale(state, saved),
                head_revision=_head_revision(state, saved),
            )

    async def async_discard_draft(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> DraftDiscarded:
        """Remove unpublished work explicitly, and return what was removed.

        Explicit because the alternatives are not the same thing: discarding a
        draft, restoring a historical revision and replacing a layout from the
        factory have different consequences, and one generic "reset" would hide
        which of them happened.
        """
        owner = actor.administrator()
        digest = request_digest(
            DISCARD_DRAFT,
            owner,
            template_id=template_id,
            label_size_id=label_size_id,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=DISCARD_DRAFT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return DraftDiscarded(
                    draft_id=str(record.locator["draft_id"]),
                    owner=owner,
                    label_size_id=str(record.locator["label_size_id"]),
                    template_id=_optional(record.locator.get("template_id")),
                    version=int(record.locator["version"]),
                    replayed=True,
                )
            draft = self._locate_draft(
                state, owner, template_id=template_id, label_size_id=label_size_id
            )
            remaining = {
                key: value for key, value in state.drafts.items() if key != draft.key
            }
            await self._async_commit(
                replace(state, drafts=remaining),
                record_of(
                    key=idempotency_key,
                    operation=DISCARD_DRAFT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={
                        "draft_id": draft.id,
                        "label_size_id": draft.label_size_id,
                        "template_id": draft.template_id,
                        "version": draft.version,
                    },
                ),
            )
            return DraftDiscarded(
                draft_id=draft.id,
                owner=draft.owner,
                label_size_id=draft.label_size_id,
                template_id=draft.template_id,
                version=draft.version,
                draft=draft,
            )

    async def async_reload_draft(
        self,
        actor: Actor,
        template_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> TemplateDraft:
        """Replace a draft with a fresh one at the template's current head.

        What an owner of a stale draft does when the newer revision is the one
        they want: the draft is discarded and started again from the head, in
        one commit, so there is no window in which the editor has no draft.

        Nothing is merged. The payload that was there moves into the new
        draft's recovery slot, so reapplying the parts worth keeping is a thing
        the editor can do by hand -- which is the only safe way to do it, since
        two independently moved layouts compose into overlap and clipping
        neither editor asked for.
        """
        owner = actor.administrator()
        digest = request_digest(RELOAD_DRAFT, owner, template_id=template_id)
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=RELOAD_DRAFT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_draft(state, record)
            template = _require_template(state, template_id)
            previous = self._locate_draft(
                state, owner, template_id=template_id, label_size_id=None
            )
            head = template.head
            now = dt_util.utcnow().isoformat()
            reloaded = TemplateDraft(
                id=ulid_now(),
                owner=owner,
                label_size_id=template.label_size_id,
                template_id=template.id,
                base_revision=head.revision,
                version=1,
                document=dict(head.document),
                created_at=now,
                modified_at=now,
                provenance=Provenance(
                    source=FROM_NAMED,
                    source_template_id=template.id,
                    source_revision=head.revision,
                ),
                recovery=RecoveryPayload(
                    reason=RELOADED,
                    document=previous.document,
                    expected_version=None,
                    draft_version=previous.version,
                    at=now,
                    name=previous.name,
                ),
            )
            await self._async_commit(
                _with_draft(state, reloaded),
                record_of(
                    key=idempotency_key,
                    operation=RELOAD_DRAFT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={"draft_key": reloaded.key, "draft_id": reloaded.id},
                ),
            )
            return reloaded

    async def async_discard_recovery(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateDraft:
        """Drop the work kept beside a draft, once its owner is done with it.

        The only thing that clears the slot short of the draft itself going.
        An ordinary autosave deliberately leaves it alone: a client saving
        newer work has not necessarily looked at what was kept, and quietly
        dropping it on the next keystroke would make the promise worthless.
        """
        owner = actor.administrator()
        digest = request_digest(
            DISCARD_RECOVERY,
            owner,
            template_id=template_id,
            label_size_id=label_size_id,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=DISCARD_RECOVERY,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_draft(state, record)
            draft = self._locate_draft(
                state, owner, template_id=template_id, label_size_id=label_size_id
            )
            if draft.recovery is None:
                raise NoRecoveryPayload(
                    f"template {template_id!r}"
                    if template_id
                    else f"Label Size {label_size_id!r}"
                )
            cleared = replace(draft, recovery=None)
            await self._async_commit(
                _with_draft(state, cleared),
                record_of(
                    key=idempotency_key,
                    operation=DISCARD_RECOVERY,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={"draft_key": cleared.key, "draft_id": cleared.id},
                ),
            )
            return cleared

    async def async_publish_draft(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        draft_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Publication:
        """Turn one draft into an immutable revision, and clear it, in one commit.

        An untitled draft becomes a new Named Template at revision 1; a
        template-bound one becomes its next revision. Either way the revision
        append, the draft removal and the generation advance are one write, so
        a crash between them is not a state this store can be in.

        A draft whose base revision is no longer the head is refused. Somebody
        published while this one was open, and appending over them would drop
        their revision from a template whose history claims to be complete. The
        draft is left untouched and remains previewable; reloading it or
        publishing it as a template of its own are both its owner's to choose.

        Passing the `draft_id` makes a retry safe without a key: if the draft
        is gone because the first attempt actually succeeded and only its
        answer was lost, the revision that draft became is found and returned
        unchanged rather than published a second time.
        """
        owner = actor.administrator()
        digest = request_digest(
            PUBLISH_DRAFT,
            owner,
            template_id=template_id,
            label_size_id=label_size_id,
            draft_id=draft_id,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=PUBLISH_DRAFT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_revision(state, record)
            draft = self._find_draft(
                state, owner, template_id=template_id, label_size_id=label_size_id
            )
            if draft is None:
                replay = _replayed_publication(state, draft_id, owner)
                if replay is not None:
                    return replay
                raise DraftNotFound(
                    f"template {template_id!r}"
                    if template_id
                    else f"Label Size {label_size_id!r}"
                )
            if draft_id is not None and draft_id != draft.id:
                raise DraftNotFound(f"draft {draft_id!r}")
            if _is_stale(state, draft):
                raise DraftIsStale(
                    template_id=str(draft.template_id),
                    base_revision=int(draft.base_revision or 0),
                    head=int(_head_revision(state, draft) or 0),
                )

            check = check_document(draft.document)
            if check.layout is None or not check.publishable:
                raise DraftNotPublishable(check.diagnostics)
            layout = check.layout

            now = dt_util.utcnow().isoformat()
            provenance = replace(
                draft.provenance, draft_id=draft.id, draft_version=draft.version
            )
            if draft.template_id is None:
                template, revision = _publish_new_template(
                    state, draft, layout, owner=owner, now=now, provenance=provenance
                )
            else:
                template, revision = _publish_next_revision(
                    state, draft, layout, owner=owner, now=now, provenance=provenance
                )

            templates = {**state.templates, template.id: template}
            drafts = {
                key: value for key, value in state.drafts.items() if key != draft.key
            }
            landed = await self._async_commit(
                replace(
                    state,
                    templates=templates,
                    drafts=drafts,
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=PUBLISH_DRAFT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={
                        "template_id": template.id,
                        "revision": revision.revision,
                    },
                ),
            )
            self._announce(
                landed,
                previous=state.generation,
                operation=PUBLISHED,
                template_id=template.id,
                revision=revision.revision,
                label_size_id=template.label_size_id,
            )
            return Publication(
                template=template, revision=revision, generation=landed.generation
            )

    # -- defaults ----------------------------------------------------------

    async def async_set_default(
        self,
        actor: Actor,
        label_size_id: str,
        ref: TemplateRef,
        *,
        idempotency_key: str | None = None,
    ) -> DefaultChanged:
        """Select one template as the override for one Label Size.

        The reference names an identity, never a display name, and it must
        belong to this Label Size: a default is a promise about one stock, and
        a template for another cannot keep it. Selecting what is already
        selected writes nothing and does not advance the generation -- there is
        no change for a client to be told about.
        """
        owner = actor.administrator()
        _require_known_size(label_size_id)
        digest = request_digest(
            SET_DEFAULT, owner, label_size_id=label_size_id, ref=ref.as_dict()
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=SET_DEFAULT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return self._replayed_default(state, label_size_id)
            resolved = self._validate_override(state, label_size_id, ref)
            if state.defaults.get(label_size_id) == ref:
                return DefaultChanged(
                    label_size_id=label_size_id,
                    override=ref,
                    effective=resolved,
                    generation=state.generation,
                    unchanged=True,
                )
            landed = await self._async_commit(
                replace(
                    state,
                    defaults={**state.defaults, label_size_id: ref},
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=SET_DEFAULT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={"label_size_id": label_size_id},
                ),
            )
            self._announce(
                landed,
                previous=state.generation,
                operation=DEFAULT_SET,
                template_id=ref.id if ref.kind == NAMED else None,
                label_size_id=label_size_id,
            )
            return DefaultChanged(
                label_size_id=label_size_id,
                override=ref,
                effective=resolved,
                generation=landed.generation,
            )

    async def async_clear_default(
        self, actor: Actor, label_size_id: str, *, idempotency_key: str | None = None
    ) -> DefaultChanged:
        """Remove one Label Size's override, exposing the factory fallback.

        Clearing an override that is not there writes nothing. Clearing one
        where no valid Factory Template is shipped still succeeds and reports
        that nothing now resolves: an administrator who could not undo their
        own selection would be worse off than a stock that says it cannot
        print.
        """
        owner = actor.administrator()
        _require_known_size(label_size_id)
        digest = request_digest(CLEAR_DEFAULT, owner, label_size_id=label_size_id)
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=CLEAR_DEFAULT,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return self._replayed_default(state, label_size_id)
            if label_size_id not in state.defaults:
                return DefaultChanged(
                    label_size_id=label_size_id,
                    override=None,
                    effective=self._effective_default(state, label_size_id),
                    generation=state.generation,
                    unchanged=True,
                )
            next_state = replace(
                state,
                defaults={
                    size: value
                    for size, value in state.defaults.items()
                    if size != label_size_id
                },
                generation=state.generation + 1,
            )
            landed = await self._async_commit(
                next_state,
                record_of(
                    key=idempotency_key,
                    operation=CLEAR_DEFAULT,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={"label_size_id": label_size_id},
                ),
            )
            self._announce(
                landed,
                previous=state.generation,
                operation=DEFAULT_CLEARED,
                label_size_id=label_size_id,
            )
            return DefaultChanged(
                label_size_id=label_size_id,
                override=None,
                effective=self._effective_default(landed, label_size_id),
                generation=landed.generation,
            )

    # -- rendering ---------------------------------------------------------

    async def async_preview_draft(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        subject: RepresentativeSubject = TYPICAL_STRAIN,
        profile: CapabilityProfile | None = None,
        density: str = "normal",
        fonts: FontLibrary | None = None,
    ) -> RenderResult:
        """Render one administrator's own draft, through the canonical path.

        The same call a print makes with one argument different, so what the
        editor is looking at is the raster the printer would receive. A draft
        that does not pass hard validation cannot be compiled at all, so the
        diagnostics come back as a refusal rather than as an approximate
        picture of an invalid layout.

        Staleness is not a reason to refuse. A draft somebody else has
        published past is still the work its owner did, and seeing it beside
        the revision that overtook it is exactly how they decide whether to
        reload, reapply by hand, or keep it as a template of its own.
        """
        owner = actor.administrator()
        state = await self.async_load()
        draft = self._locate_draft(
            state, owner, template_id=template_id, label_size_id=label_size_id
        )
        check = check_document(draft.document)
        if check.layout is None or not check.publishable:
            raise DraftNotPublishable(check.diagnostics)
        return await self._async_render(
            check.layout, subject=subject, profile=profile, density=density, fonts=fonts
        )

    async def async_preview_template(
        self,
        actor: Actor,
        ref: TemplateRef,
        *,
        revision: int | None = None,
        subject: RepresentativeSubject = TYPICAL_STRAIN,
        profile: CapabilityProfile | None = None,
        density: str = "normal",
        fonts: FontLibrary | None = None,
    ) -> RenderResult:
        """Render one published revision, for any authenticated user."""
        resolved = await self.async_resolve(actor, ref, revision)
        return await self._async_render(
            resolved.layout,
            subject=subject,
            profile=profile,
            density=density,
            fonts=fonts,
        )

    async def _async_render(
        self,
        layout: LabelLayout,
        *,
        subject: RepresentativeSubject,
        profile: CapabilityProfile | None,
        density: str,
        fonts: FontLibrary | None,
    ) -> RenderResult:
        """Render one layout against one representative subject."""
        selected = profile or _first_profile(layout.label_size_id)
        return await async_render(
            self.hass,
            layout=layout,
            content=subject.snapshot(as_of=dt_util.utcnow()),
            profile=selected,
            density=density,
            operation=PREVIEW,
            fonts=fonts,
        )

    # -- internals ---------------------------------------------------------

    def _announce(
        self,
        state: LibraryState,
        *,
        previous: int,
        operation: str,
        template_id: str | None = None,
        revision: int | None = None,
        label_size_id: str | None = None,
    ) -> None:
        """Fire one change event for a mutation that has already landed.

        After the commit, never before: an event for a write that failed would
        send every client to fetch a snapshot identical to the one it has, and
        an event for one that has not landed yet would send them to fetch the
        state it replaced.
        """
        async_fire_library_changed(
            self.hass,
            entry_id=self.entry_id,
            generation=state.generation,
            previous_generation=previous,
            operation=operation,
            template_id=template_id,
            revision=revision,
            label_size_id=label_size_id,
        )

    def _replayed_default(
        self, state: LibraryState, label_size_id: str
    ) -> DefaultChanged:
        """Answer a replayed default change by re-reading what is selected now."""
        return DefaultChanged(
            label_size_id=label_size_id,
            override=state.defaults.get(label_size_id),
            effective=self._effective_default(state, label_size_id),
            generation=state.generation,
            replayed=True,
        )

    def _effective_default(
        self, state: LibraryState, label_size_id: str
    ) -> ResolvedTemplate | None:
        """Resolve one size's Effective Default, or report that nothing does."""
        override = state.defaults.get(label_size_id)
        if override is not None:
            resolved = _resolve_override(state, override, label_size_id)
            if resolved is not None:
                return resolved
        shipped = factory_template_for_size(label_size_id)
        if shipped is None:
            return None
        layout = _factory_layout(shipped)
        if layout is None:
            return None
        return ResolvedTemplate(
            ref=TemplateRef.factory(shipped.id),
            revision=shipped.revision,
            name=shipped.name,
            label_size_id=shipped.label_size_id,
            layout=layout,
            via=FACTORY_FALLBACK,
        )

    def _validate_override(
        self, state: LibraryState, label_size_id: str, ref: TemplateRef
    ) -> ResolvedTemplate:
        """Check that one reference may be this Label Size's override."""
        if ref.kind == FACTORY:
            resolved = _resolve_factory(ref.id, None, via=OVERRIDE)
        elif ref.kind == NAMED:
            resolved = _resolve_named(
                _require_template(state, ref.id), None, via=OVERRIDE
            )
        else:
            raise LabelTemplateError(
                f"{ref.kind!r} is not a kind of template that can be a default."
            )
        if resolved.label_size_id != label_size_id:
            raise LabelSizeImmutable(
                template_id=ref.id,
                expected=resolved.label_size_id,
                found=label_size_id,
            )
        return resolved

    def _find_draft(
        self,
        state: LibraryState,
        owner: str,
        *,
        template_id: str | None,
        label_size_id: str | None,
    ) -> TemplateDraft | None:
        """Return this administrator's draft in the addressed slot, if there is one."""
        if (template_id is None) == (label_size_id is None):
            raise LabelTemplateError(
                "A draft is addressed by its template or by its Label Size, "
                "and by exactly one of them."
            )
        if template_id is not None:
            template = _require_template(state, template_id)
            return state.drafts.get(
                draft_key(
                    owner,
                    template_id=template_id,
                    label_size_id=template.label_size_id,
                )
            )
        return state.drafts.get(
            draft_key(owner, template_id=None, label_size_id=str(label_size_id))
        )

    def _locate_draft(
        self,
        state: LibraryState,
        owner: str,
        *,
        template_id: str | None,
        label_size_id: str | None,
    ) -> TemplateDraft:
        """Return this administrator's draft, or say which slot is empty."""
        draft = self._find_draft(
            state, owner, template_id=template_id, label_size_id=label_size_id
        )
        if draft is None:
            raise DraftNotFound(
                f"template {template_id!r}"
                if template_id
                else f"Label Size {label_size_id!r}"
            )
        return draft


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------


def _publish_new_template(
    state: LibraryState,
    draft: TemplateDraft,
    layout: LabelLayout,
    *,
    owner: str,
    now: str,
    provenance: Provenance,
) -> tuple[NamedTemplate, TemplateRevision]:
    """Turn one untitled draft into a Named Template at revision 1."""
    if not draft.name:
        raise TemplateNameRequired
    name = display_name(draft.name)
    if layout.label_size_id != draft.label_size_id:
        raise LabelSizeImmutable(
            template_id="(untitled)",
            expected=draft.label_size_id,
            found=layout.label_size_id,
        )
    holder = state.name_holder(name, draft.label_size_id)
    if holder is not None:
        raise DuplicateTemplateName(
            name=name, label_size_id=draft.label_size_id, template_id=holder.id
        )
    revision = TemplateRevision(
        revision=1,
        name=name,
        document=layout.as_dict(),
        digest=layout.digest,
        published_at=now,
        published_by=owner,
        operation=PUBLISH,
        parent_revision=None,
        provenance=provenance,
    )
    template = NamedTemplate(
        id=str(uuid.uuid4()),
        label_size_id=draft.label_size_id,
        created_at=now,
        created_by=owner,
        revisions=(revision,),
    )
    return template, revision


def _publish_next_revision(
    state: LibraryState,
    draft: TemplateDraft,
    layout: LabelLayout,
    *,
    owner: str,
    now: str,
    provenance: Provenance,
) -> tuple[NamedTemplate, TemplateRevision]:
    """Append one revision to the template this draft is bound to."""
    template = _require_template(state, str(draft.template_id))
    if layout.label_size_id != template.label_size_id:
        raise LabelSizeImmutable(
            template_id=template.id,
            expected=template.label_size_id,
            found=layout.label_size_id,
        )
    head = template.head
    revision = TemplateRevision(
        revision=head.revision + 1,
        name=head.name,
        document=layout.as_dict(),
        digest=layout.digest,
        published_at=now,
        published_by=owner,
        operation=PUBLISH,
        parent_revision=head.revision,
        provenance=provenance,
    )
    return template.with_revision(revision), revision


def _replayed_publication(
    state: LibraryState, draft_id: str | None, owner: str
) -> Publication | None:
    """Return the revision one draft already became, if it did.

    Only the draft's own owner is answered: the ID is opaque, but a
    publication is somebody's work and another administrator asking about it
    gets the same answer as asking about a draft that never existed.
    """
    if draft_id is None:
        return None
    for template in state.templates.values():
        for revision in template.revisions:
            if (
                revision.provenance.draft_id == draft_id
                and revision.published_by == owner
            ):
                return Publication(
                    template=template,
                    revision=revision,
                    generation=state.generation,
                    replayed=True,
                )
    return None


# ---------------------------------------------------------------------------
# Replaying a committed key
# ---------------------------------------------------------------------------


def _replayed_draft(state: LibraryState, record: CommitRecord) -> TemplateDraft:
    """Return the draft one committed key produced, as it stands now.

    The record locates a slot and names the draft that went into it. If the
    slot is empty or holds a different draft, the key's work has since been
    discarded or published -- which is a truthful "no such draft", and not a
    reason to create a second one under a key that has already been spent.
    """
    draft = state.drafts.get(str(record.locator.get("draft_key")))
    if draft is None or draft.id != record.locator.get("draft_id"):
        raise DraftNotFound(f"idempotency key {record.key!r}")
    return draft


def _replayed_revision(state: LibraryState, record: CommitRecord) -> Publication:
    """Return the publication one committed key produced.

    Revisions are immutable and never removed, so unlike a draft this is always
    findable. The generation reported is the library's now rather than the one
    the original call returned: a replay answers what is true, and the client
    asking is about to reconcile against exactly that number.
    """
    template = state.templates.get(str(record.locator.get("template_id")))
    revision = (
        None if template is None else template.revision(int(record.locator["revision"]))
    )
    if template is None or revision is None:
        raise RevisionNotFound(
            template_id=str(record.locator.get("template_id")),
            revision=int(record.locator.get("revision", 0)),
        )
    return Publication(
        template=template,
        revision=revision,
        generation=state.generation,
        replayed=True,
    )


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _head_revision(state: LibraryState, draft: TemplateDraft) -> int | None:
    """Return the current head of the template one draft is bound to."""
    if draft.template_id is None:
        return None
    template = state.templates.get(draft.template_id)
    return None if template is None else template.head.revision


def _is_stale(state: LibraryState, draft: TemplateDraft) -> bool:
    """Whether the template has moved past the revision this draft is based on.

    An untitled draft is never stale: it is based on nothing, and publishing it
    creates a template rather than appending to one. Nor is a draft whose
    template is gone -- that is an orphan, which is a different condition with
    a different remedy, and calling it stale would offer a reload of something
    that no longer exists.
    """
    head = _head_revision(state, draft)
    return head is not None and draft.base_revision != head


def _draft_wire(state: LibraryState, draft: TemplateDraft) -> dict[str, Any]:
    """Return one draft's wire form with what it cannot know about itself.

    Staleness is a fact about the draft *and* the template, so it is computed
    where both are in hand rather than stored on the draft, where a publication
    by somebody else would have to go back and rewrite it.
    """
    return {
        **draft.as_dict(),
        "stale": _is_stale(state, draft),
        "head_revision": _head_revision(state, draft),
    }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_override(
    state: LibraryState, ref: TemplateRef, label_size_id: str
) -> ResolvedTemplate | None:
    """Resolve one override, or report that it no longer resolves.

    Never an error. An override naming a template that has gone, or a revision
    that has stopped validating, is a reason to expose the factory fallback --
    not a reason for a Label Size to stop printing.
    """
    try:
        if ref.kind == FACTORY:
            resolved = _resolve_factory(ref.id, None, via=OVERRIDE)
        elif ref.kind == NAMED:
            template = state.templates.get(ref.id)
            if template is None:
                return None
            resolved = _resolve_named(template, None, via=OVERRIDE)
        else:
            return None
    except LabelTemplateError:
        return None
    return resolved if resolved.label_size_id == label_size_id else None


def _resolve_factory(
    template_id: str, revision: int | None, *, via: str
) -> ResolvedTemplate:
    """Resolve one shipped Factory Template, at the revision it ships today."""
    shipped = FACTORY_TEMPLATES.get(template_id)
    if shipped is None:
        raise TemplateNotFound(template_id)
    if revision is not None and revision != shipped.revision:
        raise RevisionNotFound(template_id=template_id, revision=revision)
    layout = _factory_layout(shipped)
    if layout is None:
        raise TemplateNotResolvable(template_id=template_id, revision=shipped.revision)
    return ResolvedTemplate(
        ref=TemplateRef.factory(shipped.id),
        revision=shipped.revision,
        name=shipped.name,
        label_size_id=shipped.label_size_id,
        layout=layout,
        via=via,
    )


def _resolve_named(
    template: NamedTemplate, revision: int | None, *, via: str
) -> ResolvedTemplate:
    """Resolve one Named Template, at its head or at a named revision."""
    selected = template.head if revision is None else template.revision(revision)
    if selected is None:
        raise RevisionNotFound(template_id=template.id, revision=int(revision or 0))
    check = check_document(selected.document)
    if check.layout is None:
        raise TemplateNotResolvable(
            template_id=template.id,
            revision=selected.revision,
            diagnostics=check.diagnostics,
        )
    return ResolvedTemplate(
        ref=TemplateRef.named(template.id),
        revision=selected.revision,
        name=selected.name,
        label_size_id=template.label_size_id,
        layout=check.layout,
        via=via,
    )


def _factory_layout(template: FactoryTemplate) -> LabelLayout | None:
    """Return one shipped layout, or nothing if it no longer validates."""
    try:
        return template.layout
    except ValueError:
        return None


def _factory_summary(template: FactoryTemplate) -> dict[str, Any]:
    """Return one shipped template's identity, and whether it is usable."""
    return {
        "kind": FACTORY,
        "id": template.id,
        "revision": template.revision,
        "name": template.name,
        "label_size_id": template.label_size_id,
        "valid": _factory_layout(template) is not None,
    }


def _effective_summary(resolved: ResolvedTemplate | None) -> dict[str, Any] | None:
    """Return one size's Effective Default without repeating its document."""
    if resolved is None:
        return None
    return {
        "ref": resolved.ref.as_dict(),
        "revision": resolved.revision,
        "name": resolved.name,
        "label_size_id": resolved.label_size_id,
        "via": resolved.via,
        "layout_digest": resolved.layout.digest,
    }


def _first_profile(label_size_id: str) -> CapabilityProfile:
    """Return a profile that can render one stock, or say there is none."""
    profiles = profiles_for_size(label_size_id)
    if not profiles:
        raise HomeAssistantError(f"No Capability Profile can render {label_size_id}")
    return profiles[0]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _optional(value: object) -> str | None:
    """Read a locator field that is either a string or genuinely absent."""
    return None if value is None else str(value)


def _require_known_size(label_size_id: str) -> None:
    """Refuse a stock that is not in the versioned catalogue."""
    if label_size_id not in LABEL_SIZES:
        raise UnsupportedLabelSize(label_size_id)


def _require_template(state: LibraryState, template_id: str) -> NamedTemplate:
    """Return one Named Template of this library, or say it is not here.

    A Factory Template ID reaches this too, and is equally "not found": a
    shipped template is not a member of anybody's library and cannot be
    published to. It is named as protected rather than as absent, because the
    two suggest different next steps.
    """
    template = state.templates.get(template_id)
    if template is None:
        if template_id in FACTORY_TEMPLATES:
            raise TemplateProtected(template_id)
        raise TemplateNotFound(template_id)
    return template


def _with_draft(state: LibraryState, draft: TemplateDraft) -> LibraryState:
    """Return the state with one draft written into its slot.

    Drafts do not advance the Library Generation. The generation identifies the
    committed *library* -- templates and defaults -- and a draft is one
    administrator's unpublished work: announcing every keystroke as a library
    change would make every other client refresh for something none of them can
    see.
    """
    return replace(state, drafts={**state.drafts, draft.key: draft})


# ---------------------------------------------------------------------------
# One library per config entry
# ---------------------------------------------------------------------------


async def async_get_library(hass: HomeAssistant, entry_id: str) -> LabelTemplateLibrary:
    """Return this config entry's library, opening it the first time.

    One instance per entry, because the lock that makes a mutation one commit
    only serializes the callers that share it.
    """
    libraries: dict[str, LabelTemplateLibrary] = hass.data.setdefault(
        DOMAIN, {}
    ).setdefault(_LIBRARIES, {})
    library = libraries.get(entry_id)
    if library is None:
        library = LabelTemplateLibrary(hass, entry_id)
        libraries[entry_id] = library
    await library.async_load()
    return library


def async_release_library(hass: HomeAssistant, entry_id: str) -> None:
    """Forget one config entry's library without touching what it stored.

    For an entry being unloaded. The `.storage` document stays exactly where
    it is: an unload is not a deletion, and the next setup reads the same
    templates back.
    """
    libraries = hass.data.get(DOMAIN, {}).get(_LIBRARIES)
    if isinstance(libraries, dict):
        libraries.pop(entry_id, None)
