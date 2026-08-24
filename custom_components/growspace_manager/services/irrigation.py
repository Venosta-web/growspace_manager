"""Service handlers for irrigation-related services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from custom_components.growspace_manager.const import (
    ATTR_DRAIN_TIMES,
    ATTR_DURATION,
    ATTR_FEED_EC_MAX,
    ATTR_FEED_EC_MIN,
    ATTR_GROWSPACE_ID,
    ATTR_IRRIGATION_TIMES,
    ATTR_STAGE,
    ATTR_STEERING_MODE,
    ATTR_TIME,
    GrowspaceService,
    SteeringMode,
)
from custom_components.growspace_manager.schemas import (
    ADD_DRAIN_TIME_SCHEMA,
    ADD_IRRIGATION_TIME_SCHEMA,
    APPLY_STEERING_MODE_SCHEMA,
    REMOVE_DRAIN_TIME_SCHEMA,
    REMOVE_IRRIGATION_TIME_SCHEMA,
    RUN_IRRIGATION_CYCLE_SCHEMA,
    SET_EC_TARGET_RANGE_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition
from .utils import handle_service_errors

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.irrigation_coordinator import (
        IrrigationCoordinator,
    )

_LOGGER = logging.getLogger(__name__)


async def _get_irrigation_coordinator(
    coordinator: GrowspaceCoordinator, growspace_id: str
) -> IrrigationCoordinator:
    """Get the irrigation coordinator for a specific growspace, raising on failure."""
    try:
        irr_coord = coordinator.services.growspaces.get_irrigation_coordinator(
            growspace_id
        )

        if irr_coord is None:
            growspace = coordinator.growspaces.get(growspace_id)
            if growspace:
                _LOGGER.info(
                    "Lazy initializing subsystems for growspace %s", growspace_id
                )
                await coordinator._subsystem_manager.async_setup_growspace_sub_coordinators(
                    growspace_id, growspace
                )
                irr_coord = coordinator.services.growspaces.get_irrigation_coordinator(
                    growspace_id
                )

            if irr_coord is None:
                raise ServiceValidationError(
                    f"Growspace '{growspace_id}' not found or has no irrigation setup."
                )
        return cast("IrrigationCoordinator", irr_coord)
    except AttributeError:
        raise ServiceValidationError(
            "Irrigation coordinators not found. Setup may be incomplete."
        ) from None


@handle_service_errors
async def handle_set_irrigation_settings(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation settings for a growspace."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)

    settings = {
        key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
    }

    await coordinator.services.growspaces.set_irrigation_settings(
        growspace_id, settings
    )
    _LOGGER.info("Set irrigation settings for growspace '%s'", growspace_id)


@handle_service_errors
async def handle_set_irrigation_strategy(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set irrigation strategy for a growspace."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)

    strategy = {
        key: value for key, value in call.data.items() if key != ATTR_GROWSPACE_ID
    }

    _build_substrate_profile_update(strategy)
    _validate_volume_mode_selection(coordinator, growspace_id, strategy)

    await coordinator.services.growspaces.set_irrigation_strategy(
        growspace_id, strategy
    )
    _LOGGER.info("Set irrigation strategy for growspace '%s'", growspace_id)


@handle_service_errors
async def handle_apply_steering_mode(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Stamp a Steering Mode's preset values into the strategy (ADR-0012).

    The grower names the mode; the server expands it into concrete strategy
    field values from its preset table and records the declared intent.
    """
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    mode = SteeringMode(call.data[ATTR_STEERING_MODE])
    await coordinator.services.growspaces.apply_steering_mode(growspace_id, mode)
    _LOGGER.info(
        "Applied %s steering mode for growspace '%s'", mode.value, growspace_id
    )


def _build_substrate_profile_update(strategy: dict) -> None:
    """Fold flat substrate-profile keys into a nested ``substrate_profile`` dict.

    The service surface accepts ``substrate_media_type`` / ``substrate_liters_per_pot``
    as flat fields; the model stores them on the nested ``SubstrateProfile``. We
    merge them into a single dict so the generic setattr-based config updater can
    deserialize them onto the strategy. Only the provided keys are touched so a
    partial update preserves the other half of the profile.
    """
    from custom_components.growspace_manager.const import (  # noqa: PLC0415
        SubstrateMediaType,
    )

    media_type = strategy.pop("substrate_media_type", None)
    liters_per_pot = strategy.pop("substrate_liters_per_pot", None)
    if media_type is None and liters_per_pot is None:
        return

    profile: dict[str, object] = {}
    if media_type is not None:
        profile["media_type"] = SubstrateMediaType(media_type).value
    if liters_per_pot is not None:
        profile["liters_per_pot"] = float(liters_per_pot)
    strategy["substrate_profile"] = profile


def _validate_volume_mode_selection(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    strategy: dict,
) -> None:
    """Reject selecting Volume Mode unless its prerequisites are met (ADR-0011).

    Volume Mode is opt-in and is only selectable when a substrate profile
    (positive liters-per-pot) and a positive pump flow rate are both configured.
    Prerequisites are evaluated against the post-update state so a single call may
    set the profile and the mode together.
    """
    from custom_components.growspace_manager.const import (  # noqa: PLC0415
        ShotSizingMode,
    )

    if strategy.get("shot_sizing_mode") != ShotSizingMode.VOLUME.value:
        return

    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        return

    # Effective values: an incoming update wins over the stored state for both
    # the per-pot volume and the pump flow rate, so a single call (e.g. the
    # config-flow form) may set the profile, the flow rate, and the mode at once.
    # The settings service stores the pump flow rate separately from the
    # strategy, so strategy updates fall back to the persisted config value.
    stored_profile = growspace.irrigation_strategy.substrate_profile
    profile_update = strategy.get("substrate_profile", {})
    liters_per_pot = profile_update.get("liters_per_pot", stored_profile.liters_per_pot)
    flow_rate = strategy.get(
        "pump_flow_rate_ml_per_sec",
        growspace.irrigation_config.pump_flow_rate_ml_per_sec,
    )

    if liters_per_pot <= 0.0 or flow_rate <= 0.0:
        raise ServiceValidationError(
            "Volume Mode requires a substrate profile (liters per pot) and a "
            "pump flow rate to be configured first."
        )


@handle_service_errors
async def handle_add_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add an irrigation time to a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

    duration = call.data.get(ATTR_DURATION)
    if duration is None:
        duration = irrigation_coord.get_default_duration("irrigation")

    await coordinator.services.growspaces.add_irrigation_schedule_item(
        growspace_id, ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME], duration
    )


@handle_service_errors
async def handle_remove_irrigation_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove an irrigation time from a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)
    await coordinator.services.growspaces.remove_irrigation_schedule_item(
        growspace_id, ATTR_IRRIGATION_TIMES, call.data[ATTR_TIME]
    )


@handle_service_errors
async def handle_add_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to add a drain time to a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)

    duration = call.data.get(ATTR_DURATION)
    if duration is None:
        duration = irrigation_coord.get_default_duration("drain")

    await coordinator.services.growspaces.add_irrigation_schedule_item(
        growspace_id, ATTR_DRAIN_TIMES, call.data[ATTR_TIME], duration
    )


@handle_service_errors
async def handle_remove_drain_time(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to remove a drain time from a schedule."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    await _get_irrigation_coordinator(coordinator, growspace_id)
    await coordinator.services.growspaces.remove_irrigation_schedule_item(
        growspace_id, ATTR_DRAIN_TIMES, call.data[ATTR_TIME]
    )


@handle_service_errors
async def handle_run_irrigation_cycle(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to manually trigger an irrigation cycle."""
    growspace_id = call.data[ATTR_GROWSPACE_ID]
    duration = call.data.get(ATTR_DURATION)
    irrigation_coord = await _get_irrigation_coordinator(coordinator, growspace_id)
    await irrigation_coord.async_manual_run(duration=duration)
    _LOGGER.info(
        "Manual irrigation cycle started for growspace '%s' (duration=%s)",
        growspace_id,
        duration,
    )


@handle_service_errors
async def handle_set_ec_target_range(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the service call to set (upsert) a feed EC target range for a stage."""
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]
    stage: str = call.data[ATTR_STAGE]
    feed_ec_min: float = call.data[ATTR_FEED_EC_MIN]
    feed_ec_max: float = call.data[ATTR_FEED_EC_MAX]

    await coordinator.services.growspaces.set_ec_target_range(
        growspace_id=growspace_id,
        stage=stage,
        feed_ec_min=feed_ec_min,
        feed_ec_max=feed_ec_max,
    )
    _LOGGER.info(
        "Set EC target range for growspace '%s' stage '%s': %.1f–%.1f",
        growspace_id,
        stage,
        feed_ec_min,
        feed_ec_max,
    )


SERVICES = [
    ServiceDefinition(
        GrowspaceService.RUN_IRRIGATION_CYCLE,
        handle_run_irrigation_cycle,
        RUN_IRRIGATION_CYCLE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_IRRIGATION_SETTINGS,
        handle_set_irrigation_settings,
        SET_IRRIGATION_SETTINGS_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_IRRIGATION_STRATEGY,
        handle_set_irrigation_strategy,
        SET_IRRIGATION_STRATEGY_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.APPLY_STEERING_MODE,
        handle_apply_steering_mode,
        APPLY_STEERING_MODE_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_IRRIGATION_TIME,
        handle_add_irrigation_time,
        ADD_IRRIGATION_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_IRRIGATION_TIME,
        handle_remove_irrigation_time,
        REMOVE_IRRIGATION_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.ADD_DRAIN_TIME,
        handle_add_drain_time,
        ADD_DRAIN_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_DRAIN_TIME,
        handle_remove_drain_time,
        REMOVE_DRAIN_TIME_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_EC_TARGET_RANGE,
        handle_set_ec_target_range,
        SET_EC_TARGET_RANGE_SCHEMA,
    ),
]
