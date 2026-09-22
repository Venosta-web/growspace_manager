"""The canonical Label Renderer: millimetres in, an authoritative raster out.

One seam, and a rule about who owns each stage of it:

    candidate JSON   ->  document.validate_document  ->  LabelLayout
    subject id       ->  subjects.async_capture_*    ->  LabelContentSnapshot
    both + a profile ->  compiler.compile_layout     ->  LabelRenderPlan
    compiled plan    ->  safety.evaluate_safety      ->  SafetyReport
    LabelRenderPlan  ->  preview.async_render        ->  RenderResult

A Label Layout is absolute millimetre geometry on a named stock, validated
against a closed schema that admits no CSS, no browser pixels, no `imagespec`
and no resolved plant data. A [[Label Content Snapshot]] is the other half:
one subject's values, resolved once from integration state and frozen, so a
preview, its print and every retry of it read the same content. A [[Capability
Profile]] supplies the resolution, the printhead, the Printable Area and the
density range one render is against. The compiler converts edges rather than
extents, so adjacent frames cannot acquire a rounding gap. The adapter
produces the raster, and what comes back is the bitmap the printer driver
would receive -- decoded and measured here rather than approximated anywhere
else. Between the compiler and the adapter sits the safety policy, which
measures what each element really inks and judges it against that profile's
calibrated limits; what it decides is one eligibility answer per operation,
not a boolean the card has to interpret.

Preview and print are the same call with one argument different, which is the
only arrangement in which a preview can honestly stand in for a print.

See the cross-repository specification at
`docs/design/label-layout-and-rendering-seam.md` in the workspace hub.
"""

from __future__ import annotations

from .canonicalization import canonicalize, digest
from .catalogue import (
    BINDING_CATALOGUE,
    BINDING_CATALOGUE_VERSION,
    CAPABILITY_GENERATION,
    FONT_TOKENS,
    LABEL_SIZE_CATALOGUE_VERSION,
    LABEL_SIZES,
    LINE_SPACING_TOKENS,
    MONOCHROME_TOKENS,
    REQUIRED_BINDING,
    STYLE_TOKEN_CATALOGUE_VERSION,
    BindingDefinition,
    ElementKind,
    ErrorCorrection,
    LabelSize,
    MissingPolicy,
    PrintContext,
)
from .compiler import (
    BLOCKED,
    COMPILER_VERSION,
    OMITTED_MISSING_CONTENT,
    OMITTED_UNSUPPORTED_CONTEXT,
    PLACED,
    CompiledLabel,
    ElementOutcome,
    PixelFrame,
    compile_layout,
    to_pixels,
)
from .content import (
    FIXTURE_CATALOGUE_VERSION,
    SUPPORTED_LOCALES,
    ContentAbsence,
    LabelAsset,
    LabelContentSnapshot,
    SubjectFacts,
    UnsupportedLocaleError,
    format_age,
    format_date,
    missing_policy,
    resolve_locale,
    resolve_subject,
    stage_display_name,
)
from .diagnostics import (
    DIAGNOSTIC_VERSION,
    Diagnostic,
    Layer,
    Recovery,
    Severity,
    has_blocking,
)
from .document import (
    QUANTUM_MM,
    SCHEMA,
    VERSION,
    DocumentValidation,
    Frame,
    LabelLayout,
    LayoutElement,
    validate_document,
)
from .eligibility import (
    Blocker,
    Operation,
    OperationEligibility,
    PrintProvenance,
    decide_eligibility,
    decide_print_request,
)
from .factory import (
    FACTORY_40X30,
    FACTORY_50X15,
    FACTORY_50X30,
    FACTORY_50X50,
    FACTORY_50X80,
    FACTORY_TEMPLATES,
    FactoryTemplate,
    factory_template_for_size,
)
from .fixtures import (
    LONG_BATCH_ITEM,
    LONG_CONTENT,
    LONG_PLANT,
    LONG_STRAIN,
    MISSING_OPTIONAL,
    REPRESENTATIVE_FAMILIES,
    REPRESENTATIVE_SUBJECTS,
    SPARSE_BATCH_ITEM,
    SPARSE_PLANT,
    SPARSE_STRAIN,
    TYPICAL,
    TYPICAL_BATCH_ITEM,
    TYPICAL_PLANT,
    TYPICAL_STRAIN,
    RepresentativeSubject,
    representative_subject,
)
from .fonts import (
    TEXT_TOOLCHAIN_VERSION,
    FontLibrary,
    MeasuredFont,
    NiimbotFontLibrary,
    niimbot_font_library,
    shipped_font_identity,
    toolchain_identity,
)
from .geometry import AreaMm
from .ink import ElementInk, InkBasis, element_ink, fit_text
from .preview import (
    DEFAULT_LABEL_SIZE_ID,
    PREVIEW,
    PRINT,
    async_render,
    async_render_factory_preview,
    font_library_for,
)
from .profiles import (
    NIIMBOT_B1_50X30,
    NIIMBOT_B1_MEASURED_LIMITS,
    PROFILE_CATALOGUE_VERSION,
    PROFILES,
    CalibratedLimits,
    CapabilityProfile,
    FeedAxis,
    ProfileEvidence,
    StockOrientation,
    profile_by_id,
    profiles_for_size,
    select_profile,
)
from .qr import QR_MODEL_VERSION, QrDataOverflow, QrSymbol, symbol_for
from .result import (
    ADAPTER_VERSION,
    CURRENT,
    FAILED,
    RENDERER_VERSION,
    Raster,
    RenderContext,
    RenderResult,
    eligibility_for,
)
from .safety import (
    OVERLAP_INK,
    OVERLAP_QR_QUIET_ZONE,
    OVERLAP_REQUIRED_CONTENT,
    SAFETY_POLICY_VERSION,
    OverlapPair,
    SafetyReport,
    evaluate_safety,
)
from .subjects import (
    PLANT_ROUTE,
    RECORD_SOURCE,
    async_capture_batch,
    async_capture_plant,
    async_capture_strain,
    stage_started_at,
)

__all__ = [
    "ADAPTER_VERSION",
    "BINDING_CATALOGUE",
    "BINDING_CATALOGUE_VERSION",
    "BLOCKED",
    "CAPABILITY_GENERATION",
    "COMPILER_VERSION",
    "CURRENT",
    "DEFAULT_LABEL_SIZE_ID",
    "DIAGNOSTIC_VERSION",
    "FACTORY_40X30",
    "FACTORY_50X15",
    "FACTORY_50X30",
    "FACTORY_50X50",
    "FACTORY_50X80",
    "FACTORY_TEMPLATES",
    "FAILED",
    "FIXTURE_CATALOGUE_VERSION",
    "FONT_TOKENS",
    "LABEL_SIZES",
    "LABEL_SIZE_CATALOGUE_VERSION",
    "LINE_SPACING_TOKENS",
    "LONG_BATCH_ITEM",
    "LONG_CONTENT",
    "LONG_PLANT",
    "LONG_STRAIN",
    "MISSING_OPTIONAL",
    "MONOCHROME_TOKENS",
    "NIIMBOT_B1_50X30",
    "NIIMBOT_B1_MEASURED_LIMITS",
    "OMITTED_MISSING_CONTENT",
    "OMITTED_UNSUPPORTED_CONTEXT",
    "OVERLAP_INK",
    "OVERLAP_QR_QUIET_ZONE",
    "OVERLAP_REQUIRED_CONTENT",
    "PLACED",
    "PLANT_ROUTE",
    "PREVIEW",
    "PRINT",
    "PROFILES",
    "PROFILE_CATALOGUE_VERSION",
    "QR_MODEL_VERSION",
    "QUANTUM_MM",
    "RECORD_SOURCE",
    "RENDERER_VERSION",
    "REPRESENTATIVE_FAMILIES",
    "REPRESENTATIVE_SUBJECTS",
    "REQUIRED_BINDING",
    "SAFETY_POLICY_VERSION",
    "SCHEMA",
    "SPARSE_BATCH_ITEM",
    "SPARSE_PLANT",
    "SPARSE_STRAIN",
    "STYLE_TOKEN_CATALOGUE_VERSION",
    "SUPPORTED_LOCALES",
    "TEXT_TOOLCHAIN_VERSION",
    "TYPICAL",
    "TYPICAL_BATCH_ITEM",
    "TYPICAL_PLANT",
    "TYPICAL_STRAIN",
    "VERSION",
    "AreaMm",
    "BindingDefinition",
    "Blocker",
    "CalibratedLimits",
    "CapabilityProfile",
    "CompiledLabel",
    "ContentAbsence",
    "Diagnostic",
    "DocumentValidation",
    "ElementInk",
    "ElementKind",
    "ElementOutcome",
    "ErrorCorrection",
    "FactoryTemplate",
    "FeedAxis",
    "FontLibrary",
    "Frame",
    "InkBasis",
    "LabelAsset",
    "LabelContentSnapshot",
    "LabelLayout",
    "LabelSize",
    "Layer",
    "LayoutElement",
    "MeasuredFont",
    "MissingPolicy",
    "NiimbotFontLibrary",
    "Operation",
    "OperationEligibility",
    "OverlapPair",
    "PixelFrame",
    "PrintContext",
    "PrintProvenance",
    "ProfileEvidence",
    "QrDataOverflow",
    "QrSymbol",
    "Raster",
    "Recovery",
    "RenderContext",
    "RenderResult",
    "RepresentativeSubject",
    "SafetyReport",
    "Severity",
    "StockOrientation",
    "SubjectFacts",
    "UnsupportedLocaleError",
    "async_capture_batch",
    "async_capture_plant",
    "async_capture_strain",
    "async_render",
    "async_render_factory_preview",
    "canonicalize",
    "compile_layout",
    "decide_eligibility",
    "decide_print_request",
    "digest",
    "element_ink",
    "eligibility_for",
    "evaluate_safety",
    "factory_template_for_size",
    "fit_text",
    "font_library_for",
    "format_age",
    "format_date",
    "has_blocking",
    "missing_policy",
    "niimbot_font_library",
    "profile_by_id",
    "profiles_for_size",
    "representative_subject",
    "resolve_locale",
    "resolve_subject",
    "select_profile",
    "shipped_font_identity",
    "stage_display_name",
    "stage_started_at",
    "symbol_for",
    "to_pixels",
    "toolchain_identity",
    "validate_document",
]
