"""Label rendering.

One seam, three layers, and a rule about the order they sit in:

    Classic request  ->  classic.resolve_classic_request  ->  LabelContent
    LabelContent     ->  renderer.render                  ->  LabelRenderPlan
    LabelRenderPlan  ->  niimbot.async_print              ->  paper or preview

Every label the integration produces goes through `render`, whatever asked for
it — the strain library, a plant, each item of a batch, a preview or a print.
Nothing upstream of `render` knows what a printer is, and nothing downstream of
it decides what a label says or where anything sits.

That ordering is the whole contract. The Niimbot `imagespec` payload is what
realises a plan, and replacing it is a change behind this seam rather than to
it. See the hub specification at
`docs/design/label-layout-and-rendering-seam.md`.

There are two compositions above that adapter, and they differ only in where
the geometry came from:

- `renderer.render` is the **Classic Path**: one fixed 400x240 design stretched
  onto the requested stock, which is what every released card prints today.
- `canonical` is the **Label Template Path**: a validated millimetre document
  compiled against a [[Capability Profile]], which is what an editor will save
  and what a preview can honestly claim to be the printed bitmap.

Both end in the same adapter and the same `LabelRenderPlan`, so the Classic
Path can be retired without anything downstream of it noticing.

Two packages sit beside the renderer rather than inside it, because neither is
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
from .classic import ClassicPrintRequest, resolve_classic_request
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
from .niimbot import async_print, async_print_inputs, async_raster_inputs
from .printing import (
    CalibrationPrint,
    LayoutSource,
    PrintOutcome,
    PrintRefused,
    async_print_calibration_label,
    async_print_record,
    async_test_print,
)
from .renderer import (
    DEFAULT_LABEL_SIZE,
    LABEL_SIZE_CANVASES,
    REFERENCE_CANVAS,
    canvas_for,
    render,
)

__all__ = [
    "DEFAULT_LABEL_SIZE",
    "LABEL_SIZE_CANVASES",
    "REFERENCE_CANVAS",
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
    "QrCode",
    "TextBlock",
    "TextLine",
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
    "canvas_for",
    "render",
    "resolve_classic_request",
]
