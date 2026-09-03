"""Tests for the Irrigation Change write seam."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import ShotSizingMode, SubstrateMediaType
from custom_components.growspace_manager.models import Growspace, SubstrateProfile
from custom_components.growspace_manager.services.irrigation_change import (
    IrrigationChange,
    IrrigationChangeError,
    IrrigationChangeOperation,
    async_apply_irrigation_change,
)


def _coordinator(growspace: Growspace) -> SimpleNamespace:
    """Return the effect shell needed by the public Irrigation Change seam."""
    coordinator = SimpleNamespace(
        growspaces={growspace.id: growspace},
        cache=MagicMock(),
        async_commit=AsyncMock(),
        async_request_refresh=AsyncMock(),
    )
    return coordinator


@pytest.mark.parametrize(
    "field",
    [
        "unknown_field",
        "active_steering_phase",
        "phase_changed_at",
        "detected_lights_on_time",
        "declared_steering_mode",
    ],
)
@pytest.mark.asyncio
async def test_change_rejects_fields_the_grower_does_not_own(field: str) -> None:
    """Unknown, derived, and runtime-owned fields fail instead of disappearing."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match=field):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.OPTIONS,
                values={field: "replacement"},
            ),
        )

    coordinator.async_commit.assert_not_awaited()
    coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_atomically_replaces_candidate_state_and_describes_it() -> None:
    """One mixed options change returns canonical immutable changed-field sets."""
    growspace = Growspace(id="tent", name="Tent")
    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy
    coordinator = _coordinator(growspace)

    result = await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.OPTIONS,
            values={
                "irrigation_duration": 45,
                "target_vwc_percent": 58.0,
            },
        ),
    )

    assert growspace.irrigation_config is not prior_config
    assert growspace.irrigation_strategy is not prior_strategy
    assert growspace.irrigation_config.irrigation_duration == 45
    assert growspace.irrigation_strategy.target_vwc_percent == 58.0
    assert result.operation is IrrigationChangeOperation.OPTIONS
    assert result.changed_config_fields == frozenset({"irrigation_duration"})
    assert result.changed_strategy_fields == frozenset({"target_vwc_percent"})
    with pytest.raises(FrozenInstanceError):
        result.operation = IrrigationChangeOperation.SETTINGS  # type: ignore[misc]
    coordinator.cache.invalidate.assert_called_once_with("tent")
    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_normalizes_compatibility_fields_to_canonical_state() -> None:
    """Pump clears, form aliases, and partial profiles keep public behavior."""
    growspace = Growspace(id="tent", name="Tent")
    growspace.irrigation_config.irrigation_pump_entity = "switch.pump"
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL,
        liters_per_pot=4.0,
    )
    coordinator = _coordinator(growspace)

    result = await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.OPTIONS,
            values={
                "irrigation_pump_entity": "",
                "use_vwc_steering": True,
                "shot_duration_seconds": 12,
                "substrate_liters_per_pot": 6.0,
            },
        ),
    )

    assert growspace.irrigation_config.irrigation_pump_entity is None
    assert growspace.irrigation_strategy.enabled is True
    assert growspace.irrigation_strategy.p1_shot_duration_seconds == 12
    assert growspace.irrigation_strategy.p2_shot_duration_seconds == 12
    assert growspace.irrigation_strategy.substrate_profile == SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL,
        liters_per_pot=6.0,
    )
    assert result.changed_config_fields == frozenset({"irrigation_pump_entity"})
    assert result.changed_strategy_fields == frozenset(
        {
            "enabled",
            "p1_shot_duration_seconds",
            "p2_shot_duration_seconds",
            "substrate_profile",
        }
    )


@pytest.mark.asyncio
async def test_change_accepts_a_typed_substrate_profile() -> None:
    """Callers may supply the canonical model value without re-encoding it."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)
    profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO,
        liters_per_pot=8.0,
    )

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.OPTIONS,
            values={"substrate_profile": profile},
        ),
    )

    assert growspace.irrigation_strategy.substrate_profile == profile


@pytest.mark.asyncio
async def test_change_merges_a_partial_substrate_profile_mapping() -> None:
    """A nested partial profile retains the stored value for its missing half."""
    growspace = Growspace(id="tent", name="Tent")
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL,
        liters_per_pot=4.0,
    )
    coordinator = _coordinator(growspace)

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.OPTIONS,
            values={"substrate_profile": {"liters_per_pot": 6.0}},
        ),
    )

    assert growspace.irrigation_strategy.substrate_profile == SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL,
        liters_per_pot=6.0,
    )


@pytest.mark.asyncio
async def test_change_rejects_a_non_mapping_substrate_profile() -> None:
    """Malformed profile input fails before state or persistence is touched."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match="must be a mapping"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.OPTIONS,
                values={"substrate_profile": "rockwool"},
            ),
        )

    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_validates_volume_mode_against_effective_state() -> None:
    """A settings-only change cannot remove a prerequisite from active Volume Mode."""
    growspace = Growspace(id="tent", name="Tent")
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 20.0
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        liters_per_pot=4.0
    )
    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match="Volume Mode requires"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.SETTINGS,
                values={"pump_flow_rate_ml_per_sec": 0.0},
            ),
        )

    assert growspace.irrigation_config is prior_config
    assert growspace.irrigation_strategy is prior_strategy
    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_accepts_volume_mode_prerequisites_in_the_same_change() -> None:
    """The effective-state candidate includes config and strategy values together."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.OPTIONS,
            values={
                "shot_sizing_mode": "volume",
                "pump_flow_rate_ml_per_sec": 12.0,
                "substrate_media_type": "rockwool",
                "substrate_liters_per_pot": 6.0,
            },
        ),
    )

    assert growspace.irrigation_strategy.shot_sizing_mode is ShotSizingMode.VOLUME
    assert growspace.irrigation_config.pump_flow_rate_ml_per_sec == 12.0
    assert growspace.irrigation_strategy.substrate_profile == SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL,
        liters_per_pot=6.0,
    )


@pytest.mark.asyncio
async def test_change_validates_partial_pore_ec_band_against_effective_state() -> None:
    """One supplied band edge is ordered against the retained opposite edge."""
    growspace = Growspace(id="tent", name="Tent")
    growspace.irrigation_strategy.pore_ec_target_min = 2.0
    growspace.irrigation_strategy.pore_ec_target_max = 4.0
    prior_strategy = growspace.irrigation_strategy
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match=r"min \(5.0\).*max \(4.0\)"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.STRATEGY,
                values={"pore_ec_target_min": 5.0},
            ),
        )

    assert growspace.irrigation_strategy is prior_strategy
    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_restores_prior_state_when_persistence_fails() -> None:
    """The candidate is never left live when the persistence effect rejects it."""
    growspace = Growspace(id="tent", name="Tent")
    prior_config = growspace.irrigation_config
    prior_strategy = growspace.irrigation_strategy
    coordinator = _coordinator(growspace)
    coordinator.async_commit.side_effect = OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.OPTIONS,
                values={
                    "irrigation_duration": 90,
                    "target_vwc_percent": 61.0,
                },
            ),
        )

    assert growspace.irrigation_config is prior_config
    assert growspace.irrigation_strategy is prior_strategy
    assert growspace.irrigation_config.irrigation_duration is None
    assert growspace.irrigation_strategy.target_vwc_percent == 55.0
    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_not_awaited()


# --- Dripper Throughput (ADR-0045) -----------------------------------------


@pytest.mark.asyncio
async def test_dripper_throughput_stores_only_the_derived_flow_rate() -> None:
    """L/h × emitters is an input spelling of ml/s; neither input is stored."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.SETTINGS,
            values={"dripper_liters_per_hour": 2.0, "emitter_count": 9},
        ),
    )

    # 2 L/h × 9 emitters = 18 L/h = 18000 ml / 3600 s = 5 ml/s.
    assert growspace.irrigation_config.pump_flow_rate_ml_per_sec == pytest.approx(5.0)
    stored = growspace.irrigation_config.to_dict()
    assert "dripper_liters_per_hour" not in stored
    assert "emitter_count" not in stored


@pytest.mark.asyncio
async def test_dripper_throughput_needs_both_halves() -> None:
    """One number alone does not name a flow rate, so it is refused."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match="emitter_count"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.SETTINGS,
                values={"dripper_liters_per_hour": 2.0},
            ),
        )

    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dripper_throughput_and_a_direct_flow_rate_conflict() -> None:
    """One stored value, so two answers for it are refused rather than ranked."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match="not both"):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.SETTINGS,
                values={
                    "pump_flow_rate_ml_per_sec": 12.0,
                    "dripper_liters_per_hour": 2.0,
                    "emitter_count": 9,
                },
            ),
        )

    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["p1", "p2", "p3"])
async def test_steering_phase_change_writes_the_phase(phase: str) -> None:
    """The steering-phase operation writes the one field it owns."""
    growspace = Growspace(id="tent", name="Tent")
    growspace.irrigation_config.active_steering_phase = "p1"
    coordinator = _coordinator(growspace)

    result = await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.STEERING_PHASE,
            values={"active_steering_phase": phase},
        ),
    )

    assert growspace.irrigation_config.active_steering_phase == phase
    # Re-selecting the phase already showing is not a change, exactly as it is
    # not for any other field the seam writes.
    expected_changed = {
        "p1": frozenset(),
        "p2": frozenset({"active_steering_phase"}),
        "p3": frozenset({"active_steering_phase", "phase_changed_at"}),
    }[phase]
    assert result.changed_config_fields == expected_changed
    assert result.changed_strategy_fields == frozenset()
    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_steering_phase_change_stamps_the_timestamp_only_for_p3() -> None:
    """The dryback readout's clock starts on entry to P3, as it does on a tick."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.STEERING_PHASE,
            values={"active_steering_phase": "p1"},
        ),
    )
    assert growspace.irrigation_config.phase_changed_at is None

    await async_apply_irrigation_change(
        coordinator,
        "tent",
        IrrigationChange(
            operation=IrrigationChangeOperation.STEERING_PHASE,
            values={"active_steering_phase": "p3"},
        ),
    )
    assert growspace.irrigation_config.phase_changed_at is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["irrigation_duration", "phase_changed_at"])
async def test_steering_phase_change_writes_nothing_else(field: str) -> None:
    """The phase operation is the phase alone: no settings ride along with it."""
    growspace = Growspace(id="tent", name="Tent")
    coordinator = _coordinator(growspace)

    with pytest.raises(IrrigationChangeError, match=field):
        await async_apply_irrigation_change(
            coordinator,
            "tent",
            IrrigationChange(
                operation=IrrigationChangeOperation.STEERING_PHASE,
                values={"active_steering_phase": "p2", field: 45},
            ),
        )

    coordinator.async_commit.assert_not_awaited()
