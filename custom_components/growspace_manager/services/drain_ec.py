"""Service handlers for drain/runoff EC monitoring."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..const import (
    ATTR_DRAIN_EC,
    ATTR_DRAIN_VOLUME_ML,
    ATTR_FEED_EC,
    ATTR_FEED_VOLUME_ML,
    ATTR_GROWSPACE_ID,
    ATTR_MAX_EC_DELTA,
    ATTR_TARGET_RUNOFF_PERCENT,
    GrowspaceService,
)
from ..schemas import (
    CONFIGURE_DRAIN_MONITORING_SCHEMA,
    LOG_DRAIN_READING_SCHEMA,
)
from .utils import handle_service_errors
from homeassistant.core import HomeAssistant, ServiceCall

from ._definition import ServiceDefinition

if TYPE_CHECKING:
    from ..coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


@handle_service_errors
async def handle_log_drain_reading(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle logging a drain EC reading.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with growspace_id, feed_ec, drain_ec, and optional volumes.
    """
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]
    feed_ec: float = call.data[ATTR_FEED_EC]
    drain_ec: float = call.data[ATTR_DRAIN_EC]
    drain_volume_ml: float | None = call.data.get(ATTR_DRAIN_VOLUME_ML)
    feed_volume_ml: float | None = call.data.get(ATTR_FEED_VOLUME_ML)

    await coordinator.async_log_drain_reading(
        growspace_id=growspace_id,
        feed_ec=feed_ec,
        drain_ec=drain_ec,
        drain_volume_ml=drain_volume_ml,
        feed_volume_ml=feed_volume_ml,
    )

    _LOGGER.info(
        "Logged drain reading for %s: feed=%.2f, drain=%.2f",
        growspace_id,
        feed_ec,
        drain_ec,
    )


@handle_service_errors
async def handle_configure_drain_monitoring(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle configuring drain EC monitoring settings.

    Args:
        hass: The Home Assistant instance.
        coordinator: The GrowspaceCoordinator instance.
        call: The service call with growspace_id and optional settings.
    """
    growspace_id: str = call.data[ATTR_GROWSPACE_ID]
    enabled: bool | None = call.data.get("enabled")
    max_ec_delta: float | None = call.data.get(ATTR_MAX_EC_DELTA)
    target_runoff_percent: float | None = call.data.get(ATTR_TARGET_RUNOFF_PERCENT)

    await coordinator.async_configure_drain_monitoring(
        growspace_id=growspace_id,
        enabled=enabled,
        max_ec_delta=max_ec_delta,
        target_runoff_percent=target_runoff_percent,
    )

    _LOGGER.info("Updated drain monitoring config for %s", growspace_id)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.LOG_DRAIN_READING,
        handle_log_drain_reading,
        LOG_DRAIN_READING_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.CONFIGURE_DRAIN_MONITORING,
        handle_configure_drain_monitoring,
        CONFIGURE_DRAIN_MONITORING_SCHEMA,
    ),
]
