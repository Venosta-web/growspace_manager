"""Production Label Template service coverage (workspace issue #241)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.labels.calibration import (
    IncompatibleCalibrationStore,
    LocalCalibrationLedger,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    Blocker,
    factory_template_for_size,
    profiles as profile_catalogue,
)
from custom_components.growspace_manager.labels.capability import contract_identity
from custom_components.growspace_manager.labels.library import (
    FACTORY,
    LabelTemplateLibrary,
    TemplateNotResolvable,
)
from custom_components.growspace_manager.labels.niimbot import (
    NIIMBOT_DOMAIN,
    NIIMBOT_PRINT_SERVICE,
)
from custom_components.growspace_manager.labels.printing import PrintRefused
from custom_components.growspace_manager.models import Plant, PlantGenetics
from custom_components.growspace_manager.schemas import PRINT_LABEL_TEMPLATE_SCHEMA
from custom_components.growspace_manager.service_registration import register_services
from custom_components.growspace_manager.services import label_templates
from custom_components.growspace_manager.websocket import label_printing
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from homeassistant.core import (
    Context,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, Unauthorized
from tests.labels.support import product_verified, provisional

from .conftest import ADMIN, _one_bit_png

PROFILE = NIIMBOT_B1_50X30
VERIFIED = product_verified(PROFILE)
SIZE = PROFILE.label_size_id
FACTORY_ID = factory_template_for_size(SIZE).id
DEVICE = "printer-a"
ENTRY_ID = "entry-a"

STRAINS = {
    "Blue Dream": {
        "meta": {"breeder": "Humboldt", "lineage": "Blueberry x Haze"},
        "phenotypes": {"#1": {}},
    }
}


class _StrainLibrary:
    async def load(self) -> None:
        return None

    def get_all(self) -> dict[str, Any]:
        return STRAINS


def _plant(plant_id: str, *, phenotype: str = "#1") -> Plant:
    return Plant(
        plant_id=plant_id,
        growspace_id="tent",
        genetics=PlantGenetics(strain_name="Blue Dream", phenotype_name=phenotype),
        stage="flower",
        veg_start="2026-07-01T08:00:00+00:00",
        flower_start="2026-09-02T09:15:00+00:00",
    )


COORDINATOR = SimpleNamespace(
    config_entry=SimpleNamespace(entry_id=ENTRY_ID),
    plants={item.plant_id: item for item in (_plant("A"), _plant("B"))},
    services=SimpleNamespace(config=SimpleNamespace(strain_library=_StrainLibrary())),
)
ADMIN_USER = SimpleNamespace(id=ADMIN, is_admin=True)


def _call(**data: Any) -> ServiceCall:
    payload: dict[str, Any] = {
        "template": {"kind": FACTORY, "id": FACTORY_ID},
        "strain": "Blue Dream",
        "phenotype": "#1",
        "device_id": DEVICE,
        "density": "normal",
        "locale": "en",
    }
    payload.update(data)
    payload = {key: value for key, value in payload.items() if value is not None}
    return ServiceCall(
        None,
        domain=DOMAIN,
        service="print_label_template",
        data=payload,
        context=Context(),
    )


async def _calibrated(hass: HomeAssistant, printer: list[dict[str, Any]]) -> None:
    actor = {WS_MSG_USER: ADMIN_USER, "contract": contract_identity()}
    sheet = await label_printing.websocket_print_label_calibration_sheet(
        hass,
        COORDINATOR,
        {
            **actor,
            "profile_id": PROFILE.id,
            "device_id": DEVICE,
            "density": "normal",
        },
    )
    await label_printing.websocket_record_label_calibration(
        hass,
        COORDINATOR,
        {
            **actor,
            "sheet_id": sheet["sheet_id"],
            "measurement": {
                "top_mm": 0.5,
                "right_mm": 0.5,
                "bottom_mm": 0.0,
                "left_mm": 0.5,
                "feed_mm": -0.4,
            },
        },
    )
    printer.clear()


def _committed(printer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in printer if not call["preview"]]


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(profile_catalogue, "PROFILES", {VERIFIED.id: VERIFIED})


@pytest.fixture(autouse=True)
def _url():
    with patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        return_value="http://ha.test:8123",
    ):
        yield


def test_schema_accepts_no_legacy_content_or_preview_fields() -> None:
    valid = {
        "label_size_id": SIZE,
        "strain": "Blue Dream",
        "device_id": DEVICE,
    }
    assert PRINT_LABEL_TEMPLATE_SCHEMA(valid)["density"] == "normal"
    for field in ("base_url", "breeder", "lineage", "breeder_logo", "preview"):
        with pytest.raises(Exception, match="extra keys not allowed"):
            PRINT_LABEL_TEMPLATE_SCHEMA({**valid, field: "value"})


@pytest.mark.parametrize(
    "change",
    [
        {"template": {"kind": FACTORY, "id": FACTORY_ID}},
        {"plant_ids": ["A"]},
        {"phenotype": "#1", "strain": None},
    ],
)
def test_schema_requires_one_template_choice_and_one_subject(
    change: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "label_size_id": SIZE,
        "strain": "Blue Dream",
        "device_id": DEVICE,
    }
    payload.update(change)
    if payload.get("strain") is None:
        payload.pop("strain")
    with pytest.raises(Exception):
        PRINT_LABEL_TEMPLATE_SCHEMA(payload)


def test_named_templates_become_published_revision_sources() -> None:
    resolved = SimpleNamespace(
        ref=SimpleNamespace(kind="named", id="named-template"),
        layout=factory_template_for_size(SIZE).layout,
        revision=4,
    )

    source = label_templates._source_of(resolved)

    assert source.reference == "revision:named-template@4"
    assert source.published is True


@pytest.mark.parametrize(
    ("blocker", "recovery"),
    [
        (Blocker.NO_RASTER, "retry_preview"),
        (Blocker.BLOCKING_DIAGNOSTICS, "fix_layout"),
        (Blocker.REVISION_NOT_PUBLISHED, "publish"),
        (Blocker.PROFILE_NOT_PRODUCT_VERIFIED, "select_profile"),
        (Blocker.LOCAL_CALIBRATION_MISSING, "calibrate"),
        (Blocker.LOCAL_CALIBRATION_STALE, "calibrate"),
        (Blocker.RESULT_NOT_CURRENT, "refresh_preview"),
        (Blocker.PREFLIGHT_NOT_CURRENT, "preflight_again"),
        (Blocker.WARNING_ACKNOWLEDGEMENT_REQUIRED, "acknowledge_warnings"),
    ],
)
def test_every_print_blocker_names_the_same_recovery_as_websocket(
    blocker: Blocker, recovery: str
) -> None:
    assert label_templates._recovery_for((str(blocker),)) == recovery
    assert label_templates._recovery_for(("content_not_actual",)) == "none"


async def test_an_unattributed_automation_prints_a_strain_with_the_size_default(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    call = _call(template=None, label_size_id=SIZE)

    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), call
    )

    assert result["outcome"] == "ok"
    assert result["template"]["via"] == "factory_fallback"
    assert result["subject"] == "Blue Dream"
    assert result["print"]["operation"] == "single_print"
    assert len(_committed(printer)) == 1


async def test_the_registered_home_assistant_service_returns_its_print_result(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    with patch.object(
        GrowspaceCoordinator, "get_for_service_call", return_value=COORDINATOR
    ):
        await register_services(hass, _StrainLibrary())
        result = await hass.services.async_call(
            DOMAIN,
            "print_label_template",
            {
                "label_size_id": SIZE,
                "plant_ids": ["A"],
                "device_id": DEVICE,
            },
            blocking=True,
            return_response=True,
        )

    assert result is not None
    assert result["outcome"] == "ok"
    assert result["batch"]["attempts"][0]["status"] == "printed"


async def test_an_unattributed_automation_prints_all_plants_after_one_preflight(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    call = _call(strain=None, phenotype=None, plant_ids=["A", "B"])

    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), call
    )

    assert result["outcome"] == "ok"
    assert [item["subject"] for item in result["batch"]["attempts"]] == ["A", "B"]
    assert {item["status"] for item in result["batch"]["attempts"]} == {"printed"}
    assert len(_committed(printer)) == 2


@pytest.mark.parametrize(
    ("overrides", "code", "recovery"),
    [
        ({"device_id": " "}, "label_template.printer_required", "choose_printer"),
        ({"locale": "xx"}, "label_template.unsupported_locale", "none"),
        (
            {"template": {"kind": "named", "id": "missing"}},
            "label_template.template_not_found",
            "choose_template",
        ),
        (
            {"profile_id": "growspace.profile.nobody.v1"},
            "label_template.unknown_profile",
            "select_profile",
        ),
        (
            {"strain": "Missing", "phenotype": None},
            "label_template.unknown_subject",
            "choose_subject",
        ),
    ],
)
async def test_invalid_service_choices_return_structured_refusals(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    overrides: dict[str, Any],
    code: str,
    recovery: str,
) -> None:
    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call(**overrides)
    )

    assert result["outcome"] == "refused"
    assert result["refusal"]["code"] == code
    assert result["refusal"]["recovery"] == recovery
    assert _committed(printer) == []


async def test_provisional_or_uncalibrated_profiles_name_the_eligibility_blocker(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        profile_catalogue, "PROFILES", {PROFILE.id: provisional(PROFILE)}
    )
    provisional_result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call()
    )
    assert provisional_result["refusal"]["blocked_by"] == [
        "profile_not_product_verified",
        "local_calibration_missing",
    ]

    monkeypatch.setattr(profile_catalogue, "PROFILES", {VERIFIED.id: VERIFIED})
    uncalibrated = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call()
    )
    assert uncalibrated["refusal"]["blocked_by"] == ["local_calibration_missing"]
    assert _committed(printer) == []


async def test_stale_calibration_names_its_blocker(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stale(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            identity="sha256:old-calibration",
            state="stale",
            stale_reasons=("font_library",),
            warnings=(),
        )

    monkeypatch.setattr(LocalCalibrationLedger, "async_status", stale)
    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call()
    )

    assert result["refusal"]["blocked_by"] == ["local_calibration_stale"]
    assert _committed(printer) == []


async def test_a_record_warning_needs_no_service_approval_handshake(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    coordinator = SimpleNamespace(
        **{
            **COORDINATOR.__dict__,
            "plants": {"W": _plant("W", phenotype="default")},
        }
    )
    call = _call(strain=None, phenotype=None, plant_ids=["W"])

    result = await label_templates.handle_print_label_template(
        hass, coordinator, _StrainLibrary(), call
    )

    assert result["outcome"] == "ok"
    assert len(_committed(printer)) == 1


async def test_every_runtime_failure_is_structured_and_prints_nothing(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unreadable(*_args: Any, **_kwargs: Any) -> Any:
        raise IncompatibleCalibrationStore(found=9, supported=1)

    monkeypatch.setattr(LocalCalibrationLedger, "async_status", unreadable)
    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call()
    )
    assert result["refusal"]["code"] == "label_template.calibration_store_unreadable"
    assert _committed(printer) == []


async def test_plant_refusal_branches_are_structured(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_profile = _call(
        strain=None,
        phenotype=None,
        plant_ids=["A"],
        profile_id="growspace.profile.nobody.v1",
    )
    unknown_profile = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), bad_profile
    )
    assert unknown_profile["refusal"]["code"] == "label_template.unknown_profile"

    missing = _call(strain=None, phenotype=None, plant_ids=["missing"])
    unknown_subject = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), missing
    )
    assert unknown_subject["refusal"]["code"] == "label_template.unknown_subject"

    uncalibrated = _call(strain=None, phenotype=None, plant_ids=["A"])
    blocked = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), uncalibrated
    )
    assert blocked["refusal"]["blocked_by"] == ["local_calibration_missing"]

    async def unreadable(*_args: Any, **_kwargs: Any) -> Any:
        raise IncompatibleCalibrationStore(found=9, supported=1)

    monkeypatch.setattr(LocalCalibrationLedger, "async_status", unreadable)
    incompatible = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), uncalibrated
    )
    assert incompatible["refusal"]["code"] == (
        "label_template.calibration_store_unreadable"
    )
    assert _committed(printer) == []


async def test_authorization_and_changed_preflight_refusals_are_structured(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    async def unauthorized(*_args: Any, **_kwargs: Any) -> Any:
        raise Unauthorized(permission="labels.read")

    with patch.object(label_templates, "_resolve_template", unauthorized):
        denied = await label_templates.handle_print_label_template(
            hass, COORDINATOR, _StrainLibrary(), _call()
        )
    assert denied["refusal"]["code"] == "label_template.not_authorized"

    await _calibrated(hass, printer)
    refused = PrintRefused("single_print", ("result_not_current",))
    with patch.object(label_templates, "async_print_record", side_effect=refused):
        changed = await label_templates.handle_print_label_template(
            hass, COORDINATOR, _StrainLibrary(), _call()
        )
    assert changed["refusal"]["blocked_by"] == ["result_not_current"]

    with patch.object(
        label_templates,
        "async_print_record",
        side_effect=IncompatibleCalibrationStore(found=9, supported=1),
    ):
        incompatible = await label_templates.handle_print_label_template(
            hass, COORDINATOR, _StrainLibrary(), _call()
        )
    assert incompatible["refusal"]["code"] == (
        "label_template.calibration_store_unreadable"
    )


async def test_an_unresolvable_template_is_a_structured_refusal(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
) -> None:
    async def unresolvable(*_args: Any, **_kwargs: Any) -> Any:
        raise TemplateNotResolvable(template_id=FACTORY_ID, revision=1)

    with patch.object(LabelTemplateLibrary, "async_resolve", unresolvable):
        result = await label_templates.handle_print_label_template(
            hass, COORDINATOR, _StrainLibrary(), _call()
        )

    assert result["refusal"]["code"] == "label_template.template_not_resolvable"
    assert _committed(printer) == []


async def test_a_printer_failure_is_returned_in_the_service_response(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    verified: None,
) -> None:
    await _calibrated(hass, printer)

    async def jammed(call: Any) -> ServiceResponse:
        printer.append(dict(call.data))
        if not call.data["preview"]:
            raise HomeAssistantError("The printer is out of labels")
        return {"image": _one_bit_png()}

    hass.services.async_register(
        NIIMBOT_DOMAIN,
        NIIMBOT_PRINT_SERVICE,
        jammed,
        supports_response=SupportsResponse.OPTIONAL,
    )
    result = await label_templates.handle_print_label_template(
        hass, COORDINATOR, _StrainLibrary(), _call()
    )

    assert result["refusal"]["code"] == "label_template.print_failed"
    assert result["refusal"]["recovery"] == "retry_print"
