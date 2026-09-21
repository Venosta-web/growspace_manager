"""The batch wire: preflight, print, watch and retry (workspace issue #229).

The domain has preflighted, printed and retried immutable batches since #222;
these are the claims the four commands on top of it make.

**The review is held, not re-derived.** A print names the preflight the
operator reviewed, and warning consent is the identity of that exact
preflight -- another one, or none, is refused before a job exists.
**Printing is watched.** A print answers with a started job in plan order,
and each attempt's outcome is on the job as soon as the printer answers.
**Retry is the failures.** It sends only a finished job's failed attempts,
in their original order, from the snapshots the review captured.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.labels.approvals import (
    BATCH_PREFLIGHT,
    approval_holder,
)
from custom_components.growspace_manager.labels.batch_jobs import (
    BATCH_JOB,
    batch_job_holder,
)
from custom_components.growspace_manager.labels.calibration import (
    IncompatibleCalibrationStore,
    LocalCalibrationLedger,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    factory_template_for_size,
    profiles as profile_catalogue,
)
from custom_components.growspace_manager.labels.capability import (
    CAPABILITY_FAMILY,
    contract_identity,
)
from custom_components.growspace_manager.labels.library import FACTORY
from custom_components.growspace_manager.labels.niimbot import (
    NIIMBOT_DOMAIN,
    NIIMBOT_PRINT_SERVICE,
)
from custom_components.growspace_manager.models.plant import Plant, PlantGenetics
from custom_components.growspace_manager.websocket import label_batch, label_printing
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from homeassistant.core import HomeAssistant, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
import homeassistant.util.dt as dt_util
from tests.labels.support import product_verified

from .conftest import ADMIN, VIEWER, _one_bit_png
from .test_label_printing_wire import _fixture

PROFILE = NIIMBOT_B1_50X30
SIZE = PROFILE.label_size_id
FACTORY_ID = factory_template_for_size(SIZE).id
VERIFIED = product_verified(PROFILE)
DEVICE = "printer-a"
ENTRY_ID = "entry-a"

STRAINS = {
    "Blue Dream": {
        "meta": {"breeder": "Humboldt", "lineage": "Blueberry x Haze"},
        "phenotypes": {"Pheno 3": {}},
    }
}


def _plant(plant_id: str, *, phenotype: str = "Pheno 3") -> Plant:
    return Plant(
        plant_id=plant_id,
        growspace_id="tent",
        genetics=PlantGenetics(strain_name="Blue Dream", phenotype_name=phenotype),
        stage="flower",
        veg_start="2026-07-01T08:00:00+00:00",
        flower_start="2026-09-02T09:15:00+00:00",
    )


class _StrainLibrary:
    async def load(self) -> None:
        return None

    def get_all(self) -> dict[str, Any]:
        return STRAINS


def _coordinator(*plants: Plant, strains: Any = None) -> Any:
    return SimpleNamespace(
        config_entry=SimpleNamespace(entry_id=ENTRY_ID),
        plants={plant.plant_id: plant for plant in plants},
        services=SimpleNamespace(
            config=SimpleNamespace(
                strain_library=_StrainLibrary() if strains is None else strains
            )
        ),
    )


COORDINATOR = _coordinator(_plant("A"), _plant("B"), _plant("W", phenotype="default"))

ADMIN_USER = SimpleNamespace(id=ADMIN, is_admin=True)
VIEWER_USER = SimpleNamespace(id=VIEWER, is_admin=False)


def _message(user: Any = VIEWER_USER, **payload: Any) -> dict[str, Any]:
    message: dict[str, Any] = {"contract": contract_identity(), WS_MSG_USER: user}
    message.update(payload)
    return message


@pytest.fixture(autouse=True)
def _url():
    """A plant label links to its plant; the link needs a base URL."""
    with patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        return_value="http://ha.test:8123",
    ):
        yield


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Promote the shipped profile, as a recorded evidence matrix would."""
    monkeypatch.setattr(profile_catalogue, "PROFILES", {VERIFIED.id: VERIFIED})


async def _calibrated(
    hass: HomeAssistant, printer: list[dict[str, Any]], *, feed_mm: float = -0.4
) -> None:
    admin = _message(ADMIN_USER)
    sheet = await label_printing.websocket_print_label_calibration_sheet(
        hass,
        COORDINATOR,
        {**admin, "profile_id": PROFILE.id, "device_id": DEVICE, "density": "normal"},
    )
    await label_printing.websocket_record_label_calibration(
        hass,
        COORDINATOR,
        {
            **admin,
            "sheet_id": sheet["sheet_id"],
            "measurement": {
                "top_mm": 0.5,
                "right_mm": 0.5,
                "bottom_mm": 0.0,
                "left_mm": 0.5,
                "feed_mm": feed_mm,
            },
        },
    )
    printer.clear()


async def _preflight(
    hass: HomeAssistant,
    *,
    user: Any = VIEWER_USER,
    coordinator: Any = COORDINATOR,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "template": {"kind": FACTORY, "id": FACTORY_ID},
        "plant_ids": ["A", "B"],
        "copies": 2,
        "device_id": DEVICE,
        "density": "normal",
        "locale": "en",
    }
    payload.update(overrides)
    return await label_batch.websocket_preflight_label_batch(
        hass, coordinator, _message(user, **payload)
    )


async def _print(
    hass: HomeAssistant, *, user: Any = VIEWER_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"preflight_id": "none"}
    payload.update(overrides)
    return await label_batch.websocket_print_label_batch(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _job(
    hass: HomeAssistant, *, user: Any = VIEWER_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"job_id": "none"}
    payload.update(overrides)
    return await label_batch.websocket_get_label_batch_job(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _retry(
    hass: HomeAssistant, *, user: Any = VIEWER_USER, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {"job_id": "none"}
    payload.update(overrides)
    return await label_batch.websocket_retry_label_batch(
        hass, COORDINATOR, _message(user, **payload)
    )


async def _finished(hass: HomeAssistant, job_id: str) -> dict[str, Any]:
    await hass.async_block_till_done(wait_background_tasks=True)
    payload = await _job(hass, job_id=job_id)
    assert payload["job"]["state"] != "running"
    return payload["job"]


def _committed(printer: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call for call in printer if not call["preview"]]


class _Failures:
    """Which committed prints fail, counted from one after `arm`."""

    def __init__(self) -> None:
        self.committed = 0
        self.failing: set[int] = set()

    def arm(self, *prints: int) -> None:
        self.committed = 0
        self.failing = set(prints)


@pytest.fixture
def failing(hass: HomeAssistant, printer: list[dict[str, Any]]) -> _Failures:
    """Make chosen committed prints fail with a printer error."""
    failures = _Failures()

    async def handle(call: Any) -> ServiceResponse:
        printer.append(dict(call.data))
        if not call.data["preview"]:
            failures.committed += 1
            if failures.committed in failures.failing:
                raise HomeAssistantError("The printer is out of labels")
        return {"image": _one_bit_png()}

    hass.services.async_register(
        NIIMBOT_DOMAIN,
        NIIMBOT_PRINT_SERVICE,
        handle,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return failures


# ---------------------------------------------------------------------------
# Registration and the gate
# ---------------------------------------------------------------------------


def test_the_four_batch_commands_are_registered_with_the_acting_user() -> None:
    assert [command.type for command in label_batch.COMMANDS] == [
        label_batch.WS_TYPE_PREFLIGHT_LABEL_BATCH,
        label_batch.WS_TYPE_PRINT_LABEL_BATCH,
        label_batch.WS_TYPE_GET_LABEL_BATCH_JOB,
        label_batch.WS_TYPE_RETRY_LABEL_BATCH,
    ]
    assert all(command.actor for command in label_batch.COMMANDS)
    assert all(command.resolve == "any" for command in label_batch.COMMANDS)


@pytest.mark.parametrize("call", [_preflight, _print, _job, _retry])
async def test_every_command_refuses_a_stale_contract(
    hass: HomeAssistant, printer: list[dict[str, Any]], call: Any
) -> None:
    stale = {"family": CAPABILITY_FAMILY, "major": 1, "generation": 0}
    payload = await call(hass, contract=stale)

    assert payload["refusal"]["code"] == "label_template.contract_incompatible"
    assert printer == []


@pytest.mark.parametrize(
    "payload",
    [
        {"plant_ids": []},
        {"plant_ids": [f"p{index}" for index in range(101)]},
        {"copies": 0},
        {"copies": 11},
    ],
)
def test_the_schema_bounds_what_one_preflight_may_hold(
    payload: dict[str, Any],
) -> None:
    message = {
        "id": 1,
        "type": label_batch.WS_TYPE_PREFLIGHT_LABEL_BATCH,
        "contract": contract_identity(),
        "template": {"kind": FACTORY, "id": FACTORY_ID},
        "plant_ids": ["A"],
        "device_id": DEVICE,
        **payload,
    }
    with pytest.raises(Exception, match="length|value must be"):
        label_batch.SCHEMA_WS_PREFLIGHT_LABEL_BATCH(message)


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


async def test_a_preflight_renders_every_record_and_plans_copy_major(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    payload = await _preflight(hass)

    assert payload["outcome"] == "ok"
    preflight = payload["preflight"]
    assert [record["subject"] for record in preflight["records"]] == ["A", "B"]
    assert [
        (attempt["subject"], attempt["copy_index"], attempt["position"])
        for attempt in preflight["attempts"]
    ] == [("A", 1, 0), ("B", 1, 1), ("A", 2, 2), ("B", 2, 3)]
    assert {attempt["status"] for attempt in preflight["attempts"]} == {"pending"}
    assert _committed(printer) == []
    # Shipped profiles are provisional and this printer was never measured.
    assert preflight["allowed"] is False
    assert preflight["blocked_by"] == [
        "profile_not_product_verified",
        "local_calibration_missing",
    ]
    assert payload["recovery"] == "select_profile"
    assert payload["preflight_id"]
    json.dumps(payload)


async def test_a_blocked_preflight_is_refused_before_any_job_exists(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    preflight = await _preflight(hass)

    payload = await _print(hass, preflight_id=preflight["preflight_id"])

    assert payload["refusal"]["code"] == "label_template.print_refused"
    assert payload["refusal"]["recovery"] == "select_profile"
    assert batch_job_holder(hass, ENTRY_ID).values(BATCH_JOB) == []
    assert _committed(printer) == []


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
            {"plant_ids": ["A", "missing"]},
            "label_template.unknown_subject",
            "choose_subject",
        ),
        (
            {"plant_ids": ["A", "A"]},
            "label_template.unknown_subject",
            "choose_subject",
        ),
    ],
)
async def test_a_preflight_names_what_it_could_not_use(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    overrides: dict[str, Any],
    code: str,
    recovery: str,
) -> None:
    payload = await _preflight(hass, **overrides)

    assert payload["refusal"]["code"] == code
    assert payload["refusal"]["recovery"] == recovery
    assert _committed(printer) == []


async def test_a_template_that_stopped_resolving_is_named(
    hass: HomeAssistant, printer: list[dict[str, Any]]
) -> None:
    from custom_components.growspace_manager.labels.library import (
        LabelTemplateLibrary,
        TemplateNotResolvable,
    )

    async def unresolvable(*_args: Any, **_kwargs: Any) -> Any:
        raise TemplateNotResolvable(template_id=FACTORY_ID, revision=1)

    with patch.object(LabelTemplateLibrary, "async_resolve", unresolvable):
        payload = await _preflight(hass)

    assert payload["refusal"]["code"] == "label_template.template_not_resolvable"
    assert payload["refusal"]["recovery"] == "choose_template"


async def test_a_preflight_without_a_strain_library_says_so(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(_plant("A"))
    coordinator.services.config.strain_library = None

    payload = await _preflight(hass, coordinator=coordinator)

    assert payload["refusal"]["code"] == "label_template.unknown_subject"
    assert payload["refusal"]["recovery"] == "none"


async def test_nobody_may_preflight_print_or_watch_a_batch(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, plant_ids=["A"], copies=1)

    for payload in (
        await _preflight(hass, user=None),
        await _print(hass, user=None, preflight_id=preflight["preflight_id"]),
        await _job(hass, user=None),
    ):
        assert payload["refusal"]["code"] == "label_template.not_authorized"


async def test_an_unreadable_calibration_history_refuses_the_preflight(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreadable(*_args: Any, **_kwargs: Any) -> Any:
        raise IncompatibleCalibrationStore(found=9, supported=1)

    monkeypatch.setattr(LocalCalibrationLedger, "async_status", unreadable)

    payload = await _preflight(hass)

    assert payload["refusal"]["code"] == "label_template.calibration_store_unreadable"


# ---------------------------------------------------------------------------
# Printing and watching
# ---------------------------------------------------------------------------


async def test_a_reviewed_batch_prints_in_plan_order_and_every_copy_is_named(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass)
    assert preflight["preflight"]["allowed"] is True
    printer.clear()

    started = await _print(
        hass,
        preflight_id=preflight["preflight_id"],
        acknowledgement=preflight["preflight"]["identity"],
    )

    assert started["outcome"] == "ok"
    job = started["job"]
    assert job["preflight_identity"] == preflight["preflight"]["identity"]
    assert job["retry_of"] is None
    assert job["selected"] == [
        attempt["id"] for attempt in preflight["preflight"]["attempts"]
    ]

    finished = await _finished(hass, job["id"])

    assert finished["state"] == "finished"
    assert [
        (attempt["subject"], attempt["copy_index"], attempt["status"])
        for attempt in finished["attempts"]
    ] == [
        ("A", 1, "printed"),
        ("B", 1, "printed"),
        ("A", 2, "printed"),
        ("B", 2, "printed"),
    ]
    records = {
        record["subject"]: record["render"]["raster_identity"]
        for record in preflight["preflight"]["records"]
    }
    assert all(
        attempt["raster_identity"] == records[attempt["subject"]]
        for attempt in finished["attempts"]
    )
    assert len(_committed(printer)) == 4


async def test_warnings_need_consent_to_this_exact_preflight(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, plant_ids=["W"], copies=1)
    review = preflight["preflight"]
    assert review["allowed"] is True
    assert review["acknowledgement_required"] is True
    assert any(
        item["subject"] == "W" and item["diagnostic"]["severity"] == "warning"
        for item in review["diagnostics"]
    )

    missing = await _print(hass, preflight_id=preflight["preflight_id"])
    assert missing["refusal"]["blocked_by"] == ["warning_acknowledgement_required"]
    assert missing["refusal"]["recovery"] == "acknowledge_warnings"

    other = await _print(
        hass, preflight_id=preflight["preflight_id"], acknowledgement="sha256:other"
    )
    assert other["refusal"]["blocked_by"] == ["preflight_not_current"]
    assert other["refusal"]["recovery"] == "preflight_again"

    # A second review of the same plants is a new identity: consent to it
    # does not carry over to the first.
    again = await _preflight(hass, plant_ids=["W"], copies=1)
    assert again["preflight"]["identity"] != review["identity"]
    stale = await _print(
        hass,
        preflight_id=preflight["preflight_id"],
        acknowledgement=again["preflight"]["identity"],
    )
    assert stale["refusal"]["blocked_by"] == ["preflight_not_current"]
    assert _committed(printer) == []

    started = await _print(
        hass, preflight_id=preflight["preflight_id"], acknowledgement=review["identity"]
    )
    assert (await _finished(hass, started["job"]["id"]))["state"] == "finished"


async def test_progress_lands_on_the_job_while_it_prints(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, copies=1)
    gate = asyncio.Event()
    committed = 0

    async def slow(call: Any) -> ServiceResponse:
        nonlocal committed
        if not call.data["preview"]:
            committed += 1
            if committed == 2:
                await gate.wait()
        return {"image": _one_bit_png()}

    hass.services.async_register(
        NIIMBOT_DOMAIN,
        NIIMBOT_PRINT_SERVICE,
        slow,
        supports_response=SupportsResponse.OPTIONAL,
    )
    started = await _print(
        hass,
        preflight_id=preflight["preflight_id"],
        acknowledgement=preflight["preflight"]["identity"],
    )
    async with asyncio.timeout(5):
        while committed < 2:
            await asyncio.sleep(0.01)

    watched = (await _job(hass, job_id=started["job"]["id"]))["job"]
    assert watched["state"] == "running"
    assert [attempt["status"] for attempt in watched["attempts"]] == [
        "printed",
        "pending",
    ]

    again = await _print(
        hass,
        preflight_id=preflight["preflight_id"],
        acknowledgement=preflight["preflight"]["identity"],
    )
    assert again["refusal"]["code"] == "label_template.batch_running"
    assert again["refusal"]["recovery"] == "wait"
    early = await _retry(hass, job_id=started["job"]["id"])
    assert early["refusal"]["code"] == "label_template.batch_running"

    gate.set()
    assert (await _finished(hass, started["job"]["id"]))["attempts"][1][
        "status"
    ] == "printed"


async def test_a_calibration_that_moves_after_review_refuses_the_started_job(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, copies=1)
    # Measured again between the review and the press of the button.
    await _calibrated(hass, printer, feed_mm=-0.2)

    started = await _print(
        hass,
        preflight_id=preflight["preflight_id"],
        acknowledgement=preflight["preflight"]["identity"],
    )
    finished = await _finished(hass, started["job"]["id"])

    assert finished["state"] == "refused"
    assert finished["refusal"]["blocked_by"] == ["preflight_not_current"]
    assert finished["refusal"]["recovery"] == "preflight_again"
    assert {attempt["status"] for attempt in finished["attempts"]} == {"pending"}
    assert _committed(printer) == []
    nothing = await _retry(hass, job_id=started["job"]["id"])
    assert nothing["refusal"]["code"] == "label_template.nothing_to_retry"


async def test_an_unexpected_stop_fails_what_had_not_printed(
    hass: HomeAssistant, printer: list[dict[str, Any]], verified: None
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, copies=1)

    def stop_after_first(original: Any):
        async def run(*args: Any, **kwargs: Any) -> Any:
            listener = kwargs["on_result"]
            await original(*args, **{**kwargs, "on_result": _once(listener)})

        return run

    def _once(listener: Any):
        def record(result: Any) -> None:
            listener(result)
            raise RuntimeError("the adapter fell over")

        return record

    with patch.object(
        label_batch,
        "async_print_batch",
        stop_after_first(label_batch.async_print_batch),
    ):
        started = await _print(
            hass,
            preflight_id=preflight["preflight_id"],
            acknowledgement=preflight["preflight"]["identity"],
        )
        finished = await _finished(hass, started["job"]["id"])

    assert finished["state"] == "finished"
    assert [attempt["status"] for attempt in finished["attempts"]] == [
        "printed",
        "failed",
    ]
    assert finished["attempts"][1]["error"]


async def test_a_lapsed_review_or_job_routes_back_to_preflight(
    hass: HomeAssistant,
) -> None:
    for payload in (
        await _print(hass, preflight_id="01J00000000000000000000000"),
        await _job(hass, job_id="01J00000000000000000000000"),
        await _retry(hass, job_id="01J00000000000000000000000"),
    ):
        assert payload["refusal"]["code"] == "label_template.approval_expired"
        assert payload["refusal"]["recovery"] == "preflight_again"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


async def test_retry_sends_only_the_failed_copies_from_the_reviewed_snapshots(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    failing: _Failures,
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass)
    review = preflight["preflight"]
    failing.arm(2, 3)
    printer.clear()

    started = await _print(
        hass, preflight_id=preflight["preflight_id"], acknowledgement=review["identity"]
    )
    first = await _finished(hass, started["job"]["id"])

    assert [
        (attempt["subject"], attempt["copy_index"], attempt["status"])
        for attempt in first["attempts"]
    ] == [
        ("A", 1, "printed"),
        ("B", 1, "failed"),
        ("A", 2, "failed"),
        ("B", 2, "printed"),
    ]
    assert first["attempts"][1]["error"]
    assert len(_committed(printer)) == 4  # two reached paper, two did not
    printer.clear()

    # The plant moves on after the review; the replacement label must not.
    COORDINATOR.plants["B"] = replace(COORDINATOR.plants["B"], stage="dry")
    try:
        retried = await _retry(
            hass, job_id=first["id"], acknowledgement=review["identity"]
        )
        assert retried["outcome"] == "ok"
        job = retried["job"]
        assert job["retry_of"] == first["id"]
        assert job["preflight_identity"] == review["identity"]
        assert job["selected"] == [
            first["attempts"][1]["id"],
            first["attempts"][2]["id"],
        ]
        assert [attempt["status"] for attempt in job["attempts"]] == [
            "printed",
            "pending",
            "pending",
            "printed",
        ]

        second = await _finished(hass, job["id"])
    finally:
        COORDINATOR.plants["B"] = _plant("B")

    assert [attempt["status"] for attempt in second["attempts"]] == ["printed"] * 4
    replacements = _committed(printer)
    assert len(replacements) == 2
    assert [attempt["raster_identity"] for attempt in second["attempts"]] == [
        next(
            record["render"]["raster_identity"]
            for record in review["records"]
            if record["subject"] == attempt["subject"]
        )
        for attempt in second["attempts"]
    ]

    nothing = await _retry(
        hass, job_id=second["id"], acknowledgement=review["identity"]
    )
    assert nothing["refusal"]["code"] == "label_template.nothing_to_retry"


async def test_a_retry_is_held_to_the_same_consent(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    failing: _Failures,
    verified: None,
) -> None:
    await _calibrated(hass, printer)
    preflight = await _preflight(hass, plant_ids=["W"], copies=1)
    identity = preflight["preflight"]["identity"]
    failing.arm(1)
    started = await _print(
        hass, preflight_id=preflight["preflight_id"], acknowledgement=identity
    )
    first = await _finished(hass, started["job"]["id"])
    assert first["attempts"][0]["status"] == "failed"

    refused = await _retry(hass, job_id=first["id"])
    assert refused["refusal"]["blocked_by"] == ["warning_acknowledgement_required"]
    unauthorized = await _retry(hass, user=None, job_id=first["id"])
    assert unauthorized["refusal"]["code"] == "label_template.not_authorized"

    retried = await _retry(hass, job_id=first["id"], acknowledgement=identity)
    assert (await _finished(hass, retried["job"]["id"]))["attempts"][0][
        "status"
    ] == "printed"


# ---------------------------------------------------------------------------
# Holding
# ---------------------------------------------------------------------------


def test_a_job_outlives_its_review_but_not_the_session(hass: HomeAssistant) -> None:
    jobs = batch_job_holder(hass, ENTRY_ID)
    assert batch_job_holder(hass, ENTRY_ID) is jobs
    assert jobs is not approval_holder(hass, ENTRY_ID)

    now = dt_util.utcnow()
    held = jobs.hold(BATCH_JOB, "job", now=now)
    assert jobs.values(BATCH_JOB, now=now) == ["job"]
    assert jobs.get(held, BATCH_JOB, now=now + timedelta(minutes=59)) == "job"
    assert jobs.get(held, BATCH_JOB, now=now + timedelta(hours=1)) is None
    assert approval_holder(hass, ENTRY_ID).get(held, BATCH_PREFLIGHT) is None


# ---------------------------------------------------------------------------
# The shape the card is held to
# ---------------------------------------------------------------------------


@freeze_time("2026-09-21T00:00:00+00:00")
async def test_the_shared_batch_fixtures_are_exact(
    hass: HomeAssistant,
    printer: list[dict[str, Any]],
    failing: _Failures,
    pytestconfig: pytest.Config,
    verified: None,
) -> None:
    """One recorded response per payload the card's schemas parse."""
    hass.config.time_zone = "UTC"
    await _calibrated(hass, printer)

    preflight = await _preflight(hass, plant_ids=["A", "W"], copies=2)
    _fixture("label_batch_preflight_v1", preflight, pytestconfig)
    identity = preflight["preflight"]["identity"]
    _fixture(
        "label_batch_refused_v1",
        await _print(hass, preflight_id=preflight["preflight_id"]),
        pytestconfig,
    )

    failing.arm(2)
    started = await _print(
        hass, preflight_id=preflight["preflight_id"], acknowledgement=identity
    )
    _fixture("label_batch_started_v1", started, pytestconfig)
    await hass.async_block_till_done(wait_background_tasks=True)
    _fixture(
        "label_batch_job_v1",
        await _job(hass, job_id=started["job"]["id"]),
        pytestconfig,
    )
    retried = await _retry(hass, job_id=started["job"]["id"], acknowledgement=identity)
    _fixture("label_batch_retry_v1", retried, pytestconfig)
    await hass.async_block_till_done(wait_background_tasks=True)
