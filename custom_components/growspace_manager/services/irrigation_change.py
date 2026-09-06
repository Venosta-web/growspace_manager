"""Irrigation Change — the one write seam for irrigation configuration writes.

The interface owns canonical field classification, normalization, validation,
atomic replacement and the effects that follow a successful change. Home
Assistant actions and config-flow handlers are transport adapters for it.

Four kinds of operation share the seam (ADR-0046):

- a **sparse patch** — the settings, strategy, options-flow and steering-phase
  transports each submit the fields a grower edited;
- a **clear** — a whole reset of ``IrrigationConfig`` that disables steering;
- a **Recipe Stamp** — a recipe identity resolved against the live target,
  optionally carrying the [[Program Progression]] context that makes the entry
  read as an automatic advance rather than a grower's own apply;
- a **Steering Mode stamp** — a mode name the seam expands into ordinary
  strategy fields from the server-owned preset table (ADR-0012).

They differ only in how the candidate state is *resolved*. Everything after
that — post-change validation, the atomic swap, persistence, rollback, the
logbook entry and the refresh — is identical, which is why they share one
function rather than separate writers that drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields as dataclass_fields, replace
from enum import StrEnum
import logging
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    EVENT_GROWSPACE_LOG_ENTRY,
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.domain.irrigation_recipe import (
    RecipeApplication,
    resolve_recipe_application,
)
from custom_components.growspace_manager.domain.plant_metrics import count_live_plants
from custom_components.growspace_manager.domain.shot_sizing import (
    dripper_flow_rate_ml_per_sec,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import (
    IrrigationConfig,
    SubstrateProfile,
)
from custom_components.growspace_manager.steering_presets import resolve_steering_preset
from homeassistant.util.dt import now, utcnow

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
    from custom_components.growspace_manager.models import Growspace
    from custom_components.growspace_manager.models.irrigation_recipe import (
        IrrigationRecipe,
    )

_LOGGER = logging.getLogger(__name__)


class IrrigationChangeError(ValueError):
    """A payload that cannot become an Irrigation Change."""


class IrrigationChangeOperation(StrEnum):
    """The public operation that submitted an Irrigation Change."""

    SETTINGS = "settings"
    STRATEGY = "strategy"
    OPTIONS = "options"
    STEERING_PHASE = "steering_phase"
    CLEAR = "clear"
    STEERING_MODE = "steering_mode"
    RECIPE = "recipe"


# Fields owned by the grower-facing settings interface. Schedule collections,
# EC target ranges, the active steering phase and its timestamp have dedicated
# owners and are deliberately absent — the phase belongs to the steering-phase
# operation below, so an unrelated settings save can never carry a stale phase
# over what the [[Steering Phase Machine]] decided.
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
        "skip_p2_after_p1",
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

# The one field a grower may write through the steering-phase operation
# (ADR-0012's manual phase override). ``phase_changed_at`` is derived here, not
# submitted: it records when the phase became what it is, and a transport that
# could state it separately could state a time the phase never changed.
IRRIGATION_PHASE_CHANGE_FIELDS: frozenset[str] = frozenset({"active_steering_phase"})

# The one field the Steering Mode stamp accepts. It is not a stored field: the
# seam expands it into ordinary strategy setpoints from the server-owned preset
# table and records the mode itself as declared intent, so a transport names a
# mode and can never hand-write the values that mode is supposed to mean.
IRRIGATION_STEERING_MODE_CHANGE_FIELDS: frozenset[str] = frozenset({"steering_mode"})

# Every field of IrrigationConfig, used to describe what a clear reset.
_IRRIGATION_CONFIG_FIELD_NAMES: frozenset[str] = frozenset(
    field.name for field in dataclass_fields(IrrigationConfig)
)

# What a clear leaves on the strategy. A clear resets the config and stops the
# growspace steering; it deliberately does not reset the rest of the strategy,
# which stays as the grower left it. ``shot_sizing_mode`` goes back to Seconds
# because Volume Mode is defined by a pump flow rate and a substrate profile
# and the clear has just taken the flow rate away — a growspace left in Volume
# Mode with no way to size a shot is a state the seam refuses to persist for
# every other operation, so a clear must not create it either.
_CLEARED_STRATEGY_VALUES: dict[str, Any] = {
    "enabled": False,
    "shot_sizing_mode": ShotSizingMode.SECONDS,
}

# Config fields this seam may write, whatever the operation. The phase pair is
# reachable only through the steering-phase operation; it is listed here so the
# derived timestamp survives the config/strategy split below.
_WRITABLE_CONFIG_FIELDS: frozenset[str] = (
    IRRIGATION_CONFIG_CHANGE_FIELDS
    | IRRIGATION_PHASE_CHANGE_FIELDS
    | frozenset({"phase_changed_at"})
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
class ProgramAdvance:
    """Why a Recipe Stamp is happening, when nobody asked for it directly.

    The one thing [[Program Progression]] knows that this module does not: an
    automatic stamp is an *advance*, and its logbook entry has to say which
    program carried a growspace into which week. Progression keeps slot
    selection, consent and the [[Program Hold]] decision; it hands over the
    subject of that one sentence and nothing else, so the recipe, the
    provenance and the commit effects stay owned here exactly as they are for
    a grower's explicit apply.
    """

    program_name: str
    stage: str | None
    week: int


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
    media_warning: str | None = None


def _accepted_fields(operation: IrrigationChangeOperation) -> frozenset[str]:
    """Return the compatibility surface for one public operation."""
    if operation is IrrigationChangeOperation.RECIPE:
        return frozenset({"recipe_id", "program_advance"})
    if operation is IrrigationChangeOperation.SETTINGS:
        return IRRIGATION_CONFIG_CHANGE_FIELDS | _CONFIG_ALIASES
    if operation is IrrigationChangeOperation.STRATEGY:
        return IRRIGATION_STRATEGY_CHANGE_FIELDS | _STRATEGY_ALIASES
    if operation is IrrigationChangeOperation.STEERING_PHASE:
        return IRRIGATION_PHASE_CHANGE_FIELDS
    if operation is IrrigationChangeOperation.STEERING_MODE:
        return IRRIGATION_STEERING_MODE_CHANGE_FIELDS
    if operation is IrrigationChangeOperation.CLEAR:
        # A clear carries no values: it names no setpoint, it restores the
        # model's own defaults. Anything sent with it is a caller confusing a
        # reset with a patch, and saying so beats writing half of each.
        return frozenset()
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

    # The steering-phase operation derives the timestamp the phase display and
    # the dryback readout both key off, exactly as the machine does when it
    # decides the same transition itself: stamped on entry to P3, and otherwise
    # left alone, because only a dryback is measured from it.
    if values.get("active_steering_phase") == "p3":
        values["phase_changed_at"] = now().isoformat()

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


@dataclass(frozen=True, slots=True)
class _Candidate:
    """The complete post-change state one operation asks for.

    ``config_fields`` and ``strategy_fields`` name what the operation set out
    to write, so the result can report which of them actually differ. They are
    not the same as "what changed": a re-stamp writes every preset field and
    changes none of them.
    """

    config: Any
    strategy: Any
    config_fields: frozenset[str]
    strategy_fields: frozenset[str]
    logbook_message: str | None = None
    media_warning: str | None = None


def resolve_validated_recipe_application(
    recipe: IrrigationRecipe,
    growspace: Growspace,
    *,
    live_plant_count: int,
) -> RecipeApplication:
    """Read what a Recipe Stamp accepts, including complete-state invariants.

    Program applicability and its temporary automatic writer use this same
    validation as explicit application. No live model or provenance is changed.
    """
    application = resolve_recipe_application(
        recipe,
        strategy=growspace.irrigation_strategy,
        config=growspace.irrigation_config,
        live_plant_count=live_plant_count,
    )
    _validate_candidate(
        replace(growspace.irrigation_config, **application.config_values),
        replace(growspace.irrigation_strategy, **application.values),
    )
    return application


def _resolve_recipe_candidate(
    change: IrrigationChange,
    growspace: Growspace,
    coordinator: GrowspaceCoordinator,
) -> _Candidate:
    """Resolve identity, target units and provenance inside the write owner."""
    recipe_id = change.values.get("recipe_id")
    if not isinstance(recipe_id, str) or not recipe_id.strip():
        raise IrrigationChangeError("A recipe change must name the recipe_id to stamp")
    advance = change.values.get("program_advance")
    if advance is not None and not isinstance(advance, ProgramAdvance):
        raise IrrigationChangeError(
            "program_advance must be a ProgramAdvance describing the automatic "
            "advance; a recipe change cannot author its own logbook entry"
        )
    recipe = coordinator._recipe_library.get_recipe(recipe_id)
    application = resolve_validated_recipe_application(
        recipe,
        growspace,
        live_plant_count=count_live_plants(
            coordinator.services.growspaces.get_growspace_plants(growspace.id)
        ),
    )
    updates = {
        **application.values,
        "applied_recipe_id": recipe.id,
        "recipe_applied_at": utcnow().isoformat(),
    }
    authored_media = recipe.provenance.media_type.value
    target_media = growspace.irrigation_strategy.substrate_profile.media_type.value
    # The entry says who asked. An advance names the program and the week it
    # moved to, because that is the whole of what the grower did not do; an
    # explicit apply names both media, because choosing across them is theirs.
    logbook_message = (
        f"Irrigation program '{advance.program_name}' advanced to "
        f"{advance.stage} week {advance.week}: applied recipe '{recipe.name}'"
        if advance is not None
        else (
            f"Applied irrigation recipe '{recipe.name}' "
            f"({authored_media} → {target_media})"
        )
    )
    return _Candidate(
        config=replace(growspace.irrigation_config, **application.config_values),
        strategy=replace(growspace.irrigation_strategy, **updates),
        config_fields=frozenset(application.config_values),
        strategy_fields=frozenset(updates),
        logbook_message=logbook_message,
        media_warning=application.media_warning,
    )


def _resolve_steering_mode(
    change: IrrigationChange, strategy: Any
) -> tuple[SteeringMode, SubstrateMediaType, dict[str, Any]]:
    """Expand a named Steering Mode into the strategy values it stamps."""
    submitted = change.values.get("steering_mode")
    if submitted is None:
        raise IrrigationChangeError(
            "A steering mode change must name the steering_mode to stamp"
        )
    try:
        mode = SteeringMode(submitted)
    except ValueError as err:
        raise IrrigationChangeError(f"Unknown steering mode '{submitted}'") from err

    media_type = strategy.substrate_profile.media_type
    # Resolved from the *stored* media type and the *active* Shot Sizing Mode:
    # the preset table keys agronomic levers by media and writes only the
    # representation the coordinator actually reads (ADR-0012).
    updates = dict(resolve_steering_preset(mode, media_type, strategy.shot_sizing_mode))
    updates["declared_steering_mode"] = mode
    return mode, media_type, updates


def _resolve_candidate(change: IrrigationChange, growspace: Any) -> _Candidate:
    """Build the post-change config and strategy one operation asks for."""
    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy

    if change.operation is IrrigationChangeOperation.CLEAR:
        return _Candidate(
            config=IrrigationConfig(),
            strategy=replace(prior_strategy, **_CLEARED_STRATEGY_VALUES),
            config_fields=_IRRIGATION_CONFIG_FIELD_NAMES,
            strategy_fields=frozenset(_CLEARED_STRATEGY_VALUES),
        )

    if change.operation is IrrigationChangeOperation.STEERING_MODE:
        mode, media_type, updates = _resolve_steering_mode(change, prior_strategy)
        return _Candidate(
            config=prior_config,
            strategy=replace(prior_strategy, **updates),
            config_fields=frozenset(),
            strategy_fields=frozenset(updates),
            logbook_message=(
                f"Applied {mode.value} steering mode ({media_type.value})"
            ),
        )

    values = _normalize_values(change, prior_strategy.substrate_profile)
    config_updates = {
        field: value
        for field, value in values.items()
        if field in _WRITABLE_CONFIG_FIELDS
    }
    strategy_updates = {
        field: value
        for field, value in values.items()
        if field in IRRIGATION_STRATEGY_CHANGE_FIELDS
    }
    return _Candidate(
        config=replace(prior_config, **config_updates),
        strategy=replace(prior_strategy, **strategy_updates),
        config_fields=frozenset(config_updates),
        strategy_fields=frozenset(strategy_updates),
    )


async def async_apply_irrigation_change(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    change: IrrigationChange,
) -> IrrigationChangeResult:
    """Apply one strict, atomic Irrigation Change.

    Ordering, whatever the operation: resolve and validate the candidate
    before the live growspace is touched, swap both models at once,
    invalidate, persist, and only then narrate and refresh. A persistence
    failure restores the prior models, so a refused write leaves neither
    changed state nor a logbook entry claiming it happened.
    """
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

    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy
    candidate = (
        _resolve_recipe_candidate(change, growspace, coordinator)
        if change.operation is IrrigationChangeOperation.RECIPE
        else _resolve_candidate(change, growspace)
    )
    _validate_candidate(candidate.config, candidate.strategy)
    changed_config_fields = frozenset(
        field
        for field in candidate.config_fields
        if getattr(prior_config, field) != getattr(candidate.config, field)
    )
    changed_strategy_fields = frozenset(
        field
        for field in candidate.strategy_fields
        if getattr(prior_strategy, field) != getattr(candidate.strategy, field)
    )

    growspace.irrigation_config = candidate.config
    growspace.irrigation_strategy = candidate.strategy
    coordinator.cache.invalidate(growspace_id)
    try:
        await coordinator.async_commit()
    except Exception:
        growspace.irrigation_config = prior_config
        growspace.irrigation_strategy = prior_strategy
        raise

    if candidate.logbook_message and candidate.config.log_to_logbook:
        coordinator.hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                ATTR_GROWSPACE_ID: growspace_id,
                "message": candidate.logbook_message,
                "category": "irrigation",
                "timestamp": now().isoformat(),
            },
        )
    if candidate.media_warning:
        _LOGGER.warning("%s", candidate.media_warning)
    await coordinator.async_request_refresh()

    return IrrigationChangeResult(
        operation=change.operation,
        changed_config_fields=changed_config_fields,
        changed_strategy_fields=changed_strategy_fields,
        media_warning=candidate.media_warning,
    )
