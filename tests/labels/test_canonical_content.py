"""Tests for the content snapshot, its formatter and the factory templates.

The snapshot is taken once and read by preview, print, every batch item and
every retry, so its identity has to follow every value it carries and its
formatting has to be the backend's rather than the document's. The factory
templates are held to the same schema as any other document, and the guard
that enforces that is tested rather than assumed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    FACTORY_TEMPLATES,
    TYPICAL_STRAIN,
    Diagnostic,
    FactoryTemplate,
    LabelContentSnapshot,
    Layer,
    MissingPolicy,
    PrintContext,
    Severity,
    factory_template_for_size,
    has_blocking,
)
from custom_components.growspace_manager.labels.canonical.content import missing_policy

AS_OF = datetime(2026, 9, 18, 14, 30, tzinfo=UTC)
SNAPSHOT = TYPICAL_STRAIN.snapshot(as_of=AS_OF)


# ---------------------------------------------------------------------------
# Resolution and formatting
# ---------------------------------------------------------------------------


def test_a_value_resolves_as_the_normalized_string_behind_the_binding() -> None:
    assert SNAPSHOT.resolve("strain.name", {}) == "Blue Dream"


def test_an_absent_binding_resolves_to_nothing() -> None:
    assert SNAPSHOT.resolve("plant.id", {}) is None


def test_an_empty_value_is_absent_rather_than_blank_ink() -> None:
    """An empty printable value is a formatter defect, not a policy."""
    blank = replace(SNAPSHOT, values={**SNAPSHOT.values, "strain.breeder": ""})
    assert blank.resolve("strain.breeder", {"presentation": "value"}) is None


def test_a_labeled_presentation_prefixes_the_backend_s_own_caption() -> None:
    assert (
        SNAPSHOT.resolve("strain.lineage", {"presentation": "labeled"})
        == "Lineage: Blueberry x Haze"
    )


def test_a_value_presentation_emits_only_the_value() -> None:
    assert SNAPSHOT.resolve("strain.breeder", {"presentation": "value"}) == (
        "Humboldt Seed Co."
    )


def test_a_labeled_presentation_on_a_binding_with_no_caption_adds_nothing() -> None:
    """`strain.name` has no caption parameter, and must not acquire one."""
    assert SNAPSHOT.resolve("strain.name", {"presentation": "labeled"}) == "Blue Dream"


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        ("short", "18/09/2026"),
        ("medium", "18 Sep 2026"),
        ("iso", "2026-09-18"),
    ],
)
def test_the_closed_date_styles_are_spelled_once(style: str, expected: str) -> None:
    assert SNAPSHOT.resolve("print.date", {"date_style": style}) == expected


@pytest.mark.parametrize(
    ("locale", "style", "expected"),
    [
        ("en-US", "short", "9/18/2026"),
        ("en-GB", "short", "18/09/2026"),
        ("en-US", "medium", "Sep 18, 2026"),
        ("en-GB", "medium", "18 Sep 2026"),
        # The one shape a scanner or a spreadsheet can rely on, whatever the
        # locale printed the rest of the label in.
        ("en-US", "iso", "2026-09-18"),
        ("en-GB", "iso", "2026-09-18"),
    ],
)
def test_a_supported_locale_decides_civil_date_order(
    locale: str, style: str, expected: str
) -> None:
    localized = replace(SNAPSHOT, locale=locale)
    assert localized.resolve("print.date", {"date_style": style}) == expected


def test_an_unrecognised_date_style_falls_back_to_the_catalogue_default() -> None:
    """The validator fills the default in, so reaching this is a defect --
    which is exactly why it must not become a third date shape."""
    assert SNAPSHOT.resolve("print.date", {"date_style": "epoch"}) == "18/09/2026"


def test_the_print_date_needs_no_value_on_the_subject() -> None:
    """It is a property of the printing, so an empty subject still has one."""
    bare = LabelContentSnapshot(
        context=PrintContext.STRAIN, subject="x", as_of=AS_OF, values={}
    )
    assert bare.resolve("print.date", {}) == "18/09/2026"


# ---------------------------------------------------------------------------
# Context and policy
# ---------------------------------------------------------------------------


def test_a_strain_subject_does_not_support_a_plant_binding() -> None:
    assert SNAPSHOT.supports("strain.name") is True
    assert SNAPSHOT.supports("plant.link") is False


def test_an_unknown_binding_is_supported_by_no_context() -> None:
    assert SNAPSHOT.supports("plant.attributes.custom") is False


def test_a_plant_subject_supports_both_the_strain_and_plant_bindings() -> None:
    plant = LabelContentSnapshot(
        context=PrintContext.PLANT, subject="plant-1", as_of=AS_OF, values={}
    )
    assert plant.supports("strain.name") is True
    assert plant.supports("plant.link") is True


@pytest.mark.parametrize(
    ("binding", "policy"),
    [
        ("strain.name", MissingPolicy.BLOCK),
        ("strain.breeder", MissingPolicy.WARN_AND_OMIT),
        ("plant.link", MissingPolicy.BLOCK),
        ("print.date", MissingPolicy.NEVER_ABSENT),
    ],
)
def test_each_binding_declares_what_its_absence_means(
    binding: str, policy: MissingPolicy
) -> None:
    assert missing_policy(binding) == policy


def test_an_unknown_binding_blocks_rather_than_being_treated_as_optional() -> None:
    """Failing open here would let an unknown binding print a blank label."""
    assert missing_policy("strain.terpenes") == MissingPolicy.BLOCK


# ---------------------------------------------------------------------------
# Snapshot identity
# ---------------------------------------------------------------------------


def test_the_same_snapshot_has_the_same_identity() -> None:
    assert TYPICAL_STRAIN.snapshot(as_of=AS_OF).identity == SNAPSHOT.identity


@pytest.mark.parametrize(
    "change",
    [
        {"values": {"strain.name": "Purple Haze"}},
        {"subject": "another"},
        {"locale": "de"},
        {"time_zone": "Europe/Berlin"},
        {"as_of": datetime(2026, 9, 19, tzinfo=UTC)},
        {"source": "caller"},
        {"context": PrintContext.PLANT},
    ],
)
def test_identity_follows_every_input_the_render_depends_on(change: dict) -> None:
    assert replace(SNAPSHOT, **change).identity != SNAPSHOT.identity


def test_a_fixture_says_it_is_a_fixture() -> None:
    """So a raster of a fixture cannot be cached as one of a record."""
    assert SNAPSHOT.source == "growspace.label-fixtures.v2"
    assert (
        LabelContentSnapshot(
            context=PrintContext.STRAIN, subject="x", as_of=AS_OF
        ).source
        == "caller"
    )


# ---------------------------------------------------------------------------
# Factory templates
# ---------------------------------------------------------------------------


def test_the_shipped_template_is_designated_for_its_own_stock() -> None:
    assert factory_template_for_size("growspace.stock.50x30.v1") is FACTORY_50X30


def test_a_stock_with_no_shipped_template_gets_none_rather_than_another_size() -> None:
    assert factory_template_for_size("growspace.stock.50x80.v1") is None


def test_every_shipped_template_is_registered_under_its_own_id() -> None:
    for template_id, template in FACTORY_TEMPLATES.items():
        assert template.id == template_id
        assert template.layout.label_size_id == template.label_size_id


def test_a_factory_template_that_stopped_being_valid_refuses_to_render() -> None:
    """Otherwise it would be the one document nothing ever validates."""
    broken = FactoryTemplate(
        id="growspace.factory.broken",
        revision=1,
        name="Broken",
        label_size_id="growspace.stock.50x30.v1",
        document={"schema": "growspace.label-layout", "version": 1, "elements": []},
    )
    with pytest.raises(ValueError, match="growspace.factory.broken is invalid"):
        _ = broken.layout


def test_the_failure_names_the_codes_rather_than_only_saying_it_failed() -> None:
    broken = FactoryTemplate(
        id="growspace.factory.broken",
        revision=1,
        name="Broken",
        label_size_id="growspace.stock.50x30.v1",
        document={"schema": "growspace.label-layout", "version": 1, "elements": []},
    )
    with pytest.raises(ValueError, match="document.unknown_label_size"):
        _ = broken.layout


def test_reading_a_factory_layout_twice_gives_equal_layouts() -> None:
    """It is validated per access; that must not make it a different document."""
    assert FACTORY_50X30.layout == FACTORY_50X30.layout
    assert FACTORY_50X30.layout.digest == FACTORY_50X30.layout.digest


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_a_diagnostic_serializes_every_field_a_client_needs() -> None:
    diagnostic = Diagnostic(
        code="content.missing_optional",
        severity=Severity.WARNING,
        layer=Layer.CONTENT,
        message="strain.breeder has no value.",
        path="/elements/3/content",
        element_id="element-breeder",
        parameters={"binding": "strain.breeder"},
    )
    assert diagnostic.as_dict() == {
        "code": "content.missing_optional",
        "severity": "warning",
        "layer": "content",
        "message": "strain.breeder has no value.",
        "path": "/elements/3/content",
        "element_id": "element-breeder",
        "parameters": {"binding": "strain.breeder"},
    }


def test_only_an_error_blocks() -> None:
    warning = Diagnostic(
        code="c", severity=Severity.WARNING, layer=Layer.CONTENT, message="m"
    )
    info = Diagnostic(
        code="c", severity=Severity.INFO, layer=Layer.CONTENT, message="m"
    )
    error = Diagnostic(
        code="c", severity=Severity.ERROR, layer=Layer.DOCUMENT, message="m"
    )
    assert has_blocking(()) is False
    assert has_blocking((warning, info)) is False
    assert has_blocking((warning, error)) is True
