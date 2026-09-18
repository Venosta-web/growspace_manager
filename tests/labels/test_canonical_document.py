"""Tests for the closed `growspace.label-layout` v1 schema (hub issue #214).

The schema is the boundary between a saved design and everything that is not
one. These tests are mostly about what it *refuses*: browser vocabulary,
printer vocabulary, geometry finer than the quantum, an element that has
stopped being identifiable, and any field a future version might mean
something by.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import (
    QUANTUM_MM,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.canonicalization import (
    canonicalize,
    digest,
)
from custom_components.growspace_manager.labels.canonical.factory import FACTORY_50X30

STRAIN_NAME_STYLE = {
    "font": "growspace.sans.bold.v1",
    "font_size_mm": 4.2,
    "horizontal_align": "left",
    "vertical_align": "center",
    "line_spacing": "growspace.spacing.compact.v1",
    "overflow": "shrink_ellipsis",
    "minimum_font_size_mm": 2.2,
    "maximum_lines": 2,
}


def _document(*extra: dict[str, Any]) -> dict[str, Any]:
    """A minimal valid document, plus whatever the test wants beside it."""
    return {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": "growspace.stock.50x30.v1",
        "elements": [
            {
                "id": "element-strain-name",
                "kind": "text",
                "frame": {
                    "x_mm": 3.0,
                    "y_mm": 3.0,
                    "width_mm": 31.0,
                    "height_mm": 7.0,
                },
                "rotation": 0,
                "content": {"binding": "strain.name", "parameters": {}},
                "style": dict(STRAIN_NAME_STYLE),
            },
            *[deepcopy(item) for item in extra],
        ],
    }


def _codes(value: dict[str, Any]) -> list[str]:
    """The diagnostic codes one candidate document produces."""
    return [item.code for item in validate_document(value).diagnostics]


# ---------------------------------------------------------------------------
# What a valid document is
# ---------------------------------------------------------------------------


def test_a_minimal_document_validates_and_normalizes() -> None:
    validation = validate_document(_document())
    assert validation.diagnostics == ()
    assert validation.layout is not None
    assert validation.layout.label_size_id == "growspace.stock.50x30.v1"
    assert len(validation.layout.elements) == 1


def test_a_validated_layout_round_trips_through_its_own_normal_form() -> None:
    """Normalization is idempotent, which is what makes a digest a comparison."""
    first = validate_document(_document()).layout
    assert first is not None
    second = validate_document(first.as_dict()).layout
    assert second is not None
    assert second == first
    assert second.digest == first.digest


def test_the_digest_ignores_key_order_and_whitespace() -> None:
    """Two spellings of one document are one document."""
    plain = _document()
    reordered = {
        "elements": plain["elements"],
        "label_size_id": plain["label_size_id"],
        "version": plain["version"],
        "schema": plain["schema"],
    }
    left = validate_document(plain).layout
    right = validate_document(reordered).layout
    assert left is not None and right is not None
    assert left.digest == right.digest


def test_the_digest_follows_geometry() -> None:
    moved = _document()
    moved["elements"][0]["frame"]["x_mm"] = 3.01
    before = validate_document(_document()).layout
    after = validate_document(moved).layout
    assert before is not None and after is not None
    assert before.digest != after.digest


# ---------------------------------------------------------------------------
# Closed schema: browser and printer vocabulary stays out
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("z_index", 3),
        ("css", ".label { font-size: 12px }"),
        ("payload", [{"type": "text"}]),
        ("x", 42),
        ("width", 120),
        ("visible", True),
        ("name", "Strain name"),
    ],
)
def test_browser_and_printer_fields_are_refused_by_name(field: str, value: Any) -> None:
    """Rejecting them is not enough; the diagnostic has to say what they are."""
    candidate = _document()
    candidate["elements"][0][field] = value
    assert "schema.foreign_field" in _codes(candidate)


def test_an_unrecognised_field_is_refused_rather_than_dropped() -> None:
    """Dropping it is how a v2 document quietly becomes a lossy v1 one."""
    candidate = _document()
    candidate["elements"][0]["shadow"] = {"blur": 2}
    assert "schema.unknown_field" in _codes(candidate)


def test_a_newer_schema_version_is_refused_rather_than_decoded() -> None:
    candidate = _document()
    candidate["version"] = 2
    assert "document.unsupported_version" in _codes(candidate)


def test_an_unknown_element_kind_is_never_coerced_to_a_known_one() -> None:
    candidate = _document({"id": "e2", "kind": "barcode"})
    assert "element.unknown_kind" in _codes(candidate)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_geometry_finer_than_the_quantum_is_rejected_not_rounded() -> None:
    """Publication must not move a frame the author did not move."""
    candidate = _document()
    candidate["elements"][0]["frame"]["x_mm"] = 3.005
    assert "geometry.finer_than_quantum" in _codes(candidate)


def test_the_quantum_itself_is_a_hundredth_of_a_millimetre() -> None:
    assert float(QUANTUM_MM) == 0.01
    candidate = _document()
    candidate["elements"][0]["frame"]["x_mm"] = 3.01
    assert _codes(candidate) == []


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_a_non_finite_coordinate_is_rejected(value: float) -> None:
    candidate = _document()
    candidate["elements"][0]["frame"]["x_mm"] = value
    assert "geometry.not_finite" in _codes(candidate)


def test_a_frame_needs_a_positive_extent() -> None:
    candidate = _document()
    candidate["elements"][0]["frame"]["width_mm"] = 0.0
    assert "frame.non_positive_extent" in _codes(candidate)


def test_a_frame_outside_the_physical_stock_cannot_publish() -> None:
    """A draft may hold it for recovery; a document that claims to be valid may not."""
    candidate = _document()
    candidate["elements"][0]["frame"]["x_mm"] = 40.0
    assert "frame.outside_stock" in _codes(candidate)


def test_an_unknown_label_size_is_not_inferred_from_anything() -> None:
    candidate = _document()
    candidate["label_size_id"] = "50x30"
    assert "document.unknown_label_size" in _codes(candidate)


# ---------------------------------------------------------------------------
# Identity and paint order
# ---------------------------------------------------------------------------


def test_element_ids_are_unique_within_a_layout() -> None:
    candidate = _document(
        {
            "id": "element-strain-name",
            "kind": "divider",
            "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
            "rotation": 0,
            "style": {"fill": "black"},
        }
    )
    assert "element.duplicate_id" in _codes(candidate)


def test_an_element_without_an_id_cannot_be_addressed_or_diagnosed() -> None:
    candidate = _document({"kind": "divider"})
    assert "element.invalid_id" in _codes(candidate)


def test_paint_order_is_the_array_order_and_nothing_else() -> None:
    """Two ordering mechanisms would let one document describe two labels."""
    divider = {
        "id": "element-rule",
        "kind": "divider",
        "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    layout = validate_document(_document(divider)).layout
    assert layout is not None
    assert [element.id for element in layout.elements] == [
        "element-strain-name",
        "element-rule",
    ]


def test_reordering_elements_changes_the_document_but_not_the_ids() -> None:
    divider = {
        "id": "element-rule",
        "kind": "divider",
        "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    forwards = _document(divider)
    backwards = dict(forwards)
    backwards["elements"] = list(reversed(forwards["elements"]))

    left = validate_document(forwards).layout
    right = validate_document(backwards).layout
    assert left is not None and right is not None
    assert left.digest != right.digest
    assert {element.id for element in left.elements} == {
        element.id for element in right.elements
    }


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_the_four_supported_rotations_validate(rotation: int) -> None:
    candidate = _document()
    candidate["elements"][0]["rotation"] = rotation
    assert _codes(candidate) == []


@pytest.mark.parametrize("rotation", [45, -90, 360, 1.5, "90", True])
def test_free_angle_rotation_is_not_a_v1_concept(rotation: Any) -> None:
    candidate = _document()
    candidate["elements"][0]["rotation"] = rotation
    assert "element.unsupported_rotation" in _codes(candidate)


def test_a_divider_is_narrowed_to_the_rotations_that_mean_something() -> None:
    """180 degrees of a rectangle is the rectangle; two spellings, one label."""
    candidate = _document(
        {
            "id": "element-rule",
            "kind": "divider",
            "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
            "rotation": 180,
            "style": {"fill": "black"},
        }
    )
    assert "element.unsupported_rotation" in _codes(candidate)


# ---------------------------------------------------------------------------
# Content sources and the required role
# ---------------------------------------------------------------------------


def test_a_layout_without_a_strain_name_element_cannot_publish() -> None:
    candidate = _document()
    candidate["elements"][0]["content"] = {
        "binding": "strain.phenotype",
        "parameters": {},
    }
    assert "document.missing_required_strain_name" in _codes(candidate)


def test_a_literal_does_not_satisfy_the_strain_name_requirement() -> None:
    candidate = _document()
    candidate["elements"][0]["content"] = {"literal": "Blue Dream"}
    assert "document.missing_required_strain_name" in _codes(candidate)


def test_a_source_is_exactly_one_variant() -> None:
    """A binding with a literal fallback would hide missing-value behaviour."""
    candidate = _document()
    candidate["elements"][0]["content"] = {
        "binding": "strain.name",
        "parameters": {},
        "literal": "Blue Dream",
    }
    assert "content.ambiguous_source" in _codes(candidate)


def test_an_unknown_binding_is_an_error_rather_than_a_lookup() -> None:
    candidate = _document()
    candidate["elements"][0]["content"] = {
        "binding": "plant.attributes.custom_field",
        "parameters": {},
    }
    assert "content.unknown_binding" in _codes(candidate)


def test_a_binding_used_on_the_wrong_kind_is_refused() -> None:
    candidate = _document(
        {
            "id": "element-qr",
            "kind": "qr",
            "frame": {"x_mm": 37.0, "y_mm": 5.0, "width_mm": 10.0, "height_mm": 10.0},
            "rotation": 0,
            "content": {"binding": "strain.name", "parameters": {}},
            "style": {"error_correction": "high", "quiet_zone_modules": 4},
        }
    )
    assert "content.binding_kind_mismatch" in _codes(candidate)


def test_a_parameter_outside_the_closed_set_is_refused() -> None:
    candidate = _document()
    candidate["elements"][0]["content"] = {
        "binding": "strain.phenotype",
        "parameters": {"presentation": "uppercase"},
    }
    assert "content.invalid_parameter" in _codes(candidate)


def test_omitted_parameters_take_the_catalogue_default() -> None:
    """Which is what makes the normalized document self-describing."""
    candidate = _document(
        {
            "id": "element-breeder",
            "kind": "text",
            "frame": {"x_mm": 3.0, "y_mm": 14.0, "width_mm": 31.0, "height_mm": 4.0},
            "rotation": 0,
            "content": {"binding": "strain.breeder", "parameters": {}},
            "style": dict(STRAIN_NAME_STYLE),
        }
    )
    layout = validate_document(candidate).layout
    assert layout is not None
    assert layout.elements[1].content.parameters == {"presentation": "labeled"}


def test_an_asset_source_is_a_logo_privilege() -> None:
    candidate = _document()
    candidate["elements"][0]["content"] = {"asset_id": "asset-1"}
    assert "content.asset_not_permitted" in _codes(candidate)


def test_a_divider_carries_no_content() -> None:
    candidate = _document(
        {
            "id": "element-rule",
            "kind": "divider",
            "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
            "rotation": 0,
            "content": {"literal": "----"},
            "style": {"fill": "black"},
        }
    )
    assert "element.divider_has_content" in _codes(candidate)


# ---------------------------------------------------------------------------
# Style tokens
# ---------------------------------------------------------------------------


def test_an_unknown_font_token_is_never_substituted() -> None:
    candidate = _document()
    candidate["elements"][0]["style"]["font"] = "Helvetica Neue"
    assert "style.unknown_token" in _codes(candidate)


def test_a_minimum_font_size_above_the_requested_one_is_incoherent() -> None:
    candidate = _document()
    candidate["elements"][0]["style"]["minimum_font_size_mm"] = 9.0
    assert "style.minimum_above_requested" in _codes(candidate)


def test_a_missing_style_field_is_reported_rather_than_defaulted() -> None:
    candidate = _document()
    del candidate["elements"][0]["style"]["overflow"]
    assert "schema.missing_field" in _codes(candidate)


def test_a_divider_has_exactly_one_fill() -> None:
    candidate = _document(
        {
            "id": "element-rule",
            "kind": "divider",
            "frame": {"x_mm": 3.0, "y_mm": 12.0, "width_mm": 31.0, "height_mm": 0.4},
            "rotation": 0,
            "style": {"fill": "#333333"},
        }
    )
    assert "style.invalid_value" in _codes(candidate)


def test_every_diagnostic_is_attributable() -> None:
    """Prose is the fallback; a code, a layer and a path are the contract."""
    candidate = _document()
    candidate["elements"][0]["style"]["font"] = "Helvetica Neue"
    diagnostic = next(
        item
        for item in validate_document(candidate).diagnostics
        if item.code == "style.unknown_token"
    )
    assert diagnostic.layer == "document"
    assert diagnostic.severity == "error"
    assert diagnostic.path == "/elements/0/style/font"
    assert diagnostic.element_id == "element-strain-name"
    assert diagnostic.parameters == {"token": "Helvetica Neue"}


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def test_canonical_bytes_sort_keys_and_drop_insignificant_whitespace() -> None:
    assert canonicalize({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'


def test_a_whole_number_canonicalizes_without_a_trailing_zero() -> None:
    """RFC 8785 numbers are ECMAScript numbers; `3.0` and `3` are one value."""
    assert canonicalize({"x_mm": 3.0}) == b'{"x_mm":3}'
    assert canonicalize({"x_mm": 4.2}) == b'{"x_mm":4.2}'


def test_canonicalization_refuses_what_it_cannot_represent_exactly() -> None:
    with pytest.raises(ValueError, match="canonical JSON"):
        canonicalize({"x_mm": float("inf")})


def test_a_digest_names_its_algorithm() -> None:
    assert digest({"a": 1}).startswith("sha256:")


# ---------------------------------------------------------------------------
# The shipped layout is held to the same schema
# ---------------------------------------------------------------------------


def test_the_shipped_factory_layout_is_valid() -> None:
    """Otherwise it would be the one document nothing ever validates."""
    validation = validate_document(dict(FACTORY_50X30.document))
    assert validation.diagnostics == ()
    assert validation.layout is not None


def test_the_shipped_factory_layout_carries_the_required_strain_name() -> None:
    layout = FACTORY_50X30.layout
    bound = [
        element.content.binding
        for element in layout.elements
        if element.content is not None and hasattr(element.content, "binding")
    ]
    assert "strain.name" in bound
