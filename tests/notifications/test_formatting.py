"""Tests for the pure notification message formatter."""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.const import MAX_NOTIFICATION_LENGTH
from custom_components.growspace_manager.notifications.formatting import (
    generate_notification_message,
)


def test_no_reasons_returns_base_message() -> None:
    """An empty reason list returns the base message unchanged."""
    assert generate_notification_message("Base", []) == "Base"


def test_reasons_appended_in_descending_probability_order() -> None:
    """Reasons are appended highest-probability first, comma separated."""
    reasons = [(0.1, "low"), (0.9, "high"), (0.5, "mid")]

    result = generate_notification_message("Base", reasons)

    assert result == "Base, high, mid, low"


def test_appending_stops_before_exceeding_max_length() -> None:
    """Reasons that would push the message past the limit are dropped."""
    base = "B"
    short_reason = "short"
    # A reason long enough that it alone cannot fit alongside the base message.
    long_reason = "x" * MAX_NOTIFICATION_LENGTH

    result = generate_notification_message(
        base, [(0.9, long_reason), (0.1, short_reason)]
    )

    # The long reason is skipped; iteration breaks at the first that doesn't fit
    # so the shorter, lower-probability reason is never appended either.
    assert result == base


@pytest.mark.parametrize(
    ("reason_len", "should_fit"),
    [
        (1, True),
        (MAX_NOTIFICATION_LENGTH, False),
    ],
)
def test_boundary_behavior(reason_len: int, should_fit: bool) -> None:
    """A reason fits only when base + reason + separator stays under the limit."""
    base = "Base"
    reason = "y" * reason_len

    result = generate_notification_message(base, [(0.9, reason)])

    assert (reason in result) is should_fit
