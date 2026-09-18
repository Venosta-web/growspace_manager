"""Label rendering.

One seam, three layers, and a rule about the order they sit in:

    Classic request  ->  classic.resolve_classic_request  ->  LabelContent
    LabelContent     ->  renderer.render                  ->  LabelRenderPlan
    LabelRenderPlan  ->  niimbot.async_print              ->  paper or preview

Every label the integration produces goes through `render`, whatever asked for
it — the strain library, a plant, each item of a batch, a preview or a print.
Nothing upstream of `render` knows what a printer is, and nothing downstream of
it decides what a label says or where anything sits.

That ordering is the whole contract. The Classic fixed-coordinate design is
currently what `render` composes and the Niimbot `imagespec` payload is
currently what realises it; replacing either is a change behind this seam, not
a change to it. See the hub specification at
`docs/design/label-layout-and-rendering-seam.md`.
"""

from __future__ import annotations

from .classic import ClassicPrintRequest, resolve_classic_request
from .model import (
    Canvas,
    Divider,
    LabelContent,
    LabelElement,
    LabelRenderPlan,
    Logo,
    QrCode,
    TextBlock,
    TextLine,
)
from .niimbot import async_print
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
    "Canvas",
    "ClassicPrintRequest",
    "Divider",
    "LabelContent",
    "LabelElement",
    "LabelRenderPlan",
    "Logo",
    "QrCode",
    "TextBlock",
    "TextLine",
    "async_print",
    "canvas_for",
    "render",
    "resolve_classic_request",
]
