"""Tests for NotificationManager option-driven cooldown/timing helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import (
    CRITICAL_COOLDOWN_MINUTES,
    RECOVERY_COOLDOWN_MINUTES,
    WARNING_COOLDOWN_MINUTES,
    NotificationTier,
)
from custom_components.growspace_manager.notification_manager import NotificationManager


def _make_manager(notification_settings: dict | None = None) -> NotificationManager:
    coordinator = MagicMock()
    coordinator.options = (
        {"notification_settings": notification_settings}
        if notification_settings is not None
        else {}
    )
    ai_rewriter = MagicMock()
    return NotificationManager(MagicMock(), coordinator, ai_rewriter)


# ---------------------------------------------------------------------------
# _get_notification_option
# ---------------------------------------------------------------------------


def test_get_notification_option_returns_value_from_options() -> None:
    """_get_notification_option returns the value stored in notification_settings."""
    manager = _make_manager({"critical_cooldown_minutes": 5})

    result = manager._get_notification_option(
        "critical_cooldown_minutes", CRITICAL_COOLDOWN_MINUTES
    )

    assert result == 5


@pytest.mark.parametrize(
    ("option_key", "stored_key"),
    [
        ("critical_cooldown_minutes", "criticalCooldownMinutes"),
        ("warning_cooldown_minutes", "warningCooldownMinutes"),
        ("recovery_cooldown_minutes", "recoveryCooldownMinutes"),
        ("escalation_delay_minutes", "escalationDelayMinutes"),
        ("min_stress_duration_seconds", "minStressDurationSeconds"),
        ("warning_persistence_minutes", "warningPersistenceMinutes"),
    ],
)
def test_get_notification_option_returns_camel_case_value(
    option_key: str, stored_key: str
) -> None:
    """_get_notification_option accepts the card's camelCase option keys."""
    manager = _make_manager({stored_key: 59})

    result = manager._get_notification_option(option_key, 30)

    assert result == 59


def test_get_notification_option_returns_fallback_when_key_absent() -> None:
    """_get_notification_option returns fallback when key is not in notification_settings."""
    manager = _make_manager({})

    result = manager._get_notification_option(
        "critical_cooldown_minutes", CRITICAL_COOLDOWN_MINUTES
    )

    assert result == CRITICAL_COOLDOWN_MINUTES


def test_get_notification_option_returns_fallback_when_settings_absent() -> None:
    """_get_notification_option returns fallback when notification_settings key is absent entirely."""
    manager = _make_manager(notification_settings=None)

    result = manager._get_notification_option(
        "critical_cooldown_minutes", CRITICAL_COOLDOWN_MINUTES
    )

    assert result == CRITICAL_COOLDOWN_MINUTES


# ---------------------------------------------------------------------------
# _get_tier_cooldown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "option_key", "const_fallback"),
    [
        (
            NotificationTier.CRITICAL,
            "critical_cooldown_minutes",
            CRITICAL_COOLDOWN_MINUTES,
        ),
        (
            NotificationTier.WARNING,
            "warning_cooldown_minutes",
            WARNING_COOLDOWN_MINUTES,
        ),
        ("recovery", "recovery_cooldown_minutes", RECOVERY_COOLDOWN_MINUTES),
    ],
)
def test_get_tier_cooldown_uses_options_value(
    tier: str, option_key: str, const_fallback: int
) -> None:
    """_get_tier_cooldown returns a timedelta from notification_settings when present."""
    custom_value = 7
    manager = _make_manager({option_key: custom_value})

    result = manager._get_tier_cooldown(tier)

    assert result == timedelta(minutes=custom_value)


@pytest.mark.parametrize(
    ("tier", "const_fallback"),
    [
        (NotificationTier.CRITICAL, CRITICAL_COOLDOWN_MINUTES),
        (NotificationTier.WARNING, WARNING_COOLDOWN_MINUTES),
        ("recovery", RECOVERY_COOLDOWN_MINUTES),
    ],
)
def test_get_tier_cooldown_falls_back_to_const_when_absent(
    tier: str, const_fallback: int
) -> None:
    """_get_tier_cooldown falls back to the const when option key is absent."""
    manager = _make_manager({})

    result = manager._get_tier_cooldown(tier)

    assert result == timedelta(minutes=const_fallback)


# ---------------------------------------------------------------------------
# _is_on_cooldown uses _get_tier_cooldown (option-aware)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "option_key", ["critical_cooldown_minutes", "criticalCooldownMinutes"]
)
def test_is_on_cooldown_respects_option_override(option_key: str) -> None:
    """Configured cooldown suppresses within its window and expires after it."""
    manager = _make_manager({option_key: 59})
    growspace_id = "gs1"
    tier = NotificationTier.CRITICAL
    last_sent = datetime(2026, 8, 12, tzinfo=UTC)
    manager._cooldowns[growspace_id] = {tier: last_sent}

    assert manager._is_on_cooldown(
        growspace_id, tier, last_sent + timedelta(minutes=58)
    )
    assert not manager._is_on_cooldown(
        growspace_id, tier, last_sent + timedelta(minutes=60)
    )


def test_is_on_cooldown_expired_with_option_override() -> None:
    """_is_on_cooldown returns False when the option-driven cooldown has passed."""

    manager = _make_manager({"critical_cooldown_minutes": 1})
    growspace_id = "gs1"
    tier = NotificationTier.CRITICAL

    # Record cooldown 90 seconds ago
    ninety_seconds_ago = datetime.now(tz=UTC) - timedelta(seconds=90)
    manager._cooldowns[growspace_id] = {tier: ninety_seconds_ago}

    now = datetime.now(tz=UTC)
    # 90s > 1 min — should NOT be on cooldown
    assert manager._is_on_cooldown(growspace_id, tier, now) is False


# ---------------------------------------------------------------------------
# Inline constant call sites: min_stress_duration, escalation_delay,
# warning_persistence
# ---------------------------------------------------------------------------


def test_get_min_stress_duration_reads_from_options() -> None:
    """_get_notification_option returns min_stress_duration_seconds from options."""
    from custom_components.growspace_manager.const import MIN_STRESS_DURATION_SECONDS

    manager = _make_manager({"min_stress_duration_seconds": 60})
    assert (
        manager._get_notification_option(
            "min_stress_duration_seconds", MIN_STRESS_DURATION_SECONDS
        )
        == 60
    )


def test_get_escalation_delay_reads_from_options() -> None:
    """_get_notification_option returns escalation_delay_minutes from options."""
    from custom_components.growspace_manager.const import ESCALATION_DELAY_MINUTES

    manager = _make_manager({"escalation_delay_minutes": 10})
    assert (
        manager._get_notification_option(
            "escalation_delay_minutes", ESCALATION_DELAY_MINUTES
        )
        == 10
    )


def test_get_warning_persistence_reads_from_options() -> None:
    """_get_notification_option returns warning_persistence_minutes from options."""
    from custom_components.growspace_manager.const import WARNING_PERSISTENCE_MINUTES

    manager = _make_manager({"warning_persistence_minutes": 5})
    assert (
        manager._get_notification_option(
            "warning_persistence_minutes", WARNING_PERSISTENCE_MINUTES
        )
        == 5
    )
