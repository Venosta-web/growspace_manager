"""Pure domain rules for Supplemental Lights v1.

Supplemental Lights are auxiliary Home Assistant ``light.*`` or ``switch.*``
outputs scheduled on Supplemental Light Windows anchored to the growspace's
managed main-light cycle (``lights_on_time`` + derived photoperiod).

This module is pure (no Home Assistant, no I/O, no logging) so window math,
merging, invalidation on photoperiod shrink, duplicate-assignment checks, and
release diffing can be unit-tested in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from custom_components.growspace_manager.models.growspace import (
    SupplementalAnchor,
    SupplementalLight,
    SupplementalLightWindow,
)

if TYPE_CHECKING:
    from custom_components.growspace_manager.models.growspace import Growspace

_SUPPORTED_DOMAINS = ("light", "switch")


@dataclass(frozen=True, slots=True)
class SkippedWindow:
    """A saved window skipped at runtime because a main-schedule change made it invalid."""

    window_id: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        """Return the wire representation."""
        return {"window_id": self.window_id, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ResolvedWindow:
    """A concrete local-time interval for a merged supplemental light window."""

    start_at: datetime
    end_at: datetime

    def as_dict(self) -> dict[str, str]:
        """Return the wire representation."""
        return {
            "start": self.start_at.isoformat(),
            "end": self.end_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SupplementalScheduleEvaluation:
    """Result of evaluating one supplemental output's windows at ``now``."""

    is_active_now: bool
    current_window: ResolvedWindow | None
    next_window: ResolvedWindow | None
    next_boundary_at: datetime | None
    merged_cycle_windows: tuple[tuple[int, int], ...]
    skipped_windows: tuple[SkippedWindow, ...]


@dataclass(frozen=True, slots=True)
class ReleasedOutput:
    """A previously controlled output being disabled, deleted, or reassigned."""

    entity_id: str
    reason: Literal["disabled", "deleted", "reassigned"]


def resolve_window_cycle_minutes(
    window: SupplementalLightWindow, cycle_duration_minutes: int
) -> tuple[int, int]:
    """Resolve a window's endpoints to minute offsets from planned main lights-on."""
    start_base = (
        0
        if window.start_anchor is SupplementalAnchor.LIGHTS_ON
        else cycle_duration_minutes
    )
    end_base = (
        0
        if window.end_anchor is SupplementalAnchor.LIGHTS_ON
        else cycle_duration_minutes
    )
    return (
        start_base + window.start_offset_minutes,
        end_base + window.end_offset_minutes,
    )


def validate_window(
    window: SupplementalLightWindow, cycle_duration_minutes: int
) -> str | None:
    """Return an error explanation if ``window`` is invalid inside the main cycle."""
    if cycle_duration_minutes <= 0 or cycle_duration_minutes > 24 * 60:
        return "Main light cycle duration must be between 1 minute and 24 hours."
    start_min, end_min = resolve_window_cycle_minutes(window, cycle_duration_minutes)
    if start_min < 0:
        return "Window starts before planned main lights-on."
    if start_min >= cycle_duration_minutes:
        return "Window starts at or after planned main lights-off."
    if end_min > cycle_duration_minutes:
        return "Window ends after planned main lights-off."
    if end_min <= start_min:
        return "Window end must be after window start."
    return None


def validate_supplemental_lights_for_save(
    lights: Sequence[SupplementalLight],
    cycle_duration_minutes: int,
) -> list[str]:
    """Validate all supplemental outputs and their windows before saving."""
    errors: list[str] = []
    for index, light in enumerate(lights):
        entity_id = light.entity_id.strip()
        if not entity_id or "." not in entity_id:
            errors.append(f"Supplemental output #{index + 1} must select an entity.")
            continue
        domain = entity_id.split(".", 1)[0]
        if domain not in _SUPPORTED_DOMAINS:
            errors.append(
                f"Supplemental output '{entity_id}' must be a light or switch entity."
            )
        for win_idx, window in enumerate(light.windows):
            if err := validate_window(window, cycle_duration_minutes):
                errors.append(f"{entity_id} window #{win_idx + 1}: {err}")
    return errors


def merge_valid_windows(
    windows: Sequence[SupplementalLightWindow],
    cycle_duration_minutes: int,
) -> tuple[list[tuple[int, int]], list[SkippedWindow]]:
    """Return merged valid ``[start, end)`` cycle intervals and skipped invalid windows."""
    valid: list[tuple[int, int]] = []
    skipped: list[SkippedWindow] = []
    for idx, window in enumerate(windows):
        if err := validate_window(window, cycle_duration_minutes):
            skipped.append(SkippedWindow(window.id or f"window_{idx + 1}", err))
            continue
        valid.append(resolve_window_cycle_minutes(window, cycle_duration_minutes))

    if not valid:
        return [], skipped

    valid.sort(key=lambda pair: (pair[0], pair[1]))
    merged: list[tuple[int, int]] = [valid[0]]
    for start_min, end_min in valid[1:]:
        prev_start, prev_end = merged[-1]
        if start_min <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end_min))
        else:
            merged.append((start_min, end_min))
    return merged, skipped


def _parse_lights_on_tod(lights_on_time: str) -> tuple[int, int, int]:
    """Parse ``HH:MM[:SS]`` into ``(hour, minute, second)``."""
    parts = [int(p) for p in lights_on_time.split(":")]
    hour = parts[0] if len(parts) > 0 else 6
    minute = parts[1] if len(parts) > 1 else 0
    second = parts[2] if len(parts) > 2 else 0
    return hour, minute, second


def _current_cycle_start(now: datetime, lights_on_time: str) -> datetime:
    """Return the local start datetime of the main-light cycle containing or preceding ``now``."""
    hour, minute, second = _parse_lights_on_tod(lights_on_time)
    today_start = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if now >= today_start:
        return today_start
    return today_start - timedelta(days=1)


def evaluate_supplemental_schedule(
    lights_on_time: str,
    photoperiod_hours: float,
    now: datetime,
    windows: Sequence[SupplementalLightWindow],
) -> SupplementalScheduleEvaluation:
    """Evaluate merged valid windows at ``now`` and resolve current/next local windows."""
    cycle_duration_minutes = round(photoperiod_hours * 60)
    merged, skipped = merge_valid_windows(windows, cycle_duration_minutes)

    if not merged or cycle_duration_minutes <= 0:
        return SupplementalScheduleEvaluation(
            is_active_now=False,
            current_window=None,
            next_window=None,
            next_boundary_at=None,
            merged_cycle_windows=tuple(merged),
            skipped_windows=tuple(skipped),
        )

    cycle_start = _current_cycle_start(now, lights_on_time)
    next_cycle_start = cycle_start + timedelta(days=1)
    elapsed_minutes = (now - cycle_start).total_seconds() / 60.0

    current_window: ResolvedWindow | None = None
    next_window: ResolvedWindow | None = None

    if 0.0 <= elapsed_minutes < cycle_duration_minutes:
        for idx, (w_start, w_end) in enumerate(merged):
            if w_start <= elapsed_minutes < w_end:
                current_window = ResolvedWindow(
                    start_at=cycle_start + timedelta(minutes=w_start),
                    end_at=cycle_start + timedelta(minutes=w_end),
                )
                if idx + 1 < len(merged):
                    n_start, n_end = merged[idx + 1]
                    next_window = ResolvedWindow(
                        start_at=cycle_start + timedelta(minutes=n_start),
                        end_at=cycle_start + timedelta(minutes=n_end),
                    )
                else:
                    n_start, n_end = merged[0]
                    next_window = ResolvedWindow(
                        start_at=next_cycle_start + timedelta(minutes=n_start),
                        end_at=next_cycle_start + timedelta(minutes=n_end),
                    )
                break
            if w_start > elapsed_minutes and next_window is None:
                next_window = ResolvedWindow(
                    start_at=cycle_start + timedelta(minutes=w_start),
                    end_at=cycle_start + timedelta(minutes=w_end),
                )
                break

    if current_window is None and next_window is None:
        # Either past the last window in the current cycle, or in the dark period.
        n_start, n_end = merged[0]
        anchor_cycle = cycle_start if elapsed_minutes < 0 else next_cycle_start
        next_window = ResolvedWindow(
            start_at=anchor_cycle + timedelta(minutes=n_start),
            end_at=anchor_cycle + timedelta(minutes=n_end),
        )

    is_active_now = current_window is not None
    next_boundary_at = (
        current_window.end_at
        if current_window is not None
        else (next_window.start_at if next_window is not None else None)
    )

    return SupplementalScheduleEvaluation(
        is_active_now=is_active_now,
        current_window=current_window,
        next_window=next_window,
        next_boundary_at=next_boundary_at,
        merged_cycle_windows=tuple(merged),
        skipped_windows=tuple(skipped),
    )


def find_duplicate_lighting_assignments(
    growspaces: Mapping[str, Growspace],
    target_growspace_id: str,
    candidate_entities: Iterable[str],
    *,
    candidate_role: Literal["main grow light", "supplemental light"],
) -> list[str]:
    """Return error messages for any entity already assigned to a lighting role."""
    errors: list[str] = []
    seen_in_candidates: set[str] = set()
    candidates = [e.strip() for e in candidate_entities if e and e.strip()]

    for entity_id in candidates:
        if entity_id in seen_in_candidates:
            errors.append(
                f"'{entity_id}' is listed more than once as a {candidate_role} in this growspace."
            )
            continue
        seen_in_candidates.add(entity_id)

        for gs in growspaces.values():
            env = gs.environment_config
            same_gs = gs.id == target_growspace_id
            checks: list[tuple[str, set[str]]] = []
            if not same_gs or candidate_role == "supplemental light":
                checks.append(
                    (
                        "main grow light",
                        set(env.growlight_entities)
                        | {d.mode_entity for d in env.growlight_ac_infinity_devices},
                    )
                )
            if not same_gs or candidate_role == "main grow light":
                checks.append(
                    (
                        "supplemental light",
                        {s.entity_id for s in env.supplemental_lights},
                    )
                )
            for role_label, assigned in checks:
                if entity_id in assigned:
                    errors.append(
                        f"'{entity_id}' is already assigned as a {role_label} in growspace '{gs.name}' ({gs.id})."
                    )

    return errors


def diff_released_outputs(
    previous: Sequence[SupplementalLight],
    next_lights: Sequence[SupplementalLight],
) -> list[ReleasedOutput]:
    """Identify previously enabled outputs that are disabled, deleted, or reassigned."""
    next_by_id: dict[str, SupplementalLight] = {
        item.id: item for item in next_lights if item.id
    }
    next_by_entity: dict[str, SupplementalLight] = {
        item.entity_id: item for item in next_lights if item.entity_id
    }

    released: list[ReleasedOutput] = []
    for prev in previous:
        if not prev.enabled or not prev.entity_id:
            continue
        matched = (
            next_by_id.get(prev.id)
            if prev.id and prev.id in next_by_id
            else next_by_entity.get(prev.entity_id)
        )
        if matched is None:
            released.append(ReleasedOutput(prev.entity_id, "deleted"))
        elif matched.entity_id != prev.entity_id:
            released.append(ReleasedOutput(prev.entity_id, "reassigned"))
        elif not matched.enabled:
            released.append(ReleasedOutput(prev.entity_id, "disabled"))

    return released


def build_supplemental_light_status(
    light: SupplementalLight,
    evaluation: SupplementalScheduleEvaluation,
    *,
    reported_state: str,
    available: bool,
    commands_allowed: bool,
    override_expires_at: datetime | None,
    lights_on_time: str,
    photoperiod_hours: float,
) -> dict[str, Any]:
    """Build the UI-facing status dictionary for one supplemental light output."""
    held_off_reason: str | None = None
    if not light.enabled:
        held_off_reason = "Output disabled"
    elif not commands_allowed:
        if override_expires_at is not None:
            held_off_reason = f"Lights manual override active until {override_expires_at.strftime('%H:%M')}"
        else:
            held_off_reason = "Lights automation inhibited"
    elif not available:
        held_off_reason = f"Output {reported_state}"
    elif not evaluation.merged_cycle_windows and evaluation.skipped_windows:
        held_off_reason = "All windows invalid under current main-light cycle"
    elif not evaluation.is_active_now:
        held_off_reason = "Outside scheduled windows"

    return {
        "id": light.id,
        "entity_id": light.entity_id,
        "enabled": light.enabled,
        "reported_state": reported_state,
        "available": available,
        "is_active_now": evaluation.is_active_now,
        "held_off_reason": held_off_reason,
        "override_expires_at": (
            override_expires_at.isoformat() if override_expires_at else None
        ),
        "current_window": (
            evaluation.current_window.as_dict()
            if evaluation.current_window is not None
            else None
        ),
        "next_window": (
            evaluation.next_window.as_dict()
            if evaluation.next_window is not None
            else None
        ),
        "skipped_windows": [w.as_dict() for w in evaluation.skipped_windows],
        "lights_on_time": lights_on_time,
        "photoperiod_hours": photoperiod_hours,
    }
