"""Unit tests for the Irrigation Schedule (ADR-0029).

Pure time-schedule rules — plain values in, verdicts out, no hass.
"""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest

from custom_components.growspace_manager.domain.irrigation_schedule import (
    next_occurrence,
    normalize_schedule_time,
    parse_stored_time,
    remove_items,
    schedulable_events,
    upsert_item,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08:00", "08:00:00"),
        ("08:00:30", "08:00:30"),
        ("23:59", "23:59:00"),
        ("00:00:00", "00:00:00"),
    ],
)
def test_normalize_schedule_time_accepts_valid(raw: str, expected: str) -> None:
    """HH:MM and HH:MM:SS both normalize to HH:MM:SS."""
    assert normalize_schedule_time(raw) == expected


@pytest.mark.parametrize("raw", ["", "25:00", "8am", "08:60", "not-a-time"])
def test_normalize_schedule_time_rejects_invalid(raw: str) -> None:
    """Writers fail loudly on garbage times."""
    with pytest.raises(ValueError):
        normalize_schedule_time(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("08:00", time(8, 0)),
        ("08:00:30", time(8, 0, 30)),
        (None, None),
        (1234, None),
        ("nope", None),
    ],
)
def test_parse_stored_time_is_lenient(raw: object, expected: time | None) -> None:
    """Stored-data reads never raise; malformed values become None."""
    assert parse_stored_time(raw) == expected


def test_upsert_item_appends_normalized() -> None:
    """A new HH:MM entry is stored normalized to HH:MM:SS."""
    change = upsert_item([], "08:00", 120)
    assert change.items == [{"time": "08:00:00", "duration": 120}]
    assert not change.updated


def test_upsert_item_updates_duration_across_formats() -> None:
    """'08:00' updates the entry stored as '08:00:00' instead of duplicating."""
    items = [{"time": "08:00:00", "duration": 60}]
    change = upsert_item(items, "08:00", 90)
    assert change.updated
    assert change.items == [{"time": "08:00:00", "duration": 90}]
    # The input list is untouched
    assert items == [{"time": "08:00:00", "duration": 60}]


def test_remove_items_matches_across_formats() -> None:
    """Removing '08:00' removes the stored '08:00:00' — the old raw-string
    comparison silently removed nothing."""
    items = [
        {"time": "08:00:00", "duration": 60},
        {"time": "18:00:00", "duration": 60},
    ]
    change = remove_items(items, "08:00")
    assert change.removed == 1
    assert change.items == [{"time": "18:00:00", "duration": 60}]


def test_remove_items_no_match_removes_nothing() -> None:
    """A non-matching time yields removed=0 and the same entries."""
    items = [{"time": "08:00:00", "duration": 60}]
    change = remove_items(items, "09:00")
    assert change.removed == 0
    assert change.items == items


def test_schedulable_events_dedups_by_parsed_time() -> None:
    """'08:00' and '08:00:00' are one event (last wins); malformed split out."""
    items = [
        {"time": "08:00", "duration": 30},
        {"time": "08:00:00", "duration": 60},
        {"time": None},
        {"time": "junk"},
    ]
    events = schedulable_events(items)
    assert len(events.valid) == 1
    parsed, item = events.valid[0]
    assert parsed == time(8, 0)
    assert item["duration"] == 60
    assert events.malformed == [{"time": None}, {"time": "junk"}]


def test_next_occurrence_rolls_past_times_to_tomorrow() -> None:
    """A time earlier than now today projects to tomorrow."""
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    items = [{"time": "08:00:00"}, {"time": "18:00:00"}]
    assert next_occurrence(items, now) == datetime(2026, 7, 7, 18, 0, tzinfo=UTC)

    late = datetime(2026, 7, 7, 23, 0, tzinfo=UTC)
    assert next_occurrence(items, late) == datetime(2026, 7, 8, 8, 0, tzinfo=UTC)


def test_next_occurrence_empty_or_malformed_is_none() -> None:
    """No entries, or only malformed ones, project no next cycle."""
    now = datetime(2026, 7, 7, 12, 0, tzinfo=UTC)
    assert next_occurrence([], now) is None
    assert next_occurrence([{"time": "junk"}], now) is None
