"""Repairs the grower can apply: the Calibration Proposal (ADR-0064 item 7).

A corrected pump flow rate is only ever proposed. The irrigation coordinator
files one Repairs issue per zone while a proposal stands, and withdraws it when
none does. **Apply** is this module's fix flow, which writes the rate through
[[Irrigation Change]] and so closes the issue; nothing here ever applies a rate
on its own.

**Ignore** is Home Assistant's own dismissal. It survives every refresh of the
issue, because refreshing never deletes it, and it ends when the issue is
withdrawn: once the Tank–Pump Disagreement clears, the issue is deleted, Home
Assistant forgets the dismissal, and a later disagreement files it afresh.

A ratio that looks like a unit mix-up is filed under the same issue as a
non-fixable one, with no Apply, naming the entity whose unit to check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir

from .const import ATTR_GROWSPACE_ID, DOMAIN
from .domain.calibration_proposal import CalibrationProposal
from .service_coordinator_locator import ServiceCoordinatorLocator
from .services.irrigation_change import (
    IrrigationChange,
    IrrigationChangeOperation,
    async_apply_irrigation_change,
)

if TYPE_CHECKING:
    from .models import Growspace

CALIBRATION_PROPOSAL_PREFIX = "calibration_proposal_"


def calibration_proposal_issue_id(growspace_id: str) -> str:
    """Return the growspace's Calibration Proposal issue: one zone, one issue."""
    return f"{CALIBRATION_PROPOSAL_PREFIX}{growspace_id}"


@callback
def async_file_calibration_proposal(
    hass: HomeAssistant, growspace: Growspace, proposal: CalibrationProposal | None
) -> None:
    """File the proposal as a Repairs issue, or withdraw it when there is none."""
    issue_id = calibration_proposal_issue_id(growspace.id)
    if proposal is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    placeholders = {
        "growspace": growspace.name,
        "configured": f"{proposal.configured_ml_per_sec:g}",
        "proposed": f"{proposal.proposed_ml_per_sec:g}",
        "evidence_count": str(proposal.evidence_count),
        "median_ratio": f"{proposal.median_ratio:.2f}",
        "entity": ", ".join(proposal.entities),
    }
    if (mix_up := proposal.mix_up) is not None:
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="calibration_unit_suspect",
            translation_placeholders={
                **placeholders,
                "factor": f"{mix_up.factor:g}",
                "units": mix_up.units,
            },
        )
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="calibration_proposal",
        translation_placeholders=placeholders,
        data={
            ATTR_GROWSPACE_ID: growspace.id,
            "configured_ml_per_sec": proposal.configured_ml_per_sec,
            "proposed_ml_per_sec": proposal.proposed_ml_per_sec,
        },
    )


class CalibrationProposalRepairFlow(RepairsFlow):
    """Apply the proposed flow rate, exactly as it was shown, or nothing."""

    def __init__(self, growspace_id: str, configured: float, proposed: float) -> None:
        """Hold the proposal the grower is looking at."""
        self._growspace_id = growspace_id
        self._configured = configured
        self._proposed = proposed

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Show the proposal."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Write the proposed rate through Irrigation Change once confirmed.

        A rate changed since the proposal was made means the proposal no longer
        describes the growspace, so it is refused rather than applied on top.
        The coordinator withdraws it on its next tick.
        """
        if user_input is None:
            issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
            return self.async_show_form(
                step_id="confirm",
                data_schema=vol.Schema({}),
                description_placeholders=(
                    issue.translation_placeholders if issue is not None else None
                ),
            )
        try:
            coordinator = ServiceCoordinatorLocator.get_for_service_call(
                self.hass, {ATTR_GROWSPACE_ID: self._growspace_id}
            )
        except ServiceValidationError:
            coordinator = None
        growspace = (
            coordinator.growspaces.get(self._growspace_id)
            if coordinator is not None
            else None
        )
        if coordinator is None or growspace is None:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)
            return self.async_abort(reason="growspace_missing")
        if growspace.default_zone.pump_flow_rate_ml_per_sec != self._configured:
            return self.async_abort(reason="proposal_stale")
        await async_apply_irrigation_change(
            coordinator,
            self._growspace_id,
            IrrigationChange(
                operation=IrrigationChangeOperation.CALIBRATION,
                values={"pump_flow_rate_ml_per_sec": self._proposed},
            ),
        )
        return self.async_create_entry(data={})


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the fix flow for a fixable issue this integration filed."""
    if issue_id.startswith(CALIBRATION_PROPOSAL_PREFIX) and data is not None:
        return CalibrationProposalRepairFlow(
            growspace_id=str(data[ATTR_GROWSPACE_ID]),
            configured=float(data["configured_ml_per_sec"] or 0.0),
            proposed=float(data["proposed_ml_per_sec"] or 0.0),
        )
    raise ValueError(f"Growspace Manager has no fix for issue {issue_id}")
