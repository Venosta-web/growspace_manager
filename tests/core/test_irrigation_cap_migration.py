"""Legacy cap review is advisory; it never changes stored settings."""

from unittest.mock import MagicMock, patch

from custom_components.growspace_manager.irrigation_cap_migration import (
    evaluate_irrigation_cap_issues,
)
from custom_components.growspace_manager.models import Growspace


def test_legacy_pump_gets_repair_until_caps_and_flow_are_set() -> None:
    growspace = Growspace.from_dict(
        {
            "id": "old",
            "name": "Old",
            "irrigation_config": {"irrigation_pump_entity": "switch.pump"},
        }
    )
    coordinator = MagicMock()
    coordinator.growspaces = {growspace.id: growspace}
    hass = MagicMock()
    with (
        patch(
            "custom_components.growspace_manager.irrigation_cap_migration.async_create_issue"
        ) as create,
        patch(
            "custom_components.growspace_manager.irrigation_cap_migration.async_delete_issue"
        ) as delete,
    ):
        evaluate_irrigation_cap_issues(hass, coordinator)
        create.assert_called_once()
        delete.assert_not_called()
        assert growspace.irrigation_config.max_cycles_per_day is None

        growspace.irrigation_config.max_cycles_per_day = 10
        growspace.irrigation_config.daily_volume_cap_liters = 5.0
        growspace.irrigation_config.pump_flow_rate_ml_per_sec = 10.0
        evaluate_irrigation_cap_issues(hass, coordinator)
        delete.assert_called_once()
