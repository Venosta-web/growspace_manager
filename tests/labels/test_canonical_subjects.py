"""Tests for the complete V1 [[Label Content Snapshot]] (hub issue #215).

Three things are proved here, and they are the three the content contract
turns on. A caller names a subject and sends no values, so nothing a dialog
holds can reach paper ahead of the record it belongs to. Every one of the ten
bindings has exactly one source per context, one closed parameter set and one
thing it does when empty. And a snapshot is *taken*: the plant, the library
row, the breeder's logo, the URL configuration and the clock may all move
afterwards without changing what a retry reprints.

The fixtures travel the same path. `resolve_subject` is the production
formatter, so a typical, long-content or missing-optional preview cannot
acquire behaviour a real record lacks -- which is the only way an editor's
preview is evidence about printing rather than about the preview.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    LONG_BATCH_ITEM,
    LONG_CONTENT,
    LONG_PLANT,
    LONG_STRAIN,
    MISSING_OPTIONAL,
    NIIMBOT_B1_50X30,
    REPRESENTATIVE_FAMILIES,
    REPRESENTATIVE_SUBJECTS,
    SPARSE_BATCH_ITEM,
    SPARSE_PLANT,
    SPARSE_STRAIN,
    SUPPORTED_LOCALES,
    TYPICAL,
    TYPICAL_BATCH_ITEM,
    TYPICAL_PLANT,
    TYPICAL_STRAIN,
    ContentAbsence,
    Diagnostic,
    LabelAsset,
    Layer,
    PrintContext,
    Severity,
    SubjectFacts,
    UnsupportedLocaleError,
    async_capture_batch,
    async_capture_plant,
    async_capture_strain,
    async_render,
    compile_layout,
    format_age,
    has_blocking,
    representative_subject,
    resolve_locale,
    resolve_subject,
    stage_display_name,
    stage_started_at,
)
from custom_components.growspace_manager.labels.canonical.document import (
    validate_document,
)
from custom_components.growspace_manager.models.plant import Plant, PlantGenetics
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import NoURLAvailableError

AS_OF = datetime(2026, 9, 18, 14, 30, tzinfo=UTC)

#: A 2x2 PNG, written out so the logo tests have real bytes without a binary
#: file beside them.
_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR42m"
    "NgYGD4//8/0////xkYGAAp8gX9PG+fOwAAAABJRU5ErkJggg=="
)
_PNG_URI = f"data:image/png;base64,{_PNG}"

#: What the printer integration returns for a render, in the shape it returns
#: it. Two colours, so the result reads as the monochrome it claims to be.
_RASTER = _PNG_URI


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _hass(tmp_path: Path | None = None, url: str = "http://ha.test:8123") -> MagicMock:
    hass = MagicMock(spec=HomeAssistant)
    hass.config = MagicMock()
    hass.config.path = MagicMock(return_value=str(tmp_path or Path("/config")))
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"status": "ok"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    hass.__growspace_url = url
    return hass


def _library(**strains: dict[str, Any]) -> MagicMock:
    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(return_value=strains)
    return library


def _row(*phenotypes: str, **meta: Any) -> dict[str, Any]:
    return {"meta": meta, "phenotypes": {name: {} for name in phenotypes}}


def _plant(**overrides: Any) -> Plant:
    fields: dict[str, Any] = {
        "plant_id": "plant-1",
        "growspace_id": "tent",
        "genetics": PlantGenetics(strain_name="Blue Dream", phenotype_name="Pheno 3"),
        "stage": "flower",
        "veg_start": "2026-07-01T08:00:00+00:00",
        "flower_start": "2026-09-02T09:15:00+00:00",
    }
    fields.update(overrides)
    return Plant(**fields)


def _coordinator(*plants: Plant) -> MagicMock:
    coordinator = MagicMock()
    coordinator.plants = {plant.plant_id: plant for plant in plants}
    return coordinator


def _url(value: str = "http://ha.test:8123") -> Any:
    return patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        return_value=value,
    )


# ---------------------------------------------------------------------------
# The caller names a subject, and sends nothing else
# ---------------------------------------------------------------------------


async def test_a_strain_snapshot_comes_from_the_saved_row_and_the_named_strain(
    tmp_path: Path,
) -> None:
    library = _library(
        **{
            "Blue Dream": _row(
                "Pheno 3", breeder="Humboldt Seed Co.", lineage="Blueberry x Haze"
            )
        }
    )
    snapshot = await async_capture_strain(
        _hass(tmp_path), library, strain="Blue Dream", phenotype="Pheno 3", as_of=AS_OF
    )

    assert snapshot.context is PrintContext.STRAIN
    assert snapshot.values["strain.name"] == "Blue Dream"
    assert snapshot.values["strain.phenotype"] == "Pheno 3"
    assert snapshot.values["strain.breeder"] == "Humboldt Seed Co."
    assert snapshot.values["strain.lineage"] == "Blueberry x Haze"


async def test_no_adapter_takes_an_authoritative_field_value(tmp_path: Path) -> None:
    """A caller names a subject. Breeder, lineage, logo, URL and date are the
    backend's to resolve, and there is nowhere to submit them."""
    import inspect

    for adapter in (async_capture_strain, async_capture_plant, async_capture_batch):
        parameters = set(inspect.signature(adapter).parameters)
        assert not parameters & {
            "breeder",
            "lineage",
            "breeder_logo",
            "base_url",
            "fields",
            "values",
            "printed_on",
        }


async def test_a_plant_keeps_its_own_genetics_when_the_library_has_no_row(
    tmp_path: Path,
) -> None:
    """A plant's strain and phenotype are its identity; breeder and lineage
    are the library's, and neither borrows the other's answer."""
    with _url():
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )

    assert snapshot.values["strain.name"] == "Blue Dream"
    assert snapshot.values["strain.phenotype"] == "Pheno 3"
    assert "strain.breeder" not in snapshot.values
    assert snapshot.absence("strain.breeder") is not None
    assert snapshot.absence("strain.breeder").code == "content.source_unresolved"


async def test_a_missing_library_row_reads_differently_from_an_empty_breeder(
    tmp_path: Path,
) -> None:
    with _url():
        linked = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(**{"Blue Dream": _row(lineage="Blueberry x Haze")}),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    assert linked.absence("strain.breeder").code == "content.missing_optional"


async def test_an_unknown_plant_is_named_rather_than_printed_blank() -> None:
    with pytest.raises(HomeAssistantError, match="Plant plant-9 not found"):
        await async_capture_plant(
            _hass(), _coordinator(), _library(), plant_id="plant-9", as_of=AS_OF
        )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["default", "Default", "", "   ", "-", "–"])
async def test_a_sentinel_phenotype_normalizes_to_absence(
    tmp_path: Path, name: str
) -> None:
    """None of the stores' ways of saying "nothing recorded" may reach paper."""
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row()}),
        strain="Blue Dream",
        phenotype=name,
        as_of=AS_OF,
    )
    assert "strain.phenotype" not in snapshot.values
    assert snapshot.absence("strain.phenotype").severity is Severity.WARNING


async def test_a_whitespace_padded_value_prints_without_its_padding(
    tmp_path: Path,
) -> None:
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="  Humboldt Seed Co. ")}),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert snapshot.values["strain.breeder"] == "Humboldt Seed Co."


def test_a_subject_with_no_strain_name_blocks_the_record() -> None:
    snapshot = resolve_subject(
        SubjectFacts(context=PrintContext.STRAIN, subject="x", strain_name="   "),
        as_of=AS_OF,
    )
    assert [item.code for item in snapshot.diagnostics] == ["content.missing_required"]
    assert snapshot.diagnostics[0].severity is Severity.ERROR


# ---------------------------------------------------------------------------
# Stage, date and age
# ---------------------------------------------------------------------------


def test_the_stage_date_is_the_current_stage_s_and_no_earlier_one() -> None:
    """A flowering plant reads `flower_start`; the populated `veg_start` sitting
    beside it would date the label to a stage the plant has left."""
    assert stage_started_at(_plant()) == "2026-09-02T09:15:00+00:00"


def test_a_sub_stage_reads_the_field_of_the_stage_it_belongs_to() -> None:
    assert stage_started_at(_plant(stage="flower_late")) == "2026-09-02T09:15:00+00:00"


def test_an_empty_current_stage_field_yields_no_date_rather_than_the_previous_one() -> (
    None
):
    assert stage_started_at(_plant(flower_start=None)) is None


async def test_a_missing_stage_date_omits_both_the_date_and_the_age(
    tmp_path: Path,
) -> None:
    with _url():
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant(flower_start=None)),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    for binding in ("plant.stage_started_on", "plant.stage_and_age"):
        assert binding not in snapshot.values
        assert snapshot.absence(binding).code == "content.stage_date_missing"
        assert snapshot.absence(binding).severity is Severity.WARNING


async def test_a_future_stage_date_blocks_the_record_and_every_element_that_asked(
    tmp_path: Path,
) -> None:
    """An age cannot be negative. This record's lifecycle data is wrong, and a
    layout binding neither field would otherwise print a plausible label for
    an impossible plant."""
    with _url():
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant(flower_start="2026-09-25T09:15:00+00:00")),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )

    assert [item.code for item in snapshot.diagnostics] == [
        "content.stage_date_in_future"
    ]
    assert snapshot.diagnostics[0].severity is Severity.ERROR
    assert snapshot.absence("plant.stage_and_age").severity is Severity.ERROR


async def test_the_stage_and_age_composite_counts_whole_days_from_that_date(
    tmp_path: Path,
) -> None:
    with _url():
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    assert snapshot.resolve("plant.stage_and_age", {}) == "Flower · 16 days"


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, "Flower · 0 days"), (1, "Flower · 1 day"), (2, "Flower · 2 days")],
)
def test_day_zero_is_valid_and_only_one_day_is_singular(
    days: int, expected: str
) -> None:
    assert format_age("Flower", days) == expected


async def test_one_batch_shares_one_instant_across_local_midnight(
    tmp_path: Path,
) -> None:
    """Otherwise the age ticks over between items of one job."""
    plants = [
        _plant(plant_id="plant-1"),
        _plant(plant_id="plant-2"),
        _plant(plant_id="plant-3"),
    ]
    with _url():
        snapshots = await async_capture_batch(
            _hass(tmp_path),
            _coordinator(*plants),
            _library(),
            plant_ids=["plant-1", "plant-2", "plant-3"],
            as_of=AS_OF,
        )
    assert [item.subject for item in snapshots] == ["plant-1", "plant-2", "plant-3"]
    assert {item.as_of for item in snapshots} == {AS_OF}
    assert {item.values["plant.stage_and_age"] for item in snapshots} == {
        "Flower · 16 days"
    }


async def test_a_batch_item_is_its_own_context_with_a_plant_s_rules(
    tmp_path: Path,
) -> None:
    with _url():
        snapshots = await async_capture_batch(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_ids=["plant-1"],
            as_of=AS_OF,
        )
        single = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    assert snapshots[0].context is PrintContext.BATCH_ITEM
    assert dict(snapshots[0].values) == dict(single.values)


async def test_a_batch_refuses_a_repeated_plant_rather_than_reading_it_as_a_copy(
    tmp_path: Path,
) -> None:
    with pytest.raises(HomeAssistantError, match="more than once"):
        await async_capture_batch(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_ids=["plant-1", "plant-1"],
            as_of=AS_OF,
        )


async def test_an_empty_batch_is_refused(tmp_path: Path) -> None:
    with pytest.raises(HomeAssistantError, match="at least one plant"):
        await async_capture_batch(
            _hass(tmp_path), _coordinator(), _library(), plant_ids=[], as_of=AS_OF
        )


# ---------------------------------------------------------------------------
# Locale
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("requested", ["en-GB", "en-gb", "EN-GB", " en-GB "])
def test_a_supported_locale_resolves_to_its_catalogue_spelling(requested: str) -> None:
    assert resolve_locale(requested) == "en-GB"


def test_an_absent_locale_resolves_to_the_product_language() -> None:
    assert resolve_locale(None) == SUPPORTED_LOCALES[0] == "en"


@pytest.mark.parametrize("requested", ["de-DE", "fr", "en-XX", "klingon"])
def test_an_unsupported_locale_is_refused_rather_than_quietly_becoming_english(
    requested: str,
) -> None:
    """Printing English captions under a locale the caller believes is German
    is the failure this refuses."""
    with pytest.raises(UnsupportedLocaleError, match="not a supported print locale"):
        resolve_locale(requested)


async def test_an_unsupported_locale_fails_the_capture_rather_than_the_paper(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnsupportedLocaleError):
        await async_capture_strain(
            _hass(tmp_path),
            _library(**{"Blue Dream": _row()}),
            strain="Blue Dream",
            locale="de-DE",
            as_of=AS_OF,
        )


# ---------------------------------------------------------------------------
# QR targets
# ---------------------------------------------------------------------------


async def test_both_qr_targets_reach_the_same_configured_plant_route(
    tmp_path: Path,
) -> None:
    with _url("http://ha.test:8123"):
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )

    assert snapshot.resolve("plant.link", {"target": "dashboard_url"}) == (
        "http://ha.test:8123/growspace/plant/plant-1"
    )
    assert snapshot.resolve("plant.link", {"target": "home_assistant_app"}) == (
        "homeassistant://navigate/growspace/plant/plant-1"
    )


async def test_a_trailing_slash_on_the_configured_url_does_not_double(
    tmp_path: Path,
) -> None:
    with _url("http://ha.test:8123/"):
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    assert snapshot.resolve("plant.link", {"target": "dashboard_url"}) == (
        "http://ha.test:8123/growspace/plant/plant-1"
    )


async def test_an_unreachable_dashboard_url_blocks_the_record_that_asked_for_one(
    tmp_path: Path,
) -> None:
    with patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        side_effect=NoURLAvailableError,
    ):
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )

    assert snapshot.resolve("plant.link", {"target": "dashboard_url"}) is None
    assert snapshot.absence("plant.link").severity is Severity.ERROR
    # The app deep link needs no configured base, so it still resolves.
    assert snapshot.resolve("plant.link", {"target": "home_assistant_app"}) == (
        "homeassistant://navigate/growspace/plant/plant-1"
    )


def test_a_strain_context_link_is_unsupported_rather_than_broken() -> None:
    """No plant subject exists to target, which is a different thing from a
    plant whose route could not be built."""
    assert TYPICAL_STRAIN.snapshot(as_of=AS_OF).supports("plant.link") is False


# ---------------------------------------------------------------------------
# The breeder logo
# ---------------------------------------------------------------------------


async def test_a_stored_logo_is_captured_as_immutable_normalized_bytes(
    tmp_path: Path,
) -> None:
    logo = tmp_path / "breeder_humboldt.png"
    logo.write_bytes(base64.b64decode(_PNG))
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=str(logo))}),
        strain="Blue Dream",
        as_of=AS_OF,
    )

    asset = snapshot.assets["strain.breeder.logo"]
    assert asset.media_type == "image/png"
    assert asset.content_hash.startswith("sha256:")
    assert snapshot.resolve("strain.breeder.logo", {}).startswith(
        "data:image/png;base64,"
    )


async def test_replacing_the_logo_file_afterwards_does_not_change_the_snapshot(
    tmp_path: Path,
) -> None:
    """A retry must reprint the label the operator approved, not the one the
    breeder's new mark would produce."""
    logo = tmp_path / "breeder_humboldt.png"
    logo.write_bytes(base64.b64decode(_PNG))
    library = _library(
        **{"Blue Dream": _row(breeder="Humboldt", breeder_logo=str(logo))}
    )
    before = await async_capture_strain(
        _hass(tmp_path), library, strain="Blue Dream", as_of=AS_OF
    )

    logo.write_bytes(b"not an image at all")
    assert before.assets["strain.breeder.logo"].data_uri
    assert before.identity == replace(before).identity


async def test_a_data_uri_logo_is_captured_the_same_way_a_file_is(
    tmp_path: Path,
) -> None:
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=_PNG_URI)}),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert "strain.breeder.logo" in snapshot.assets


async def test_a_remote_url_is_refused_rather_than_fetched(tmp_path: Path) -> None:
    """It is not ours, it can change between preview and paper, and fetching
    one at print time would make a label depend on the internet."""
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(
            **{
                "Blue Dream": _row(
                    breeder="Humboldt", breeder_logo="https://cdn.test/logo.png"
                )
            }
        ),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert "strain.breeder.logo" not in snapshot.assets
    absence = snapshot.absence("strain.breeder.logo")
    assert absence.code == "content.logo_unusable"
    assert absence.parameters["reason"] == "not_integration_managed"
    assert absence.severity is Severity.WARNING


async def test_an_unreadable_logo_warns_and_paints_nothing(tmp_path: Path) -> None:
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(
            **{
                "Blue Dream": _row(
                    breeder="Humboldt", breeder_logo=str(tmp_path / "gone.png")
                )
            }
        ),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert snapshot.absence("strain.breeder.logo").parameters["reason"] == "unreadable"


async def test_a_corrupt_logo_warns_rather_than_failing_the_label(
    tmp_path: Path,
) -> None:
    logo = tmp_path / "broken.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n and then nothing")
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=str(logo))}),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert snapshot.absence("strain.breeder.logo").code == "content.logo_unusable"
    assert "strain.breeder.logo" not in snapshot.assets


async def test_an_oversized_logo_is_refused_before_it_is_decoded(
    tmp_path: Path,
) -> None:
    logo = tmp_path / "huge.png"
    logo.write_bytes(b"0" * (4 * 1024 * 1024 + 1))
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=str(logo))}),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert snapshot.absence("strain.breeder.logo").parameters["reason"] == "oversized"


async def test_logo_capture_stays_off_the_event_loop(tmp_path: Path) -> None:
    """Pillow initialises its native libraries lazily on the first decode."""
    hass = _hass(tmp_path)
    await async_capture_strain(
        hass,
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=_PNG_URI)}),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert hass.async_add_executor_job.await_count == 1


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


async def test_a_snapshot_is_unchanged_by_the_plant_it_was_taken_of(
    tmp_path: Path,
) -> None:
    plant = _plant()
    coordinator = _coordinator(plant)
    with _url():
        snapshot = await async_capture_plant(
            _hass(tmp_path), coordinator, _library(), plant_id="plant-1", as_of=AS_OF
        )
    identity = snapshot.identity

    coordinator.plants["plant-1"] = _plant(
        genetics=PlantGenetics(strain_name="Purple Haze", phenotype_name="Pheno 9"),
        stage="dry",
        dry_start="2026-09-17T09:00:00+00:00",
    )
    assert snapshot.values["strain.name"] == "Blue Dream"
    assert snapshot.identity == identity


@pytest.mark.parametrize(
    "change",
    [
        {"values": {"strain.name": "Purple Haze"}},
        {"locale": "en-US"},
        {"time_zone": "Europe/Berlin"},
        {"as_of": AS_OF + timedelta(days=1)},
        {"links": {"dashboard_url": "http://elsewhere.test/growspace/plant/plant-1"}},
        {"sources": {"strain": "Something Else"}},
        {
            "assets": {
                "strain.breeder.logo": LabelAsset(
                    asset_id="breeder-logo:other",
                    content_hash="sha256:0",
                    media_type="image/png",
                    data_uri=_PNG_URI,
                    width=2,
                    height=2,
                )
            }
        },
        {
            "absences": {
                "strain.breeder": ContentAbsence(
                    code="content.source_unresolved", severity=Severity.WARNING
                )
            }
        },
    ],
)
def test_identity_follows_every_captured_input(change: dict[str, Any]) -> None:
    snapshot = TYPICAL_PLANT.snapshot(as_of=AS_OF)
    assert replace(snapshot, **change).identity != snapshot.identity


def test_identity_does_not_follow_a_diagnostic_it_derived() -> None:
    """A diagnostic is a consequence of the captured inputs, not one of them."""
    snapshot = TYPICAL_PLANT.snapshot(as_of=AS_OF)
    assert replace(snapshot, diagnostics=()).identity == snapshot.identity


# ---------------------------------------------------------------------------
# The representative subjects
# ---------------------------------------------------------------------------


def test_every_family_has_a_fixture_for_every_context() -> None:
    for family in (TYPICAL, LONG_CONTENT, MISSING_OPTIONAL):
        for context in PrintContext:
            assert representative_subject(family, context) is not None


def test_every_fixture_is_registered_under_its_own_id() -> None:
    for fixture_id, fixture in REPRESENTATIVE_SUBJECTS.items():
        assert fixture.id == fixture_id
        assert fixture.snapshot(as_of=AS_OF).subject == fixture_id


def test_a_batch_fixture_is_its_plant_fixture_in_the_batch_context() -> None:
    """Two sets would be two sets to keep in agreement."""
    for plant, item in (
        (TYPICAL_PLANT, TYPICAL_BATCH_ITEM),
        (LONG_PLANT, LONG_BATCH_ITEM),
        (SPARSE_PLANT, SPARSE_BATCH_ITEM),
    ):
        assert item.context is PrintContext.BATCH_ITEM
        assert dict(item.snapshot(as_of=AS_OF).values) == dict(
            plant.snapshot(as_of=AS_OF).values
        )


def test_the_missing_optional_fixtures_carry_a_name_and_nothing_else() -> None:
    for fixture in (SPARSE_STRAIN, SPARSE_PLANT, SPARSE_BATCH_ITEM):
        snapshot = fixture.snapshot(as_of=AS_OF)
        assert snapshot.values["strain.name"]
        assert snapshot.assets == {}
        assert "strain.breeder" not in snapshot.values
        assert "strain.lineage" not in snapshot.values
        assert "strain.phenotype" not in snapshot.values
        assert snapshot.diagnostics == ()


def test_the_long_fixtures_are_longer_than_the_typical_ones_everywhere() -> None:
    typical = TYPICAL_STRAIN.snapshot(as_of=AS_OF)
    long_content = LONG_STRAIN.snapshot(as_of=AS_OF)
    for binding in (
        "strain.name",
        "strain.phenotype",
        "strain.breeder",
        "strain.lineage",
    ):
        assert len(long_content.values[binding]) > len(typical.values[binding])


def test_a_fixture_resolves_through_the_production_formatter() -> None:
    """Not example strings maintained beside the renderer: the same captions,
    dates and composites a record gets."""
    snapshot = TYPICAL_PLANT.snapshot(as_of=AS_OF)
    assert snapshot.resolve("strain.lineage", {"presentation": "labeled"}) == (
        "Lineage: Blueberry x Haze"
    )
    assert snapshot.resolve("plant.stage_and_age", {}) == "Flower · 16 days"
    assert snapshot.resolve("print.date", {"date_style": "iso"}) == "2026-09-18"


def test_a_fixture_says_which_catalogue_version_it_came_from() -> None:
    assert TYPICAL_PLANT.snapshot(as_of=AS_OF).source == "growspace.label-fixtures.v2"


def test_a_fixture_can_be_previewed_in_any_supported_locale() -> None:
    localized = TYPICAL_PLANT.snapshot(as_of=AS_OF, locale="en-US")
    assert localized.resolve("print.date", {"date_style": "short"}) == "9/18/2026"


# ---------------------------------------------------------------------------
# Every fixture through the production renderer
# ---------------------------------------------------------------------------


def _layout_with_every_binding() -> Any:
    """A layout binding all ten v1 bindings, so nothing goes unexercised."""

    def text(
        element_id: str,
        binding: str,
        parameters: dict[str, str],
        y_mm: float,
    ) -> dict[str, Any]:
        return {
            "id": element_id,
            "kind": "text",
            "frame": {
                "x_mm": 2.0,
                "y_mm": y_mm,
                "width_mm": 30.0,
                "height_mm": 3.0,
            },
            "rotation": 0,
            "content": {"binding": binding, "parameters": parameters},
            "style": {
                "font": "growspace.sans.regular.v1",
                "font_size_mm": 2.4,
                "horizontal_align": "left",
                "vertical_align": "center",
                "line_spacing": "growspace.spacing.compact.v1",
                "overflow": "shrink_ellipsis",
                "minimum_font_size_mm": 1.6,
                "maximum_lines": 1,
            },
        }

    document = {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": "growspace.stock.50x30.v1",
        "elements": [
            text("element-name", "strain.name", {}, 1.0),
            text("element-pheno", "strain.phenotype", {"presentation": "value"}, 4.5),
            text("element-breeder", "strain.breeder", {"presentation": "labeled"}, 8.0),
            text(
                "element-lineage", "strain.lineage", {"presentation": "labeled"}, 11.5
            ),
            text(
                "element-started",
                "plant.stage_started_on",
                {"presentation": "labeled", "date_style": "iso"},
                15.0,
            ),
            text("element-age", "plant.stage_and_age", {}, 18.5),
            text("element-id", "plant.id", {"presentation": "labeled"}, 22.0),
            text("element-printed", "print.date", {"date_style": "medium"}, 25.5),
            {
                "id": "element-logo",
                "kind": "logo",
                "frame": {
                    "x_mm": 34.0,
                    "y_mm": 1.0,
                    "width_mm": 10.0,
                    "height_mm": 10.0,
                },
                "rotation": 0,
                "content": {"binding": "strain.breeder.logo", "parameters": {}},
                "style": {
                    "monochrome": "growspace.mono.threshold.v1",
                    "fit": "contain",
                },
            },
            {
                "id": "element-qr",
                "kind": "qr",
                "frame": {
                    "x_mm": 34.0,
                    "y_mm": 13.0,
                    "width_mm": 12.0,
                    "height_mm": 12.0,
                },
                "rotation": 0,
                "content": {
                    "binding": "plant.link",
                    "parameters": {"target": "dashboard_url"},
                },
                "style": {"error_correction": "medium", "quiet_zone_modules": 4},
            },
        ],
    }
    validation = validate_document(document)
    assert validation.diagnostics == ()
    return validation.layout


EVERY_BINDING = _layout_with_every_binding()


@pytest.mark.parametrize("fixture_id", sorted(REPRESENTATIVE_SUBJECTS))
def test_every_fixture_compiles_through_the_production_compiler(
    fixture_id: str,
) -> None:
    """Whatever it is missing, a frame is preserved for every element and an
    outcome is reported for every stable ID."""
    snapshot = REPRESENTATIVE_SUBJECTS[fixture_id].snapshot(as_of=AS_OF)
    compiled = compile_layout(EVERY_BINDING, snapshot, NIIMBOT_B1_50X30)

    assert [item.element_id for item in compiled.outcomes] == [
        element.id for element in EVERY_BINDING.elements
    ]
    assert all(item.pixel_frame is not None for item in compiled.outcomes)


def test_a_typical_plant_fills_all_ten_bindings() -> None:
    compiled = compile_layout(
        EVERY_BINDING, TYPICAL_PLANT.snapshot(as_of=AS_OF), NIIMBOT_B1_50X30
    )
    assert {item.status for item in compiled.outcomes} == {"placed"}
    assert compiled.diagnostics == ()


def test_a_strain_leaves_the_plant_only_frames_empty_and_says_why() -> None:
    compiled = compile_layout(
        EVERY_BINDING, TYPICAL_STRAIN.snapshot(as_of=AS_OF), NIIMBOT_B1_50X30
    )
    by_element = {item.element_id: item.status for item in compiled.outcomes}
    assert by_element["element-started"] == "omitted_unsupported_context"
    assert by_element["element-age"] == "omitted_unsupported_context"
    assert by_element["element-id"] == "omitted_unsupported_context"
    assert by_element["element-qr"] == "omitted_unsupported_context"
    assert by_element["element-name"] == "placed"
    assert {item.severity for item in compiled.diagnostics} == {Severity.WARNING}


def test_a_missing_optional_subject_prints_its_name_and_warns_about_the_rest() -> None:
    compiled = compile_layout(
        EVERY_BINDING, SPARSE_PLANT.snapshot(as_of=AS_OF), NIIMBOT_B1_50X30
    )
    by_element = {item.element_id: item.status for item in compiled.outcomes}
    assert by_element["element-name"] == "placed"
    assert by_element["element-breeder"] == "omitted_missing_content"
    assert by_element["element-logo"] == "omitted_missing_content"
    assert by_element["element-qr"] == "placed"
    assert not any(item.severity is Severity.ERROR for item in compiled.diagnostics)


def test_every_family_and_context_pair_is_distinct() -> None:
    """An editor switching family or context must be looking at something else."""
    identities = {
        fixture.snapshot(as_of=AS_OF).identity
        for family in REPRESENTATIVE_FAMILIES.values()
        for fixture in family.values()
    }
    assert len(identities) == len(REPRESENTATIVE_SUBJECTS)


def test_a_record_level_error_reaches_a_layout_that_binds_nothing_to_it() -> None:
    """The factory layout carries no stage field at all, and a plausible label
    for an impossible plant is exactly what must not print."""
    impossible = replace(
        TYPICAL_PLANT.snapshot(as_of=AS_OF),
        diagnostics=(
            Diagnostic(
                code="content.stage_date_in_future",
                severity=Severity.ERROR,
                layer=Layer.CONTENT,
                message="entered flower after the day it is being printed on",
            ),
        ),
    )
    compiled = compile_layout(FACTORY_50X30.layout, impossible, NIIMBOT_B1_50X30)

    assert compiled.diagnostics[0].code == "content.stage_date_in_future"
    assert has_blocking(compiled.diagnostics)


def test_the_record_s_own_diagnostics_are_read_before_any_element_s() -> None:
    """Errors are read top-down, and "this record cannot print" outranks
    "this frame is empty"."""
    compiled = compile_layout(
        EVERY_BINDING,
        resolve_subject(
            SubjectFacts(
                context=PrintContext.PLANT,
                subject="plant-1",
                strain_name="",
                plant_id="plant-1",
                stage="flower",
                stage_started_at="2026-09-02T09:15:00+00:00",
                links={"dashboard_url": "http://ha.test/growspace/plant/plant-1"},
            ),
            as_of=AS_OF,
        ),
        NIIMBOT_B1_50X30,
    )
    assert compiled.diagnostics[0].code == "content.missing_required"
    assert compiled.diagnostics[0].element_id is None


async def test_an_unsaved_strain_is_refused_rather_than_printed_from_its_name(
    tmp_path: Path,
) -> None:
    """The name is a reference. Accepting one the library does not know would
    be the caller supplying the value the label prints."""
    with pytest.raises(HomeAssistantError, match="not in the strain library"):
        await async_capture_strain(
            _hass(tmp_path), _library(), strain="Blue Dreem", as_of=AS_OF
        )


async def test_an_unsaved_phenotype_is_refused_the_same_way(tmp_path: Path) -> None:
    with pytest.raises(HomeAssistantError, match="not saved for this strain"):
        await async_capture_strain(
            _hass(tmp_path),
            _library(**{"Blue Dream": _row("Pheno 3")}),
            strain="Blue Dream",
            phenotype="Pheno 9",
            as_of=AS_OF,
        )


async def test_a_selected_phenotype_is_recorded_as_a_source(tmp_path: Path) -> None:
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row("Pheno 3")}),
        strain="Blue Dream",
        phenotype="Pheno 3",
        as_of=AS_OF,
    )
    assert snapshot.sources == {"strain": "Blue Dream", "phenotype": "Pheno 3"}


async def test_a_later_url_change_does_not_move_a_captured_route(
    tmp_path: Path,
) -> None:
    """Both forms are captured, so a template edited tomorrow to prefer the
    app deep link reprints against the snapshot rather than against whatever
    the URL configuration has become by then."""
    with _url("http://ha.test:8123"):
        snapshot = await async_capture_plant(
            _hass(tmp_path),
            _coordinator(_plant()),
            _library(),
            plant_id="plant-1",
            as_of=AS_OF,
        )
    identity = snapshot.identity

    with _url("https://moved.example"):
        assert snapshot.resolve("plant.link", {"target": "dashboard_url"}) == (
            "http://ha.test:8123/growspace/plant/plant-1"
        )
    assert snapshot.identity == identity


@pytest.mark.parametrize("fixture_id", sorted(REPRESENTATIVE_SUBJECTS))
async def test_every_fixture_renders_through_the_production_renderer(
    fixture_id: str,
) -> None:
    """Not a CSS approximation maintained beside the renderer: the bitmap the
    printer driver would receive, for the content an editor is looking at."""
    hass = _hass()
    hass.services.async_call = AsyncMock(return_value={"image": _RASTER})
    result = await async_render(
        hass,
        layout=EVERY_BINDING,
        content=REPRESENTATIVE_SUBJECTS[fixture_id].snapshot(as_of=AS_OF),
        profile=NIIMBOT_B1_50X30,
    )

    assert result.status == "current"
    assert result.raster is not None
    assert result.context.content_identity.startswith("sha256:")
    assert result.context.content_source == "growspace.label-fixtures.v2"
    assert not any(item.severity is Severity.ERROR for item in result.diagnostics)


@pytest.mark.parametrize("stage", ["", None, "hibernating"])
def test_a_stage_the_registry_does_not_know_carries_no_date(stage: str | None) -> None:
    """A name nothing defines a start field for is not a date this label can
    invent one for."""
    assert stage_started_at(_plant(stage=stage)) is None
    assert stage_display_name(stage) is None


def test_a_plant_with_no_route_at_all_blocks_the_qr_that_asked_for_one() -> None:
    snapshot = resolve_subject(
        SubjectFacts(
            context=PrintContext.PLANT,
            subject="plant-1",
            strain_name="Blue Dream",
            plant_id="plant-1",
        ),
        as_of=AS_OF,
    )
    assert snapshot.absence("plant.link").code == "content.qr_target_unavailable"
    assert snapshot.absence("plant.link").severity is Severity.ERROR


async def test_a_local_logo_path_resolves_under_the_config_directory(
    tmp_path: Path,
) -> None:
    """The one shape an imported library writes, and still an asset this
    integration owns rather than a URL it would have to fetch."""
    (tmp_path / "www" / "growspace_manager").mkdir(parents=True)
    logo = tmp_path / "www" / "growspace_manager" / "breeder.png"
    logo.write_bytes(base64.b64decode(_PNG))
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(
            **{
                "Blue Dream": _row(
                    breeder="Humboldt",
                    breeder_logo="/local/growspace_manager/breeder.png",
                )
            }
        ),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert "strain.breeder.logo" in snapshot.assets


async def test_a_data_uri_that_is_not_base64_warns_rather_than_raising(
    tmp_path: Path,
) -> None:
    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(
            **{
                "Blue Dream": _row(
                    breeder="Humboldt", breeder_logo="data:image/png;base64,not base64"
                )
            }
        ),
        strain="Blue Dream",
        as_of=AS_OF,
    )
    assert snapshot.absence("strain.breeder.logo").parameters["reason"] == "unreadable"


async def test_a_transparent_logo_is_composited_onto_white(tmp_path: Path) -> None:
    """Transparency saved straight to a monochrome raster prints as black,
    which turns a wordmark into a filled rectangle."""
    transparent = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    transparent.putpixel((0, 0), (0, 0, 0, 255))
    buffer = BytesIO()
    transparent.save(buffer, format="PNG")
    logo = tmp_path / "wordmark.png"
    logo.write_bytes(buffer.getvalue())

    snapshot = await async_capture_strain(
        _hass(tmp_path),
        _library(**{"Blue Dream": _row(breeder="Humboldt", breeder_logo=str(logo))}),
        strain="Blue Dream",
        as_of=AS_OF,
    )

    captured = snapshot.assets["strain.breeder.logo"]
    with Image.open(
        BytesIO(base64.b64decode(captured.data_uri.split(",", 1)[1]))
    ) as image:
        assert image.mode == "RGB"
        assert image.getpixel((3, 3)) == (255, 255, 255)
        assert image.getpixel((0, 0)) == (0, 0, 0)
