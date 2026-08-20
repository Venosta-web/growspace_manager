"""Tests for the exhaust-fan sole-ownership migration repair (ADR-0019)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exhaust_migration import (
    evaluate_exhaust_migration_issues,
)
from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.models.growspace import (
    ExhaustFanConfig,
    Growspace,
)
from homeassistant.core import HomeAssistant


def _growspace(
    *,
    control_dehumidifier: bool,
    exhaust_fan_entities: list[str],
    exhaust_enabled: bool,
    gs_id: str = "gs1",
    name: str = "Tent 1",
) -> Growspace:
    """Build a growspace with the migration-relevant fields set."""
    return Growspace(
        id=gs_id,
        name=name,
        environment_config=EnvironmentConfig(
            control_dehumidifier=control_dehumidifier,
            exhaust_fan_entities=exhaust_fan_entities,
            exhaust_fan_config=ExhaustFanConfig(enabled=exhaust_enabled),
        ),
    )


def _coordinator(*growspaces: Growspace) -> MagicMock:
    coord = MagicMock()
    coord.growspaces = {gs.id: gs for gs in growspaces}
    return coord


@pytest.mark.parametrize(
    ("control_dehumidifier", "exhaust_fan_entities", "exhaust_enabled"),
    [
        (False, ["fan.exhaust"], False),  # dehumidifier control off
        (True, [], False),  # no exhaust fans configured
        (True, ["fan.exhaust"], True),  # new controller already enabled
    ],
)
async def test_no_repair_when_condition_absent(
    hass: HomeAssistant,
    control_dehumidifier: bool,
    exhaust_fan_entities: list[str],
    exhaust_enabled: bool,
) -> None:
    """The repair is not raised unless all three trigger conditions hold."""
    coordinator = _coordinator(
        _growspace(
            control_dehumidifier=control_dehumidifier,
            exhaust_fan_entities=exhaust_fan_entities,
            exhaust_enabled=exhaust_enabled,
        )
    )

    with (
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_create_issue"
        ) as mock_create,
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_delete_issue"
        ) as mock_delete,
    ):
        evaluate_exhaust_migration_issues(hass, coordinator)

    mock_create.assert_not_called()
    mock_delete.assert_called_once_with(hass, DOMAIN, "exhaust_fan_migration_gs1")


async def test_repair_raised_when_condition_holds(hass: HomeAssistant) -> None:
    """The repair is raised for an install relying on the old behavior."""
    coordinator = _coordinator(
        _growspace(
            control_dehumidifier=True,
            exhaust_fan_entities=["fan.exhaust"],
            exhaust_enabled=False,
            name="Flower Tent",
        )
    )

    with (
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_create_issue"
        ) as mock_create,
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_delete_issue"
        ) as mock_delete,
    ):
        evaluate_exhaust_migration_issues(hass, coordinator)

    mock_delete.assert_not_called()
    mock_create.assert_called_once()
    _, kwargs = mock_create.call_args
    assert kwargs["translation_key"] == "exhaust_fan_migration"
    assert kwargs["is_fixable"] is False
    assert kwargs["translation_placeholders"] == {"growspace": "Flower Tent"}
    args = mock_create.call_args.args
    assert args[1] == DOMAIN
    assert args[2] == "exhaust_fan_migration_gs1"


async def test_repair_is_per_growspace(hass: HomeAssistant) -> None:
    """Each growspace is evaluated independently."""
    coordinator = _coordinator(
        _growspace(
            control_dehumidifier=True,
            exhaust_fan_entities=["fan.exhaust"],
            exhaust_enabled=False,
            gs_id="affected",
        ),
        _growspace(
            control_dehumidifier=False,
            exhaust_fan_entities=[],
            exhaust_enabled=False,
            gs_id="clean",
        ),
    )

    with (
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_create_issue"
        ) as mock_create,
        patch(
            "custom_components.growspace_manager.exhaust_migration.async_delete_issue"
        ) as mock_delete,
    ):
        evaluate_exhaust_migration_issues(hass, coordinator)

    mock_create.assert_called_once()
    assert mock_create.call_args.args[2] == "exhaust_fan_migration_affected"
    mock_delete.assert_called_once_with(hass, DOMAIN, "exhaust_fan_migration_clean")
