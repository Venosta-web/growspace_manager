"""Preflight, print, and retry one immutable batch of plant labels.

A batch is not a loop around single printing.  It is one operation with one
review boundary: every plant is captured, every distinct label is rendered,
and every refusal and warning is known before the first label reaches paper.
The resulting :class:`BatchPreflight` is the job.  Printing and retry both
consume that object, never a reconstruction of its request, so a plant, strain
row, logo, clock, template or printer setting that changes later cannot alter
a replacement label.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .calibration.ledger import LocalCalibrationLedger, required_dependencies
from .canonical.canonicalization import digest
from .canonical.content import LabelContentSnapshot
from .canonical.diagnostics import Diagnostic, Severity
from .canonical.eligibility import (
    Blocker,
    Operation,
    OperationEligibility,
    PrintProvenance,
    decide_print_request,
)
from .canonical.fonts import FontLibrary
from .canonical.preview import PREVIEW, async_render, font_library_for
from .canonical.profiles import CapabilityProfile
from .canonical.result import RenderResult
from .canonical.subjects import RECORD_SOURCE, async_capture_batch
from .library.actor import Actor
from .printing import LayoutSource, PrintOutcome, PrintRefused, _async_judge_then_print

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.strain_library import StrainLibrary


class AttemptStatus(StrEnum):
    """What happened to one physical label in the immutable attempt plan."""

    PENDING = "pending"
    PRINTED = "printed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BatchDiagnostic:
    """One render diagnostic attributed to its record and stable element."""

    record_index: int
    subject: str
    snapshot_identity: str
    diagnostic: Diagnostic

    def as_dict(self) -> dict[str, Any]:
        """Return the attributable wire form."""
        return {
            "record_index": self.record_index,
            "subject": self.subject,
            "snapshot_identity": self.snapshot_identity,
            "diagnostic": self.diagnostic.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """One captured plant and the authoritative raster preflight produced."""

    index: int
    snapshot: LabelContentSnapshot
    render: RenderResult
    decision: OperationEligibility

    def as_dict(self) -> dict[str, Any]:
        """Return the record, its immutable identity, and its raster."""
        return {
            "index": self.index,
            "subject": self.snapshot.subject,
            "snapshot_identity": self.snapshot.identity,
            "decision": self.decision.as_dict(),
            "render": self.render.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class BatchAttempt:
    """One stable copy-major physical attempt."""

    id: str
    position: int
    record_index: int
    subject: str
    snapshot_identity: str
    copy_index: int

    def as_dict(self) -> dict[str, Any]:
        """Return the plan entry; every preflighted attempt starts pending."""
        return {
            "id": self.id,
            "position": self.position,
            "record_index": self.record_index,
            "subject": self.subject,
            "snapshot_identity": self.snapshot_identity,
            "copy_index": self.copy_index,
            "status": str(AttemptStatus.PENDING),
        }


@dataclass(frozen=True, slots=True)
class BatchPreflight:
    """The complete immutable review boundary for one batch."""

    source: LayoutSource
    profile: CapabilityProfile
    device_id: str
    density: str
    firmware: str | None
    calibration_identity: str | None
    calibration_state: str
    calibration_stale_reasons: tuple[str, ...]
    calibration_warnings: tuple[str, ...]
    records: tuple[BatchRecord, ...]
    attempts: tuple[BatchAttempt, ...]
    diagnostics: tuple[BatchDiagnostic, ...]

    @property
    def allowed(self) -> bool:
        """Whether every record authorizes this batch as a whole."""
        return all(record.decision.allowed for record in self.records)

    @property
    def warnings(self) -> tuple[BatchDiagnostic, ...]:
        """Every record warning, still carrying record and element identity."""
        return tuple(
            item
            for item in self.diagnostics
            if item.diagnostic.severity is Severity.WARNING
        )

    @property
    def acknowledgement_required(self) -> bool:
        """Whether printing requires consent to this exact preflight."""
        return bool(self.warnings or self.calibration_warnings)

    @property
    def blocked_by(self) -> tuple[str, ...]:
        """Every distinct hard refusal, retaining renderer order."""
        found: list[str] = []
        for record in self.records:
            for blocker in record.decision.blocked_by:
                if blocker not in found:
                    found.append(blocker)
        return tuple(found)

    @property
    def identity(self) -> str:
        """Digest every input and outcome warning consent is bound to."""
        return digest(
            {
                "source": {
                    **self.source.as_dict(),
                    "layout_digest": self.source.layout.digest,
                },
                "profile": self.profile.as_dict(),
                "printer": {
                    "device_id": self.device_id,
                    "density": self.density,
                    "firmware": self.firmware,
                    "calibration_identity": self.calibration_identity,
                    "calibration_state": self.calibration_state,
                    "calibration_stale_reasons": self.calibration_stale_reasons,
                    "calibration_warnings": self.calibration_warnings,
                },
                "records": [
                    {
                        "index": record.index,
                        "subject": record.snapshot.subject,
                        "snapshot_identity": record.snapshot.identity,
                        "render_context": record.render.context.as_dict(),
                        "raster_identity": record.render.raster_identity,
                        "raster_input_digest": record.render.raster_input_digest,
                        "decision": record.decision.as_dict(),
                    }
                    for record in self.records
                ],
                "attempts": [attempt.as_dict() for attempt in self.attempts],
                "diagnostics": [item.as_dict() for item in self.diagnostics],
            }
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the complete review surface, rasters included."""
        return {
            "identity": self.identity,
            "allowed": self.allowed,
            "acknowledgement_required": self.acknowledgement_required,
            "blocked_by": list(self.blocked_by),
            "source": self.source.as_dict(),
            "profile": self.profile.as_dict(),
            "printer": {
                "device_id": self.device_id,
                "density": self.density,
                "firmware": self.firmware,
                "calibration_identity": self.calibration_identity,
                "calibration_state": self.calibration_state,
                "calibration_stale_reasons": list(self.calibration_stale_reasons),
                "calibration_warnings": list(self.calibration_warnings),
            },
            "records": [record.as_dict() for record in self.records],
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class BatchAttemptResult:
    """The result of one original attempt, successful or otherwise."""

    attempt: BatchAttempt
    status: AttemptStatus
    outcome: PrintOutcome | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return one result without losing its original plan identity."""
        return {
            **self.attempt.as_dict(),
            "status": str(self.status),
            "error": self.error,
            "outcome": self.outcome.as_dict() if self.outcome else None,
        }


@dataclass(frozen=True, slots=True)
class BatchPrintResult:
    """The latest outcome of every attempt in one preflighted job."""

    preflight: BatchPreflight
    attempts: tuple[BatchAttemptResult, ...]
    attempted_ids: tuple[str, ...]

    @property
    def failed(self) -> tuple[BatchAttemptResult, ...]:
        """Attempts eligible for failed-only retry, in original order."""
        return tuple(
            item for item in self.attempts if item.status is AttemptStatus.FAILED
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the job result and every attempt's explicit state."""
        return {
            "preflight_identity": self.preflight.identity,
            "attempted_ids": list(self.attempted_ids),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


class BatchRefused(PrintRefused):
    """A complete batch was refused before any physical output."""


async def async_preflight_batch(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    plant_ids: Sequence[str],
    copies: int,
    source: LayoutSource,
    profile: CapabilityProfile,
    ledger: LocalCalibrationLedger,
    actor: Actor,
    device_id: str,
    density: str = "normal",
    firmware: str | None = None,
    locale: str | None = None,
    as_of: datetime | None = None,
    fonts: FontLibrary | None = None,
) -> BatchPreflight:
    """Capture and render every unique plant before any physical command."""
    actor.authenticated()
    if isinstance(copies, bool) or not isinstance(copies, int) or copies < 1:
        raise HomeAssistantError("A label batch copy count must be a positive integer")
    if not device_id.strip():
        raise HomeAssistantError("A label batch needs a printer device ID")

    snapshots = await async_capture_batch(
        hass,
        coordinator,
        strain_library,
        plant_ids=plant_ids,
        locale=locale,
        as_of=as_of,
    )
    library = fonts or font_library_for(hass)
    calibration = await ledger.async_status(
        required=required_dependencies(
            profile, library, device_id=device_id, firmware=firmware
        )
    )

    records: list[BatchRecord] = []
    attributable: list[BatchDiagnostic] = []
    for index, snapshot in enumerate(snapshots):
        rendered = await async_render(
            hass,
            layout=source.layout,
            content=snapshot,
            profile=profile,
            density=density,
            device_id=device_id,
            operation=PREVIEW,
            local_calibration=calibration.identity,
            calibration_stale_reasons=calibration.stale_reasons,
            fonts=library,
        )
        decision = decide_print_request(
            rendered.eligibility,
            Operation.BATCH_PREFLIGHT,
            provenance=PrintProvenance(
                published_revision=source.published,
                actual_content=snapshot.source == RECORD_SOURCE,
                result_current=True,
            ),
        )
        records.append(
            BatchRecord(
                index=index,
                snapshot=snapshot,
                render=rendered,
                decision=decision,
            )
        )
        attributable.extend(
            BatchDiagnostic(
                record_index=index,
                subject=snapshot.subject,
                snapshot_identity=snapshot.identity,
                diagnostic=item,
            )
            for item in rendered.diagnostics
        )

    attempts = _attempt_plan(tuple(records), copies)
    return BatchPreflight(
        source=source,
        profile=profile,
        device_id=device_id,
        density=density,
        firmware=firmware,
        calibration_identity=calibration.identity,
        calibration_state=calibration.state,
        calibration_stale_reasons=calibration.stale_reasons,
        calibration_warnings=calibration.warnings,
        records=tuple(records),
        attempts=attempts,
        diagnostics=tuple(attributable),
    )


async def async_print_batch(
    hass: HomeAssistant,
    *,
    preflight: BatchPreflight,
    ledger: LocalCalibrationLedger,
    actor: Actor,
    acknowledgement: str | None = None,
    fonts: FontLibrary | None = None,
) -> BatchPrintResult:
    """Print every original attempt, preserving the preflight's exact order."""
    pending = tuple(
        BatchAttemptResult(attempt=item, status=AttemptStatus.PENDING)
        for item in preflight.attempts
    )
    return await _async_execute(
        hass,
        preflight=preflight,
        previous=pending,
        selected=frozenset(item.id for item in preflight.attempts),
        ledger=ledger,
        actor=actor,
        acknowledgement=acknowledgement,
        fonts=fonts,
    )


async def async_retry_failed_batch(
    hass: HomeAssistant,
    *,
    previous: BatchPrintResult,
    ledger: LocalCalibrationLedger,
    actor: Actor,
    acknowledgement: str | None = None,
    fonts: FontLibrary | None = None,
) -> BatchPrintResult:
    """Retry only failed original attempts, retaining their relative order."""
    selected = frozenset(item.attempt.id for item in previous.failed)
    return await _async_execute(
        hass,
        preflight=previous.preflight,
        previous=previous.attempts,
        selected=selected,
        ledger=ledger,
        actor=actor,
        acknowledgement=acknowledgement,
        fonts=fonts,
    )


def _attempt_plan(
    records: tuple[BatchRecord, ...], copies: int
) -> tuple[BatchAttempt, ...]:
    """Build A1, B1, C1, A2, B2, C2 -- never record-major order."""
    attempts: list[BatchAttempt] = []
    for copy_index in range(1, copies + 1):
        for record in records:
            position = len(attempts)
            attempt_id = digest(
                {
                    "position": position,
                    "record_index": record.index,
                    "subject": record.snapshot.subject,
                    "snapshot_identity": record.snapshot.identity,
                    "copy_index": copy_index,
                }
            )
            attempts.append(
                BatchAttempt(
                    id=attempt_id,
                    position=position,
                    record_index=record.index,
                    subject=record.snapshot.subject,
                    snapshot_identity=record.snapshot.identity,
                    copy_index=copy_index,
                )
            )
    return tuple(attempts)


async def _async_execute(
    hass: HomeAssistant,
    *,
    preflight: BatchPreflight,
    previous: tuple[BatchAttemptResult, ...],
    selected: frozenset[str],
    ledger: LocalCalibrationLedger,
    actor: Actor,
    acknowledgement: str | None,
    fonts: FontLibrary | None,
) -> BatchPrintResult:
    """Execute one selected subset only after all whole-batch gates pass."""
    actor.authenticated()
    _authorize(preflight, acknowledgement=acknowledgement)
    library = fonts or font_library_for(hass)
    calibration = await ledger.async_status(
        required=required_dependencies(
            preflight.profile,
            library,
            device_id=preflight.device_id,
            firmware=preflight.firmware,
        )
    )
    if (
        calibration.identity != preflight.calibration_identity
        or calibration.state != preflight.calibration_state
        or calibration.stale_reasons != preflight.calibration_stale_reasons
        or calibration.warnings != preflight.calibration_warnings
    ):
        raise BatchRefused(
            str(Operation.BATCH_PREFLIGHT),
            (str(Blocker.PREFLIGHT_NOT_CURRENT),),
            "The printer calibration changed after this batch was reviewed. "
            "Preflight it again before printing.",
        )

    by_id: Mapping[str, BatchAttemptResult] = {
        item.attempt.id: item for item in previous
    }
    updated: list[BatchAttemptResult] = []
    attempted: list[str] = []
    for attempt in preflight.attempts:
        old = by_id[attempt.id]
        if attempt.id not in selected:
            updated.append(old)
            continue
        attempted.append(attempt.id)
        record = preflight.records[attempt.record_index]
        try:
            outcome = await _async_judge_then_print(
                hass,
                operation=Operation.BATCH_PREFLIGHT,
                source=preflight.source,
                content=record.snapshot,
                profile=preflight.profile,
                density=preflight.density,
                device_id=preflight.device_id,
                fonts=library,
                provenance=PrintProvenance(
                    published_revision=preflight.source.published,
                    actual_content=record.snapshot.source == RECORD_SOURCE,
                    result_current=True,
                ),
                expected_raster_identity=record.render.raster_identity,
                calibration=calibration,
            )
        except (HomeAssistantError, PrintRefused) as err:
            updated.append(
                BatchAttemptResult(
                    attempt=attempt,
                    status=AttemptStatus.FAILED,
                    error=str(err),
                )
            )
        else:
            updated.append(
                BatchAttemptResult(
                    attempt=attempt,
                    status=AttemptStatus.PRINTED,
                    outcome=outcome,
                )
            )
    return BatchPrintResult(
        preflight=preflight,
        attempts=tuple(updated),
        attempted_ids=tuple(attempted),
    )


def _authorize(preflight: BatchPreflight, *, acknowledgement: str | None) -> None:
    """Refuse a hard error or warning consent for any other identity."""
    if not preflight.allowed:
        raise BatchRefused(str(Operation.BATCH_PREFLIGHT), preflight.blocked_by)
    if not preflight.acknowledgement_required:
        return
    if acknowledgement is None:
        raise BatchRefused(
            str(Operation.BATCH_PREFLIGHT),
            (str(Blocker.WARNING_ACKNOWLEDGEMENT_REQUIRED),),
        )
    if acknowledgement != preflight.identity:
        raise BatchRefused(
            str(Operation.BATCH_PREFLIGHT),
            (str(Blocker.PREFLIGHT_NOT_CURRENT),),
            "The warning acknowledgement belongs to a different preflight.",
        )


__all__ = [
    "AttemptStatus",
    "BatchAttempt",
    "BatchAttemptResult",
    "BatchDiagnostic",
    "BatchPreflight",
    "BatchPrintResult",
    "BatchRecord",
    "BatchRefused",
    "async_preflight_batch",
    "async_print_batch",
    "async_retry_failed_batch",
]
