"""The full backup: moving a library, not sharing a design.

Where a portable bundle carries current revisions for somebody else to use,
a backup carries **everything one config entry's library is**: every Named
Template with its complete history, every default override, every
administrator's drafts with whatever invalid work is in them, every tombstone
with the recovery window still ticking on it, all of the provenance, the
idempotency ledger and the Library Generation. It is the document a restore
replaces a library with, which is why it holds the things a share deliberately
does not -- a backup that dropped tombstones would silently shorten every
recovery window it was restored over, and one that dropped drafts would throw
away the work nobody had published yet.

**Restore is replacement, never merge.** Two libraries cannot be reconciled:
the same UUID may hold different history on each side, the same name may be
taken by different identities, and a merge would have to pick, silently, for
every one of them. So a restore stages the whole document, validates all of it,
and only then writes once. Anything that fails leaves the library exactly as it
was -- which is the only acceptable outcome for the one operation whose success
overwrites all of somebody's templates.

**The entry ID travels but is not enforced.** A backup records which config
entry it was taken from, because that is worth knowing when there are two; it
does not refuse to be restored into another, because restoring into a fresh
entry after a reinstall is exactly what a backup is for.

Validation here is structural: that every record reads back as itself, that the
dictionaries are keyed by what their records say they are, and that history
really is history. It is deliberately *not* layout validation -- a backup of a
library holding a Quarantined Template must restore that template exactly as it
was, still quarantined, rather than refusing to restore the library it lives in.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..canonical import digest
from .errors import BackupNotRestorable
from .records import STORE_VERSION, LibraryState

#: The backup document's own identity, beside its version. Distinct from a
#: bundle's, because handing one to the wrong operation is exactly the mistake
#: worth catching: importing a backup would resurrect somebody else's drafts,
#: and restoring a bundle would delete everything it does not carry.
BACKUP_SCHEMA = "growspace.label-template-backup"

#: The backup format this integration writes and reads. Separate from the store
#: version it wraps: the envelope may grow a field without the library's own
#: shape moving, and a backup names both so a refusal can say which is too new.
BACKUP_VERSION = 1


def build_backup(entry_id: str, state: LibraryState, *, created_at: str) -> dict:
    """Return the complete backup document for one library."""
    payload: dict[str, Any] = {
        "schema": BACKUP_SCHEMA,
        "version": BACKUP_VERSION,
        "store_version": STORE_VERSION,
        "entry_id": entry_id,
        "created_at": created_at,
        "library": state.as_dict(),
    }
    return {**payload, "checksum": digest(payload)}


def read_backup(value: object) -> LibraryState:
    """Stage one backup into a library state, or refuse the whole of it.

    Every refusal in here happens before a caller has written anything, which
    is the point: by the time this returns a state, the only thing left to do
    is one store write.
    """
    if not isinstance(value, Mapping):
        raise BackupNotRestorable("a backup is a JSON object.")
    if value.get("schema") != BACKUP_SCHEMA:
        raise BackupNotRestorable(
            f"its schema is {value.get('schema')!r}, not {BACKUP_SCHEMA!r}."
        )
    found = value.get("version")
    if not isinstance(found, int) or isinstance(found, bool) or found < 1:
        raise BackupNotRestorable(f"{found!r} is not a backup format version.")
    if found > BACKUP_VERSION:
        raise BackupNotRestorable(
            f"it is at backup format version {found} and this integration "
            f"reads {BACKUP_VERSION}, so it was written by a newer Growspace "
            "Manager."
        )
    _verify_checksum(value)

    library = value.get("library")
    if not isinstance(library, Mapping):
        raise BackupNotRestorable("it carries no library document.")
    state = _staged(migrate(dict(library), found))
    _verify_structure(state)
    return state


def migrate(library: dict[str, Any], version: int) -> dict[str, Any]:
    """Lift one backed-up library document to the current format, in memory.

    There is one format, so this is the identity today, and it is a named seam
    for the same reason the bundle's is: one place a future step is added, and
    no place for a version check to be forgotten. The store version *inside*
    the document is a separate number and refuses itself -- a backup this
    envelope understands may still hold a library written by a newer store.
    """
    return library


def _staged(library: Mapping[str, Any]) -> LibraryState:
    """Read the library document, turning any malformed record into a refusal."""
    try:
        return LibraryState.from_dict(library)
    except (KeyError, TypeError, ValueError) as err:
        raise BackupNotRestorable(f"a record in it is malformed ({err}).") from err


def _verify_checksum(value: Mapping[str, Any]) -> None:
    """Refuse a backup whose checksum does not describe what it carries."""
    claimed = value.get("checksum")
    if not isinstance(claimed, str) or not claimed:
        raise BackupNotRestorable("it carries no checksum.")
    payload = {key: item for key, item in value.items() if key != "checksum"}
    if claimed != digest(payload):
        raise BackupNotRestorable(
            "its checksum does not match its contents, so it was damaged or "
            "edited after it was written."
        )


def _verify_structure(state: LibraryState) -> None:
    """Refuse a library whose dictionaries disagree with their own records.

    Cheap, and it catches the one class of damage a checksum cannot: a backup
    assembled by hand, or by a tool that meant well. A draft filed under
    another draft's slot would quietly break the one-draft-per-administrator
    rule the slot *is*, and a template filed under the wrong UUID would be a
    template nothing could ever resolve.
    """
    for key, template in state.templates.items():
        if key != template.id:
            raise BackupNotRestorable(
                f"template {template.id!r} is filed under {key!r}."
            )
        if not template.revisions:
            raise BackupNotRestorable(f"template {key!r} has no revisions.")
        numbers = [revision.revision for revision in template.revisions]
        if numbers != sorted(numbers) or len(set(numbers)) != len(numbers):
            raise BackupNotRestorable(
                f"the history of template {key!r} is not in order."
            )
    for key, draft in state.drafts.items():
        if key != draft.key:
            raise BackupNotRestorable(f"a draft of {draft.owner!r} is in slot {key!r}.")
    for key, stone in state.tombstones.items():
        if key != stone.id:
            raise BackupNotRestorable(
                f"the deletion of template {stone.id!r} is filed under {key!r}."
            )
        if key in state.templates:
            raise BackupNotRestorable(f"template {key!r} is both live and deleted.")
    if state.generation < 0:
        raise BackupNotRestorable("its Library Generation is negative.")
