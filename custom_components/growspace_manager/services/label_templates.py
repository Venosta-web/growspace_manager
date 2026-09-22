"""Production-only Label Template printing for Home Assistant services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import GrowspaceService
from custom_components.growspace_manager.labels.batch import (
    BatchRefused,
    async_preflight_batch,
    async_print_batch,
    authorize_batch,
)
from custom_components.growspace_manager.labels.calibration import (
    IncompatibleCalibrationStore,
    async_get_calibration_ledger,
    required_dependencies,
)
from custom_components.growspace_manager.labels.canonical import (
    FACTORY_TEMPLATES,
    PREVIEW,
    SUPPORTED_LOCALES,
    Blocker,
    Operation,
    PrintProvenance,
    async_capture_strain,
    async_render,
    decide_print_request,
    font_library_for,
    select_profile,
)
from custom_components.growspace_manager.labels.canonical.subjects import RECORD_SOURCE
from custom_components.growspace_manager.labels.library import (
    FACTORY,
    Actor,
    LabelTemplateError,
    ResolvedTemplate,
    RevisionNotFound,
    TemplateNotFound,
    TemplateNotResolvable,
    TemplateRef,
    async_get_library,
)
from custom_components.growspace_manager.labels.printing import (
    LayoutSource,
    PrintFailed,
    PrintRefused,
    async_print_record,
)
from custom_components.growspace_manager.schemas import PRINT_LABEL_TEMPLATE_SCHEMA
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, Unauthorized

from ._definition import ServiceDefinition

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

# A Home Assistant automation or script legitimately has no user attached to
# its Context. This principal exists only inside this production-print handler:
# it can read published templates and pass the ordinary production eligibility
# check, but no management or administrator-only route ever receives it.
SERVICE_PRINCIPAL = "growspace_manager.service.print_label_template"


def _ok(**payload: Any) -> dict[str, Any]:
    return {"outcome": "ok", **payload}


def _refused(code: str, message: str, recovery: str, **detail: Any) -> dict[str, Any]:
    return {
        "outcome": "refused",
        "refusal": {
            "code": code,
            "message": message,
            "recovery": recovery,
            **detail,
        },
    }


def _print_refused(error: PrintRefused) -> dict[str, Any]:
    return _refused(
        "label_template.print_refused",
        str(error),
        _recovery_for(error.blockers),
        operation=error.operation,
        blocked_by=list(error.blockers),
    )


def _recovery_for(blockers: tuple[str, ...]) -> str:
    """Choose the same first correction as the interactive print routes."""
    routes = (
        (str(Blocker.NO_RASTER), "retry_preview"),
        (str(Blocker.BLOCKING_DIAGNOSTICS), "fix_layout"),
        (str(Blocker.REVISION_NOT_PUBLISHED), "publish"),
        (str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED), "select_profile"),
        (str(Blocker.LOCAL_CALIBRATION_MISSING), "calibrate"),
        (str(Blocker.LOCAL_CALIBRATION_STALE), "calibrate"),
        (str(Blocker.RESULT_NOT_CURRENT), "refresh_preview"),
        (str(Blocker.PREFLIGHT_NOT_CURRENT), "preflight_again"),
        (str(Blocker.WARNING_ACKNOWLEDGEMENT_REQUIRED), "acknowledge_warnings"),
    )
    present = set(blockers)
    return next(
        (recovery for blocker, recovery in routes if blocker in present), "none"
    )


def _actor(call: ServiceCall) -> Actor:
    """Attribute user calls and admit unattributed production service calls."""
    return Actor(user_id=call.context.user_id or SERVICE_PRINCIPAL, is_admin=False)


def _source_of(resolved: ResolvedTemplate) -> LayoutSource:
    if resolved.ref.kind == FACTORY:
        return LayoutSource.from_factory(FACTORY_TEMPLATES[resolved.ref.id])
    return LayoutSource.from_revision(
        resolved.layout, template_id=resolved.ref.id, revision=resolved.revision
    )


async def _resolve_template(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    actor: Actor,
    data: dict[str, Any],
) -> ResolvedTemplate:
    library = await async_get_library(hass, coordinator.config_entry.entry_id)
    wanted = data.get("template")
    if wanted is None:
        return await library.async_resolve_default(actor, data["label_size_id"])
    return await library.async_resolve(
        actor,
        TemplateRef(kind=wanted["kind"], id=wanted["id"]),
        wanted.get("revision"),
    )


async def _print_strain(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    resolved: ResolvedTemplate,
    actor: Actor,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Internally preflight and print one strain record without an approval ID."""
    profile = select_profile(resolved.label_size_id, data.get("profile_id"))
    if profile is None:
        return _refused(
            "label_template.unknown_profile",
            f"{data.get('profile_id')} is not a Capability Profile for "
            f"{resolved.label_size_id}",
            "select_profile",
            label_size_id=resolved.label_size_id,
        )

    try:
        content = await async_capture_strain(
            hass,
            strain_library,
            strain=data["strain"],
            phenotype=data.get("phenotype"),
            locale=data["locale"],
        )
    except HomeAssistantError as error:
        return _refused(
            "label_template.unknown_subject",
            str(error),
            "choose_subject",
        )

    ledger = await async_get_calibration_ledger(hass, coordinator.config_entry.entry_id)
    fonts = font_library_for(hass)
    try:
        calibration = await ledger.async_status(
            required=required_dependencies(profile, fonts, device_id=data["device_id"])
        )
    except IncompatibleCalibrationStore as error:
        return _refused(
            "label_template.calibration_store_unreadable",
            str(error),
            "none",
        )

    source = _source_of(resolved)
    rendered = await async_render(
        hass,
        layout=source.layout,
        content=content,
        profile=profile,
        density=data["density"],
        device_id=data["device_id"],
        operation=PREVIEW,
        local_calibration=calibration.identity,
        calibration_stale_reasons=calibration.stale_reasons,
        fonts=fonts,
    )
    decision = decide_print_request(
        rendered.eligibility,
        Operation.SINGLE_PRINT,
        provenance=PrintProvenance(
            published_revision=source.published,
            actual_content=content.source == RECORD_SOURCE,
            result_current=True,
        ),
    )
    if not decision.allowed:
        return _print_refused(
            PrintRefused(str(Operation.SINGLE_PRINT), decision.blocked_by)
        )

    try:
        outcome = await async_print_record(
            hass,
            source=source,
            content=content,
            profile=profile,
            ledger=ledger,
            actor=actor,
            device_id=data["device_id"],
            expected_raster_identity=rendered.raster_identity,
            density=data["density"],
            fonts=fonts,
        )
    except PrintRefused as error:
        return _print_refused(error)
    except PrintFailed as error:
        return _refused("label_template.print_failed", str(error), "retry_print")
    except IncompatibleCalibrationStore as error:
        return _refused(
            "label_template.calibration_store_unreadable",
            str(error),
            "none",
        )
    return _ok(
        template=resolved.as_dict(),
        subject=content.subject,
        print=outcome.as_dict(),
    )


async def _print_plants(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    *,
    resolved: ResolvedTemplate,
    actor: Actor,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Preflight every plant before committing the first physical label."""
    profile = select_profile(resolved.label_size_id, data.get("profile_id"))
    if profile is None:
        return _refused(
            "label_template.unknown_profile",
            f"{data.get('profile_id')} is not a Capability Profile for "
            f"{resolved.label_size_id}",
            "select_profile",
            label_size_id=resolved.label_size_id,
        )
    ledger = await async_get_calibration_ledger(hass, coordinator.config_entry.entry_id)
    try:
        preflight = await async_preflight_batch(
            hass,
            coordinator,
            strain_library,
            plant_ids=data["plant_ids"],
            copies=1,
            source=_source_of(resolved),
            profile=profile,
            ledger=ledger,
            actor=actor,
            device_id=data["device_id"],
            density=data["density"],
            locale=data["locale"],
        )
        # This service has no approval handshake. Renderer warnings remain in
        # the returned preflight result but are not eligibility blockers; the
        # service proceeds only after every record's hard decision is allowed.
        acknowledgement = (
            preflight.identity if preflight.acknowledgement_required else None
        )
        authorize_batch(preflight, acknowledgement=acknowledgement)
        printed = await async_print_batch(
            hass,
            preflight=preflight,
            ledger=ledger,
            actor=actor,
            acknowledgement=acknowledgement,
        )
    except BatchRefused as error:
        return _print_refused(error)
    except IncompatibleCalibrationStore as error:
        return _refused(
            "label_template.calibration_store_unreadable",
            str(error),
            "none",
        )
    except HomeAssistantError as error:
        return _refused(
            "label_template.unknown_subject",
            str(error),
            "choose_subject",
        )
    return _ok(template=resolved.as_dict(), batch=printed.as_dict())


async def handle_print_label_template(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> dict[str, Any]:
    """Print record-backed labels through a published Label Template."""
    data = dict(call.data)
    data.setdefault("density", "normal")
    data.setdefault("locale", SUPPORTED_LOCALES[0])
    if not data["device_id"].strip():
        return _refused(
            "label_template.printer_required",
            "Choose the printer this label is for.",
            "choose_printer",
        )
    if data["locale"] not in SUPPORTED_LOCALES:
        return _refused(
            "label_template.unsupported_locale",
            f"{data['locale']} is not a supported print locale",
            "none",
            locale=data["locale"],
        )

    actor = _actor(call)
    try:
        resolved = await _resolve_template(hass, coordinator, actor, data)
    except Unauthorized as error:
        return _refused(
            "label_template.not_authorized",
            "Printing a label requires a Home Assistant user or automation.",
            "none",
            permission=getattr(error, "permission", None),
        )
    except TemplateNotResolvable as error:
        return _refused(
            "label_template.template_not_resolvable",
            str(error),
            "choose_template",
        )
    except (TemplateNotFound, RevisionNotFound, LabelTemplateError) as error:
        return _refused(
            "label_template.template_not_found", str(error), "choose_template"
        )

    if "strain" in data:
        return await _print_strain(
            hass,
            coordinator,
            strain_library,
            resolved=resolved,
            actor=actor,
            data=data,
        )
    return await _print_plants(
        hass,
        coordinator,
        strain_library,
        resolved=resolved,
        actor=actor,
        data=data,
    )


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        GrowspaceService.PRINT_LABEL_TEMPLATE,
        handle_print_label_template,
        PRINT_LABEL_TEMPLATE_SCHEMA,
        needs_strain_lib=True,
        supports_response=SupportsResponse.OPTIONAL,
    )
]
