"""Grow Run lifecycle over the WebSocket API (#668).

**Every refusal is a result**, as with the Label Template drafts. A card
starting a Run has to tell "someone else started one" from "you may not" from
"the history is unreadable" and act differently on each, and each refusal
carries the Growspace's current Run Revision and Active Run so it can: a stale
command is answered with where the ledger really is, never with a bare error.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.grow_run import (
    MAX_LABEL_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    MAX_TEXT_LENGTH,
    GrowRunRefused,
    RunMetadata,
    run_summary,
)
from custom_components.growspace_manager.services.grow_runs import async_start_grow_run
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WS_MSG_USER, WSCommand

WS_TYPE_START_GROW_RUN = "growspace_manager/start_grow_run"

OUTCOME_STARTED = "started"
OUTCOME_REFUSED = "refused"

SCHEMA_WS_START_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_START_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        vol.Optional("label"): vol.Any(
            None, vol.All(str, vol.Length(max=MAX_LABEL_LENGTH))
        ),
        vol.Optional("tags"): vol.All(
            [vol.All(str, vol.Length(max=MAX_TAG_LENGTH))], vol.Length(max=MAX_TAGS)
        ),
        vol.Optional("goals"): vol.Any(
            None, vol.All(str, vol.Length(max=MAX_TEXT_LENGTH))
        ),
    }
)


def refusal_result(refused: GrowRunRefused) -> dict[str, Any]:
    """Shape one refusal with the ledger position it was refused against."""
    active = refused.active_run
    return {
        "outcome": OUTCOME_REFUSED,
        "refusal": {
            "code": refused.code,
            "message": str(refused),
            "current_revision": refused.current_revision,
            "active_run": (
                run_summary(active, refused.current_revision)
                if active is not None and refused.current_revision is not None
                else None
            ),
        },
    }


async def websocket_start_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Start the Growspace's Active Run, or say why not and where it stands."""
    metadata = RunMetadata.create(
        label=msg.get("label"), tags=msg.get("tags", ()), goals=msg.get("goals")
    )
    try:
        run, revision = await async_start_grow_run(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            expected_revision=msg["expected_run_revision"],
            metadata=metadata,
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_STARTED,
        "run_revision": revision,
        "active_run": run_summary(run, revision),
    }


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_START_GROW_RUN,
        websocket_start_grow_run,
        SCHEMA_WS_START_GROW_RUN,
        actor=True,
    ),
]
