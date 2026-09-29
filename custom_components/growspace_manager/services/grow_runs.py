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
that commit; nothing is completed in the past. The Growspace's Unattributed
Activity coverage opens at that boundary in the same write.

**Starting in the past** (#670). A start may name an earlier local day. It
then claims the Growspace's Unattributed Activity from that day on: the plan
the grower previewed is recomputed under the same locks the commit holds, a
conflicting boundary refuses it, and the claimed facts leave the ledger in
the write that gives them to the Run.

**What a finalization freezes** (#673). Every committed movement, harvest
outcome and Participant identity is copied into the Runs first, under the
Plant lock, so the snapshot is drawn from the Plants' last state; from then on
it is read from the Run alone. Neither finalizing nor describing a Run needs
its Growspace to still exist: that is what makes the history outlive it.

**Correcting and backing out** (#917). Reopening a Finalized Run is an
administrator's command, never a controller's: it is the one lifecycle command
that makes frozen history editable again, so Home Assistant's own
administrator flag is asked, not entity control. Discarding an Active Run that
recorded nothing is a controller's, because it is only the undo of a start.
It projects every committed movement and harvest outcome first, under the
Plant lock, so a fact still on its way to the Run counts as activity rather
than being orphaned by the discard.
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
    CompletionPreview,
    DiscardedRun,
    FinalizationPreview,
    GrowRun,
    OpeningBaseline,
    PresentPlant,
    RunMetadata,
    RunNotAuthorized,
    preview_completion,
    preview_finalization,
)
from ..domain.unattributed_activity import ClaimPlan, claim_preview, plan_claim
from ..exceptions import GrowspaceNotFoundError
from .safety import managed_outputs

if TYPE_CHECKING:
    from homeassistant.auth.models import User

    from ..coordinator import GrowspaceCoordinator
    from ..grow_run_store import GrowRunStore

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


def require_admin(user: User | None, action: str) -> str:
    """Return the acting user's ID if they are a Home Assistant administrator."""
    if user is None or not user.is_admin:
        raise RunNotAuthorized(
            f"{action} a Grow Run requires a Home Assistant administrator",
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
    user_id = _authorize(hass, store, growspace_id, user, "Starting")
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
                prior_coverage=activity.covered_since,
            )
            remaining = activity.close() if plan is None else plan.remaining(activity)
            await store.async_commit(ledger, activities=(remaining,))
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
    user_id = _authorize(hass, store, growspace_id, user, "Completing")
    # The plant lock first, so no Plant can move across the boundary between
    # the preview being read and the Run being committed. Movements already
    # committed are projected first, so the boundary closes what they opened,
    # and harvest outcomes are copied in so the preview judges the latest ones.
    async with coordinator.lock:
        await coordinator.async_project_activity()
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
            # The Growspace is Run-free from the boundary on, so its
            # Unattributed Activity coverage opens there, in the same write:
            # a later backdated start finds no gap between the two Runs.
            coverage = store.unattributed(growspace_id).observe(
                preview.completed_at,
                hass.config.time_zone,
                [plant.plant_id for plant in preview.plants_present],
            )
            await store.async_commit(ledger, activities=(coverage,))
    store.announce(run)
    coordinator.async_update_listeners()
    return run, ledger.revision


def _authorize(
    hass: HomeAssistant,
    store: GrowRunStore,
    growspace_id: str,
    user: User | None,
    action: str,
    *,
    admin: bool = False,
) -> str:
    """Return the acting user's ID, or refuse with where the ledger stands."""
    try:
        if admin:
            return require_admin(user, action)
        return require_controller(hass, growspace_id, user, action)
    except RunNotAuthorized as refused:
        ledger = store.ledger(growspace_id)
        refused.current_revision = ledger.revision
        refused.active_run = ledger.active_run
        raise


def _growspace_name(coordinator: GrowspaceCoordinator, growspace_id: str) -> str:
    """The Growspace's name now, or its ID once the Growspace is gone."""
    growspace = coordinator.growspaces.get(growspace_id)
    return growspace.name if growspace is not None else growspace_id


async def async_preview_grow_run_finalization(
    coordinator: GrowspaceCoordinator, *, growspace_id: str, run_id: str
) -> FinalizationPreview:
    """What finalizing a Completed Run now would freeze; nothing of it is written.

    The Plants' committed state is copied into the Runs first, exactly as a
    finalization does, so the preview shows the snapshot that would land.
    """
    async with coordinator.lock:
        await coordinator.async_project_activity()
        await coordinator.async_project_harvest_outcomes()
        return preview_finalization(
            coordinator.grow_runs.ledger(growspace_id),
            run_id,
            now=dt_util.utcnow(),
            growspace_name=_growspace_name(coordinator, growspace_id),
        )


async def async_finalize_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    run_id: str,
    expected_revision: int,
    acknowledged: list[str],
    user: User | None,
) -> tuple[GrowRun, int]:
    """Freeze a Completed Run; return it and the Growspace's new Run Revision.

    Raises a `GrowRunRefused` for every refusal the caller can act on.
    """
    store = coordinator.grow_runs
    user_id = _authorize(hass, store, growspace_id, user, "Finalizing")
    async with coordinator.lock:
        await coordinator.async_project_activity()
        await coordinator.async_project_harvest_outcomes()
        async with store.lock:
            ledger = store.ledger(growspace_id)
            ledger.require_revision(expected_revision)
            preview = preview_finalization(
                ledger,
                run_id,
                now=dt_util.utcnow(),
                growspace_name=_growspace_name(coordinator, growspace_id),
            )
            ledger, run = ledger.finalize(
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


async def async_update_grow_run_metadata(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    run_id: str,
    expected_revision: int,
    changes: dict[str, Any],
    user: User | None,
) -> tuple[GrowRun, int]:
    """Edit a Run's label, tags, goals or notes; a field not named is kept.

    Raises a `GrowRunRefused` for every refusal the caller can act on.
    """
    store = coordinator.grow_runs
    user_id = _authorize(hass, store, growspace_id, user, "Describing")
    async with store.lock:
        ledger = store.ledger(growspace_id)
        ledger.require_revision(expected_revision)
        current = ledger.find(run_id).metadata
        metadata = RunMetadata.create(
            label=changes.get("label", current.label),
            tags=changes.get("tags", current.tags),
            goals=changes.get("goals", current.goals),
            notes=changes.get("notes", current.notes),
        )
        updated, run = ledger.update_metadata(
            expected_revision=expected_revision,
            run_id=run_id,
            metadata=metadata,
            command_id=uuid4().hex,
            actor_user_id=user_id,
            now=dt_util.utcnow(),
        )
        if updated is ledger:
            return run, ledger.revision
        await store.async_commit(updated)
    store.announce(run)
    coordinator.async_update_listeners()
    return run, updated.revision


async def async_reopen_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    run_id: str,
    expected_revision: int,
    reason: str,
    user: User | None,
) -> tuple[GrowRun, int]:
    """Return a Finalized Run to Completed; return it and the new Run Revision.

    Nothing about the Run's boundaries moves. From here on its outcomes and
    Participant identities follow the Plants again, exactly as before its
    first finalization, until it is finalized once more.

    Raises a `GrowRunRefused` for every refusal the caller can act on.
    """
    store = coordinator.grow_runs
    user_id = _authorize(hass, store, growspace_id, user, "Reopening", admin=True)
    async with store.lock:
        ledger, run = store.ledger(growspace_id).reopen(
            expected_revision=expected_revision,
            run_id=run_id,
            reason=reason,
            command_id=uuid4().hex,
            actor_user_id=user_id,
            now=dt_util.utcnow(),
        )
        await store.async_commit(ledger)
    store.announce(run)
    coordinator.async_update_listeners()
    return run, ledger.revision


async def async_discard_grow_run(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    *,
    growspace_id: str,
    run_id: str,
    expected_revision: int,
    reason: str | None,
    user: User | None,
) -> tuple[DiscardedRun, int]:
    """Remove an activity-free Active Run; return its record and the new revision.

    The Growspace's Unattributed Activity coverage resumes in the same write,
    from where the start ended it. Raises a `GrowRunRefused` for every refusal
    the caller can act on, including `RunHasActivity` with its reasons.
    """
    store = coordinator.grow_runs
    user_id = _authorize(hass, store, growspace_id, user, "Discarding")
    now = dt_util.utcnow()
    # The plant lock first, as for a completion: no Plant may move into the
    # Run between its activity being judged and the Run being removed.
    async with coordinator.lock:
        await coordinator.async_project_activity()
        await coordinator.async_project_harvest_outcomes()
        async with store.lock:
            ledger = store.ledger(growspace_id)
            ledger.require_revision(expected_revision)
            run = ledger.find(run_id)
            updated, discarded = ledger.discard(
                expected_revision=expected_revision,
                run_id=run_id,
                reason=reason,
                command_id=uuid4().hex,
                actor_user_id=user_id,
                now=now,
                pending_facts=coordinator.storage_manager.activity_facts,
                harvest_source_plant_ids=[
                    plant.plant_id
                    for plant in coordinator.plants.values()
                    if plant.harvest_source_run_id == run_id
                ],
            )
            coverage = (
                store.unattributed(growspace_id)
                .restore(run)
                .observe(
                    now, hass.config.time_zone, _plants_in(coordinator, growspace_id)
                )
            )
            await store.async_commit(updated, activities=(coverage,))
    store.announce_discard(growspace_id, discarded)
    coordinator.async_update_listeners()
    return discarded, updated.revision
