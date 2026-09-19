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

Nothing here is registered as a service or a websocket command yet. The
Template Capability is advertised as one complete envelope once every required
v1 operation exists, so that the card cannot assemble a guessed capability out
of which commands happen to be registered.
"""

from __future__ import annotations

from .actor import MANAGE_LIBRARY, READ_LIBRARY, Actor
from .blank import blank_document, blank_layout
from .errors import (
    DraftNotFound,
    DraftNotPublishable,
    DuplicateTemplateName,
    IncompatibleTemplateStore,
    LabelSizeImmutable,
    LabelTemplateError,
    NoEffectiveDefault,
    RevisionNotFound,
    TemplateNameRequired,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateProtected,
    UnsupportedLabelSize,
)
from .library import (
    EXPLICIT,
    FACTORY_FALLBACK,
    OVERRIDE,
    DefaultChanged,
    DraftSaved,
    LabelTemplateLibrary,
    Publication,
    ResolvedTemplate,
    async_get_library,
    async_release_library,
)
from .publication import PublicationCheck, check_document
from .records import (
    FACTORY,
    FROM_BLANK,
    FROM_FACTORY,
    FROM_NAMED,
    NAMED,
    PUBLISH,
    STORE_SCHEMA,
    STORE_VERSION,
    LibraryState,
    NamedTemplate,
    Provenance,
    TemplateDraft,
    TemplateRef,
    TemplateRevision,
    display_name,
    draft_key,
    normalized_name,
)
from .store import STORAGE_KEY_PREFIX, LabelTemplateStore, storage_key

__all__ = [
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
    "READ_LIBRARY",
    "STORAGE_KEY_PREFIX",
    "STORE_SCHEMA",
    "STORE_VERSION",
    "Actor",
    "DefaultChanged",
    "DraftNotFound",
    "DraftNotPublishable",
    "DraftSaved",
    "DuplicateTemplateName",
    "IncompatibleTemplateStore",
    "LabelSizeImmutable",
    "LabelTemplateError",
    "LabelTemplateLibrary",
    "LabelTemplateStore",
    "LibraryState",
    "NamedTemplate",
    "NoEffectiveDefault",
    "Provenance",
    "Publication",
    "PublicationCheck",
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
