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

**Starting in the past** (#670). A start may name an earlier local day. It
then claims the Growspace's Unattributed Activity from that day on: the plan
the grower previewed is recomputed under the same locks the commit holds, a
conflicting boundary refuses it, and the claimed facts leave the ledger in
the write that gives them to the Run.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.auth.permissions.const import POLICY_CONTROL
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import homeassistant.util.dt as dt_util

from ..const import DOMAIN
from ..domain.grow_run import (
    BaselineState,
    GrowRun,
    OpeningBaseline,
    RunMetadata,
    RunNotAuthorized,
)
from ..domain.unattributed_activity import ClaimPlan, claim_preview, plan_claim
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
    hass: HomeAssistant, growspace_id: str, user: User | None
) -> str:
    """Return the acting user's ID if they may operate this Growspace's Runs."""
    if user is None:
        raise RunNotAuthorized(
            "Starting a Grow Run requires a signed-in Home Assistant user",
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
            "Starting a Grow Run requires permission to control this growspace",
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


def _plants_in(coordinator: GrowspaceCoordinator, growspace_id: str) -> list[str]:
    return sorted(
        plant.plant_id
        for plant in coordinator.plants.values()
        if plant.growspace_id == growspace_id
    )


def _plan(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    started_on: date,
) -> ClaimPlan:
    store = coordinator.grow_runs
    return plan_claim(
        store.ledger(growspace_id),
        store.unattributed(growspace_id),
        started_on=started_on,
        now=dt_util.utcnow(),
        timezone=hass.config.time_zone,
        retention_days=store.retention_days,
        plant_ids=_plants_in(coordinator, growspace_id),
    )


async def async_preview_grow_run_start(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    started_on: date,
) -> dict[str, Any]:
    """What starting on ``started_on`` would claim; nothing is written.

    Raises `RunStoreUnreadable` while the history cannot be read.
    """
    if growspace_id not in coordinator.growspaces:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
    async with coordinator.lock:
        await coordinator.async_project_activity()
        plan = _plan(hass, coordinator, growspace_id, started_on)
    names = {
        plant.plant_id: plant.strain
        for plant in coordinator.plants.values()
        if plant.strain
    }
    return claim_preview(
        plan,
        revision=coordinator.grow_runs.ledger(growspace_id).revision,
        names=names,
    )


async def async_start_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    expected_revision: int,
    metadata: RunMetadata,
    user: User | None,
    started_on: date | None = None,
) -> tuple[GrowRun, int]:
    """Start a Run; return it and the Growspace's new Run Revision.

    With ``started_on`` the Run starts at that local day's midnight and
    claims the Unattributed Activity since. Raises a `GrowRunRefused` for
    every refusal the caller can act on.
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
    async with coordinator.lock:
        # Every fact already committed must be in the ledger before it is
        # claimed; a pending one would otherwise miss the reconstruction.
        if started_on is not None:
            await coordinator.async_project_activity()
        async with store.lock:
            ledger = store.ledger(growspace_id)
            activity = store.unattributed(growspace_id)
            plan = None
            if started_on is not None:
                ledger.require_revision(expected_revision)
                plan = _plan(hass, coordinator, growspace_id, started_on)
                if plan.conflict is not None:
                    raise plan.conflict
            ledger, run = ledger.start(
                expected_revision=expected_revision,
                run_id=uuid4().hex,
                command_id=uuid4().hex,
                now=dt_util.utcnow(),
                timezone=hass.config.time_zone,
                metadata=metadata,
                baseline=opening_baseline(hass, coordinator, growspace_id),
                plant_ids=_plants_in(coordinator, growspace_id),
                actor_user_id=user_id,
                claim=None if plan is None else plan.history,
            )
            remaining = activity.close() if plan is None else plan.remaining(activity)
            await store.async_commit(ledger, activities=(remaining,))
    store.announce_start(run, user_id)
    coordinator.async_update_listeners()
    return run, ledger.revision
