"""Tests for Classic requests painted through the canonical compiler (hub #240).

Four promises, each one a condition hub #232 names for deleting the fixed
renderer:

1. **Byte-identical.** Every legacy Label Size crossed with every combination
   of the five visibility flags compiles, through `compile_layout`, to the
   exact raster inputs the fixed renderer paints -- and to the reviewed golden
   recorded for it.
2. **Transient.** The compatibility layout, snapshot and profile are never
   Template state and can never become it: the layout does not validate, the
   profile authorizes nothing, and a Classic print writes nothing to storage.
3. **Explicit about hardware.** A printer whose driver cannot take the raster
   or the density is refused by name before anything is sent.
4. **Still Classic.** The response is the printer integration's, untouched.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.labels import (
    PRINTER_LIMITS,
    PrinterLimits,
    printer_limits,
)
from custom_components.growspace_manager.labels.canonical import (
    PROFILES,
    PrintContext,
    Severity,
    digest,
    preview,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.compatibility import (
    CLASSIC_BINDINGS,
    CLASSIC_CANVASES,
    DETAILS,
    FIELD_FLAGS,
    TITLE,
    ClassicLogoStyle,
    compatibility_layout,
    compatibility_profile,
    compatibility_snapshot,
    layout_id,
    visible_fields,
)
from custom_components.growspace_manager.labels.classic import (
    CLASSIC_PRINTHEAD_OVERHANG,
    async_compatibility_print,
    compile_classic,
    resolve_classic_request,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .classic_golden import (
    FROZEN_NOW,
    INTERNAL_URL,
    ClassicCase,
    async_canonical_inputs,
    async_fixed_inputs,
    classic_cases,
    current_identity,
    load_manifest,
    load_payloads,
    png_path,
)

CASES = classic_cases()
ALL_FIELDS = frozenset(FIELD_FLAGS)


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_manifest()


# ---------------------------------------------------------------------------
# 1. Byte-identical, for every legacy size and every combination of flags
# ---------------------------------------------------------------------------


def test_the_matrix_is_every_size_crossed_with_every_flag_combination() -> None:
    assert len(CASES) == len(CLASSIC_CANVASES) * 2 ** len(FIELD_FLAGS) == 160
    assert len({case.id for case in CASES}) == len(CASES)


def test_the_goldens_cover_exactly_the_matrix(manifest: dict[str, Any]) -> None:
    """A size or flag added without recording its goldens is a silent gap."""
    assert sorted(manifest["cases"]) == sorted(case.id for case in CASES)
    assert sorted(load_payloads()) == sorted(case.id for case in CASES)


def test_the_goldens_were_recorded_under_the_current_identities(
    manifest: dict[str, Any],
) -> None:
    """A moved identity means the goldens have to be recorded -- and reviewed -- again."""
    assert manifest["identity"] == current_identity()
    assert manifest["history"][-1]["reviewer"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_every_classic_layout_compiles_to_its_golden_raster(
    case: ClassicCase, manifest: dict[str, Any]
) -> None:
    with freeze_time(FROZEN_NOW):
        inputs = await async_canonical_inputs(case)

    assert digest(inputs) == manifest["cases"][case.id]["raster_inputs"]
    assert inputs == load_payloads()[case.id]
    image = png_path(case.id).read_bytes()
    assert (
        f"sha256:{hashlib.sha256(image).hexdigest()}"
        == manifest["cases"][case.id]["png_sha256"]
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
async def test_the_fixed_renderer_paints_every_golden_byte_for_byte(
    case: ClassicCase,
) -> None:
    """The deletion proof: the retired renderer and the compiler agree exactly."""
    with freeze_time(FROZEN_NOW):
        canonical = await async_canonical_inputs(case)
    assert json.dumps(canonical, sort_keys=True) == json.dumps(
        await async_fixed_inputs(case), sort_keys=True
    )


# ---------------------------------------------------------------------------
# 2. Transient: never Template state, and unable to become it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", CLASSIC_CANVASES)
def test_no_compatibility_layout_is_a_valid_label_layout(size: str) -> None:
    """The document schema refuses it, so no Template can ever be one."""
    validation = validate_document(compatibility_layout(size, ALL_FIELDS).as_dict())

    assert validation.layout is None
    assert any(item.severity is Severity.ERROR for item in validation.diagnostics)


def test_a_compatibility_layout_binds_only_the_private_namespace() -> None:
    bound = {
        element.content.binding
        for element in compatibility_layout("50x30", ALL_FIELDS).elements
        if element.content is not None
    }
    assert bound <= CLASSIC_BINDINGS


@pytest.mark.parametrize("size", CLASSIC_CANVASES)
def test_a_compatibility_profile_authorizes_nothing(size: str) -> None:
    profile = compatibility_profile(size)

    assert profile.id not in PROFILES
    assert not profile.authorizes_production
    assert profile.device_models == ()
    assert not profile.covers_device_model("B1")


def test_layout_identities_are_versioned_and_name_what_they_show() -> None:
    assert layout_id("50x15", frozenset({"qr", "phenotype"})) == (
        "growspace.classic-layout.v1/50x15/phenotype+qr"
    )
    assert layout_id("50x30", frozenset()) == "growspace.classic-layout.v1/50x30/none"
    assert visible_fields(None) == ALL_FIELDS
    assert visible_fields({"logo": False, "unknown": False}) == ALL_FIELDS - {"logo"}


def test_the_classic_styles_have_wire_forms() -> None:
    """Every Classic element serializes, so a layout can be digested and logged."""
    layout = compatibility_layout("50x30", ALL_FIELDS)
    styles = {element.id: element.style.as_dict() for element in layout.elements}

    assert styles["title"]["classic"] == "text"
    assert styles["title"]["uppercase"] is True
    assert styles["printed_on"]["classic"] == "line"
    assert styles["qr"] == {"classic": "qr", "boxsize": 3}
    assert ClassicLogoStyle().as_dict() == {"classic": "logo"}
    assert layout.digest.startswith("sha256:")


def test_the_compatibility_snapshot_answers_only_classic_bindings() -> None:
    snapshot = compatibility_snapshot(
        context=PrintContext.STRAIN,
        subject="Gelato",
        as_of=None,
        values={TITLE: "Gelato", "classic.breeder": "Cookies", "classic.logo": None},
    )

    assert snapshot.source == "classic"
    assert snapshot.supports(TITLE)
    assert not snapshot.supports("strain.name")
    assert snapshot.absence("strain.name") is None
    assert snapshot.absence("classic.logo").severity is Severity.WARNING
    assert snapshot.resolve("classic.logo", {}) is None
    # Unknown line names are ignored, and no `lines` parameter selects nothing.
    assert snapshot.resolve(DETAILS, {"lines": "breeder,colour"}) == "Cookies"
    assert snapshot.resolve(DETAILS, {}) == ""


def _world(
    *, plants: dict[str, Any] | None = None
) -> tuple[MagicMock, MagicMock, MagicMock]:
    hass = MagicMock(spec=HomeAssistant)
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock(return_value={"image": "data:image/png;x"})
    hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *a: func(*a))
    coordinator = MagicMock()
    coordinator.plants = plants or {}
    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(return_value={})
    return hass, coordinator, library


async def test_a_classic_print_saves_nothing_anywhere() -> None:
    """No revision, draft, default or export entry -- not even a store write."""
    hass, coordinator, library = _world()
    with (
        patch(
            "homeassistant.helpers.storage.Store.async_save",
            side_effect=AssertionError("a Classic print wrote to storage"),
        ),
        patch(
            "homeassistant.helpers.storage.Store.async_delay_save",
            side_effect=AssertionError("a Classic print wrote to storage"),
        ),
    ):
        await async_compatibility_print(
            hass, coordinator, library, {"strain": "Gelato", "preview": True}
        )

    assert {call[0] for call in library.mock_calls} == {"load", "get_all"}


async def test_the_response_is_the_printer_integrations_untouched() -> None:
    """Old cards read the legacy response; nothing canonical is added to it."""
    hass, coordinator, library = _world()
    response = await async_compatibility_print(
        hass, coordinator, library, {"strain": "Gelato", "preview": True}
    )
    assert response == {"image": "data:image/png;x"}


async def test_a_classic_print_logs_its_audit_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    hass, coordinator, library = _world()
    with caplog.at_level("INFO"):
        await async_compatibility_print(
            hass, coordinator, library, {"strain": "Gelato", "label_size": "50x15"}
        )
    assert "layout growspace.classic-layout.v1/50x15/" in caplog.text
    assert "content sha256:" in caplog.text
    assert "raster sha256:" in caplog.text


async def test_a_layout_that_does_not_compile_is_an_error_not_a_partial_label() -> None:
    hass, coordinator, library = _world()
    request = await resolve_classic_request(
        hass, coordinator, library, {"strain": "Gelato"}
    )
    with pytest.raises(HomeAssistantError, match="profile.unsupported_density"):
        compile_classic(replace(request, density="scorching"))


async def test_an_unrecognised_density_keeps_the_classic_default() -> None:
    hass, coordinator, library = _world()
    request = await resolve_classic_request(
        hass, coordinator, library, {"strain": "Gelato", "density": "scorching"}
    )
    assert request.density == "normal"


async def test_a_qr_code_switched_off_never_asks_for_a_url() -> None:
    """The web route needs Home Assistant's URL; a label without a QR does not."""
    hass, coordinator, library = _world(
        plants={
            "p1": SimpleNamespace(
                genetics=SimpleNamespace(strain_name="Gelato", phenotype_name=None)
            )
        }
    )
    with patch(
        "custom_components.growspace_manager.labels.classic.get_url",
        side_effect=AssertionError("asked for a URL"),
    ):
        request = await resolve_classic_request(
            hass, coordinator, library, {"plant_id": "p1", "fields": {"qr": False}}
        )
    assert request.content.context is PrintContext.PLANT


# ---------------------------------------------------------------------------
# 3. Explicit about hardware
# ---------------------------------------------------------------------------


def _printer(monkeypatch: pytest.MonkeyPatch, model: str | None) -> None:
    monkeypatch.setattr(preview, "device_model", lambda _hass, _device_id: model)


async def _print(data: dict[str, Any]) -> MagicMock:
    hass, coordinator, library = _world()
    with patch(
        "custom_components.growspace_manager.labels.classic.get_url",
        return_value=INTERNAL_URL,
    ):
        await async_compatibility_print(
            hass, coordinator, library, {"strain": "Gelato", **data}
        )
    return hass.services.async_call


@pytest.mark.parametrize("size", ["50x30", "50x50", "50x80", "50x15"])
@pytest.mark.parametrize("density", ["low", "normal"])
async def test_a_b1_keeps_printing_every_50mm_classic_label(
    monkeypatch: pytest.MonkeyPatch, size: str, density: str
) -> None:
    """400 pixels on a 384-dot head is the accepted legacy overhang."""
    _printer(monkeypatch, "B1")
    sent = await _print(
        {"device_id": "printer", "label_size": size, "density": density}
    )
    assert sent.await_count == 1
    assert 400 - PRINTER_LIMITS["B1"].printhead_pixels == CLASSIC_PRINTHEAD_OVERHANG


@pytest.mark.parametrize("preview_only", [False, True])
async def test_a_density_the_printer_rejects_is_refused_before_it_is_sent(
    monkeypatch: pytest.MonkeyPatch, preview_only: bool
) -> None:
    """Classic `high` is 8, and a B1 takes 1-5. Preview answers as the print would."""
    _printer(monkeypatch, "B1")
    hass, coordinator, library = _world()
    with pytest.raises(
        ServiceValidationError, match=r"level 8, and the B1 accepts 1-5"
    ):
        await async_compatibility_print(
            hass,
            coordinator,
            library,
            {
                "strain": "Gelato",
                "device_id": "printer",
                "density": "high",
                "preview": preview_only,
            },
        )
    hass.services.async_call.assert_not_awaited()


@pytest.mark.parametrize(
    ("model", "size"),
    [
        ("D110", "50x30"),
        ("D110", "40x30"),
        ("D11", "50x15"),
        ("B18", "50x80"),
        ("D101", "40x30"),
    ],
)
async def test_a_raster_the_printhead_cannot_carry_is_refused(
    monkeypatch: pytest.MonkeyPatch, model: str, size: str
) -> None:
    _printer(monkeypatch, model)
    hass, coordinator, library = _world()
    with pytest.raises(ServiceValidationError, match=rf"the {model} printhead is"):
        await async_compatibility_print(
            hass,
            coordinator,
            library,
            {"strain": "Gelato", "device_id": "printer", "label_size": size},
        )
    hass.services.async_call.assert_not_awaited()


async def test_a_printer_whose_range_starts_above_classic_low_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _printer(monkeypatch, "B11")
    hass, coordinator, library = _world()
    with pytest.raises(ServiceValidationError, match="accepts 6-15"):
        await async_compatibility_print(
            hass,
            coordinator,
            library,
            {"strain": "Gelato", "device_id": "printer", "density": "low"},
        )


@pytest.mark.parametrize("model", [None, "SOMETHING_NEW"])
async def test_a_printer_nobody_has_limits_for_is_sent_as_it_always_was(
    monkeypatch: pytest.MonkeyPatch, model: str | None
) -> None:
    """Refusing an unknown model would be a guess, not a safety correction."""
    _printer(monkeypatch, model)
    sent = await _print({"device_id": "printer", "density": "high"})
    assert sent.await_count == 1


async def test_no_printer_named_is_never_looked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def looked_up(_hass: Any, _device_id: str) -> str:
        raise AssertionError("looked up a printer nobody named")

    monkeypatch.setattr(preview, "device_model", looked_up)
    sent = await _print({"density": "high"})
    assert sent.await_count == 1


def test_printer_limits_are_the_drivers_own() -> None:
    assert printer_limits(None) is None
    assert printer_limits("NOPE") is None
    assert printer_limits("D110") == PrinterLimits(96, 1, 3)
    assert PrinterLimits(384, 1, 5).accepts_density(5)
    assert not PrinterLimits(384, 1, 5).accepts_density(8)
    assert not PrinterLimits(384, 6, 15).accepts_density(3)
