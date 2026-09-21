"""The batch seam: preflight, print, watch, and retry the failed labels.

The domain has held all of this since the batch work landed
(`labels.batch`); what was missing was the wire, and the decisions below are
about the shape of that wire.

**The preflight is held, and printing names it.** A batch captures one instant
for every record, and that instant is part of every raster identity, so a
second request could never reproduce what the operator reviewed. The whole
:class:`BatchPreflight` -- snapshots, rasters, attempt plan, calibration --
stays on this side under an ID. A print presents that ID and, when the review
had warnings, the preflight identity it consented to. Nothing a client sends
can stand in for the reviewed batch.

**Consent is refused before anything starts.** Hard errors and a missing or
foreign acknowledgement are answered by `print_label_batch` itself, as a
refusal with a recovery, rather than as a job that failed a moment later.

**Printing is a job, and the card watches it.** A batch waits on a printer
once per label, so `print_label_batch` answers as soon as the job is started
and `get_label_batch_job` reports each attempt as it lands -- pending, printed
or failed, in the copy-major plan order the preflight showed.

**Retry is the failed attempts, and nothing else.** `retry_label_batch` names
a finished job; it sends only that job's failed attempts, in their original
order, from the same held preflight. Printing the whole batch again is a new
preflight, never a retry.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.approvals import (
    BATCH_PREFLIGHT,
    ApprovalHolder,
)
from custom_components.growspace_manager.labels.batch import (
    BatchPreflight,
    BatchRefused,
    async_preflight_batch,
    async_print_batch,
    async_retry_failed_batch,
    authorize_batch,
)
from custom_components.growspace_manager.labels.batch_jobs import (
    BATCH_JOB,
    BatchJob,
    JobState,
    batch_job_holder,
    running_job_for,
    start_batch_job,
)
from custom_components.growspace_manager.labels.calibration import (
    IncompatibleCalibrationStore,
)
from custom_components.growspace_manager.labels.canonical import (
    SUPPORTED_LOCALES,
    select_profile,
)
from custom_components.growspace_manager.labels.library import (
    RevisionNotFound,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateRef,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from ._common import WSCommand
from .drafts import (
    CODE_UNSUPPORTED_LOCALE,
    RECOVERY_NONE,
    _actor,
    _base_schema,
    _gate,
    _library,
    _ok,
    _refused,
)
from .label_printing import (
    CODE_APPROVAL_EXPIRED,
    CODE_TEMPLATE_NOT_FOUND,
    CODE_TEMPLATE_NOT_RESOLVABLE,
    CODE_UNKNOWN_SUBJECT,
    RECOVERY_CHOOSE_SUBJECT,
    RECOVERY_CHOOSE_TEMPLATE,
    RECOVERY_PREFLIGHT_AGAIN,
    _holder,
    _ledger,
    _not_authorized,
    _print_refused,
    _printer_required,
    _source_of,
    _unknown_profile,
    _unreadable_store,
    recovery_for,
)

WS_TYPE_PREFLIGHT_LABEL_BATCH = f"{DOMAIN}/preflight_label_batch"
WS_TYPE_PRINT_LABEL_BATCH = f"{DOMAIN}/print_label_batch"
WS_TYPE_GET_LABEL_BATCH_JOB = f"{DOMAIN}/get_label_batch_job"
WS_TYPE_RETRY_LABEL_BATCH = f"{DOMAIN}/retry_label_batch"

CODE_BATCH_RUNNING = "label_template.batch_running"
CODE_NOTHING_TO_RETRY = "label_template.nothing_to_retry"

RECOVERY_WAIT = "wait"

#: The most labels one preflight may plan. A batch is rendered in full before
#: anything prints and held in memory until it lapses; this keeps one request
#: from holding hundreds of rasters. Copies are bounded for the same reason.
MAX_BATCH_RECORDS = 100
MAX_BATCH_COPIES = 10

SCHEMA_WS_PREFLIGHT_LABEL_BATCH = _base_schema(WS_TYPE_PREFLIGHT_LABEL_BATCH).extend(
    {
        vol.Required("template"): vol.Schema(
            {
                vol.Required("kind"): str,
                vol.Required("id"): str,
                vol.Optional("revision"): vol.Any(None, int),
            }
        ),
        vol.Required("plant_ids"): vol.All(
            [str], vol.Length(min=1, max=MAX_BATCH_RECORDS)
        ),
        vol.Optional("copies", default=1): vol.All(
            int, vol.Range(min=1, max=MAX_BATCH_COPIES)
        ),
        vol.Optional("profile_id"): vol.Any(None, str),
        vol.Required("device_id"): str,
        vol.Optional("locale", default=SUPPORTED_LOCALES[0]): str,
        vol.Optional("density", default="normal"): str,
    }
)

SCHEMA_WS_PRINT_LABEL_BATCH = _base_schema(WS_TYPE_PRINT_LABEL_BATCH).extend(
    {
        vol.Required("preflight_id"): str,
        vol.Optional("acknowledgement"): vol.Any(None, str),
    }
)

SCHEMA_WS_GET_LABEL_BATCH_JOB = _base_schema(WS_TYPE_GET_LABEL_BATCH_JOB).extend(
    {vol.Required("job_id"): str}
)

SCHEMA_WS_RETRY_LABEL_BATCH = _base_schema(WS_TYPE_RETRY_LABEL_BATCH).extend(
    {
        vol.Required("job_id"): str,
        vol.Optional("acknowledgement"): vol.Any(None, str),
    }
)


def _preflight_expired() -> dict[str, Any]:
    return _refused(
        CODE_APPROVAL_EXPIRED,
        "That batch review is no longer held. Preflight the batch again.",
        RECOVERY_PREFLIGHT_AGAIN,
    )


def _job_expired() -> dict[str, Any]:
    return _refused(
        CODE_APPROVAL_EXPIRED,
        "That batch is no longer held. Preflight it again to print it.",
        RECOVERY_PREFLIGHT_AGAIN,
    )


def _running(job: BatchJob) -> dict[str, Any]:
    return _refused(
        CODE_BATCH_RUNNING,
        "This batch is still printing. Wait for it to finish.",
        RECOVERY_WAIT,
        job_id=job.id,
    )


def _jobs(hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> ApprovalHolder:
    return batch_job_holder(hass, coordinator.config_entry.entry_id)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


async def websocket_preflight_label_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Capture and render every plant in order, and hold the review.

    Answers with the complete preflight -- every record's raster and
    decision, every diagnostic attributed to its record, the copy-major
    attempt plan -- and the ID a print presents. Nothing is sent to the
    printer.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    if not msg["device_id"].strip():
        return _printer_required()
    locale = msg["locale"]
    if locale not in SUPPORTED_LOCALES:
        return _refused(
            CODE_UNSUPPORTED_LOCALE,
            f"{locale} is not a supported print locale",
            RECOVERY_NONE,
            locale=locale,
        )

    wanted = msg["template"]
    ref = TemplateRef(kind=wanted["kind"], id=wanted["id"])
    library = await _library(hass, coordinator)
    try:
        resolved = await library.async_resolve(_actor(msg), ref, wanted.get("revision"))
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    except (TemplateNotFound, RevisionNotFound) as error:
        return _refused(CODE_TEMPLATE_NOT_FOUND, str(error), RECOVERY_CHOOSE_TEMPLATE)
    except TemplateNotResolvable as error:
        return _refused(
            CODE_TEMPLATE_NOT_RESOLVABLE, str(error), RECOVERY_CHOOSE_TEMPLATE
        )

    profile = select_profile(resolved.label_size_id, msg.get("profile_id"))
    if profile is None:
        return _unknown_profile(msg.get("profile_id"), resolved.label_size_id)

    strains = coordinator.services.config.strain_library
    if strains is None:
        return _refused(
            CODE_UNKNOWN_SUBJECT, "The strain library is not loaded.", RECOVERY_NONE
        )

    ledger = await _ledger(hass, coordinator)
    try:
        preflight = await async_preflight_batch(
            hass,
            coordinator,
            strains,
            plant_ids=msg["plant_ids"],
            copies=msg["copies"],
            source=_source_of(resolved),
            profile=profile,
            ledger=ledger,
            actor=_actor(msg),
            device_id=msg["device_id"],
            density=msg["density"],
            locale=locale,
        )
    except IncompatibleCalibrationStore as error:
        return _unreadable_store(error)
    except HomeAssistantError as error:
        # A plant that is gone, or one listed twice: the list is wrong, not
        # the template.
        return _refused(CODE_UNKNOWN_SUBJECT, str(error), RECOVERY_CHOOSE_SUBJECT)

    preflight_id = _holder(hass, coordinator).hold(BATCH_PREFLIGHT, preflight)
    return _ok(
        template=resolved.as_dict(),
        preflight_id=preflight_id,
        recovery=recovery_for(preflight.blocked_by),
        preflight=preflight.as_dict(),
    )


# ---------------------------------------------------------------------------
# Printing, watching, retrying
# ---------------------------------------------------------------------------


async def websocket_print_label_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Start printing the reviewed batch, or say why it may not start."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    preflight_id = msg["preflight_id"]
    preflight: BatchPreflight | None = _holder(hass, coordinator).get(
        preflight_id, BATCH_PREFLIGHT
    )
    if preflight is None:
        return _preflight_expired()

    jobs = _jobs(hass, coordinator)
    if (running := running_job_for(jobs, preflight_id)) is not None:
        return _running(running)

    actor = _actor(msg)
    acknowledgement = msg.get("acknowledgement")
    try:
        actor.authenticated()
        authorize_batch(preflight, acknowledgement=acknowledgement)
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    except BatchRefused as error:
        return _print_refused(error)

    ledger = await _ledger(hass, coordinator)
    job = start_batch_job(
        hass,
        jobs,
        preflight_id=preflight_id,
        preflight=preflight,
        previous=None,
        run=lambda listener: async_print_batch(
            hass,
            preflight=preflight,
            ledger=ledger,
            actor=actor,
            acknowledgement=acknowledgement,
            on_result=listener,
        ),
    )
    return _ok(job=job.as_dict())


async def websocket_get_label_batch_job(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Report every attempt of one job as it stands right now."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    try:
        _actor(msg).authenticated()
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    job: BatchJob | None = _jobs(hass, coordinator).get(msg["job_id"], BATCH_JOB)
    if job is None:
        return _job_expired()
    return _ok(job=job.as_dict())


async def websocket_retry_label_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Print one finished job's failed attempts again, from the same review."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    jobs = _jobs(hass, coordinator)
    previous: BatchJob | None = jobs.get(msg["job_id"], BATCH_JOB)
    if previous is None:
        return _job_expired()
    if (running := running_job_for(jobs, previous.preflight_id)) is not None:
        return _running(running)
    if previous.state is not JobState.FINISHED or not previous.failed:
        return _refused(
            CODE_NOTHING_TO_RETRY,
            "No label in this batch failed, so there is nothing to retry.",
            RECOVERY_NONE,
            job_id=previous.id,
        )

    actor = _actor(msg)
    acknowledgement = msg.get("acknowledgement")
    try:
        actor.authenticated()
        authorize_batch(previous.preflight, acknowledgement=acknowledgement)
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    except BatchRefused as error:
        return _print_refused(error)

    ledger = await _ledger(hass, coordinator)
    result = previous.result()
    job = start_batch_job(
        hass,
        jobs,
        preflight_id=previous.preflight_id,
        preflight=previous.preflight,
        previous=previous,
        run=lambda listener: async_retry_failed_batch(
            hass,
            previous=result,
            ledger=ledger,
            actor=actor,
            acknowledgement=acknowledgement,
            on_result=listener,
        ),
    )
    return _ok(job=job.as_dict())


COMMANDS: list[WSCommand] = [
    WSCommand(command, handler, schema, resolve="any", actor=True)
    for command, handler, schema in (
        (
            WS_TYPE_PREFLIGHT_LABEL_BATCH,
            websocket_preflight_label_batch,
            SCHEMA_WS_PREFLIGHT_LABEL_BATCH,
        ),
        (
            WS_TYPE_PRINT_LABEL_BATCH,
            websocket_print_label_batch,
            SCHEMA_WS_PRINT_LABEL_BATCH,
        ),
        (
            WS_TYPE_GET_LABEL_BATCH_JOB,
            websocket_get_label_batch_job,
            SCHEMA_WS_GET_LABEL_BATCH_JOB,
        ),
        (
            WS_TYPE_RETRY_LABEL_BATCH,
            websocket_retry_label_batch,
            SCHEMA_WS_RETRY_LABEL_BATCH,
        ),
    )
]
