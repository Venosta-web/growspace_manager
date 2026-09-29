"""The recovery seam: calibration, test printing and one production print.

The library and the print routes have held all of this since the calibration
work landed; what was missing was the wire, and every decision below is about
the shape of that wire rather than about printing.

**An approval is held, never re-derived.** A content snapshot carries the
instant it was captured, that instant is part of the raster identity, and so a
second request cannot reproduce the raster an operator approved -- a fresh
capture is a fresh instant. Every preview here therefore holds what it drew in
`labels.approvals` and answers with an ID; a print names the ID and the
identity it approved, and the route re-renders from what was held and compares.
Nothing a client sends can stand in for the held content.

**A calibration is recorded against a sheet that printed.** The sheet's
dependencies stay on this side for the same reason. Four numbers a client
sends are attached to the identities of the label that really reached paper,
or they are refused.

**Every refusal is a result and names where to go.** The same rule the draft
commands follow, with one addition: a print refused for several reasons says
all of them in `blocked_by`, and `recovery` names the one correction to make
first -- the editor before the profile, the profile before the calibration,
the calibration before a fresh preview -- because fixing the second reason and
finding the button still disabled is how a recovery flow loses people.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.approvals import (
    CALIBRATION_SHEET,
    DRAFT_APPROVAL,
    RECORD_APPROVAL,
    ApprovalHolder,
    CalibrationSheet,
    DraftApproval,
    RecordApproval,
    approval_holder,
)
from custom_components.growspace_manager.labels.calibration import (
    CalibrationSheetNotPrinted,
    CalibrationSheetUnavailable,
    CalibrationStatus,
    IncompatibleCalibrationStore,
    LocalCalibrationLedger,
    MeasurementBounds,
    MeasurementInvalid,
    PlacementMeasurement,
    async_get_calibration_ledger,
    required_dependencies,
)
from custom_components.growspace_manager.labels.canonical import (
    FACTORY_TEMPLATES,
    PREVIEW,
    QUANTUM_MM,
    SUPPORTED_LOCALES,
    Blocker,
    CapabilityProfile,
    Operation,
    PrintProvenance,
    async_capture_strain,
    async_render,
    decide_print_request,
    font_library_for,
    overridable,
    profile_by_id,
    select_profile,
)
from custom_components.growspace_manager.labels.canonical.subjects import RECORD_SOURCE
from custom_components.growspace_manager.labels.library import (
    FACTORY,
    DraftNotFound,
    DraftNotPublishable,
    DraftVersionConflict,
    ResolvedTemplate,
    RevisionNotFound,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateRef,
)
from custom_components.growspace_manager.labels.printing import (
    LayoutSource,
    PrintFailed,
    PrintRefused,
    async_print_calibration_label,
    async_print_evidence_label,
    async_print_record,
    async_test_print,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from ._common import WSCommand
from .drafts import (
    _SLOT,
    CODE_DRAFT_NOT_FOUND,
    CODE_DRAFT_NOT_PUBLISHABLE,
    CODE_DRAFT_VERSION_MISMATCH,
    CODE_UNKNOWN_PROFILE,
    CODE_UNSUPPORTED_LOCALE,
    RECOVERY_FIX_LAYOUT,
    RECOVERY_NONE,
    RECOVERY_RELOAD_DRAFT,
    RECOVERY_REOPEN_DRAFT,
    RECOVERY_SELECT_PROFILE,
    RECOVERY_SIGN_IN_AS_ADMIN,
    _actor,
    _base_schema,
    _gate,
    _library,
    _ok,
    _refused,
    _slot,
)

WS_TYPE_GET_LABEL_CALIBRATION_STATUS = f"{DOMAIN}/get_label_calibration_status"
WS_TYPE_PRINT_LABEL_CALIBRATION_SHEET = f"{DOMAIN}/print_label_calibration_sheet"
WS_TYPE_RECORD_LABEL_CALIBRATION = f"{DOMAIN}/record_label_calibration"
WS_TYPE_PRINT_LABEL_EVIDENCE_SHEET = f"{DOMAIN}/print_label_evidence_sheet"
WS_TYPE_TEST_PRINT_LABEL_TEMPLATE_DRAFT = f"{DOMAIN}/test_print_label_template_draft"
WS_TYPE_PREVIEW_LABEL_RECORD = f"{DOMAIN}/preview_label_record"
WS_TYPE_PRINT_LABEL_RECORD = f"{DOMAIN}/print_label_record"

CODE_NOT_AUTHORIZED = "label_template.not_authorized"
CODE_APPROVAL_EXPIRED = "label_template.approval_expired"
CODE_PRINT_REFUSED = "label_template.print_refused"
CODE_PRINT_FAILED = "label_template.print_failed"
CODE_CALIBRATION_SHEET_NOT_PRINTED = "label_template.calibration_sheet_not_printed"
CODE_CALIBRATION_STORE_UNREADABLE = "label_template.calibration_store_unreadable"
CODE_MEASUREMENT_INVALID = "label_template.measurement_invalid"
CODE_PRINTER_REQUIRED = "label_template.printer_required"
CODE_TEMPLATE_NOT_FOUND = "label_template.template_not_found"
CODE_TEMPLATE_NOT_RESOLVABLE = "label_template.template_not_resolvable"
CODE_UNKNOWN_SUBJECT = "label_template.unknown_subject"

RECOVERY_CALIBRATE = "calibrate"
RECOVERY_PRINT_CALIBRATION_SHEET = "print_calibration_sheet"
RECOVERY_FIX_MEASUREMENT = "fix_measurement"
RECOVERY_REFRESH_PREVIEW = "refresh_preview"
RECOVERY_RETRY_PREVIEW = "retry_preview"
RECOVERY_CHOOSE_PRINTER = "choose_printer"
RECOVERY_CHOOSE_SUBJECT = "choose_subject"
RECOVERY_CHOOSE_TEMPLATE = "choose_template"
RECOVERY_PUBLISH = "publish"
RECOVERY_RETRY_PRINT = "retry_print"
RECOVERY_ACKNOWLEDGE_WARNINGS = "acknowledge_warnings"
RECOVERY_PREFLIGHT_AGAIN = "preflight_again"

#: Which correction clears each blocker, in the order they should be made.
#: A missing raster first: the renderer or the printer did not answer, the
#: diagnostics beside it are that failure rather than the layout's, and
#: nothing else can be judged until a render comes back. Then the layout,
#: because nothing downstream of an unprintable one is worth fixing yet; then
#: the printer and its measurement; then a fresh look. A batch's own two come
#: last: consent is worth giving only to a batch that could otherwise print.
_BLOCKER_RECOVERY: tuple[tuple[str, str], ...] = (
    (str(Blocker.NO_RASTER), RECOVERY_RETRY_PREVIEW),
    (str(Blocker.BLOCKING_DIAGNOSTICS), RECOVERY_FIX_LAYOUT),
    (str(Blocker.REVISION_NOT_PUBLISHED), RECOVERY_PUBLISH),
    (str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED), RECOVERY_SELECT_PROFILE),
    (str(Blocker.PRINTER_MODEL_NOT_COVERED), RECOVERY_SELECT_PROFILE),
    (str(Blocker.LOCAL_CALIBRATION_MISSING), RECOVERY_CALIBRATE),
    (str(Blocker.LOCAL_CALIBRATION_STALE), RECOVERY_CALIBRATE),
    (str(Blocker.RESULT_NOT_CURRENT), RECOVERY_REFRESH_PREVIEW),
    (str(Blocker.PREFLIGHT_NOT_CURRENT), RECOVERY_PREFLIGHT_AGAIN),
    (str(Blocker.WARNING_ACKNOWLEDGEMENT_REQUIRED), RECOVERY_ACKNOWLEDGE_WARNINGS),
)

SCHEMA_WS_GET_LABEL_CALIBRATION_STATUS = _base_schema(
    WS_TYPE_GET_LABEL_CALIBRATION_STATUS
).extend(
    {
        vol.Required("profile_id"): str,
        vol.Required("device_id"): str,
    }
)

SCHEMA_WS_PRINT_LABEL_CALIBRATION_SHEET = _base_schema(
    WS_TYPE_PRINT_LABEL_CALIBRATION_SHEET
).extend(
    {
        vol.Required("profile_id"): str,
        vol.Required("device_id"): str,
        vol.Optional("density", default="normal"): str,
    }
)

SCHEMA_WS_PRINT_LABEL_EVIDENCE_SHEET = _base_schema(
    WS_TYPE_PRINT_LABEL_EVIDENCE_SHEET
).extend(
    {
        vol.Required("profile_id"): str,
        vol.Required("device_id"): str,
        vol.Optional("density", default="normal"): str,
    }
)

SCHEMA_WS_RECORD_LABEL_CALIBRATION = _base_schema(
    WS_TYPE_RECORD_LABEL_CALIBRATION
).extend(
    {
        vol.Required("sheet_id"): str,
        vol.Required("measurement"): vol.Schema(
            {
                vol.Required(name): vol.Coerce(float)
                for name in ("top_mm", "right_mm", "bottom_mm", "left_mm", "feed_mm")
            }
        ),
        vol.Optional("notes"): vol.Any(None, str),
    }
)

SCHEMA_WS_TEST_PRINT_LABEL_TEMPLATE_DRAFT = _base_schema(
    WS_TYPE_TEST_PRINT_LABEL_TEMPLATE_DRAFT
).extend(
    {
        **_SLOT,
        vol.Required("expected_draft_version"): int,
        vol.Required("approval_id"): str,
        vol.Required("expected_raster_identity"): str,
        vol.Required("device_id"): str,
    }
)

SCHEMA_WS_PREVIEW_LABEL_RECORD = _base_schema(WS_TYPE_PREVIEW_LABEL_RECORD).extend(
    {
        vol.Required("template"): vol.Schema(
            {
                vol.Required("kind"): str,
                vol.Required("id"): str,
                vol.Optional("revision"): vol.Any(None, int),
            }
        ),
        vol.Required("strain"): str,
        vol.Optional("phenotype"): vol.Any(None, str),
        vol.Optional("profile_id"): vol.Any(None, str),
        vol.Required("device_id"): str,
        vol.Optional("locale", default=SUPPORTED_LOCALES[0]): str,
        vol.Optional("density", default="normal"): str,
    }
)

SCHEMA_WS_PRINT_LABEL_RECORD = _base_schema(WS_TYPE_PRINT_LABEL_RECORD).extend(
    {
        vol.Required("approval_id"): str,
        vol.Required("expected_raster_identity"): str,
        # Consent to print past the overridable refusals. A plain flag is
        # enough: the approval it travels with already binds the exact raster
        # the operator looked at.
        vol.Optional("override", default=False): bool,
    }
)


# ---------------------------------------------------------------------------
# Shaping answers
# ---------------------------------------------------------------------------


def recovery_for(blockers: Sequence[str]) -> str:
    """Return the one correction to make first, for a refused print."""
    present = set(blockers)
    return next(
        (recovery for blocker, recovery in _BLOCKER_RECOVERY if blocker in present),
        RECOVERY_NONE,
    )


def _print_refused(error: PrintRefused) -> dict[str, Any]:
    """Shape one refused print, naming every reason and the first correction."""
    return _refused(
        CODE_PRINT_REFUSED,
        str(error),
        recovery_for(error.blockers),
        operation=error.operation,
        blocked_by=list(error.blockers),
    )


def _print_failed(error: PrintFailed) -> dict[str, Any]:
    """Every gate passed and the printer did not take the label."""
    return _refused(CODE_PRINT_FAILED, str(error), RECOVERY_RETRY_PRINT)


def _not_authorized(error: Unauthorized, *, administrator: bool) -> dict[str, Any]:
    """Say who may do this; the one recovery a card cannot perform."""
    return _refused(
        CODE_NOT_AUTHORIZED,
        "Calibrating a printer and test printing require a Home Assistant "
        "administrator."
        if administrator
        else "Printing a label requires a signed-in Home Assistant user.",
        RECOVERY_SIGN_IN_AS_ADMIN if administrator else RECOVERY_NONE,
        permission=getattr(error, "permission", None),
    )


def _expired(recovery: str = RECOVERY_REFRESH_PREVIEW) -> dict[str, Any]:
    """The approval named is not held: it lapsed, or it was never issued here."""
    return _refused(
        CODE_APPROVAL_EXPIRED,
        "That preview is no longer held. Preview it again before printing.",
        recovery,
    )


def _unknown_profile(profile_id: str | None, label_size_id: str) -> dict[str, Any]:
    return _refused(
        CODE_UNKNOWN_PROFILE,
        f"{profile_id} is not a Capability Profile for {label_size_id}",
        RECOVERY_SELECT_PROFILE,
        label_size_id=label_size_id,
    )


def _printer_required() -> dict[str, Any]:
    return _refused(
        CODE_PRINTER_REQUIRED,
        "Choose the printer this label is for.",
        RECOVERY_CHOOSE_PRINTER,
    )


def _unreadable_store(error: IncompatibleCalibrationStore) -> dict[str, Any]:
    return _refused(CODE_CALIBRATION_STORE_UNREADABLE, str(error), RECOVERY_NONE)


def _bounds(bounds: MeasurementBounds) -> dict[str, Any]:
    """What the calibration form has to hold its five numbers to."""
    return {
        "printable_width_mm": bounds.printable_width_mm,
        "printable_height_mm": bounds.printable_height_mm,
        "feed_axis": bounds.feed_axis,
        "quantum_mm": float(QUANTUM_MM),
    }


async def _ledger(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> LocalCalibrationLedger:
    """Return this config entry's calibration ledger."""
    return await async_get_calibration_ledger(hass, coordinator.config_entry.entry_id)


def _holder(hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> ApprovalHolder:
    """Return this config entry's held approvals."""
    return approval_holder(hass, coordinator.config_entry.entry_id)


async def _status(
    hass: HomeAssistant,
    ledger: LocalCalibrationLedger,
    profile: CapabilityProfile,
    device_id: str,
) -> CalibrationStatus:
    """This printer's calibration, judged against what a print needs now."""
    return await ledger.async_status(
        required=required_dependencies(
            profile, font_library_for(hass), device_id=device_id
        )
    )


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


async def websocket_get_label_calibration_status(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Say whether one printer has been measured for one profile, and when.

    Readable by any authenticated user, because the answer is what explains a
    refused print to the person holding it.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    try:
        _actor(msg).authenticated()
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    profile = profile_by_id(msg["profile_id"])
    if profile is None:
        return _unknown_profile(msg["profile_id"], "any Label Size")
    if not msg["device_id"].strip():
        return _printer_required()

    ledger = await _ledger(hass, coordinator)
    try:
        status = await _status(hass, ledger, profile, msg["device_id"])
    except IncompatibleCalibrationStore as error:
        return _unreadable_store(error)
    return _ok(
        profile=profile.as_dict(),
        device_id=msg["device_id"],
        calibration=status.as_dict(),
        bounds=_bounds(MeasurementBounds.of_profile(profile)),
    )


async def websocket_print_label_calibration_sheet(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Put the standardized calibration label on paper, and hold what it was.

    The sheet's dependencies are held rather than returned for the card to
    send back: the measurement recorded afterwards must belong to the label
    that really printed, and a round trip through a client is where that
    stops being a property.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    profile = profile_by_id(msg["profile_id"])
    if profile is None:
        return _unknown_profile(msg["profile_id"], "any Label Size")
    if not msg["device_id"].strip():
        return _printer_required()

    try:
        printed = await async_print_calibration_label(
            hass,
            profile=profile,
            actor=_actor(msg),
            device_id=msg["device_id"],
            density=msg["density"],
            time_zone=hass.config.time_zone or "UTC",
        )
    except Unauthorized as error:
        return _not_authorized(error, administrator=True)
    except CalibrationSheetNotPrinted as error:
        cause = error.__cause__
        blockers = list(cause.blockers) if isinstance(cause, PrintRefused) else []
        return _refused(
            CODE_CALIBRATION_SHEET_NOT_PRINTED,
            str(error),
            recovery_for(blockers or [str(Blocker.NO_RASTER)]),
            blocked_by=blockers,
        )

    sheet_id = _holder(hass, coordinator).hold(
        CALIBRATION_SHEET,
        CalibrationSheet(
            printed=printed,
            profile=profile,
            density=msg["density"],
            device_id=msg["device_id"],
        ),
    )
    return _ok(
        sheet_id=sheet_id,
        sheet_raster_identity=printed.sheet_raster_identity,
        bounds=_bounds(MeasurementBounds.of_dependencies(printed.dependencies)),
        print=printed.outcome.as_dict(),
    )


async def websocket_record_label_calibration(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Append what the operator read off the sheet that printed."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    held: CalibrationSheet | None = _holder(hass, coordinator).get(
        msg["sheet_id"], CALIBRATION_SHEET
    )
    if held is None:
        return _refused(
            CODE_APPROVAL_EXPIRED,
            "That calibration label is no longer held. Print a new one and measure it.",
            RECOVERY_PRINT_CALIBRATION_SHEET,
        )

    ledger = await _ledger(hass, coordinator)
    try:
        record = await ledger.async_record(
            _actor(msg),
            measurement=PlacementMeasurement(**msg["measurement"]),
            dependencies=held.printed.dependencies,
            sheet_raster_identity=held.printed.sheet_raster_identity,
            printed_density=held.density,
            notes=msg.get("notes"),
        )
    except Unauthorized as error:
        return _not_authorized(error, administrator=True)
    except MeasurementInvalid as error:
        return _refused(
            CODE_MEASUREMENT_INVALID,
            str(error),
            RECOVERY_FIX_MEASUREMENT,
            field=error.field,
        )
    except IncompatibleCalibrationStore as error:
        return _unreadable_store(error)

    status = await _status(hass, ledger, held.profile, held.device_id)
    return _ok(record=record.summary(), calibration=status.as_dict())


async def websocket_print_label_evidence_sheet(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Put the evidence label on paper for a Release Evidence Record.

    Nothing is held and nothing can be recorded against it here: what it
    proves is read off paper and a phone by a person, and lands in the
    record a profile promotion is reviewed from.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    profile = profile_by_id(msg["profile_id"])
    if profile is None:
        return _unknown_profile(msg["profile_id"], "any Label Size")
    if not msg["device_id"].strip():
        return _printer_required()

    try:
        outcome = await async_print_evidence_label(
            hass,
            profile=profile,
            actor=_actor(msg),
            device_id=msg["device_id"],
            density=msg["density"],
            time_zone=hass.config.time_zone or "UTC",
        )
    except Unauthorized as error:
        return _not_authorized(error, administrator=True)
    except CalibrationSheetUnavailable as error:
        return _refused(CODE_PRINT_REFUSED, str(error), RECOVERY_SELECT_PROFILE)
    except PrintRefused as error:
        return _print_refused(error)
    except PrintFailed as error:
        return _print_failed(error)
    return _ok(print=outcome.as_dict())


# ---------------------------------------------------------------------------
# Test printing a draft
# ---------------------------------------------------------------------------


async def websocket_test_print_label_template_draft(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Put the draft preview an administrator is looking at on paper.

    The held approval pins the version; the draft is read again and refused
    if it has moved, so what prints is the stored layout rather than a copy
    that outlived an edit.
    """
    if (refusal := _gate(msg)) is not None:
        return refusal
    if not msg["device_id"].strip():
        return _printer_required()
    held: DraftApproval | None = _holder(hass, coordinator).get(
        msg["approval_id"], DRAFT_APPROVAL
    )
    if held is None:
        return _expired()
    expected = msg["expected_draft_version"]
    if held.draft_version != expected:
        return _refused(
            CODE_DRAFT_VERSION_MISMATCH,
            "The preview approved is of another version of this draft.",
            RECOVERY_REFRESH_PREVIEW,
            expected_version=expected,
            found_version=held.draft_version,
        )

    library = await _library(hass, coordinator)
    try:
        draft, layout = await library.async_draft_layout(
            _actor(msg), **_slot(msg), expected_version=expected
        )
    except Unauthorized as error:
        return _not_authorized(error, administrator=True)
    except DraftVersionConflict as error:
        return _refused(
            CODE_DRAFT_VERSION_MISMATCH,
            str(error),
            RECOVERY_RELOAD_DRAFT,
            expected_version=error.expected,
            found_version=error.found,
        )
    except DraftNotPublishable as error:
        return _refused(
            CODE_DRAFT_NOT_PUBLISHABLE,
            str(error),
            RECOVERY_FIX_LAYOUT,
            draft_version=expected,
            diagnostics=[item.as_dict() for item in error.diagnostics],
        )
    except DraftNotFound as error:
        return _refused(CODE_DRAFT_NOT_FOUND, str(error), RECOVERY_REOPEN_DRAFT)
    if draft.id != held.draft_id:
        # Same slot, same version number, another draft: the one approved was
        # discarded and a new one started in its place.
        return _expired()

    try:
        outcome = await async_test_print(
            hass,
            source=LayoutSource.from_draft(layout, draft_key=draft.id),
            content=held.content,
            profile=held.profile,
            actor=_actor(msg),
            device_id=msg["device_id"],
            density=held.density,
            expected_raster_identity=msg["expected_raster_identity"],
        )
    except PrintRefused as error:
        return _print_refused(error)
    except PrintFailed as error:
        return _print_failed(error)
    return _ok(print=outcome.as_dict())


# ---------------------------------------------------------------------------
# One production print
# ---------------------------------------------------------------------------


async def websocket_preview_label_record(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Render one published layout for one saved strain, judged for printing.

    Judged exactly as the print will be -- against this printer's calibration
    and with the request's provenance -- so every reason the print would be
    refused is on screen before anybody presses anything.
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
    try:
        content = await async_capture_strain(
            hass,
            strains,
            strain=msg["strain"],
            phenotype=msg.get("phenotype"),
            locale=locale,
        )
    except HomeAssistantError as error:
        return _refused(CODE_UNKNOWN_SUBJECT, str(error), RECOVERY_CHOOSE_SUBJECT)

    ledger = await _ledger(hass, coordinator)
    try:
        calibration = await _status(hass, ledger, profile, msg["device_id"])
    except IncompatibleCalibrationStore as error:
        return _unreadable_store(error)

    source = _source_of(resolved)
    result = await async_render(
        hass,
        layout=source.layout,
        content=content,
        profile=profile,
        density=msg["density"],
        device_id=msg["device_id"],
        operation=PREVIEW,
        local_calibration=calibration.identity,
        calibration_stale_reasons=calibration.stale_reasons,
    )
    decision = decide_print_request(
        result.eligibility,
        Operation.SINGLE_PRINT,
        provenance=PrintProvenance(
            published_revision=source.published,
            actual_content=content.source == RECORD_SOURCE,
            result_current=True,
        ),
    )
    approval_id = _holder(hass, coordinator).hold(
        RECORD_APPROVAL,
        RecordApproval(
            source=source,
            content=content,
            profile=profile,
            density=msg["density"],
            device_id=msg["device_id"],
            raster_identity=result.raster_identity,
        ),
    )
    return _ok(
        template=resolved.as_dict(),
        subject=content.subject,
        approval_id=approval_id,
        calibration=calibration.as_dict(),
        decision=decision.as_dict(),
        override_available=overridable(decision.blocked_by),
        recovery=recovery_for(decision.blocked_by),
        render=result.as_dict(),
    )


async def websocket_print_label_record(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any]:
    """Print the record preview an operator approved, or say why not."""
    if (refusal := _gate(msg)) is not None:
        return refusal
    held: RecordApproval | None = _holder(hass, coordinator).get(
        msg["approval_id"], RECORD_APPROVAL
    )
    if held is None:
        return _expired()

    ledger = await _ledger(hass, coordinator)
    try:
        outcome = await async_print_record(
            hass,
            source=held.source,
            content=held.content,
            profile=held.profile,
            ledger=ledger,
            actor=_actor(msg),
            device_id=held.device_id,
            expected_raster_identity=msg["expected_raster_identity"],
            density=held.density,
            override=msg.get("override", False),
        )
    except Unauthorized as error:
        return _not_authorized(error, administrator=False)
    except PrintRefused as error:
        return _print_refused(error)
    except PrintFailed as error:
        return _print_failed(error)
    except IncompatibleCalibrationStore as error:
        return _unreadable_store(error)
    return _ok(print=outcome.as_dict())


def _source_of(resolved: ResolvedTemplate) -> LayoutSource:
    """Name a resolved revision the way a print route records it."""
    if resolved.ref.kind == FACTORY:
        return LayoutSource.from_factory(FACTORY_TEMPLATES[resolved.ref.id])
    return LayoutSource.from_revision(
        resolved.layout, template_id=resolved.ref.id, revision=resolved.revision
    )


COMMANDS: list[WSCommand] = [
    WSCommand(
        command,
        handler,
        schema,
        resolve="any",
        actor=True,
    )
    for command, handler, schema in (
        (
            WS_TYPE_GET_LABEL_CALIBRATION_STATUS,
            websocket_get_label_calibration_status,
            SCHEMA_WS_GET_LABEL_CALIBRATION_STATUS,
        ),
        (
            WS_TYPE_PRINT_LABEL_CALIBRATION_SHEET,
            websocket_print_label_calibration_sheet,
            SCHEMA_WS_PRINT_LABEL_CALIBRATION_SHEET,
        ),
        (
            WS_TYPE_RECORD_LABEL_CALIBRATION,
            websocket_record_label_calibration,
            SCHEMA_WS_RECORD_LABEL_CALIBRATION,
        ),
        (
            WS_TYPE_PRINT_LABEL_EVIDENCE_SHEET,
            websocket_print_label_evidence_sheet,
            SCHEMA_WS_PRINT_LABEL_EVIDENCE_SHEET,
        ),
        (
            WS_TYPE_TEST_PRINT_LABEL_TEMPLATE_DRAFT,
            websocket_test_print_label_template_draft,
            SCHEMA_WS_TEST_PRINT_LABEL_TEMPLATE_DRAFT,
        ),
        (
            WS_TYPE_PREVIEW_LABEL_RECORD,
            websocket_preview_label_record,
            SCHEMA_WS_PREVIEW_LABEL_RECORD,
        ),
        (
            WS_TYPE_PRINT_LABEL_RECORD,
            websocket_print_label_record,
            SCHEMA_WS_PRINT_LABEL_RECORD,
        ),
    )
]
