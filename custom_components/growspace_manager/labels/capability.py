"""The complete, fail-closed Label Template capability contract.

This is deliberately one envelope.  A card either understands this complete
contract or stays on the Classic Path; it must never infer a template feature
from an individual command, integration version, or successful trial call.

The builder audits the backend pieces before returning anything.  That audit
is the publication boundary: a missing operation, invalid Factory Template,
or internally inconsistent catalogue makes the capability unavailable rather
than advertising a surface that will fail halfway through an editor session.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .batch import async_preflight_batch, async_print_batch, async_retry_failed_batch
from .calibration.ledger import LocalCalibrationLedger
from .calibration.records import STORE_VERSION as CALIBRATION_STORE_VERSION
from .calibration.sheet import SHEET_VERSION
from .canonical import (
    ADAPTER_VERSION,
    BINDING_CATALOGUE,
    BINDING_CATALOGUE_VERSION,
    CAPABILITY_GENERATION,
    COMPILER_VERSION,
    DIAGNOSTIC_VERSION,
    FACTORY_TEMPLATES,
    FIXTURE_CATALOGUE_VERSION,
    FONT_TOKENS,
    LABEL_SIZE_CATALOGUE_VERSION,
    LABEL_SIZES,
    LINE_SPACING_TOKENS,
    MONOCHROME_TOKENS,
    PROFILE_CATALOGUE_VERSION,
    PROFILES,
    QR_MODEL_VERSION,
    QUANTUM_MM,
    RENDERER_VERSION,
    REPRESENTATIVE_FAMILIES,
    SAFETY_POLICY_VERSION,
    SCHEMA,
    STYLE_TOKEN_CATALOGUE_VERSION,
    SUPPORTED_LOCALES,
    TEXT_TOOLCHAIN_VERSION,
    VERSION,
    ElementKind,
    PrintContext,
    async_render,
    validate_document,
)
from .canonical.qr import MAX_VERSION as QR_MAX_VERSION
from .canonical.subjects import MAX_LOGO_SOURCE_BYTES
from .library import (
    BACKUP_VERSION,
    BUNDLE_VERSION,
    COMMIT_LEDGER_LIMIT,
    STORE_VERSION,
    LabelTemplateLibrary,
)
from .printing import (
    async_print_calibration_label,
    async_print_evidence_label,
    async_print_record,
    async_test_print,
)

CAPABILITY_FAMILY = "growspace.label-templates"
CONTRACT_MAJOR = 1
CONTRACT_MINOR = 0
MINIMUM_CARD_CONTRACT = "growspace.label-templates-card.v1"

DISCOVER = "discover"
LIFECYCLE = "lifecycle"
VALIDATE = "validate"
PREVIEW = "preview"
CALIBRATION = "calibration"
TEST_PRINT = "test_print"
SINGLE_PRINT = "single_print"
BATCH_PREFLIGHT = "batch_preflight"
BATCH_PRINT = "batch_print"
BATCH_RETRY = "batch_retry"
PORTABLE_EXPORT = "portable_export"
PORTABLE_IMPORT = "portable_import"
BACKUP = "backup"
RESTORE = "restore"

REQUIRED_OPERATIONS = (
    DISCOVER,
    LIFECYCLE,
    VALIDATE,
    PREVIEW,
    CALIBRATION,
    TEST_PRINT,
    SINGLE_PRINT,
    BATCH_PREFLIGHT,
    BATCH_PRINT,
    BATCH_RETRY,
    PORTABLE_EXPORT,
    PORTABLE_IMPORT,
    BACKUP,
    RESTORE,
)

# The callable inventory is kept beside the advertised operation inventory so
# adding a word to the envelope without implementing it cannot pass the audit.
_IMPLEMENTATIONS: Mapping[str, tuple[Callable[..., Any], ...]] = {
    DISCOVER: (validate_document,),
    LIFECYCLE: (
        LabelTemplateLibrary.async_snapshot,
        LabelTemplateLibrary.async_create_draft,
        LabelTemplateLibrary.async_open_editing_draft,
        LabelTemplateLibrary.async_discard_draft,
        LabelTemplateLibrary.async_autosave_draft,
        LabelTemplateLibrary.async_publish_draft,
        LabelTemplateLibrary.async_set_default,
        LabelTemplateLibrary.async_delete_template,
        LabelTemplateLibrary.async_restore_template,
    ),
    VALIDATE: (validate_document,),
    PREVIEW: (
        async_render,
        LabelTemplateLibrary.async_preview_draft,
        LabelTemplateLibrary.async_preview_template,
    ),
    CALIBRATION: (
        async_print_calibration_label,
        async_print_evidence_label,
        LocalCalibrationLedger.async_record,
        LocalCalibrationLedger.async_status,
    ),
    TEST_PRINT: (async_test_print,),
    SINGLE_PRINT: (async_print_record,),
    BATCH_PREFLIGHT: (async_preflight_batch,),
    BATCH_PRINT: (async_print_batch,),
    BATCH_RETRY: (async_retry_failed_batch,),
    PORTABLE_EXPORT: (LabelTemplateLibrary.async_export_templates,),
    PORTABLE_IMPORT: (LabelTemplateLibrary.async_import_templates,),
    BACKUP: (LabelTemplateLibrary.async_backup,),
    RESTORE: (LabelTemplateLibrary.async_restore_backup,),
}


class IncompatibleLabelTemplateContract(HomeAssistantError):
    """A new-path command named a missing, stale, or unknown contract."""

    def __init__(self, reason: str, received: object) -> None:
        """Record why the received identity cannot be used."""
        self.reason = reason
        self.received = received
        super().__init__(f"Label Template contract is {reason}")

    def as_dict(self) -> dict[str, Any]:
        """Return the stable incompatibility result shared with the card."""
        return {
            "code": "label_template.contract_incompatible",
            "reason": self.reason,
            "received": self.received,
            "current": contract_identity(),
            "recovery": "refresh_capability",
        }


@dataclass(frozen=True, slots=True)
class LabelTemplateCapability:
    """One already-audited V1 capability."""

    value: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a plain JSON-safe copy of the envelope."""
        return dict(self.value)


def contract_identity() -> dict[str, Any]:
    """Return the identity every new-path command must echo."""
    return {
        "family": CAPABILITY_FAMILY,
        "major": CONTRACT_MAJOR,
        "minor": CONTRACT_MINOR,
        "generation": CAPABILITY_GENERATION,
    }


def require_contract(received: object) -> None:
    """Reject a command that did not negotiate the current exact contract."""
    if not isinstance(received, Mapping):
        raise IncompatibleLabelTemplateContract("missing", received)
    family = received.get("family")
    major = received.get("major")
    generation = received.get("generation")
    if family != CAPABILITY_FAMILY or major != CONTRACT_MAJOR:
        raise IncompatibleLabelTemplateContract("unknown", dict(received))
    if generation != CAPABILITY_GENERATION:
        raise IncompatibleLabelTemplateContract("stale", dict(received))


def capability_errors(
    *,
    implementations: Mapping[str, Sequence[Callable[..., Any]]] = _IMPLEMENTATIONS,
    factories: Mapping[str, Any] = FACTORY_TEMPLATES,
) -> tuple[str, ...]:
    """Return every reason the complete capability cannot be advertised."""
    errors: list[str] = []
    if set(implementations) != set(REQUIRED_OPERATIONS):
        missing = sorted(set(REQUIRED_OPERATIONS) - set(implementations))
        extra = sorted(set(implementations) - set(REQUIRED_OPERATIONS))
        errors.append(f"operation inventory differs (missing={missing}, extra={extra})")
    for operation in REQUIRED_OPERATIONS:
        functions = implementations.get(operation, ())
        if not functions or not all(callable(item) for item in functions):
            errors.append(f"operation {operation} has no complete implementation")

    by_size: dict[str, list[Any]] = {size_id: [] for size_id in LABEL_SIZES}
    for key, template in factories.items():
        if key != template.id:
            errors.append(f"Factory Template key {key} does not match {template.id}")
        if template.label_size_id not in by_size:
            errors.append(f"Factory Template {key} names an unknown Label Size")
            continue
        by_size[template.label_size_id].append(template)
        try:
            layout = template.layout
        except ValueError as err:
            errors.append(str(err))
        else:
            if layout.label_size_id != template.label_size_id:
                errors.append(f"Factory Template {key} document names another stock")
    for size_id, shipped in by_size.items():
        if len(shipped) != 1:
            errors.append(f"Label Size {size_id} has {len(shipped)} factory fallbacks")

    for profile_id, profile in PROFILES.items():
        if profile_id != profile.id or profile.label_size_id not in LABEL_SIZES:
            errors.append(f"Capability Profile {profile_id} is internally inconsistent")
    return tuple(errors)


def published_capability(
    *,
    implementations: Mapping[str, Sequence[Callable[..., Any]]] = _IMPLEMENTATIONS,
    factories: Mapping[str, Any] = FACTORY_TEMPLATES,
) -> LabelTemplateCapability | None:
    """Return the complete capability, or nothing when its audit fails."""
    if capability_errors(implementations=implementations, factories=factories):
        return None
    return LabelTemplateCapability(_envelope(factories))


def _envelope(factories: Mapping[str, Any]) -> dict[str, Any]:
    """Build the complete deterministic V1 wire envelope."""
    return {
        "contract": contract_identity(),
        "minimum_card_contract": MINIMUM_CARD_CONTRACT,
        "versions": {
            "layout": f"{SCHEMA}.v{VERSION}",
            "template_store": f"growspace.label-template-store.v{STORE_VERSION}",
            "portable_bundle": f"growspace.label-template-bundle.v{BUNDLE_VERSION}",
            "backup": f"growspace.label-template-backup.v{BACKUP_VERSION}",
            "calibration_store": f"growspace.label-calibration-store.v{CALIBRATION_STORE_VERSION}",
            "calibration_sheet": SHEET_VERSION,
            "label_sizes": LABEL_SIZE_CATALOGUE_VERSION,
            "bindings": BINDING_CATALOGUE_VERSION,
            "style_tokens": STYLE_TOKEN_CATALOGUE_VERSION,
            "profiles": PROFILE_CATALOGUE_VERSION,
            "fixtures": FIXTURE_CATALOGUE_VERSION,
            "compiler": COMPILER_VERSION,
            "renderer": RENDERER_VERSION,
            "adapter": ADAPTER_VERSION,
            "diagnostics": DIAGNOSTIC_VERSION,
            "safety_policy": SAFETY_POLICY_VERSION,
            "qr_model": QR_MODEL_VERSION,
            "text_toolchain": TEXT_TOOLCHAIN_VERSION,
        },
        "operations": {
            name: {
                "available": True,
                "contract_required": name != DISCOVER,
            }
            for name in REQUIRED_OPERATIONS
        },
        "catalogues": {
            "label_sizes": [
                {
                    "id": item.id,
                    "width_mm": item.width_mm,
                    "height_mm": item.height_mm,
                    "classic_key": item.classic_key,
                    "factory_template_id": next(
                        template.id
                        for template in factories.values()
                        if template.label_size_id == item.id
                    ),
                }
                for item in LABEL_SIZES.values()
            ],
            "bindings": [
                {
                    "id": item.id,
                    "kinds": [str(kind) for kind in item.kinds],
                    "contexts": [str(context) for context in item.contexts],
                    "parameters": {
                        name: list(values) for name, values in item.parameters.items()
                    },
                    "missing_policy": str(item.missing_policy),
                    "required": item.required,
                }
                for item in BINDING_CATALOGUE.values()
            ],
            "style_tokens": {
                "fonts": [
                    {"id": item.id, "description": item.description}
                    for item in FONT_TOKENS.values()
                ],
                "line_spacing": [
                    {"id": item.id, "ratio": item.ratio}
                    for item in LINE_SPACING_TOKENS.values()
                ],
                "monochrome": [
                    {"id": item.id, "dither": item.dither}
                    for item in MONOCHROME_TOKENS.values()
                ],
            },
            "profiles": [profile.as_dict() for profile in PROFILES.values()],
            "factory_templates": [
                {
                    "id": item.id,
                    "revision": item.revision,
                    "name": item.name,
                    "label_size_id": item.label_size_id,
                    "layout": item.layout.as_dict(),
                    "layout_digest": item.layout.digest,
                }
                for item in factories.values()
            ],
            "representative_fixtures": {
                family: {str(context): fixture.id for context, fixture in rows.items()}
                for family, rows in REPRESENTATIVE_FAMILIES.items()
            },
        },
        "supported": {
            "contexts": [str(item) for item in PrintContext],
            "locales": list(SUPPORTED_LOCALES),
            "element_kinds": [str(item) for item in ElementKind],
        },
        "limits": {
            "coordinate_quantum_mm": float(QUANTUM_MM),
            "commit_ledger_entries": COMMIT_LEDGER_LIMIT,
            "logo_source_bytes": MAX_LOGO_SOURCE_BYTES,
            "qr_max_version": QR_MAX_VERSION,
        },
    }
