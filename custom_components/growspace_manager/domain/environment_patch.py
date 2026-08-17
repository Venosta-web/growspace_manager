"""Environment Patch — the one write seam for EnvironmentConfig (ADR-0026).

Build validates, apply is total: the writer-specific builders normalise a raw
payload into an :class:`EnvironmentPatch` (raising
:class:`EnvironmentPatchError` on invalid input), and
:func:`apply_environment_patch` merges a built patch onto the existing config
without raising. Patch semantics throughout: a key absent from the payload
keeps the existing value; a key explicitly present — including an empty
list/dict — is a deliberate set or clear.

Merge behaviour derives entirely from ``ENVIRONMENT_FIELD_OWNERSHIP`` (declared
beside the model): grower-config fields are set when present, runtime-
accumulated state is always carried over from the existing config (including
the tank runtime fields, matched per item by ``sensor_entity``), and
sub-configs are replaced whole. Unknown keys mirror
``EnvironmentConfig.__pre_deserialize__``'s catch-all and merge into
``bayesian_options`` — that is how the advanced Bayesian/trend settings have
always been stored, so the builders must not reject them.

Pure module: no hass, no I/O, no logging. Effects (save, refresh, controller
restarts, the exhaust-repair re-evaluation) belong to the commit shell.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dc_field, fields, replace
from typing import Any

from custom_components.growspace_manager.const import FanRegulationMode
from custom_components.growspace_manager.models import (
    ENVIRONMENT_FIELD_OWNERSHIP,
    ACInfinityDevice,
    ACInfinityGrowLight,
    BaseModel,
    CirculationFanConfig,
    EnvironmentConfig,
    ExhaustFanConfig,
    FieldClass,
    GrowLightConfig,
    IrrigationTank,
    SensorGroup,
    VisionCheckupConfig,
)

from .fan_control import FAN_VPD_STAGE_DEFAULTS
from .moisture_band import MOISTURE_BAND_CEILING, MOISTURE_BAND_FLOOR, is_valid_band

_VALID_STAGE_KEYS = {stage.value for stage in FAN_VPD_STAGE_DEFAULTS}
_VPD_OVERRIDE_MIN = 0.1
_VPD_OVERRIDE_MAX = 3.0

# Wire-only singular spellings (not model fields), mirroring the migration
# table in EnvironmentConfig.__pre_deserialize__ and the service handlers'
# historic singular parameters. Model-field shadows (temperature_sensor etc.)
# are declared via ``canonical=`` on their ownership row instead.
_WIRE_ALIASES: dict[str, str] = {
    "light_sensor": "light_sensors",
    "exhaust_entity": "exhaust_fan_entities",
    "exhaust_fan_entity": "exhaust_fan_entities",
    "circulation_fan_entity": "circulation_fan_entities",
    "humidifier_entity": "humidifier_entities",
    "dehumidifier_entity": "dehumidifier_entities",
    "growlight_entity": "growlight_entities",
    "ph_sensor": "ph_sensors",
    "feed_ec_sensor": "feed_ec_sensors",
    "substrate_ec_sensor": "bulk_ec_sensors",
    "substrate_ec_sensors": "bulk_ec_sensors",
    "runoff_ec_sensor": "runoff_ec_sensors",
    "drain_volume_sensor": "drain_volume_sensors",
    "irrigation_flow_sensor": "irrigation_flow_sensors",
}
_SHADOW_ALIASES: dict[str, str] = {
    name: ownership.canonical
    for name, ownership in ENVIRONMENT_FIELD_OWNERSHIP.items()
    if ownership.canonical is not None
}
_ALL_ALIASES: dict[str, str] = {**_WIRE_ALIASES, **_SHADOW_ALIASES}

_ITEM_TYPES: dict[str, type[BaseModel]] = {
    "irrigation_tanks": IrrigationTank,
    "sensor_groups": SensorGroup,
    "exhaust_fan_ac_infinity_devices": ACInfinityDevice,
    "circulation_fan_ac_infinity_devices": ACInfinityDevice,
    "humidifier_ac_infinity_devices": ACInfinityDevice,
    "dehumidifier_ac_infinity_devices": ACInfinityDevice,
    "growlight_ac_infinity_devices": ACInfinityGrowLight,
}
_SUB_CONFIG_TYPES: dict[str, type[BaseModel]] = {
    "vision_checkup_config": VisionCheckupConfig,
    "circulation_fan_config": CirculationFanConfig,
    "exhaust_fan_config": ExhaustFanConfig,
    "growlight_config": GrowLightConfig,
}

# With PEP 649 lazy annotations, dataclass field types are strings — good
# enough to classify None-handling per field shape.
_NULLABLE_FIELDS = {f.name for f in fields(EnvironmentConfig) if "None" in str(f.type)}
_LIST_FIELDS = {
    f.name for f in fields(EnvironmentConfig) if str(f.type).startswith("list[")
}
# DehumidifierThresholds / BayesianOptions are dict type aliases.
_DICT_FIELDS = {
    f.name for f in fields(EnvironmentConfig) if str(f.type).startswith("dict[")
} | {"dehumidifier_thresholds", "bayesian_options"}

_CONTROLLER_RELEVANT_FIELDS: dict[str, frozenset[str]] = {
    "dehumidifier": frozenset(
        {
            "control_dehumidifier",
            "dehumidifier_entities",
            "dehumidifier_ac_infinity_devices",
            "dehumidifier_thresholds",
            "vpd_sensor",
            "light_sensors",
        }
    ),
    "humidifier": frozenset(
        {
            "control_humidifier",
            "humidifier_entities",
            "humidifier_ac_infinity_devices",
            "humidifier_thresholds",
            "vpd_sensor",
            "light_sensors",
        }
    ),
    "circulation_fan": frozenset(
        {
            "circulation_fan_config",
            "circulation_fan_entities",
            "circulation_fan_ac_infinity_devices",
        }
    ),
    "exhaust_fan": frozenset(
        {
            "exhaust_fan_config",
            "exhaust_fan_entities",
            "exhaust_fan_ac_infinity_devices",
        }
    ),
    # Day-hour changes move the photoperiod window the grow light derives its
    # schedule from, so they are growlight-relevant too.
    "growlight": frozenset(
        {
            "growlight_config",
            "growlight_entities",
            "growlight_ac_infinity_devices",
            "veg_day_hours",
            "flower_day_hours",
        }
    ),
}
_EXHAUST_REPAIR_FIELDS = frozenset(
    {"control_dehumidifier", "exhaust_fan_entities", "exhaust_fan_config"}
)


class EnvironmentPatchError(ValueError):
    """A payload that cannot become an Environment Patch.

    The message is user-presentable; shells translate to
    ServiceValidationError or config-flow form errors at the seam.
    """


@dataclass(frozen=True, slots=True)
class PatchWarning:
    """An input the builder dropped rather than rejected."""

    field: str
    message: str


@dataclass(frozen=True, slots=True)
class EnvironmentPatch:
    """The value a writer submits: the grower's edit.

    ``values`` maps canonical EnvironmentConfig field names to already-typed
    values (sub-configs are dataclass instances, dataclass-list fields hold
    parsed items). Absence of a field means "keep existing". Every key must be
    a classified, directly-patchable field — unknown names, runtime-accumulated
    fields, and singular shadows (patch the plural instead) are rejected here,
    so :func:`apply_environment_patch` never has to.

    ``bayesian_updates`` carries catch-all keys that merge *into*
    ``bayesian_options`` on apply; an explicit ``bayesian_options`` entry in
    ``values`` replaces the whole dict first.
    """

    values: Mapping[str, Any]
    bayesian_updates: Mapping[str, Any] = dc_field(default_factory=dict)
    warnings: tuple[PatchWarning, ...] = ()

    def __post_init__(self) -> None:
        """Reject keys the merge could not honour (programmer error)."""
        for name in self.values:
            ownership = ENVIRONMENT_FIELD_OWNERSHIP.get(name)
            if ownership is None:
                raise EnvironmentPatchError(f"Unknown EnvironmentConfig field '{name}'")
            if ownership.field_class is FieldClass.RUNTIME_ACCUMULATED:
                raise EnvironmentPatchError(
                    f"Field '{name}' is runtime-accumulated and cannot be patched"
                )
            if ownership.canonical is not None:
                raise EnvironmentPatchError(
                    f"Field '{name}' is a legacy shadow of '{ownership.canonical}'"
                    " — patch the plural field instead"
                )


@dataclass(frozen=True, slots=True)
class EnvironmentPatchVerdict:
    """The value applying an Environment Patch returns (Cycle Verdict mould).

    ``config`` is a fresh EnvironmentConfig — inputs are never mutated.
    ``changed_fields`` is computed by value comparison, so a patch restating
    current values changes nothing and restarts nothing. The verdict records
    the decision; the commit shell performs the effects.
    """

    config: EnvironmentConfig
    changed_fields: frozenset[str]
    controllers_to_restart: frozenset[str]
    exhaust_repair_relevant: bool
    summary: str
    warnings: tuple[PatchWarning, ...] = ()

    def changed(self, *field_names: str) -> bool:
        """Return True when any named field changed."""
        return bool(self.changed_fields.intersection(field_names))


def validate_stage_vpd_overrides(
    overrides: dict | None,
) -> dict[str, dict[str, float]]:
    """Validate stage_vpd_overrides, raising EnvironmentPatchError on bad input."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise EnvironmentPatchError("stage_vpd_overrides must be a dictionary.")
    for stage_key, entry in overrides.items():
        if stage_key not in _VALID_STAGE_KEYS:
            raise EnvironmentPatchError(
                f"Unknown stage key '{stage_key}' in stage_vpd_overrides. "
                f"Valid keys: {sorted(_VALID_STAGE_KEYS)}"
            )
        if not isinstance(entry, dict) or "day" not in entry or "night" not in entry:
            raise EnvironmentPatchError(
                f"Stage '{stage_key}' entry must contain both 'day' and 'night' keys."
            )
        for period in ("day", "night"):
            val = entry[period]
            if not isinstance(val, (int, float)):
                raise EnvironmentPatchError(
                    f"Stage '{stage_key}' {period} VPD override must be a number."
                )
            if not (_VPD_OVERRIDE_MIN <= val <= _VPD_OVERRIDE_MAX):
                raise EnvironmentPatchError(
                    f"Stage '{stage_key}' {period} VPD override {val} kPa is out of "
                    f"range ({_VPD_OVERRIDE_MIN}–{_VPD_OVERRIDE_MAX} kPa)."
                )
    return overrides


def validate_vpd_optimal_overrides(
    overrides: dict | None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Validate vpd_optimal_overrides, raising EnvironmentPatchError on bad input."""
    if overrides is None:
        return {}
    if not isinstance(overrides, dict):
        raise EnvironmentPatchError("vpd_optimal_overrides must be a dictionary.")
    for stage_key, entry in overrides.items():
        if stage_key not in _VALID_STAGE_KEYS:
            raise EnvironmentPatchError(
                f"Unknown stage key '{stage_key}' in vpd_optimal_overrides. "
                f"Valid keys: {sorted(_VALID_STAGE_KEYS)}"
            )
        if not isinstance(entry, dict) or "day" not in entry or "night" not in entry:
            raise EnvironmentPatchError(
                f"Stage '{stage_key}' entry must contain both 'day' and 'night' keys."
            )
        for period in ("day", "night"):
            period_entry = entry[period]
            if (
                not isinstance(period_entry, dict)
                or "low" not in period_entry
                or "high" not in period_entry
            ):
                raise EnvironmentPatchError(
                    f"Stage '{stage_key}' {period} entry must contain both "
                    "'low' and 'high' keys."
                )
            low = period_entry["low"]
            high = period_entry["high"]
            if not (_VPD_OVERRIDE_MIN <= low <= _VPD_OVERRIDE_MAX) or not (
                _VPD_OVERRIDE_MIN <= high <= _VPD_OVERRIDE_MAX
            ):
                raise EnvironmentPatchError(
                    f"Stage '{stage_key}' {period} VPD values out of range "
                    f"({_VPD_OVERRIDE_MIN}–{_VPD_OVERRIDE_MAX} kPa). "
                    f"Got low={low}, high={high}."
                )
            if low >= high:
                raise EnvironmentPatchError(
                    f"Stage '{stage_key}' {period}: low ({low}) must be < high "
                    f"({high})."
                )
    return overrides


def patch_from_service_call(data: Mapping[str, Any]) -> EnvironmentPatch:
    """Build an Environment Patch from a configure_environment service payload.

    Drops ``growspace_id`` (routing, not config). Singular aliases are
    rewritten onto their plural field — when both spellings are present, the
    plural wins. Invalid tank / sensor-group / AC-Infinity items are dropped
    into warnings (lenient, matching the historic behaviour); structural
    errors — bad VPD overrides, a non-dict where a dict is required — raise
    :class:`EnvironmentPatchError`.
    """
    return _build_patch(data, ignore_keys=frozenset({"growspace_id"}))


def patch_from_flow_options(options: Mapping[str, Any]) -> EnvironmentPatch:
    """Build an Environment Patch from a config-flow assembled options dict.

    Same normalisation core as :func:`patch_from_service_call`, additionally
    dropping the flow bookkeeping keys (``configure_advanced``,
    ``configure_dehumidifier``). ``stage_thresholds.py`` stays upstream as the
    form-encoding owner — its nested threshold tables arrive here as ordinary
    present keys.
    """
    return _build_patch(
        options,
        ignore_keys=frozenset({"configure_advanced", "configure_dehumidifier"}),
    )


def circulation_fan_patch(data: Mapping[str, Any]) -> EnvironmentPatch:
    """Build a one-field patch from a configure_circulation_fan payload.

    Sub-config semantics: the whole CirculationFanConfig is replaced, omitted
    keys taking the sub-config dataclass defaults.
    """
    return EnvironmentPatch(
        values={"circulation_fan_config": _parse_circulation_fan_config(data)}
    )


def exhaust_fan_patch(data: Mapping[str, Any]) -> EnvironmentPatch:
    """Build a one-field patch from a configure_exhaust_fan payload."""
    return EnvironmentPatch(
        values={"exhaust_fan_config": _parse_exhaust_fan_config(data)}
    )


def apply_environment_patch(
    current: EnvironmentConfig | None,
    patch: EnvironmentPatch,
) -> EnvironmentPatchVerdict:
    """Merge an Environment Patch onto the current config. Pure and total.

    ``current=None`` applies the patch onto dataclass defaults — this is the
    one-time options-blob migration path, where the patch items' own runtime
    values are adopted because there is nothing to carry over.

    Never raises on a built patch. Neither input is mutated; unpatched values
    are carried into the new config by reference, so callers should treat
    ``current`` as consumed once they adopt ``verdict.config``.
    """
    base = current if current is not None else EnvironmentConfig()
    new_kwargs: dict[str, Any] = {}
    for f in fields(EnvironmentConfig):
        ownership = ENVIRONMENT_FIELD_OWNERSHIP[f.name]
        if (
            ownership.field_class is FieldClass.RUNTIME_ACCUMULATED
            or f.name not in patch.values
        ):
            new_kwargs[f.name] = getattr(base, f.name)
        else:
            new_kwargs[f.name] = patch.values[f.name]

    if patch.bayesian_updates:
        merged = dict(new_kwargs["bayesian_options"] or {})
        merged.update(patch.bayesian_updates)
        new_kwargs["bayesian_options"] = merged

    # Nested runtime carry-over: a patched item matching an existing item by
    # identity keeps the existing runtime state; an unmatched item keeps its
    # own values (fresh tank, or the migration adopting a serialized blob).
    for name, ownership in ENVIRONMENT_FIELD_OWNERSHIP.items():
        if not ownership.item_runtime_fields or name not in patch.values:
            continue
        existing_by_id = {
            getattr(item, ownership.item_identity): item for item in getattr(base, name)
        }
        carried = []
        for item in new_kwargs[name]:
            match = existing_by_id.get(getattr(item, ownership.item_identity))
            if match is not None:
                item = replace(
                    item,
                    **{
                        runtime_field: getattr(match, runtime_field)
                        for runtime_field in ownership.item_runtime_fields
                    },
                )
            carried.append(item)
        new_kwargs[name] = carried

    # Re-derive singular shadows from their canonical plural so a stale
    # singular can never resurrect a deliberately cleared plural via
    # EnvironmentConfig.__post_init__.
    for name, ownership in ENVIRONMENT_FIELD_OWNERSHIP.items():
        if ownership.canonical is not None:
            plural = new_kwargs[ownership.canonical]
            new_kwargs[name] = plural[0] if plural else None

    config = EnvironmentConfig(**new_kwargs)

    changed = frozenset(
        f.name
        for f in fields(EnvironmentConfig)
        if getattr(config, f.name) != getattr(base, f.name)
    )
    controllers = frozenset(
        controller
        for controller, relevant in _CONTROLLER_RELEVANT_FIELDS.items()
        if changed & relevant
    )
    summary = "updated " + ", ".join(sorted(changed)) if changed else "no changes"
    return EnvironmentPatchVerdict(
        config=config,
        changed_fields=changed,
        controllers_to_restart=controllers,
        exhaust_repair_relevant=bool(changed & _EXHAUST_REPAIR_FIELDS),
        summary=summary,
        warnings=patch.warnings,
    )


def _build_patch(
    raw: Mapping[str, Any], *, ignore_keys: frozenset[str]
) -> EnvironmentPatch:
    """Shared builder core: normalise, parse, validate a raw payload."""
    data = {k: v for k, v in raw.items() if k not in ignore_keys}
    values: dict[str, Any] = {}
    bayesian_updates: dict[str, Any] = {}
    warnings: list[PatchWarning] = []

    for alias, canonical in _ALL_ALIASES.items():
        if alias not in data:
            continue
        val = data.pop(alias)
        if canonical in data:
            continue
        if val is None:
            data[canonical] = []
        elif isinstance(val, list):
            data[canonical] = val
        else:
            data[canonical] = [val]

    for key, val in data.items():
        ownership = ENVIRONMENT_FIELD_OWNERSHIP.get(key)
        if ownership is None:
            # Catch-all mirror of EnvironmentConfig.__pre_deserialize__: the
            # advanced Bayesian/trend settings have no model fields of their
            # own and have always lived inside bayesian_options.
            bayesian_updates[key] = val
            continue
        if ownership.field_class is FieldClass.RUNTIME_ACCUMULATED:
            warnings.append(PatchWarning(key, "runtime-accumulated field ignored"))
            continue
        if key in _SUB_CONFIG_TYPES:
            # Explicit null sub-config means "keep existing" — the historic
            # service contract (callers could never distinguish null from
            # absent). Reset-to-defaults is an explicit empty dict.
            if val is not None:
                values[key] = _parse_sub_config(key, val)
        elif key in _ITEM_TYPES:
            items, item_warnings = _parse_item_list(key, val)
            values[key] = items
            warnings.extend(item_warnings)
        elif key == "vpd_optimal_overrides":
            values[key] = validate_vpd_optimal_overrides(val)
        else:
            _parse_plain_field(key, val, values, warnings)

    _validate_moisture_band(values)

    return EnvironmentPatch(
        values=values,
        bayesian_updates=bayesian_updates,
        warnings=tuple(warnings),
    )


def _validate_moisture_band(values: dict[str, Any]) -> None:
    """Keep the Acceptable Moisture Band an atomic, valid pair.

    Patch semantics would otherwise let a payload carrying only one bound
    combine with the stored other bound into a partial or inverted band, so a
    payload touching either bound must carry both. Both ``None`` is the
    deliberate clear back to the inherited default.
    """
    present = {"soil_moisture_min", "soil_moisture_max"} & values.keys()
    if not present:
        return
    if len(present) == 1:
        raise EnvironmentPatchError(
            "The Acceptable Moisture Band is set as a pair: send both "
            "'soil_moisture_min' and 'soil_moisture_max', or neither."
        )

    minimum = values["soil_moisture_min"]
    maximum = values["soil_moisture_max"]
    if minimum is None and maximum is None:
        return
    if minimum is None or maximum is None:
        raise EnvironmentPatchError(
            "The Acceptable Moisture Band needs both bounds or neither; "
            "clear it by sending both as null."
        )
    if not is_valid_band(minimum, maximum):
        raise EnvironmentPatchError(
            f"Invalid Acceptable Moisture Band ({minimum}–{maximum}%): requires "
            f"{MOISTURE_BAND_FLOOR:g} ≤ minimum < maximum ≤ {MOISTURE_BAND_CEILING:g}."
        )
    values["soil_moisture_min"] = float(minimum)
    values["soil_moisture_max"] = float(maximum)


def _parse_plain_field(
    key: str,
    val: Any,
    values: dict[str, Any],
    warnings: list[PatchWarning],
) -> None:
    """Place one scalar/list/dict field into ``values``, normalising None."""
    if val is None:
        if key in _LIST_FIELDS:
            values[key] = []
        elif key in _DICT_FIELDS:
            values[key] = {}
        elif key in _NULLABLE_FIELDS:
            values[key] = None
        else:
            # Explicit null for a non-nullable field (the historic
            # electricity_cost_per_kwh type violation): keep the existing
            # value rather than failing the whole save.
            warnings.append(
                PatchWarning(key, "null for non-nullable field ignored; kept existing")
            )
        return
    if key in _DICT_FIELDS and not isinstance(val, Mapping):
        raise EnvironmentPatchError(f"Field '{key}' must be a dictionary")
    if key in _LIST_FIELDS and not isinstance(val, list):
        # Historic singular-value tolerance: a bare string for a list field
        # is wrapped, anything else is a structural error.
        if isinstance(val, str):
            values[key] = [val]
            return
        raise EnvironmentPatchError(f"Field '{key}' must be a list")
    values[key] = val


def _parse_sub_config(key: str, val: Any) -> Any:
    """Parse a sub-config payload into its dataclass (whole replace)."""
    sub_type = _SUB_CONFIG_TYPES[key]
    if isinstance(val, sub_type):
        return val
    if not isinstance(val, Mapping):
        raise EnvironmentPatchError(f"Field '{key}' must be a dictionary")
    if key == "circulation_fan_config":
        return _parse_circulation_fan_config(val)
    if key == "exhaust_fan_config":
        return _parse_exhaust_fan_config(val)
    valid = {f.name for f in fields(sub_type)}
    filtered = {k: v for k, v in val.items() if k in valid}
    try:
        return sub_type.from_dict(filtered)
    except (TypeError, ValueError, LookupError) as err:
        raise EnvironmentPatchError(f"Invalid {key} payload: {err}") from err


def _parse_circulation_fan_config(raw: Mapping[str, Any]) -> CirculationFanConfig:
    """Build a CirculationFanConfig from a raw payload (whole replace)."""
    try:
        return CirculationFanConfig(
            enabled=bool(raw.get("enabled", False)),
            regulation_mode=FanRegulationMode(
                raw.get("regulation_mode", FanRegulationMode.VPD)
            ),
            min_speed=int(raw.get("min_speed", 0)),
            max_speed=int(raw.get("max_speed", 100)),
            vpd_target=float(raw.get("vpd_target", 1.0)),
            vpd_tolerance=float(raw.get("vpd_tolerance", 0.2)),
            humidity_target=float(raw.get("humidity_target", 60.0)),
            humidity_tolerance=float(raw.get("humidity_tolerance", 5.0)),
            temperature_target=float(raw.get("temperature_target", 25.0)),
            temperature_tolerance=float(raw.get("temperature_tolerance", 2.0)),
            critical_temp_low=raw.get("critical_temp_low"),
            critical_temp_high=raw.get("critical_temp_high"),
            critical_temp_hysteresis=float(raw.get("critical_temp_hysteresis", 1.0)),
            wind_enabled=bool(raw.get("wind_enabled", False)),
            wind_period_seconds=int(raw.get("wind_period_seconds", 60)),
            wind_amplitude_pct=int(raw.get("wind_amplitude_pct", 10)),
            stage_vpd_enabled=bool(raw.get("stage_vpd_enabled", False)),
            stage_vpd_overrides=validate_stage_vpd_overrides(
                raw.get("stage_vpd_overrides", {})
            ),
        )
    except (TypeError, ValueError) as err:
        if isinstance(err, EnvironmentPatchError):
            raise
        raise EnvironmentPatchError(
            f"Invalid circulation_fan_config payload: {err}"
        ) from err


def _parse_exhaust_fan_config(raw: Mapping[str, Any]) -> ExhaustFanConfig:
    """Build an ExhaustFanConfig from a raw payload (whole replace)."""
    try:
        return ExhaustFanConfig(
            enabled=bool(raw.get("enabled", False)),
            min_speed=int(raw.get("min_speed", 0)),
            max_speed=int(raw.get("max_speed", 100)),
            temperature_target=float(raw.get("temperature_target", 25.0)),
            temperature_tolerance=float(raw.get("temperature_tolerance", 2.0)),
            humidity_target=float(raw.get("humidity_target", 60.0)),
            humidity_tolerance=float(raw.get("humidity_tolerance", 5.0)),
            vpd_target=float(raw.get("vpd_target", 1.0)),
            vpd_tolerance=float(raw.get("vpd_tolerance", 0.2)),
            stage_vpd_enabled=bool(raw.get("stage_vpd_enabled", False)),
            stage_vpd_overrides=validate_stage_vpd_overrides(
                raw.get("stage_vpd_overrides", {})
            ),
            critical_temp_low=raw.get("critical_temp_low"),
            critical_temp_high=raw.get("critical_temp_high"),
            critical_temp_hysteresis=float(raw.get("critical_temp_hysteresis", 1.0)),
        )
    except (TypeError, ValueError) as err:
        if isinstance(err, EnvironmentPatchError):
            raise
        raise EnvironmentPatchError(
            f"Invalid exhaust_fan_config payload: {err}"
        ) from err


def _parse_item_list(key: str, val: Any) -> tuple[list[Any], list[PatchWarning]]:
    """Parse a list-of-dataclass field, dropping invalid items into warnings."""
    if val is None:
        return [], []
    if not isinstance(val, list):
        raise EnvironmentPatchError(f"Field '{key}' must be a list")
    item_type = _ITEM_TYPES[key]
    valid = {f.name for f in fields(item_type)}
    items: list[Any] = []
    warnings: list[PatchWarning] = []
    for entry in val:
        if isinstance(entry, item_type):
            items.append(entry)
            continue
        if not isinstance(entry, Mapping):
            warnings.append(
                PatchWarning(key, f"invalid item dropped: {entry!r} (not a mapping)")
            )
            continue
        filtered = {k: v for k, v in entry.items() if k in valid}
        try:
            items.append(item_type.from_dict(filtered))
        except (TypeError, ValueError, LookupError) as err:
            warnings.append(
                PatchWarning(key, f"invalid item dropped: {entry!r} ({err})")
            )
    return items, warnings
