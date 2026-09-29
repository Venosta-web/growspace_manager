"""Grow Run lifecycle over the WebSocket API (#668, #671).

**Every refusal is a result**, as with the Label Template drafts. A card
starting a Run has to tell "someone else started one" from "you may not" from
"the history is unreadable" and act differently on each, and each refusal
carries the Growspace's current Run Revision and Active Run so it can: a stale
command is answered with where the ledger really is, never with a bare error.

**Starting in the past** (#670) is two commands: ``preview_grow_run_start``
shows what a start on an earlier day would claim -- Participants, facts, days,
uncovered gaps and any conflicting boundary -- and ``start_grow_run`` with the
same ``started_on`` commits it.

**Finalizing** (#673) is two commands as well: ``preview_grow_run_finalization``
shows the Run Finalization Snapshot a Completed Run would freeze and what it
lacks, and ``finalize_grow_run`` freezes it, acknowledging an incomplete one.
``list_grow_runs`` names every Run a Growspace's ledger holds, and
``update_grow_run_metadata`` edits a Run's description in any status. None of
the four asks whether the Growspace still exists: its history outlives it.

**Comparing** (#675) is ``compare_grow_runs``: exactly two Finalized Runs of
one Growspace, the newest and its predecessor unless the grower names two. It
answers with every Finalized Run as well, so the Grow Run View fills both of
its pickers from the one read.

**Correcting** (#917): ``reopen_grow_run`` returns a Finalized Run to Completed
for an administrator who says why, and ``discard_grow_run`` removes an Active
Run that recorded nothing. A discard refused for the Run's activity names each
kind in the refusal's ``reasons``.
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
    WARNING_ATTRIBUTION_GAPS,
    WARNING_INCOMPLETE_SNAPSHOT,
    WARNING_MISSING_OUTCOMES,
    WARNING_PLANTS_PRESENT,
    DiscardedRun,
    GrowRunRefused,
    RunMetadata,
    compare_runs,
    finalized_runs,
    run_details,
    run_summary,
)
from custom_components.growspace_manager.services.grow_runs import (
    KEEP_NOTE,
    async_complete_grow_run,
    async_discard_grow_run,
    async_finalize_grow_run,
    async_preview_grow_run_finalization,
    async_preview_grow_run_start,
    async_reopen_grow_run,
    async_start_grow_run,
    async_update_grow_run_metadata,
    preview_grow_run_completion,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from ._common import WS_MSG_USER, WSCommand

WS_TYPE_START_GROW_RUN = "growspace_manager/start_grow_run"
WS_TYPE_GET_GROW_RUN = "growspace_manager/get_grow_run"
WS_TYPE_PREVIEW_GROW_RUN_COMPLETION = "growspace_manager/preview_grow_run_completion"
WS_TYPE_COMPLETE_GROW_RUN = "growspace_manager/complete_grow_run"
WS_TYPE_PREVIEW_GROW_RUN_START = "growspace_manager/preview_grow_run_start"
WS_TYPE_LIST_GROW_RUNS = "growspace_manager/list_grow_runs"
WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION = (
    "growspace_manager/preview_grow_run_finalization"
)
WS_TYPE_FINALIZE_GROW_RUN = "growspace_manager/finalize_grow_run"
WS_TYPE_UPDATE_GROW_RUN_METADATA = "growspace_manager/update_grow_run_metadata"
WS_TYPE_COMPARE_GROW_RUNS = "growspace_manager/compare_grow_runs"
WS_TYPE_REOPEN_GROW_RUN = "growspace_manager/reopen_grow_run"
WS_TYPE_DISCARD_GROW_RUN = "growspace_manager/discard_grow_run"

OUTCOME_STARTED = "started"
OUTCOME_REFUSED = "refused"
OUTCOME_PREVIEW = "preview"
OUTCOME_COMPLETED = "completed"
OUTCOME_LISTED = "listed"
OUTCOME_FINALIZED = "finalized"
OUTCOME_UPDATED = "updated"
OUTCOME_COMPARED = "compared"
OUTCOME_REOPENED = "reopened"
OUTCOME_DISCARDED = "discarded"

_NOTE = vol.Any(None, vol.All(str, vol.Length(max=MAX_TEXT_LENGTH)))

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


SCHEMA_WS_PREVIEW_GROW_RUN_COMPLETION = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_PREVIEW_GROW_RUN_COMPLETION,
            vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
            vol.Optional("retrospective_note"): _NOTE,
        }
    )
)

SCHEMA_WS_COMPLETE_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_COMPLETE_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        vol.Required("acknowledged_warnings"): [
            vol.In(
                [
                    WARNING_PLANTS_PRESENT,
                    WARNING_MISSING_OUTCOMES,
                    WARNING_ATTRIBUTION_GAPS,
                ]
            )
        ],
        vol.Optional("retrospective_note"): _NOTE,
    }
)


SCHEMA_WS_LIST_GROW_RUNS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_LIST_GROW_RUNS,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
    }
)

SCHEMA_WS_PREVIEW_GROW_RUN_FINALIZATION = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
            vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
            vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        }
    )
)

SCHEMA_WS_FINALIZE_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_FINALIZE_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        vol.Required("acknowledged_warnings"): [vol.In([WARNING_INCOMPLETE_SNAPSHOT])],
    }
)

SCHEMA_WS_UPDATE_GROW_RUN_METADATA = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_GROW_RUN_METADATA,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        vol.Optional("label"): vol.Any(
            None, vol.All(str, vol.Length(max=MAX_LABEL_LENGTH))
        ),
        vol.Optional("tags"): vol.All(
            [vol.All(str, vol.Length(max=MAX_TAG_LENGTH))], vol.Length(max=MAX_TAGS)
        ),
        vol.Optional("goals"): _NOTE,
        vol.Optional("notes"): _NOTE,
    }
)

SCHEMA_WS_COMPARE_GROW_RUNS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_COMPARE_GROW_RUNS,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Optional("run_ids"): vol.All(
            [vol.All(str, vol.Length(min=1))], vol.Length(min=2, max=2)
        ),
    }
)

SCHEMA_WS_REOPEN_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_REOPEN_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        # Blank is a refusal with a code, not a schema error, so the card can
        # say what is missing in the grower's own language.
        vol.Required("reason"): vol.All(str, vol.Length(max=MAX_TEXT_LENGTH)),
    }
)

SCHEMA_WS_DISCARD_GROW_RUN = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_DISCARD_GROW_RUN,
        vol.Required("growspace_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("run_id"): vol.All(str, vol.Length(min=1)),
        vol.Required("expected_run_revision"): vol.All(int, vol.Range(min=0)),
        vol.Optional("reason"): _NOTE,
    }
)

_METADATA_FIELDS = ("label", "tags", "goals", "notes")


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
            "reasons": list(refused.reasons),
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


async def websocket_preview_grow_run_completion(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Show what completing the Active Run now would do, or why it cannot."""
    try:
        preview = preview_grow_run_completion(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            retrospective_note=msg.get("retrospective_note", KEEP_NOTE),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {"outcome": OUTCOME_PREVIEW, "preview": preview.as_dict()}


async def websocket_complete_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Complete the Active Run, or say why not and where the ledger stands."""
    try:
        run, revision = await async_complete_grow_run(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            run_id=msg["run_id"],
            expected_revision=msg["expected_run_revision"],
            acknowledged=msg["acknowledged_warnings"],
            retrospective_note=msg.get("retrospective_note", KEEP_NOTE),
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_COMPLETED,
        "run_revision": revision,
        "run": run_summary(run, revision),
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


async def websocket_list_grow_runs(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Name every Run the Growspace's ledger holds, newest first."""
    try:
        ledger = coordinator.grow_runs.ledger(msg["growspace_id"])
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_LISTED,
        "run_revision": ledger.revision,
        "runs": [
            run_summary(run, ledger.revision)
            for run in sorted(ledger.runs, key=lambda row: -row.sequence_number)
        ],
    }


async def websocket_preview_grow_run_finalization(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Show the snapshot finalizing a Completed Run would freeze, or why not."""
    try:
        preview = await async_preview_grow_run_finalization(
            coordinator, growspace_id=msg["growspace_id"], run_id=msg["run_id"]
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {"outcome": OUTCOME_PREVIEW, "preview": preview.as_dict()}


async def websocket_finalize_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Freeze a Completed Run, or say why not and where the ledger stands."""
    try:
        run, revision = await async_finalize_grow_run(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            run_id=msg["run_id"],
            expected_revision=msg["expected_run_revision"],
            acknowledged=msg["acknowledged_warnings"],
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    assert run.snapshot is not None
    return {
        "outcome": OUTCOME_FINALIZED,
        "run_revision": revision,
        "run": run_summary(run, revision),
        "snapshot": run.snapshot.as_dict(),
    }


async def websocket_update_grow_run_metadata(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Edit a Run's description, or say why not and where the ledger stands."""
    try:
        run, revision = await async_update_grow_run_metadata(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            run_id=msg["run_id"],
            expected_revision=msg["expected_run_revision"],
            changes={key: msg[key] for key in _METADATA_FIELDS if key in msg},
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_UPDATED,
        "run_revision": revision,
        "run": run_summary(run, revision),
    }


async def websocket_compare_grow_runs(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Set two Finalized Runs side by side, or say why they cannot be."""
    try:
        ledger = coordinator.grow_runs.ledger(msg["growspace_id"])
        run_ids = msg.get("run_ids")
        comparison = compare_runs(
            ledger, None if run_ids is None else (run_ids[0], run_ids[1])
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_COMPARED,
        "run_revision": ledger.revision,
        "finalized": [
            run_summary(run, ledger.revision) for run in finalized_runs(ledger)
        ],
        "comparison": comparison.as_dict(),
    }


async def websocket_reopen_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Reopen a Finalized Run, or say why not and where the ledger stands."""
    try:
        run, revision = await async_reopen_grow_run(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            run_id=msg["run_id"],
            expected_revision=msg["expected_run_revision"],
            reason=msg["reason"],
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return {
        "outcome": OUTCOME_REOPENED,
        "run_revision": revision,
        "run": run_summary(run, revision),
    }


async def websocket_discard_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Discard an activity-free Active Run, or say what it recorded."""
    try:
        discarded, revision = await async_discard_grow_run(
            hass,
            coordinator,
            growspace_id=msg["growspace_id"],
            run_id=msg["run_id"],
            expected_revision=msg["expected_run_revision"],
            reason=msg.get("reason"),
            user=msg.get(WS_MSG_USER),
        )
    except GrowRunRefused as refused:
        return refusal_result(refused)
    return discard_result(discarded, revision)


def discard_result(discarded: DiscardedRun, revision: int) -> dict[str, Any]:
    """The wire form of a committed discard: which Run left, at which revision."""
    return {
        "outcome": OUTCOME_DISCARDED,
        "run_revision": revision,
        "run_id": discarded.run_id,
        "sequence_number": discarded.sequence_number,
    }


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
    WSCommand(
        WS_TYPE_PREVIEW_GROW_RUN_COMPLETION,
        websocket_preview_grow_run_completion,
        SCHEMA_WS_PREVIEW_GROW_RUN_COMPLETION,
    ),
    WSCommand(
        WS_TYPE_COMPLETE_GROW_RUN,
        websocket_complete_grow_run,
        SCHEMA_WS_COMPLETE_GROW_RUN,
        actor=True,
    ),
    WSCommand(
        WS_TYPE_LIST_GROW_RUNS,
        websocket_list_grow_runs,
        SCHEMA_WS_LIST_GROW_RUNS,
    ),
    WSCommand(
        WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
        websocket_preview_grow_run_finalization,
        SCHEMA_WS_PREVIEW_GROW_RUN_FINALIZATION,
    ),
    WSCommand(
        WS_TYPE_FINALIZE_GROW_RUN,
        websocket_finalize_grow_run,
        SCHEMA_WS_FINALIZE_GROW_RUN,
        actor=True,
    ),
    WSCommand(
        WS_TYPE_UPDATE_GROW_RUN_METADATA,
        websocket_update_grow_run_metadata,
        SCHEMA_WS_UPDATE_GROW_RUN_METADATA,
        actor=True,
    ),
    WSCommand(
        WS_TYPE_COMPARE_GROW_RUNS,
        websocket_compare_grow_runs,
        SCHEMA_WS_COMPARE_GROW_RUNS,
    ),
    WSCommand(
        WS_TYPE_REOPEN_GROW_RUN,
        websocket_reopen_grow_run,
        SCHEMA_WS_REOPEN_GROW_RUN,
        actor=True,
    ),
    WSCommand(
        WS_TYPE_DISCARD_GROW_RUN,
        websocket_discard_grow_run,
        SCHEMA_WS_DISCARD_GROW_RUN,
        actor=True,
    ),
]
