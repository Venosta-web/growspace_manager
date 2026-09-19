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
    found and this library refuses to operate, because a best-effort read is
    how a newer store quietly becomes a lossy older one. Raising the Home
    Assistant repair issue and running read-only alongside it belongs to the
    recovery route.
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
    explicitly says why it cannot be used. Preserving it as a Quarantined
    Template, with everything an administrator needs to repair or replace it,
    belongs to the recovery route.
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
