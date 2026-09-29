"""The tank-sourced Calibration Proposal on a running coordinator (ADR-0064, #890).

Each case raises a Tank–Pump Disagreement the way it is raised in production:
the pump's Delivery Attempts go into the growspace's store, the tank's
consumption events onto the tank, and the irrigation coordinator's minute tick
judges each day after midnight. The Repairs issue is Home Assistant's own, and
**Apply** runs through Home Assistant's Repairs flow manager.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import (
    CATEGORY_CALIBRATION,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.delivery_attempt_store import (
    DeliveryAttemptStore,
)
from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationTank,
)
from custom_components.growspace_manager.repairs import (
    CalibrationProposalRepairFlow,
    async_create_fix_flow,
)
from homeassistant.components.repairs import DOMAIN as REPAIRS_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

GROWSPACE_ID = "gs1"
PUMP = "switch.pump"
TANK = "sensor.reservoir"
ISSUE_ID = f"calibration_proposal_{GROWSPACE_ID}"
RATE = 10.0


def _at(day: int, clock: str = "00:00:30") -> datetime:
    """Return a moment on a day of September 2026, in the tests' UTC."""
    return datetime.fromisoformat(f"2026-09-{day:02d}T{clock}+00:00")


def _growspace() -> Growspace:
    return Growspace(
        id=GROWSPACE_ID,
        name="Tent",
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity=PUMP,
            irrigation_duration=60,
            pump_flow_rate_ml_per_sec=RATE,
        ),
        environment_config=EnvironmentConfig(
            irrigation_tanks=[
                IrrigationTank(
                    sensor_entity=TANK,
                    name="Reservoir",
                    volume_liters=100.0,
                    stale_after_minutes=0,
                )
            ]
        ),
    )


@pytest.fixture
async def main(hass: HomeAssistant, enable_custom_integrations: None) -> MagicMock:
    """The growspace coordinator, loaded under a config entry the flow can find.

    Custom integrations are enabled, and the domain counted as set up, so Home
    Assistant finds this integration's Repairs platform rather than falling
    back to its own flow that only confirms.
    """
    await async_setup_component(hass, REPAIRS_DOMAIN, {})
    hass.config.components.add(DOMAIN)
    hass.states.async_set(TANK, "60")
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.growspaces = {GROWSPACE_ID: _growspace()}
    coordinator.async_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    entry = MockConfigEntry(domain=DOMAIN, state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    coordinator.deliveries = DeliveryAttemptStore(hass, entry.entry_id)
    return coordinator


@pytest.fixture
async def irrigation(hass: HomeAssistant, main: MagicMock) -> IrrigationCoordinator:
    """The growspace's irrigation coordinator, started on a fresh store."""
    entry = MagicMock()
    entry.entry_id = "entry1"
    coordinator = IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)
    await coordinator._async_load_deliveries()
    return coordinator


@pytest.fixture
def logbook(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Collect every growspace logbook line."""
    lines: list[dict[str, Any]] = []

    @callback
    def collect(event: Event) -> None:
        lines.append(dict(event.data))

    hass.bus.async_listen(EVENT_GROWSPACE_LOG_ENTRY, collect)
    return lines


def _water_day(
    coordinator: IrrigationCoordinator, day: int, *, tank_l: float, pump_l: float
) -> None:
    """Record one day: a shot delivering ``pump_l`` and the tank dropping ``tank_l``."""
    on = _at(day, "08:00:00")
    rate = coordinator.growspace.irrigation_config.pump_flow_rate_ml_per_sec
    coordinator._deliveries.attempts.append(
        DeliveryAttempt.requested(
            attempt_id=f"shot-{day}",
            growspace_id=GROWSPACE_ID,
            output=PUMP,
            trigger=AttemptTrigger.SCHEDULE,
            planned_s=pump_l * 1000 / rate,
            flow_rate_ml_per_sec=rate,
            requested_at=on,
        )
        .commanded(on)
        .confirmed_on(on, on.date())
        .closed(off_commanded_at=on + timedelta(seconds=pump_l * 1000 / rate))
    )
    coordinator.growspace.environment_config.irrigation_tanks[
        0
    ].water_history.events.append(
        {
            "timestamp": _at(day, "08:30:00").isoformat(),
            "event_type": "consumption",
            "pct_delta": -tank_l,
            "liters": tank_l,
        }
    )


async def _tick(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    coordinator: IrrigationCoordinator,
    at: datetime,
) -> None:
    freezer.move_to(at)
    coordinator._watch_calibration()
    await hass.async_block_till_done()


async def _raise(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    coordinator: IrrigationCoordinator,
    *,
    tank_l: float = 12.0,
    pump_l: float = 8.0,
    first: int = 25,
) -> None:
    """Watch from the day before ``first``, then disagree on it and the next day."""
    await _tick(hass, freezer, coordinator, _at(first - 1, "10:00:00"))
    for day in (first, first + 1):
        _water_day(coordinator, day, tank_l=tank_l, pump_l=pump_l)
    await _tick(hass, freezer, coordinator, _at(first + 2))


def _issue(hass: HomeAssistant) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)


async def _start_fix(hass: HomeAssistant) -> dict[str, Any]:
    manager = hass.data[REPAIRS_DOMAIN]["flow_manager"]
    return await manager.async_init(DOMAIN, data={"issue_id": ISSUE_ID})


async def _submit(hass: HomeAssistant, flow_id: str) -> dict[str, Any]:
    manager = hass.data[REPAIRS_DOMAIN]["flow_manager"]
    return await manager.async_configure(flow_id, {})


# ── Filing it ──────────────────────────────────────────────────────────────


async def test_a_raised_disagreement_files_one_fixable_proposal(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """Configured, proposed, evidence count and median ratio, and the tank."""
    await _tick(hass, freezer, irrigation, _at(24, "10:00:00"))
    _water_day(irrigation, 25, tank_l=12.0, pump_l=8.0)
    await _tick(hass, freezer, irrigation, _at(26))
    assert _issue(hass) is None

    _water_day(irrigation, 26, tank_l=12.0, pump_l=8.0)
    await _tick(hass, freezer, irrigation, _at(27))

    issue = _issue(hass)
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "calibration_proposal"
    assert issue.translation_placeholders == {
        "growspace": "Tent",
        "configured": "10",
        "proposed": "15",
        "evidence_count": "2",
        "median_ratio": "1.50",
        "entity": TANK,
    }
    assert issue.data == {
        "growspace_id": GROWSPACE_ID,
        "configured_ml_per_sec": RATE,
        "proposed_ml_per_sec": 15.0,
    }


async def test_nothing_is_ever_applied_without_the_grower(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """Days of a standing proposal leave the configured rate alone."""
    await _raise(hass, freezer, irrigation)
    for day in (27, 28, 29):
        _water_day(irrigation, day, tank_l=12.0, pump_l=8.0)
        await _tick(hass, freezer, irrigation, _at(day + 1))

    assert irrigation.growspace.irrigation_config.pump_flow_rate_ml_per_sec == RATE
    issue = _issue(hass)
    assert issue is not None
    assert issue.translation_placeholders["evidence_count"] == "5"


async def test_a_ratio_like_a_unit_mix_up_offers_no_apply(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """Gallons read as litres: the issue names the tank instead of a rate."""
    await _raise(hass, freezer, irrigation, tank_l=30.28, pump_l=8.0)

    issue = _issue(hass)
    assert issue is not None
    assert not issue.is_fixable
    assert issue.translation_key == "calibration_unit_suspect"
    assert issue.data is None
    assert issue.translation_placeholders["entity"] == TANK
    assert issue.translation_placeholders["factor"] == "3.785"
    assert issue.translation_placeholders["units"] == "gallons and litres"
    assert issue.translation_placeholders["median_ratio"] == "3.79"


# ── Apply ──────────────────────────────────────────────────────────────────


async def test_apply_writes_the_rate_and_closes_the_issue_for_good(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
    main: MagicMock,
    logbook: list[dict[str, Any]],
) -> None:
    """Through Irrigation Change, and the evidence at the old rate is set aside."""
    await _raise(hass, freezer, irrigation)

    shown = await _start_fix(hass)
    assert shown["type"] is FlowResultType.FORM
    assert shown["step_id"] == "confirm"
    assert shown["description_placeholders"]["proposed"] == "15"

    done = await _submit(hass, shown["flow_id"])

    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert irrigation.growspace.irrigation_config.pump_flow_rate_ml_per_sec == 15.0
    main.async_commit.assert_awaited()
    assert _issue(hass) is None
    assert logbook[-1]["message"] == (
        "Applied a Calibration Proposal: pump flow rate 10 → 15 ml/s"
    )

    # The next tick starts the comparison again at the new rate, rather than
    # proposing a second correction from days judged at the old one.
    await _tick(hass, freezer, irrigation, _at(27, "00:01:30"))
    assert _issue(hass) is None
    view = irrigation.calibration_payload()["tank_pump_disagreement"]
    assert view["state"] == "clear"
    assert view["days"] == []
    assert logbook[-1]["category"] == CATEGORY_CALIBRATION
    assert "flow rate changed" in logbook[-1]["message"]


async def test_a_rate_changed_since_the_proposal_is_not_applied(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """The grower changed it by hand: the stale proposal is refused, then withdrawn."""
    await _raise(hass, freezer, irrigation)
    shown = await _start_fix(hass)
    irrigation.growspace.irrigation_config.pump_flow_rate_ml_per_sec = 12.0

    done = await _submit(hass, shown["flow_id"])

    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "proposal_stale"
    assert irrigation.growspace.irrigation_config.pump_flow_rate_ml_per_sec == 12.0
    assert _issue(hass) is not None

    await _tick(hass, freezer, irrigation, _at(27, "00:01:30"))
    assert _issue(hass) is None


async def test_a_proposal_for_a_growspace_that_is_gone_is_withdrawn(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
    main: MagicMock,
) -> None:
    """Nothing is left to correct, so nothing is left to propose."""
    await _raise(hass, freezer, irrigation)
    shown = await _start_fix(hass)
    main.growspaces.clear()

    done = await _submit(hass, shown["flow_id"])

    assert done["type"] is FlowResultType.ABORT
    assert done["reason"] == "growspace_missing"
    assert _issue(hass) is None


async def test_a_proposal_with_no_integration_loaded_is_withdrawn(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """Without a loaded entry there is no growspace to write to."""
    await _raise(hass, freezer, irrigation)
    shown = await _start_fix(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)

    done = await _submit(hass, shown["flow_id"])

    assert done["reason"] == "growspace_missing"


# ── Ignore ─────────────────────────────────────────────────────────────────


async def test_ignore_holds_until_the_disagreement_clears_then_files_afresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    irrigation: IrrigationCoordinator,
) -> None:
    """The dismissal outlives refreshes, and is forgotten once it clears."""
    await _raise(hass, freezer, irrigation, first=15)
    ir.async_ignore_issue(hass, DOMAIN, ISSUE_ID, True)

    _water_day(irrigation, 17, tank_l=12.0, pump_l=8.0)
    await _tick(hass, freezer, irrigation, _at(18))
    issue = _issue(hass)
    assert issue is not None
    assert issue.dismissed_version is not None
    assert issue.translation_placeholders["evidence_count"] == "3"

    for day in (18, 19):
        _water_day(irrigation, day, tank_l=8.0, pump_l=8.0)
    await _tick(hass, freezer, irrigation, _at(20))
    assert irrigation.calibration_payload()["tank_pump_disagreement"]["state"] == (
        "clear"
    )
    assert _issue(hass) is None

    for day in (20, 21):
        _water_day(irrigation, day, tank_l=12.0, pump_l=8.0)
    await _tick(hass, freezer, irrigation, _at(22))

    refiled = _issue(hass)
    assert refiled is not None
    assert refiled.dismissed_version is None
    assert refiled.is_fixable


# ── The platform ───────────────────────────────────────────────────────────


async def test_the_fix_flow_is_only_for_a_proposal(hass: HomeAssistant) -> None:
    """Any other issue of this integration is not fixable, and asks for no flow."""
    flow = await async_create_fix_flow(
        hass,
        ISSUE_ID,
        {
            "growspace_id": GROWSPACE_ID,
            "configured_ml_per_sec": 10,
            "proposed_ml_per_sec": 15.0,
        },
    )
    assert isinstance(flow, CalibrationProposalRepairFlow)

    with pytest.raises(ValueError, match="irrigation_fault_gs1"):
        await async_create_fix_flow(hass, "irrigation_fault_gs1", None)


async def test_the_form_shows_without_an_issue_to_read(hass: HomeAssistant) -> None:
    """A flow whose issue went away meanwhile still renders, just unfilled."""
    flow = CalibrationProposalRepairFlow(GROWSPACE_ID, 10.0, 15.0)
    flow.hass = hass
    flow.handler = DOMAIN
    flow.issue_id = ISSUE_ID
    flow.flow_id = "flow"

    shown = await flow.async_step_init()

    assert shown["type"] is FlowResultType.FORM
    assert shown["description_placeholders"] is None
