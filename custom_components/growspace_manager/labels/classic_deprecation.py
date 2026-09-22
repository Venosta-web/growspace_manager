"""Telling the person who still prints Classic labels that the service goes.

A log warning reaches whoever reads the log, and the Classic `print_label`
caller is usually somebody who does not: a released card on a tablet, or an
automation written a year ago. So the first Classic call in a Home Assistant
run also raises a Repairs issue naming the removal release and the migration
guide, with the replacement for each kind of caller.

**Once per run, from the registry itself.** The issue is created non-persistent,
and Home Assistant restores a non-persistent issue *inactive* at the next
start. So "is the issue active?" is exactly "has a Classic call been made this
run?", and it is the only place that remembers: later calls find it active and
do nothing, and an integration reload -- which re-registers the service but
does not restart Home Assistant -- still finds it. The log warning rides the
same predicate, so the two can never disagree about which call was first.

**It clears by itself.** A run without a Classic call never re-raises it, so the
issue is gone after the first full run in which nothing printed through the
Classic service -- the card was upgraded, the automations were switched. That
is the lifecycle, and it is deliberately not a fix flow: there is nothing Home
Assistant could change on the caller's behalf. Home Assistant's own *Ignore*
still works as it does for every issue; it is remembered until Home Assistant's
version changes, which is Home Assistant's rule, not this integration's.

Printing is never affected. The issue is raised before the request is handed to
the Compatibility Adapter and nothing here can refuse it.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

#: The release that removes the Classic `print_label` request. Announced, so
#: it is a promise to automation authors and must not move silently.
PRINT_LABEL_REMOVAL_VERSION = "2.0.0"
PRINT_LABEL_MIGRATION_URL = (
    "https://github.com/Venosta-web/growspace_manager/blob/main/"
    "docs/deprecations/print-label.md"
)

#: The Repairs issue's identity. One per Home Assistant, not per entry: the
#: service is registered once for the whole domain.
ISSUE_ID = "print_label_deprecated"

#: The `strings.json` key the message is localized from.
TRANSLATION_KEY = "print_label_deprecated"


@callback
def async_note_classic_call(hass: HomeAssistant) -> None:
    """Warn about the Classic request, once per Home Assistant run."""
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)
    if issue is not None and issue.active:
        return
    _LOGGER.warning(
        "The growspace_manager.print_label service is deprecated and will "
        "be removed in Growspace Manager %s. See %s for what replaces it",
        PRINT_LABEL_REMOVAL_VERSION,
        PRINT_LABEL_MIGRATION_URL,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ID,
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        learn_more_url=PRINT_LABEL_MIGRATION_URL,
        translation_key=TRANSLATION_KEY,
        translation_placeholders={
            "removal_version": PRINT_LABEL_REMOVAL_VERSION,
            "migration_url": PRINT_LABEL_MIGRATION_URL,
        },
    )
