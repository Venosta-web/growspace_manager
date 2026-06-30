"""Unit tests for the Stage Hysteresis Thresholds round-trip.

The whole point of the shared module is that the schema a step renders and the
parse a step reads share one field-name encoding. These tests pin that encoding
and, crucially, the round-trip: every field the schema declares is a field the
parse can read back, so the two halves can never silently drift.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.config_handlers.stage_thresholds import (
    build_stage_threshold_schema,
    parse_stage_thresholds,
)
from custom_components.growspace_manager.const import DEHUMIDIFIER_STAGES

# A defaults table shaped like the appliance coordinators' DEFAULT_THRESHOLDS,
# distinct values per stage/cycle/edge so a mis-wiring would show up.
_DEFAULTS: dict[str, dict[str, dict[str, float]]] = {
    stage: {
        "day": {"on": 1.0, "off": 0.8},
        "night": {"on": 0.9, "off": 0.7},
    }
    for stage in DEHUMIDIFIER_STAGES
}


def _schema_keys(schema: vol.Schema) -> set[str]:
    """Return the set of field names a built schema declares."""
    return {str(key.schema) for key in schema.schema}


def test_parse_folds_flat_fields_into_nested_table() -> None:
    """Flat {stage}_{cycle}_on/off fields fold into stage -> cycle -> edge."""
    stage = DEHUMIDIFIER_STAGES[0]
    user_input: dict[str, Any] = {
        f"{stage}_day_on": 1.1,
        f"{stage}_day_off": 0.9,
        f"{stage}_night_on": 1.0,
        f"{stage}_night_off": 0.8,
    }
    # Provide the remaining stages so the parse has every field it iterates.
    for other in DEHUMIDIFIER_STAGES[1:]:
        for cycle in ("day", "night"):
            user_input[f"{other}_{cycle}_on"] = 1.0
            user_input[f"{other}_{cycle}_off"] = 0.8

    result = parse_stage_thresholds(user_input)

    assert result[stage] == {
        "day": {"on": 1.1, "off": 0.9},
        "night": {"on": 1.0, "off": 0.8},
    }
    assert set(result) == set(DEHUMIDIFIER_STAGES)


def test_schema_seeds_from_current_then_defaults() -> None:
    """A current value wins; an absent one falls back to the defaults table."""
    stage = DEHUMIDIFIER_STAGES[0]
    current = {stage: {"day": {"on": 2.5, "off": 2.0}}}

    schema = build_stage_threshold_schema(current, _DEFAULTS)
    defaults_by_key = {str(key.schema): key.default() for key in schema.schema}

    assert defaults_by_key[f"{stage}_day_on"] == 2.5  # from current
    assert defaults_by_key[f"{stage}_day_off"] == 2.0  # from current
    assert defaults_by_key[f"{stage}_night_on"] == 0.9  # from defaults table
    assert defaults_by_key[f"{stage}_night_off"] == 0.7  # from defaults table


def test_schema_and_parse_share_one_encoding() -> None:
    """Every field the schema declares is one the parse reads back — no drift.

    This is the locality guarantee: build a schema, read its declared defaults
    as if submitted, and the parse must reconstruct exactly the defaults table.
    """
    schema = build_stage_threshold_schema({}, _DEFAULTS)
    submitted = {str(key.schema): key.default() for key in schema.schema}

    parsed = parse_stage_thresholds(submitted)

    assert parsed == _DEFAULTS
    # No schema field is left unconsumed by the parse and vice versa.
    expected_fields = {
        f"{stage}_{cycle}_{edge}"
        for stage in DEHUMIDIFIER_STAGES
        for cycle in ("day", "night")
        for edge in ("on", "off")
    }
    assert _schema_keys(schema) == expected_fields
