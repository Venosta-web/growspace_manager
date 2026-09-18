"""Factory Templates: the layouts the integration ships.

A Factory Template follows the installed integration version. An upgrade may
append a new shipped revision and advance the current head; it never edits a
revision in place and never touches a Named Template someone copied from it.
An administrator who needs a frozen layout takes a copy, which is why these
definitions can keep improving without anyone's label changing underneath
them.

The documents below are written as plain JSON rather than as constructed
objects, and go through the same public validator every candidate document
does. A factory layout that stopped being valid would otherwise be the one
invalid document nothing checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .document import LabelLayout, validate_document

#: Element IDs are opaque and stable for the life of a revision: an editor
#: addresses an element by these, a diagnostic names them, and a restored
#: historical revision has to mean the same elements it meant when saved.
STRAIN_NAME_ELEMENT = "01M2V1PQB882FPJSG6H1GTFKX2"
RULE_ELEMENT = "01M2V1PQB82ZAZR3V5NKXZDS0Z"
PHENOTYPE_ELEMENT = "01M2V1PQB83XP8GJZZAP08DDKM"
BREEDER_ELEMENT = "01M2V1PQB8CH61GQ903X1XF808"
LINEAGE_ELEMENT = "01M2V1PQB8QKBBEH26QWK9FHT8"
PRINT_DATE_ELEMENT = "01M2V1PQB8NNQA4TA7RZEJZCCW"

_HEADING_FONT = "growspace.sans.bold.v1"
_BODY_FONT = "growspace.sans.regular.v1"
_COMPACT = "growspace.spacing.compact.v1"


def _text(
    element_id: str,
    binding: str,
    parameters: Mapping[str, str],
    frame: Mapping[str, float],
    *,
    font: str,
    size_mm: float,
    minimum_mm: float,
    align: str = "left",
    maximum_lines: int = 1,
) -> dict[str, Any]:
    """Spell one bound text element of a shipped layout."""
    return {
        "id": element_id,
        "kind": "text",
        "frame": dict(frame),
        "rotation": 0,
        "content": {"binding": binding, "parameters": dict(parameters)},
        "style": {
            "font": font,
            "font_size_mm": size_mm,
            "horizontal_align": align,
            "vertical_align": "center",
            "line_spacing": _COMPACT,
            "overflow": "shrink_ellipsis",
            "minimum_font_size_mm": minimum_mm,
            "maximum_lines": maximum_lines,
        },
    }


#: The 50x30 shipped layout, revision 1.
#:
#: It carries the elements every print context can resolve: the required
#: strain name, a rule, the three optional strain lines and the printed-on
#: stamp. A breeder logo and a plant QR are deliberately not in this revision
#: -- `plant.link` is unavailable when printing a strain, so a single shipped
#: layout containing it could not serve all three contexts, and both arrive
#: with the content snapshot work that can resolve them honestly.
_FACTORY_50X30_DOCUMENT: dict[str, Any] = {
    "schema": "growspace.label-layout",
    "version": 1,
    "label_size_id": "growspace.stock.50x30.v1",
    "elements": [
        _text(
            STRAIN_NAME_ELEMENT,
            "strain.name",
            {},
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 43.0, "height_mm": 8.4},
            font=_HEADING_FONT,
            size_mm=5.6,
            minimum_mm=3.0,
            maximum_lines=2,
        ),
        {
            "id": RULE_ELEMENT,
            "kind": "divider",
            "frame": {"x_mm": 2.0, "y_mm": 11.0, "width_mm": 43.0, "height_mm": 0.4},
            "rotation": 0,
            "style": {"fill": "black"},
        },
        _text(
            PHENOTYPE_ELEMENT,
            "strain.phenotype",
            {"presentation": "value"},
            {"x_mm": 2.0, "y_mm": 12.2, "width_mm": 43.0, "height_mm": 4.4},
            font=_BODY_FONT,
            size_mm=3.2,
            minimum_mm=2.2,
        ),
        _text(
            BREEDER_ELEMENT,
            "strain.breeder",
            {"presentation": "labeled"},
            {"x_mm": 2.0, "y_mm": 17.0, "width_mm": 43.0, "height_mm": 4.4},
            font=_BODY_FONT,
            size_mm=3.2,
            minimum_mm=2.2,
        ),
        _text(
            LINEAGE_ELEMENT,
            "strain.lineage",
            {"presentation": "labeled"},
            {"x_mm": 2.0, "y_mm": 21.8, "width_mm": 43.0, "height_mm": 4.4},
            font=_BODY_FONT,
            size_mm=3.2,
            minimum_mm=2.2,
        ),
        _text(
            PRINT_DATE_ELEMENT,
            "print.date",
            {"date_style": "medium"},
            {"x_mm": 2.0, "y_mm": 26.6, "width_mm": 43.0, "height_mm": 2.8},
            font=_BODY_FONT,
            size_mm=2.4,
            minimum_mm=2.0,
            align="right",
        ),
    ],
}


@dataclass(frozen=True, slots=True)
class FactoryTemplate:
    """One shipped layout, at one shipped revision."""

    id: str
    revision: int
    name: str
    label_size_id: str
    document: Mapping[str, Any]

    @property
    def layout(self) -> LabelLayout:
        """The validated layout, or an error naming what is wrong with it.

        Validated on every access rather than at import: an integration that
        refuses to load because a shipped layout is malformed takes every
        growspace down with it, and a label is not worth that.
        """
        validation = validate_document(dict(self.document))
        if validation.layout is None:
            codes = ", ".join(item.code for item in validation.diagnostics)
            raise ValueError(f"Factory Template {self.id} is invalid: {codes}")
        return validation.layout


FACTORY_50X30 = FactoryTemplate(
    id="growspace.factory.50x30",
    revision=1,
    name="Strain label",
    label_size_id="growspace.stock.50x30.v1",
    document=_FACTORY_50X30_DOCUMENT,
)

FACTORY_TEMPLATES: Mapping[str, FactoryTemplate] = {
    FACTORY_50X30.id: FACTORY_50X30,
}


def factory_template_for_size(label_size_id: str) -> FactoryTemplate | None:
    """Return the shipped template designated for one stock, if there is one."""
    for template in FACTORY_TEMPLATES.values():
        if template.label_size_id == label_size_id:
            return template
    return None
