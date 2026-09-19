"""What publication checks, and -- just as deliberately -- what it does not.

Publication is the moment a draft stops being somebody's work in progress and
becomes a revision that other people's labels resolve to. The gate is therefore
the **document layer**, in full: the closed schema, the 0.01 mm quantum,
identity and paint order, supported rotation, and the required text element
bound to `strain.name` -- inside a frame that really fits the stock, because a
required element placed off the paper is not printable however present it is.

The profile-relative layers are **not** in the gate, and that is a decision
rather than an omission. A Capability Profile is chosen per render: the same
saved revision is meant to print on a printer nobody has bought yet, which is
the whole reason a layout holds millimetres and no DPI. Judging ink coverage,
safe areas or glyph legibility at publication would pin a template to today's
one profile, and would refuse to save a perfectly good 50x50 design for the
sole reason that no 50x50 profile has shipped. Those judgements belong to the
render and print operations, where a profile exists and the answer is about
that printer.

So: the document layer needs no printer, no fonts and no profile, and an error
it finds is an error nobody has to reproduce on hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..canonical import (
    Diagnostic,
    DocumentValidation,
    LabelLayout,
    Operation,
    has_blocking,
    validate_document,
)


@dataclass(frozen=True, slots=True)
class PublicationCheck:
    """Whether one candidate document may be published, and why not."""

    layout: LabelLayout | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def publishable(self) -> bool:
        """Whether this document is eligible to become an immutable revision.

        A warning does not block. The document layer raises errors for what
        cannot be saved and warnings for what can be saved but deserves
        looking at, and collapsing the two would make a template unsavable for
        a reason the editor could not clear.
        """
        return self.layout is not None and not has_blocking(self.diagnostics)

    def as_dict(self) -> dict[str, Any]:
        """Return the check's wire form, in the eligibility vocabulary."""
        return {
            "operation": str(Operation.PUBLISH),
            "allowed": self.publishable,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def check_document(document: object) -> PublicationCheck:
    """Validate one candidate document the way publication validates it."""
    validation: DocumentValidation = validate_document(document)
    return PublicationCheck(
        layout=validation.layout, diagnostics=tuple(validation.diagnostics)
    )
