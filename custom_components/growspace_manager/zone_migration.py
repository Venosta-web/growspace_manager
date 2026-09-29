"""Say which growspaces have irrigation held on invalid stored zones (ADR-0063).

The version 2 store moved every growspace into its implicit Irrigation Zone.
A growspace whose stored zones fail the integrity check is held under the
latched ``zone_migration_invalid`` fault — its irrigation only; its plants,
climate and everything else carry on — and this Repairs issue says which one,
why, and where the Pre-Migration Copy is. Unlike a pump fault nothing is
acknowledged: the cause is the stored data, so the hold and the issue both
clear on the first load that finds it valid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN, STORAGE_KEY_CONFIG
from .domain.irrigation_zone import ZONE_MIGRATION_INVALID

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

# Where the untouched version 1 document was kept, relative to the config dir.
PRE_MIGRATION_COPY = f".storage/{STORAGE_KEY_CONFIG}.v1"


@callback
def evaluate_zone_migration_issues(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Raise an issue for each growspace whose zones are invalid; clear the rest."""
    problems = coordinator.storage_manager.zone_problems
    for growspace_id, growspace in coordinator.growspaces.items():
        issue_id = f"{ZONE_MIGRATION_INVALID}_{growspace_id}"
        if found := problems.get(growspace_id):
            async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=False,
                severity=IssueSeverity.ERROR,
                translation_key=ZONE_MIGRATION_INVALID,
                translation_placeholders={
                    "growspace": growspace.name,
                    "problems": "; ".join(found),
                    "copy": PRE_MIGRATION_COPY,
                },
            )
        else:
            async_delete_issue(hass, DOMAIN, issue_id)
