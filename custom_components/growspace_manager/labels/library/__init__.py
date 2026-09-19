"""The Label Template library: who owns a layout once somebody saves it.

The canonical renderer beside this package turns a layout into a raster. This
package answers the question that comes first -- *which* layout -- and it is
the only place in the integration that does:

    blank / factory / named  ->  create_draft   ->  Template Draft
    Template Draft           ->  autosave       ->  Template Draft (any state)
    Template Draft           ->  publish        ->  Template Revision
    Label Size               ->  resolve        ->  one concrete revision

One Home Assistant config entry owns one library. Inside it are the Factory
Templates the integration ships, the Named Templates an administrator created,
one optional default override per Label Size, the immutable revision history
beneath each template, and each administrator's own durable drafts. Another
config entry's library is another `.storage` document that shares none of it.

The three invariants worth knowing before changing anything here:

- **A published revision is immutable.** The head moves by appending, never by
  editing. That is what lets a print reference a revision and stay truthful.
- **A draft may be anything.** Autosave keeps invalid work, because half of
  editing is passing through states that do not validate yet. Publication is
  the one moment a document must be a valid `LabelLayout`.
- **A template's Label Size never changes.** The millimetres mean something
  different on different paper, so converting a design between stocks is a
  transform, not an edit.
- **No write overwrites one it has not seen.** An autosave is compare-and-swap
  on the draft version and a publication compares the draft's base with the
  head, a refused write keeps its payload in the draft's recovery slot, and a
  mutation carrying an idempotency key is performed once however often it is
  retried. Divergent layouts are never merged: two independently edited
  designs compose into overlap and clipping that neither editor asked for.

Nothing here is registered as a service or a websocket command yet. The
Template Capability is advertised as one complete envelope once every required
v1 operation exists, so that the card cannot assemble a guessed capability out
of which commands happen to be registered.
"""

from __future__ import annotations

from .actor import MANAGE_LIBRARY, READ_LIBRARY, Actor
from .blank import blank_document, blank_layout
from .commits import (
    AUTOSAVE_DRAFT,
    CLEAR_DEFAULT,
    CREATE_DRAFT,
    DISCARD_DRAFT,
    DISCARD_RECOVERY,
    PUBLISH_DRAFT,
    RELOAD_DRAFT,
    SET_DEFAULT,
)
from .errors import (
    DraftIsStale,
    DraftNotFound,
    DraftNotPublishable,
    DraftVersionConflict,
    DuplicateTemplateName,
    IdempotencyKeyReused,
    IncompatibleTemplateStore,
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
from .events import (
    DEFAULT_CLEARED,
    DEFAULT_SET,
    EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED,
    PUBLISHED,
    LibraryChangedEventPayload,
    async_fire_library_changed,
)
from .library import (
    EXPLICIT,
    FACTORY_FALLBACK,
    OVERRIDE,
    DefaultChanged,
    DraftDiscarded,
    DraftSaved,
    LabelTemplateLibrary,
    Publication,
    ResolvedTemplate,
    async_get_library,
    async_release_library,
)
from .publication import PublicationCheck, check_document
from .records import (
    COMMIT_LEDGER_LIMIT,
    FACTORY,
    FROM_BLANK,
    FROM_FACTORY,
    FROM_NAMED,
    NAMED,
    PUBLISH,
    REJECTED_SAVE,
    RELOADED,
    STORE_SCHEMA,
    STORE_VERSION,
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
    normalized_name,
)
from .store import STORAGE_KEY_PREFIX, LabelTemplateStore, storage_key

__all__ = [
    "AUTOSAVE_DRAFT",
    "CLEAR_DEFAULT",
    "COMMIT_LEDGER_LIMIT",
    "CREATE_DRAFT",
    "DEFAULT_CLEARED",
    "DEFAULT_SET",
    "DISCARD_DRAFT",
    "DISCARD_RECOVERY",
    "EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED",
    "EXPLICIT",
    "FACTORY",
    "FACTORY_FALLBACK",
    "FROM_BLANK",
    "FROM_FACTORY",
    "FROM_NAMED",
    "MANAGE_LIBRARY",
    "NAMED",
    "OVERRIDE",
    "PUBLISH",
    "PUBLISHED",
    "PUBLISH_DRAFT",
    "READ_LIBRARY",
    "REJECTED_SAVE",
    "RELOADED",
    "RELOAD_DRAFT",
    "SET_DEFAULT",
    "STORAGE_KEY_PREFIX",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "Actor",
    "CommitRecord",
    "DefaultChanged",
    "DraftDiscarded",
    "DraftIsStale",
    "DraftNotFound",
    "DraftNotPublishable",
    "DraftSaved",
    "DraftVersionConflict",
    "DuplicateTemplateName",
    "IdempotencyKeyReused",
    "IncompatibleTemplateStore",
    "LabelSizeImmutable",
    "LabelTemplateError",
    "LabelTemplateLibrary",
    "LabelTemplateStore",
    "LibraryChangedEventPayload",
    "LibraryState",
    "NamedTemplate",
    "NoEffectiveDefault",
    "NoRecoveryPayload",
    "Provenance",
    "Publication",
    "PublicationCheck",
    "RecoveryPayload",
    "ResolvedTemplate",
    "RevisionNotFound",
    "TemplateDraft",
    "TemplateNameRequired",
    "TemplateNotFound",
    "TemplateNotResolvable",
    "TemplateProtected",
    "TemplateRef",
    "TemplateRevision",
    "UnsupportedLabelSize",
    "async_fire_library_changed",
    "async_get_library",
    "async_release_library",
    "blank_document",
    "blank_layout",
    "check_document",
    "display_name",
    "draft_key",
    "normalized_name",
    "storage_key",
]
