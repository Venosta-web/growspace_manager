"""What the template library refuses, and why -- one type per reason.

Every one of these is a state a correct client can reach, so each says what
happened rather than that something went wrong. They subclass the
integration's own error base, so a service call and a websocket command report
them the same way the rest of Growspace Manager reports a refused write.

Authorization is deliberately *not* here. A non-administrator asking to mutate
the library raises Home Assistant's own `Unauthorized`, because that is not a
label problem: it is the same refusal every privileged command in Home
Assistant makes, and giving it a domain-specific type would invite somebody to
catch it as one.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...exceptions import EntityNotFoundError, GrowspaceError
from ..canonical import Diagnostic


class LabelTemplateError(GrowspaceError):
    """Base error for every Label Template lifecycle refusal."""


class UnsupportedLabelSize(LabelTemplateError):
    """A Label Size that is not in the versioned catalogue was named."""

    def __init__(self, label_size_id: str) -> None:
        """Name the stock nobody ships."""
        self.label_size_id = label_size_id
        super().__init__(f"{label_size_id!r} is not a supported Label Size.")


class TemplateNotFound(EntityNotFoundError):
    """No template of this identity exists in this config entry's library.

    Also what a UUID belonging to *another* config entry produces: one entry's
    library never resolves another's identities, and saying "not found" is the
    whole of that isolation.
    """

    def __init__(self, template_id: str) -> None:
        """Name the identity this library does not hold."""
        self.template_id = template_id
        super().__init__(f"No Label Template {template_id!r} exists here.")


class DraftNotFound(EntityNotFoundError):
    """The administrator has no draft of this template or Label Size."""

    def __init__(self, detail: str) -> None:
        """Say which draft slot is empty."""
        super().__init__(f"No Template Draft exists for {detail}.")


class TemplateProtected(LabelTemplateError):
    """A Factory Template was asked to change.

    Factory Templates follow the installed integration version and belong to
    it. An administrator who wants to change one takes a copy, which is what
    keeps an upgrade from rewriting somebody's label.
    """

    def __init__(self, template_id: str) -> None:
        """Name the shipped template that cannot be written to."""
        self.template_id = template_id
        super().__init__(
            f"Factory Template {template_id!r} is supplied by the integration "
            "and cannot be published to, renamed or deleted. Derive a Named "
            "Template from it instead."
        )


class NoFactoryTemplate(LabelTemplateError):
    """The integration ships no Factory Template for this stock.

    What "replace this layout from the factory" runs into on a Label Size the
    integration has never shipped a design for. Distinct from a stock nothing
    *resolves* for: an administrator here has a perfectly good template and
    asked for a starting point that does not exist, which is a packaging gap
    rather than a broken library -- and never a reason to invent an
    approximate layout to hand them.
    """

    def __init__(self, label_size_id: str) -> None:
        """Name the stock nothing is shipped for."""
        self.label_size_id = label_size_id
        super().__init__(
            f"The integration ships no Factory Template for {label_size_id!r}, "
            "so there is nothing to replace this layout from."
        )


class LabelSizeImmutable(LabelTemplateError):
    """A publication tried to move a template to another stock.

    Converting a design between stocks is a transform, not an edit: the
    millimetres mean something different on different paper. A template's size
    is therefore fixed for its whole life, and a draft that disagrees with its
    base is rejected rather than reinterpreted.
    """

    def __init__(self, *, template_id: str, expected: str, found: str) -> None:
        """Name both stocks, because either one could be the mistake."""
        self.template_id = template_id
        self.expected = expected
        self.found = found
        super().__init__(
            f"Label Template {template_id!r} is for {expected!r}; the draft is "
            f"for {found!r}. A template's Label Size cannot change."
        )


class DuplicateTemplateName(LabelTemplateError):
    """Another template of this Label Size already has this name.

    Compared trimmed and case-insensitively, and only within the size: the
    same name at another stock is a different label, not a collision.
    """

    def __init__(self, *, name: str, label_size_id: str, template_id: str) -> None:
        """Name the conflict and the template that already holds it."""
        self.name = name
        self.label_size_id = label_size_id
        self.template_id = template_id
        super().__init__(
            f"{name!r} is already the name of a Label Template for {label_size_id!r}."
        )


class TemplateNameRequired(LabelTemplateError):
    """An untitled draft was published without a name to publish it under."""

    def __init__(self) -> None:
        """Say what is missing."""
        super().__init__(
            "A Named Template needs a name before it can be published. Set one "
            "on the draft first."
        )


class DraftNotPublishable(LabelTemplateError):
    """The draft's layout does not validate, so there is nothing to publish.

    It carries the diagnostics rather than a summary, because the editor's job
    on receiving this is to select the element each one names -- and the draft
    itself is untouched, which is what lets invalid work keep being work.
    """

    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        """Keep every attributable reason this layout cannot be published."""
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics)
        codes = ", ".join(item.code for item in self.diagnostics) or "no diagnostics"
        super().__init__(f"This Template Draft cannot be published: {codes}.")


class DraftVersionConflict(LabelTemplateError):
    """An autosave was written over a draft version the client had not seen.

    The stored draft is not replaced and the rejected payload is not thrown
    away: it is kept in the draft's recovery slot, and this error carries the
    draft it was kept on, so one answer tells the client both what the server
    holds and that its own work survived.
    """

    def __init__(self, *, expected: int, found: int, draft: object) -> None:
        """Name both versions, and hand back the draft the payload is on."""
        self.expected = expected
        self.found = found
        #: The stored draft, with the rejected payload in its recovery slot.
        self.draft = draft
        super().__init__(
            f"This Template Draft is at version {found}; the save expected "
            f"{expected}. Nothing was overwritten and the rejected payload is "
            "kept for recovery."
        )


class DraftIsStale(LabelTemplateError):
    """The draft was based on a revision that is no longer the head.

    Somebody published while this draft was open. Publishing it anyway would
    silently drop their revision, and the two layouts cannot be merged:
    independent moves, resizes and typography changes are structurally
    mergeable while producing physically unsafe output. So the draft is kept,
    stays previewable, and its owner chooses -- discard and reload, reapply by
    hand, or publish it as a template of its own.
    """

    def __init__(self, *, template_id: str, base_revision: int, head: int) -> None:
        """Name the revision this draft was started from, and the current one."""
        self.template_id = template_id
        self.base_revision = base_revision
        self.head = head
        super().__init__(
            f"This Template Draft is based on revision {base_revision} of Label "
            f"Template {template_id!r}, which is now at revision {head}. It "
            "cannot be published over the newer revision."
        )


class IdempotencyKeyReused(LabelTemplateError):
    """One idempotency key was presented for two different calls.

    A key identifies one intended mutation, so replaying it with the same input
    is a retry and returns the first result. Presenting it with different input
    is a client bug, and performing the second call under the first one's key
    would leave the ledger describing something that never happened.
    """

    def __init__(self, *, key: str, operation: str) -> None:
        """Name the key and what it was already spent on."""
        self.key = key
        self.operation = operation
        super().__init__(
            f"Idempotency key {key!r} has already been used for a different "
            f"{operation} request."
        )


class NoRecoveryPayload(LabelTemplateError):
    """There is no declined work kept beside this draft to act on."""

    def __init__(self, detail: str) -> None:
        """Say which draft has nothing kept beside it."""
        super().__init__(f"No recovery payload is kept for {detail}.")


class NoEffectiveDefault(LabelTemplateError):
    """This Label Size has no selectable template at all.

    Which means the integration shipped no valid Factory Template for it. That
    is a packaging failure, and the honest answer is that template-based
    printing is unavailable for this stock -- never an approximate emergency
    layout invented here.
    """

    def __init__(self, label_size_id: str) -> None:
        """Name the stock nothing resolves for."""
        self.label_size_id = label_size_id
        super().__init__(
            f"No valid Label Template resolves for {label_size_id!r}: the "
            "integration ships no valid Factory Template for this stock."
        )


class IncompatibleTemplateStore(LabelTemplateError):
    """The stored library was written by a newer integration.

    Nothing here downgrades it. The stored document is left byte-for-byte as
    found and this library refuses to operate -- reads included, because a
    best-effort read is how a newer store quietly becomes a lossy older one,
    and half a library answered confidently is worse than no library at all.
    The entry raises a Home Assistant repair issue naming both versions and
    every other Growspace Manager feature carries on; the way out is the newer
    integration or a restore, never a downgrade and never a reset.
    """

    def __init__(self, *, found: int, supported: int) -> None:
        """Name both versions, which is what a repair message needs."""
        self.found = found
        self.supported = supported
        super().__init__(
            f"This Label Template library was written at store version {found}; "
            f"this integration supports {supported}. It has not been modified."
        )


class TemplateNotResolvable(LabelTemplateError):
    """A stored revision no longer validates, so it cannot be rendered.

    Reachable when a catalogue this document references has moved on beneath
    it. The revision is never rewritten or repaired to fit -- default
    resolution steps past it to the valid factory fallback, and naming it
    explicitly says why it cannot be used. A template whose *head* is in this
    state is a Quarantined Template: it stays listed, readable, exportable and
    openable as a draft, and is refused only where using it would mean
    printing it.
    """

    def __init__(
        self,
        *,
        template_id: str,
        revision: int,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> None:
        """Name the revision and keep every reason it no longer validates."""
        self.template_id = template_id
        self.revision = revision
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics)
        codes = ", ".join(item.code for item in self.diagnostics) or "no diagnostics"
        super().__init__(
            f"Revision {revision} of Label Template {template_id!r} no longer "
            f"validates: {codes}."
        )


class RevisionNotFound(EntityNotFoundError):
    """That template has no such revision.

    Distinct from a revision that exists and no longer validates: one is a
    reference to something that was never published, the other is published
    history that the catalogues have moved past, and they call for different
    next steps.
    """

    def __init__(self, *, template_id: str, revision: int) -> None:
        """Name the template and the revision it does not have."""
        self.template_id = template_id
        self.revision = revision
        super().__init__(f"Label Template {template_id!r} has no revision {revision}.")


class TemplateDeleted(LabelTemplateError):
    """That identity is soft-deleted, and is not a template you can use.

    Deliberately not "not found". A deleted template is still here, still
    complete, and still restorable until its tombstone expires -- so the next
    step is to restore it or to stop referring to it, and those are different
    actions from the ones a genuinely unknown identity calls for.
    """

    def __init__(self, *, template_id: str, expires_at: str) -> None:
        """Name the identity and when it stops being recoverable."""
        self.template_id = template_id
        self.expires_at = expires_at
        super().__init__(
            f"Label Template {template_id!r} was deleted and is recoverable "
            f"until {expires_at}. Restore it before using it again."
        )


class TombstoneNotFound(EntityNotFoundError):
    """Nothing was deleted under this identity.

    Which is also the answer for a template that is still here: asking to
    restore something that was never deleted is a question about a deletion,
    and inventing one would be the wrong kind of helpful.
    """

    def __init__(self, template_id: str) -> None:
        """Name the identity no deletion is held for."""
        self.template_id = template_id
        super().__init__(f"No deleted Label Template {template_id!r} is recoverable.")


class TombstoneExpired(LabelTemplateError):
    """The recovery window on this deletion has closed.

    The record may still be sitting in the store waiting to be collected, and
    it is deliberately not restorable anyway: a thirty-day promise that
    quietly held for ninety would be a promise nobody could plan around, and
    an administrator who reads the expiry date is entitled to it.
    """

    def __init__(self, *, template_id: str, expires_at: str) -> None:
        """Name the identity and the instant it stopped being recoverable."""
        self.template_id = template_id
        self.expires_at = expires_at
        super().__init__(
            f"The deletion of Label Template {template_id!r} expired at "
            f"{expires_at} and can no longer be restored."
        )


class DraftIsOrphaned(LabelTemplateError):
    """The template this draft belongs to has been deleted.

    An orphan is kept, not corrected: its owner may read it, preview it,
    export it, discard it, or publish it under a fresh identity with Save As.
    What it may not do is carry on editing towards a template that is not
    there -- an autosave into an orphan would be work aimed at a revision that
    can never be appended.
    """

    def __init__(self, *, template_id: str) -> None:
        """Name the template this draft is still pointed at."""
        self.template_id = template_id
        super().__init__(
            f"This Template Draft belongs to Label Template {template_id!r}, "
            "which has been deleted. It can be read, previewed, saved as a "
            "new template or discarded, but not edited."
        )


class BundleNotReadable(LabelTemplateError):
    """A portable bundle is not one, or has been damaged in transit.

    Structure and checksum are the same refusal on purpose: both mean the
    bytes offered are not a bundle this integration can vouch for, and neither
    is a reason to import the parts that happen to parse.
    """

    def __init__(self, detail: str) -> None:
        """Say what about the bundle could not be trusted."""
        super().__init__(f"This Label Template bundle cannot be read: {detail}")


class IncompatibleBundle(LabelTemplateError):
    """The bundle was written in a format this integration does not know.

    A newer bundle fails preflight without writing anything and names the
    version that can read it, because the remedy is an upgrade rather than a
    partial import of the fields that happen to be familiar.
    """

    def __init__(self, *, found: int, supported: int) -> None:
        """Name both formats, which is what the remedy is read from."""
        self.found = found
        self.supported = supported
        super().__init__(
            f"This Label Template bundle is at format version {found}; this "
            f"integration reads {supported}. Upgrade Growspace Manager to "
            "import it. Nothing has been changed."
        )


class UnsupportedDependency(LabelTemplateError):
    """An imported template needs something this installation does not have.

    A Label Size, a binding, a font, a spacing or a monochrome token that is
    not in the catalogues here. Never silently dropped and never substituted
    with the nearest thing: a label missing its lineage line is a label that
    prints wrongly without saying so, and the remedy -- the integration or
    version that ships the missing catalogue entry -- is only findable if the
    refusal names it.
    """

    def __init__(self, *, template_id: str, missing: Sequence[str]) -> None:
        """Name the template and every dependency it is missing."""
        self.template_id = template_id
        self.missing: tuple[str, ...] = tuple(missing)
        super().__init__(
            f"Label Template {template_id!r} needs "
            f"{', '.join(self.missing)}, which this installation does not "
            "have. Nothing has been changed."
        )


class ImportCollision(LabelTemplateError):
    """An imported identity already means something else here.

    The same UUID carrying different content is the one thing an import must
    never resolve on its own: whichever side it picked would silently replace
    somebody's design or silently discard the one being imported. The
    administrator says which, by importing that entry as a copy under a fresh
    identity or by leaving it out.
    """

    def __init__(self, *, template_id: str, reason: str) -> None:
        """Name the identity and why it could not be taken as given."""
        self.template_id = template_id
        self.reason = reason
        super().__init__(
            f"Label Template {template_id!r} cannot be imported as itself: "
            f"{reason}. Import it as a copy, or leave it out of the bundle. "
            "Nothing has been changed."
        )


class BackupNotRestorable(LabelTemplateError):
    """A backup document cannot be staged, so nothing is replaced.

    Restore is replacement rather than merge, so everything is validated
    before anything is written: a backup that fails here leaves the library
    exactly as it was, which is the only safe outcome for an operation whose
    success would overwrite all of it.
    """

    def __init__(self, detail: str) -> None:
        """Say what about the backup could not be staged."""
        super().__init__(
            f"This Label Template backup cannot be restored: {detail} "
            "The current library has not been changed."
        )
