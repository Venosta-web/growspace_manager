"""Templates the library keeps but will not print.

A saved revision can stop validating without anybody touching it. The
catalogues move: a Label Size is retired, a binding is withdrawn, a style token
is renamed. The document that referenced them is still exactly the bytes its
author saved, and it is still a perfectly good record of what they wanted -- it
has simply stopped being something this integration can compile.

**Nothing is repaired.** A quarantined template is not clamped, re-pointed,
stripped of the element that stopped resolving or migrated to a neighbouring
size. It is kept as found and excluded from the two things that would print it:
resolution and default selection. Everything else an administrator might need
stays open -- it is listed, its history is readable, it can be exported, it can
be opened as a draft and repaired element by element, and an older revision of
it can be restored past the broken head.

Quarantine is therefore **computed, never stored**. It is a fact about a
document and today's catalogues together, so writing it onto the template would
mean a flag that goes stale the moment an upgrade brings the missing catalogue
entry back -- and a template that stayed quarantined after the reason for it
had gone would need a repair nobody would think to run.

The gate is the Publication Gate, unchanged: what could not be published today
cannot be printed today either. Holding quarantine to a *different* standard
than publication is how a library ends up with templates it will save but not
print, or print but not save.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..canonical import Diagnostic
from .publication import check_document
from .records import NamedTemplate


@dataclass(frozen=True, slots=True)
class Quarantine:
    """Why one template's head cannot be compiled, kept for its administrator.

    It carries the diagnostics rather than a summary for the same reason a
    refused publication does: repairing this means selecting the elements they
    name, and a count would send somebody looking for them by eye.
    """

    template_id: str
    revision: int
    diagnostics: tuple[Diagnostic, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the quarantine's wire form."""
        return {
            "template_id": self.template_id,
            "revision": self.revision,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def quarantine_of(template: NamedTemplate) -> Quarantine | None:
    """Return why this template's head cannot be printed, or nothing.

    Only the head. An older revision that has stopped validating is history,
    and history is preserved and readable rather than a reason to withdraw a
    template that resolves perfectly well today; a restore is what asks whether
    one of those can be made the head again.
    """
    head = template.head
    check = check_document(head.document)
    if check.publishable:
        return None
    return Quarantine(
        template_id=template.id,
        revision=head.revision,
        diagnostics=check.diagnostics,
    )
