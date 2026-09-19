"""Telling somebody their template library was written by a newer version.

A store this integration cannot read is not a crash and not a reason to reset
anything. It is a fact about two version numbers, and the person who can act on
it is not looking at the log: they downgraded, or restored a snapshot, or
rolled an update back, and what they see is that their labels stopped working.
So the boundary raises a Home Assistant repair issue naming both versions, and
the rest of Growspace Manager carries on around it.

**Create or clear, from one predicate.** The issue is raised when a load finds
a newer store and deleted when a load succeeds, so it heals itself the moment
the newer integration is reinstalled -- without a second place remembering
whether it was ever raised.

It is deliberately not fixable in the repairs UI. There is no gesture Home
Assistant could offer that would be honest: the only ways out are the version
that wrote the store and a restore from a backup this version can read, and a
"fix" button whose real behaviour was "discard your templates" is exactly the
best-effort downgrade the whole route exists to refuse.

One issue per config entry, because one entry is one library and another
entry's may be perfectly readable.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from ...const import DOMAIN
from .errors import IncompatibleTemplateStore

#: The repair issue's identity, per config entry.
ISSUE_ID_PREFIX = "label_template_store_incompatible_"

#: The `strings.json` key the message is localized from.
TRANSLATION_KEY = "label_template_store_incompatible"


def issue_id(entry_id: str) -> str:
    """Return the repair issue identity for one config entry's library."""
    return f"{ISSUE_ID_PREFIX}{entry_id}"


@callback
def async_raise_store_issue(
    hass: HomeAssistant, entry_id: str, error: IncompatibleTemplateStore
) -> None:
    """Report that this entry's library was written by a newer integration."""
    async_create_issue(
        hass,
        DOMAIN,
        issue_id(entry_id),
        is_fixable=False,
        severity=IssueSeverity.ERROR,
        translation_key=TRANSLATION_KEY,
        translation_placeholders={
            "found": str(error.found),
            "supported": str(error.supported),
        },
    )


@callback
def async_clear_store_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Withdraw the report, because this entry's library reads again."""
    async_delete_issue(hass, DOMAIN, issue_id(entry_id))
