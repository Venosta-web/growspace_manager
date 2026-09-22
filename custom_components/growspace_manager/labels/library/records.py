"""The records one config entry's template library is made of.

Three identities, kept apart on purpose:

- a **Named Template** has an opaque UUID and belongs permanently to one
  versioned Label Size;
- every publication appends an immutable **Template Revision** numbered
  beneath that UUID; and
- a **Template Draft** is unpublished state owned by one administrator, based
  on one explicit revision or on nothing at all.

Keeping them separate is what lets a name change without the identity moving,
history stay truthful while the head advances, and unfinished work survive a
restart without ever being mistaken for something that was published.

Two more records exist only because more than one client edits this library at
once. A **Recovery Payload** sits beside a draft and holds work the server
declined to make current -- a rejected autosave, or the payload a reload
replaced -- because no arrangement of versions justifies losing what somebody
typed. A **Commit Record** remembers one idempotency key and where what it
committed can be re-read, so a retry of a call whose answer was lost finds the
first attempt instead of performing a second one.

A **Tombstone** is the fifth, and it is the whole of a deleted template: the
record is the `NamedTemplate` itself, set aside with the instant it was deleted
and the instant it stops being recoverable. Deletion moves a template between
two dictionaries rather than destroying anything, which is what lets the same
UUID and the same history come back thirty days later.

A **Tombstone** is the fifth, and it is the whole of a deleted template: the
record *is* the `NamedTemplate`, set aside with the instant it was deleted and
the instant it stops being recoverable. Deletion moves a template between two
dictionaries rather than destroying anything, which is what lets the same UUID
and the same history come back thirty days later instead of an approximation
of them.

A draft's `document` is deliberately **opaque**. It is whatever the editor last
had, valid or not, and this module does not validate it: an autosave that
refused invalid work would make every diagnostic a threat to the draft. The
document becomes a `LabelLayout` at exactly one moment -- publication -- and
nowhere else.

Serialization is written out by hand rather than taken from `asdict`, because
this is the persisted shape of somebody's saved work: a field renamed in a
dataclass must be a deliberate migration, not a silent change to what is on
disk.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .errors import IncompatibleTemplateStore

#: The persisted document's own identity, beside its version. Spelled so a
#: stray `.storage` file can be recognised for what it is.
STORE_SCHEMA = "growspace.label-template-store"

#: The store shape this integration reads and writes. A higher number on disk
#: was written by a newer integration and is refused rather than interpreted.
STORE_VERSION = 1

#: Which kind of template an identity names. A Factory Template's ID is the
#: integration's own namespaced one; a Named Template's is a UUID. The kind is
#: recorded rather than inferred from the shape, so a UUID-shaped factory ID
#: could never be read as somebody's template.
FACTORY = "factory"
NAMED = "named"

#: What a revision or draft was derived from.
FROM_BLANK = "blank"
FROM_FACTORY = "factory"
FROM_NAMED = "named"
FROM_IMPORT = "import"

#: Which act appended a revision. Each is a deliberate thing an administrator
#: did, and a history that recorded them all as "publish" could not tell a
#: restore from the edit it was reaching back past.
#:
#: `PUBLISH` is a draft becoming its template's next revision. `RENAME` carries
#: the previous revision's document forward unchanged under a new name.
#: `DUPLICATE` and `SAVE_AS` open a template of their own at revision 1 -- from
#: a saved head and from the active draft respectively. `RESTORE` copies a
#: historical document forward as a new head, which is the only way back to an
#: old layout: history is appended to and never rewound. `IMPORT` opens a
#: template at revision 1 from a portable bundle, which carries one current
#: revision rather than a history -- so an imported template's first revision
#: says it arrived rather than claiming somebody published it here.
PUBLISH = "publish"
RENAME = "rename"
DUPLICATE = "duplicate"
SAVE_AS = "save_as"
RESTORE = "restore"
IMPORT = "import"

#: Why a payload is sitting in a draft's recovery slot rather than being the
#: draft itself. All three are work the server declined to make current, and an
#: editor says different things about them, so the reason is recorded rather
#: than inferred from which call happened to put it there.
REJECTED_SAVE = "rejected_save"
RELOADED = "reloaded"
REPLACED_FROM_FACTORY = "replaced_from_factory"

#: How many idempotency keys one library remembers. A key exists to make a
#: retry of a call whose answer was lost safe, which is a window of seconds --
#: so this is generous rather than a history. It is capped at all because the
#: ledger is persisted, and an unbounded one would grow with every autosave for
#: the life of the installation.
COMMIT_LEDGER_LIMIT = 64


def normalized_name(name: str) -> str:
    """Return the comparison form of a template name.

    Trimmed and case-folded, because "Clone tags" and "clone tags " are the
    same name to the person reading the label off a shelf. `casefold` rather
    than `lower`: it is the comparison Unicode defines for exactly this.
    """
    return " ".join(name.split()).casefold()


def display_name(name: str) -> str:
    """Return the stored form of a template name: trimmed, otherwise as typed."""
    return " ".join(name.split())


@dataclass(frozen=True, slots=True)
class TemplateRef:
    """A reference to one template, by kind and identity.

    An administrator's default override holds one of these. It names an
    identity and never a display name, so renaming a template cannot move
    anybody's default onto a different design.
    """

    kind: str
    id: str

    def as_dict(self) -> dict[str, Any]:
        """Return the reference's persisted and wire form."""
        return {"kind": self.kind, "id": self.id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TemplateRef:
        """Read one persisted reference."""
        return cls(kind=str(value["kind"]), id=str(value["id"]))

    @classmethod
    def factory(cls, template_id: str) -> TemplateRef:
        """Reference one shipped Factory Template."""
        return cls(kind=FACTORY, id=template_id)

    @classmethod
    def named(cls, template_id: str) -> TemplateRef:
        """Reference one administrator-created Named Template."""
        return cls(kind=NAMED, id=template_id)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a revision's or a draft's content came from.

    Structural rather than descriptive: it records identities, so a restore or
    a migration can say which installed definition a template was derived
    from even after that definition has moved on.
    """

    source: str
    factory_id: str | None = None
    factory_revision: int | None = None
    source_template_id: str | None = None
    source_revision: int | None = None
    #: The draft this revision was published from, and the version of it that
    #: was published. The ID is what makes a replayed publication recognisable
    #: after the draft it consumed has been cleared: a retry finds the revision
    #: its own draft already became instead of a missing draft.
    draft_id: str | None = None
    draft_version: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the provenance's persisted and wire form."""
        return {
            "source": self.source,
            "factory_id": self.factory_id,
            "factory_revision": self.factory_revision,
            "source_template_id": self.source_template_id,
            "source_revision": self.source_revision,
            "draft_id": self.draft_id,
            "draft_version": self.draft_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Provenance:
        """Read one persisted provenance."""
        return cls(
            source=str(value["source"]),
            factory_id=_optional_str(value.get("factory_id")),
            factory_revision=_optional_int(value.get("factory_revision")),
            source_template_id=_optional_str(value.get("source_template_id")),
            source_revision=_optional_int(value.get("source_revision")),
            draft_id=_optional_str(value.get("draft_id")),
            draft_version=_optional_int(value.get("draft_version")),
        )


@dataclass(frozen=True, slots=True)
class TemplateRevision:
    """One immutable published state of a Named Template.

    Immutable after commit means exactly that: nothing in this route rewrites
    one, and the only way the head moves is another revision beside it.
    """

    revision: int
    name: str
    document: Mapping[str, Any]
    digest: str
    published_at: str
    published_by: str | None
    operation: str
    parent_revision: int | None
    provenance: Provenance

    def as_dict(self) -> dict[str, Any]:
        """Return the revision's persisted form."""
        return {
            "revision": self.revision,
            "name": self.name,
            "document": dict(self.document),
            "digest": self.digest,
            "published_at": self.published_at,
            "published_by": self.published_by,
            "operation": self.operation,
            "parent_revision": self.parent_revision,
            "provenance": self.provenance.as_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TemplateRevision:
        """Read one persisted revision."""
        return cls(
            revision=int(value["revision"]),
            name=str(value["name"]),
            document=dict(value["document"]),
            digest=str(value["digest"]),
            published_at=str(value["published_at"]),
            published_by=_optional_str(value.get("published_by")),
            operation=str(value.get("operation", PUBLISH)),
            parent_revision=_optional_int(value.get("parent_revision")),
            provenance=Provenance.from_dict(value["provenance"]),
        )

    def summary(self) -> dict[str, Any]:
        """Return the revision without its document.

        What a library listing carries: a client choosing a template does not
        need every historical layout, and sending them all would make the
        snapshot grow with the history.
        """
        return {
            key: value for key, value in self.as_dict().items() if key != "document"
        }


@dataclass(frozen=True, slots=True)
class NamedTemplate:
    """One administrator-created template, with its complete history."""

    id: str
    label_size_id: str
    created_at: str
    created_by: str | None
    revisions: tuple[TemplateRevision, ...]

    @property
    def head(self) -> TemplateRevision:
        """The current published revision."""
        return self.revisions[-1]

    @property
    def name(self) -> str:
        """The current name, which is the head revision's."""
        return self.head.name

    def revision(self, number: int) -> TemplateRevision | None:
        """Return one historical revision by number, or nothing."""
        for candidate in self.revisions:
            if candidate.revision == number:
                return candidate
        return None

    def with_revision(self, revision: TemplateRevision) -> NamedTemplate:
        """Return this template with one more revision appended."""
        return replace(self, revisions=(*self.revisions, revision))

    def as_dict(self) -> dict[str, Any]:
        """Return the template's persisted form, history included."""
        return {
            "id": self.id,
            "label_size_id": self.label_size_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "revisions": [item.as_dict() for item in self.revisions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NamedTemplate:
        """Read one persisted template."""
        return cls(
            id=str(value["id"]),
            label_size_id=str(value["label_size_id"]),
            created_at=str(value["created_at"]),
            created_by=_optional_str(value.get("created_by")),
            revisions=tuple(
                TemplateRevision.from_dict(item) for item in value["revisions"]
            ),
        )

    def summary(self) -> dict[str, Any]:
        """Return the template's identity and history without any document."""
        return {
            "kind": NAMED,
            "id": self.id,
            "label_size_id": self.label_size_id,
            "name": self.name,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "head_revision": self.head.revision,
            "revisions": [item.summary() for item in self.revisions],
        }


@dataclass(frozen=True, slots=True)
class RecoveryPayload:
    """Editing work the server declined to make the draft, kept beside it.

    Two things put a payload here, and both are the same promise: nothing a
    client sent is thrown away because the server preferred something else. A
    rejected autosave -- a second client writing over a version it has not
    seen -- keeps the payload it was refused, and a reload keeps the payload it
    replaced, which is what "manually reapply my changes" reads from.

    One slot, most recent wins. It is never merged into the document and never
    published from: an editor shows it, copies what it wants out of it, and
    discards it.
    """

    reason: str
    document: Any
    #: The draft version the client believed it was writing over, and the
    #: version the draft really held. Together they are the whole of why this
    #: payload is here rather than being the draft.
    expected_version: int | None
    draft_version: int
    at: str
    name: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the recovery payload's persisted and wire form."""
        return {
            "reason": self.reason,
            "document": self.document,
            "expected_version": self.expected_version,
            "draft_version": self.draft_version,
            "at": self.at,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RecoveryPayload:
        """Read one persisted recovery payload."""
        return cls(
            reason=str(value["reason"]),
            document=value.get("document"),
            expected_version=_optional_int(value.get("expected_version")),
            draft_version=int(value["draft_version"]),
            at=str(value["at"]),
            name=_optional_str(value.get("name")),
        )


@dataclass(frozen=True, slots=True)
class TemplateDraft:
    """One administrator's unpublished editing state.

    Bound either to a template -- the draft that will become its next revision
    -- or to a Label Size alone, which is the untitled draft a new template
    comes from. Both are durable, both may be invalid, and neither is visible
    to another administrator.
    """

    #: Opaque and minted once, so a publication can be recognised as this
    #: draft's own after the draft itself is gone.
    id: str
    owner: str
    label_size_id: str
    version: int
    document: Any
    created_at: str
    modified_at: str
    provenance: Provenance
    template_id: str | None = None
    base_revision: int | None = None
    #: The name an untitled draft will be published under. A template-bound
    #: draft carries none: renaming is its own operation on the template.
    name: str | None = None
    #: The `growspace.label-layout` version the payload was written at, kept
    #: beside the payload so a migration can tell what it is looking at.
    layout_schema_version: int = 1
    #: Work this draft declined to take, kept for its owner to recover from.
    recovery: RecoveryPayload | None = None

    @property
    def key(self) -> str:
        """This draft's slot in the store.

        One active draft per administrator and template, one untitled draft
        per administrator and Label Size. The slot *is* that rule, so there is
        no separate place for it to be enforced or forgotten.
        """
        return draft_key(
            self.owner, template_id=self.template_id, label_size_id=self.label_size_id
        )

    @property
    def is_untitled(self) -> bool:
        """Whether publishing this draft creates a template rather than a revision."""
        return self.template_id is None

    def as_dict(self) -> dict[str, Any]:
        """Return the draft's persisted form, payload and all."""
        return {
            "id": self.id,
            "owner": self.owner,
            "label_size_id": self.label_size_id,
            "template_id": self.template_id,
            "base_revision": self.base_revision,
            "version": self.version,
            "name": self.name,
            "document": self.document,
            "layout_schema_version": self.layout_schema_version,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "provenance": self.provenance.as_dict(),
            "recovery": self.recovery.as_dict() if self.recovery else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TemplateDraft:
        """Read one persisted draft, payload untouched."""
        return cls(
            id=str(value["id"]),
            owner=str(value["owner"]),
            label_size_id=str(value["label_size_id"]),
            template_id=_optional_str(value.get("template_id")),
            base_revision=_optional_int(value.get("base_revision")),
            version=int(value["version"]),
            name=_optional_str(value.get("name")),
            document=value.get("document"),
            layout_schema_version=int(value.get("layout_schema_version", 1)),
            created_at=str(value["created_at"]),
            modified_at=str(value["modified_at"]),
            provenance=Provenance.from_dict(value["provenance"]),
            recovery=(
                RecoveryPayload.from_dict(stored)
                if (stored := value.get("recovery"))
                else None
            ),
        )


#: How long a soft-deleted Named Template stays recoverable. Long enough that
#: somebody who deleted the wrong thing finds out and comes back, short enough
#: that a library is not a graveyard.
TOMBSTONE_DAYS = 30


@dataclass(frozen=True, slots=True)
class Tombstone:
    """One soft-deleted Named Template, kept whole with a clock on it.

    The record *is* the template -- identity, name, every revision and all of
    their provenance -- set aside rather than reduced to a note that something
    used to be here. That is the whole of why restoring returns the same UUID
    and the same history rather than an approximation of them.

    It also remembers whether the deletion cleared a default. Restoring never
    reclaims that selection -- whatever was chosen instead has been printing
    ever since -- but an administrator deciding whether to restore deserves to
    be told that this was the template their labels were coming from.
    """

    template: NamedTemplate
    deleted_at: str
    deleted_by: str | None
    #: The instant after which this is no longer restorable and may be
    #: collected. Stored rather than computed from `deleted_at`, so shortening
    #: the window later cannot retroactively expire somebody's deletion.
    expires_at: str
    was_default: bool = False

    @property
    def id(self) -> str:
        """The identity this tombstone holds, which is the template's own."""
        return self.template.id

    @property
    def label_size_id(self) -> str:
        """The stock the deleted template belonged to."""
        return self.template.label_size_id

    @property
    def name(self) -> str:
        """The name it had when it was deleted."""
        return self.template.name

    def has_expired(self, now: datetime) -> bool:
        """Whether this tombstone's recovery window has already closed."""
        expires = dt_util.parse_datetime(self.expires_at)
        if expires is None:
            raise ValueError(f"{self.expires_at!r} is not a stored instant.")
        return now >= expires

    def as_dict(self) -> dict[str, Any]:
        """Return the tombstone's persisted form, template and all."""
        return {
            "template": self.template.as_dict(),
            "deleted_at": self.deleted_at,
            "deleted_by": self.deleted_by,
            "expires_at": self.expires_at,
            "was_default": self.was_default,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Tombstone:
        """Read one persisted tombstone."""
        return cls(
            template=NamedTemplate.from_dict(value["template"]),
            deleted_at=str(value["deleted_at"]),
            deleted_by=_optional_str(value.get("deleted_by")),
            expires_at=str(value["expires_at"]),
            was_default=bool(value.get("was_default", False)),
        )

    def summary(self) -> dict[str, Any]:
        """Return what an administrator choosing what to restore is shown."""
        return {
            "template": self.template.summary(),
            "deleted_at": self.deleted_at,
            "deleted_by": self.deleted_by,
            "expires_at": self.expires_at,
            "was_default": self.was_default,
        }


def draft_key(owner: str, *, template_id: str | None, label_size_id: str) -> str:
    """Return the store slot one administrator's draft occupies."""
    if template_id is not None:
        return f"{owner}:template:{template_id}"
    return f"{owner}:size:{label_size_id}"


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """One committed mutation, remembered by the idempotency key that made it.

    What it holds is a *locator*, never a result: which draft slot, which
    template and revision, which Label Size. A replay is answered by re-reading
    the library at that locator, so the ledger cannot drift from the state it
    describes and does not carry a second copy of anybody's document.

    The owner is part of the record because a key is a client's private token.
    Another administrator presenting the same string gets the same answer as
    presenting one nobody has used, which is that it has not been used.
    """

    key: str
    owner: str
    operation: str
    #: A digest of the call's own arguments. Replaying a key with identical
    #: input returns the original result; reusing it with different input is a
    #: client bug and is refused rather than silently doing the second thing.
    request: str
    generation: int
    at: str
    locator: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the record's persisted form."""
        return {
            "key": self.key,
            "owner": self.owner,
            "operation": self.operation,
            "request": self.request,
            "generation": self.generation,
            "at": self.at,
            "locator": dict(self.locator),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CommitRecord:
        """Read one persisted record."""
        return cls(
            key=str(value["key"]),
            owner=str(value["owner"]),
            operation=str(value["operation"]),
            request=str(value["request"]),
            generation=int(value["generation"]),
            at=str(value["at"]),
            locator=dict(value.get("locator") or {}),
        )


@dataclass(frozen=True, slots=True)
class LibraryState:
    """The complete committed state of one config entry's library.

    Passed around whole and replaced whole. A mutation composes the next state
    in memory and writes it in one go, so there is no arrangement in which a
    revision lands without its draft being cleared or a default change lands
    without its generation.

    It is also exactly what a full backup holds and what a restore replaces,
    which is why the deleted templates live here beside the live ones: a
    backup that carried no tombstones would quietly shorten every recovery
    window it was restored over.
    """

    generation: int = 0
    templates: Mapping[str, NamedTemplate] = field(default_factory=dict)
    drafts: Mapping[str, TemplateDraft] = field(default_factory=dict)
    defaults: Mapping[str, TemplateRef] = field(default_factory=dict)
    #: Soft-deleted templates, by the identity they still hold. Kept beside
    #: the live ones rather than inside them, so nothing that lists, resolves
    #: or names a template has to remember to exclude the deleted.
    tombstones: Mapping[str, Tombstone] = field(default_factory=dict)
    #: The idempotency keys this library has already committed, oldest first.
    #: Persisted, because the retry a key protects is at its most useful across
    #: exactly the failure that loses an answer -- and a restart is one.
    commits: tuple[CommitRecord, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Return the persisted document this state is saved as."""
        return {
            "schema": STORE_SCHEMA,
            "version": STORE_VERSION,
            "generation": self.generation,
            "templates": {
                key: template.as_dict() for key, template in self.templates.items()
            },
            "drafts": {key: draft.as_dict() for key, draft in self.drafts.items()},
            "defaults": {size: ref.as_dict() for size, ref in self.defaults.items()},
            "tombstones": {
                key: stone.as_dict() for key, stone in self.tombstones.items()
            },
            "commits": [record.as_dict() for record in self.commits],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> LibraryState:
        """Read one persisted library, refusing a newer store outright."""
        if not value:
            return cls()
        found = int(value.get("version", STORE_VERSION))
        if found > STORE_VERSION:
            raise IncompatibleTemplateStore(found=found, supported=STORE_VERSION)
        return cls(
            generation=int(value.get("generation", 0)),
            templates={
                key: NamedTemplate.from_dict(item)
                for key, item in (value.get("templates") or {}).items()
            },
            drafts={
                key: TemplateDraft.from_dict(item)
                for key, item in (value.get("drafts") or {}).items()
            },
            defaults={
                size: TemplateRef.from_dict(item)
                for size, item in (value.get("defaults") or {}).items()
            },
            tombstones={
                key: Tombstone.from_dict(item)
                for key, item in (value.get("tombstones") or {}).items()
            },
            commits=tuple(
                CommitRecord.from_dict(item) for item in (value.get("commits") or ())
            ),
        )

    def commit_record(self, key: str) -> CommitRecord | None:
        """Return what this idempotency key already committed, if anything."""
        for record in reversed(self.commits):
            if record.key == key:
                return record
        return None

    def with_commit(self, record: CommitRecord) -> tuple[CommitRecord, ...]:
        """Return the ledger with one more record on it, oldest evicted.

        A mutation made without a key never reaches here: idempotency is a
        client's protection against its own retry, and a caller that does not
        retry does not have to carry one.
        """
        kept = tuple(item for item in self.commits if item.key != record.key)
        return (*kept, record)[-COMMIT_LEDGER_LIMIT:]

    def name_holder(
        self, name: str, label_size_id: str, *, excluding: str | None = None
    ) -> NamedTemplate | None:
        """Return the template of this size already holding this name, if any."""
        wanted = normalized_name(name)
        for template in self.templates.values():
            if template.id == excluding or template.label_size_id != label_size_id:
                continue
            if normalized_name(template.name) == wanted:
                return template
        return None


def _optional_str(value: object) -> str | None:
    """Read a field that is either a string or genuinely absent."""
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    """Read a field that is either an integer or genuinely absent."""
    if value is None:
        return None
    if not isinstance(value, (int, str)) or isinstance(value, bool):
        raise TypeError(f"{value!r} is not a stored integer.")
    return int(value)
