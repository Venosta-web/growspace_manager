"""Grow Run lifecycle commands: the shell around `domain/grow_run.py` (#668).

**Who may start a Run.** Run Lifecycle Authorization lets a *Growspace
controller* start, complete and finalize, and keeps reopen, void, correction
and purge for administrators. Home Assistant's own permission for "may operate
this" is entity control, so a Growspace controller is a user who may control
the Growspace's Active Run Sensor: every ordinary user, every administrator,
and not a read-only user. It is asked on every command, never remembered.

**What a start captures.** The Plants standing in the Growspace become Run
Participants from the start boundary, and the Run Opening Baseline records
this Growspace's condition sensors and every output Growspace Manager
commands, as they read at that moment.

**What a completion decides on** (#671). The Run Completion Preview is built
from the same reads twice: once for the grower, and again under the locks at
commit, so the warnings a completion must acknowledge and the irrigation that
refuses it are the ones true at the boundary. The boundary is the moment of
that commit; nothing is completed in the past.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import homeassistant.util.dt as dt_util

from ..const import DOMAIN
from ..domain.grow_run import (
    BaselineState,
    CompletionPreview,
    GrowRun,
    OpeningBaseline,
    PresentPlant,
    RunMetadata,
    RunNotAuthorized,
    preview_completion,
)
from ..exceptions import GrowspaceNotFoundError
from .safety import managed_outputs

if TYPE_CHECKING:
    from homeassistant.auth.models import User

    from ..coordinator import GrowspaceCoordinator

ACTIVE_RUN_KEY = "active_run"


def active_run_unique_id(growspace_id: str) -> str:
    """The Active Run Sensor's unique ID for one Growspace."""
    return f"{DOMAIN}_{growspace_id}_{ACTIVE_RUN_KEY}"


def require_controller(
    hass: HomeAssistant,
    growspace_id: str,
    user: User | None,
    action: str = "Starting",
) -> str:
    """Return the acting user's ID if they may operate this Growspace's Runs."""
    if user is None:
        raise RunNotAuthorized(
            f"{action} a Grow Run requires a signed-in Home Assistant user",
            current_revision=None,
        )
    if user.is_admin:
        return user.id
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.SENSOR, DOMAIN, active_run_unique_id(growspace_id)
    )
    allowed = (
        user.permissions.check_entity(entity_id, POLICY_CONTROL)
        if entity_id
        else user.permissions.access_all_entities(POLICY_CONTROL)
    )
    if not allowed:
        raise RunNotAuthorized(
            f"{action} a Grow Run requires permission to control this growspace",
            current_revision=None,
        )
    return user.id


def opening_baseline(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, growspace_id: str
) -> OpeningBaseline:
    """Read this Growspace's conditions and outputs as they stand now."""
    prefix = f"{DOMAIN}_{growspace_id}_"
    conditions = sorted(
        (
            entry.entity_id,
            entry.unique_id.removeprefix(prefix),
        )
        for entry in er.async_get(hass).entities.values()
        if entry.platform == DOMAIN
        and entry.domain == Platform.BINARY_SENSOR
        and entry.unique_id.startswith(prefix)
    )

    def read(entity_id: str) -> str:
        state = hass.states.get(entity_id)
        return state.state if state is not None else "unavailable"

    return OpeningBaseline(
        conditions=tuple(
            BaselineState(entity_id, key, read(entity_id))
            for entity_id, key in conditions
        ),
        equipment=tuple(
            BaselineState(entity_id, entity_id.split(".", 1)[0], read(entity_id))
            for entity_id in managed_outputs(coordinator.growspaces[growspace_id])
        ),
    )


async def async_start_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    expected_revision: int,
    metadata: RunMetadata,
    user: User | None,
) -> tuple[GrowRun, int]:
    """Start a Run; return it and the Growspace's new Run Revision.

    Raises a `GrowRunRefused` for every refusal the caller can act on.
    """
    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
    store = coordinator.grow_runs
    try:
        user_id = require_controller(hass, growspace_id, user)
    except RunNotAuthorized as refused:
        ledger = store.ledger(growspace_id)
        refused.current_revision = ledger.revision
        refused.active_run = ledger.active_run
        raise
    # The plant lock first, so no Plant can move across the start boundary
    # between being counted and the Run being committed.
    async with coordinator.lock, store.lock:
        ledger, run = store.ledger(growspace_id).start(
            expected_revision=expected_revision,
            run_id=uuid4().hex,
            command_id=uuid4().hex,
            now=dt_util.utcnow(),
            timezone=hass.config.time_zone,
            metadata=metadata,
            baseline=opening_baseline(hass, coordinator, growspace_id),
            plant_ids=sorted(
                plant.plant_id
                for plant in coordinator.plants.values()
                if plant.growspace_id == growspace_id
            ),
            actor_user_id=user_id,
        )
        await store.async_commit(ledger)
    store.announce(run)
    coordinator.async_update_listeners()
    return run, ledger.revision


#: A completion that leaves the retrospective note as it is.
KEEP_NOTE = object()


def _completion_preview(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    retrospective_note: str | None | object,
) -> CompletionPreview:
    """Read what completing the Growspace's Active Run now would do and risk."""
    ledger = coordinator.grow_runs.ledger(growspace_id)
    active = ledger.active_run
    return preview_completion(
        ledger,
        now=dt_util.utcnow(),
        plants_present=[
            PresentPlant(
                plant.plant_id,
                plant.genetics.strain_name,
                plant.genetics.phenotype_name,
                str(plant.stage),
            )
            for plant in coordinator.plants.values()
            if plant.growspace_id == growspace_id
        ],
        pending_facts=coordinator.storage_manager.activity_facts,
        delivering_outputs=coordinator.irrigation_delivering_outputs(growspace_id),
        retrospective_note=(
            (active.metadata.notes if active is not None else None)
            if retrospective_note is KEEP_NOTE
            else retrospective_note  # type: ignore[arg-type]
        ),
    )


def preview_grow_run_completion(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    retrospective_note: str | None | object = KEEP_NOTE,
) -> CompletionPreview:
    """The Run Completion Preview for the Growspace's Active Run, as of now.

    Raises a `GrowRunRefused` when there is no Active Run or no readable
    history, so the caller can say which.
    """
    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
    return _completion_preview(hass, coordinator, growspace_id, retrospective_note)


async def async_complete_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    run_id: str,
    expected_revision: int,
    acknowledged: list[str],
    retrospective_note: str | None | object = KEEP_NOTE,
    user: User | None,
) -> tuple[GrowRun, int]:
    """Complete the Active Run; return it and the Growspace's new Run Revision.

    Raises a `GrowRunRefused` for every refusal the caller can act on.
    """
    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
    store = coordinator.grow_runs
    try:
        user_id = require_controller(hass, growspace_id, user, "Completing")
    except RunNotAuthorized as refused:
        ledger = store.ledger(growspace_id)
        refused.current_revision = ledger.revision
        refused.active_run = ledger.active_run
        raise
    # The plant lock first, so no Plant can move across the boundary between
    # the preview being read and the Run being committed. Movements already
    # committed are projected first, so the boundary closes what they opened,
    # and harvest outcomes are copied in so the preview judges the latest ones.
    async with coordinator.lock:
        await coordinator.async_project_pending_activity()
        await coordinator.async_project_harvest_outcomes()
        async with store.lock:
            # A stale command is answered as stale, whatever the preview says.
            store.ledger(growspace_id).require_revision(expected_revision)
            preview = _completion_preview(
                hass, coordinator, growspace_id, retrospective_note
            )
            ledger, run = store.ledger(growspace_id).complete(
                expected_revision=expected_revision,
                run_id=run_id,
                preview=preview,
                acknowledged=acknowledged,
                command_id=uuid4().hex,
                actor_user_id=user_id,
            )
            await store.async_commit(ledger)
    store.announce(run)
    coordinator.async_update_listeners()
    return run, ledger.revision
