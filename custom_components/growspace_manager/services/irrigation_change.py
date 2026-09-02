"""Irrigation Change — the one write seam for sparse irrigation changes.

The interface owns canonical field classification, normalization, validation,
atomic replacement and the effects that follow a successful change. Home
Assistant actions and config-flow handlers are transport adapters for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import ShotSizingMode, SubstrateMediaType
from custom_components.growspace_manager.domain.shot_sizing import (
    dripper_flow_rate_ml_per_sec,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import SubstrateProfile

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator


class IrrigationChangeError(ValueError):
    """A payload that cannot become an Irrigation Change."""


class IrrigationChangeOperation(StrEnum):
    """The public operation that submitted an Irrigation Change."""

    SETTINGS = "settings"
    STRATEGY = "strategy"
    OPTIONS = "options"


# Fields owned by the grower-facing settings interface. Schedule collections,
# EC target ranges, the active steering phase and its timestamp have dedicated
# owners and are deliberately absent.
IRRIGATION_CONFIG_CHANGE_FIELDS: frozenset[str] = frozenset(
    {
        "irrigation_pump_entity",
        "drain_pump_entity",
        "irrigation_duration",
        "drain_duration",
        "pump_flow_rate_ml_per_sec",
        "soil_trigger_percent",
        "daily_volume_cap_liters",
        "max_cycles_per_day",
        "skip_during_dark",
        "pause_on_low_tank",
        "log_to_logbook",
        "auto_advance_p1_to_p2",
        "auto_advance_p2_to_p3",
        "program_auto_advance",
        "halt_on_runoff_ec_threshold",
    }
)

# Canonical strategy fields owned by growers. detected_lights_on_time is an
# observed runtime value and declared_steering_mode belongs to the preset-stamp
# operation, so neither is writable through a sparse strategy change.
IRRIGATION_STRATEGY_CHANGE_FIELDS: frozenset[str] = frozenset(
    {
        "enabled",
        "lights_on_time",
        "p0_duration_minutes",
        "p2_stop_before_lights_off_minutes",
        "target_vwc_percent",
        "maintenance_dryback_percent",
        "p1_shot_duration_seconds",
        "p1_shot_interval_minutes",
        "p2_shot_duration_seconds",
        "p2_shot_interval_minutes",
        "auto_light_tracking",
        "shot_sizing_mode",
        "substrate_profile",
        "p1_shot_volume_percent",
        "p2_shot_volume_percent",
        "dynamic_shot_enabled",
        "dynamic_aggressiveness",
        "dynamic_recovery",
        "dynamic_shot_size_floor",
        "dynamic_interval_ceiling",
        "pore_ec_target_min",
        "pore_ec_target_max",
        "ec_modulation_enabled",
    }
)

# Compatibility spellings accepted by existing action/config-flow payloads.
_STRATEGY_ALIASES = frozenset(
    {
        "shot_duration_seconds",
        "shot_interval_minutes",
        "substrate_media_type",
        "substrate_liters_per_pot",
    }
)
# [[Dripper Throughput]]: the grower-facing input representation of
# ``pump_flow_rate_ml_per_sec``. Accepted as a pair here and collapsed into that
# single stored value during normalization — two numbers that must agree would
# be a reconciliation rule waiting to be written, so neither is persisted.
_CONFIG_ALIASES = frozenset({"dripper_liters_per_hour", "emitter_count"})
_OPTIONS_ALIASES = frozenset({"use_vwc_steering"})


@dataclass(frozen=True, slots=True)
class IrrigationChange:
    """One sparse irrigation edit from a public operation."""

    operation: IrrigationChangeOperation
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Take an immutable snapshot of the transport payload."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True, slots=True)
class IrrigationChangeResult:
    """Immutable description of an applied Irrigation Change."""

    operation: IrrigationChangeOperation
    changed_config_fields: frozenset[str]
    changed_strategy_fields: frozenset[str]


def _accepted_fields(operation: IrrigationChangeOperation) -> frozenset[str]:
    """Return the compatibility surface for one public operation."""
    if operation is IrrigationChangeOperation.SETTINGS:
        return IRRIGATION_CONFIG_CHANGE_FIELDS | _CONFIG_ALIASES
    if operation is IrrigationChangeOperation.STRATEGY:
        return IRRIGATION_STRATEGY_CHANGE_FIELDS | _STRATEGY_ALIASES
    return (
        IRRIGATION_CONFIG_CHANGE_FIELDS
        | IRRIGATION_STRATEGY_CHANGE_FIELDS
        | _CONFIG_ALIASES
        | _STRATEGY_ALIASES
        | _OPTIONS_ALIASES
    )


def _normalize_values(
    change: IrrigationChange, existing_profile: SubstrateProfile
) -> dict[str, Any]:
    """Translate compatibility spellings into canonical typed model values."""
    values = dict(change.values)

    if "use_vwc_steering" in values:
        values.setdefault("enabled", bool(values.pop("use_vwc_steering")))

    for alias, phase_fields in {
        "shot_duration_seconds": (
            "p1_shot_duration_seconds",
            "p2_shot_duration_seconds",
        ),
        "shot_interval_minutes": (
            "p1_shot_interval_minutes",
            "p2_shot_interval_minutes",
        ),
    }.items():
        if alias in values:
            alias_value = values.pop(alias)
            for phase_field in phase_fields:
                values.setdefault(phase_field, alias_value)

    liters_per_hour = values.pop("dripper_liters_per_hour", None)
    emitter_count = values.pop("emitter_count", None)
    if liters_per_hour is not None or emitter_count is not None:
        if liters_per_hour is None or emitter_count is None:
            raise IrrigationChangeError(
                "Dripper throughput needs both dripper_liters_per_hour and "
                "emitter_count; one alone does not name a flow rate."
            )
        if "pump_flow_rate_ml_per_sec" in values:
            raise IrrigationChangeError(
                "Set the pump flow rate either directly or as dripper "
                "throughput, not both; there is one stored value and no rule "
                "for reconciling two answers."
            )
        values["pump_flow_rate_ml_per_sec"] = dripper_flow_rate_ml_per_sec(
            float(liters_per_hour), int(emitter_count)
        )

    profile_update = values.pop("substrate_profile", None)
    media_type = values.pop("substrate_media_type", None)
    liters_per_pot = values.pop("substrate_liters_per_pot", None)
    if (
        profile_update is not None
        or media_type is not None
        or liters_per_pot is not None
    ):
        if isinstance(profile_update, SubstrateProfile):
            profile_data: dict[str, Any] = {
                "media_type": profile_update.media_type,
                "liters_per_pot": profile_update.liters_per_pot,
            }
        elif isinstance(profile_update, Mapping):
            profile_data = dict(profile_update)
        elif profile_update is None:
            profile_data = {}
        else:
            raise IrrigationChangeError("substrate_profile must be a mapping")
        if media_type is not None:
            profile_data["media_type"] = media_type
        if liters_per_pot is not None:
            profile_data["liters_per_pot"] = liters_per_pot
        values["substrate_profile"] = SubstrateProfile(
            media_type=SubstrateMediaType(
                profile_data.get("media_type", existing_profile.media_type)
            ),
            liters_per_pot=float(
                profile_data.get("liters_per_pot", existing_profile.liters_per_pot)
            ),
        )

    for pump_field in ("irrigation_pump_entity", "drain_pump_entity"):
        if pump_field in values and not values[pump_field]:
            values[pump_field] = None

    if "shot_sizing_mode" in values:
        values["shot_sizing_mode"] = ShotSizingMode(values["shot_sizing_mode"])

    return values


def _validate_candidate(config: Any, strategy: Any) -> None:
    """Validate invariants against the complete post-change state."""
    if strategy.shot_sizing_mode is ShotSizingMode.VOLUME and (
        strategy.substrate_profile.liters_per_pot <= 0.0
        or config.pump_flow_rate_ml_per_sec <= 0.0
    ):
        raise IrrigationChangeError(
            "Volume Mode requires a substrate profile (liters per pot) and a "
            "pump flow rate to be configured first."
        )

    band_min = strategy.pore_ec_target_min
    band_max = strategy.pore_ec_target_max
    if band_min is not None and band_max is not None and band_min >= band_max:
        raise IrrigationChangeError(
            f"Pore EC target band invalid: min ({band_min}) must be below "
            f"max ({band_max})"
        )


async def async_apply_irrigation_change(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    change: IrrigationChange,
) -> IrrigationChangeResult:
    """Apply one strict, atomic Irrigation Change."""
    accepted = _accepted_fields(change.operation)
    for field in change.values:
        if field not in accepted:
            raise IrrigationChangeError(
                f"Field '{field}' is not writable by the "
                f"{change.operation.value} irrigation operation"
            )

    growspace = coordinator.growspaces.get(growspace_id)
    if growspace is None:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    values = _normalize_values(change, growspace.irrigation_strategy.substrate_profile)
    config_updates = {
        field: value
        for field, value in values.items()
        if field in IRRIGATION_CONFIG_CHANGE_FIELDS
    }
    strategy_updates = {
        field: value
        for field, value in values.items()
        if field in IRRIGATION_STRATEGY_CHANGE_FIELDS
    }
    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy
    candidate_config = replace(prior_config, **config_updates)
    candidate_strategy = replace(prior_strategy, **strategy_updates)
    _validate_candidate(candidate_config, candidate_strategy)
    changed_config_fields = frozenset(
        field
        for field in config_updates
        if getattr(prior_config, field) != getattr(candidate_config, field)
    )
    changed_strategy_fields = frozenset(
        field
        for field in strategy_updates
        if getattr(prior_strategy, field) != getattr(candidate_strategy, field)
    )

    growspace.irrigation_config = candidate_config
    growspace.irrigation_strategy = candidate_strategy
    coordinator.cache.invalidate(growspace_id)
    try:
        await coordinator.async_commit()
    except Exception:
        growspace.irrigation_config = prior_config
        growspace.irrigation_strategy = prior_strategy
        raise
    await coordinator.async_request_refresh()

    return IrrigationChangeResult(
        operation=change.operation,
        changed_config_fields=changed_config_fields,
        changed_strategy_fields=changed_strategy_fields,
    )
