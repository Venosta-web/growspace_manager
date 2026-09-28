"""Grow Run lifecycle over the WebSocket API (#668).

**Every refusal is a result**, as with the Label Template drafts. A card
starting a Run has to tell "someone else started one" from "you may not" from
"the history is unreadable" and act differently on each, and each refusal
carries the Growspace's current Run Revision and Active Run so it can: a stale
command is answered with where the ledger really is, never with a bare error.

**Starting in the past** (#670) is two commands: ``preview_grow_run_start``
shows what a start on an earlier day would claim -- Participants, facts, days,
uncovered gaps and any conflicting boundary -- and ``start_grow_run`` with the
same ``started_on`` commits it.
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
    run_details,
    run_summary,
)
from custom_components.growspace_manager.services.grow_runs import (
    async_preview_grow_run_start,
    async_start_grow_run,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from ._common import WS_MSG_USER, WSCommand

WS_TYPE_START_GROW_RUN = "growspace_manager/start_grow_run"
WS_TYPE_GET_GROW_RUN = "growspace_manager/get_grow_run"
WS_TYPE_PREVIEW_GROW_RUN_START = "growspace_manager/preview_grow_run_start"

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
        vol.Optional("started_on"): cv.date,
    }
)

SCHEMA_WS_PREVIEW_GROW_RUN_START = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_PREVIEW_GROW_RUN_START,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("started_on"): cv.date,
    }
)

SCHEMA_WS_GET_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
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
            started_on=msg.get("started_on"),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_STARTED,
        "run_revision": revision,
        "active_run": run_summary(run, revision),
    }


async def websocket_preview_grow_run_start(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Show what a start on an earlier day would claim; write nothing."""
    try:
        return await async_preview_grow_run_start(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            started_on=msg["started_on"],
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)


async def websocket_get_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Read a selected Run's Participants and durable movement history."""
    ledger = coordinator.grow_runs.ledger(msg["growspace_id"])
    run = next((row for row in ledger.runs if row.run_id == msg["run_id"]), None)
    if run is None:
        return {"outcome": "not_found"}
    return run_details(run, ledger.revision)


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_GET_GROW_RUN,
        websocket_get_grow_run,
        SCHEMA_WS_GET_GROW_RUN,
    ),
    WSCommand(
        WS_TYPE_PREVIEW_GROW_RUN_START,
        websocket_preview_grow_run_start,
        SCHEMA_WS_PREVIEW_GROW_RUN_START,
    ),
    WSCommand(
        WS_TYPE_START_GROW_RUN,
        websocket_start_grow_run,
        SCHEMA_WS_START_GROW_RUN,
        actor=True,
    ),
]
