"""Label rendering.

One seam, three layers, and a rule about the order they sit in:

    content snapshot + layout + profile  ->  canonical.compile_layout  ->  plan
    LabelRenderPlan                      ->  niimbot adapter           ->  paper

Every label the integration produces is compiled by `canonical.compile_layout`,
whatever asked for it -- a Label Template, a calibration sheet, or a Classic
request from a released card. Nothing upstream of the compiler knows what a
printer is, and nothing downstream of it decides what a label says or where
anything sits. The Niimbot `imagespec` payload is what realises a plan, and
replacing it is a change behind this seam rather than to it. See the hub
specification at `docs/design/label-layout-and-rendering-seam.md`.

There are two ways into that compiler, and they differ only in where the
layout came from:

- `classic` is the **Compatibility Adapter**: it turns a pre-template
  `print_label` request into a transient compatibility layout, content
  snapshot and profile (`canonical.compatibility`), and prints exactly what
  released cards have always printed.
- `canonical` is the **Label Template Path**: a validated millimetre document
  compiled against a [[Capability Profile]], which is what an editor saves and
  what a preview can honestly claim to be the printed bitmap.

`renderer` is the retired fixed-coordinate Classic design. No entry point
reaches it any more; it stays in the tree only as the reference the
compatibility goldens are proven byte-identical against, until the adapter has
shipped enabled in two stable releases and it may be deleted (hub #232).

Two packages sit beside the compiler rather than inside it, because neither is
about turning millimetres into dots:

- `library` owns *which* layout -- templates, drafts, revisions and defaults.
- `calibration` owns where one installed printer really puts ink, and
  `printing` is the three routes that put a label on paper: the standardized
  calibration sheet, an administrator's test print, and a production print of
  one real record.
"""

from __future__ import annotations

from . import calibration, canonical
from .batch import (
    AttemptStatus,
    BatchAttempt,
    BatchAttemptResult,
    BatchDiagnostic,
    BatchPreflight,
    BatchPrintResult,
    BatchRecord,
    BatchRefused,
    async_preflight_batch,
    async_print_batch,
    async_retry_failed_batch,
)
from .classic import (
    ClassicPrintRequest,
    async_compatibility_print,
    resolve_classic_request,
)
from .model import (
    Canvas,
    Divider,
    FittedText,
    LabelContent,
    LabelElement,
    LabelRenderPlan,
    Logo,
    QrCode,
    TextBlock,
    TextLine,
)
from .niimbot import (
    PRINTER_LIMITS,
    PrinterLimits,
    async_print,
    async_print_inputs,
    async_raster_inputs,
    printer_limits,
)
from .printing import (
    CalibrationPrint,
    LayoutSource,
    PrintOutcome,
    PrintRefused,
    async_print_calibration_label,
    async_print_record,
    async_test_print,
)

__all__ = [
    "PRINTER_LIMITS",
    "AttemptStatus",
    "BatchAttempt",
    "BatchAttemptResult",
    "BatchDiagnostic",
    "BatchPreflight",
    "BatchPrintResult",
    "BatchRecord",
    "BatchRefused",
    "CalibrationPrint",
    "Canvas",
    "ClassicPrintRequest",
    "Divider",
    "FittedText",
    "LabelContent",
    "LabelElement",
    "LabelRenderPlan",
    "LayoutSource",
    "Logo",
    "PrintOutcome",
    "PrintRefused",
    "PrinterLimits",
    "QrCode",
    "TextBlock",
    "TextLine",
    "async_compatibility_print",
    "async_preflight_batch",
    "async_print",
    "async_print_batch",
    "async_print_calibration_label",
    "async_print_inputs",
    "async_print_record",
    "async_raster_inputs",
    "async_retry_failed_batch",
    "async_test_print",
    "calibration",
    "canonical",
    "printer_limits",
    "resolve_classic_request",
]
