"""How a client finds out somebody else changed the library.

One event, fired on the Home Assistant bus every time a library mutation
commits. Only an authenticated Home Assistant client can subscribe to that bus,
which is the whole of "authenticated change event": there is no second channel
to secure and no payload a signed-out browser can reach.

What it carries is deliberately thin -- the new Library Generation, the one it
replaced, the kind of operation, and the identities it touched. Never the
document. A client that treated the event as the state would be building its
own second source of truth out of messages it might have missed; the event says
*that* something changed and what to ask about, and the authoritative answer is
a snapshot.

`previous_generation` is what makes a gap detectable. A client holding
generation N can apply an event whose previous is N, and knows it missed
something when it is anything else -- a dropped connection, a resubscribe, a
Home Assistant restart -- and refreshes the whole snapshot rather than guessing
what it did not see.

Draft autosaves fire nothing. A draft is one administrator's private,
unpublished work, so announcing every keystroke would make every other client
refresh for something none of them can read -- the same reason a draft does not
advance the Library Generation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from ...const import DOMAIN

if TYPE_CHECKING:  # pragma: no cover
    from homeassistant.core import HomeAssistant

#: Fired once per committed Label Template library mutation.
EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED = f"{DOMAIN}_label_template_library_changed"

#: The kinds of change the event names. Every management operation that
#: appends a revision has its own, because a client deciding whether to warn
#: somebody that their open editor has been overtaken wants to know whether the
#: layout moved or only the name did.
#:
#: Replacing a draft from the factory is deliberately not here. It changes one
#: administrator's private draft and no saved state, so it advances no
#: generation and announces nothing -- the same rule autosave follows.
PUBLISHED = "published"
RENAMED = "renamed"
DUPLICATED = "duplicated"
SAVED_AS = "saved_as"
RESTORED = "restored"
DEFAULT_SET = "default_set"
DEFAULT_CLEARED = "default_cleared"


class LibraryChangedEventPayload(TypedDict):
    """What one library change announces about itself."""

    entry_id: str
    generation: int
    previous_generation: int
    operation: str
    template_id: str | None
    revision: int | None
    label_size_id: str | None


def async_fire_library_changed(
    hass: HomeAssistant,
    *,
    entry_id: str,
    generation: int,
    previous_generation: int,
    operation: str,
    template_id: str | None = None,
    revision: int | None = None,
    label_size_id: str | None = None,
) -> None:
    """Announce one committed mutation, after it has landed.

    Called from the commit path with the generation the store really returned,
    so nothing is announced that a failed write left unwritten.
    """
    data: LibraryChangedEventPayload = {
        "entry_id": entry_id,
        "generation": generation,
        "previous_generation": previous_generation,
        "operation": operation,
        "template_id": template_id,
        "revision": revision,
        "label_size_id": label_size_id,
    }
    hass.bus.async_fire(EVENT_LABEL_TEMPLATE_LIBRARY_CHANGED, data)
