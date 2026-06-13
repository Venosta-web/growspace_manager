"""Volume Mode + Substrate Profile in the irrigation config-flow form (issue #455).

These tests drive the real ``GrowspaceFacade`` (not a mock) so the form's write
path and its Volume Mode gating are exercised exactly as production would, which
is the only way to prove the values truly round-trip onto the model.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.irrigation_config_handler import (
    IrrigationConfigHandler,
)
from custom_components.growspace_manager.const import ShotSizingMode, SubstrateMediaType
from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    SubstrateProfile,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


def _suggested_value(schema: vol.Schema, key: str):
    """Return the suggested_value seeded for a form field, or a sentinel."""
    for marker in schema.schema:
        if getattr(marker, "schema", None) == key:
            return (marker.description or {}).get("suggested_value", "<<missing>>")
    return "<<absent>>"


@pytest.fixture
def handler(mock_coordinator: MagicMock) -> IrrigationConfigHandler:
    """Handler wired to a real ServiceFacade over a configurable coordinator."""
    coordinator = mock_coordinator
    coordinator.cache = MagicMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    # The facade's get_growspace delegates to the data repository.
    coordinator._data_repository.get_growspace.side_effect = (  # noqa: SLF001
        lambda gid: coordinator.growspaces.get(gid)
    )

    config_entry = MagicMock()
    config_entry.runtime_data = coordinator
    config_entry.options = {}

    handler = IrrigationConfigHandler(MagicMock(spec=HomeAssistant), config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    handler.flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    return handler


def _add_growspace(
    coordinator: MagicMock,
    *,
    strategy: IrrigationStrategy | None = None,
    config: IrrigationConfig | None = None,
) -> Growspace:
    gs = Growspace(
        id="gs1",
        name="GS1",
        irrigation_config=config or IrrigationConfig(),
        irrigation_strategy=strategy or IrrigationStrategy(),
    )
    coordinator.growspaces = {"gs1": gs}
    return gs


async def test_volume_mode_fields_render(handler: IrrigationConfigHandler) -> None:
    """All new Volume Mode fields appear in the steering schema."""
    options = {"use_vwc_steering": True}
    schema = handler.get_irrigation_overview_schema(options, "gs1")
    keys = {getattr(m, "schema", m) for m in schema.schema}
    assert {
        "shot_sizing_mode",
        "substrate_media_type",
        "substrate_liters_per_pot",
        "pump_flow_rate_ml_per_sec",
        "p1_shot_volume_percent",
        "p2_shot_volume_percent",
    } <= keys


async def test_new_fields_seeded_from_stored_strategy(
    handler: IrrigationConfigHandler,
) -> None:
    """The form seeds defaults from the stored strategy/config, not hardcoded ones."""
    coordinator = handler.config_entry.runtime_data
    _add_growspace(
        coordinator,
        strategy=IrrigationStrategy(
            enabled=True,
            shot_sizing_mode=ShotSizingMode.VOLUME,
            substrate_profile=SubstrateProfile(
                media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=6.0
            ),
            p1_shot_volume_percent=3.0,
            p2_shot_volume_percent=5.0,
        ),
        config=IrrigationConfig(pump_flow_rate_ml_per_sec=12.5),
    )

    result = await handler.async_step_irrigation_overview()
    schema: vol.Schema = result["data_schema"]

    assert _suggested_value(schema, "shot_sizing_mode") == ShotSizingMode.VOLUME
    assert _suggested_value(schema, "substrate_media_type") == (
        SubstrateMediaType.ROCKWOOL
    )
    assert _suggested_value(schema, "substrate_liters_per_pot") == 6.0
    assert _suggested_value(schema, "pump_flow_rate_ml_per_sec") == 12.5
    assert _suggested_value(schema, "p1_shot_volume_percent") == 3.0
    assert _suggested_value(schema, "p2_shot_volume_percent") == 5.0


async def test_volume_mode_round_trips_through_real_facade(
    handler: IrrigationConfigHandler,
) -> None:
    """Submitting Volume Mode + profile + flow rate in one form persists on the model."""
    coordinator = handler.config_entry.runtime_data
    gs = _add_growspace(coordinator)

    user_input = {
        "shot_sizing_mode": ShotSizingMode.VOLUME.value,
        "substrate_media_type": SubstrateMediaType.ROCKWOOL.value,
        "substrate_liters_per_pot": 6.0,
        "pump_flow_rate_ml_per_sec": 15.0,
        "p1_shot_volume_percent": 3.0,
        "p2_shot_volume_percent": 5.0,
    }

    result = await handler.async_step_irrigation_overview(user_input)

    assert result["type"] == "create_entry"
    assert gs.irrigation_strategy.shot_sizing_mode == ShotSizingMode.VOLUME
    assert gs.irrigation_strategy.substrate_profile == SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=6.0
    )
    assert gs.irrigation_strategy.p1_shot_volume_percent == 3.0
    assert gs.irrigation_strategy.p2_shot_volume_percent == 5.0
    assert gs.irrigation_config.pump_flow_rate_ml_per_sec == 15.0


async def test_volume_mode_rejected_without_prerequisites_in_flow(
    handler: IrrigationConfigHandler,
) -> None:
    """Selecting Volume Mode with no profile/flow rate raises the shared error."""
    coordinator = handler.config_entry.runtime_data
    gs = _add_growspace(coordinator)

    with pytest.raises(ServiceValidationError, match="Volume Mode requires"):
        await handler.async_step_irrigation_overview(
            {"shot_sizing_mode": ShotSizingMode.VOLUME.value}
        )

    # The rejected submission leaves the strategy untouched.
    assert gs.irrigation_strategy.shot_sizing_mode == ShotSizingMode.SECONDS


async def test_seconds_mode_submission_unaffected(
    handler: IrrigationConfigHandler,
) -> None:
    """Seconds Mode users can submit without a profile and see no new behavior."""
    coordinator = handler.config_entry.runtime_data
    gs = _add_growspace(coordinator)

    result = await handler.async_step_irrigation_overview(
        {"shot_sizing_mode": ShotSizingMode.SECONDS.value, "irrigation_duration": 45}
    )

    assert result["type"] == "create_entry"
    assert gs.irrigation_strategy.shot_sizing_mode == ShotSizingMode.SECONDS
    assert gs.irrigation_config.irrigation_duration == 45
