"""The canonical Label Renderer: millimetres in, an authoritative raster out.

One seam, five stages, and a rule about who owns each:

    candidate JSON   ->  document.validate_document  ->  LabelLayout
    LabelLayout      ->  compiler.compile_layout     ->  LabelRenderPlan
    LabelRenderPlan  ->  preview.async_render        ->  RenderResult

A Label Layout is absolute millimetre geometry on a named stock, validated
against a closed schema that admits no CSS, no browser pixels, no `imagespec`
and no resolved plant data. A [[Capability Profile]] supplies the resolution,
the printhead, the Printable Area and the density range one render is against.
The compiler converts edges rather than extents, so adjacent frames cannot
acquire a rounding gap. The adapter produces the raster, and what comes back
is the bitmap the printer driver would receive -- decoded and measured here
rather than approximated anywhere else.

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
    PLACED,
    CompiledLabel,
    ElementOutcome,
    PixelFrame,
    compile_layout,
    to_pixels,
)
from .content import (
    REPRESENTATIVE_SUBJECTS,
    TYPICAL_STRAIN,
    LabelContentSnapshot,
    RepresentativeSubject,
)
from .diagnostics import Diagnostic, Layer, Severity, has_blocking
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
from .factory import (
    FACTORY_50X30,
    FACTORY_TEMPLATES,
    FactoryTemplate,
    factory_template_for_size,
)
from .preview import (
    DEFAULT_LABEL_SIZE_ID,
    PREVIEW,
    PRINT,
    async_render,
    async_render_factory_preview,
)
from .profiles import (
    NIIMBOT_B1_50X30,
    PROFILES,
    CapabilityProfile,
    ProfileEvidence,
    profiles_for_size,
)
from .result import (
    ADAPTER_VERSION,
    CURRENT,
    FAILED,
    RENDERER_VERSION,
    Raster,
    RenderContext,
    RenderResult,
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
    "FACTORY_50X30",
    "FACTORY_TEMPLATES",
    "FAILED",
    "FONT_TOKENS",
    "LABEL_SIZES",
    "LABEL_SIZE_CATALOGUE_VERSION",
    "LINE_SPACING_TOKENS",
    "MONOCHROME_TOKENS",
    "NIIMBOT_B1_50X30",
    "OMITTED_MISSING_CONTENT",
    "PLACED",
    "PREVIEW",
    "PRINT",
    "PROFILES",
    "QUANTUM_MM",
    "RENDERER_VERSION",
    "REPRESENTATIVE_SUBJECTS",
    "SCHEMA",
    "STYLE_TOKEN_CATALOGUE_VERSION",
    "TYPICAL_STRAIN",
    "VERSION",
    "BindingDefinition",
    "CapabilityProfile",
    "CompiledLabel",
    "Diagnostic",
    "DocumentValidation",
    "ElementKind",
    "ElementOutcome",
    "ErrorCorrection",
    "FactoryTemplate",
    "Frame",
    "LabelContentSnapshot",
    "LabelLayout",
    "LabelSize",
    "Layer",
    "LayoutElement",
    "MissingPolicy",
    "PixelFrame",
    "PrintContext",
    "ProfileEvidence",
    "Raster",
    "RenderContext",
    "RenderResult",
    "RepresentativeSubject",
    "Severity",
    "async_render",
    "async_render_factory_preview",
    "canonicalize",
    "compile_layout",
    "digest",
    "factory_template_for_size",
    "has_blocking",
    "profiles_for_size",
    "to_pixels",
    "validate_document",
]
