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

Managing a template afterwards is five more operations, each of them one of
two shapes and never a third. Rename and historical restore **append a
revision** to an identity that does not move. Duplicate and Save As **mint an
identity**, from the saved head and from the active draft respectively.
Replacing a layout from the factory touches **only a draft**, which is why it
is the one of the five that announces nothing. What none of them is, is a
generic "reset": discarding a draft, restoring a revision and replacing from
the factory have three different consequences, and one control that guessed
between them would be a control nobody could safely press.

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

**Nothing is destroyed to make something work.** The recovery operations are
the same three rules again, at the scale of a whole library. Deleting a
template sets it aside for thirty days with its identity and history intact and
turns its drafts into orphans rather than removing them. A template whose head
has stopped validating is quarantined -- kept, listed, exportable, openable as
a draft, and refused only where using it would mean printing it. Importing a
bundle stages all of it and commits all of it or none. Restoring a backup
replaces, because two libraries cannot be reconciled without silently choosing
for somebody. And a store written by a newer integration is not read at all:
the library reports itself contained, Home Assistant raises a repair issue
naming both versions, and every other feature carries on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
import logging
from types import MappingProxyType
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
from .backup import build_backup, read_backup
from .blank import blank_document
from .commits import (
    AUTOSAVE_DRAFT,
    CLEAR_DEFAULT,
    COLLECT_TOMBSTONES,
    CREATE_DRAFT,
    DELETE_TEMPLATE,
    DISCARD_DRAFT,
    DISCARD_RECOVERY,
    DUPLICATE_TEMPLATE,
    IMPORT_TEMPLATES,
    PUBLISH_DRAFT,
    RELOAD_DRAFT,
    RENAME_TEMPLATE,
    REPLACE_FROM_FACTORY,
    RESTORE_BACKUP,
    RESTORE_REVISION,
    RESTORE_TEMPLATE,
    SAVE_AS_TEMPLATE,
    SET_DEFAULT,
    committed,
    record_of,
    request_digest,
)
from .errors import (
    BundleNotReadable,
    DraftIsOrphaned,
    DraftIsStale,
    DraftNotFound,
    DraftNotPublishable,
    DraftVersionConflict,
    DuplicateTemplateName,
    ImportCollision,
    IncompatibleTemplateStore,
    LabelSizeImmutable,
    LabelTemplateError,
    LibraryVersionConflict,
    NoEffectiveDefault,
    NoFactoryTemplate,
    NoRecoveryPayload,
    RevisionNotFound,
    TemplateDeleted,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateProtected,
    TombstoneExpired,
    TombstoneNotFound,
    UnsupportedDependency,
    UnsupportedLabelSize,
)
from .events import (
    COLLECTED,
    DEFAULT_CLEARED,
    DEFAULT_SET,
    DELETED,
    DUPLICATED,
    IMPORTED,
    PUBLISHED,
    RENAMED,
    RESTORED,
    RESTORED_BACKUP,
    SAVED_AS,
    UNDELETED,
    async_fire_library_changed,
)
from .portable import (
    BundleEntry,
    TemplateBundle,
    build_bundle,
    read_bundle,
    unknown_dependencies,
)
from .publication import PublicationCheck, check_document
from .quarantine import quarantine_of
from .records import (
    DUPLICATE,
    FACTORY,
    FROM_BLANK,
    FROM_FACTORY,
    FROM_IMPORT,
    FROM_NAMED,
    IMPORT,
    NAMED,
    PUBLISH,
    REJECTED_SAVE,
    RELOADED,
    RENAME,
    REPLACED_FROM_FACTORY,
    RESTORE,
    SAVE_AS,
    STORE_VERSION,
    TOMBSTONE_DAYS,
    CommitRecord,
    LibraryState,
    NamedTemplate,
    Provenance,
    RecoveryPayload,
    TemplateDraft,
    TemplateRef,
    TemplateRevision,
    Tombstone,
    display_name,
    draft_key,
)
from .repair import async_clear_store_issue, async_raise_store_issue
from .store import LabelTemplateStore

_LOGGER = logging.getLogger(__name__)

#: Where the per-entry libraries are kept once opened.
_LIBRARIES = "label_template_libraries"

#: How one resolution arrived at the revision it returned.
EXPLICIT = "explicit"
OVERRIDE = "override"
FACTORY_FALLBACK = "factory_fallback"

#: Distinguishes "leave the name alone" from "set the name to nothing" on an
#: autosave, which `None` cannot do.
_UNSET = object()

#: An import that minted no copies, as a default nobody can mutate.
_EMPTY_COPIES: Mapping[str, str] = MappingProxyType({})


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
    """One committed revision, however it came to be appended.

    What publishing a draft returns, and what rename, duplicate, Save As and
    historical restore return too: all five end in one immutable revision, and
    a client that has just performed one asks the same things about it.
    """

    template: NamedTemplate
    revision: TemplateRevision
    generation: int
    #: True when this call found the revision its own draft had already
    #: become, rather than creating one. A retry after a lost response.
    replayed: bool = False
    #: True when the library already held exactly what was asked for, so
    #: nothing was appended and the generation did not move. Renaming a
    #: template to the name it has and restoring the revision that is already
    #: the head are the two ways here: a history that recorded them would be
    #: recording that nothing happened.
    unchanged: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the publication's wire form."""
        return {
            "template": self.template.summary(),
            "revision": self.revision.summary(),
            "generation": self.generation,
            "replayed": self.replayed,
            "unchanged": self.unchanged,
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


@dataclass(frozen=True, slots=True)
class TemplateDeletion:
    """One soft-deleted template, and everything the deletion moved with it.

    Three things travel back, because a deletion is three consequences at
    once and an interface that reported only the first would be hiding two.
    The tombstone says what was set aside and until when. `effective` says
    what the stock prints now, which is how "deleting the default falls back
    atomically" is observed rather than assumed. And the orphans name the
    drafts that were aimed at this template and are now recovery work.
    """

    tombstone: Tombstone
    generation: int
    #: What the deleted template's Label Size resolves to now. `None` means
    #: nothing does, which is the packaging failure a stock with no valid
    #: Factory Template has, not something this deletion caused.
    effective: ResolvedTemplate | None
    #: The drafts this deletion orphaned, by ID. Somebody else's included:
    #: an administrator deleting a template is entitled to know that other
    #: people had unpublished work aimed at it.
    orphaned: tuple[str, ...] = ()
    #: True when this deletion also cleared the Label Size's override, in the
    #: same commit.
    cleared_default: bool = False
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the deletion's wire form."""
        return {
            "tombstone": self.tombstone.summary(),
            "generation": self.generation,
            "effective": _effective_summary(self.effective),
            "orphaned_drafts": list(self.orphaned),
            "cleared_default": self.cleared_default,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class TemplateRestored:
    """One template brought back from its tombstone, whole.

    The same UUID and the same revisions: a restoration is the deletion
    undone, not a new template that resembles the old one. `renamed` says
    whether the old name had been taken in the meantime and a rename revision
    was appended to settle it, and `reconnected` names the orphaned drafts
    that are drafts of a live template again.
    """

    template: NamedTemplate
    generation: int
    renamed: bool = False
    reconnected: tuple[str, ...] = ()
    replayed: bool = False

    @property
    def revision(self) -> TemplateRevision:
        """The head this template came back at."""
        return self.template.head

    def as_dict(self) -> dict[str, Any]:
        """Return the restoration's wire form."""
        return {
            "template": self.template.summary(),
            "revision": self.revision.summary(),
            "generation": self.generation,
            "renamed": self.renamed,
            "reconnected_drafts": list(self.reconnected),
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class TombstonesCollected:
    """What one garbage collection removed for good.

    The only operation in this package that destroys anything, which is why it
    is explicit, administrator-only, and says exactly what it took. A run that
    found nothing expired writes nothing and moves no generation.
    """

    collected: tuple[str, ...] = ()
    drafts: tuple[str, ...] = ()
    generation: int = 0
    unchanged: bool = False
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the collection's wire form."""
        return {
            "collected": list(self.collected),
            "drafts": list(self.drafts),
            "generation": self.generation,
            "unchanged": self.unchanged,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class TemplatesImported:
    """What one portable import committed, entry by entry.

    Three outcomes and no fourth, because every entry of a bundle is one of
    them: it arrived under the identity it came with, it was already here
    identically and nothing happened, or the administrator asked for it under
    a fresh identity. Anything else refused the whole import before this
    existed.
    """

    imported: tuple[NamedTemplate, ...] = ()
    unchanged: tuple[str, ...] = ()
    copies: Mapping[str, str] = _EMPTY_COPIES
    generation: int = 0
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the import's wire form."""
        return {
            "imported": [template.summary() for template in self.imported],
            "unchanged": list(self.unchanged),
            "copies": dict(self.copies),
            "generation": self.generation,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class LibraryRestored:
    """One library replaced wholesale by a backup.

    `previous_generation` is here rather than derivable because a restore is
    the one operation whose generation can go *down*: the backup's number is
    restored exactly, and a client holding a higher one must be told that the
    library moved rather than left to conclude it is ahead.
    """

    generation: int
    previous_generation: int
    templates: int = 0
    drafts: int = 0
    tombstones: int = 0
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the restore's wire form."""
        return {
            "generation": self.generation,
            "previous_generation": self.previous_generation,
            "templates": self.templates,
            "drafts": self.drafts,
            "tombstones": self.tombstones,
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
        #: Set once a load finds a store this integration cannot read. From
        #: then on every operation raises it: containment is a property of the
        #: library rather than something each caller has to remember to check.
        self._incompatible: IncompatibleTemplateStore | None = None

    # -- loading -----------------------------------------------------------

    async def async_load(self) -> LibraryState:
        """Read the committed library, once, or refuse a store from the future.

        A store written at a newer version is not read at all, and this is the
        one place that is decided: every operation in this class goes through
        here, so containment cannot be forgotten at one of them. The refusal
        is remembered rather than retried, because the store does not become
        readable while Home Assistant is running and re-reading it once per
        call would only mean logging the same failure all day.

        Raising the repair issue happens here too, on the transition rather
        than on every call, and a load that succeeds withdraws it -- so the
        report heals itself when the newer integration comes back, with no
        second place remembering whether it was ever raised.
        """
        if self._incompatible is not None:
            raise self._incompatible
        if self._state is None:
            try:
                loaded = await self._store.async_load()
            except IncompatibleTemplateStore as err:
                self._incompatible = err
                async_raise_store_issue(self.hass, self.entry_id, err)
                raise
            self._state = loaded
            async_clear_store_issue(self.hass, self.entry_id)
        return self._state

    @property
    def read_only(self) -> bool:
        """Whether this library is contained behind a store it cannot read."""
        return self._incompatible is not None

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

        A contained library answers too, with the containment instead of the
        contents. That is the one place in this class where being unable to
        read the store is not an exception: a client that got an error here
        would have nothing to show but an error, when what an administrator
        needs is the two version numbers and the news that nothing was lost.
        """
        user_id = actor.authenticated()
        if self._incompatible is not None:
            return self._contained_snapshot(self._incompatible)
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
            "store": {"readable": True, "version": STORE_VERSION},
            "factory_templates": [
                _factory_summary(template) for template in FACTORY_TEMPLATES.values()
            ],
            "templates": [
                _template_summary(template)
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
            "tombstones": (
                [
                    stone.summary()
                    for stone in sorted(
                        state.tombstones.values(), key=lambda item: item.deleted_at
                    )
                ]
                if actor.is_admin
                else []
            ),
        }

    def _contained_snapshot(
        self, contained: IncompatibleTemplateStore
    ) -> dict[str, Any]:
        """Return what a library behind an unreadable store can honestly say.

        The lists are empty because nothing was read, not because nothing is
        there, and `store.readable` is what says which -- so a client renders
        the repair rather than an empty library somebody might start
        recreating templates into. The Factory Templates are still listed:
        they are the installed integration's own and were never in the store.
        """
        return {
            "entry_id": self.entry_id,
            "generation": None,
            "store": {
                "readable": False,
                "version": contained.supported,
                "found_version": contained.found,
            },
            "factory_templates": [
                _factory_summary(template) for template in FACTORY_TEMPLATES.values()
            ],
            "templates": [],
            "defaults": {},
            "effective_defaults": {},
            "drafts": [],
            "tombstones": [],
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

    async def async_open_editing_draft(
        self,
        actor: Actor,
        *,
        label_size_id: str | None = None,
        template_id: str | None = None,
        derive_from: TemplateRef | None = None,
    ) -> tuple[TemplateDraft, bool]:
        """Open what an editor is about to edit, resuming rather than replacing.

        One entry point for both slots, because "open the editor" is one act
        whichever it lands in: a Named Template's own draft when `template_id`
        names one, and this administrator's untitled draft for the stock
        otherwise.

        Resuming is the whole point, and it is why this is not
        :meth:`async_create_draft`. One untitled draft per administrator and
        Label Size *is* the store's slot, so a second create for the same
        stock replaces whatever was in it -- an editor that opened by creating
        would throw away the work it was reopening every time the page
        reloaded, the connection dropped, or the administrator opened a second
        client.

        A resume deliberately ignores `derive_from`: the existing work wins,
        because re-deriving would be the same destruction wearing an argument.
        The returned flag says which happened, so an editor can tell its user
        it came back to unsaved work instead of silently showing something
        other than the layout they just chose to start from.
        """
        owner = actor.administrator()
        if template_id is not None:
            state = await self.async_load()
            _require_template(state, template_id)
            existed = (
                self._find_draft(
                    state, owner, template_id=template_id, label_size_id=None
                )
                is not None
            )
            return await self.async_open_draft(actor, template_id), existed

        if label_size_id is None:
            raise LabelTemplateError(
                "Opening an editor needs either a Label Template or the Label "
                "Size an untitled draft is for."
            )
        _require_known_size(label_size_id)
        state = await self.async_load()
        existing = self._find_draft(
            state, owner, template_id=None, label_size_id=label_size_id
        )
        if existing is not None:
            return existing, True
        created = await self.async_create_draft(
            actor, label_size_id=label_size_id, derive_from=derive_from
        )
        return created, False

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
            _require_live(state, draft)
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
        expected_generation: int | None = None,
        expected_draft_version: int | None = None,
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
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            if expected_draft_version is not None:
                reviewed = self._locate_draft(
                    state, owner, template_id=template_id, label_size_id=label_size_id
                )
                if reviewed.version != expected_draft_version:
                    raise DraftVersionConflict(
                        expected=expected_draft_version,
                        found=reviewed.version,
                        draft=reviewed,
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
        expected_generation: int | None = None,
        expected_draft_version: int | None = None,
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
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            if expected_draft_version is not None:
                reviewed = self._locate_draft(
                    state, owner, template_id=template_id, label_size_id=None
                )
                if reviewed.version != expected_draft_version:
                    raise DraftVersionConflict(
                        expected=expected_draft_version,
                        found=reviewed.version,
                        draft=reviewed,
                    )
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
        expected_draft_version: int | None = None,
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
            if expected_draft_version is not None:
                reviewed = self._locate_draft(
                    state, owner, template_id=template_id, label_size_id=label_size_id
                )
                if reviewed.version != expected_draft_version:
                    raise DraftVersionConflict(
                        expected=expected_draft_version,
                        found=reviewed.version,
                        draft=reviewed,
                    )
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
            _require_live(state, draft)
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

    # -- managing templates ------------------------------------------------

    async def async_rename_template(
        self,
        actor: Actor,
        template_id: str,
        name: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> Publication:
        """Give one template a new name, keeping its identity and its layout.

        The UUID does not move, which is the whole point: a default override,
        a print that referenced this template and every draft of it name the
        identity, and none of them should follow a display name around.

        The new name is appended as a revision rather than written over the
        head, because the name is part of what a revision says about itself --
        a print's audit record names the template it used, and rewriting the
        name in place would silently change what an old print claims. The
        appended revision carries the previous one's document byte for byte.

        Renaming therefore advances the head, and a draft based on the
        previous one becomes stale exactly as it would after any other
        publication. That is the documented rule rather than an exception
        carved out for renames: its owner reloads, or saves their work as a
        template of its own.
        """
        owner = actor.administrator()
        digest = request_digest(
            RENAME_TEMPLATE, owner, template_id=template_id, name=name
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=RENAME_TEMPLATE,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_revision(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            template = _require_template(state, template_id)
            wanted = display_name(name)
            if not wanted:
                raise TemplateNameRequired
            head = template.head
            if wanted == head.name:
                return Publication(
                    template=template,
                    revision=head,
                    generation=state.generation,
                    unchanged=True,
                )
            _require_free_name(
                state, wanted, template.label_size_id, excluding=template.id
            )
            revision = TemplateRevision(
                revision=head.revision + 1,
                name=wanted,
                document=dict(head.document),
                digest=head.digest,
                published_at=dt_util.utcnow().isoformat(),
                published_by=owner,
                operation=RENAME,
                parent_revision=head.revision,
                provenance=Provenance(
                    source=FROM_NAMED,
                    source_template_id=template.id,
                    source_revision=head.revision,
                ),
            )
            return await self._async_append(
                state,
                template.with_revision(revision),
                revision,
                owner=owner,
                event=RENAMED,
                key=idempotency_key,
                operation=RENAME_TEMPLATE,
                digest=digest,
            )

    async def async_duplicate_template(
        self,
        actor: Actor,
        ref: TemplateRef,
        name: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> Publication:
        """Copy one template's saved head into a template of its own.

        The *saved* head, never a draft. An administrator with unpublished
        work open who duplicates is asking for a copy of what the library
        holds -- if they wanted their draft under a new identity, that is Save
        As, and the two must not be one control that guesses.

        A Factory Template can be duplicated as well as a named one: taking a
        copy is the documented way to own a shipped design, and the copy stops
        following the installed version from that moment. Nothing about the
        source changes either way.
        """
        owner = actor.administrator()
        digest = request_digest(DUPLICATE_TEMPLATE, owner, ref=ref.as_dict(), name=name)
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=DUPLICATE_TEMPLATE,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_revision(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            source = (
                _resolve_factory(ref.id, None, via=EXPLICIT)
                if ref.kind == FACTORY
                else _resolve_named(
                    _require_template(state, ref.id), None, via=EXPLICIT
                )
            )
            provenance = (
                Provenance(
                    source=FROM_FACTORY,
                    factory_id=source.ref.id,
                    factory_revision=source.revision,
                )
                if ref.kind == FACTORY
                else Provenance(
                    source=FROM_NAMED,
                    source_template_id=source.ref.id,
                    source_revision=source.revision,
                )
            )
            template, revision = _new_template(
                state,
                name=name,
                label_size_id=source.label_size_id,
                layout=source.layout,
                owner=owner,
                now=dt_util.utcnow().isoformat(),
                operation=DUPLICATE,
                provenance=provenance,
            )
            return await self._async_append(
                state,
                template,
                revision,
                owner=owner,
                event=DUPLICATED,
                key=idempotency_key,
                operation=DUPLICATE_TEMPLATE,
                digest=digest,
            )

    async def async_save_as(
        self,
        actor: Actor,
        name: str,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        draft_id: str | None = None,
        recovery_document: object | None = None,
        expected_generation: int | None = None,
        expected_draft_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> Publication:
        """Publish the active draft under a fresh identity, and clear it.

        The remedy for every situation in which a draft is good work that
        cannot become its template's next revision: somebody published first
        and it is stale, or its owner simply decided it should be a second
        label rather than a new version of the first. Staleness is therefore
        deliberately not a refusal here -- it is the reason this exists.

        The source template is not touched, at all. What this appends is
        revision 1 of a new UUID, and the draft it consumed is removed in the
        same commit, so an editor switching to the new template cannot end up
        with the old draft still sitting in its slot.
        """
        owner = actor.administrator()
        digest = request_digest(
            SAVE_AS_TEMPLATE,
            owner,
            template_id=template_id,
            label_size_id=label_size_id,
            draft_id=draft_id,
            name=name,
            recovery_document=recovery_document,
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=SAVE_AS_TEMPLATE,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_revision(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            if expected_draft_version is not None:
                reviewed = self._locate_draft(
                    state, owner, template_id=template_id, label_size_id=label_size_id
                )
                if reviewed.version != expected_draft_version:
                    raise DraftVersionConflict(
                        expected=expected_draft_version,
                        found=reviewed.version,
                        draft=reviewed,
                    )
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

            check = check_document(
                draft.document if recovery_document is None else recovery_document
            )
            if check.layout is None or not check.publishable:
                raise DraftNotPublishable(check.diagnostics)
            template, revision = _new_template(
                state,
                name=name,
                label_size_id=draft.label_size_id,
                layout=check.layout,
                owner=owner,
                now=dt_util.utcnow().isoformat(),
                operation=SAVE_AS,
                provenance=replace(
                    draft.provenance, draft_id=draft.id, draft_version=draft.version
                ),
            )
            return await self._async_append(
                state,
                template,
                revision,
                owner=owner,
                event=SAVED_AS,
                key=idempotency_key,
                operation=SAVE_AS_TEMPLATE,
                digest=digest,
                consuming=draft if recovery_document is None else None,
            )

    async def async_replace_from_factory(
        self,
        actor: Actor,
        template_id: str,
        *,
        factory_id: str | None = None,
        expected_generation: int | None = None,
        expected_draft_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateDraft:
        """Start this template's draft again from a shipped layout.

        A **draft** operation, and only that. The template keeps its UUID, its
        name and every revision it has; what changes is one administrator's
        unpublished editing state, which is why nothing here advances the
        Library Generation or announces anything. The saved layout changes
        when that draft is published and at no other moment.

        The payload that was in the draft moves to its recovery slot rather
        than being dropped -- the same promise a reload makes, for the same
        reason: an administrator who reaches for the factory design and then
        wants one measurement back off their own must be able to read it.

        Which shipped layout is named explicitly or is the one designated for
        this template's stock; either way it has to be for that stock, because
        a template's Label Size does not move.
        """
        owner = actor.administrator()
        digest = request_digest(
            REPLACE_FROM_FACTORY, owner, template_id=template_id, factory_id=factory_id
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=REPLACE_FROM_FACTORY,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_draft(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            if expected_draft_version is not None:
                reviewed = self._locate_draft(
                    state, owner, template_id=template_id, label_size_id=None
                )
                if reviewed.version != expected_draft_version:
                    raise DraftVersionConflict(
                        expected=expected_draft_version,
                        found=reviewed.version,
                        draft=reviewed,
                    )
            template = _require_template(state, template_id)
            source = _resolve_factory(
                _designated_factory(template.label_size_id, factory_id),
                None,
                via=EXPLICIT,
            )
            if source.label_size_id != template.label_size_id:
                raise LabelSizeImmutable(
                    template_id=template.id,
                    expected=template.label_size_id,
                    found=source.label_size_id,
                )

            previous = self._find_draft(
                state, owner, template_id=template_id, label_size_id=None
            )
            now = dt_util.utcnow().isoformat()
            head = template.head
            replaced = TemplateDraft(
                id=ulid_now(),
                owner=owner,
                label_size_id=template.label_size_id,
                template_id=template.id,
                base_revision=head.revision,
                version=1,
                document=source.document,
                created_at=now,
                modified_at=now,
                provenance=Provenance(
                    source=FROM_FACTORY,
                    factory_id=source.ref.id,
                    factory_revision=source.revision,
                ),
                recovery=(
                    None
                    if previous is None
                    else RecoveryPayload(
                        reason=REPLACED_FROM_FACTORY,
                        document=previous.document,
                        expected_version=None,
                        draft_version=previous.version,
                        at=now,
                        name=previous.name,
                    )
                ),
            )
            await self._async_commit(
                _with_draft(state, replaced),
                record_of(
                    key=idempotency_key,
                    operation=REPLACE_FROM_FACTORY,
                    owner=owner,
                    digest=digest,
                    generation=state.generation,
                    locator={"draft_key": replaced.key, "draft_id": replaced.id},
                ),
            )
            return replaced

    async def async_restore_revision(
        self,
        actor: Actor,
        template_id: str,
        revision: int,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> Publication:
        """Bring one historical layout back, by appending it as the new head.

        Never by rewinding. The revisions in between stay exactly where they
        are, and the restored content arrives as the next number up with
        provenance naming what it was copied from -- so the history of a
        template that was taken back to an older design still shows the
        design it was taken back from.

        The name does not travel with the layout. Content and identity are
        separate axes here, and an administrator restoring a layout has not
        asked to be renamed to whatever the template was called then.

        A revision that no longer validates cannot be restored. It is history,
        it is preserved, and making it the head would put a layout nothing can
        render in front of every print that resolves this template.
        """
        owner = actor.administrator()
        digest = request_digest(
            RESTORE_REVISION, owner, template_id=template_id, revision=revision
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=RESTORE_REVISION,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_revision(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            template = _require_template(state, template_id)
            source = template.revision(revision)
            if source is None:
                raise RevisionNotFound(template_id=template_id, revision=revision)
            head = template.head
            if source.revision == head.revision:
                return Publication(
                    template=template,
                    revision=head,
                    generation=state.generation,
                    unchanged=True,
                )
            check = check_document(source.document)
            if check.layout is None or not check.publishable:
                raise TemplateNotResolvable(
                    template_id=template_id,
                    revision=source.revision,
                    diagnostics=check.diagnostics,
                )
            restored = TemplateRevision(
                revision=head.revision + 1,
                name=head.name,
                document=check.layout.as_dict(),
                digest=check.layout.digest,
                published_at=dt_util.utcnow().isoformat(),
                published_by=owner,
                operation=RESTORE,
                parent_revision=head.revision,
                provenance=Provenance(
                    source=FROM_NAMED,
                    source_template_id=template.id,
                    source_revision=source.revision,
                ),
            )
            return await self._async_append(
                state,
                template.with_revision(restored),
                restored,
                owner=owner,
                event=RESTORED,
                key=idempotency_key,
                operation=RESTORE_REVISION,
                digest=digest,
            )

    async def _async_append(
        self,
        state: LibraryState,
        template: NamedTemplate,
        revision: TemplateRevision,
        *,
        owner: str,
        event: str,
        key: str | None,
        operation: str,
        digest: str,
        consuming: TemplateDraft | None = None,
    ) -> Publication:
        """Commit one appended revision, and announce it once it landed.

        The tail every management operation shares: write the template, drop
        the draft that became it where there was one, advance the generation,
        record the idempotency key, and fire the change event -- all in the
        one order that cannot leave a revision without its generation or an
        event for a write that did not happen.
        """
        drafts = (
            state.drafts
            if consuming is None
            else {
                item: value
                for item, value in state.drafts.items()
                if item != consuming.key
            }
        )
        landed = await self._async_commit(
            replace(
                state,
                templates={**state.templates, template.id: template},
                drafts=drafts,
                generation=state.generation + 1,
            ),
            record_of(
                key=key,
                operation=operation,
                owner=owner,
                digest=digest,
                generation=state.generation + 1,
                locator={"template_id": template.id, "revision": revision.revision},
            ),
        )
        self._announce(
            landed,
            previous=state.generation,
            operation=event,
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
        expected_generation: int | None = None,
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
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
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
        self,
        actor: Actor,
        label_size_id: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
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
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
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

    # -- deleting, and undeleting ------------------------------------------

    async def async_delete_template(
        self,
        actor: Actor,
        template_id: str,
        *,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateDeletion:
        """Set one Named Template aside for thirty days, whole.

        Not a removal. The template -- identity, name, every revision and all
        of their provenance -- moves into a tombstone that holds it until it
        expires, which is what lets a restoration return the same UUID and the
        same history rather than something that resembles them. A print whose
        audit record names this template still names something that exists.

        Three things happen in the one commit, because any two of them apart
        would be a state somebody could observe. The template leaves ordinary
        selection. If it was a Label Size's override, that override is
        cleared, so the stock falls back to its Factory Template instead of
        resolving through an identity that is no longer selectable. And the
        drafts aimed at it become Orphaned Drafts: kept, readable, previewable
        and available to Save As, because deleting a template is not a
        decision about somebody else's unpublished work.

        Factory Templates cannot be deleted, which `_require_template` already
        says: they are the integration's, and they are what everything else
        falls back to.
        """
        owner = actor.administrator()
        digest = request_digest(DELETE_TEMPLATE, owner, template_id=template_id)
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=DELETE_TEMPLATE,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return self._replayed_deletion(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            template = _require_template(state, template_id)
            now = dt_util.utcnow()
            held = tuple(
                size
                for size, ref in state.defaults.items()
                if ref.kind == NAMED and ref.id == template_id
            )
            stone = Tombstone(
                template=template,
                deleted_at=now.isoformat(),
                deleted_by=owner,
                expires_at=(now + timedelta(days=TOMBSTONE_DAYS)).isoformat(),
                was_default=bool(held),
            )
            orphaned = tuple(
                draft.id
                for draft in state.drafts.values()
                if draft.template_id == template_id
            )
            landed = await self._async_commit(
                replace(
                    state,
                    templates={
                        key: value
                        for key, value in state.templates.items()
                        if key != template_id
                    },
                    tombstones={**state.tombstones, template_id: stone},
                    defaults={
                        size: ref
                        for size, ref in state.defaults.items()
                        if size not in held
                    },
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=DELETE_TEMPLATE,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={
                        "template_id": template_id,
                        "label_size_id": template.label_size_id,
                    },
                ),
            )
            self._announce(
                landed,
                previous=state.generation,
                operation=DELETED,
                template_id=template_id,
                label_size_id=template.label_size_id,
            )
            return TemplateDeletion(
                tombstone=stone,
                generation=landed.generation,
                effective=self._effective_default(landed, template.label_size_id),
                orphaned=orphaned,
                cleared_default=bool(held),
            )

    async def async_restore_template(
        self,
        actor: Actor,
        template_id: str,
        *,
        name: str | None = None,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> TemplateRestored:
        """Bring one deleted template back, with the identity it always had.

        The same UUID and the same revisions, because that is what was set
        aside; every default override, print reference and draft that named
        this identity means this template again without being rewritten.

        Two things it deliberately does not do. It **does not reclaim the
        default**: whatever was selected while this template was gone has been
        printing ever since, and taking that back silently would change what
        comes out of the printer for a reason nobody asked for. And it does
        not take a name that somebody else has used in the meantime -- the
        deletion freed the name, so a conflict is refused and an administrator
        supplies a new one, which is appended as a rename revision because a
        name lives on a revision and revisions are not rewritten.

        Orphaned drafts reconnect by doing nothing at all: a draft names the
        template it is for, so restoring the template makes it a draft again.
        One based on the revision that was the head before a rename is stale
        afterwards, which is the ordinary rule rather than a special case.

        An expired tombstone is refused rather than quietly honoured. Thirty
        days that sometimes meant ninety would be a promise nobody could plan
        around.
        """
        owner = actor.administrator()
        digest = request_digest(
            RESTORE_TEMPLATE, owner, template_id=template_id, name=name
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=RESTORE_TEMPLATE,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return self._replayed_restoration(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            stone = state.tombstones.get(template_id)
            if stone is None:
                raise TombstoneNotFound(template_id)
            if stone.has_expired(dt_util.utcnow()):
                raise TombstoneExpired(
                    template_id=template_id, expires_at=stone.expires_at
                )
            template = stone.template
            wanted = display_name(name) if name is not None else template.name
            if not wanted:
                raise TemplateNameRequired
            _require_free_name(
                state, wanted, template.label_size_id, excluding=template.id
            )
            renamed = wanted != template.name
            if renamed:
                head = template.head
                template = template.with_revision(
                    TemplateRevision(
                        revision=head.revision + 1,
                        name=wanted,
                        document=dict(head.document),
                        digest=head.digest,
                        published_at=dt_util.utcnow().isoformat(),
                        published_by=owner,
                        operation=RENAME,
                        parent_revision=head.revision,
                        provenance=Provenance(
                            source=FROM_NAMED,
                            source_template_id=template.id,
                            source_revision=head.revision,
                        ),
                    )
                )
            reconnected = tuple(
                draft.id
                for draft in state.drafts.values()
                if draft.template_id == template_id
            )
            landed = await self._async_commit(
                replace(
                    state,
                    templates={**state.templates, template.id: template},
                    tombstones={
                        key: value
                        for key, value in state.tombstones.items()
                        if key != template_id
                    },
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=RESTORE_TEMPLATE,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={
                        "template_id": template_id,
                        "revision": template.head.revision,
                        "renamed": renamed,
                    },
                ),
            )
            self._announce(
                landed,
                previous=state.generation,
                operation=UNDELETED,
                template_id=template.id,
                revision=template.head.revision,
                label_size_id=template.label_size_id,
            )
            return TemplateRestored(
                template=template,
                generation=landed.generation,
                renamed=renamed,
                reconnected=reconnected,
            )

    async def async_collect_tombstones(
        self, actor: Actor, *, idempotency_key: str | None = None
    ) -> TombstonesCollected:
        """Remove the deletions whose recovery window has closed, for good.

        The one operation here that destroys anything, which is why it is
        explicit rather than something a load quietly does on the way past.
        Opening a library must not write, and a sweep that ran on every start
        would make "your templates were collected" a thing that happened
        while nobody was looking.

        An expired tombstone takes its remaining Orphaned Drafts with it. They
        were work aimed at a template that has now genuinely gone, they have
        had the same thirty days, and leaving them behind would be keeping a
        draft of nothing forever.

        Nothing expired means nothing written and no generation advanced:
        there is no change for another client to hear about.
        """
        owner = actor.administrator()
        digest = request_digest(COLLECT_TOMBSTONES, owner)
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=COLLECT_TOMBSTONES,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return TombstonesCollected(
                    collected=tuple(
                        str(item) for item in record.locator.get("collected", ())
                    ),
                    drafts=tuple(
                        str(item) for item in record.locator.get("drafts", ())
                    ),
                    generation=state.generation,
                    replayed=True,
                )
            now = dt_util.utcnow()
            expired = tuple(
                key for key, stone in state.tombstones.items() if stone.has_expired(now)
            )
            if not expired:
                return TombstonesCollected(generation=state.generation, unchanged=True)
            abandoned = tuple(
                draft.key
                for draft in state.drafts.values()
                if draft.template_id in expired
            )
            landed = await self._async_commit(
                replace(
                    state,
                    tombstones={
                        key: value
                        for key, value in state.tombstones.items()
                        if key not in expired
                    },
                    drafts={
                        key: value
                        for key, value in state.drafts.items()
                        if key not in abandoned
                    },
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=COLLECT_TOMBSTONES,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={
                        "collected": list(expired),
                        "drafts": [
                            state.drafts[key].id
                            for key in abandoned
                            if key in state.drafts
                        ],
                    },
                ),
            )
            collected = TombstonesCollected(
                collected=expired,
                drafts=tuple(state.drafts[key].id for key in abandoned),
                generation=landed.generation,
            )
            self._announce(landed, previous=state.generation, operation=COLLECTED)
            return collected

    async def async_inspect_template(
        self, actor: Actor, template_id: str
    ) -> dict[str, Any]:
        """Read complete history, including quarantined and deleted documents."""
        actor.administrator()
        state = await self.async_load()
        template = state.templates.get(template_id)
        if template is None:
            stone = state.tombstones.get(template_id)
            if stone is None:
                raise TemplateNotFound(template_id)
            template = stone.template
        return template.as_dict()

    async def async_preflight_import(
        self,
        actor: Actor,
        bundle: object,
        *,
        as_copy: Sequence[str] = (),
        names: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Report all entry conflicts without writing any part of the bundle."""
        owner = actor.administrator()
        async with self._lock:
            state = await self.async_load()
            parsed = read_bundle(bundle)
            issues: list[dict[str, Any]] = []
            working = state
            rows = []
            for entry in parsed.entries:
                rows.append(
                    {
                        "id": entry.id,
                        "name": entry.name,
                        "label_size_id": entry.label_size_id,
                    }
                )
                # Independently check content, identity and name so resolving an
                # identity collision does not reveal a previously hidden name conflict.
                checks = (
                    lambda entry=entry: _importable(entry),
                    lambda working=working, entry=entry: _import_target(
                        working, entry, as_copy=frozenset(as_copy)
                    ),
                    lambda working=working, entry=entry: _require_free_name(
                        working,
                        display_name((names or {}).get(entry.id, entry.name)),
                        entry.label_size_id,
                        excluding=entry.id if entry.id not in as_copy else None,
                    ),
                )
                for check in checks:
                    try:
                        check()
                    except LabelTemplateError as error:
                        issues.append(
                            {
                                "template_id": entry.id,
                                "code": type(error).__name__,
                                "reason": str(error),
                            }
                        )
                try:
                    staged = _stage_import(
                        working,
                        replace(parsed, entries=(entry,)),
                        as_copy=frozenset(as_copy),
                        names=names or {},
                        owner=owner,
                        now=dt_util.utcnow().isoformat(),
                    )
                    working = replace(
                        working,
                        templates={
                            **working.templates,
                            **{item.id: item for item in staged.templates},
                        },
                    )
                except LabelTemplateError as error:
                    issue = {
                        "template_id": entry.id,
                        "code": type(error).__name__,
                        "reason": str(error),
                    }
                    if issue not in issues:
                        issues.append(issue)
            return {
                "generation": state.generation,
                "entries": rows,
                "issues": issues,
                "ready": not issues,
            }

    # -- moving a library --------------------------------------------------

    async def async_export_templates(
        self, actor: Actor, refs: Sequence[TemplateRef] | None = None
    ) -> dict[str, Any]:
        """Bundle the current revisions of these templates, for somebody else.

        Administrator-only, like every other library operation that is not
        resolving or rendering a published template: a bundle is the complete
        saved design of every template in it, which is more than a user who
        prints labels has ever been shown.

        `refs` names Named Templates, and all of them when it is omitted. A
        Factory Template is refused rather than bundled -- it is the
        installed integration's, the other installation already has its own,
        and shipping a copy is how two installations end up disagreeing about
        what the factory design is. Duplicating one into a Named Template
        first is the documented way to share it.

        What comes back is unvalidated on purpose. A Quarantined Template is
        exactly what an administrator most needs to hand to somebody with a
        newer integration, and refusing to export what cannot be printed today
        would make export useless at the one moment it matters.
        """
        actor.administrator()
        state = await self.async_load()
        chosen = (
            sorted(state.templates.values(), key=lambda item: item.name.casefold())
            if refs is None
            else [_require_named(state, ref) for ref in refs]
        )
        return build_bundle(chosen, exported_at=dt_util.utcnow().isoformat()).as_dict()

    async def async_import_templates(
        self,
        actor: Actor,
        bundle: object,
        *,
        as_copy: Sequence[str] = (),
        names: Mapping[str, str] | None = None,
        expected_generation: int | None = None,
        idempotency_key: str | None = None,
    ) -> TemplatesImported:
        """Add somebody else's templates, all of them or none of them.

        The whole bundle is staged before anything is written: format,
        checksum, every Label Size, every document against the publication
        gate, every dependency against the installed catalogues, and every
        identity and name collision. A refusal at any of them leaves the
        library untouched, which is the only way an import can be safe to
        retry -- a half-applied bundle would have to be un-applied by hand.

        Collisions are the administrator's to resolve, never this method's.
        An identity nobody here has arrives as itself. The same identity
        carrying the same content is already here, so nothing happens. The
        same identity carrying *different* content is refused: whichever side
        this picked, it would be silently discarding a design somebody made.
        Naming that entry in `as_copy` mints a fresh identity for it instead,
        and `names` settles a name another template of that stock already
        holds.

        What an import never does is publish a draft, change a default, or
        touch history. Everything it commits arrives as a saved, non-default
        Named Template at revision 1, recording in its provenance which
        template and revision it came from.
        """
        owner = actor.administrator()
        digest = request_digest(
            IMPORT_TEMPLATES,
            owner,
            bundle=bundle.get("checksum") if isinstance(bundle, Mapping) else None,
            as_copy=sorted(as_copy),
            names=dict(sorted((names or {}).items())),
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=IMPORT_TEMPLATES,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return _replayed_import(state, record)
            if (
                expected_generation is not None
                and state.generation != expected_generation
            ):
                raise LibraryVersionConflict(expected_generation, state.generation)
            staged = _stage_import(
                state,
                read_bundle(bundle),
                as_copy=frozenset(as_copy),
                names=names or {},
                owner=owner,
                now=dt_util.utcnow().isoformat(),
            )
            if not staged.templates:
                return TemplatesImported(
                    unchanged=staged.unchanged, generation=state.generation
                )
            landed = await self._async_commit(
                replace(
                    state,
                    templates={
                        **state.templates,
                        **{item.id: item for item in staged.templates},
                    },
                    generation=state.generation + 1,
                ),
                record_of(
                    key=idempotency_key,
                    operation=IMPORT_TEMPLATES,
                    owner=owner,
                    digest=digest,
                    generation=state.generation + 1,
                    locator={
                        "template_ids": [item.id for item in staged.templates],
                        "unchanged": list(staged.unchanged),
                        "copies": dict(staged.copies),
                    },
                ),
            )
            self._announce(landed, previous=state.generation, operation=IMPORTED)
            return TemplatesImported(
                imported=staged.templates,
                unchanged=staged.unchanged,
                copies=staged.copies,
                generation=landed.generation,
            )

    async def async_backup(self, actor: Actor) -> dict[str, Any]:
        """Return this entry's complete library as a restorable document.

        Everything, including the parts a portable bundle deliberately leaves
        out: full revision history, every administrator's drafts with whatever
        invalid work is in them, the default overrides, the tombstones with
        their recovery windows still ticking, the idempotency ledger and the
        Library Generation. A backup that dropped any of those would restore a
        library that had quietly lost something nobody asked it to lose.
        """
        actor.administrator()
        state = await self.async_load()
        return build_backup(
            self.entry_id, state, created_at=dt_util.utcnow().isoformat()
        )

    async def async_restore_backup(
        self,
        actor: Actor,
        document: object,
        *,
        idempotency_key: str | None = None,
    ) -> LibraryRestored:
        """Replace this entry's library with a backup, once all of it validates.

        Replacement rather than merge, and the reason is that a merge would
        have to choose: the same UUID may hold different history on each side,
        and the same name may belong to different identities. There is no rule
        that picks correctly without being told, and picking silently is how
        somebody's templates disappear into a successful-looking restore.

        Everything is staged and validated first -- format, checksum, every
        record, and that the dictionaries agree with the records in them -- so
        a failure is a refusal rather than a partial library. The write itself
        is the ordinary one commit, and the in-memory state is replaced only
        once the store returned.

        The generation comes back exactly as the backup held it, which can be
        *lower* than the one this library was at. That is why the change event
        matters here more than anywhere else: a client compares the event's
        previous generation with its own, finds a gap, and refreshes the whole
        snapshot rather than believing it is ahead of the server.
        """
        owner = actor.administrator()
        digest = request_digest(
            RESTORE_BACKUP,
            owner,
            checksum=(
                document.get("checksum") if isinstance(document, Mapping) else None
            ),
        )
        async with self._lock:
            state = await self.async_load()
            record = committed(
                state,
                key=idempotency_key,
                operation=RESTORE_BACKUP,
                owner=owner,
                digest=digest,
            )
            if record is not None:
                return LibraryRestored(
                    generation=state.generation,
                    previous_generation=int(record.locator.get("previous", 0)),
                    templates=len(state.templates),
                    drafts=len(state.drafts),
                    tombstones=len(state.tombstones),
                    replayed=True,
                )
            staged = read_backup(document)
            landed = await self._async_commit(
                staged,
                record_of(
                    key=idempotency_key,
                    operation=RESTORE_BACKUP,
                    owner=owner,
                    digest=digest,
                    generation=staged.generation,
                    locator={"previous": state.generation},
                ),
            )
            self._announce(landed, previous=state.generation, operation=RESTORED_BACKUP)
            return LibraryRestored(
                generation=landed.generation,
                previous_generation=state.generation,
                templates=len(landed.templates),
                drafts=len(landed.drafts),
                tombstones=len(landed.tombstones),
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
        expected_version: int | None = None,
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

        `expected_version` is. A render is slow and an editor is fast, so a
        preview asked for before the last autosave landed would come back as a
        picture of an older layout with nothing on it saying so. Passing the
        version makes the render a read of exactly that state or nothing:
        refused, the editor keeps a raster it knows is stale, which is the
        honest state and the one the user can see.
        """
        _draft, layout = await self.async_draft_layout(
            actor,
            template_id=template_id,
            label_size_id=label_size_id,
            expected_version=expected_version,
        )
        return await self._async_render(
            layout, subject=subject, profile=profile, density=density, fonts=fonts
        )

    async def async_draft_layout(
        self,
        actor: Actor,
        *,
        template_id: str | None = None,
        label_size_id: str | None = None,
        expected_version: int | None = None,
    ) -> tuple[TemplateDraft, LabelLayout]:
        """Return this administrator's draft at one version, compiled or refused.

        The one read every route that puts a draft in front of somebody shares
        -- a preview on screen and a test print on paper alike -- so the two
        cannot disagree about which version they drew or whether it validated.
        """
        owner = actor.administrator()
        state = await self.async_load()
        draft = self._locate_draft(
            state, owner, template_id=template_id, label_size_id=label_size_id
        )
        if expected_version is not None and expected_version != draft.version:
            raise DraftVersionConflict(
                expected=expected_version, found=draft.version, draft=draft
            )
        check = check_document(draft.document)
        if check.layout is None or not check.publishable:
            raise DraftNotPublishable(check.diagnostics)
        return draft, check.layout

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

    def _replayed_deletion(
        self, state: LibraryState, record: CommitRecord
    ) -> TemplateDeletion:
        """Answer a replayed deletion by re-reading the tombstone it made.

        A tombstone that has since been collected is gone for good, and
        saying so is truthful where reconstructing one from the ledger would
        be inventing a recovery window that has already expired.
        """
        template_id = str(record.locator["template_id"])
        stone = state.tombstones.get(template_id)
        if stone is None:
            raise TombstoneNotFound(template_id)
        return TemplateDeletion(
            tombstone=stone,
            generation=state.generation,
            effective=self._effective_default(state, stone.label_size_id),
            orphaned=tuple(
                draft.id
                for draft in state.drafts.values()
                if draft.template_id == template_id
            ),
            cleared_default=stone.was_default,
            replayed=True,
        )

    def _replayed_restoration(
        self, state: LibraryState, record: CommitRecord
    ) -> TemplateRestored:
        """Answer a replayed restoration by re-reading the template it revived."""
        template_id = str(record.locator["template_id"])
        template = state.templates.get(template_id)
        if template is None:
            raise TemplateNotFound(template_id)
        return TemplateRestored(
            template=template,
            generation=state.generation,
            renamed=bool(record.locator.get("renamed", False)),
            reconnected=tuple(
                draft.id
                for draft in state.drafts.values()
                if draft.template_id == template_id
            ),
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
            return state.drafts.get(
                draft_key(
                    owner,
                    template_id=template_id,
                    label_size_id=_draft_subject(state, template_id),
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
    return _new_template(
        state,
        name=draft.name,
        label_size_id=draft.label_size_id,
        layout=layout,
        owner=owner,
        now=now,
        operation=PUBLISH,
        provenance=provenance,
    )


def _new_template(
    state: LibraryState,
    *,
    name: str,
    label_size_id: str,
    layout: LabelLayout,
    owner: str,
    now: str,
    operation: str,
    provenance: Provenance,
) -> tuple[NamedTemplate, TemplateRevision]:
    """Mint one Named Template at revision 1 from a validated layout.

    What publishing an untitled draft, duplicating a saved head and Save As
    all come down to: a fresh UUID, a free name within the stock, and one
    revision recording which of the three it was. The identity is minted here
    and nowhere else, so there is exactly one place a template can be born.
    """
    wanted = display_name(name)
    if not wanted:
        raise TemplateNameRequired
    if layout.label_size_id != label_size_id:
        raise LabelSizeImmutable(
            template_id="(untitled)",
            expected=label_size_id,
            found=layout.label_size_id,
        )
    _require_free_name(state, wanted, label_size_id)
    revision = TemplateRevision(
        revision=1,
        name=wanted,
        document=layout.as_dict(),
        digest=layout.digest,
        published_at=now,
        published_by=owner,
        operation=operation,
        parent_revision=None,
        provenance=provenance,
    )
    template = NamedTemplate(
        id=str(uuid.uuid4()),
        label_size_id=label_size_id,
        created_at=now,
        created_by=owner,
        revisions=(revision,),
    )
    return template, revision


def _require_free_name(
    state: LibraryState,
    name: str,
    label_size_id: str,
    *,
    excluding: str | None = None,
) -> None:
    """Refuse a name another template of this stock already holds.

    Trimmed and case-insensitively, and only within the Label Size: the same
    name on different paper is a different label, not a collision. `excluding`
    is how a rename asks the question without the template answering it about
    itself.
    """
    holder = state.name_holder(name, label_size_id, excluding=excluding)
    if holder is not None:
        raise DuplicateTemplateName(
            name=name, label_size_id=label_size_id, template_id=holder.id
        )


def _designated_factory(label_size_id: str, factory_id: str | None) -> str:
    """Return the shipped template to start from, or say none is shipped.

    An explicit ID is taken as given -- whether it exists is `_resolve_factory`
    to answer, and whether it is for the right stock is the caller's. With no
    ID it is the one designated for this stock, and a stock the integration
    ships nothing for says exactly that rather than producing an approximate
    layout from somewhere else.
    """
    if factory_id is not None:
        return factory_id
    shipped = factory_template_for_size(label_size_id)
    if shipped is None:
        raise NoFactoryTemplate(label_size_id)
    return shipped.id


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
# Staging one import
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StagedImport:
    """One fully validated bundle, composed but not yet written."""

    templates: tuple[NamedTemplate, ...]
    unchanged: tuple[str, ...]
    copies: Mapping[str, str]


def _stage_import(
    state: LibraryState,
    bundle: TemplateBundle,
    *,
    as_copy: frozenset[str],
    names: Mapping[str, str],
    owner: str,
    now: str,
) -> _StagedImport:
    """Validate and compose every entry of a bundle, writing nothing.

    All of it before any of it, which is what makes an import atomic in the
    only sense that matters to the person running one: the twelfth entry
    colliding is a reason for the first eleven not to arrive, because a
    partial library is one nobody can reason about afterwards.

    Names are checked against the library *as this import would leave it*, so
    two entries of one bundle claiming the same name collide with each other
    rather than the second quietly overwriting the first.
    """
    minted: list[NamedTemplate] = []
    unchanged: list[str] = []
    copies: dict[str, str] = {}
    working = state
    for entry in bundle.entries:
        layout = _importable(entry)
        target = _import_target(working, entry, as_copy=as_copy)
        wanted = display_name(names.get(entry.id, entry.name))
        if not wanted:
            raise TemplateNameRequired
        if target is None:
            _require_free_name(working, wanted, entry.label_size_id, excluding=entry.id)
            unchanged.append(entry.id)
            continue
        _require_free_name(working, wanted, entry.label_size_id)
        template = NamedTemplate(
            id=target,
            label_size_id=entry.label_size_id,
            created_at=now,
            created_by=owner,
            revisions=(
                TemplateRevision(
                    revision=1,
                    name=wanted,
                    document=layout.as_dict(),
                    digest=layout.digest,
                    published_at=now,
                    published_by=owner,
                    operation=IMPORT,
                    parent_revision=None,
                    provenance=Provenance(
                        source=FROM_IMPORT,
                        source_template_id=entry.id,
                        source_revision=entry.revision,
                    ),
                ),
            ),
        )
        if target != entry.id:
            copies[entry.id] = target
        minted.append(template)
        working = replace(
            working, templates={**working.templates, template.id: template}
        )
    return _StagedImport(
        templates=tuple(minted),
        unchanged=tuple(unchanged),
        copies=copies,
    )


def _importable(entry: BundleEntry) -> LabelLayout:
    """Return the layout one entry carries, or refuse to import it.

    Three questions, in the order whose answers are most useful: is this stock
    one we have, is everything the document refers to installed, and does the
    document itself still pass the gate every published revision passes. An
    entry that fails any of them is refused by name -- never imported with the
    unknown parts dropped, which would be the one outcome that looks like
    success and prints wrongly.
    """
    _require_known_size(entry.label_size_id)
    missing = unknown_dependencies(entry.dependencies)
    if missing:
        raise UnsupportedDependency(template_id=entry.id, missing=missing)
    check = check_document(entry.document)
    if check.layout is None or not check.publishable:
        raise TemplateNotResolvable(
            template_id=entry.id,
            revision=entry.revision,
            diagnostics=check.diagnostics,
        )
    if check.layout.label_size_id != entry.label_size_id:
        raise LabelSizeImmutable(
            template_id=entry.id,
            expected=entry.label_size_id,
            found=check.layout.label_size_id,
        )
    if entry.digest != check.layout.digest:
        raise BundleNotReadable(
            f"template {entry.id!r} carries a digest that does not describe "
            "its own layout."
        )
    return check.layout


def _import_target(
    state: LibraryState, entry: BundleEntry, *, as_copy: frozenset[str]
) -> str | None:
    """Return the identity this entry should arrive under, or nothing at all.

    `None` means it is already here, identically, and an import of something
    that is already here is not an event. A fresh UUID means the
    administrator asked for a copy. Anything else that cannot be taken as
    given is a collision they have to answer, because both available answers
    -- overwrite theirs, or discard the import -- destroy a design somebody
    made.
    """
    if entry.id in as_copy:
        return str(uuid.uuid4())
    existing = state.templates.get(entry.id)
    if existing is not None:
        if existing.head.digest == entry.digest:
            return None
        raise ImportCollision(
            template_id=entry.id,
            reason="a different layout is already saved under that identity here",
        )
    if entry.id in state.tombstones:
        raise ImportCollision(
            template_id=entry.id,
            reason="it was deleted here and is still recoverable",
        )
    return entry.id


def _replayed_import(state: LibraryState, record: CommitRecord) -> TemplatesImported:
    """Answer a replayed import by re-reading the templates it committed."""
    imported = []
    for template_id in record.locator.get("template_ids", ()):
        template = state.templates.get(str(template_id))
        if template is None:
            raise TemplateNotFound(str(template_id))
        imported.append(template)
    return TemplatesImported(
        imported=tuple(imported),
        unchanged=tuple(str(item) for item in record.locator.get("unchanged", ())),
        copies={
            str(key): str(value)
            for key, value in (record.locator.get("copies") or {}).items()
        },
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
        "orphaned": _is_orphaned(state, draft),
    }


def _is_orphaned(state: LibraryState, draft: TemplateDraft) -> bool:
    """Whether this draft's template has been deleted out from under it.

    Reported beside staleness rather than folded into it, because the two have
    opposite remedies: a stale draft reloads from a newer head, and an orphan
    has no head to reload from. An editor offering "reload" for an orphan
    would be offering to fetch something that is not there.
    """
    return draft.template_id is not None and draft.template_id not in state.templates


def _template_summary(template: NamedTemplate) -> dict[str, Any]:
    """Return one template's listing entry, with why it cannot print if so.

    Quarantine is attached here rather than stored on the record because it is
    a fact about a document and *today's* catalogues: a flag written onto the
    template would survive the upgrade that fixed it.
    """
    quarantine = quarantine_of(template)
    return {
        **template.summary(),
        "quarantined": quarantine is not None,
        "quarantine": quarantine.as_dict() if quarantine is not None else None,
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
    """Resolve one Named Template, at its head or at a named revision.

    The gate is the Publication Gate, exactly: what could not be published
    today cannot be printed today either. Holding resolution to a weaker
    standard is how a library ends up able to print something it would refuse
    to save -- and a template whose head fails it is a Quarantined Template,
    which is this refusal seen from the listing rather than a second rule.
    """
    selected = template.head if revision is None else template.revision(revision)
    if selected is None:
        raise RevisionNotFound(template_id=template.id, revision=int(revision or 0))
    check = check_document(selected.document)
    if check.layout is None or not check.publishable:
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
    """Return one Named Template of this library, or say why it is not here.

    Three different absences, because they call for three different next
    steps. A Factory Template ID is *protected*: it is the integration's, not
    a member of anybody's library, and the way to change one is to copy it. A
    soft-deleted identity is *deleted*: it is still here, still complete, and
    restoring it is one call away. Anything else genuinely does not exist.
    """
    template = state.templates.get(template_id)
    if template is None:
        if template_id in FACTORY_TEMPLATES:
            raise TemplateProtected(template_id)
        stone = state.tombstones.get(template_id)
        if stone is not None:
            raise TemplateDeleted(template_id=template_id, expires_at=stone.expires_at)
        raise TemplateNotFound(template_id)
    return template


def _require_named(state: LibraryState, ref: TemplateRef) -> NamedTemplate:
    """Return the Named Template one reference names, refusing any other kind."""
    if ref.kind != NAMED:
        raise TemplateProtected(ref.id)
    return _require_template(state, ref.id)


def _draft_subject(state: LibraryState, template_id: str) -> str:
    """Return the stock a draft's template is for, deleted or not.

    A draft outlives the deletion of its template, so addressing one cannot
    go through the live templates alone. The slot itself does not depend on
    the answer -- a template-bound draft is keyed by its template -- but the
    question of whether this identity means anything at all does, and an
    identity nobody has ever heard of is still a genuine "not found".
    """
    template = state.templates.get(template_id)
    if template is not None:
        return template.label_size_id
    stone = state.tombstones.get(template_id)
    if stone is not None:
        return stone.label_size_id
    if template_id in FACTORY_TEMPLATES:
        raise TemplateProtected(template_id)
    raise TemplateNotFound(template_id)


def _require_live(state: LibraryState, draft: TemplateDraft) -> None:
    """Refuse a draft whose template has been deleted out from under it.

    Applied where the operation only makes sense against a template that is
    there: editing towards a revision that can never be appended, reloading
    from a head that is gone, publishing onto nothing. Reading, previewing,
    discarding and Save As are deliberately not in that list -- an orphan is
    recovery work, and every one of those is how somebody recovers it.
    """
    if draft.template_id is not None and draft.template_id not in state.templates:
        raise DraftIsOrphaned(template_id=draft.template_id)


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

    A store this integration cannot read comes back as a **contained**
    library rather than as an exception. That is what "other Growspace Manager
    features continue" is made of: setting up an entry must not fail because
    its templates were written by a newer version, and every call that needed
    to read the store raises for itself anyway. The repair issue naming both
    versions has been raised by the time this returns.
    """
    libraries: dict[str, LabelTemplateLibrary] = hass.data.setdefault(
        DOMAIN, {}
    ).setdefault(_LIBRARIES, {})
    library = libraries.get(entry_id)
    if library is None:
        library = LabelTemplateLibrary(hass, entry_id)
        libraries[entry_id] = library
    try:
        await library.async_load()
    except IncompatibleTemplateStore:
        _LOGGER.error(
            "The Label Template library of config entry %s was written by a "
            "newer Growspace Manager and has been left untouched; template "
            "management and template-based printing are unavailable for it",
            entry_id,
        )
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
