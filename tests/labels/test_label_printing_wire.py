"""The recovery wire: calibration, test printing and one production print.

Workspace issue #228. The print routes and the calibration ledger have existed
since #221; these are the claims the commands on top of them make.

Three carry the ticket. **An approval is held, not re-derived**: a print names
what the operator looked at, and nothing a client sends can substitute for the
held content. **A measurement belongs to a sheet that printed**: the numbers
are attached to the identities of the label that reached paper, or refused.
And **every refusal routes somewhere**: a print refused for several reasons
names all of them and the one correction to make first, so a card can take the
user to profile selection, calibration or a fresh preview rather than show a
sentence beside a disabled button.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.labels import approvals
from custom_components.growspace_manager.labels.approvals import (
    DRAFT_APPROVAL,
    ApprovalHolder,
    DraftApproval,
    approval_holder,
)
from custom_components.growspace_manager.labels.calibration import (
    IncompatibleCalibrationStore,
    LocalCalibrationLedger,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    PROFILES,
    TYPICAL_STRAIN,
    ProfileEvidence,
    factory_template_for_size,
    profile_by_id,
    profiles as profile_catalogue,
    select_profile,
)
from custom_components.growspace_manager.labels.capability import (
    CAPABILITY_FAMILY,
    contract_identity,
)
from custom_components.growspace_manager.labels.library import (
    FACTORY,
    LabelTemplateLibrary,
    TemplateNotResolvable,
)
from custom_components.growspace_manager.websocket import drafts, label_printing
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from .conftest import ADMIN, VIEWER

PROFILE = NIIMBOT_B1_50X30
SIZE = PROFILE.label_size_id
FACTORY_ID = factory_template_for_size(SIZE).id
VERIFIED = replace(PROFILE, evidence=ProfileEvidence.PRODUCT_VERIFIED)
DEVICE = "printer-a"
ENTRY_ID = "entry-a"

STRAINS = {
    "Blue Dream": {
        "meta": {"breeder": "Humboldt", "lineage": "Blueberry x Haze"},
        "phenotypes": {"#1": {}},
    }
}


class _StrainLibrary:
    """The two calls a strain capture makes, over a fixed library."""

    async def load(self) -> None:
        return None

    def get_all(self) -> dict[str, Any]:
        return STRAINS


COORDINATOR = SimpleNamespace(
    config_entry=SimpleNamespace(entry_id=ENTRY_ID),
    services=SimpleNamespace(config=SimpleNamespace(strain_library=_StrainLibrary())),
)

ADMIN_USER = SimpleNamespace(id=ADMIN, is_admin=True)
VIEWER_USER = SimpleNamespace(id=VIEWER, is_admin=False)

MEASUREMENT = {
    "top_mm": 0.5,
    "right_mm": 0.5,
    "bottom_mm": 0.0,
    "left_mm": 0.5,
    "feed_mm": -0.4,
}


def _message(user: Any = ADMIN_USER, **payload: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"contract": contract_identity(), WS_MSG_USER: user}
    message.update(payload)
    return message


async def _status(hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any):
    payload = {"profile_id": PROFILE.id, "device_id": DEVICE}
    payload.update(overrides)
    return await label_printing.websocket_get_label_calibration_status(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _sheet(hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any):
    payload = {"profile_id": PROFILE.id, "device_id": DEVICE, "density": "normal"}
    payload.update(overrides)
    return await label_printing.websocket_print_label_calibration_sheet(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _record(hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any):
    payload: dict[str, Any] = {"sheet_id": "none", "measurement": dict(MEASUREMENT)}
    payload.update(overrides)
    return await label_printing.websocket_record_label_calibration(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _open(hass: HomeAssistant, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label_size_id": SIZE,
        "derive_from": {"kind": FACTORY, "id": FACTORY_ID},
    }
    payload.update(overrides)
    return await drafts.websocket_open_label_template_draft(
        hass, COORDINATOR, _message(**payload)
    )


async def _draft_preview(
    hass: HomeAssistant, version: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label_size_id": SIZE,
        "expected_draft_version": version,
        "context": "strain",
        "fixture_family": "typical",
        "density": "normal",
        "locale": "en",
        "device_id": DEVICE,
    }
    payload.update(overrides)
    return await drafts.websocket_preview_label_template_draft(
        hass, COORDINATOR, _message(**payload)
    )


async def _test_print(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label_size_id": SIZE,
        "expected_draft_version": 1,
        "approval_id": "none",
        "expected_raster_identity": "sha256:none",
        "device_id": DEVICE,
    }
    payload.update(overrides)
    return await label_printing.websocket_test_print_label_template_draft(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _record_preview(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "template": {"kind": FACTORY, "id": FACTORY_ID},
        "strain": "Blue Dream",
        "phenotype": "#1",
        "device_id": DEVICE,
        "density": "normal",
        "locale": "en",
    }
    payload.update(overrides)
    return await label_printing.websocket_preview_label_record(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _print(
    hass: HomeAssistant, *, user: Any = ADMIN_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "approval_id": "none",
        "expected_raster_identity": "sha256:none",
    }
    payload.update(overrides)
    return await label_printing.websocket_print_label_record(
        hass, COORDINATOR, _message(user, **payload)
    )


def _committed(printer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in printer if not call["preview"]]


async def _calibrated(hass: HomeAssistant) -> dict[str, Any]:
    sheet = await _sheet(hass)
    return await _record(hass, sheet_id=sheet["sheet_id"])


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Promote the shipped profile, as a recorded evidence matrix would."""
    monkeypatch.setattr(profile_catalogue, "PROFILES", {VERIFIED.id: VERIFIED})


def _unreadable(*_args: Any, **_kwargs: Any) -> Any:
    raise IncompatibleCalibrationStore(found=9, supported=1)


# ---------------------------------------------------------------------------
# Registration and the gate
# ---------------------------------------------------------------------------


def test_the_six_recovery_commands_are_registered_with_the_acting_user() -> None:
    assert [command.type for command in label_printing.COMMANDS] == [
        label_printing.WS_TYPE_GET_LABEL_CALIBRATION_STATUS,
        label_printing.WS_TYPE_PRINT_LABEL_CALIBRATION_SHEET,
        label_printing.WS_TYPE_RECORD_LABEL_CALIBRATION,
        label_printing.WS_TYPE_TEST_PRINT_LABEL_TEMPLATE_DRAFT,
        label_printing.WS_TYPE_PREVIEW_LABEL_RECORD,
        label_printing.WS_TYPE_PRINT_LABEL_RECORD,
    ]
    assert all(command.actor for command in label_printing.COMMANDS)
    assert all(command.resolve == "any" for command in label_printing.COMMANDS)
    assert all(
        "contract" in command.schema.schema for command in label_printing.COMMANDS
    )


@pytest.mark.parametrize(
    "call", [_status, _sheet, _record, _test_print, _record_preview, _print]
)
async def test_every_command_refuses_a_stale_contract(
    hass: HomeAssistant, printer: list[dict[str, Any]], call: Any
) -> None:
    stale = {"family": CAPABILITY_FAMILY, "major": 1, "generation": 0}
    payload = await call(hass, contract=stale)

    assert payload["refusal"]["code"] == "label_template.contract_incompatible"
    assert printer == []


@pytest.mark.parametrize("call", [_status, _sheet, _test_print, _record_preview])
async def test_a_command_without_a_printer_asks_for_one(
    hass: HomeAssistant, printer: list[dict[str, Any]], call: Any
) -> None:
    payload = await call(hass, device_id="  ")

    assert payload["refusal"]["code"] == "label_template.printer_required"
    assert payload["refusal"]["recovery"] == "choose_printer"
    assert printer == []


@pytest.mark.parametrize("call", [_status, _sheet])
async def test_an_unknown_profile_routes_to_profile_selection(
    hass: HomeAssistant, call: Any
) -> None:
    payload = await call(hass, profile_id="growspace.profile.nobody.v1")

    assert payload["refusal"]["code"] == "label_template.unknown_profile"
    assert payload["refusal"]["recovery"] == "select_profile"


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


async def test_an_unmeasured_printer_is_absent_and_says_what_to_measure(
    hass: HomeAssistant,
) -> None:
    payload = await _status(hass, user=VIEWER_USER)

    assert payload["outcome"] == "ok"
    assert payload["calibration"]["state"] == "absent"
    assert payload["profile"]["id"] == PROFILE.id
    assert payload["bounds"] == {
        "printable_width_mm": PROFILE.printable_width_mm,
        "printable_height_mm": PROFILE.printable_height_mm,
        "feed_axis": "y",
        "quantum_mm": 0.01,
    }


async def test_nobody_is_told_to_sign_in_rather_than_shown_a_status(
    hass: HomeAssistant,
) -> None:
    payload = await _status(hass, user=None)

    assert payload["refusal"]["code"] == "label_template.not_authorized"
    assert payload["refusal"]["recovery"] == "none"


async def test_an_unreadable_calibration_history_is_named(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalCalibrationLedger, "async_status", _unreadable)

    payload = await _status(hass)

    assert payload["refusal"]["code"] == "label_template.calibration_store_unreadable"


async def test_the_sheet_prints_and_its_measurement_makes_the_printer_current(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    sheet = await _sheet(hass)

    assert sheet["outcome"] == "ok"
    assert sheet["print"]["operation"] == "test_print"
    assert len(_committed(printer)) == 1

    recorded = await _record(hass, sheet_id=sheet["sheet_id"], notes="new roll")

    assert recorded["outcome"] == "ok"
    assert recorded["record"]["sheet_raster_identity"] == sheet["sheet_raster_identity"]
    assert recorded["record"]["notes"] == "new roll"
    assert recorded["calibration"]["state"] == "current"
    assert (await _status(hass))["calibration"]["state"] == "current"


async def test_only_an_administrator_prints_or_records_a_calibration(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    refused = await _sheet(hass, user=VIEWER_USER)
    assert refused["refusal"]["code"] == "label_template.not_authorized"
    assert refused["refusal"]["recovery"] == "sign_in_as_administrator"

    sheet = await _sheet(hass)
    recorded = await _record(hass, user=VIEWER_USER, sheet_id=sheet["sheet_id"])
    assert recorded["refusal"]["code"] == "label_template.not_authorized"


async def test_a_sheet_that_did_not_print_says_to_try_again(
    hass: HomeAssistant,
) -> None:
    """No printer integration answers, so there is no raster and no paper."""
    payload = await _sheet(hass)

    assert payload["refusal"]["code"] == "label_template.calibration_sheet_not_printed"
    assert payload["refusal"]["recovery"] == "retry_preview"
    assert "no_raster" in payload["refusal"]["blocked_by"]


async def test_numbers_for_a_sheet_nobody_printed_are_refused(
    hass: HomeAssistant,
) -> None:
    payload = await _record(hass, sheet_id="01J00000000000000000000000")

    assert payload["refusal"]["code"] == "label_template.approval_expired"
    assert payload["refusal"]["recovery"] == "print_calibration_sheet"


async def test_an_impossible_measurement_names_the_box_it_came_from(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    sheet = await _sheet(hass)

    payload = await _record(
        hass,
        sheet_id=sheet["sheet_id"],
        measurement={**MEASUREMENT, "left_mm": -1.0},
    )

    assert payload["refusal"]["code"] == "label_template.measurement_invalid"
    assert payload["refusal"]["recovery"] == "fix_measurement"
    assert payload["refusal"]["field"] == "left_mm"


async def test_recording_into_an_unreadable_history_is_refused(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sheet = await _sheet(hass)
    monkeypatch.setattr(LocalCalibrationLedger, "async_record", _unreadable)

    payload = await _record(hass, sheet_id=sheet["sheet_id"])

    assert payload["refusal"]["code"] == "label_template.calibration_store_unreadable"


# ---------------------------------------------------------------------------
# Test printing a draft
# ---------------------------------------------------------------------------


async def _approved_draft(hass: HomeAssistant) -> tuple[dict[str, Any], dict[str, Any]]:
    opened = await _open(hass)
    preview = await _draft_preview(hass, opened["draft"]["version"])
    return opened, preview


async def test_a_draft_preview_holds_what_it_drew_for_a_test_print(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)
    printer.clear()

    payload = await _test_print(
        hass,
        expected_draft_version=opened["draft"]["version"],
        approval_id=preview["approval_id"],
        expected_raster_identity=preview["render"]["raster_identity"],
    )

    assert payload["outcome"] == "ok"
    assert payload["print"]["operation"] == "test_print"
    assert payload["print"]["raster_identity"] == preview["render"]["raster_identity"]
    assert payload["print"]["source"]["published"] is False
    assert [call["preview"] for call in printer] == [True, False]


async def test_a_draft_preview_against_a_profile_of_another_stock_is_refused(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened = await _open(hass)

    payload = await _draft_preview(
        hass, opened["draft"]["version"], profile_id="growspace.profile.other.v1"
    )

    assert payload["refusal"]["code"] == "label_template.unknown_profile"
    assert payload["refusal"]["recovery"] == "select_profile"
    assert printer == []


async def test_a_test_print_of_another_raster_says_to_look_again(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)
    printer.clear()

    payload = await _test_print(
        hass,
        expected_draft_version=opened["draft"]["version"],
        approval_id=preview["approval_id"],
        expected_raster_identity="sha256:something-else",
    )

    assert payload["refusal"]["code"] == "label_template.print_refused"
    assert payload["refusal"]["blocked_by"] == ["result_not_current"]
    assert payload["refusal"]["recovery"] == "refresh_preview"
    assert _committed(printer) == []


async def test_an_approval_that_lapsed_or_was_never_issued_is_refused(
    hass: HomeAssistant,
) -> None:
    payload = await _test_print(hass)

    assert payload["refusal"]["code"] == "label_template.approval_expired"
    assert payload["refusal"]["recovery"] == "refresh_preview"


async def test_an_approval_of_another_version_is_refused(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)

    payload = await _test_print(
        hass,
        expected_draft_version=opened["draft"]["version"] + 1,
        approval_id=preview["approval_id"],
    )

    assert payload["refusal"]["code"] == "label_template.draft_version_mismatch"
    assert payload["refusal"]["recovery"] == "refresh_preview"


async def test_a_draft_that_moved_after_its_preview_is_not_test_printed(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)
    document = json.loads(json.dumps(opened["draft"]["document"]))
    document["elements"][0]["frame"]["x_mm"] = 3.0
    await drafts.websocket_autosave_label_template_draft(
        hass,
        COORDINATOR,
        _message(
            label_size_id=SIZE,
            document=document,
            expected_version=opened["draft"]["version"],
        ),
    )
    printer.clear()

    payload = await _test_print(
        hass,
        expected_draft_version=opened["draft"]["version"],
        approval_id=preview["approval_id"],
        expected_raster_identity=preview["render"]["raster_identity"],
    )

    assert payload["refusal"]["code"] == "label_template.draft_version_mismatch"
    assert payload["refusal"]["recovery"] == "reload_draft"
    assert printer == []


async def test_only_an_administrator_test_prints(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)

    payload = await _test_print(
        hass,
        user=VIEWER_USER,
        expected_draft_version=opened["draft"]["version"],
        approval_id=preview["approval_id"],
    )

    assert payload["refusal"]["code"] == "label_template.not_authorized"


async def test_a_discarded_draft_cannot_be_test_printed_nor_its_successor(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened, preview = await _approved_draft(hass)
    await drafts.websocket_discard_label_template_draft(
        hass, COORDINATOR, _message(label_size_id=SIZE)
    )
    arguments = {
        "expected_draft_version": opened["draft"]["version"],
        "approval_id": preview["approval_id"],
        "expected_raster_identity": preview["render"]["raster_identity"],
    }

    gone = await _test_print(hass, **arguments)
    assert gone["refusal"]["code"] == "label_template.draft_not_found"

    await _open(hass)
    successor = await _test_print(hass, **arguments)
    assert successor["refusal"]["code"] == "label_template.approval_expired"


async def test_an_invalid_draft_is_not_test_printed(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    """Reachable only by a held approval of a version that stopped validating."""
    opened = await _open(hass)
    document = json.loads(json.dumps(opened["draft"]["document"]))
    document["elements"][0]["frame"]["x_mm"] = 999.0
    saved = await drafts.websocket_autosave_label_template_draft(
        hass,
        COORDINATOR,
        _message(
            label_size_id=SIZE,
            document=document,
            expected_version=opened["draft"]["version"],
        ),
    )
    version = saved["draft"]["version"]
    approval_id = approval_holder(hass, ENTRY_ID).hold(
        DRAFT_APPROVAL,
        DraftApproval(
            draft_id=saved["draft"]["id"],
            template_id=None,
            label_size_id=SIZE,
            draft_version=version,
            content=TYPICAL_STRAIN.snapshot(as_of=dt_util.utcnow()),
            profile=PROFILE,
            density="normal",
            raster_identity="sha256:none",
        ),
    )

    payload = await _test_print(
        hass, expected_draft_version=version, approval_id=approval_id
    )

    assert payload["refusal"]["code"] == "label_template.draft_not_publishable"
    assert payload["refusal"]["recovery"] == "fix_layout"
    assert payload["refusal"]["diagnostics"]


# ---------------------------------------------------------------------------
# One production print
# ---------------------------------------------------------------------------


async def test_a_provisional_profile_previews_but_routes_to_profile_selection(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _record_preview(hass, user=VIEWER_USER)

    assert payload["outcome"] == "ok"
    assert payload["subject"] == "Blue Dream"
    assert payload["template"]["ref"] == {"kind": FACTORY, "id": FACTORY_ID}
    assert payload["calibration"]["state"] == "absent"
    assert payload["decision"]["allowed"] is False
    assert payload["decision"]["blocked_by"] == [
        "profile_not_product_verified",
        "local_calibration_missing",
    ]
    assert payload["recovery"] == "select_profile"

    printed = await _print(
        hass,
        user=VIEWER_USER,
        approval_id=payload["approval_id"],
        expected_raster_identity=payload["render"]["raster_identity"],
    )
    assert printed["refusal"]["code"] == "label_template.print_refused"
    assert printed["refusal"]["recovery"] == "select_profile"
    assert _committed(printer) == []


async def test_a_verified_uncalibrated_printer_routes_to_calibration(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    payload = await _record_preview(hass)

    assert payload["decision"]["blocked_by"] == ["local_calibration_missing"]
    assert payload["recovery"] == "calibrate"


async def test_a_verified_calibrated_printer_prints_exactly_what_was_approved(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass)
    preview = await _record_preview(hass, user=VIEWER_USER)
    assert preview["decision"]["allowed"] is True
    assert preview["recovery"] == "none"
    printer.clear()

    printed = await _print(
        hass,
        user=VIEWER_USER,
        approval_id=preview["approval_id"],
        expected_raster_identity=preview["render"]["raster_identity"],
    )

    assert printed["outcome"] == "ok"
    assert printed["print"]["operation"] == "single_print"
    assert printed["print"]["raster_identity"] == preview["render"]["raster_identity"]
    assert len(_committed(printer)) == 1


async def test_a_named_revision_prints_under_its_own_reference(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    opened = await _open(hass)
    await drafts.websocket_autosave_label_template_draft(
        hass,
        COORDINATOR,
        _message(
            label_size_id=SIZE,
            document=opened["draft"]["document"],
            name="Bench label",
            expected_version=opened["draft"]["version"],
        ),
    )
    published = await drafts.websocket_publish_label_template_draft(
        hass, COORDINATOR, _message(label_size_id=SIZE)
    )
    template_id = published["template"]["id"]

    payload = await _record_preview(
        hass, template={"kind": "named", "id": template_id, "revision": 1}
    )

    assert payload["outcome"] == "ok"
    assert payload["template"]["ref"] == {"kind": "named", "id": template_id}


@pytest.mark.parametrize(
    ("overrides", "code", "recovery"),
    [
        ({"locale": "xx"}, "label_template.unsupported_locale", "none"),
        (
            {"template": {"kind": "named", "id": "missing"}},
            "label_template.template_not_found",
            "choose_template",
        ),
        (
            {"template": {"kind": FACTORY, "id": FACTORY_ID, "revision": 99}},
            "label_template.template_not_found",
            "choose_template",
        ),
        (
            {"profile_id": "growspace.profile.other.v1"},
            "label_template.unknown_profile",
            "select_profile",
        ),
        (
            {"strain": "Nobody Grows This"},
            "label_template.unknown_subject",
            "choose_subject",
        ),
    ],
)
async def test_a_record_preview_names_what_it_could_not_find(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    overrides: dict[str, Any],
    code: str,
    recovery: str,
) -> None:
    payload = await _record_preview(hass, **overrides)

    assert payload["refusal"]["code"] == code
    assert payload["refusal"]["recovery"] == recovery
    assert printer == []


async def test_a_record_preview_without_a_strain_library_says_so(
    hass: HomeAssistant,
) -> None:
    unloaded = SimpleNamespace(
        config_entry=COORDINATOR.config_entry,
        services=SimpleNamespace(config=SimpleNamespace(strain_library=None)),
    )
    payload = await label_printing.websocket_preview_label_record(
        hass,
        unloaded,
        _message(
            template={"kind": FACTORY, "id": FACTORY_ID},
            strain="Blue Dream",
            device_id=DEVICE,
            density="normal",
            locale="en",
        ),
    )

    assert payload["refusal"]["code"] == "label_template.unknown_subject"
    assert payload["refusal"]["recovery"] == "none"


async def test_a_template_that_stopped_validating_is_named(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise TemplateNotResolvable(template_id=FACTORY_ID, revision=1)

    monkeypatch.setattr(LabelTemplateLibrary, "async_resolve", refuse)

    payload = await _record_preview(hass)

    assert payload["refusal"]["code"] == "label_template.template_not_resolvable"


async def test_nobody_may_preview_or_print_a_record(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    refused = await _record_preview(hass, user=None)
    assert refused["refusal"]["code"] == "label_template.not_authorized"

    preview = await _record_preview(hass)
    printed = await _print(
        hass,
        user=None,
        approval_id=preview["approval_id"],
        expected_raster_identity=preview["render"]["raster_identity"],
    )
    assert printed["refusal"]["code"] == "label_template.not_authorized"


async def test_a_record_print_without_a_held_approval_is_refused(
    hass: HomeAssistant,
) -> None:
    payload = await _print(hass)

    assert payload["refusal"]["code"] == "label_template.approval_expired"


async def test_an_unreadable_history_refuses_a_record_preview_and_print(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = await _record_preview(hass)
    monkeypatch.setattr(LocalCalibrationLedger, "async_status", _unreadable)

    assert (await _record_preview(hass))["refusal"][
        "code"
    ] == "label_template.calibration_store_unreadable"
    printed = await _print(
        hass,
        approval_id=preview["approval_id"],
        expected_raster_identity=preview["render"]["raster_identity"],
    )
    assert printed["refusal"]["code"] == "label_template.calibration_store_unreadable"


# ---------------------------------------------------------------------------
# The holder and the profile lookups
# ---------------------------------------------------------------------------


def test_a_held_approval_lapses_and_the_oldest_is_evicted_first() -> None:
    holder = ApprovalHolder(ttl=timedelta(minutes=1), limit=2)
    now = dt_util.utcnow()

    first = holder.hold("draft", "a", now=now)
    second = holder.hold("draft", "b", now=now)
    third = holder.hold("draft", "c", now=now)

    assert holder.get(first, "draft", now=now) is None
    assert holder.get(second, "draft", now=now) == "b"
    assert holder.get(second, "record", now=now) is None
    assert holder.get(third, "draft", now=now + timedelta(minutes=2)) is None


def test_one_holder_per_config_entry(hass: HomeAssistant) -> None:
    assert approval_holder(hass, "a") is approval_holder(hass, "a")
    assert approval_holder(hass, "a") is not approval_holder(hass, "b")
    assert timedelta(minutes=15) == approvals.APPROVAL_TTL


def test_a_profile_is_selected_only_for_its_own_stock() -> None:
    assert select_profile(SIZE) is PROFILE
    assert select_profile(SIZE, PROFILE.id) is PROFILE
    assert select_profile(SIZE, "growspace.profile.other.v1") is None
    assert select_profile("growspace.stock.none.v1") is None
    assert profile_by_id(PROFILE.id) is PROFILES[PROFILE.id]
    assert profile_by_id("growspace.profile.other.v1") is None


def test_every_blocker_routes_to_one_correction() -> None:
    assert label_printing.recovery_for([]) == "none"
    assert label_printing.recovery_for(["no_raster", "blocking_diagnostics"]) == (
        "retry_preview"
    )
    assert label_printing.recovery_for(
        ["local_calibration_stale", "result_not_current"]
    ) == ("calibrate")
    assert label_printing.recovery_for(["revision_not_published"]) == "publish"
    assert label_printing.recovery_for(["content_not_actual"]) == "none"


# ---------------------------------------------------------------------------
# The shape the card is held to
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures" / "contract"

_OPAQUE = re.compile(
    r"^(?:[0-9A-HJKMNP-TV-Z]{26}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


_REFERENCE = re.compile(r"^(?P<kind>draft):(?P<id>[0-9A-HJKMNP-TV-Z]{26})$")


def _stable(value: Any, seen: dict[str, str] | None = None) -> Any:
    """Replace minted identities with stable placeholders, in first-seen order."""
    seen = {} if seen is None else seen
    if isinstance(value, dict):
        return {key: _stable(item, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_stable(item, seen) for item in value]
    if isinstance(value, str) and _OPAQUE.match(value):
        return seen.setdefault(value, f"<opaque-{len(seen) + 1}>")
    if isinstance(value, str) and (match := _REFERENCE.match(value)):
        # A print's source reference names the draft it came from.
        return f"{match['kind']}:{_stable(match['id'], seen)}"
    return value


def _fixture(name: str, payload: Any, pytestconfig: pytest.Config) -> None:
    path = FIXTURES / f"{name}.json"
    stable = _stable(payload)
    if pytestconfig.getoption("regenerate_contract_fixture"):
        path.write_text(
            f"{json.dumps(stable, indent=2, sort_keys=True)}\n", encoding="utf-8"
        )
    assert path.exists()
    assert stable == json.loads(path.read_text(encoding="utf-8"))


@freeze_time("2026-09-21T00:00:00+00:00")
async def test_the_shared_recovery_fixtures_are_exact(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    pytestconfig: pytest.Config,
    verified: None,
) -> None:
    """One recorded response per payload the card's schemas parse."""
    hass.config.time_zone = "UTC"

    _fixture("label_calibration_status_v1", await _status(hass), pytestconfig)
    sheet = await _sheet(hass)
    _fixture("label_calibration_sheet_v1", sheet, pytestconfig)
    _fixture(
        "label_calibration_recorded_v1",
        await _record(hass, sheet_id=sheet["sheet_id"]),
        pytestconfig,
    )

    opened, preview = await _approved_draft(hass)
    _fixture(
        "label_draft_test_print_v1",
        await _test_print(
            hass,
            expected_draft_version=opened["draft"]["version"],
            approval_id=preview["approval_id"],
            expected_raster_identity=preview["render"]["raster_identity"],
        ),
        pytestconfig,
    )

    record = await _record_preview(hass)
    _fixture("label_record_preview_v1", record, pytestconfig)
    _fixture(
        "label_record_printed_v1",
        await _print(
            hass,
            approval_id=record["approval_id"],
            expected_raster_identity=record["render"]["raster_identity"],
        ),
        pytestconfig,
    )
    _fixture(
        "label_print_refused_v1",
        await _print(
            hass,
            approval_id=record["approval_id"],
            expected_raster_identity="sha256:another",
        ),
        pytestconfig,
    )
