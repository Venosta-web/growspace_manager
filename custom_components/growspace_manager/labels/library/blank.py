"""The layout a blank draft starts from: the required element, and nothing else.

"Blank" cannot mean empty. Every publishable Label Layout carries one text
element bound to `strain.name`, so a truly empty document would be a draft that
cannot be published until the administrator discovers the rule -- and would
make the first thing a new template does a refusal.

So a blank draft is **valid by construction**: one strain-name element, placed
inside the stock with the same 2 mm margin the shipped layouts use, sized from
the paper rather than from a constant, and pushed through the public validator
before it is handed over. A blank draft that did not validate would be this
route's one invalid document nothing checks -- which is also the guard that
catches a stock added to the catalogue too thin for these margins.
"""

from __future__ import annotations

from typing import Any

from homeassistant.util.ulid import ulid_now

from ..canonical import LABEL_SIZES, REQUIRED_BINDING, LabelLayout, validate_document
from .errors import LabelTemplateError, UnsupportedLabelSize

#: The margin the shipped layouts keep, reused so a blank template and a
#: derived one start from the same relationship to the paper edge.
MARGIN_MM = 2.0

#: The strain name's frame height on ordinary stock, and the cap on it. Short
#: stock gets whatever is left between the margins instead.
NAME_HEIGHT_MM = 8.4

#: The requested size and the floor it may shrink to, in the proportion the
#: shipped 50x30 heading uses.
NAME_FONT_MM = 5.6
NAME_MINIMUM_FONT_MM = 3.0

_HEADING_FONT = "growspace.sans.bold.v1"
_COMPACT = "growspace.spacing.compact.v1"


def blank_document(label_size_id: str) -> dict[str, Any]:
    """Return the candidate document a blank draft of this stock starts as.

    The element ID is minted fresh. Element identities are per-document and
    stable for the life of a revision, so two blank drafts sharing one would
    make two unrelated templates address the same element by name.
    """
    size = LABEL_SIZES.get(label_size_id)
    if size is None:
        raise UnsupportedLabelSize(label_size_id)

    width_mm = round(size.width_mm - 2 * MARGIN_MM, 2)
    height_mm = round(min(NAME_HEIGHT_MM, size.height_mm - 2 * MARGIN_MM), 2)
    font_mm = round(min(NAME_FONT_MM, height_mm), 2)
    minimum_mm = round(min(NAME_MINIMUM_FONT_MM, font_mm), 2)

    return {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": size.id,
        "elements": [
            {
                "id": ulid_now(),
                "kind": "text",
                "frame": {
                    "x_mm": MARGIN_MM,
                    "y_mm": MARGIN_MM,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                },
                "rotation": 0,
                "content": {"binding": REQUIRED_BINDING, "parameters": {}},
                "style": {
                    "font": _HEADING_FONT,
                    "font_size_mm": font_mm,
                    "horizontal_align": "left",
                    "vertical_align": "center",
                    "line_spacing": _COMPACT,
                    "overflow": "shrink_ellipsis",
                    "minimum_font_size_mm": minimum_mm,
                    "maximum_lines": 2,
                },
            }
        ],
    }


def blank_layout(label_size_id: str) -> LabelLayout:
    """Return the validated blank layout, refusing to hand over an invalid one."""
    validation = validate_document(blank_document(label_size_id))
    if validation.layout is None:
        codes = ", ".join(item.code for item in validation.diagnostics)
        raise LabelTemplateError(
            f"The blank layout for {label_size_id} does not validate: {codes}. "
            "This stock is too small for the blank template's margins."
        )
    return validation.layout
