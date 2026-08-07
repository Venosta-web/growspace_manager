"""Tests for Volume Mode shot sizing wiring in the VWC Irrigation Coordinator (ADR-0011).

Volume Mode expresses per-phase shot size as a percentage of total substrate
volume (liters_per_pot x live_plant_count) and converts that to pump seconds via
the configured pump flow rate. The conversion math, mode gating, and the
volume-change note now live in the Steering Phase Machine and are unit-tested in
``tests/domain/test_steering_phase.py``; these tests verify the *wiring*: the
coordinator feeds real plant lists into the machine's inputs and executes the
verdict's effects (pump cycle, logbook note, idle phase).
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PlantStage, ShotSizingMode
from custom_components.growspace_manager.domain.steering_phase import (
    ShotRequest,
    SteeringTickInputs,
    SteeringTickVerdict,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationStrategy,
    SubstrateProfile,
)
from custom_components.growspace_manager.models.plant import Plant
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)
from homeassistant.util import dt as dt_util


@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep


@pytest.fixture(autouse=True)
def mock_wait_for_switch_state():
    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator."
        "VWCIrrigationCoordinator._async_wait_for_switch_state",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.async_create_task = MagicMock(side_effect=asyncio.create_task)
    hass.async_create_background_task = MagicMock(
        side_effect=lambda target, name: asyncio.create_task(target)
    )
    return hass


async def _drain_tasks() -> None:
    """Await any background tasks spawned by the fire path."""
    await asyncio.sleep(0)
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    for task in pending:
        await task


def _make_plants(stages: list[str]) -> list[Plant]:
    """Build a plant list for a growspace from a list of stage values."""
    return [
        Plant(plant_id=f"p{i}", growspace_id="gs1", stage=stage)
        for i, stage in enumerate(stages)
    ]


def _tick_inputs(
    coord: VWCIrrigationCoordinator, growspace: Growspace
) -> SteeringTickInputs:
    """Assemble tick inputs through the coordinator's real wiring."""
    return coord._tick_inputs(40.0, growspace.irrigation_strategy, growspace)


def _base_duration(
    coord: VWCIrrigationCoordinator, growspace: Growspace, phase: str
) -> tuple[int | None, str | None]:
    """Evaluate the machine's Volume Mode base duration with coordinator-fed inputs."""
    return coord._machine._volume_mode_base_duration(
        _tick_inputs(coord, growspace), phase
    )


def _drive_watering(
    coord: VWCIrrigationCoordinator, growspace: Growspace, phase: str
) -> None:
    """Drive the machine's shot evaluation plus the shell's fire path."""
    fire, _note, _suppressed = coord._machine._evaluate_shot(
        _tick_inputs(coord, growspace), phase, reset_pending=False
    )
    if fire is not None:
        coord._fire_shot(growspace.irrigation_strategy, fire)


@pytest.fixture
def volume_growspace():
    """Growspace configured for Volume Mode: profile + pump flow rate present."""
    growspace = Growspace(
        id="gs1",
        name="Volume Tent",
        environment_config=EnvironmentConfig(soil_moisture_sensor="sensor.moisture"),
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity="switch.pump",
            pump_flow_rate_ml_per_sec=20.0,
        ),
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=True,
        lights_on_time="08:00:00",
        p0_duration_minutes=60,
        target_vwc_percent=50.0,
        maintenance_dryback_percent=2.0,
        p1_shot_duration_seconds=10,
        p1_shot_interval_minutes=15,
        p2_shot_duration_seconds=10,
        p2_shot_interval_minutes=15,
        p2_stop_before_lights_off_minutes=120,
        shot_sizing_mode=ShotSizingMode.VOLUME,
        substrate_profile=SubstrateProfile(liters_per_pot=6.0),
        p1_shot_volume_percent=4.0,
        p2_shot_volume_percent=4.0,
    )
    return growspace


@pytest.fixture
def make_coordinator(mock_hass):
    """Build a VWC coordinator wired to a growspace and plant list."""

    def _build(growspace: Growspace, plants: list[Plant]) -> VWCIrrigationCoordinator:
        main = MagicMock()
        main.growspaces = {"gs1": growspace}
        main.add_event = MagicMock()
        main.services.growspaces.get_growspace_plants.return_value = plants
        main.services.growspaces.get_substrate_tracker.return_value = None

        config_entry = MagicMock()
        config_entry.runtime_data = main
        config_entry.async_create_background_task.side_effect = (
            lambda hass, target, name: asyncio.create_task(target)
        )
        return VWCIrrigationCoordinator(mock_hass, config_entry, "gs1", main)

    return _build


# ---------------------------------------------------------------------------
# Conversion math: percent -> ml -> seconds, scaling with live plant count.
# The math itself is domain-tested; here real plant lists flow through the
# coordinator's _live_plant_count into the machine's inputs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("live_count", "percent", "liters", "flow_rate", "expected_seconds"),
    [
        # 4% of 6L * 12 plants = 2880 ml / 20 ml/s = 144 s
        (12, 4.0, 6.0, 20.0, 144),
        # Halving plants halves volume: 4% of 6L * 6 = 1440 ml / 20 = 72 s
        (6, 4.0, 6.0, 20.0, 72),
        # Single plant constant dose: 4% of 6L * 1 = 240 ml / 20 = 12 s
        (1, 4.0, 6.0, 20.0, 12),
        # Sub-1s rounds up to the 1 s floor (not suspended — plants present).
        (1, 0.1, 1.0, 20.0, 1),
    ],
)
def test_volume_conversion_scales_with_live_count(
    make_coordinator,
    volume_growspace,
    live_count,
    percent,
    liters,
    flow_rate,
    expected_seconds,
) -> None:
    """Percent->seconds conversion is correct and scales linearly with plants."""
    volume_growspace.irrigation_strategy.substrate_profile.liters_per_pot = liters
    volume_growspace.irrigation_strategy.p1_shot_volume_percent = percent
    volume_growspace.irrigation_config.pump_flow_rate_ml_per_sec = flow_rate
    plants = _make_plants([PlantStage.FLOWER_MID.value] * live_count)
    coord = make_coordinator(volume_growspace, plants)

    duration, _note = _base_duration(coord, volume_growspace, "P1")

    assert duration == expected_seconds


def test_volume_uses_per_phase_percent(make_coordinator, volume_growspace) -> None:
    """P1 and P2 use their own percent fields."""
    volume_growspace.irrigation_strategy.p1_shot_volume_percent = 4.0
    volume_growspace.irrigation_strategy.p2_shot_volume_percent = 2.0
    plants = _make_plants([PlantStage.FLOWER_MID.value] * 10)
    coord = make_coordinator(volume_growspace, plants)

    # P1: 4% of 6L * 10 = 2400 ml / 20 = 120 s
    assert _base_duration(coord, volume_growspace, "P1")[0] == 120
    # P2: 2% of 6L * 10 = 1200 ml / 20 = 60 s
    assert _base_duration(coord, volume_growspace, "P2")[0] == 60


# ---------------------------------------------------------------------------
# Live plant count: dry/cure stages excluded
# ---------------------------------------------------------------------------


def test_live_plant_count_excludes_dry_and_cure(
    make_coordinator, volume_growspace
) -> None:
    """Plants in dry/cure stages do not count toward the live dosing basis."""
    plants = _make_plants(
        [
            PlantStage.FLOWER_MID.value,
            PlantStage.VEG.value,
            PlantStage.DRY.value,
            PlantStage.CURE.value,
        ]
    )
    coord = make_coordinator(volume_growspace, plants)

    assert coord._live_plant_count() == 2


# ---------------------------------------------------------------------------
# Zero plants -> suspend (idle phase, no pump cycle, no 1s floor)
# ---------------------------------------------------------------------------


def test_zero_plants_suspends_shot(make_coordinator, volume_growspace) -> None:
    """Zero live plants returns None (suspend) rather than a floored 1 s shot."""
    coord = make_coordinator(volume_growspace, [])

    duration, _note = _base_duration(coord, volume_growspace, "P1")

    assert duration is None


async def test_zero_plants_reports_idle_phase_no_pump(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """A zero-plant growspace in Volume Mode reports idle and fires no pump."""
    coord = make_coordinator(volume_growspace, [])
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)  # inside P1 window

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        mock_hass.states.get.return_value = MagicMock(state="40.0")
        await coord._update_loop(now)

    assert coord._machine.current_phase == "Idle (no plants)"
    mock_hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# Live-count change recomputes volume AND emits a logbook entry. The note text
# is produced by the machine; the coordinator's _apply_verdict owns the
# log_to_logbook gate and the actual bus event.
# ---------------------------------------------------------------------------


def _note_verdict(note: str | None) -> SteeringTickVerdict:
    """A no-transition verdict carrying only a volume-change note."""
    return SteeringTickVerdict(
        phase="P1 - Ramp Up",
        canonical="p1",
        phase_changed=False,
        transition_message=None,
        reset_composer=False,
        fire=None,
        volume_change_note=note,
    )


def test_live_count_change_emits_logbook_entry(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """A live-count change that alters shot volume writes a logbook entry."""
    coord = make_coordinator(volume_growspace, [])
    coord._main_coordinator.services.growspaces.get_growspace_plants.side_effect = [
        _make_plants([PlantStage.FLOWER_MID.value] * 12),
        _make_plants([PlantStage.FLOWER_MID.value] * 6),
    ]
    strategy = volume_growspace.irrigation_strategy

    # First tick establishes the baseline (no note on first observation).
    first, first_note = _base_duration(coord, volume_growspace, "P1")
    assert first == 144
    assert first_note is None

    # Second tick: count 12 -> 6 halves the volume; the note fires via the shell.
    second, second_note = _base_duration(coord, volume_growspace, "P1")
    assert second == 72
    coord._apply_verdict(_note_verdict(second_note), strategy)

    mock_hass.bus.async_fire.assert_called_once()
    _event_type, payload = mock_hass.bus.async_fire.call_args[0]
    assert "2880" in payload["message"] and "1440" in payload["message"]
    assert "12" in payload["message"] and "6" in payload["message"]


def test_unchanged_count_no_logbook_entry(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """An unchanged live count never produces a note or a logbook entry."""
    plants = _make_plants([PlantStage.FLOWER_MID.value] * 8)
    coord = make_coordinator(volume_growspace, plants)
    strategy = volume_growspace.irrigation_strategy

    _, note_a = _base_duration(coord, volume_growspace, "P1")
    _, note_b = _base_duration(coord, volume_growspace, "P1")
    coord._apply_verdict(_note_verdict(note_a), strategy)
    coord._apply_verdict(_note_verdict(note_b), strategy)

    mock_hass.bus.async_fire.assert_not_called()


def test_logbook_suppressed_when_disabled(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """No logbook entry when log_to_logbook is disabled, even on volume change."""
    volume_growspace.irrigation_config.log_to_logbook = False
    coord = make_coordinator(volume_growspace, [])
    coord._main_coordinator.services.growspaces.get_growspace_plants.side_effect = [
        _make_plants([PlantStage.FLOWER_MID.value] * 12),
        _make_plants([PlantStage.FLOWER_MID.value] * 6),
    ]
    strategy = volume_growspace.irrigation_strategy

    _, note_a = _base_duration(coord, volume_growspace, "P1")
    _, note_b = _base_duration(coord, volume_growspace, "P1")
    assert note_b is not None  # the machine still reports the change
    coord._apply_verdict(_note_verdict(note_a), strategy)
    coord._apply_verdict(_note_verdict(note_b), strategy)

    mock_hass.bus.async_fire.assert_not_called()


# Mode gating (selected + profile + flow rate) is pure domain logic now,
# unit-tested in tests/domain/test_steering_phase.py (the former
# test_volume_mode_inactive_*/test_volume_mode_active_* cases).


# ---------------------------------------------------------------------------
# Pipeline: Volume base -> scale factor -> downstream cap (Seconds unchanged)
# ---------------------------------------------------------------------------


async def test_volume_mode_applies_scale_factor_after_base(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """The VWC feedback scale factor multiplies the Volume Mode base duration."""
    plants = _make_plants([PlantStage.FLOWER_MID.value] * 10)
    coord = make_coordinator(volume_growspace, plants)
    coord._composer.size_factor = 0.5
    captured: dict[str, int] = {}

    async def _fake_cycle(event_type, pump_entity, duration, event_data):
        captured["duration"] = duration

    with (
        patch.object(coord, "_run_pump_cycle", side_effect=_fake_cycle),
        patch.object(coord, "_record_substrate_shot"),
    ):
        # Base: 4% of 6L * 10 = 2400 ml / 20 = 120 s; * 0.5 scale = 60 s
        _drive_watering(coord, volume_growspace, "P1")
        await _drain_tasks()

    assert captured["duration"] == 60


async def test_seconds_mode_duration_unchanged(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """Seconds Mode passes the configured seconds straight through (byte-for-byte)."""
    volume_growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.SECONDS
    volume_growspace.irrigation_strategy.p1_shot_duration_seconds = 10
    plants = _make_plants([PlantStage.FLOWER_MID.value] * 10)
    coord = make_coordinator(volume_growspace, plants)
    captured: dict[str, int] = {}

    async def _fake_cycle(event_type, pump_entity, duration, event_data):
        captured["duration"] = duration

    with (
        patch.object(coord, "_run_pump_cycle", side_effect=_fake_cycle),
        patch.object(coord, "_record_substrate_shot"),
    ):
        _drive_watering(coord, volume_growspace, "P1")
        await _drain_tasks()

    # Scale factor defaults to 1.0; configured 10 s passes through unchanged.
    assert captured["duration"] == 10


async def test_zero_plants_volume_mode_fires_no_pump(
    make_coordinator, volume_growspace
) -> None:
    """The shot evaluation suspends (no pump cycle) when Volume Mode has zero plants."""
    coord = make_coordinator(volume_growspace, [])
    cycle = MagicMock()

    with (
        patch.object(coord, "_run_pump_cycle", side_effect=cycle),
        patch.object(coord, "_record_substrate_shot"),
    ):
        _drive_watering(coord, volume_growspace, "P1")
        await _drain_tasks()

    cycle.assert_not_called()


async def test_fire_shot_uses_request_base_seconds(
    make_coordinator, volume_growspace, mock_hass
) -> None:
    """_fire_shot composes from the verdict's base seconds, not any config field."""
    plants = _make_plants([PlantStage.FLOWER_MID.value] * 10)
    coord = make_coordinator(volume_growspace, plants)

    async def _fake_cycle(event_type, pump_entity, duration, event_data):
        return None

    with (
        patch.object(coord, "_run_pump_cycle", side_effect=_fake_cycle),
        patch.object(coord, "_record_substrate_shot"),
    ):
        coord._fire_shot(
            volume_growspace.irrigation_strategy,
            ShotRequest(phase="P1", base_seconds=77),
        )
        await _drain_tasks()

    comp = coord._composer.last_composition
    assert comp.base_seconds == 77
