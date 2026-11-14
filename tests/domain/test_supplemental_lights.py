"""Tests for pure Supplemental Lights domain rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from custom_components.growspace_manager.domain.supplemental_lights import (
    build_supplemental_light_status,
    diff_released_outputs,
    evaluate_supplemental_schedule,
    find_duplicate_lighting_assignments,
    merge_valid_windows,
    validate_supplemental_lights_for_save,
    validate_window,
)
from custom_components.growspace_manager.models.growspace import (
    ACInfinityGrowLight,
    EnvironmentConfig,
    SupplementalAnchor,
    SupplementalLight,
    SupplementalLightWindow,
)

_TZ = timezone(timedelta(hours=2))


def _win(
    start_anchor: SupplementalAnchor,
    start_offset: int,
    end_anchor: SupplementalAnchor,
    end_offset: int,
    win_id: str = "w1",
) -> SupplementalLightWindow:
    return SupplementalLightWindow(
        id=win_id,
        start_anchor=start_anchor,
        start_offset_minutes=start_offset,
        end_anchor=end_anchor,
        end_offset_minutes=end_offset,
    )


def test_validate_window_accepts_valid_anchors() -> None:
    """Windows inside [0, cycle_duration] with positive length are valid."""
    assert (
        validate_window(
            _win(SupplementalAnchor.LIGHTS_ON, 0, SupplementalAnchor.LIGHTS_ON, 60),
            12 * 60,
        )
        is None
    )
    assert (
        validate_window(
            _win(SupplementalAnchor.LIGHTS_OFF, -60, SupplementalAnchor.LIGHTS_OFF, 0),
            12 * 60,
        )
        is None
    )
    assert (
        validate_window(
            _win(SupplementalAnchor.LIGHTS_ON, 30, SupplementalAnchor.LIGHTS_OFF, -30),
            18 * 60,
        )
        is None
    )


@pytest.mark.parametrize(
    ("window", "cycle_minutes", "expected_fragment"),
    [
        (
            _win(SupplementalAnchor.LIGHTS_ON, -15, SupplementalAnchor.LIGHTS_ON, 30),
            12 * 60,
            "before planned main lights-on",
        ),
        (
            _win(SupplementalAnchor.LIGHTS_OFF, 0, SupplementalAnchor.LIGHTS_OFF, 30),
            12 * 60,
            "at or after planned main lights-off",
        ),
        (
            _win(SupplementalAnchor.LIGHTS_ON, 600, SupplementalAnchor.LIGHTS_ON, 780),
            12 * 60,
            "after planned main lights-off",
        ),
        (
            _win(SupplementalAnchor.LIGHTS_ON, 120, SupplementalAnchor.LIGHTS_ON, 120),
            12 * 60,
            "after window start",
        ),
        (
            _win(SupplementalAnchor.LIGHTS_ON, 120, SupplementalAnchor.LIGHTS_ON, 60),
            12 * 60,
            "after window start",
        ),
    ],
)
def test_validate_window_rejects_out_of_cycle_or_empty(
    window: SupplementalLightWindow,
    cycle_minutes: int,
    expected_fragment: str,
) -> None:
    """Invalid windows return a descriptive reason."""
    err = validate_window(window, cycle_minutes)
    assert err is not None
    assert expected_fragment in err


def test_merge_valid_windows_joins_overlapping_and_skips_invalid() -> None:
    """Overlapping/adjacent valid windows join; newly invalid ones are skipped with reason."""
    windows = [
        _win(SupplementalAnchor.LIGHTS_ON, 60, SupplementalAnchor.LIGHTS_ON, 180, "a"),
        _win(SupplementalAnchor.LIGHTS_ON, 150, SupplementalAnchor.LIGHTS_ON, 240, "b"),
        _win(SupplementalAnchor.LIGHTS_ON, 240, SupplementalAnchor.LIGHTS_ON, 300, "c"),
        # Valid in 18h veg (1080m), invalid in 12h flower (720m):
        _win(
            SupplementalAnchor.LIGHTS_ON, 780, SupplementalAnchor.LIGHTS_ON, 840, "late"
        ),
        _win(
            SupplementalAnchor.LIGHTS_ON,
            660,
            SupplementalAnchor.LIGHTS_ON,
            780,
            "overlap_off",
        ),
    ]
    merged, skipped = merge_valid_windows(windows, 12 * 60)
    assert merged == [(60, 300)]
    assert [s.window_id for s in skipped] == ["late", "overlap_off"]
    assert "lights-off" in skipped[0].reason
    assert "lights-off" in skipped[1].reason


def test_evaluate_schedule_across_midnight_and_between_windows() -> None:
    """Evaluates active window, next window, and boundary across midnight."""
    # Main cycle: 20:00 -> 08:00 (12h)
    windows = [
        _win(
            SupplementalAnchor.LIGHTS_ON, 30, SupplementalAnchor.LIGHTS_ON, 120, "early"
        ),
        _win(
            SupplementalAnchor.LIGHTS_OFF,
            -90,
            SupplementalAnchor.LIGHTS_OFF,
            -30,
            "late",
        ),
    ]
    # 21:00 (60m into cycle): inside first window [20:30, 22:00)
    now_active = datetime(2026, 7, 3, 21, 0, 0, tzinfo=_TZ)
    ev = evaluate_supplemental_schedule("20:00:00", 12, now_active, windows)
    assert ev.is_active_now is True
    assert ev.current_window is not None
    assert ev.current_window.start_at == datetime(2026, 7, 3, 20, 30, 0, tzinfo=_TZ)
    assert ev.current_window.end_at == datetime(2026, 7, 3, 22, 0, 0, tzinfo=_TZ)
    assert ev.next_window is not None
    assert ev.next_window.start_at == datetime(2026, 7, 4, 6, 30, 0, tzinfo=_TZ)
    assert ev.next_boundary_at == datetime(2026, 7, 3, 22, 0, 0, tzinfo=_TZ)

    # 02:00 next day: between windows -> off, next_window is 06:30
    now_gap = datetime(2026, 7, 4, 2, 0, 0, tzinfo=_TZ)
    ev_gap = evaluate_supplemental_schedule("20:00:00", 12, now_gap, windows)
    assert ev_gap.is_active_now is False
    assert ev_gap.current_window is None
    assert ev_gap.next_window is not None
    assert ev_gap.next_window.start_at == datetime(2026, 7, 4, 6, 30, 0, tzinfo=_TZ)
    assert ev_gap.next_boundary_at == datetime(2026, 7, 4, 6, 30, 0, tzinfo=_TZ)

    # 12:00 in dark period: off, next_window is tonight 20:30
    now_dark = datetime(2026, 7, 4, 12, 0, 0, tzinfo=_TZ)
    ev_dark = evaluate_supplemental_schedule("20:00:00", 12, now_dark, windows)
    assert ev_dark.is_active_now is False
    assert ev_dark.next_window is not None
    assert ev_dark.next_window.start_at == datetime(2026, 7, 4, 20, 30, 0, tzinfo=_TZ)


def test_find_duplicate_lighting_assignments_across_roles_and_growspaces() -> None:
    """Rejects duplicates across growspaces and main/supplemental roles."""
    gs1 = SimpleNamespace(
        id="gs1",
        name="Flower Tent",
        environment_config=EnvironmentConfig(
            growlight_entities=["light.main_flower"],
            growlight_ac_infinity_devices=[
                ACInfinityGrowLight(
                    mode_entity="select.aci_mode",
                    on_time_entity="time.on",
                    off_time_entity="time.off",
                    power_entity="number.power",
                )
            ],
            supplemental_lights=[
                SupplementalLight(id="s1", entity_id="switch.uv_flower")
            ],
        ),
    )
    gs2 = SimpleNamespace(
        id="gs2",
        name="Veg Tent",
        environment_config=EnvironmentConfig(
            supplemental_lights=[SupplementalLight(id="s2", entity_id="light.veg_supp")]
        ),
    )
    growspaces = {"gs1": gs1, "gs2": gs2}

    # Same growspace main light
    errs = find_duplicate_lighting_assignments(
        growspaces, "gs1", ["light.main_flower"], candidate_role="supplemental light"
    )
    assert len(errs) == 1
    assert "Flower Tent" in errs[0]
    assert "main grow light" in errs[0]

    # Other growspace supplemental light
    errs2 = find_duplicate_lighting_assignments(
        growspaces, "gs1", ["light.veg_supp"], candidate_role="supplemental light"
    )
    assert len(errs2) == 1
    assert "Veg Tent" in errs2[0]
    assert "supplemental light" in errs2[0]

    # Main grow light conflicting with supplemental light
    errs3 = find_duplicate_lighting_assignments(
        growspaces, "gs1", ["switch.uv_flower"], candidate_role="main grow light"
    )
    assert len(errs3) == 1
    assert "supplemental light" in errs3[0]

    # Re-saving existing supplemental light on same growspace is allowed
    assert (
        find_duplicate_lighting_assignments(
            growspaces, "gs1", ["switch.uv_flower"], candidate_role="supplemental light"
        )
        == []
    )


def test_diff_released_outputs_detects_disable_delete_and_reassign() -> None:
    """Detects outputs leaving automation control via disable, delete, or reassignment."""
    prev = [
        SupplementalLight(id="1", entity_id="light.a", enabled=True),
        SupplementalLight(id="2", entity_id="light.b", enabled=True),
        SupplementalLight(id="3", entity_id="light.c", enabled=True),
        SupplementalLight(id="4", entity_id="light.d", enabled=False),
    ]
    nxt = [
        SupplementalLight(id="1", entity_id="light.a", enabled=False),  # disabled
        # id="2" deleted
        SupplementalLight(id="3", entity_id="light.c_new", enabled=True),  # reassigned
        # id="4" deleted while already disabled -> not under automation control
    ]
    released = diff_released_outputs(prev, nxt)
    assert [(r.entity_id, r.reason) for r in released] == [
        ("light.a", "disabled"),
        ("light.b", "deleted"),
        ("light.c", "reassigned"),
    ]


def test_validate_supplemental_lights_for_save_and_status() -> None:
    """Save validation rejects non-light/switch entities and invalid windows."""
    bad = [
        SupplementalLight(
            id="1",
            entity_id="sensor.not_a_light",
            windows=[
                _win(SupplementalAnchor.LIGHTS_ON, 0, SupplementalAnchor.LIGHTS_ON, 30)
            ],
        ),
        SupplementalLight(
            id="2",
            entity_id="switch.uv",
            windows=[
                _win(
                    SupplementalAnchor.LIGHTS_ON, -10, SupplementalAnchor.LIGHTS_ON, 30
                )
            ],
        ),
    ]
    errors = validate_supplemental_lights_for_save(bad, 12 * 60)
    assert len(errors) == 2

    now = datetime(2026, 7, 3, 10, 0, 0, tzinfo=UTC)
    light = SupplementalLight(
        id="ok",
        entity_id="switch.uv",
        enabled=True,
        windows=[
            _win(SupplementalAnchor.LIGHTS_ON, 0, SupplementalAnchor.LIGHTS_ON, 60)
        ],
    )
    ev = evaluate_supplemental_schedule("06:00:00", 12, now, light.windows)
    status = build_supplemental_light_status(
        light,
        ev,
        reported_state="off",
        available=True,
        commands_allowed=False,
        override_expires_at=datetime(2026, 7, 3, 11, 30, 0, tzinfo=UTC),
        lights_on_time="06:00:00",
        photoperiod_hours=12,
    )
    assert status["held_off_reason"] == "Lights manual override active until 11:30"
    assert status["reported_state"] == "off"
