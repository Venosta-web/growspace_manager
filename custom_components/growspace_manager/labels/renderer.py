"""The one place a Growspace label is composed.

Every label the integration produces — strain library, plant, each item of a
batch, preview and print alike — passes through `render`. That is the whole
point of the module: preview and print cannot disagree about a label when
neither of them lays one out.

The design itself is still the Classic fixed-coordinate one, written against a
400x240 reference canvas and stretched onto the requested stock. Replacing it
with the canonical millimetre document (hub issue #206) is a change to this
function's body, not to anyone who calls it.
"""

from __future__ import annotations

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

#: The canvas every frame below is written against. Other stocks are reached
#: by scaling, so editing a coordinate here moves it on all five sizes.
REFERENCE_CANVAS = Canvas(width=400, height=240)

#: Device pixels per supported Label Size identity.
LABEL_SIZE_CANVASES: dict[str, Canvas] = {
    "50x30": Canvas(width=400, height=240),
    "40x30": Canvas(width=320, height=240),
    "50x50": Canvas(width=400, height=400),
    "50x80": Canvas(width=400, height=640),
    "50x15": Canvas(width=400, height=120),
}

#: What an absent or unrecognised `label_size` resolves to. Classic callers
#: have always been allowed to send a size the integration does not know, and
#: tightening that into an error is a compatibility decision, not a refactor.
DEFAULT_LABEL_SIZE = "50x30"

_TITLE_FONT = "ppb.ttf"
_BODY_FONT = "rbm.ttf"


def canvas_for(label_size: str | None) -> Canvas:
    """Resolve a Label Size identity to its canvas, falling back to the default."""
    return LABEL_SIZE_CANVASES.get(label_size or DEFAULT_LABEL_SIZE, REFERENCE_CANVAS)


def render(
    content: LabelContent, *, label_size: str | None, density: str
) -> LabelRenderPlan:
    """Compose one label and place it on the canvas `label_size` names."""
    elements: list[LabelElement] = [
        # Title: the strain, as large as the header band allows.
        TextBlock(
            value=content.title.upper(),
            x=0,
            y=20,
            x_end=260,
            width=250,
            height=50,
            size=50,
            font=_TITLE_FONT,
        ),
        # The rule under the title.
        Divider(x_start=0, x_end=260, y_start=85, y_end=88),
        # Phenotype, breeder and lineage, whichever of them survived filtering.
        TextBlock(
            value="\n".join(content.info_lines),
            x=0,
            y=100,
            x_end=260,
            width=250,
            height=100,
            size=40,
            font=_BODY_FONT,
        ),
    ]

    if content.logo:
        elements.append(Logo(url=content.logo, x=290, y=20, xsize=100, ysize=100))

    if content.qr_data:
        elements.append(QrCode(data=content.qr_data, x=290, y=130, boxsize=3))

    # The printed-on stamp, bottom right and deliberately small.
    elements.append(
        TextLine(value=content.printed_on, x=290, y=224, size=6, font=_BODY_FONT)
    )

    plan = LabelRenderPlan(
        canvas=REFERENCE_CANVAS, elements=tuple(elements), density=density
    )
    return plan.scaled_to(canvas_for(label_size))
