"""Tests for the unmigrated EC ramp curve repair (ADR-0046, workspace#108)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.ec_ramp_migration import (
    evaluate_ec_ramp_migration_issues,
)
from custom_components.growspace_manager.models import ECRampCurve
from homeassistant.core import HomeAssistant

MODULE = "custom_components.growspace_manager.ec_ramp_migration"


def _coordinator(*curves: ECRampCurve) -> MagicMock:
    coord = MagicMock()
    coord.services.config.ec_ramp_curves = {c.id: c for c in curves}
    return coord


def _evaluate(hass: HomeAssistant, coordinator: MagicMock):
    with (
        patch(f"{MODULE}.async_create_issue") as mock_create,
        patch(f"{MODULE}.async_delete_issue") as mock_delete,
    ):
        evaluate_ec_ramp_migration_issues(hass, coordinator)
    return mock_create, mock_delete


async def test_repair_raised_for_a_curve_without_an_owner(hass: HomeAssistant) -> None:
    """A curve stored before the binding existed is surfaced, never rewritten.

    The broken save path left the grower's typed name in ``stage`` and a
    growspace id in ``name``, so the repair labels the curve with what the grower
    will recognise in the EC Ramp list.
    """
    coordinator = _coordinator(
        ECRampCurve(id="c1", growspace_id="", name="gs_abc123", stage="9-Week Bloom")
    )

    mock_create, mock_delete = _evaluate(hass, coordinator)

    mock_delete.assert_not_called()
    mock_create.assert_called_once()
    args, kwargs = mock_create.call_args
    assert args[1] == DOMAIN
    assert args[2] == "ec_ramp_curve_unmigrated_c1"
    assert kwargs["translation_key"] == "ec_ramp_curve_unmigrated"
    assert kwargs["is_fixable"] is False
    assert kwargs["translation_placeholders"] == {"curve": "9-Week Bloom"}


async def test_repair_clears_once_the_curve_is_bound(hass: HomeAssistant) -> None:
    """Re-saving the curve heals it, so the repair deletes itself."""
    coordinator = _coordinator(
        ECRampCurve(id="c1", growspace_id="gs_1", name="9-Week Bloom", stage="flower")
    )

    mock_create, mock_delete = _evaluate(hass, coordinator)

    mock_create.assert_not_called()
    mock_delete.assert_called_once_with(hass, DOMAIN, "ec_ramp_curve_unmigrated_c1")


async def test_repair_is_per_curve(hass: HomeAssistant) -> None:
    """Each curve is evaluated independently."""
    coordinator = _coordinator(
        ECRampCurve(id="broken", growspace_id="", name="gs_1", stage="Bloom"),
        ECRampCurve(id="ok", growspace_id="gs_1", name="Veg Ramp", stage="veg"),
    )

    mock_create, mock_delete = _evaluate(hass, coordinator)

    mock_create.assert_called_once()
    assert mock_create.call_args.args[2] == "ec_ramp_curve_unmigrated_broken"
    mock_delete.assert_called_once_with(hass, DOMAIN, "ec_ramp_curve_unmigrated_ok")


@pytest.mark.parametrize(
    ("name", "stage", "expected"),
    [
        ("gs_abc", "9-Week Bloom", "9-Week Bloom"),  # corrupt: grower name in stage
        ("Veg Ramp", "", "Veg Ramp"),  # no stage at all
        ("", "", "c1"),  # nothing but the id
    ],
)
async def test_repair_labels_the_curve_with_the_best_available_name(
    hass: HomeAssistant, name: str, stage: str, expected: str
) -> None:
    """The placeholder degrades stage → name → id so the repair is never nameless."""
    coordinator = _coordinator(
        ECRampCurve(id="c1", growspace_id="", name=name, stage=stage)
    )

    mock_create, _ = _evaluate(hass, coordinator)

    assert mock_create.call_args.kwargs["translation_placeholders"] == {
        "curve": expected
    }
