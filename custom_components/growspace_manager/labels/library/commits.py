"""Idempotency keys: making a client's retry safe without doing it twice.

Every mutation of this library may carry a key. The key is the client's, minted
once per intended action and presented again on every retry of it, and the
library remembers the keys it has committed. So a call whose answer was lost --
a websocket that dropped, a timeout on a slow store write, a browser reloaded
mid-publish -- can be repeated, and the repeat finds the first attempt rather
than publishing a second revision or advancing the Library Generation again.

Three rules, and the whole module is them.

**A record is a locator, never a result.** It says which draft slot, which
template and revision, or which Label Size the committed call touched, and a
replay is answered by re-reading the library there. The ledger therefore cannot
describe a state the library is not in, and it never holds a second copy of
somebody's document -- which matters, because the ledger is persisted and a
draft payload is the largest thing here.

**A key belongs to the actor that spent it.** Keys are opaque client strings,
so another administrator presenting the same one gets the answer they would get
for a key nobody has used. A replay is a question about your own call.

**Same key, different call, is refused.** Replaying with identical input is a
retry. Presenting a spent key with different input is a client bug, and the one
thing that must not happen is performing the second call under the first one's
identity.

The digest is taken over the call's own arguments, including a draft payload
that may be anything at all, so it is written against `repr` for values JSON
cannot carry rather than refusing to hash an autosave the library would have
accepted.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from homeassistant.util import dt as dt_util

from .errors import IdempotencyKeyReused
from .records import CommitRecord, LibraryState

#: The operations a key can be spent on. Recorded on the record so a key
#: presented for a different kind of call is refused as loudly as one presented
#: for the same kind with different arguments.
CREATE_DRAFT = "create_draft"
AUTOSAVE_DRAFT = "autosave_draft"
DISCARD_DRAFT = "discard_draft"
RELOAD_DRAFT = "reload_draft"
DISCARD_RECOVERY = "discard_recovery"
PUBLISH_DRAFT = "publish_draft"
SET_DEFAULT = "set_default"
CLEAR_DEFAULT = "clear_default"
RENAME_TEMPLATE = "rename_template"
DUPLICATE_TEMPLATE = "duplicate_template"
SAVE_AS_TEMPLATE = "save_as_template"
REPLACE_FROM_FACTORY = "replace_from_factory"
RESTORE_REVISION = "restore_revision"
DELETE_TEMPLATE = "delete_template"
RESTORE_TEMPLATE = "restore_template"
COLLECT_TOMBSTONES = "collect_tombstones"
IMPORT_TEMPLATES = "import_templates"
RESTORE_BACKUP = "restore_backup"


def request_digest(operation: str, owner: str, **arguments: Any) -> str:
    """Return a stable digest of one call, arguments and all."""
    payload = json.dumps(
        {"operation": operation, "owner": owner, "arguments": arguments},
        sort_keys=True,
        default=repr,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def committed(
    state: LibraryState,
    *,
    key: str | None,
    operation: str,
    owner: str,
    digest: str,
) -> CommitRecord | None:
    """Return this key's committed record, refusing a key spent on something else.

    `None` means there is nothing to replay and the call should proceed -- which
    is also the answer for a caller that passed no key at all, and for a key
    another administrator happens to hold.
    """
    if key is None:
        return None
    record = state.commit_record(key)
    if record is None or record.owner != owner:
        return None
    if record.operation != operation or record.request != digest:
        raise IdempotencyKeyReused(key=key, operation=record.operation)
    return record


def record_of(
    *,
    key: str | None,
    operation: str,
    owner: str,
    digest: str,
    generation: int,
    locator: Mapping[str, Any],
) -> CommitRecord | None:
    """Return the record one committed call leaves behind, if it carried a key."""
    if key is None:
        return None
    return CommitRecord(
        key=key,
        owner=owner,
        operation=operation,
        request=digest,
        generation=generation,
        at=dt_util.utcnow().isoformat(),
        locator=dict(locator),
    )
