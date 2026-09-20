"""Preflight, print, and failed-only retry for label batches (hub issue #222)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.labels.batch import (
    AttemptStatus,
    BatchRefused,
    async_preflight_batch,
    async_print_batch,
    async_retry_failed_batch,
)
from custom_components.growspace_manager.labels.calibration import (
    LocalCalibrationLedger,
    PlacementMeasurement,
)
from custom_components.growspace_manager.labels.canonical import (
    FACTORY_50X30,
    NIIMBOT_B1_50X30,
    Blocker,
    ProfileEvidence,
    Severity,
)
from custom_components.growspace_manager.labels.printing import (
    LayoutSource,
    PrintOutcome,
    async_print_calibration_label,
)
from custom_components.growspace_manager.models.plant import Plant, PlantGenetics
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .support import StubFonts

AS_OF = datetime(2026, 9, 20, 9, 30, tzinfo=UTC)
DEVICE = "printer-a"
FONTS = StubFonts()
VERIFIED = replace(NIIMBOT_B1_50X30, evidence=ProfileEvidence.PRODUCT_VERIFIED)
MEASUREMENT = PlacementMeasurement(
    top_mm=0.5, right_mm=0.5, bottom_mm=0.0, left_mm=0.5, feed_mm=-0.4
)


@pytest.fixture
def ledger(hass: HomeAssistant) -> LocalCalibrationLedger:
    """One real append-only calibration ledger."""
    return LocalCalibrationLedger(hass, "entry-a")


def _plant(plant_id: str, *, strain: str = "Blue Dream") -> Plant:
    return Plant(
        plant_id=plant_id,
        growspace_id="tent",
        genetics=PlantGenetics(strain_name=strain, phenotype_name="Pheno 3"),
        stage="flower",
        veg_start="2026-07-01T08:00:00+00:00",
        flower_start="2026-09-02T09:15:00+00:00",
    )


def _coordinator(*plants: Plant) -> MagicMock:
    coordinator = MagicMock()
    coordinator.plants = {plant.plant_id: plant for plant in plants}
    return coordinator


def _library() -> MagicMock:
    library = MagicMock()
    library.load = AsyncMock()
    library.get_all = MagicMock(
        return_value={
            "Blue Dream": {
                "meta": {
                    "breeder": "Humboldt Seed Co.",
                    "lineage": "Blueberry x Haze",
                },
                "phenotypes": {"Pheno 3": {}},
            }
        }
    )
    return library


async def _calibrate(
    hass: HomeAssistant,
    ledger: LocalCalibrationLedger,
    admin: Any,
    printer: list[dict[str, Any]],
) -> None:
    printed = await async_print_calibration_label(
        hass,
        profile=VERIFIED,
        actor=admin,
        device_id=DEVICE,
        as_of=AS_OF,
        fonts=FONTS,
    )
    await ledger.async_record(
        admin,
        measurement=MEASUREMENT,
        dependencies=printed.dependencies,
        sheet_raster_identity=printed.sheet_raster_identity,
        printed_density="normal",
    )
    printer.clear()


async def _preflight(
    hass: HomeAssistant,
    ledger: LocalCalibrationLedger,
    actor: Any,
    plants: list[Plant],
    *,
    copies: int = 1,
):
    with patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        return_value="http://ha.test:8123",
    ):
        return await async_preflight_batch(
            hass,
            _coordinator(*plants),
            _library(),
            plant_ids=[plant.plant_id for plant in plants],
            copies=copies,
            source=LayoutSource.from_factory(FACTORY_50X30),
            profile=VERIFIED,
            ledger=ledger,
            actor=actor,
            device_id=DEVICE,
            as_of=AS_OF,
            fonts=FONTS,
        )


async def test_preflight_captures_and_renders_every_record_before_printing(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(
        hass,
        ledger,
        admin,
        [_plant("A"), _plant("B"), _plant("C")],
        copies=2,
    )

    assert [record.snapshot.subject for record in preflight.records] == ["A", "B", "C"]
    assert all(record.render.raster is not None for record in preflight.records)
    assert {record.snapshot.as_of for record in preflight.records} == {AS_OF}
    assert all(call["preview"] for call in printer)
    assert [
        (attempt.subject, attempt.copy_index) for attempt in preflight.attempts
    ] == [("A", 1), ("B", 1), ("C", 1), ("A", 2), ("B", 2), ("C", 2)]
    assert {attempt.as_dict()["status"] for attempt in preflight.attempts} == {
        "pending"
    }


async def test_one_hard_record_error_blocks_the_whole_rendered_batch(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(
        hass,
        ledger,
        admin,
        [_plant("A"), _plant("B", strain=""), _plant("C")],
    )
    printer.clear()

    assert len(preflight.records) == 3
    assert not preflight.allowed
    assert any(
        item.subject == "B" and item.diagnostic.severity is Severity.ERROR
        for item in preflight.diagnostics
    )
    with pytest.raises(BatchRefused) as refusal:
        await async_print_batch(
            hass, preflight=preflight, ledger=ledger, actor=admin, fonts=FONTS
        )
    assert str(Blocker.BLOCKING_DIAGNOSTICS) in refusal.value.blockers
    assert printer == []


async def test_warnings_require_consent_for_the_complete_preflight_identity(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    # No phenotype makes the factory template's phenotype element warn.
    plant = _plant("A")
    plant.genetics = PlantGenetics(strain_name="Blue Dream", phenotype_name="default")
    preflight = await _preflight(hass, ledger, admin, [plant])
    printer.clear()

    assert preflight.acknowledgement_required
    warning = next(item for item in preflight.warnings)
    assert warning.subject == "A"
    assert warning.diagnostic.element_id is not None

    with pytest.raises(BatchRefused) as missing:
        await async_print_batch(
            hass, preflight=preflight, ledger=ledger, actor=admin, fonts=FONTS
        )
    assert missing.value.blockers == (str(Blocker.WARNING_ACKNOWLEDGEMENT_REQUIRED),)

    with pytest.raises(BatchRefused) as changed:
        await async_print_batch(
            hass,
            preflight=preflight,
            ledger=ledger,
            actor=admin,
            acknowledgement="sha256:another-preflight",
            fonts=FONTS,
        )
    assert changed.value.blockers == (str(Blocker.PREFLIGHT_NOT_CURRENT),)
    assert printer == []

    result = await async_print_batch(
        hass,
        preflight=preflight,
        ledger=ledger,
        actor=admin,
        acknowledgement=preflight.identity,
        fonts=FONTS,
    )
    assert [item.status for item in result.attempts] == [AttemptStatus.PRINTED]
    assert result.as_dict()["attempts"][0]["status"] == "printed"
    json.dumps(result.as_dict())


async def test_changed_calibration_invalidates_the_review_before_output(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(hass, ledger, admin, [_plant("A")])
    changed = replace(preflight, calibration_identity="sha256:older-calibration")
    printer.clear()

    with pytest.raises(BatchRefused) as refusal:
        await async_print_batch(
            hass,
            preflight=changed,
            ledger=ledger,
            actor=admin,
            acknowledgement=changed.identity,
            fonts=FONTS,
        )
    assert refusal.value.blockers == (str(Blocker.PREFLIGHT_NOT_CURRENT),)
    assert printer == []


async def test_a_warning_free_preflight_needs_no_acknowledgement(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(hass, ledger, admin, [_plant("A")])
    warning_free = replace(
        preflight,
        diagnostics=tuple(
            item
            for item in preflight.diagnostics
            if item.diagnostic.severity is not Severity.WARNING
        ),
        calibration_warnings=(),
    )

    with patch(
        "custom_components.growspace_manager.labels.batch._async_judge_then_print",
        return_value=MagicMock(spec=PrintOutcome),
    ):
        result = await async_print_batch(
            hass,
            preflight=warning_free,
            ledger=ledger,
            actor=admin,
            fonts=FONTS,
        )
    assert result.attempts[0].status is AttemptStatus.PRINTED


async def test_retry_selects_failed_attempts_in_original_order_and_snapshots(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(
        hass,
        ledger,
        admin,
        [_plant("A"), _plant("B"), _plant("C")],
        copies=2,
    )
    originals = {
        record.snapshot.subject: record.snapshot for record in preflight.records
    }
    calls: list[Any] = []

    async def first_run(*args: Any, **kwargs: Any) -> PrintOutcome:
        calls.append(kwargs["content"])
        if len(calls) in {2, 4}:
            raise HomeAssistantError("printer unavailable")
        return MagicMock(spec=PrintOutcome)

    with patch(
        "custom_components.growspace_manager.labels.batch._async_judge_then_print",
        side_effect=first_run,
    ):
        first = await async_print_batch(
            hass,
            preflight=preflight,
            ledger=ledger,
            actor=admin,
            acknowledgement=preflight.identity,
            fonts=FONTS,
        )

    assert [item.status for item in first.attempts] == [
        AttemptStatus.PRINTED,
        AttemptStatus.FAILED,
        AttemptStatus.PRINTED,
        AttemptStatus.FAILED,
        AttemptStatus.PRINTED,
        AttemptStatus.PRINTED,
    ]
    retry_calls: list[Any] = []

    async def retry_run(*args: Any, **kwargs: Any) -> PrintOutcome:
        retry_calls.append(kwargs["content"])
        return MagicMock(spec=PrintOutcome)

    with patch(
        "custom_components.growspace_manager.labels.batch._async_judge_then_print",
        side_effect=retry_run,
    ):
        retried = await async_retry_failed_batch(
            hass,
            previous=first,
            ledger=ledger,
            actor=admin,
            acknowledgement=preflight.identity,
            fonts=FONTS,
        )

    assert [snapshot.subject for snapshot in retry_calls] == ["B", "A"]
    assert retry_calls == [originals["B"], originals["A"]]
    assert retried.attempted_ids == (
        preflight.attempts[1].id,
        preflight.attempts[3].id,
    )
    assert all(item.status is AttemptStatus.PRINTED for item in retried.attempts)


async def test_batch_wire_forms_name_every_attempt_and_are_json_safe(
    hass, printer, admin, ledger
) -> None:
    await _calibrate(hass, ledger, admin, printer)
    preflight = await _preflight(hass, ledger, admin, [_plant("A")])
    wire = preflight.as_dict()

    assert wire["identity"] == preflight.identity
    assert wire["attempts"][0]["status"] == "pending"
    assert wire["records"][0]["render"]["raster"] is not None
    json.dumps(wire)


@pytest.mark.parametrize("copies", [0, -1, True, 1.5])
async def test_copy_count_is_an_explicit_positive_integer(
    hass, admin, ledger, copies: Any
) -> None:
    with pytest.raises(HomeAssistantError, match="positive integer"):
        await _preflight(hass, ledger, admin, [_plant("A")], copies=copies)


async def test_a_batch_requires_a_concrete_printer(hass, admin, ledger) -> None:
    with patch(
        "custom_components.growspace_manager.labels.canonical.subjects.get_url",
        return_value="http://ha.test:8123",
    ):
        with pytest.raises(HomeAssistantError, match="printer device ID"):
            await async_preflight_batch(
                hass,
                _coordinator(_plant("A")),
                _library(),
                plant_ids=["A"],
                copies=1,
                source=LayoutSource.from_factory(FACTORY_50X30),
                profile=VERIFIED,
                ledger=ledger,
                actor=admin,
                device_id=" ",
                as_of=AS_OF,
                fonts=FONTS,
            )
