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

# The remaining shipped templates use their own stable element identities.
# Element identities are local to a layout, but keeping them distinct makes
# diagnostics and golden fixture diffs unambiguous when two stocks are shown
# beside one another.
_IDS: Mapping[str, Mapping[str, str]] = {
    size: {
        role: f"growspace.factory.{size}.{role}.v1"
        for role in ("strain", "rule", "phenotype", "breeder", "lineage", "date")
    }
    for size in ("40x30", "50x50", "50x80", "50x15")
}

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
            {"x_mm": 2.0, "y_mm": 21.8, "width_mm": 43.0, "height_mm": 4.2},
            font=_BODY_FONT,
            size_mm=3.2,
            minimum_mm=2.2,
        ),
        _text(
            PRINT_DATE_ELEMENT,
            "print.date",
            {"date_style": "medium"},
            {"x_mm": 2.0, "y_mm": 26.0, "width_mm": 43.0, "height_mm": 3.0},
            font=_BODY_FONT,
            size_mm=2.4,
            minimum_mm=2.2,
            align="right",
        ),
    ],
}


def _standard_document(
    size: str,
    *,
    width_mm: float,
    title: tuple[float, float, float],
    rule_y_mm: float,
    rows: tuple[tuple[str, str, Mapping[str, str], float, float, int], ...],
    date: tuple[float, float, float],
) -> dict[str, Any]:
    """Build one deliberately composed factory layout.

    The dimensions are authored per stock below. This helper removes JSON
    ceremony; it is not a scaling algorithm and never derives one stock from
    another.
    """
    ids = _IDS[size]
    left = 2.0
    content_width = width_mm - 4.0
    elements: list[dict[str, Any]] = [
        _text(
            ids["strain"],
            "strain.name",
            {},
            {
                "x_mm": left,
                "y_mm": title[0],
                "width_mm": content_width,
                "height_mm": title[1],
            },
            font=_HEADING_FONT,
            size_mm=title[2],
            minimum_mm=2.4,
            maximum_lines=2 if title[1] >= 7.0 else 1,
        ),
        {
            "id": ids["rule"],
            "kind": "divider",
            "frame": {
                "x_mm": left,
                "y_mm": rule_y_mm,
                "width_mm": content_width,
                "height_mm": 0.4,
            },
            "rotation": 0,
            "style": {"fill": "black"},
        },
    ]
    for role, binding, parameters, y_mm, height_mm, maximum_lines in rows:
        elements.append(
            _text(
                ids[role],
                binding,
                parameters,
                {
                    "x_mm": left,
                    "y_mm": y_mm,
                    "width_mm": content_width,
                    "height_mm": height_mm,
                },
                font=_BODY_FONT,
                size_mm=3.2,
                minimum_mm=2.0,
                maximum_lines=maximum_lines,
            )
        )
    elements.append(
        _text(
            ids["date"],
            "print.date",
            {"date_style": "medium"},
            {
                "x_mm": left,
                "y_mm": date[0],
                "width_mm": content_width,
                "height_mm": date[1],
            },
            font=_BODY_FONT,
            size_mm=date[2],
            minimum_mm=1.6,
            align="right",
        )
    )
    return {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": f"growspace.stock.{size}.v1",
        "elements": elements,
    }


# Each composition uses the stock's extra or missing space intentionally. In
# particular the 50x15 layout omits lineage and breeder instead of crushing a
# 30 mm design to half-height, while the tall stocks give lineage two lines.
_FACTORY_40X30_DOCUMENT = _standard_document(
    "40x30",
    width_mm=40.0,
    title=(2.0, 8.4, 5.2),
    rule_y_mm=11.0,
    rows=(
        ("phenotype", "strain.phenotype", {"presentation": "value"}, 12.2, 4.4, 1),
        ("breeder", "strain.breeder", {"presentation": "labeled"}, 17.0, 4.4, 1),
        ("lineage", "strain.lineage", {"presentation": "labeled"}, 21.8, 4.4, 1),
    ),
    date=(26.6, 2.8, 2.4),
)

_FACTORY_50X50_DOCUMENT = _standard_document(
    "50x50",
    width_mm=50.0,
    title=(2.0, 10.0, 6.0),
    rule_y_mm=12.8,
    rows=(
        ("phenotype", "strain.phenotype", {"presentation": "value"}, 14.0, 6.0, 1),
        ("breeder", "strain.breeder", {"presentation": "labeled"}, 21.0, 6.0, 1),
        ("lineage", "strain.lineage", {"presentation": "labeled"}, 28.0, 11.0, 2),
    ),
    date=(45.0, 3.0, 2.5),
)

_FACTORY_50X80_DOCUMENT = _standard_document(
    "50x80",
    width_mm=50.0,
    title=(3.0, 12.0, 6.4),
    rule_y_mm=16.0,
    rows=(
        ("phenotype", "strain.phenotype", {"presentation": "value"}, 18.0, 7.0, 1),
        ("breeder", "strain.breeder", {"presentation": "labeled"}, 27.0, 7.0, 1),
        ("lineage", "strain.lineage", {"presentation": "labeled"}, 36.0, 14.0, 2),
    ),
    date=(74.0, 3.5, 2.6),
)

_FACTORY_50X15_DOCUMENT = _standard_document(
    "50x15",
    width_mm=50.0,
    title=(1.0, 5.0, 4.2),
    rule_y_mm=6.3,
    rows=(("phenotype", "strain.phenotype", {"presentation": "value"}, 7.1, 3.2, 1),),
    date=(11.7, 2.0, 1.8),
)


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
    # Revision 2: the date's frame was shorter than one line of its own face,
    # so it printed at 2.13 mm -- under the 2.2 mm the B1 evidence showed to
    # be readable. It is 0.2 mm taller now, and lineage 0.2 mm shorter.
    revision=2,
    name="Strain label",
    label_size_id="growspace.stock.50x30.v1",
    document=_FACTORY_50X30_DOCUMENT,
)

FACTORY_40X30 = FactoryTemplate(
    id="growspace.factory.40x30",
    revision=1,
    name="Compact strain label",
    label_size_id="growspace.stock.40x30.v1",
    document=_FACTORY_40X30_DOCUMENT,
)

FACTORY_50X50 = FactoryTemplate(
    id="growspace.factory.50x50",
    revision=1,
    name="Square strain label",
    label_size_id="growspace.stock.50x50.v1",
    document=_FACTORY_50X50_DOCUMENT,
)

FACTORY_50X80 = FactoryTemplate(
    id="growspace.factory.50x80",
    revision=1,
    name="Tall strain label",
    label_size_id="growspace.stock.50x80.v1",
    document=_FACTORY_50X80_DOCUMENT,
)

FACTORY_50X15 = FactoryTemplate(
    id="growspace.factory.50x15",
    revision=1,
    name="Slim strain label",
    label_size_id="growspace.stock.50x15.v1",
    document=_FACTORY_50X15_DOCUMENT,
)

FACTORY_TEMPLATES: Mapping[str, FactoryTemplate] = {
    template.id: template
    for template in (
        FACTORY_50X30,
        FACTORY_40X30,
        FACTORY_50X50,
        FACTORY_50X80,
        FACTORY_50X15,
    )
}


def factory_template_for_size(label_size_id: str) -> FactoryTemplate | None:
    """Return the shipped template designated for one stock, if there is one."""
    for template in FACTORY_TEMPLATES.values():
        if template.label_size_id == label_size_id:
            return template
    return None
