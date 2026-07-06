"""Irrigation Schedule — pure time-schedule rules (ADR-0029).

The one owner of what a schedule time *is* and how the irrigation/drain
schedule lists change. Follows the EC State / Pump Cycle Gate precedent:
plain data in, verdicts out, no ``hass``, no I/O. The coordinator keeps the
effects — listener registration, save/reload, logging.

Two parsing strictnesses on purpose:

- :func:`normalize_schedule_time` — strict, for **writes** (add/remove).
  Raises ``ValueError`` so a bad service call fails loudly. Add and remove
  share it, so they can never again disagree about what a time means (the
  remove path previously compared the raw input against normalized stored
  times, so removing ``"08:00"`` silently missed the stored ``"08:00:00"``).
- :func:`parse_stored_time` — lenient, for **reads** of stored lists.
  Returns ``None`` on malformed entries; the caller decides whether that is
  worth a warning (listener registration) or a silent skip (projection).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

ScheduleItem = dict[str, Any]


def normalize_schedule_time(time_str: str) -> str:
    """Validate and normalize a schedule time to ``HH:MM:SS``.

    Accepts ``HH:MM`` or ``HH:MM:SS``. Raises ``ValueError`` on anything
    else — writers must fail loudly, not store garbage.
    """
    if not time_str:
        raise ValueError("Time cannot be empty")
    if len(time_str) == 5:
        time_str = f"{time_str}:00"
    try:
        datetime.strptime(time_str, "%H:%M:%S")
    except ValueError as err:
        raise ValueError(f"Invalid time '{time_str}': hours must be 00-23") from err
    return time_str


def parse_stored_time(time_str: Any) -> time | None:
    """Parse a stored schedule time, returning None on malformed entries."""
    if not isinstance(time_str, str):
        return None
    if len(time_str) == 5:
        time_str = f"{time_str}:00"
    try:
        return datetime.strptime(time_str, "%H:%M:%S").time()
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class ScheduleChange:
    """The result of a schedule write: the new list plus what happened."""

    items: list[ScheduleItem]
    updated: bool = False
    removed: int = 0


def upsert_item(
    items: list[ScheduleItem], time_str: str, duration: int | None
) -> ScheduleChange:
    """Add a time entry, or update its duration if the time already exists.

    ``time_str`` is normalized before matching, so ``"08:00"`` and
    ``"08:00:00"`` are the same entry.
    """
    normalized = normalize_schedule_time(time_str)
    new_list = [dict(item) for item in items]
    for item in new_list:
        if item.get("time") == normalized:
            item["duration"] = duration
            return ScheduleChange(items=new_list, updated=True)
    new_list.append({"time": normalized, "duration": duration})
    return ScheduleChange(items=new_list)


def remove_items(items: list[ScheduleItem], time_str: str) -> ScheduleChange:
    """Remove every entry matching the (normalized) time."""
    normalized = normalize_schedule_time(time_str)
    new_list = [item for item in items if item.get("time") != normalized]
    return ScheduleChange(items=new_list, removed=len(items) - len(new_list))


@dataclass(frozen=True, slots=True)
class SchedulableEvents:
    """Stored schedule entries split into registrable and malformed."""

    valid: list[tuple[time, ScheduleItem]] = field(default_factory=list)
    malformed: list[ScheduleItem] = field(default_factory=list)


def schedulable_events(items: list[ScheduleItem]) -> SchedulableEvents:
    """Resolve a stored list into unique, parsed, registrable events.

    Duplicate times keep the last entry (matching the previous dedup rule).
    Identity is the *parsed* time, so a legacy ``"08:00"`` and a normalized
    ``"08:00:00"`` cannot register twice. Entries whose time does not parse
    are returned separately so the caller can warn about them.
    """
    by_time: dict[time, tuple[time, ScheduleItem]] = {}
    malformed: list[ScheduleItem] = []
    for item in items:
        parsed = parse_stored_time(item.get("time"))
        if parsed is None:
            malformed.append(item)
        else:
            by_time[parsed] = (parsed, item)
    return SchedulableEvents(valid=list(by_time.values()), malformed=malformed)


def next_occurrence(items: list[ScheduleItem], now: datetime) -> datetime | None:
    """Project the soonest future occurrence of any entry, or None.

    A time earlier than ``now`` today rolls to tomorrow. Malformed entries
    are skipped.
    """
    soonest: datetime | None = None
    for parsed, _item in schedulable_events(items).valid:
        candidate = datetime.combine(now.date(), parsed, tzinfo=now.tzinfo)
        if candidate <= now:
            candidate = datetime.combine(
                now.date() + timedelta(days=1), parsed, tzinfo=now.tzinfo
            )
        if soonest is None or candidate < soonest:
            soonest = candidate
    return soonest
