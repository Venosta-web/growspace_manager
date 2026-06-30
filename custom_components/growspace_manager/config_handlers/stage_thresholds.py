"""Shared round-trip for Stage Hysteresis Thresholds.

A Stage Hysteresis Threshold table is the per-stage, day/night, on/off VPD
band that drives a humidifier or dehumidifier: ``{stage: {cycle: {on, off}}}``.
Both halves of a configure-humidifier / configure-dehumidifier step go through
this module so the form-field encoding (``{stage}_{cycle}_on`` / ``_off``) is
defined exactly once — the schema-build (the form a step shows) and the parse
(the submission a step reads) can never drift apart, even though they live in
different handlers.

Parameterised only by the appliance's default-thresholds table; the calling
handler owns which config key the parsed table lands under (``humidifier_thresholds``
vs ``dehumidifier_thresholds``). The on/off semantics differ by appliance
(humidifier on > off, dehumidifier on < off) but that lives entirely in the
defaults data — the structure here is appliance-agnostic.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_DAY,
    CONF_NIGHT,
    CONF_OFF,
    CONF_ON,
    DEHUMIDIFIER_STAGES,
)
from homeassistant.helpers import selector

_CYCLES = (CONF_DAY, CONF_NIGHT)
_EDGES = (CONF_ON, CONF_OFF)

# The VPD threshold input shared by every stage/cycle/edge field.
_VPD_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0.1,
        max=3.0,
        step=0.01,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="kPa",
    )
)

# The thresholds nested table: stage -> cycle -> edge -> kPa.
StageThresholds = dict[str, dict[str, dict[str, float]]]


def _field_name(stage: str, cycle: str, edge: str) -> str:
    """Return the flat form-field name for one threshold cell.

    The single source of truth for the encoding shared by the schema and the
    parse; changing it changes both halves at once.
    """
    return f"{stage}_{cycle}_{edge}"


def parse_stage_thresholds(user_input: dict[str, Any]) -> StageThresholds:
    """Fold the flat ``{stage}_{cycle}_on/off`` form fields into the nested table."""
    thresholds: StageThresholds = {}
    for stage in DEHUMIDIFIER_STAGES:
        thresholds[stage] = {}
        for cycle in _CYCLES:
            thresholds[stage][cycle] = {
                edge: user_input[_field_name(stage, cycle, edge)] for edge in _EDGES
            }
    return thresholds


def build_stage_threshold_schema(
    current_thresholds: dict[str, Any], defaults: dict[Any, Any]
) -> vol.Schema:
    """Build the per-stage day/night on/off schema, seeded from current or defaults."""
    schema_dict: dict[Any, Any] = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in _CYCLES:
            cell = current_thresholds.get(stage, {}).get(cycle, defaults[stage][cycle])
            for edge in _EDGES:
                schema_dict[
                    vol.Required(_field_name(stage, cycle, edge), default=cell[edge])
                ] = _VPD_SELECTOR
    return vol.Schema(schema_dict)
